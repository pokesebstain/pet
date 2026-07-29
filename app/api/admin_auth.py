"""Admin 后台登录鉴权（硬编码单用户 + 启动期生成 token）。

设计：
- 启动时若 :attr:`Settings.admin_password` 为空，自动生成随机密码并打 WARNING 日志，
  让运维从日志取密码；若 :attr:`Settings.admin_token` 为空，自动生成 64 字节 url-safe token。
- 登录用常量时间比较防时序攻击；token 验证同样常量时间。
- 后端不维护会话表（无状态），token 由 .env 持久化，丢失可通过清空重启生成。
"""
from __future__ import annotations

import hashlib
import hmac
import secrets

from fastapi import Header, HTTPException, status
from pydantic import BaseModel

from app.core.config import get_settings

_TOKEN_LEN = 64


def ensure_admin_secrets() -> tuple[str, str, str]:
    """确保 admin_password / admin_token 已设置；返回 (username, password_plain, token)。

    若 :attr:`Settings.admin_password` 为空，生成一个 16 字符随机密码并日志提示；
    若 :attr:`Settings.admin_token` 为空，生成一个 64 字节 url-safe token。
    注意：本函数只读 + 写回 ``Settings``，**不**回写 .env（避免 IO 副作用）；
    调用方应在 entrypoint 阶段把生成结果回写到 :file:`.env`。
    """
    settings = get_settings()
    username = settings.admin_username or "admin"

    password = settings.admin_password.get_secret_value()
    if not password:
        # 16 字符密码对店主来说够用 + 难猜
        password = secrets.token_urlsafe(12)[:16]
        settings.admin_password = type(settings.admin_password)(password)  # type: ignore[call-arg]

    token = settings.admin_token.get_secret_value()
    if not token:
        token = secrets.token_urlsafe(_TOKEN_LEN)
        settings.admin_token = type(settings.admin_token)(token)  # type: ignore[call-arg]

    return username, password, token


def _constant_time_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def verify_credentials(username: str, password: str) -> bool:
    """验证登录凭证。"""
    settings = get_settings()
    expected_user = settings.admin_username or "admin"
    if not _constant_time_eq(username, expected_user):
        return False
    expected_pw = settings.admin_password.get_secret_value()
    if not expected_pw:
        return False
    # 使用 SHA-256 哈希后比较，避免明文密码在内存 / 日志中泄露。
    a = hashlib.sha256(password.encode("utf-8")).hexdigest()
    b = hashlib.sha256(expected_pw.encode("utf-8")).hexdigest()
    return _constant_time_eq(a, b)


def get_current_token(authorization: str | None = Header(default=None)) -> str:
    """从 ``Authorization: Bearer <token>`` header 提取并验证 token。

    Returns:
        当前用户的 token（验证通过）。

    Raises:
        HTTPException 401: 未提供 token / token 错误。
    """
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未登录",
            headers={"WWW-Authenticate": "Bearer"},
        )
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization 格式错误，应为 'Bearer <token>'",
            headers={"WWW-Authenticate": "Bearer"},
        )
    provided = parts[1].strip()
    expected = get_settings().admin_token.get_secret_value()
    if not _constant_time_eq(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="token 无效或已失效",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return provided


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    username: str


class MeResponse(BaseModel):
    username: str
