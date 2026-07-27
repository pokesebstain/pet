"""流失预测 `predict_churn` 单元测试（对应 Requirement 7 与设计 6.2）。

覆盖：分数有界、活跃度单调不增、空特征 / 缺 RFM / 越界 / 未知特征拒绝、
归一化边界与确定性。属性测试（Property 2）由任务 3.4 单独实现。
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.engines import InvalidParameterError, predict_churn
from app.models import FeatureVector


def _fv(features: dict[str, float]) -> FeatureVector:
    """构造一个最小可用的 churn 特征向量。"""
    return FeatureVector(
        entity_id="cust-1",
        tenant_id="store_88",
        feature_group="churn",
        features=features,
        computed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def _base_features() -> dict[str, float]:
    return {
        "recency": 30.0,
        "frequency": 12.0,
        "monetary": 5_000.0,
        "activity": 400.0,
    }


def test_returns_score_within_unit_interval() -> None:
    """合法特征向量返回值应落在 [0, 1]。"""
    score = predict_churn(_fv(_base_features()))
    assert 0.0 <= score <= 1.0


def test_deterministic() -> None:
    """相同输入应产生完全一致的输出（纯函数、无随机性）。"""
    fv = _fv(_base_features())
    assert predict_churn(fv) == predict_churn(fv)


def test_boundary_features_stay_in_range() -> None:
    """归一化区间端点（min / max）不应越界或抛错。"""
    low = predict_churn(
        _fv({"recency": 0.0, "frequency": 0.0, "monetary": 0.0, "activity": 0.0})
    )
    high = predict_churn(
        _fv(
            {
                "recency": 3650.0,
                "frequency": 1000.0,
                "monetary": 1_000_000.0,
                "activity": 1000.0,
            }
        )
    )
    assert 0.0 <= low <= 1.0
    assert 0.0 <= high <= 1.0


def test_higher_activity_does_not_increase_churn() -> None:
    """其余特征相同、活跃度更高时 churn_score 单调不增（Requirement 7.2）。"""
    prev = None
    for activity in [0.0, 100.0, 250.0, 500.0, 800.0, 1000.0]:
        feats = _base_features()
        feats["activity"] = activity
        score = predict_churn(_fv(feats))
        if prev is not None:
            assert score <= prev + 1e-12
        prev = score


def test_higher_frequency_does_not_increase_churn() -> None:
    """频度（活跃类特征）更高时 churn_score 单调不增。"""
    feats_low = _base_features()
    feats_low["frequency"] = 1.0
    feats_high = _base_features()
    feats_high["frequency"] = 900.0
    assert predict_churn(_fv(feats_high)) <= predict_churn(_fv(feats_low))


def test_higher_recency_does_not_decrease_churn() -> None:
    """近度（距上次消费天数）更大时流失分数不降。"""
    feats_recent = _base_features()
    feats_recent["recency"] = 5.0
    feats_stale = _base_features()
    feats_stale["recency"] = 3000.0
    assert predict_churn(_fv(feats_stale)) >= predict_churn(_fv(feats_recent))


def test_empty_feature_vector_raises() -> None:
    """空特征向量应拒绝（Requirement 7.3）。"""
    with pytest.raises(InvalidParameterError):
        predict_churn(_fv({}))


@pytest.mark.parametrize("missing", ["recency", "frequency", "monetary"])
def test_missing_required_rfm_raises(missing: str) -> None:
    """缺少任一 RFM 必需特征应拒绝（Requirement 7.4）。"""
    feats = _base_features()
    del feats[missing]
    with pytest.raises(InvalidParameterError):
        predict_churn(_fv(feats))


@pytest.mark.parametrize(
    "name,value",
    [
        ("recency", -1.0),
        ("recency", 3650.1),
        ("frequency", -0.5),
        ("frequency", 1000.1),
        ("monetary", -10.0),
        ("activity", 1000.5),
        ("activity", float("nan")),
        ("activity", float("inf")),
    ],
)
def test_out_of_range_feature_raises(name: str, value: float) -> None:
    """越界或非有限特征值应拒绝（Requirement 7.4）。"""
    feats = _base_features()
    feats[name] = value
    with pytest.raises(InvalidParameterError):
        predict_churn(_fv(feats))


def test_unknown_feature_raises() -> None:
    """未知特征键视为无效特征而拒绝（Requirement 7.4）。"""
    feats = _base_features()
    feats["mystery"] = 1.0
    with pytest.raises(InvalidParameterError):
        predict_churn(_fv(feats))


def test_activity_optional() -> None:
    """仅含 RFM（无 activity）时仍应返回有界分数。"""
    feats = {"recency": 30.0, "frequency": 12.0, "monetary": 5_000.0}
    score = predict_churn(_fv(feats))
    assert 0.0 <= score <= 1.0
