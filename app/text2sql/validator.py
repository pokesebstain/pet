"""SQL 三重校验（任务 9.2，Requirements 2.2、2.3、20.2，Correctness Property 11）。

对应设计文档：
- Components / 组件 3「统一工具层」中的 ``db_query_tool``（Text2SQL）能力的**校验**子步骤；
- Error Handling 表「Text2SQL 生成非法/越权 SQL」一行；
- Correctness Property 11「Text2SQL 安全校验」。

职责边界（重要）：
- 本模块**只**负责对上游（任务 9.1）生成的**候选 SQL 字符串**执行三重静态校验，
  三项全部通过才视为可执行；任一失败即判定为拒绝，且**不触碰数据库、不产生任何变更**。
- 实际执行、超时终止、结果截断与降级回退由 :mod:`app.text2sql.executor` 负责。

三重校验（Requirement 2.2）：
1. **只读约束**（read_only）：仅允许单条只读查询（``SELECT`` / ``UNION`` 等集合查询，
   含 ``WITH`` CTE）；拒绝任何写操作（INSERT/UPDATE/DELETE/MERGE）、DDL
   （CREATE/DROP/ALTER/TRUNCATE）、会话 / 权限命令（SET/GRANT 等）、多语句与不可解析语句。
2. **白名单**（whitelist）：仅允许引用固定 Schema（:mod:`app.db.metadata`）内的表与列；
   ``WITH`` 定义的 CTE 名与查询内声明的列别名视为合法引用。
3. **RLS**（rls）：确保存在有效的租户上下文（非空 ``tenant_id``），从而查询在数据库
   行级安全策略下按租户过滤执行（Requirements 2.2、5.4）。真正的逐行过滤由 PostgreSQL
   RLS 强制。

实现选择：采用 ``sqlglot`` 进行健壮的方言感知解析（PostgreSQL），基于抽象语法树（AST）
判定语句类型与引用的表 / 列，避免脆弱的字符串 / 正则匹配被大小写、注释、空白或子查询
绕过。``sqlglot`` 版本已在 ``pyproject.toml`` 固定。

可测试性：本模块为**纯函数**静态校验，不依赖数据库连接，可用任意 SQL 字符串直接测试。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from app.db.metadata import ALL_TABLES
from app.text2sql.errors import (
    SQLNotReadOnlyError,
    SQLRLSValidationError,
    SQLValidationError,
    SQLWhitelistError,
)

__all__ = [
    "SQL_DIALECT",
    "ALLOWED_TABLE_NAMES",
    "ALLOWED_COLUMN_NAMES",
    "CheckStatus",
    "ValidationReport",
    "check_read_only",
    "check_whitelist",
    "check_rls",
    "validate_sql",
]

#: 解析 / 校验使用的 SQL 方言（与数据层 PostgreSQL 一致）。
SQL_DIALECT = "postgres"

#: 白名单允许引用的表名集合（源自固定 Schema 单一真相 :mod:`app.db.metadata`）。
ALLOWED_TABLE_NAMES: frozenset[str] = frozenset(table.name for table in ALL_TABLES)

#: 白名单允许引用的列名集合（跨全部业务表并集）。
ALLOWED_COLUMN_NAMES: frozenset[str] = frozenset(
    column.name for table in ALL_TABLES for column in table.columns
)

# 只读约束禁止出现的顶层 / 嵌套表达式类型（写操作 / DDL / 会话与权限命令等）。
# 采用类名字符串集合以兼容不同 sqlglot 版本对个别节点的命名差异。
_FORBIDDEN_EXPR_NAMES: frozenset[str] = frozenset(
    {
        "Insert",
        "Update",
        "Delete",
        "Merge",
        "Create",
        "Drop",
        "Alter",
        "AlterTable",
        "TruncateTable",
        "Truncate",
        "Command",  # sqlglot 对 SET / VACUUM / 未识别语句的回退类型
        "Set",
        "SetItem",
        "Grant",
        "Revoke",
        "Copy",
        "Call",
        "Use",
        "Analyze",
        "Attach",
        "Detach",
        "Pragma",
    }
)

# 只读查询允许的根表达式类型（含集合运算；``WITH ... SELECT`` 解析为带 CTE 的 Select）。
_READONLY_ROOT_TYPES: tuple[type[exp.Expression], ...] = (
    exp.Select,
    exp.Union,
    exp.Intersect,
    exp.Except,
    exp.Subquery,
)


class CheckStatus(str, Enum):
    """单项校验状态。"""

    PASSED = "passed"
    FAILED = "failed"


@dataclass(frozen=True)
class ValidationReport:
    """三重校验的汇总报告。

    Attributes:
        ok: 三项校验是否**全部**通过（仅当全部通过才允许执行）。
        checks_passed: 已通过的校验类别有序元组（``read_only`` / ``whitelist`` / ``rls``）。
        failed_check: 首个失败的校验类别；全部通过时为 ``None``。
        reason: 失败原因说明（用于生成澄清提示）；全部通过时为 ``None``。
    """

    ok: bool
    checks_passed: tuple[str, ...] = ()
    failed_check: str | None = None
    reason: str | None = None


# --- 内部辅助 ---------------------------------------------------------------


def _parse_single_statement(sql: str) -> exp.Expression:
    """将 SQL 解析为**单条**语句表达式，否则视为只读校验失败。

    Raises:
        SQLNotReadOnlyError: SQL 为空、无法解析或包含多条语句时。
    """
    if not sql or not sql.strip():
        raise SQLNotReadOnlyError("候选 SQL 为空，拒绝执行。")
    try:
        statements = [s for s in sqlglot.parse(sql, read=SQL_DIALECT) if s is not None]
    except SqlglotError as exc:  # 解析失败：无法证明其只读 / 合法，拒绝。
        raise SQLNotReadOnlyError(f"候选 SQL 无法解析，拒绝执行：{exc}") from exc
    if len(statements) == 0:
        raise SQLNotReadOnlyError("候选 SQL 未包含任何有效语句，拒绝执行。")
    if len(statements) > 1:
        raise SQLNotReadOnlyError(
            f"候选 SQL 包含 {len(statements)} 条语句，仅允许单条只读查询。"
        )
    return statements[0]


# --- 单项校验 ---------------------------------------------------------------


def check_read_only(sql: str) -> exp.Expression:
    """只读约束校验：仅允许单条只读查询。

    拒绝写操作 / DDL / 会话与权限命令 / 多语句 / 不可解析语句（Requirement 2.3）。

    Args:
        sql: 待校验的候选 SQL 字符串。

    Returns:
        解析得到的语句 AST（供白名单校验复用，避免重复解析）。

    Raises:
        SQLNotReadOnlyError: 违反只读约束时。
    """
    statement = _parse_single_statement(sql)

    # 根表达式必须是只读查询类型。
    if not isinstance(statement, _READONLY_ROOT_TYPES):
        raise SQLNotReadOnlyError(
            f"仅允许只读 SELECT 查询，检测到不允许的语句类型：{type(statement).__name__}。"
        )

    # 深度扫描 AST，任一节点命中禁止类型即拒绝（覆盖 CTE / 子查询内的写操作）。
    for node in statement.walk():
        node_name = type(node).__name__
        if node_name in _FORBIDDEN_EXPR_NAMES:
            raise SQLNotReadOnlyError(
                f"候选 SQL 含不允许的操作（{node_name}），仅允许只读查询。"
            )

    # SELECT ... INTO 会创建新表，属于写操作，单独拦截。
    if statement.args.get("into") is not None:
        raise SQLNotReadOnlyError("候选 SQL 含 SELECT ... INTO 写操作，拒绝执行。")

    return statement


def _cte_names(statement: exp.Expression) -> set[str]:
    """收集查询内 ``WITH`` 定义的 CTE 名（视为合法的表引用别名）。"""
    names: set[str] = set()
    for cte in statement.find_all(exp.CTE):
        alias = cte.alias
        if alias:
            names.add(alias)
    return names


def _alias_names(statement: exp.Expression) -> set[str]:
    """收集查询内声明的列 / 表别名（视为合法的列引用，如 ``SELECT x AS y ... ORDER BY y``）。"""
    names: set[str] = set()
    for alias in statement.find_all(exp.Alias):
        name = alias.alias
        if name:
            names.add(name)
    for table_alias in statement.find_all(exp.TableAlias):
        name = table_alias.name
        if name:
            names.add(name)
    return names


def check_whitelist(statement: exp.Expression) -> None:
    """白名单校验：仅允许引用固定 Schema 内的表与列。

    ``WITH`` 定义的 CTE 名与查询内声明的别名视为合法引用（Requirement 2.3）。

    Args:
        statement: :func:`check_read_only` 解析得到的语句 AST。

    Raises:
        SQLWhitelistError: 引用了白名单外的表或列时。
    """
    cte_names = _cte_names(statement)
    allowed_tables = ALLOWED_TABLE_NAMES | cte_names

    for table in statement.find_all(exp.Table):
        name = table.name
        if name and name not in allowed_tables:
            raise SQLWhitelistError(
                f"候选 SQL 引用了白名单外的表 {name!r}，拒绝执行。"
            )

    allowed_columns = ALLOWED_COLUMN_NAMES | cte_names | _alias_names(statement)
    for column in statement.find_all(exp.Column):
        name = column.name
        if name and name not in allowed_columns:
            raise SQLWhitelistError(
                f"候选 SQL 引用了白名单外的列 {name!r}，拒绝执行。"
            )


def check_rls(tenant_id: object) -> None:
    """RLS 校验：确保存在有效的租户上下文（非空 ``tenant_id``）。

    实际逐行过滤由 PostgreSQL 行级安全策略在执行时强制（经
    :func:`app.db.session.set_tenant_context` 注入 ``app.current_tenant``）。本校验
    确保执行前存在有效租户上下文，缺失即拒绝（Requirements 2.2、5.4）。

    Args:
        tenant_id: 请求上下文租户标识。

    Raises:
        SQLRLSValidationError: ``tenant_id`` 缺失或为空（None / 非字符串 / 空串 / 纯空白）时。
    """
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise SQLRLSValidationError(
            "缺少有效的租户上下文：无法在 RLS 范围内执行该 SQL。"
        )


# --- 组合校验 ---------------------------------------------------------------


def validate_sql(sql: str, tenant_id: object) -> ValidationReport:
    """按 只读 → 白名单 → RLS 顺序执行三重校验并返回汇总报告。

    任一校验失败即短路返回失败报告（记录失败类别与原因），三项全部通过才返回
    ``ok=True``。本函数**不抛异常、不执行任何 SQL**，供执行层据报告决定执行或拒绝 +
    回退（Requirements 2.2、2.3、20.2，Correctness Property 11）。

    Args:
        sql: 候选 SQL 字符串。
        tenant_id: 请求上下文租户标识。

    Returns:
        ValidationReport: 三重校验的汇总结果。
    """
    passed: list[str] = []
    try:
        statement = check_read_only(sql)
        passed.append("read_only")

        check_whitelist(statement)
        passed.append("whitelist")

        check_rls(tenant_id)
        passed.append("rls")
    except SQLValidationError as exc:
        return ValidationReport(
            ok=False,
            checks_passed=tuple(passed),
            failed_check=exc.check,
            reason=str(exc),
        )

    return ValidationReport(ok=True, checks_passed=tuple(passed))
