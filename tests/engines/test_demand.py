"""需求预测 `forecast_demand` 单元测试（对应任务 4.1 / Requirements 11.1–11.4）。

覆盖：季节性+趋势正常路径、历史不足回退降级、无历史抛错、`horizon_days` 越界/非整数，
以及输出边界（demand ≥ 0、confidence ∈ [0, 1]）。
"""

from __future__ import annotations

import pytest

from app.engines.demand import (
    MAX_HORIZON_DAYS,
    MIN_HISTORY_DAYS,
    forecast_demand,
)
from app.engines.errors import DataNotFoundError, InvalidParameterError
from app.models.commerce import DemandForecast


def _stable_series(days: int, value: float = 10.0) -> list[float]:
    """构造平稳的每日销量序列。"""
    return [value] * days


class _ListProvider:
    """简单的历史销量提供者，用于验证 provider 注入路径。"""

    def __init__(self, series: list[float]) -> None:
        self._series = series

    def get_sales_series(self, sku_id: str) -> list[float]:  # noqa: ARG002
        return self._series


class TestForecastDemandNormalPath:
    def test_returns_demand_forecast_with_sufficient_history(self) -> None:
        result = forecast_demand("sku_1", 14, series=_stable_series(60))
        assert isinstance(result, DemandForecast)
        assert result.sku_id == "sku_1"
        assert result.horizon_days == 14
        assert result.predicted_demand >= 0.0
        assert 0.0 <= result.confidence <= 1.0
        assert result.degraded is False

    def test_stable_series_predicts_close_to_average_times_horizon(self) -> None:
        # 平稳序列（每天 10）预测 10 天，总需求应接近 100。
        result = forecast_demand("sku_1", 10, series=_stable_series(60, 10.0))
        assert result.predicted_demand == pytest.approx(100.0, rel=0.05)

    def test_provider_injection_path(self) -> None:
        provider = _ListProvider(_stable_series(40, 5.0))
        result = forecast_demand("sku_1", 7, provider=provider)
        assert result.predicted_demand >= 0.0
        assert result.degraded is False

    def test_upward_trend_series_stays_non_negative(self) -> None:
        series = [float(i) for i in range(1, 61)]  # 递增趋势
        result = forecast_demand("sku_1", 30, series=series)
        assert result.predicted_demand >= 0.0
        assert 0.0 <= result.confidence <= 1.0

    def test_declining_trend_predicted_demand_clamped_non_negative(self) -> None:
        # 强烈下降趋势，未来外推可能为负，须 clamp 到 ≥ 0。
        series = [max(100.0 - 3.0 * i, 0.0) for i in range(60)]
        result = forecast_demand("sku_1", 60, series=series)
        assert result.predicted_demand >= 0.0


class TestForecastDemandFallback:
    def test_history_below_threshold_flags_degraded(self) -> None:
        result = forecast_demand("sku_1", 7, series=_stable_series(MIN_HISTORY_DAYS - 1))
        assert result.degraded is True
        assert result.predicted_demand >= 0.0
        assert 0.0 <= result.confidence <= 1.0

    def test_exactly_min_history_is_not_degraded(self) -> None:
        result = forecast_demand("sku_1", 7, series=_stable_series(MIN_HISTORY_DAYS))
        assert result.degraded is False

    def test_moving_average_fallback_value(self) -> None:
        result = forecast_demand("sku_1", 5, series=_stable_series(10, 8.0))
        # 移动平均：日均 8 * 5 天 = 40。
        assert result.predicted_demand == pytest.approx(40.0)


class TestForecastDemandNoHistory:
    def test_no_series_and_no_provider_raises(self) -> None:
        with pytest.raises(DataNotFoundError):
            forecast_demand("sku_1", 7)

    def test_empty_series_raises(self) -> None:
        with pytest.raises(DataNotFoundError):
            forecast_demand("sku_1", 7, series=[])

    def test_provider_returns_empty_raises(self) -> None:
        with pytest.raises(DataNotFoundError):
            forecast_demand("sku_1", 7, provider=_ListProvider([]))


class TestForecastDemandInvalidHorizon:
    @pytest.mark.parametrize("horizon", [0, -1, -100])
    def test_non_positive_horizon_raises(self, horizon: int) -> None:
        with pytest.raises(InvalidParameterError):
            forecast_demand("sku_1", horizon, series=_stable_series(60))

    def test_horizon_above_max_raises(self) -> None:
        with pytest.raises(InvalidParameterError):
            forecast_demand("sku_1", MAX_HORIZON_DAYS + 1, series=_stable_series(60))

    def test_max_horizon_boundary_accepted(self) -> None:
        result = forecast_demand("sku_1", MAX_HORIZON_DAYS, series=_stable_series(60))
        assert result.horizon_days == MAX_HORIZON_DAYS

    @pytest.mark.parametrize("horizon", [7.0, 7.5, "7", None])
    def test_non_integer_horizon_raises(self, horizon: object) -> None:
        with pytest.raises(InvalidParameterError):
            forecast_demand("sku_1", horizon, series=_stable_series(60))  # type: ignore[arg-type]

    def test_bool_horizon_rejected(self) -> None:
        # bool 是 int 的子类，须被拒绝。
        with pytest.raises(InvalidParameterError):
            forecast_demand("sku_1", True, series=_stable_series(60))  # type: ignore[arg-type]


class TestForecastDemandInvalidInputs:
    def test_blank_sku_id_raises(self) -> None:
        with pytest.raises(InvalidParameterError):
            forecast_demand("   ", 7, series=_stable_series(60))

    def test_negative_sales_value_raises(self) -> None:
        series = _stable_series(60)
        series[3] = -1.0
        with pytest.raises(InvalidParameterError):
            forecast_demand("sku_1", 7, series=series)

    def test_non_numeric_sales_value_raises(self) -> None:
        series: list = _stable_series(60)
        series[3] = "oops"
        with pytest.raises(InvalidParameterError):
            forecast_demand("sku_1", 7, series=series)
