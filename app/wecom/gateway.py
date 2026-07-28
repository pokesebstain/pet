"""企业微信入站网关（WeCom Inbound Gateway，设计文档 14.3 组件 A）。

该网关是**企业微信入站消息**驱动的一条新交互链路的入口：

    入站回调 → 验签/解密 → 还原客户消息 → 构造 AgentState（注入 tenant_id/thread_id）
    → 转发 Supervisor（AI 决策中枢）→ 出站回复文本

对应 Requirement 21 的 21.1 / 21.2 / 21.3：

- 21.1 WHEN 回调携带客户入站消息且**验签与解密通过**，网关 SHALL 还原客户消息、将映射到的
  门店 ``tenant_id`` 与会话 ``thread_id`` 注入请求上下文，并转发至 Supervisor。
- 21.2 IF 验签或解密失败，THEN 网关 SHALL **拒绝处理**该回调、**不转发**至决策中枢，并
  **记录该事件**。
- 21.3 IF 入站消息的 ``msg_id`` 与已处理消息重复，THEN 网关 SHALL **幂等去重**、不重复触发
  预约处理，并**返回首次处理的结果**。

设计约束与可测性：

- 由于无真实企业微信环境，**验签/解密与出站传输均经接口注入**：加解密与验签藏在
  :class:`WeComCodec` 协议之后，测试注入伪实现（:class:`FakeWeComCodec`），**不硬编码任何
  真实企业微信密钥**。
- Supervisor 图（:func:`~app.agents.supervisor.compile_supervisor_graph` 的编译结果）与
  幂等存储均经注入；测试使用内存假实现，可在无网络/无数据库下验证三条验收标准。
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from pydantic import Field

from app.agents.state import AgentState, new_state
from app.core.errors import PetOpsError
from app.models.base import NonBlankStr, PetOpsModel, TenantId
from app.observability.metrics import WECOM_CALLBACK_TOTAL

__all__ = [
    "WeComInboundMessage",
    "WeComKfNotification",
    "WeComCodec",
    "FakeWeComCodec",
    "SupervisorGraph",
    "IdempotencyStore",
    "InMemoryIdempotencyStore",
    "GatewayEventSink",
    "InMemoryGatewayEventSink",
    "GatewayEvent",
    "ReplySender",
    "KfEventProcessor",
    "WeComInboundGateway",
    "WeComSignatureError",
    "EVENT_SIGNATURE_REJECTED",
    "EVENT_MESSAGE_FORWARDED",
    "EVENT_MESSAGE_DEDUPLICATED",
    "EVENT_KF_NOTIFICATION_SKIPPED",
    "EVENT_KF_NOTIFICATION_PROCESSED",
    "DEFAULT_REPLY_TEXT",
    "extract_final_answer",
]

#: 验签/解密失败被拒绝的审计事件类型（Requirement 21.2）。
EVENT_SIGNATURE_REJECTED: str = "wecom_callback_rejected"

#: 消息成功还原并转发 Supervisor 的审计事件类型（Requirement 21.1）。
EVENT_MESSAGE_FORWARDED: str = "wecom_message_forwarded"

#: 重复 ``msg_id`` 命中幂等去重的审计事件类型（Requirement 21.3）。
EVENT_MESSAGE_DEDUPLICATED: str = "wecom_message_deduplicated"

#: 收到微信客服通知但未配置 ``kf_processor`` 时的审计事件类型（优雅跳过，不阻断）。
EVENT_KF_NOTIFICATION_SKIPPED: str = "wecom_kf_notification_skipped"

#: 微信客服通知已交由 ``kf_processor`` 处理（拉取消息 + 转发 + 回复）的审计事件类型。
EVENT_KF_NOTIFICATION_PROCESSED: str = "wecom_kf_notification_processed"

#: Supervisor 未产出 ``final_answer`` 时的兜底回复文案。
DEFAULT_REPLY_TEXT: str = "已收到您的消息，我们会尽快为您处理。"


def extract_final_answer(result: Mapping[str, Any]) -> str:
    """从 Supervisor 返回状态中提取回复文本，缺省时回退到兜底文案。

    公开为模块级函数，供入站网关（普通应用消息路径）与微信客服事件处理器
    （:mod:`app.wecom.kf`）共用，避免重复实现。
    """
    if isinstance(result, Mapping):
        answer = result.get("final_answer")
        if isinstance(answer, str) and answer.strip():
            return answer
    return DEFAULT_REPLY_TEXT


class WeComSignatureError(PetOpsError):
    """企业微信回调验签/解密失败错误（Requirement 21.2）。

    网关在验签失败时抛出本错误以**拒绝处理**该回调；抛出前已记录审计事件，且**不会**将
    消息转发至决策中枢，作为进入 AI 决策中枢前的安全闸门。
    """


class WeComInboundMessage(PetOpsModel):
    """企业微信入站消息（验签/解密还原后）。

    对应设计文档 14.3 组件 A 的 ``WeComInboundMessage``。租户隔离键 ``tenant_id`` 由企业微信
    corp/agent 映射到门店租户（在 :meth:`WeComCodec.decode` 内完成），非空。
    """

    tenant_id: TenantId                 # 由企业微信 corp/agent 映射到门店租户
    external_user_id: NonBlankStr       # 企业微信客户标识（外部联系人）
    customer_id: str | None = None      # 映射到平台 Customer（可能需绑定）
    content: str                        # 客户自然语言文本
    msg_id: NonBlankStr                 # 幂等去重键
    received_at: datetime = Field(default_factory=datetime.now)


class WeComKfNotification(PetOpsModel):
    """微信客服"有新消息"通知（``kf_msg_or_event`` 事件，解密还原后）。

    对应设计文档 14.9（微信客服接入补充）与企业微信文档 94670「接收消息和事件」。
    通知本身**不含**消息内容，仅携带用于调用 ``sync_msg`` 接口拉取真正消息的临时
    ``token``（10 分钟内有效，与回调验签 Token 是两个不同的值）与客服账号标识
    ``open_kf_id``。收到本通知后须：

    1. 调用 ``POST /cgi-bin/kf/sync_msg`` 携带 ``open_kf_id`` + ``token`` + ``cursor``
       拉取自上次以来的新消息（可能多条）；
    2. 对每条消息按需分配会话状态（``service_state/trans``）；
    3. 逐条转发 Supervisor 并经 ``kf/send_msg`` 回复。

    该流程由 :class:`KfEventProcessor` 实现并注入网关（见 :mod:`app.wecom.kf`）。
    """

    tenant_id: TenantId
    open_kf_id: NonBlankStr
    token: str = ""  # sync_msg 拉取令牌；通知无 token 时为空（企业微信偶发不带该字段）
    received_at: datetime = Field(default_factory=datetime.now)


@runtime_checkable
class WeComCodec(Protocol):
    """企业微信回调编解码器（验签 + 解密/还原）。

    将加解密与签名校验的实现细节隔离在协议之后：生产环境由真实的企业微信加解密库实现
    （携带 corp 密钥 / token / EncodingAESKey，从配置注入，**绝不硬编码**）；测试注入
    :class:`FakeWeComCodec`，在无真实密钥的情况下模拟验签成功/失败与消息还原。
    """

    def verify_signature(self, raw: Mapping[str, Any]) -> bool:
        """校验回调签名，通过返回 ``True``，否则返回 ``False``。"""
        ...

    def decode(self, raw: Mapping[str, Any]) -> WeComInboundMessage:
        """解密并还原为 :class:`WeComInboundMessage`（含 corp/agent→tenant_id 映射）。

        仅适用于自建应用普通消息；微信客服通知请用 :meth:`is_kf_notification` 先判断，
        再改用 :meth:`decode_kf_notification`（真实实现 :class:`~app.wecom.crypto.WeComCryptoCodec`
        同时提供两者；测试伪实现 :class:`FakeWeComCodec` 默认仅支持普通消息路径）。
        """
        ...

    def is_kf_notification(self, raw: Mapping[str, Any]) -> bool:  # pragma: no cover - 协议声明
        """判断本次回调是否为微信客服"有新消息"通知（``kf_msg_or_event``）。"""
        ...

    def decode_kf_notification(
        self, raw: Mapping[str, Any]
    ) -> WeComKfNotification:  # pragma: no cover - 协议声明
        """解密并还原为 :class:`WeComKfNotification`（微信客服通知专用）。"""
        ...


@runtime_checkable
class KfEventProcessor(Protocol):
    """微信客服"有新消息"通知的处理器：拉取消息 → 转发 Supervisor → 回复客户。

    真实实现 :class:`~app.wecom.kf.KfSyncMessageProcessor` 调用 ``sync_msg`` 接口拉取自
    上次以来的新消息（可能多条），对每条消息执行既有的"构造 AgentState → 转发 Supervisor
    → 经 kf/send_msg 回复"流程。测试可注入伪实现验证网关的路由与幂等/审计逻辑。
    """

    def process(
        self, notification: WeComKfNotification
    ) -> None:  # pragma: no cover - 协议声明
        """处理一条微信客服通知（可能拉取到零至多条消息，内部完成转发与回复）。"""
        ...


@runtime_checkable
class SupervisorGraph(Protocol):
    """AI 决策中枢（已编译的 Supervisor 图）的最小调用协议。

    与 :func:`~app.agents.supervisor.compile_supervisor_graph` 的返回对象一致：以
    ``config={"configurable": {"thread_id": <id>}}`` 调用可按会话线程持久化多轮状态。
    """

    def invoke(
        self, state: AgentState, config: Mapping[str, Any] | None = ...
    ) -> Mapping[str, Any]:
        ...


@runtime_checkable
class IdempotencyStore(Protocol):
    """按 ``msg_id`` 幂等去重的存储协议（Requirement 21.3）。"""

    def get(self, msg_id: str) -> str | None:
        """返回该 ``msg_id`` 首次处理的回复；未处理过返回 ``None``。"""
        ...

    def put(self, msg_id: str, reply: str) -> None:
        """记录该 ``msg_id`` 的首次处理结果。"""
        ...


class InMemoryIdempotencyStore:
    """进程内幂等存储（测试/单机默认实现）。

    生产可替换为 Redis/DB 实现以在多实例间共享去重状态。
    """

    def __init__(self) -> None:
        self._seen: dict[str, str] = {}

    def get(self, msg_id: str) -> str | None:
        return self._seen.get(msg_id)

    def put(self, msg_id: str, reply: str) -> None:
        # 仅保留首次结果：已存在则不覆盖，保证"返回首次处理的结果"。
        self._seen.setdefault(msg_id, reply)


class GatewayEvent(PetOpsModel):
    """网关记录的审计事件（Requirement 21.2 要求记录被拒事件）。"""

    event_type: NonBlankStr
    payload: dict[str, Any] = Field(default_factory=dict)
    recorded_at: datetime = Field(default_factory=datetime.now)


@runtime_checkable
class GatewayEventSink(Protocol):
    """网关审计事件记录汇（Requirement 21.2）。"""

    def record(self, event_type: str, payload: Mapping[str, Any]) -> None:
        ...


class InMemoryGatewayEventSink:
    """进程内事件记录汇（测试默认实现）。"""

    def __init__(self) -> None:
        self.events: list[GatewayEvent] = []

    def record(self, event_type: str, payload: Mapping[str, Any]) -> None:
        self.events.append(GatewayEvent(event_type=event_type, payload=dict(payload)))


@runtime_checkable
class ReplySender(Protocol):
    """企业微信出站回复发送器（扩展自既有企业微信推送通道）。

    可选注入；注入后网关在返回回复文本的同时经该通道推送给客户。
    """

    def send(self, tenant_id: str, external_user_id: str, text: str) -> None:
        ...


class WeComInboundGateway:
    """企业微信入站网关（设计文档 14.3 组件 A）。

    Args:
        codec: 验签/解密编解码器（:class:`WeComCodec`）。加解密与验签藏在其后，测试注入
            :class:`FakeWeComCodec`。
        supervisor_graph: 已编译的 Supervisor 图（:class:`SupervisorGraph`），转发目标。
        idempotency_store: 按 ``msg_id`` 去重的存储；缺省使用内存实现（Requirement 21.3）。
        event_sink: 审计事件记录汇；缺省使用内存实现（Requirement 21.2）。
        reply_sender: 可选出站回复发送器；注入后在返回回复文本的同时推送给客户。
        kf_processor: 可选微信客服通知处理器（:class:`KfEventProcessor`）。收到
            ``kf_msg_or_event`` 通知时：已注入则委派给它完成"拉取 sync_msg → 转发
            Supervisor → kf/send_msg 回复"；未注入则**优雅跳过**（记录审计事件、不报错，
            因为普通应用消息路径不受影响，微信客服是可选能力）。
    """

    def __init__(
        self,
        codec: WeComCodec,
        supervisor_graph: SupervisorGraph,
        *,
        idempotency_store: IdempotencyStore | None = None,
        event_sink: GatewayEventSink | None = None,
        reply_sender: ReplySender | None = None,
        kf_processor: KfEventProcessor | None = None,
    ) -> None:
        self._codec = codec
        self._graph = supervisor_graph
        self._store: IdempotencyStore = idempotency_store or InMemoryIdempotencyStore()
        self._events: GatewayEventSink = event_sink or InMemoryGatewayEventSink()
        self._reply_sender = reply_sender
        self._kf_processor = kf_processor

    # -- 设计文档 14.3 组件 A 接口 ------------------------------------------

    def verify_signature(self, raw: Mapping[str, Any]) -> bool:
        """校验回调签名（委派给注入的编解码器）。"""
        return self._codec.verify_signature(raw)

    def decode(self, raw: Mapping[str, Any]) -> WeComInboundMessage:
        """解密并还原入站消息（委派给注入的编解码器）。"""
        return self._codec.decode(raw)

    def handle(self, raw: Mapping[str, Any]) -> str:
        """处理一次企业微信回调，返回面向客户的回复文本。

        流程（对应 21.1 / 21.2 / 21.3）：

        1. **验签**：失败则记录被拒事件、**不转发**决策中枢并抛出
           :class:`WeComSignatureError`（21.2）。
        2. **解密/还原**为 :class:`WeComInboundMessage`。
        3. **幂等去重**：若 ``msg_id`` 已处理，直接返回首次结果，不重复触发（21.3）。
        4. **构造 AgentState** 注入 ``tenant_id``，以 ``thread_id`` 复用会话并**转发
           Supervisor**（21.1）。
        5. 记录首次结果用于去重，可选经出站通道推送回复。

        Raises:
            WeComSignatureError: 验签/解密失败时（已记录事件、未转发）。
        """
        # 1) 验签失败 → 拒绝、记录、不进入决策中枢（Requirement 21.2）。
        if not self.verify_signature(raw):
            self._events.record(
                EVENT_SIGNATURE_REJECTED,
                {"reason": "signature_verification_failed", "raw_keys": sorted(raw)},
            )
            WECOM_CALLBACK_TOTAL.labels(outcome="rejected").inc()
            raise WeComSignatureError(
                "企业微信回调验签/解密失败，已拒绝处理且未转发至决策中枢（Requirement 21.2）。"
            )

        # 1.5) 微信客服"有新消息"通知（kf_msg_or_event）：与普通应用消息是两条不同的
        # 回调路径——通知本身不含消息内容，需交由 kf_processor 拉取真正消息（企业微信
        # 文档 94670）。未注入 kf_processor 时优雅跳过（记录事件、返回默认回复），
        # 不影响普通应用消息路径，也不误当作空文本消息转发 Supervisor。
        is_kf = getattr(self._codec, "is_kf_notification", None)
        if is_kf is not None and is_kf(raw):
            return self._handle_kf_notification(raw)

        # 2) 解密/还原客户消息。
        message = self.decode(raw)

        # 3) 幂等去重：重复 msg_id 返回首次结果，不重复触发（Requirement 21.3）。
        cached = self._store.get(message.msg_id)
        if cached is not None:
            self._events.record(
                EVENT_MESSAGE_DEDUPLICATED,
                {"msg_id": message.msg_id, "tenant_id": message.tenant_id},
            )
            WECOM_CALLBACK_TOTAL.labels(outcome="deduplicated").inc()
            return cached

        # 4) 构造 AgentState（注入 tenant_id）并按 thread_id 复用会话转发 Supervisor。
        thread_id = self._derive_thread_id(message)
        state = new_state(
            message.tenant_id,
            messages=[{"role": "user", "content": message.content}],
            # 透传企业微信外部联系人标识，供接待预约 Agent 消解客户 / 宠物（设计 14）。
            external_user_id=message.external_user_id,
            customer_id=message.customer_id,
        )
        result = self._graph.invoke(
            state, config={"configurable": {"thread_id": thread_id}}
        )
        reply = self._extract_reply(result)

        # 5) 记录首次结果供去重，并记录转发审计事件；可选推送出站回复。
        self._store.put(message.msg_id, reply)
        self._events.record(
            EVENT_MESSAGE_FORWARDED,
            {
                "msg_id": message.msg_id,
                "tenant_id": message.tenant_id,
                "thread_id": thread_id,
            },
        )
        WECOM_CALLBACK_TOTAL.labels(outcome="forwarded").inc()
        if self._reply_sender is not None:
            self._reply_sender.send(message.tenant_id, message.external_user_id, reply)
        return reply

    # -- 内部辅助 ------------------------------------------------------------

    def _handle_kf_notification(self, raw: Mapping[str, Any]) -> str:
        """处理微信客服"有新消息"通知：委派给 ``kf_processor`` 或优雅跳过。

        通知本身不含消息内容，因此本方法**不做幂等去重 / 不转发 Supervisor**——真正的
        消息拉取、去重、转发与回复均在 ``kf_processor.process()`` 内部完成（该处理器
        按 ``sync_msg`` 返回的每条消息 ``msgid`` 做自己的幂等去重）。返回值仅用于满足
        企业微信要求的同步 200 响应，不代表实际回复内容。
        """
        decode_kf = getattr(self._codec, "decode_kf_notification", None)
        if decode_kf is None or self._kf_processor is None:
            self._events.record(
                EVENT_KF_NOTIFICATION_SKIPPED,
                {"reason": "kf_processor_not_configured"},
            )
            WECOM_CALLBACK_TOTAL.labels(outcome="kf_skipped").inc()
            return DEFAULT_REPLY_TEXT

        notification = decode_kf(raw)
        self._kf_processor.process(notification)
        self._events.record(
            EVENT_KF_NOTIFICATION_PROCESSED,
            {"tenant_id": notification.tenant_id, "open_kf_id": notification.open_kf_id},
        )
        WECOM_CALLBACK_TOTAL.labels(outcome="kf_processed").inc()
        return DEFAULT_REPLY_TEXT

    @staticmethod
    def _derive_thread_id(message: WeComInboundMessage) -> str:
        """按（租户, 外部联系人）派生稳定的会话 ``thread_id``，以复用多轮上下文。"""
        return f"wecom:{message.tenant_id}:{message.external_user_id}"

    @staticmethod
    def _extract_reply(result: Mapping[str, Any]) -> str:
        """从 Supervisor 返回状态中提取回复文本，缺省时回退到兜底文案。"""
        return extract_final_answer(result)


class FakeWeComCodec:
    """测试用伪编解码器：不含任何真实密钥/加解密。

    通过 ``valid`` 控制验签结果，通过 ``message`` 指定 :meth:`decode` 还原的消息；也可提供
    ``message_factory`` 以按 ``raw`` 动态构造消息（例如从 raw 中取 ``msg_id`` 模拟去重）。
    默认 :meth:`is_kf_notification` 恒返回 ``False``（即普通消息路径），可传入
    ``kf_notification`` 模拟微信客服通知场景。
    """

    def __init__(
        self,
        *,
        valid: bool = True,
        message: WeComInboundMessage | None = None,
        message_factory: Any = None,
        kf_notification: WeComKfNotification | None = None,
    ) -> None:
        self._valid = valid
        self._message = message
        self._message_factory = message_factory
        self._kf_notification = kf_notification

    def verify_signature(self, raw: Mapping[str, Any]) -> bool:
        return self._valid

    def decode(self, raw: Mapping[str, Any]) -> WeComInboundMessage:
        if self._message_factory is not None:
            return self._message_factory(raw)
        if self._message is not None:
            return self._message
        raise ValueError("FakeWeComCodec 需要提供 message 或 message_factory 才能 decode。")

    def is_kf_notification(self, raw: Mapping[str, Any]) -> bool:  # noqa: ARG002
        return self._kf_notification is not None

    def decode_kf_notification(self, raw: Mapping[str, Any]) -> WeComKfNotification:  # noqa: ARG002
        if self._kf_notification is None:
            raise ValueError("FakeWeComCodec 未配置 kf_notification，无法模拟微信客服通知。")
        return self._kf_notification
