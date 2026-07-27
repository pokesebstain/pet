"""多轮有状态 What-if 与 thread_id 状态持久化测试（任务 22.1）。

覆盖 Requirement 3（多轮有状态 What-if 分析）：

- 3.1 / 3.3：同一 ``thread_id`` 连续调用，后续轮次可加载并访问前序轮次持久化的状态
  （对应设计文档 Correctness Property 9：多轮状态一致）。
- 3.2：Operation_Agent 基于持久化的上一轮结果执行 What-if 模拟，返回召回率 ∈ [0, 1]
  与 GMV ≥ 0。
- 3.4：携带无任何持久化状态的 ``thread_id`` 以空会话初始化。
- 3.5：无可供推演的上轮结果时拒绝 What-if 并返回缺少上轮结果的提示。

全部测试均在无网络 / 无数据库下运行：意图分类器为伪实现，checkpointer 使用
:class:`~langgraph.checkpoint.memory.MemorySaver`，专家依赖为内存假实现。
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from langgraph.checkpoint.memory import MemorySaver

from app.agents.experts import (
    NO_PREVIOUS_RESULT_MESSAGE,
    OperationAgent,
    record_expert_output,
)
from app.agents.intent import IntentResult
from app.agents.state import AgentState, new_state
from app.agents.supervisor import compile_supervisor_graph
from app.engines.ltv_engine import (
    SEGMENT_CHURN_RISK,
    InMemoryCustomerFeatureProvider,
    LTVEngine,
)


# --------------------------------------------------------------------------- #
# 测试替身
# --------------------------------------------------------------------------- #
class KeywordIntentClassifier:
    """伪意图分类器：含 What-if 关键词路由到 operation，否则路由到 analysis。"""

    def classify(self, messages: Sequence, *, timeout: float | None = None) -> IntentResult:
        text = ""
        for message in reversed(list(messages)):
            if isinstance(message, tuple) and len(message) == 2:
                text = str(message[1])
            elif isinstance(message, dict):
                text = str(message.get("content", ""))
            else:
                text = str(message)
            if text.strip():
                break
        if any(kw in text for kw in ("如果", "预计", "挽回", "假设")):
            return IntentResult(intent="operation", confidence=0.95)
        return IntentResult(intent="analysis", confidence=0.95)


class FakeSegmentAnalysisExpert:
    """伪分析专家：产出一批带 LTV / 流失分数的目标客户名单（模拟上一轮筛选结果）。"""

    name = "analysis"

    def __init__(self, segments: list[dict], at_risk_ids: list[str]) -> None:
        self._segments = segments
        self._at_risk_ids = at_risk_ids

    def run(self, state: AgentState) -> AgentState:
        output = {
            "status": "ok",
            "summary": f"筛选出 {len(self._segments)} 位目标客户。",
            "segments": self._segments,
            "at_risk_customer_ids": self._at_risk_ids,
        }
        return record_expert_output(self.name, state, output)


def _operation_agent() -> OperationAgent:
    """构造仅用于 What-if 的运营专家（LTV 引擎在 What-if 路径中不会被调用）。"""
    return OperationAgent(LTVEngine(InMemoryCustomerFeatureProvider()))


def _sample_segments() -> tuple[list[dict], list[str]]:
    segments = [
        {"customer_id": "c1", "ltv": 1200.0, "churn_score": 0.8, "segment": SEGMENT_CHURN_RISK},
        {"customer_id": "c2", "ltv": 800.0, "churn_score": 0.7, "segment": SEGMENT_CHURN_RISK},
        {"customer_id": "c3", "ltv": 300.0, "churn_score": 0.2, "segment": "成长"},
    ]
    at_risk = ["c1", "c2"]
    return segments, at_risk


# --------------------------------------------------------------------------- #
# thread_id 状态持久化 / 多轮加载（Requirement 3.1 / 3.3 / 3.4）
# --------------------------------------------------------------------------- #
def test_same_thread_id_later_turn_accesses_earlier_persisted_state() -> None:
    """Property 9：同一 thread_id 的后续轮次可访问前序轮次持久化状态。"""
    segments, at_risk = _sample_segments()
    graph = compile_supervisor_graph(
        classifier=KeywordIntentClassifier(),
        experts={
            "analysis": FakeSegmentAnalysisExpert(segments, at_risk),
            "operation": _operation_agent(),
        },
        checkpointer=MemorySaver(),
    )
    config = {"configurable": {"thread_id": "boss-session-001"}}

    # 第 1 轮：分析类，产出目标客户名单并持久化。
    first = graph.invoke(
        {"tenant_id": "store_88", "messages": [("user", "上个月哪些高价值客户在流失?")]},
        config=config,
    )
    assert first["agent_outputs"]["analysis"]["segments"] == segments

    # 第 2 轮：相同 thread_id 追问 What-if，应能加载上一轮持久化状态。
    second = graph.invoke(
        {"messages": [("user", "如果给他们发8折券,预计能挽回多少?")]},
        config=config,
    )
    # 前序轮次的分析结果仍可见（持久化状态被加载）。
    assert "analysis" in second["agent_outputs"]
    assert second["agent_outputs"]["analysis"]["segments"] == segments
    # 消息在同一 thread_id 上累积（后续轮次访问了前序消息）。
    contents = [m[1] for m in second["messages"]]
    assert any("在流失" in c for c in contents)
    assert any("8折券" in c for c in contents)


def test_fresh_thread_id_initializes_empty_session() -> None:
    """Requirement 3.4：无任何持久化状态的 thread_id 以空会话初始化。"""
    segments, at_risk = _sample_segments()
    graph = compile_supervisor_graph(
        classifier=KeywordIntentClassifier(),
        experts={
            "analysis": FakeSegmentAnalysisExpert(segments, at_risk),
            "operation": _operation_agent(),
        },
        checkpointer=MemorySaver(),
    )

    graph.invoke(
        {"tenant_id": "store_88", "messages": [("user", "上个月哪些高价值客户在流失?")]},
        config={"configurable": {"thread_id": "thread-A"}},
    )
    # 全新 thread_id：不应看到 thread-A 的任何历史消息。
    fresh = graph.invoke(
        {"tenant_id": "store_88", "messages": [("user", "这只狗健康吗?")]},
        config={"configurable": {"thread_id": "thread-B"}},
    )
    # 空会话初始化：thread-B 仅含自身消息，未见 thread-A 的任何历史消息。
    contents = [m[1] for m in fresh["messages"]]
    assert contents == ["这只狗健康吗?"]


def test_whatif_through_compiled_graph_returns_bounded_recall_and_gmv() -> None:
    """Requirement 3.2：经编译图多轮调用，What-if 返回召回率 ∈ [0,1] 与 GMV ≥ 0。"""
    segments, at_risk = _sample_segments()
    graph = compile_supervisor_graph(
        classifier=KeywordIntentClassifier(),
        experts={
            "analysis": FakeSegmentAnalysisExpert(segments, at_risk),
            "operation": _operation_agent(),
        },
        checkpointer=MemorySaver(),
    )
    config = {"configurable": {"thread_id": "wt"}}

    graph.invoke(
        {"tenant_id": "store_88", "messages": [("user", "上个月哪些高价值客户在流失?")]},
        config=config,
    )
    second = graph.invoke(
        {"messages": [("user", "如果给他们发8折券,预计能挽回多少?")]},
        config=config,
    )
    op = second["agent_outputs"]["operation"]
    assert op["status"] == "ok"
    assert 0.0 <= op["predicted_recall"] <= 1.0
    assert op["predicted_gmv"] >= 0.0
    assert op["discount"] == pytest.approx(0.8)


# --------------------------------------------------------------------------- #
# Operation_Agent What-if 模拟（Requirement 3.2 / 3.5）
# --------------------------------------------------------------------------- #
def test_operation_agent_whatif_reads_previous_persisted_result() -> None:
    """Requirement 3.2：基于持久化上轮结果推演，召回率 ∈ [0,1] 且 GMV ≥ 0。"""
    segments, at_risk = _sample_segments()
    agent = _operation_agent()
    state = new_state(
        "store_88",
        messages=[("user", "如果给他们发8折券,预计能挽回多少?")],
        plan=[{"agent": "operation", "status": "pending"}],
        agent_outputs={
            "analysis": {"segments": segments, "at_risk_customer_ids": at_risk}
        },
    )
    delta = agent.run(state)
    output = delta["agent_outputs"]["operation"]
    assert output["status"] == "ok"
    assert output["what_if"] is True
    assert 0.0 <= output["predicted_recall"] <= 1.0
    assert output["predicted_gmv"] >= 0.0
    # 仅聚焦流失风险名单（c1、c2），c3 被排除。
    assert output["target_customer_count"] == 2


def test_operation_agent_whatif_rejects_without_previous_result() -> None:
    """Requirement 3.5：无可供推演的上轮结果时拒绝并提示。"""
    agent = _operation_agent()
    state = new_state(
        "store_88",
        messages=[("user", "如果给他们发8折券,预计能挽回多少?")],
        plan=[{"agent": "operation", "status": "pending"}],
        agent_outputs={},
    )
    delta = agent.run(state)
    output = delta["agent_outputs"]["operation"]
    assert output["status"] == "no_previous_result"
    assert output["summary"] == NO_PREVIOUS_RESULT_MESSAGE
    assert output["predicted_recall"] is None
    assert output["predicted_gmv"] is None


@pytest.mark.parametrize("discount", [0.5, 0.7, 0.8, 0.95, 1.0])
def test_simulate_what_if_invariants_hold(discount: float) -> None:
    """Requirement 3.2：不同折扣下召回率恒 ∈ [0,1]、GMV 恒 ≥ 0。"""
    segments, at_risk = _sample_segments()
    agent = _operation_agent()
    previous = {"segments": segments, "at_risk_customer_ids": at_risk}
    output = agent.simulate_what_if(previous, discount=discount)
    assert output["status"] == "ok"
    assert 0.0 <= output["predicted_recall"] <= 1.0
    assert output["predicted_gmv"] >= 0.0


def test_simulate_what_if_all_customers_when_no_at_risk_marker() -> None:
    """未标注流失风险名单时，退化为全部客户参与推演，仍满足边界。"""
    segments, _ = _sample_segments()
    agent = _operation_agent()
    output = agent.simulate_what_if({"segments": segments}, discount=0.8)
    assert output["status"] == "ok"
    assert output["target_customer_count"] == len(segments)
    assert 0.0 <= output["predicted_recall"] <= 1.0
    assert output["predicted_gmv"] >= 0.0
