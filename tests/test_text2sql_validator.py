"""任务 9.2 单元测试：SQL 三重校验（Requirements 2.2、2.3、20.2，Property 11）。

纯函数静态校验，不依赖数据库。覆盖：
- 只读约束：SELECT / WITH / UNION 通过；INSERT/UPDATE/DELETE/DDL/命令/多语句/不可解析拒绝。
- 白名单：仅允许固定 Schema 内的表 / 列；CTE 名与别名放行；越界表 / 列拒绝。
- RLS：有效 tenant_id 通过；缺失 / 空拒绝。
- 组合校验按顺序短路并汇总报告。
"""

from __future__ import annotations

import pytest

from app.text2sql.errors import (
    SQLNotReadOnlyError,
    SQLRLSValidationError,
    SQLWhitelistError,
)
from app.text2sql.validator import (
    check_read_only,
    check_rls,
    check_whitelist,
    validate_sql,
)


# --- 只读约束 --------------------------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT name, phone FROM customers",
        "SELECT customer_id FROM customers WHERE churn_score > 0.6 ORDER BY ltv DESC",
        "SELECT name FROM customers UNION SELECT name FROM customers",
        "WITH hot AS (SELECT customer_id FROM customers) SELECT customer_id FROM hot",
        "SELECT count(*) FROM skus WHERE current_stock <= 0",
    ],
)
def test_read_only_accepts_select_queries(sql: str) -> None:
    # 不抛异常即视为通过（返回解析后的 AST）。
    assert check_read_only(sql) is not None


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO customers (customer_id) VALUES ('c1')",
        "UPDATE customers SET name = 'x'",
        "DELETE FROM customers",
        "DROP TABLE customers",
        "CREATE TABLE t (a int)",
        "ALTER TABLE customers ADD COLUMN x int",
        "TRUNCATE TABLE customers",
        "GRANT SELECT ON customers TO evil",
        "SET ROLE admin",
        "SELECT name FROM customers; DROP TABLE customers",  # 多语句
        "WITH x AS (DELETE FROM customers RETURNING customer_id) SELECT * FROM x",
        "",  # 空
        "not a sql at all @@@",  # 不可解析
    ],
)
def test_read_only_rejects_writes_ddl_and_multistatement(sql: str) -> None:
    with pytest.raises(SQLNotReadOnlyError):
        check_read_only(sql)


# --- 白名单 ----------------------------------------------------------------


def test_whitelist_accepts_known_tables_and_columns() -> None:
    statement = check_read_only(
        "SELECT customer_id, name, churn_score FROM customers"
    )
    check_whitelist(statement)  # 不抛异常


def test_whitelist_accepts_cte_and_alias_names() -> None:
    statement = check_read_only(
        "WITH hot AS (SELECT customer_id AS cid FROM customers) "
        "SELECT cid FROM hot ORDER BY cid"
    )
    check_whitelist(statement)  # CTE 名 hot 与列别名 cid 均放行


def test_whitelist_rejects_unknown_table() -> None:
    statement = check_read_only("SELECT * FROM secret_admin_table")
    with pytest.raises(SQLWhitelistError):
        check_whitelist(statement)


def test_whitelist_rejects_unknown_column() -> None:
    statement = check_read_only("SELECT password_hash FROM customers")
    with pytest.raises(SQLWhitelistError):
        check_whitelist(statement)


def test_whitelist_blocks_system_catalog_access() -> None:
    # 访问系统目录表以试图越权：不在白名单内，被拦截。
    statement = check_read_only("SELECT tablename FROM pg_tables")
    with pytest.raises(SQLWhitelistError):
        check_whitelist(statement)


# --- RLS -------------------------------------------------------------------


def test_rls_accepts_valid_tenant() -> None:
    check_rls("tenant-a")  # 不抛异常


@pytest.mark.parametrize("bad", [None, "", "   ", 123, object()])
def test_rls_rejects_missing_tenant(bad: object) -> None:
    with pytest.raises(SQLRLSValidationError):
        check_rls(bad)


# --- 组合校验 --------------------------------------------------------------


def test_validate_sql_all_pass() -> None:
    report = validate_sql("SELECT name FROM customers", "tenant-a")
    assert report.ok is True
    assert report.checks_passed == ("read_only", "whitelist", "rls")
    assert report.failed_check is None


def test_validate_sql_short_circuits_on_read_only() -> None:
    report = validate_sql("DELETE FROM customers", "tenant-a")
    assert report.ok is False
    assert report.failed_check == "read_only"
    assert report.checks_passed == ()
    assert report.reason


def test_validate_sql_fails_whitelist_after_read_only() -> None:
    report = validate_sql("SELECT nope FROM customers", "tenant-a")
    assert report.ok is False
    assert report.failed_check == "whitelist"
    assert report.checks_passed == ("read_only",)


def test_validate_sql_fails_rls_when_tenant_missing() -> None:
    report = validate_sql("SELECT name FROM customers", "")
    assert report.ok is False
    assert report.failed_check == "rls"
    assert report.checks_passed == ("read_only", "whitelist")
