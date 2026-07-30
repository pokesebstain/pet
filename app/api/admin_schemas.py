"""Admin Dashboard 通用 Pydantic 模式（请求 / 响应 / 分页）。"""
from __future__ import annotations

from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PageResp(BaseModel, Generic[T]):
    """分页响应统一格式：``items`` + 元信息。"""

    items: list[T]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=200)


class PageReq(BaseModel):
    """分页请求参数（Query 注入用）。"""

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=200)


class CustomerOut(BaseModel):
    customer_id: str
    name: str
    phone: str | None
    registered_at: datetime
    ltv: float | None
    churn_score: float | None
    segment: str | None
    onboarding_pending: bool
    deleted_at: datetime | None  # 软删字段：DB 迁移阶段加
    pet_count: int = Field(default=0, ge=0)


class CustomerIn(BaseModel):
    name: str
    phone: str | None = None


class PetOut(BaseModel):
    pet_id: str
    owner_id: str
    name: str | None
    # 公众号渐进式建档允许物种/品种暂缺（Requirement 26.5），此处必须与数据库可空列
    # 及 app.models.entities.Pet 保持一致，否则待完善档案的宠物会在序列化时报错。
    species: str | None
    breed: str | None
    birth_date: datetime | None
    weight_kg: float | None
    life_stage: str | None
    onboarding_pending: bool


class PetIn(BaseModel):
    owner_id: str
    name: str | None = None
    species: str | None = None
    breed: str | None = None
    birth_date: datetime | None = None
    weight_kg: float | None = None
    life_stage: str | None = None


# 补充缺失的 In 模型（创建 / 更新请求体）
class AppointmentUpdateIn(BaseModel):
    """Appointment PUT 请求体（与 AppointmentIn 字段一致）。"""
    customer_id: str
    pet_id: str
    service_type: str
    start_at: datetime
    end_at: datetime
    resource_id: str | None = None


class BusinessHourIn(BaseModel):
    open_time: str  # HH:MM
    close_time: str  # HH:MM
    is_closed: bool = False


class ResourceIn(BaseModel):
    name: str
    capacity: int
    is_active: bool = True


class SkuIn(BaseModel):
    name: str
    unit: str
    current_stock: float
    reorder_point: float
    safety_stock: float


class MarketingContentGenerateIn(BaseModel):
    topic: str
    channel: str


# --------------------------------------------------------------------------- #
# Appointments
# --------------------------------------------------------------------------- #
class AppointmentOut(BaseModel):
    appointment_id: str
    customer_id: str
    pet_id: str
    service_type: str
    start_at: datetime
    end_at: datetime
    resource_id: str | None
    status: str
    source: str


class AppointmentIn(BaseModel):
    customer_id: str
    pet_id: str
    service_type: str
    start_at: datetime
    end_at: datetime
    resource_id: str | None = None


# --------------------------------------------------------------------------- #
# Business Hours + Resources（配置类）
# --------------------------------------------------------------------------- #
class BusinessHourOut(BaseModel):
    weekday: int  # 0-6
    open_time: str  # HH:MM
    close_time: str  # HH:MM
    is_closed: bool = False


class BusinessHourIn(BaseModel):
    open_time: str
    close_time: str
    is_closed: bool = False


class ResourceOut(BaseModel):
    resource_id: str
    name: str
    capacity: int
    is_active: bool = True


class ResourceIn(BaseModel):
    name: str
    capacity: int
    is_active: bool = True


# --------------------------------------------------------------------------- #
# Health
# --------------------------------------------------------------------------- #
class HealthMetricOut(BaseModel):
    metric_id: str
    pet_id: str
    metric_type: str
    value: float
    recorded_at: datetime
    source: str | None = None


class HealthAlertOut(BaseModel):
    alert_id: str
    pet_id: str
    level: str  # info / warn / critical
    title: str
    message: str
    created_at: datetime
    acked_at: datetime | None = None


# --------------------------------------------------------------------------- #
# Operations
# --------------------------------------------------------------------------- #
class LtvSegmentOut(BaseModel):
    segment: str
    customer_count: int
    avg_ltv: float
    total_ltv: float


class ChurnRiskOut(BaseModel):
    customer_id: str
    name: str
    churn_score: float
    last_visit_at: datetime | None
    total_visits: int


class FeatureVectorOut(BaseModel):
    customer_id: str
    features: dict[str, float]
    computed_at: datetime


# --------------------------------------------------------------------------- #
# Supply
# --------------------------------------------------------------------------- #
class SkuOut(BaseModel):
    sku_id: str
    name: str
    unit: str
    current_stock: float
    reorder_point: float
    safety_stock: float


class SkuIn(BaseModel):
    name: str
    unit: str
    current_stock: float
    reorder_point: float
    safety_stock: float


class RestockDecisionOut(BaseModel):
    decision_id: str
    sku_id: str
    recommended_qty: float
    urgency: str  # low / medium / high
    created_at: datetime


# --------------------------------------------------------------------------- #
# Marketing
# --------------------------------------------------------------------------- #
class MarketingContentOut(BaseModel):
    content_id: str
    topic: str
    channel: str
    body_preview: str
    status: str  # draft / approved / sent
    generated_at: datetime


class MarketingContentGenerateIn(BaseModel):
    topic: str
    channel: str


# --------------------------------------------------------------------------- #
# Subscriptions + Ecosystem
# --------------------------------------------------------------------------- #
class SubscriptionOut(BaseModel):
    subscription_id: str
    customer_id: str
    plan_id: str
    status: str  # active / paused / cancelled
    started_at: datetime
    next_billing_at: datetime | None


class BillingReportOut(BaseModel):
    month: str  # YYYY-MM
    total_amount: float
    paid_count: int
    failed_count: int


class PartnerHospitalOut(BaseModel):
    partner_id: str
    name: str
    address: str
    phone: str
    specialties: list[str]


class ReferralOut(BaseModel):
    referral_id: str
    customer_id: str
    pet_id: str
    partner_id: str
    status: str  # pending / approved / rejected / completed
    created_at: datetime


# --------------------------------------------------------------------------- #
# Traces
# --------------------------------------------------------------------------- #
class TraceOut(BaseModel):
    trace_id: str
    thread_id: str
    started_at: datetime
    ended_at: datetime | None
    status: str  # running / completed / error
    final_answer: str | None = None


class TraceDetailOut(TraceOut):
    steps: list[dict] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Dashboard
# --------------------------------------------------------------------------- #
class OverviewStats(BaseModel):
    today_appointments: int = 0
    today_new_customers: int = 0
    pending_alerts: int = 0
    low_stock_skus: int = 0
    recent_revenue: float = 0.0


class DailyTrendPoint(BaseModel):
    """仪表盘 KPI 卡片迷你趋势图的单日数据点。"""

    date: str  # YYYY-MM-DD
    appointments: int = 0
    new_customers: int = 0
    health_alerts: int = 0


class TrendsOut(BaseModel):
    """最近 N 天的每日趋势序列，供仪表盘 KPI 卡片绘制 sparkline。"""

    points: list[DailyTrendPoint] = Field(default_factory=list)


class TodoOut(BaseModel):
    """仪表盘"今日待办"面板的单个分类计数，点击跳转对应列表并预筛选。"""

    key: str  # 前端路由跳转标识，如 "pending_appointments"
    label: str
    count: int
    link: str  # 跳转路径（含查询参数预筛选）
