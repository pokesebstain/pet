"""SQLAlchemy 2.0 Schema 元数据定义（对应设计文档 Data Models）。

集中定义所有持久化表的 ``MetaData`` 与 ``Table`` 结构，作为程序化访问与测试内省的
类型化真相来源。原生 SQL 迁移脚本（``app/db/migrations``）与本模块保持一致，但由后者
负责部署时执行扩展、TimescaleDB 超表与行级安全（RLS）策略等 SQLAlchemy 不便表达的部分。

多租户约定：
- 除 ``knowledge_chunks`` 外，所有携带 ``tenant_id`` 的表均要求 ``tenant_id`` 非空，
  并启用/强制 RLS，策略基于会话变量 ``app.current_tenant``。
- ``knowledge_chunks`` 的 ``tenant_id`` 可为空，表示平台级共享知识，对所有租户可见
  （Requirements 16.1、16.3）。
"""

from __future__ import annotations

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    MetaData,
    Numeric,
    PrimaryKeyConstraint,
    String,
    Table,
    Text,
    Time,
)

# 知识片段 embedding 向量维度（云端 LLM 文本向量，默认 1024 维；如更换向量模型需同步迁移）。
EMBEDDING_DIM = 1024

# 驱动 RLS 策略的 PostgreSQL 会话变量名。RLS 上下文管理器（任务 2.2）通过
# ``SET LOCAL app.current_tenant = '<tenant_id>'`` 注入当前租户。
SESSION_TENANT_VARIABLE = "app.current_tenant"

# 统一命名约定，便于 Alembic 等工具生成稳定的约束名。
_NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "pk": "pk_%(table_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s",
}

metadata = MetaData(naming_convention=_NAMING_CONVENTION)


# --- 4.1 多租户与核心实体 -------------------------------------------------

tenants = Table(
    "tenants",
    metadata,
    Column("tenant_id", String, primary_key=True),
    Column("store_name", String, nullable=False),
    Column("plan_tier", String, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

customers = Table(
    "customers",
    metadata,
    Column("customer_id", String, primary_key=True),
    Column("tenant_id", String, nullable=False, index=True),
    Column("name", String, nullable=False),
    Column("phone", String, nullable=False),
    Column("registered_at", DateTime(timezone=True), nullable=False),
    Column("ltv", Float, nullable=True),
    Column("churn_score", Float, nullable=True),
    Column("segment", String, nullable=True),
)

pets = Table(
    "pets",
    metadata,
    Column("pet_id", String, primary_key=True),
    Column("tenant_id", String, nullable=False, index=True),
    Column("owner_id", String, nullable=False, index=True),
    Column("species", String, nullable=False),
    Column("breed", String, nullable=False),
    Column("birth_date", DateTime(timezone=True), nullable=False),
    Column("weight_kg", Float, nullable=False),
    Column("life_stage", String, nullable=True),
)


# --- 4.2 时序 / 事件 / 向量 ------------------------------------------------

# TimescaleDB 超表：主键包含时间列 ``ts``（超表要求分区列参与唯一约束）。
health_metrics = Table(
    "health_metrics",
    metadata,
    Column("pet_id", String, nullable=False),
    Column("tenant_id", String, nullable=False, index=True),
    Column("ts", DateTime(timezone=True), nullable=False),
    Column("weight_kg", Float, nullable=False),
    Column("activity_minutes", Float, nullable=False),
    Column("food_intake_g", Float, nullable=False),
    PrimaryKeyConstraint("pet_id", "ts", name="pk_health_metrics"),
)

domain_events = Table(
    "domain_events",
    metadata,
    Column("event_id", String, primary_key=True),
    Column("tenant_id", String, nullable=False, index=True),
    Column("event_type", String, nullable=False, index=True),
    Column("payload", JSON, nullable=False),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
)

# pgvector 知识片段：``tenant_id`` 可空表示平台级共享知识。
knowledge_chunks = Table(
    "knowledge_chunks",
    metadata,
    Column("chunk_id", String, primary_key=True),
    Column("tenant_id", String, nullable=True, index=True),
    Column("content", Text, nullable=False),
    Column("embedding", Vector(EMBEDDING_DIM), nullable=False),
    Column("source_type", String, nullable=False),
)

feature_vectors = Table(
    "feature_vectors",
    metadata,
    Column("entity_id", String, nullable=False),
    Column("tenant_id", String, nullable=False, index=True),
    Column("feature_group", String, nullable=False),
    Column("features", JSON, nullable=False),
    Column("computed_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint(
        "entity_id", "feature_group", name="pk_feature_vectors"
    ),
)


# --- 4.3 订阅与供应链 ------------------------------------------------------

subscriptions = Table(
    "subscriptions",
    metadata,
    Column("subscription_id", String, primary_key=True),
    Column("tenant_id", String, nullable=False, index=True),
    Column("customer_id", String, nullable=False, index=True),
    Column("plan_id", String, nullable=False),
    Column("status", String, nullable=False),
    Column("next_billing_at", DateTime(timezone=True), nullable=False),
)

skus = Table(
    "skus",
    metadata,
    Column("sku_id", String, primary_key=True),
    Column("tenant_id", String, nullable=False, index=True),
    Column("name", String, nullable=False),
    Column("category", String, nullable=False),
    Column("unit_cost", Numeric(18, 2), nullable=False),
    Column("current_stock", Float, nullable=False),
    Column("lead_time_days", Float, nullable=False),
)


# --- 4.4 企业微信预约排期（对应设计 14.4 / 14.7.3；任务 26.2） -----------------
#
# 说明：预约模块的租户隔离键 ``tenant_id`` 均非空并启用/强制 RLS（策略见迁移 006）。
# 防超卖采用"双保险"（Requirements 22.2、24.1）：
#   1) ``slot_capacities`` 为每个 (tenant_id, service_type, start_at) 维护一行容量记录，
#      作为 ``book_appointment`` 事务内 ``SELECT … FOR UPDATE`` 的加锁对象，串行化同槽并发。
#   2) ``appointments`` 上的 PostgreSQL 排他约束（EXCLUDE USING gist）阻止同一 ``resource_id``
#      的处于 PENDING/CONFIRMED 状态预约在时间上重叠（见迁移 006，需 btree_gist 扩展）。
# 排他约束与 tstzrange 重叠语义为 SQLAlchemy 不便表达的部分，统一由迁移 006 负责。

grooming_resources = Table(
    "grooming_resources",
    metadata,
    Column("resource_id", String, primary_key=True),
    Column("tenant_id", String, nullable=False, index=True),
    Column("name", String, nullable=False),
    Column("service_type", String, nullable=False),
    Column("active", Boolean, nullable=False, server_default="true"),
)

business_hours = Table(
    "business_hours",
    metadata,
    Column("tenant_id", String, nullable=False, index=True),
    Column("weekday", Integer, nullable=False),  # 0=周一 … 6=周日
    Column("open_time", Time, nullable=False),
    Column("close_time", Time, nullable=False),
    PrimaryKeyConstraint("tenant_id", "weekday", name="pk_business_hours"),
)

# 时段容量行：供 book_appointment 事务内 SELECT … FOR UPDATE 加锁串行化并发预约。
slot_capacities = Table(
    "slot_capacities",
    metadata,
    Column("tenant_id", String, nullable=False, index=True),
    Column("service_type", String, nullable=False),
    Column("start_at", DateTime(timezone=True), nullable=False),
    Column("end_at", DateTime(timezone=True), nullable=False),
    Column("capacity", Integer, nullable=False),
    PrimaryKeyConstraint(
        "tenant_id", "service_type", "start_at", name="pk_slot_capacities"
    ),
)

appointments = Table(
    "appointments",
    metadata,
    Column("appointment_id", String, primary_key=True),
    Column("tenant_id", String, nullable=False, index=True),
    Column("customer_id", String, nullable=False, index=True),
    Column("pet_id", String, nullable=False, index=True),
    Column("service_type", String, nullable=False),
    Column("start_at", DateTime(timezone=True), nullable=False),
    Column("end_at", DateTime(timezone=True), nullable=False),
    Column("resource_id", String, nullable=True),
    Column("status", String, nullable=False),
    Column("source", String, nullable=False, server_default="wecom"),
    Column("created_at", DateTime(timezone=True), nullable=False),
)


# 全部表（含无 tenant_id 的 tenants 本体）。
ALL_TABLES: tuple[Table, ...] = (
    tenants,
    customers,
    pets,
    health_metrics,
    domain_events,
    knowledge_chunks,
    feature_vectors,
    subscriptions,
    skus,
    grooming_resources,
    business_hours,
    slot_capacities,
    appointments,
)

# 需启用 RLS 的租户数据表：策略要求 ``tenant_id = current_setting('app.current_tenant')``。
# 说明：``tenants`` 表本身以 ``tenant_id`` 为主键，同样启用 RLS 以限制每个租户仅见自身记录。
RLS_TABLES: tuple[Table, ...] = (
    tenants,
    customers,
    pets,
    health_metrics,
    domain_events,
    feature_vectors,
    subscriptions,
    skus,
    grooming_resources,
    business_hours,
    slot_capacities,
    appointments,
)

# 允许平台级共享（tenant_id 为空）可见的表：RLS 策略额外放行 ``tenant_id IS NULL``。
TENANT_SHARED_TABLES: tuple[Table, ...] = (knowledge_chunks,)
