"""云端 LLM 客户端共享异常类型。

集中定义 Cloud_LLM（通义千问 / 智谱 GLM）调用层复用的错误类型，使传输层
（HTTP / SDK）对"超时""限流""不可用"等外部瞬时故障抛出一致、可被客户端识别
并纳入重试 / 退避 / 熔断处理的异常。

范围约束：本次不含任何本地微调模型，降级路径仅由"受限模板查询"承担，
不依赖任何本地 / 微调模型。
"""

from __future__ import annotations

from app.core.errors import PetOpsError


class LLMError(PetOpsError):
    """Cloud_LLM 调用错误基类。

    所有继承自本类的异常均视为**可重试的外部瞬时故障**：客户端会按指数退避重试，
    并将每次失败计入熔断器的连续失败计数。
    """


class LLMTimeoutError(LLMError):
    """Cloud_LLM 调用超时错误（对应 Requirement 20.1：调用超过 10 秒超时）。"""


class LLMRateLimitError(LLMError):
    """Cloud_LLM 调用被限流错误（对应 Requirement 20.1：被限流）。"""


class LLMUnavailableError(LLMError):
    """Cloud_LLM 服务不可用错误（网络错误、5xx 等外部瞬时故障）。"""
