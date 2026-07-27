"""数据模型公共基类与可复用字段校验。

集中定义跨模型复用的校验逻辑（如非空 `tenant_id`），避免在各模型中重复实现。
所有实体默认禁止未知字段并在赋值时校验，以尽早暴露数据错误。

对应设计文档 "Data Models" 一节的校验规则：
- 所有实体必须携带非空 `tenant_id`（平台级共享知识的 `tenant_id` 可为空，见 KnowledgeChunk）。
- `churn_score ∈ [0, 1]`、`ltv ≥ 0`、`weight_kg > 0`、`birth_date ≤ 当前时间`。
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict


def _require_non_blank(value: str) -> str:
    """校验字符串非空且非纯空白。"""
    if value is None or not value.strip():
        raise ValueError("该字段不能为空")
    return value


def _validate_tenant_id(value: str) -> str:
    """校验 `tenant_id` 为非空字符串（RLS 隔离键，写入前必须存在）。"""
    if value is None or not value.strip():
        raise ValueError("tenant_id 不能为空")
    return value


def _reject_future_datetime(value: datetime) -> datetime:
    """校验时间不晚于当前时间（用于 `birth_date` 等历史时间字段）。"""
    now = datetime.now(tz=value.tzinfo) if value.tzinfo else datetime.now()
    if value > now:
        raise ValueError("时间不能晚于当前时间")
    return value


# 复用的带校验注解类型。
NonBlankStr = Annotated[str, AfterValidator(_require_non_blank)]
"""非空字符串（去除首尾空白后长度必须大于 0）。"""

TenantId = Annotated[str, AfterValidator(_validate_tenant_id)]
"""非空的多租户隔离键 `tenant_id`。"""

PastDatetime = Annotated[datetime, AfterValidator(_reject_future_datetime)]
"""不晚于当前时间的历史时间戳。"""


class PetOpsModel(BaseModel):
    """PetOps 数据模型公共基类。

    统一模型配置：禁止未知字段、赋值时校验、允许使用枚举成员值填充。
    """

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        use_enum_values=False,
    )
