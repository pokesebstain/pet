"""客户 LTV 预测（Customer Lifetime Value）纯函数算法层。

对应设计文档 6.3 节与 Requirement 6。核心函数 :func:`predict_ltv` 依据客户特征与
复用 :func:`app.engines.churn.predict_churn` 得到的留存概率，按月累加折现，输出未来
``horizon_months`` 个月内的客户净价值。

设计约束（形式化规格）：

- **前置条件**：``horizon_months`` 为 1..120（含端点）的整数；客户特征可获取且数据充足。
- **后置条件**：返回值 ``≥ 0``；对同一客户，``horizon_months`` 增大时 LTV 单调不减。
- **循环不变式**：按月累加循环中，``ltv ≥ 0`` 恒成立。

单调不减由构造保证：每月增量 = ``purchase_freq * avg_value * survivalᵐ * discount_factor(m)``，
其中各因子均非负（``purchase_freq ≥ 0``、``avg_value ≥ 0``、``survival ∈ [0, 1]``、
``discount_factor(m) > 0``），故随 ``horizon_months`` 增大只会累加非负项。

为便于在无实时数据库的情况下测试，客户特征可通过 ``features`` 参数直接注入，或通过实现了
:class:`CustomerFeatureProvider` 协议的 ``provider`` 注入。
"""

from __future__ import annotations

import math
from typing import Protocol, runtime_checkable

from app.engines.churn import FEATURE_SPEC, REQUIRED_FEATURES, predict_churn
from app.engines.errors import DataNotFoundError, InvalidParameterError
from app.models import FeatureVector

__all__ = [
    "predict_ltv",
    "CustomerFeatureProvider",
    "REQUIRED_LTV_FEATURES",
    "MAX_HORIZON_MONTHS",
    "DEFAULT_HORIZON_MONTHS",
    "DEFAULT_MONTHLY_DISCOUNT_RATE",
]

#: ``horizon_months`` 的上界（含）（Requirement 6.1 / 6.3）。
MAX_HORIZON_MONTHS = 120

#: ``horizon_months`` 默认值。
DEFAULT_HORIZON_MONTHS = 24

#: 月度折现率（约合年化 ~12.7%）。折现因子 = 1 / (1 + r)^m > 0。
DEFAULT_MONTHLY_DISCOUNT_RATE = 0.01

#: 平均月订单数特征键（对应伪代码 ``purchase_freq``）。
AVG_MONTHLY_ORDERS_KEY = "avg_monthly_orders"

#: 平均订单金额特征键（对应伪代码 ``avg_value``）。
AVG_ORDER_VALUE_KEY = "avg_order_value"

#: LTV 计算必需的特征键：缺失任一项视为数据不足。
REQUIRED_LTV_FEATURES: frozenset[str] = frozenset(
    {AVG_MONTHLY_ORDERS_KEY, AVG_ORDER_VALUE_KEY}
)


@runtime_checkable
class CustomerFeatureProvider(Protocol):
    """客户特征提供者协议。

    实现者根据 ``customer_id`` 返回该客户的特征向量；客户不存在时返回 ``None``。
    """

    def get_features(self, customer_id: str) -> FeatureVector | None:  # pragma: no cover - 协议声明
        ...


def predict_ltv(
    customer_id: str,
    horizon_months: int = DEFAULT_HORIZON_MONTHS,
    features: FeatureVector | None = None,
    *,
    provider: CustomerFeatureProvider | None = None,
    monthly_discount_rate: float = DEFAULT_MONTHLY_DISCOUNT_RATE,
) -> float:
    """预测客户未来 ``horizon_months`` 个月内的净价值（LTV）。

    Args:
        customer_id: 客户标识（非空）。
        horizon_months: 预测跨度（月），必须为整数且 1 ≤ horizon_months ≤ 120。
        features: 可选，直接注入的客户特征向量。
        provider: 可选，客户特征提供者；当未直接提供 ``features`` 时用于查询。
        monthly_discount_rate: 月度折现率（≥ 0），用于计算逐月折现因子。

    Returns:
        取值 ``≥ 0`` 的 LTV；对同一客户，``horizon_months`` 越大结果单调不减。

    Raises:
        InvalidParameterError: ``customer_id`` 为空、``horizon_months`` 非整数或越界、
            ``monthly_discount_rate`` 非法，或客户特征取值非法（Requirement 6.3）。
        DataNotFoundError: 客户不存在或历史交易数据不足（Requirement 6.6）。
    """
    _validate_customer_id(customer_id)
    _validate_horizon(horizon_months)
    _validate_discount_rate(monthly_discount_rate)

    resolved = _resolve_features(customer_id, features, provider)

    purchase_freq = _require_feature(resolved, AVG_MONTHLY_ORDERS_KEY)
    avg_value = _require_feature(resolved, AVG_ORDER_VALUE_KEY)

    # 复用流失模型得到留存概率；predict_churn 仅接受其已知特征键，故先投影出 churn 子向量。
    # predict_churn 保证返回值 ∈ [0, 1]，并对越界特征值抛 InvalidParameterError。
    churn_features = _project_churn_features(resolved)
    retain_prob = 1.0 - predict_churn(churn_features)
    # 数值兜底：确保留存概率严格落在 [0, 1]，使 survival 因子非负。
    retain_prob = min(1.0, max(0.0, retain_prob))

    ltv = 0.0
    for m in range(1, horizon_months + 1):
        # 循环不变式：ltv ≥ 0 恒成立（累加的每一项均非负）。
        assert ltv >= 0.0, "LTV 累加不变式被破坏"
        survival = retain_prob**m
        discount = _discount_factor(m, monthly_discount_rate)
        ltv += purchase_freq * avg_value * survival * discount

    # 后置条件：LTV ≥ 0。
    assert ltv >= 0.0
    return ltv


def _validate_customer_id(customer_id: str) -> None:
    if not isinstance(customer_id, str) or not customer_id.strip():
        raise InvalidParameterError("customer_id 不能为空")


def _validate_horizon(horizon_months: int) -> None:
    # bool 是 int 的子类，需显式排除，避免 True/False 被当作 1/0。
    if isinstance(horizon_months, bool) or not isinstance(horizon_months, int):
        raise InvalidParameterError("horizon_months 必须为整数")
    if horizon_months <= 0 or horizon_months > MAX_HORIZON_MONTHS:
        raise InvalidParameterError(
            f"horizon_months 必须在 (0, {MAX_HORIZON_MONTHS}] 之间，实际为 {horizon_months}"
        )


def _validate_discount_rate(monthly_discount_rate: float) -> None:
    if isinstance(monthly_discount_rate, bool) or not isinstance(
        monthly_discount_rate, (int, float)
    ):
        raise InvalidParameterError("monthly_discount_rate 必须为数值")
    if not math.isfinite(monthly_discount_rate) or monthly_discount_rate < 0:
        raise InvalidParameterError("monthly_discount_rate 必须为非负有限数值")


def _resolve_features(
    customer_id: str,
    features: FeatureVector | None,
    provider: CustomerFeatureProvider | None,
) -> FeatureVector:
    """解析客户特征向量。

    优先使用直接注入的 ``features``；否则经 ``provider`` 查询。客户不存在或无可用来源
    视为数据缺失（Requirement 6.6）。
    """
    resolved = features
    if resolved is None and provider is not None:
        resolved = provider.get_features(customer_id)

    if resolved is None:
        raise DataNotFoundError(f"客户 {customer_id} 不存在或历史交易数据不足")

    # 数据不足：缺少 LTV 计算必需特征或复用 churn 所需的 RFM 必需特征。
    required = REQUIRED_LTV_FEATURES | REQUIRED_FEATURES
    missing = required - resolved.features.keys()
    if missing:
        raise DataNotFoundError(
            f"客户 {customer_id} 历史交易数据不足，缺少特征：{', '.join(sorted(missing))}"
        )
    return resolved


def _project_churn_features(features: FeatureVector) -> FeatureVector:
    """投影出仅含 churn 已知特征键的子向量，供 :func:`predict_churn` 复用。

    LTV 专属特征（如 ``avg_monthly_orders``）会被流失模型视为未知特征而拒绝，
    因此这里仅保留 :data:`app.engines.churn.FEATURE_SPEC` 中定义的特征。
    """
    subset = {
        name: value
        for name, value in features.features.items()
        if name in FEATURE_SPEC
    }
    return features.model_copy(update={"features": subset})


def _require_feature(features: FeatureVector, key: str) -> float:
    """读取并校验非负有限的特征值。"""
    value = features.features[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InvalidParameterError(f"特征 {key} 必须为数值")
    fvalue = float(value)
    if not math.isfinite(fvalue) or fvalue < 0:
        raise InvalidParameterError(f"特征 {key}={value} 必须为非负有限数值")
    return fvalue


def _discount_factor(month: int, monthly_discount_rate: float) -> float:
    """逐月折现因子 = 1 / (1 + r)^m，恒为正。"""
    return 1.0 / ((1.0 + monthly_discount_rate) ** month)
