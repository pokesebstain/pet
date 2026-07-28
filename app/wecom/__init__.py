"""企业微信接入层：入站网关（验签/解密/转发 Supervisor）与出站回复通道。

对应设计文档 14.3 组件 A（WeComInboundGateway）与 Requirement 21（企业微信智能客服接入）。
"""

from app.wecom.gateway import (
    DEFAULT_REPLY_TEXT,
    EVENT_KF_NOTIFICATION_PROCESSED,
    EVENT_KF_NOTIFICATION_SKIPPED,
    EVENT_MESSAGE_DEDUPLICATED,
    EVENT_MESSAGE_FORWARDED,
    EVENT_SIGNATURE_REJECTED,
    FakeWeComCodec,
    GatewayEvent,
    GatewayEventSink,
    IdempotencyStore,
    InMemoryGatewayEventSink,
    InMemoryIdempotencyStore,
    KfEventProcessor,
    ReplySender,
    SupervisorGraph,
    WeComCodec,
    WeComInboundGateway,
    WeComInboundMessage,
    WeComKfNotification,
    WeComSignatureError,
    extract_final_answer,
)
from app.wecom.crypto import (
    WeComCryptoCodec,
    WeComCryptoError,
    build_echostr,
    build_encrypted_envelope,
    build_kf_notification_envelope,
)
from app.wecom.kf import (
    MAX_SYNC_PAGES_PER_NOTIFICATION,
    CursorStore,
    InMemoryCursorStore,
    KfMessageSendStrategy,
    KfSyncBatch,
    KfSyncedMessage,
    KfSyncError,
    KfSyncMessageClient,
    KfSyncMessageProcessor,
)
from app.wecom.sender import (
    DEFAULT_WECOM_API_BASE_URL,
    WECOM_TOKEN_EXPIRED_ERRCODES,
    AppMessageSendStrategy,
    HttpTransport,
    MessageSendStrategy,
    UrllibHttpTransport,
    WeComAccessTokenManager,
    WeComMessageSender,
    WeComSendError,
    WeComTokenError,
)

__all__ = [
    # 入站网关（任务 27.1）
    "WeComInboundGateway",
    "WeComInboundMessage",
    "WeComKfNotification",
    "WeComSignatureError",
    "extract_final_answer",
    # 注入接口与内存实现
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
    # 审计事件类型常量
    "EVENT_SIGNATURE_REJECTED",
    "EVENT_MESSAGE_FORWARDED",
    "EVENT_MESSAGE_DEDUPLICATED",
    "EVENT_KF_NOTIFICATION_SKIPPED",
    "EVENT_KF_NOTIFICATION_PROCESSED",
    "DEFAULT_REPLY_TEXT",
    # 真实编解码器（任务：企业微信回调端点）
    "WeComCryptoCodec",
    "WeComCryptoError",
    "build_encrypted_envelope",
    "build_echostr",
    "build_kf_notification_envelope",
    # 微信客服消息拉取与回复（sync_msg / kf/send_msg，设计 14.9 补充）
    "KfSyncedMessage",
    "KfSyncBatch",
    "KfSyncError",
    "KfSyncMessageClient",
    "CursorStore",
    "InMemoryCursorStore",
    "KfMessageSendStrategy",
    "KfSyncMessageProcessor",
    "MAX_SYNC_PAGES_PER_NOTIFICATION",
    # 出站回复通道（客户消息 → 自动预约 → 回复回推客户闭环）
    "HttpTransport",
    "UrllibHttpTransport",
    "WeComAccessTokenManager",
    "WeComMessageSender",
    "MessageSendStrategy",
    "AppMessageSendStrategy",
    "WeComSendError",
    "WeComTokenError",
    "WECOM_TOKEN_EXPIRED_ERRCODES",
    "DEFAULT_WECOM_API_BASE_URL",
]
