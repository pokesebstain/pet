"""接待预约 Agent 的客户 / 宠物消解接线测试（任务 26.2 / 27.3）。

验证注入 ``pet_resolver`` 后的行为（无需数据库，消解器用内存伪实现）：

- 恰好一只宠物：即使 LLM 未消解出宠物标识，也回填该宠物并回填客户标识后自动预约；
- 多只宠物且无法唯一确定：请客户指明（不预约）；
- 零只宠物 / 找不到客户：相应澄清（不预约）；
- 多只宠物但 LLM 已消解到名下某只：采用之并自动预约。
"""

from __future__ import annotations

import json
from datetime import datetime, time

from app.agents.reception import (
    MULTIPLE_PETS_REPLY,
    NO_CUSTOMER_REPLY,
    NO_PET_REPLY,
    ReceptionAgent,
)
from app.agents.state import new_state
from app.engines.scheduling import (
    InMemoryBusinessHoursProvider,
    InMemoryResourceProvider,
    InMemoryTransactionalSlotStore,
    SchedulingEngine,
)
from app.engines.scheduling_db import PetResolution
from app.llm.client import CloudLLMClient, RestrictedTemplateQuery
from app.models import DomainEvent
from app.models.scheduling import ServiceType

TENANT = "store-001"
EXT = "wm-tester"
SERVICE = ServiceType.GROOMING
SLOT_START = datetime(2024, 1, 6, 14, 0)  # 周六
SLOT_END = datetime(2024, 1, 6, 15, 0)


class _CannedTransport:
    def __init__(self, text: str) -> None:
        self._text = text

    def generate(self, prompt: str, *, timeout: float) -> str:
        return self._text


class _RecordingBus:
    def __init__(self) -> None:
        self.events: list[DomainEvent] = []

    def publish(self, event: DomainEvent) -> str:
        self.events.append(event)
        return event.event_id


class _FakeResolver:
    def __init__(self, resolution: PetResolution) -> None:
        self._resolution = resolution
        self.calls: list[tuple[str, str]] = []

    def resolve(self, tenant_id: str, external_user_id: str) -> PetResolution:
        self.calls.append((tenant_id, external_user_id))
        return self._resolution


def _slots_json(*, pet_id=None, ambiguous=True, confidence=0.95) -> str:
    return json.dumps(
        {
            "service_type": "grooming",
            "pet_id": pet_id,
            "pet_ref": "我家狗",
            "requested_start": "2024-01-06T14:00:00",
            "requested_end": "2024-01-06T15:00:00",
            "confidence": confidence,
            "ambiguous": ambiguous,
        }
    )


def _make_agent(canned: str, resolver: _FakeResolver, bus: _RecordingBus) -> ReceptionAgent:
    llm = CloudLLMClient(
        transport=_CannedTransport(canned),
        template_query=RestrictedTemplateQuery(),
        timeout_seconds=10.0,
        max_retries=0,
    )
    hours = InMemoryBusinessHoursProvider()
    for wd in range(7):
        hours.set_weekday(TENANT, wd, time(9, 0), time(19, 0))
    resources = InMemoryResourceProvider()
    resources.set_capacity(TENANT, SERVICE, 1)
    store = InMemoryTransactionalSlotStore()
    engine = SchedulingEngine(hours, resources, store, slot_minutes=60)
    return ReceptionAgent(
        llm,
        engine,
        slot_locks=store,
        appointment_writer=store,
        event_bus=bus,
        pet_resolver=resolver,
    )


def _state(text: str = "周六下午两点给狗洗澡") -> dict:
    st = new_state(TENANT, messages=[("user", text)])
    st["external_user_id"] = EXT  # type: ignore[typeddict-unknown-key]
    return st


def test_single_pet_auto_books_with_resolved_ids() -> None:
    resolver = _FakeResolver(PetResolution(customer_id="cust-1", pet_ids=["pet-1"]))
    bus = _RecordingBus()
    agent = _make_agent(_slots_json(pet_id=None, ambiguous=True), resolver, bus)

    delta = agent.run(_state())

    output = delta["agent_outputs"]["reception"]
    assert output["status"] == "booked"
    appt = output["appointment"]
    assert appt is not None
    assert appt["customer_id"] == "cust-1"
    assert appt["pet_id"] == "pet-1"
    assert resolver.calls == [(TENANT, EXT)]


def test_multiple_pets_requests_clarification() -> None:
    resolver = _FakeResolver(
        PetResolution(customer_id="cust-1", pet_ids=["pet-a", "pet-b"])
    )
    bus = _RecordingBus()
    agent = _make_agent(_slots_json(pet_id=None), resolver, bus)

    delta = agent.run(_state())

    output = delta["agent_outputs"]["reception"]
    assert output["status"] == "needs_clarification"
    assert output["reply_text"] == MULTIPLE_PETS_REPLY
    assert bus.events == []  # 未预约


def test_multiple_pets_uses_llm_resolved_pet_when_valid() -> None:
    resolver = _FakeResolver(
        PetResolution(customer_id="cust-1", pet_ids=["pet-a", "pet-b"])
    )
    bus = _RecordingBus()
    # LLM 消解到名下的 pet-b（属于该客户）→ 采用之并预约。
    agent = _make_agent(_slots_json(pet_id="pet-b", ambiguous=False), resolver, bus)

    delta = agent.run(_state())

    output = delta["agent_outputs"]["reception"]
    assert output["status"] == "booked"
    assert output["appointment"]["pet_id"] == "pet-b"


def test_zero_pets_requests_clarification() -> None:
    resolver = _FakeResolver(PetResolution(customer_id="cust-1", pet_ids=[]))
    bus = _RecordingBus()
    agent = _make_agent(_slots_json(), resolver, bus)

    delta = agent.run(_state())

    output = delta["agent_outputs"]["reception"]
    assert output["status"] == "needs_clarification"
    assert output["reply_text"] == NO_PET_REPLY
    assert bus.events == []


def test_unknown_customer_requests_clarification() -> None:
    resolver = _FakeResolver(PetResolution(customer_id=None, pet_ids=[]))
    bus = _RecordingBus()
    agent = _make_agent(_slots_json(), resolver, bus)

    delta = agent.run(_state())

    output = delta["agent_outputs"]["reception"]
    assert output["status"] == "needs_clarification"
    assert output["reply_text"] == NO_CUSTOMER_REPLY
    assert bus.events == []
