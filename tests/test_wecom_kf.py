"""微信客服（``kf_msg_or_event``）通知拉取与回复的单元测试（设计文档 14.9 补充）。

覆盖：

- :class:`WeComCryptoCodec`：正确区分普通消息与微信客服通知（``is_kf_notification`` /
  ``decode_kf_notification``），且不影响既有 :meth:`decode` 行为。
- :class:`WeComInboundGateway`：收到 kf 通知时路由到 ``kf_processor``；未注入时优雅跳过
  （不报错、记录审计事件），不误当作空文本消息转发 Supervisor。
- :class:`KfSyncMessageClient`：``sync_msg`` 翻页拉取、令牌失效重试。
- :class:`KfSyncMessageProcessor`：拉取 → 幂等去重 → 转发 Supervisor → 经 ``kf/send_msg``
  回复的完整流程；单条消息故障不中断整批处理。

全部测试在无真实网络 / 企业微信环境下运行：HTTP 传输 / access_token / Supervisor 图均
经内存伪实现注入。
"""

from __future__ import annotations

import base64
from typing import Any

import pytest

from app.wecom.crypto import WeComCryptoCodec, build_kf_notification_envelope
from app.wecom.gateway import (
    EVENT_KF_NOTIFICATION_PROCESSED,
    EVENT_KF_NOTIFICATION_SKIPPED,
    FakeWeComCodec,
    InMemoryGatewayEventSink,
    WeComInboundGateway,
    WeComKfNotification,
)
from app.wecom.kf import (
    InMemoryCursorStore,
    KfMessageSendStrategy,
    KfSyncedMessage,
    KfSyncError,
    KfSyncMessageClient,
    KfSyncMessageProcessor,
)
from app.wecom.sender import WeComAccessTokenManager, WeComMessageSender, WeComSendError

CORP_ID = "wwtestcorpid001"
TOKEN = "petops-callback-token"
ENCODING_AES_KEY = base64.b64encode(b"petops-wecom-aes-256-seed-32bytes!"[:32]).decode()[:43]
TENANT = "store_88"
OPEN_KF_ID = "wk-kf-1"


def _make_codec() -> WeComCryptoCodec:
    return WeComCryptoCodec(
        corp_id=CORP_ID, token=TOKEN, encoding_aes_key=ENCODING_AES_KEY,
        default_tenant_id=TENANT,
    )


# --------------------------------------------------------------------------- #
# WeComCryptoCodec：kf 通知识别与解码
# --------------------------------------------------------------------------- #
def test_codec_detects_kf_notification_and_decodes_it() -> None:
    codec = _make_codec()
    raw = build_kf_notification_envelope(
        codec, open_kf_id=OPEN_KF_ID, kf_token="sync-token-abc"
    )

    assert codec.is_kf_notification(raw) is True

    notification = codec.decode_kf_notification(raw)
    assert notification.tenant_id == TENANT
    assert notification.open_kf_id == OPEN_KF_ID
    assert notification.token == "sync-token-abc"


def test_codec_regular_message_is_not_kf_notification() -> None:
    from app.wecom.crypto import build_encrypted_envelope

    codec = _make_codec()
    raw = build_encrypted_envelope(
        codec, from_user="wx-user", content="想约洗澡", msg_id="msg-1"
    )

    assert codec.is_kf_notification(raw) is False
    # 既有 decode() 行为不受影响。
    message = codec.decode(raw)
    assert message.content == "想约洗澡"


# --------------------------------------------------------------------------- #
# 网关路由：kf 通知 → kf_processor（或优雅跳过）
# --------------------------------------------------------------------------- #
class _RecordingSupervisorGraph:
    def __init__(self, reply: str = "已处理") -> None:
        self.invocations: list[dict[str, Any]] = []
        self._reply = reply

    def invoke(self, state: Any, config: Any = None) -> dict[str, Any]:
        self.invocations.append({"state": dict(state), "config": config})
        return {"final_answer": self._reply}


class _RecordingKfProcessor:
    def __init__(self) -> None:
        self.processed: list[WeComKfNotification] = []

    def process(self, notification: WeComKfNotification) -> None:
        self.processed.append(notification)


def test_gateway_routes_kf_notification_to_processor() -> None:
    notification = WeComKfNotification(
        tenant_id=TENANT, open_kf_id=OPEN_KF_ID, token="tok"
    )
    codec = FakeWeComCodec(valid=True, kf_notification=notification)
    graph = _RecordingSupervisorGraph()
    processor = _RecordingKfProcessor()
    events = InMemoryGatewayEventSink()
    gateway = WeComInboundGateway(
        codec, graph, kf_processor=processor, event_sink=events
    )

    gateway.handle({"msg_signature": "x", "timestamp": "1", "nonce": "1", "body": "<xml/>"})

    assert processor.processed == [notification]
    # 普通消息路径（Supervisor 转发）不应被误触发。
    assert graph.invocations == []
    assert any(e.event_type == EVENT_KF_NOTIFICATION_PROCESSED for e in events.events)


def test_gateway_skips_kf_notification_gracefully_without_processor() -> None:
    notification = WeComKfNotification(
        tenant_id=TENANT, open_kf_id=OPEN_KF_ID, token="tok"
    )
    codec = FakeWeComCodec(valid=True, kf_notification=notification)
    graph = _RecordingSupervisorGraph()
    events = InMemoryGatewayEventSink()
    # 未注入 kf_processor。
    gateway = WeComInboundGateway(codec, graph, event_sink=events)

    reply = gateway.handle(
        {"msg_signature": "x", "timestamp": "1", "nonce": "1", "body": "<xml/>"}
    )

    assert reply  # 返回兜底文案，不报错。
    assert graph.invocations == []
    assert any(e.event_type == EVENT_KF_NOTIFICATION_SKIPPED for e in events.events)


# --------------------------------------------------------------------------- #
# KfSyncMessageClient：sync_msg 拉取 / 令牌失效重试
# --------------------------------------------------------------------------- #
class _FakeTransport:
    """记录调用并按队列顺序返回预设响应的伪 HTTP 传输。"""

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self._responses = list(responses)
        self.post_calls: list[dict[str, Any]] = []

    def get_json(self, url, *, params=None, timeout=None):  # noqa: ANN001
        return {"errcode": 0, "access_token": "tok-1", "expires_in": 7200}

    def post_json(self, url, *, params=None, json_body=None, timeout=None):  # noqa: ANN001
        self.post_calls.append({"url": url, "params": dict(params or {}), "body": json_body})
        return self._responses.pop(0)


def _token_manager(transport: _FakeTransport) -> WeComAccessTokenManager:
    return WeComAccessTokenManager(
        corp_id=CORP_ID, secret="sekret", transport=transport
    )


def test_sync_msg_parses_text_messages_and_cursor() -> None:
    transport = _FakeTransport(
        [
            {
                "errcode": 0,
                "next_cursor": "cur-1",
                "has_more": 0,
                "msg_list": [
                    {
                        "msgid": "m1",
                        "open_kfid": OPEN_KF_ID,
                        "external_userid": "wm-1",
                        "send_time": 100,
                        "origin": 3,
                        "msgtype": "text",
                        "text": {"content": "想约洗澡"},
                    }
                ],
            }
        ]
    )
    client = KfSyncMessageClient(token_manager=_token_manager(transport), transport=transport)

    batch = client.sync_msg(open_kf_id=OPEN_KF_ID, kf_token="tok")

    assert len(batch.messages) == 1
    msg = batch.messages[0]
    assert msg.text_content == "想约洗澡"
    assert msg.is_from_customer is True
    assert batch.next_cursor == "cur-1"
    assert batch.has_more is False


def test_sync_msg_raises_on_error_errcode() -> None:
    transport = _FakeTransport([{"errcode": 88888, "errmsg": "boom"}])
    client = KfSyncMessageClient(token_manager=_token_manager(transport), transport=transport)

    with pytest.raises(KfSyncError):
        client.sync_msg(open_kf_id=OPEN_KF_ID)


def test_sync_msg_retries_once_on_token_expired() -> None:
    transport = _FakeTransport(
        [
            {"errcode": 42001, "errmsg": "token expired"},
            {"errcode": 0, "next_cursor": "", "has_more": 0, "msg_list": []},
        ]
    )
    client = KfSyncMessageClient(token_manager=_token_manager(transport), transport=transport)

    batch = client.sync_msg(open_kf_id=OPEN_KF_ID)

    assert batch.messages == ()
    assert len(transport.post_calls) == 2


# --------------------------------------------------------------------------- #
# KfSyncMessageProcessor：完整拉取 → 转发 → 回复流程
# --------------------------------------------------------------------------- #
class _QueuedSyncClient:
    """按队列顺序返回预设 KfSyncBatch 的伪客户端（跳过真实 HTTP）。"""

    def __init__(self, batches: list[Any]) -> None:
        self._batches = list(batches)
        self.calls: list[dict[str, Any]] = []

    def sync_msg(self, *, open_kf_id: str, cursor: str = "", kf_token: str = ""):
        self.calls.append({"open_kf_id": open_kf_id, "cursor": cursor, "kf_token": kf_token})
        return self._batches.pop(0)


class _RecordingReplySender:
    def __init__(self, *, fail_for: set[str] | None = None) -> None:
        self.sent: list[tuple[str, str, str]] = []
        self._fail_for = fail_for or set()

    def send(self, tenant_id: str, external_user_id: str, text: str) -> None:
        if external_user_id in self._fail_for:
            raise WeComSendError("boom")
        self.sent.append((tenant_id, external_user_id, text))


def _synced_text(msg_id: str, external_user_id: str, content: str) -> KfSyncedMessage:
    return KfSyncedMessage(
        msg_id=msg_id,
        open_kf_id=OPEN_KF_ID,
        external_user_id=external_user_id,
        send_time=100,
        origin=3,
        msg_type="text",
        text_content=content,
    )


def test_processor_forwards_and_replies_for_each_message() -> None:
    from app.wecom.kf import KfSyncBatch

    client = _QueuedSyncClient(
        [KfSyncBatch(messages=(_synced_text("m1", "wm-1", "想约洗澡"),), next_cursor="c1", has_more=False)]
    )
    graph = _RecordingSupervisorGraph(reply="已为您安排洗护。")
    sender = _RecordingReplySender()
    processor = KfSyncMessageProcessor(client, graph, reply_sender=sender)

    processor.process(WeComKfNotification(tenant_id=TENANT, open_kf_id=OPEN_KF_ID, token="tok"))

    assert len(graph.invocations) == 1
    assert sender.sent == [(TENANT, "wm-1", "已为您安排洗护。")]


def test_processor_paginates_until_has_more_false() -> None:
    from app.wecom.kf import KfSyncBatch

    client = _QueuedSyncClient(
        [
            KfSyncBatch(messages=(_synced_text("m1", "wm-1", "a"),), next_cursor="c1", has_more=True),
            KfSyncBatch(messages=(_synced_text("m2", "wm-2", "b"),), next_cursor="c2", has_more=False),
        ]
    )
    graph = _RecordingSupervisorGraph()
    processor = KfSyncMessageProcessor(client, graph)

    processor.process(WeComKfNotification(tenant_id=TENANT, open_kf_id=OPEN_KF_ID, token="tok"))

    assert len(graph.invocations) == 2
    assert [c["cursor"] for c in client.calls] == ["", "c1"]


def test_processor_skips_duplicate_msgid() -> None:
    from app.wecom.kf import KfSyncBatch

    client = _QueuedSyncClient(
        [KfSyncBatch(messages=(_synced_text("dup-1", "wm-1", "a"),), next_cursor="", has_more=False)]
    )
    graph = _RecordingSupervisorGraph()
    processor = KfSyncMessageProcessor(client, graph)
    notification = WeComKfNotification(tenant_id=TENANT, open_kf_id=OPEN_KF_ID, token="tok")

    # 手动预置幂等存储，模拟"已处理过"。
    processor._idempotency.put("dup-1", "已处理")
    processor.process(notification)

    assert graph.invocations == []  # 未重复转发


def test_processor_continues_after_single_reply_failure() -> None:
    """一条消息的出站回复失败不应中断同批次其它消息的处理。"""
    from app.wecom.kf import KfSyncBatch

    client = _QueuedSyncClient(
        [
            KfSyncBatch(
                messages=(
                    _synced_text("m1", "wm-fail", "a"),
                    _synced_text("m2", "wm-ok", "b"),
                ),
                next_cursor="",
                has_more=False,
            )
        ]
    )
    graph = _RecordingSupervisorGraph(reply="ok")
    sender = _RecordingReplySender(fail_for={"wm-fail"})
    processor = KfSyncMessageProcessor(client, graph, reply_sender=sender)

    processor.process(WeComKfNotification(tenant_id=TENANT, open_kf_id=OPEN_KF_ID, token="tok"))

    assert len(graph.invocations) == 2  # 两条都转发了
    assert sender.sent == [(TENANT, "wm-ok", "ok")]  # 仅成功的那条记录


def test_processor_ignores_non_text_and_non_customer_messages() -> None:
    from app.wecom.kf import KfSyncBatch

    event_msg = KfSyncedMessage(
        msg_id="ev-1", open_kf_id=OPEN_KF_ID, external_user_id="wm-1",
        send_time=1, origin=4, msg_type="event",
    )
    client = _QueuedSyncClient(
        [KfSyncBatch(messages=(event_msg,), next_cursor="", has_more=False)]
    )
    graph = _RecordingSupervisorGraph()
    processor = KfSyncMessageProcessor(client, graph)

    processor.process(WeComKfNotification(tenant_id=TENANT, open_kf_id=OPEN_KF_ID, token="tok"))

    assert graph.invocations == []


# --------------------------------------------------------------------------- #
# KfMessageSendStrategy：kf/send_msg 载荷构造
# --------------------------------------------------------------------------- #
def test_kf_send_strategy_builds_expected_payload() -> None:
    strategy = KfMessageSendStrategy(open_kf_id=OPEN_KF_ID)
    payload = strategy.build_payload(
        tenant_id=TENANT, external_user_id="wm-1", text="已为您预约成功"
    )
    assert payload == {
        "touser": "wm-1",
        "open_kfid": OPEN_KF_ID,
        "msgtype": "text",
        "text": {"content": "已为您预约成功"},
    }
    assert strategy.endpoint("https://qyapi.weixin.qq.com").endswith("/cgi-bin/kf/send_msg")


def test_kf_send_strategy_rejects_blank_open_kf_id() -> None:
    with pytest.raises(ValueError):
        KfMessageSendStrategy(open_kf_id="")


# --------------------------------------------------------------------------- #
# 组合根接线：配置了 open_kf_id 时自动装配 kf_processor
# --------------------------------------------------------------------------- #
def test_composition_wires_kf_processor_when_open_kf_id_configured() -> None:
    from app.api.composition import build_composition
    from app.core.config import Settings

    settings = Settings(
        wecom={
            "corp_id": CORP_ID,
            "token": TOKEN,
            "encoding_aes_key": ENCODING_AES_KEY,
            "secret": "app-secret",
            "agent_id": 1000001,
            "open_kf_id": OPEN_KF_ID,
        }
    )
    comp = build_composition(settings=settings)

    assert comp.wecom_gateway is not None
    assert comp.wecom_gateway._kf_processor is not None  # type: ignore[attr-defined]


def test_composition_skips_kf_processor_when_open_kf_id_absent() -> None:
    from app.api.composition import build_composition
    from app.core.config import Settings

    settings = Settings(
        wecom={
            "corp_id": CORP_ID,
            "token": TOKEN,
            "encoding_aes_key": ENCODING_AES_KEY,
            "secret": "app-secret",
            "agent_id": 1000001,
            # 未配置 open_kf_id。
        }
    )
    comp = build_composition(settings=settings)

    assert comp.wecom_gateway is not None
    assert comp.wecom_gateway._kf_processor is None  # type: ignore[attr-defined]
