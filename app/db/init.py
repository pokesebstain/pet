"""数据库初始化与迁移执行例程。

按文件名前缀顺序执行 ``app/db/migrations`` 下的原生 SQL 脚本，完成扩展启用、建表、
TimescaleDB 超表转换、行级安全（RLS）策略与向量索引创建。

设计要点：
- 所有函数惰性构建连接，不在模块导入时连接数据库；无运行中的数据库亦可导入本模块。
- 迁移脚本本身保证幂等（IF NOT EXISTS / DROP POLICY IF EXISTS 等），可重复执行。
- 使用 ``exec_driver_sql`` 将整段脚本交由 psycopg 执行，以支持单文件内多条 DDL 语句。

用法::

    from app.db import init_database
    init_database()            # 使用默认配置
    # 或
    from app.db import create_db_engine, run_migrations
    engine = create_db_engine()
    run_migrations(engine)
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import create_engine, event

from app.core.config import Settings, get_settings

if TYPE_CHECKING:  # 仅用于类型标注，避免运行时强依赖。
    from sqlalchemy.engine import Engine

# 迁移脚本目录（与本模块同级的 migrations/）。
MIGRATIONS_DIR = Path(__file__).parent / "migrations"

#: 门店本地时区（单门店部署，暂不支持跨时区多门店）。
#:
#: 背景：应用层大量"裸时间"（不带 tzinfo 的 datetime）在语义上均指"门店本地时间"
#: （如企业微信 LLM 从"周六下午4点"抽取出的 requested_start、排期引擎的营业时间
#: 枚举），但写入 PostgreSQL 的 ``TIMESTAMPTZ`` 列时，若数据库会话时区不是
#: ``Asia/Shanghai``，驱动会按会话时区（通常是 UTC）解释这些裸时间——导致"15点"被
#: 当成"UTC 15点"存入，实际比真实北京时间晚 8 小时，前端按浏览器时区（+8）显示时
#: 进一步雪上加霜（表现为预约时间整体偏移，如 15 点显示成 23 点甚至跨天）。
#: 在每个新建的物理连接上设置会话时区，使裸时间被数据库正确解释为北京时间，且
#: 读出时序列化的 ISO8601 字符串携带正确的 ``+08:00`` 偏移，无需改动任何业务代码
#: 里"裸时间即门店本地时间"的既有约定。
STORE_TIMEZONE = "Asia/Shanghai"


def iter_migration_files(migrations_dir: Path | None = None) -> list[Path]:
    """返回按文件名升序排列的迁移 SQL 文件列表。

    文件名以数字前缀（如 ``001_``、``002_``）编号，确保执行顺序确定。
    """
    directory = migrations_dir or MIGRATIONS_DIR
    return sorted(directory.glob("*.sql"))


def load_migration_sql(path: Path) -> str:
    """读取单个迁移脚本内容。"""
    return path.read_text(encoding="utf-8")


def create_db_engine(settings: Settings | None = None) -> "Engine":
    """基于应用配置构建 SQLAlchemy Engine。

    使用配置中的连接池参数；``future=True`` 采用 SQLAlchemy 2.0 风格。
    调用本函数不会立即建立连接（连接在首次使用时惰性创建）。
    """
    cfg = (settings or get_settings()).database
    engine = create_engine(
        cfg.dsn,
        pool_size=cfg.pool_size,
        max_overflow=cfg.max_overflow,
        pool_pre_ping=True,
        future=True,
    )

    @event.listens_for(engine, "connect")
    def _set_store_timezone(dbapi_connection, connection_record) -> None:  # noqa: ANN001
        """每个新建的物理连接上设置会话时区为门店本地时区（见 STORE_TIMEZONE 注释）。"""
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute(f"SET TIME ZONE '{STORE_TIMEZONE}'")
        finally:
            cursor.close()

    return engine


def run_migrations(
    engine: "Engine", migrations_dir: Path | None = None
) -> list[str]:
    """按顺序执行全部迁移脚本。

    每个脚本在独立事务中执行（``engine.begin()``），任一脚本失败即回滚该脚本。
    返回已成功执行的脚本文件名列表，便于日志与测试断言。
    """
    executed: list[str] = []
    for sql_file in iter_migration_files(migrations_dir):
        sql = load_migration_sql(sql_file)
        if not sql.strip():
            continue
        with engine.begin() as conn:
            # exec_driver_sql 直接把整段脚本交给 psycopg，支持单文件多语句 DDL。
            conn.exec_driver_sql(sql)
        executed.append(sql_file.name)
    return executed


def init_database(settings: Settings | None = None) -> list[str]:
    """初始化数据库：构建 Engine 并执行全部迁移。

    返回已执行的迁移脚本名列表。适用于本地/测试环境的一键初始化；生产环境建议由
    专门的迁移流水线调用 :func:`run_migrations`。
    """
    engine = create_db_engine(settings)
    try:
        return run_migrations(engine)
    finally:
        engine.dispose()
