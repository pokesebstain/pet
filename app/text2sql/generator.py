"""基于 Cloud_LLM 的 Text2SQL **生成**（任务 9.1，Requirement 2.1）。

对应设计文档：
- Components / 组件 3「统一工具层」中的 ``db_query_tool``（Text2SQL）能力的**生成**子步骤；
- 二、核心业务流程时序图 2.1（分析 Agent → ``text2sql_tool``）；
- Error Handling 表中「Text2SQL 生成非法/越权 SQL」一行的**上游生成**环节。

职责边界（重要）：
- 本模块**只**负责：结合提示工程 / 少样本，基于**固定 Schema**（``app.db.metadata``）
  通过 :class:`~app.llm.client.CloudLLMClient` 生成一条**候选只读 SQL 字符串**，并在
  **30 秒生成预算**内返回（Requirement 2.1）。
- 本模块**不**负责：SQL 白名单 / 只读约束 / RLS 三重校验与实际执行、结果截断等
  （由任务 9.2 负责）。因此这里仅返回候选 SQL，不保证其安全性 / 合法性。

范围约束：Text2SQL 经**云端 LLM**（通义千问 / 智谱 GLM）结合提示工程 / 少样本实现，
**不含任何模型微调**（不涉及 Qwen2.5-7B + LoRA / LLaMA-Factory / vLLM）。

可测试性：LLM 被抽象在既有可注入的 :class:`~app.llm.client.CloudLLMClient` 之后
（其传输层 :class:`~app.llm.client.LLMTransport` 可注入伪实现），故生成逻辑可在
**无真实网络**的情况下测试。时间通过 :class:`~app.llm.client.Clock` 注入以便快速验证
生成预算。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import Table

from app.db.metadata import ALL_TABLES
from app.llm.client import (
    Clock,
    CloudLLMClient,
    FewShotExample,
    ResponseSource,
    SystemClock,
)
from app.text2sql.errors import (
    Text2SQLGenerationTimeoutError,
    Text2SQLUnavailableError,
)

__all__ = [
    "GENERATION_BUDGET_SECONDS",
    "Text2SQLResult",
    "Text2SQLGenerator",
    "build_schema_description",
    "build_system_prompt",
    "default_few_shot_examples",
    "clean_sql",
]

#: Text2SQL 生成的整体时间预算（秒），对应 Requirement 2.1「30 秒内」。
GENERATION_BUDGET_SECONDS: float = 30.0


# --- 固定 Schema 描述（提示工程素材）---------------------------------------


def build_schema_description(tables: Sequence[Table] = ALL_TABLES) -> str:
    """将固定 Schema 渲染为紧凑的文本描述，供提示工程使用。

    描述来源于 :mod:`app.db.metadata` 的类型化 ``Table`` 定义（单一真相来源），
    从而与实际数据库结构保持一致。输出形如::

        customers(customer_id: VARCHAR, tenant_id: VARCHAR, name: VARCHAR, ...)

    Args:
        tables: 需描述的表集合，默认全部业务表。

    Returns:
        每行一张表的多行字符串。
    """
    lines: list[str] = []
    for table in tables:
        columns = ", ".join(
            f"{column.name}: {column.type}" for column in table.columns
        )
        lines.append(f"{table.name}({columns})")
    return "\n".join(lines)


def build_system_prompt(schema_description: str) -> str:
    """构造 Text2SQL 系统提示（提示工程）。

    系统提示明确约束模型：仅可基于给定固定 Schema 生成**只读**（``SELECT``）SQL，
    禁止任何写操作 / DDL，且只输出 SQL 本身。

    注意：这些仅为**提示层**的约束，真正的安全保证由任务 9.2 的三重校验强制执行。
    """
    return (
        "你是 PetOps 平台的 Text2SQL 生成助手。"
        "你的任务是：根据用户的自然语言问题，仅基于下方给定的固定数据库 Schema，"
        "生成一条 PostgreSQL 方言的**只读**查询语句。\n"
        "严格遵守以下规则：\n"
        "1. 只能生成单条 SELECT 查询，禁止 INSERT/UPDATE/DELETE/DDL 等任何写操作；\n"
        "2. 只能引用下方 Schema 中出现的表与列，不得臆造表 / 列；\n"
        "3. 查询应限定在当前租户范围内（行级安全由数据库层强制，不要写入或修改数据）；\n"
        "4. 只输出 SQL 语句本身，不要输出解释、注释或 Markdown 代码块标记。\n\n"
        "固定数据库 Schema：\n"
        f"{schema_description}"
    )


def default_few_shot_examples() -> tuple[FewShotExample, ...]:
    """返回默认少样本示例（自然语言 → 只读 SQL）。

    示例覆盖典型的门店经营分析问句，帮助模型稳定输出符合固定 Schema 的只读 SQL。
    """
    return (
        FewShotExample(
            user="列出所有客户的姓名和电话",
            assistant="SELECT name, phone FROM customers;",
        ),
        FewShotExample(
            user="上个月哪些高价值客户在流失？按 LTV 从高到低排列",
            assistant=(
                "SELECT customer_id, name, ltv, churn_score "
                "FROM customers "
                "WHERE churn_score > 0.6 AND ltv IS NOT NULL "
                "ORDER BY ltv DESC;"
            ),
        ),
        FewShotExample(
            user="查询当前库存量小于等于 0 的缺货商品",
            assistant=(
                "SELECT sku_id, name, current_stock "
                "FROM skus "
                "WHERE current_stock <= 0 "
                "ORDER BY sku_id ASC;"
            ),
        ),
    )


# --- 候选 SQL 清洗 ----------------------------------------------------------


def clean_sql(text: str) -> str:
    """清洗 LLM 返回文本，提取候选 SQL 字符串。

    去除首尾空白与常见的 Markdown 代码块围栏（```sql ... ``` 或 ``` ... ```），
    使返回值为尽量纯净的 SQL 文本。不做任何语义 / 安全校验（属任务 9.2）。
    """
    cleaned = text.strip()
    if cleaned.startswith("```"):
        # 去掉起始围栏行（可能形如 ```sql）。
        newline = cleaned.find("\n")
        cleaned = cleaned[newline + 1 :] if newline != -1 else cleaned[3:]
        # 去掉结尾围栏。
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rstrip()[:-3]
    return cleaned.strip()


# --- 生成结果 ---------------------------------------------------------------


@dataclass(frozen=True)
class Text2SQLResult:
    """Text2SQL 生成结果。

    Attributes:
        sql: 生成的**候选**只读 SQL 字符串（未经安全校验）。
        natural_language: 触发生成的原始自然语言问题。
        elapsed_seconds: 生成耗时（秒），用于验证 30 秒预算。
    """

    sql: str
    natural_language: str
    elapsed_seconds: float


# --- 生成器 -----------------------------------------------------------------


class Text2SQLGenerator:
    """基于 Cloud_LLM 的 Text2SQL 候选 SQL 生成器（任务 9.1）。

    通过既有可注入的 :class:`~app.llm.client.CloudLLMClient` 结合提示工程 / 少样本，
    基于固定 Schema 生成候选只读 SQL，并在 30 秒生成预算内返回。

    典型用法::

        generator = Text2SQLGenerator(client=cloud_llm_client)
        result = generator.generate("上个月哪些高价值客户在流失？")
        candidate_sql = result.sql  # 交由任务 9.2 做三重校验与执行

    所有外部依赖（LLM 客户端、时钟、Schema、少样本）均可注入，便于无网络测试。
    """

    def __init__(
        self,
        client: CloudLLMClient,
        *,
        tables: Sequence[Table] = ALL_TABLES,
        examples: Sequence[FewShotExample] | None = None,
        clock: Clock | None = None,
        generation_budget_seconds: float = GENERATION_BUDGET_SECONDS,
    ) -> None:
        self._client = client
        self._clock = clock or SystemClock()
        self._examples = tuple(examples) if examples is not None else default_few_shot_examples()
        self._budget = generation_budget_seconds
        schema_description = build_schema_description(tables)
        self._system_prompt = build_system_prompt(schema_description)

    @property
    def system_prompt(self) -> str:
        """本生成器使用的系统提示（含固定 Schema 描述）。"""
        return self._system_prompt

    def generate(self, natural_language: str) -> Text2SQLResult:
        """基于自然语言问题生成一条候选只读 SQL。

        Args:
            natural_language: 用户的自然语言分析问题。

        Returns:
            Text2SQLResult: 含候选 SQL 与生成耗时。

        Raises:
            Text2SQLUnavailableError: Cloud_LLM 降级（模板 / 重述），无法产出候选 SQL。
            Text2SQLGenerationTimeoutError: 生成耗时超过 30 秒预算（Requirement 2.1）。
        """
        start = self._clock.now()
        response = self._client.complete(
            natural_language,
            system_prompt=self._system_prompt,
            examples=self._examples,
        )
        elapsed = self._clock.now() - start

        # 超出 30 秒生成预算：判定为生成超时（Requirement 2.1）。
        if elapsed > self._budget:
            raise Text2SQLGenerationTimeoutError(
                f"Text2SQL 生成耗时 {elapsed:.3f}s 超过预算 {self._budget:.0f}s"
            )

        # Cloud_LLM 降级（受限模板 / 请用户重述）：无法产出有效候选 SQL。
        if response.source is not ResponseSource.LLM:
            raise Text2SQLUnavailableError(
                "Cloud_LLM 不可用，已降级，无法生成候选 SQL"
            )

        return Text2SQLResult(
            sql=clean_sql(response.text),
            natural_language=natural_language,
            elapsed_seconds=elapsed,
        )
