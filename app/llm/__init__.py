"""云端 LLM 客户端层（通义千问 / 智谱 GLM）。

封装提示工程 / 少样本调用、统一超时与错误类型、指数退避重试、熔断，以及受限模板查询
降级。范围约束：本次不含任何模型微调，降级路径不依赖任何本地 / 微调模型。
"""

from app.llm.client import (
    CIRCUIT_FAILURE_THRESHOLD,
    CIRCUIT_OPEN_SECONDS,
    CIRCUIT_WINDOW_SECONDS,
    INITIAL_BACKOFF_SECONDS,
    MAX_BACKOFF_SECONDS,
    RESTATE_PROMPT,
    CircuitBreaker,
    Clock,
    CloudLLMClient,
    FewShotExample,
    LLMResponse,
    LLMTransport,
    ResponseSource,
    RestrictedTemplate,
    RestrictedTemplateQuery,
    SystemClock,
)
from app.llm.errors import (
    LLMError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnavailableError,
)
0from app.llm.transport import CloudLLMHttpTransport, build_llm_transport

__all__ = [
    "CloudLLMHttpTransport",
    "build_llm_transport",
    "CloudLLMClient",
    "Clock",
    "SystemClock",
    "LLMTransport",
    "FewShotExample",
    "ResponseSource",
    "LLMResponse",
    "RestrictedTemplate",
    "RestrictedTemplateQuery",
    "CircuitBreaker",
    "RESTATE_PROMPT",
    "INITIAL_BACKOFF_SECONDS",
    "MAX_BACKOFF_SECONDS",
    "CIRCUIT_FAILURE_THRESHOLD",
    "CIRCUIT_WINDOW_SECONDS",
    "CIRCUIT_OPEN_SECONDS",
    "LLMError",
    "LLMTimeoutError",
    "LLMRateLimitError",
    "LLMUnavailableError",
]
