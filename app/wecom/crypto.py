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
import json
import logging
import os
import struct
from collections.abc import Mapping
from typing import Any
from xml.etree import ElementTree as ET

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from app.wecom.gateway import WeComInboundMessage, WeComKfNotification, WeComSignatureError

logger = logging.getLogger(__name__)

__all__ = [
    "WeComCryptoCodec",
    "WeComCryptoError",
    "build_encrypted_envelope",
    "build_echostr",
    "build_kf_notification_envelope",
]

#: 微信客服"有新消息"通知的事件标识（对应设计文档 14.9 / Requirement 25 补充）。
_KF_MSG_OR_EVENT: str = "kf_msg_or_event"

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


def _pkcs7_unpad(data: bytes, *, key_fingerprint: str = "") -> bytes:
    if not data:
        raise WeComCryptoError("解密结果为空，无法去除 PKCS7 填充。")
    pad = data[-1]
    if pad < 1 or pad > _AES_BLOCK_SIZE or pad > len(data):
        logger.warning(
            "PKCS7 填充非法（last_byte=%d，需 1..16），疑似密钥不匹配或密文被篡改；"
            "key_fingerprint=%s",
            pad,
            key_fingerprint or "<unknown>",
        )
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

    def aes_key_fingerprint(self) -> str:
        """返回当前生效 EncodingAESKey 解码后字节的前 8 位十六进制指纹（不泄露完整密钥）。

        用于启动期日志核对：当解密持续失败（如 PKCS7 填充非法）却排除了 Token 错误
        （验签通过）时，可用此指纹对比企业微信后台当前 EncodingAESKey 与容器内实际
        生效值是否一致，排查"后台已更换密钥但容器仍持有旧 .env / 镜像未重建"等问题。
        """
        return self._aes_key[:8].hex()

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
        except (KeyError, WeComCryptoError) as exc:
            logger.warning(
                "企业微信回调验签：提取密文失败（%s: %s），body[:200]=%r",
                type(exc).__name__,
                exc,
                str(raw.get("body") or "")[:200],
            )
            return False
        expected = _sha1_signature(self._token, timestamp, nonce, encrypt)
        if not _constant_time_equals(expected, msg_signature):
            logger.warning(
                "企业微信回调验签失败：签名不匹配（token_prefix=%s，encrypt_len=%d）",
                self._token[:4] if self._token else "<empty>",
                len(encrypt),
            )
            return False
        return True

    def decode(self, raw: Mapping[str, Any]) -> WeComInboundMessage:
        """解密并还原为 :class:`WeComInboundMessage`（含 corp→tenant 映射）。

        仅适用于**自建应用普通消息**（明文携带 ``Content`` 字段）。微信客服通知
        （``MsgType=event`` 且 ``Event=kf_msg_or_event``）请改用 :meth:`decode_kf_notification`
        ——微信客服回调的明文**不含**消息内容，只是"有新消息"的通知，须再调用
        ``sync_msg`` 接口拉取真正的消息（设计 14.9 / Requirement 25 补充；
        参见企业微信文档 94670「接收消息和事件」）。调用方（网关）应先用
        :meth:`peek_event_type` 判断回调类型再分派到对应方法。

        Raises:
            WeComCryptoError: 密文缺失 / 解密失败 / ReceiveId 与 corp_id 不符 / XML 非法。
        """
        fields = self._decode_fields(raw)
        to_user = fields.get("ToUserName") or self._corp_id
        tenant_id = self._corp_to_tenant.get(to_user, self._default_tenant_id)
        return WeComInboundMessage(
            tenant_id=tenant_id,
            external_user_id=fields.get("FromUserName", ""),
            content=fields.get("Content", ""),
            msg_id=fields.get("MsgId", ""),
        )

    def decode_kf_notification(self, raw: Mapping[str, Any]) -> WeComKfNotification:
        """解密并还原为微信客服"有新消息"通知（``kf_msg_or_event`` 事件）。

        通知本身不含消息内容，仅携带用于调用 ``sync_msg`` 接口拉取真正消息的临时
        ``Token``（与验签用的回调 Token **不是同一个**，见企业微信文档 94670）与
        客服账号标识 ``OpenKfId``。

        Raises:
            WeComCryptoError: 密文缺失 / 解密失败 / ReceiveId 与 corp_id 不符 / XML 非法。
        """
        fields = self._decode_fields(raw)
        to_user = fields.get("ToUserName") or self._corp_id
        tenant_id = self._corp_to_tenant.get(to_user, self._default_tenant_id)
        return WeComKfNotification(
            tenant_id=tenant_id,
            open_kf_id=fields.get("OpenKfId", ""),
            token=fields.get("Token", ""),
        )

    def peek_event_type(self, raw: Mapping[str, Any]) -> tuple[str, str]:
        """解密并读取 ``(MsgType, Event)``，用于网关判断回调类型（不构造消息对象）。

        普通文本消息 ``Event`` 为空串；微信客服通知 ``MsgType="event"`` 且
        ``Event="kf_msg_or_event"``。

        Raises:
            WeComCryptoError: 密文缺失 / 解密失败 / ReceiveId 与 corp_id 不符 / XML 非法。
        """
        fields = self._decode_fields(raw)
        return fields.get("MsgType", ""), fields.get("Event", "")

    def is_kf_notification(self, raw: Mapping[str, Any]) -> bool:
        """便捷判断：本次回调是否为微信客服"有新消息"通知。"""
        msg_type, event = self.peek_event_type(raw)
        return msg_type == "event" and event == _KF_MSG_OR_EVENT

    def _decode_fields(self, raw: Mapping[str, Any]) -> dict[str, str]:
        """解密并解析明文 XML 为字段映射，校验 ReceiveId（供上述方法共用）。"""
        encrypt = self._extract_encrypt(raw)
        xml_text, receive_id = self._decrypt(encrypt)
        if receive_id != self._corp_id:
            raise WeComCryptoError(
                "解密后的 ReceiveId 与配置的 corp_id 不一致，拒绝处理（Requirement 21.2）。"
            )
        return _parse_message_xml(xml_text)

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
        key_fp = self._aes_key[:8].hex()
        try:
            ciphertext = base64.b64decode(encrypt)
        except (ValueError, base64.binascii.Error) as exc:  # type: ignore[attr-defined]
            logger.warning("企业微信回调解密：密文 Base64 解码失败：%s", exc)
            raise WeComCryptoError("密文 Base64 解码失败。") from exc
        if not ciphertext or len(ciphertext) % _AES_BLOCK_SIZE != 0:
            logger.warning(
                "企业微信回调解密：密文长度非法（len=%d，非 16 字节对齐）；key_fingerprint=%s",
                len(ciphertext) if ciphertext else 0,
                key_fp,
            )
            raise WeComCryptoError("密文长度非法，疑似被篡改或密钥不匹配。")
        decryptor = self._cipher().decryptor()
        try:
            padded = decryptor.update(ciphertext) + decryptor.finalize()
        except ValueError as exc:
            logger.warning("企业微信回调解密：AES 解密失败：%s；key_fingerprint=%s", exc, key_fp)
            raise WeComCryptoError("AES 解密失败。") from exc
        plaintext = _pkcs7_unpad(padded, key_fingerprint=key_fp)
        if len(plaintext) < _RANDOM_PREFIX_LEN + 4:
            logger.warning(
                "企业微信回调解密：明文过短（%d 字节），疑似密钥不匹配；key_fingerprint=%s",
                len(plaintext),
                key_fp,
            )
            raise WeComCryptoError("解密明文过短，结构非法。")
        content = plaintext[_RANDOM_PREFIX_LEN:]
        msg_len = struct.unpack(">I", content[:4])[0]
        if msg_len < 0 or 4 + msg_len > len(content):
            logger.warning(
                "企业微信回调解密：msg_len=%d 对 %d 字节明文非法，疑似密钥不匹配；key_fingerprint=%s",
                msg_len,
                len(content),
                key_fp,
            )
            raise WeComCryptoError("消息长度字段非法，疑似密钥不匹配。")
        msg = content[4 : 4 + msg_len]
        receive_id = content[4 + msg_len :]
        msg_text = msg.decode("utf-8")
        logger.info("企业微信回调解密成功，明文 XML：%s", msg_text)
        return msg_text, receive_id.decode("utf-8")

    def _cipher(self) -> Cipher:
        return Cipher(algorithms.AES(self._aes_key), modes.CBC(self._iv))

    def _extract_encrypt(self, raw: Mapping[str, Any]) -> str:
        """从回调中取出密文：覆盖 GET/POST 的多种 WeCom 体格式。

        优先级：
        1. ``echostr``（GET URL 握手）—— 自建应用与微信客服均使用。
        2. 顶层 ``encrypt`` / ``Encrypt`` 字段（部分回调形式直接挂载在 query/body 外层）。
        3. POST 体：依次尝试解析为 **JSON**（微信客服 ``POST /cgi-bin/kf/event``）与
           **XML**（自建应用回调）。JSON 体里 ``encrypt`` 键携带密文，与 XML 的
           ``<Encrypt>`` 节点同义。
        4. 全部失败抛 :class:`WeComCryptoError`，由网关拒绝（Requirement 21.2）。
        """
        logger.debug("企业微信回调 _extract_encrypt：raw_keys=%s", sorted(raw))
        echostr = raw.get("echostr")
        if isinstance(echostr, str) and echostr.strip():
            logger.debug("企业微信回调 _extract_encrypt：命中 echostr 分支")
            return echostr
        encrypt = raw.get("encrypt") or raw.get("Encrypt")
        if isinstance(encrypt, str) and encrypt.strip():
            logger.debug("企业微信回调 _extract_encrypt：命中顶层 encrypt 字段分支")
            return encrypt
        body = raw.get("body") or raw.get("xml")
        if isinstance(body, (bytes, bytearray)):
            body = body.decode("utf-8", errors="replace")
        if not (isinstance(body, str) and body.strip()):
            logger.warning("企业微信回调 _extract_encrypt：body 为空，无法提取密文。")
            raise WeComCryptoError("回调中缺少密文（echostr / Encrypt）。")

        # 微信客服回调：body 是 JSON，形如 ``{"encrypt": "..."}``。
        stripped = body.lstrip()
        if stripped.startswith("{"):
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                payload = None
            if isinstance(payload, dict):
                value = payload.get("encrypt") or payload.get("Encrypt")
                if isinstance(value, str) and value.strip():
                    logger.debug("企业微信回调 _extract_encrypt：命中 JSON body 分支")
                    return value

        # 自建应用回调：body 是 XML，``<Encrypt>`` 节点携带密文。
        try:
            parsed = _parse_message_xml(body)
        except WeComCryptoError as exc:
            logger.warning("企业微信回调 _extract_encrypt：XML 解析失败：%s；body[:200]=%r", exc, body[:200])
            raise
        value = parsed.get("Encrypt")
        if value:
            logger.debug(
                "企业微信回调 _extract_encrypt：命中 XML body 分支；encrypt_len=%d",
                len(value),
            )
            return value
        logger.warning("企业微信回调 _extract_encrypt：未找到 Encrypt 字段；keys=%s", sorted(parsed))
        raise WeComCryptoError("回调中缺少密文（echostr / Encrypt / json.encrypt）。")

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


def build_kf_notification_envelope(
    codec: WeComCryptoCodec,
    *,
    open_kf_id: str,
    kf_token: str,
    to_user: str | None = None,
    timestamp: str = "1600000000",
    nonce: str = "test-nonce",
) -> dict[str, str]:
    """构造一条合法的加密微信客服"有新消息"通知回调（供测试往返，无需真实企业微信）。

    Args:
        codec: 用于加密的编解码器（复用其 Token/EncodingAESKey）。
        open_kf_id: 客服账号 ID。
        kf_token: 通知内携带的临时 ``sync_msg`` 拉取令牌（与回调验签 Token 不同）。
        to_user: 明文 ``ToUserName``（企业微信 CorpID）；缺省用编解码器的 corp_id。

    Returns:
        结构与 :func:`build_encrypted_envelope` 一致的 ``raw`` 字典。
    """
    inner_xml = (
        "<xml>"
        f"<ToUserName><![CDATA[{to_user or ''}]]></ToUserName>"
        f"<CreateTime>{timestamp}</CreateTime>"
        "<MsgType><![CDATA[event]]></MsgType>"
        "<Event><![CDATA[kf_msg_or_event]]></Event>"
        f"<Token><![CDATA[{kf_token}]]></Token>"
        f"<OpenKfId><![CDATA[{open_kf_id}]]></OpenKfId>"
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
