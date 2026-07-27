"""预约模块数据模型字段校验单元测试（对应任务 26.1 / 设计 14.4）。"""

from __future__ import annotations

from datetime import datetime, time, timezone

import pytest
from pydantic import ValidationError

from app.models import (
    Appointment,
    AppointmentStatus,
    BookingIntent,
    BookingOutcome,
    BookingRequest,
    BusinessHours,
    GroomingResource,
    ServiceType,
    TimeSlot,
)

TENANT = "tenant-1"
T0 = datetime(2025, 1, 4, 14, 0, tzinfo=timezone.utc)
T1 = datetime(2025, 1, 4, 15, 0, tzinfo=timezone.utc)


# --- TimeSlot ---------------------------------------------------------------


def test_timeslot_valid_and_available() -> None:
    slot = TimeSlot(
        tenant_id=TENANT,
        service_type=ServiceType.GROOMING,
        start_at=T0,
        end_at=T1,
        capacity=3,
        booked_count=1,
    )
    assert slot.available == 2


def test_timeslot_available_never_negative_when_full() -> None:
    slot = TimeSlot(
        tenant_id=TENANT,
        service_type=ServiceType.GROOMING,
        start_at=T0,
        end_at=T1,
        capacity=2,
        booked_count=2,
    )
    assert slot.available == 0


def test_timeslot_rejects_negative_capacity() -> None:
    with pytest.raises(ValidationError):
        TimeSlot(
            tenant_id=TENANT,
            service_type=ServiceType.GROOMING,
            start_at=T0,
            end_at=T1,
            capacity=-1,
            booked_count=0,
        )


def test_timeslot_rejects_booked_exceeding_capacity() -> None:
    with pytest.raises(ValidationError):
        TimeSlot(
            tenant_id=TENANT,
            service_type=ServiceType.GROOMING,
            start_at=T0,
            end_at=T1,
            capacity=2,
            booked_count=3,
        )


def test_timeslot_rejects_negative_booked_count() -> None:
    with pytest.raises(ValidationError):
        TimeSlot(
            tenant_id=TENANT,
            service_type=ServiceType.GROOMING,
            start_at=T0,
            end_at=T1,
            capacity=2,
            booked_count=-1,
        )


def test_timeslot_rejects_start_not_before_end() -> None:
    with pytest.raises(ValidationError):
        TimeSlot(
            tenant_id=TENANT,
            service_type=ServiceType.GROOMING,
            start_at=T1,
            end_at=T0,
            capacity=1,
            booked_count=0,
        )


def test_timeslot_rejects_blank_tenant() -> None:
    with pytest.raises(ValidationError):
        TimeSlot(
            tenant_id="   ",
            service_type=ServiceType.GROOMING,
            start_at=T0,
            end_at=T1,
            capacity=1,
            booked_count=0,
        )


# --- Appointment ------------------------------------------------------------


def test_appointment_valid() -> None:
    appt = Appointment(
        appointment_id="a-1",
        tenant_id=TENANT,
        customer_id="c-1",
        pet_id="p-1",
        service_type=ServiceType.GROOMING,
        start_at=T0,
        end_at=T1,
        resource_id=None,
        status=AppointmentStatus.CONFIRMED,
        created_at=T0,
    )
    assert appt.source == "wecom"
    assert appt.status is AppointmentStatus.CONFIRMED


def test_appointment_rejects_start_not_before_end() -> None:
    with pytest.raises(ValidationError):
        Appointment(
            appointment_id="a-1",
            tenant_id=TENANT,
            customer_id="c-1",
            pet_id="p-1",
            service_type=ServiceType.GROOMING,
            start_at=T1,
            end_at=T0,
            status=AppointmentStatus.PENDING,
            created_at=T0,
        )


def test_appointment_rejects_blank_tenant() -> None:
    with pytest.raises(ValidationError):
        Appointment(
            appointment_id="a-1",
            tenant_id="",
            customer_id="c-1",
            pet_id="p-1",
            service_type=ServiceType.GROOMING,
            start_at=T0,
            end_at=T1,
            status=AppointmentStatus.PENDING,
            created_at=T0,
        )


# --- BusinessHours ----------------------------------------------------------


def test_business_hours_valid() -> None:
    bh = BusinessHours(
        tenant_id=TENANT,
        weekday=5,
        open_time=time(9, 0),
        close_time=time(18, 0),
    )
    assert bh.weekday == 5


def test_business_hours_rejects_open_not_before_close() -> None:
    with pytest.raises(ValidationError):
        BusinessHours(
            tenant_id=TENANT,
            weekday=5,
            open_time=time(18, 0),
            close_time=time(9, 0),
        )


def test_business_hours_rejects_out_of_range_weekday() -> None:
    with pytest.raises(ValidationError):
        BusinessHours(
            tenant_id=TENANT,
            weekday=7,
            open_time=time(9, 0),
            close_time=time(18, 0),
        )


# --- BookingIntent ----------------------------------------------------------


def test_booking_intent_confidence_bounds() -> None:
    intent = BookingIntent(confidence=0.5, ambiguous=False)
    assert intent.confidence == 0.5
    assert intent.service_type is None


@pytest.mark.parametrize("bad", [-0.01, 1.01])
def test_booking_intent_rejects_confidence_out_of_range(bad: float) -> None:
    with pytest.raises(ValidationError):
        BookingIntent(confidence=bad, ambiguous=True)


# --- GroomingResource / BookingRequest / BookingOutcome ---------------------


def test_grooming_resource_defaults_active() -> None:
    res = GroomingResource(
        resource_id="r-1",
        tenant_id=TENANT,
        name="工位A",
        service_type=ServiceType.GROOMING,
    )
    assert res.active is True


def test_booking_request_rejects_blank_tenant() -> None:
    with pytest.raises(ValidationError):
        BookingRequest(
            tenant_id="",
            customer_id="c-1",
            pet_id="p-1",
            service_type=ServiceType.GROOMING,
            start_at=T0,
            end_at=T1,
        )


def test_booking_outcome_defaults() -> None:
    outcome = BookingOutcome(status="needs_clarification", reply_text="请问是哪只宠物?")
    assert outcome.alternatives == []
    assert outcome.current_schedule == []
    assert outcome.appointment is None
