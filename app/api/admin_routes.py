"""Admin Dashboard 后端路由（按资源分 router，全部挂在 ``/api/admin/`` 前缀下）。

所有端点依赖 :func:`app.api.auth.require_tenant` 自动注入 RLS 上下文；不新增鉴权。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text

from app.api.admin_schemas import CustomerIn, CustomerOut, PageResp
from app.api.auth import require_tenant
from app.db.init import create_db_engine

# 顶层 router：所有资源挂在此下，统一前缀 ``/api/admin`` 由 app.py 注册时设置。
router = APIRouter(tags=["admin"])


@router.get("/health")
def admin_health(tenant_id: str = Depends(require_tenant)) -> dict[str, str]:
    """管理后台存活探针：含当前租户 ID（验证 RLS 注入）。"""
    return {"status": "ok", "tenant_id": tenant_id}


# --------------------------------------------------------------------------- #
# Customers 资源
# --------------------------------------------------------------------------- #
customers_router = APIRouter(prefix="/customers", tags=["admin-customers"])


@customers_router.get("", response_model=PageResp[CustomerOut])
def list_customers(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    search: str | None = Query(None),
    tenant_id: str = Depends(require_tenant),
) -> PageResp[CustomerOut]:
    """客户列表：分页 + 搜索。"""
    engine = create_db_engine()
    offset = (page - 1) * page_size
    where_clauses = ["tenant_id = :tid", "deleted_at IS NULL"]
    params: dict[str, object] = {"tid": tenant_id, "limit": page_size, "offset": offset}
    if search:
        where_clauses.append("(name ILIKE :s OR phone ILIKE :s)")
        params["s"] = f"%{search}%"
    where_sql = " AND ".join(where_clauses)
    with engine.connect() as conn:
        conn.execute(text("SET LOCAL app.current_tenant = :tid"), {"tid": tenant_id})
        conn.execute(text("BEGIN"))
        rows = conn.execute(
            text(
                f"SELECT customer_id, name, phone, registered_at, ltv, churn_score, "
                f"segment, onboarding_pending FROM customers "
                f"WHERE {where_sql} ORDER BY registered_at DESC LIMIT :limit OFFSET :offset"
            ),
            params,
        ).fetchall()
        total = conn.execute(
            text(f"SELECT COUNT(*) FROM customers WHERE {where_sql}"), params
        ).scalar_one()
    items = [
        CustomerOut(
            customer_id=r.customer_id,
            name=r.name,
            phone=r.phone,
            registered_at=r.registered_at,
            ltv=r.ltv,
            churn_score=r.churn_score,
            segment=r.segment,
            onboarding_pending=r.onboarding_pending,
            deleted_at=None,
        )
        for r in rows
    ]
    return PageResp(items=items, total=total, page=page, page_size=page_size)


@customers_router.get("/{customer_id}", response_model=CustomerOut)
def get_customer(customer_id: str, tenant_id: str = Depends(require_tenant)) -> CustomerOut:
    engine = create_db_engine()
    with engine.connect() as conn:
        conn.execute(text("SET LOCAL app.current_tenant = :tid"), {"tid": tenant_id})
        conn.execute(text("BEGIN"))
        row = conn.execute(
            text(
                "SELECT customer_id, name, phone, registered_at, ltv, churn_score, "
                "segment, onboarding_pending FROM customers "
                "WHERE customer_id = :cid AND deleted_at IS NULL"
            ),
            {"tid": tenant_id, "cid": customer_id},
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="客户不存在")
    return CustomerOut(
        customer_id=row.customer_id,
        name=row.name,
        phone=row.phone,
        registered_at=row.registered_at,
        ltv=row.ltv,
        churn_score=row.churn_score,
        segment=row.segment,
        onboarding_pending=row.onboarding_pending,
        deleted_at=None,
    )


@customers_router.post("", response_model=CustomerOut, status_code=status.HTTP_201_CREATED)
def create_customer(
    payload: CustomerIn, tenant_id: str = Depends(require_tenant)
) -> CustomerOut:
    customer_id = f"cust-{uuid.uuid4().hex[:12]}"
    engine = create_db_engine()
    registered_at = datetime.now(timezone.utc)
    with engine.connect() as conn:
        conn.execute(text("SET LOCAL app.current_tenant = :tid"), {"tid": tenant_id})
        conn.execute(text("BEGIN"))
        conn.execute(
            text(
                "INSERT INTO customers (customer_id, tenant_id, name, phone, registered_at) "
                "VALUES (:cid, :tid, :name, :phone, :reg_at)"
            ),
            {
                "cid": customer_id,
                "tid": tenant_id,
                "name": payload.name,
                "phone": payload.phone,
                "reg_at": registered_at,
            },
        )
        conn.commit()
    return CustomerOut(
        customer_id=customer_id,
        name=payload.name,
        phone=payload.phone,
        registered_at=registered_at,
        ltv=None,
        churn_score=None,
        segment=None,
        onboarding_pending=False,
        deleted_at=None,
    )


@customers_router.put("/{customer_id}", response_model=CustomerOut)
def update_customer(
    customer_id: str,
    payload: CustomerIn,
    tenant_id: str = Depends(require_tenant),
) -> CustomerOut:
    engine = create_db_engine()
    with engine.connect() as conn:
        conn.execute(text("SET LOCAL app.current_tenant = :tid"), {"tid": tenant_id})
        conn.execute(text("BEGIN"))
        result = conn.execute(
            text(
                "UPDATE customers SET name = :name, phone = :phone "
                "WHERE customer_id = :cid AND deleted_at IS NULL"
            ),
            {"name": payload.name, "phone": payload.phone, "cid": customer_id},
        )
        conn.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="客户不存在")
    return get_customer(customer_id, tenant_id)


@customers_router.delete("/{customer_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_customer(customer_id: str, tenant_id: str = Depends(require_tenant)) -> None:
    engine = create_db_engine()
    with engine.connect() as conn:
        conn.execute(text("SET LOCAL app.current_tenant = :tid"), {"tid": tenant_id})
        conn.execute(text("BEGIN"))
        result = conn.execute(
            text(
                "UPDATE customers SET deleted_at = :now "
                "WHERE customer_id = :cid AND deleted_at IS NULL"
            ),
            {"now": datetime.now(timezone.utc), "cid": customer_id},
        )
        conn.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="客户不存在")


router.include_router(customers_router)
