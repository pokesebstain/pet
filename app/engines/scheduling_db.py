"""排期引擎的 PostgreSQL 后端提供者（对应设计 14.7 / 14.8，落地任务 26 的真实数据接线）。

:mod:`app.engines.scheduling` 的 :class:`~app.engines.scheduling.SchedulingEngine` 通过若干
**协议**（``BusinessHoursProvider`` / ``ResourceProvider`` / ``AppointmentProvider`` 以及写入路径
的 ``SlotLockManager`` / ``AppointmentWriter`` / ``BookingEventPublisher``）访问数据，从而与具体
存储解耦。本模块提供这些协议的 **PostgreSQL 实现**，全部经既有 RLS 会话上下文
（:func:`~app.db.session.tenant_session`，等价 ``SET LOCAL app.current_tenant``）访问，
保证每次数据访问都在正确的租户隔离上下文内（Property 17 / Requirement 5.1）。

组件：

- :class:`DbBusinessHoursProvider`：读取 ``business_hours``。
- :class:`DbResourceProvider`：统计某服务类型的**活跃**洗护资源数作为时段容量。
- :class:`DbAppointmentProvider`：统计与目标时段**重叠**、状态在给定集合内的预约数。
- :class:`DbSlotLockManager`：对 ``slot_capacities`` 的 ``(tenant, service_type, start_at)`` 行执行
  ``SELECT … FOR UPDATE`` 串行化同槽并发预约（行不存在时先幂等创建），复刻设计 14.7.3 的行级锁。
- :class:`DbAppointmentWriter`：向 ``appointments`` 插入预约记录。
- :class:`DbCustomerPetResolver`：由租户 + 企业微信 ``external_user_id`` 解析下单客户及其宠物，
  用于接待预约 Agent 的宠物消解（恰好一只 → 采用；零只 / 多只 → 请客户澄清）。

并发正确性（防超卖，Property 14）：``book_appointment`` 在 ``with slot_locks.lock_slot(...)``
临界区内完成"检查—写入"。:class:`DbSlotLockManager` 持有的行级锁事务在**写入提交之后**才随
``with`` 退出而释放，因此后到的并发请求在获得同一行锁后必然能看到已提交的写入并据此判定满档，
绝不超容量。计数 / 写入各自在独立的 ``tenant_session`` 事务内进行，但由行级锁串行化其相对顺序。
"""

from __future__ import annotations

from collections.abc import Iterable
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import uuid

from sqlalchemy import func, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.metadata import (
    appointments as appointments_table,
    business_hours as business_hours_table,
    customers as customers_table,
    grooming_resources as grooming_resources_table,
    pets as pets_table,
    slot_capacities as slot_capacities_table,
)
from app.db.session import tenant_session
from app.engines.scheduling import DEFAULT_SLOT_MINUTES, SchedulingEngine
from app.models.scheduling import (
    Appointment,
    AppointmentStatus,
    BusinessHours,
    ServiceType,
)

if TYPE_CHECKING:  # 仅用于类型标注，避免运行时强依赖。
    from sqlalchemy.engine import Engine

__all__ = [
    "DbBusinessHoursProvider",
    "DbResourceProvider",
    "DbAppointmentProvider",
    "DbSlotLockManager",
    "DbAppointmentWriter",
    "DbCustomerPetResolver",
    "DbOnboardingWriter",
    "PetResolution",
    "build_db_scheduling_engine",
    "DbSchedulingComponents",
]


# --------------------------------------------------------------------------- #
# 只读提供者
# --------------------------------------------------------------------------- #
class DbBusinessHoursProvider:
    """基于 ``business_hours`` 表的 :class:`~app.engines.scheduling.BusinessHoursProvider`。"""

    def __init__(self, engine: "Engine") -> None:
        self._engine = engine

    def get_business_hours(self, tenant_id: str, weekday: int) -> BusinessHours | None:
        stmt = select(
            business_hours_table.c.open_time, business_hours_table.c.close_time
        ).where(
            business_hours_table.c.tenant_id == tenant_id,
            business_hours_table.c.weekday == weekday,
        )
        with tenant_session(self._engine, tenant_id) as conn:
            row = conn.execute(stmt).first()
        if row is None:
            return None
        return BusinessHours(
            tenant_id=tenant_id,
            weekday=weekday,
            open_time=row.open_time,
            close_time=row.close_time,
        )


class DbResourceProvider:
    """基于 ``grooming_resources`` 的 :class:`~app.engines.scheduling.ResourceProvider`。

    某服务类型的**活跃**资源数即该服务在同一时段可并行服务的容量。
    """

    def __init__(self, engine: "Engine") -> None:
        self._engine = engine

    def count_active_resources(
        self, tenant_id: str, service_type: ServiceType
    ) -> int:
        stmt = (
            select(func.count())
            .select_from(grooming_resources_table)
            .where(
                grooming_resources_table.c.tenant_id == tenant_id,
                grooming_resources_table.c.service_type == service_type.value,
                grooming_resources_table.c.active.is_(True),
            )
        )
        with tenant_session(self._engine, tenant_id) as conn:
            return int(conn.execute(stmt).scalar_one())


class DbAppointmentProvider:
    """基于 ``appointments`` 的 :class:`~app.engines.scheduling.AppointmentProvider`。

    统计与半开区间 ``[start_at, end_at)`` **重叠**、状态在 ``statuses`` 内的预约数
    （RLS 内计数，仅当前租户）。重叠条件：``appt.start_at < end_at AND appt.end_at > start_at``。
    """

    def __init__(self, engine: "Engine") -> None:
        self._engine = engine

    def count_overlapping_appointments(
        self,
        tenant_id: str,
        service_type: ServiceType,
        start_at: datetime,
        end_at: datetime,
        statuses: Iterable[AppointmentStatus],
    ) -> int:
        status_values = [s.value for s in statuses]
        stmt = (
            select(func.count())
            .select_from(appointments_table)
            .where(
                appointments_table.c.tenant_id == tenant_id,
                appointments_table.c.service_type == service_type.value,
                appointments_table.c.status.in_(status_values),
                appointments_table.c.start_at < end_at,
                appointments_table.c.end_at > start_at,
            )
        )
        with tenant_session(self._engine, tenant_id) as conn:
            return int(conn.execute(stmt).scalar_one())


# --------------------------------------------------------------------------- #
# 写入路径：行级锁 + 预约写入
# --------------------------------------------------------------------------- #
class DbSlotLockManager:
    """时段容量行行级锁管理器（``SELECT … FOR UPDATE``，复刻设计 14.7.3）。

    :meth:`lock_slot` 打开一个 ``tenant_session`` 事务，对 ``slot_capacities`` 中
    ``(tenant_id, service_type, start_at)`` 对应行加行级锁；行不存在时先以
    ``INSERT … ON CONFLICT DO NOTHING`` 幂等创建（容量取当前活跃资源数，仅作锚点）。
    锁随 ``with`` 退出时事务提交而释放，从而串行化同槽并发预约的"检查—写入"。
    """

    def __init__(
        self, engine: "Engine", *, slot_minutes: int = DEFAULT_SLOT_MINUTES
    ) -> None:
        self._engine = engine
        self._slot_minutes = slot_minutes

    @contextmanager
    def lock_slot(
        self, tenant_id: str, service_type: ServiceType, start_at: datetime
    ):
        end_at = start_at + timedelta(minutes=self._slot_minutes)
        with tenant_session(self._engine, tenant_id) as conn:
            # 容量锚点 = 当前活跃资源数（仅用于建行，可用性以 ResourceProvider 为准）。
            capacity = int(
                conn.execute(
                    select(func.count())
                    .select_from(grooming_resources_table)
                    .where(
                        grooming_resources_table.c.tenant_id == tenant_id,
                        grooming_resources_table.c.service_type == service_type.value,
                        grooming_resources_table.c.active.is_(True),
                    )
                ).scalar_one()
            )
            conn.execute(
                pg_insert(slot_capacities_table)
                .values(
                    tenant_id=tenant_id,
                    service_type=service_type.value,
                    start_at=start_at,
                    end_at=end_at,
                    capacity=capacity,
                )
                .on_conflict_do_nothing(
                    index_elements=["tenant_id", "service_type", "start_at"]
                )
            )
            # 行级锁：串行化同槽并发预约（同一行的后到者阻塞至本事务提交）。
            conn.execute(
                select(slot_capacities_table.c.capacity)
                .where(
                    slot_capacities_table.c.tenant_id == tenant_id,
                    slot_capacities_table.c.service_type == service_type.value,
                    slot_capacities_table.c.start_at == start_at,
                )
                .with_for_update()
            ).first()
            yield
        # 事务在此提交，行级锁释放。


class DbAppointmentWriter:
    """向 ``appointments`` 写入预约记录的 :class:`~app.engines.scheduling.AppointmentWriter`。"""

    def __init__(self, engine: "Engine") -> None:
        self._engine = engine

    def insert_appointment(self, appointment: Appointment) -> None:
        stmt = insert(appointments_table).values(
            appointment_id=appointment.appointment_id,
            tenant_id=appointment.tenant_id,
            customer_id=appointment.customer_id,
            pet_id=appointment.pet_id,
            service_type=appointment.service_type.value,
            start_at=appointment.start_at,
            end_at=appointment.end_at,
            resource_id=appointment.resource_id,
            status=appointment.status.value,
            source=appointment.source,
            created_at=appointment.created_at,
        )
        with tenant_session(self._engine, appointment.tenant_id) as conn:
            conn.execute(stmt)


# --------------------------------------------------------------------------- #
# 客户 / 宠物消解（企业微信外部联系人 → Customer + Pets）
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class PetResolution:
    """当前租户中外部联系人对应的客户、宠物和建档进度。"""

    customer_id: str | None
    pet_ids: list[str] = field(default_factory=list)
    onboarding_pending: bool = False
    missing_profile_fields: tuple[str, ...] = ()

    @property
    def single_pet_id(self) -> str | None:
        """恰好一只宠物时返回其标识，否则返回 ``None``（零只 / 多只需澄清）。"""
        return self.pet_ids[0] if len(self.pet_ids) == 1 else None


class DbCustomerPetResolver:
    """在 RLS 范围内按租户和外部联系人标识解析客户、宠物及待补齐资料。"""

    def __init__(self, engine: "Engine") -> None:
        self._engine = engine

    def resolve(self, tenant_id: str, external_user_id: str) -> PetResolution:
        if not external_user_id or not external_user_id.strip():
            return PetResolution(customer_id=None)
        ext = external_user_id.strip()
        with tenant_session(self._engine, tenant_id) as conn:
            row = conn.execute(
                select(
                    customers_table.c.customer_id,
                    customers_table.c.phone,
                    customers_table.c.onboarding_pending,
                ).where(customers_table.c.wecom_external_id == ext)
            ).first()
            if row is None:
                row = conn.execute(
                    select(
                        customers_table.c.customer_id,
                        customers_table.c.phone,
                        customers_table.c.onboarding_pending,
                    ).where(customers_table.c.customer_id == ext)
                ).first()
            if row is None:
                return PetResolution(customer_id=None)
            pet_rows = conn.execute(
                select(
                    pets_table.c.pet_id,
                    pets_table.c.species,
                    pets_table.c.breed,
                    pets_table.c.onboarding_pending,
                )
                .where(pets_table.c.owner_id == row.customer_id)
                .order_by(pets_table.c.pet_id)
            ).all()

        missing: list[str] = []
        if not _present(row.phone):
            missing.append("phone")
        if not pet_rows:
            missing.append("pet_name")
        for pet in pet_rows:
            if not _present(pet.species) and "species" not in missing:
                missing.append("species")
            if not _present(pet.breed) and "breed" not in missing:
                missing.append("breed")
        pending = bool(row.onboarding_pending) or any(
            bool(pet.onboarding_pending) for pet in pet_rows
        ) or bool(missing)
        return PetResolution(
            customer_id=row.customer_id,
            pet_ids=[pet.pet_id for pet in pet_rows],
            onboarding_pending=pending,
            missing_profile_fields=tuple(missing),
        )


class DbOnboardingWriter:
    """RLS 内的渐进式建档写入器：缺失资料始终保留 ``NULL``。"""

    def __init__(self, engine: "Engine") -> None:
        self._engine = engine

    def create(
        self,
        tenant_id: str,
        external_user_id: str,
        customer_name: str,
        pet_name: str,
        *,
        phone: str | None = None,
        species: str | None = None,
        breed: str | None = None,
    ) -> PetResolution:
        """以姓名和宠物名建最小档案，并写入本轮已明确的可选资料。"""
        customer_id = f"wechat-{uuid.uuid4().hex[:16]}"
        pet_id = f"wechat-pet-{uuid.uuid4().hex[:16]}"
        phone, species, breed = map(_optional_value, (phone, species, breed))
        pending = not all((phone, species, breed))
        with tenant_session(self._engine, tenant_id) as conn:
            conn.execute(
                insert(customers_table).values(
                    customer_id=customer_id,
                    tenant_id=tenant_id,
                    name=customer_name,
                    phone=phone,
                    registered_at=datetime.now(),
                    wecom_external_id=external_user_id,
                    onboarding_pending=pending,
                )
            )
            conn.execute(
                insert(pets_table).values(
                    pet_id=pet_id,
                    tenant_id=tenant_id,
                    owner_id=customer_id,
                    name=pet_name,
                    species=species,
                    breed=breed,
                    birth_date=None,
                    weight_kg=None,
                    onboarding_pending=pending,
                )
            )
        return self.resolve(tenant_id, external_user_id)

    def update(
        self,
        tenant_id: str,
        customer_id: str,
        pet_id: str,
        *,
        phone: str | None = None,
        species: str | None = None,
        breed: str | None = None,
    ) -> PetResolution:
        """仅更新本轮已确认字段，并根据完整性同步待建档标记。"""
        phone, species, breed = map(_optional_value, (phone, species, breed))
        with tenant_session(self._engine, tenant_id) as conn:
            customer = conn.execute(
                select(customers_table.c.phone).where(
                    customers_table.c.customer_id == customer_id
                )
            ).first()
            pet = conn.execute(
                select(pets_table.c.species, pets_table.c.breed).where(
                    pets_table.c.pet_id == pet_id,
                    pets_table.c.owner_id == customer_id,
                )
            ).first()
            if customer is None or pet is None:
                return PetResolution(customer_id=None)
            final_phone = phone or customer.phone
            final_species = species or pet.species
            final_breed = breed or pet.breed
            pending = not all(map(_present, (final_phone, final_species, final_breed)))
            conn.execute(
                customers_table.update()
                .where(customers_table.c.customer_id == customer_id)
                .values(phone=final_phone, onboarding_pending=pending)
            )
            conn.execute(
                pets_table.update()
                .where(pets_table.c.pet_id == pet_id, pets_table.c.owner_id == customer_id)
                .values(
                    species=final_species,
                    breed=final_breed,
                    onboarding_pending=pending,
                )
            )
        # 按绑定重新解析，确保返回值仍受租户过滤并反映落库后的进度。
        return self.resolve(tenant_id, external_user_id=self._external_id(tenant_id, customer_id))

    def _external_id(self, tenant_id: str, customer_id: str) -> str:
        with tenant_session(self._engine, tenant_id) as conn:
            row = conn.execute(
                select(customers_table.c.wecom_external_id).where(
                    customers_table.c.customer_id == customer_id
                )
            ).first()
        return str(row.wecom_external_id) if row and row.wecom_external_id else customer_id

    def resolve(self, tenant_id: str, external_user_id: str) -> PetResolution:
        return DbCustomerPetResolver(self._engine).resolve(tenant_id, external_user_id)


def _optional_value(value: str | None) -> str | None:
    normalized = value.strip() if isinstance(value, str) else None
    return normalized or None


def _present(value: object) -> bool:
    return bool(value and str(value).strip())


# --------------------------------------------------------------------------- #
# 组合辅助
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class DbSchedulingComponents:
    """PostgreSQL 后端排期组件的装配束（供组合根接线接待预约 Agent）。"""

    engine: SchedulingEngine
    slot_locks: DbSlotLockManager
    appointment_writer: DbAppointmentWriter
    pet_resolver: DbCustomerPetResolver
    onboarding_writer: DbOnboardingWriter


def build_db_scheduling_engine(
    db_engine: "Engine", *, slot_minutes: int = DEFAULT_SLOT_MINUTES
) -> DbSchedulingComponents:
    """基于 SQLAlchemy Engine 装配 PostgreSQL 后端的排期引擎与写入协作者。

    Args:
        db_engine: 已配置的 SQLAlchemy Engine（连接真实 PostgreSQL）。
        slot_minutes: 时段粒度（分钟），须与门店服务时长一致（默认 60）。

    Returns:
        DbSchedulingComponents: 含排期引擎、行级锁管理器、预约写入器与客户 / 宠物消解器。
    """
    engine = SchedulingEngine(
        DbBusinessHoursProvider(db_engine),
        DbResourceProvider(db_engine),
        DbAppointmentProvider(db_engine),
        slot_minutes=slot_minutes,
    )
    return DbSchedulingComponents(
        engine=engine,
        slot_locks=DbSlotLockManager(db_engine, slot_minutes=slot_minutes),
        appointment_writer=DbAppointmentWriter(db_engine),
        pet_resolver=DbCustomerPetResolver(db_engine),
        onboarding_writer=DbOnboardingWriter(db_engine),
    )
