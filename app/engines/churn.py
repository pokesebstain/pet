"""流失预测（Churn Prediction）纯函数算法层。

对应设计文档 6.2 节与 Requirement 7。核心函数 :func:`predict_churn` 依据客户
RFM（近度 / 频度 / 金额）与行为特征输出取值范围为 ``[0, 1]`` 的流失概率。

设计约束（形式化规格）：

- **前置条件**：``features`` 非空且包含 RFM 必需项；所有已知特征取值落在其有效范围内。
- **后置条件**：返回值 ``∈ [0, 1]``；纯函数、无副作用。
- **循环不变式**：特征归一化循环中，已处理特征均落在 ``[0, 1]``。
- **单调性**：其余特征相同、活跃度更高的客户，其 ``churn_score`` 单调不增。

MVP 采用**确定性加权逻辑回归**（无外部模型训练）。每个已知特征定义 [min, max]
有效区间与线性归一化，再经带符号权重求和并通过 sigmoid 映射到 (0, 1)，最终 clamp 到
``[0, 1]``。活跃类特征（``frequency`` / ``monetary`` / ``activity``）权重为负，保证活跃度
越高流失分数越低；``recency``（距上次消费天数）权重为正。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.engines.errors import InvalidParameterError
from app.models import FeatureVector

__all__ = [
    "predict_churn",
    "REQUIRED_FEATURES",
    "FEATURE_SPEC",
]


@dataclass(frozen=True)
class _FeatureSpec:
    """单个特征的有效区间与在逻辑回归中的带符号权重。

    ``weight`` 作用于归一化后的 ``[0, 1]`` 取值：正权重增大流失分数，负权重降低流失分数。
    """

    min_value: float
    max_value: float
    weight: float


# 已知特征规格。RFM 三项为必需；``activity`` 为可选的行为（活跃度）特征。
# 活跃类特征（frequency / monetary / activity）权重为负 → 活跃度越高流失分数越低（单调不增）。
FEATURE_SPEC: dict[str, _FeatureSpec] = {
    # 近度：距上次消费天数，越大越可能流失。
    "recency": _FeatureSpec(min_value=0.0, max_value=3650.0, weight=2.5),
    # 频度：累计消费次数，越大越不易流失。
    "frequency": _FeatureSpec(min_value=0.0, max_value=1000.0, weight=-2.5),
    # 金额：累计消费金额，越大越不易流失。
    "monetary": _FeatureSpec(min_value=0.0, max_value=1_000_000.0, weight=-2.0),
    # 活跃度：行为活跃度评分，越大越不易流失（可选）。
    "activity": _FeatureSpec(min_value=0.0, max_value=1000.0, weight=-2.5),
}

# RFM 必需特征：缺少任一项即拒绝。
REQUIRED_FEATURES: frozenset[str] = frozenset({"recency", "frequency", "monetary"})

# 偏置项：使 RFM 与活跃度均处于区间中点的客户流失分数居中。
_BIAS: float = 2.25


def _sigmoid(x: float) -> float:
    """数值稳定的 sigmoid，输出落在开区间 (0, 1)。"""
    if x >= 0.0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def _clamp(value: float, low: float, high: float) -> float:
    """将 ``value`` 夹紧到闭区间 ``[low, high]``。"""
    return max(low, min(high, value))


def predict_churn(features: FeatureVector) -> float:
    """预测客户流失概率，返回值 ``∈ [0, 1]``。

    Args:
        features: 客户特征向量，其 ``features`` 字典需包含 RFM 必需项
            （``recency`` / ``frequency`` / ``monetary``），可附带 ``activity`` 行为特征。

    Returns:
        取值范围为 ``[0, 1]``（含端点）的流失概率。

    Raises:
        InvalidParameterError: 特征向量为空（Requirement 7.3）；或缺少 RFM 必需项、
            存在取值越界或未知特征（Requirement 7.4）。
    """
    raw_features = features.features

    # Requirement 7.3：空特征向量拒绝。
    if not raw_features:
        raise InvalidParameterError("特征向量为空，无法计算流失分数")

    # Requirement 7.4：缺少 RFM 必需项拒绝。
    missing = REQUIRED_FEATURES - raw_features.keys()
    if missing:
        raise InvalidParameterError(
            f"缺少 RFM 必需特征：{', '.join(sorted(missing))}"
        )

    # 归一化循环：逐个校验并归一化，维护"已处理特征落在 [0,1]"的循环不变式。
    processed: dict[str, float] = {}
    for name, value in raw_features.items():
        spec = FEATURE_SPEC.get(name)
        # Requirement 7.4：未知特征视为无效特征。
        if spec is None:
            raise InvalidParameterError(f"未知特征：{name}")
        # Requirement 7.4：非有限值（NaN / inf）或越界均视为无效。
        if not math.isfinite(value) or value < spec.min_value or value > spec.max_value:
            raise InvalidParameterError(
                f"特征 {name}={value} 超出有效范围 "
                f"[{spec.min_value}, {spec.max_value}]"
            )
        normalized = (value - spec.min_value) / (spec.max_value - spec.min_value)
        # 循环不变式：已处理特征均落在 [0, 1]。
        assert 0.0 <= normalized <= 1.0, "归一化不变式被破坏"
        processed[name] = normalized

    # 加权逻辑回归打分（确定性；共享 Feature Store 特征）。
    logit = _BIAS + sum(
        FEATURE_SPEC[name].weight * normalized
        for name, normalized in processed.items()
    )
    score = _clamp(_sigmoid(logit), 0.0, 1.0)

    # 后置条件：流失分数落在 [0, 1]。
    assert 0.0 <= score <= 1.0
    return score
