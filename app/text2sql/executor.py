"""SQL 执行控制（任务 9.2，Requirements 2.2–2.7、20.2，Correctness Property 11）。

对应设计文档：
- Components / 组件 3「统一工具层」中的 ``db_query_tool``（Text2SQL）能力的**执行**子步骤；
- 二、核心业务流程时序图 2.1（``text2sql_tool`` → RLS 范围内查询 → 数据 + 洞察）；
- Error Handling 表「Text2SQL 生成非法/越权 SQL」一行的**执行 / 回退**环节。

本模块在 :mod:`app.text2sql.validator` 的三重校验之上实现执行控制，编排以下不变量：

1. **全部通过才执行**（Requirement 2.2）：先做 SQL 白名单 / 只读约束 / RLS 三重校验，
   三项全部通过才提交执行。
2. **失败即拒绝且无变更 + 澄清 + 回退**（Requirements 2.3、20.2）：任一校验失败则
   **不执行 SQL、不产生任何数据库变更**，返回指明失败原因的澄清提示，并回退到
   **受限模板查询**（复用 :class:`~app.llm.client.RestrictedTemplateQuery`；无匹配时
   返回请用户重述的提示）。
3. **30 秒超时终止且无变更**（Requirement 2.6）：执行耗时超过预算即终止，**不产生
   任何数据库变更**，返回查询超时错误。
4. **>1000 行截断并打标**（Requirement 2.7）：执行结果超过上限时截断并标记
   （复用 :func:`app.tools.base.build_tool_result`）。

RLS 与租户隔离复用统一工具层 / 会话层：真实执行经
:func:`app.tools.base.run_tenant_scoped_query` / :func:`app.db.session.tenant_session`
在注入了 ``app.current_tenant`` 的事务内进行，并对结果做逐条租户校验与截断。

可测试性：底层 SQL 执行经 :class:`SQLRunner` 协议注入，可传入**伪执行器**在无真实
数据库的情况下覆盖校验与执行控制逻辑（拒绝 / 回退 / 超时 / 截断）。真实的引擎绑定
执行器由 :func:`build_engine_runner` 提供（依赖数据库，不在单元测试路径中触发）。
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Protocol, runtime_checkable

from app.llm.client import RESTATE_PROMPT, RestrictedTemplateQuery
from app.text2sql.errors import SQLExecutionTimeoutError
from app.text2sql.validator import ValidationReport, validate_sql
from app.tools.base import MAX_RESULT_ROWS, ToolResult, build_tool_result

__all__ = [
    "EXECUTION_TIMEOUT_SECONDS",
    "SQLRunner",
    "ExecutionOutcome",
    "FallbackKind",
    "SafeSQLExecution",
    "SafeSQLExecutor",
    "build_engine_runner",
]

#: SQL 执行时间预算（秒），对应 Requirement 2.6「超过 30 秒终止」。
EXECUTION_TIMEOUT_SECONDS: float = 30.0


@runtime_checkable
class SQLRunner(Protocol):
    """底层 SQL 执行器协议（隔离真实数据库访问）。

    实现者负责在**当前租户的 RLS 上下文**内执行已通过三重校验的只读 SQL，返回原始
    记录序列；并在执行耗时超过 ``timeout_seconds`` 时终止执行且不产生任何数据库变更、
    抛出 :class:`~app.text2sql.errors.SQLExecutionTimeoutError`。
    """

    def __call__(
        self, tenant_id: str, sql: str, *, timeout_seconds: float
    ) -> Iterable[Any]:  # pragma: no cover - 协议声明
        ...


class ExecutionOutcome(str, Enum):
    """安全执行的最终结果类别。"""

    #: 三重校验通过并成功执行，返回（可能被截断的）结果集。
    EXECUTED = "executed"
    #: 三重校验失败被拒绝，未执行、无数据库变更，已回退受限模板查询。
    REJECTED = "rejected"
    #: 执行超过时间预算被终止，无数据库变更。
    TIMEOUT = "timeout"


class FallbackKind(str, Enum):
    """校验失败后受限模板查询的回退类别。"""

    #: 受限模板命中，返回模板固定应答。
    TEMPLATE = "template"
    #: 受限模板无匹配，返回请用户重述的提示。
    RESTATE = "restate"


@dataclass(frozen=True)
class SafeSQLExecution:
    """安全执行的统一返回封装。

    Attributes:
        outcome: 最终结果类别，见 :class:`ExecutionOutcome`。
        validation: 三重校验报告。
        executed: 是否真正对数据库发起了执行（拒绝 / 超时前拒绝时为 False）。
        result: 执行成功时的受控结果（含截断标记）；否则为 None。
        clarification: 拒绝 / 超时时指明原因的澄清 / 错误提示；成功时为 None。
        fallback_kind: 校验失败回退受限模板查询的类别；非拒绝场景为 None。
        fallback_text: 受限模板查询回退的应答文本；非拒绝场景为 None。
    """

    outcome: ExecutionOutcome
    validation: ValidationReport
    executed: bool
    result: ToolResult | None = None
    clarification: str | None = None
    fallback_kind: FallbackKind | None = None
    fallback_text: str | None = None


class SafeSQLExecutor:
    """Text2SQL 候选 SQL 的安全执行控制器（任务 9.2）。

    编排三重校验、执行、超时终止、结果截断与失败回退。所有外部依赖（底层执行器、
    受限模板查询、时间预算、行数上限）均可注入，便于无真实数据库测试。

    典型用法::

        executor = SafeSQLExecutor(runner=engine_runner, template_query=templates)
        outcome = executor.run(
            natural_language="哪些客户在流失？",
            sql=candidate_sql,
            tenant_id="store_88",
        )
        if outcome.outcome is ExecutionOutcome.EXECUTED:
            rows = outcome.result.rows
    """

    def __init__(
        self,
        runner: SQLRunner,
        *,
        template_query: RestrictedTemplateQuery | None = None,
        timeout_seconds: float = EXECUTION_TIMEOUT_SECONDS,
        max_rows: int = MAX_RESULT_ROWS,
    ) -> None:
        self._runner = runner
        self._templates = template_query or RestrictedTemplateQuery()
        self._timeout = timeout_seconds
        self._max_rows = max_rows

    def run(
        self,
        *,
        natural_language: str,
        sql: str,
        tenant_id: object,
    ) -> SafeSQLExecution:
        """对候选 SQL 执行三重校验并按结果控制执行 / 拒绝 / 回退 / 超时。

        Args:
            natural_language: 触发本次查询的原始自然语言问题（用于受限模板回退匹配）。
            sql: 上游（任务 9.1）生成的候选只读 SQL。
            tenant_id: 请求上下文租户标识。

        Returns:
            SafeSQLExecution: 统一封装的执行结果。
        """
        report = validate_sql(sql, tenant_id)

        # 三重校验任一失败：拒绝执行、无数据库变更、返回澄清并回退受限模板查询。
        if not report.ok:
            return self._reject(natural_language, report)

        # 全部通过：在租户 RLS 上下文内执行，受 30 秒预算约束。
        normalized_tenant = tenant_id  # 已由 RLS 校验确认为有效字符串。
        assert isinstance(normalized_tenant, str)
        try:
            raw_rows = self._runner(
                normalized_tenant, sql, timeout_seconds=self._timeout
            )
        except SQLExecutionTimeoutError as exc:
            # 超时终止：无数据库变更，返回查询超时错误。
            return SafeSQLExecution(
                outcome=ExecutionOutcome.TIMEOUT,
                validation=report,
                executed=True,
                clarification=(
                    f"查询执行超过 {self._timeout:.0f} 秒预算已被终止，未产生任何数据库变更：{exc}"
                ),
            )

        # 结果 >1000 行截断并打标；逐条租户校验复用统一工具层。
        result = build_tool_result(raw_rows, normalized_tenant, max_rows=self._max_rows)
        return SafeSQLExecution(
            outcome=ExecutionOutcome.EXECUTED,
            validation=report,
            executed=True,
            result=result,
        )

    def _reject(
        self, natural_language: str, report: ValidationReport
    ) -> SafeSQLExecution:
        """构造拒绝结果：澄清提示 + 回退受限模板查询（Requirements 2.3、20.2、20.5）。"""
        clarification = (
            f"生成的 SQL 未通过{_check_label(report.failed_check)}校验，已拒绝执行且未对"
            f"数据库产生任何变更。原因：{report.reason}"
        )
        matched = self._templates.match(natural_language)
        if matched is not None:
            fallback_kind = FallbackKind.TEMPLATE
            fallback_text = matched
        else:
            fallback_kind = FallbackKind.RESTATE
            fallback_text = RESTATE_PROMPT
        return SafeSQLExecution(
            outcome=ExecutionOutcome.REJECTED,
            validation=report,
            executed=False,
            clarification=clarification,
            fallback_kind=fallback_kind,
            fallback_text=fallback_text,
        )


def _check_label(check: str | None) -> str:
    """将校验类别代码映射为中文标签，用于澄清提示。"""
    return {
        "read_only": "只读约束",
        "whitelist": "SQL 白名单",
        "rls": "RLS",
    }.get(check or "", "安全")


def build_engine_runner(
    engine: Any,
    *,
    row_mapper: Callable[[Any], Any] | None = None,
) -> SQLRunner:
    """构建基于 SQLAlchemy Engine 的真实 :class:`SQLRunner`（依赖数据库）。

    在注入了 ``app.current_tenant`` 的事务内执行只读 SQL：先设置事务本地
    ``statement_timeout``（对应 30 秒预算），再执行 SQL 并物化结果行。数据库因语句
    超时取消查询时，将底层取消异常映射为
    :class:`~app.text2sql.errors.SQLExecutionTimeoutError`（事务随之回滚，无变更）。

    RLS 上下文注入与结果的逐条租户校验 / 截断由
    :func:`app.tools.base.run_tenant_scoped_query` 统一负责，此处仅在其查询回调内执行
    SQL 文本。

    Args:
        engine: SQLAlchemy Engine。
        row_mapper: 可选的行映射函数（如将 ``Row`` 转为 ``dict``）；默认原样返回。

    Returns:
        可注入 :class:`SafeSQLExecutor` 的执行器。

    注意：本函数依赖真实数据库连接，不在单元测试路径中触发；单元测试使用伪执行器。
    """
    from sqlalchemy import text

    from app.tools.base import run_tenant_scoped_query

    def _runner(tenant_id: str, sql: str, *, timeout_seconds: float) -> Iterable[Any]:
        timeout_ms = max(int(timeout_seconds * 1000), 1)

        def _query(connection: Any) -> list[Any]:
            try:
                # 事务本地语句超时：超过即由数据库终止查询（Requirement 2.6）。
                connection.execute(
                    text("SET LOCAL statement_timeout = :ms"), {"ms": timeout_ms}
                )
                rows = connection.execute(text(sql)).mappings().all()
            except Exception as exc:  # 将查询取消 / 超时映射为统一的超时错误。
                if _is_query_timeout(exc):
                    raise SQLExecutionTimeoutError(
                        f"查询执行超过 {timeout_seconds:.0f} 秒预算，已被数据库终止。"
                    ) from exc
                raise
            if row_mapper is not None:
                return [row_mapper(row) for row in rows]
            return list(rows)

        # run_tenant_scoped_query 已在会话内做租户校验与截断；此处放开底层上限，
        # 由 SafeSQLExecutor 统一按 MAX_RESULT_ROWS 截断打标。
        result = run_tenant_scoped_query(
            engine, tenant_id, _query, max_rows=_NO_TRUNCATE_LIMIT
        )
        return result.rows

    return _runner


#: 底层执行阶段不额外截断时使用的“无上限”行数（实际截断统一由 SafeSQLExecutor 完成）。
_NO_TRUNCATE_LIMIT = 2**62


def _is_query_timeout(exc: BaseException) -> bool:
    """判断异常是否为数据库查询超时 / 取消（跨驱动的宽松匹配）。"""
    name = type(exc).__name__.lower()
    if "timeout" in name or "querycanceled" in name or "cancelled" in name:
        return True
    message = str(exc).lower()
    return "statement timeout" in message or "canceling statement" in message
