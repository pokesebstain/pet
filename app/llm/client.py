"""云端 LLM 客户端（通义千问 / 智谱 GLM）。

对应设计文档 "Error Handling" / "Performance & Security" 与 Requirement 20
（错误处理与降级）。本模块实现 :class:`CloudLLMClient`，封装：

1. **提示工程 / 少样本调用接口**：将系统提示、少样本示例与用户输入组织为最终 prompt，
   经传输层调用 Cloud_LLM；统一超时（默认 10s）与错误类型（见 :mod:`app.llm.errors`）。
2. **指数退避重试**（Requirement 20.1）：初始 1s、每次翻倍、上限 8s、最多 3 次；
   重试耗尽后降级到受限模板查询。
3. **熔断**（Requirement 20.4）：60s 窗口内连续失败达到 5 次触发熔断，其后 30s 内
   后续请求直接降级到受限模板查询。
4. **受限模板查询降级**（Requirement 20.5）：受限模板无法匹配用户请求时返回请用户
   重述的提示。

范围约束（重要）：模型微调**不在本次范围**。本客户端为**云端 LLM 客户端**，仅通过
提示工程 / 少样本驱动；降级路径**不依赖任何本地 / 微调模型**，仅由熔断 + 指数退避 +
受限模板查询三者组合承担。

可测试性：
- 真实的 HTTP / SDK 调用被抽象在 :class:`LLMTransport` 协议之后，测试可注入伪实现，
  在无真实网络的情况下模拟超时 / 限流 / 连续失败。
- 时间通过 :class:`Clock` 协议注入（``now`` 与 ``sleep``），使退避 / 熔断相关测试可
  快速运行而无需真实等待。
"""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable

from app.core.config import LLMSettings, get_settings
from app.llm.errors import LLMError

logger = logging.getLogger(__name__)

__all__ = [
    "Clock",
    "SystemClock",
    "LLMTransport",
    "FewShotExample",
    "ResponseSource",
    "LLMResponse",
    "RestrictedTemplate",
    "RestrictedTemplateQuery",
    "CircuitBreaker",
    "CloudLLMClient",
    "RESTATE_PROMPT",
    "INITIAL_BACKOFF_SECONDS",
    "MAX_BACKOFF_SECONDS",
    "CIRCUIT_FAILURE_THRESHOLD",
    "CIRCUIT_WINDOW_SECONDS",
    "CIRCUIT_OPEN_SECONDS",
]

# --- 退避与熔断常量（Requirement 20.1 / 20.4）---------------------------------

#: 指数退避初始等待（秒）。
INITIAL_BACKOFF_SECONDS: float = 1.0
#: 指数退避上限（秒）。
MAX_BACKOFF_SECONDS: float = 8.0
#: 触发熔断的连续失败次数阈值。
CIRCUIT_FAILURE_THRESHOLD: int = 5
#: 连续失败计数的时间窗口（秒）。
CIRCUIT_WINDOW_SECONDS: float = 60.0
#: 熔断打开后的直接降级时长（秒）。
CIRCUIT_OPEN_SECONDS: float = 30.0

#: 受限模板无法匹配时返回的重述提示（Requirement 20.5）。
RESTATE_PROMPT: str = "抱歉，当前无法处理您的请求，请换一种说法重述您的问题。"


# --- 时钟抽象（便于快速测试退避 / 熔断）---------------------------------------


@runtime_checkable
class Clock(Protocol):
    """时间抽象：提供当前时间与休眠能力，便于注入伪时钟加速测试。"""

    def now(self) -> float:  # pragma: no cover - 协议声明
        """返回单调递增的当前时间（秒）。"""
        ...

    def sleep(self, seconds: float) -> None:  # pragma: no cover - 协议声明
        """休眠指定秒数（退避等待）。"""
        ...


class SystemClock:
    """基于系统时间的默认 :class:`Clock` 实现。"""

    def now(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        if seconds > 0:
            time.sleep(seconds)


# --- 传输层抽象（隔离真实 HTTP / SDK 调用）-----------------------------------


@runtime_checkable
class LLMTransport(Protocol):
    """Cloud_LLM 传输层协议。

    实现者负责真实的 HTTP / SDK 调用，并**必须**在超时 / 限流 / 不可用时抛出
    :mod:`app.llm.errors` 中定义的异常（``LLMTimeoutError`` / ``LLMRateLimitError`` /
    ``LLMUnavailableError``）。传输层需自行按 ``timeout`` 约束调用时长。

    范围约束：真实传输实现（通义 / GLM SDK）不在本任务范围内；本任务仅定义抽象接口，
    使测试可注入伪实现。
    """

    def generate(self, prompt: str, *, timeout: float) -> str:  # pragma: no cover - 协议声明
        """根据完整 prompt 生成文本；失败时抛出 :class:`~app.llm.errors.LLMError` 子类。"""
        ...


# --- 提示工程 / 少样本 -------------------------------------------------------


@dataclass(frozen=True)
class FewShotExample:
    """少样本示例：一对输入 / 期望输出，用于提示工程。"""

    user: str
    assistant: str


# --- 响应模型 ----------------------------------------------------------------


class ResponseSource(str, Enum):
    """响应来源，用于区分正常结果与各类降级结果。"""

    #: 由 Cloud_LLM 正常生成。
    LLM = "llm"
    #: 由受限模板查询降级生成。
    TEMPLATE = "template"
    #: 受限模板无法匹配，返回请用户重述的提示。
    RESTATE = "restate"


@dataclass(frozen=True)
class LLMResponse:
    """Cloud_LLM 调用结果。

    Attributes:
        text: 返回文本（正常结果、模板结果或重述提示）。
        source: 结果来源，见 :class:`ResponseSource`。
        degraded: 是否为降级结果（模板或重述均视为降级）。
        attempts: 实际发起的 Cloud_LLM 调用次数（含首次与重试）。
    """

    text: str
    source: ResponseSource
    degraded: bool
    attempts: int = 0


# --- 受限模板查询（降级路径）-------------------------------------------------


@dataclass(frozen=True)
class RestrictedTemplate:
    """单条受限模板：任一关键词命中用户输入即返回对应响应。

    Attributes:
        keywords: 触发关键词（大小写不敏感，子串匹配）。
        response: 命中后返回的固定响应文本。
    """

    keywords: tuple[str, ...]
    response: str


class RestrictedTemplateQuery:
    """受限模板查询：在 Cloud_LLM 不可用时提供有限的固定应答能力。

    仅依赖预置模板，**不依赖任何本地 / 微调模型**（符合范围约束）。当无任一模板匹配
    用户输入时，:meth:`match` 返回 ``None``，调用方据此返回请用户重述的提示。
    """

    def __init__(self, templates: Sequence[RestrictedTemplate] | None = None) -> None:
        self._templates: tuple[RestrictedTemplate, ...] = tuple(templates or ())

    def match(self, user_input: str) -> str | None:
        """返回首个命中模板的响应；无匹配时返回 ``None``。"""
        if not user_input:
            return None
        haystack = user_input.casefold()
        for template in self._templates:
            for keyword in template.keywords:
                if keyword and keyword.casefold() in haystack:
                    return template.response
        return None


# --- 熔断器 ------------------------------------------------------------------


class CircuitBreaker:
    """基于"时间窗口内连续失败次数"的熔断器（Requirement 20.4）。

    - 连续失败在 :data:`CIRCUIT_WINDOW_SECONDS` 窗口内达到
      :data:`CIRCUIT_FAILURE_THRESHOLD` 次即触发熔断。
    - 熔断打开后 :data:`CIRCUIT_OPEN_SECONDS` 内 :meth:`is_open` 返回 ``True``，
      调用方据此直接降级。
    - 任一成功即清零连续失败计数（"连续"语义）。
    - 冷却期过后自动恢复（半开 / 关闭），重新允许调用。
    """

    def __init__(
        self,
        *,
        clock: Clock,
        failure_threshold: int = CIRCUIT_FAILURE_THRESHOLD,
        window_seconds: float = CIRCUIT_WINDOW_SECONDS,
        open_seconds: float = CIRCUIT_OPEN_SECONDS,
    ) -> None:
        self._clock = clock
        self._failure_threshold = failure_threshold
        self._window_seconds = window_seconds
        self._open_seconds = open_seconds
        self._failures: list[float] = []
        self._open_until: float | None = None

    def is_open(self) -> bool:
        """当前是否处于熔断打开（应直接降级）状态。"""
        if self._open_until is None:
            return False
        if self._clock.now() < self._open_until:
            return True
        # 冷却期已过：恢复到关闭状态并清空计数。
        self._open_until = None
        self._failures.clear()
        return False

    def record_success(self) -> None:
        """记录一次成功调用：清零连续失败计数并关闭熔断。"""
        self._failures.clear()
        self._open_until = None

    def record_failure(self) -> None:
        """记录一次失败调用；达到阈值则打开熔断。"""
        now = self._clock.now()
        # 仅保留窗口内的连续失败时间戳。
        cutoff = now - self._window_seconds
        self._failures = [t for t in self._failures if t >= cutoff]
        self._failures.append(now)
        if len(self._failures) >= self._failure_threshold:
            self._open_until = now + self._open_seconds


# --- Cloud_LLM 客户端 --------------------------------------------------------


class CloudLLMClient:
    """云端 LLM 客户端，封装提示工程、重试退避、熔断与受限模板降级。

    典型用法::

        client = CloudLLMClient(transport=my_transport)
        result = client.complete("上个月销售额多少?", examples=[...])
        if result.degraded:
            ...  # 已降级到模板 / 重述

    所有外部依赖（传输层、时钟、受限模板）均可注入，便于测试。
    """

    def __init__(
        self,
        transport: LLMTransport,
        *,
        template_query: RestrictedTemplateQuery | None = None,
        clock: Clock | None = None,
        settings: LLMSettings | None = None,
        timeout_seconds: float | None = None,
        max_retries: int | None = None,
    ) -> None:
        resolved = settings or get_settings().llm
        self._transport = transport
        self._clock = clock or SystemClock()
        self._templates = template_query or RestrictedTemplateQuery()
        self._timeout = (
            timeout_seconds if timeout_seconds is not None else resolved.timeout_seconds
        )
        self._max_retries = (
            max_retries if max_retries is not None else resolved.max_retries
        )
        self._circuit = CircuitBreaker(clock=self._clock)

    # -- 提示工程 / 少样本 ----------------------------------------------------

    @staticmethod
    def build_prompt(
        user_input: str,
        *,
        system_prompt: str | None = None,
        examples: Sequence[FewShotExample] | None = None,
    ) -> str:
        """将系统提示、少样本示例与用户输入组织为单个 prompt 字符串。"""
        parts: list[str] = []
        if system_prompt:
            parts.append(f"System: {system_prompt}")
        for example in examples or ():
            parts.append(f"User: {example.user}")
            parts.append(f"Assistant: {example.assistant}")
        parts.append(f"User: {user_input}")
        parts.append("Assistant:")
        return "\n".join(parts)

    # -- 主调用入口 -----------------------------------------------------------

    def complete(
        self,
        user_input: str,
        *,
        system_prompt: str | None = None,
        examples: Sequence[FewShotExample] | None = None,
    ) -> LLMResponse:
        """调用 Cloud_LLM 生成回答；失败时按退避重试并在必要时降级。

        Args:
            user_input: 用户自然语言输入。
            system_prompt: 可选的系统提示（提示工程）。
            examples: 可选的少样本示例。

        Returns:
            LLMResponse: 正常结果（``source=LLM``）或降级结果
            （``source=TEMPLATE`` / ``RESTATE``，``degraded=True``）。
        """
        # 熔断打开：直接降级，不发起任何调用（Requirement 20.4）。
        if self._circuit.is_open():
            logger.warning("云端 LLM 熔断已打开，直接降级（不发起调用）。")
            return self._degrade(user_input, attempts=0)

        prompt = self.build_prompt(
            user_input, system_prompt=system_prompt, examples=examples
        )

        attempts = 0
        backoff = INITIAL_BACKOFF_SECONDS
        # 首次调用 + 最多 max_retries 次重试。
        for attempt_index in range(self._max_retries + 1):
            attempts += 1
            try:
                text = self._transport.generate(prompt, timeout=self._timeout)
            except LLMError as exc:
                # 记录真实失败原因（超时 / 限流 / 网络错误等），否则调用方只会看到
                # 静默降级结果，无法定位云端 LLM 侧的真实问题（如配置错误、鉴权失败）。
                logger.warning(
                    "云端 LLM 调用失败（第 %d 次尝试）：%s: %s",
                    attempts,
                    type(exc).__name__,
                    exc,
                )
                # 每次失败计入熔断连续失败计数。
                self._circuit.record_failure()
                # 熔断在本次失败后打开：立即停止重试并降级。
                if self._circuit.is_open():
                    break
                # 仍有剩余重试次数：按指数退避等待后重试。
                if attempt_index < self._max_retries:
                    self._clock.sleep(backoff)
                    backoff = min(backoff * 2.0, MAX_BACKOFF_SECONDS)
                # 否则重试耗尽，退出循环进入降级。
            else:
                self._circuit.record_success()
                return LLMResponse(
                    text=text,
                    source=ResponseSource.LLM,
                    degraded=False,
                    attempts=attempts,
                )

        # 重试耗尽或熔断打开：降级到受限模板查询（Requirement 20.1 / 20.4）。
        return self._degrade(user_input, attempts=attempts)

    # -- 降级路径 -------------------------------------------------------------

    def _degrade(self, user_input: str, *, attempts: int) -> LLMResponse:
        """降级到受限模板查询；无匹配时返回请用户重述的提示（Requirement 20.5）。"""
        matched = self._templates.match(user_input)
        if matched is not None:
            return LLMResponse(
                text=matched,
                source=ResponseSource.TEMPLATE,
                degraded=True,
                attempts=attempts,
            )
        return LLMResponse(
            text=RESTATE_PROMPT,
            source=ResponseSource.RESTATE,
            degraded=True,
            attempts=attempts,
        )
