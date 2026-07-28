"""Agent 决策链全链路追溯（LangSmith / LangFuse）。

对应设计文档 "Property 10: 事件可追溯（Event Traceability）" 与 Requirement 18：

- 18.2：WHEN Supervisor 或任一 Expert_Agent 产生决策，THE Observability SHALL 为该
  决策链留存包含 **关联 trace ID、请求输入、参与决策的各 Agent 标识、各决策节点输出
  与各节点起止时间戳** 的追溯记录。
- 18.3：THE Observability SHALL 将每条决策追溯记录 **至少保留 180 天**。

设计要点
--------
- **后端抽象**：真实环境写入 LangSmith / LangFuse，但为可测试性将其隐藏在
  :class:`TracingBackend` 接口之后。测试使用 :class:`InMemoryTracingBackend`（进程内
  记录器），无需任何外部服务。
- **决策链模型**：一条决策链（:class:`DecisionTrace`）由若干节点跨度
  （:class:`NodeSpan`）组成，每个跨度记录节点名、Agent 标识、输入、输出与起止时间戳。
- **采集方式**：通过 :class:`DecisionChainTracer` 提供的上下文管理器 :meth:`trace`
  开启一条决策链，并借助 :meth:`DecisionChain.span` 上下文管理器或 :func:`traced_node`
  装饰器包裹 Supervisor / 各专家 Agent 节点执行以自动捕获跨度。
- **保留策略**：:class:`RetentionConfig` 强制保留天数 ≥ 180（需求 18.3）。
"""

from __future__ import annotations

import functools
import uuid
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Iterator, Protocol, TypeVar, runtime_checkable

from app.observability.errors import RetentionPolicyError, TraceBackendError

__all__ = [
    "DEFAULT_RETENTION_DAYS",
    "MIN_RETENTION_DAYS",
    "RetentionConfig",
    "NodeSpan",
    "DecisionTrace",
    "SpanHandle",
    "DecisionChain",
    "TracingBackend",
    "InMemoryTracingBackend",
    "ExternalTracingClient",
    "LangSmithBackend",
    "LangFuseBackend",
    "get_tracing_backend",
    "DecisionChainTracer",
    "traced_node",
    "current_chain",
]

# --- 保留策略（需求 18.3）--------------------------------------------------
#: 合规要求的最小保留天数。
MIN_RETENTION_DAYS = 180
#: 默认保留天数（等于合规下限）。
DEFAULT_RETENTION_DAYS = MIN_RETENTION_DAYS


def _utcnow() -> datetime:
    """默认时钟：返回带时区的 UTC 当前时间。"""
    return datetime.now(timezone.utc)


Clock = Callable[[], datetime]
IdFactory = Callable[[], str]


@dataclass(frozen=True)
class RetentionConfig:
    """决策追溯记录的保留配置（需求 18.3）。

    Attributes:
        retention_days: 追溯记录保留天数，必须 ≥ :data:`MIN_RETENTION_DAYS`（180）。

    Raises:
        RetentionPolicyError: 当 ``retention_days`` 低于合规下限时。
    """

    retention_days: int = DEFAULT_RETENTION_DAYS

    def __post_init__(self) -> None:
        if not isinstance(self.retention_days, int) or isinstance(self.retention_days, bool):
            raise RetentionPolicyError("retention_days 必须为整数天数")
        if self.retention_days < MIN_RETENTION_DAYS:
            raise RetentionPolicyError(
                f"追溯记录保留天数必须 ≥ {MIN_RETENTION_DAYS} 天（需求 18.3），"
                f"当前为 {self.retention_days} 天"
            )


# --- 决策链数据模型 --------------------------------------------------------
@dataclass
class NodeSpan:
    """决策链中的单个节点跨度。

    记录 Supervisor 或某个专家 Agent 单个决策节点的执行信息（需求 18.2）：
    节点名、Agent 标识、输入、输出，以及起止时间戳。
    """

    node: str
    agent: str
    input: Any = None
    output: Any = None
    started_at: datetime = field(default_factory=_utcnow)
    ended_at: datetime | None = None
    error: str | None = None

    @property
    def duration_seconds(self) -> float | None:
        """节点耗时（秒）；未结束时返回 ``None``。"""
        if self.ended_at is None:
            return None
        return (self.ended_at - self.started_at).total_seconds()

    @property
    def is_complete(self) -> bool:
        """跨度是否已记录结束时间戳。"""
        return self.ended_at is not None

    def to_dict(self) -> dict[str, Any]:
        """序列化为可上报字典（用于外部后端）。"""
        return {
            "node": self.node,
            "agent": self.agent,
            "input": _safe(self.input),
            "output": _safe(self.output),
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "duration_seconds": self.duration_seconds,
            "error": self.error,
        }


@dataclass
class DecisionTrace:
    """一条完整的 Agent 决策链追溯记录（需求 18.2）。"""

    trace_id: str
    request_input: Any
    tenant_id: str | None = None
    #: 会话线程标识（对应 Requirement 3 的 ``thread_id``），用于在外部后端将同一多轮
    #: 会话的各轮决策链关联展示；不影响 ``trace_id`` 的唯一性。
    session_id: str | None = None
    #: 本轮决策链的最终输出摘要（如聚合后的 ``final_answer``）；可选。
    output: Any = None
    spans: list[NodeSpan] = field(default_factory=list)
    created_at: datetime = field(default_factory=_utcnow)

    @property
    def agents(self) -> list[str]:
        """参与决策的各 Agent 标识（按首次出现顺序去重）。"""
        seen: dict[str, None] = {}
        for span in self.spans:
            seen.setdefault(span.agent, None)
        return list(seen)

    @property
    def is_complete(self) -> bool:
        """是否所有节点跨度均已结束（决策链完整）。"""
        return bool(self.spans) and all(s.is_complete for s in self.spans)

    def to_dict(self) -> dict[str, Any]:
        """序列化为可上报字典（用于外部后端）。"""
        return {
            "trace_id": self.trace_id,
            "tenant_id": self.tenant_id,
            "session_id": self.session_id,
            "request_input": _safe(self.request_input),
            "output": _safe(self.output),
            "agents": self.agents,
            "created_at": self.created_at.isoformat(),
            "spans": [s.to_dict() for s in self.spans],
        }


def _safe(obj: Any) -> Any:
    """尽力将任意对象转换为可 JSON 序列化的形态，失败则回退为 ``repr``。"""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {str(k): _safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_safe(v) for v in obj]
    if isinstance(obj, datetime):
        return obj.isoformat()
    return repr(obj)


# --- 跨度采集句柄 ----------------------------------------------------------
class SpanHandle:
    """在 :meth:`DecisionChain.span` 上下文中设置节点输出的句柄。"""

    def __init__(self, span: NodeSpan) -> None:
        self._span = span

    @property
    def span(self) -> NodeSpan:
        return self._span

    def set_output(self, output: Any) -> None:
        """记录节点输出。"""
        self._span.output = output

    def set_input(self, value: Any) -> None:
        """（可选）覆盖节点输入。"""
        self._span.input = value


class DecisionChain:
    """进行中的决策链，负责收集各节点跨度并生成 :class:`DecisionTrace`。"""

    def __init__(
        self,
        trace_id: str,
        request_input: Any,
        tenant_id: str | None = None,
        clock: Clock = _utcnow,
        session_id: str | None = None,
    ) -> None:
        self.trace_id = trace_id
        self.request_input = request_input
        self.tenant_id = tenant_id
        self.session_id = session_id
        self.output: Any = None
        self._clock = clock
        self._created_at = clock()
        self._spans: list[NodeSpan] = []

    def set_output(self, output: Any) -> None:
        """记录本轮决策链的最终输出摘要（如聚合后的 ``final_answer``）。"""
        self.output = output

    @property
    def spans(self) -> list[NodeSpan]:
        return list(self._spans)

    @contextmanager
    def span(self, node: str, agent: str, input: Any = None) -> Iterator[SpanHandle]:
        """包裹单个节点执行，自动记录起止时间戳，异常时记录错误后重抛。"""
        node_span = NodeSpan(
            node=node,
            agent=agent,
            input=input,
            started_at=self._clock(),
        )
        handle = SpanHandle(node_span)
        try:
            yield handle
        except Exception as exc:  # noqa: BLE001 - 记录后原样重抛
            node_span.error = repr(exc)
            raise
        finally:
            node_span.ended_at = self._clock()
            self._spans.append(node_span)

    def to_trace(self) -> DecisionTrace:
        """快照当前决策链为不可变追溯记录。"""
        trace = DecisionTrace(
            trace_id=self.trace_id,
            request_input=self.request_input,
            tenant_id=self.tenant_id,
            session_id=self.session_id,
            output=self.output,
            spans=list(self._spans),
        )
        trace.created_at = self._created_at
        return trace


# --- 后端抽象（隐藏 LangSmith / LangFuse）----------------------------------
@runtime_checkable
class TracingBackend(Protocol):
    """决策链追溯后端接口。

    真实实现写入 LangSmith / LangFuse；测试使用 :class:`InMemoryTracingBackend`。
    """

    def record(self, trace: DecisionTrace) -> None:
        """持久化一条决策链追溯记录。"""
        ...

    def get_trace(self, trace_id: str) -> DecisionTrace | None:
        """按 trace ID 读取追溯记录；不存在返回 ``None``。"""
        ...

    def list_traces(self) -> list[DecisionTrace]:
        """列出全部追溯记录。"""
        ...


class InMemoryTracingBackend:
    """进程内追溯记录器，供测试与本地开发使用（无外部依赖）。

    同时按 :class:`RetentionConfig` 提供保留期裁剪能力：:meth:`prune` 仅移除超过
    保留天数的记录，从而保证记录 **至少保留** 配置的天数（需求 18.3）。
    """

    def __init__(self, retention: RetentionConfig | None = None, clock: Clock = _utcnow) -> None:
        self.retention = retention or RetentionConfig()
        self._clock = clock
        self._traces: dict[str, DecisionTrace] = {}

    def record(self, trace: DecisionTrace) -> None:
        self._traces[trace.trace_id] = trace

    def get_trace(self, trace_id: str) -> DecisionTrace | None:
        return self._traces.get(trace_id)

    def list_traces(self) -> list[DecisionTrace]:
        return list(self._traces.values())

    def __len__(self) -> int:
        return len(self._traces)

    def prune(self) -> int:
        """移除超过保留期的记录，返回被移除的数量。

        仅当记录的 ``created_at`` 早于 ``now - retention_days`` 时才移除，
        因此保留期内（≥180 天）的记录始终不会被裁剪。
        """
        now = self._clock()
        cutoff_seconds = self.retention.retention_days * 86400
        expired = [
            tid
            for tid, tr in self._traces.items()
            if (now - tr.created_at).total_seconds() > cutoff_seconds
        ]
        for tid in expired:
            del self._traces[tid]
        return len(expired)


@runtime_checkable
class ExternalTracingClient(Protocol):
    """外部追溯服务（LangSmith / LangFuse）客户端最小接口。

    通过该协议将具体 SDK 与本模块解耦：真实客户端只需实现 ``submit_trace``，
    即可被 :class:`LangSmithBackend` / :class:`LangFuseBackend` 适配。
    """

    def submit_trace(self, payload: dict[str, Any]) -> None:
        """上报一条序列化后的追溯记录。"""
        ...


class _ExternalBackend:
    """外部追溯后端基类：将 :class:`DecisionTrace` 序列化后交由客户端上报。"""

    #: 子类覆盖为后端名称，便于日志与诊断。
    backend_name = "external"

    def __init__(self, client: ExternalTracingClient, retention: RetentionConfig | None = None) -> None:
        self.client = client
        self.retention = retention or RetentionConfig()

    def record(self, trace: DecisionTrace) -> None:
        try:
            self.client.submit_trace(trace.to_dict())
        except Exception as exc:  # noqa: BLE001 - 归一化为可观测性错误
            raise TraceBackendError(
                f"{self.backend_name} 追溯上报失败: {exc!r}"
            ) from exc

    def get_trace(self, trace_id: str) -> DecisionTrace | None:  # pragma: no cover - 外部查询不在本任务范围
        raise TraceBackendError(f"{self.backend_name} 后端不支持进程内读取，请使用其控制台查询")

    def list_traces(self) -> list[DecisionTrace]:  # pragma: no cover
        raise TraceBackendError(f"{self.backend_name} 后端不支持进程内枚举，请使用其控制台查询")


class LangSmithBackend(_ExternalBackend):
    """LangSmith 追溯后端适配器。"""

    backend_name = "langsmith"


class LangFuseBackend(_ExternalBackend):
    """LangFuse 追溯后端适配器。"""

    backend_name = "langfuse"


def get_tracing_backend(
    provider: str = "memory",
    *,
    client: ExternalTracingClient | None = None,
    retention: RetentionConfig | None = None,
) -> TracingBackend:
    """按名称构造追溯后端工厂。

    Args:
        provider: ``"memory"``（默认，进程内）/ ``"langsmith"`` / ``"langfuse"``。
        client: 外部后端所需的客户端实例（``langsmith`` / ``langfuse`` 时必填）。
        retention: 保留配置；缺省使用合规默认（180 天）。

    Returns:
        TracingBackend: 对应后端实例。
    """
    key = provider.strip().lower()
    if key == "memory":
        return InMemoryTracingBackend(retention=retention)
    if key in ("langsmith", "langfuse"):
        if client is None:
            raise TraceBackendError(f"{key} 后端需要提供 client 实例")
        backend_cls = LangSmithBackend if key == "langsmith" else LangFuseBackend
        return backend_cls(client=client, retention=retention)
    raise TraceBackendError(f"未知的追溯后端: {provider!r}")


# --- 活动决策链上下文（供装饰器使用）--------------------------------------
_active_chain: ContextVar[DecisionChain | None] = ContextVar(
    "petops_active_decision_chain", default=None
)


def current_chain() -> DecisionChain | None:
    """返回当前上下文中活动的决策链；无则返回 ``None``。"""
    return _active_chain.get()


F = TypeVar("F", bound=Callable[..., Any])


def traced_node(agent: str, node: str | None = None) -> Callable[[F], F]:
    """装饰器：将被包裹的节点函数执行记录为当前决策链的一个跨度。

    若当前上下文无活动决策链（未在 :meth:`DecisionChainTracer.trace` 内），则直接
    透传执行、不产生跨度，从而不影响非追溯路径。

    Args:
        agent: Agent 标识（如 ``"supervisor"``、``"health_agent"``）。
        node: 节点名；缺省取被装饰函数名。
    """

    def decorator(fn: F) -> F:
        span_node = node or fn.__name__

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            chain = current_chain()
            if chain is None:
                return fn(*args, **kwargs)
            captured_input = {"args": list(args), "kwargs": dict(kwargs)}
            with chain.span(node=span_node, agent=agent, input=captured_input) as handle:
                result = fn(*args, **kwargs)
                handle.set_output(result)
                return result

        return wrapper  # type: ignore[return-value]

    return decorator


# --- 顶层追溯器 ------------------------------------------------------------
class DecisionChainTracer:
    """决策链追溯器：开启决策链、采集跨度并落库到后端。

    典型用法::

        tracer = DecisionChainTracer(InMemoryTracingBackend())
        with tracer.trace(request_input=user_msg, tenant_id="store_1") as chain:
            with chain.span(node="intent", agent="supervisor", input=user_msg) as h:
                intent = classify(user_msg)
                h.set_output(intent)
            # ... 各专家 Agent 节点 ...
    """

    def __init__(
        self,
        backend: TracingBackend | None = None,
        *,
        retention: RetentionConfig | None = None,
        clock: Clock = _utcnow,
        id_factory: IdFactory | None = None,
    ) -> None:
        self.retention = retention or RetentionConfig()
        self.backend = (
            backend
            if backend is not None
            else InMemoryTracingBackend(retention=self.retention)
        )
        self._clock = clock
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)

    def new_trace_id(self) -> str:
        """生成一个新的关联 trace ID。"""
        return self._id_factory()

    @contextmanager
    def trace(
        self,
        request_input: Any,
        tenant_id: str | None = None,
        trace_id: str | None = None,
        session_id: str | None = None,
    ) -> Iterator[DecisionChain]:
        """开启一条决策链上下文；退出时（含异常）将其记录到后端。

        Args:
            session_id: 可选会话线程标识（对应 Requirement 3 的 ``thread_id``），
                用于在外部后端（LangFuse）将同一多轮会话的各轮决策链关联展示。
        """
        chain = DecisionChain(
            trace_id=trace_id or self.new_trace_id(),
            request_input=request_input,
            tenant_id=tenant_id,
            clock=self._clock,
            session_id=session_id,
        )
        token: Token[DecisionChain | None] = _active_chain.set(chain)
        try:
            yield chain
        finally:
            _active_chain.reset(token)
            self.backend.record(chain.to_trace())
