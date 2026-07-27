"""任务 9.1 单元测试：基于 Cloud_LLM 的 Text2SQL 生成（Requirement 2.1）。

覆盖：
- 提示工程 / 少样本正常生成候选只读 SQL；
- 候选 SQL 清洗（去除 Markdown 代码块围栏）；
- 系统提示包含固定 Schema 描述；
- Cloud_LLM 降级（重试耗尽 / 熔断）时拒绝产出候选 SQL；
- 生成超过 30 秒预算时判定为生成超时。

所有测试通过注入伪传输层与伪时钟实现，无真实网络、无真实等待。
"""

from __future__ import annotations

import pytest

from app.llm.client import (
    CloudLLMClient,
    RestrictedTemplateQuery,
)
from app.llm.errors import LLMTimeoutError
from app.text2sql.errors import (
    Text2SQLGenerationTimeoutError,
    Text2SQLUnavailableError,
)
from app.text2sql.generator import (
    GENERATION_BUDGET_SECONDS,
    Text2SQLGenerator,
    build_schema_description,
    build_system_prompt,
    clean_sql,
    default_few_shot_examples,
)


# --- 测试替身 --------------------------------------------------------------


class _FakeClock:
    """可控伪时钟：now() 按预设步进推进，sleep() 直接累加不真实等待。"""

    def __init__(self, steps: list[float] | None = None) -> None:
        self._t = 0.0
        # 每次 now() 调用后推进的增量序列（用于模拟耗时）。
        self._steps = list(steps or [])

    def now(self) -> float:
        current = self._t
        if self._steps:
            self._t += self._steps.pop(0)
        return current

    def sleep(self, seconds: float) -> None:
        if seconds > 0:
            self._t += seconds


class _CannedTransport:
    """始终返回预设文本的伪传输层。"""

    def __init__(self, text: str) -> None:
        self._text = text
        self.calls = 0

    def generate(self, prompt: str, *, timeout: float) -> str:
        self.calls += 1
        self.last_prompt = prompt
        return self._text


class _AlwaysFailTransport:
    """始终抛出可重试错误的伪传输层（触发重试耗尽 → 降级）。"""

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, prompt: str, *, timeout: float) -> str:
        self.calls += 1
        raise LLMTimeoutError("boom")


def _make_client(transport, *, clock=None) -> CloudLLMClient:
    return CloudLLMClient(
        transport=transport,
        template_query=RestrictedTemplateQuery(),
        clock=clock,
        timeout_seconds=10.0,
        max_retries=3,
    )


# --- Schema 描述与系统提示 --------------------------------------------------


def test_schema_description_includes_core_tables() -> None:
    """固定 Schema 描述应来源于 metadata 并包含核心表与列。"""
    description = build_schema_description()
    assert "customers(" in description
    assert "skus(" in description
    assert "customer_id" in description
    assert "churn_score" in description


def test_system_prompt_embeds_schema_and_readonly_rule() -> None:
    """系统提示应嵌入 Schema 且明确只读约束。"""
    prompt = build_system_prompt(build_schema_description())
    assert "只读" in prompt
    assert "SELECT" in prompt
    assert "customers(" in prompt


def test_default_few_shot_examples_are_readonly_selects() -> None:
    """默认少样本示例均为 SELECT 只读语句。"""
    examples = default_few_shot_examples()
    assert len(examples) >= 1
    for example in examples:
        assert example.assistant.strip().upper().startswith("SELECT")


# --- 候选 SQL 清洗 ----------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("SELECT 1;", "SELECT 1;"),
        ("  SELECT 1;  ", "SELECT 1;"),
        ("```sql\nSELECT 1;\n```", "SELECT 1;"),
        ("```\nSELECT 1;\n```", "SELECT 1;"),
    ],
)
def test_clean_sql_strips_fences_and_whitespace(raw: str, expected: str) -> None:
    assert clean_sql(raw) == expected


# --- 正常生成 --------------------------------------------------------------


def test_generate_returns_candidate_sql() -> None:
    """正常情况下应返回 LLM 生成的候选只读 SQL。"""
    sql = "SELECT customer_id, name FROM customers WHERE churn_score > 0.6;"
    transport = _CannedTransport(sql)
    generator = Text2SQLGenerator(client=_make_client(transport))

    result = generator.generate("哪些客户在流失？")

    assert result.sql == sql
    assert result.natural_language == "哪些客户在流失？"
    assert transport.calls == 1


def test_generate_strips_markdown_fences() -> None:
    """LLM 返回带 Markdown 围栏时，候选 SQL 应被清洗。"""
    transport = _CannedTransport("```sql\nSELECT name FROM customers;\n```")
    generator = Text2SQLGenerator(client=_make_client(transport))

    result = generator.generate("列出客户姓名")

    assert result.sql == "SELECT name FROM customers;"


def test_generate_prompt_includes_schema_and_examples() -> None:
    """发送给传输层的 prompt 应包含系统提示（Schema）与少样本示例。"""
    transport = _CannedTransport("SELECT 1;")
    generator = Text2SQLGenerator(client=_make_client(transport))

    generator.generate("测试问题")

    assert "customers(" in transport.last_prompt
    # 至少一个少样本示例的输入出现在 prompt 中。
    assert "列出所有客户的姓名和电话" in transport.last_prompt
    assert "测试问题" in transport.last_prompt


# --- 降级与超时 ------------------------------------------------------------


def test_generate_raises_when_llm_degrades() -> None:
    """Cloud_LLM 重试耗尽降级时应拒绝产出候选 SQL。"""
    transport = _AlwaysFailTransport()
    # 使用不真实等待的伪时钟，避免退避真实 sleep。
    clock = _FakeClock()
    client = _make_client(transport, clock=clock)
    generator = Text2SQLGenerator(client=client, clock=_FakeClock())

    with pytest.raises(Text2SQLUnavailableError):
        generator.generate("哪些客户在流失？")


def test_generate_raises_on_budget_exceeded() -> None:
    """生成耗时超过 30 秒预算时应判定为生成超时。"""
    transport = _CannedTransport("SELECT 1;")
    # 生成器时钟：第一次 now()=0，第二次推进到超过预算。
    slow_clock = _FakeClock(steps=[GENERATION_BUDGET_SECONDS + 1.0, 0.0])
    generator = Text2SQLGenerator(client=_make_client(transport), clock=slow_clock)

    with pytest.raises(Text2SQLGenerationTimeoutError):
        generator.generate("一个很慢的查询")


def test_generate_within_budget_ok() -> None:
    """生成耗时在预算内应正常返回并记录耗时。"""
    transport = _CannedTransport("SELECT 1;")
    fast_clock = _FakeClock(steps=[1.5, 0.0])
    generator = Text2SQLGenerator(client=_make_client(transport), clock=fast_clock)

    result = generator.generate("快查询")

    assert result.sql == "SELECT 1;"
    assert result.elapsed_seconds == pytest.approx(1.5)
