"""时序 / 事件 / 向量数据模型（对应设计文档 Data Models 4.2）。

包含 `HealthMetric`（TimescaleDB 超表）、`DomainEvent`（事件总线消息）、
`KnowledgeChunk`（pgvector 片段）、`FeatureVector`（特征存储）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from app.models.base import NonBlankStr, PetOpsModel, TenantId


class HealthMetric(PetOpsModel):
    """健康时序指标，写入 TimescaleDB 超表（hypertable）。

    `weight_kg > 0`；活动时长与进食量非负。
    """

    pet_id: NonBlankStr
    tenant_id: TenantId
    ts: datetime
    weight_kg: float = Field(gt=0.0)
    activity_minutes: float = Field(ge=0.0)
    food_intake_g: float = Field(ge=0.0)


class DomainEvent(PetOpsModel):
    """事件总线消息（Redis Stream → Kafka）。"""

    event_id: NonBlankStr
    tenant_id: TenantId
    event_type: NonBlankStr  # health_alert / coupon_issued / ...
    payload: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime


class KnowledgeChunk(PetOpsModel):
    """pgvector 存储的知识 / 问答 / 病例片段。

    `tenant_id` 为 None 表示平台级共享知识，可被所有租户检索。
    """

    chunk_id: NonBlankStr
    tenant_id: TenantId | None = None
    content: NonBlankStr
    embedding: list[float]  # pgvector vector 类型
    source_type: str  # care_qa / case / marketing


class FeatureVector(PetOpsModel):
    """特征存储：LTV / churn / demand 共享特征。"""

    entity_id: NonBlankStr  # customer_id 或 sku_id
    tenant_id: TenantId
    feature_group: NonBlankStr
    features: dict[str, float] = Field(default_factory=dict)
    computed_at: datetime
