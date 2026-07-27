"""接待预约 Agent 单元测试（任务 27.2）。

覆盖 Requirements 21.4 / 21.5 / 21.6 / 22.1 / 22.5 / 24.3：
- ``parse_booking_intent`` 经 Cloud_LLM 少样本抽取，``confidence`` 夹取到 [0, 1]，
  服务类型 / 宠物 / 时间任一缺失或歧义时置 ``ambiguous = True``；
- ``should_auto_book`` 门控四类判定（自动 / 满档 / 澄清 / HITL）；
- ``handle_booking`` / ``run`` 编排：可用且明确→自动预约；满档→现状+备选；
  歧义→请澄清；低置信 / 关闭自动预约→转 HITL（写入 ``pending_action``）；
  缺 ``tenant_id``→拒绝。

依赖经内存假实现注入（伪 LLM 传输层 + 排期引擎内存提供者），无需网络 / 数据库。
"""

from __future__ import annotations

import json
from datetime import datetime, time

import pytest

from app.agents.reception import (
    BookingDecision,
    ReceptionAgent,
    ReceptionConfig,
    should_auto_book,
)
from app.agents.state import new_state
from app.core.errors import TenantContextMissingError
from app.engines.scheduling import (
    APPOINTMENT_BOOKED_EVENT,
    InMemoryBusinessHoursProvider,
    InMemoryResourceProvider,
    InMemoryTransactionalSlotStore,
    SchedulingEngine,
)
from app.llm.client import CloudLLMClient, RestrictedTemplateQuery
from app.llm.errors import LLMTimeoutError
from app.models import DomainEvent
from app.models.scheduling import AppointmentStatus, BookingIntent, ServiceType

TENANT = "tenant-a"
CUSTOMER = "cust-1"
PET = "pet-1"
SERVICE = ServiceType.GROOMING

# 2024-01-06 是周六（weekday=5）。
SLOT_START = datetime(2024, 1, 6, 14, 0)
SLOT_END = datetime(2024, 1, 6, 15, 0)


# --------------------------------------------------------------------------- #
# 伪造依赖
# --------------------------------------------------------------------------- #
class _CannedTransport:
    """始终返回预设文本的伪 LLM 传输层。"""

    def __init__(self, text: str) -> None:
        self._text = text

    def generate(self, prompt: str, *, timeout: float) -> str:
        return self._text


class _AlwaysFailTransport:
    """始终抛可重试错误的伪传输层（触发降级 → 非 LLM 来源）。"""

    def generate(self, prompt: str, *, timeout: float) -> str:
        raise LLMTimeoutError("boom")


class _RecordingBus:
    """记录已发布领域事件的最小事件发布器。"""

    def __init__(self) -> None:
        self.events: list[DomainEvent] = []

    def publish(self, event: DomainEvent) -> str:
        self.events.append(event)
        return event.event_id

    def types(self) -> list[str]:
        return [e.event_type for e in self.events]


def _slots_json(
    *,
    service_type: str | None = "grooming",
    pet_id: str | None = PET,
    pet_ref: str | None = "我家狗",
    start: str | None = "2024-01-06T14:00:00",
    end: str | None = "2024-01-06T15:00:00",
    confidence: float = 0.95,
    ambiguous: bool = False,
) -> str:
    return json.dumps(
        {
            "service_type": service_type,
            "pet_id": pet_id,
            "pet_ref": pet_ref,
            "requested_start": start,
            "requested_end": end,
            "confidence": confidence,
            "ambiguous": ambiguous,
        }
    )


def _make_llm(text: str) -> CloudLLMClient:
    return CloudLLMClient(
        transport=_CannedTransport(text),
        template_query=RestrictedTemplateQuery(),
        timeout_seconds=10.0,
        max_retries=0,
    )


def _make_degraded_llm() -> CloudLLMClient:
    return CloudLLMClient(
        transport=_AlwaysFailTransport(),
        template_query=RestrictedTemplateQuery(),
        timeout_seconds=10.0,
        max_retries=0,
    )


def _make_engine(
    *,
    capacity: int = 1,
    store: InMemoryTransactionalSlotStore | None = None,
) -> tuple[SchedulingEngine, InMemoryTransactionalSlotStore]:
    hours = InMemoryBusinessHoursProvider()
    for wd in range(7):
        hours.set_weekday(TENANT, wd, time(9, 0), time(18, 0))
    resources = InMemoryResourceProvider()
    resources.set_capacity(TENANT, SERVICE, capacity)
    store = store or InMemoryTransactionalSlotStore()
    engine = SchedulingEngine(hours, resources, store, slot_minutes=60)
    return engine, store


def _make_agent(
    llm: CloudLLMClient,
    engine: SchedulingEngine,
    store: InMemoryTransactionalSlotStore,
    bus: _RecordingBus,
    *,
    config: ReceptionConfig | None = None,
) -> ReceptionAgent:
    return ReceptionAgent(
        llm,
        engine,
        config=config,
        slot_locks=store,
        appointment_writer=store,
        event_bus=bus,
    )


def _state(text: str, *, tenant_id: str = TENANT) -> dict:
    st = new_state(tenant_id, messages=[("user", text)])
    st["customer_id"] = CUSTOMER  # type: ignore[typeddict-unknown-key]
    return st


# --------------------------------------------------------------------------- #
# parse_booking_intent（Requirement 21.4 / 21.5）
# --------------------------------------------------------------------------- #
def test_parse_booking_intent_extracts_slots() -> None:
    engine, store = _make_engine()
    agent = _make_agent(_make_llm(_slots_json()), engine, store, _RecordingBus())

    intent = agent.parse_booking_intent("周六下午两点带狗洗澡", TENANT)

    assert intent.service_type is ServiceType.GROOMING
    assert intent.pet_id == PET
    assert intent.requested_start == SLOT_START
    assert intent.requested_end == SLOT_END
    assert 0.0 <= intent.confidence <= 1.0
    assert intent.ambiguous is False


def test_parse_booking_intent_clamps_confidence_into_unit_interval() -> None:
    engine, store = _make_engine()
    # LLM 返回越界置信度 1.7 → 应夹取到 1.0。
    agent = _make_agent(
        _make_llm(_slots_json(confidence=1.7)), engine, store, _RecordingBus()
    )

    intent = agent.parse_booking_intent("周六下午两点带狗洗澡", TENANT)

    assert intent.confidence == 1.0


def test_parse_booking_intent_marks_ambiguous_when_slots_missing() -> None:
    engine, store = _make_engine()
    # 缺失时间与宠物消解 → ambiguous。
    agent = _make_agent(
        _make_llm(
            _slots_json(pet_id=None, start=None, end=None, confidence=0.6, ambiguous=True)
        ),
        engine,
        store,
        _RecordingBus(),
    )

    intent = agent.parse_booking_intent("帮我家狗约个洗护", TENANT)

    assert intent.ambiguous is True
    assert intent.requested_start is None


def test_parse_booking_intent_degraded_llm_is_ambiguous() -> None:
    engine, store = _make_engine()
    agent = _make_agent(_make_degraded_llm(), engine, store, _RecordingBus())

    intent = agent.parse_booking_intent("周六下午两点带狗洗澡", TENANT)

    assert intent.ambiguous is True
    assert intent.confidence == 0.0


def test_parse_booking_intent_rejects_missing_tenant() -> None:
    engine, store = _make_engine()
    agent = _make_agent(_make_llm(_slots_json()), engine, store, _RecordingBus())

    with pytest.raises(TenantContextMissingError):
        agent.parse_booking_intent("周六下午两点带狗洗澡", "")


# --------------------------------------------------------------------------- #
# should_auto_book 门控（Requirement 22.5）
# --------------------------------------------------------------------------- #
def _intent(**overrides) -> BookingIntent:
    base = dict(
        service_type=ServiceType.GROOMING,
        pet_id=PET,
        pet_ref="狗",
        requested_start=SLOT_START,
        requested_end=SLOT_END,
        confidence=0.95,
        ambiguous=False,
    )
    base.update(overrides)
    return BookingIntent(**base)


class _Avail:
    def __init__(self, available: int, in_business_hours: bool = True) -> None:
        self.available = available
        self.in_business_hours = in_business_hours
        self.capacity = 1
        self.booked = 1 - available


def test_should_auto_book_auto_when_available_and_clear() -> None:
    decision = should_auto_book(_intent(), _Avail(1), ReceptionConfig())
    assert decision is BookingDecision.AUTO_BOOK


def test_should_auto_book_full_when_no_capacity() -> None:
    decision = should_auto_book(_intent(), _Avail(0), ReceptionConfig())
    assert decision is BookingDecision.FULL_SUGGEST


def test_should_auto_book_clarify_when_ambiguous() -> None:
    decision = should_auto_book(_intent(ambiguous=True), _Avail(1), ReceptionConfig())
    assert decision is BookingDecision.NEEDS_CLARIFICATION


def test_should_auto_book_hitl_when_low_confidence() -> None:
    decision = should_auto_book(_intent(confidence=0.4), _Avail(1), ReceptionConfig())
    assert decision is BookingDecision.NEEDS_HITL


def test_should_auto_book_hitl_when_auto_book_disabled() -> None:
    decision = should_auto_book(
        _intent(), _Avail(1), ReceptionConfig(auto_book_enabled=False)
    )
    assert decision is BookingDecision.NEEDS_HITL


def test_should_auto_book_clarify_when_slot_missing() -> None:
    decision = should_auto_book(
        _intent(requested_start=None, requested_end=None, ambiguous=False),
        None,
        ReceptionConfig(),
    )
    assert decision is BookingDecision.NEEDS_CLARIFICATION


# --------------------------------------------------------------------------- #
# handle_booking / run 编排
# --------------------------------------------------------------------------- #
def test_run_available_auto_books_and_emits_event() -> None:
    engine, store = _make_engine(capacity=1)
    bus = _RecordingBus()
    agent = _make_agent(_make_llm(_slots_json()), engine, store, bus)

    delta = agent.run(_state("周六下午两点带狗洗澡"))

    output = delta["agent_outputs"]["reception"]
    assert output["status"] == "booked"
    assert output["appointment"] is not None
    # 落库一条 CONFIRMED 预约。
    booked = store.count_overlapping_appointments(
        TENANT, SERVICE, SLOT_START, SLOT_END, {AppointmentStatus.CONFIRMED}
    )
    assert booked == 1
    assert APPOINTMENT_BOOKED_EVENT in bus.types()


def test_run_full_slot_replies_with_alternatives() -> None:
    # 预置一条预约占满 14:00-15:00（capacity=1）。
    store = InMemoryTransactionalSlotStore()
    store.add_booking(TENANT, SERVICE, SLOT_START, SLOT_END, AppointmentStatus.CONFIRMED)
    engine, store = _make_engine(capacity=1, store=store)
    bus = _RecordingBus()
    agent = _make_agent(_make_llm(_slots_json()), engine, store, bus)

    delta = agent.run(_state("周六下午两点带狗洗澡"))

    output = delta["agent_outputs"]["reception"]
    assert output["status"] == "full"
    assert len(output["alternatives"]) > 0  # 有就近可约备选
    # 未新增写入（仍为预置的 1 条）。
    booked = store.count_overlapping_appointments(
        TENANT, SERVICE, SLOT_START, SLOT_END, {AppointmentStatus.CONFIRMED}
    )
    assert booked == 1


def test_run_ambiguous_requests_clarification() -> None:
    engine, store = _make_engine()
    bus = _RecordingBus()
    agent = _make_agent(
        _make_llm(
            _slots_json(pet_id=None, start=None, end=None, confidence=0.6, ambiguous=True)
        ),
        engine,
        store,
        bus,
    )

    delta = agent.run(_state("帮我家狗约个洗护"))

    output = delta["agent_outputs"]["reception"]
    assert output["status"] == "needs_clarification"
    assert output["reply_text"]
    assert bus.events == []  # 未写入、未发事件


def test_run_low_confidence_routes_to_hitl_with_pending_action() -> None:
    engine, store = _make_engine()
    bus = _RecordingBus()
    agent = _make_agent(
        _make_llm(_slots_json(confidence=0.4)), engine, store, bus
    )

    delta = agent.run(_state("周六下午两点带狗洗澡"))

    output = delta["agent_outputs"]["reception"]
    assert output["status"] == "needs_hitl"
    # 复用既有 HITL 机制：写入待确认动作，批准前不执行。
    assert delta["pending_action"]["action_type"] == "appointment_book"
    assert delta["pending_action"]["executed"] is False
    booked = store.count_overlapping_appointments(
        TENANT, SERVICE, SLOT_START, SLOT_END, {AppointmentStatus.CONFIRMED}
    )
    assert booked == 0  # 未写入


def test_run_auto_book_disabled_routes_to_hitl() -> None:
    engine, store = _make_engine()
    bus = _RecordingBus()
    agent = _make_agent(
        _make_llm(_slots_json()),
        engine,
        store,
        bus,
        config=ReceptionConfig(auto_book_enabled=False),
    )

    delta = agent.run(_state("周六下午两点带狗洗澡"))

    assert delta["agent_outputs"]["reception"]["status"] == "needs_hitl"
    assert "pending_action" in delta


def test_run_missing_tenant_rejects() -> None:
    engine, store = _make_engine()
    bus = _RecordingBus()
    agent = _make_agent(_make_llm(_slots_json()), engine, store, bus)

    delta = agent.run(_state("周六下午两点带狗洗澡", tenant_id=""))

    output = delta["agent_outputs"]["reception"]
    assert output["status"] == "rejected"
    assert output["appointment"] is None
    assert bus.events == []


def test_handle_booking_raises_on_missing_tenant() -> None:
    engine, store = _make_engine()
    agent = _make_agent(_make_llm(_slots_json()), engine, store, _RecordingBus())
    intent = _intent()
    state = new_state("", messages=[("user", "x")])

    with pytest.raises(TenantContextMissingError):
        agent.handle_booking(intent, state)
