"""核心 Pydantic 数据模型（租户、客户、宠物、健康、订阅、供应链等）。

按设计文档 "Data Models" 分节组织：
- ``entities``   : 多租户与核心实体（Tenant / Customer / LifeStage / Pet）。
- ``timeseries`` : 时序 / 事件 / 向量（HealthMetric / DomainEvent / KnowledgeChunk / FeatureVector）。
- ``commerce``   : 订阅与供应链（Subscription / SKU / DemandForecast）。

统一从本包顶层导入，例如::

    from app.models import Customer, Pet, LifeStage
"""

from app.models.base import (
    NonBlankStr,
    PastDatetime,
    PetOpsModel,
    TenantId,
)
from app.models.commerce import SKU, DemandForecast, Subscription
from app.models.entities import Customer, LifeStage, Pet, Tenant
from app.models.scheduling import (
    Appointment,
    AppointmentStatus,
    BookingIntent,
    BookingOutcome,
    BookingRequest,
    BusinessHours,
    GroomingResource,
    ServiceType,
    TimeSlot,
)
from app.models.timeseries import (
    DomainEvent,
    FeatureVector,
    HealthMetric,
    KnowledgeChunk,
)

__all__ = [
    # base / 复用类型
    "PetOpsModel",
    "NonBlankStr",
    "TenantId",
    "PastDatetime",
    # 4.1 核心实体
    "Tenant",
    "Customer",
    "LifeStage",
    "Pet",
    # 4.2 时序 / 事件 / 向量
    "HealthMetric",
    "DomainEvent",
    "KnowledgeChunk",
    "FeatureVector",
    # 4.3 订阅与供应链
    "Subscription",
    "SKU",
    "DemandForecast",
    # 14.4 预约模块（企业微信洗护预约）
    "ServiceType",
    "AppointmentStatus",
    "BusinessHours",
    "GroomingResource",
    "TimeSlot",
    "Appointment",
    "BookingIntent",
    "BookingRequest",
    "BookingOutcome",
]
