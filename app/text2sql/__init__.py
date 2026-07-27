"""Text2SQL 层：基于云端 LLM 的自然语言转 SQL。

任务 9.1 实现**生成**子层：结合提示工程 / 少样本，基于固定 Schema
（``app.db.metadata``）通过可注入的 :class:`~app.llm.client.CloudLLMClient`
生成候选只读 SQL（30 秒生成预算内）。SQL 白名单 / 只读 / RLS 三重校验与执行
由任务 9.2 负责，不在本层范围内。

范围约束：Text2SQL 经云端 LLM（通义千问 / 智谱 GLM）结合提示工程 / 少样本实现，
不含任何模型微调。
"""

from app.text2sql.errors import (
    Text2SQLError,
    Text2SQLGenerationTimeoutError,
    Text2SQLUnavailableError,
)
from app.text2sql.generator import (
    GENERATION_BUDGET_SECONDS,
    Text2SQLGenerator,
    Text2SQLResult,
    build_schema_description,
    build_system_prompt,
    clean_sql,
    default_few_shot_examples,
)

__all__ = [
    "GENERATION_BUDGET_SECONDS",
    "Text2SQLGenerator",
    "Text2SQLResult",
    "build_schema_description",
    "build_system_prompt",
    "default_few_shot_examples",
    "clean_sql",
    "Text2SQLError",
    "Text2SQLGenerationTimeoutError",
    "Text2SQLUnavailableError",
]

# --- 任务 9.2：SQL 三重校验与执行控制（append-only） ------------------------
from app.text2sql.errors import (  # noqa: E402
    SQLExecutionTimeoutError,
    SQLNotReadOnlyError,
    SQLRLSValidationError,
    SQLValidationError,
    SQLWhitelistError,
)
from app.text2sql.executor import (  # noqa: E402
    EXECUTION_TIMEOUT_SECONDS,
    ExecutionOutcome,
    FallbackKind,
    SafeSQLExecution,
    SafeSQLExecutor,
    SQLRunner,
    build_engine_runner,
)
from app.text2sql.validator import (  # noqa: E402
    ALLOWED_COLUMN_NAMES,
    ALLOWED_TABLE_NAMES,
    SQL_DIALECT,
    CheckStatus,
    ValidationReport,
    check_read_only,
    check_rls,
    check_whitelist,
    validate_sql,
)

__all__ += [
    # 校验
    "SQL_DIALECT",
    "ALLOWED_TABLE_NAMES",
    "ALLOWED_COLUMN_NAMES",
    "CheckStatus",
    "ValidationReport",
    "check_read_only",
    "check_whitelist",
    "check_rls",
    "validate_sql",
    # 执行控制
    "EXECUTION_TIMEOUT_SECONDS",
    "SQLRunner",
    "ExecutionOutcome",
    "FallbackKind",
    "SafeSQLExecution",
    "SafeSQLExecutor",
    "build_engine_runner",
    # 错误
    "SQLValidationError",
    "SQLNotReadOnlyError",
    "SQLWhitelistError",
    "SQLRLSValidationError",
    "SQLExecutionTimeoutError",
]
