"""企业微信入站网关测试（任务 27.1）。

覆盖 Requirement 21 的 21.1 / 21.2 / 21.3：

- 21.1：验签通过 → 还原消息、注入 tenant_id/thread_id 并转发 Supervisor，返回回复文本。
- 21.2：验签失败 → 拒绝处理、不转发决策中枢、记录被拒事件。
- 21.3：重复 msg_id → 幂等去重，返回首次结果且不重复触发 Supervisor。

全部测试在无网络/无真实企业微信密钥下运行：验签/解密经 :class:`FakeWeComCodec` 注入，
Supervisor 图使用记录调用次数的内存假实现。
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

import pytest

from app.wecom.gateway import (
    DEFAULT_REPLY_TEXT,
    EVENT_MESSAGE_DEDUPLICATED,
    EVENT_MESSAGE_FORWARDED,
    EVENT_SIGNATURE_REJECTED,
    FakeWeComCodec,
    InMemoryGatewayEventSink,
    InMemoryIdempotencyStore,
    WeComInboundGateway,
    WeComInboundMessage,
    WeComSignatureError,
)


# --------------------------------------------------------------------------- #
# 测试替身
# --------------------------------------------------------------------------- #
class RecordingSupervisorGraph:
    """记录调用次数与配置的伪 Supervisor 图，返回固定 final_answer。"""

    def __init__(self, reply: str | None = "已为您约好周六下午的洗护。") -> None:
        self.reply = reply
        self.calls: list[tuple[Mapping[str, Any], Mapping[str, Any] | None]] = []

    def invoke(
        self, state: Mapping[str, Any], config: Mapping[str, Any] | None = None
    ) -> Mapping[str, Any]:
        self.calls.append((dict(state), dict(config) if config else None))
        return {"final_answer": self.reply}


class RecordingReplySender:
    """记录出站推送的伪回复发送器。"""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    def send(self, tenant_id: str, external_user_id: str, text: str) -> None:
        self.sent.append((tenant_id, external_user_id, text))


def _message(msg_id: str = "msg-1", content: str = "想约周六下午给狗狗洗澡") -> WeComInboundMessage:
    return WeComInboundMessage(
        tenant_id="store-001",
        external_user_id="wx-user-abc",
        customer_id=None,
        content=content,
        msg_id=msg_id,
        received_at=datetime(2026, 1, 1, 10, 0, 0),
    )


def _raw(msg_id: str = "msg-1") -> dict[str, Any]:
    """模拟企业微信回调载荷（加密内容此处以明文占位，解密由伪编解码器完成）。"""
    return {"msg_signature": "sig", "timestamp": "1", "nonce": "n", "echostr": msg_id}


# --------------------------------------------------------------------------- #
# 21.1：验签通过 → 转发 Supervisor 并返回回复
# --------------------------------------------------------------------------- #
def test_valid_callback_forwards_to_supervisor_and_returns_reply() -> None:
    codec = FakeWeComCodec(valid=True, message=_message())
    graph = RecordingSupervisorGraph(reply="已为您约好周六下午的洗护。")
    events = InMemoryGatewayEventSink()
    sender = RecordingReplySender()
    gateway = WeComInboundGateway(
        codec, graph, event_sink=events, reply_sender=sender
    )

    reply = gateway.handle(_raw())

    assert reply == "已为您约好周六下午的洗护。"
    # 已转发 Supervisor 恰一次。
    assert len(graph.calls) == 1
    forwarded_state, config = graph.calls[0]
    # 注入了 tenant_id 与消息内容。
    assert forwarded_state["tenant_id"] == "store-001"
    assert forwarded_state["messages"] == [
        {"role": "user", "content": "想约周六下午给狗狗洗澡"}
    ]
    # 注入了会话 thread_id（复用多轮上下文）。
    assert config == {"configurable": {"thread_id": "wecom:store-001:wx-user-abc"}}
    # 出站回复被推送。
    assert sender.sent == [("store-001", "wx-user-abc", "已为您约好周六下午的洗护。")]
    # 记录了转发审计事件。
    assert any(e.event_type == EVENT_MESSAGE_FORWARDED for e in events.events)


def test_valid_callback_without_final_answer_falls_back_to_default_reply() -> None:
    codec = FakeWeComCodec(valid=True, message=_message())
    graph = RecordingSupervisorGraph(reply=None)
    gateway = WeComInboundGateway(codec, graph)

    reply = gateway.handle(_raw())

    assert reply == DEFAULT_REPLY_TEXT


# --------------------------------------------------------------------------- #
# 21.2：验签失败 → 拒绝、不转发、记录事件
# --------------------------------------------------------------------------- #
def test_bad_signature_rejects_and_does_not_forward() -> None:
    codec = FakeWeComCodec(valid=False, message=_message())
    graph = RecordingSupervisorGraph()
    events = InMemoryGatewayEventSink()
    gateway = WeComInboundGateway(codec, graph, event_sink=events)

    with pytest.raises(WeComSignatureError):
        gateway.handle(_raw())

    # 绝不进入决策中枢。
    assert graph.calls == []
    # 记录了被拒事件（Requirement 21.2）。
    assert len(events.events) == 1
    assert events.events[0].event_type == EVENT_SIGNATURE_REJECTED


# --------------------------------------------------------------------------- #
# 21.3：重复 msg_id → 幂等去重，返回首次结果且不重复触发
# --------------------------------------------------------------------------- #
def test_duplicate_msg_id_is_deduplicated() -> None:
    codec = FakeWeComCodec(valid=True, message=_message(msg_id="dup-1"))
    graph = RecordingSupervisorGraph(reply="首次处理结果")
    events = InMemoryGatewayEventSink()
    store = InMemoryIdempotencyStore()
    gateway = WeComInboundGateway(
        codec, graph, idempotency_store=store, event_sink=events
    )

    first = gateway.handle(_raw("dup-1"))
    second = gateway.handle(_raw("dup-1"))

    # 两次返回一致，且为首次处理的结果。
    assert first == "首次处理结果"
    assert second == "首次处理结果"
    # Supervisor 只被触发一次（未重复处理）。
    assert len(graph.calls) == 1
    # 第二次命中去重并记录去重事件。
    assert any(e.event_type == EVENT_MESSAGE_DEDUPLICATED for e in events.events)


def test_distinct_msg_ids_each_trigger_supervisor() -> None:
    """不同 msg_id 不应被误去重（去重仅针对相同 msg_id）。"""
    graph = RecordingSupervisorGraph(reply="ok")
    store = InMemoryIdempotencyStore()

    def factory(raw: Mapping[str, Any]) -> WeComInboundMessage:
        return _message(msg_id=str(raw["echostr"]))

    codec = FakeWeComCodec(valid=True, message_factory=factory)
    gateway = WeComInboundGateway(codec, graph, idempotency_store=store)

    gateway.handle(_raw("m-1"))
    gateway.handle(_raw("m-2"))

    assert len(graph.calls) == 2
