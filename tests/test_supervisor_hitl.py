"""HITL 检查点中断 / 恢复测试（任务 22.3）。

覆盖 Requirement 4（副作用动作的人工确认）与 Requirement 8.5：

- 4.1：含副作用（计费 / 推送 / 转介绍写入）的规划在检查点中断，暴露包含动作类型、
  目标对象与影响范围的待确认方案，且在批准前**不执行**。
- 4.2：批准后执行副作用并向 Event_Bus 发布事件。
- 4.3：拒绝时取消、不改数据，返回标识未执行的结果。
- 4.4：等待超过 300 秒时超时取消、不改数据，返回标识因超时未执行的结果。
- 4.5：因拒绝 / 超时取消时记录审计日志并通知用户。

全部测试在无网络 / 无真实等待下运行：审批来源、时钟、执行器、事件发布、审计与通知
均为可注入的确定性 / 内存假实现。既覆盖 :class:`HITLCheckpoint` 单元路径，也覆盖经
编译图的 interrupt→approve→resume 与 interrupt→reject 端到端流程。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta, timezone

import pytest

from app.agents.hitl import (
    REJECTED_MESSAGE,
    TIMED_OUT_MESSAGE,
    AllowAllApprovalProvider,
    ApprovalResponse,
    CallableApprovalProvider,
    DenyAllApprovalProvider,
    HITLCheckpoint,
    HITLOutcome,
    InMemoryAuditLogger,
    InMemoryNotifier,
    NoResponseApprovalProvider,
    RecordingSideEffectExecutor,
)
from app.agents.intent import IntentResult
from app.agents.state import AgentState, new_state
from app.agents.supervisor import compile_supervisor_graph
from app.models import DomainEvent


# --------------------------------------------------------------------------- #
# 测试替身
# --------------------------------------------------------------------------- #
class RecordingEventPublisher:
    """记录已发布事件的假事件发布器。"""

    def __init__(self) -> None:
        self.events: list[DomainEvent] = []

    def publish(self, event: DomainEvent) -> str:
        self.events.append(event)
        return f"evt-{len(self.events)}"


class StubClock:
    """确定性时钟：按调用顺序返回预置时间，耗尽后停留在最后一个时间。"""

    def __init__(self, times: Sequence[datetime]) -> None:
        self._times = list(times)
        self._i = 0

    def __call__(self) -> datetime:
        t = self._times[min(self._i, len(self._times) - 1)]
        self._i += 1
        return t


class FixedIntentClassifier:
    """伪意图分类器：恒返回指定意图与高置信度。"""

    def __init__(self, intent: str) -> None:
        self._intent = intent

    def classify(
        self, messages: Sequence, *, timeout: float | None = None
    ) -> IntentResult:
        return IntentResult(intent=self._intent, confidence=0.99)


class FakePushExpert:
    """伪运营专家：提议一个"推送"副作用动作（含目标对象与影响范围）。"""

    name = "operation"

    def run(self, state: AgentState) -> AgentState:
        plan = [dict(step) for step in state.get("plan", [])]
        for step in plan:
            if step.get("agent") == self.name and step.get("status") != "done":
                step["status"] = "done"
                break
        outputs = dict(state.get("agent_outputs", {}))
        outputs[self.name] = {
            "status": "ok",
            "summary": "生成召回券方案并拟向 50 位流失客户推送。",
            "proposed_action": {
                "type": "push",
                "target": {"recipients": ["c1", "c2"], "coupon": "8折召回券"},
                "impact_scope": {"recipient_count": 50, "channel": "wecom"},
                "payload": {"template": "recall_v1"},
            },
        }
        return {"plan": plan, "agent_outputs": outputs}


def _t0() -> datetime:
    return datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _side_effect_state() -> AgentState:
    """构造一个含推送副作用动作、已聚合完成的状态。"""
    return new_state(
        "store_88",
        messages=[("user", "对流失客户发召回券并推送")],
        plan=[{"agent": "operation", "status": "done"}],
        agent_outputs={
            "operation": {
                "summary": "召回券方案",
                "proposed_action": {
                    "type": "push",
                    "target": {"recipients": ["c1", "c2"]},
                    "impact_scope": {"recipient_count": 50},
                    "payload": {"template": "recall_v1"},
                },
            }
        },
        final_answer="已生成召回券推送方案。",
    )


# --------------------------------------------------------------------------- #
# 副作用判定与动作抽取（Requirement 4.1）
# --------------------------------------------------------------------------- #
def test_extract_action_exposes_type_target_and_impact() -> None:
    """4.1：待确认方案暴露动作类型、目标对象与影响范围。"""
    state = _side_effect_state()
    assert HITLCheckpoint.has_side_effect(state) is True
    pending = HITLCheckpoint.extract_action(state)
    assert pending["action_type"] == "push"
    assert pending["target"] == {"recipients": ["c1", "c2"]}
    assert pending["impact_scope"] == {"recipient_count": 50}
    assert pending["status"] == "pending_approval"
    assert pending["executed"] is False


def test_no_side_effect_does_not_interrupt() -> None:
    """无副作用动作时不中断：run 返回空增量、执行器不被调用。"""
    executor = RecordingSideEffectExecutor()
    checkpoint = HITLCheckpoint(
        approval_provider=AllowAllApprovalProvider(), executor=executor
    )
    state = new_state(
        "store_88",
        plan=[{"agent": "analysis", "status": "done"}],
        agent_outputs={"analysis": {"summary": "只读分析，无副作用。"}},
    )
    assert HITLCheckpoint.has_side_effect(state) is False
    assert checkpoint.run(state) == {}
    assert executor.executed == []


# --------------------------------------------------------------------------- #
# 批准前不执行（Requirement 4.1，安全默认）
# --------------------------------------------------------------------------- #
def test_default_deny_does_not_execute_before_approval() -> None:
    """4.1：默认拒绝（安全默认）下不调用执行器、不发布事件。"""
    executor = RecordingSideEffectExecutor()
    publisher = RecordingEventPublisher()
    checkpoint = HITLCheckpoint(  # 不注入审批来源 → 默认 DenyAll
        executor=executor,
        event_publisher=publisher,
        audit_logger=InMemoryAuditLogger(),
        notifier=InMemoryNotifier(),
    )
    delta = checkpoint.run(_side_effect_state())
    assert delta["pending_action"]["executed"] is False
    assert executor.executed == []
    assert publisher.events == []


# --------------------------------------------------------------------------- #
# 批准 → 执行并发布事件（Requirement 4.2）
# --------------------------------------------------------------------------- #
def test_approve_executes_and_publishes_event() -> None:
    """4.2：批准后执行副作用并发布事件。"""
    executor = RecordingSideEffectExecutor()
    publisher = RecordingEventPublisher()
    checkpoint = HITLCheckpoint(
        approval_provider=AllowAllApprovalProvider(),
        executor=executor,
        event_publisher=publisher,
        clock=StubClock([_t0()]),
    )
    delta = checkpoint.run(_side_effect_state())
    pending = delta["pending_action"]

    assert pending["outcome"] == HITLOutcome.APPROVED.value
    assert pending["executed"] is True
    assert pending["result"]["executed"] is True
    # 执行器仅在批准后被调用一次。
    assert len(executor.executed) == 1
    # 发布了对应事件（push → push_sent）。
    assert len(publisher.events) == 1
    assert publisher.events[0].event_type == "push_sent"
    assert publisher.events[0].tenant_id == "store_88"
    assert pending["event_id"] == "evt-1"


# --------------------------------------------------------------------------- #
# 拒绝 → 取消、不改数据、审计 + 通知（Requirement 4.3 / 4.5）
# --------------------------------------------------------------------------- #
def test_reject_cancels_without_data_change_and_audits_and_notifies() -> None:
    """4.3 / 4.5：拒绝取消、不执行，记录审计并通知。"""
    executor = RecordingSideEffectExecutor()
    publisher = RecordingEventPublisher()
    audit = InMemoryAuditLogger()
    notifier = InMemoryNotifier()
    checkpoint = HITLCheckpoint(
        approval_provider=CallableApprovalProvider(lambda a: False),
        executor=executor,
        event_publisher=publisher,
        audit_logger=audit,
        notifier=notifier,
        clock=StubClock([_t0()]),
    )
    delta = checkpoint.run(_side_effect_state())
    pending = delta["pending_action"]

    assert pending["outcome"] == HITLOutcome.REJECTED.value
    assert pending["executed"] is False
    assert pending["result"] is None
    assert pending["message"] == REJECTED_MESSAGE
    # 不改数据：执行器与事件发布均未触发。
    assert executor.executed == []
    assert publisher.events == []
    # 审计 + 通知（4.5）。
    assert len(audit.entries) == 1
    assert audit.entries[0]["outcome"] == "rejected"
    assert audit.entries[0]["action_type"] == "push"
    assert notifier.notifications == [("store_88", REJECTED_MESSAGE)]


# --------------------------------------------------------------------------- #
# 超时 → 取消、不改数据、审计 + 通知（Requirement 4.4 / 4.5）
# --------------------------------------------------------------------------- #
def test_timeout_via_no_response_cancels_and_audits() -> None:
    """4.4 / 4.5：无响应视为超时，取消、不执行，审计并通知。"""
    executor = RecordingSideEffectExecutor()
    audit = InMemoryAuditLogger()
    notifier = InMemoryNotifier()
    checkpoint = HITLCheckpoint(
        approval_provider=NoResponseApprovalProvider(),
        executor=executor,
        audit_logger=audit,
        notifier=notifier,
        clock=StubClock([_t0()]),
    )
    delta = checkpoint.run(_side_effect_state())
    pending = delta["pending_action"]

    assert pending["outcome"] == HITLOutcome.TIMED_OUT.value
    assert pending["executed"] is False
    assert pending["message"] == TIMED_OUT_MESSAGE
    assert executor.executed == []
    assert audit.entries[0]["outcome"] == "timed_out"
    assert notifier.notifications == [("store_88", TIMED_OUT_MESSAGE)]


def test_timeout_via_elapsed_exceeding_300s_cancels() -> None:
    """4.4：即便最终"批准"，若等待已超过 300 秒仍判定为超时取消。"""
    executor = RecordingSideEffectExecutor()
    audit = InMemoryAuditLogger()
    notifier = InMemoryNotifier()
    # 请求时刻 t0，响应时刻 t0+400s（超过 300s 上限）。
    late = _t0() + timedelta(seconds=400)
    checkpoint = HITLCheckpoint(
        approval_provider=CallableApprovalProvider(
            lambda a: ApprovalResponse(approved=True, responded_at=late)
        ),
        executor=executor,
        audit_logger=audit,
        notifier=notifier,
        clock=StubClock([_t0()]),
    )
    delta = checkpoint.run(_side_effect_state())
    pending = delta["pending_action"]

    assert pending["outcome"] == HITLOutcome.TIMED_OUT.value
    assert pending["executed"] is False
    assert executor.executed == []
    assert notifier.notifications == [("store_88", TIMED_OUT_MESSAGE)]


def test_approval_within_300s_executes() -> None:
    """4.2 边界：等待未超过 300 秒且批准时正常执行。"""
    executor = RecordingSideEffectExecutor()
    publisher = RecordingEventPublisher()
    within = _t0() + timedelta(seconds=299)
    checkpoint = HITLCheckpoint(
        approval_provider=CallableApprovalProvider(
            lambda a: ApprovalResponse(approved=True, responded_at=within)
        ),
        executor=executor,
        event_publisher=publisher,
        clock=StubClock([_t0()]),
    )
    delta = checkpoint.run(_side_effect_state())
    assert delta["pending_action"]["outcome"] == HITLOutcome.APPROVED.value
    assert len(executor.executed) == 1
    assert len(publisher.events) == 1


# --------------------------------------------------------------------------- #
# 端到端：经编译图的 interrupt→approve→resume 与 interrupt→reject
# --------------------------------------------------------------------------- #
def test_graph_interrupt_approve_resume_executes_and_publishes() -> None:
    """端到端：图在返回用户前经 HITL 检查点，批准后执行并发布事件。"""
    executor = RecordingSideEffectExecutor()
    publisher = RecordingEventPublisher()
    hitl = HITLCheckpoint(
        approval_provider=AllowAllApprovalProvider(),
        executor=executor,
        event_publisher=publisher,
        clock=StubClock([_t0()]),
    )
    graph = compile_supervisor_graph(
        classifier=FixedIntentClassifier("operation"),
        experts={"operation": FakePushExpert()},
        hitl=hitl,
    )
    final = graph.invoke(
        {"tenant_id": "store_88", "messages": [("user", "对流失客户发召回券并推送")]},
        config={"configurable": {"thread_id": "hitl-approve"}},
    )
    pending = final["pending_action"]
    assert pending["action_type"] == "push"
    assert pending["executed"] is True
    assert pending["outcome"] == HITLOutcome.APPROVED.value
    assert len(executor.executed) == 1
    assert len(publisher.events) == 1


def test_graph_interrupt_reject_does_not_execute() -> None:
    """端到端：图经 HITL 检查点被拒绝时不执行、不改数据。"""
    executor = RecordingSideEffectExecutor()
    publisher = RecordingEventPublisher()
    audit = InMemoryAuditLogger()
    notifier = InMemoryNotifier()
    hitl = HITLCheckpoint(
        approval_provider=DenyAllApprovalProvider(),
        executor=executor,
        event_publisher=publisher,
        audit_logger=audit,
        notifier=notifier,
        clock=StubClock([_t0()]),
    )
    graph = compile_supervisor_graph(
        classifier=FixedIntentClassifier("operation"),
        experts={"operation": FakePushExpert()},
        hitl=hitl,
    )
    final = graph.invoke(
        {"tenant_id": "store_88", "messages": [("user", "对流失客户发召回券并推送")]},
        config={"configurable": {"thread_id": "hitl-reject"}},
    )
    pending = final["pending_action"]
    assert pending["executed"] is False
    assert pending["outcome"] == HITLOutcome.REJECTED.value
    assert executor.executed == []
    assert publisher.events == []
    assert len(audit.entries) == 1
    assert notifier.notifications == [("store_88", REJECTED_MESSAGE)]
