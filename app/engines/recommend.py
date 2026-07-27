"""推荐规则引擎（Recommendation Rules）。

对应设计文档 6.6 节的 ``recommend`` 实现与 Requirement 13。结合宠物**生命阶段**、
**健康预警**、客户**流失分数**与 SKU**库存可售性**生成可解释、可售的商品推荐。

设计要点（见 design.md 6.6、Property 7 与 requirements.md Requirement 13）：

前置条件（Preconditions）
    - 客户存在且属于当前请求上下文的租户（``customer.tenant_id == context["tenant_id"]``）。

后置条件（Postconditions）
    - 返回列表按 ``score`` 降序；``score`` 并列时按 ``sku_id`` 升序稳定排序。
    - 每条 ``score ∈ [0, 1]``；列表最多 20 条。
    - 不包含可售库存 ≤ 0 的缺货 SKU。
    - 每条推荐附带引用生命阶段 / 健康 / 流失分数 / 库存可售性的可解释 ``reason``。
    - 无满足条件的候选时返回空列表。

错误处理
    - ``context`` 缺少 ``tenant_id`` → :class:`InvalidParameterError`。
    - 客户不存在 → :class:`DataNotFoundError`。
    - 客户 ``tenant_id`` 与上下文不一致 → :class:`AuthorizationError`（越权，不返回任何推荐）。

为便于在无真实数据库的情况下测试，宠物 / 候选 SKU / 健康预警 / 流失分数 / 可售库存
均通过注入的 :class:`RecommendationDataProvider` 获取（对应设计中的 ``get_pets`` /
``rules_engine`` / ``rank_model``）。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from app.engines.errors import (
    AuthorizationError,
    DataNotFoundError,
    InvalidParameterError,
)
from app.engines.lifestage import judge_life_stage
from app.models import SKU, LifeStage, Pet

__all__ = [
    "Recommendation",
    "RuleCandidate",
    "RecommendationDataProvider",
    "StaticRecommendationData",
    "recommend",
    "MAX_RECOMMENDATIONS",
]

# 返回推荐条数上限（Requirement 13.1）。
MAX_RECOMMENDATIONS: int = 20

# rank 打分各信号权重（和为 1，保证 score ∈ [0, 1]）。
_W_RELEVANCE: float = 0.5  # 规则层生命阶段 / 品类相关度
_W_HEALTH: float = 0.3     # 是否命中健康预警
_W_CHURN: float = 0.2      # 客户流失分数（越高越优先做挽留推荐）


def _clamp01(value: float) -> float:
    """将取值夹紧到闭区间 ``[0, 1]``。"""
    return max(0.0, min(1.0, value))


@dataclass(frozen=True)
class Recommendation:
    """单条商品推荐结果。

    ``score`` 取值范围为 ``[0, 1]``；``reason`` 为引用生命阶段 / 健康 / 流失 / 库存的
    可解释理由。
    """

    sku_id: str
    score: float
    reason: str
    category: str = ""
    life_stage: LifeStage | None = None

    def __post_init__(self) -> None:
        # 后置条件：score 落在 [0, 1]（Requirement 13.1）。
        if not (0.0 <= self.score <= 1.0):
            raise InvalidParameterError(
                f"score 必须落在 [0, 1]：{self.score}"
            )


@dataclass(frozen=True)
class RuleCandidate:
    """规则引擎产出的候选项（对应设计中 ``rules_engine`` 的输出）。

    ``relevance`` ∈ [0, 1] 表示该 SKU 与当前生命阶段 / 品类的匹配强度；
    ``matched_alerts`` 为该候选命中的健康预警标识。
    """

    sku: SKU
    relevance: float = 1.0
    matched_alerts: tuple[str, ...] = ()


@runtime_checkable
class RecommendationDataProvider(Protocol):
    """推荐引擎所需的数据提供者。

    抽象掉数据来源（客户 / 宠物主数据、规则引擎、Feature Store、库存等），
    使算法层无需连接真实数据库即可测试。
    """

    def get_customer_tenant(self, customer_id: str) -> str | None:
        """返回客户所属租户 ``tenant_id``；客户不存在时返回 ``None``。"""
        ...

    def get_pets(self, customer_id: str) -> Sequence[Pet]:
        """返回该客户名下的宠物列表（可为空）。"""
        ...

    def get_health_alerts(self, pet: Pet) -> Sequence[str]:
        """返回该宠物当前的健康预警标识列表（可为空）。"""
        ...

    def get_churn_score(self, customer_id: str) -> float:
        """返回客户流失分数 ``∈ [0, 1]``。"""
        ...

    def get_rule_candidates(
        self, stage: LifeStage, health_alerts: Sequence[str]
    ) -> Sequence[RuleCandidate]:
        """按生命阶段与健康预警匹配候选 SKU（对应 ``rules_engine``）。"""
        ...

    def get_available_stock(self, sku: SKU) -> float:
        """返回该 SKU 的可售库存（可能扣除预留量）。"""
        ...


@dataclass(frozen=True)
class StaticRecommendationData:
    """基于静态取值的 :class:`RecommendationDataProvider` 实现。

    便于单元 / 属性测试直接注入固定的客户租户、宠物、健康预警、流失分数与候选规则，
    无需连接真实数据库。
    """

    customer_tenants: dict[str, str] = field(default_factory=dict)
    pets_by_customer: dict[str, list[Pet]] = field(default_factory=dict)
    alerts_by_pet: dict[str, list[str]] = field(default_factory=dict)
    churn_by_customer: dict[str, float] = field(default_factory=dict)
    # (stage, frozenset(health_alerts)) 简化为按 stage 提供候选；健康命中在候选内标注。
    candidates_by_stage: dict[LifeStage, list[RuleCandidate]] = field(
        default_factory=dict
    )
    # 可售库存覆盖表；缺省回退到 ``sku.current_stock``。
    available_stock_by_sku: dict[str, float] = field(default_factory=dict)

    def get_customer_tenant(self, customer_id: str) -> str | None:
        return self.customer_tenants.get(customer_id)

    def get_pets(self, customer_id: str) -> Sequence[Pet]:
        return self.pets_by_customer.get(customer_id, [])

    def get_health_alerts(self, pet: Pet) -> Sequence[str]:
        return self.alerts_by_pet.get(pet.pet_id, [])

    def get_churn_score(self, customer_id: str) -> float:
        return self.churn_by_customer.get(customer_id, 0.0)

    def get_rule_candidates(
        self, stage: LifeStage, health_alerts: Sequence[str]
    ) -> Sequence[RuleCandidate]:
        return self.candidates_by_stage.get(stage, [])

    def get_available_stock(self, sku: SKU) -> float:
        return self.available_stock_by_sku.get(sku.sku_id, sku.current_stock)


def _rank_score(relevance: float, has_health_match: bool, churn_score: float) -> float:
    """确定性 rank 打分（对应设计中的 ``rank_model``），输出 ``∈ [0, 1]``。

    综合规则相关度、健康预警命中与客户流失分数，权重之和为 1，因此结果落在 ``[0, 1]``。
    """
    relevance = _clamp01(relevance)
    churn = _clamp01(churn_score)
    health_signal = 1.0 if has_health_match else 0.0
    score = (
        _W_RELEVANCE * relevance
        + _W_HEALTH * health_signal
        + _W_CHURN * churn
    )
    return _clamp01(score)


def _build_reason(
    stage: LifeStage,
    category: str,
    matched_alerts: Sequence[str],
    churn_score: float,
    available_stock: float,
) -> str:
    """构造引用生命阶段 / 健康 / 流失 / 库存的可解释理由（Requirement 13.3）。"""
    stage_label = stage.value
    if matched_alerts:
        health_part = f"命中健康预警 {', '.join(matched_alerts)}"
    else:
        health_part = "无相关健康预警"
    return (
        f"适配 {stage_label} 生命阶段的 {category or '通用'} 品类；"
        f"{health_part}；"
        f"客户流失分数 {_clamp01(churn_score):.2f}；"
        f"可售库存 {available_stock:g}"
    )


def recommend(
    customer_id: str,
    context: dict,
    *,
    provider: RecommendationDataProvider,
) -> list[Recommendation]:
    """结合生命阶段 / 健康 / 流失 / 库存生成可解释、可售的商品推荐。

    Args:
        customer_id: 目标客户标识。
        context: 请求上下文，必须包含 ``tenant_id``。
        provider: 数据提供者（注入以便脱离真实数据库测试）。

    Returns:
        按 ``score`` 降序（并列按 ``sku_id`` 升序稳定排序）的推荐列表，最多 20 条；
        不含缺货 SKU；无候选时返回空列表。

    Raises:
        InvalidParameterError: ``context`` 缺少 ``tenant_id``。
        DataNotFoundError: 客户不存在。
        AuthorizationError: 客户 ``tenant_id`` 与上下文不一致（越权）。
    """
    # --- 校验上下文租户 ---
    context_tenant = context.get("tenant_id") if isinstance(context, dict) else None
    if context_tenant is None or not str(context_tenant).strip():
        raise InvalidParameterError("请求上下文缺少 tenant_id")

    # --- 校验客户存在与归属租户（前置条件 / Requirement 13.4）---
    customer_tenant = provider.get_customer_tenant(customer_id)
    if customer_tenant is None:
        raise DataNotFoundError(f"客户不存在：{customer_id}")
    if customer_tenant != context_tenant:
        # 越权：不返回任何推荐（Requirement 13.4）。
        raise AuthorizationError(
            f"客户 {customer_id} 不属于当前租户 {context_tenant}"
        )

    churn_score = provider.get_churn_score(customer_id)

    # --- 逐宠物生成候选，过滤缺货，按 sku_id 去重保留最高分 ---
    best_by_sku: dict[str, Recommendation] = {}
    for pet in provider.get_pets(customer_id):
        stage = judge_life_stage(pet.species, pet.breed, _age_months(pet))
        health_alerts = list(provider.get_health_alerts(pet))

        for candidate in provider.get_rule_candidates(stage, health_alerts):
            sku = candidate.sku
            # Requirement 13.2：排除可售库存 ≤ 0 的缺货 SKU。
            available = provider.get_available_stock(sku)
            if available <= 0:
                continue

            has_health_match = bool(candidate.matched_alerts)
            score = _rank_score(candidate.relevance, has_health_match, churn_score)
            reason = _build_reason(
                stage=stage,
                category=sku.category,
                matched_alerts=candidate.matched_alerts,
                churn_score=churn_score,
                available_stock=available,
            )
            rec = Recommendation(
                sku_id=sku.sku_id,
                score=score,
                reason=reason,
                category=sku.category,
                life_stage=stage,
            )

            # 同一 SKU 可能由多只宠物 / 多条规则命中，保留最高分的一条。
            existing = best_by_sku.get(sku.sku_id)
            if existing is None or rec.score > existing.score:
                best_by_sku[sku.sku_id] = rec

    if not best_by_sku:
        # Requirement 13.5：无候选返回空列表。
        return []

    # 稳定排序：score 降序，score 并列按 sku_id 升序（Requirement 13.1）。
    ordered = sorted(
        best_by_sku.values(),
        key=lambda r: (-r.score, r.sku_id),
    )
    return ordered[:MAX_RECOMMENDATIONS]


def _age_months(pet: Pet) -> float:
    """由宠物出生日期推算月龄（近似 30.4375 天/月），并 clamp 到生命阶段合法上限。"""
    from datetime import datetime, timezone

    birth = pet.birth_date
    now = datetime.now(tz=birth.tzinfo) if birth.tzinfo else datetime.now(tz=timezone.utc)
    if birth.tzinfo is None:
        now = datetime.now()
    delta_days = (now - birth).days
    months = max(0.0, delta_days / 30.4375)
    # judge_life_stage 要求 age_months ∈ [0, 360]。
    return min(months, 360.0)
