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

    `phone` 可为 `None`：企业微信自动建档场景（Requirement 25）仅采集姓名 + 宠物名，
    手机号留空由店员到店后核实补全，此时 `onboarding_pending = True`。
    """

    customer_id: NonBlankStr
    tenant_id: TenantId
    name: str
    phone: str | None = None
    registered_at: datetime
    ltv: float | None = Field(default=None, ge=0.0)
    churn_score: float | None = Field(default=None, ge=0.0, le=1.0)
    segment: str | None = None  # 高价值 / 成长 / 流失风险等
    #: 是否为企业微信自动建档、待店员核实补全完整信息（Requirement 25）。
    onboarding_pending: bool = False


class LifeStage(str, Enum):
    """宠物生命阶段。"""

    PUPPY = "puppy"  # 幼年
    ADULT = "adult"  # 成年
    SENIOR = "senior"  # 老年


class Pet(PetOpsModel):
    """宠物实体。

    `weight_kg > 0`（若已知）、`birth_date ≤ 当前时间`（若已知）。

    `birth_date` / `weight_kg` 可为 `None`：企业微信自动建档场景（Requirement 25）
    无法获知这些信息，留空由店员到店后核实补全（`onboarding_pending = True`），
    避免用臆造占位值污染生命阶段判断 / 健康分析等下游引擎（这些引擎需按 `None`
    跳过而非当作真实数据参与计算）。
    """

    pet_id: NonBlankStr
    tenant_id: TenantId
    owner_id: NonBlankStr
    name: str | None = None  # 客户对宠物的称呼（如"绒绒"）
    # 公众号渐进式建档允许尚未提供物种 / 品种；缺失须保留为空，不能伪造 "unknown"。
    species: NonBlankStr | None = None  # dog / cat / ...
    breed: str | None = None
    birth_date: PastDatetime | None = None
    weight_kg: float | None = Field(default=None, gt=0.0)
    life_stage: LifeStage | None = None
    #: 是否为企业微信自动建档、待店员核实补全完整信息（Requirement 25）。
    onboarding_pending: bool = False
