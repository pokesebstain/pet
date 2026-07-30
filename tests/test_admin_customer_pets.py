"""Focused contracts for customer-pet admin routes without a PostgreSQL dependency."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api import admin_routes
from app.api.admin_schemas import PetIn


class _Result:
    def __init__(self, *, rows=(), row=None, scalar=None, rowcount=1):
        self._rows = list(rows)
        self._row = row
        self._scalar = scalar
        self.rowcount = rowcount

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._row

    def scalar_one(self):
        return self._scalar


class _Connection:
    def __init__(self, responder):
        self.calls: list[tuple[str, dict | None]] = []
        self._responder = responder

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, statement, params=None):
        sql = str(statement)
        self.calls.append((sql, params))
        return self._responder(sql, params or {})

    def commit(self):
        pass


class _Engine:
    def __init__(self, connection: _Connection):
        self.connection = connection

    def connect(self):
        return self.connection


def test_customer_list_returns_tenant_scoped_pet_count(monkeypatch: pytest.MonkeyPatch) -> None:
    """The correlated count keeps customers with zero pets and matches their tenant."""
    customer = SimpleNamespace(
        customer_id="cust-a", name="张三", phone=None,
        registered_at=datetime.now(timezone.utc), ltv=None, churn_score=None,
        segment=None, onboarding_pending=False, pet_count=0,
    )

    def respond(sql: str, _params: dict) -> _Result:
        if "SELECT c.customer_id" in sql:
            return _Result(rows=[customer])
        if "SELECT COUNT(*) FROM customers c" in sql:
            return _Result(scalar=1)
        return _Result()

    connection = _Connection(respond)
    monkeypatch.setattr(admin_routes, "create_db_engine", lambda: _Engine(connection))

    response = admin_routes.list_customers(
        page=1, page_size=20, search=None, onboarding_pending=None, tenant_id="tenant-a"
    )

    assert response.items[0].pet_count == 0
    query = next(sql for sql, _ in connection.calls if "SELECT c.customer_id" in sql)
    assert "p.owner_id = c.customer_id" in query
    assert "p.tenant_id = c.tenant_id" in query


def test_owner_filtered_pet_list_checks_current_tenant_customer(monkeypatch: pytest.MonkeyPatch) -> None:
    """owner_id cannot expose a cross-tenant customer's pets."""
    pet = SimpleNamespace(
        pet_id="pet-a", owner_id="cust-a", name="团团", species=None, breed=None,
        birth_date=None, weight_kg=None, life_stage=None, onboarding_pending=True,
    )

    def respond(sql: str, _params: dict) -> _Result:
        if "SELECT 1 FROM customers" in sql:
            return _Result(row=SimpleNamespace(exists=1))
        if "SELECT p.pet_id" in sql:
            return _Result(rows=[pet])
        if "SELECT COUNT(*) FROM pets p" in sql:
            return _Result(scalar=1)
        return _Result()

    connection = _Connection(respond)
    monkeypatch.setattr(admin_routes, "create_db_engine", lambda: _Engine(connection))

    response = admin_routes.list_pets(
        page=1, page_size=20, search=None, onboarding_pending=None,
        owner_id="cust-a", tenant_id="tenant-a",
    )

    assert response.items[0].pet_id == "pet-a"
    owner_query = next(sql for sql, _ in connection.calls if "SELECT 1 FROM customers" in sql)
    pets_query = next(sql for sql, _ in connection.calls if "SELECT p.pet_id" in sql)
    assert "tenant_id = :tid" in owner_query
    assert "p.tenant_id = :tid" in pets_query
    assert "p.owner_id = :owner_id" in pets_query


def test_owner_filter_rejects_customer_outside_current_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    def respond(sql: str, _params: dict) -> _Result:
        if "SELECT 1 FROM customers" in sql:
            return _Result(row=None)
        return _Result()

    connection = _Connection(respond)
    monkeypatch.setattr(admin_routes, "create_db_engine", lambda: _Engine(connection))

    with pytest.raises(HTTPException, match="客户不存在") as error:
        admin_routes.list_pets(
            page=1, page_size=20, search=None, onboarding_pending=None,
            owner_id="cust-b", tenant_id="tenant-a",
        )

    assert error.value.status_code == 404
    assert not any("SELECT p.pet_id" in sql for sql, _ in connection.calls)


def test_creating_pet_preserves_missing_profile_fields_as_null(monkeypatch: pytest.MonkeyPatch) -> None:
    inserted: dict[str, object] = {}

    def respond(sql: str, params: dict) -> _Result:
        if "SELECT 1 FROM customers" in sql:
            return _Result(row=SimpleNamespace(exists=1))
        if "INSERT INTO pets" in sql:
            inserted.update(params)
        return _Result()

    connection = _Connection(respond)
    monkeypatch.setattr(admin_routes, "create_db_engine", lambda: _Engine(connection))

    response = admin_routes.create_pet(
        PetIn(owner_id="cust-a", name="团团", species=None, breed="  "), "tenant-a"
    )

    assert response.species is None
    assert response.breed is None
    assert response.onboarding_pending is True
    assert inserted["sp"] is None
    assert inserted["br"] is None
    assert inserted["op"] is True
