"""任务 27.3 预约相关工具与 reception 意图路由的单元测试。

覆盖 Requirements 21.1 / 22.1 / 22.5 / 24.2：

- ``schedule_query_tool``（只读）：经 RLS 强制注入 ``tenant_id``、逐条校验时段租户归属、
  缺租户拒绝（Requirement 23.1 / 24.2）。
- ``appointment_book_tool``（副作用）：自动执行原子写入（Requirement 22.1）、``tenant_id``
  强制归一（RLS 注入，Requirement 24.2）、满档返回 ``full``、``auto_execute=False`` 转 HITL
  不写入（Requirement 22.5）、缺租户拒绝。
- ``wecom_reply_tool``（副作用）：经企业微信通道回复、缺租户拒绝（Requirement 21.1 / 24.2）。
- Supervisor 意图分类新增 ``reception`` 路由到 Reception_Agent（复用既有 Cloud_LLM 分类器）。

依赖经内存假实现注入（内存排期存储 + 伪出站通道 + 伪意图分类器），无需网络 / 数据库。
"""

from __future__ import annotations

from datetime import datetime, time

import pytest

from app.agents.intent import EXPERT_INTENTS
from app.agents.state import new_state
from app.agents.supervisor import SupervisorAgent, build_supervisor_graph
from app.core.errors import TenantContextMissingError, TenantIsolationError
from app.engines.scheduling import (
    APPOINTMENT_BOOKED_EVENT,
    InMemoryBusinessHoursProvider,
    InMemoryResourceProvider,
    InMemoryTransactionalSlotStore,
    SchedulingEngine,
)
from app.models.scheduling import AppointmentStatus, ServiceType
from app.tools import (
    build_appointment_book_tool,
    build_schedule_query_tool,
    build_wecom_reply_tool,
)

TENANT = "tenant-a"
OTHER = "tenant-b"
CUSTOMER = "cust-1"
PET = "pet-1"
SERVICE = ServiceType.GROOMING

# 2024-01-06 是周六（weekday=5）。
DAY = "2024-01-06"
SLOT_START = datetime(2024, 1, 6, 14, 0)
SLOT_END = datetime(2024, 1, 6, 15, 0)


# --------------------------------------------------------------------------- #
# 伪造依赖
# --------------------------------------------------------------------------- #
class _RecordingBus:
    """记录已发布领域事件的最小事件发布器。"""

    def __init__(self) -> None:
        self.events: list = []

    def publish(self, event) -> str:
        self.events.append(event)
        return event.event_id

    def types(self) -> list[str]:
        return [e.event_type for e in self.events]


class _RecordingReplyChannel:
    """记录出站企业微信回复的伪通道（无网络）。"""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    def send(self, tenant_id: str, external_user_id: str, text: str) -> None:
        self.sent.append((tenant_id, external_user_id, text))


class _FixedIntentClassifier:
    """伪意图分类器：恒返回指定意图与高置信度。"""

    def __init__(self, intent: str) -> None:
        self._intent = intent

    def classify(self, messages, *, timeout=None):
        from app.agents.intent import IntentResult

        return IntentResult(intent=self._intent, confidence=0.95)


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


def _req() -> dict:
    return {
        "customer_id": CUSTOMER,
        "pet_id": PET,
        "service_type": SERVICE.value,
        "start_at": SLOT_START.isoformat(),
        "end_at": SLOT_END.isoformat(),
    }


# --------------------------------------------------------------------------- #
# schedule_query_tool（只读，Requirement 23.1 / 24.2）
# --------------------------------------------------------------------------- #
def test_schedule_query_tool_returns_day_schedule() -> None:
    engine, _ = _make_engine(capacity=2)
    tool = build_schedule_query_tool(engine)

    out = tool.invoke({"tenant_id": TENANT, "service_type": SERVICE.value, "day": DAY})

    assert out["tenant_id"] == TENANT
    assert out["service_type"] == SERVICE.value
    assert out["row_count"] == len(out["rows"]) > 0
    # 每条时段记录租户归属正确（Requirement 24.2）。
    assert all(row["tenant_id"] == TENANT for row in out["rows"])


def test_schedule_query_tool_rejects_missing_tenant() -> None:
    engine, _ = _make_engine()
    tool = build_schedule_query_tool(engine)

    with pytest.raises(TenantContextMissingError):
        tool.invoke({"tenant_id": "", "service_type": SERVICE.value, "day": DAY})


def test_schedule_query_tool_blocks_foreign_rows() -> None:
    """引擎返回越界记录时，工具应逐条校验并阻断整个结果集（Property 17）。"""
    engine, _ = _make_engine()

    class _LeakyEngine:
        def get_day_schedule(self, tenant_id, service_type, day):
            from app.models.scheduling import TimeSlot

            return [
                TimeSlot(
                    tenant_id=OTHER,  # 越界记录
                    service_type=service_type,
                    start_at=SLOT_START,
                    end_at=SLOT_END,
                    capacity=1,
                    booked_count=0,
                )
            ]

    tool = build_schedule_query_tool(_LeakyEngine())
    with pytest.raises(TenantIsolationError):
        tool.invoke({"tenant_id": TENANT, "service_type": SERVICE.value, "day": DAY})


# --------------------------------------------------------------------------- #
# appointment_book_tool（副作用，Requirement 22.1 / 22.5 / 24.2）
# --------------------------------------------------------------------------- #
def test_appointment_book_tool_auto_executes_and_emits_event() -> None:
    engine, store = _make_engine(capacity=1)
    bus = _RecordingBus()
    tool = build_appointment_book_tool(
        engine, slot_locks=store, appointment_writer=store, event_bus=bus
    )

    out = tool.invoke({"tenant_id": TENANT, "req": _req(), "auto_execute": True})

    assert out["executed"] is True
    assert out["status"] == "booked"
    assert out["appointment"]["tenant_id"] == TENANT
    booked = store.count_overlapping_appointments(
        TENANT, SERVICE, SLOT_START, SLOT_END, {AppointmentStatus.CONFIRMED}
    )
    assert booked == 1
    assert APPOINTMENT_BOOKED_EVENT in bus.types()


def test_appointment_book_tool_injects_context_tenant() -> None:
    """请求体携带其他租户时，工具强制归一为上下文租户后写入（RLS 注入，Req 24.2）。"""
    engine, store = _make_engine(capacity=1)
    bus = _RecordingBus()
    tool = build_appointment_book_tool(
        engine, slot_locks=store, appointment_writer=store, event_bus=bus
    )
    req = _req()
    req["tenant_id"] = OTHER  # 试图越权写入其他租户

    out = tool.invoke({"tenant_id": TENANT, "req": req, "auto_execute": True})

    assert out["executed"] is True
    assert out["appointment"]["tenant_id"] == TENANT  # 已归一到上下文租户


def test_appointment_book_tool_full_when_no_capacity() -> None:
    store = InMemoryTransactionalSlotStore()
    store.add_booking(TENANT, SERVICE, SLOT_START, SLOT_END, AppointmentStatus.CONFIRMED)
    engine, store = _make_engine(capacity=1, store=store)
    bus = _RecordingBus()
    tool = build_appointment_book_tool(
        engine, slot_locks=store, appointment_writer=store, event_bus=bus
    )

    out = tool.invoke({"tenant_id": TENANT, "req": _req(), "auto_execute": True})

    assert out["executed"] is False
    assert out["status"] == "full"
    # 未新增写入（仍为预置的 1 条）。
    booked = store.count_overlapping_appointments(
        TENANT, SERVICE, SLOT_START, SLOT_END, {AppointmentStatus.CONFIRMED}
    )
    assert booked == 1


def test_appointment_book_tool_hitl_does_not_write() -> None:
    engine, store = _make_engine(capacity=1)
    bus = _RecordingBus()
    tool = build_appointment_book_tool(
        engine, slot_locks=store, appointment_writer=store, event_bus=bus
    )

    out = tool.invoke({"tenant_id": TENANT, "req": _req(), "auto_execute": False})

    assert out["executed"] is False
    assert out["status"] == "pending_hitl"
    assert out["pending_action"]["action_type"] == "appointment_book"
    assert out["pending_action"]["executed"] is False
    # 转 HITL 时不写入、不发事件（Requirement 22.5）。
    booked = store.count_overlapping_appointments(
        TENANT, SERVICE, SLOT_START, SLOT_END, {AppointmentStatus.CONFIRMED}
    )
    assert booked == 0
    assert bus.events == []


def test_appointment_book_tool_rejects_missing_tenant() -> None:
    engine, store = _make_engine()
    bus = _RecordingBus()
    tool = build_appointment_book_tool(
        engine, slot_locks=store, appointment_writer=store, event_bus=bus
    )

    with pytest.raises(TenantContextMissingError):
        tool.invoke({"tenant_id": "", "req": _req(), "auto_execute": True})


# --------------------------------------------------------------------------- #
# wecom_reply_tool（副作用，Requirement 21.1 / 24.2）
# --------------------------------------------------------------------------- #
def test_wecom_reply_tool_sends_via_channel() -> None:
    channel = _RecordingReplyChannel()
    tool = build_wecom_reply_tool(channel)

    out = tool.invoke(
        {"tenant_id": TENANT, "external_user_id": "wx-user-1", "text": "已为您预约成功"}
    )

    assert out["sent"] is True
    assert out["tenant_id"] == TENANT
    assert channel.sent == [(TENANT, "wx-user-1", "已为您预约成功")]


def test_wecom_reply_tool_rejects_missing_tenant() -> None:
    channel = _RecordingReplyChannel()
    tool = build_wecom_reply_tool(channel)

    with pytest.raises(TenantContextMissingError):
        tool.invoke({"tenant_id": "  ", "external_user_id": "wx-user-1", "text": "hi"})
    assert channel.sent == []  # 缺租户时未触碰发送通道


# --------------------------------------------------------------------------- #
# Supervisor reception 意图路由（Requirement 21.1）
# --------------------------------------------------------------------------- #
def test_reception_is_registered_intent() -> None:
    assert "reception" in EXPERT_INTENTS


def test_supervisor_routes_reception_intent() -> None:
    """预约类消息经 Cloud_LLM 分类器归为 reception 时，Supervisor 路由到 reception。"""
    sup = SupervisorAgent(_FixedIntentClassifier("reception"))
    state = new_state(TENANT, messages=[("user", "想约周六下午给狗狗洗澡")])
    delta = sup.recognize_intent(state)
    working = {**state, **delta}

    assert delta["intent"] == "reception"
    assert sup.route(working) == "reception"


def test_reception_agent_runs_via_supervisor_graph() -> None:
    """编排图注入 reception 专家后，reception 意图消息应被路由并执行该专家。"""

    class _FakeReception:
        name = "reception"

        def run(self, state):
            from app.agents.experts import record_expert_output

            return record_expert_output(
                self.name, state, {"status": "booked", "summary": "已为您预约成功"}
            )

    graph = build_supervisor_graph(
        classifier=_FixedIntentClassifier("reception"),
        experts={"reception": _FakeReception()},
    ).compile()

    result = graph.invoke(new_state(TENANT, messages=[("user", "约洗澡")]))

    assert result["agent_outputs"]["reception"]["status"] == "booked"
    assert "已为您预约成功" in result["final_answer"]
    # 单一专家参与本轮时，回复不应携带内部 Agent 标识（如 "[reception]"）。
    assert "[reception]" not in result["final_answer"]
    assert result["final_answer"] == "已为您预约成功"
