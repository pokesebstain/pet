"""客户 LTV 引擎装配（对应设计文档组件 4 `LTVEngine` 与 6.3 / Requirement 6）。

本模块将算法层的 :func:`app.engines.ltv.predict_ltv` 与
:func:`app.engines.churn.predict_churn` 组合为面向业务的 :class:`LTVEngine`，
并通过注入的 :class:`~app.engines.ltv.CustomerFeatureProvider` 接入客户特征来源，
从而无需实时数据库即可测试。

对外方法：
- :meth:`LTVEngine.compute_ltv`：预测客户 LTV（复用任务 3.5 的
  :func:`~app.engines.ltv.predict_ltv`，含 ``horizon_months`` 参数校验与
  数据缺失判定；Requirement 6.1 / 6.3 / 6.6）。
- :meth:`LTVEngine.compute_customer_value`：一次性返回单个客户的 LTV、Churn_Score
  与所属分层（复用同一份已解析特征向量，避免重复查询）。
- :meth:`LTVEngine.segment_customers`：对一组客户基于 LTV 与 Churn_Score 分层，
  每个客户被分到 高价值 / 成长 / 流失风险 三者中的**恰好一个**（Requirement 6.4）。

**分层规则（形式化规格）**：

分层按有序等级刻画 —— 流失风险(0) < 成长(1) < 高价值(2)。规则：

1. IF ``churn_score > churn_risk_threshold`` → 流失风险（无论 LTV 高低）。
2. ELIF ``ltv >= ltv_high_threshold``（且 churn 不超阈值）→ 高价值。
3. ELSE → 成长。

该规则对每个客户产生**恰好一个**分层（三个分支互斥且完备）。

**单调性（Requirement 6.5）**：若客户 A 的 ``ltv_A >= ltv_B`` 且
``churn_A <= churn_B``，则 A 的分层等级不低于 B。证明按 B 的分层分类：

- B 为流失风险(0)：A 等级 ≥ 0 恒成立。
- B 为成长(1)：则 ``churn_B <= C`` 且 ``ltv_B < H``。由 ``churn_A <= churn_B <= C``
  知 A 非流失风险，故 A ∈ {成长, 高价值}，等级 ≥ 1。
- B 为高价值(2)：则 ``churn_B <= C`` 且 ``ltv_B >= H``。由 ``churn_A <= churn_B <= C``
  与 ``ltv_A >= ltv_B >= H`` 知 A 亦为高价值，等级 = 2。

故规则对（LTV 非降、Churn 非增）方向弱单调，满足"LTV 更高且 Churn_Score 更低者
分层不低于对方"。
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from app.engines.churn import predict_churn
from app.engines.errors import InvalidParameterError
from app.engines.ltv import (
    CustomerFeatureProvider,
    DEFAULT_HORIZON_MONTHS,
    DEFAULT_MONTHLY_DISCOUNT_RATE,
    _project_churn_features,
    _resolve_features,
    predict_ltv,
)
from app.models import FeatureVector

__all__ = [
    "LTVEngine",
    "Segment",
    "InMemoryCustomerFeatureProvider",
    "SEGMENT_HIGH_VALUE",
    "SEGMENT_GROWTH",
    "SEGMENT_CHURN_RISK",
    "DEFAULT_LTV_HIGH_THRESHOLD",
    "DEFAULT_CHURN_RISK_THRESHOLD",
]

#: 高价值分层标签。
SEGMENT_HIGH_VALUE = "高价值"

#: 成长分层标签。
SEGMENT_GROWTH = "成长"

#: 流失风险分层标签。
SEGMENT_CHURN_RISK = "流失风险"

#: 分层有序等级：流失风险(0) < 成长(1) < 高价值(2)。数值越大分层越高。
_SEGMENT_RANK: dict[str, int] = {
    SEGMENT_CHURN_RISK: 0,
    SEGMENT_GROWTH: 1,
    SEGMENT_HIGH_VALUE: 2,
}

#: 判定"高价值"的 LTV 阈值默认值（可在构造时覆盖）。
DEFAULT_LTV_HIGH_THRESHOLD = 1000.0

#: 判定"流失风险"的 Churn_Score 阈值默认值（严格大于该值即流失风险）。
DEFAULT_CHURN_RISK_THRESHOLD = 0.5


@dataclass(frozen=True)
class Segment:
    """单个客户的分层结果。

    ``segment`` 为 高价值 / 成长 / 流失风险 之一；``tier_rank`` 为其有序等级
    （0=流失风险，1=成长，2=高价值），便于比较与断言单调性。
    """

    customer_id: str
    ltv: float
    churn_score: float
    segment: str
    tier_rank: int


class InMemoryCustomerFeatureProvider:
    """基于内存字典的 :class:`~app.engines.ltv.CustomerFeatureProvider` 假实现。

    供测试与无数据库场景使用：按 ``customer_id`` 返回登记的特征向量，缺失时返回 ``None``
    （由算法层判定为客户不存在或数据不足）。
    """

    def __init__(self, features_by_customer: dict[str, FeatureVector] | None = None) -> None:
        self._features: dict[str, FeatureVector] = dict(features_by_customer or {})

    def add(self, customer_id: str, features: FeatureVector) -> None:
        """登记 / 覆盖某客户的特征向量。"""
        self._features[customer_id] = features

    def get_features(self, customer_id: str) -> FeatureVector | None:
        return self._features.get(customer_id)


class LTVEngine:
    """客户 LTV 引擎：组合 LTV 预测与流失预测，并据此对客户分层。"""

    def __init__(
        self,
        provider: CustomerFeatureProvider,
        *,
        ltv_high_threshold: float = DEFAULT_LTV_HIGH_THRESHOLD,
        churn_risk_threshold: float = DEFAULT_CHURN_RISK_THRESHOLD,
        monthly_discount_rate: float = DEFAULT_MONTHLY_DISCOUNT_RATE,
    ) -> None:
        """构造引擎。

        Args:
            provider: 客户特征提供者（对应 Feature Store / 业务库查询）。
            ltv_high_threshold: 判定"高价值"的 LTV 下界（≥ 0）。
            churn_risk_threshold: 判定"流失风险"的 Churn_Score 阈值，取值 [0, 1)。
            monthly_discount_rate: 传递给 :func:`~app.engines.ltv.predict_ltv` 的月度折现率。

        Raises:
            InvalidParameterError: 阈值取值非法。
        """
        self._validate_thresholds(ltv_high_threshold, churn_risk_threshold)
        self._provider = provider
        self._ltv_high_threshold = float(ltv_high_threshold)
        self._churn_risk_threshold = float(churn_risk_threshold)
        self._monthly_discount_rate = monthly_discount_rate

    # ------------------------------------------------------------------ #
    # LTV 预测
    # ------------------------------------------------------------------ #
    def compute_ltv(
        self,
        customer_id: str,
        horizon_months: int = DEFAULT_HORIZON_MONTHS,
    ) -> float:
        """预测客户未来 ``horizon_months`` 个月的 LTV（≥ 0）。

        直接复用算法层 :func:`~app.engines.ltv.predict_ltv`，因此完全沿用任务 3.5 的
        参数校验（``horizon_months`` 越界 / 非整数抛
        :class:`~app.engines.errors.InvalidParameterError`）与数据缺失判定
        （客户不存在或历史交易数据不足抛
        :class:`~app.engines.errors.DataNotFoundError`）。

        Raises:
            InvalidParameterError: ``horizon_months`` 非法（Requirement 6.3）。
            DataNotFoundError: 客户不存在或数据不足（Requirement 6.6）。
        """
        return predict_ltv(
            customer_id,
            horizon_months,
            provider=self._provider,
            monthly_discount_rate=self._monthly_discount_rate,
        )

    # ------------------------------------------------------------------ #
    # 单客户价值与分层
    # ------------------------------------------------------------------ #
    def compute_customer_value(
        self,
        customer_id: str,
        horizon_months: int = DEFAULT_HORIZON_MONTHS,
    ) -> Segment:
        """计算单个客户的 LTV、Churn_Score 及其所属分层。

        为避免重复查询，先解析一次客户特征向量，再据其分别计算 LTV 与流失分数，
        最后按分层规则得到 高价值 / 成长 / 流失风险 之一。

        Raises:
            InvalidParameterError: ``horizon_months`` 非法。
            DataNotFoundError: 客户不存在或数据不足。
        """
        features = _resolve_features(customer_id, None, self._provider)
        ltv = predict_ltv(
            customer_id,
            horizon_months,
            features=features,
            monthly_discount_rate=self._monthly_discount_rate,
        )
        churn_score = predict_churn(_project_churn_features(features))
        label, rank = self._classify(ltv, churn_score)
        return Segment(
            customer_id=customer_id,
            ltv=ltv,
            churn_score=churn_score,
            segment=label,
            tier_rank=rank,
        )

    def segment_customers(
        self,
        customer_ids: Iterable[str],
        horizon_months: int = DEFAULT_HORIZON_MONTHS,
    ) -> list[Segment]:
        """对一组客户分层。

        每个客户被分配到 高价值 / 成长 / 流失风险 三者中的**恰好一个**
        （Requirement 6.4）；分层对（LTV 非降、Churn 非增）方向弱单调
        （Requirement 6.5）。结果顺序与输入 ``customer_ids`` 一致。

        Args:
            customer_ids: 待分层的客户标识集合（当前租户范围内）。
            horizon_months: LTV 预测跨度（月），沿用算法层校验。

        Returns:
            与输入对应的 :class:`Segment` 列表。

        Raises:
            InvalidParameterError: ``horizon_months`` 非法。
            DataNotFoundError: 任一客户不存在或数据不足。
        """
        return [
            self.compute_customer_value(customer_id, horizon_months)
            for customer_id in customer_ids
        ]

    # ------------------------------------------------------------------ #
    # 内部辅助
    # ------------------------------------------------------------------ #
    def _classify(self, ltv: float, churn_score: float) -> tuple[str, int]:
        """按分层规则返回 (分层标签, 有序等级)。

        规则（互斥且完备，保证恰好一个分层）：
        1. churn_score > 阈值 → 流失风险；
        2. 否则 ltv ≥ 高价值阈值 → 高价值；
        3. 否则 → 成长。
        """
        if churn_score > self._churn_risk_threshold:
            label = SEGMENT_CHURN_RISK
        elif ltv >= self._ltv_high_threshold:
            label = SEGMENT_HIGH_VALUE
        else:
            label = SEGMENT_GROWTH
        return label, _SEGMENT_RANK[label]

    @staticmethod
    def _validate_thresholds(
        ltv_high_threshold: float, churn_risk_threshold: float
    ) -> None:
        if (
            isinstance(ltv_high_threshold, bool)
            or not isinstance(ltv_high_threshold, (int, float))
            or ltv_high_threshold < 0
        ):
            raise InvalidParameterError("ltv_high_threshold 必须为非负数值")
        if (
            isinstance(churn_risk_threshold, bool)
            or not isinstance(churn_risk_threshold, (int, float))
            or not (0.0 <= churn_risk_threshold < 1.0)
        ):
            raise InvalidParameterError("churn_risk_threshold 必须落在 [0, 1) 区间")
