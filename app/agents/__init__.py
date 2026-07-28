"""AI 决策中枢：Supervisor 与专家 Agent（分析/运营/健康/供应链/营销）。"""

from app.agents.health import (
    ANALYSIS_WINDOW_DAYS,
    DETECTION_DEADLINE_SECONDS,
    HEALTH_ALERT_EVENT,
    HEALTH_DATA_INGESTED_EVENT,
    LEVEL_HIGH_THRESHOLD,
    LEVEL_MEDIUM_THRESHOLD,
    WEIGHT_DROP_THRESHOLD,
    WEIGHT_DROP_WINDOW_DAYS,
    AlertTask,
    AlertTaskSink,
    HealthAgent,
    HealthAlert,
    HealthAlertLevel,
    HealthDetectionTimeoutError,
    HealthMetricReader,
    InMemoryAlertTaskSink,
    InMemoryHealthMetricReader,
)
from app.agents.marketing import (
    DEFAULT_SYSTEM_PROMPT,
    DEFAULT_TIME_BUDGET_SECONDS,
    LLM_FAILED_MESSAGE,
    MISSING_REFERENCES_MESSAGE,
    ContentGenerationResult,
    ContentGenerationTimeoutError,
    ContentStatus,
    EmbeddingProvider,
    MarketingAgent,
    MarketingError,
)

__all__ = [
    # 健康 Agent（任务 15.2）
    "HealthAgent",
    "HealthAlert",
    "HealthAlertLevel",
    "AlertTask",
    "HealthMetricReader",
    "InMemoryHealthMetricReader",
    "AlertTaskSink",
    "InMemoryAlertTaskSink",
    "HealthDetectionTimeoutError",
    "HEALTH_DATA_INGESTED_EVENT",
    "HEALTH_ALERT_EVENT",
    "DETECTION_DEADLINE_SECONDS",
    "ANALYSIS_WINDOW_DAYS",
    "WEIGHT_DROP_WINDOW_DAYS",
    "WEIGHT_DROP_THRESHOLD",
    "LEVEL_MEDIUM_THRESHOLD",
    "LEVEL_HIGH_THRESHOLD",
    # 营销 / 社区内容生成 Agent（任务 18.1）
    "MarketingAgent",
    "MarketingError",
    "ContentGenerationTimeoutError",
    "ContentGenerationResult",
    "ContentStatus",
    "EmbeddingProvider",
    "DEFAULT_TIME_BUDGET_SECONDS",
    "DEFAULT_SYSTEM_PROMPT",
    "LLM_FAILED_MESSAGE",
    "MISSING_REFERENCES_MESSAGE",
]


# --- AI 决策中枢：Supervisor 与全局状态（任务 21.1）-------------------------
from app.agents.intent import (
    DEFAULT_CONFIDENCE_THRESHOLD,
    EXPERT_INTENTS,
    CloudLLMIntentClassifier,
    IntentClassifier,
    IntentResult,
)
from app.agents.state import AgentState, new_state
from app.agents.supervisor import (
    CLARIFICATION_PROMPT,
    INTENT_TIMEOUT_SECONDS,
    MAX_REPLANS,
    PARTIAL_ANSWER_PREFIX,
    ReflectDecision,
    RouteDecision,
    SupervisorAgent,
    build_supervisor_graph,
)

__all__ += [
    # 全局状态（任务 21.1）
    "AgentState",
    "new_state",
    # 意图识别（任务 21.1）
    "EXPERT_INTENTS",
    "DEFAULT_CONFIDENCE_THRESHOLD",
    "IntentResult",
    "IntentClassifier",
    "CloudLLMIntentClassifier",
    # Supervisor（任务 21.1）
    "SupervisorAgent",
    "build_supervisor_graph",
    "MAX_REPLANS",
    "INTENT_TIMEOUT_SECONDS",
    "CLARIFICATION_PROMPT",
    "PARTIAL_ANSWER_PREFIX",
    "RouteDecision",
    "ReflectDecision",
]


# --- 专家 Agent 层：五个专家 Agent 的真实实现（任务 21.2）--------------------
from app.agents.experts import (
    AnalysisAgent,
    ExpertAgent,
    HealthExpertAgent,
    MarketingExpertAgent,
    MISSING_INPUT_MESSAGE,
    NO_MATCH_EXPLANATION,
    OperationAgent,
    SupplyAgent,
    build_expert_agents,
    record_expert_output,
)

__all__ += [
    # 专家 Agent 层（任务 21.2）
    "ExpertAgent",
    "AnalysisAgent",
    "OperationAgent",
    "HealthExpertAgent",
    "SupplyAgent",
    "MarketingExpertAgent",
    "build_expert_agents",
    "record_expert_output",
    "NO_MATCH_EXPLANATION",
    "MISSING_INPUT_MESSAGE",
]


# --- 多轮有状态 What-if 与 thread_id 持久化（任务 22.1）----------------------
from app.agents.experts import (
    DEFAULT_WHATIF_DISCOUNT,
    NO_PREVIOUS_RESULT_MESSAGE,
    RECALL_SENSITIVITY,
    WHATIF_KEYWORDS,
)
from app.agents.supervisor import compile_supervisor_graph

__all__ += [
    # thread_id 状态持久化编译入口（任务 22.1）
    "compile_supervisor_graph",
    # Operation_Agent What-if 模拟（任务 22.1）
    "NO_PREVIOUS_RESULT_MESSAGE",
    "DEFAULT_WHATIF_DISCOUNT",
    "RECALL_SENSITIVITY",
    "WHATIF_KEYWORDS",
]


# --- HITL 检查点：副作用动作的人工确认（任务 22.3，Requirement 4 / 8.5）--------
from app.agents.hitl import (
    HITL_TIMEOUT_SECONDS,
    REJECTED_MESSAGE,
    SIDE_EFFECT_EVENT_TYPES,
    SIDE_EFFECT_TYPES,
    TIMED_OUT_MESSAGE,
    AllowAllApprovalProvider,
    ApprovalProvider,
    ApprovalResponse,
    AuditLogger,
    CallableApprovalProvider,
    DenyAllApprovalProvider,
    EventPublisher,
    HITLCheckpoint,
    HITLOutcome,
    InMemoryAuditLogger,
    InMemoryNotifier,
    NoResponseApprovalProvider,
    Notifier,
    RecordingSideEffectExecutor,
    SideEffectExecutor,
)

__all__ += [
    # HITL 检查点（任务 22.3）
    "HITLCheckpoint",
    "HITLOutcome",
    "ApprovalResponse",
    "ApprovalProvider",
    "DenyAllApprovalProvider",
    "AllowAllApprovalProvider",
    "NoResponseApprovalProvider",
    "CallableApprovalProvider",
    "SideEffectExecutor",
    "RecordingSideEffectExecutor",
    "EventPublisher",
    "AuditLogger",
    "InMemoryAuditLogger",
    "Notifier",
    "InMemoryNotifier",
    "HITL_TIMEOUT_SECONDS",
    "SIDE_EFFECT_TYPES",
    "SIDE_EFFECT_EVENT_TYPES",
    "REJECTED_MESSAGE",
    "TIMED_OUT_MESSAGE",
]


# --- 接待预约 Agent：意图抽取 + 自动预约门控编排（任务 27.2，Requirement 21/22/24）----
from app.agents.reception import (
    BOOKING_INTENT_FEW_SHOTS,
    BOOKING_INTENT_SYSTEM_PROMPT,
    DEFAULT_INTENT_CONFIDENCE_THRESHOLD,
    DEFAULT_INTENT_TIME_BUDGET_SECONDS,
    DEFAULT_SEARCH_HORIZON_DAYS as RECEPTION_DEFAULT_SEARCH_HORIZON_DAYS,
    DEFAULT_SLOT_MINUTES as RECEPTION_DEFAULT_SLOT_MINUTES,
    DEFAULT_SUGGESTION_COUNT as RECEPTION_DEFAULT_SUGGESTION_COUNT,
    MULTIPLE_PETS_REPLY,
    NEEDS_HITL_REPLY,
    NO_ALTERNATIVES_REPLY,
    NO_CUSTOMER_REPLY,
    NO_PET_REPLY,
    TENANT_MISSING_REPLY,
    BookingDecision,
    PetResolutionResult,
    PetResolver,
    ReceptionAgent,
    ReceptionConfig,
    should_auto_book,
)

__all__ += [
    # 接待预约 Agent（任务 27.2）
    "ReceptionAgent",
    "ReceptionConfig",
    "BookingDecision",
    "should_auto_book",
    "DEFAULT_INTENT_CONFIDENCE_THRESHOLD",
    "DEFAULT_INTENT_TIME_BUDGET_SECONDS",
    "RECEPTION_DEFAULT_SUGGESTION_COUNT",
    "RECEPTION_DEFAULT_SEARCH_HORIZON_DAYS",
    "RECEPTION_DEFAULT_SLOT_MINUTES",
    "BOOKING_INTENT_SYSTEM_PROMPT",
    "BOOKING_INTENT_FEW_SHOTS",
    "NEEDS_HITL_REPLY",
    "TENANT_MISSING_REPLY",
    "NO_ALTERNATIVES_REPLY",
    "NO_CUSTOMER_REPLY",
    "NO_PET_REPLY",
    "MULTIPLE_PETS_REPLY",
    "PetResolver",
    "PetResolutionResult",
]
