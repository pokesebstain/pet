"""接待预约 Agent 的客户 / 宠物消解接线测试（任务 26.2 / 27.3）。

验证注入 ``pet_resolver`` 后的行为（无需数据库，消解器用内存伪实现）：

- 恰好一只宠物：即使 LLM 未消解出宠物标识，也回填该宠物并回填客户标识后自动预约；
- 多只宠物且无法唯一确定：请客户指明（不预约）；
- 零只宠物 / 找不到客户：相应澄清（不预约）；
- 多只宠物但 LLM 已消解到名下某只：采用之并自动预约。

另覆盖 Requirement 25（找不到会员时自动建档，见文末 ``_FakeOnboardingWriter`` 相关测试）：
- 未注入 ``onboarding_writer``：保持既有行为（:data:`NO_CUSTOMER_REPLY`，不建档）；
- 注入后且能从对话抽取姓名 + 宠物名：自动建档并在同一轮直接完成预约；
- 仅提供其一：请客户补充缺失的那一项（不重复问已提供的部分）。
"""

from __future__ import annotations

import json
from datetime import datetime, time

from app.agents.reception import (
    MULTIPLE_PETS_REPLY,
    NO_CUSTOMER_REPLY,
    ONBOARDING_MISSING_CUSTOMER_NAME_REPLY,
    ONBOARDING_MISSING_PET_NAME_REPLY,
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


class _RoutingTransport:
    """按 prompt 是否含建档系统提示关键词路由到不同预设返回值的伪传输层。

    ``parse_booking_intent`` 与 ``extract_onboarding_info`` 共用同一个 LLM 客户端 /
    传输层，但两者的系统提示与期望 JSON 结构不同；用固定文本的传输层无法同时满足
    两者，需按 prompt 内容路由。
    """

    def __init__(self, booking_text: str, onboarding_text: str) -> None:
        self._booking_text = booking_text
        self._onboarding_text = onboarding_text

    def generate(self, prompt: str, *, timeout: float) -> str:
        if "建档" in prompt or "customer_name" in prompt:
            return self._onboarding_text
        return self._booking_text


class _FakeOnboardingWriter:
    """内存伪建档 writer：记录调用参数，返回固定的新建客户 / 宠物标识。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, str]] = []

    def create(self, tenant_id, external_user_id, customer_name, pet_name):  # noqa: ANN001
        self.calls.append((tenant_id, external_user_id, customer_name, pet_name))
        return PetResolution(customer_id="new-cust-1", pet_ids=["new-pet-1"])


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


def _make_agent(
    canned: str,
    resolver: _FakeResolver,
    bus: _RecordingBus,
    *,
    onboarding_writer: _FakeOnboardingWriter | None = None,
    transport: object | None = None,
) -> ReceptionAgent:
    llm = CloudLLMClient(
        transport=transport or _CannedTransport(canned),
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
        onboarding_writer=onboarding_writer,
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
    """未注入 onboarding_writer 时保持既有行为：直接拒绝，不建档。"""
    resolver = _FakeResolver(PetResolution(customer_id=None, pet_ids=[]))
    bus = _RecordingBus()
    agent = _make_agent(_slots_json(), resolver, bus)

    delta = agent.run(_state())

    output = delta["agent_outputs"]["reception"]
    assert output["status"] == "needs_clarification"
    assert output["reply_text"] == NO_CUSTOMER_REPLY
    assert bus.events == []


# --------------------------------------------------------------------------- #
# 自动建档（Requirement 25：找不到会员时仅采集姓名 + 宠物名即建档）
# --------------------------------------------------------------------------- #
def test_unknown_customer_onboards_and_books_when_names_provided() -> None:
    """注入 onboarding_writer 且能抽取姓名 + 宠物名时：自动建档并在同一轮完成预约。"""
    resolver = _FakeResolver(PetResolution(customer_id=None, pet_ids=[]))
    bus = _RecordingBus()
    writer = _FakeOnboardingWriter()
    transport = _RoutingTransport(
        booking_text=_slots_json(pet_id=None, ambiguous=True),
        onboarding_text=json.dumps(
            {"customer_name": "王炳杰", "pet_name": "绒绒"}
        ),
    )
    agent = _make_agent(
        "", resolver, bus, onboarding_writer=writer, transport=transport
    )

    delta = agent.run(_state("想约周六下午两点给绒绒洗澡，我叫王炳杰"))

    assert writer.calls == [(TENANT, EXT, "王炳杰", "绒绒")]
    output = delta["agent_outputs"]["reception"]
    assert output["status"] == "booked"
    assert output["appointment"]["customer_id"] == "new-cust-1"
    assert output["appointment"]["pet_id"] == "new-pet-1"
    assert "已为您建立会员档案（王炳杰 / 绒绒）" in output["reply_text"]


def test_unknown_customer_missing_pet_name_asks_for_it_only() -> None:
    """已提供姓名但未提供宠物名时：仅追问宠物名（不重复问姓名）。"""
    resolver = _FakeResolver(PetResolution(customer_id=None, pet_ids=[]))
    bus = _RecordingBus()
    writer = _FakeOnboardingWriter()
    transport = _RoutingTransport(
        booking_text=_slots_json(pet_id=None, ambiguous=True),
        onboarding_text=json.dumps({"customer_name": "王炳杰", "pet_name": None}),
    )
    agent = _make_agent(
        "", resolver, bus, onboarding_writer=writer, transport=transport
    )

    delta = agent.run(_state("我叫王炳杰"))

    output = delta["agent_outputs"]["reception"]
    assert output["status"] == "needs_clarification"
    assert output["reply_text"] == ONBOARDING_MISSING_PET_NAME_REPLY
    assert writer.calls == []  # 未建档


def test_unknown_customer_missing_customer_name_asks_for_it_only() -> None:
    """已提供宠物名但未提供姓名时：仅追问姓名（不重复问宠物名）。"""
    resolver = _FakeResolver(PetResolution(customer_id=None, pet_ids=[]))
    bus = _RecordingBus()
    writer = _FakeOnboardingWriter()
    transport = _RoutingTransport(
        booking_text=_slots_json(pet_id=None, ambiguous=True),
        onboarding_text=json.dumps({"customer_name": None, "pet_name": "绒绒"}),
    )
    agent = _make_agent(
        "", resolver, bus, onboarding_writer=writer, transport=transport
    )

    delta = agent.run(_state("我家狗叫绒绒"))

    output = delta["agent_outputs"]["reception"]
    assert output["status"] == "needs_clarification"
    assert output["reply_text"] == ONBOARDING_MISSING_CUSTOMER_NAME_REPLY
    assert writer.calls == []


def test_external_user_id_survives_full_supervisor_graph_invoke() -> None:
    """回归测试：``external_user_id`` / ``customer_id`` 必须在 ``AgentState`` TypedDict
    中显式声明，否则 LangGraph 按 schema 驱动状态通道，会在 ``graph.invoke()`` 时静默
    丢弃未声明的键——导致接待预约 Agent 的 ``pet_resolver`` 永远收不到企业微信外部联系人
    标识，宠物消解完全不生效（表现为无论客户是谁都反复追问"具体是哪只宠物"）。

    经**完整编译后的 Supervisor 图**（而非直接调用 ``agent.run``）验证，因为该 bug只有
    在状态经 LangGraph 的 channel 机制传递时才会触发，直接函数调用不会暴露此问题。
    """
    from app.agents.intent import IntentResult
    from app.agents.supervisor import build_supervisor_graph

    resolver = _FakeResolver(PetResolution(customer_id="cust-1", pet_ids=["pet-1"]))
    bus = _RecordingBus()
    agent = _make_agent(_slots_json(pet_id=None, ambiguous=True), resolver, bus)

    class _FixedReceptionIntent:
        def classify(self, messages, *, timeout=None):  # noqa: ANN001
            return IntentResult(intent="reception", confidence=0.95)

    graph = build_supervisor_graph(
        classifier=_FixedReceptionIntent(), experts={"reception": agent}
    ).compile()

    state = new_state(TENANT, messages=[("user", "周六下午两点给狗洗澡")])
    state["external_user_id"] = EXT  # type: ignore[typeddict-unknown-key]

    result = graph.invoke(state)

    assert resolver.calls == [(TENANT, EXT)]
    output = result["agent_outputs"]["reception"]
    assert output["status"] == "booked"
    assert output["appointment"]["customer_id"] == "cust-1"
