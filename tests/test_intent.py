"""Cloud LLM 公号宠主意图白名单测试（Requirement 26.2）。"""

from __future__ import annotations

import pytest

from app.agents.intent import CloudLLMIntentClassifier
from app.llm.client import CloudLLMClient, RestrictedTemplateQuery


class _CannedTransport:
    def __init__(self, response: str) -> None:
        self._response = response

    def generate(self, prompt: str, *, timeout: float) -> str:  # noqa: ARG002
        return self._response


def _public_result(response: str):
    client = CloudLLMClient(
        transport=_CannedTransport(response),
        template_query=RestrictedTemplateQuery(),
        max_retries=0,
    )
    return CloudLLMIntentClassifier(client).classify_public(
        [("user", "公众号宠主消息")]
    )


@pytest.mark.parametrize("intent", ["reception", "health"])
def test_classify_public_keeps_only_pet_owner_service_intents(intent: str) -> None:
    """**Validates: Requirements 26.2**"""
    result = _public_result(f'{{"intent": "{intent}", "confidence": 0.95}}')

    assert result.intent == intent
    assert result.confidence == pytest.approx(0.95)


@pytest.mark.parametrize("intent", ["analysis", "operation", "supply", "marketing"])
def test_classify_public_rejects_internal_business_intents(intent: str) -> None:
    """真实 CloudLLMIntentClassifier 公号路径不得接受内部标签。"""
    result = _public_result(f'{{"intent": "{intent}", "confidence": 0.99}}')

    assert result.intent is None
    assert result.confidence == pytest.approx(0.99)


def test_classify_public_clamps_confidence_and_safely_degrades_invalid_json() -> None:
    """置信度边界与非 JSON 响应都不会误路由到宠主服务以外。"""
    bounded = _public_result('{"intent": "reception", "confidence": 4}')
    malformed = _public_result("not-json")

    assert bounded.intent == "reception"
    assert bounded.confidence == 1.0
    assert malformed.intent is None
    assert malformed.confidence == 0.0
