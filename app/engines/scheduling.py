"""排期引擎（对应设计文档 14.3 组件 C `SchedulingEngine` 与 14.7.2 / 14.7.4）。

本模块实现排期引擎的**可用性检查**与**备选时段建议**能力（任务 26.3），
是容量/时段模型的权威判定来源：

- :meth:`SchedulingEngine.check_availability`：判定目标时段是否完全落在营业时间内，
  并计算剩余容量 ``available = max(capacity - booked, 0) ≥ 0``（对应 14.7.2）。
- :meth:`SchedulingEngine.get_day_schedule`：枚举某营业日各时段的容量与已订数，
  用于向客户回复排期现状（Requirement 23.1）。
- :meth:`SchedulingEngine.suggest_alternatives`：满档时返回至多 N 个 ``available > 0``
  且完全落在营业时间内的备选时段，按与期望时间的接近度升序（同天优先）排列；
  搜索范围内无可用时返回空列表（对应 14.7.4，Requirement 23.2 / 23.3）。

设计要点：所有数据访问（营业时间、活跃资源数=容量、重叠预约计数）均经协议抽象
（:class:`BusinessHoursProvider` / :class:`ResourceProvider` / :class:`AppointmentProvider`），
从而引擎逻辑可用内存假实现在**无实时数据库**的情况下完整测试。原子写入
``book_appointment`` 属任务 26.4，本模块暂不实现。
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Protocol, runtime_checkable

from app.engines.errors import InvalidParameterError
from app.models.scheduling import (
    AppointmentStatus,
    BusinessHours,
    ServiceType,
    TimeSlot,
)

__all__ = [
    "SlotAvailability",
    "BusinessHoursProvider",
    "ResourceProvider",
    "AppointmentProvider",
    "InMemoryBusinessHoursProvider",
    "InMemoryResourceProvider",
    "InMemoryAppointmentProvider",
    "SchedulingEngine",
    "DEFAULT_SLOT_MINUTES",
    "DEFAULT_SEARCH_HORIZON_DAYS",
    "DEFAULT_SUGGESTION_COUNT",
    "OCCUPYING_STATUSES",
]

#: 时段枚举的默认粒度（分钟）。营业时间按此粒度切分为等长时段。
DEFAULT_SLOT_MINUTES = 60

#: 备选建议默认搜索范围（天）。
DEFAULT_SEARCH_HORIZON_DAYS = 7

#: 备选建议默认返回数量。
DEFAULT_SUGGESTION_COUNT = 3

#: 计入容量占用的预约状态（PENDING / CONFIRMED），对应设计 14.7.2。
OCCUPYING_STATUSES: frozenset[AppointmentStatus] = frozenset(
    {AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED}
)


@dataclass(frozen=True)
class SlotAvailability:
    """时段可用性判定结果（对应设计 14.7.2 的 ``SlotAvailability``）。

    - ``available``：剩余容量 = ``max(capacity - booked, 0)``，恒 ``≥ 0``。
    - ``in_business_hours``：目标时段是否**完全**落在营业时间内。
    - ``capacity`` / ``booked``：该时段容量与已占用数（诊断/回复用）。
    """

    available: int
    in_business_hours: bool
    capacity: int
    booked: int


@runtime_checkable
class BusinessHoursProvider(Protocol):
    """营业时间提供者协议。

    按 ``tenant_id`` 与星期（0=周一 … 6=周日）返回 :class:`BusinessHours`，
    该门店当日不营业时返回 ``None``。
    """

    def get_business_hours(
        self, tenant_id: str, weekday: int
    ) -> BusinessHours | None:  # pragma: no cover - 协议声明
        ...


@runtime_checkable
class ResourceProvider(Protocol):
    """洗护资源提供者协议。

    返回某 ``tenant_id`` 下指定服务类型的**活跃资源数**（工位/店员数），
    即同一时段的并行服务容量。
    """

    def count_active_resources(
        self, tenant_id: str, service_type: ServiceType
    ) -> int:  # pragma: no cover - 协议声明
        ...


@runtime_checkable
class AppointmentProvider(Protocol):
    """预约计数提供者协议。

    返回与给定时段 ``[start_at, end_at)`` **重叠**、状态在 ``statuses`` 内的预约数
    （RLS 内计数，仅当前租户）。
    """

    def count_overlapping_appointments(
        self,
        tenant_id: str,
        service_type: ServiceType,
        start_at: datetime,
        end_at: datetime,
        statuses: Iterable[AppointmentStatus],
    ) -> int:  # pragma: no cover - 协议声明
        ...


# --------------------------------------------------------------------------- #
# 内存假实现（供无数据库测试）
# --------------------------------------------------------------------------- #
class InMemoryBusinessHoursProvider:
    """基于内存字典的 :class:`BusinessHoursProvider` 假实现。"""

    def __init__(self, hours: Iterable[BusinessHours] | None = None) -> None:
        # 键：(tenant_id, weekday) → BusinessHours
        self._hours: dict[tuple[str, int], BusinessHours] = {}
        for bh in hours or ():
            self.set_hours(bh)

    def set_hours(self, business_hours: BusinessHours) -> None:
        """登记 / 覆盖某租户某星期的营业时间。"""
        self._hours[(business_hours.tenant_id, business_hours.weekday)] = business_hours

    def set_weekday(
        self,
        tenant_id: str,
        weekday: int,
        open_time: time,
        close_time: time,
    ) -> None:
        """便捷方法：直接设置某星期营业时间。"""
        self.set_hours(
            BusinessHours(
                tenant_id=tenant_id,
                weekday=weekday,
                open_time=open_time,
                close_time=close_time,
            )
        )

    def get_business_hours(self, tenant_id: str, weekday: int) -> BusinessHours | None:
        return self._hours.get((tenant_id, weekday))


class InMemoryResourceProvider:
    """基于内存字典的 :class:`ResourceProvider` 假实现。"""

    def __init__(
        self, capacity_by_service: dict[tuple[str, ServiceType], int] | None = None
    ) -> None:
        self._capacity: dict[tuple[str, ServiceType], int] = dict(
            capacity_by_service or {}
        )

    def set_capacity(
        self, tenant_id: str, service_type: ServiceType, capacity: int
    ) -> None:
        """设置某租户某服务类型的活跃资源数（容量）。"""
        if capacity < 0:
            raise ValueError("capacity 不能为负")
        self._capacity[(tenant_id, service_type)] = capacity

    def count_active_resources(
        self, tenant_id: str, service_type: ServiceType
    ) -> int:
        return self._capacity.get((tenant_id, service_type), 0)


class InMemoryAppointmentProvider:
    """基于内存列表的 :class:`AppointmentProvider` 假实现。

    以 ``(tenant_id, service_type, start_at, end_at, status)`` 记录已占用的预约，
    ``count_overlapping_appointments`` 按半开区间 ``[start, end)`` 判定重叠。
    """

    def __init__(
        self,
        bookings: Iterable[
            tuple[str, ServiceType, datetime, datetime, AppointmentStatus]
        ]
        | None = None,
    ) -> None:
        self._bookings: list[
            tuple[str, ServiceType, datetime, datetime, AppointmentStatus]
        ] = list(bookings or ())

    def add_booking(
        self,
        tenant_id: str,
        service_type: ServiceType,
        start_at: datetime,
        end_at: datetime,
        status: AppointmentStatus = AppointmentStatus.CONFIRMED,
    ) -> None:
        """登记一条已占用预约。"""
        self._bookings.append((tenant_id, service_type, start_at, end_at, status))

    def count_overlapping_appointments(
        self,
        tenant_id: str,
        service_type: ServiceType,
        start_at: datetime,
        end_at: datetime,
        statuses: Iterable[AppointmentStatus],
    ) -> int:
        status_set = set(statuses)
        count = 0
        for b_tenant, b_service, b_start, b_end, b_status in self._bookings:
            if b_tenant != tenant_id or b_service != service_type:
                continue
            if b_status not in status_set:
                continue
            # 半开区间重叠：b_start < end_at 且 start_at < b_end
            if b_start < end_at and start_at < b_end:
                count += 1
        return count


class SchedulingEngine:
    """排期引擎：可用性检查、某日排期查询与满档备选建议。

    通过注入的三个数据提供者接入营业时间、资源容量与预约计数；``slot_minutes``
    决定营业时间被切分的时段粒度（默认 60 分钟）。
    """

    def __init__(
        self,
        business_hours_provider: BusinessHoursProvider,
        resource_provider: ResourceProvider,
        appointment_provider: AppointmentProvider,
        *,
        slot_minutes: int = DEFAULT_SLOT_MINUTES,
    ) -> None:
        if not isinstance(slot_minutes, int) or slot_minutes <= 0:
            raise InvalidParameterError("slot_minutes 必须为正整数")
        self._business_hours = business_hours_provider
        self._resources = resource_provider
        self._appointments = appointment_provider
        self._slot_minutes = slot_minutes

    # ------------------------------------------------------------------ #
    # 可用性检查（14.7.2）
    # ------------------------------------------------------------------ #
    def check_availability(
        self,
        tenant_id: str,
        service_type: ServiceType,
        start_at: datetime,
        end_at: datetime,
    ) -> SlotAvailability:
        """检查目标时段是否在营业时间内且有剩余容量。

        Returns:
            :class:`SlotAvailability`，其中 ``available = max(capacity - booked, 0) ≥ 0``，
            ``in_business_hours`` 反映时段是否完全落在营业时间内。

        Raises:
            InvalidParameterError: ``tenant_id`` 为空或 ``start_at >= end_at``。
        """
        self._require_tenant(tenant_id)
        if start_at >= end_at:
            raise InvalidParameterError("start_at 必须早于 end_at")

        in_hours = self._is_within_business_hours(tenant_id, start_at, end_at)
        capacity = self._resources.count_active_resources(tenant_id, service_type)
        booked = self._appointments.count_overlapping_appointments(
            tenant_id, service_type, start_at, end_at, OCCUPYING_STATUSES
        )
        available = max(capacity - booked, 0)
        return SlotAvailability(
            available=available,
            in_business_hours=in_hours,
            capacity=capacity,
            booked=booked,
        )

    # ------------------------------------------------------------------ #
    # 某日排期（Requirement 23.1）
    # ------------------------------------------------------------------ #
    def get_day_schedule(
        self,
        tenant_id: str,
        service_type: ServiceType,
        day: date,
    ) -> list[TimeSlot]:
        """返回某营业日各时段的容量与已订数。

        按 ``slot_minutes`` 粒度枚举当日营业时间内的等长时段，逐个填充容量与已订数。
        门店当日不营业时返回空列表。

        Raises:
            InvalidParameterError: ``tenant_id`` 为空。
        """
        self._require_tenant(tenant_id)
        schedule: list[TimeSlot] = []
        for start_at, end_at in self._enumerate_business_slots(tenant_id, day):
            capacity = self._resources.count_active_resources(tenant_id, service_type)
            booked = self._appointments.count_overlapping_appointments(
                tenant_id, service_type, start_at, end_at, OCCUPYING_STATUSES
            )
            schedule.append(
                TimeSlot(
                    tenant_id=tenant_id,
                    service_type=service_type,
                    start_at=start_at,
                    end_at=end_at,
                    capacity=capacity,
                    # 计数可能超过容量（异常/历史数据），clamp 以维持模型不变式；
                    # 剩余容量仍由 TimeSlot.available = max(capacity - booked, 0) 表达。
                    booked_count=min(booked, capacity),
                )
            )
        return schedule

    # ------------------------------------------------------------------ #
    # 备选时段建议（14.7.4，Requirement 23.2 / 23.3）
    # ------------------------------------------------------------------ #
    def suggest_alternatives(
        self,
        tenant_id: str,
        service_type: ServiceType,
        requested_start: datetime,
        n: int = DEFAULT_SUGGESTION_COUNT,
        search_horizon_days: int = DEFAULT_SEARCH_HORIZON_DAYS,
    ) -> list[TimeSlot]:
        """满档时返回至多 ``n`` 个真实可用的备选时段。

        自 ``requested_start`` 当天起，在 ``search_horizon_days`` 天范围内枚举营业时段，
        仅保留 ``available > 0`` 且完全落在营业时间内者，按"与期望时间接近度"升序排列
        （同一天优先，其次按 ``|start - requested_start|`` 升序），取前 ``n`` 个。
        无可用时段时返回空列表。

        Raises:
            InvalidParameterError: ``tenant_id`` 为空、``n <= 0`` 或
                ``search_horizon_days <= 0``。
        """
        self._require_tenant(tenant_id)
        if not isinstance(n, int) or n <= 0:
            raise InvalidParameterError("n 必须为正整数")
        if not isinstance(search_horizon_days, int) or search_horizon_days <= 0:
            raise InvalidParameterError("search_horizon_days 必须为正整数")

        requested_day = requested_start.date()
        candidates: list[TimeSlot] = []
        for offset in range(search_horizon_days):
            day = requested_day + timedelta(days=offset)
            for start_at, end_at in self._enumerate_business_slots(tenant_id, day):
                avail = self.check_availability(
                    tenant_id, service_type, start_at, end_at
                )
                if avail.in_business_hours and avail.available > 0:
                    candidates.append(
                        TimeSlot(
                            tenant_id=tenant_id,
                            service_type=service_type,
                            start_at=start_at,
                            end_at=end_at,
                            capacity=avail.capacity,
                            booked_count=min(avail.booked, avail.capacity),
                        )
                    )

        candidates.sort(
            key=lambda s: self._proximity_key(s.start_at, requested_start)
        )
        return candidates[:n]

    # ------------------------------------------------------------------ #
    # 内部辅助
    # ------------------------------------------------------------------ #
    @staticmethod
    def _require_tenant(tenant_id: str) -> None:
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise InvalidParameterError("tenant_id 不能为空")

    def _is_within_business_hours(
        self, tenant_id: str, start_at: datetime, end_at: datetime
    ) -> bool:
        """判定 ``[start_at, end_at]`` 是否完全落在当日营业时间内。

        跨天区间（``end`` 日期晚于 ``start`` 日期）视为不满足单日营业时间约束。
        """
        if end_at.date() != start_at.date():
            return False
        hours = self._business_hours.get_business_hours(
            tenant_id, start_at.weekday()
        )
        if hours is None:
            return False
        return start_at.time() >= hours.open_time and end_at.time() <= hours.close_time

    def _enumerate_business_slots(
        self, tenant_id: str, day: date
    ) -> list[tuple[datetime, datetime]]:
        """枚举某日营业时间内、按 ``slot_minutes`` 切分的等长时段区间。

        仅返回**完整**落在营业时间内的时段（末尾不足一个粒度的余量丢弃）。
        当日不营业时返回空列表。
        """
        hours = self._business_hours.get_business_hours(tenant_id, day.weekday())
        if hours is None:
            return []

        step = timedelta(minutes=self._slot_minutes)
        slot_start = datetime.combine(day, hours.open_time)
        close_dt = datetime.combine(day, hours.close_time)
        slots: list[tuple[datetime, datetime]] = []
        while slot_start + step <= close_dt:
            slot_end = slot_start + step
            slots.append((slot_start, slot_end))
            slot_start = slot_end
        return slots

    @staticmethod
    def _proximity_key(
        slot_start: datetime, requested_start: datetime
    ) -> tuple[int, float]:
        """排序键：同一天优先（0/1），其次按与期望时间的绝对间隔（秒）升序。"""
        same_day = 0 if slot_start.date() == requested_start.date() else 1
        distance = abs((slot_start - requested_start).total_seconds())
        return (same_day, distance)


# =========================================================================== #
# 任务 26.4：原子预约 `book_appointment`（防双重预订）
#
# 对应设计 14.7.3 与 14.8，实现"检查—写入"在时段容量行行级锁下的串行化，
# 从而在并发争抢同一最后空档时仅一笔成功、绝不超容量（Property 14）。
#
# 为使该逻辑可在**无实时数据库**时被完整（含并发）测试，写入路径经三个协议抽象注入：
#   - :class:`SlotLockManager` —— 复刻 ``SELECT … FOR UPDATE`` 的时段行级锁语义；
#   - :class:`AppointmentWriter` —— 预约插入（等价事务内 INSERT）；
#   - :class:`BookingEventPublisher` —— 领域事件发布（既有 ``EventBus`` 结构化满足）。
# 并提供 :class:`InMemoryTransactionalSlotStore`，它同时充当计数源 / 写入器 / 锁管理器，
# 以真实互斥锁串行化并发临界区，可让并发测试断言"两个争抢者仅一个赢得最后空档"。
#
# 本段以**追加**方式扩展模块（新增符号、经 ``__all__ +=`` 追加导出、
# 经 ``SchedulingEngine.book_appointment = _book_appointment`` 将方法挂载到引擎类），
# 不改动既有代码与既有导出，保证既有测试不受影响。
# =========================================================================== #
import threading
import uuid
from contextlib import contextmanager

from app.engines.errors import AuthorizationError, EngineError
from app.models.scheduling import Appointment, BookingRequest
from app.models.timeseries import DomainEvent

#: 预约写入成功后发布的事件类型（设计 14.8）。
APPOINTMENT_BOOKED_EVENT = "appointment_booked"

#: 目标时段满档时发布的事件类型（设计 14.8）。
APPOINTMENT_REJECTED_FULL_EVENT = "appointment_rejected_full"


class OutOfBusinessHoursError(EngineError):
    """目标时段未完全落在门店营业时间内（Requirement 22.4）。

    ``book_appointment`` 抛出本错误时保证**无任何写入**（原子性）。
    """


class SlotFullError(EngineError):
    """目标时段满档，剩余容量为 0（Requirement 22.2 / 23.4 / 24.1）。

    ``book_appointment`` 抛出本错误时保证**无任何写入**；并发争抢同一最后空档时，
    未抢到的请求即以本错误"按满档处理"。
    """


@runtime_checkable
class SlotLockManager(Protocol):
    """时段容量行行级锁管理器协议（复刻 ``SELECT … FOR UPDATE`` 语义）。

    ``lock_slot`` 返回一个上下文管理器：进入时对 ``(tenant_id, service_type, start_at)``
    对应的时段容量行加互斥锁，退出时释放，从而串行化同一时段并发预约的"检查—写入"。
    """

    def lock_slot(
        self, tenant_id: str, service_type: ServiceType, start_at: datetime
    ):  # pragma: no cover - 协议声明
        ...


@runtime_checkable
class AppointmentWriter(Protocol):
    """预约写入器协议（等价事务内 ``INSERT Appointment``）。"""

    def insert_appointment(
        self, appointment: Appointment
    ) -> None:  # pragma: no cover - 协议声明
        ...


@runtime_checkable
class BookingEventPublisher(Protocol):
    """领域事件发布器协议（既有 :class:`~app.events.EventBus` 结构化满足）。"""

    def publish(self, event: DomainEvent):  # pragma: no cover - 协议声明
        ...


class InMemoryTransactionalSlotStore:
    """内存事务性时段存储：预约计数源 + 写入器 + 时段行级锁管理器三合一。

    以每个 ``(tenant_id, service_type, start_at)`` 一把互斥锁串行化并发预约的
    "检查—写入"临界区，在无实时数据库时忠实复刻 ``SELECT … FOR UPDATE`` 语义：
    抢占同一最后空档的多个并发请求中，仅一笔可在持锁临界区内看到剩余容量并写入，
    其余在获锁后重新计数时必然看到满档，据此被拒（``SlotFullError``），绝不超容量。

    该类同时实现 :class:`AppointmentProvider`（``count_overlapping_appointments``）、
    :class:`AppointmentWriter`（``insert_appointment``）与 :class:`SlotLockManager`
    （``lock_slot``），因此可作为同一实例注入排期引擎的计数、写入与加锁三个角色，
    从而保证"写入对随后的计数立即可见"。
    """

    def __init__(
        self,
        bookings: Iterable[
            tuple[str, ServiceType, datetime, datetime, AppointmentStatus]
        ]
        | None = None,
    ) -> None:
        self._bookings: list[
            tuple[str, ServiceType, datetime, datetime, AppointmentStatus]
        ] = list(bookings or ())
        # 保护 _bookings 读写的数据锁（细粒度、短临界区）。
        self._data_lock = threading.Lock()
        # 保护 _slot_locks 注册表的锁 + 每时段一把的行级锁。
        self._registry_lock = threading.Lock()
        self._slot_locks: dict[tuple[str, ServiceType, datetime], threading.Lock] = {}

    def add_booking(
        self,
        tenant_id: str,
        service_type: ServiceType,
        start_at: datetime,
        end_at: datetime,
        status: AppointmentStatus = AppointmentStatus.CONFIRMED,
    ) -> None:
        """登记一条已占用预约（测试构造/预置用）。"""
        with self._data_lock:
            self._bookings.append((tenant_id, service_type, start_at, end_at, status))

    def insert_appointment(self, appointment: Appointment) -> None:
        """写入一条预约（等价事务内 INSERT），对随后的计数立即可见。"""
        self.add_booking(
            appointment.tenant_id,
            appointment.service_type,
            appointment.start_at,
            appointment.end_at,
            appointment.status,
        )

    def count_overlapping_appointments(
        self,
        tenant_id: str,
        service_type: ServiceType,
        start_at: datetime,
        end_at: datetime,
        statuses: Iterable[AppointmentStatus],
    ) -> int:
        status_set = set(statuses)
        with self._data_lock:
            snapshot = list(self._bookings)
        count = 0
        for b_tenant, b_service, b_start, b_end, b_status in snapshot:
            if b_tenant != tenant_id or b_service != service_type:
                continue
            if b_status not in status_set:
                continue
            # 半开区间重叠：b_start < end_at 且 start_at < b_end
            if b_start < end_at and start_at < b_end:
                count += 1
        return count

    @contextmanager
    def lock_slot(
        self, tenant_id: str, service_type: ServiceType, start_at: datetime
    ):
        """对目标时段容量行加互斥锁，串行化该时段并发预约的"检查—写入"。"""
        key = (tenant_id, service_type, start_at)
        with self._registry_lock:
            lock = self._slot_locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._slot_locks[key] = lock
        lock.acquire()
        try:
            yield
        finally:
            lock.release()


def _book_appointment(
    self: "SchedulingEngine",
    req: BookingRequest,
    *,
    context_tenant_id: str,
    slot_locks: SlotLockManager,
    appointment_writer: AppointmentWriter,
    event_bus: BookingEventPublisher,
    appointment_id: str | None = None,
    resource_id: str | None = None,
    now: datetime | None = None,
) -> Appointment:
    """原子预约：在时段行级锁下串行化"检查—写入"，保证绝不超容量（设计 14.7.3）。

    前置校验（任一不满足即抛错且**无任何写入**）：

    - ``context_tenant_id`` / ``req.tenant_id`` 非空；
    - ``req.start_at < req.end_at``（无效时间区间 → :class:`InvalidParameterError`，Req 22.6）；
    - ``req.tenant_id == context_tenant_id``（租户越权 → :class:`AuthorizationError`，Req 24.3）。

    临界区（持有 ``(tenant_id, service_type, start_at)`` 行级锁）：

    - 时段不完全落在营业时间内 → :class:`OutOfBusinessHoursError`（Req 22.4），无写入；
    - 剩余容量为 0 → 退出锁后发布 ``appointment_rejected_full`` 并抛 :class:`SlotFullError`
      （Req 22.2 / 23.4 / 24.1），无写入；
    - 否则写入一条 ``CONFIRMED`` 预约，并断言写入后 ``booked_count ≤ capacity``（Property 14）。

    成功后（退出锁）发布 ``appointment_booked`` 事件（Req 22.3）并返回该 :class:`Appointment`。

    Returns:
        新写入的 :class:`Appointment`（``status = CONFIRMED``）。

    Raises:
        InvalidParameterError: ``tenant_id`` 为空或 ``start_at >= end_at``。
        AuthorizationError: ``req.tenant_id`` 与上下文 ``tenant_id`` 不一致。
        OutOfBusinessHoursError: 时段未完全落在营业时间内。
        SlotFullError: 目标时段满档（剩余容量为 0）。
    """
    self._require_tenant(context_tenant_id)
    self._require_tenant(req.tenant_id)
    # 时间区间无效（Requirement 22.6）——无写入。
    if req.start_at >= req.end_at:
        raise InvalidParameterError("start_at 必须早于 end_at")
    # 租户越权（Requirement 24.3）——无写入。
    if req.tenant_id != context_tenant_id:
        raise AuthorizationError(
            "预约请求的 tenant_id 与上下文不一致，拒绝写入并返回越权错误"
        )

    occurred_at = now if now is not None else datetime.now()
    appt: Appointment | None = None

    # 临界区：以时段容量行行级锁串行化并发"检查—写入"（复刻 SELECT … FOR UPDATE）。
    with slot_locks.lock_slot(req.tenant_id, req.service_type, req.start_at):
        avail = self.check_availability(
            req.tenant_id, req.service_type, req.start_at, req.end_at
        )
        if not avail.in_business_hours:
            # 营业时间外——回滚（无写入），抛错。
            raise OutOfBusinessHoursError(
                "目标时段未完全落在门店营业时间内，拒绝写入"
            )
        if avail.available > 0:
            appt = Appointment(
                appointment_id=appointment_id or uuid.uuid4().hex,
                tenant_id=req.tenant_id,
                customer_id=req.customer_id,
                pet_id=req.pet_id,
                service_type=req.service_type,
                start_at=req.start_at,
                end_at=req.end_at,
                resource_id=resource_id,
                status=AppointmentStatus.CONFIRMED,
                source="wecom",
                created_at=occurred_at,
            )
            appointment_writer.insert_appointment(appt)
            # 不变式（Property 14）：写入后重叠占用数恒 ≤ capacity。
            booked_after = self._appointments.count_overlapping_appointments(
                req.tenant_id,
                req.service_type,
                req.start_at,
                req.end_at,
                OCCUPYING_STATUSES,
            )
            if booked_after > avail.capacity:  # pragma: no cover - 持锁下不可达
                raise EngineError(
                    "预约写入违反容量不变式：booked_count 超过 capacity"
                )
        # avail.available <= 0：满档，标记为 appt is None，退出锁后处理。

    if appt is None:
        # 满档（Requirement 22.2 / 23.4 / 24.1）：发布拒绝事件并抛错，无写入。
        event_bus.publish(
            DomainEvent(
                event_id=uuid.uuid4().hex,
                tenant_id=req.tenant_id,
                event_type=APPOINTMENT_REJECTED_FULL_EVENT,
                payload={
                    "tenant_id": req.tenant_id,
                    "service_type": req.service_type.value,
                    "requested_start": req.start_at.isoformat(),
                    "customer_id": req.customer_id,
                },
                occurred_at=occurred_at,
            )
        )
        raise SlotFullError("目标时段满档，剩余容量为 0，按满档处理")

    # 写入成功（Requirement 22.1 / 22.3）：发布预约成功事件并返回。
    event_bus.publish(
        DomainEvent(
            event_id=uuid.uuid4().hex,
            tenant_id=appt.tenant_id,
            event_type=APPOINTMENT_BOOKED_EVENT,
            payload={
                "appointment_id": appt.appointment_id,
                "tenant_id": appt.tenant_id,
                "service_type": appt.service_type.value,
                "start_at": appt.start_at.isoformat(),
                "end_at": appt.end_at.isoformat(),
                "resource_id": appt.resource_id,
                "customer_id": appt.customer_id,
                "pet_id": appt.pet_id,
            },
            occurred_at=occurred_at,
        )
    )
    return appt


# 将原子预约方法挂载到排期引擎类（追加式扩展，不改动既有 __init__ 与既有方法）。
SchedulingEngine.book_appointment = _book_appointment


# 任务 26.4 新增符号——追加导出（不改动既有 __all__ 列表）。
__all__ += [
    "APPOINTMENT_BOOKED_EVENT",
    "APPOINTMENT_REJECTED_FULL_EVENT",
    "OutOfBusinessHoursError",
    "SlotFullError",
    "SlotLockManager",
    "AppointmentWriter",
    "BookingEventPublisher",
    "InMemoryTransactionalSlotStore",
]
