"""供应链引擎装配（对应设计文档组件 4 `SupplyChainEngine` 与 6.4 / 6.5）。

本模块将算法层的 :func:`app.engines.demand.forecast_demand` 与
:func:`app.engines.inventory.compute_safety_stock` / :func:`compute_reorder_point`
封装为面向业务的 :class:`SupplyChainEngine`，并通过注入的数据提供者接入
TimescaleDB 销量查询与 SKU 主数据：

- :class:`SalesHistoryProvider`（复用 :mod:`app.engines.demand`）：按 SKU 返回按时间
  升序的历史每日销量序列（对应 TimescaleDB 销量查询）。
- :class:`SkuMasterProvider`：按 SKU 返回 :class:`~app.models.commerce.SKU` 主数据
  （当前库存、提前期等）。

对外方法：
- :meth:`SupplyChainEngine.forecast_demand`：预测未来需求，并在结果中填充安全库存与
  再订货点（Requirements 11.1 / 12.1 / 12.3）。
- :meth:`SupplyChainEngine.safety_stock`：按服务水平计算安全库存（Requirements 12.1）。
- :meth:`SupplyChainEngine.reorder_point`：计算再订货点（Requirements 12.3）。
- :meth:`SupplyChainEngine.compute_inventory_policy`：一次性返回安全库存 + 再订货点。
- :meth:`SupplyChainEngine.evaluate_restock`：补货判定，比较"预测需求 + 安全库存"
  与当前库存，返回 :class:`RestockDecision`。

设计要点：安全库存计算所需的需求标准差 ``σ_d`` 与平均日需求由历史销量序列在引擎内
派生（而非要求外部再提供），提前期取自 SKU 主数据；从而算法层保持纯函数、引擎层负责
数据接入。所有数据访问经协议抽象，可用内存假实现（:class:`InMemorySalesHistoryProvider`
/ :class:`InMemorySkuMasterProvider`）在无实时数据库的情况下测试。
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from app.engines.demand import (
    MAX_HORIZON_DAYS,
    MIN_HISTORY_DAYS,
    SalesHistoryProvider,
    forecast_demand as _forecast_demand_algo,
)
from app.engines.errors import DataNotFoundError, InvalidParameterError
from app.engines.inventory import (
    InventoryPolicy,
    compute_reorder_point,
    compute_safety_stock,
)
from app.models.commerce import SKU, DemandForecast

__all__ = [
    "SalesHistoryProvider",
    "SkuMasterProvider",
    "InMemorySalesHistoryProvider",
    "InMemorySkuMasterProvider",
    "RestockDecision",
    "SupplyChainEngine",
    "DEFAULT_SERVICE_LEVEL",
]

#: 安全库存默认服务水平（与算法层保持一致）。
DEFAULT_SERVICE_LEVEL = 0.95


@runtime_checkable
class SkuMasterProvider(Protocol):
    """SKU 主数据提供者协议。

    抽象掉 SKU 主数据来源（业务库 / 缓存等），按 ``sku_id`` 返回
    :class:`~app.models.commerce.SKU`。找不到时应抛出
    :class:`~app.engines.errors.DataNotFoundError`。
    """

    def get_sku(self, sku_id: str) -> SKU:  # pragma: no cover - 协议声明
        ...


class InMemorySalesHistoryProvider:
    """基于内存字典的 :class:`SalesHistoryProvider` 假实现，供测试与无数据库场景使用。"""

    def __init__(self, series_by_sku: dict[str, Sequence[float]] | None = None) -> None:
        self._series_by_sku: dict[str, list[float]] = {
            sku_id: list(series) for sku_id, series in (series_by_sku or {}).items()
        }

    def set_series(self, sku_id: str, series: Sequence[float]) -> None:
        """写入 / 覆盖某 SKU 的历史销量序列。"""
        self._series_by_sku[sku_id] = list(series)

    def get_sales_series(self, sku_id: str) -> list[float]:
        # 缺失时返回空序列，交由算法层判定为"无历史数据"。
        return list(self._series_by_sku.get(sku_id, []))


class InMemorySkuMasterProvider:
    """基于内存字典的 :class:`SkuMasterProvider` 假实现，供测试与无数据库场景使用。"""

    def __init__(self, skus: dict[str, SKU] | None = None) -> None:
        self._skus: dict[str, SKU] = dict(skus or {})

    def add(self, sku: SKU) -> None:
        """登记一个 SKU 主数据。"""
        self._skus[sku.sku_id] = sku

    def get_sku(self, sku_id: str) -> SKU:
        try:
            return self._skus[sku_id]
        except KeyError as exc:
            raise DataNotFoundError(f"SKU {sku_id} 主数据不存在") from exc


@dataclass(frozen=True)
class RestockDecision:
    """补货判定结果。

    ``needs_restock`` 为真表示"预测需求 + 安全库存"已超过当前可用库存，应触发补货。
    ``suggested_order_quantity`` 为覆盖缺口所需的建议补货量（≥ 0）。
    """

    sku_id: str
    horizon_days: int
    predicted_demand: float
    safety_stock: float
    reorder_point: float
    current_stock: float
    #: 覆盖预测需求与安全库存所需的库存基线（predicted_demand + safety_stock）。
    required_stock: float
    needs_restock: bool
    suggested_order_quantity: float
    degraded: bool


class SupplyChainEngine:
    """供应链引擎：组合需求预测与安全库存算法，接入销量与 SKU 数据。"""

    def __init__(
        self,
        sales_provider: SalesHistoryProvider,
        sku_provider: SkuMasterProvider,
    ) -> None:
        """构造引擎。

        Args:
            sales_provider: 历史销量提供者（对应 TimescaleDB 销量查询）。
            sku_provider: SKU 主数据提供者。
        """
        self._sales_provider = sales_provider
        self._sku_provider = sku_provider

    # ------------------------------------------------------------------ #
    # 需求预测
    # ------------------------------------------------------------------ #
    def forecast_demand(
        self,
        sku_id: str,
        horizon_days: int,
        service_level: float = DEFAULT_SERVICE_LEVEL,
    ) -> DemandForecast:
        """预测 SKU 未来 ``horizon_days`` 天需求，并填充安全库存与再订货点。

        通过销量提供者查询历史序列后调用算法层 ``forecast_demand``；随后基于同一历史
        序列与 SKU 提前期计算安全库存与再订货点，回填到返回的
        :class:`~app.models.commerce.DemandForecast` 中。

        Raises:
            InvalidParameterError: ``horizon_days`` / ``service_level`` 非法。
            DataNotFoundError: SKU 无任何历史销量数据或主数据缺失。
        """
        series = self._sales_provider.get_sales_series(sku_id)
        forecast = _forecast_demand_algo(sku_id, horizon_days, series=series)

        sku = self._sku_provider.get_sku(sku_id)
        sigma_d, avg_daily = _demand_stats(series)
        ss = compute_safety_stock(service_level, sigma_d, sku.lead_time_days)
        rop = compute_reorder_point(avg_daily, sku.lead_time_days, ss)

        return forecast.model_copy(update={"safety_stock": ss, "reorder_point": rop})

    # ------------------------------------------------------------------ #
    # 安全库存 / 再订货点
    # ------------------------------------------------------------------ #
    def safety_stock(
        self,
        sku_id: str,
        service_level: float = DEFAULT_SERVICE_LEVEL,
    ) -> float:
        """按服务水平计算 SKU 的安全库存（≥ 0）。"""
        return self.compute_inventory_policy(sku_id, service_level).safety_stock

    def reorder_point(
        self,
        sku_id: str,
        service_level: float = DEFAULT_SERVICE_LEVEL,
    ) -> float:
        """计算 SKU 的再订货点（≥ 安全库存且 ≥ 0）。"""
        return self.compute_inventory_policy(sku_id, service_level).reorder_point

    def compute_inventory_policy(
        self,
        sku_id: str,
        service_level: float = DEFAULT_SERVICE_LEVEL,
    ) -> InventoryPolicy:
        """一次性返回安全库存与再订货点。

        需求标准差与平均日需求由历史销量序列派生，提前期取自 SKU 主数据。

        Raises:
            InvalidParameterError: ``service_level`` 非法。
            DataNotFoundError: SKU 无任何历史销量数据或主数据缺失。
        """
        series = self._require_series(sku_id)
        sku = self._sku_provider.get_sku(sku_id)
        sigma_d, avg_daily = _demand_stats(series)

        ss = compute_safety_stock(service_level, sigma_d, sku.lead_time_days)
        rop = compute_reorder_point(avg_daily, sku.lead_time_days, ss)
        return InventoryPolicy(safety_stock=ss, reorder_point=rop)

    # ------------------------------------------------------------------ #
    # 补货判定
    # ------------------------------------------------------------------ #
    def evaluate_restock(
        self,
        sku_id: str,
        horizon_days: int,
        service_level: float = DEFAULT_SERVICE_LEVEL,
    ) -> RestockDecision:
        """补货判定：比较"预测需求 + 安全库存"与当前库存。

        当 ``predicted_demand + safety_stock > current_stock`` 时判定为需要补货，
        建议补货量为二者之差（≥ 0）。

        Raises:
            InvalidParameterError: ``horizon_days`` / ``service_level`` 非法。
            DataNotFoundError: SKU 无任何历史销量数据或主数据缺失。
        """
        forecast = self.forecast_demand(sku_id, horizon_days, service_level)
        sku = self._sku_provider.get_sku(sku_id)

        required = forecast.predicted_demand + forecast.safety_stock
        gap = required - sku.current_stock
        needs_restock = gap > 0.0
        suggested = max(gap, 0.0)

        return RestockDecision(
            sku_id=sku_id,
            horizon_days=horizon_days,
            predicted_demand=forecast.predicted_demand,
            safety_stock=forecast.safety_stock,
            reorder_point=forecast.reorder_point,
            current_stock=sku.current_stock,
            required_stock=required,
            needs_restock=needs_restock,
            suggested_order_quantity=suggested,
            degraded=forecast.degraded,
        )

    # ------------------------------------------------------------------ #
    # 内部辅助
    # ------------------------------------------------------------------ #
    def _require_series(self, sku_id: str) -> list[float]:
        """查询历史销量序列，缺失则抛数据缺失错误。"""
        if not isinstance(sku_id, str) or not sku_id.strip():
            raise InvalidParameterError("sku_id 不能为空")
        series = list(self._sales_provider.get_sales_series(sku_id))
        if not series:
            raise DataNotFoundError(f"SKU {sku_id} 无任何历史销量数据")
        return series


def _demand_stats(series: Sequence[float]) -> tuple[float, float]:
    """由历史销量序列派生 (需求标准差 σ_d, 平均日需求)。

    使用总体标准差；空序列时返回 (0.0, 0.0)。负值不会出现于合法历史序列，
    此处不额外校验（算法层已在预测路径校验）。
    """
    values = [float(v) for v in series]
    n = len(values)
    if n == 0:
        return 0.0, 0.0
    mean = sum(values) / n
    variance = sum((v - mean) ** 2 for v in values) / n
    return math.sqrt(variance), mean
