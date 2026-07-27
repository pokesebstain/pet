"""订阅与供应链数据模型（对应设计文档 Data Models 4.3）。

包含 `Subscription`、`SKU`、`DemandForecast`。

`DemandForecast` 施加与设计正确性属性一致的字段约束：
`predicted_demand ≥ 0`、`confidence ∈ [0, 1]`、`safety_stock ≥ 0`、`reorder_point ≥ 0`、
`horizon_days > 0`（对应 Property 6 / Requirements 11.1）。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.models.base import NonBlankStr, PetOpsModel, TenantId


class Subscription(PetOpsModel):
    """客户订阅。"""

    subscription_id: NonBlankStr
    tenant_id: TenantId
    customer_id: NonBlankStr
    plan_id: NonBlankStr
    status: str  # active / paused / cancelled
    next_billing_at: datetime


class SKU(PetOpsModel):
    """库存单元（SKU）。

    单位成本与当前库存非负；提前期为正。
    """

    sku_id: NonBlankStr
    tenant_id: TenantId
    name: NonBlankStr
    category: str
    unit_cost: float = Field(ge=0.0)
    current_stock: float = Field(ge=0.0)
    lead_time_days: float = Field(gt=0.0)


class DemandForecast(PetOpsModel):
    """需求预测结果。

    注意：`DemandForecast` 是预测输出结果对象，本身不携带 `tenant_id`
    （与设计文档 4.3 一致），其租户隔离由生成它的 SKU / 查询上下文保证。
    """

    sku_id: NonBlankStr
    horizon_days: int = Field(gt=0)
    predicted_demand: float = Field(ge=0.0)
    confidence: float = Field(ge=0.0, le=1.0)
    safety_stock: float = Field(default=0.0, ge=0.0)
    reorder_point: float = Field(default=0.0, ge=0.0)
    degraded: bool = False
    """是否为降级（回退）结果。

    当 SKU 可用历史销量数据不足（少于 `MIN_HISTORY_DAYS` 天）而回退到移动平均法时，
    该结果被标记为降级（对应 Requirements 11.2）。安全库存 / 再订货点由供应链引擎装配阶段
    （任务 4.3 / 16.1）填充，此处默认 0.0。
    """
