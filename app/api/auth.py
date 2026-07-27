"""BFF 认证与 RLS 上下文注入（任务 24.1，Requirement 5.1 / 5.4）。

对应设计文档 "Architecture / 1.1 总体分层架构" 中接入层
``API Gateway / BFF（FastAPI Router + Auth + RLS 上下文）`` 的 **Auth + RLS 上下文** 职责。

本模块负责：

1. **从请求中提取并校验 ``tenant_id``**：优先取 ``X-Tenant-Id`` 请求头；否则从
   ``Authorization: Bearer <token>`` 中解析（支持 ``tenant:<id>`` 简易令牌与未签名 JWT
   的 ``tenant_id`` / ``tid`` 声明，作为可替换的 **JWT 桩**）。缺失或为空即拒绝请求
   （HTTP 401），杜绝无租户上下文的数据访问（Requirement 5.4）。
2. **将 ``tenant_id`` 注入请求级 RLS 上下文**：以 ``contextvars`` 承载当前请求的租户标识，
   语义等价于数据库层的 ``SET LOCAL app.current_tenant``（见
   :func:`app.db.session.set_tenant_context`）——请求进入时设置、结束时清理，保证并发请求
   之间互不串扰。若组合根注入了数据库 Engine，则同时开启
   :func:`app.db.session.tenant_session`，令工具层的数据访问在真正的 RLS 事务内进行。

范围约束：真实的身份鉴权（JWT 签名校验、密钥管理）不在本任务范围内；此处提供可替换的
桩实现，聚焦"租户上下文提取 + RLS 注入 + 缺失即拒绝"这一安全边界。
"""

from __future__ import annotations

import base64
import binascii
import json
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

from fastapi import Request

from app.core.errors import TenantContextMissingError

__all__ = [
    "TENANT_ID_HEADER",
    "current_tenant_id",
    "rls_context",
    "extract_request_tenant_id",
    "require_tenant",
]

#: 承载租户上下文的请求头名称。
TENANT_ID_HEADER = "X-Tenant-Id"

#: 请求级 RLS 上下文：保存当前请求的 ``tenant_id``（等价 ``SET LOCAL app.current_tenant``）。
_current_tenant: ContextVar[str | None] = ContextVar("petops_current_tenant", default=None)


def current_tenant_id() -> str | None:
    """返回当前请求上下文中已注入的 ``tenant_id``（未注入时为 ``None``）。"""
    return _current_tenant.get()


def _normalize_tenant_id(tenant_id: object) -> str:
    """校验并归一化 ``tenant_id``；缺失 / 为空时抛租户上下文缺失错误（Requirement 5.4）。"""
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise TenantContextMissingError("缺少有效的租户上下文：tenant_id 不可为空。")
    return tenant_id.strip()


@contextmanager
def rls_context(tenant_id: str, *, db_engine: object | None = None) -> Iterator[str]:
    """在请求期间注入 RLS 上下文（并在需要时开启租户数据库事务）。

    进入时把归一化后的 ``tenant_id`` 写入请求级 ``contextvars``（等价 ``SET LOCAL``），
    退出时恢复先前值，保证并发 / 嵌套请求互不影响。当注入了数据库 Engine 时，同时进入
    :func:`app.db.session.tenant_session`，令块内的数据访问运行在真正设置了
    ``app.current_tenant`` 的 RLS 事务中。

    Raises:
        TenantContextMissingError: ``tenant_id`` 缺失或为空（Requirement 5.4）。
    """
    normalized = _normalize_tenant_id(tenant_id)
    # 记录并在退出时恢复先前值（而非 Token.reset）：FastAPI 对同步生成器依赖的进入 /
    # 退出可能发生在不同的执行上下文，Token.reset 会因跨上下文而失败；直接恢复先前值
    # 既避免该问题，又保证请求间不残留租户上下文。
    previous = _current_tenant.get()
    _current_tenant.set(normalized)
    try:
        if db_engine is not None:
            # 延迟导入，避免在无数据库场景下引入 SQLAlchemy 依赖。
            from app.db.session import tenant_session

            with tenant_session(db_engine, normalized):
                yield normalized
        else:
            yield normalized
    finally:
        _current_tenant.set(previous)


def _decode_bearer_tenant(token: str) -> str | None:
    """从 Bearer 令牌解析 ``tenant_id``（JWT 桩）。

    支持两种形态：

    - ``tenant:<id>`` 简易令牌：直接取冒号后的部分。
    - 未签名 / 已签名 JWT：解析（不校验签名）其 payload 段中的 ``tenant_id`` 或 ``tid`` 声明。

    无法解析时返回 ``None``。真实的 JWT 签名校验不在本任务范围内。
    """
    token = token.strip()
    if not token:
        return None

    # 形态一：tenant:<id> 简易令牌。
    if token.lower().startswith("tenant:"):
        candidate = token.split(":", 1)[1].strip()
        return candidate or None

    # 形态二：JWT（header.payload.signature）——解析 payload 段声明。
    parts = token.split(".")
    if len(parts) >= 2:
        payload_segment = parts[1]
        # base64url 解码需补齐 padding。
        padding = "=" * (-len(payload_segment) % 4)
        try:
            decoded = base64.urlsafe_b64decode(payload_segment + padding)
            claims = json.loads(decoded)
        except (binascii.Error, ValueError, TypeError):
            return None
        if isinstance(claims, dict):
            for key in ("tenant_id", "tid"):
                value = claims.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
    return None


def extract_request_tenant_id(request: Request) -> str | None:
    """从请求提取 ``tenant_id``：优先 ``X-Tenant-Id`` 头，其次 ``Authorization: Bearer``。

    返回归一化后的租户标识；无法提取时返回 ``None``（由调用方决定是否拒绝）。
    """
    header_value = request.headers.get(TENANT_ID_HEADER)
    if isinstance(header_value, str) and header_value.strip():
        return header_value.strip()

    authorization = request.headers.get("Authorization")
    if isinstance(authorization, str):
        scheme, _, credentials = authorization.partition(" ")
        if scheme.lower() == "bearer" and credentials.strip():
            return _decode_bearer_tenant(credentials)
    return None


def require_tenant(request: Request) -> Iterator[str]:
    """FastAPI 依赖：提取并校验租户上下文，随后注入请求级 RLS 上下文。

    作为受保护端点的依赖使用：从请求解析 ``tenant_id``，缺失 / 为空则返回 HTTP 401
    （拒绝无租户上下文的访问，Requirement 5.4）；否则在 :func:`rls_context` 内 ``yield``
    该租户标识，请求处理期间 RLS 上下文有效，处理结束后自动清理。

    组合根若注入了数据库 Engine（``request.app.state.composition.db_engine``），RLS 上下文
    会同时开启对应租户的数据库事务，使工具层的数据访问受行级安全约束（Requirement 5.1）。
    """
    # 延迟导入以避免模块级循环依赖（fastapi.HTTPException 仅在校验失败时需要）。
    from fastapi import HTTPException, status

    tenant_id = extract_request_tenant_id(request)
    try:
        normalized = _normalize_tenant_id(tenant_id)
    except TenantContextMissingError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    composition = getattr(request.app.state, "composition", None)
    db_engine = getattr(composition, "db_engine", None) if composition is not None else None

    with rls_context(normalized, db_engine=db_engine) as active_tenant:
        yield active_tenant
