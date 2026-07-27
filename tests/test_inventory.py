"""安全库存与再订货点算法单元测试（任务 4.3 / Requirements 12）。

覆盖正常计算、单调性、clamp、再订货点关系与参数越界错误。属性测试见任务 4.4。
"""

from __future__ import annotations

import math

import pytest

from app.engines.inventory import (
    InventoryPolicy,
    ParameterInvalidError,
    StaticInventoryData,
    compute_inventory_policy,
    compute_reorder_point,
    compute_safety_stock,
    inverse_normal_cdf,
    reorder_point,
    safety_stock,
)


def _provider(
    *, demand_std: float = 10.0, avg_daily_demand: float = 5.0, lead_time_days: float = 9.0
) -> StaticInventoryData:
    return StaticInventoryData(
        demand_std_value=demand_std,
        avg_daily_demand_value=avg_daily_demand,
        lead_time_days_value=lead_time_days,
    )


# --- inverse_normal_cdf ---------------------------------------------------


def test_inverse_normal_cdf_median_is_zero() -> None:
    assert inverse_normal_cdf(0.5) == pytest.approx(0.0, abs=1e-9)


def test_inverse_normal_cdf_95_percent() -> None:
    # 95% 服务水平对应 z ≈ 1.645。
    assert inverse_normal_cdf(0.95) == pytest.approx(1.6448536, abs=1e-4)


def test_inverse_normal_cdf_is_increasing() -> None:
    assert inverse_normal_cdf(0.6) < inverse_normal_cdf(0.9)


# --- compute_safety_stock -------------------------------------------------


def test_safety_stock_known_value() -> None:
    # z(0.95)=1.6448536, σ=10, L=9 → √L=3 → ss ≈ 49.345608
    ss = compute_safety_stock(0.95, demand_std=10.0, lead_time_days=9.0)
    assert ss == pytest.approx(1.6448536 * 10.0 * 3.0, abs=1e-3)


def test_safety_stock_non_negative_and_clamped_below_half() -> None:
    # service_level < 0.5 → z < 0 → 原始值为负，应被 clamp 到 0。
    assert compute_safety_stock(0.2, demand_std=10.0, lead_time_days=9.0) == 0.0


def test_safety_stock_zero_when_no_demand_variance() -> None:
    assert compute_safety_stock(0.95, demand_std=0.0, lead_time_days=9.0) == 0.0


def test_safety_stock_monotonic_in_service_level() -> None:
    lo = compute_safety_stock(0.80, demand_std=10.0, lead_time_days=9.0)
    hi = compute_safety_stock(0.99, demand_std=10.0, lead_time_days=9.0)
    assert lo <= hi


# --- compute_reorder_point ------------------------------------------------


def test_reorder_point_formula() -> None:
    # rop = avg_daily_demand * L + ss
    rop = compute_reorder_point(5.0, lead_time_days=9.0, safety_stock_value=49.35)
    assert rop == pytest.approx(5.0 * 9.0 + 49.35)


def test_reorder_point_ge_safety_stock() -> None:
    ss = 49.35
    rop = compute_reorder_point(5.0, lead_time_days=9.0, safety_stock_value=ss)
    assert rop >= ss


def test_reorder_point_rejects_negative_safety_stock() -> None:
    with pytest.raises(ParameterInvalidError):
        compute_reorder_point(5.0, lead_time_days=9.0, safety_stock_value=-1.0)


# --- compute_inventory_policy / public API --------------------------------


def test_compute_inventory_policy_via_provider() -> None:
    policy = compute_inventory_policy("sku-1", 0.95, provider=_provider())
    assert isinstance(policy, InventoryPolicy)
    assert policy.safety_stock >= 0.0
    assert policy.reorder_point >= policy.safety_stock >= 0.0


def test_safety_stock_and_reorder_point_helpers() -> None:
    provider = _provider()
    ss = safety_stock("sku-1", 0.95, provider=provider)
    rop = reorder_point("sku-1", 0.95, provider=provider)
    assert ss >= 0.0
    assert rop >= ss


def test_default_service_level_is_095() -> None:
    provider = _provider()
    assert safety_stock("sku-1", provider=provider) == pytest.approx(
        safety_stock("sku-1", 0.95, provider=provider)
    )


# --- 参数越界错误 (Requirements 12.4) --------------------------------------


@pytest.mark.parametrize("bad", [0.0, 1.0, -0.1, 1.5, math.nan])
def test_invalid_service_level_raises(bad: float) -> None:
    with pytest.raises(ParameterInvalidError):
        compute_safety_stock(bad, demand_std=10.0, lead_time_days=9.0)


@pytest.mark.parametrize("bad", [0.0, -1.0, 366.0, math.nan])
def test_invalid_lead_time_raises(bad: float) -> None:
    with pytest.raises(ParameterInvalidError):
        compute_safety_stock(0.95, demand_std=10.0, lead_time_days=bad)


def test_lead_time_upper_bound_365_allowed() -> None:
    # 365 是包含端点。
    assert compute_safety_stock(0.95, demand_std=1.0, lead_time_days=365.0) >= 0.0


@pytest.mark.parametrize("bad", [-1.0, -0.001, math.nan])
def test_invalid_demand_std_raises(bad: float) -> None:
    with pytest.raises(ParameterInvalidError):
        compute_safety_stock(0.95, demand_std=bad, lead_time_days=9.0)


@pytest.mark.parametrize("bad", [-1.0, -0.001, math.nan])
def test_invalid_avg_daily_demand_raises(bad: float) -> None:
    with pytest.raises(ParameterInvalidError):
        compute_reorder_point(bad, lead_time_days=9.0, safety_stock_value=0.0)


def test_policy_rejects_out_of_range_via_provider() -> None:
    with pytest.raises(ParameterInvalidError):
        compute_inventory_policy(
            "sku-1", 0.95, provider=_provider(avg_daily_demand=-5.0)
        )
