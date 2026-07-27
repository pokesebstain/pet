"""安全库存与再订货点算法（对应设计文档 6.5 与 Requirements 12）。

本模块实现纯函数化的安全库存 / 再订货点计算：

- ``inverse_normal_cdf``：标准正态分布分位函数（服务水平 → z 值），基于标准库
  ``statistics.NormalDist`` 实现，无需引入 scipy 等重型依赖。
- ``compute_safety_stock``：``ss = z · σ_d · √L``，并 clamp 到 ≥ 0。
- ``compute_reorder_point``：``rop = 平均日需求 · L + ss``，恒 ≥ ss 且 ≥ 0。
- ``safety_stock`` / ``reorder_point`` / ``compute_inventory_policy``：按设计签名对外暴露，
  通过注入的 :class:`InventoryDataProvider` 获取 σ_d / 平均日需求 / 提前期，
  因而无需连接真实数据库即可测试。

参数越界（``service_level ∉ (0, 1)``、``lead_time_days ∉ (0, 365]``、
``avg_daily_demand < 0``、``demand_std < 0``）时抛出 :class:`ParameterInvalidError`。

不变量（对应 Property 5 / Requirements 12.1、12.2、12.3）：
- ``safety_stock ≥ 0``；
- ``service_level`` 增大时 ``safety_stock`` 单调不减（``σ_d``、``L`` 不变）；
- ``reorder_point ≥ safety_stock`` 且 ``reorder_point ≥ 0``。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import NormalDist
from typing import Protocol, runtime_checkable

__all__ = [
    "ParameterInvalidError",
    "InventoryDataProvider",
    "StaticInventoryData",
    "InventoryPolicy",
    "inverse_normal_cdf",
    "compute_safety_stock",
    "compute_reorder_point",
    "compute_inventory_policy",
    "safety_stock",
    "reorder_point",
]

# 提前期上限（天），与 Requirements 12.4 一致。
_MAX_LEAD_TIME_DAYS = 365.0

# 复用单个标准正态分布实例（均值 0、标准差 1）。
_STANDARD_NORMAL = NormalDist(0.0, 1.0)


class ParameterInvalidError(ValueError):
    """参数无效错误：入参越界或类型非法时抛出。"""


@runtime_checkable
class InventoryDataProvider(Protocol):
    """库存计算所需的数据提供者。

    抽象掉数据来源（时序库销量、SKU 主数据等），使算法层可脱离真实数据库测试。
    """

    def demand_std(self, sku_id: str) -> float:
        """返回该 SKU 的需求标准差 ``σ_d``（应 ≥ 0）。"""
        ...

    def avg_daily_demand(self, sku_id: str) -> float:
        """返回该 SKU 的平均日需求（应 ≥ 0）。"""
        ...

    def lead_time_days(self, sku_id: str) -> float:
        """返回该 SKU 的补货提前期（天，应在 (0, 365]）。"""
        ...


@dataclass(frozen=True)
class StaticInventoryData:
    """基于静态取值的 :class:`InventoryDataProvider` 实现。

    便于单元/属性测试与无数据库场景下直接注入固定的 σ_d / 平均日需求 / 提前期。
    """

    demand_std_value: float
    avg_daily_demand_value: float
    lead_time_days_value: float

    def demand_std(self, sku_id: str) -> float:  # noqa: ARG002 - 接口签名保持一致
        return self.demand_std_value

    def avg_daily_demand(self, sku_id: str) -> float:  # noqa: ARG002
        return self.avg_daily_demand_value

    def lead_time_days(self, sku_id: str) -> float:  # noqa: ARG002
        return self.lead_time_days_value


@dataclass(frozen=True)
class InventoryPolicy:
    """安全库存与再订货点的计算结果。"""

    safety_stock: float
    reorder_point: float


def inverse_normal_cdf(service_level: float) -> float:
    """标准正态分布分位函数：给定服务水平返回对应 z 值。

    对单调递增函数，``service_level`` 越大返回的 z 值越大。要求
    ``service_level ∈ (0, 1)``，否则抛出 :class:`ParameterInvalidError`。
    """
    _validate_service_level(service_level)
    return _STANDARD_NORMAL.inv_cdf(service_level)


def compute_safety_stock(
    service_level: float,
    demand_std: float,
    lead_time_days: float,
) -> float:
    """计算安全库存 ``ss = z · σ_d · √L`` 并 clamp 到 ≥ 0。

    校验 ``service_level ∈ (0, 1)``、``lead_time_days ∈ (0, 365]``、``demand_std ≥ 0``。
    """
    _validate_service_level(service_level)
    _validate_lead_time(lead_time_days)
    _validate_demand_std(demand_std)

    z = _STANDARD_NORMAL.inv_cdf(service_level)
    ss = z * demand_std * math.sqrt(lead_time_days)
    # service_level < 0.5 时 z < 0 会得到负值，clamp 保证 ss ≥ 0。
    return max(ss, 0.0)


def compute_reorder_point(
    avg_daily_demand: float,
    lead_time_days: float,
    safety_stock_value: float,
) -> float:
    """计算再订货点 ``rop = 平均日需求 · L + ss``。

    由于 ``avg_daily_demand ≥ 0``、``L > 0`` 且 ``ss ≥ 0``，结果恒 ≥ ss 且 ≥ 0。
    """
    _validate_lead_time(lead_time_days)
    _validate_avg_daily_demand(avg_daily_demand)
    if safety_stock_value < 0:
        raise ParameterInvalidError("安全库存不能为负")

    return avg_daily_demand * lead_time_days + safety_stock_value


def compute_inventory_policy(
    sku_id: str,
    service_level: float = 0.95,
    *,
    provider: InventoryDataProvider,
) -> InventoryPolicy:
    """计算 SKU 的安全库存与再订货点。

    通过注入的 ``provider`` 获取 σ_d / 平均日需求 / 提前期，返回同时包含
    ``safety_stock`` 与 ``reorder_point`` 的 :class:`InventoryPolicy`。
    """
    sigma_d = provider.demand_std(sku_id)
    daily = provider.avg_daily_demand(sku_id)
    lead = provider.lead_time_days(sku_id)

    ss = compute_safety_stock(service_level, sigma_d, lead)
    rop = compute_reorder_point(daily, lead, ss)
    return InventoryPolicy(safety_stock=ss, reorder_point=rop)


def safety_stock(
    sku_id: str,
    service_level: float = 0.95,
    *,
    provider: InventoryDataProvider,
) -> float:
    """按设计签名返回 SKU 的安全库存量（≥ 0）。"""
    return compute_inventory_policy(sku_id, service_level, provider=provider).safety_stock


def reorder_point(
    sku_id: str,
    service_level: float = 0.95,
    *,
    provider: InventoryDataProvider,
) -> float:
    """返回 SKU 的再订货点（≥ 安全库存且 ≥ 0）。"""
    return compute_inventory_policy(sku_id, service_level, provider=provider).reorder_point


def _validate_service_level(service_level: float) -> None:
    if isinstance(service_level, bool) or not isinstance(service_level, (int, float)):
        raise ParameterInvalidError("service_level 必须为数值")
    if math.isnan(service_level) or not (0.0 < service_level < 1.0):
        raise ParameterInvalidError("service_level 必须在 (0, 1) 区间内")


def _validate_lead_time(lead_time_days: float) -> None:
    if isinstance(lead_time_days, bool) or not isinstance(lead_time_days, (int, float)):
        raise ParameterInvalidError("lead_time_days 必须为数值")
    if math.isnan(lead_time_days) or not (0.0 < lead_time_days <= _MAX_LEAD_TIME_DAYS):
        raise ParameterInvalidError("lead_time_days 必须在 (0, 365] 区间内")


def _validate_demand_std(demand_std: float) -> None:
    if isinstance(demand_std, bool) or not isinstance(demand_std, (int, float)):
        raise ParameterInvalidError("demand_std 必须为数值")
    if math.isnan(demand_std) or demand_std < 0.0:
        raise ParameterInvalidError("demand_std 不能为负")


def _validate_avg_daily_demand(avg_daily_demand: float) -> None:
    if isinstance(avg_daily_demand, bool) or not isinstance(avg_daily_demand, (int, float)):
        raise ParameterInvalidError("avg_daily_demand 必须为数值")
    if math.isnan(avg_daily_demand) or avg_daily_demand < 0.0:
        raise ParameterInvalidError("avg_daily_demand 不能为负")
