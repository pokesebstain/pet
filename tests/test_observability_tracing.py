"""任务 23.1 决策链追溯（LangSmith / LangFuse）的单元测试。

使用进程内后端（:class:`InMemoryTracingBackend`），无需任何外部服务，验证：
- 决策链留存关联 trace ID、请求输入、参与决策的各 Agent 标识、各节点输出与起止
  时间戳（需求 18.2）。
- 保留策略强制 ≥ 180 天（需求 18.3）。
- 上下文管理器与装饰器均能捕获跨度；异常路径记录错误后重抛。
- 外部后端（LangSmith / LangFuse）经客户端接口上报，与决策链模型解耦。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from itertools import count

import pytest

from app.observability import (
    DEFAULT_RETENTION_DAYS,
    MIN_RETENTION_DAYS,
    DecisionChainTracer,
    DecisionTrace,
    InMemoryTracingBackend,
    LangFuseBackend,
    LangSmithBackend,
    RetentionConfig,
    RetentionPolicyError,
    TraceBackendError,
    current_chain,
    get_tracing_backend,
    traced_node,
)


# --- 保留策略（需求 18.3）-------------------------------------------------
def test_default_retention_is_180_days() -> None:
    assert DEFAULT_RETENTION_DAYS == 180
    assert MIN_RETENTION_DAYS == 180
    assert RetentionConfig().retention_days == 180


def test_retention_at_or_above_minimum_ok() -> None:
    assert RetentionConfig(retention_days=180).retention_days == 180
    assert RetentionConfig(retention_days=365).retention_days == 365


def test_retention_below_minimum_rejected() -> None:
    with pytest.raises(RetentionPolicyError):
        RetentionConfig(retention_days=179)
    with pytest.raises(RetentionPolicyError):
        RetentionConfig(retention_days=0)


# --- 决策链留存内容（需求 18.2）------------------------------------------
def test_trace_records_all_required_fields() -> None:
    backend = InMemoryTracingBackend()
    tracer = DecisionChainTracer(backend, id_factory=lambda: "trace-1")

    with tracer.trace(request_input={"q": "为什么销量下降"}, tenant_id="store_1") as chain:
        with chain.span(node="intent", agent="supervisor", input="raw") as h:
            h.set_output({"intent": "analysis"})
        with chain.span(node="analyze", agent="analysis_agent", input="raw") as h:
            h.set_output({"insight": "客单价下滑"})

    trace = backend.get_trace("trace-1")
    assert trace is not None
    # 关联 trace ID + 请求输入 + tenant
    assert trace.trace_id == "trace-1"
    assert trace.request_input == {"q": "为什么销量下降"}
    assert trace.tenant_id == "store_1"
    # 参与决策的各 Agent 标识
    assert trace.agents == ["supervisor", "analysis_agent"]
    # 各节点输出与起止时间戳
    assert [s.node for s in trace.spans] == ["intent", "analyze"]
    assert trace.spans[0].output == {"intent": "analysis"}
    assert trace.spans[1].output == {"insight": "客单价下滑"}
    for span in trace.spans:
        assert isinstance(span.started_at, datetime)
        assert isinstance(span.ended_at, datetime)
        assert span.ended_at >= span.started_at
        assert span.duration_seconds is not None
    assert trace.is_complete is True


def test_trace_auto_generates_id_when_absent() -> None:
    tracer = DecisionChainTracer(id_factory=lambda: "auto-xyz")
    with tracer.trace(request_input="hi") as chain:
        assert chain.trace_id == "auto-xyz"


def test_span_records_error_and_reraises() -> None:
    backend = InMemoryTracingBackend()
    tracer = DecisionChainTracer(backend, id_factory=lambda: "trace-err")

    with pytest.raises(ValueError):
        with tracer.trace(request_input="x") as chain:
            with chain.span(node="boom", agent="supervisor"):
                raise ValueError("模型不可用")

    # 即便节点抛错，决策链仍被记录，且跨度含错误与结束时间戳。
    trace = backend.get_trace("trace-err")
    assert trace is not None
    assert len(trace.spans) == 1
    span = trace.spans[0]
    assert "模型不可用" in (span.error or "")
    assert span.ended_at is not None


# --- 装饰器采集 -----------------------------------------------------------
def test_traced_node_decorator_captures_span() -> None:
    backend = InMemoryTracingBackend()
    tracer = DecisionChainTracer(backend, id_factory=lambda: "trace-deco")

    @traced_node(agent="health_agent", node="detect")
    def detect(payload: dict) -> dict:
        return {"level": "high", "pet": payload["pet"]}

    with tracer.trace(request_input="req"):
        assert current_chain() is not None
        result = detect({"pet": "p-1"})

    assert result == {"level": "high", "pet": "p-1"}
    trace = backend.get_trace("trace-deco")
    assert trace is not None
    assert trace.agents == ["health_agent"]
    assert trace.spans[0].node == "detect"
    assert trace.spans[0].output == {"level": "high", "pet": "p-1"}


def test_traced_node_passthrough_without_active_chain() -> None:
    """无活动决策链时装饰器应透传执行、不报错、不产生跨度。"""

    @traced_node(agent="supervisor")
    def plan(x: int) -> int:
        return x + 1

    assert current_chain() is None
    assert plan(41) == 42


def test_active_chain_reset_after_context() -> None:
    tracer = DecisionChainTracer(id_factory=lambda: "t")
    assert current_chain() is None
    with tracer.trace(request_input="x"):
        assert current_chain() is not None
    assert current_chain() is None


# --- 保留期裁剪 -----------------------------------------------------------
def test_prune_keeps_records_within_retention() -> None:
    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    backend = InMemoryTracingBackend(retention=RetentionConfig(180), clock=lambda: now)

    fresh = DecisionTrace(trace_id="fresh", request_input="x")
    fresh.created_at = now - timedelta(days=179)
    old = DecisionTrace(trace_id="old", request_input="x")
    old.created_at = now - timedelta(days=181)
    backend.record(fresh)
    backend.record(old)

    removed = backend.prune()
    assert removed == 1
    assert backend.get_trace("fresh") is not None
    assert backend.get_trace("old") is None


# --- 后端抽象（LangSmith / LangFuse）-------------------------------------
class _FakeClient:
    def __init__(self) -> None:
        self.payloads: list[dict] = []

    def submit_trace(self, payload: dict) -> None:
        self.payloads.append(payload)


def test_external_backend_serializes_and_submits() -> None:
    client = _FakeClient()
    tracer = DecisionChainTracer(
        LangSmithBackend(client=client), id_factory=lambda: "trace-ext"
    )
    with tracer.trace(request_input="req", tenant_id="store_2") as chain:
        with chain.span(node="route", agent="supervisor") as h:
            h.set_output("analysis_agent")

    assert len(client.payloads) == 1
    payload = client.payloads[0]
    assert payload["trace_id"] == "trace-ext"
    assert payload["tenant_id"] == "store_2"
    assert payload["agents"] == ["supervisor"]
    assert payload["spans"][0]["node"] == "route"
    assert payload["spans"][0]["output"] == "analysis_agent"


def test_external_backend_wraps_client_errors() -> None:
    class _Boom:
        def submit_trace(self, payload: dict) -> None:
            raise RuntimeError("network down")

    backend = LangFuseBackend(client=_Boom())
    trace = DecisionTrace(trace_id="t", request_input="x")
    with pytest.raises(TraceBackendError):
        backend.record(trace)


def test_factory_builds_backends() -> None:
    assert isinstance(get_tracing_backend("memory"), InMemoryTracingBackend)
    assert isinstance(
        get_tracing_backend("langsmith", client=_FakeClient()), LangSmithBackend
    )
    assert isinstance(
        get_tracing_backend("langfuse", client=_FakeClient()), LangFuseBackend
    )
    with pytest.raises(TraceBackendError):
        get_tracing_backend("langsmith")  # 缺 client
    with pytest.raises(TraceBackendError):
        get_tracing_backend("unknown")


def test_monotonic_clock_orders_timestamps() -> None:
    ticks = count()
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    tracer = DecisionChainTracer(
        InMemoryTracingBackend(),
        id_factory=lambda: "t",
        clock=lambda: base + timedelta(seconds=next(ticks)),
    )
    with tracer.trace(request_input="x") as chain:
        with chain.span(node="a", agent="supervisor"):
            pass
    trace = tracer.backend.get_trace("t")
    assert trace is not None
    assert trace.spans[0].ended_at > trace.spans[0].started_at
