"""可观测性层错误类型。

集中定义决策链追溯（LangSmith / LangFuse）相关的错误，避免与业务层耦合。
"""

from __future__ import annotations

from app.core.errors import PetOpsError


class ObservabilityError(PetOpsError):
    """可观测性层错误基类。"""


class RetentionPolicyError(ObservabilityError, ValueError):
    """追溯记录保留策略非法错误。

    当配置的保留天数低于合规下限（见 :data:`app.observability.tracing.MIN_RETENTION_DAYS`）
    时抛出。需求 18.3 要求每条决策追溯记录至少保留 180 天。
    """


class TraceBackendError(ObservabilityError):
    """追溯后端（LangSmith / LangFuse 等）写入 / 读取失败错误。"""
