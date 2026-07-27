"""敏感数据脱敏工具（对应 Requirements 20.3 / 20.6，设计 Correctness Property 13）。

对手机号、身份证号、银行卡号等敏感字段，在**展示**（display）与**存储**（storage）
两条路径上对中间部分字符进行掩码，仅保留必要的前缀 / 后缀以便识别与对账。

设计要点：
- 纯函数、无副作用、可独立单元测试；不做任何 I/O。
- 掩码始终发生：当有效字符数不足以同时保留前后缀时，整体掩码，绝不泄露原文。
- 展示路径保留较多可识别字符（便于用户核对），存储路径保留更少字符（最小化留存）。
- 保证不变量：对任一含敏感字段的展示 / 存储，掩码结果中一定含掩码字符且不等于原文
  （前提是原文含至少一个可掩码的中间字符）。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.engines.errors import InvalidParameterError

#: 用于替换中间字符的掩码符号。
MASK_CHAR = "*"


class MaskMode(str, Enum):
    """脱敏模式。

    - ``DISPLAY``：展示脱敏，保留较多可识别字符（Requirement 20.3）。
    - ``STORAGE``：存储脱敏，保留更少字符以最小化敏感信息留存（Requirement 20.6）。
    """

    DISPLAY = "display"
    STORAGE = "storage"


class SensitiveKind(str, Enum):
    """支持脱敏的敏感数据类型。"""

    PHONE = "phone"
    NATIONAL_ID = "national_id"
    BANK_CARD = "bank_card"


@dataclass(frozen=True)
class _MaskSpec:
    """某类敏感数据在展示 / 存储两种模式下保留的前后缀长度。"""

    display_prefix: int
    display_suffix: int
    storage_prefix: int
    storage_suffix: int

    def window(self, mode: MaskMode) -> tuple[int, int]:
        if mode is MaskMode.DISPLAY:
            return self.display_prefix, self.display_suffix
        return self.storage_prefix, self.storage_suffix


# 各敏感类型的保留窗口配置。
# 展示模式保留较多字符便于核对；存储模式仅保留尾部少量字符用于对账。
_SPECS: dict[SensitiveKind, _MaskSpec] = {
    # 手机号：展示 138****1234；存储 *******1234。
    SensitiveKind.PHONE: _MaskSpec(3, 4, 0, 4),
    # 身份证号：展示保留省市段前缀与尾号；存储仅保留尾 4 位。
    SensitiveKind.NATIONAL_ID: _MaskSpec(3, 4, 0, 4),
    # 银行卡号：展示保留前 4 后 4；存储仅保留尾 4 位。
    SensitiveKind.BANK_CARD: _MaskSpec(4, 4, 0, 4),
}


def _mask_middle(
    value: str,
    keep_prefix: int,
    keep_suffix: int,
    mask_char: str = MASK_CHAR,
) -> str:
    """对字符串中间部分进行掩码，保留给定长度的前缀与后缀。

    当有效字符数不足以同时保留前后缀（``len <= keep_prefix + keep_suffix``）时，
    整体掩码，避免泄露任何原文片段。

    :raises InvalidParameterError: ``value`` 非字符串或去除首尾空白后为空。
    """
    if not isinstance(value, str):
        raise InvalidParameterError("敏感数据必须为字符串")
    if keep_prefix < 0 or keep_suffix < 0:
        raise InvalidParameterError("保留前后缀长度不能为负")

    stripped = value.strip()
    if stripped == "":
        raise InvalidParameterError("敏感数据不能为空")

    n = len(stripped)
    if n <= keep_prefix + keep_suffix:
        return mask_char * n

    masked_len = n - keep_prefix - keep_suffix
    suffix = stripped[n - keep_suffix:] if keep_suffix > 0 else ""
    return stripped[:keep_prefix] + mask_char * masked_len + suffix


def _mask_by_kind(value: str, kind: SensitiveKind, mode: MaskMode) -> str:
    spec = _SPECS[kind]
    prefix, suffix = spec.window(mode)
    return _mask_middle(value, prefix, suffix)


def mask_phone(value: str, mode: MaskMode = MaskMode.DISPLAY) -> str:
    """脱敏手机号，掩码中间字符。

    展示模式保留前 3 位与后 4 位（如 ``138****1234``）；
    存储模式仅保留后 4 位（如 ``*******1234``）。
    """
    return _mask_by_kind(value, SensitiveKind.PHONE, mode)


def mask_national_id(value: str, mode: MaskMode = MaskMode.DISPLAY) -> str:
    """脱敏身份证号，掩码中间字符（含出生日期段）。

    展示模式保留前 3 位与后 4 位；存储模式仅保留后 4 位。
    """
    return _mask_by_kind(value, SensitiveKind.NATIONAL_ID, mode)


def mask_bank_card(value: str, mode: MaskMode = MaskMode.DISPLAY) -> str:
    """脱敏银行卡号，掩码中间字符。

    展示模式保留前 4 位与后 4 位；存储模式仅保留后 4 位。
    """
    return _mask_by_kind(value, SensitiveKind.BANK_CARD, mode)


def mask_sensitive(
    value: str,
    kind: SensitiveKind,
    mode: MaskMode = MaskMode.DISPLAY,
) -> str:
    """按敏感数据类型进行脱敏的统一入口。

    :param value: 原始敏感字符串。
    :param kind: 敏感数据类型（手机号 / 身份证号 / 银行卡号）。
    :param mode: 脱敏模式（展示 / 存储）。
    :raises InvalidParameterError: ``kind`` 不受支持或 ``value`` 无效。
    """
    if not isinstance(kind, SensitiveKind):
        raise InvalidParameterError(f"不支持的敏感数据类型: {kind!r}")
    return _mask_by_kind(value, kind, mode)


def mask_fields(
    record: dict[str, object],
    field_kinds: dict[str, SensitiveKind],
    mode: MaskMode = MaskMode.DISPLAY,
) -> dict[str, object]:
    """对记录（dict）中指定的敏感字段进行脱敏，返回新字典（不修改入参）。

    仅处理 ``field_kinds`` 中列出且在 ``record`` 中存在的字段；值为 ``None`` 的字段
    保持不变。非字符串值会先转为字符串再脱敏。

    :param record: 原始记录。
    :param field_kinds: 字段名到敏感类型的映射。
    :param mode: 脱敏模式（展示 / 存储）。
    """
    masked: dict[str, object] = dict(record)
    for field, kind in field_kinds.items():
        if field not in masked:
            continue
        value = masked[field]
        if value is None:
            continue
        masked[field] = mask_sensitive(str(value), kind, mode)
    return masked
