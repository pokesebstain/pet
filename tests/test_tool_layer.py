"""任务 7.1 工具层基础框架与 tenant_id 强制注入的单元测试。

不依赖运行中的数据库：使用假连接与假记录，覆盖：
- 租户上下文校验（缺失/空拒绝）。
- 结果集逐条租户校验（越界阻断、缺失字段视为越界、共享记录放行）。
- 结果截断与打标（<=1000 不截断，>1000 截断）。
- ``tenant_scoped_tool`` 装饰器：注入 RLS 上下文、校验、截断、缺租户拒绝。
- ``run_tenant_scoped_query`` 经租户会话执行并受控返回。
- ``build_tenant_scoped_langchain_tool`` 生成的 @tool 入口的注入 / 校验 / 截断。
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.core.errors import TenantContextMissingError, TenantIsolationError
from app.db.metadata import SESSION_TENANT_VARIABLE
from app.tools import (
    MAX_RESULT_ROWS,
    ToolResult,
    build_tenant_scoped_langchain_tool,
    build_tool_result,
    enforce_tenant_isolation,
    extract_tenant_id,
    require_tenant_context,
    run_tenant_scoped_query,
    tenant_scoped_tool,
    truncate_rows,
)


# --- 假记录 / 假连接 -------------------------------------------------------

@dataclass
class _Record:
    """具备 tenant_id 属性的假记录（模拟 Pydantic / ORM 行）。"""

    tenant_id: str
    value: int = 0


def _rows(tenant_id: str, n: int) -> list[_Record]:
    return [_Record(tenant_id=tenant_id, value=i) for i in range(n)]


class _SpyConnection:
    """记录 execute 调用的假连接（用于验证 RLS 注入语句）。"""

    def __init__(self) -> None:
        self.executed: list[tuple[str, dict]] = []

    def execute(self, statement, parameters=None):
        self.executed.append((str(statement), dict(parameters or {})))
        return None


class _SpyTransaction:
    def __init__(self) -> None:
        self.committed = False
        self.rolled_back = False

    def __enter__(self) -> "_SpyTransaction":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is not None:
            self.rolled_back = True
        else:
            self.committed = True
        return False


class _SessionConnection(_SpyConnection):
    """兼容 tenant_session 上下文管理协议的假连接。"""

    def __init__(self) -> None:
        super().__init__()
        self.transaction: _SpyTransaction | None = None
        self.closed = False

    def begin(self) -> _SpyTransaction:
        self.transaction = _SpyTransaction()
        return self.transaction

    def __enter__(self) -> "_SessionConnection":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.closed = True
        return False


class _SpyEngine:
    def __init__(self) -> None:
        self.connection = _SessionConnection()
        self.connect_calls = 0

    def connect(self) -> _SessionConnection:
        self.connect_calls += 1
        return self.connection


# --- require_tenant_context ------------------------------------------------

def test_require_tenant_context_accepts_valid() -> None:
    assert require_tenant_context("tenant-a") == "tenant-a"


@pytest.mark.parametrize(
    "bad", [None, "", "   ", "\t\n", 123, object()],
    ids=["none", "empty", "spaces", "whitespace", "int", "object"],
)
def test_require_tenant_context_rejects_invalid(bad) -> None:
    with pytest.raises(TenantContextMissingError):
        require_tenant_context(bad)


# --- extract_tenant_id -----------------------------------------------------

def test_extract_tenant_id_from_mapping_and_object() -> None:
    assert extract_tenant_id({"tenant_id": "t1"}) == "t1"
    assert extract_tenant_id(_Record(tenant_id="t2")) == "t2"


def test_extract_tenant_id_missing_is_not_a_valid_tenant() -> None:
    # 缺失字段返回哨兵，不等于任何真实 tenant_id。
    sentinel = extract_tenant_id({"other": 1})
    assert sentinel != "t1"
    assert sentinel != None  # noqa: E711 - 明确区分缺失与 None


# --- enforce_tenant_isolation ----------------------------------------------

def test_enforce_isolation_passes_when_all_match() -> None:
    enforce_tenant_isolation(_rows("t1", 5), "t1")  # 不抛错


def test_enforce_isolation_blocks_on_foreign_record() -> None:
    rows = _rows("t1", 3) + [_Record(tenant_id="t2")]
    with pytest.raises(TenantIsolationError):
        enforce_tenant_isolation(rows, "t1")


def test_enforce_isolation_blocks_on_missing_tenant_field() -> None:
    with pytest.raises(TenantIsolationError):
        enforce_tenant_isolation([{"value": 1}], "t1")


def test_enforce_isolation_allow_shared_permits_none() -> None:
    rows = [{"tenant_id": "t1"}, {"tenant_id": None}]
    # 默认严格：None 越界
    with pytest.raises(TenantIsolationError):
        enforce_tenant_isolation(rows, "t1")
    # 放行共享：None 允许
    enforce_tenant_isolation(rows, "t1", allow_shared=True)


# --- truncate_rows ---------------------------------------------------------

def test_truncate_below_and_at_limit_keeps_all() -> None:
    kept, truncated = truncate_rows(list(range(MAX_RESULT_ROWS)))
    assert truncated is False
    assert len(kept) == MAX_RESULT_ROWS


def test_truncate_above_limit_flags_and_cuts() -> None:
    kept, truncated = truncate_rows(list(range(MAX_RESULT_ROWS + 5)))
    assert truncated is True
    assert len(kept) == MAX_RESULT_ROWS


# --- build_tool_result -----------------------------------------------------

def test_build_tool_result_truncates_and_flags() -> None:
    result = build_tool_result(_rows("t1", MAX_RESULT_ROWS + 10), "t1")
    assert isinstance(result, ToolResult)
    assert result.truncated is True
    assert result.row_count == MAX_RESULT_ROWS
    assert result.tenant_id == "t1"


def test_build_tool_result_enforces_before_truncation() -> None:
    # 越界记录位于 1000 行之后，仍必须被检出（先校验全集再截断）。
    rows = _rows("t1", MAX_RESULT_ROWS) + [_Record(tenant_id="t2")]
    with pytest.raises(TenantIsolationError):
        build_tool_result(rows, "t1")


def test_build_tool_result_no_truncation_when_within_limit() -> None:
    result = build_tool_result(_rows("t1", 3), "t1")
    assert result.truncated is False
    assert result.row_count == 3


# --- tenant_scoped_tool 装饰器 ---------------------------------------------

def test_tenant_scoped_tool_injects_context_and_returns_result() -> None:
    @tenant_scoped_tool
    def fetch(connection, tenant_id):
        return _rows(tenant_id, 2)

    conn = _SpyConnection()
    result = fetch(conn, "tenant-a")

    # 注入了 RLS 上下文（等价 SET LOCAL app.current_tenant）。
    assert len(conn.executed) == 1
    sql, params = conn.executed[0]
    assert "set_config" in sql.lower()
    assert params == {"var_name": SESSION_TENANT_VARIABLE, "tenant_id": "tenant-a"}
    assert result.row_count == 2
    assert result.truncated is False


def test_tenant_scoped_tool_rejects_missing_tenant_without_query() -> None:
    calls: list[str] = []

    @tenant_scoped_tool
    def fetch(connection, tenant_id):
        calls.append("called")
        return []

    conn = _SpyConnection()
    with pytest.raises(TenantContextMissingError):
        fetch(conn, "")
    # 缺租户时不注入、不调用底层数据访问。
    assert conn.executed == []
    assert calls == []


def test_tenant_scoped_tool_blocks_foreign_rows() -> None:
    @tenant_scoped_tool
    def fetch(connection, tenant_id):
        return _rows(tenant_id, 1) + [_Record(tenant_id="other")]

    with pytest.raises(TenantIsolationError):
        fetch(_SpyConnection(), "tenant-a")


def test_tenant_scoped_tool_with_params_truncates() -> None:
    @tenant_scoped_tool(max_rows=10)
    def fetch(connection, tenant_id):
        return _rows(tenant_id, 25)

    result = fetch(_SpyConnection(), "tenant-a")
    assert result.truncated is True
    assert result.row_count == 10


# --- run_tenant_scoped_query -----------------------------------------------

def test_run_tenant_scoped_query_uses_session_and_enforces() -> None:
    engine = _SpyEngine()

    result = run_tenant_scoped_query(
        engine, "tenant-a", lambda conn: _rows("tenant-a", 3)
    )
    assert result.row_count == 3
    assert engine.connect_calls == 1
    # 会话内注入了租户上下文并提交事务。
    assert engine.connection.executed[0][1]["tenant_id"] == "tenant-a"
    assert engine.connection.transaction is not None
    assert engine.connection.transaction.committed is True


def test_run_tenant_scoped_query_rejects_missing_tenant_before_connect() -> None:
    engine = _SpyEngine()
    with pytest.raises(TenantContextMissingError):
        run_tenant_scoped_query(engine, "", lambda conn: [])
    assert engine.connect_calls == 0


def test_run_tenant_scoped_query_blocks_foreign_rows() -> None:
    engine = _SpyEngine()
    with pytest.raises(TenantIsolationError):
        run_tenant_scoped_query(
            engine, "tenant-a", lambda conn: [_Record(tenant_id="evil")]
        )


# --- build_tenant_scoped_langchain_tool ------------------------------------

def test_langchain_tool_invokes_fetcher_and_returns_dict() -> None:
    def fetcher(tenant_id, query):
        return _rows(tenant_id, 2)

    entry = build_tenant_scoped_langchain_tool(
        name="db_query_tool",
        description="租户范围内数据查询",
        fetcher=fetcher,
    )
    assert entry.name == "db_query_tool"

    out = entry.invoke({"tenant_id": "tenant-a", "query": "q"})
    assert out["row_count"] == 2
    assert out["truncated"] is False
    assert out["tenant_id"] == "tenant-a"


def test_langchain_tool_rejects_missing_tenant() -> None:
    called: list[str] = []

    def fetcher(tenant_id, query):
        called.append("x")
        return []

    entry = build_tenant_scoped_langchain_tool(
        name="db_query_tool", description="d", fetcher=fetcher
    )
    with pytest.raises(TenantContextMissingError):
        entry.invoke({"tenant_id": "", "query": "q"})
    assert called == []


def test_langchain_tool_blocks_foreign_rows_and_truncates() -> None:
    entry_block = build_tenant_scoped_langchain_tool(
        name="t1",
        description="d",
        fetcher=lambda tid, q: [_Record(tenant_id="foreign")],
    )
    with pytest.raises(TenantIsolationError):
        entry_block.invoke({"tenant_id": "tenant-a", "query": ""})

    entry_trunc = build_tenant_scoped_langchain_tool(
        name="t2",
        description="d",
        fetcher=lambda tid, q: _rows(tid, 30),
        max_rows=10,
    )
    out = entry_trunc.invoke({"tenant_id": "tenant-a", "query": ""})
    assert out["truncated"] is True
    assert out["row_count"] == 10
