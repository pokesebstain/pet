"""生态合作网络：健康预警转介绍动作构造与写入（对应设计文档组件 4 ``EcosystemNetwork``、
序列图 2.3 与 Requirement 14）。

本模块实现 :class:`EcosystemNetwork` 的转介绍职责（任务 17.1）：

> 需求 14.1：WHEN 收到级别为高的 ``health_alert`` 事件而需发起转介绍，
> THE Ecosystem_Network SHALL 在 5 秒内构造包含目标合作宠物医院、客户标识、宠物标识与
> 转介绍原因的转介绍动作并提交至 HITL_Checkpoint 待确认，且在确认前不执行任何转介绍写入。
>
> 需求 14.2 / 14.3：转介绍动作获批准后执行写入；写入成功后向 Event_Bus 发布转介绍事件。
>
> 需求 14.4：IF 转介绍涉及的客户或宠物的 ``tenant_id`` 不等于请求上下文的 ``tenant_id``，
> THEN 拒绝该转介绍、不执行写入，并返回越权错误。
>
> 需求 14.5：IF 不存在可匹配的合作宠物医院，THEN 拒绝发起该转介绍、不提交至 HITL_Checkpoint，
> 并返回无可用合作方的提示。

设计要点：

- **默认拒绝的 HITL 审批闸门**：与订阅引擎（任务 14.1）一致，实际写入前必须经可注入的
  :class:`ReferralApprovalGate` 放行；闸门**默认拒绝**（:class:`DenyAllReferralApprovalGate`），
  即未显式批准则**不**写入、**不**发布事件、**不**产生任何数据变更，动作停留在待确认（pending）
  状态。完整的 HITL 检查点中断 / 恢复交互由任务 22.3 在 Supervisor 图层实现，本引擎仅放置
  放行钩子。
- **构造在前、写入在后**：先做租户越权校验（14.4）→ 匹配合作医院（14.5）→ 构造转介绍动作
  （14.1）并提交审批闸门 → 仅当获批准才写入（14.2）并发布事件（14.3）。任一前置校验失败即
  抛出对应异常，不触达写入、不发布事件。
- **依赖注入 / 可测**：合作医院、客户 / 宠物目录、转介绍写入、事件发布均以协议（Protocol）
  抽象注入，可用内存假实现在无实时数据库 / Redis 的情况下测试。

范围约束：本任务 **不** 实现健康异常检测（``health_alert`` 的产生属于任务 15.2），也 **不**
实现 HITL 检查点的完整中断 / 恢复交互（任务 22.3）。
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Protocol, runtime_checkable

from app.engines.errors import AuthorizationError, DataNotFoundError, InvalidParameterError
from app.engines.subscription import EventPublisher
from app.models import Customer, DomainEvent, Pet

__all__ = [
    "REFERRAL_CREATED_EVENT",
    "HEALTH_ALERT_EVENT",
    "HIGH_ALERT_LEVEL",
    "REFERRAL_DEADLINE_SECONDS",
    "ReferralStatus",
    "PartnerHospital",
    "ReferralAction",
    "ReferralOutcome",
    "PartnerHospitalProvider",
    "CustomerDirectory",
    "PetDirectory",
    "ReferralStore",
    "ReferralApprovalGate",
    "DenyAllReferralApprovalGate",
    "AllowAllReferralApprovalGate",
    "CallableReferralApprovalGate",
    "InMemoryPartnerHospitalProvider",
    "InMemoryCustomerDirectory",
    "InMemoryPetDirectory",
    "InMemoryReferralStore",
    "NoMatchingPartnerError",
    "EcosystemNetwork",
]

#: 转介绍写入成功后发布的领域事件类型（需求 14.3）。
REFERRAL_CREATED_EVENT = "referral_created"

#: 触发转介绍的上游事件类型（设计文档 7.1 关键事件类型之一）。
HEALTH_ALERT_EVENT = "health_alert"

#: 触发转介绍所要求的告警级别（需求 14.1：仅"高"级别 health_alert 发起转介绍）。
HIGH_ALERT_LEVEL = "high"

#: 需求 14.1 规定的构造 + 提交 HITL 的时间预算（秒）。
REFERRAL_DEADLINE_SECONDS = 5.0


class ReferralStatus(str, Enum):
    """转介绍处理结果状态。"""

    #: 已获 HITL 批准并完成写入、已发布事件（需求 14.2 / 14.3）。
    WRITTEN = "written"
    #: 已构造并提交审批闸门，但未获批准；未写入、未发布（需求 14.1 的"确认前不写入"）。
    PENDING_APPROVAL = "pending_approval"


class NoMatchingPartnerError(DataNotFoundError):
    """无可匹配合作宠物医院错误（需求 14.5）。

    不存在可匹配的合作方时抛出；调用方据此拒绝发起转介绍、不提交至 HITL_Checkpoint，
    并向用户返回无可用合作方的提示。
    """


@dataclass(frozen=True)
class PartnerHospital:
    """合作宠物医院。

    Attributes:
        hospital_id: 合作医院标识（非空）。
        name: 合作医院名称。
        tenant_id: 归属租户；``None`` 表示平台级共享合作方，可被所有租户匹配。
        species: 该医院支持的物种集合；``None`` 表示不限物种。
    """

    hospital_id: str
    name: str
    tenant_id: str | None = None
    species: tuple[str, ...] | None = None

    def matches(self, tenant_id: str, species: str | None) -> bool:
        """判断该医院是否可服务给定租户与物种。"""
        if self.tenant_id is not None and self.tenant_id != tenant_id:
            return False
        if species is not None and self.species is not None and species not in self.species:
            return False
        return True


@dataclass(frozen=True)
class ReferralAction:
    """待确认的转介绍动作（需求 14.1：含目标合作医院、客户、宠物与原因）。

    该动作是提交给 HITL_Checkpoint 展示 / 待确认的内容；批准前不产生任何写入。
    """

    tenant_id: str
    hospital: PartnerHospital
    customer_id: str
    pet_id: str
    reason: str


@dataclass(frozen=True)
class ReferralOutcome:
    """一次转介绍处理的结果。"""

    status: ReferralStatus
    action: ReferralAction
    referral_id: str | None = None
    event_id: str | None = None

    @property
    def approved(self) -> bool:
        """是否已获批准并完成写入。"""
        return self.status is ReferralStatus.WRITTEN


@runtime_checkable
class PartnerHospitalProvider(Protocol):
    """合作医院数据源协议：为给定租户与物种匹配一个合作宠物医院。"""

    def find_match(
        self, tenant_id: str, *, species: str | None = None
    ) -> PartnerHospital | None:  # pragma: no cover - 协议声明
        """返回一个可匹配的合作医院；无匹配返回 ``None``。"""
        ...


@runtime_checkable
class CustomerDirectory(Protocol):
    """客户目录协议：按 ID 查询客户（用于租户越权校验，需求 14.4）。"""

    def get_customer(self, customer_id: str) -> Customer | None:  # pragma: no cover - 协议声明
        ...


@runtime_checkable
class PetDirectory(Protocol):
    """宠物目录协议：按 ID 查询宠物（用于租户越权校验，需求 14.4）。"""

    def get_pet(self, pet_id: str) -> Pet | None:  # pragma: no cover - 协议声明
        ...


@runtime_checkable
class ReferralStore(Protocol):
    """转介绍写入协议：持久化一条转介绍记录，返回其标识（需求 14.2）。"""

    def write_referral(self, action: ReferralAction) -> str:  # pragma: no cover - 协议声明
        ...


@runtime_checkable
class ReferralApprovalGate(Protocol):
    """转介绍审批闸门协议：实际写入前的 HITL 放行钩子（需求 14.1 / 14.2）。

    :meth:`is_approved` 返回 ``True`` 才允许执行转介绍写入；返回 ``False`` 则动作停留在
    待确认（pending）状态，**不**写入、**不**发布事件、**不**产生任何数据变更。
    """

    def is_approved(self, action: ReferralAction) -> bool:  # pragma: no cover - 协议声明
        ...


class DenyAllReferralApprovalGate:
    """默认审批闸门：拒绝一切转介绍写入（需求 14.1 的安全默认）。

    未显式配置批准来源时使用；保证在缺少 HITL 批准的情况下**从不**写入。
    """

    def is_approved(self, action: ReferralAction) -> bool:
        return False


class AllowAllReferralApprovalGate:
    """放行一切转介绍写入的审批闸门，供测试与已在上层完成 HITL 批准的场景使用。"""

    def is_approved(self, action: ReferralAction) -> bool:
        return True


class CallableReferralApprovalGate:
    """将任意 ``(action) -> bool`` 回调包装为 :class:`ReferralApprovalGate` 的适配器。"""

    def __init__(self, callback: Callable[[ReferralAction], bool]) -> None:
        self._callback = callback

    def is_approved(self, action: ReferralAction) -> bool:
        return bool(self._callback(action))


class InMemoryPartnerHospitalProvider:
    """基于内存列表的 :class:`PartnerHospitalProvider` 假实现，供测试与无数据库场景使用。

    ``find_match`` 返回首个满足租户与物种匹配的合作医院（保持登记顺序，结果稳定）。
    """

    def __init__(self, hospitals: list[PartnerHospital] | None = None) -> None:
        self._hospitals: list[PartnerHospital] = list(hospitals or [])

    def add(self, hospital: PartnerHospital) -> None:
        """登记一个合作医院。"""
        self._hospitals.append(hospital)

    def find_match(
        self, tenant_id: str, *, species: str | None = None
    ) -> PartnerHospital | None:
        for hospital in self._hospitals:
            if hospital.matches(tenant_id, species):
                return hospital
        return None


class InMemoryCustomerDirectory:
    """基于内存字典的 :class:`CustomerDirectory` 假实现。"""

    def __init__(self, customers: list[Customer] | None = None) -> None:
        self._customers: dict[str, Customer] = {
            c.customer_id: c for c in (customers or [])
        }

    def add(self, customer: Customer) -> None:
        self._customers[customer.customer_id] = customer

    def get_customer(self, customer_id: str) -> Customer | None:
        return self._customers.get(customer_id)


class InMemoryPetDirectory:
    """基于内存字典的 :class:`PetDirectory` 假实现。"""

    def __init__(self, pets: list[Pet] | None = None) -> None:
        self._pets: dict[str, Pet] = {p.pet_id: p for p in (pets or [])}

    def add(self, pet: Pet) -> None:
        self._pets[pet.pet_id] = pet

    def get_pet(self, pet_id: str) -> Pet | None:
        return self._pets.get(pet_id)


class InMemoryReferralStore:
    """基于内存列表的 :class:`ReferralStore` 假实现，供测试断言"批准前不写入"。"""

    def __init__(self, id_factory: Callable[[], str] | None = None) -> None:
        self._rows: list[tuple[str, ReferralAction]] = []
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)

    def write_referral(self, action: ReferralAction) -> str:
        referral_id = self._id_factory()
        self._rows.append((referral_id, action))
        return referral_id

    @property
    def rows(self) -> list[tuple[str, ReferralAction]]:
        """返回已写入转介绍记录的只读副本。"""
        return list(self._rows)

    def __len__(self) -> int:
        return len(self._rows)


class EcosystemNetwork:
    """生态合作网络：健康预警转介绍动作构造、审批放行、写入与事件发布。"""

    def __init__(
        self,
        partner_provider: PartnerHospitalProvider,
        customer_directory: CustomerDirectory,
        pet_directory: PetDirectory,
        referral_store: ReferralStore,
        event_publisher: EventPublisher,
        *,
        approval_gate: ReferralApprovalGate | None = None,
        id_factory: Callable[[], str] | None = None,
        clock: Callable[[], datetime] | None = None,
        enforce_deadline: bool = False,
        deadline_seconds: float = REFERRAL_DEADLINE_SECONDS,
    ) -> None:
        """构造生态合作网络引擎。

        Args:
            partner_provider: 合作医院数据源（匹配转介绍目标）。
            customer_directory: 客户目录（租户越权校验，需求 14.4）。
            pet_directory: 宠物目录（租户越权校验，需求 14.4）。
            referral_store: 转介绍写入（需求 14.2）。
            event_publisher: 事件发布器（``referral_created`` 事件，需求 14.3）。
            approval_gate: 写入前的 HITL 审批闸门（需求 14.1 / 14.2）。**默认拒绝**
                （:class:`DenyAllReferralApprovalGate`）：未显式批准则不写入、不发事件。
            id_factory: 生成转介绍 ID / 事件 ID 的工厂，默认使用 UUID4。
            clock: 返回当前时间的时钟，默认使用带 UTC 时区的当前时间。
            enforce_deadline: 为真时，构造 + 提交耗时超过预算将抛
                :class:`~app.engines.errors.InvalidParameterError`（默认关闭）。
            deadline_seconds: 时间预算（秒），默认 :data:`REFERRAL_DEADLINE_SECONDS`。
        """
        self._partner_provider = partner_provider
        self._customer_directory = customer_directory
        self._pet_directory = pet_directory
        self._referral_store = referral_store
        self._event_publisher = event_publisher
        self._approval_gate: ReferralApprovalGate = (
            approval_gate or DenyAllReferralApprovalGate()
        )
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)
        self._clock = clock or (lambda: datetime.now(tz=timezone.utc))
        self._enforce_deadline = enforce_deadline
        self._deadline_seconds = deadline_seconds

    def refer_from_alert(
        self, alert: DomainEvent | Mapping[str, Any], tenant_id: str
    ) -> ReferralOutcome:
        """基于高级别 ``health_alert`` 构造并（经批准后）执行转介绍。

        流程（需求 14.1–14.5）：

        1. 校验入参：``tenant_id`` 非空、告警为"高"级别，提取 ``customer_id`` /
           ``pet_id`` / 原因。
        2. 租户越权校验：客户与宠物的 ``tenant_id`` 均须等于上下文 ``tenant_id``，否则
           抛 :class:`~app.engines.errors.AuthorizationError`（需求 14.4）。
        3. 匹配合作医院：无匹配则抛 :class:`NoMatchingPartnerError`、不提交 HITL（需求 14.5）。
        4. 构造转介绍动作并提交审批闸门（需求 14.1）。
        5. 获批准则写入并发布 ``referral_created`` 事件（需求 14.2 / 14.3）；未获批准则
           返回 :attr:`ReferralStatus.PENDING_APPROVAL`，不写入、不发事件。

        Args:
            alert: 高级别 ``health_alert`` 事件（:class:`~app.models.DomainEvent`）或其
                字段映射（须含 ``customer_id``、``pet_id``；可含 ``level``、``reason``、
                ``species``）。
            tenant_id: 请求上下文的租户标识（RLS 隔离键）。

        Returns:
            :class:`ReferralOutcome`：``WRITTEN``（已写入并发事件）或 ``PENDING_APPROVAL``
            （已提交 HITL、待确认）。

        Raises:
            InvalidParameterError: ``tenant_id`` 为空、告警级别非"高"或缺少必需字段。
            AuthorizationError: 客户 / 宠物 ``tenant_id`` 与上下文不符（需求 14.4）。
            DataNotFoundError: 客户 / 宠物不存在。
            NoMatchingPartnerError: 无可匹配的合作宠物医院（需求 14.5）。
        """
        start = time.monotonic()

        tenant_id = self._require_non_blank(tenant_id, "tenant_id")
        payload = self._extract_payload(alert)
        self._require_high_level(payload)

        customer_id = self._require_non_blank(payload.get("customer_id"), "customer_id")
        pet_id = self._require_non_blank(payload.get("pet_id"), "pet_id")
        reason = self._resolve_reason(payload)

        # 租户越权校验（需求 14.4）：客户与宠物均须属于上下文租户。
        pet = self._authorize_pet(pet_id, tenant_id)
        self._authorize_customer(customer_id, tenant_id)

        # 匹配合作医院（需求 14.5）：无匹配即拒绝，且不提交 HITL。
        species = payload.get("species") or pet.species
        hospital = self._partner_provider.find_match(tenant_id, species=species)
        if hospital is None:
            raise NoMatchingPartnerError(
                f"租户 {tenant_id} 下无可匹配的合作宠物医院（物种={species!r}）"
            )

        # 构造转介绍动作并提交 HITL 审批闸门（需求 14.1）。
        action = ReferralAction(
            tenant_id=tenant_id,
            hospital=hospital,
            customer_id=customer_id,
            pet_id=pet_id,
            reason=reason,
        )

        self._check_deadline(start)

        # 批准前不写入（需求 14.1）：默认拒绝闸门下返回 pending。
        if not self._approval_gate.is_approved(action):
            return ReferralOutcome(
                status=ReferralStatus.PENDING_APPROVAL, action=action
            )

        # 获批准：执行写入（需求 14.2）并发布事件（需求 14.3）。
        referral_id = self._referral_store.write_referral(action)
        event_id = self._publish_referral_event(action, referral_id)
        return ReferralOutcome(
            status=ReferralStatus.WRITTEN,
            action=action,
            referral_id=referral_id,
            event_id=event_id,
        )

    # ------------------------------------------------------------------ #
    # 校验与辅助
    # ------------------------------------------------------------------ #
    def _authorize_customer(self, customer_id: str, tenant_id: str) -> Customer:
        customer = self._customer_directory.get_customer(customer_id)
        if customer is None:
            raise DataNotFoundError(f"客户 {customer_id!r} 不存在")
        if customer.tenant_id != tenant_id:
            raise AuthorizationError(
                f"客户 {customer_id!r} 的 tenant_id={customer.tenant_id!r} 与上下文 "
                f"{tenant_id!r} 不符，拒绝转介绍"
            )
        return customer

    def _authorize_pet(self, pet_id: str, tenant_id: str) -> Pet:
        pet = self._pet_directory.get_pet(pet_id)
        if pet is None:
            raise DataNotFoundError(f"宠物 {pet_id!r} 不存在")
        if pet.tenant_id != tenant_id:
            raise AuthorizationError(
                f"宠物 {pet_id!r} 的 tenant_id={pet.tenant_id!r} 与上下文 "
                f"{tenant_id!r} 不符，拒绝转介绍"
            )
        return pet

    def _publish_referral_event(self, action: ReferralAction, referral_id: str) -> str:
        """构造并发布 ``referral_created`` 领域事件，返回事件消息 ID（需求 14.3）。"""
        event = DomainEvent(
            event_id=self._id_factory(),
            tenant_id=action.tenant_id,
            event_type=REFERRAL_CREATED_EVENT,
            payload={
                "referral_id": referral_id,
                "hospital_id": action.hospital.hospital_id,
                "hospital_name": action.hospital.name,
                "customer_id": action.customer_id,
                "pet_id": action.pet_id,
                "reason": action.reason,
            },
            occurred_at=self._clock(),
        )
        return self._event_publisher.publish(event)

    @staticmethod
    def _extract_payload(alert: DomainEvent | Mapping[str, Any]) -> dict[str, Any]:
        """从 health_alert 事件或字段映射中提取转介绍所需字段。"""
        if isinstance(alert, DomainEvent):
            data: dict[str, Any] = dict(alert.payload)
            # 事件类型冗余校验：仅 health_alert 触发转介绍。
            if alert.event_type != HEALTH_ALERT_EVENT:
                raise InvalidParameterError(
                    f"事件类型 {alert.event_type!r} 非 {HEALTH_ALERT_EVENT!r}，"
                    "无法发起转介绍"
                )
            return data
        if isinstance(alert, Mapping):
            return dict(alert)
        raise InvalidParameterError("alert 必须为 DomainEvent 或字段映射")

    @staticmethod
    def _require_high_level(payload: Mapping[str, Any]) -> None:
        """校验告警级别为"高"（需求 14.1：仅高级别 health_alert 发起转介绍）。"""
        level = payload.get("level")
        if level != HIGH_ALERT_LEVEL:
            raise InvalidParameterError(
                f"仅级别为 {HIGH_ALERT_LEVEL!r} 的 health_alert 发起转介绍，"
                f"当前 level={level!r}"
            )

    @staticmethod
    def _resolve_reason(payload: Mapping[str, Any]) -> str:
        """解析转介绍原因；缺失时回退到通用高危健康预警说明。"""
        reason = payload.get("reason")
        if isinstance(reason, str) and reason.strip():
            return reason
        return "检测到高级别健康异常，建议转介绍至合作宠物医院进一步诊疗"

    def _check_deadline(self, start: float) -> None:
        if not self._enforce_deadline:
            return
        elapsed = time.monotonic() - start
        if elapsed > self._deadline_seconds:
            raise InvalidParameterError(
                f"转介绍动作构造与提交耗时 {elapsed:.3f}s，超过预算 "
                f"{self._deadline_seconds:.1f}s"
            )

    @staticmethod
    def _require_non_blank(value: Any, field_name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise InvalidParameterError(f"{field_name} 不能为空")
        return value
