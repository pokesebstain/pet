"""企业微信出站回复通道测试（Requirement 21，设计文档 14.3 组件 A 出站侧）。

覆盖"客户消息 → 自动预约 → 回复回推客户"闭环的**出站**一环。全部测试使用**无网络**的
伪 HTTP 传输（:class:`FakeHttpTransport`）：

- access_token 获取 + 缓存（第二次发送复用缓存令牌）。
- 令牌过期触发重新获取。
- 业务接口返回 42001（令牌失效）→ 刷新令牌并重试一次后成功。
- 发送成功：校验命中正确端点与载荷（touser/msgtype/agentid/text）。
- 错误处理：非零 errcode 抛出 :class:`WeComSendError`。
- 端到端：一条合法的 ``POST /wecom/callback`` 使注入的发送器被调用并推送 Supervisor
  产出的回复文本。

安全：断言过程中不依赖 / 不打印任何真实密钥；secret / access_token 仅在内存中流转。
"""

from __future__ import annotations

import base64
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api import build_composition, create_app
from app.wecom.crypto import WeComCryptoCodec, build_encrypted_envelope
from app.wecom.gateway import WeComInboundGateway
from app.wecom.sender import (
    AppMessageSendStrategy,
    WeComAccessTokenManager,
    WeComMessageSender,
    WeComSendError,
    WeComTokenError,
)

BASE_URL = "https://qyapi.weixin.qq.com"
CORP_ID = "wwtestcorpid001"
SECRET = "app-secret-not-real"
AGENT_ID = 1000002


# --------------------------------------------------------------------------- #
# 无网络伪 HTTP 传输
# --------------------------------------------------------------------------- #
class FakeHttpTransport:
    """可编程的无网络 HTTP 传输：记录请求并按队列返回预置响应。"""

    def __init__(self) -> None:
        self.get_calls: list[dict[str, Any]] = []
        self.post_calls: list[dict[str, Any]] = []
        #: gettoken 响应队列；耗尽后复用最后一个。
        self.token_responses: list[dict[str, Any]] = [
            {"errcode": 0, "errmsg": "ok", "access_token": "TOKEN_A", "expires_in": 7200}
        ]
        #: message/send 响应队列；耗尽后复用最后一个。
        self.send_responses: list[dict[str, Any]] = [{"errcode": 0, "errmsg": "ok"}]

    @staticmethod
    def _next(queue: list[dict[str, Any]]) -> dict[str, Any]:
        if len(queue) > 1:
            return queue.pop(0)
        return queue[0]

    def get_json(
        self, url: str, *, params: Any = None, timeout: float = 10.0
    ) -> dict[str, Any]:
        self.get_calls.append({"url": url, "params": dict(params or {})})
        return self._next(self.token_responses)

    def post_json(
        self,
        url: str,
        *,
        params: Any = None,
        json_body: Any = None,
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        self.post_calls.append(
            {"url": url, "params": dict(params or {}), "json_body": dict(json_body or {})}
        )
        return self._next(self.send_responses)


class _FakeClock:
    """可控时间源，便于测试令牌过期。"""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _build_sender(
    transport: FakeHttpTransport, *, clock: _FakeClock | None = None
) -> WeComMessageSender:
    manager = WeComAccessTokenManager(
        corp_id=CORP_ID,
        secret=SECRET,
        transport=transport,
        base_url=BASE_URL,
        time_func=clock,
    )
    strategy = AppMessageSendStrategy(agent_id=AGENT_ID)
    return WeComMessageSender(
        token_manager=manager,
        transport=transport,
        strategy=strategy,
        base_url=BASE_URL,
    )


# --------------------------------------------------------------------------- #
# access_token 获取 + 缓存
# --------------------------------------------------------------------------- #
def test_access_token_fetched_and_cached() -> None:
    transport = FakeHttpTransport()
    sender = _build_sender(transport)

    sender.send("store-1", "user-1", "第一次回复")
    sender.send("store-1", "user-1", "第二次回复")

    # gettoken 仅调用一次（第二次复用缓存令牌）。
    assert len(transport.get_calls) == 1
    # 令牌请求带上 corpid + corpsecret。
    assert transport.get_calls[0]["params"]["corpid"] == CORP_ID
    assert transport.get_calls[0]["params"]["corpsecret"] == SECRET
    # 两次消息发送都携带缓存的 access_token。
    assert len(transport.post_calls) == 2
    assert transport.post_calls[0]["params"]["access_token"] == "TOKEN_A"
    assert transport.post_calls[1]["params"]["access_token"] == "TOKEN_A"


def test_access_token_refetched_after_expiry() -> None:
    transport = FakeHttpTransport()
    transport.token_responses = [
        {"errcode": 0, "access_token": "TOKEN_A", "expires_in": 7200},
        {"errcode": 0, "access_token": "TOKEN_B", "expires_in": 7200},
    ]
    clock = _FakeClock()
    sender = _build_sender(transport, clock=clock)

    sender.send("store-1", "user-1", "hi")
    # 快进超过 expires_in（含提前刷新余量），令牌应过期并重取。
    clock.now += 7200
    sender.send("store-1", "user-1", "hi again")

    assert len(transport.get_calls) == 2
    assert transport.post_calls[0]["params"]["access_token"] == "TOKEN_A"
    assert transport.post_calls[1]["params"]["access_token"] == "TOKEN_B"


def test_token_error_raises() -> None:
    transport = FakeHttpTransport()
    transport.token_responses = [
        {"errcode": 40001, "errmsg": "invalid credential"}
    ]
    sender = _build_sender(transport)

    with pytest.raises(WeComTokenError):
        sender.send("store-1", "user-1", "hi")


# --------------------------------------------------------------------------- #
# 令牌失效（42001）→ 刷新并重试一次
# --------------------------------------------------------------------------- #
def test_expired_token_errcode_triggers_refresh_and_retry() -> None:
    transport = FakeHttpTransport()
    transport.token_responses = [
        {"errcode": 0, "access_token": "TOKEN_A", "expires_in": 7200},
        {"errcode": 0, "access_token": "TOKEN_B", "expires_in": 7200},
    ]
    transport.send_responses = [
        {"errcode": 42001, "errmsg": "access_token expired"},  # 首次：令牌失效
        {"errcode": 0, "errmsg": "ok"},  # 重试成功
    ]
    sender = _build_sender(transport)

    sender.send("store-1", "user-1", "hi")

    # 令牌刷新了一次（共两次 gettoken：初始 + 失效后强刷）。
    assert len(transport.get_calls) == 2
    # 发送尝试了两次，第二次用新令牌。
    assert len(transport.post_calls) == 2
    assert transport.post_calls[0]["params"]["access_token"] == "TOKEN_A"
    assert transport.post_calls[1]["params"]["access_token"] == "TOKEN_B"


# --------------------------------------------------------------------------- #
# 发送成功：端点与载荷正确
# --------------------------------------------------------------------------- #
def test_send_hits_correct_endpoint_and_payload() -> None:
    transport = FakeHttpTransport()
    sender = _build_sender(transport)

    sender.send("store-1", "external_user_9", "您的美容预约已确认")

    call = transport.post_calls[0]
    assert call["url"] == f"{BASE_URL}/cgi-bin/message/send"
    assert call["json_body"] == {
        "touser": "external_user_9",
        "msgtype": "text",
        "agentid": AGENT_ID,
        "text": {"content": "您的美容预约已确认"},
    }


# --------------------------------------------------------------------------- #
# 错误处理：非零 errcode 抛 WeComSendError
# --------------------------------------------------------------------------- #
def test_non_zero_errcode_raises_send_error() -> None:
    transport = FakeHttpTransport()
    transport.send_responses = [{"errcode": 60011, "errmsg": "no privilege"}]
    sender = _build_sender(transport)

    with pytest.raises(WeComSendError):
        sender.send("store-1", "user-1", "hi")


def test_persistent_token_expiry_after_retry_raises() -> None:
    """令牌刷新重试后仍返回失效 errcode，最终抛出 WeComSendError。"""
    transport = FakeHttpTransport()
    transport.send_responses = [
        {"errcode": 40014, "errmsg": "invalid access_token"},
        {"errcode": 40014, "errmsg": "invalid access_token"},
    ]
    sender = _build_sender(transport)

    with pytest.raises(WeComSendError):
        sender.send("store-1", "user-1", "hi")


# --------------------------------------------------------------------------- #
# 端到端：POST /wecom/callback → 注入的发送器被调用并推送回复
# --------------------------------------------------------------------------- #
ENCODING_AES_KEY = base64.b64encode(
    b"petops-wecom-aes-256-seed-32bytes!"[:32]
).decode()[:43]
TOKEN = "petops-callback-token"


def _make_codec() -> WeComCryptoCodec:
    return WeComCryptoCodec(
        corp_id=CORP_ID,
        token=TOKEN,
        encoding_aes_key=ENCODING_AES_KEY,
        default_tenant_id="store_88",
    )


class _RecordingSupervisorGraph:
    def invoke(self, state: Any, config: Any = None) -> dict[str, Any]:
        return {"final_answer": "已为您预约周六上午的洗护，期待光临。"}


def test_callback_pushes_reply_via_injected_sender() -> None:
    transport = FakeHttpTransport()
    sender = _build_sender(transport)
    codec = _make_codec()
    gateway = WeComInboundGateway(
        codec, _RecordingSupervisorGraph(), reply_sender=sender
    )
    client = TestClient(create_app(composition=build_composition(wecom_gateway=gateway)))

    envelope = build_encrypted_envelope(
        _make_codec(),
        from_user="external_user_01",
        content="我家狗狗要洗澡",
        msg_id="msg-e2e-1",
        to_user=CORP_ID,
    )
    resp = client.post(
        "/wecom/callback",
        params={
            "msg_signature": envelope["msg_signature"],
            "timestamp": envelope["timestamp"],
            "nonce": envelope["nonce"],
        },
        content=envelope["body"],
        headers={"Content-Type": "text/xml"},
    )

    assert resp.status_code == 200
    # 出站发送器被调用一次，推送 Supervisor 的 final_answer 给客户。
    assert len(transport.post_calls) == 1
    call = transport.post_calls[0]
    assert call["url"] == f"{BASE_URL}/cgi-bin/message/send"
    assert call["json_body"]["touser"] == "external_user_01"
    assert call["json_body"]["text"]["content"] == "已为您预约周六上午的洗护，期待光临。"
