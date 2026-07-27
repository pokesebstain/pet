"""客户 LTV 预测 `predict_ltv` 单元测试（对应任务 3.5 / Requirements 6.1, 6.2, 6.3, 6.6）。

覆盖：LTV 非负、随 horizon_months 单调不减、参数校验（越界 / 非整数 / bool）、
客户不存在或数据不足抛错、特征注入与 provider 注入路径、留存概率复用 predict_churn。
属性测试（Property 3）由任务 3.6 单独实现。
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.engines import (
    DataNotFoundError,
    InvalidParameterError,
    MAX_HORIZON_MONTHS,
    predict_ltv,
)
from app.models import FeatureVector


def _base_features() -> dict[str, float]:
    return {
        # churn 复用所需 RFM
        "recency": 30.0,
        "frequency": 12.0,
        "monetary": 5_000.0,
        "activity": 400.0,
        # LTV 所需
        "avg_monthly_orders": 2.0,
        "avg_order_value": 150.0,
    }


def _fv(features: dict[str, float]) -> FeatureVector:
    return FeatureVector(
        entity_id="cust-1",
        tenant_id="store_88",
        feature_group="ltv",
        features=features,
        computed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


class _DictProvider:
    """按 customer_id 返回特征向量的提供者；未知客户返回 None。"""

    def __init__(self, mapping: dict[str, FeatureVector]) -> None:
        self._mapping = mapping

    def get_features(self, customer_id: str) -> FeatureVector | None:
        return self._mapping.get(customer_id)


class TestPredictLtvNormalPath:
    def test_returns_non_negative_ltv(self) -> None:
        ltv = predict_ltv("cust-1", 24, features=_fv(_base_features()))
        assert ltv >= 0.0

    def test_default_horizon(self) -> None:
        ltv = predict_ltv("cust-1", features=_fv(_base_features()))
        assert ltv >= 0.0

    def test_deterministic(self) -> None:
        fv = _fv(_base_features())
        assert predict_ltv("cust-1", 12, features=fv) == predict_ltv(
            "cust-1", 12, features=fv
        )

    def test_provider_injection_path(self) -> None:
        provider = _DictProvider({"cust-1": _fv(_base_features())})
        ltv = predict_ltv("cust-1", 12, provider=provider)
        assert ltv >= 0.0

    def test_zero_purchase_activity_yields_zero_ltv(self) -> None:
        feats = _base_features()
        feats["avg_monthly_orders"] = 0.0
        ltv = predict_ltv("cust-1", 24, features=_fv(feats))
        assert ltv == 0.0


class TestPredictLtvMonotonic:
    def test_monotonic_non_decreasing_in_horizon(self) -> None:
        """horizon_months 增大时 LTV 单调不减（Requirement 6.2）。"""
        fv = _fv(_base_features())
        prev = None
        for horizon in [1, 2, 6, 12, 24, 60, 120]:
            ltv = predict_ltv("cust-1", horizon, features=fv)
            if prev is not None:
                assert ltv >= prev - 1e-9
            prev = ltv

    def test_larger_horizon_strictly_greater_for_active_customer(self) -> None:
        fv = _fv(_base_features())
        assert predict_ltv("cust-1", 24, features=fv) > predict_ltv(
            "cust-1", 1, features=fv
        )


class TestPredictLtvInvalidHorizon:
    @pytest.mark.parametrize("horizon", [0, -1, -50])
    def test_non_positive_horizon_raises(self, horizon: int) -> None:
        with pytest.raises(InvalidParameterError):
            predict_ltv("cust-1", horizon, features=_fv(_base_features()))

    def test_horizon_above_max_raises(self) -> None:
        with pytest.raises(InvalidParameterError):
            predict_ltv(
                "cust-1", MAX_HORIZON_MONTHS + 1, features=_fv(_base_features())
            )

    def test_max_horizon_boundary_accepted(self) -> None:
        ltv = predict_ltv("cust-1", MAX_HORIZON_MONTHS, features=_fv(_base_features()))
        assert ltv >= 0.0

    @pytest.mark.parametrize("horizon", [24.0, 24.5, "24", None])
    def test_non_integer_horizon_raises(self, horizon: object) -> None:
        with pytest.raises(InvalidParameterError):
            predict_ltv("cust-1", horizon, features=_fv(_base_features()))  # type: ignore[arg-type]

    def test_bool_horizon_rejected(self) -> None:
        with pytest.raises(InvalidParameterError):
            predict_ltv("cust-1", True, features=_fv(_base_features()))  # type: ignore[arg-type]


class TestPredictLtvDataNotFound:
    def test_no_features_and_no_provider_raises(self) -> None:
        with pytest.raises(DataNotFoundError):
            predict_ltv("cust-1", 12)

    def test_unknown_customer_via_provider_raises(self) -> None:
        provider = _DictProvider({})
        with pytest.raises(DataNotFoundError):
            predict_ltv("ghost", 12, provider=provider)

    @pytest.mark.parametrize("missing", ["avg_monthly_orders", "avg_order_value"])
    def test_insufficient_ltv_features_raises(self, missing: str) -> None:
        feats = _base_features()
        del feats[missing]
        with pytest.raises(DataNotFoundError):
            predict_ltv("cust-1", 12, features=_fv(feats))


class TestPredictLtvInvalidInputs:
    def test_blank_customer_id_raises(self) -> None:
        with pytest.raises(InvalidParameterError):
            predict_ltv("   ", 12, features=_fv(_base_features()))

    def test_negative_discount_rate_raises(self) -> None:
        with pytest.raises(InvalidParameterError):
            predict_ltv(
                "cust-1", 12, features=_fv(_base_features()), monthly_discount_rate=-0.1
            )

    @pytest.mark.parametrize("key", ["avg_monthly_orders", "avg_order_value"])
    def test_negative_ltv_feature_raises(self, key: str) -> None:
        feats = _base_features()
        feats[key] = -1.0
        with pytest.raises(InvalidParameterError):
            predict_ltv("cust-1", 12, features=_fv(feats))

    def test_invalid_churn_feature_propagates(self) -> None:
        # RFM 特征越界应经 predict_churn 触发参数无效错误。
        feats = _base_features()
        feats["recency"] = -5.0
        with pytest.raises(InvalidParameterError):
            predict_ltv("cust-1", 12, features=_fv(feats))
