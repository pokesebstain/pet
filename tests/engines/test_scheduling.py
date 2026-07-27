"""排期引擎单元测试（任务 26.3 / Requirements 22.1, 22.4, 23.1, 23.2, 23.3）。

覆盖：
- ``check_availability``：营业时间判定（完全落入 / 越界 / 非营业日 / 跨天）、
  ``available = max(capacity - booked, 0) ≥ 0``、非法入参拒绝（22.1, 22.4）。
- ``get_day_schedule``：按粒度枚举营业时段、填充容量与已订数、非营业日返回空（23.1）。
- ``suggest_alternatives``：仅返回 ``available > 0`` 且在营业时间内的时段、
  按接近度升序（同天优先）、数量 ≤ N、搜索期内无可用返回空、非法入参拒绝（23.2, 23.3）。

依赖经内存假实现注入，无需实时数据库。属性测试（Property 15/16）属任务 26.6。
"""

from __future__ import annotations

from datetime import datetime, time

import pytest

from app.engines.errors import InvalidParameterError
from app.engines.scheduling import (
    InMemoryAppointmentProvider,
    InMemoryBusinessHoursProvider,
    InMemoryResourceProvider,
    SchedulingEngine,
    SlotAvailability,
)
from app.models.scheduling import AppointmentStatus, ServiceType

TENANT = "tenant-a"
SERVICE = ServiceType.GROOMING

# 2024-01-06 是周六（weekday=5）。
SATURDAY = datetime(2024, 1, 6, 14, 0)


def _make_engine(
    *,
    capacity: int = 1,
    slot_minutes: int = 60,
    open_time: time = time(9, 0),
    close_time: time = time(18, 0),
    weekdays: tuple[int, ...] = (0, 1, 2, 3, 4, 5, 6),
    bookings: list[tuple[datetime, datetime, AppointmentStatus]] | None = None,
) -> SchedulingEngine:
    hours = InMemoryBusinessHoursProvider()
    for wd in weekdays:
        hours.set_weekday(TENANT, wd, open_time, close_time)
    resources = InMemoryResourceProvider()
    resources.set_capacity(TENANT, SERVICE, capacity)
    appts = InMemoryAppointmentProvider()
    for start, end, status in bookings or []:
        appts.add_booking(TENANT, SERVICE, start, end, status)
    return SchedulingEngine(hours, resources, appts, slot_minutes=slot_minutes)


# --------------------------------------------------------------------------- #
# check_availability
# --------------------------------------------------------------------------- #
def test_check_availability_within_hours_free() -> None:
    engine = _make_engine(capacity=2)
    avail = engine.check_availability(
        TENANT, SERVICE, datetime(2024, 1, 6, 14, 0), datetime(2024, 1, 6, 15, 0)
    )
    assert isinstance(avail, SlotAvailability)
    assert avail.in_business_hours is True
    assert avail.capacity == 2
    assert avail.booked == 0
    assert avail.available == 2


def test_check_availability_counts_overlapping_pending_and_confirmed() -> None:
    engine = _make_engine(
        capacity=2,
        bookings=[
            (datetime(2024, 1, 6, 14, 30), datetime(2024, 1, 6, 15, 30), AppointmentStatus.CONFIRMED),
            (datetime(2024, 1, 6, 13, 30), datetime(2024, 1, 6, 14, 30), AppointmentStatus.PENDING),
            # 已取消不计入
            (datetime(2024, 1, 6, 14, 0), datetime(2024, 1, 6, 15, 0), AppointmentStatus.CANCELLED),
        ],
    )
    avail = engine.check_availability(
        TENANT, SERVICE, datetime(2024, 1, 6, 14, 0), datetime(2024, 1, 6, 15, 0)
    )
    assert avail.booked == 2
    assert avail.available == 0


def test_check_availability_available_never_negative() -> None:
    # 已订超过容量（异常数据）时 available 仍 clamp 到 0。
    engine = _make_engine(
        capacity=1,
        bookings=[
            (datetime(2024, 1, 6, 14, 0), datetime(2024, 1, 6, 15, 0), AppointmentStatus.CONFIRMED),
            (datetime(2024, 1, 6, 14, 0), datetime(2024, 1, 6, 15, 0), AppointmentStatus.CONFIRMED),
        ],
    )
    avail = engine.check_availability(
        TENANT, SERVICE, datetime(2024, 1, 6, 14, 0), datetime(2024, 1, 6, 15, 0)
    )
    assert avail.booked == 2
    assert avail.available == 0


def test_check_availability_out_of_hours_end_after_close() -> None:
    engine = _make_engine(capacity=1, close_time=time(18, 0))
    avail = engine.check_availability(
        TENANT, SERVICE, datetime(2024, 1, 6, 17, 30), datetime(2024, 1, 6, 18, 30)
    )
    assert avail.in_business_hours is False


def test_check_availability_before_open() -> None:
    engine = _make_engine(capacity=1, open_time=time(9, 0))
    avail = engine.check_availability(
        TENANT, SERVICE, datetime(2024, 1, 6, 8, 0), datetime(2024, 1, 6, 9, 30)
    )
    assert avail.in_business_hours is False


def test_check_availability_non_business_day() -> None:
    # 仅周一营业，周六请求 → 非营业时间。
    engine = _make_engine(capacity=1, weekdays=(0,))
    avail = engine.check_availability(
        TENANT, SERVICE, datetime(2024, 1, 6, 14, 0), datetime(2024, 1, 6, 15, 0)
    )
    assert avail.in_business_hours is False


def test_check_availability_rejects_invalid_interval() -> None:
    engine = _make_engine()
    with pytest.raises(InvalidParameterError):
        engine.check_availability(
            TENANT, SERVICE, datetime(2024, 1, 6, 15, 0), datetime(2024, 1, 6, 15, 0)
        )


def test_check_availability_rejects_blank_tenant() -> None:
    engine = _make_engine()
    with pytest.raises(InvalidParameterError):
        engine.check_availability(
            "  ", SERVICE, datetime(2024, 1, 6, 14, 0), datetime(2024, 1, 6, 15, 0)
        )


# --------------------------------------------------------------------------- #
# get_day_schedule
# --------------------------------------------------------------------------- #
def test_get_day_schedule_enumerates_hourly_slots() -> None:
    engine = _make_engine(capacity=1, open_time=time(9, 0), close_time=time(12, 0))
    schedule = engine.get_day_schedule(TENANT, SERVICE, SATURDAY.date())
    # 9-10, 10-11, 11-12 → 3 个时段
    assert len(schedule) == 3
    assert [s.start_at.hour for s in schedule] == [9, 10, 11]
    assert all(s.capacity == 1 for s in schedule)


def test_get_day_schedule_reflects_bookings() -> None:
    engine = _make_engine(
        capacity=1,
        open_time=time(9, 0),
        close_time=time(11, 0),
        bookings=[
            (datetime(2024, 1, 6, 9, 0), datetime(2024, 1, 6, 10, 0), AppointmentStatus.CONFIRMED),
        ],
    )
    schedule = engine.get_day_schedule(TENANT, SERVICE, SATURDAY.date())
    assert schedule[0].booked_count == 1
    assert schedule[0].available == 0
    assert schedule[1].booked_count == 0
    assert schedule[1].available == 1


def test_get_day_schedule_empty_on_non_business_day() -> None:
    engine = _make_engine(capacity=1, weekdays=(0,))
    assert engine.get_day_schedule(TENANT, SERVICE, SATURDAY.date()) == []


def test_get_day_schedule_drops_partial_trailing_slot() -> None:
    # 9:00-10:30 且粒度 60min → 仅 9-10 一个完整时段。
    engine = _make_engine(
        capacity=1, open_time=time(9, 0), close_time=time(10, 30), slot_minutes=60
    )
    schedule = engine.get_day_schedule(TENANT, SERVICE, SATURDAY.date())
    assert len(schedule) == 1
    assert schedule[0].start_at.hour == 9


# --------------------------------------------------------------------------- #
# suggest_alternatives
# --------------------------------------------------------------------------- #
def test_suggest_alternatives_all_available_and_in_hours() -> None:
    engine = _make_engine(capacity=1, open_time=time(9, 0), close_time=time(18, 0))
    result = engine.suggest_alternatives(TENANT, SERVICE, SATURDAY, n=3)
    assert len(result) == 3
    for slot in result:
        assert slot.available > 0
        avail = engine.check_availability(
            TENANT, SERVICE, slot.start_at, slot.end_at
        )
        assert avail.in_business_hours is True


def test_suggest_alternatives_orders_by_proximity_same_day_first() -> None:
    engine = _make_engine(capacity=1, open_time=time(9, 0), close_time=time(18, 0))
    result = engine.suggest_alternatives(TENANT, SERVICE, SATURDAY, n=3)
    # 期望 14:00：最近的应是 14-15（距离 0），其次 13-14 与 15-16。
    assert result[0].start_at == datetime(2024, 1, 6, 14, 0)
    # 均为同一天，按接近度升序
    keys = [
        engine._proximity_key(s.start_at, SATURDAY) for s in result
    ]
    assert keys == sorted(keys)


def test_suggest_alternatives_excludes_full_slots() -> None:
    # 14-15 满档，返回的备选不应包含它。
    engine = _make_engine(
        capacity=1,
        open_time=time(9, 0),
        close_time=time(18, 0),
        bookings=[
            (datetime(2024, 1, 6, 14, 0), datetime(2024, 1, 6, 15, 0), AppointmentStatus.CONFIRMED),
        ],
    )
    result = engine.suggest_alternatives(TENANT, SERVICE, SATURDAY, n=5)
    assert all(
        not (s.start_at == datetime(2024, 1, 6, 14, 0)) for s in result
    )
    assert all(s.available > 0 for s in result)


def test_suggest_alternatives_respects_limit_n() -> None:
    engine = _make_engine(capacity=1, open_time=time(9, 0), close_time=time(18, 0))
    result = engine.suggest_alternatives(TENANT, SERVICE, SATURDAY, n=2)
    assert len(result) == 2


def test_suggest_alternatives_searches_future_days() -> None:
    # 周六满档整天（capacity 0 那天不行，改用只有周日营业）。
    engine = _make_engine(
        capacity=1,
        open_time=time(9, 0),
        close_time=time(18, 0),
        weekdays=(6,),  # 仅周日营业
    )
    # 周六请求，应回退到周日（次日）
    result = engine.suggest_alternatives(TENANT, SERVICE, SATURDAY, n=1)
    assert len(result) == 1
    assert result[0].start_at.date() == datetime(2024, 1, 7).date()


def test_suggest_alternatives_empty_when_none_available() -> None:
    # 容量 0 → 无任何可用时段。
    engine = _make_engine(capacity=0, open_time=time(9, 0), close_time=time(18, 0))
    assert engine.suggest_alternatives(TENANT, SERVICE, SATURDAY, n=3) == []


def test_suggest_alternatives_empty_when_no_business_hours_in_horizon() -> None:
    engine = _make_engine(capacity=1, weekdays=())  # 全周不营业
    assert engine.suggest_alternatives(TENANT, SERVICE, SATURDAY, n=3) == []


def test_suggest_alternatives_rejects_invalid_params() -> None:
    engine = _make_engine()
    with pytest.raises(InvalidParameterError):
        engine.suggest_alternatives(TENANT, SERVICE, SATURDAY, n=0)
    with pytest.raises(InvalidParameterError):
        engine.suggest_alternatives(TENANT, SERVICE, SATURDAY, n=3, search_horizon_days=0)
    with pytest.raises(InvalidParameterError):
        engine.suggest_alternatives("  ", SERVICE, SATURDAY, n=3)


def test_engine_rejects_bad_slot_minutes() -> None:
    hours = InMemoryBusinessHoursProvider()
    resources = InMemoryResourceProvider()
    appts = InMemoryAppointmentProvider()
    with pytest.raises(InvalidParameterError):
        SchedulingEngine(hours, resources, appts, slot_minutes=0)
