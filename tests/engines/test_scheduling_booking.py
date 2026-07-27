"""原子预约 `book_appointment` 单元 + 并发测试（任务 26.4）。

覆盖 Requirements 22.1, 22.2, 22.3, 22.4, 22.6, 23.4, 24.1, 24.3：
- 成功写入 CONFIRMED 预约、保证 booked_count ≤ capacity、发布 ``appointment_booked``；
- 营业时间外 → OutOfBusinessHoursError，无写入、无事件；
- 满档 → SlotFullError，无写入，发布 ``appointment_rejected_full``；
- 租户越权 → AuthorizationError，无写入；
- 时间区间无效 → InvalidParameterError，无写入；
- 并发争抢最后一个空档：仅一笔成功，绝不超容量（Property 14 场景）。

依赖经内存事务性假实现注入（:class:`InMemoryTransactionalSlotStore`），无需实时数据库。
属性测试（Property 14/15/16）属任务 26.5 / 26.6。
"""

from __future__ import annotations

import threading
from datetime import datetime, time

import pytest

from app.engines.errors import AuthorizationError, InvalidParameterError
from app.engines.scheduling import (
    APPOINTMENT_BOOKED_EVENT,
    APPOINTMENT_REJECTED_FULL_EVENT,
    InMemoryBusinessHoursProvider,
    InMemoryResourceProvider,
    InMemoryTransactionalSlotStore,
    OutOfBusinessHoursError,
    SchedulingEngine,
    SlotFullError,
)
from app.models import DomainEvent
from app.models.scheduling import (
    Appointment,
    AppointmentStatus,
    BookingRequest,
    ServiceType,
)

TENANT = "tenant-a"
SERVICE = ServiceType.GROOMING

# 2024-01-06 是周六（weekday=5）。
SLOT_START = datetime(2024, 1, 6, 14, 0)
SLOT_END = datetime(2024, 1, 6, 15, 0)


class RecordingBus:
    """记录已发布领域事件的最小事件发布器（结构化满足 BookingEventPublisher）。"""

    def __init__(self) -> None:
        self.events: list[DomainEvent] = []
        self._lock = threading.Lock()

    def publish(self, event: DomainEvent) -> str:
        with self._lock:
            self.events.append(event)
        return event.event_id

    def types(self) -> list[str]:
        return [e.event_type for e in self.events]


def _make_engine(
    *,
    capacity: int = 1,
    open_time: time = time(9, 0),
    close_time: time = time(18, 0),
    weekdays: tuple[int, ...] = (0, 1, 2, 3, 4, 5, 6),
    store: InMemoryTransactionalSlotStore | None = None,
) -> tuple[SchedulingEngine, InMemoryTransactionalSlotStore]:
    hours = InMemoryBusinessHoursProvider()
    for wd in weekdays:
        hours.set_weekday(TENANT, wd, open_time, close_time)
    resources = InMemoryResourceProvider()
    resources.set_capacity(TENANT, SERVICE, capacity)
    store = store or InMemoryTransactionalSlotStore()
    engine = SchedulingEngine(hours, resources, store, slot_minutes=60)
    return engine, store


def _request(
    *,
    tenant_id: str = TENANT,
    start_at: datetime = SLOT_START,
    end_at: datetime = SLOT_END,
) -> BookingRequest:
    return BookingRequest(
        tenant_id=tenant_id,
        customer_id="cust-1",
        pet_id="pet-1",
        service_type=SERVICE,
        start_at=start_at,
        end_at=end_at,
    )


def _confirmed_count(store: InMemoryTransactionalSlotStore) -> int:
    return store.count_overlapping_appointments(
        TENANT, SERVICE, SLOT_START, SLOT_END, {AppointmentStatus.CONFIRMED}
    )


# --------------------------------------------------------------------------- #
# 成功路径（Requirements 22.1, 22.3, 22.2）
# --------------------------------------------------------------------------- #
def test_book_appointment_success_writes_confirmed_and_emits_event() -> None:
    engine, store = _make_engine(capacity=1)
    bus = RecordingBus()

    appt = engine.book_appointment(
        _request(),
        context_tenant_id=TENANT,
        slot_locks=store,
        appointment_writer=store,
        event_bus=bus,
    )

    assert isinstance(appt, Appointment)
    assert appt.status == AppointmentStatus.CONFIRMED
    assert appt.tenant_id == TENANT
    assert appt.source == "wecom"
    # 写入落库，booked_count ≤ capacity 成立。
    assert _confirmed_count(store) == 1
    # 发布 appointment_booked（Requirement 22.3）。
    assert bus.types() == [APPOINTMENT_BOOKED_EVENT]
    assert bus.events[0].payload["appointment_id"] == appt.appointment_id
    assert bus.events[0].payload["tenant_id"] == TENANT


# --------------------------------------------------------------------------- #
# 营业时间外（Requirement 22.4）——无写入、无事件
# --------------------------------------------------------------------------- #
def test_book_appointment_out_of_business_hours_rejected_no_write() -> None:
    engine, store = _make_engine(capacity=1, open_time=time(9, 0), close_time=time(12, 0))
    bus = RecordingBus()

    with pytest.raises(OutOfBusinessHoursError):
        engine.book_appointment(
            _request(),  # 14:00-15:00 在 12:00 关门后
            context_tenant_id=TENANT,
            slot_locks=store,
            appointment_writer=store,
            event_bus=bus,
        )

    assert _confirmed_count(store) == 0  # 无任何写入
    assert bus.events == []


# --------------------------------------------------------------------------- #
# 满档（Requirements 22.2, 23.4, 24.1）——无写入，发布 rejected_full
# --------------------------------------------------------------------------- #
def test_book_appointment_full_rejected_and_emits_rejected_full() -> None:
    store = InMemoryTransactionalSlotStore()
    store.add_booking(TENANT, SERVICE, SLOT_START, SLOT_END, AppointmentStatus.CONFIRMED)
    engine, store = _make_engine(capacity=1, store=store)
    bus = RecordingBus()

    with pytest.raises(SlotFullError):
        engine.book_appointment(
            _request(),
            context_tenant_id=TENANT,
            slot_locks=store,
            appointment_writer=store,
            event_bus=bus,
        )

    # 满档不新增写入（仍为预置的 1 条）。
    assert _confirmed_count(store) == 1
    assert bus.types() == [APPOINTMENT_REJECTED_FULL_EVENT]


# --------------------------------------------------------------------------- #
# 租户越权（Requirement 24.3）——无写入
# --------------------------------------------------------------------------- #
def test_book_appointment_tenant_mismatch_raises_authorization_no_write() -> None:
    engine, store = _make_engine(capacity=1)
    bus = RecordingBus()

    with pytest.raises(AuthorizationError):
        engine.book_appointment(
            _request(tenant_id="tenant-b"),
            context_tenant_id=TENANT,
            slot_locks=store,
            appointment_writer=store,
            event_bus=bus,
        )

    assert _confirmed_count(store) == 0
    assert bus.events == []


# --------------------------------------------------------------------------- #
# 时间区间无效（Requirement 22.6）——无写入
# --------------------------------------------------------------------------- #
def test_book_appointment_invalid_interval_raises_no_write() -> None:
    engine, store = _make_engine(capacity=1)
    bus = RecordingBus()
    # 绕过模型层校验，直接构造 start_at >= end_at 的请求以验证引擎自身的防御性拒绝。
    bad_req = BookingRequest.model_construct(
        tenant_id=TENANT,
        customer_id="cust-1",
        pet_id="pet-1",
        service_type=SERVICE,
        start_at=SLOT_END,
        end_at=SLOT_START,
    )

    with pytest.raises(InvalidParameterError):
        engine.book_appointment(
            bad_req,
            context_tenant_id=TENANT,
            slot_locks=store,
            appointment_writer=store,
            event_bus=bus,
        )

    assert _confirmed_count(store) == 0
    assert bus.events == []


# --------------------------------------------------------------------------- #
# 并发争抢最后一个空档：仅一笔成功，绝不超容量（Requirements 24.1, 22.2）
# --------------------------------------------------------------------------- #
def test_book_appointment_concurrent_never_overbooks_last_slot() -> None:
    engine, store = _make_engine(capacity=1)
    bus = RecordingBus()

    results: dict[str, object] = {}
    barrier = threading.Barrier(2)

    def racer(name: str) -> None:
        barrier.wait()  # 尽量让两线程同时进入临界区争抢
        try:
            appt = engine.book_appointment(
                _request(),
                context_tenant_id=TENANT,
                slot_locks=store,
                appointment_writer=store,
                event_bus=bus,
            )
            results[name] = appt
        except SlotFullError as exc:  # noqa: PERF203 - 记录败者
            results[name] = exc

    threads = [threading.Thread(target=racer, args=(f"r{i}",)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    winners = [v for v in results.values() if isinstance(v, Appointment)]
    losers = [v for v in results.values() if isinstance(v, SlotFullError)]

    # 恰有一笔成功、一笔满档失败。
    assert len(winners) == 1
    assert len(losers) == 1
    # 绝不超容量：CONFIRMED 重叠预约数恒 == 1（== capacity）。
    assert _confirmed_count(store) == 1
    # 事件：一条 booked + 一条 rejected_full。
    assert sorted(bus.types()) == sorted(
        [APPOINTMENT_BOOKED_EVENT, APPOINTMENT_REJECTED_FULL_EVENT]
    )


def test_book_appointment_many_racers_never_exceed_capacity() -> None:
    """多轮多线程争抢：CONFIRMED 数恒 ≤ capacity（放大版并发不变式检查）。"""
    capacity = 3
    engine, store = _make_engine(capacity=capacity)
    bus = RecordingBus()

    n_racers = 12
    barrier = threading.Barrier(n_racers)
    successes: list[Appointment] = []
    lock = threading.Lock()

    def racer() -> None:
        barrier.wait()
        try:
            appt = engine.book_appointment(
                _request(),
                context_tenant_id=TENANT,
                slot_locks=store,
                appointment_writer=store,
                event_bus=bus,
            )
            with lock:
                successes.append(appt)
        except SlotFullError:
            pass

    threads = [threading.Thread(target=racer) for _ in range(n_racers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(successes) == capacity
    assert _confirmed_count(store) == capacity  # 绝不超容量
