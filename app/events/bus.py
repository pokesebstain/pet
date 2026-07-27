"""事件总线：领域事件发布与多消费者分发（任务 11.1）。

对应设计文档 "七、事件驱动数据架构"（图 7.1）与需求 18.1：

> WHEN 业务后端或健康中台产生领域事件，THE Event_Bus SHALL 在 2 秒内将该事件分发给
> Agent 触发器、特征更新消费者、通知推送消费者与审计日志消费者，且每个消费者至少
> 接收该事件一次。

本模块通过 :class:`~app.events.transport.StreamTransport` 抽象底层传输（Redis Stream
语义），从而把"发布 + 扇出分发"逻辑与具体传输解耦，便于用内存实现进行测试。

设计要点：

- **单一 stream + 四个消费者组**：所有领域事件写入同一 stream，四类消费者各自作为
  独立的消费者组订阅，Redis Stream 的消费者组扇出天然保证"每组都收到全部事件"。
- **至少一次投递**：消费者组读取消息后进入待确认列表（PEL），仅在处理成功后 ``ack``；
  处理抛异常则不确认，消息保留以待后续重投（重试 / DLQ 由任务 11.2 实现，本任务不含）。
- **2 秒预算**：:meth:`EventBus.dispatch` 接受 ``deadline_seconds``（默认 2.0），在预算
  内尽可能完成分发，超预算即停止本轮读取，避免阻塞上游。

任务 11.2 扩展：为消费失败叠加 **指数退避重试 + 死信队列（DLQ）+ 告警**（需求 18.4 /
18.5）。当 :class:`EventBus` 被注入 :class:`~app.events.retry.RetryingConsumer` 时，
``dispatch`` 会以重试语义处理失败消息；重试耗尽的事件被转入 DLQ（保留原始内容）、触发
告警，并从主 stream 确认（ack）移除。未注入时保持任务 11.1 的原有语义（失败不 ack、
消息留存 PEL 待重投）。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Callable

from app.models import DomainEvent

if TYPE_CHECKING:  # pragma: no cover - 仅类型检查期使用
    from app.events.retry import RetryingConsumer
    from app.events.transport import StreamTransport


class ConsumerGroup(str, Enum):
    """需求 18.1 要求分发到的四类消费者（各自对应一个 Redis Stream 消费者组）。"""

    AGENT_TRIGGER = "agent-trigger"        # Agent 触发器
    FEATURE_UPDATE = "feature-update"      # 特征更新消费者
    NOTIFICATION_PUSH = "notification-push"  # 通知 / 推送消费者
    AUDIT_LOG = "audit-log"                # 审计日志消费者


#: 事件分发的目标消费者组集合（顺序固定，便于稳定遍历与测试）。
DEFAULT_CONSUMER_GROUPS: tuple[ConsumerGroup, ...] = (
    ConsumerGroup.AGENT_TRIGGER,
    ConsumerGroup.FEATURE_UPDATE,
    ConsumerGroup.NOTIFICATION_PUSH,
    ConsumerGroup.AUDIT_LOG,
)

#: 领域事件写入的默认 stream 名称。
DEFAULT_STREAM = "petops:domain-events"

#: 需求 18.1 规定的分发时间预算（秒）。
DISPATCH_DEADLINE_SECONDS = 2.0

#: 事件序列化后在 stream 条目中承载完整 JSON 的字段名。
_EVENT_FIELD = "event"

# 消费者回调：接收反序列化后的领域事件；成功返回视为处理完成（将被 ack）。
EventHandler = Callable[[DomainEvent], None]


@dataclass
class DeliveryReport:
    """一轮 :meth:`EventBus.dispatch` 的分发结果，供调用方与测试内省。"""

    delivered: dict[ConsumerGroup, int] = field(default_factory=dict)
    acked: dict[ConsumerGroup, int] = field(default_factory=dict)
    failed: dict[ConsumerGroup, int] = field(default_factory=dict)
    #: 重试耗尽后转入 DLQ 的消息计数（需求 18.5，仅在注入重试消费者时非零）。
    dead_lettered: dict[ConsumerGroup, int] = field(default_factory=dict)
    timed_out: bool = False

    def total_delivered(self) -> int:
        return sum(self.delivered.values())

    def total_acked(self) -> int:
        return sum(self.acked.values())

    def total_failed(self) -> int:
        return sum(self.failed.values())

    def total_dead_lettered(self) -> int:
        return sum(self.dead_lettered.values())


class EventBus:
    """领域事件总线：发布事件并向四类消费者组扇出分发。

    Args:
        transport: 底层传输实现（Redis / 内存），见 :class:`StreamTransport`。
        stream: 领域事件写入的 stream 名称。
        consumer_groups: 参与扇出的消费者组，默认四类（需求 18.1）。

    构造时即在传输层幂等创建全部消费者组，确保随后发布的事件对每个组均可见
    （消费者组从"创建时刻的末尾"开始消费）。
    """

    def __init__(
        self,
        transport: "StreamTransport",
        *,
        stream: str = DEFAULT_STREAM,
        consumer_groups: tuple[ConsumerGroup, ...] = DEFAULT_CONSUMER_GROUPS,
        retrying_consumer: "RetryingConsumer | None" = None,
    ) -> None:
        self._transport = transport
        self._stream = stream
        self._groups = consumer_groups
        self._handlers: dict[ConsumerGroup, EventHandler] = {}
        # 注入后启用 "重试 + DLQ + 告警"（任务 11.2 / 需求 18.4、18.5）；
        # 未注入则维持任务 11.1 的原有失败语义（不 ack、留存 PEL）。
        self._retrying_consumer = retrying_consumer
        # 先建组再发布：保证事件对所有目标组可见（至少一次投递的前提）。
        for group in self._groups:
            self._transport.ensure_group(self._stream, group.value)

    @property
    def consumer_groups(self) -> tuple[ConsumerGroup, ...]:
        return self._groups

    def register_handler(self, group: ConsumerGroup, handler: EventHandler) -> None:
        """为某消费者组注册处理回调。"""
        if group not in self._groups:
            raise ValueError(f"未知消费者组: {group!r}")
        self._handlers[group] = handler

    def publish(self, event: DomainEvent) -> str:
        """发布一个领域事件到 stream，返回其消息 ID。

        事件以 JSON 形式承载于单一字段，消费端反序列化回 :class:`DomainEvent`。
        """
        fields = {
            _EVENT_FIELD: event.model_dump_json(),
            # 冗余若干标量字段，便于运维/调试期直接检视 stream 条目。
            "event_type": event.event_type,
            "tenant_id": event.tenant_id,
            "event_id": event.event_id,
        }
        return self._transport.append(self._stream, fields)

    def dispatch(
        self,
        *,
        max_messages_per_group: int = 128,
        deadline_seconds: float = DISPATCH_DEADLINE_SECONDS,
        consumer_name: str = "dispatcher-1",
    ) -> DeliveryReport:
        """在时间预算内，将新事件扇出分发给各消费者组并处理。

        对每个消费者组：读取新消息 → 反序列化 → 调用其处理回调 → 成功则 ``ack``。
        处理失败（回调抛异常）不 ``ack``，消息保留于 PEL 以待后续重投（任务 11.2）。

        Args:
            max_messages_per_group: 单组单轮读取的消息上限。
            deadline_seconds: 本轮分发的时间预算（需求 18.1：2 秒内）。
            consumer_name: 消费者名称（同组内可多消费者，本任务用单一消费者）。

        Returns:
            :class:`DeliveryReport`，含各组投递 / 确认 / 失败计数与是否超时。
        """
        report = DeliveryReport()
        deadline = time.monotonic() + deadline_seconds

        for group in self._groups:
            report.delivered.setdefault(group, 0)
            report.acked.setdefault(group, 0)
            report.failed.setdefault(group, 0)
            report.dead_lettered.setdefault(group, 0)

            if time.monotonic() >= deadline:
                report.timed_out = True
                break

            handler = self._handlers.get(group)
            messages = self._transport.read_new(
                self._stream, group.value, consumer_name, max_messages_per_group
            )
            for message_id, fields in messages:
                report.delivered[group] += 1
                event = self._deserialize(fields)

                # 未注册处理回调时，视为"已投递但无需处理"，直接确认避免堆积。
                if handler is None:
                    self._transport.ack(self._stream, group.value, message_id)
                    report.acked[group] += 1
                    continue

                if self._retrying_consumer is not None:
                    # 任务 11.2：以指数退避重试消费；耗尽则转 DLQ 并告警。
                    outcome = self._retrying_consumer.consume(
                        handler, event, group.value
                    )
                    if outcome.succeeded:
                        self._transport.ack(self._stream, group.value, message_id)
                        report.acked[group] += 1
                    else:
                        # 已转入 DLQ（保留原始内容）：视为已处理，确认以移出主 stream。
                        self._transport.ack(self._stream, group.value, message_id)
                        report.dead_lettered[group] += 1
                else:
                    try:
                        handler(event)
                    except Exception:  # noqa: BLE001 - 单个消费失败不应影响其它组/消息
                        # 至少一次投递：不 ack，消息保留待重投（未启用重试/DLQ 时）。
                        report.failed[group] += 1
                        continue

                    self._transport.ack(self._stream, group.value, message_id)
                    report.acked[group] += 1

                if time.monotonic() >= deadline:
                    report.timed_out = True
                    break

        return report

    @staticmethod
    def _deserialize(fields: dict[str, str]) -> DomainEvent:
        """从 stream 条目字段还原领域事件。"""
        return DomainEvent.model_validate_json(fields[_EVENT_FIELD])
