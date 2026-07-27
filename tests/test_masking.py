"""敏感数据脱敏工具单元测试（对应 Requirements 20.3 / 20.6，设计 Property 13）。

覆盖：手机号 / 身份证号 / 银行卡号的展示与存储脱敏、中间掩码不变量、
短值整体掩码、空值 / 非字符串拒绝、字典字段脱敏。属性测试（Property 13）由任务 7.4 单独实现。
"""

from __future__ import annotations

import pytest

from app.engines import InvalidParameterError
from app.tools import (
    MASK_CHAR,
    MaskMode,
    SensitiveKind,
    mask_bank_card,
    mask_fields,
    mask_national_id,
    mask_phone,
    mask_sensitive,
)


def test_mask_phone_display_keeps_prefix_suffix() -> None:
    """展示脱敏手机号保留前 3 后 4，中间掩码。"""
    assert mask_phone("13812341234") == "138****1234"


def test_mask_phone_storage_keeps_only_suffix() -> None:
    """存储脱敏手机号仅保留后 4 位。"""
    assert mask_phone("13812341234", MaskMode.STORAGE) == "*******1234"


def test_mask_national_id_display() -> None:
    """展示脱敏身份证号保留前 3 后 4，中间（含出生日期段）掩码。"""
    masked = mask_national_id("110105199003071234")
    assert masked == "110" + MASK_CHAR * 11 + "1234"


def test_mask_national_id_storage() -> None:
    """存储脱敏身份证号仅保留后 4 位。"""
    masked = mask_national_id("110105199003071234", MaskMode.STORAGE)
    assert masked == MASK_CHAR * 14 + "1234"


def test_mask_bank_card_display() -> None:
    """展示脱敏银行卡号保留前 4 后 4。"""
    assert mask_bank_card("6222021234567890") == "6222" + MASK_CHAR * 8 + "7890"


def test_mask_bank_card_storage() -> None:
    """存储脱敏银行卡号仅保留后 4 位。"""
    assert mask_bank_card("6222021234567890", MaskMode.STORAGE) == MASK_CHAR * 12 + "7890"


def test_masking_always_hides_middle_characters() -> None:
    """脱敏结果一定含掩码字符且不等于原文（中间部分被掩码）。"""
    for raw, fn in [
        ("13812341234", mask_phone),
        ("110105199003071234", mask_national_id),
        ("6222021234567890", mask_bank_card),
    ]:
        for mode in (MaskMode.DISPLAY, MaskMode.STORAGE):
            masked = fn(raw, mode)
            assert MASK_CHAR in masked
            assert masked != raw
            assert len(masked) == len(raw)


def test_short_value_is_fully_masked() -> None:
    """短于保留窗口的值整体掩码，绝不泄露原文片段。"""
    # 手机号存储窗口为后 4 位；值仅 4 位则整体掩码。
    assert mask_phone("1234", MaskMode.STORAGE) == MASK_CHAR * 4
    # 银行卡展示窗口前 4 后 4；值仅 8 位则整体掩码。
    assert mask_bank_card("12345678") == MASK_CHAR * 8


def test_strips_surrounding_whitespace() -> None:
    """脱敏前去除首尾空白。"""
    assert mask_phone("  13812341234  ") == "138****1234"


def test_mask_sensitive_dispatch() -> None:
    """统一入口按类型分派与专用函数一致。"""
    assert mask_sensitive("13812341234", SensitiveKind.PHONE) == mask_phone("13812341234")


@pytest.mark.parametrize("bad", ["", "   ", None, 12345])
def test_invalid_value_raises(bad: object) -> None:
    """空字符串 / 空白 / 非字符串输入应拒绝。"""
    with pytest.raises(InvalidParameterError):
        mask_phone(bad)  # type: ignore[arg-type]


def test_mask_fields_returns_new_dict_and_masks_targets() -> None:
    """字典脱敏返回新字典，仅掩码目标字段，不修改入参。"""
    record = {
        "name": "张三",
        "phone": "13812341234",
        "id_card": "110105199003071234",
        "note": "vip",
    }
    masked = mask_fields(
        record,
        {"phone": SensitiveKind.PHONE, "id_card": SensitiveKind.NATIONAL_ID},
    )
    assert masked["phone"] == "138****1234"
    assert masked["id_card"] == "110" + MASK_CHAR * 11 + "1234"
    # 非敏感字段保持不变。
    assert masked["name"] == "张三"
    assert masked["note"] == "vip"
    # 入参未被修改。
    assert record["phone"] == "13812341234"


def test_mask_fields_skips_missing_and_none() -> None:
    """缺失字段跳过；值为 None 的字段保持不变。"""
    record = {"phone": None}
    masked = mask_fields(
        record,
        {"phone": SensitiveKind.PHONE, "bank_card": SensitiveKind.BANK_CARD},
    )
    assert masked["phone"] is None
    assert "bank_card" not in masked
