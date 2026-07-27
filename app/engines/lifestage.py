"""生命阶段判定（Life-Stage Judgement）。

对应设计文档 6.1 节的 ``judge_life_stage`` 纯函数实现，依据物种、品种、月龄
判定宠物处于 PUPPY（幼年）/ ADULT（成年）/ SENIOR（老年）中的哪个阶段。

设计要点（见 design.md 6.1 与 requirements.md Requirement 10）：

前置条件（Preconditions）
    - ``species`` ∈ 已知物种集合；``age_months`` ∈ [0, 360]（单位：月）。
    - 品种体型分级表（size_class）与阈值表已加载（见本模块常量）。

后置条件（Postconditions）
    - 返回值 ∈ {PUPPY, ADULT, SENIOR}。
    - 同一物种体型越大（成年标准体重越大）的犬型 SENIOR 起始阈值越早
      （大型犬 SENIOR 阈值 ≤ 小型犬 SENIOR 阈值）。
    - 对同一物种/品种，随 ``age_months`` 递增，返回阶段按
      PUPPY→ADULT→SENIOR 单调不回退。
    - 纯函数，无副作用。

错误处理
    - ``age_months`` < 0 或 > 360 → :class:`ParameterInvalidError`。
    - 缺少物种或品种、物种不受支持 → :class:`ParameterInvalidError`。
    - 品种未收录但物种受支持 → 回退到该物种的默认体型阈值判定。
"""

from __future__ import annotations

import math

from app.core.errors import ParameterInvalidError
from app.models import LifeStage

# ``age_months`` 的合法闭区间（单位：月）。360 月 = 30 年，覆盖犬猫寿命上限。
MIN_AGE_MONTHS: float = 0.0
MAX_AGE_MONTHS: float = 360.0

# 体型分级取值。
SIZE_SMALL = "small"
SIZE_MEDIUM = "medium"
SIZE_LARGE = "large"

# 阈值表：species -> size_class -> (puppy_months, senior_months)。
# 语义：age < puppy_months → PUPPY；puppy_months ≤ age < senior_months → ADULT；
#       age ≥ senior_months → SENIOR。
#
# 犬型遵循"体型越大衰老越早"：large 的 senior 起始阈值 ≤ small 的 senior 起始阈值。
THRESHOLDS: dict[str, dict[str, tuple[float, float]]] = {
    "dog": {
        SIZE_SMALL: (12.0, 132.0),   # 小型犬约 11 岁进入老年
        SIZE_MEDIUM: (12.0, 108.0),  # 中型犬约 9 岁进入老年
        SIZE_LARGE: (15.0, 84.0),    # 大型犬约 7 岁进入老年（衰老最早）
    },
    "cat": {
        SIZE_SMALL: (10.0, 120.0),
        SIZE_MEDIUM: (10.0, 120.0),  # 猫约 10 岁进入老年
        SIZE_LARGE: (10.0, 108.0),
    },
}

# 品种 → 体型分级表。键均以小写规范化后匹配。
BREED_SIZE_CLASS: dict[str, dict[str, str]] = {
    "dog": {
        "chihuahua": SIZE_SMALL,
        "pomeranian": SIZE_SMALL,
        "poodle": SIZE_SMALL,
        "toy poodle": SIZE_SMALL,
        "shih tzu": SIZE_SMALL,
        "beagle": SIZE_MEDIUM,
        "bulldog": SIZE_MEDIUM,
        "border collie": SIZE_MEDIUM,
        "cocker spaniel": SIZE_MEDIUM,
        "labrador": SIZE_LARGE,
        "labrador retriever": SIZE_LARGE,
        "golden retriever": SIZE_LARGE,
        "german shepherd": SIZE_LARGE,
        "great dane": SIZE_LARGE,
        "rottweiler": SIZE_LARGE,
    },
    "cat": {
        "siamese": SIZE_SMALL,
        "persian": SIZE_MEDIUM,
        "british shorthair": SIZE_MEDIUM,
        "domestic shorthair": SIZE_MEDIUM,
        "maine coon": SIZE_LARGE,
        "ragdoll": SIZE_LARGE,
    },
}

# 物种默认体型：未收录品种回退到该物种默认阈值判定。
SPECIES_DEFAULT_SIZE: dict[str, str] = {
    "dog": SIZE_MEDIUM,
    "cat": SIZE_MEDIUM,
}


def _normalize(value: str) -> str:
    """去除首尾空白并转小写，用于物种/品种查表。"""
    return value.strip().lower()


def lookup_size_class(species: str, breed: str) -> str:
    """查表得到 (species, breed) 的体型分级。

    品种未收录时回退到该物种的默认体型分级。调用方需保证 ``species`` 已受支持。
    """
    species_key = _normalize(species)
    breed_key = _normalize(breed)
    breed_table = BREED_SIZE_CLASS.get(species_key, {})
    return breed_table.get(breed_key, SPECIES_DEFAULT_SIZE[species_key])


def judge_life_stage(species: str, breed: str, age_months: float) -> LifeStage:
    """根据物种/品种/月龄判定生命阶段。

    参数
        species: 物种（如 ``"dog"`` / ``"cat"``），大小写不敏感。
        breed: 品种；未收录品种回退到物种默认阈值。
        age_months: 月龄，必须落在 [0, 360] 闭区间内。

    返回
        :class:`~app.models.LifeStage` 之一（PUPPY / ADULT / SENIOR）。

    异常
        :class:`ParameterInvalidError`:
            当物种或品种缺失、物种不受支持，或 ``age_months`` 越界/非法时抛出。
    """
    # --- 校验物种与品种存在且非空 ---
    if species is None or not str(species).strip():
        raise ParameterInvalidError("缺少物种（species）")
    if breed is None or not str(breed).strip():
        raise ParameterInvalidError("缺少品种（breed）")

    # --- 校验物种受支持 ---
    species_key = _normalize(species)
    if species_key not in THRESHOLDS:
        raise ParameterInvalidError(f"不支持的物种：{species}")

    # --- 校验月龄合法（数值、非 NaN/Inf、落在 [0, 360]）---
    # 排除 bool（bool 是 int 的子类，语义上不是合法月龄）。
    if isinstance(age_months, bool) or not isinstance(age_months, (int, float)):
        raise ParameterInvalidError(f"age_months 必须为数值：{age_months!r}")
    if math.isnan(age_months) or math.isinf(age_months):
        raise ParameterInvalidError(f"age_months 必须为有限数值：{age_months!r}")
    if age_months < MIN_AGE_MONTHS or age_months > MAX_AGE_MONTHS:
        raise ParameterInvalidError(
            f"age_months 必须落在 [{MIN_AGE_MONTHS}, {MAX_AGE_MONTHS}]：{age_months}"
        )

    # --- 查体型分级与阈值（品种未收录时回退物种默认）---
    size = lookup_size_class(species_key, breed)
    puppy_limit, senior_start = THRESHOLDS[species_key][size]

    # --- 阶段判定 ---
    if age_months < puppy_limit:
        return LifeStage.PUPPY
    if age_months < senior_start:
        return LifeStage.ADULT
    return LifeStage.SENIOR
