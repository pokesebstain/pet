"""Admin Dashboard 后端路由（按资源分 router，全部挂在 ``/api/admin/`` 前缀下）。

业务端点依赖 :func:`app.api.auth.require_admin_tenant` 解析门店默认租户；
登录端点 (``/login`` / ``/logout`` / ``/me``) 与大屏端点 (``/stats/bigscreen``) 不需要鉴权。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text

from app.api.admin_auth import (
    LoginRequest,
    LoginResponse,
    MeResponse,
    ensure_admin_secrets,
    get_current_token,
    verify_credentials,
)
from app.api.admin_schemas import (
    AppointmentIn,
    AppointmentOut,
    AppointmentUpdateIn,
    BillingReportOut,
    BusinessHourIn,
    BusinessHourOut,
    ChurnRiskOut,
    CustomerIn,
    PetInlineIn,
    CustomerOut,
    DailyTrendPoint,
    FeatureVectorOut,
    HealthAlertOut,
    HealthMetricOut,
    LtvSegmentOut,
    MarketingContentGenerateIn,
    MarketingContentOut,
    OverviewStats,
    PageResp,
    PartnerHospitalOut,
    PetIn,
    PetOut,
    ReferralOut,
    ResourceIn,
    ResourceOut,
    RestockDecisionOut,
    SkuIn,
    SkuOut,
    SubscriptionOut,
    TodoOut,
    TraceDetailOut,
    TraceOut,
    TrendsOut,
)
from app.api.auth import require_admin_tenant
from app.core.config import get_settings
from app.db.init import create_db_engine

# 顶层 router：所有资源挂在此下，统一前缀 ``/api/admin`` 由 app.py 注册时设置。
router = APIRouter(tags=["admin"])


@router.get("/health")
def admin_health(tenant_id: str = Depends(require_admin_tenant)) -> dict[str, str]:
    """管理后台存活探针：含当前租户 ID（验证 RLS 注入）。"""
    return {"status": "ok", "tenant_id": tenant_id}


# --------------------------------------------------------------------------- #
# 登录鉴权（无需 tenant / token 即可调用）
# --------------------------------------------------------------------------- #
@router.post("/login", response_model=LoginResponse)
def admin_login(payload: LoginRequest) -> LoginResponse:
    """登录：验证 username/password → 返回 token。

    首次启动若 ``admin_password`` 为空，:func:`ensure_admin_secrets` 自动生成随机密码
    并日志提示（运维从日志取）。前端拿到 token 后存 localStorage，axios 拦截器自动
    加 ``Authorization: Bearer <token>``。
    """
    # 触发启动期 secrets 生成（仅在 .env 为空时有效）
    username, _password, _token = ensure_admin_secrets()
    if not verify_credentials(payload.username, payload.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )
    settings = get_settings()
    return LoginResponse(
        token=settings.admin_token.get_secret_value(),
        username=username,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def admin_logout() -> None:
    """登出（无状态，前端清 token 即可）。"""
    return None


@router.get("/me", response_model=MeResponse, dependencies=[Depends(get_current_token)])
def admin_me() -> MeResponse:
    """返回当前登录用户（验证 token 有效性用）。"""
    settings = get_settings()
    return MeResponse(username=settings.admin_username or "admin")


# --------------------------------------------------------------------------- #
# 大屏（公开访问，无 token / 无 tenant 要求）
# --------------------------------------------------------------------------- #
@router.get("/stats/bigscreen")
def stats_bigscreen() -> dict:
    """大屏聚合数据：核心数字 + 服务分布 + 热门宠物 TOP 5。

    公开访问（店内电视友好），不需 tenant；数据来自默认租户。
    """
    settings = get_settings()
    tenant_id = settings.default_tenant_id or settings.wecom.corp_id or "default"
    engine = create_db_engine()
    with engine.connect() as conn:
        conn.execute(text("SELECT set_config('app.current_tenant', :tid, true)"), {"tid": tenant_id})
        conn.execute(text("BEGIN"))
        # 5 个核心数字
        today_appts = conn.execute(
            text(
                "SELECT COUNT(*) FROM appointments "
                "WHERE start_at::date = CURRENT_DATE AND status NOT IN ('cancelled')"
            ),
            {"tid": tenant_id},
        ).scalar_one()
        new_custs = conn.execute(
            text(
                "SELECT COUNT(*) FROM customers "
                "WHERE registered_at::date = CURRENT_DATE AND deleted_at IS NULL"
            ),
            {"tid": tenant_id},
        ).scalar_one()
        month_revenue = conn.execute(
            text(
                "SELECT COALESCE(SUM(amount), 0) FROM billing_records "
                "WHERE billing_month = DATE_TRUNC('month', CURRENT_DATE)::date "
                "AND status = 'paid'"
            ),
            {"tid": tenant_id},
        ).scalar_one()
        pending_alerts = conn.execute(
            text("SELECT COUNT(*) FROM health_alerts WHERE acked_at IS NULL"),
            {"tid": tenant_id},
        ).scalar_one()
        low_stock = conn.execute(
            text("SELECT COUNT(*) FROM skus WHERE current_stock < safety_stock"),
            {"tid": tenant_id},
        ).scalar_one()

        # 服务分布（按 service_type 聚合）
        svc_rows = conn.execute(
            text(
                "SELECT service_type, COUNT(*) AS cnt FROM appointments "
                "WHERE status NOT IN ('cancelled') AND start_at >= "
                "DATE_TRUNC('month', CURRENT_DATE) "
                "GROUP BY service_type"
            ),
            {"tid": tenant_id},
        ).fetchall()
        total_svc = sum(int(r.cnt) for r in svc_rows) or 1
        service_distribution = {
            r.service_type: round(int(r.cnt) * 100.0 / total_svc, 1)
            for r in svc_rows
        }

        # 热门宠物 TOP 5（按到店次数降序）
        top_pets_rows = conn.execute(
            text(
                "SELECT name, COUNT(*) AS visits FROM pets p "
                "JOIN appointments a ON a.pet_id = p.pet_id "
                "WHERE a.status NOT IN ('cancelled') "
                "GROUP BY p.pet_id, p.name "
                "ORDER BY visits DESC LIMIT 5"
            ),
            {"tid": tenant_id},
        ).fetchall()
        top_pets = [
            {"name": r.name or "未命名", "visits": int(r.visits)}
            for r in top_pets_rows
        ]

    return {
        "today_appointments": int(today_appts),
        "today_new_customers": int(new_custs),
        "month_revenue": float(month_revenue),
        "pending_alerts": int(pending_alerts),
        "low_stock_skus": int(low_stock),
        "service_distribution": service_distribution,
        "top_pets": top_pets,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


# --------------------------------------------------------------------------- #
# Customers 资源
# --------------------------------------------------------------------------- #
customers_router = APIRouter(prefix="/customers", tags=["admin-customers"], dependencies=[Depends(get_current_token)])


@customers_router.get("", response_model=PageResp[CustomerOut])
def list_customers(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    search: str | None = Query(None),
    onboarding_pending: bool | None = Query(None),
    tenant_id: str = Depends(require_admin_tenant),
) -> PageResp[CustomerOut]:
    """客户列表：分页 + 搜索 + 可选按待完善档案过滤（供仪表盘待办跳转预筛选）。"""
    engine = create_db_engine()
    offset = (page - 1) * page_size
    where_clauses = ["c.tenant_id = :tid", "c.deleted_at IS NULL"]
    params: dict[str, object] = {"tid": tenant_id, "limit": page_size, "offset": offset}
    if search:
        where_clauses.append("(c.name ILIKE :s OR c.phone ILIKE :s)")
        params["s"] = f"%{search}%"
    if onboarding_pending is not None:
        where_clauses.append("c.onboarding_pending = :onboarding_pending")
        params["onboarding_pending"] = onboarding_pending
    where_sql = " AND ".join(where_clauses)
    with engine.connect() as conn:
        conn.execute(text("SELECT set_config('app.current_tenant', :tid, true)"), {"tid": tenant_id})
        conn.execute(text("BEGIN"))
        rows = conn.execute(
            text(
                f"SELECT c.customer_id, c.name, c.phone, c.registered_at, c.ltv, c.churn_score, "
                f"c.segment, c.onboarding_pending, c.wechat_openid, "
                f"(SELECT COUNT(*) FROM pets p WHERE p.owner_id = c.customer_id "
                f"AND p.tenant_id = c.tenant_id) AS pet_count "
                f"FROM customers c WHERE {where_sql} "
                f"ORDER BY c.registered_at DESC LIMIT :limit OFFSET :offset"
            ),
            params,
        ).fetchall()
        total = conn.execute(
            text(f"SELECT COUNT(*) FROM customers c WHERE {where_sql}"), params
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
            pet_count=int(r.pet_count),
            wechat_openid=r.wechat_openid,
        )
        for r in rows
    ]
    return PageResp(items=items, total=total, page=page, page_size=page_size)


@customers_router.get("/{customer_id}", response_model=CustomerOut)
def get_customer(customer_id: str, tenant_id: str = Depends(require_admin_tenant)) -> CustomerOut:
    engine = create_db_engine()
    with engine.connect() as conn:
        conn.execute(text("SELECT set_config('app.current_tenant', :tid, true)"), {"tid": tenant_id})
        conn.execute(text("BEGIN"))
        row = conn.execute(
            text(
                "SELECT c.customer_id, c.name, c.phone, c.registered_at, c.ltv, c.churn_score, "
                "c.segment, c.onboarding_pending, c.wechat_openid, "
                "(SELECT COUNT(*) FROM pets p WHERE p.owner_id = c.customer_id "
                "AND p.tenant_id = c.tenant_id) AS pet_count, c.wechat_openid "
                "FROM customers c WHERE c.customer_id = :cid AND c.tenant_id = :tid "
                "AND c.deleted_at IS NULL"
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
        pet_count=int(row.pet_count),
        wechat_openid=row.wechat_openid,
    )


@customers_router.post("", response_model=CustomerOut, status_code=status.HTTP_201_CREATED)
def create_customer(
    payload: CustomerIn, tenant_id: str = Depends(require_admin_tenant)
) -> CustomerOut:
    customer_id = f"cust-{uuid.uuid4().hex[:12]}"
    engine = create_db_engine()
    registered_at = datetime.now(timezone.utc)
    with engine.connect() as conn:
        conn.execute(text("SELECT set_config('app.current_tenant', :tid, true)"), {"tid": tenant_id})
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
        # 同时创建宠物（如果提供了宠物信息）
        if payload.pet and payload.pet.name:
            pet_id = f"pet-{uuid.uuid4().hex[:12]}"
            conn.execute(
                text(
                    "INSERT INTO pets (pet_id, tenant_id, owner_id, name, species, breed, onboarding_pending) "
                    "VALUES (:pid, :tid, :oid, :pname, :species, :breed, :pending)"
                ),
                {
                    "pid": pet_id,
                    "tid": tenant_id,
                    "oid": customer_id,
                    "pname": payload.pet.name,
                    "species": payload.pet.species,
                    "breed": payload.pet.breed,
                    "pending": False,
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
    tenant_id: str = Depends(require_admin_tenant),
) -> CustomerOut:
    engine = create_db_engine()
    with engine.connect() as conn:
        conn.execute(text("SELECT set_config('app.current_tenant', :tid, true)"), {"tid": tenant_id})
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
def delete_customer(customer_id: str, tenant_id: str = Depends(require_admin_tenant)) -> None:
    engine = create_db_engine()
    with engine.connect() as conn:
        conn.execute(text("SELECT set_config('app.current_tenant', :tid, true)"), {"tid": tenant_id})
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


# --------------------------------------------------------------------------- #
# Pets 资源
# --------------------------------------------------------------------------- #
pets_router = APIRouter(prefix="/pets", tags=["admin-pets"], dependencies=[Depends(get_current_token)])


def _require_current_tenant_customer(conn, owner_id: str, tenant_id: str) -> None:
    """确认宠物归属客户属于当前租户，避免跨租户或孤立 owner_id 写入。"""
    owner = conn.execute(
        text(
            "SELECT 1 FROM customers WHERE customer_id = :oid AND tenant_id = :tid "
            "AND deleted_at IS NULL"
        ),
        {"oid": owner_id, "tid": tenant_id},
    ).fetchone()
    if owner is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="客户不存在")


def _nullable_text(value: str | None) -> str | None:
    """将未填写或仅空白的渐进式资料保持为 NULL，而不是事实性占位值。"""
    return value.strip() or None if value else None


@pets_router.get("", response_model=PageResp[PetOut])
def list_pets(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    search: str | None = Query(None),
    onboarding_pending: bool | None = Query(None),
    owner_id: str | None = Query(None),
    tenant_id: str = Depends(require_admin_tenant),
) -> PageResp[PetOut]:
    """宠物列表；owner_id 只在当前租户已存在的客户范围内查询。"""
    engine = create_db_engine()
    offset = (page - 1) * page_size
    where = ["p.tenant_id = :tid"]
    params: dict[str, object] = {"tid": tenant_id, "limit": page_size, "offset": offset}
    if search:
        where.append("(p.name ILIKE :s OR p.breed ILIKE :s)")
        params["s"] = f"%{search}%"
    if onboarding_pending is not None:
        where.append("p.onboarding_pending = :onboarding_pending")
        params["onboarding_pending"] = onboarding_pending
    if owner_id:
        where.append("p.owner_id = :owner_id")
        params["owner_id"] = owner_id
    where_sql = " AND ".join(where)
    with engine.connect() as conn:
        conn.execute(text("SELECT set_config('app.current_tenant', :tid, true)"), {"tid": tenant_id})
        conn.execute(text("BEGIN"))
        if owner_id:
            _require_current_tenant_customer(conn, owner_id, tenant_id)
        rows = conn.execute(
            text(
                f"SELECT p.pet_id, p.owner_id, p.name, p.species, p.breed, p.birth_date, p.weight_kg, "
                f"p.life_stage, p.onboarding_pending FROM pets p WHERE {where_sql} "
                f"ORDER BY p.pet_id LIMIT :limit OFFSET :offset"
            ),
            params,
        ).fetchall()
        total = conn.execute(
            text(f"SELECT COUNT(*) FROM pets p WHERE {where_sql}"), params
        ).scalar_one()
    items = [
        PetOut(
            pet_id=r.pet_id, owner_id=r.owner_id, name=r.name,
            species=r.species, breed=r.breed, birth_date=r.birth_date,
            weight_kg=float(r.weight_kg) if r.weight_kg is not None else None,
            life_stage=r.life_stage,
            onboarding_pending=bool(r.onboarding_pending),
        )
        for r in rows
    ]
    return PageResp(items=items, total=total, page=page, page_size=page_size)


@pets_router.get("/{pet_id}", response_model=PetOut)
def get_pet(pet_id: str, tenant_id: str = Depends(require_admin_tenant)) -> PetOut:
    engine = create_db_engine()
    with engine.connect() as conn:
        conn.execute(text("SELECT set_config('app.current_tenant', :tid, true)"), {"tid": tenant_id})
        conn.execute(text("BEGIN"))
        row = conn.execute(
            text(
                "SELECT pet_id, owner_id, name, species, breed, birth_date, weight_kg, "
                "life_stage, onboarding_pending FROM pets "
                "WHERE pet_id = :pid AND tenant_id = :tid"
            ),
            {"tid": tenant_id, "pid": pet_id},
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="宠物不存在")
    return PetOut(
        pet_id=row.pet_id, owner_id=row.owner_id, name=row.name,
        species=row.species, breed=row.breed, birth_date=row.birth_date,
        weight_kg=float(row.weight_kg) if row.weight_kg is not None else None,
        life_stage=row.life_stage,
        onboarding_pending=bool(row.onboarding_pending),
    )


@pets_router.post("", response_model=PetOut, status_code=status.HTTP_201_CREATED)
def create_pet(payload: PetIn, tenant_id: str = Depends(require_admin_tenant)) -> PetOut:
    pet_id = f"pet-{uuid.uuid4().hex[:12]}"
    species = _nullable_text(payload.species)
    breed = _nullable_text(payload.breed)
    onboarding_pending = species is None or breed is None
    engine = create_db_engine()
    with engine.connect() as conn:
        conn.execute(text("SELECT set_config('app.current_tenant', :tid, true)"), {"tid": tenant_id})
        conn.execute(text("BEGIN"))
        _require_current_tenant_customer(conn, payload.owner_id, tenant_id)
        conn.execute(
            text(
                "INSERT INTO pets (pet_id, tenant_id, owner_id, name, species, breed, "
                "birth_date, weight_kg, life_stage, onboarding_pending) "
                "VALUES (:pid, :tid, :oid, :n, :sp, :br, :bd, :w, :ls, :op)"
            ),
            {
                "pid": pet_id, "tid": tenant_id, "oid": payload.owner_id,
                "n": _nullable_text(payload.name), "sp": species, "br": breed,
                "bd": payload.birth_date, "w": payload.weight_kg, "ls": payload.life_stage,
                "op": onboarding_pending,
            },
        )
        conn.commit()
    return PetOut(
        pet_id=pet_id, owner_id=payload.owner_id, name=_nullable_text(payload.name),
        species=species, breed=breed, birth_date=payload.birth_date,
        weight_kg=payload.weight_kg, life_stage=payload.life_stage,
        onboarding_pending=onboarding_pending,
    )


@pets_router.put("/{pet_id}", response_model=PetOut)
def update_pet(pet_id: str, payload: PetIn, tenant_id: str = Depends(require_admin_tenant)) -> PetOut:
    species = _nullable_text(payload.species)
    breed = _nullable_text(payload.breed)
    onboarding_pending = species is None or breed is None
    engine = create_db_engine()
    with engine.connect() as conn:
        conn.execute(text("SELECT set_config('app.current_tenant', :tid, true)"), {"tid": tenant_id})
        conn.execute(text("BEGIN"))
        _require_current_tenant_customer(conn, payload.owner_id, tenant_id)
        result = conn.execute(
            text(
                "UPDATE pets SET owner_id = :oid, name = :n, species = :sp, breed = :br, "
                "birth_date = :bd, weight_kg = :w, life_stage = :ls, "
                "onboarding_pending = :op WHERE pet_id = :pid AND tenant_id = :tid"
            ),
            {
                "pid": pet_id, "tid": tenant_id, "oid": payload.owner_id,
                "n": _nullable_text(payload.name), "sp": species, "br": breed,
                "bd": payload.birth_date, "w": payload.weight_kg, "ls": payload.life_stage,
                "op": onboarding_pending,
            },
        )
        conn.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="宠物不存在")
    return get_pet(pet_id, tenant_id)


@pets_router.delete("/{pet_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_pet(pet_id: str, tenant_id: str = Depends(require_admin_tenant)) -> None:
    engine = create_db_engine()
    with engine.connect() as conn:
        conn.execute(text("SELECT set_config('app.current_tenant', :tid, true)"), {"tid": tenant_id})
        conn.execute(text("BEGIN"))
        result = conn.execute(
            text("DELETE FROM pets WHERE pet_id = :pid AND tenant_id = :tid"),
            {"tid": tenant_id, "pid": pet_id},
        )
        conn.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="宠物不存在")


router.include_router(pets_router)


# --------------------------------------------------------------------------- #
# Appointments 资源
# --------------------------------------------------------------------------- #
appointments_router = APIRouter(prefix="/appointments", tags=["admin-appointments"], dependencies=[Depends(get_current_token)])


@appointments_router.get("", response_model=PageResp[AppointmentOut])
def list_appointments(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    status_filter: str | None = Query(None, alias="status"),
    customer_id: str | None = Query(None),
    tenant_id: str = Depends(require_admin_tenant),
):
    engine = create_db_engine()
    offset = (page - 1) * page_size
    where = ["tenant_id = :tid"]
    params: dict[str, object] = {"tid": tenant_id, "limit": page_size, "offset": offset}
    if status_filter:
        where.append("status = :status")
        params["status"] = status_filter
    if customer_id:
        where.append("customer_id = :cid")
        params["cid"] = customer_id
    where_sql = " AND ".join(where)
    with engine.connect() as conn:
        conn.execute(text("SELECT set_config('app.current_tenant', :tid, true)"), {"tid": tenant_id})
        conn.execute(text("BEGIN"))
        rows = conn.execute(
            text(
                f"SELECT appointment_id, customer_id, pet_id, service_type, start_at, "
                f"end_at, resource_id, status, source FROM appointments "
                f"WHERE {where_sql} ORDER BY start_at DESC LIMIT :limit OFFSET :offset"
            ),
            params,
        ).fetchall()
        total = conn.execute(
            text(f"SELECT COUNT(*) FROM appointments WHERE {where_sql}"), params
        ).scalar_one()
    from app.api.admin_schemas import AppointmentOut

    items = [
        AppointmentOut(
            appointment_id=r.appointment_id, customer_id=r.customer_id, pet_id=r.pet_id,
            service_type=r.service_type, start_at=r.start_at, end_at=r.end_at,
            resource_id=r.resource_id, status=r.status, source=r.source,
        )
        for r in rows
    ]
    return PageResp(items=items, total=total, page=page, page_size=page_size)


@appointments_router.get("/{appointment_id}", response_model=AppointmentOut)
def get_appointment(appointment_id: str, tenant_id: str = Depends(require_admin_tenant)):
    from app.api.admin_schemas import AppointmentOut
    engine = create_db_engine()
    with engine.connect() as conn:
        conn.execute(text("SELECT set_config('app.current_tenant', :tid, true)"), {"tid": tenant_id})
        conn.execute(text("BEGIN"))
        row = conn.execute(
            text(
                "SELECT appointment_id, customer_id, pet_id, service_type, start_at, "
                "end_at, resource_id, status, source FROM appointments "
                "WHERE appointment_id = :aid"
            ),
            {"tid": tenant_id, "aid": appointment_id},
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="预约不存在")
    return AppointmentOut(
        appointment_id=row.appointment_id, customer_id=row.customer_id, pet_id=row.pet_id,
        service_type=row.service_type, start_at=row.start_at, end_at=row.end_at,
        resource_id=row.resource_id, status=row.status, source=row.source,
    )


@appointments_router.post("", response_model=AppointmentOut, status_code=201)
def create_appointment(payload: AppointmentIn, tenant_id: str = Depends(require_admin_tenant)) -> AppointmentOut:
    appointment_id = f"appt-{uuid.uuid4().hex[:12]}"
    engine = create_db_engine()
    with engine.connect() as conn:
        conn.execute(text("SELECT set_config('app.current_tenant', :tid, true)"), {"tid": tenant_id})
        conn.execute(text("BEGIN"))
        conn.execute(
            text(
                "INSERT INTO appointments (appointment_id, tenant_id, customer_id, pet_id, "
                "service_type, start_at, end_at, resource_id, status, source, created_at) "
                "VALUES (:aid, :tid, :cid, :pid, :st, :sa, :ea, :rid, 'pending', 'admin', NOW())"
            ),
            {
                "aid": appointment_id, "tid": tenant_id, "cid": payload.customer_id,
                "pid": payload.pet_id, "st": payload.service_type,
                "sa": payload.start_at, "ea": payload.end_at, "rid": payload.resource_id,
            },
        )
        conn.commit()
    return AppointmentOut(
        appointment_id=appointment_id, customer_id=payload.customer_id, pet_id=payload.pet_id,
        service_type=payload.service_type, start_at=payload.start_at, end_at=payload.end_at,
        resource_id=payload.resource_id, status="pending", source="admin",
    )


@appointments_router.put("/{appointment_id}", response_model=AppointmentOut)
def update_appointment(appointment_id: str, payload: AppointmentUpdateIn, tenant_id: str = Depends(require_admin_tenant)) -> AppointmentOut:
    return get_appointment(appointment_id, tenant_id)


@appointments_router.delete("/{appointment_id}", status_code=204)
def cancel_appointment(appointment_id: str, tenant_id: str = Depends(require_admin_tenant)) -> None:
    """取消预约：把 status 改为 cancelled（不真删）。"""
    engine = create_db_engine()
    with engine.connect() as conn:
        conn.execute(text("SELECT set_config('app.current_tenant', :tid, true)"), {"tid": tenant_id})
        conn.execute(text("BEGIN"))
        result = conn.execute(
            text(
                "UPDATE appointments SET status = 'cancelled' "
                "WHERE appointment_id = :aid AND status IN ('pending', 'confirmed')"
            ),
            {"tid": tenant_id, "aid": appointment_id},
        )
        conn.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="预约不存在或已取消")


router.include_router(appointments_router)


# --------------------------------------------------------------------------- #
# Business Hours（配置类：仅 list + update）
# --------------------------------------------------------------------------- #
business_hours_router = APIRouter(prefix="/business-hours", tags=["admin-config"], dependencies=[Depends(get_current_token)])


@business_hours_router.get("", response_model=list[BusinessHourOut])
def list_business_hours(tenant_id: str = Depends(require_admin_tenant)):
    engine = create_db_engine()
    with engine.connect() as conn:
        conn.execute(text("SELECT set_config('app.current_tenant', :tid, true)"), {"tid": tenant_id})
        conn.execute(text("BEGIN"))
        rows = conn.execute(
            text(
                "SELECT weekday, open_time::text, close_time::text, is_closed "
                "FROM business_hours ORDER BY weekday"
            ),
            {"tid": tenant_id},
        ).fetchall()
    from app.api.admin_schemas import BusinessHourOut

    return [
        BusinessHourOut(
            weekday=r.weekday, open_time=r.open_time, close_time=r.close_time,
            is_closed=bool(r.is_closed),
        )
        for r in rows
    ]


@business_hours_router.put("/{weekday}", response_model=BusinessHourOut)
def update_business_hour(
    weekday: int,
    payload: BusinessHourIn,
    tenant_id: str = Depends(require_admin_tenant),
) -> BusinessHourOut:
    engine = create_db_engine()
    with engine.connect() as conn:
        conn.execute(text("SELECT set_config('app.current_tenant', :tid, true)"), {"tid": tenant_id})
        conn.execute(text("BEGIN"))
        conn.execute(
            text(
                "UPDATE business_hours SET open_time = :ot, close_time = :ct, "
                "is_closed = :ic WHERE weekday = :wd"
            ),
            {"ot": payload.open_time, "ct": payload.close_time,
             "ic": payload.is_closed, "wd": weekday, "tid": tenant_id},
        )
        conn.commit()
    return BusinessHourOut(
        weekday=weekday, open_time=payload.open_time, close_time=payload.close_time,
        is_closed=payload.is_closed,
    )


router.include_router(business_hours_router)


# --------------------------------------------------------------------------- #
# Resources（配置类：仅 list + update）
# --------------------------------------------------------------------------- #
resources_router = APIRouter(prefix="/resources", tags=["admin-config"], dependencies=[Depends(get_current_token)])


@resources_router.get("", response_model=list[ResourceOut])
def list_resources(tenant_id: str = Depends(require_admin_tenant)):
    engine = create_db_engine()
    with engine.connect() as conn:
        conn.execute(text("SELECT set_config('app.current_tenant', :tid, true)"), {"tid": tenant_id})
        conn.execute(text("BEGIN"))
        rows = conn.execute(
            text(
                "SELECT resource_id, name, capacity, active "
                "FROM grooming_resources ORDER BY resource_id"
            ),
            {"tid": tenant_id},
        ).fetchall()
    from app.api.admin_schemas import ResourceOut

    return [
        ResourceOut(
            resource_id=r.resource_id, name=r.name,
            capacity=int(r.capacity), is_active=bool(r.active),
        )
        for r in rows
    ]


@resources_router.put("/{resource_id}", response_model=ResourceOut)
def update_resource(resource_id: str, payload: ResourceIn, tenant_id: str = Depends(require_admin_tenant)) -> ResourceOut:
    engine = create_db_engine()
    with engine.connect() as conn:
        conn.execute(text("SELECT set_config('app.current_tenant', :tid, true)"), {"tid": tenant_id})
        conn.execute(text("BEGIN"))
        conn.execute(
            text(
                "UPDATE grooming_resources SET name = :n, capacity = :c, active = :ia "
                "WHERE resource_id = :rid"
            ),
            {"n": payload.name, "c": payload.capacity, "ia": payload.is_active,
             "rid": resource_id, "tid": tenant_id},
        )
        conn.commit()
    return ResourceOut(
        resource_id=resource_id, name=payload.name,
        capacity=payload.capacity, is_active=payload.is_active,
    )


router.include_router(resources_router)


# --------------------------------------------------------------------------- #
# Health（指标 + 告警）
# --------------------------------------------------------------------------- #
health_router = APIRouter(prefix="/health", tags=["admin-health"], dependencies=[Depends(get_current_token)])


@health_router.get("/metrics", response_model=PageResp[HealthMetricOut])
def list_health_metrics(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    pet_id: str | None = Query(None),
    tenant_id: str = Depends(require_admin_tenant),
):
    """健康指标列表：从 TimescaleDB 宽表 ``health_metrics`` 读取并展开为三条指标记录。

    ``health_metrics`` 是"一次体检 = 一行，含体重/活动量/进食量三列"的宽表（写入侧见
    :mod:`app.engines.health`），而非"一行一个指标"的窄表。之前的实现假设了不存在的
    ``metric_id``/``metric_type``/``value``/``source`` 列，导致线上 500
    （``UndefinedColumn``）。这里改为按分页读取宽表行，在应用层展开为三条
    :class:`~app.api.admin_schemas.HealthMetricOut`（体重 / 活动量 / 进食量各一条），
    保持前端既有的"指标列表"展示契约不变，同时避免迁移/改造 TimescaleDB 超表结构。
    """
    engine = create_db_engine()
    offset = (page - 1) * page_size
    where = ["tenant_id = :tid"]
    params: dict[str, object] = {"tid": tenant_id, "limit": page_size, "offset": offset}
    if pet_id:
        where.append("pet_id = :pid")
        params["pid"] = pet_id
    where_sql = " AND ".join(where)
    with engine.connect() as conn:
        conn.execute(text("SELECT set_config('app.current_tenant', :tid, true)"), {"tid": tenant_id})
        conn.execute(text("BEGIN"))
        rows = conn.execute(
            text(
                f"SELECT pet_id, ts, weight_kg, activity_minutes, food_intake_g "
                f"FROM health_metrics WHERE {where_sql} "
                f"ORDER BY ts DESC LIMIT :limit OFFSET :offset"
            ),
            params,
        ).fetchall()
        total_visits = conn.execute(
            text(f"SELECT COUNT(*) FROM health_metrics WHERE {where_sql}"), params
        ).scalar_one()
    from app.api.admin_schemas import HealthMetricOut

    items: list[HealthMetricOut] = []
    for r in rows:
        for metric_type, value in (
            ("weight_kg", r.weight_kg),
            ("activity_minutes", r.activity_minutes),
            ("food_intake_g", r.food_intake_g),
        ):
            items.append(
                HealthMetricOut(
                    metric_id=f"{r.pet_id}:{r.ts.isoformat()}:{metric_type}",
                    pet_id=r.pet_id,
                    metric_type=metric_type,
                    value=float(value),
                    recorded_at=r.ts,
                    source="timescale",
                )
            )
    # 每行体检记录展开为 3 条指标：total 按"指标条数"口径与 items 一致（而非体检次数）。
    return PageResp(items=items, total=int(total_visits) * 3, page=page, page_size=page_size)


@health_router.get("/alerts", response_model=list[HealthAlertOut])
def list_health_alerts(tenant_id: str = Depends(require_admin_tenant)):
    engine = create_db_engine()
    with engine.connect() as conn:
        conn.execute(text("SELECT set_config('app.current_tenant', :tid, true)"), {"tid": tenant_id})
        conn.execute(text("BEGIN"))
        rows = conn.execute(
            text(
                "SELECT alert_id, pet_id, level, title, message, created_at, acked_at "
                "FROM health_alerts ORDER BY created_at DESC LIMIT 200"
            ),
            {"tid": tenant_id},
        ).fetchall()
    from app.api.admin_schemas import HealthAlertOut

    return [
        HealthAlertOut(
            alert_id=r.alert_id, pet_id=r.pet_id, level=r.level,
            title=r.title, message=r.message,
            created_at=r.created_at, acked_at=r.acked_at,
        )
        for r in rows
    ]


@health_router.post("/alerts/{alert_id}/ack", status_code=204)
def ack_health_alert(alert_id: str, tenant_id: str = Depends(require_admin_tenant)) -> None:
    engine = create_db_engine()
    with engine.connect() as conn:
        conn.execute(text("SELECT set_config('app.current_tenant', :tid, true)"), {"tid": tenant_id})
        conn.execute(text("BEGIN"))
        conn.execute(
            text("UPDATE health_alerts SET acked_at = NOW() WHERE alert_id = :aid"),
            {"tid": tenant_id, "aid": alert_id},
        )
        conn.commit()


router.include_router(health_router)


# --------------------------------------------------------------------------- #
# Operations（LTV + 流失 + 客户特征）
# --------------------------------------------------------------------------- #
operations_router = APIRouter(prefix="/operations", tags=["admin-operations"], dependencies=[Depends(get_current_token)])


@operations_router.get("/ltv", response_model=list[LtvSegmentOut])
def ltv_by_segment(tenant_id: str = Depends(require_admin_tenant)):
    engine = create_db_engine()
    with engine.connect() as conn:
        conn.execute(text("SELECT set_config('app.current_tenant', :tid, true)"), {"tid": tenant_id})
        conn.execute(text("BEGIN"))
        rows = conn.execute(
            text(
                "SELECT COALESCE(segment, 'unknown') AS segment, "
                "COUNT(*) AS cnt, AVG(ltv) AS avg_ltv, SUM(ltv) AS total_ltv "
                "FROM customers WHERE deleted_at IS NULL AND ltv IS NOT NULL "
                "GROUP BY segment ORDER BY total_ltv DESC"
            ),
            {"tid": tenant_id},
        ).fetchall()
    from app.api.admin_schemas import LtvSegmentOut

    return [
        LtvSegmentOut(
            segment=r.segment, customer_count=int(r.cnt),
            avg_ltv=float(r.avg_ltv or 0), total_ltv=float(r.total_ltv or 0),
        )
        for r in rows
    ]


@operations_router.get("/churn", response_model=list[ChurnRiskOut])
def churn_risk_list(
    threshold: float = Query(0.5, ge=0.0, le=1.0),
    tenant_id: str = Depends(require_admin_tenant),
):
    engine = create_db_engine()
    with engine.connect() as conn:
        conn.execute(text("SELECT set_config('app.current_tenant', :tid, true)"), {"tid": tenant_id})
        conn.execute(text("BEGIN"))
        rows = conn.execute(
            text(
                "SELECT customer_id, name, churn_score, last_visit_at, total_visits "
                "FROM customers "
                "WHERE deleted_at IS NULL AND churn_score >= :threshold "
                "ORDER BY churn_score DESC LIMIT 200"
            ),
            {"tid": tenant_id, "threshold": threshold},
        ).fetchall()
    from app.api.admin_schemas import ChurnRiskOut

    return [
        ChurnRiskOut(
            customer_id=r.customer_id, name=r.name,
            churn_score=float(r.churn_score), last_visit_at=r.last_visit_at,
            total_visits=int(r.total_visits or 0),
        )
        for r in rows
    ]


@operations_router.get("/feature-vectors/{customer_id}", response_model=FeatureVectorOut)
def get_feature_vector(customer_id: str, tenant_id: str = Depends(require_admin_tenant)):
    """按客户查询已计算特征向量（``feature_vectors.entity_id`` 存的是 customer_id 或
    sku_id 的通用实体标识，见 :mod:`app.features.store`；本端点固定按客户特征组查询）。
    """
    from app.api.admin_schemas import FeatureVectorOut
    engine = create_db_engine()
    with engine.connect() as conn:
        conn.execute(text("SELECT set_config('app.current_tenant', :tid, true)"), {"tid": tenant_id})
        conn.execute(text("BEGIN"))
        row = conn.execute(
            text(
                "SELECT entity_id, features, computed_at "
                "FROM feature_vectors WHERE entity_id = :cid"
            ),
            {"tid": tenant_id, "cid": customer_id},
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="客户特征未计算")
    return FeatureVectorOut(
        customer_id=row.entity_id,
        features=dict(row.features or {}),
        computed_at=row.computed_at,
    )


router.include_router(operations_router)


# --------------------------------------------------------------------------- #
# Supply（SKU + 补货决策）
# --------------------------------------------------------------------------- #
supply_router = APIRouter(prefix="/supply", tags=["admin-supply"], dependencies=[Depends(get_current_token)])


@supply_router.get("/skus", response_model=PageResp[SkuOut])
def list_skus(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    search: str | None = Query(None),
    tenant_id: str = Depends(require_admin_tenant),
):
    engine = create_db_engine()
    offset = (page - 1) * page_size
    where = ["tenant_id = :tid"]
    params: dict[str, object] = {"tid": tenant_id, "limit": page_size, "offset": offset}
    if search:
        where.append("name ILIKE :s")
        params["s"] = f"%{search}%"
    where_sql = " AND ".join(where)
    with engine.connect() as conn:
        conn.execute(text("SELECT set_config('app.current_tenant', :tid, true)"), {"tid": tenant_id})
        conn.execute(text("BEGIN"))
        rows = conn.execute(
            text(
                f"SELECT sku_id, name, unit, current_stock, reorder_point, safety_stock "
                f"FROM skus WHERE {where_sql} ORDER BY sku_id LIMIT :limit OFFSET :offset"
            ),
            params,
        ).fetchall()
        total = conn.execute(
            text(f"SELECT COUNT(*) FROM skus WHERE {where_sql}"), params
        ).scalar_one()
    from app.api.admin_schemas import SkuOut

    items = [
        SkuOut(
            sku_id=r.sku_id, name=r.name, unit=r.unit,
            current_stock=float(r.current_stock), reorder_point=float(r.reorder_point),
            safety_stock=float(r.safety_stock),
        )
        for r in rows
    ]
    return PageResp(items=items, total=total, page=page, page_size=page_size)


@supply_router.put("/skus/{sku_id}", response_model=SkuOut)
def update_sku(sku_id: str, payload: SkuIn, tenant_id: str = Depends(require_admin_tenant)) -> SkuOut:
    engine = create_db_engine()
    with engine.connect() as conn:
        conn.execute(text("SELECT set_config('app.current_tenant', :tid, true)"), {"tid": tenant_id})
        conn.execute(text("BEGIN"))
        conn.execute(
            text(
                "UPDATE skus SET name = :n, unit = :u, current_stock = :cs, "
                "reorder_point = :rp, safety_stock = :ss WHERE sku_id = :sid"
            ),
            {"n": payload.name, "u": payload.unit, "cs": payload.current_stock,
             "rp": payload.reorder_point, "ss": payload.safety_stock,
             "sid": sku_id, "tid": tenant_id},
        )
        conn.commit()
    return SkuOut(
        sku_id=sku_id, name=payload.name, unit=payload.unit,
        current_stock=payload.current_stock, reorder_point=payload.reorder_point,
        safety_stock=payload.safety_stock,
    )


@supply_router.get("/restock-decisions", response_model=list[RestockDecisionOut])
def list_restock_decisions(tenant_id: str = Depends(require_admin_tenant)):
    engine = create_db_engine()
    with engine.connect() as conn:
        conn.execute(text("SELECT set_config('app.current_tenant', :tid, true)"), {"tid": tenant_id})
        conn.execute(text("BEGIN"))
        rows = conn.execute(
            text(
                "SELECT decision_id, sku_id, recommended_qty, urgency, created_at "
                "FROM restock_decisions WHERE status = 'open' "
                "ORDER BY created_at DESC LIMIT 200"
            ),
            {"tid": tenant_id},
        ).fetchall()
    from app.api.admin_schemas import RestockDecisionOut

    return [
        RestockDecisionOut(
            decision_id=r.decision_id, sku_id=r.sku_id,
            recommended_qty=float(r.recommended_qty), urgency=r.urgency,
            created_at=r.created_at,
        )
        for r in rows
    ]


router.include_router(supply_router)


# --------------------------------------------------------------------------- #
# Marketing（内容记录 + 手动触发）
# --------------------------------------------------------------------------- #
marketing_router = APIRouter(prefix="/marketing", tags=["admin-marketing"], dependencies=[Depends(get_current_token)])


@marketing_router.get("/contents", response_model=PageResp[MarketingContentOut])
def list_marketing_contents(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    status_filter: str | None = Query(None, alias="status"),
    tenant_id: str = Depends(require_admin_tenant),
):
    engine = create_db_engine()
    offset = (page - 1) * page_size
    where = ["tenant_id = :tid"]
    params: dict[str, object] = {"tid": tenant_id, "limit": page_size, "offset": offset}
    if status_filter:
        where.append("status = :status")
        params["status"] = status_filter
    where_sql = " AND ".join(where)
    with engine.connect() as conn:
        conn.execute(text("SELECT set_config('app.current_tenant', :tid, true)"), {"tid": tenant_id})
        conn.execute(text("BEGIN"))
        rows = conn.execute(
            text(
                f"SELECT content_id, topic, channel, body_preview, status, generated_at "
                f"FROM marketing_contents WHERE {where_sql} "
                f"ORDER BY generated_at DESC LIMIT :limit OFFSET :offset"
            ),
            params,
        ).fetchall()
        total = conn.execute(
            text(f"SELECT COUNT(*) FROM marketing_contents WHERE {where_sql}"), params
        ).scalar_one()
    from app.api.admin_schemas import MarketingContentOut

    items = [
        MarketingContentOut(
            content_id=r.content_id, topic=r.topic, channel=r.channel,
            body_preview=r.body_preview or "", status=r.status,
            generated_at=r.generated_at,
        )
        for r in rows
    ]
    return PageResp(items=items, total=total, page=page, page_size=page_size)


@marketing_router.post("/contents/generate", response_model=MarketingContentOut, status_code=201)
def generate_marketing_content(payload: MarketingContentGenerateIn, tenant_id: str = Depends(require_admin_tenant)) -> MarketingContentOut:
    """手动触发内容生成：调用 MarketingAgent 异步生成。"""
    content_id = f"mc-{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc)
    # MVP：写一条占位 draft 记录；真实生成应入 MarketingAgent 任务队列
    engine = create_db_engine()
    with engine.connect() as conn:
        conn.execute(text("SELECT set_config('app.current_tenant', :tid, true)"), {"tid": tenant_id})
        conn.execute(text("BEGIN"))
        conn.execute(
            text(
                "INSERT INTO marketing_contents "
                "(content_id, tenant_id, topic, channel, body_preview, status, generated_at) "
                "VALUES (:cid, :tid, :t, :c, '', 'draft', :now)"
            ),
            {"cid": content_id, "tid": tenant_id, "t": payload.topic,
             "c": payload.channel, "now": now},
        )
        conn.commit()
    return MarketingContentOut(
        content_id=content_id, topic=payload.topic, channel=payload.channel,
        body_preview="", status="draft", generated_at=now,
    )


router.include_router(marketing_router)


# --------------------------------------------------------------------------- #
# Subscriptions + Ecosystem
# --------------------------------------------------------------------------- #
subscriptions_router = APIRouter(prefix="/subscriptions", tags=["admin-subscriptions"], dependencies=[Depends(get_current_token)])


@subscriptions_router.get("", response_model=PageResp[SubscriptionOut])
def list_subscriptions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    tenant_id: str = Depends(require_admin_tenant),
):
    engine = create_db_engine()
    offset = (page - 1) * page_size
    with engine.connect() as conn:
        conn.execute(text("SELECT set_config('app.current_tenant', :tid, true)"), {"tid": tenant_id})
        conn.execute(text("BEGIN"))
        rows = conn.execute(
            text(
                "SELECT subscription_id, customer_id, plan_id, status, started_at, "
                "next_billing_at FROM subscriptions "
                "ORDER BY started_at DESC LIMIT :limit OFFSET :offset"
            ),
            {"tid": tenant_id, "limit": page_size, "offset": offset},
        ).fetchall()
        total = conn.execute(
            text("SELECT COUNT(*) FROM subscriptions"), {"tid": tenant_id}
        ).scalar_one()
    from app.api.admin_schemas import SubscriptionOut

    items = [
        SubscriptionOut(
            subscription_id=r.subscription_id, customer_id=r.customer_id,
            plan_id=r.plan_id, status=r.status, started_at=r.started_at,
            next_billing_at=r.next_billing_at,
        )
        for r in rows
    ]
    return PageResp(items=items, total=total, page=page, page_size=page_size)


@subscriptions_router.get("/{subscription_id}", response_model=SubscriptionOut)
def get_subscription(subscription_id: str, tenant_id: str = Depends(require_admin_tenant)):
    from app.api.admin_schemas import SubscriptionOut
    engine = create_db_engine()
    with engine.connect() as conn:
        conn.execute(text("SELECT set_config('app.current_tenant', :tid, true)"), {"tid": tenant_id})
        conn.execute(text("BEGIN"))
        row = conn.execute(
            text(
                "SELECT subscription_id, customer_id, plan_id, status, started_at, "
                "next_billing_at FROM subscriptions WHERE subscription_id = :sid"
            ),
            {"tid": tenant_id, "sid": subscription_id},
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="订阅不存在")
    return SubscriptionOut(
        subscription_id=row.subscription_id, customer_id=row.customer_id,
        plan_id=row.plan_id, status=row.status, started_at=row.started_at,
        next_billing_at=row.next_billing_at,
    )


@subscriptions_router.get("/billing-reports", response_model=list[BillingReportOut])
def list_billing_reports(
    month: str | None = Query(None, description="YYYY-MM"),
    tenant_id: str = Depends(require_admin_tenant),
):
    engine = create_db_engine()
    params: dict[str, object] = {"tid": tenant_id}
    where_sql = "tenant_id = :tid"
    if month:
        where_sql += " AND TO_CHAR(billing_month, 'YYYY-MM') = :month"
        params["month"] = month
    with engine.connect() as conn:
        conn.execute(text("SELECT set_config('app.current_tenant', :tid, true)"), {"tid": tenant_id})
        conn.execute(text("BEGIN"))
        rows = conn.execute(
            text(
                f"SELECT TO_CHAR(billing_month, 'YYYY-MM') AS month, "
                f"SUM(amount) AS total, "
                f"SUM(CASE WHEN status='paid' THEN 1 ELSE 0 END) AS paid_cnt, "
                f"SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed_cnt "
                f"FROM billing_records WHERE {where_sql} "
                f"GROUP BY month ORDER BY month DESC LIMIT 24"
            ),
            params,
        ).fetchall()
    from app.api.admin_schemas import BillingReportOut

    return [
        BillingReportOut(
            month=r.month, total_amount=float(r.total or 0),
            paid_count=int(r.paid_cnt or 0), failed_count=int(r.failed_cnt or 0),
        )
        for r in rows
    ]


router.include_router(subscriptions_router)


# --------------------------------------------------------------------------- #
# Ecosystem（合作医院 + 转诊）
# --------------------------------------------------------------------------- #
ecosystem_router = APIRouter(prefix="/ecosystem", tags=["admin-ecosystem"], dependencies=[Depends(get_current_token)])


@ecosystem_router.get("/partners", response_model=list[PartnerHospitalOut])
def list_partners(tenant_id: str = Depends(require_admin_tenant)):
    engine = create_db_engine()
    with engine.connect() as conn:
        conn.execute(text("SELECT set_config('app.current_tenant', :tid, true)"), {"tid": tenant_id})
        conn.execute(text("BEGIN"))
        rows = conn.execute(
            text(
                "SELECT partner_id, name, address, phone, specialties "
                "FROM partner_hospitals ORDER BY partner_id"
            ),
            {"tid": tenant_id},
        ).fetchall()
    from app.api.admin_schemas import PartnerHospitalOut

    return [
        PartnerHospitalOut(
            partner_id=r.partner_id, name=r.name, address=r.address, phone=r.phone,
            specialties=list(r.specialties or []),
        )
        for r in rows
    ]


@ecosystem_router.get("/referrals", response_model=PageResp[ReferralOut])
def list_referrals(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    status_filter: str | None = Query(None, alias="status"),
    tenant_id: str = Depends(require_admin_tenant),
):
    engine = create_db_engine()
    offset = (page - 1) * page_size
    where = ["tenant_id = :tid"]
    params: dict[str, object] = {"tid": tenant_id, "limit": page_size, "offset": offset}
    if status_filter:
        where.append("status = :status")
        params["status"] = status_filter
    where_sql = " AND ".join(where)
    with engine.connect() as conn:
        conn.execute(text("SELECT set_config('app.current_tenant', :tid, true)"), {"tid": tenant_id})
        conn.execute(text("BEGIN"))
        rows = conn.execute(
            text(
                f"SELECT referral_id, customer_id, pet_id, partner_id, status, created_at "
                f"FROM referrals WHERE {where_sql} "
                f"ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
            ),
            params,
        ).fetchall()
        total = conn.execute(
            text(f"SELECT COUNT(*) FROM referrals WHERE {where_sql}"), params
        ).scalar_one()
    from app.api.admin_schemas import ReferralOut

    items = [
        ReferralOut(
            referral_id=r.referral_id, customer_id=r.customer_id, pet_id=r.pet_id,
            partner_id=r.partner_id, status=r.status, created_at=r.created_at,
        )
        for r in rows
    ]
    return PageResp(items=items, total=total, page=page, page_size=page_size)


router.include_router(ecosystem_router)


# --------------------------------------------------------------------------- #
# Traces（Agent 对话追溯）
# --------------------------------------------------------------------------- #
traces_router = APIRouter(prefix="/traces", tags=["admin-traces"], dependencies=[Depends(get_current_token)])


@traces_router.get("", response_model=PageResp[TraceOut])
def list_traces(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    tenant_id: str = Depends(require_admin_tenant),
):
    """Agent 对话追溯列表：从进程内 trace backend 拉取。"""
    from app.observability.tracing import InMemoryTracingBackend

    backend = InMemoryTracingBackend()
    traces = list(backend.recent(limit=page * page_size))
    total = len(traces)
    start = (page - 1) * page_size
    items = [
        TraceOut(
            trace_id=t.trace_id, thread_id=t.session_id or "",
            started_at=t.started_at, ended_at=t.ended_at,
            status="completed" if t.ended_at else "running",
            final_answer=getattr(t, "output", None),
        )
        for t in traces[start:start + page_size]
    ]
    return PageResp(items=items, total=total, page=page, page_size=page_size)


@traces_router.get("/{thread_id}", response_model=TraceDetailOut)
def get_trace_detail(thread_id: str, tenant_id: str = Depends(require_admin_tenant)):
    from app.observability.tracing import InMemoryTracingBackend

    backend = InMemoryTracingBackend()
    for t in backend.recent(limit=500):
        if t.session_id == thread_id:
            return TraceDetailOut(
                trace_id=t.trace_id, thread_id=thread_id,
                started_at=t.started_at, ended_at=t.ended_at,
                status="completed" if t.ended_at else "running",
                final_answer=getattr(t, "output", None),
                steps=[{"event": "request_input", "value": getattr(t, "request_input", "")}],
            )
    raise HTTPException(status_code=404, detail="未找到该 thread")


router.include_router(traces_router)


# --------------------------------------------------------------------------- #
# Dashboard 聚合统计
# --------------------------------------------------------------------------- #
@router.get("/stats/overview", response_model=OverviewStats)
def stats_overview(tenant_id: str = Depends(require_admin_tenant)):
    engine = create_db_engine()
    with engine.connect() as conn:
        conn.execute(text("SELECT set_config('app.current_tenant', :tid, true)"), {"tid": tenant_id})
        conn.execute(text("BEGIN"))
        today_appts = conn.execute(
            text(
                "SELECT COUNT(*) FROM appointments "
                "WHERE start_at::date = CURRENT_DATE AND status NOT IN ('cancelled')"
            ),
            {"tid": tenant_id},
        ).scalar_one()
        new_custs = conn.execute(
            text(
                "SELECT COUNT(*) FROM customers "
                "WHERE registered_at::date = CURRENT_DATE AND deleted_at IS NULL"
            ),
            {"tid": tenant_id},
        ).scalar_one()
        pending_alerts = conn.execute(
            text("SELECT COUNT(*) FROM health_alerts WHERE acked_at IS NULL"),
            {"tid": tenant_id},
        ).scalar_one()
        low_stock = conn.execute(
            text(
                "SELECT COUNT(*) FROM skus "
                "WHERE current_stock < safety_stock"
            ),
            {"tid": tenant_id},
        ).scalar_one()
        revenue = conn.execute(
            text(
                "SELECT COALESCE(SUM(amount), 0) FROM billing_records "
                "WHERE billing_month = DATE_TRUNC('month', CURRENT_DATE)::date "
                "AND status = 'paid'"
            ),
            {"tid": tenant_id},
        ).scalar_one()
    return OverviewStats(
        today_appointments=int(today_appts),
        today_new_customers=int(new_custs),
        pending_alerts=int(pending_alerts),
        low_stock_skus=int(low_stock),
        recent_revenue=float(revenue),
    )


@router.get("/stats/trends", response_model=TrendsOut)
def stats_trends(
    days: int = Query(7, ge=1, le=90), tenant_id: str = Depends(require_admin_tenant)
) -> TrendsOut:
    """最近 N 天每日预约数 / 新增客户数 / 健康告警数，供仪表盘 KPI 卡片画 sparkline。

    按日聚合，缺失的日期补 0（避免前端画趋势图时因为某天无数据而断线）。
    """
    engine = create_db_engine()
    with engine.connect() as conn:
        conn.execute(text("SELECT set_config('app.current_tenant', :tid, true)"), {"tid": tenant_id})
        conn.execute(text("BEGIN"))
        appt_rows = conn.execute(
            text(
                "SELECT start_at::date AS d, COUNT(*) AS cnt FROM appointments "
                "WHERE start_at >= CURRENT_DATE - (:days - 1) "
                "AND status NOT IN ('cancelled') GROUP BY d"
            ),
            {"tid": tenant_id, "days": days},
        ).fetchall()
        cust_rows = conn.execute(
            text(
                "SELECT registered_at::date AS d, COUNT(*) AS cnt FROM customers "
                "WHERE registered_at >= CURRENT_DATE - (:days - 1) "
                "AND deleted_at IS NULL GROUP BY d"
            ),
            {"tid": tenant_id, "days": days},
        ).fetchall()
        alert_rows = conn.execute(
            text(
                "SELECT created_at::date AS d, COUNT(*) AS cnt FROM health_alerts "
                "WHERE created_at >= CURRENT_DATE - (:days - 1) GROUP BY d"
            ),
            {"tid": tenant_id, "days": days},
        ).fetchall()

    appt_by_day = {r.d.isoformat(): int(r.cnt) for r in appt_rows}
    cust_by_day = {r.d.isoformat(): int(r.cnt) for r in cust_rows}
    alert_by_day = {r.d.isoformat(): int(r.cnt) for r in alert_rows}

    today = datetime.now(timezone.utc).date()
    points = []
    for offset in range(days - 1, -1, -1):
        day = (today - timedelta(days=offset)).isoformat()
        points.append(
            DailyTrendPoint(
                date=day,
                appointments=appt_by_day.get(day, 0),
                new_customers=cust_by_day.get(day, 0),
                health_alerts=alert_by_day.get(day, 0),
            )
        )
    return TrendsOut(points=points)


@router.get("/stats/todos", response_model=list[TodoOut])
def stats_todos(tenant_id: str = Depends(require_admin_tenant)) -> list[TodoOut]:
    """今日待办：待确认预约 / 待处理健康告警 / 待完善档案，供仪表盘首页面板展示。

    每项均带 ``link``（含查询参数预筛选），前端点击直达对应列表并已按该待办条件过滤。
    """
    engine = create_db_engine()
    with engine.connect() as conn:
        conn.execute(text("SELECT set_config('app.current_tenant', :tid, true)"), {"tid": tenant_id})
        conn.execute(text("BEGIN"))
        pending_appts = conn.execute(
            text("SELECT COUNT(*) FROM appointments WHERE status = 'pending'"),
            {"tid": tenant_id},
        ).scalar_one()
        unacked_alerts = conn.execute(
            text("SELECT COUNT(*) FROM health_alerts WHERE acked_at IS NULL"),
            {"tid": tenant_id},
        ).scalar_one()
        pending_customers = conn.execute(
            text(
                "SELECT COUNT(*) FROM customers "
                "WHERE onboarding_pending = TRUE AND deleted_at IS NULL"
            ),
            {"tid": tenant_id},
        ).scalar_one()
        pending_pets = conn.execute(
            text("SELECT COUNT(*) FROM pets WHERE onboarding_pending = TRUE"),
            {"tid": tenant_id},
        ).scalar_one()
    return [
        TodoOut(
            key="pending_appointments",
            label="待确认预约",
            count=int(pending_appts),
            link="/appointments?status=pending",
        ),
        TodoOut(
            key="unacked_alerts",
            label="待处理健康告警",
            count=int(unacked_alerts),
            link="/health/alerts",
        ),
        TodoOut(
            key="pending_customers",
            label="待完善客户档案",
            count=int(pending_customers),
            link="/customers?onboarding_pending=true",
        ),
        TodoOut(
            key="pending_pets",
            label="待完善宠物档案",
            count=int(pending_pets),
            link="/pets?onboarding_pending=true",
        ),
    ]
