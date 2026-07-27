"""订阅引擎：套餐管理与计费周期（对应设计文档组件 4 ``SubscriptionEngine`` 与 Requirement 8）。

本模块实现 :class:`SubscriptionEngine`：

- :meth:`SubscriptionEngine.create_plan`：校验计费周期与金额范围后保存套餐规格并返回
  套餐标识（Requirements 8.1 / 8.2）。
- :meth:`SubscriptionEngine.run_billing_cycle`：对状态为 ``active`` 的订阅逐笔生成计费，
  返回包含成功笔数、失败笔数与失败原因的计费报告；单笔失败跳过且不改变其状态并记录
  原因（Requirements 8.3 / 8.4）。扣费成功后向事件总线发布 ``subscription_billed`` 事件
  （Requirement 8.6）。

**范围约束（重要）**：实际扣费前的 Human-in-the-loop（HITL）确认（Requirements 8.3 / 8.5）
的**完整检查点交互**由任务 22.3 在 Supervisor 图层实现。本引擎仅对计费进行建模，真正的扣费动作
被委托给可注入的 :class:`PaymentGateway`（收单网关 / charger），本模块 **不** 执行任何真实扣费。
为满足 “批准前不得扣费、不修改账务数据” 的约束（Requirements 8.3 / 8.5），引擎在每笔实际扣费前
必须先经可注入的 :class:`ApprovalGate`（审批闸门 / 钩子）放行；闸门**默认拒绝**（
:class:`DenyAllApprovalGate`），即未显式批准则不会调用收单网关、不产生任何扣费或账务变更，
该笔被作为失败跳过并记录原因。测试可注入 :class:`AllowAllApprovalGate` 或自定义闸门来验证
成功 / 失败 / 未批准三类路径。

所有外部依赖（套餐存储、订阅存储、收单网关、审批闸门、事件发布）均以协议（Protocol）抽象注入，
从而无需真实数据库 / Redis / HITL 前端即可测试。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Protocol, runtime_checkable

from app.engines.errors import InvalidParameterError
from app.models import DomainEvent, Subscription

__all__ = [
    "BillingCycle",
    "PlanSpec",
    "Plan",
    "ChargeOutcome",
    "BillingFailure",
    "BillingReport",
    "PlanStore",
    "SubscriptionStore",
    "PaymentGateway",
    "ApprovalGate",
    "EventPublisher",
    "InMemoryPlanStore",
    "InMemorySubscriptionStore",
    "DenyAllApprovalGate",
    "AllowAllApprovalGate",
    "CallableApprovalGate",
    "SubscriptionEngine",
    "SUBSCRIPTION_BILLED_EVENT",
    "ACTIVE_STATUS",
    "MIN_PLAN_AMOUNT",
    "MAX_PLAN_AMOUNT",
]

#: 计费成功后发布的事件类型（Requirement 8.6）。
SUBSCRIPTION_BILLED_EVENT = "subscription_billed"

#: 参与计费周期的订阅状态（仅 ``active`` 订阅生成计费，Requirement 8.3）。
ACTIVE_STATUS = "active"

#: 套餐金额下界（含），单位：元（Requirement 8.1）。
MIN_PLAN_AMOUNT = 0.01

#: 套餐金额上界（含），单位：元（Requirement 8.1）。
MAX_PLAN_AMOUNT = 999_999_999.99


class BillingCycle(str, Enum):
    """合法的计费周期（Requirement 8.1）。"""

    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"


@dataclass(frozen=True)
class PlanSpec:
    """创建套餐的输入规格。

    Attributes:
        tenant_id: 租户隔离键（非空）。
        name: 套餐名称（非空）。
        billing_cycle: 计费周期，取值须为 :class:`BillingCycle` 之一（或其字符串值）。
        amount: 计费金额（元），须在 ``[MIN_PLAN_AMOUNT, MAX_PLAN_AMOUNT]`` 之间。
    """

    tenant_id: str
    name: str
    billing_cycle: str
    amount: float


@dataclass(frozen=True)
class Plan:
    """已保存的订阅套餐（含系统分配的套餐标识）。"""

    plan_id: str
    tenant_id: str
    name: str
    billing_cycle: BillingCycle
    amount: float


@dataclass(frozen=True)
class ChargeOutcome:
    """单笔扣费结果（由注入的 :class:`PaymentGateway` 返回）。

    ``success`` 为真表示扣费成功；失败时 ``reason`` 应说明原因。
    """

    success: bool
    reason: str | None = None
    transaction_id: str | None = None


@dataclass(frozen=True)
class BillingFailure:
    """单笔计费失败记录（Requirement 8.4）。"""

    subscription_id: str
    reason: str


@dataclass
class BillingReport:
    """一次计费周期运行的结果报告（Requirement 8.3）。"""

    tenant_id: str
    success_count: int = 0
    failure_count: int = 0
    failures: list[BillingFailure] = field(default_factory=list)
    #: 成功扣费后发布的 ``subscription_billed`` 事件 ID 列表（Requirement 8.6）。
    billed_event_ids: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        """本轮处理的订阅总笔数。"""
        return self.success_count + self.failure_count


@runtime_checkable
class PlanStore(Protocol):
    """套餐存储协议：保存与查询套餐规格。"""

    def save_plan(self, plan: Plan) -> None:  # pragma: no cover - 协议声明
        ...

    def get_plan(self, plan_id: str) -> Plan | None:  # pragma: no cover - 协议声明
        ...


@runtime_checkable
class SubscriptionStore(Protocol):
    """订阅存储协议：按租户列出状态为 ``active`` 的订阅。"""

    def list_active(self, tenant_id: str) -> list[Subscription]:  # pragma: no cover - 协议声明
        ...


@runtime_checkable
class PaymentGateway(Protocol):
    """收单网关（charger）协议：执行单笔扣费。

    真实实现对接微信支付等外部收单系统；本引擎不感知底层来源，也不在此执行真实扣费。
    实现应返回 :class:`ChargeOutcome`；若抛出异常，引擎会将其视为单笔失败并记录原因。
    """

    def charge(
        self, subscription: Subscription, plan: Plan
    ) -> ChargeOutcome:  # pragma: no cover - 协议声明
        ...


@runtime_checkable
class ApprovalGate(Protocol):
    """审批闸门协议：实际扣费前的 HITL 放行钩子（Requirements 8.3 / 8.5）。

    :meth:`is_approved` 返回 ``True`` 才允许对该笔订阅执行扣费；返回 ``False`` 则该笔被作为
    失败跳过，**不** 调用收单网关、不产生任何扣费或账务变更。本引擎仅在此处放置放行钩子，
    完整的 HITL 检查点中断 / 恢复交互由任务 22.3 在 Supervisor 图层实现。
    """

    def is_approved(
        self, subscription: Subscription, plan: Plan
    ) -> bool:  # pragma: no cover - 协议声明
        ...


@runtime_checkable
class EventPublisher(Protocol):
    """事件发布协议：与具体事件总线实现解耦。

    :class:`app.events.EventBus` 满足该协议（其 :meth:`publish` 接受
    :class:`~app.models.DomainEvent` 并返回消息 ID）。
    """

    def publish(self, event: DomainEvent) -> str:  # pragma: no cover - 协议声明
        ...


class InMemoryPlanStore:
    """基于内存字典的 :class:`PlanStore` 假实现，供测试与无数据库场景使用。"""

    def __init__(self) -> None:
        self._plans: dict[str, Plan] = {}

    def save_plan(self, plan: Plan) -> None:
        self._plans[plan.plan_id] = plan

    def get_plan(self, plan_id: str) -> Plan | None:
        return self._plans.get(plan_id)


class InMemorySubscriptionStore:
    """基于内存字典的 :class:`SubscriptionStore` 假实现，供测试与无数据库场景使用。"""

    def __init__(self, subscriptions: list[Subscription] | None = None) -> None:
        self._subscriptions: list[Subscription] = list(subscriptions or [])

    def add(self, subscription: Subscription) -> None:
        """登记一个订阅。"""
        self._subscriptions.append(subscription)

    def list_active(self, tenant_id: str) -> list[Subscription]:
        return [
            sub
            for sub in self._subscriptions
            if sub.tenant_id == tenant_id and sub.status == ACTIVE_STATUS
        ]


class DenyAllApprovalGate:
    """默认审批闸门：拒绝一切扣费（Requirements 8.3 / 8.5 的安全默认）。

    未显式配置批准来源时使用；保证引擎在缺少 HITL 批准的情况下**从不**扣费。
    """

    def is_approved(self, subscription: Subscription, plan: Plan) -> bool:
        return False


class AllowAllApprovalGate:
    """放行一切扣费的审批闸门，供测试与已在上层完成 HITL 批准的场景使用。"""

    def is_approved(self, subscription: Subscription, plan: Plan) -> bool:
        return True


class CallableApprovalGate:
    """将任意回调包装为 :class:`ApprovalGate` 的适配器。

    便于上层直接注入一个 ``(subscription, plan) -> bool`` 的审批回调（例如查询 HITL
    批准结果集或白名单）。
    """

    def __init__(self, callback: Callable[[Subscription, Plan], bool]) -> None:
        self._callback = callback

    def is_approved(self, subscription: Subscription, plan: Plan) -> bool:
        return bool(self._callback(subscription, plan))


class SubscriptionEngine:
    """订阅引擎：套餐管理与计费周期。"""

    def __init__(
        self,
        plan_store: PlanStore,
        subscription_store: SubscriptionStore,
        charger: PaymentGateway,
        event_publisher: EventPublisher,
        *,
        approval_gate: ApprovalGate | None = None,
        id_factory: Callable[[], str] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """构造引擎。

        Args:
            plan_store: 套餐存储（保存 / 查询套餐规格）。
            subscription_store: 订阅存储（列出 ``active`` 订阅）。
            charger: 收单网关（可注入的扣费实现；本引擎不执行真实扣费）。
            event_publisher: 事件发布器（``subscription_billed`` 事件）。
            approval_gate: 实际扣费前的 HITL 审批闸门（Requirements 8.3 / 8.5）。
                **默认拒绝**（:class:`DenyAllApprovalGate`）：未显式批准则不扣费、不产生账务变更。
            id_factory: 可选，生成套餐 ID / 事件 ID 的工厂，默认使用 UUID4。
            clock: 可选，返回当前时间的时钟，默认使用带 UTC 时区的当前时间。
        """
        self._plan_store = plan_store
        self._subscription_store = subscription_store
        self._charger = charger
        self._event_publisher = event_publisher
        self._approval_gate: ApprovalGate = approval_gate or DenyAllApprovalGate()
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)
        self._clock = clock or (lambda: datetime.now(tz=timezone.utc))

    # ------------------------------------------------------------------ #
    # 套餐管理
    # ------------------------------------------------------------------ #
    def create_plan(self, spec: PlanSpec) -> Plan:
        """校验并保存订阅套餐，返回套餐标识（Requirements 8.1 / 8.2）。

        校验通过（计费周期为 monthly/quarterly/yearly 之一，金额在
        ``[0.01, 999,999,999.99]`` 之间）才保存并返回 :class:`Plan`；任一校验失败则拒绝、
        不保存数据，并抛出 :class:`~app.engines.errors.InvalidParameterError` 指明无效字段。

        Raises:
            InvalidParameterError: ``tenant_id`` / ``name`` 为空、计费周期非法或金额越界。
        """
        tenant_id = self._require_non_blank(spec.tenant_id, "tenant_id")
        name = self._require_non_blank(spec.name, "name")
        billing_cycle = self._validate_billing_cycle(spec.billing_cycle)
        amount = self._validate_amount(spec.amount)

        plan = Plan(
            plan_id=self._id_factory(),
            tenant_id=tenant_id,
            name=name,
            billing_cycle=billing_cycle,
            amount=amount,
        )
        # 仅在全部校验通过后写入，保证校验失败时不产生任何数据变更（Requirement 8.2）。
        self._plan_store.save_plan(plan)
        return plan

    # ------------------------------------------------------------------ #
    # 计费周期
    # ------------------------------------------------------------------ #
    def run_billing_cycle(self, tenant_id: str) -> BillingReport:
        """对租户下 ``active`` 订阅逐笔生成计费，返回计费报告（Requirements 8.3 / 8.4 / 8.6）。

        逐笔处理：解析套餐 → 委托 :class:`PaymentGateway` 扣费。扣费成功则发布
        ``subscription_billed`` 事件并计入成功笔数；单笔失败（网关返回失败、抛异常，或
        套餐缺失）则跳过该笔、**不改变其订阅状态**、记录失败原因并计入失败笔数，继续处理
        后续订阅。

        Raises:
            InvalidParameterError: ``tenant_id`` 为空。
        """
        tenant_id = self._require_non_blank(tenant_id, "tenant_id")
        report = BillingReport(tenant_id=tenant_id)

        for subscription in self._subscription_store.list_active(tenant_id):
            self._bill_one(subscription, report)

        return report

    def _bill_one(self, subscription: Subscription, report: BillingReport) -> None:
        """处理单笔订阅计费，将结果累加到报告中（失败被隔离，不影响其它订阅）。"""
        plan = self._plan_store.get_plan(subscription.plan_id)
        if plan is None:
            self._record_failure(
                report, subscription, f"套餐 {subscription.plan_id} 不存在"
            )
            return

        # HITL 审批闸门（Requirements 8.3 / 8.5）：批准前不得扣费、不修改账务数据。
        # 未获批准时不调用收单网关，将该笔作为失败跳过并记录原因（不改变其订阅状态）。
        try:
            approved = self._approval_gate.is_approved(subscription, plan)
        except Exception as exc:  # noqa: BLE001 - 审批钩子异常同样不得触发扣费
            self._record_failure(report, subscription, f"审批钩子异常：{exc}")
            return

        if not approved:
            self._record_failure(report, subscription, "未获 HITL 批准，跳过扣费")
            return

        try:
            outcome = self._charger.charge(subscription, plan)
        except Exception as exc:  # noqa: BLE001 - 单笔失败必须被隔离，不中断整轮计费
            self._record_failure(report, subscription, f"扣费异常：{exc}")
            return

        if not outcome.success:
            reason = outcome.reason or "扣费失败"
            self._record_failure(report, subscription, reason)
            return

        # 扣费成功：发布 subscription_billed 事件（Requirement 8.6）。
        event_id = self._publish_billed_event(subscription, plan, outcome)
        report.success_count += 1
        report.billed_event_ids.append(event_id)

    def _record_failure(
        self, report: BillingReport, subscription: Subscription, reason: str
    ) -> None:
        """记录单笔失败：跳过该笔、保持其状态不变（本引擎从不修改订阅状态）。"""
        report.failure_count += 1
        report.failures.append(
            BillingFailure(subscription_id=subscription.subscription_id, reason=reason)
        )

    def _publish_billed_event(
        self, subscription: Subscription, plan: Plan, outcome: ChargeOutcome
    ) -> str:
        """构造并发布 ``subscription_billed`` 领域事件，返回事件消息 ID。"""
        event = DomainEvent(
            event_id=self._id_factory(),
            tenant_id=subscription.tenant_id,
            event_type=SUBSCRIPTION_BILLED_EVENT,
            payload={
                "subscription_id": subscription.subscription_id,
                "customer_id": subscription.customer_id,
                "plan_id": plan.plan_id,
                "amount": plan.amount,
                "billing_cycle": plan.billing_cycle.value,
                "transaction_id": outcome.transaction_id,
            },
            occurred_at=self._clock(),
        )
        return self._event_publisher.publish(event)

    # ------------------------------------------------------------------ #
    # 校验辅助
    # ------------------------------------------------------------------ #
    @staticmethod
    def _require_non_blank(value: str, field_name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise InvalidParameterError(f"{field_name} 不能为空")
        return value

    @staticmethod
    def _validate_billing_cycle(billing_cycle: str) -> BillingCycle:
        try:
            return BillingCycle(billing_cycle)
        except ValueError as exc:
            valid = ", ".join(c.value for c in BillingCycle)
            raise InvalidParameterError(
                f"billing_cycle 非法：{billing_cycle!r}，须为 {valid} 之一"
            ) from exc

    @staticmethod
    def _validate_amount(amount: float) -> float:
        if isinstance(amount, bool) or not isinstance(amount, (int, float)):
            raise InvalidParameterError("amount 必须为数值")
        fvalue = float(amount)
        # NaN/inf 及越界一律拒绝。
        if not (MIN_PLAN_AMOUNT <= fvalue <= MAX_PLAN_AMOUNT):
            raise InvalidParameterError(
                f"amount={amount} 越界，须在 [{MIN_PLAN_AMOUNT}, {MAX_PLAN_AMOUNT}] 之间"
            )
        return fvalue
