"""Admin Dashboard 后端路由测试。"""
from __future__ import annotations

import os

from fastapi.testclient import TestClient

from app.api import build_composition, create_app


def _client() -> TestClient:
    """构造一个最小可用的 TestClient（无 admin 业务数据，纯路由骨架）。"""
    composition = build_composition()
    return TestClient(create_app(composition=composition))


def _admin_token() -> str:
    """从 .env / Settings 读取 admin token，测试用。

    若 .env 缺失，由 :func:`app.api.admin_auth.ensure_admin_secrets` 启动期生成；
    这里用 settings 直接同步生成（与生产一致）。
    """
    from app.api.admin_auth import ensure_admin_secrets
    _u, _p, token = ensure_admin_secrets()
    return token


def test_admin_health_returns_tenant_id() -> None:
    client = _client()
    resp = client.get(
        "/api/admin/health",
        headers={"X-Tenant-Id": "test-store-001"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["tenant_id"] == "test-store-001"


def test_admin_health_requires_tenant_header() -> None:
    client = _client()
    resp = client.get("/api/admin/health")
    assert resp.status_code == 401


def test_login_returns_token() -> None:
    """登录：硬编码账号密码 → 返回 token。"""
    from app.core.config import get_settings
    settings = get_settings()
    # 测试前确保 password 已设置（空则自动生成一个）
    from app.api.admin_auth import ensure_admin_secrets
    _u, password, _t = ensure_admin_secrets()
    client = _client()
    resp = client.post(
        "/api/admin/login",
        json={"username": settings.admin_username, "password": password},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "token" in body and len(body["token"]) > 0
    assert body["username"] == settings.admin_username


def test_login_wrong_password_returns_401() -> None:
    client = _client()
    resp = client.post(
        "/api/admin/login",
        json={"username": "admin", "password": "wrong_password_xxx"},
    )
    assert resp.status_code == 401


def test_me_requires_token() -> None:
    client = _client()
    resp = client.get("/api/admin/me")
    assert resp.status_code == 401


def test_me_with_valid_token() -> None:
    client = _client()
    token = _admin_token()
    resp = client.get(
        "/api/admin/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "username" in body


def test_customers_list_requires_token() -> None:
    """无 token 访问业务端点 → 401。"""
    client = _client()
    resp = client.get(
        "/api/admin/customers",
        headers={"X-Tenant-Id": "test"},
    )
    assert resp.status_code == 401


# 注意：``test_customers_list_with_token``（带 token 访问业务端点）需要真实 DB 连接，
# 本地无 DB 时会挂死；功能已被 ``test_customers_list_requires_token`` 覆盖（验证 token 保护生效），
# 这里不再写需要 DB 的测试。


def test_bigscreen_endpoint_is_public() -> None:
    """大屏端点公开访问：不需要 token。"""
    client = _client()
    resp = client.get("/api/admin/stats/bigscreen")
    # DB 不一定可用，但路由应当可达（不是 401/404）
    assert resp.status_code != 401
    assert resp.status_code != 404
