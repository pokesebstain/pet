"""领域层公共异常类型。

集中定义算法层与业务引擎共享的错误类型，避免在各模块中重复定义。
"""

from __future__ import annotations


class PetOpsError(Exception):
    """PetOps 领域错误基类。"""


class ParameterInvalidError(PetOpsError, ValueError):
    """参数无效错误。

    当调用方传入非法、越界或缺失的参数时抛出（如 ``age_months`` 越界、
    缺少物种/品种、物种不受支持等）。同时继承 :class:`ValueError`，
    以兼容常见的 ``except ValueError`` 处理路径。
    """


class TenantContextMissingError(PetOpsError):
    """租户上下文缺失错误。

    当数据访问所需的租户上下文缺失或 ``tenant_id`` 为空（None、空串或纯空白）时抛出。
    用于在数据库/工具层拒绝无租户上下文的调用，避免绕过行级安全（RLS）导致跨租户
    数据泄露（Requirements 5.1、5.4）。
    """


class TenantIsolationError(PetOpsError):
    """租户隔离违规错误。

    当数据访问结果集中出现 ``tenant_id`` 不等于请求上下文 ``tenant_id`` 的记录时抛出。
    工具层（任务 7.1）在返回结果前对每条记录做租户校验，一旦发现越界记录即阻断整个
    结果集的返回并抛出本错误，作为 PostgreSQL 行级安全（RLS）之上的纵深防御，杜绝
    跨租户数据泄露（Requirements 5.2、5.5、Correctness Property 1）。
    """


class ResultTruncatedError(PetOpsError):
    """结果集超限错误（保留供严格模式使用）。

    默认工具层对超过上限的结果集采取截断并打标策略而非报错；本错误类型保留给需要以
    硬失败方式对待超限结果的调用方（Requirements 2.7）。
    """
