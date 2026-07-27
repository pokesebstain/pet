"""任务 9.2 单元测试：SQL 执行控制（Requirements 2.2–2.7、20.2、20.5，Property 11）。

使用伪执行器（无真实数据库），覆盖：
- 三重校验通过才执行，返回受控结果。
- 校验失败拒绝：不执行、无数据库变更、返回澄清并回退受限模板查询（命中模板 / 重述）。
- 执行超过 30 秒预算被终止：返回超时结果，无数据库变更。
- 结果 >1000 行截断并打标（复用工具层）。
- 逐条租户校验（越界记录阻断）。
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.core.errors import TenantIsolationError
from app.llm.client import RestrictedTemplate, RestrictedTemplateQuery
from app.text2sql.errors import SQLExecutionTimeoutError
from app.text2sql.executor import (
    EXECUTION_TIMEOUT_SECONDS,
    ExecutionOutcome,
    FallbackKind,
    SafeSQLExecutor,
)
from app.tools.base import MAX_RESULT_ROWS


# --- 测试替身 --------------------------------------------------------------


@dataclass
class _Row:
    tenant_id: str
    value: int = 0


class _RecordingRunner:
    """记录调用并返回预设行的伪执行器。"""

    def __init__(self, rows: list[_Row]) -> None:
        self._rows = rows
        self.calls: list[tuple[str, str, float]] = []

    def __call__(self, tenant_id, sql, *, timeout_seconds):
        self.calls.append((tenant_id, sql, timeout_seconds))
        return list(self._rows)


class _TimeoutRunner:
    """始终抛出执行超时的伪执行器。"""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, tenant_id, sql, *, timeout_seconds):
        self.calls += 1
        raise SQLExecutionTimeoutError("模拟数据库语句超时")


class _NeverCalledRunner:
    """一旦被调用即失败（用于验证拒绝路径不触碰数据库）。"""

    def __call__(self, tenant_id, sql, *, timeout_seconds):  # pragma: no cover
        raise AssertionError("校验失败时不应发起任何执行")


def _templates() -> RestrictedTemplateQuery:
    return RestrictedTemplateQuery(
        [RestrictedTemplate(keywords=("流失",), response="模板：高流失风险客户名单")]
    )


# --- 执行成功 --------------------------------------------------------------


def test_run_executes_when_all_checks_pass() -> None:
    runner = _RecordingRunner([_Row("tenant-a", 1), _Row("tenant-a", 2)])
    executor = SafeSQLExecutor(runner=runner, template_query=_templates())

    outcome = executor.run(
        natural_language="列出客户",
        sql="SELECT name FROM customers",
        tenant_id="tenant-a",
    )

    assert outcome.outcome is ExecutionOutcome.EXECUTED
    assert outcome.executed is True
    assert outcome.result is not None
    assert outcome.result.row_count == 2
    assert outcome.result.truncated is False
    # 执行器以 30 秒预算调用底层执行器。
    assert runner.calls[0][2] == EXECUTION_TIMEOUT_SECONDS


def test_run_truncates_over_limit_and_flags() -> None:
    rows = [_Row("tenant-a", i) for i in range(MAX_RESULT_ROWS + 25)]
    executor = SafeSQLExecutor(runner=_RecordingRunner(rows))

    outcome = executor.run(
        natural_language="全部客户",
        sql="SELECT name FROM customers",
        tenant_id="tenant-a",
    )

    assert outcome.outcome is ExecutionOutcome.EXECUTED
    assert outcome.result.truncated is True
    assert outcome.result.row_count == MAX_RESULT_ROWS


def test_run_blocks_foreign_tenant_rows() -> None:
    rows = [_Row("tenant-a", 1), _Row("evil-tenant", 2)]
    executor = SafeSQLExecutor(runner=_RecordingRunner(rows))

    with pytest.raises(TenantIsolationError):
        executor.run(
            natural_language="q",
            sql="SELECT name FROM customers",
            tenant_id="tenant-a",
        )


# --- 校验失败：拒绝 + 无变更 + 澄清 + 回退 ---------------------------------


def test_run_rejects_non_readonly_without_executing() -> None:
    runner = _NeverCalledRunner()
    executor = SafeSQLExecutor(runner=runner, template_query=_templates())

    outcome = executor.run(
        natural_language="删掉流失客户",
        sql="DELETE FROM customers",
        tenant_id="tenant-a",
    )

    assert outcome.outcome is ExecutionOutcome.REJECTED
    assert outcome.executed is False
    assert outcome.result is None
    assert outcome.validation.failed_check == "read_only"
    assert outcome.clarification and "只读约束" in outcome.clarification
    # 命中受限模板回退。
    assert outcome.fallback_kind is FallbackKind.TEMPLATE
    assert outcome.fallback_text == "模板：高流失风险客户名单"


def test_run_rejects_whitelist_violation() -> None:
    executor = SafeSQLExecutor(runner=_NeverCalledRunner())

    outcome = executor.run(
        natural_language="随便问问",
        sql="SELECT password_hash FROM customers",
        tenant_id="tenant-a",
    )

    assert outcome.outcome is ExecutionOutcome.REJECTED
    assert outcome.validation.failed_check == "whitelist"
    # 无匹配模板：回退到请用户重述提示。
    assert outcome.fallback_kind is FallbackKind.RESTATE
    assert outcome.fallback_text


def test_run_rejects_when_tenant_missing() -> None:
    executor = SafeSQLExecutor(runner=_NeverCalledRunner())

    outcome = executor.run(
        natural_language="q",
        sql="SELECT name FROM customers",
        tenant_id="",
    )

    assert outcome.outcome is ExecutionOutcome.REJECTED
    assert outcome.validation.failed_check == "rls"
    assert outcome.executed is False


# --- 执行超时 --------------------------------------------------------------


def test_run_returns_timeout_when_execution_exceeds_budget() -> None:
    runner = _TimeoutRunner()
    executor = SafeSQLExecutor(runner=runner, template_query=_templates())

    outcome = executor.run(
        natural_language="一个很慢的查询",
        sql="SELECT name FROM customers",
        tenant_id="tenant-a",
    )

    assert outcome.outcome is ExecutionOutcome.TIMEOUT
    assert outcome.result is None
    assert runner.calls == 1
    assert outcome.clarification and "超过" in outcome.clarification
