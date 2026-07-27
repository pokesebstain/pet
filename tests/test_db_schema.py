"""任务 2.1 数据库 Schema / RLS / 时序-向量扩展的单元测试。

覆盖：
- SQLAlchemy 元数据表结构（表齐全、tenant_id 存在、pgvector 向量列、可空共享列）。
- 迁移脚本存在且有序，包含扩展、超表、RLS 策略与向量索引的关键语句。
- 每张 RLS 表在迁移中启用/强制 RLS 且策略基于会话变量 app.current_tenant。
- knowledge_chunks 的可见性策略额外放行平台级共享（tenant_id IS NULL）。
- 初始化例程可在无运行数据库时导入、枚举与构建 Engine（不建立连接）。

这些测试不依赖运行中的 PostgreSQL：仅内省元数据、读取 SQL 文本并做静态断言。
"""

from __future__ import annotations

import pytest
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

import app.db as db
from app.db.metadata import EMBEDDING_DIM, SESSION_TENANT_VARIABLE

# --- 元数据结构 ------------------------------------------------------------

# 核心业务表（迁移 002 建表）。
_CORE_TABLES = {
    "tenants",
    "customers",
    "pets",
    "health_metrics",
    "domain_events",
    "knowledge_chunks",
    "feature_vectors",
    "subscriptions",
    "skus",
}

# 企业微信预约排期表（迁移 006 建表；任务 26.2）。
_SCHEDULING_TABLES = {
    "grooming_resources",
    "business_hours",
    "slot_capacities",
    "appointments",
}

_EXPECTED_TABLES = _CORE_TABLES | _SCHEDULING_TABLES


def test_all_expected_tables_defined() -> None:
    """元数据应定义设计文档中的全部持久化表。"""
    assert {t.name for t in db.ALL_TABLES} == _EXPECTED_TABLES
    assert set(db.metadata.tables) == _EXPECTED_TABLES


@pytest.mark.parametrize("table", db.RLS_TABLES, ids=lambda t: t.name)
def test_rls_tables_have_non_nullable_tenant_id(table) -> None:
    """每张 RLS 表都应有非空 tenant_id 列（RLS 隔离键）。"""
    assert "tenant_id" in table.c
    assert table.c.tenant_id.nullable is False


def test_knowledge_chunks_tenant_id_nullable_for_shared() -> None:
    """knowledge_chunks.tenant_id 可空，以表示平台级共享知识。"""
    assert db.knowledge_chunks.c.tenant_id.nullable is True


def test_knowledge_chunks_has_vector_embedding_column() -> None:
    """knowledge_chunks.embedding 应为 pgvector 向量列且维度一致。"""
    embedding = db.knowledge_chunks.c.embedding
    assert isinstance(embedding.type, Vector)
    assert embedding.type.dim == EMBEDDING_DIM
    assert embedding.nullable is False


def test_health_metrics_primary_key_includes_time_column() -> None:
    """TimescaleDB 超表要求分区列 ts 参与主键。"""
    pk_cols = {c.name for c in db.health_metrics.primary_key.columns}
    assert pk_cols == {"pet_id", "ts"}


def test_metadata_compiles_to_postgresql_ddl() -> None:
    """全部表应能编译为 PostgreSQL DDL（校验语法与类型有效）。"""
    dialect = postgresql.dialect()
    for table in db.ALL_TABLES:
        ddl = str(CreateTable(table).compile(dialect=dialect))
        assert f"CREATE TABLE {table.name}" in ddl


# --- 迁移脚本 --------------------------------------------------------------

def _read(name: str) -> str:
    path = db.MIGRATIONS_DIR / name
    return db.load_migration_sql(path)


# RLS 策略分布在两个迁移中：核心表在 004，预约排期表在 006。
_RLS_MIGRATIONS = ("004_rls_policies.sql", "006_appointments.sql")


def _rls_sql() -> str:
    """合并所有承载 RLS 策略的迁移脚本，便于跨文件断言。"""
    return "\n".join(_read(name) for name in _RLS_MIGRATIONS)


def test_migration_files_present_and_ordered() -> None:
    """迁移文件应齐全且按数字前缀有序。"""
    names = [p.name for p in db.iter_migration_files()]
    assert names == [
        "001_extensions.sql",
        "002_core_tables.sql",
        "003_timescale_hypertable.sql",
        "004_rls_policies.sql",
        "005_vector_index.sql",
        "006_appointments.sql",
    ]


def test_extensions_migration_enables_vector_and_timescaledb() -> None:
    """001 应启用 pgvector 与 TimescaleDB 扩展。"""
    sql = _read("001_extensions.sql").lower()
    assert "create extension if not exists vector" in sql
    assert "create extension if not exists timescaledb" in sql


def test_core_tables_migration_creates_all_tables() -> None:
    """002 应包含全部核心表的建表语句，且向量列维度与元数据一致。"""
    sql = _read("002_core_tables.sql").lower()
    for table in _CORE_TABLES:
        assert f"create table if not exists {table}" in sql
    assert f"vector({EMBEDDING_DIM})" in sql


def test_hypertable_migration_targets_health_metrics() -> None:
    """003 应将 health_metrics 按 ts 转换为超表。"""
    sql = _read("003_timescale_hypertable.sql").lower()
    assert "create_hypertable(" in sql
    assert "health_metrics" in sql
    assert "'ts'" in sql


@pytest.mark.parametrize("table", db.RLS_TABLES, ids=lambda t: t.name)
def test_rls_enabled_and_forced_for_each_tenant_table(table) -> None:
    """迁移应为每张 RLS 表启用并强制行级安全（核心表在 004，预约表在 006）。"""
    sql = _rls_sql().lower()
    assert f"alter table {table.name} enable row level security" in sql
    assert f"alter table {table.name} force row level security" in sql


@pytest.mark.parametrize("table", db.RLS_TABLES, ids=lambda t: t.name)
def test_rls_policy_filters_on_session_variable(table) -> None:
    """每张 RLS 表的策略应基于会话变量 app.current_tenant 过滤。"""
    sql = _rls_sql()
    # 定位该表的 CREATE POLICY 语句块，断言引用了会话变量与 tenant_id。
    marker = f"CREATE POLICY tenant_isolation ON {table.name}\n"
    if table.name == "knowledge_chunks":  # 共享表使用不同策略名，此处不匹配
        pytest.skip("knowledge_chunks 使用独立可见性策略")
    assert marker in sql
    block = sql.split(marker, 1)[1]
    assert f"current_setting('{SESSION_TENANT_VARIABLE}', TRUE)" in block


def test_all_rls_policies_reference_session_variable() -> None:
    """RLS 迁移中每条策略均引用 current_setting('app.current_tenant', TRUE)。"""
    sql = _rls_sql()
    # 仅统计真实策略语句（策略名以 tenant_ 前缀），避免误匹配注释中的 "CREATE POLICY"。
    policy_count = sql.count("CREATE POLICY tenant_")
    ref_count = sql.count(f"current_setting('{SESSION_TENANT_VARIABLE}', TRUE)")
    # 每条策略至少在 USING 与 WITH CHECK 各引用一次会话变量。
    assert policy_count == len(db.RLS_TABLES) + len(db.TENANT_SHARED_TABLES)
    assert ref_count >= policy_count


def test_knowledge_chunks_policy_allows_platform_shared() -> None:
    """knowledge_chunks 可见性策略应放行平台级共享（tenant_id IS NULL）。"""
    sql = _read("004_rls_policies.sql")
    assert "CREATE POLICY tenant_visibility ON knowledge_chunks" in sql
    block = sql.split("CREATE POLICY tenant_visibility ON knowledge_chunks", 1)[1]
    assert "tenant_id IS NULL" in block
    assert f"current_setting('{SESSION_TENANT_VARIABLE}', TRUE)" in block


# --- 预约排期表与防超卖约束（迁移 006；任务 26.2） -------------------------

@pytest.mark.parametrize("table", sorted(_SCHEDULING_TABLES))
def test_appointments_migration_creates_scheduling_tables(table) -> None:
    """006 应创建全部预约排期表。"""
    sql = _read("006_appointments.sql").lower()
    assert f"create table if not exists {table}" in sql


@pytest.mark.parametrize("table", sorted(_SCHEDULING_TABLES))
def test_scheduling_tables_have_non_nullable_tenant_id(table) -> None:
    """每张预约排期表都应有非空 tenant_id 列（RLS 隔离键）。"""
    t = db.metadata.tables[table]
    assert "tenant_id" in t.c
    assert t.c.tenant_id.nullable is False


def test_appointments_migration_enables_btree_gist_extension() -> None:
    """排他约束依赖 btree_gist 扩展以支持 text 列的 GiST 等值比较。"""
    sql = _read("006_appointments.sql").lower()
    assert "create extension if not exists btree_gist" in sql


def test_appointments_has_resource_overlap_exclusion_constraint() -> None:
    """appointments 应有防重叠排他约束：同一 resource_id 的有效预约时段不重叠。"""
    sql = _read("006_appointments.sql")
    assert "EXCLUDE USING gist" in sql
    # 关键要素：resource_id 等值 + tstzrange 时间重叠（&&），仅约束有效状态且已分配资源。
    assert "resource_id WITH =" in sql
    assert "tstzrange(start_at, end_at) WITH &&" in sql
    assert "status IN ('pending', 'confirmed')" in sql
    assert "resource_id IS NOT NULL" in sql


def test_slot_capacities_row_supports_select_for_update() -> None:
    """时段容量行以 (tenant_id, service_type, start_at) 为主键，供 SELECT … FOR UPDATE 加锁。"""
    slot = db.slot_capacities
    pk_cols = {c.name for c in slot.primary_key.columns}
    assert pk_cols == {"tenant_id", "service_type", "start_at"}
    assert "capacity" in slot.c


@pytest.mark.parametrize("table", sorted(_SCHEDULING_TABLES))
def test_scheduling_tables_enable_and_force_rls(table) -> None:
    """006 应为每张预约排期表启用并强制 RLS，且策略基于会话变量。"""
    sql = _read("006_appointments.sql")
    lowered = sql.lower()
    assert f"alter table {table} enable row level security" in lowered
    assert f"alter table {table} force row level security" in lowered
    marker = f"CREATE POLICY tenant_isolation ON {table}\n"
    assert marker in sql
    block = sql.split(marker, 1)[1]
    assert f"current_setting('{SESSION_TENANT_VARIABLE}', TRUE)" in block


def test_vector_index_migration_targets_embedding() -> None:
    """005 应为 knowledge_chunks.embedding 创建向量检索索引。"""
    sql = _read("005_vector_index.sql").lower()
    assert "knowledge_chunks" in sql
    assert "embedding" in sql
    assert "using ivfflat" in sql


# --- 初始化例程（无需运行数据库） -----------------------------------------

def test_load_migration_sql_reads_non_empty() -> None:
    """每个迁移脚本均可读取且非空。"""
    for path in db.iter_migration_files():
        assert db.load_migration_sql(path).strip()


def test_create_db_engine_does_not_connect() -> None:
    """构建 Engine 不应立即建立连接，且 DSN 指向 PostgreSQL。"""
    engine = db.create_db_engine()
    try:
        assert engine.url.drivername.startswith("postgresql")
    finally:
        engine.dispose()
