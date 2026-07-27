"""任务 2.2 RLS 会话上下文管理器的单元测试。

不依赖运行中的 PostgreSQL：使用间谍（spy）连接/引擎记录所发出的语句与参数，
验证：
- 进入 ``tenant_session`` 时在事务内注入 ``app.current_tenant``（等价 SET LOCAL）。
- 注入使用绑定参数传递 tenant_id（防注入），且作用域为事务本地。
- 退出时事务被提交（正常）或回滚（异常），从而自动清理会话变量。
- tenant_id 缺失或为空（None / 空串 / 纯空白 / 非字符串）时抛租户上下文缺失错误，
  且不建立任何连接（Requirements 5.4）。
"""

from __future__ import annotations

import pytest

from app.core.errors import TenantContextMissingError
from app.db import set_tenant_context, tenant_session
from app.db.metadata import SESSION_TENANT_VARIABLE


class _SpyTransaction:
    """记录 commit/rollback 的假事务，兼容上下文管理器协议。"""

    def __init__(self, connection: "_SpyConnection") -> None:
        self._conn = connection
        self.committed = False
        self.rolled_back = False

    def __enter__(self) -> "_SpyTransaction":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        # 模拟 SQLAlchemy 事务上下文：异常回滚，否则提交。
        if exc_type is not None:
            self.rolled_back = True
        else:
            self.committed = True
        return False  # 不吞异常


class _SpyConnection:
    """记录 execute 调用的假连接，兼容上下文管理器协议。"""

    def __init__(self) -> None:
        self.executed: list[tuple[str, dict]] = []
        self.transaction: _SpyTransaction | None = None
        self.closed = False

    def begin(self) -> _SpyTransaction:
        self.transaction = _SpyTransaction(self)
        return self.transaction

    def execute(self, statement, parameters=None):
        self.executed.append((str(statement), dict(parameters or {})))
        return None

    def __enter__(self) -> "_SpyConnection":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.closed = True
        return False


class _SpyEngine:
    """按需返回间谍连接的假引擎。"""

    def __init__(self) -> None:
        self.connection = _SpyConnection()
        self.connect_calls = 0

    def connect(self) -> _SpyConnection:
        self.connect_calls += 1
        return self.connection


# --- 正常路径：注入并清理 --------------------------------------------------

def test_tenant_session_sets_local_tenant_variable() -> None:
    """进入时应在事务内以绑定参数注入 app.current_tenant。"""
    engine = _SpyEngine()
    with tenant_session(engine, "tenant-a") as conn:
        assert conn is engine.connection

    # 恰好发出一条设置语句。
    assert len(engine.connection.executed) == 1
    sql, params = engine.connection.executed[0]
    # 使用参数化 set_config，等价于 SET LOCAL（事务本地作用域 true）。
    assert "set_config" in sql.lower()
    assert "true" in sql.lower()
    assert params == {
        "var_name": SESSION_TENANT_VARIABLE,
        "tenant_id": "tenant-a",
    }


def test_tenant_session_runs_within_transaction() -> None:
    """设置应在事务内进行，正常退出时提交（事务结束即清理 SET LOCAL）。"""
    engine = _SpyEngine()
    with tenant_session(engine, "tenant-a"):
        pass
    txn = engine.connection.transaction
    assert txn is not None
    assert txn.committed is True
    assert txn.rolled_back is False
    assert engine.connection.closed is True


def test_tenant_session_rolls_back_on_exception() -> None:
    """块内异常时事务回滚（同样触发 SET LOCAL 自动清理），并向外传播异常。"""
    engine = _SpyEngine()
    with pytest.raises(ValueError):
        with tenant_session(engine, "tenant-a"):
            raise ValueError("boom")
    txn = engine.connection.transaction
    assert txn is not None
    assert txn.rolled_back is True
    assert txn.committed is False
    assert engine.connection.closed is True


def test_set_tenant_context_injects_on_existing_connection() -> None:
    """set_tenant_context 应在既有连接上注入并返回归一化 tenant_id。"""
    conn = _SpyConnection()
    result = set_tenant_context(conn, "tenant-x")
    assert result == "tenant-x"
    assert len(conn.executed) == 1
    sql, params = conn.executed[0]
    assert "set_config" in sql.lower()
    assert params == {
        "var_name": SESSION_TENANT_VARIABLE,
        "tenant_id": "tenant-x",
    }


# --- 缺失/空租户上下文：拒绝且不连接 --------------------------------------

@pytest.mark.parametrize(
    "bad_tenant",
    [None, "", "   ", "\t\n", 123, object()],
    ids=["none", "empty", "spaces", "whitespace", "int", "object"],
)
def test_tenant_session_rejects_missing_tenant(bad_tenant) -> None:
    """tenant_id 缺失或为空时抛错，且不建立任何连接。"""
    engine = _SpyEngine()
    with pytest.raises(TenantContextMissingError):
        with tenant_session(engine, bad_tenant):  # type: ignore[arg-type]
            pass
    # 在建立连接前即拒绝，未占用数据库资源。
    assert engine.connect_calls == 0


@pytest.mark.parametrize(
    "bad_tenant",
    [None, "", "   ", 123],
    ids=["none", "empty", "spaces", "int"],
)
def test_set_tenant_context_rejects_missing_tenant(bad_tenant) -> None:
    """set_tenant_context 对空/缺失 tenant_id 抛错，且不发出任何语句。"""
    conn = _SpyConnection()
    with pytest.raises(TenantContextMissingError):
        set_tenant_context(conn, bad_tenant)  # type: ignore[arg-type]
    assert conn.executed == []
