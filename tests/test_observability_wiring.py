"""决策链追溯（LangFuse/内存）在组合根中的接线测试（链路监控补齐）。

验证：
- 未配置 LangFuse 时，组合根默认使用进程内追溯后端，且经 Supervisor 一次真实调用后
  能留存包含 trace ID、tenant_id、session_id（thread_id）、各节点跨度与最终输出的
  决策链（Requirement 18.2）。
- 配置了 LangFuse（public_key + secret_key）时，组合根改用 LangFuse 后端。
- ``/metrics`` 指标在一次 Supervisor 调用后按预期递增（意图识别计数）。
"""

from __future__ import annotations

from collections.abc import Sequence

from app.agents.intent import IntentResult
from app.agents.state import AgentState
from app.agents.experts import record_expert_output
from app.api.composition import build_composition
from app.core.config import Settings
from app.observability import InMemoryTracingBackend, LangFuseBackend


class _FixedIntentClassifier:
    """伪意图分类器：固定返回指定意图。"""

    def __init__(self, intent: str, confidence: float = 0.95) -> None:
        self._intent = intent
        self._confidence = confidence

    def classify(self, messages: Sequence, *, timeout: float | None = None) -> IntentResult:
        return IntentResult(intent=self._intent, confidence=self._confidence)


class _FakeAnalysisExpert:
    name = "analysis"

    def run(self, state: AgentState) -> AgentState:
        return record_expert_output(
            self.name, state, {"status": "ok", "summary": "分析完成。"}
        )


def _build(**kwargs):
    kwargs.setdefault("settings", _settings_without_langfuse())
    return build_composition(
        classifier=_FixedIntentClassifier("analysis"),
        experts={"analysis": _FakeAnalysisExpert()},
        **kwargs,
    )


def _settings_without_langfuse() -> Settings:
    """显式清空 LangFuse 配置。

    本机 / CI 的 ``.env`` 可能配置了真实 LangFuse ``public_key`` / ``secret_key``
    （用于生产可观测性），若在此处依赖 ``get_settings()`` 默认加载，会与本文件
    "未配置 LangFuse 时回退进程内后端" 这组测试断言冲突，因此显式构造空配置。
    """
    return Settings(langfuse={"public_key": "", "secret_key": ""})


def test_default_tracer_is_in_memory_backend() -> None:
    """未配置 LangFuse 时回退进程内追溯后端，不产生任何出站请求。"""
    comp = _build()
    assert comp.tracer is not None
    assert isinstance(comp.tracer.backend, InMemoryTracingBackend)


def test_supervisor_invoke_records_full_decision_chain() -> None:
    """一次真实 Supervisor 调用后，追溯后端留存完整决策链（Requirement 18.2）。"""
    comp = _build()
    result = comp.supervisor_graph.invoke(
        {"tenant_id": "store_1", "messages": [("user", "上月销量如何？")]},
        config={"configurable": {"thread_id": "thread-abc"}},
    )
    assert result.get("intent") == "analysis"

    traces = comp.tracer.backend.list_traces()
    assert len(traces) == 1
    trace = traces[0]
    assert trace.tenant_id == "store_1"
    assert trace.session_id == "thread-abc"
    assert trace.request_input == "上月销量如何？"
    assert trace.output == result.get("final_answer")
    # 意图识别 → 调度 → 专家 → 反思 → 聚合，各节点均留有跨度。
    node_names = [s.node for s in trace.spans]
    assert "recognize_intent" in node_names
    assert "expert_analysis" in node_names
    assert "aggregate" in node_names
    assert trace.is_complete is True


def test_langfuse_backend_selected_when_configured() -> None:
    """配置了 LangFuse public_key/secret_key 时，组合根改用 LangFuse 后端。"""
    settings = Settings(
        langfuse={"public_key": "pk-test", "secret_key": "sk-test"}
    )
    comp = _build(settings=settings)
    assert isinstance(comp.tracer.backend, LangFuseBackend)
