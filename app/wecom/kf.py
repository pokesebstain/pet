"""微信客服消息拉取与回复（``kf_msg_or_event`` 通知的下游处理，设计文档 14.9 补充）。

对应企业微信文档「接收消息和事件」（94670）与「发送消息」（94677）：微信客服回调
本身**不含**消息内容，只是"有新消息"的通知；收到通知后须调用
``POST /cgi-bin/kf/sync_msg`` 拉取自上次以来的新消息（可能多条，需按 ``next_cursor``
翻页），对每条消息转发 Supervisor 并经 ``POST /cgi-bin/kf/send_msg`` 回复客户。

本模块提供：

- :class:`KfSyncedMessage`：``sync_msg`` 返回的单条消息（当前仅解析文本消息内容，
  其它类型标记 ``msgtype`` 供上层按需处理）。
- :class:`KfSyncMessageClient`：调用 ``sync_msg`` 接口并翻页拉取全部新消息。
- :class:`CursorStore` / :class:`InMemoryCursorStore`：按客服账号持久化拉取游标
  （``next_cursor``），避免重启后重复拉取或漏拉。
- :class:`KfMessageSendStrategy`：微信客服出站回复策略（``kf/send_msg``），可与既有
  :class:`~app.wecom.sender.WeComMessageSender` 组合复用 access_token 管理 / 重试逻辑。
- :class:`KfSyncMessageProcessor`：实现 :class:`~app.wecom.gateway.KfEventProcessor`
  协议，串联"拉取 → 幂等去重 → 转发 Supervisor → 回复"完整流程，供网关在收到
  ``kf_msg_or_event`` 通知时委派处理。

设计要点（重要）：``kf/send_msg`` 仅在客户处于"新接入待处理"（``service_state=0``）
或"由智能助手接待"（``service_state=1``）时可用（企业微信文档 94677 概述）；本模块
**不**主动变更会话状态（``service_state/trans``），MVP 阶段直接尝试回复——若客户已被
转人工接待（``service_state≥2``），回复会失败，此时记录日志而不中断整批消息处理
（同一批次其它客户的消息仍应正常处理）。

安全：**绝不记录** access_token / sync_msg 拉取令牌；仅记录长度 / 是否存在。
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from app.wecom.gateway import (
    IdempotencyStore,
    InMemoryIdempotencyStore,
    ReplySender,
    SupervisorGraph,
    WeComKfNotification,
    extract_final_answer,
)
from app.wecom.sender import (
    DEFAULT_WECOM_API_BASE_URL,
    HttpTransport,
    WeComAccessTokenManager,
    WeComSendError,
)

__all__ = [
    "KfSyncedMessage",
    "KfSyncBatch",
    "KfSyncError",
    "KfSyncMessageClient",
    "CursorStore",
    "InMemoryCursorStore",
    "KfMessageSendStrategy",
    "KfSyncMessageProcessor",
    "MAX_SYNC_PAGES_PER_NOTIFICATION",
]

logger = logging.getLogger(__name__)

#: 单次通知最多翻页拉取次数（安全上限，避免因 has_more 异常返回导致死循环）。
MAX_SYNC_PAGES_PER_NOTIFICATION: int = 20


class KfSyncError(WeComSendError):
    """``sync_msg`` 拉取失败错误（企业微信返回非零 ``errcode``）。"""


@dataclass(frozen=True)
class KfSyncedMessage:
    """``sync_msg`` 返回的单条消息（对应企业微信文档 94670 「消息类型」）。

    当前仅解析文本消息（``msgtype == "text"``）的 ``text_content``；其它类型
    （图片/语音/视频/文件/位置/事件等）保留 ``msgtype`` 供上层按需扩展，
    ``text_content`` 为空串。
    """

    msg_id: str
    open_kf_id: str
    external_user_id: str
    send_time: int
    origin: int
    msg_type: str
    text_content: str = ""

    @property
    def is_from_customer(self) -> bool:
        """是否为微信客户发送的消息（``origin == 3``，区别于系统事件 / 接待人员消息）。"""
        return self.origin == 3


@dataclass(frozen=True)
class KfSyncBatch:
    """一次 ``sync_msg`` 调用的结果。"""

    messages: tuple[KfSyncedMessage, ...] = field(default_factory=tuple)
    next_cursor: str = ""
    has_more: bool = False


class KfSyncMessageClient:
    """``POST /cgi-bin/kf/sync_msg`` 客户端（企业微信文档 94670）。

    Args:
        token_manager: access_token 管理器（复用 :class:`~app.wecom.sender.WeComAccessTokenManager`）。
        transport: HTTP 传输实现。
        base_url: 企业微信 API 根地址。
        timeout: 单次请求超时（秒）。
        limit: 单次拉取期望数据量（默认 1000，企业微信最大值）。
    """

    def __init__(
        self,
        *,
        token_manager: WeComAccessTokenManager,
        transport: HttpTransport,
        base_url: str = DEFAULT_WECOM_API_BASE_URL,
        timeout: float = 10.0,
        limit: int = 1000,
    ) -> None:
        self._tokens = token_manager
        self._transport = transport
        self._base_url = base_url.rstrip("/")
        self._timeout = float(timeout)
        self._limit = int(limit)

    def sync_msg(
        self, *, open_kf_id: str, cursor: str = "", kf_token: str = ""
    ) -> KfSyncBatch:
        """拉取一页新消息。

        Args:
            open_kf_id: 客服账号 ID。
            cursor: 上次调用返回的 ``next_cursor``；首次拉取传空串（从最早消息开始）。
            kf_token: 通知携带的临时拉取令牌（10 分钟内有效）；``cursor`` 非空时通常
                可不传（企业微信文档：不填时接口有更严格的频率限制，建议首次拉取传）。

        Raises:
            KfSyncError: 企业微信返回非零 ``errcode``。
        """
        access_token = self._tokens.get_token()
        body: dict[str, Any] = {"open_kfid": open_kf_id, "limit": self._limit}
        if cursor:
            body["cursor"] = cursor
        if kf_token:
            body["token"] = kf_token

        response = self._post(access_token, body)
        errcode = int(response.get("errcode", 0) or 0)
        if errcode in (42001, 40014):
            # access_token 失效：刷新并重试一次。
            self._tokens.invalidate()
            response = self._post(self._tokens.get_token(force_refresh=True), body)
            errcode = int(response.get("errcode", 0) or 0)
        if errcode != 0:
            raise KfSyncError(
                f"企业微信 sync_msg 拉取失败：errcode={errcode}, "
                f"errmsg={response.get('errmsg', '')}"
            )

        messages = tuple(
            _parse_synced_message(raw) for raw in response.get("msg_list", []) or []
        )
        return KfSyncBatch(
            messages=messages,
            next_cursor=str(response.get("next_cursor", "") or ""),
            has_more=bool(response.get("has_more", 0)),
        )

    def _post(self, access_token: str, body: Mapping[str, Any]) -> Mapping[str, Any]:
        return self._transport.post_json(
            f"{self._base_url}/cgi-bin/kf/sync_msg",
            params={"access_token": access_token},
            json_body=body,
            timeout=self._timeout,
        )


def _parse_synced_message(raw: Mapping[str, Any]) -> KfSyncedMessage:
    """将 ``sync_msg`` 响应中单条消息的原始字典解析为 :class:`KfSyncedMessage`。"""
    msg_type = str(raw.get("msgtype", ""))
    text_content = ""
    if msg_type == "text":
        text_obj = raw.get("text") or {}
        if isinstance(text_obj, Mapping):
            text_content = str(text_obj.get("content", ""))
    return KfSyncedMessage(
        msg_id=str(raw.get("msgid", "")),
        open_kf_id=str(raw.get("open_kfid", "")),
        external_user_id=str(raw.get("external_userid", "")),
        send_time=int(raw.get("send_time", 0) or 0),
        origin=int(raw.get("origin", 0) or 0),
        msg_type=msg_type,
        text_content=text_content,
    )


# --------------------------------------------------------------------------- #
# 拉取游标持久化
# --------------------------------------------------------------------------- #
@runtime_checkable
class CursorStore(Protocol):
    """按客服账号持久化 ``sync_msg`` 拉取游标的协议。

    避免进程重启后重复拉取历史消息或（若游标丢失且企业微信游标已过期）漏拉消息。
    生产环境建议使用 Redis / DB 实现以在多实例间共享；单机部署可用内存实现。
    """

    def get_cursor(self, open_kf_id: str) -> str | None:
        """返回该客服账号的上次拉取游标；无记录时返回 ``None``。"""
        ...

    def set_cursor(self, open_kf_id: str, cursor: str) -> None:
        """保存该客服账号的最新拉取游标。"""
        ...


class InMemoryCursorStore:
    """进程内游标存储（测试 / 单机默认实现）。"""

    def __init__(self) -> None:
        self._cursors: dict[str, str] = {}

    def get_cursor(self, open_kf_id: str) -> str | None:
        return self._cursors.get(open_kf_id)

    def set_cursor(self, open_kf_id: str, cursor: str) -> None:
        if cursor:
            self._cursors[open_kf_id] = cursor


# --------------------------------------------------------------------------- #
# 出站回复（kf/send_msg）
# --------------------------------------------------------------------------- #
class KfMessageSendStrategy:
    """微信客服出站回复策略 ``POST /cgi-bin/kf/send_msg``（企业微信文档 94677）。

    与既有 :class:`~app.wecom.sender.AppMessageSendStrategy` 并列，可注入同一个
    :class:`~app.wecom.sender.WeComMessageSender` 复用其 access_token 管理 / 令牌失效
    重试逻辑，仅替换端点与载荷构造。

    Args:
        open_kf_id: 客服账号 ID（单门店部署场景下固定，与
            :class:`~app.wecom.sender.AppMessageSendStrategy` 的 ``agent_id`` 构造期固定
            设计一致；多客服账号场景需按需扩展为按 ``tenant_id`` 查表）。

    约束（企业微信文档 94677）：仅当客户处于"新接入待处理"或"由智能助手接待"状态时
    可调用；客户主动发消息后 48 小时内最多回复 5 条。本策略不做状态前置校验，失败时
    由调用方（:class:`WeComMessageSender`）抛出 :class:`~app.wecom.sender.WeComSendError`。
    """

    def __init__(self, *, open_kf_id: str) -> None:
        if not open_kf_id or not open_kf_id.strip():
            raise ValueError("open_kf_id 不可为空。")
        self._open_kf_id = open_kf_id.strip()

    def endpoint(self, base_url: str) -> str:
        return f"{base_url.rstrip('/')}/cgi-bin/kf/send_msg"

    def build_payload(
        self, *, tenant_id: str, external_user_id: str, text: str
    ) -> Mapping[str, Any]:
        # tenant_id 目前不参与载荷构造（保留形参以符合 MessageSendStrategy 协议）。
        return {
            "touser": external_user_id,
            "open_kfid": self._open_kf_id,
            "msgtype": "text",
            "text": {"content": text},
        }


# --------------------------------------------------------------------------- #
# 通知处理器（实现 KfEventProcessor 协议）
# --------------------------------------------------------------------------- #
class KfSyncMessageProcessor:
    """微信客服通知处理器：拉取 → 幂等去重 → 转发 Supervisor → 回复（企业微信文档 94670）。

    实现 :class:`~app.wecom.gateway.KfEventProcessor` 协议，供
    :class:`~app.wecom.gateway.WeComInboundGateway` 在收到 ``kf_msg_or_event`` 通知时
    委派处理。

    Args:
        sync_client: ``sync_msg`` 拉取客户端。
        supervisor_graph: 已编译的 Supervisor 图（转发目标，与普通消息路径共用）。
        reply_sender: 微信客服出站回复发送器（通常为注入 :class:`KfMessageSendStrategy`
            的 :class:`~app.wecom.sender.WeComMessageSender`）；``None`` 时仅转发不回复
            （便于测试 / 暂未配置出站场景）。
        idempotency_store: 按消息 ``msgid`` 去重的存储；缺省使用内存实现。
        cursor_store: 拉取游标持久化；缺省使用内存实现（进程重启后从游标缺失处重新拉取，
            可能重复处理少量消息，由幂等去重兜底）。
        max_pages: 单次通知最多翻页次数（安全上限）。

    可测试性：所有外部依赖（HTTP 传输、access_token、存储）均经构造函数注入协议接口，
    可在无真实网络 / 企业微信环境下用伪实现验证完整拉取 → 转发 → 回复流程。
    """

    def __init__(
        self,
        sync_client: KfSyncMessageClient,
        supervisor_graph: SupervisorGraph,
        *,
        reply_sender: ReplySender | None = None,
        idempotency_store: IdempotencyStore | None = None,
        cursor_store: CursorStore | None = None,
        max_pages: int = MAX_SYNC_PAGES_PER_NOTIFICATION,
    ) -> None:
        self._client = sync_client
        self._graph = supervisor_graph
        self._reply_sender = reply_sender
        self._idempotency: IdempotencyStore = idempotency_store or InMemoryIdempotencyStore()
        self._cursors: CursorStore = cursor_store or InMemoryCursorStore()
        self._max_pages = int(max_pages)

    def process(self, notification: WeComKfNotification) -> None:
        """处理一条微信客服通知：翻页拉取全部新消息并逐条转发 / 回复。

        任一消息的 Supervisor 转发或出站回复失败均**不中断**整批处理——记录日志后
        继续处理下一条，避免一条消息的故障影响同批次其它客户。
        """
        open_kf_id = notification.open_kf_id
        cursor = self._cursors.get_cursor(open_kf_id) or ""
        kf_token = notification.token

        for _ in range(self._max_pages):
            batch = self._client.sync_msg(
                open_kf_id=open_kf_id, cursor=cursor, kf_token=kf_token
            )
            # sync_msg 文档：token 仅首次调用有意义，后续翻页凭 cursor 即可。
            kf_token = ""

            for message in batch.messages:
                self._process_one(notification.tenant_id, message)

            if batch.next_cursor:
                cursor = batch.next_cursor
                self._cursors.set_cursor(open_kf_id, cursor)
            if not batch.has_more:
                break

    # -- 内部辅助 -------------------------------------------------------- #
    def _process_one(self, tenant_id: str, message: KfSyncedMessage) -> None:
        """处理单条已拉取消息：幂等去重 → 转发 Supervisor → 回复。"""
        if self._idempotency.get(message.msg_id) is not None:
            return  # 已处理过（Requirement 21.3 幂等语义在客服路径同样适用）。

        if not message.is_from_customer or message.msg_type != "text":
            # 非客户文本消息（系统事件 / 接待人员消息 / 图片语音等暂不支持的类型）：
            # 记录去重标记但不转发 Supervisor，避免误处理。
            self._idempotency.put(message.msg_id, "")
            return

        from app.agents.state import new_state  # 延迟导入，避免循环依赖

        thread_id = f"wecom-kf:{tenant_id}:{message.external_user_id}"
        state = new_state(
            tenant_id,
            messages=[("user", message.text_content)],
            external_user_id=message.external_user_id,
        )
        try:
            result = self._graph.invoke(
                state, config={"configurable": {"thread_id": thread_id}}
            )
        except Exception as exc:  # noqa: BLE001 - 单条消息故障不应中断整批处理
            logger.error(
                "微信客服消息转发 Supervisor 失败（msgid=%s）：%s: %s",
                message.msg_id,
                type(exc).__name__,
                exc,
            )
            return

        reply = extract_final_answer(result)
        self._idempotency.put(message.msg_id, reply)

        if self._reply_sender is not None:
            try:
                self._reply_sender.send(tenant_id, message.external_user_id, reply)
            except WeComSendError as exc:
                # 常见原因：客户已转人工接待（service_state ≥ 2）导致 kf/send_msg
                # 被拒绝；记录日志而不中断整批处理（企业微信文档 94677 概述）。
                logger.warning(
                    "微信客服回复发送失败（msgid=%s，可能已转人工接待）：%s",
                    message.msg_id,
                    exc,
                )
