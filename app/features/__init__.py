"""特征存储 Feature Store 包（对应设计文档 7.2，Requirement 19）。

为 LTV / churn / demand 模型提供统一的在线（Redis）/ 离线（DB）特征读写，
保证在线-离线一致性、缺失默认打标与离线回填、以及在线不可用时的降级回退。

统一从本包顶层导入，例如::

    from app.features import FeatureStore, FeatureVector
"""

from app.models.timeseries import FeatureVector

from app.features.store import (
    DEFAULT_FEATURE_GROUP,
    DEFAULT_FEATURE_VALUE,
    BackfillHandler,
    BackfillRequest,
    FeatureFetchResult,
    FeatureNotFoundError,
    FeatureStore,
    FeatureStoreError,
    InMemoryOfflineBackend,
    InMemoryOnlineBackend,
    OfflineFeatureBackend,
    OnlineBackendUnavailable,
    OnlineFeatureBackend,
    RedisOnlineBackend,
)

__all__ = [
    # 主入口
    "FeatureStore",
    "FeatureVector",
    # 结果 / 回填
    "FeatureFetchResult",
    "BackfillRequest",
    "BackfillHandler",
    # 后端协议与实现
    "OnlineFeatureBackend",
    "OfflineFeatureBackend",
    "InMemoryOnlineBackend",
    "InMemoryOfflineBackend",
    "RedisOnlineBackend",
    # 常量
    "DEFAULT_FEATURE_VALUE",
    "DEFAULT_FEATURE_GROUP",
    # 异常
    "FeatureStoreError",
    "OnlineBackendUnavailable",
    "FeatureNotFoundError",
]
