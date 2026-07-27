"""任务 11.2 消费失败重试与死信队列（DLQ）的单元测试（需求 18.4 / 18.5）。

时钟与告警器均注入内存实现、``sleep`` 注入无操作函数，使测试在毫秒级完成且无需实时
Redis，同时可确定性地验证：
- 指数退避的时长序列（初始 1s、翻倍、封顶 8s、最多 3 次）。
- 首次或重试成功即不进入 DLQ；重试耗尽才转入 DLQ。
- 转入 DLQ 的记录完整保留原始事件内容。
- 转入 DLQ 后触发告警，且告警时延满足 60s SLA。
- 与事件总线集成：耗尽的消息转 DLQ 后从主 stream 确认移除，其它组不受影响。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.events import (
    ALERT_SLA_SECONDS,
    ConsumerGroup,
    EventBus,
    InMemoryDeadLetterQueue,
    InMemoryStreamTransport,
    RecordingAlerter,
    RetryingConsumer,
    RetryPolicy,
)
from app.models import DomainEvent


def _make_event(event_id: str = "evt-1", tenant_id: str = "store_88") -> DomainEvent:
    return DomainEvent(
        event_id=event_id,
        tenant_id=tenant_id,
        event_type="health_alert",
        payload={"level": "high", "pet_id": "pet-1"},
        occurred_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


class _FakeClock:
    """确定性时钟：每次调用推进固定步长，便于校验告警时延。"""

    def __init__(self, start: datetime, step: timedelta = timedelta(seconds=0)) -> None:
        self._now = start
        self._step = step

    def __call__(self) -> datetime:
        current = self._now
        self._now = self._now + self._step
        return current


# --- RetryPolicy 退避计算 ---------------------------------------------------


def test_retry_policy_default_backoff_sequence() -> None:
    """默认策略退避应为 1s → 2s → 4s（翻倍且封顶 8s），共 3 次重试。"""
    policy = RetryPolicy()
    assert policy.max_retries == 3
    assert policy.delays() == [1.0, 2.0, 4.0]


def test_retry_policy_backoff_capped_at_max_delay() -> None:
    """退避时长应封顶于 max_delay。"""
    policy = RetryPolicy(max_retries=5, base_delay=1.0, factor=2.0, max_delay=8.0)
    # 1, 2, 4, 8, 8（第 4、5 次被 max_delay 封顶）。
    assert policy.delays() == [1.0, 2.0, 4.0, 8.0, 8.0]


def test_retry_policy_rejects_invalid_config() -> None:
    with pytest.raises(ValueError):
        RetryPolicy(max_retries=-1)
    with pytest.raises(ValueError):
        RetryPolicy(factor=0.5)


# --- RetryingConsumer 行为 --------------------------------------------------


def _make_consumer(**kwargs) -> tuple[RetryingConsumer, InMemoryDeadLetterQueue, RecordingAlerter, list[float]]:
    dlq = InMemoryDeadLetterQueue()
    alerter = RecordingAlerter()
    slept: list[float] = []
    consumer = RetryingConsumer(
        dead_letter_queue=dlq,
        alerter=alerter,
        sleep=slept.append,  # 无操作：仅记录退避时长，不真正等待
        **kwargs,
    )
    return consumer, dlq, alerter, slept


def test_success_on_first_attempt_no_retry_no_dlq() -> None:
    consumer, dlq, alerter, slept = _make_consumer()
    calls = {"n": 0}

    def handler(_e: DomainEvent) -> None:
        calls["n"] += 1

    outcome = consumer.consume(handler, _make_event(), ConsumerGroup.AUDIT_LOG.value)

    assert outcome.succeeded is True
    assert outcome.attempts == 1
    assert calls["n"] == 1
    assert slept == []            # 未失败，无退避
    assert len(dlq) == 0
    assert len(alerter) == 0


def test_success_after_transient_failures() -> None:
    """前两次失败、第三次成功：应在重试预算内成功，不进入 DLQ。"""
    consumer, dlq, alerter, slept = _make_consumer()
    attempts = {"n": 0}

    def handler(_e: DomainEvent) -> None:
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise RuntimeError("transient")

    outcome = consumer.consume(handler, _make_event(), ConsumerGroup.FEATURE_UPDATE.value)

    assert outcome.succeeded is True
    assert outcome.attempts == 3
    assert slept == [1.0, 2.0]    # 两次失败对应两次退避
    assert len(dlq) == 0
    assert len(alerter) == 0


def test_retries_at_most_three_times_then_dead_letters() -> None:
    """始终失败：总尝试 4 次（1 首次 + 3 重试），随后转入 DLQ（需求 18.4）。"""
    consumer, dlq, alerter, slept = _make_consumer()
    calls = {"n": 0}

    def always_fail(_e: DomainEvent) -> None:
        calls["n"] += 1
        raise RuntimeError("permanent failure")

    outcome = consumer.consume(always_fail, _make_event(), ConsumerGroup.AGENT_TRIGGER.value)

    assert calls["n"] == 4                # 首次 + 3 次重试
    assert outcome.succeeded is False
    assert outcome.attempts == 4
    assert outcome.dead_lettered is True
    assert slept == [1.0, 2.0, 4.0]       # 恰好 3 次退避
    assert len(dlq) == 1


def test_dead_letter_preserves_original_event_content() -> None:
    """转入 DLQ 的记录应完整保留原始事件内容（需求 18.5）。"""
    consumer, dlq, alerter, _ = _make_consumer()
    original = _make_event(event_id="evt-preserve", tenant_id="store_99")

    def always_fail(_e: DomainEvent) -> None:
        raise ValueError("boom")

    consumer.consume(always_fail, original, ConsumerGroup.AGENT_TRIGGER.value)

    record = dlq.records[0]
    assert record.event == original       # 原始内容无损保留
    assert record.event.event_id == "evt-preserve"
    assert record.event.payload == {"level": "high", "pet_id": "pet-1"}
    assert record.consumer_group == ConsumerGroup.AGENT_TRIGGER.value
    assert record.attempts == 4
    assert "boom" in record.error


def test_alert_triggered_within_sla_after_dead_letter() -> None:
    """转入 DLQ 后应触发告警，且告警时延满足 60s SLA（需求 18.5）。"""
    clock = _FakeClock(
        start=datetime(2026, 1, 1, tzinfo=timezone.utc),
        step=timedelta(seconds=1),  # failed_at 与 raised_at 相差 1s
    )
    consumer, dlq, alerter, _ = _make_consumer(clock=clock)

    def always_fail(_e: DomainEvent) -> None:
        raise RuntimeError("nope")

    outcome = consumer.consume(always_fail, _make_event(), ConsumerGroup.NOTIFICATION_PUSH.value)

    assert outcome.alerted is True
    assert len(alerter) == 1
    raised = alerter.alerts[0]
    assert raised.dead_letter is dlq.records[0]
    assert raised.latency_seconds() == 1.0
    assert raised.latency_seconds() <= ALERT_SLA_SECONDS


# --- 与 EventBus 集成 -------------------------------------------------------


def test_bus_dead_letters_after_retries_and_acks_message() -> None:
    """事件总线注入重试消费者后：失败事件耗尽重试转 DLQ，并从主 stream 确认移除。"""
    transport = InMemoryStreamTransport()
    dlq = InMemoryDeadLetterQueue()
    alerter = RecordingAlerter()
    consumer = RetryingConsumer(dead_letter_queue=dlq, alerter=alerter, sleep=lambda _s: None)
    bus = EventBus(transport, retrying_consumer=consumer)

    def boom(_e: DomainEvent) -> None:
        raise RuntimeError("consumer failure")

    audit_seen: list[DomainEvent] = []
    bus.register_handler(ConsumerGroup.AGENT_TRIGGER, boom)
    bus.register_handler(ConsumerGroup.AUDIT_LOG, audit_seen.append)

    bus.publish(_make_event(event_id="evt-dlq"))
    report = bus.dispatch()

    # 失败组：转入 DLQ、告警一次、并已 ack（不再滞留 PEL）。
    assert report.dead_lettered[ConsumerGroup.AGENT_TRIGGER] == 1
    assert report.failed[ConsumerGroup.AGENT_TRIGGER] == 0
    assert len(dlq) == 1
    assert dlq.records[0].event.event_id == "evt-dlq"
    assert len(alerter) == 1
    stream = bus._stream  # noqa: SLF001 - 测试内省
    assert not transport.pending_ids(stream, ConsumerGroup.AGENT_TRIGGER.value)

    # 成功组不受影响，正常接收并确认。
    assert report.acked[ConsumerGroup.AUDIT_LOG] == 1
    assert len(audit_seen) == 1
    assert report.total_dead_lettered() == 1


def test_bus_without_retrying_consumer_keeps_at_least_once_semantics() -> None:
    """未注入重试消费者时，失败消息保持任务 11.1 语义（不 ack、留存 PEL）。"""
    transport = InMemoryStreamTransport()
    bus = EventBus(transport)

    def boom(_e: DomainEvent) -> None:
        raise RuntimeError("fail")

    bus.register_handler(ConsumerGroup.AGENT_TRIGGER, boom)
    bus.publish(_make_event())
    report = bus.dispatch()

    assert report.failed[ConsumerGroup.AGENT_TRIGGER] == 1
    assert report.dead_lettered[ConsumerGroup.AGENT_TRIGGER] == 0
    stream = bus._stream  # noqa: SLF001 - 测试内省
    assert transport.pending_ids(stream, ConsumerGroup.AGENT_TRIGGER.value)
