"""基于 Cloud_LLM 的意图识别（提示工程 / 少样本）。

对应 Requirement 1.1（10 秒内经 Cloud_LLM 结合提示工程与少样本识别意图）与
Requirement 1.7（无法归类或置信度低于阈值时请用户澄清 / 重述）。

范围约束（重要）：意图识别经**云端 LLM（通义千问 / 智谱 GLM）**结合提示工程 /
少样本实现，**不引入任何模型微调**。可测试性：Cloud_LLM 调用被
:class:`~app.llm.client.CloudLLMClient` 及其可注入的 :class:`~app.llm.client.LLMTransport`
抽象隔离，测试可注入伪实现，在无真实网络的情况下模拟识别结果与各类降级。
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from app.llm.client import CloudLLMClient, FewShotExample, ResponseSource

__all__ = [
    "EXPERT_INTENTS",
    "DEFAULT_CONFIDENCE_THRESHOLD",
    "IntentResult",
    "IntentClassifier",
    "CloudLLMIntentClassifier",
    "INTENT_SYSTEM_PROMPT",
    "INTENT_FEW_SHOTS",
]

#: 专家 Agent 意图标签（Requirement 1.2）。除既有五类外，新增 ``reception``（企业微信
#: 接待预约意图，任务 27.3），使 Supervisor 复用既有 Cloud_LLM 分类器即可将预约 / 洗护
#: 类消息路由到 :class:`~app.agents.reception.ReceptionAgent`（Requirement 21.1）。
EXPERT_INTENTS: tuple[str, ...] = (
    "analysis",
    "operation",
    "health",
    "supply",
    "marketing",
    "reception",
)

#: 低置信度阈值：识别置信度低于该值视为无法可靠归类（Requirement 1.7）。
DEFAULT_CONFIDENCE_THRESHOLD: float = 0.6


@dataclass(frozen=True)
class IntentResult:
    """意图识别结果。

    Attributes:
        intent: 五类意图之一；无法归类时为 ``None``。
        confidence: 识别置信度，取值范围 [0, 1]。
    """

    intent: str | None
    confidence: float


@runtime_checkable
class IntentClassifier(Protocol):
    """意图识别协议：将对话历史映射为 :class:`IntentResult`。

    通过协议解耦，使 Supervisor 在测试中可注入伪分类器，而生产环境使用
    :class:`CloudLLMIntentClassifier`（Cloud_LLM 驱动）。
    """

    def classify(
        self, messages: Sequence, *, timeout: float | None = None
    ) -> IntentResult:  # pragma: no cover - 协议声明
        """识别对话历史对应的意图；无法归类时 ``intent=None``。"""
        ...


# --- 提示工程 / 少样本 -------------------------------------------------------

INTENT_SYSTEM_PROMPT: str = (
    "你是宠物店运营平台的意图路由器。请将用户请求归类到以下六类之一："
    "analysis（数据分析/查询/洞察）、operation（客户运营/流失召回/LTV决策）、"
    "health（宠物健康趋势/预警/转介绍）、supply（库存/补货/需求预测/定价）、"
    "marketing（营销/社区内容生成）、reception（企业微信接待/洗护预约/约洗澡/改约/查排期）。"
    "仅输出 JSON：{\"intent\": <六类之一或 unknown>, \"confidence\": <0到1之间的小数>}。"
    "无法可靠归类时 intent 输出 unknown。"
)

#: 每类意图各一条少样本示例，帮助 Cloud_LLM 稳定归类。
INTENT_FEW_SHOTS: tuple[FewShotExample, ...] = (
    FewShotExample(
        user="上个月哪些高价值客户在流失?",
        assistant='{"intent": "analysis", "confidence": 0.95}',
    ),
    FewShotExample(
        user="给这批流失客户发8折券预计能挽回多少?",
        assistant='{"intent": "operation", "confidence": 0.92}',
    ),
    FewShotExample(
        user="这只狗最近体重下降,健康有没有问题?",
        assistant='{"intent": "health", "confidence": 0.93}',
    ),
    FewShotExample(
        user="狗粮下个月要补多少货?",
        assistant='{"intent": "supply", "confidence": 0.94}',
    ),
    FewShotExample(
        user="帮我写一篇猫咪养护的社区推文",
        assistant='{"intent": "marketing", "confidence": 0.9}',
    ),
    FewShotExample(
        user="想约周六下午给狗狗洗澡",
        assistant='{"intent": "reception", "confidence": 0.92}',
    ),
)


class CloudLLMIntentClassifier:
    """经 Cloud_LLM（提示工程 / 少样本）实现的意图识别器。

    调用 :class:`~app.llm.client.CloudLLMClient` 生成结构化 JSON 结果并解析。任一降级
    （模板 / 重述）或解析失败均视为无法可靠归类，返回 ``intent=None`` 且置信度 0，
    由 Supervisor 据此请用户澄清（Requirement 1.7）。
    """

    def __init__(
        self,
        client: CloudLLMClient,
        *,
        system_prompt: str = INTENT_SYSTEM_PROMPT,
        few_shots: Sequence[FewShotExample] = INTENT_FEW_SHOTS,
    ) -> None:
        self._client = client
        self._system_prompt = system_prompt
        self._few_shots = tuple(few_shots)

    def classify(
        self, messages: Sequence, *, timeout: float | None = None
    ) -> IntentResult:
        user_input = _latest_user_text(messages)
        if not user_input:
            return IntentResult(intent=None, confidence=0.0)

        response = self._client.complete(
            user_input,
            system_prompt=self._system_prompt,
            examples=self._few_shots,
        )
        # 任一降级（模板 / 重述）都无法提供可靠意图，交由澄清路径处理。
        if response.source is not ResponseSource.LLM:
            return IntentResult(intent=None, confidence=0.0)
        return _parse_intent(response.text)


# --- 辅助函数 ----------------------------------------------------------------


def _latest_user_text(messages: Sequence) -> str:
    """从对话历史中提取最近一条用户文本。

    兼容多种消息形态：``(role, text)`` 元组、``{"role": ..., "content": ...}`` 字典、
    以及带 ``.content`` 属性的对象；无法解析时回退为其字符串形式。
    """
    for message in reversed(list(messages)):
        text = _message_text(message)
        if text:
            return text
    return ""


def _message_text(message: object) -> str:
    if isinstance(message, tuple) and len(message) == 2:
        return str(message[1])
    if isinstance(message, dict):
        return str(message.get("content", ""))
    content = getattr(message, "content", None)
    if content is not None:
        return str(content)
    return str(message) if message is not None else ""


def _parse_intent(text: str) -> IntentResult:
    """解析 Cloud_LLM 返回的意图 JSON；解析失败视为无法归类。"""
    payload = _extract_json(text)
    if payload is None:
        return IntentResult(intent=None, confidence=0.0)

    raw_intent = payload.get("intent")
    intent = str(raw_intent).strip().lower() if raw_intent is not None else ""
    if intent not in EXPERT_INTENTS:
        # unknown 或非法标签：无法可靠归类。
        return IntentResult(intent=None, confidence=_coerce_confidence(payload))

    return IntentResult(intent=intent, confidence=_coerce_confidence(payload))


def _extract_json(text: str) -> dict | None:
    """从文本中提取首个 JSON 对象；无有效对象时返回 ``None``。"""
    if not text:
        return None
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except (ValueError, TypeError):
        pass
    # 回退：截取首个花括号包裹的子串再尝试解析。
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            parsed = json.loads(text[start : end + 1])
            return parsed if isinstance(parsed, dict) else None
        except (ValueError, TypeError):
            return None
    return None


def _coerce_confidence(payload: dict) -> float:
    """将置信度字段安全地夹取到 [0, 1]；缺失或非法时为 0。"""
    try:
        value = float(payload.get("confidence", 0.0))
    except (ValueError, TypeError):
        return 0.0
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value
