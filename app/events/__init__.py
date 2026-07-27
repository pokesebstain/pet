"""事件驱动架构：基于 Redis Stream 的事件总线、消费者与死信队列。"""

from app.events.bus import (
    DEFAULT_CONSUMER_GROUPS,
    DEFAULT_STREAM,
    DISPATCH_DEADLINE_SECONDS,
    ConsumerGroup,
    DeliveryReport,
    EventBus,
    EventHandler,
)
from app.events.transport import (
    InMemoryStreamTransport,
    RedisStreamTransport,
    StreamMessage,
    StreamTransport,
)
from app.events.retry import (
    ALERT_SLA_SECONDS,
    Alerter,
    Clock,
    DeadLetter,
    DeadLetterQueue,
    InMemoryDeadLetterQueue,
    RaisedAlert,
    RecordingAlerter,
    RetryOutcome,
    RetryPolicy,
    RetryingConsumer,
    Sleeper,
    default_clock,
)

__all__ = [
    # 事件总线（任务 11.1）
    "EventBus",
    "ConsumerGroup",
    "DeliveryReport",
    "EventHandler",
    "DEFAULT_CONSUMER_GROUPS",
    "DEFAULT_STREAM",
    "DISPATCH_DEADLINE_SECONDS",
    # 传输层抽象与实现
    "StreamTransport",
    "StreamMessage",
    "InMemoryStreamTransport",
    "RedisStreamTransport",
    # 消费失败重试与死信队列（任务 11.2）
    "RetryPolicy",
    "RetryingConsumer",
    "RetryOutcome",
    "DeadLetter",
    "DeadLetterQueue",
    "InMemoryDeadLetterQueue",
    "Alerter",
    "RecordingAlerter",
    "RaisedAlert",
    "Clock",
    "Sleeper",
    "default_clock",
    "ALERT_SLA_SECONDS",
]
