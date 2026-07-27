"""多租户与核心实体模型（对应设计文档 Data Models 4.1）。

包含 `Tenant`、`Customer`、`LifeStage`、`Pet`。
校验规则：`churn_score ∈ [0, 1]`、`ltv ≥ 0`、`weight_kg > 0`、`birth_date ≤ 当前时间`、
所有实体携带非空 `tenant_id`。
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import Field

from app.models.base import NonBlankStr, PastDatetime, PetOpsModel, TenantId


class Tenant(PetOpsModel):
    """租户（门店），`tenant_id` 为 RLS 隔离键。"""

    tenant_id: TenantId
    store_name: NonBlankStr
    plan_tier: str
    created_at: datetime


class Customer(PetOpsModel):
    """客户实体。

    `ltv ≥ 0`、`churn_score ∈ [0, 1]`（二者可为 None 表示尚未计算）。
    """

    customer_id: NonBlankStr
    tenant_id: TenantId
    name: str
    phone: str
    registered_at: datetime
    ltv: float | None = Field(default=None, ge=0.0)
    churn_score: float | None = Field(default=None, ge=0.0, le=1.0)
    segment: str | None = None  # 高价值 / 成长 / 流失风险等


class LifeStage(str, Enum):
    """宠物生命阶段。"""

    PUPPY = "puppy"  # 幼年
    ADULT = "adult"  # 成年
    SENIOR = "senior"  # 老年


class Pet(PetOpsModel):
    """宠物实体。

    `weight_kg > 0`、`birth_date ≤ 当前时间`。
    """

    pet_id: NonBlankStr
    tenant_id: TenantId
    owner_id: NonBlankStr
    species: NonBlankStr  # dog / cat / ...
    breed: str
    birth_date: PastDatetime
    weight_kg: float = Field(gt=0.0)
    life_stage: LifeStage | None = None
