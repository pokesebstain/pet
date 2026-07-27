"""RLS 会话上下文管理器（任务 2.2）。

在连接/会话级注入当前租户的 ``tenant_id``，驱动 PostgreSQL 行级安全（RLS）策略。
迁移 ``004_rls_policies.sql`` 中的策略通过 ``current_setting('app.current_tenant', TRUE)``
读取该会话变量，因此进入受保护的数据访问前必须先设置它（Requirements 5.1）。

核心设计：
- 使用事务本地（transaction-local）设置，等价于 ``SET LOCAL app.current_tenant = '<tenant_id>'``：
  变量仅在当前事务内生效，事务提交或回滚时由 PostgreSQL 自动清理，无需显式 RESET，
  从而保证连接归还连接池后不会残留上一租户的上下文。
- 为杜绝 SQL 注入，使用参数化的 ``set_config(:name, :value, true)`` 函数注入租户值，
  其中第三个参数 ``true`` 表示事务本地作用域（与 ``SET LOCAL`` 语义一致）。
- ``tenant_id`` 缺失或为空（None、空串、纯空白）时抛出
  :class:`~app.core.errors.TenantContextMissingError`，拒绝任何数据访问（Requirements 5.4）。

用法::

    from app.db import tenant_session
    with tenant_session(engine, "tenant-a") as conn:
        rows = conn.execute(select(customers)).all()  # 仅可见 tenant-a 数据
    # 退出时事务结束，app.current_tenant 自动清理
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Iterator

from sqlalchemy import text

from app.core.errors import TenantContextMissingError
from app.db.metadata import SESSION_TENANT_VARIABLE

if TYPE_CHECKING:  # 仅用于类型标注，避免运行时强依赖。
    from sqlalchemy.engine import Connection, Engine

# 参数化设置语句：等价于 ``SET LOCAL app.current_tenant = '<tenant_id>'``。
# 第三参数 true 表示事务本地作用域（事务结束自动清理），并以绑定参数传值防注入。
_SET_TENANT_CONTEXT_SQL = text("SELECT set_config(:var_name, :tenant_id, true)")


def _require_tenant_id(tenant_id: object) -> str:
    """校验并归一化 ``tenant_id``。

    仅接受非空且去除首尾空白后仍非空的字符串；否则视为租户上下文缺失。

    Raises:
        TenantContextMissingError: 当 ``tenant_id`` 为 None、非字符串、空串或纯空白时。
    """
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise TenantContextMissingError(
            "缺少有效的租户上下文：tenant_id 不可为空。"
        )
    return tenant_id


def set_tenant_context(connection: "Connection", tenant_id: str) -> str:
    """在既有连接的当前事务上注入租户上下文。

    发出等价于 ``SET LOCAL app.current_tenant = '<tenant_id>'`` 的语句。调用方需保证
    ``connection`` 处于活动事务中，设置随事务结束自动清理。适用于工具层（任务 7）在
    自管理事务内复用本注入逻辑。

    Args:
        connection: 处于活动事务中的 SQLAlchemy 连接。
        tenant_id: 目标租户标识，不可为空。

    Returns:
        归一化后的 ``tenant_id``。

    Raises:
        TenantContextMissingError: 当 ``tenant_id`` 缺失或为空时。
    """
    normalized = _require_tenant_id(tenant_id)
    connection.execute(
        _SET_TENANT_CONTEXT_SQL,
        {"var_name": SESSION_TENANT_VARIABLE, "tenant_id": normalized},
    )
    return normalized


@contextmanager
def tenant_session(engine: "Engine", tenant_id: str) -> Iterator["Connection"]:
    """打开一个已注入租户上下文的连接/事务上下文管理器。

    进入时在新连接的事务内设置 ``app.current_tenant``（事务本地，等价 ``SET LOCAL``）；
    退出时事务提交（异常时回滚），PostgreSQL 随事务结束自动清理该会话变量。

    Args:
        engine: SQLAlchemy Engine。
        tenant_id: 当前租户标识，不可为空。

    Yields:
        已设置租户上下文、处于活动事务中的连接；块内的读写均受 RLS 约束在该租户范围内。

    Raises:
        TenantContextMissingError: 当 ``tenant_id`` 缺失或为空时（在建立连接前即拒绝）。
    """
    # 先校验再获取连接：上下文缺失时不占用任何数据库资源。
    normalized = _require_tenant_id(tenant_id)
    with engine.connect() as connection:
        with connection.begin():
            set_tenant_context(connection, normalized)
            yield connection
        # 事务在此结束（提交或回滚），SET LOCAL 设置随之自动清理。
