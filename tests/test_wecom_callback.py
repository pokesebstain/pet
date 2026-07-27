"""企业微信回调 HTTP 端点测试（Requirement 21，设计文档 14.3 组件 A）。

覆盖：

- ``GET /wecom/callback`` URL 验证握手：验签 + 解密 echostr，返回明文（往返自洽）。
- 坏签名 → HTTP 403（安全闸门，Requirement 21.2）。
- ``POST /wecom/callback`` 合法加密消息 → HTTP 200，并转发到（伪）Supervisor 图。
- 坏签名的 POST → HTTP 403，不转发。
- 未配置 WeCom 时回调返回 503，但 /health 仍可用（不破坏应用构造）。
- :class:`~app.wecom.crypto.WeComCryptoCodec` 加解密 / 验签 / ReceiveId 校验的单元测试。

全部测试在无真实企业微信环境下运行：用同一套 Token / EncodingAESKey 通过 crypto 辅助
函数构造合法的加密回调（往返），再经 FastAPI ``TestClient`` 断言端到端行为。
"""

from __future__ import annotations

import base64
from typing import Any

from fastapi.testclient import TestClient

from app.api import build_composition, create_app
from app.wecom.crypto import (
    WeComCryptoCodec,
    WeComCryptoError,
    build_echostr,
    build_encrypted_envelope,
)
from app.wecom.gateway import WeComInboundGateway

# --------------------------------------------------------------------------- #
# 测试固定密钥（非真实企业微信凭据，仅供加解密往返）
# --------------------------------------------------------------------------- #
CORP_ID = "wwtestcorpid001"
TOKEN = "petops-callback-token"
# 43 位 EncodingAESKey：由 32 字节种子 Base64 编码后去掉尾部 '='。
ENCODING_AES_KEY = base64.b64encode(b"petops-wecom-aes-256-seed-32bytes!"[:32]).decode()[:43]


def _make_codec() -> WeComCryptoCodec:
    return WeComCryptoCodec(
        corp_id=CORP_ID,
        token=TOKEN,
        encoding_aes_key=ENCODING_AES_KEY,
        default_tenant_id="store_88",
    )


class _RecordingSupervisorGraph:
    """伪 Supervisor 图：记录被转发的状态并返回带 final_answer 的结果。"""

    def __init__(self) -> None:
        self.invocations: list[dict[str, Any]] = []

    def invoke(self, state: Any, config: Any = None) -> dict[str, Any]:
        self.invocations.append({"state": dict(state), "config": config})
        return {"final_answer": "已收到您的咨询，稍后回复。"}


def _build_client_with_wecom(graph: _RecordingSupervisorGraph) -> TestClient:
    codec = _make_codec()
    gateway = WeComInboundGateway(codec, graph)
    composition = build_composition(wecom_gateway=gateway)
    return TestClient(create_app(composition=composition))


# --------------------------------------------------------------------------- #
# GET URL 验证握手
# --------------------------------------------------------------------------- #
def test_get_callback_returns_decrypted_echostr() -> None:
    graph = _RecordingSupervisorGraph()
    client = _build_client_with_wecom(graph)
    params = build_echostr(_make_codec(), plaintext="verify-echo-1234567")
    resp = client.get(
        "/wecom/callback",
        params={
            "msg_signature": params["msg_signature"],
            "timestamp": params["timestamp"],
            "nonce": params["nonce"],
            "echostr": params["echostr"],
        },
    )
    assert resp.status_code == 200
    assert resp.text == "verify-echo-1234567"


def test_get_callback_bad_signature_returns_403() -> None:
    graph = _RecordingSupervisorGraph()
    client = _build_client_with_wecom(graph)
    params = build_echostr(_make_codec())
    resp = client.get(
        "/wecom/callback",
        params={
            "msg_signature": "deadbeef",  # 篡改签名
            "timestamp": params["timestamp"],
            "nonce": params["nonce"],
            "echostr": params["echostr"],
        },
    )
    assert resp.status_code == 403


# --------------------------------------------------------------------------- #
# POST 入站消息回调
# --------------------------------------------------------------------------- #
def test_post_callback_valid_message_forwarded() -> None:
    graph = _RecordingSupervisorGraph()
    client = _build_client_with_wecom(graph)
    envelope = build_encrypted_envelope(
        _make_codec(),
        from_user="external_user_01",
        content="我家狗狗需要美容预约",
        msg_id="msg-0001",
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
    assert len(graph.invocations) == 1
    forwarded = graph.invocations[0]["state"]
    assert forwarded["tenant_id"] == "store_88"


def test_post_callback_bad_signature_returns_403_and_not_forwarded() -> None:
    graph = _RecordingSupervisorGraph()
    client = _build_client_with_wecom(graph)
    envelope = build_encrypted_envelope(
        _make_codec(),
        from_user="external_user_01",
        content="hello",
        msg_id="msg-0002",
        to_user=CORP_ID,
    )
    resp = client.post(
        "/wecom/callback",
        params={
            "msg_signature": "0000000000000000",  # 坏签名
            "timestamp": envelope["timestamp"],
            "nonce": envelope["nonce"],
        },
        content=envelope["body"],
        headers={"Content-Type": "text/xml"},
    )
    assert resp.status_code == 403
    assert graph.invocations == []


def test_post_callback_deduplicates_by_msg_id() -> None:
    """Requirement 21.3：重复 msg_id 幂等去重，仅转发一次。"""
    graph = _RecordingSupervisorGraph()
    client = _build_client_with_wecom(graph)

    def _send() -> int:
        envelope = build_encrypted_envelope(
            _make_codec(),
            from_user="external_user_01",
            content="重复消息",
            msg_id="msg-dup-1",
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
        return resp.status_code

    assert _send() == 200
    assert _send() == 200
    # 同一 msg_id 仅真正转发一次。
    assert len(graph.invocations) == 1


# --------------------------------------------------------------------------- #
# 未配置 WeCom：回调 503，但 /health 仍可用
# --------------------------------------------------------------------------- #
def test_callback_returns_503_when_wecom_not_configured() -> None:
    client = TestClient(create_app(composition=build_composition()))
    # /health 不受影响。
    assert client.get("/health").status_code == 200
    # 未配置 WeCom → 回调 503。
    assert client.get("/wecom/callback", params={"echostr": "x"}).status_code == 503
    assert client.post("/wecom/callback").status_code == 503


# --------------------------------------------------------------------------- #
# WeComCryptoCodec 单元测试
# --------------------------------------------------------------------------- #
def test_codec_encrypt_decrypt_roundtrip() -> None:
    codec = _make_codec()
    envelope = build_encrypted_envelope(
        codec,
        from_user="u1",
        content="你好",
        msg_id="m1",
        to_user=CORP_ID,
    )
    assert codec.verify_signature(envelope) is True
    message = codec.decode(envelope)
    assert message.external_user_id == "u1"
    assert message.content == "你好"
    assert message.msg_id == "m1"
    assert message.tenant_id == "store_88"


def test_codec_rejects_wrong_receive_id() -> None:
    codec = _make_codec()
    # 用不同的 corp_id 加密（错误的 ReceiveId），解密时应被拒绝。
    other = WeComCryptoCodec(
        corp_id="wwOTHERcorp999",
        token=TOKEN,
        encoding_aes_key=ENCODING_AES_KEY,
    )
    envelope = build_encrypted_envelope(
        other, from_user="u1", content="x", msg_id="m1", to_user="wwOTHERcorp999"
    )
    # 验签仍可能通过（同 token），但 decode 因 ReceiveId 不符而拒绝。
    try:
        codec.decode(envelope)
    except WeComCryptoError:
        pass
    else:
        raise AssertionError("期望 ReceiveId 不符时抛出 WeComCryptoError")


def test_codec_bad_encoding_aes_key_rejected() -> None:
    try:
        WeComCryptoCodec(corp_id=CORP_ID, token=TOKEN, encoding_aes_key="tooshort")
    except WeComCryptoError:
        pass
    else:
        raise AssertionError("期望非法 EncodingAESKey 抛出 WeComCryptoError")


def test_codec_verify_signature_false_on_tamper() -> None:
    codec = _make_codec()
    envelope = build_encrypted_envelope(
        codec, from_user="u1", content="x", msg_id="m1", to_user=CORP_ID
    )
    envelope["msg_signature"] = "tampered"
    assert codec.verify_signature(envelope) is False
