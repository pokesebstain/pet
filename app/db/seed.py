"""单门店种子数据例程（对应设计 14.1 / 14.4，落地任务 26 的运行时数据准备）。

在真实 PostgreSQL 上为**单门店（单租户）**幂等地写入排期所需的基础数据，使企业微信
洗护预约在部署后即可端到端跑通：

- **营业时间**：每天（周一至周日，``weekday`` 0-6）09:00–19:00。
- **洗护资源**：一个「人工洗」工位（:class:`ServiceType.GROOMING`，容量=1 个活跃资源）
  + 一个「自助洗」工位（:class:`ServiceType.SELF_SERVICE`）。人工洗是自动预约主路径。
- **（可选）演示数据**：一位演示客户 + 一只宠物，并把该客户绑定到可配置的企业微信
  ``external_user_id``，从而绑定的测试账号可完成一次真实预约。演示数据默认不写入，
  经 ``seed_demo=True`` 或 CLI 环境变量显式开启。

所有写入均经既有 RLS 会话上下文（:func:`~app.db.session.tenant_session`）在目标租户内进行
（Property 17）。全部采用 ``INSERT … ON CONFLICT DO NOTHING`` / 存在性检查以保证幂等，可随
应用启动重复执行。

CLI 用法（读取 ``PETOPS_DEFAULT_TENANT_ID``，缺省回退企业微信 ``corp_id``）::

    python -m app.db.seed                 # 仅基础数据（营业时间 + 资源）
    PETOPS_SEED_DEMO=1 python -m app.db.seed   # 额外写入演示客户 + 宠物
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, time
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.config import Settings, get_settings
from app.db.metadata import (
    business_hours as business_hours_table,
    customers as customers_table,
    grooming_resources as grooming_resources_table,
    pets as pets_table,
)
from app.db.session import tenant_session
from app.models.scheduling import ServiceType

if TYPE_CHECKING:  # 仅用于类型标注。
    from sqlalchemy.engine import Connection, Engine

__all__ = [
    "seed_single_store",
    "seed_from_settings",
    "DEFAULT_OPEN_TIME",
    "DEFAULT_CLOSE_TIME",
    "GROOMING_RESOURCE_ID",
    "SELF_SERVICE_RESOURCE_ID",
    "DEMO_CUSTOMER_ID",
    "DEMO_PET_ID",
    "SEED_DEMO_ENV",
    "DEMO_EXTERNAL_ID_ENV",
]

_LOG = logging.getLogger(__name__)

#: 门店营业时间：每天 09:00–19:00。
DEFAULT_OPEN_TIME = time(9, 0)
DEFAULT_CLOSE_TIME = time(19, 0)

#: 固定的资源标识（幂等种子的主键锚点）。
GROOMING_RESOURCE_ID = "res-grooming-1"
SELF_SERVICE_RESOURCE_ID = "res-self-service-1"

#: 演示客户 / 宠物标识。
DEMO_CUSTOMER_ID = "demo-customer-1"
DEMO_PET_ID = "demo-pet-1"

#: 控制演示数据写入的环境变量与绑定外部联系人标识。
SEED_DEMO_ENV = "PETOPS_SEED_DEMO"
DEMO_EXTERNAL_ID_ENV = "PETOPS_SEED_DEMO_EXTERNAL_ID"


def seed_single_store(
    engine: "Engine",
    tenant_id: str,
    *,
    seed_demo: bool = False,
    demo_external_id: str | None = None,
) -> dict[str, int]:
    """幂等地为单门店写入营业时间、洗护资源与（可选）演示客户 / 宠物。

    Args:
        engine: SQLAlchemy Engine（连接真实 PostgreSQL）。
        tenant_id: 目标门店租户；为空时抛错（避免误写默认租户）。
        seed_demo: 是否额外写入演示客户 + 宠物（默认否）。
        demo_external_id: 演示客户绑定的企业微信 ``external_user_id``；``None`` 时仅按
            ``customer_id == DEMO_CUSTOMER_ID`` 约定可解析。

    Returns:
        各类数据"新增行数"的统计字典（幂等：重复执行时计数为 0）。

    Raises:
        TenantContextMissingError: ``tenant_id`` 为空（由 ``tenant_session`` 校验）。
    """
    counts = {"business_hours": 0, "resources": 0, "customers": 0, "pets": 0}
    with tenant_session(engine, tenant_id) as conn:
        counts["business_hours"] = _seed_business_hours(conn, tenant_id)
        counts["resources"] = _seed_resources(conn, tenant_id)
        if seed_demo:
            counts["customers"] = _seed_demo_customer(
                conn, tenant_id, demo_external_id
            )
            counts["pets"] = _seed_demo_pet(conn, tenant_id)
    _LOG.info("种子数据写入完成（tenant=%s）：%s", tenant_id, counts)
    return counts


def _seed_business_hours(conn: "Connection", tenant_id: str) -> int:
    """写入周一至周日 09:00–19:00 的营业时间（幂等）。"""
    added = 0
    for weekday in range(7):
        stmt = (
            pg_insert(business_hours_table)
            .values(
                tenant_id=tenant_id,
                weekday=weekday,
                open_time=DEFAULT_OPEN_TIME,
                close_time=DEFAULT_CLOSE_TIME,
            )
            .on_conflict_do_nothing(index_elements=["tenant_id", "weekday"])
        )
        result = conn.execute(stmt)
        added += int(result.rowcount or 0)
    return added


def _seed_resources(conn: "Connection", tenant_id: str) -> int:
    """写入一个人工洗（GROOMING）+ 一个自助洗（SELF_SERVICE）资源（幂等）。"""
    rows = [
        {
            "resource_id": GROOMING_RESOURCE_ID,
            "tenant_id": tenant_id,
            "name": "人工洗",
            "service_type": ServiceType.GROOMING.value,
            "active": True,
        },
        {
            "resource_id": SELF_SERVICE_RESOURCE_ID,
            "tenant_id": tenant_id,
            "name": "自助洗",
            "service_type": ServiceType.SELF_SERVICE.value,
            "active": True,
        },
    ]
    added = 0
    for row in rows:
        stmt = (
            pg_insert(grooming_resources_table)
            .values(**row)
            .on_conflict_do_nothing(index_elements=["resource_id"])
        )
        added += int(conn.execute(stmt).rowcount or 0)
    return added


def _seed_demo_customer(
    conn: "Connection", tenant_id: str, demo_external_id: str | None
) -> int:
    """写入演示客户（幂等），可绑定企业微信外部联系人标识。"""
    stmt = (
        pg_insert(customers_table)
        .values(
            customer_id=DEMO_CUSTOMER_ID,
            tenant_id=tenant_id,
            name="演示客户",
            phone="00000000000",
            registered_at=datetime.now(),
            wecom_external_id=(demo_external_id or None),
        )
        .on_conflict_do_nothing(index_elements=["customer_id"])
    )
    added = int(conn.execute(stmt).rowcount or 0)
    # 已存在但需补绑定：当提供了 external_id 且当前记录未绑定时更新。
    if demo_external_id:
        existing = conn.execute(
            select(customers_table.c.wecom_external_id).where(
                customers_table.c.customer_id == DEMO_CUSTOMER_ID
            )
        ).first()
        if existing is not None and not existing.wecom_external_id:
            conn.execute(
                customers_table.update()
                .where(customers_table.c.customer_id == DEMO_CUSTOMER_ID)
                .values(wecom_external_id=demo_external_id)
            )
    return added


def _seed_demo_pet(conn: "Connection", tenant_id: str) -> int:
    """写入演示宠物（幂等），归属演示客户。"""
    stmt = (
        pg_insert(pets_table)
        .values(
            pet_id=DEMO_PET_ID,
            tenant_id=tenant_id,
            owner_id=DEMO_CUSTOMER_ID,
            species="dog",
            breed="金毛",
            birth_date=datetime(2022, 1, 1),
            weight_kg=25.0,
        )
        .on_conflict_do_nothing(index_elements=["pet_id"])
    )
    return int(conn.execute(stmt).rowcount or 0)


def seed_from_settings(
    settings: Settings | None = None, *, engine: "Engine | None" = None
) -> dict[str, int] | None:
    """按配置为默认租户执行种子（供入口脚本 / CLI 调用）。

    默认租户取 :attr:`Settings.resolved_default_tenant_id`（``PETOPS_DEFAULT_TENANT_ID``，
    缺省回退企业微信 ``corp_id``）。未配置默认租户时**跳过并返回 ``None``**（不误写）。
    演示数据是否写入由 ``PETOPS_SEED_DEMO`` 控制，绑定外部联系人由
    ``PETOPS_SEED_DEMO_EXTERNAL_ID`` 提供。

    Args:
        settings: 应用配置；缺省取进程缓存单例。
        engine: 可选注入的 Engine（便于测试）；缺省经 :func:`create_db_engine` 构造并在
            结束时释放。
    """
    cfg = settings or get_settings()
    tenant_id = cfg.resolved_default_tenant_id
    if not tenant_id:
        _LOG.warning("未配置 PETOPS_DEFAULT_TENANT_ID / 企业微信 corp_id，跳过种子。")
        return None

    seed_demo = _env_flag(SEED_DEMO_ENV)
    demo_external_id = os.getenv(DEMO_EXTERNAL_ID_ENV, "").strip() or None

    owns_engine = engine is None
    if engine is None:
        # 延迟导入，避免与迁移初始化的循环依赖。
        from app.db.init import create_db_engine

        engine = create_db_engine(cfg)
    try:
        return seed_single_store(
            engine,
            tenant_id,
            seed_demo=seed_demo,
            demo_external_id=demo_external_id,
        )
    finally:
        if owns_engine:
            engine.dispose()


def _env_flag(name: str) -> bool:
    """解析布尔环境变量（1/true/yes/on 视为真，大小写不敏感）。"""
    return os.getenv(name, "").strip().lower() in ("1", "true", "yes", "on")


def main() -> None:  # pragma: no cover - CLI 入口
    """CLI 入口：为默认租户执行幂等种子。"""
    logging.basicConfig(level=logging.INFO)
    result = seed_from_settings()
    if result is None:
        print("[seed] 未配置默认租户，已跳过。")
    else:
        print(f"[seed] 完成：{result}")


if __name__ == "__main__":  # pragma: no cover
    main()
