"""数据库层：Schema 定义、迁移脚本与初始化逻辑。

对应设计文档 "Data Models" 与 "Architecture"（PostgreSQL + pgvector + TimescaleDB）。

本包提供三部分能力：

- ``metadata``   : 基于 SQLAlchemy 2.0 的 ``MetaData`` 与 ``Table`` 定义，供程序化
  访问、类型化与测试内省使用（``knowledge_chunks`` 使用 pgvector 的 ``Vector`` 列）。
- ``migrations/``: 权威的原生 SQL 迁移脚本（扩展、建表、TimescaleDB 超表、行级安全
  策略、索引），按文件名前缀顺序执行，是部署时的真相来源。
- ``init``       : 迁移执行与初始化例程（构建 Engine、按序运行 SQL 脚本）。

多租户行级安全（RLS）基于会话变量 ``app.current_tenant``，由 ``app.core`` 中的
RLS 上下文管理器（任务 2.2）负责注入。所有携带 ``tenant_id`` 的表均启用并强制 RLS，
以在数据库层杜绝跨租户数据泄露（Requirements 5.1、5.2）。
"""

from app.db.metadata import (
    ALL_TABLES,
    RLS_TABLES,
    SESSION_TENANT_VARIABLE,
    TENANT_SHARED_TABLES,
    appointments,
    business_hours,
    customers,
    domain_events,
    feature_vectors,
    grooming_resources,
    health_metrics,
    knowledge_chunks,
    metadata,
    pets,
    skus,
    slot_capacities,
    subscriptions,
    tenants,
)
from app.db.init import (
    MIGRATIONS_DIR,
    create_db_engine,
    init_database,
    iter_migration_files,
    load_migration_sql,
    run_migrations,
)
from app.db.session import set_tenant_context, tenant_session

__all__ = [
    # metadata
    "metadata",
    "ALL_TABLES",
    "RLS_TABLES",
    "TENANT_SHARED_TABLES",
    "SESSION_TENANT_VARIABLE",
    "tenants",
    "customers",
    "pets",
    "health_metrics",
    "domain_events",
    "knowledge_chunks",
    "feature_vectors",
    "subscriptions",
    "skus",
    # 企业微信预约排期（任务 26.2）
    "grooming_resources",
    "business_hours",
    "slot_capacities",
    "appointments",
    # init / migrations
    "MIGRATIONS_DIR",
    "iter_migration_files",
    "load_migration_sql",
    "create_db_engine",
    "run_migrations",
    "init_database",
    # RLS 会话上下文（任务 2.2）
    "tenant_session",
    "set_tenant_context",
]
