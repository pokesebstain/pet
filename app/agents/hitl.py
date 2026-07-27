"""HITL 检查点：副作用动作的人工确认（Human-in-the-loop）。

对应设计文档 "2.2 HITL 中断/恢复序列"、"6.7 Supervisor 编排主循环（含反思与 HITL）"
与 "Correctness Property 8：副作用需批准"，实现 Requirement 4（副作用动作的人工确认）的
4.1–4.5 与 Requirement 8.5（计费扣费前须经 HITL 确认）：

- 4.1 规划包含带副作用的动作（计费 / 推送 / 转介绍写入）时，在 HITL 检查点**中断**，
  向用户展示包含**动作类型、目标对象与影响范围**的待确认方案，并在获得用户响应前
  **不执行**该动作（``pending_action`` 在批准前即可见，但绝不调用执行器）。
- 4.2 用户**批准**后由 Tool_Layer 执行该副作用动作，执行成功后向 Event_Bus **发布事件**。
- 4.3 用户**拒绝**时取消该动作、**保持数据不被修改**，返回标识该动作未执行的结果。
- 4.4 等待批准**超过 300 秒**时取消该动作、保持数据不被修改，返回标识因超时未执行的结果。
- 4.5 因拒绝或超时被取消时，**记录审计日志**并向用户**发出取消通知**。

范围与可测性约束（重要）：与订阅引擎 / 生态网络的 :class:`ApprovalGate` 模式保持一致，
本检查点将 **人工审批来源**、**时钟**、**副作用执行器**、**事件发布**、**审计日志** 与
**用户通知** 全部抽象为可注入协议。审批来源默认 **拒绝**（安全默认：无显式批准则不执行）。
借助可注入时钟，超时逻辑可在**无真实等待、无网络**的情况下确定性验证。

本模块只负责"检查点"这一层：判定规划是否含副作用（:meth:`HITLCheckpoint.has_side_effect`）、
抽取待确认动作（:meth:`HITLCheckpoint.extract_action`）、按审批结果放行 / 取消
（:meth:`HITLCheckpoint.run`）。真正的扣费 / 推送 / 转介绍写入由注入的
:class:`SideEffectExecutor`（Tool_Layer 适配）完成，本模块 **不** 执行任何真实副作用。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from app.agents.state import AgentState
from app.models import DomainEvent

__all__ = [
    "HITL_TIMEOUT_SECONDS",
    "SIDE_EFFECT_TYPES",
    "SIDE_EFFECT_EVENT_TYPES",
    "REJECTED_MESSAGE",
    "TIMED_OUT_MESSAGE",
    "HITLOutcome",
    "ApprovalResponse",
    "ApprovalProvider",
    "DenyAllApprovalProvider",
    "AllowAllApprovalProvider",
    "CallableApprovalProvider",
    "NoResponseApprovalProvider",
    "SideEffectExecutor",
    "RecordingSideEffectExecutor",
    "EventPublisher",
    "AuditLogger",
    "InMemoryAuditLogger",
    "Notifier",
    "InMemoryNotifier",
    "HITLCheckpoint",
]

#: HITL 检查点等待批准的时间上限（秒，Requirement 4.4）。
HITL_TIMEOUT_SECONDS: float = 300.0

#: 需经 HITL 确认的副作用动作类型（Requirement 4.1：计费 / 推送 / 转介绍写入）。
SIDE_EFFECT_TYPES: tuple[str, ...] = ("billing", "push", "referral_write")

#: 各副作用类型执行成功后向 Event_Bus 发布的默认事件类型（Requirement 4.2）。
SIDE_EFFECT_EVENT_TYPES: dict[str, str] = {
    "billing": "subscription_billed",
    "push": "push_sent",
    "referral_write": "referral_created",
}

#: 用户拒绝时返回结果 / 通知中使用的说明（Requirement 4.3 / 4.5）。
REJECTED_MESSAGE: str = "该副作用动作已被拒绝，未执行，相关数据未做任何修改。"

#: 等待超时被取消时返回结果 / 通知中使用的说明（Requirement 4.4 / 4.5）。
TIMED_OUT_MESSAGE: str = (
    "该副作用动作因等待批准超过 300 秒已超时取消，未执行，相关数据未做任何修改。"
)


class HITLOutcome(str, Enum):
    """HITL 检查点的三类结局。"""

    #: 已批准并执行、已发布事件（Requirement 4.2）。
    APPROVED = "approved"
    #: 被用户拒绝、未执行（Requirement 4.3）。
    REJECTED = "rejected"
    #: 等待超时、未执行（Requirement 4.4）。
    TIMED_OUT = "timed_out"


@dataclass(frozen=True)
class ApprovalResponse:
    """人工审批来源对待确认动作的响应。

    Attributes:
        approved: ``True`` 批准、``False`` 拒绝、``None`` 表示在等待期内未收到任何响应
            （据此判定为超时，Requirement 4.4）。
        responded_at: 收到响应的时刻；``None`` 时由检查点以当前时钟时间衡量等待时长。
            用于确定"是否等待超过 300 秒"（Requirement 4.4）。
    """

    approved: bool | None
    responded_at: datetime | None = None


@runtime_checkable
class ApprovalProvider(Protocol):
    """人工审批来源协议：HITL 检查点向其请求对待确认动作的批准 / 拒绝。

    生产实现对接前端确认交互（老板端展示方案后回填结果）；测试可注入确定性实现。
    与 :class:`~app.engines.subscription.ApprovalGate` 一致，**默认拒绝**（未显式批准
    则不执行），以保证安全默认。
    """

    def request_approval(
        self, pending_action: dict[str, Any]
    ) -> ApprovalResponse:  # pragma: no cover - 协议声明
        ...


class DenyAllApprovalProvider:
    """默认审批来源：拒绝一切副作用动作（安全默认，Requirement 4.1 的"批准前不执行"）。"""

    def request_approval(self, pending_action: dict[str, Any]) -> ApprovalResponse:
        return ApprovalResponse(approved=False)


class AllowAllApprovalProvider:
    """放行一切副作用动作的审批来源，供测试与已在上层完成 HITL 批准的场景使用。"""

    def request_approval(self, pending_action: dict[str, Any]) -> ApprovalResponse:
        return ApprovalResponse(approved=True)


class NoResponseApprovalProvider:
    """从不响应的审批来源：始终返回 ``approved=None``，据此判定为超时（Requirement 4.4）。"""

    def request_approval(self, pending_action: dict[str, Any]) -> ApprovalResponse:
        return ApprovalResponse(approved=None)


class CallableApprovalProvider:
    """将任意 ``(pending_action) -> ApprovalResponse | bool | None`` 回调包装为审批来源。

    回调返回 :class:`ApprovalResponse` 时原样使用；返回 ``bool`` / ``None`` 时包装为
    对应的 :class:`ApprovalResponse`（``None`` 视为未响应 → 超时）。
    """

    def __init__(
        self,
        callback: Callable[[dict[str, Any]], ApprovalResponse | bool | None],
    ) -> None:
        self._callback = callback

    def request_approval(self, pending_action: dict[str, Any]) -> ApprovalResponse:
        result = self._callback(pending_action)
        if isinstance(result, ApprovalResponse):
            return result
        return ApprovalResponse(approved=result)


@runtime_checkable
class SideEffectExecutor(Protocol):
    """副作用执行器协议：批准后由 Tool_Layer 执行实际动作（Requirement 4.2）。

    仅在获得批准后被调用；返回执行结果字典（并入 ``pending_action.result``）。
    """

    def execute(
        self, pending_action: dict[str, Any]
    ) -> dict[str, Any]:  # pragma: no cover - 协议声明
        ...


class RecordingSideEffectExecutor:
    """记录被执行动作的假执行器，供测试断言"仅批准后才执行"。"""

    def __init__(self) -> None:
        #: 已执行动作的记录（按执行顺序）。未批准 / 拒绝 / 超时时应保持为空。
        self.executed: list[dict[str, Any]] = []

    def execute(self, pending_action: dict[str, Any]) -> dict[str, Any]:
        self.executed.append(pending_action)
        return {"executed": True, "action_type": pending_action.get("action_type")}


@runtime_checkable
class EventPublisher(Protocol):
    """事件发布协议（与 :class:`app.events.EventBus` 兼容）。"""

    def publish(self, event: DomainEvent) -> str:  # pragma: no cover - 协议声明
        ...


@runtime_checkable
class AuditLogger(Protocol):
    """审计日志协议：记录副作用动作被取消的审计条目（Requirement 4.5）。"""

    def record(self, entry: dict[str, Any]) -> None:  # pragma: no cover - 协议声明
        ...


class InMemoryAuditLogger:
    """基于内存列表的 :class:`AuditLogger` 假实现，供测试与无外部依赖场景使用。"""

    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []

    def record(self, entry: dict[str, Any]) -> None:
        self.entries.append(entry)


@runtime_checkable
class Notifier(Protocol):
    """用户通知协议：向用户发出动作被取消的通知（Requirement 4.5）。"""

    def notify(
        self, tenant_id: str, message: str
    ) -> None:  # pragma: no cover - 协议声明
        ...


class InMemoryNotifier:
    """基于内存列表的 :class:`Notifier` 假实现，供测试与无外部依赖场景使用。"""

    def __init__(self) -> None:
        self.notifications: list[tuple[str, str]] = []

    def notify(self, tenant_id: str, message: str) -> None:
        self.notifications.append((tenant_id, message))


class HITLCheckpoint:
    """副作用动作的人工确认检查点（Requirement 4.1–4.5、8.5）。

    所有外部依赖均以协议注入，便于在无网络 / 无真实等待的情况下测试：

    Args:
        approval_provider: 人工审批来源；缺省为 :class:`DenyAllApprovalProvider`（安全默认）。
        executor: 批准后执行副作用的执行器（Tool_Layer 适配）；仅批准后被调用。
        event_publisher: 执行成功后发布事件的发布器（Requirement 4.2）。
        audit_logger: 取消（拒绝 / 超时）时记录审计日志（Requirement 4.5）。
        notifier: 取消（拒绝 / 超时）时通知用户（Requirement 4.5）。
        timeout_seconds: 等待批准的时间上限（秒，默认 :data:`HITL_TIMEOUT_SECONDS`）。
        clock: 返回当前时间的时钟，默认带 UTC 时区的当前时间；注入后可确定性验证超时。
        id_factory: 生成事件 ID 的工厂，默认使用 UUID4。
    """

    def __init__(
        self,
        *,
        approval_provider: ApprovalProvider | None = None,
        executor: SideEffectExecutor | None = None,
        event_publisher: EventPublisher | None = None,
        audit_logger: AuditLogger | None = None,
        notifier: Notifier | None = None,
        timeout_seconds: float = HITL_TIMEOUT_SECONDS,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._approval_provider: ApprovalProvider = (
            approval_provider or DenyAllApprovalProvider()
        )
        self._executor = executor
        self._event_publisher = event_publisher
        self._audit_logger = audit_logger
        self._notifier = notifier
        self._timeout_seconds = timeout_seconds
        self._clock = clock or (lambda: datetime.now(tz=timezone.utc))
        if id_factory is not None:
            self._id_factory = id_factory
        else:
            import uuid

            self._id_factory = lambda: uuid.uuid4().hex

    # -- 副作用判定与动作抽取（Requirement 4.1）-----------------------------

    @staticmethod
    def has_side_effect(state: AgentState) -> bool:
        """判定当前规划是否包含带副作用的动作（计费 / 推送 / 转介绍写入）。"""
        return bool(_collect_side_effect_actions(state))

    @staticmethod
    def extract_action(state: AgentState) -> dict[str, Any]:
        """抽取首个待确认副作用动作，构造展示给用户的待确认方案。

        待确认方案包含**动作类型**、**目标对象**与**影响范围**（Requirement 4.1）。

        Returns:
            dict: ``pending_action``，含 ``action_type`` / ``target`` / ``impact_scope``
            与 ``status="pending_approval"``；无副作用动作时返回空字典。
        """
        actions = _collect_side_effect_actions(state)
        if not actions:
            return {}
        action = actions[0]
        return {
            "action_type": _action_type(action),
            "target": action.get("target"),
            "impact_scope": action.get("impact_scope", action.get("impact")),
            "payload": action.get("payload", {}),
            "event_type": action.get("event_type"),
            "status": "pending_approval",
            "executed": False,
        }

    # -- 检查点主流程（Requirement 4.1–4.5）--------------------------------

    def run(self, state: AgentState) -> AgentState:
        """执行 HITL 检查点，返回状态增量。

        无副作用动作时直接返回空增量（不中断）。否则暴露 ``pending_action``（批准前
        绝不执行），请求人工审批：批准 → 执行并发布事件；拒绝 / 超时 → 取消、不改数据、
        记审计并通知。

        Returns:
            AgentState: 含更新后 ``pending_action`` 的状态增量；无副作用时为空。
        """
        pending = self.extract_action(state)
        if not pending:
            return {}

        outcome = self._await_decision(pending)

        if outcome is HITLOutcome.APPROVED:
            resolved = self._execute_and_publish(state, pending)
        else:
            resolved = self._cancel(state, pending, outcome)

        return {"pending_action": resolved}

    # -- 内部：审批等待与超时判定（Requirement 4.4）-------------------------

    def _await_decision(self, pending: dict[str, Any]) -> HITLOutcome:
        """向审批来源请求决定，并据等待时长判定批准 / 拒绝 / 超时。"""
        requested_at = self._clock()
        response = self._approval_provider.request_approval(pending)
        responded_at = response.responded_at or self._clock()
        elapsed = (responded_at - requested_at).total_seconds()

        # 未响应或等待超过 300 秒 → 超时取消（Requirement 4.4）。
        if response.approved is None or elapsed > self._timeout_seconds:
            return HITLOutcome.TIMED_OUT
        if response.approved:
            return HITLOutcome.APPROVED
        return HITLOutcome.REJECTED

    # -- 内部：批准执行并发布事件（Requirement 4.2）-------------------------

    def _execute_and_publish(
        self, state: AgentState, pending: dict[str, Any]
    ) -> dict[str, Any]:
        """批准路径：执行副作用动作并发布事件。"""
        result: dict[str, Any] | None = None
        if self._executor is not None:
            result = self._executor.execute(pending)

        event_id: str | None = None
        if self._event_publisher is not None:
            event = self._build_event(state, pending)
            event_id = self._event_publisher.publish(event)

        resolved = dict(pending)
        resolved.update(
            {
                "status": "executed",
                "executed": True,
                "outcome": HITLOutcome.APPROVED.value,
                "result": result,
                "event_id": event_id,
            }
        )
        return resolved

    def _build_event(self, state: AgentState, pending: dict[str, Any]) -> DomainEvent:
        """依据待确认动作构造执行成功后发布的领域事件。"""
        action_type = pending.get("action_type") or ""
        event_type = (
            pending.get("event_type")
            or SIDE_EFFECT_EVENT_TYPES.get(action_type)
            or f"{action_type}_executed"
        )
        return DomainEvent(
            event_id=self._id_factory(),
            tenant_id=str(state.get("tenant_id") or ""),
            event_type=event_type,
            payload={
                "action_type": action_type,
                "target": pending.get("target"),
                "impact_scope": pending.get("impact_scope"),
                **(pending.get("payload") or {}),
            },
            occurred_at=self._clock(),
        )

    # -- 内部：取消（拒绝 / 超时）→ 审计 + 通知（Requirement 4.3–4.5）-------

    def _cancel(
        self, state: AgentState, pending: dict[str, Any], outcome: HITLOutcome
    ) -> dict[str, Any]:
        """取消路径：不执行、不改数据，记录审计日志并通知用户。"""
        message = (
            TIMED_OUT_MESSAGE if outcome is HITLOutcome.TIMED_OUT else REJECTED_MESSAGE
        )
        tenant_id = str(state.get("tenant_id") or "")

        # 审计日志（Requirement 4.5）。
        if self._audit_logger is not None:
            self._audit_logger.record(
                {
                    "tenant_id": tenant_id,
                    "action_type": pending.get("action_type"),
                    "target": pending.get("target"),
                    "impact_scope": pending.get("impact_scope"),
                    "outcome": outcome.value,
                    "message": message,
                    "recorded_at": self._clock().isoformat(),
                }
            )

        # 用户通知（Requirement 4.5）。
        if self._notifier is not None:
            self._notifier.notify(tenant_id, message)

        resolved = dict(pending)
        resolved.update(
            {
                "status": outcome.value,
                "executed": False,
                "outcome": outcome.value,
                "result": None,
                "message": message,
            }
        )
        return resolved


# --------------------------------------------------------------------------- #
# 内部辅助：从规划 / 专家输出中收集待确认副作用动作
# --------------------------------------------------------------------------- #
def _action_type(action: dict[str, Any]) -> str | None:
    """读取动作类型（兼容 ``type`` / ``action_type`` 两种键）。"""
    return action.get("action_type") or action.get("type")


def _is_side_effect(action: dict[str, Any]) -> bool:
    """判断单个动作是否属于需 HITL 确认的副作用类型。"""
    return _action_type(action) in SIDE_EFFECT_TYPES


def _collect_side_effect_actions(state: AgentState) -> list[dict[str, Any]]:
    """从规划步骤与专家输出中收集所有副作用动作（保持稳定顺序）。

    动作来源（两者皆支持，便于不同专家以任一方式提出待确认动作）：

    - 规划步骤 ``plan[i]["action"]``：步骤直接携带的副作用动作。
    - 专家输出 ``agent_outputs[name]["proposed_action"]``：专家提议的待确认动作。
    """
    actions: list[dict[str, Any]] = []

    for step in state.get("plan", []) or []:
        action = step.get("action") if isinstance(step, dict) else None
        if isinstance(action, dict) and _is_side_effect(action):
            actions.append(action)

    outputs = state.get("agent_outputs", {}) or {}
    for output in outputs.values():
        if not isinstance(output, dict):
            continue
        proposed = output.get("proposed_action")
        if isinstance(proposed, dict) and _is_side_effect(proposed):
            actions.append(proposed)

    return actions
