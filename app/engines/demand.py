"""需求预测算法层（对应设计文档 6.4 Demand Forecast）。

实现 `forecast_demand`：基于历史销量时序，使用"季节性 + 趋势"模型预测未来
`horizon_days` 天的总需求；当可用历史不足 `MIN_HISTORY_DAYS` 天时回退到移动平均法
并将结果标记为降级；无任何历史数据时抛出数据缺失错误。

前置 / 后置条件（与设计一致）：
- `horizon_days` 必须为整数且 0 < horizon_days ≤ 365，否则抛 `InvalidParameterError`。
- 返回的 `predicted_demand` ≥ 0，`confidence ∈ [0, 1]`（Property 6 / Requirements 11.1）。
- 历史 < `MIN_HISTORY_DAYS` 天：移动平均回退，`degraded=True`（Requirements 11.2）。
- 无历史数据：抛 `DataNotFoundError`（Requirements 11.4）。

为便于在无实时数据库的情况下测试，历史销量序列可通过 `series` 参数直接注入，
或通过实现了 `SalesHistoryProvider` 协议的 `provider` 注入。
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from app.engines.errors import DataNotFoundError, InvalidParameterError
from app.models.commerce import DemandForecast

#: 判定是否回退到移动平均法的最小历史天数阈值（Requirements 11.2）。
MIN_HISTORY_DAYS = 30

#: `horizon_days` 的上界（含）（Requirements 11.1 / 11.3）。
MAX_HORIZON_DAYS = 365

#: 季节性周期（按周）。
_SEASONAL_PERIOD = 7


@runtime_checkable
class SalesHistoryProvider(Protocol):
    """历史销量数据提供者协议。

    实现者根据 `sku_id` 返回按时间升序（最旧在前、最新在后）排列的每日销量序列。
    """

    def get_sales_series(self, sku_id: str) -> Sequence[float]:  # pragma: no cover - 协议声明
        ...


def forecast_demand(
    sku_id: str,
    horizon_days: int,
    series: Sequence[float] | None = None,
    *,
    provider: SalesHistoryProvider | None = None,
) -> DemandForecast:
    """预测 SKU 未来 `horizon_days` 天的总需求。

    Args:
        sku_id: SKU 标识（非空）。
        horizon_days: 预测跨度（天），必须为整数且 0 < horizon_days ≤ 365。
        series: 可选，直接注入的历史每日销量序列（按时间升序）。
        provider: 可选，历史销量提供者；当未直接提供 `series` 时用于查询。

    Returns:
        DemandForecast: `predicted_demand ≥ 0`、`confidence ∈ [0, 1]`；历史不足时
        `degraded=True`。

    Raises:
        InvalidParameterError: `sku_id` 为空、`horizon_days` 非整数或越界，或历史序列含非法值。
        DataNotFoundError: 无任何可用历史销量数据。
    """
    _validate_sku_id(sku_id)
    _validate_horizon(horizon_days)

    resolved = _resolve_series(sku_id, series, provider)

    if len(resolved) < MIN_HISTORY_DAYS:
        return _fallback_moving_average(sku_id, horizon_days, resolved)

    return _seasonal_trend_forecast(sku_id, horizon_days, resolved)


def _validate_sku_id(sku_id: str) -> None:
    if not isinstance(sku_id, str) or not sku_id.strip():
        raise InvalidParameterError("sku_id 不能为空")


def _validate_horizon(horizon_days: int) -> None:
    # bool 是 int 的子类，需显式排除，避免 True/False 被当作 1/0。
    if isinstance(horizon_days, bool) or not isinstance(horizon_days, int):
        raise InvalidParameterError("horizon_days 必须为整数")
    if horizon_days <= 0 or horizon_days > MAX_HORIZON_DAYS:
        raise InvalidParameterError(
            f"horizon_days 必须在 (0, {MAX_HORIZON_DAYS}] 之间，实际为 {horizon_days}"
        )


def _resolve_series(
    sku_id: str,
    series: Sequence[float] | None,
    provider: SalesHistoryProvider | None,
) -> list[float]:
    """解析并校验历史销量序列。

    优先使用直接注入的 `series`；否则经 `provider` 查询。空序列或缺失来源视为无历史。
    """
    raw: Sequence[float] | None = series
    if raw is None and provider is not None:
        raw = provider.get_sales_series(sku_id)

    if raw is None or len(raw) == 0:
        raise DataNotFoundError(f"SKU {sku_id} 无任何历史销量数据")

    cleaned: list[float] = []
    for value in raw:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise InvalidParameterError("历史销量序列包含非数值项")
        fvalue = float(value)
        if not math.isfinite(fvalue) or fvalue < 0:
            raise InvalidParameterError("历史销量必须为非负有限数值")
        cleaned.append(fvalue)
    return cleaned


def _fallback_moving_average(
    sku_id: str, horizon_days: int, series: list[float]
) -> DemandForecast:
    """历史不足时的移动平均回退，结果标记为降级（Requirements 11.2）。"""
    avg_daily = sum(series) / len(series)
    predicted = max(avg_daily * horizon_days, 0.0)
    # 回退结果置信度在基础置信度上打折，且恒落在 [0, 1]。
    confidence = _clamp01(_confidence_from_series(series) * 0.6)
    return DemandForecast(
        sku_id=sku_id,
        horizon_days=horizon_days,
        predicted_demand=predicted,
        confidence=confidence,
        degraded=True,
    )


def _seasonal_trend_forecast(
    sku_id: str, horizon_days: int, series: list[float]
) -> DemandForecast:
    """季节性 + 趋势预测：线性趋势 + 加性周季节分量。"""
    n = len(series)
    slope, intercept = _linear_fit(series)

    # 以趋势拟合残差估计每个"星期几"的加性季节分量。
    seasonal_sum = [0.0] * _SEASONAL_PERIOD
    seasonal_cnt = [0] * _SEASONAL_PERIOD
    for t in range(n):
        residual = series[t] - (intercept + slope * t)
        bucket = t % _SEASONAL_PERIOD
        seasonal_sum[bucket] += residual
        seasonal_cnt[bucket] += 1
    seasonal = [
        (seasonal_sum[i] / seasonal_cnt[i]) if seasonal_cnt[i] else 0.0
        for i in range(_SEASONAL_PERIOD)
    ]

    total = 0.0
    for k in range(1, horizon_days + 1):
        t = n + k - 1
        daily = intercept + slope * t + seasonal[t % _SEASONAL_PERIOD]
        total += max(daily, 0.0)

    predicted = max(total, 0.0)
    confidence = _clamp01(_confidence_from_series(series))
    return DemandForecast(
        sku_id=sku_id,
        horizon_days=horizon_days,
        predicted_demand=predicted,
        confidence=confidence,
        degraded=False,
    )


def _linear_fit(series: list[float]) -> tuple[float, float]:
    """对序列做最小二乘线性拟合，返回 (slope, intercept)。"""
    n = len(series)
    if n == 1:
        return 0.0, series[0]
    mean_x = (n - 1) / 2.0
    mean_y = sum(series) / n
    var_x = 0.0
    cov_xy = 0.0
    for t in range(n):
        dx = t - mean_x
        var_x += dx * dx
        cov_xy += dx * (series[t] - mean_y)
    if var_x == 0:
        return 0.0, mean_y
    slope = cov_xy / var_x
    intercept = mean_y - slope * mean_x
    return slope, intercept


def _confidence_from_series(series: list[float]) -> float:
    """基于变异系数估计置信度，恒落在 (0, 1]。

    序列越平稳（相对波动越小），置信度越高。
    """
    n = len(series)
    if n < 2:
        return 0.5
    mean_y = sum(series) / n
    if mean_y <= 0:
        return 0.5
    variance = sum((v - mean_y) ** 2 for v in series) / n
    std = math.sqrt(variance)
    cv = std / mean_y
    return 1.0 / (1.0 + cv)


def _clamp01(value: float) -> float:
    """将取值裁剪到 [0, 1]。"""
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value
