"""工具层基础框架与 tenant_id 强制注入（任务 7.1）。

本模块为统一工具层（Tool Layer）提供受控、可审计、租户隔离的数据访问基础设施。
所有数据访问工具都应经由此处封装的调用入口，以在数据库行级安全（RLS）之上再叠加
一层应用侧的纵深防御，确保：

1. **强制注入 tenant_id**：进入任何数据访问前，都先经 RLS 上下文注入当前租户
   （复用 :func:`app.db.session.set_tenant_context`），驱动 PostgreSQL RLS 策略
   （Requirements 5.1）。
2. **结果集租户校验**：返回前逐条校验记录的 ``tenant_id`` 是否等于上下文 ``tenant_id``，
   任一记录越界即阻断整个结果集并抛 :class:`~app.core.errors.TenantIsolationError`
   （Requirements 5.2、5.5、Correctness Property 1）。
3. **结果截断并打标**：结果集超过 :data:`MAX_RESULT_ROWS` 行时截断到上限并在
   :class:`ToolResult` 上标记 ``truncated=True``（Requirements 2.7）。
4. **上下文缺失拒绝**：``tenant_id`` 缺失或为空（None / 空串 / 纯空白 / 非字符串）时
   拒绝调用并抛 :class:`~app.core.errors.TenantContextMissingError`（Requirements 5.4）。

为便于独立测试，纯粹的执行逻辑（租户校验、截断、结果封装）与需要数据库连接的注入逻辑
被拆分开：前者是不依赖数据库的纯函数，可用假记录直接验证；后者通过 ``connection``
形参接收（可传入假连接），无需真实数据库即可覆盖。

设计约定：``@tool`` 封装的 LangChain 调用入口经 :func:`build_tenant_scoped_langchain_tool`
工厂生成，内部同样复用本模块的注入与校验逻辑。
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import wraps
from typing import Any, Callable, Iterable, Mapping, Optional, TypeVar

from app.core.errors import TenantContextMissingError, TenantIsolationError
from app.db.session import set_tenant_context

__all__ = [
    "MAX_RESULT_ROWS",
    "TENANT_ID_FIELD",
    "ToolResult",
    "require_tenant_context",
    "extract_tenant_id",
    "enforce_tenant_isolation",
    "truncate_rows",
    "build_tool_result",
    "tenant_scoped_tool",
    "run_tenant_scoped_query",
    "build_tenant_scoped_langchain_tool",
]

# 单次工具调用返回的最大行数；超出即截断并打标（Requirements 2.7）。
MAX_RESULT_ROWS = 1000

# 记录中承载租户标识的字段名。
TENANT_ID_FIELD = "tenant_id"

# 用于区分"字段缺失"与"字段值为 None"的哨兵对象。
_MISSING = object()

F = TypeVar("F", bound=Callable[..., Iterable[Any]])


@dataclass(frozen=True)
class ToolResult:
    """工具层数据访问的标准返回封装。

    Attributes:
        rows: 经租户校验并按上限截断后的记录列表。
        row_count: ``rows`` 的实际条数（截断后）。
        truncated: 原始结果是否因超过 :data:`MAX_RESULT_ROWS` 而被截断。
        tenant_id: 本次调用所绑定的（已归一化的）租户标识。
    """

    rows: list[Any]
    row_count: int
    truncated: bool
    tenant_id: str

    def as_dict(self) -> dict[str, Any]:
        """转为可被 LangChain / JSON 序列化的普通字典。"""
        return {
            "rows": self.rows,
            "row_count": self.row_count,
            "truncated": self.truncated,
            "tenant_id": self.tenant_id,
        }


def require_tenant_context(tenant_id: object) -> str:
    """校验并归一化租户上下文。

    仅接受非空且去除首尾空白后仍非空的字符串；否则视为租户上下文缺失。用于在打开
    数据库连接或调用数据源之前先行拒绝无效租户，避免占用任何数据访问资源
    （Requirements 5.4）。

    Args:
        tenant_id: 待校验的租户标识。

    Returns:
        原始字符串形式的 ``tenant_id``（保留其原值，不做 strip 改写以匹配 RLS 注入语义）。

    Raises:
        TenantContextMissingError: 当 ``tenant_id`` 为 None、非字符串、空串或纯空白时。
    """
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise TenantContextMissingError(
            "缺少有效的租户上下文：tenant_id 不可为空。"
        )
    return tenant_id


def extract_tenant_id(record: Any) -> Any:
    """从记录中提取 ``tenant_id``。

    兼容映射类型（如 dict、``RowMapping``）与具备 ``tenant_id`` 属性的对象
    （如 Pydantic 模型、ORM 行）。字段缺失时返回内部哨兵，使校验将其视为越界。

    Args:
        record: 单条结果记录。

    Returns:
        记录的 ``tenant_id`` 值；若记录不含该字段，返回内部哨兵对象。
    """
    if isinstance(record, Mapping):
        return record.get(TENANT_ID_FIELD, _MISSING)
    return getattr(record, TENANT_ID_FIELD, _MISSING)


def enforce_tenant_isolation(
    rows: Iterable[Any],
    tenant_id: str,
    *,
    allow_shared: bool = False,
) -> None:
    """逐条校验结果集的租户归属，发现越界立即阻断。

    只要任一记录的 ``tenant_id`` 不等于上下文 ``tenant_id`` 即抛错，从而阻断整个结果集
    的返回（Requirements 5.2、5.5、Correctness Property 1）。缺失 ``tenant_id`` 字段的
    记录无法证明归属，一律视为越界。

    Args:
        rows: 待校验的记录序列。
        tenant_id: 请求上下文的租户标识。
        allow_shared: 为 True 时额外放行 ``tenant_id`` 为 None 的平台级共享记录
            （供 RAG 等共享知识场景使用，任务 10）。默认 False，严格要求逐条相等。

    Raises:
        TenantIsolationError: 存在 ``tenant_id`` 与上下文不符（或缺失）的记录时。
    """
    for index, record in enumerate(rows):
        record_tenant = extract_tenant_id(record)
        if record_tenant == tenant_id:
            continue
        if allow_shared and record_tenant is None:
            continue
        found = "<缺失>" if record_tenant is _MISSING else repr(record_tenant)
        raise TenantIsolationError(
            "租户隔离违规：结果集第 "
            f"{index} 条记录的 tenant_id={found} 与请求上下文 "
            f"tenant_id={tenant_id!r} 不一致，已阻断整个结果集返回。"
        )


def truncate_rows(
    rows: list[Any], max_rows: int = MAX_RESULT_ROWS
) -> tuple[list[Any], bool]:
    """将结果集截断到上限并返回是否发生截断。

    Args:
        rows: 已物化的记录列表。
        max_rows: 允许返回的最大行数。

    Returns:
        ``(kept_rows, truncated)`` 元组：``kept_rows`` 至多含 ``max_rows`` 条；
        ``truncated`` 表示原始结果是否超过上限而被截断。
    """
    if len(rows) > max_rows:
        return rows[:max_rows], True
    return rows, False


def build_tool_result(
    rows: Iterable[Any],
    tenant_id: str,
    *,
    max_rows: int = MAX_RESULT_ROWS,
    allow_shared: bool = False,
) -> ToolResult:
    """将原始记录序列封装为经校验、截断后的 :class:`ToolResult`。

    执行顺序为"先安全后截断"：先对**完整**结果集做租户隔离校验（安全优先，避免越界
    记录被截断掩盖），再截断到上限并打标。

    Args:
        rows: 数据源返回的原始记录序列（可为生成器，将被物化）。
        tenant_id: 已归一化的请求租户标识。
        max_rows: 返回行数上限。
        allow_shared: 是否放行平台级共享（``tenant_id`` 为 None）记录。

    Returns:
        封装了行数据、行数与截断标记的 :class:`ToolResult`。

    Raises:
        TenantIsolationError: 结果集包含越界记录时。
    """
    materialized = list(rows)
    enforce_tenant_isolation(materialized, tenant_id, allow_shared=allow_shared)
    kept, truncated = truncate_rows(materialized, max_rows)
    return ToolResult(
        rows=kept,
        row_count=len(kept),
        truncated=truncated,
        tenant_id=tenant_id,
    )


def tenant_scoped_tool(
    func: Optional[F] = None,
    *,
    max_rows: int = MAX_RESULT_ROWS,
    allow_shared: bool = False,
) -> Callable[..., Any]:
    """将数据访问函数封装为强制租户注入 + 校验 + 截断的工具入口。

    被装饰函数的签名约定为 ``fn(connection, tenant_id, *args, **kwargs) -> Iterable``，
    即接收一个（已注入租户上下文的）数据库连接与归一化后的租户标识，返回记录序列。
    装饰后得到的可调用对象签名为 ``wrapper(connection, tenant_id, *args, **kwargs) -> ToolResult``，
    其行为：

    1. 经 :func:`set_tenant_context` 校验并向 ``connection`` 注入 ``tenant_id``
       （``tenant_id`` 缺失/空时在此抛 :class:`TenantContextMissingError`，且不执行查询）。
    2. 调用被装饰函数获取原始记录。
    3. 逐条校验租户归属（越界抛 :class:`TenantIsolationError`）。
    4. 超过 ``max_rows`` 时截断并打标。

    可作为无参装饰器 ``@tenant_scoped_tool`` 或带参装饰器
    ``@tenant_scoped_tool(max_rows=..., allow_shared=...)`` 使用。

    Args:
        func: 被装饰的数据访问函数（无参用法下自动传入）。
        max_rows: 返回行数上限。
        allow_shared: 是否放行平台级共享记录。

    Returns:
        装饰后的工具函数，或在带参用法下返回装饰器。
    """

    def decorator(fn: F) -> Callable[..., ToolResult]:
        @wraps(fn)
        def wrapper(connection: Any, tenant_id: str, *args: Any, **kwargs: Any) -> ToolResult:
            # set_tenant_context 先校验（缺失即抛错，不触碰连接），再注入 RLS 上下文。
            normalized = set_tenant_context(connection, tenant_id)
            raw = fn(connection, normalized, *args, **kwargs)
            return build_tool_result(
                raw, normalized, max_rows=max_rows, allow_shared=allow_shared
            )

        wrapper.__tenant_scoped__ = True  # type: ignore[attr-defined]
        return wrapper

    if func is not None:
        return decorator(func)
    return decorator


def run_tenant_scoped_query(
    engine: Any,
    tenant_id: str,
    query_fn: Callable[[Any], Iterable[Any]],
    *,
    max_rows: int = MAX_RESULT_ROWS,
    allow_shared: bool = False,
) -> ToolResult:
    """在自管理的租户会话内执行一次数据访问并返回受控结果。

    先在打开连接前校验租户上下文（缺失即拒绝，不占用连接资源），再经
    :func:`app.db.session.tenant_session` 打开一个已注入 ``app.current_tenant`` 的
    事务连接，交由 ``query_fn`` 执行查询，最后统一做租户校验与截断。

    Args:
        engine: SQLAlchemy Engine。
        tenant_id: 请求上下文租户标识。
        query_fn: 接收已注入租户上下文的连接、返回记录序列的查询回调。
        max_rows: 返回行数上限。
        allow_shared: 是否放行平台级共享记录。

    Returns:
        经校验与截断的 :class:`ToolResult`。

    Raises:
        TenantContextMissingError: ``tenant_id`` 缺失或为空。
        TenantIsolationError: 结果集包含越界记录。
    """
    # 延迟导入以避免在无需数据库的纯逻辑测试路径上引入连接依赖。
    from app.db.session import tenant_session

    normalized = require_tenant_context(tenant_id)
    with tenant_session(engine, normalized) as connection:
        raw = query_fn(connection)
        return build_tool_result(
            raw, normalized, max_rows=max_rows, allow_shared=allow_shared
        )


def build_tenant_scoped_langchain_tool(
    *,
    name: str,
    description: str,
    fetcher: Callable[..., Iterable[Any]],
    max_rows: int = MAX_RESULT_ROWS,
    allow_shared: bool = False,
) -> Any:
    """构建一个强制租户隔离的 LangChain ``@tool`` 数据访问调用入口。

    返回的工具遵循统一工具层契约：Agent 调用时必须传入 ``tenant_id``；工具在调用
    ``fetcher`` 前先校验租户上下文（缺失即拒绝），取得记录后统一做逐条租户校验与截断，
    并以普通字典形式返回（``rows`` / ``row_count`` / ``truncated`` / ``tenant_id``）。

    ``fetcher`` 的签名约定为 ``fetcher(tenant_id: str, query: str) -> Iterable``，负责
    实际的数据获取（如 Text2SQL 执行、规则查询等，在后续任务中接入真实数据源）。
    将数据获取以回调注入，使本入口的注入 / 校验 / 截断逻辑可用假 ``fetcher`` 独立测试，
    无需真实数据库。

    Args:
        name: 工具名称（供 Supervisor / Agent 路由与 LLM 函数调用识别）。
        description: 工具描述。
        fetcher: 实际数据获取回调。
        max_rows: 返回行数上限。
        allow_shared: 是否放行平台级共享记录。

    Returns:
        一个 LangChain ``StructuredTool``（由 ``@tool`` 等价机制构建）。
    """
    from langchain_core.tools import tool as langchain_tool

    @langchain_tool(name, description=description)
    def _entry(tenant_id: str, query: str = "") -> dict[str, Any]:
        normalized = require_tenant_context(tenant_id)
        raw = fetcher(normalized, query)
        result = build_tool_result(
            raw, normalized, max_rows=max_rows, allow_shared=allow_shared
        )
        return result.as_dict()

    return _entry
