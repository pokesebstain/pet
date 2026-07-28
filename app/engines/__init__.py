"""业务引擎：LTV、订阅、健康数据中台、供应链、生态合作网络等。"""

from app.engines.health import (
    HEALTH_DATA_INGESTED_EVENT,
    INGEST_DEADLINE_SECONDS,
    HealthDataHub,
    HealthDataIngestTimeoutError,
    HealthDataValidationError,
    HealthMetricRepository,
    InMemoryHealthMetricRepository,
)
from app.engines.churn import (
    FEATURE_SPEC,
    REQUIRED_FEATURES,
    predict_churn,
)
from app.engines.demand import (
    MAX_HORIZON_DAYS,
    MIN_HISTORY_DAYS,
    SalesHistoryProvider,
    forecast_demand,
)
from app.engines.errors import (
    AuthorizationError,
    DataNotFoundError,
    EngineError,
    InvalidParameterError,
)
from app.engines.recommend import (
    MAX_RECOMMENDATIONS,
    Recommendation,
    RecommendationDataProvider,
    RuleCandidate,
    StaticRecommendationData,
    recommend,
)
from app.engines.ltv import (
    CustomerFeatureProvider,
    DEFAULT_HORIZON_MONTHS,
    DEFAULT_MONTHLY_DISCOUNT_RATE,
    MAX_HORIZON_MONTHS,
    REQUIRED_LTV_FEATURES,
    predict_ltv,
)
from app.engines.supply_chain import (
    DEFAULT_SERVICE_LEVEL,
    InMemorySalesHistoryProvider,
    InMemorySkuMasterProvider,
    RestockDecision,
    SkuMasterProvider,
    SupplyChainEngine,
)
from app.engines.subscription import (
    ACTIVE_STATUS,
    BillingCycle,
    BillingFailure,
    BillingReport,
    ChargeOutcome,
    EventPublisher,
    InMemoryPlanStore,
    InMemorySubscriptionStore,
    MAX_PLAN_AMOUNT,
    MIN_PLAN_AMOUNT,
    PaymentGateway,
    Plan,
    PlanSpec,
    PlanStore,
    SUBSCRIPTION_BILLED_EVENT,
    SubscriptionEngine,
    SubscriptionStore,
)
from app.engines.ltv_engine import (
    DEFAULT_CHURN_RISK_THRESHOLD,
    DEFAULT_LTV_HIGH_THRESHOLD,
    InMemoryCustomerFeatureProvider,
    LTVEngine,
    SEGMENT_CHURN_RISK,
    SEGMENT_GROWTH,
    SEGMENT_HIGH_VALUE,
    Segment,
)

__all__ = [
    "forecast_demand",
    "SalesHistoryProvider",
    "MIN_HISTORY_DAYS",
    "MAX_HORIZON_DAYS",
    "predict_churn",
    "REQUIRED_FEATURES",
    "FEATURE_SPEC",
    "EngineError",
    "InvalidParameterError",
    "DataNotFoundError",
    "AuthorizationError",
    "recommend",
    "Recommendation",
    "RuleCandidate",
    "RecommendationDataProvider",
    "StaticRecommendationData",
    "MAX_RECOMMENDATIONS",
    "predict_ltv",
    "CustomerFeatureProvider",
    "REQUIRED_LTV_FEATURES",
    "MAX_HORIZON_MONTHS",
    "DEFAULT_HORIZON_MONTHS",
    "DEFAULT_MONTHLY_DISCOUNT_RATE",
    "SupplyChainEngine",
    "SkuMasterProvider",
    "InMemorySalesHistoryProvider",
    "InMemorySkuMasterProvider",
    "RestockDecision",
    "DEFAULT_SERVICE_LEVEL",
    "LTVEngine",
    "Segment",
    "InMemoryCustomerFeatureProvider",
    "SEGMENT_HIGH_VALUE",
    "SEGMENT_GROWTH",
    "SEGMENT_CHURN_RISK",
    "DEFAULT_LTV_HIGH_THRESHOLD",
    "DEFAULT_CHURN_RISK_THRESHOLD",
    "HealthDataHub",
    "HealthMetricRepository",
    "InMemoryHealthMetricRepository",
    "HealthDataValidationError",
    "HealthDataIngestTimeoutError",
    "HEALTH_DATA_INGESTED_EVENT",
    "INGEST_DEADLINE_SECONDS",
    # 订阅引擎（任务 14.1）
    "SubscriptionEngine",
    "PlanSpec",
    "Plan",
    "BillingCycle",
    "ChargeOutcome",
    "BillingFailure",
    "BillingReport",
    "PlanStore",
    "SubscriptionStore",
    "PaymentGateway",
    "EventPublisher",
    "InMemoryPlanStore",
    "InMemorySubscriptionStore",
    "SUBSCRIPTION_BILLED_EVENT",
    "ACTIVE_STATUS",
    "MIN_PLAN_AMOUNT",
    "MAX_PLAN_AMOUNT",
]


# 订阅引擎 HITL 审批闸门（任务 14.1，Requirements 8.3 / 8.5）——追加导出。
from app.engines.subscription import (  # noqa: E402
    AllowAllApprovalGate,
    ApprovalGate,
    CallableApprovalGate,
    DenyAllApprovalGate,
)

__all__ += [
    "ApprovalGate",
    "DenyAllApprovalGate",
    "AllowAllApprovalGate",
    "CallableApprovalGate",
]


# 生态合作网络：转介绍动作构造与写入（任务 17.1，Requirement 14）——追加导出。
from app.engines.ecosystem import (  # noqa: E402
    AllowAllReferralApprovalGate,
    CallableReferralApprovalGate,
    CustomerDirectory,
    DenyAllReferralApprovalGate,
    EcosystemNetwork,
    HEALTH_ALERT_EVENT,
    HIGH_ALERT_LEVEL,
    InMemoryCustomerDirectory,
    InMemoryPartnerHospitalProvider,
    InMemoryPetDirectory,
    InMemoryReferralStore,
    NoMatchingPartnerError,
    PartnerHospital,
    PartnerHospitalProvider,
    PetDirectory,
    REFERRAL_CREATED_EVENT,
    REFERRAL_DEADLINE_SECONDS,
    ReferralAction,
    ReferralApprovalGate,
    ReferralOutcome,
    ReferralStatus,
    ReferralStore,
)

__all__ += [
    "EcosystemNetwork",
    "PartnerHospital",
    "ReferralAction",
    "ReferralOutcome",
    "ReferralStatus",
    "PartnerHospitalProvider",
    "CustomerDirectory",
    "PetDirectory",
    "ReferralStore",
    "ReferralApprovalGate",
    "DenyAllReferralApprovalGate",
    "AllowAllReferralApprovalGate",
    "CallableReferralApprovalGate",
    "InMemoryPartnerHospitalProvider",
    "InMemoryCustomerDirectory",
    "InMemoryPetDirectory",
    "InMemoryReferralStore",
    "NoMatchingPartnerError",
    "REFERRAL_CREATED_EVENT",
    "HEALTH_ALERT_EVENT",
    "HIGH_ALERT_LEVEL",
    "REFERRAL_DEADLINE_SECONDS",
]


# 排期引擎：可用性检查与备选时段建议（任务 26.3，Requirements 22 / 23）——追加导出。
from app.engines.scheduling import (  # noqa: E402
    AppointmentProvider,
    BusinessHoursProvider,
    DEFAULT_SEARCH_HORIZON_DAYS,
    DEFAULT_SLOT_MINUTES,
    DEFAULT_SUGGESTION_COUNT,
    InMemoryAppointmentProvider,
    InMemoryBusinessHoursProvider,
    InMemoryResourceProvider,
    OCCUPYING_STATUSES,
    ResourceProvider,
    SchedulingEngine,
    SlotAvailability,
)

__all__ += [
    "SchedulingEngine",
    "SlotAvailability",
    "BusinessHoursProvider",
    "ResourceProvider",
    "AppointmentProvider",
    "InMemoryBusinessHoursProvider",
    "InMemoryResourceProvider",
    "InMemoryAppointmentProvider",
    "DEFAULT_SLOT_MINUTES",
    "DEFAULT_SEARCH_HORIZON_DAYS",
    "DEFAULT_SUGGESTION_COUNT",
    "OCCUPYING_STATUSES",
]


# 排期引擎：原子预约 book_appointment（任务 26.4，Requirements 22 / 23 / 24）——追加导出。
from app.engines.scheduling import (  # noqa: E402
    APPOINTMENT_BOOKED_EVENT,
    APPOINTMENT_REJECTED_FULL_EVENT,
    AppointmentWriter,
    BookingEventPublisher,
    InMemoryTransactionalSlotStore,
    OutOfBusinessHoursError,
    SlotFullError,
    SlotLockManager,
)

__all__ += [
    "APPOINTMENT_BOOKED_EVENT",
    "APPOINTMENT_REJECTED_FULL_EVENT",
    "OutOfBusinessHoursError",
    "SlotFullError",
    "SlotLockManager",
    "AppointmentWriter",
    "BookingEventPublisher",
    "InMemoryTransactionalSlotStore",
]


# 排期引擎 PostgreSQL 后端提供者（任务 26 真实数据接线）——追加导出。
from app.engines.scheduling_db import (  # noqa: E402
    DbAppointmentProvider,
    DbAppointmentWriter,
    DbBusinessHoursProvider,
    DbCustomerPetResolver,
    DbResourceProvider,
    DbSchedulingComponents,
    DbSlotLockManager,
    PetResolution,
    build_db_scheduling_engine,
)

__all__ += [
    "DbBusinessHoursProvider",
    "DbResourceProvider",
    "DbAppointmentProvider",
    "DbSlotLockManager",
    "DbAppointmentWriter",
    "DbCustomerPetResolver",
    "PetResolution",
    "DbSchedulingComponents",
    "build_db_scheduling_engine",
]
