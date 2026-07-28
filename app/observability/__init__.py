"""可观测性：Agent 决策链全链路追溯（LangSmith / LangFuse）+ Prometheus 运行时指标。"""

from app.observability.errors import (
    ObservabilityError,
    RetentionPolicyError,
    TraceBackendError,
)
from app.observability.metrics import (
    BOOKING_OUTCOMES_TOTAL,
    CONTENT_TYPE_LATEST,
    HTTP_REQUEST_DURATION,
    HTTP_REQUESTS_TOTAL,
    INTENT_TOTAL,
    LLM_REQUESTS_TOTAL,
    WECOM_CALLBACK_TOTAL,
    render_latest,
)
from app.observability.tracing import (
    DEFAULT_RETENTION_DAYS,
    MIN_RETENTION_DAYS,
    DecisionChain,
    DecisionChainTracer,
    DecisionTrace,
    ExternalTracingClient,
    InMemoryTracingBackend,
    LangFuseBackend,
    LangSmithBackend,
    NodeSpan,
    RetentionConfig,
    SpanHandle,
    TracingBackend,
    current_chain,
    get_tracing_backend,
    traced_node,
)

__all__ = [
    # 错误类型
    "ObservabilityError",
    "RetentionPolicyError",
    "TraceBackendError",
    # 决策链追溯（任务 23.1）
    "DecisionChainTracer",
    "DecisionChain",
    "DecisionTrace",
    "NodeSpan",
    "SpanHandle",
    "RetentionConfig",
    "DEFAULT_RETENTION_DAYS",
    "MIN_RETENTION_DAYS",
    "traced_node",
    "current_chain",
    # 后端抽象
    "TracingBackend",
    "InMemoryTracingBackend",
    "ExternalTracingClient",
    "LangSmithBackend",
    "LangFuseBackend",
    "get_tracing_backend",
    # Prometheus 运行时指标（链路监控）
    "CONTENT_TYPE_LATEST",
    "render_latest",
    "HTTP_REQUEST_DURATION",
    "HTTP_REQUESTS_TOTAL",
    "LLM_REQUESTS_TOTAL",
    "INTENT_TOTAL",
    "BOOKING_OUTCOMES_TOTAL",
    "WECOM_CALLBACK_TOTAL",
]
