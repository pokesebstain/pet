"""Admin Dashboard 后端路由测试。"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.api import build_composition, create_app


def _client() -> TestClient:
    """构造一个最小可用的 TestClient（无 admin 业务数据，纯路由骨架）。"""
    composition = build_composition()
    return TestClient(create_app(composition=composition))


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


def test_customers_list_endpoint_registered() -> None:
    """路由已注册（即使 DB 不可用时 OpenAPI schema 仍可见）。"""
    client = _client()
    resp = client.get("/api/admin/customers", headers={"X-Tenant-Id": "test"})
    # 401/500/200 都行，关键是路由存在而不是 404
    assert resp.status_code != 404
