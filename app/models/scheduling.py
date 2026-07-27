"""企业微信预约模块数据模型（对应设计文档 Data Models 14.4）。

包含服务类型/状态枚举、营业时间、洗护资源、时段容量视图、预约记录，
以及接待预约 Agent 相关的意图/请求/结果对象。

校验规则（与设计 14.4「校验规则」一致）：
- 所有实体携带非空 ``tenant_id``（复用 ``TenantId``，经既有 RLS 上下文校验）。
- ``TimeSlot``：``capacity ≥ 0``、``0 ≤ booked_count ≤ capacity``、``start_at < end_at``。
- ``Appointment``：``start_at < end_at``；``status ∈ AppointmentStatus``。
- ``BusinessHours``：``open_time < close_time``。
- ``BookingIntent.confidence ∈ [0, 1]``。
"""

from __future__ import annotations

from datetime import datetime, time
from enum import Enum

from pydantic import Field, model_validator

from app.models.base import NonBlankStr, PetOpsModel, TenantId


class ServiceType(str, Enum):
    """可预约的服务类型（本模块主场景为洗护）。"""

    GROOMING = "grooming"          # 洗护 / 洗澡
    MEDICAL_BATH = "medical_bath"  # 药浴


class AppointmentStatus(str, Enum):
    """预约状态。"""

    PENDING = "pending"      # 待确认（转 HITL 时）
    CONFIRMED = "confirmed"  # 已确认（自动或人工批准后）
    CANCELLED = "cancelled"
    COMPLETED = "completed"


class BusinessHours(PetOpsModel):
    """门店营业时间（按星期）。

    约束：``open_time < close_time``。
    """

    tenant_id: TenantId
    weekday: int = Field(ge=0, le=6)  # 0=周一 … 6=周日
    open_time: time
    close_time: time

    @model_validator(mode="after")
    def _check_time_window(self) -> "BusinessHours":
        if self.open_time >= self.close_time:
            raise ValueError("open_time 必须早于 close_time")
        return self


class GroomingResource(PetOpsModel):
    """洗护资源（工位/店员），容量 = 同一时段可并行服务的资源数。"""

    resource_id: NonBlankStr
    tenant_id: TenantId
    name: NonBlankStr
    service_type: ServiceType
    active: bool = True


class TimeSlot(PetOpsModel):
    """一个时段的容量视图。

    约束：``capacity ≥ 0``、``0 ≤ booked_count ≤ capacity``、``start_at < end_at``。
    """

    tenant_id: TenantId
    service_type: ServiceType
    start_at: datetime
    end_at: datetime
    capacity: int = Field(ge=0)
    booked_count: int = Field(ge=0)

    @model_validator(mode="after")
    def _check_slot(self) -> "TimeSlot":
        if self.start_at >= self.end_at:
            raise ValueError("start_at 必须早于 end_at")
        if self.booked_count > self.capacity:
            raise ValueError("booked_count 不能超过 capacity")
        return self

    @property
    def available(self) -> int:
        """剩余容量 = capacity - booked_count，保证 ≥ 0。"""
        return max(self.capacity - self.booked_count, 0)


class Appointment(PetOpsModel):
    """预约记录（写入 appointments 表，启用 RLS）。

    约束：``start_at < end_at``。
    """

    appointment_id: NonBlankStr
    tenant_id: TenantId  # RLS 隔离键，非空
    customer_id: NonBlankStr
    pet_id: NonBlankStr
    service_type: ServiceType
    start_at: datetime
    end_at: datetime
    resource_id: str | None = None  # 分配的工位/店员
    status: AppointmentStatus
    source: str = "wecom"  # 来源渠道
    created_at: datetime

    @model_validator(mode="after")
    def _check_time_window(self) -> "Appointment":
        if self.start_at >= self.end_at:
            raise ValueError("start_at 必须早于 end_at")
        return self


class BookingIntent(PetOpsModel):
    """Cloud_LLM 从对话抽取的预约意图（NLU 输出）。

    约束：``confidence ∈ [0, 1]``。此对象为 NLU 输出，租户隔离由生成它的
    调用上下文（RLS 内的工具层）保证，故本身不携带 ``tenant_id``。
    """

    service_type: ServiceType | None = None
    pet_ref: str | None = None       # 客户对宠物的指代（"我家狗狗"）
    pet_id: str | None = None        # 消解后的宠物标识
    requested_start: datetime | None = None
    requested_end: datetime | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    ambiguous: bool  # 槽位不完整/歧义（多宠物、时间模糊等）


class BookingRequest(PetOpsModel):
    """接待预约 Agent 的下单请求。"""

    tenant_id: TenantId
    customer_id: NonBlankStr
    pet_id: NonBlankStr
    service_type: ServiceType
    start_at: datetime
    end_at: datetime

    @model_validator(mode="after")
    def _check_time_window(self) -> "BookingRequest":
        if self.start_at >= self.end_at:
            raise ValueError("start_at 必须早于 end_at")
        return self


class BookingOutcome(PetOpsModel):
    """接待预约 Agent 的处理结果。

    ``BookingOutcome`` 为处理结果对象，其租户隔离由内部的 ``appointment`` /
    时段列表承载，本身不携带 ``tenant_id``。
    """

    status: str  # booked / full / needs_hitl / needs_clarification / rejected
    appointment: Appointment | None = None
    alternatives: list[TimeSlot] = Field(default_factory=list)   # 满档时的备选建议
    current_schedule: list[TimeSlot] = Field(default_factory=list)  # 满档时的排期现状
    reply_text: str  # 面向客户的企业微信回复文案
