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


class CustomerIn(BaseModel):
    name: str
    phone: str | None = None


class PetOut(BaseModel):
    pet_id: str
    owner_id: str
    name: str | None
    species: str
    breed: str
    birth_date: datetime | None
    weight_kg: float | None
    life_stage: str | None
    onboarding_pending: bool


class PetIn(BaseModel):
    owner_id: str
    name: str | None = None
    species: str
    breed: str
    birth_date: datetime | None = None
    weight_kg: float | None = None
    life_stage: str | None = None
