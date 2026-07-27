"""企业微信官方回调加解密与验签实现（Requirement 21，设计文档 14.3 组件 A）。

本模块提供符合企业微信官方 ``WXBizMsgCrypt`` 方案的**真实**编解码器
:class:`WeComCryptoCodec`，实现既有 :class:`~app.wecom.gateway.WeComCodec` 协议
（``verify_signature`` + ``decode``），作为入站网关在生产环境的验签 / 解密实现。

企业微信官方方案（AES-256-CBC + SHA1 签名）:

- **签名**：``sha1( sort([token, timestamp, nonce, encrypt]) 拼接 )`` 的十六进制摘要，
  与回调携带的 ``msg_signature`` 比对（Requirement 21.2 的安全闸门）。
- **解密**：``key = base64decode(EncodingAESKey + "=")``（32 字节），``iv = key[:16]``，
  AES-256-CBC 解密后做 PKCS7 去填充；明文结构为
  ``random(16) + msg_len(4, big-endian) + msg + ReceiveId``。取出 ``msg``（XML）后，
  校验尾部 ``ReceiveId`` 是否等于配置的 ``corp_id``（防止跨企业投递）。
- **XML 解析**：从明文 XML 提取 ``FromUserName`` → ``external_user_id``、``Content`` →
  ``content``、``MsgId`` → ``msg_id``、``ToUserName``（CorpID）→ 经映射得到 ``tenant_id``。

为在**无真实企业微信环境**下可测，本模块另提供 :func:`WeComCryptoCodec.encrypt`
（及 :func:`build_encrypted_envelope` / :func:`build_echostr`）辅助函数，可用同一套 Token /
EncodingAESKey 生成合法的加密回调（GET echostr 与 POST 密文），供测试做端到端往返。

安全：本模块**绝不**记录 Token / EncodingAESKey / 明文密钥；密钥仅在内存中用于加解密。
"""

from __future__ import annotations

import base64
import hashlib
import os
import struct
from collections.abc import Mapping
from typing import Any
from xml.etree import ElementTree as ET

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from app.wecom.gateway import WeComInboundMessage, WeComSignatureError

__all__ = [
    "WeComCryptoCodec",
    "WeComCryptoError",
    "build_encrypted_envelope",
    "build_echostr",
]

#: 明文前缀的随机字节数（企业微信官方方案固定 16 字节）。
_RANDOM_PREFIX_LEN = 16
#: AES 块大小（字节）。
_AES_BLOCK_SIZE = 16


class WeComCryptoError(WeComSignatureError):
    """企业微信真实验签 / 解密失败错误（Requirement 21.2）。

    继承自 :class:`~app.wecom.gateway.WeComSignatureError`，使网关既有的"验签失败拒绝并
    记录"路径无需改动即可覆盖真实编解码器抛出的错误。
    """


def _sha1_signature(token: str, timestamp: str, nonce: str, encrypt: str) -> str:
    """按企业微信方案计算签名：对四元组排序后拼接求 SHA1 十六进制摘要。"""
    items = sorted([token, timestamp, nonce, encrypt])
    return hashlib.sha1("".join(items).encode("utf-8")).hexdigest()


def _pkcs7_pad(data: bytes) -> bytes:
    pad = _AES_BLOCK_SIZE - (len(data) % _AES_BLOCK_SIZE)
    return data + bytes([pad]) * pad


def _pkcs7_unpad(data: bytes) -> bytes:
    if not data:
        raise WeComCryptoError("解密结果为空，无法去除 PKCS7 填充。")
    pad = data[-1]
    if pad < 1 or pad > _AES_BLOCK_SIZE or pad > len(data):
        raise WeComCryptoError("PKCS7 填充非法，疑似密钥不匹配或密文被篡改。")
    return data[:-pad]


class WeComCryptoCodec:
    """企业微信官方方案的真实编解码器（实现 :class:`~app.wecom.gateway.WeComCodec`）。

    Args:
        corp_id: 企业微信企业 ID（CorpID）；解密后据此校验明文尾部 ReceiveId。
        token: 回调 Token，用于消息签名校验。
        encoding_aes_key: EncodingAESKey（43 位 Base64，无尾部 ``=``）。
        corp_to_tenant: 可选 corp_id → tenant_id 映射；用于多企业接入。缺省时所有回调映射
            到 ``default_tenant_id``（单租户 / 单企业部署）。
        default_tenant_id: 映射缺失时使用的默认租户；缺省回退为 ``corp_id`` 本身。

    Raises:
        WeComCryptoError: EncodingAESKey 无法 Base64 解码或长度不为 32 字节。
    """

    def __init__(
        self,
        *,
        corp_id: str,
        token: str,
        encoding_aes_key: str,
        corp_to_tenant: Mapping[str, str] | None = None,
        default_tenant_id: str | None = None,
    ) -> None:
        if not corp_id or not corp_id.strip():
            raise WeComCryptoError("corp_id 不可为空。")
        if not token or not token.strip():
            raise WeComCryptoError("token 不可为空。")
        self._corp_id = corp_id.strip()
        self._token = token
        self._aes_key = self._decode_aes_key(encoding_aes_key)
        self._iv = self._aes_key[:_AES_BLOCK_SIZE]
        self._corp_to_tenant = dict(corp_to_tenant or {})
        self._default_tenant_id = (default_tenant_id or self._corp_id).strip()

    # -- WeComCodec 协议实现 ------------------------------------------------

    def verify_signature(self, raw: Mapping[str, Any]) -> bool:
        """按企业微信方案校验回调签名（Requirement 21.2）。

        从 ``raw`` 读取 ``token``（此处指请求参数 ``msg_signature``）、``timestamp``、
        ``nonce`` 与密文（``echostr`` 或 XML 体内 ``Encrypt``），比对计算得到的 SHA1 签名。
        任一字段缺失或不匹配返回 ``False``。
        """
        try:
            msg_signature = str(raw["msg_signature"])
            timestamp = str(raw["timestamp"])
            nonce = str(raw["nonce"])
            encrypt = self._extract_encrypt(raw)
        except (KeyError, WeComCryptoError):
            return False
        expected = _sha1_signature(self._token, timestamp, nonce, encrypt)
        # 恒定时间比较，避免时序侧信道。
        return _constant_time_equals(expected, msg_signature)

    def decode(self, raw: Mapping[str, Any]) -> WeComInboundMessage:
        """解密并还原为 :class:`WeComInboundMessage`（含 corp→tenant 映射）。

        Raises:
            WeComCryptoError: 密文缺失 / 解密失败 / ReceiveId 与 corp_id 不符 / XML 非法。
        """
        encrypt = self._extract_encrypt(raw)
        xml_text, receive_id = self._decrypt(encrypt)
        if receive_id != self._corp_id:
            raise WeComCryptoError(
                "解密后的 ReceiveId 与配置的 corp_id 不一致，拒绝处理（Requirement 21.2）。"
            )
        fields = _parse_message_xml(xml_text)
        to_user = fields.get("ToUserName") or self._corp_id
        tenant_id = self._corp_to_tenant.get(to_user, self._default_tenant_id)
        return WeComInboundMessage(
            tenant_id=tenant_id,
            external_user_id=fields.get("FromUserName", ""),
            content=fields.get("Content", ""),
            msg_id=fields.get("MsgId", ""),
        )

    # -- 解密 / 加密 --------------------------------------------------------

    def decrypt_echostr(self, raw: Mapping[str, Any]) -> str:
        """URL 验证握手：解密 ``echostr`` 并返回明文（Requirement 21）。

        企业微信在配置回调 URL 时发起 ``GET`` 校验：先验签，再解密 ``echostr``，原样返回
        解密后的明文字符串。ReceiveId 同样需等于 corp_id。

        Raises:
            WeComCryptoError: 密文缺失 / 解密失败 / ReceiveId 不符。
        """
        encrypt = self._extract_encrypt(raw)
        plaintext, receive_id = self._decrypt(encrypt)
        if receive_id != self._corp_id:
            raise WeComCryptoError("echostr 的 ReceiveId 与 corp_id 不一致。")
        return plaintext

    def encrypt(self, message: str, *, receive_id: str | None = None) -> str:
        """将明文（XML 或 echostr）按企业微信方案加密为 Base64 密文（供测试 / 出站使用）。

        明文结构：``random(16) + msg_len(4, big-endian) + msg + ReceiveId``，PKCS7 填充后
        AES-256-CBC 加密再 Base64 编码。
        """
        rid = (receive_id or self._corp_id).encode("utf-8")
        msg_bytes = message.encode("utf-8")
        random_prefix = os.urandom(_RANDOM_PREFIX_LEN)
        payload = (
            random_prefix
            + struct.pack(">I", len(msg_bytes))
            + msg_bytes
            + rid
        )
        encryptor = self._cipher().encryptor()
        ciphertext = encryptor.update(_pkcs7_pad(payload)) + encryptor.finalize()
        return base64.b64encode(ciphertext).decode("ascii")

    def sign(self, timestamp: str, nonce: str, encrypt: str) -> str:
        """计算回调签名（供测试构造合法回调 / 出站回复签名）。"""
        return _sha1_signature(self._token, timestamp, nonce, encrypt)

    # -- 内部辅助 -----------------------------------------------------------

    def _decrypt(self, encrypt: str) -> tuple[str, str]:
        """解密密文，返回 ``(msg_xml, receive_id)``。"""
        try:
            ciphertext = base64.b64decode(encrypt)
        except (ValueError, base64.binascii.Error) as exc:  # type: ignore[attr-defined]
            raise WeComCryptoError("密文 Base64 解码失败。") from exc
        if not ciphertext or len(ciphertext) % _AES_BLOCK_SIZE != 0:
            raise WeComCryptoError("密文长度非法，疑似被篡改或密钥不匹配。")
        decryptor = self._cipher().decryptor()
        try:
            padded = decryptor.update(ciphertext) + decryptor.finalize()
        except ValueError as exc:
            raise WeComCryptoError("AES 解密失败。") from exc
        plaintext = _pkcs7_unpad(padded)
        if len(plaintext) < _RANDOM_PREFIX_LEN + 4:
            raise WeComCryptoError("解密明文过短，结构非法。")
        content = plaintext[_RANDOM_PREFIX_LEN:]
        msg_len = struct.unpack(">I", content[:4])[0]
        if msg_len < 0 or 4 + msg_len > len(content):
            raise WeComCryptoError("消息长度字段非法，疑似密钥不匹配。")
        msg = content[4 : 4 + msg_len]
        receive_id = content[4 + msg_len :]
        return msg.decode("utf-8"), receive_id.decode("utf-8")

    def _cipher(self) -> Cipher:
        return Cipher(algorithms.AES(self._aes_key), modes.CBC(self._iv))

    def _extract_encrypt(self, raw: Mapping[str, Any]) -> str:
        """从回调中取出密文：优先 ``echostr``（GET），否则从 XML 体的 ``Encrypt``（POST）。"""
        echostr = raw.get("echostr")
        if isinstance(echostr, str) and echostr.strip():
            return echostr
        encrypt = raw.get("encrypt") or raw.get("Encrypt")
        if isinstance(encrypt, str) and encrypt.strip():
            return encrypt
        body = raw.get("body") or raw.get("xml")
        if isinstance(body, (bytes, bytearray)):
            body = body.decode("utf-8", errors="replace")
        if isinstance(body, str) and body.strip():
            parsed = _parse_message_xml(body)
            value = parsed.get("Encrypt")
            if value:
                return value
        raise WeComCryptoError("回调中缺少密文（echostr / Encrypt）。")

    @staticmethod
    def _decode_aes_key(encoding_aes_key: str) -> bytes:
        if not encoding_aes_key or not encoding_aes_key.strip():
            raise WeComCryptoError("EncodingAESKey 不可为空。")
        try:
            key = base64.b64decode(encoding_aes_key.strip() + "=")
        except (ValueError, base64.binascii.Error) as exc:  # type: ignore[attr-defined]
            raise WeComCryptoError("EncodingAESKey Base64 解码失败。") from exc
        if len(key) != 32:
            raise WeComCryptoError("EncodingAESKey 解码后长度必须为 32 字节（AES-256）。")
        return key


def _constant_time_equals(a: str, b: str) -> bool:
    """恒定时间字符串比较，避免签名比对的时序侧信道。"""
    import hmac

    return hmac.compare_digest(a, b)


def _parse_message_xml(xml_text: str) -> dict[str, str]:
    """解析企业微信回调 XML，返回顶层子元素文本映射。

    Raises:
        WeComCryptoError: XML 无法解析。
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise WeComCryptoError("回调 XML 解析失败。") from exc
    result: dict[str, str] = {}
    for child in root:
        result[child.tag] = (child.text or "").strip()
    return result


def build_encrypted_envelope(
    codec: WeComCryptoCodec,
    *,
    from_user: str,
    content: str,
    msg_id: str,
    to_user: str | None = None,
    timestamp: str = "1600000000",
    nonce: str = "test-nonce",
) -> dict[str, str]:
    """构造一条合法的加密 POST 回调（供测试往返，无需真实企业微信）。

    返回包含 ``msg_signature`` / ``timestamp`` / ``nonce`` 查询参数与加密 XML ``body`` 的字典，
    结构与 :class:`~app.wecom.gateway.WeComInboundGateway.handle` 期望的 ``raw`` 一致。
    """
    inner_xml = (
        "<xml>"
        f"<ToUserName><![CDATA[{to_user or ''}]]></ToUserName>"
        f"<FromUserName><![CDATA[{from_user}]]></FromUserName>"
        f"<CreateTime>{timestamp}</CreateTime>"
        "<MsgType><![CDATA[text]]></MsgType>"
        f"<Content><![CDATA[{content}]]></Content>"
        f"<MsgId>{msg_id}</MsgId>"
        "<AgentID>1000002</AgentID>"
        "</xml>"
    )
    encrypt = codec.encrypt(inner_xml)
    signature = codec.sign(timestamp, nonce, encrypt)
    body = (
        "<xml>"
        f"<ToUserName><![CDATA[{to_user or ''}]]></ToUserName>"
        f"<Encrypt><![CDATA[{encrypt}]]></Encrypt>"
        "</xml>"
    )
    return {
        "msg_signature": signature,
        "timestamp": timestamp,
        "nonce": nonce,
        "body": body,
    }


def build_echostr(
    codec: WeComCryptoCodec,
    *,
    plaintext: str = "1234567890123456",
    timestamp: str = "1600000000",
    nonce: str = "test-nonce",
) -> dict[str, str]:
    """构造一次合法的 GET URL 验证握手参数（供测试往返）。

    返回 ``msg_signature`` / ``timestamp`` / ``nonce`` / ``echostr`` 查询参数，其中
    ``echostr`` 为 ``plaintext`` 加密后的密文；解密后应还原为 ``plaintext``。
    """
    encrypt = codec.encrypt(plaintext)
    signature = codec.sign(timestamp, nonce, encrypt)
    return {
        "msg_signature": signature,
        "timestamp": timestamp,
        "nonce": nonce,
        "echostr": encrypt,
        "expected_plaintext": plaintext,
    }
