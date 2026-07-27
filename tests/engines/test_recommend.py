"""推荐规则引擎单元测试（任务 4.5 / Requirements 13）。

覆盖：按 score 降序 + sku_id 升序稳定排序、缺货过滤、reason 可解释性、
越权拒绝、客户不存在、缺少 tenant_id、无候选返回空列表、最多 20 条。
属性测试见任务 4.6。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.engines.errors import (
    AuthorizationError,
    DataNotFoundError,
    InvalidParameterError,
)
from app.engines.recommend import (
    MAX_RECOMMENDATIONS,
    Recommendation,
    RuleCandidate,
    StaticRecommendationData,
    recommend,
)
from app.models import SKU, LifeStage, Pet

TENANT = "tenant-1"
CUSTOMER = "cust-1"


def _pet(pet_id: str = "pet-1", species: str = "dog", breed: str = "beagle") -> Pet:
    # 出生 36 个月前 → ADULT 阶段（中型犬）。
    birth = datetime.now(tz=timezone.utc) - timedelta(days=int(36 * 30.4375))
    return Pet(
        pet_id=pet_id,
        tenant_id=TENANT,
        owner_id=CUSTOMER,
        species=species,
        breed=breed,
        birth_date=birth,
        weight_kg=12.0,
    )


def _sku(sku_id: str, *, stock: float = 10.0, category: str = "food") -> SKU:
    return SKU(
        sku_id=sku_id,
        tenant_id=TENANT,
        name=f"name-{sku_id}",
        category=category,
        unit_cost=1.0,
        current_stock=stock,
        lead_time_days=5.0,
    )


def _provider(
    *,
    candidates: list[RuleCandidate] | None = None,
    stage: LifeStage = LifeStage.ADULT,
    churn: float = 0.4,
    customer_tenant: str | None = TENANT,
    pets: list[Pet] | None = None,
    alerts_by_pet: dict[str, list[str]] | None = None,
) -> StaticRecommendationData:
    return StaticRecommendationData(
        customer_tenants={CUSTOMER: customer_tenant} if customer_tenant else {},
        pets_by_customer={CUSTOMER: pets if pets is not None else [_pet()]},
        alerts_by_pet=alerts_by_pet or {},
        churn_by_customer={CUSTOMER: churn},
        candidates_by_stage={stage: candidates or []},
    )


# --- 排序与稳定性 (Requirement 13.1) --------------------------------------


def test_sorted_by_score_desc() -> None:
    cands = [
        RuleCandidate(sku=_sku("a"), relevance=0.2),
        RuleCandidate(sku=_sku("b"), relevance=0.9),
        RuleCandidate(sku=_sku("c"), relevance=0.5),
    ]
    result = recommend(CUSTOMER, {"tenant_id": TENANT}, provider=_provider(candidates=cands))
    scores = [r.score for r in result]
    assert scores == sorted(scores, reverse=True)
    assert [r.sku_id for r in result] == ["b", "c", "a"]


def test_tie_break_by_sku_id_asc() -> None:
    # 相同 relevance / churn → 相同 score，应按 sku_id 升序。
    cands = [
        RuleCandidate(sku=_sku("z"), relevance=0.5),
        RuleCandidate(sku=_sku("m"), relevance=0.5),
        RuleCandidate(sku=_sku("a"), relevance=0.5),
    ]
    result = recommend(CUSTOMER, {"tenant_id": TENANT}, provider=_provider(candidates=cands))
    assert [r.sku_id for r in result] == ["a", "m", "z"]


def test_score_within_unit_interval() -> None:
    cands = [RuleCandidate(sku=_sku("a"), relevance=1.0)]
    result = recommend(CUSTOMER, {"tenant_id": TENANT}, provider=_provider(candidates=cands, churn=1.0))
    assert result
    for r in result:
        assert 0.0 <= r.score <= 1.0


def test_max_twenty_items() -> None:
    cands = [RuleCandidate(sku=_sku(f"s{i:03d}"), relevance=i / 30.0) for i in range(30)]
    result = recommend(CUSTOMER, {"tenant_id": TENANT}, provider=_provider(candidates=cands))
    assert len(result) == MAX_RECOMMENDATIONS


# --- 缺货过滤 (Requirement 13.2) ------------------------------------------


def test_excludes_out_of_stock() -> None:
    cands = [
        RuleCandidate(sku=_sku("in", stock=5.0), relevance=0.5),
        RuleCandidate(sku=_sku("zero", stock=0.0), relevance=0.9),
        RuleCandidate(sku=_sku("neg", stock=1.0), relevance=0.9),
    ]
    provider = _provider(candidates=cands)
    # 覆盖为负可售库存（如超卖预留）→ 应被排除。
    provider.available_stock_by_sku["neg"] = -2.0
    result = recommend(CUSTOMER, {"tenant_id": TENANT}, provider=provider)
    assert [r.sku_id for r in result] == ["in"]


def test_available_stock_override_excludes() -> None:
    provider = _provider(candidates=[RuleCandidate(sku=_sku("a", stock=100.0), relevance=0.5)])
    # 覆盖可售库存为 0（如全部被预留）→ 应被排除。
    provider.available_stock_by_sku["a"] = 0.0
    result = recommend(CUSTOMER, {"tenant_id": TENANT}, provider=provider)
    assert result == []


# --- reason 可解释 (Requirement 13.3) -------------------------------------


def test_reason_references_all_signals() -> None:
    cands = [RuleCandidate(sku=_sku("a", stock=7.0, category="dental"), relevance=0.8, matched_alerts=("dental_tartar",))]
    provider = _provider(candidates=cands, churn=0.62, alerts_by_pet={"pet-1": ["dental_tartar"]})
    result = recommend(CUSTOMER, {"tenant_id": TENANT}, provider=provider)
    reason = result[0].reason
    assert "adult" in reason  # 生命阶段
    assert "dental_tartar" in reason  # 健康预警
    assert "0.62" in reason  # 流失分数
    assert "7" in reason  # 可售库存


# --- 越权与存在性 (Requirement 13.4) --------------------------------------


def test_authorization_error_on_tenant_mismatch() -> None:
    provider = _provider(candidates=[RuleCandidate(sku=_sku("a"))], customer_tenant="other-tenant")
    with pytest.raises(AuthorizationError):
        recommend(CUSTOMER, {"tenant_id": TENANT}, provider=provider)


def test_missing_customer_raises_not_found() -> None:
    provider = _provider(candidates=[RuleCandidate(sku=_sku("a"))], customer_tenant=None)
    with pytest.raises(DataNotFoundError):
        recommend(CUSTOMER, {"tenant_id": TENANT}, provider=provider)


def test_missing_tenant_in_context_raises() -> None:
    provider = _provider(candidates=[RuleCandidate(sku=_sku("a"))])
    with pytest.raises(InvalidParameterError):
        recommend(CUSTOMER, {}, provider=provider)


# --- 无候选 (Requirement 13.5) --------------------------------------------


def test_no_candidates_returns_empty() -> None:
    result = recommend(CUSTOMER, {"tenant_id": TENANT}, provider=_provider(candidates=[]))
    assert result == []


def test_no_pets_returns_empty() -> None:
    provider = _provider(candidates=[RuleCandidate(sku=_sku("a"))], pets=[])
    result = recommend(CUSTOMER, {"tenant_id": TENANT}, provider=provider)
    assert result == []


# --- 去重：同一 SKU 保留最高分 -------------------------------------------


def test_duplicate_sku_keeps_highest_score() -> None:
    pet_a = _pet(pet_id="pet-a")
    pet_b = _pet(pet_id="pet-b")
    # 两只宠物同为 ADULT，命中同一 SKU；其中一只有健康预警命中 → 分数更高。
    shared = _sku("shared", stock=5.0)
    provider = StaticRecommendationData(
        customer_tenants={CUSTOMER: TENANT},
        pets_by_customer={CUSTOMER: [pet_a, pet_b]},
        alerts_by_pet={"pet-a": ["skin"]},
        churn_by_customer={CUSTOMER: 0.3},
        candidates_by_stage={
            LifeStage.ADULT: [
                RuleCandidate(sku=shared, relevance=0.5, matched_alerts=("skin",)),
            ]
        },
    )
    result = recommend(CUSTOMER, {"tenant_id": TENANT}, provider=provider)
    ids = [r.sku_id for r in result]
    assert ids.count("shared") == 1


def test_recommendation_score_out_of_range_rejected() -> None:
    with pytest.raises(InvalidParameterError):
        Recommendation(sku_id="a", score=1.5, reason="x")
