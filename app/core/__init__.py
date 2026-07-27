"""核心基础设施：配置加载、RLS 上下文、公共工具与领域异常。"""

from app.core.errors import ParameterInvalidError, PetOpsError

__all__ = [
    "PetOpsError",
    "ParameterInvalidError",
]

# 任务 7.1：工具层租户隔离相关异常（追加导出，便于统一从 app.core 引用）。
from app.core.errors import (  # noqa: E402
    ResultTruncatedError,
    TenantContextMissingError,
    TenantIsolationError,
)

__all__ += [
    "TenantContextMissingError",
    "TenantIsolationError",
    "ResultTruncatedError",
]
