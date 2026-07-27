"""任务 11.1 事件总线发布与多消费者分发的单元测试。

使用内存传输（:class:`InMemoryStreamTransport`）注入，无需实时 Redis，验证：
- 一次发布的领域事件扇出分发给四类消费者组，每组至少接收一次（需求 18.1）。
- 至少一次投递语义：处理成功才确认（ack）；处理失败不确认，消息保留待重投。
- 各消费者组彼此独立，一组失败不影响其它组接收同一事件。
- 分发在时间预算（2 秒）内完成，且超时能被报告。
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.events import (
    DEFAULT_CONSUMER_GROUPS,
    ConsumerGroup,
    EventBus,
    InMemoryStreamTransport,
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


@pytest.fixture()
def bus() -> EventBus:
    return EventBus(InMemoryStreamTransport())


def test_default_four_consumer_groups() -> None:
    """默认应配置需求 18.1 规定的四类消费者组。"""
    assert set(DEFAULT_CONSUMER_GROUPS) == {
        ConsumerGroup.AGENT_TRIGGER,
        ConsumerGroup.FEATURE_UPDATE,
        ConsumerGroup.NOTIFICATION_PUSH,
        ConsumerGroup.AUDIT_LOG,
    }


def test_publish_returns_message_id(bus: EventBus) -> None:
    """发布事件应返回非空消息 ID。"""
    message_id = bus.publish(_make_event())
    assert isinstance(message_id, str)
    assert message_id


def test_fan_out_to_all_four_groups(bus: EventBus) -> None:
    """一次发布应扇出给全部四类消费者组，每组各接收一次。"""
    received: dict[ConsumerGroup, list[DomainEvent]] = {
        g: [] for g in DEFAULT_CONSUMER_GROUPS
    }
    for group in DEFAULT_CONSUMER_GROUPS:
        bus.register_handler(group, lambda evt, g=group: received[g].append(evt))

    bus.publish(_make_event(event_id="evt-42"))
    report = bus.dispatch()

    # 每个组恰好投递并确认一次。
    for group in DEFAULT_CONSUMER_GROUPS:
        assert report.delivered[group] == 1
        assert report.acked[group] == 1
        assert report.failed[group] == 0
        assert len(received[group]) == 1
        assert received[group][0].event_id == "evt-42"

    assert report.total_delivered() == 4
    assert report.total_acked() == 4
    assert report.timed_out is False


def test_event_round_trips_intact(bus: EventBus) -> None:
    """消费端收到的事件应与发布的事件字段一致（序列化往返无损）。"""
    got: list[DomainEvent] = []
    bus.register_handler(ConsumerGroup.AUDIT_LOG, got.append)

    original = _make_event(event_id="evt-round")
    bus.publish(original)
    bus.dispatch()

    assert len(got) == 1
    assert got[0] == original


def test_at_least_once_failed_handler_not_acked() -> None:
    """处理失败的组不应确认消息，消息保留在待确认列表中（至少一次投递）。"""
    transport = InMemoryStreamTransport()
    bus = EventBus(transport)

    def boom(_evt: DomainEvent) -> None:
        raise RuntimeError("consumer failure")

    audit_received: list[DomainEvent] = []
    bus.register_handler(ConsumerGroup.AGENT_TRIGGER, boom)
    bus.register_handler(ConsumerGroup.AUDIT_LOG, audit_received.append)

    bus.publish(_make_event())
    report = bus.dispatch()

    # 失败组：投递发生但未确认；成功组：正常确认。
    assert report.delivered[ConsumerGroup.AGENT_TRIGGER] == 1
    assert report.failed[ConsumerGroup.AGENT_TRIGGER] == 1
    assert report.acked[ConsumerGroup.AGENT_TRIGGER] == 0
    assert report.acked[ConsumerGroup.AUDIT_LOG] == 1

    # 失败组的消息仍处于待确认（PEL），成功组已清空。
    stream = bus._stream  # noqa: SLF001 - 测试内省
    assert transport.pending_ids(stream, ConsumerGroup.AGENT_TRIGGER.value)
    assert not transport.pending_ids(stream, ConsumerGroup.AUDIT_LOG.value)

    # 其它组不受失败组影响，同一事件仍被接收。
    assert len(audit_received) == 1


def test_multiple_events_all_delivered(bus: EventBus) -> None:
    """多条事件应全部投递给每个消费者组，顺序保持。"""
    seen: list[str] = []
    bus.register_handler(ConsumerGroup.FEATURE_UPDATE, lambda e: seen.append(e.event_id))

    for i in range(5):
        bus.publish(_make_event(event_id=f"evt-{i}"))
    report = bus.dispatch()

    assert report.delivered[ConsumerGroup.FEATURE_UPDATE] == 5
    assert seen == [f"evt-{i}" for i in range(5)]


def test_unregistered_group_auto_acks(bus: EventBus) -> None:
    """未注册回调的组应视为无需处理，直接确认以免消息堆积。"""
    bus.publish(_make_event())
    report = bus.dispatch()

    for group in DEFAULT_CONSUMER_GROUPS:
        assert report.delivered[group] == 1
        assert report.acked[group] == 1
        assert report.failed[group] == 0


def test_dispatch_respects_deadline_zero_budget(bus: EventBus) -> None:
    """零时间预算时应立即标记超时且不投递。"""
    bus.register_handler(ConsumerGroup.AUDIT_LOG, lambda _e: None)
    bus.publish(_make_event())

    report = bus.dispatch(deadline_seconds=0.0)

    assert report.timed_out is True
    assert report.total_delivered() == 0


def test_dispatch_within_two_second_budget(bus: EventBus) -> None:
    """在默认 2 秒预算内应完成分发且不超时（需求 18.1）。"""
    import time

    for group in DEFAULT_CONSUMER_GROUPS:
        bus.register_handler(group, lambda _e: None)
    for i in range(20):
        bus.publish(_make_event(event_id=f"evt-{i}"))

    start = time.monotonic()
    report = bus.dispatch()
    elapsed = time.monotonic() - start

    assert elapsed < 2.0
    assert report.timed_out is False
    assert report.total_delivered() == 20 * len(DEFAULT_CONSUMER_GROUPS)


def test_already_dispatched_events_not_redelivered(bus: EventBus) -> None:
    """已成功消费的事件在下一轮不应被重复投递（游标前移）。"""
    count = {"n": 0}
    bus.register_handler(ConsumerGroup.AUDIT_LOG, lambda _e: count.__setitem__("n", count["n"] + 1))

    bus.publish(_make_event())
    bus.dispatch()
    second = bus.dispatch()

    assert count["n"] == 1
    assert second.delivered[ConsumerGroup.AUDIT_LOG] == 0
