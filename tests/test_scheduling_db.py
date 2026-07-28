"""排期引擎 PostgreSQL 后端提供者的单元测试（任务 26 真实数据接线）。

无需运行中的 PostgreSQL：

- 只读提供者 / 客户宠物消解器 / 预约写入器：在**共享内存 SQLite**（注册 ``set_config``
  以兼容 :func:`~app.db.session.tenant_session` 的 RLS 会话注入）上建表并执行真实 SQL，
  验证查询过滤（含租户过滤）、计数与写入的逻辑路径。
- 行级锁管理器 :class:`DbSlotLockManager`：因 ``FOR UPDATE`` / ``ON CONFLICT`` 属 PostgreSQL
  行为，改用**间谍连接**断言其在 ``tenant_session`` 内注入了租户上下文，并发出了
  ``slot_capacities`` 的 ``INSERT … ON CONFLICT DO NOTHING`` 与 ``SELECT … FOR UPDATE``。
"""

from __future__ import annotations

from datetime import datetime, time

import pytest
from sqlalchemy import create_engine, event, insert
from sqlalchemy.dialects import postgresql
from sqlalchemy.pool import StaticPool

from app.db.metadata import (
    appointments as appointments_table,
    business_hours as business_hours_table,
    customers as customers_table,
    grooming_resources as grooming_resources_table,
    metadata,
    pets as pets_table,
)
from app.db.metadata import SESSION_TENANT_VARIABLE
from app.engines.scheduling_db import (
    DbAppointmentProvider,
    DbAppointmentWriter,
    DbBusinessHoursProvider,
    DbCustomerPetResolver,
    DbResourceProvider,
    DbSlotLockManager,
)
from app.models.scheduling import (
    Appointment,
    AppointmentStatus,
    ServiceType,
)

TENANT = "store-001"
OTHER = "store-002"
DAY = datetime(2024, 1, 6)  # 周六 weekday=5
S14 = datetime(2024, 1, 6, 14, 0)
E15 = datetime(2024, 1, 6, 15, 0)


# --------------------------------------------------------------------------- #
# 共享内存 SQLite 引擎（注册 set_config 以兼容 tenant_session）
# --------------------------------------------------------------------------- #
@pytest.fixture()
def engine():
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )

    @event.listens_for(eng, "connect")
    def _register(dbapi_conn, _rec):  # noqa: ANN001
        # tenant_session 发出 SELECT set_config('app.current_tenant', :tid, true)；
        # SQLite 无此函数，注册一个返回值即可（无 RLS 强制，仅联通链路）。
        dbapi_conn.create_function(
            "set_config", 3, lambda _name, value, _local: value
        )

    tables = [
        customers_table,
        pets_table,
        business_hours_table,
        grooming_resources_table,
        appointments_table,
    ]
    metadata.create_all(eng, tables=tables)
    yield eng
    eng.dispose()


def _insert(engine, table, **values) -> None:
    with engine.begin() as conn:
        conn.execute(insert(table).values(**values))


# --------------------------------------------------------------------------- #
# DbBusinessHoursProvider
# --------------------------------------------------------------------------- #
def test_business_hours_provider_reads_row(engine) -> None:
    _insert(
        engine,
        business_hours_table,
        tenant_id=TENANT,
        weekday=5,
        open_time=time(9, 0),
        close_time=time(19, 0),
    )
    provider = DbBusinessHoursProvider(engine)

    hours = provider.get_business_hours(TENANT, 5)

    assert hours is not None
    assert hours.open_time == time(9, 0)
    assert hours.close_time == time(19, 0)
    # 未配置的星期返回 None。
    assert provider.get_business_hours(TENANT, 4) is None


# --------------------------------------------------------------------------- #
# DbResourceProvider
# --------------------------------------------------------------------------- #
def test_resource_provider_counts_active_of_service_type(engine) -> None:
    _insert(engine, grooming_resources_table, resource_id="r1", tenant_id=TENANT,
            name="人工洗1", service_type="grooming", active=True)
    _insert(engine, grooming_resources_table, resource_id="r2", tenant_id=TENANT,
            name="人工洗2", service_type="grooming", active=True)
    # 非活跃洗护工位不计入。
    _insert(engine, grooming_resources_table, resource_id="r3", tenant_id=TENANT,
            name="停用工位", service_type="grooming", active=False)
    # 其它服务类型不计入。
    _insert(engine, grooming_resources_table, resource_id="r4", tenant_id=TENANT,
            name="自助洗", service_type="self_service", active=True)
    # 其它租户不计入（租户过滤）。
    _insert(engine, grooming_resources_table, resource_id="r5", tenant_id=OTHER,
            name="别店工位", service_type="grooming", active=True)

    provider = DbResourceProvider(engine)

    assert provider.count_active_resources(TENANT, ServiceType.GROOMING) == 2
    assert provider.count_active_resources(TENANT, ServiceType.SELF_SERVICE) == 1
    assert provider.count_active_resources(OTHER, ServiceType.GROOMING) == 1


# --------------------------------------------------------------------------- #
# DbAppointmentProvider
# --------------------------------------------------------------------------- #
def _appt(engine, appt_id, tenant, start, end, status, service="grooming") -> None:
    _insert(
        engine,
        appointments_table,
        appointment_id=appt_id,
        tenant_id=tenant,
        customer_id="c",
        pet_id="p",
        service_type=service,
        start_at=start,
        end_at=end,
        resource_id=None,
        status=status,
        source="wecom",
        created_at=DAY,
    )


def test_appointment_provider_counts_overlapping_occupying(engine) -> None:
    # 完全重叠、CONFIRMED → 计入。
    _appt(engine, "a1", TENANT, S14, E15, "confirmed")
    # 部分重叠、PENDING → 计入。
    _appt(engine, "a2", TENANT, datetime(2024, 1, 6, 14, 30), datetime(2024, 1, 6, 15, 30), "pending")
    # 相邻不重叠（15:00-16:00）→ 不计入（半开区间）。
    _appt(engine, "a3", TENANT, E15, datetime(2024, 1, 6, 16, 0), "confirmed")
    # 已取消 → 不计入。
    _appt(engine, "a4", TENANT, S14, E15, "cancelled")
    # 其它租户 → 不计入。
    _appt(engine, "a5", OTHER, S14, E15, "confirmed")

    provider = DbAppointmentProvider(engine)
    count = provider.count_overlapping_appointments(
        TENANT,
        ServiceType.GROOMING,
        S14,
        E15,
        [AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED],
    )
    assert count == 2


# --------------------------------------------------------------------------- #
# DbAppointmentWriter
# --------------------------------------------------------------------------- #
def test_appointment_writer_inserts_row(engine) -> None:
    writer = DbAppointmentWriter(engine)
    appt = Appointment(
        appointment_id="new-1",
        tenant_id=TENANT,
        customer_id="cust-1",
        pet_id="pet-1",
        service_type=ServiceType.GROOMING,
        start_at=S14,
        end_at=E15,
        resource_id=None,
        status=AppointmentStatus.CONFIRMED,
        source="wecom",
        created_at=DAY,
    )

    writer.insert_appointment(appt)

    provider = DbAppointmentProvider(engine)
    count = provider.count_overlapping_appointments(
        TENANT, ServiceType.GROOMING, S14, E15, [AppointmentStatus.CONFIRMED]
    )
    assert count == 1


# --------------------------------------------------------------------------- #
# DbCustomerPetResolver
# --------------------------------------------------------------------------- #
def _customer(engine, cid, tenant=TENANT, wecom_external_id=None) -> None:
    _insert(
        engine,
        customers_table,
        customer_id=cid,
        tenant_id=tenant,
        name="张三",
        phone="13800000000",
        registered_at=DAY,
        wecom_external_id=wecom_external_id,
    )


def _pet(engine, pid, owner, tenant=TENANT) -> None:
    _insert(
        engine,
        pets_table,
        pet_id=pid,
        tenant_id=tenant,
        owner_id=owner,
        species="dog",
        breed="金毛",
        birth_date=DAY,
        weight_kg=20.0,
    )


def test_resolver_matches_by_wecom_external_id_single_pet(engine) -> None:
    _customer(engine, "cust-1", wecom_external_id="wm-abc")
    _pet(engine, "pet-1", "cust-1")

    resolver = DbCustomerPetResolver(engine)
    resolution = resolver.resolve(TENANT, "wm-abc")

    assert resolution.customer_id == "cust-1"
    assert resolution.pet_ids == ["pet-1"]
    assert resolution.single_pet_id == "pet-1"


def test_resolver_falls_back_to_customer_id_convention(engine) -> None:
    # 未绑定 wecom_external_id，但 customer_id == external_user_id。
    _customer(engine, "ext-2", wecom_external_id=None)
    _pet(engine, "pet-2", "ext-2")

    resolver = DbCustomerPetResolver(engine)
    resolution = resolver.resolve(TENANT, "ext-2")

    assert resolution.customer_id == "ext-2"
    assert resolution.pet_ids == ["pet-2"]


def test_resolver_multiple_pets_has_no_single(engine) -> None:
    _customer(engine, "cust-3", wecom_external_id="wm-3")
    _pet(engine, "pet-3a", "cust-3")
    _pet(engine, "pet-3b", "cust-3")

    resolution = DbCustomerPetResolver(engine).resolve(TENANT, "wm-3")

    assert resolution.customer_id == "cust-3"
    assert sorted(resolution.pet_ids) == ["pet-3a", "pet-3b"]
    assert resolution.single_pet_id is None


def test_resolver_zero_pets(engine) -> None:
    _customer(engine, "cust-4", wecom_external_id="wm-4")

    resolution = DbCustomerPetResolver(engine).resolve(TENANT, "wm-4")

    assert resolution.customer_id == "cust-4"
    assert resolution.pet_ids == []
    assert resolution.single_pet_id is None


def test_resolver_unknown_external_user_returns_none(engine) -> None:
    resolution = DbCustomerPetResolver(engine).resolve(TENANT, "nobody")
    assert resolution.customer_id is None
    assert resolution.pet_ids == []


def test_resolver_blank_external_user_returns_none(engine) -> None:
    resolution = DbCustomerPetResolver(engine).resolve(TENANT, "   ")
    assert resolution.customer_id is None


# --------------------------------------------------------------------------- #
# DbSlotLockManager（间谍连接：验证租户上下文 + FOR UPDATE + ON CONFLICT）
# --------------------------------------------------------------------------- #
class _SpyResult:
    def scalar_one(self) -> int:
        return 0

    def first(self):
        return None


class _SpyTxn:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _SpyConn:
    def __init__(self) -> None:
        self.statements: list = []
        self.params: list = []

    def begin(self):
        return _SpyTxn()

    def execute(self, statement, parameters=None):
        self.statements.append(statement)
        self.params.append(parameters)
        return _SpyResult()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _SpyEngine:
    def __init__(self) -> None:
        self.connection = _SpyConn()

    def connect(self):
        return self.connection


def _render(statement) -> str:
    return str(statement.compile(dialect=postgresql.dialect()))


def test_slot_lock_manager_sets_tenant_and_locks_row() -> None:
    spy = _SpyEngine()
    mgr = DbSlotLockManager(spy, slot_minutes=60)

    with mgr.lock_slot(TENANT, ServiceType.GROOMING, S14):
        pass

    rendered = [_render(s) for s in spy.connection.statements]
    joined = "\n".join(rendered)

    # 1) 租户上下文注入（tenant_session 的 set_config）。
    assert any("set_config" in r for r in rendered)
    # set_config 以绑定参数传入目标租户。
    assert any(
        p and p.get("tenant_id") == TENANT and p.get("var_name") == SESSION_TENANT_VARIABLE
        for p in spy.connection.params
    )
    # 2) slot_capacities 的幂等建行（INSERT ... ON CONFLICT DO NOTHING）。
    assert "INSERT INTO slot_capacities" in joined
    assert "ON CONFLICT" in joined
    # 3) 行级锁：SELECT ... FOR UPDATE。
    assert "FOR UPDATE" in joined
