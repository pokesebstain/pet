"""AI 决策中枢：Supervisor（意图识别 / 路由 / 反思 / 聚合）。

对应设计文档 "组件 1：AI 决策中枢"、架构 1.3 与 "6.7 Supervisor 编排主循环"，
实现 Requirement 1（意图识别与多智能体编排）的 1.1–1.8：

- 1.1 经 Cloud_LLM（提示工程 / 少样本）在 10 秒内识别意图并生成任务规划。
- 1.2 将任务路由到 analysis/operation/health/supply/marketing 之一或直接聚合。
- 1.3 每个专家 Agent 输出后执行反思，判定继续重规划或进入聚合（重规划次数 ≤ 5）。
- 1.4 所有规划步骤完成后聚合各专家 Agent 输出生成最终回答。
- 1.5 处理请求前校验 ``state.tenant_id`` 为非空值。
- 1.6 上下文缺少 ``tenant_id`` 时拒绝处理并返回租户上下文缺失错误。
- 1.7 无法归类或置信度低于阈值时拒绝路由并返回请用户澄清 / 重述的提示。
- 1.8 累计重规划达到 5 次上限仍有未完成步骤时，终止重规划、进入聚合并标记部分完成。

范围约束（重要）：意图识别经**云端 LLM**结合提示工程 / 少样本实现，**不引入任何
模型微调**。Cloud_LLM 调用被 :class:`~app.agents.intent.IntentClassifier` 协议隔离，
测试可注入伪分类器，在无真实网络的情况下模拟识别结果与降级。

本模块提供两种编排入口：

1. :meth:`SupervisorAgent.run` —— 以纯 Python 复刻设计文档 6.7 主循环，便于直接单元
   测试各分支（缺租户 / 澄清 / 五类路由 / 重规划上限部分完成）。
2. :func:`build_supervisor_graph` —— 用 LangGraph :class:`StateGraph` 装配等价的编排图
   （含反思循环）。专家 Agent 节点接线到注入的真实专家（任务 21.2，见
   :mod:`app.agents.experts`），未注入时回退到占位专家；状态持久化（checkpointer）与
   HITL 中断由任务 22.x 在编译期接入。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agents.experts import ExpertAgent
from app.agents.hitl import HITLCheckpoint
from app.agents.intent import (
    DEFAULT_CONFIDENCE_THRESHOLD,
    EXPERT_INTENTS,
    CloudLLMIntentClassifier,
    IntentClassifier,
)
from app.agents.state import AgentState
from app.core.errors import TenantContextMissingError
from app.llm.client import CloudLLMClient
from app.observability.tracing import current_chain

__all__ = [
    "MAX_REPLANS",
    "INTENT_TIMEOUT_SECONDS",
    "CLARIFICATION_PROMPT",
    "PARTIAL_ANSWER_PREFIX",
    "RouteDecision",
    "ReflectDecision",
    "SupervisorAgent",
    "build_supervisor_graph",
    "compile_supervisor_graph",
]

#: 反思重规划次数上限（Requirement 1.3 / 1.8）。
MAX_REPLANS: int = 5

#: 意图识别时间预算（秒，Requirement 1.1）。
INTENT_TIMEOUT_SECONDS: float = 10.0

#: 无法归类 / 低置信度时返回的澄清提示（Requirement 1.7）。
CLARIFICATION_PROMPT: str = (
    "抱歉，我无法确定您的具体需求。请补充说明您想进行数据分析、客户运营、"
    "宠物健康、库存供应链还是营销内容方面的操作？"
)

#: 部分完成结果的前缀标记（Requirement 1.8）。
PARTIAL_ANSWER_PREFIX: str = "[部分完成] "

#: 路由决策：六类专家意图之一或进入聚合（含企业微信接待预约 ``reception``，任务 27.3）。
RouteDecision = Literal[
    "analysis",
    "operation",
    "health",
    "supply",
    "marketing",
    "reception",
    "aggregate",
]

#: 反思决策：继续重规划或进入聚合。
ReflectDecision = Literal["replan", "aggregate"]

# LangGraph 中用于承接"重规划"回边的调度节点名。
_DISPATCH_NODE = "dispatch"

# 聚合后承接副作用人工确认的 HITL 检查点节点名（Requirement 4）。
_HITL_NODE = "hitl"


class SupervisorAgent:
    """主管 Agent：负责意图识别、路由、反思与聚合。

    所有外部依赖（意图分类器）均可注入，便于在无真实网络的情况下测试。生产环境使用
    :class:`~app.agents.intent.CloudLLMIntentClassifier`（Cloud_LLM 驱动）。

    Args:
        classifier: 意图分类器，实现 :class:`~app.agents.intent.IntentClassifier` 协议。
        confidence_threshold: 低置信度阈值，低于该值视为无法可靠归类（Requirement 1.7）。
        max_replans: 反思重规划次数上限（Requirement 1.3 / 1.8）。
        intent_timeout: 意图识别时间预算（秒，Requirement 1.1）。
        experts: 可选的专家 Agent 映射（名称→:class:`~app.agents.experts.ExpertAgent`）。
            注入后由真实专家（任务 21.2）执行；未注入时回退到占位专家，保持任务 21.1 的
            路由 / 反思 / 聚合契约与端到端联通性。
        hitl: 可选的 HITL 检查点（任务 22.3）。注入后在聚合完成、返回用户前，对含副作用
            （计费 / 推送 / 转介绍写入）的规划中断并请求人工确认（Requirement 4）；未注入
            时不做副作用确认（保持任务 21.1 的纯编排语义）。
    """

    def __init__(
        self,
        classifier: IntentClassifier,
        *,
        confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
        max_replans: int = MAX_REPLANS,
        intent_timeout: float = INTENT_TIMEOUT_SECONDS,
        experts: Mapping[str, ExpertAgent] | None = None,
        hitl: HITLCheckpoint | None = None,
    ) -> None:
        self._classifier = classifier
        self._confidence_threshold = confidence_threshold
        self._max_replans = max_replans
        self._intent_timeout = intent_timeout
        self._experts: dict[str, ExpertAgent] = dict(experts or {})
        self._hitl = hitl

    # -- 意图识别与规划（Requirement 1.1 / 1.5 / 1.6 / 1.7）------------------

    def recognize_intent(self, state: AgentState) -> AgentState:
        """识别意图并生成任务规划，返回状态增量。

        处理前校验 ``tenant_id`` 非空（Requirement 1.5）；缺失则抛出
        :class:`~app.core.errors.TenantContextMissingError`（Requirement 1.6）。
        无法归类或置信度低于阈值时不生成规划，转澄清路径（Requirement 1.7）。

        Returns:
            AgentState: 仅包含变更字段的状态增量（``total=False``）。
        """
        tenant_id = state.get("tenant_id")
        if tenant_id is None or not str(tenant_id).strip():
            raise TenantContextMissingError(
                "Supervisor 处理请求前要求非空 tenant_id（Requirement 1.5 / 1.6）。"
            )

        result = self._classifier.classify(
            state.get("messages", []), timeout=self._intent_timeout
        )

        if result.intent is None or result.confidence < self._confidence_threshold:
            # 无法可靠归类：拒绝路由并请用户澄清（Requirement 1.7）。
            return {
                "intent": None,
                "intent_confidence": result.confidence,
                "plan": [],
                "needs_clarification": True,
                "clarification": CLARIFICATION_PROMPT,
            }

        return {
            "intent": result.intent,
            "intent_confidence": result.confidence,
            "plan": self._plan_tasks(result.intent),
            "needs_clarification": False,
            "clarification": None,
        }

    @staticmethod
    def _plan_tasks(intent: str) -> list[dict[str, Any]]:
        """依据意图生成任务规划步骤。

        MVP 阶段每个意图对应单一专家步骤；后续可扩展为多步规划（由反思循环推进）。
        """
        return [{"agent": intent, "status": "pending"}]

    # -- 路由（Requirement 1.2）---------------------------------------------

    def route(self, state: AgentState) -> RouteDecision:
        """选择下一个专家 Agent 或进入聚合阶段。

        需澄清或无有效意图时直接聚合（由聚合阶段返回澄清提示）；否则返回首个未完成
        规划步骤对应的专家意图；无待办步骤时聚合。
        """
        if state.get("needs_clarification") or not state.get("intent"):
            return "aggregate"
        for step in state.get("plan", []):
            if step.get("status") != "done":
                agent = step.get("agent")
                if agent in EXPERT_INTENTS:
                    return agent  # type: ignore[return-value]
        return "aggregate"

    # -- 反思（Requirement 1.3 / 1.8）--------------------------------------

    def reflect(self, state: AgentState) -> ReflectDecision:
        """在专家 Agent 输出后判定继续重规划或进入聚合。

        无未完成步骤 → 聚合（Requirement 1.4）；累计重规划达到上限 → 聚合并由聚合阶段
        标记部分完成（Requirement 1.8）；否则继续重规划（Requirement 1.3）。
        """
        if not self._pending_steps(state):
            return "aggregate"
        if state.get("replan_count", 0) >= self._max_replans:
            return "aggregate"
        return "replan"

    # -- 聚合（Requirement 1.4 / 1.8）--------------------------------------

    def aggregate(self, state: AgentState) -> AgentState:
        """聚合各专家 Agent 输出生成最终回答，返回状态增量。

        需澄清时返回澄清提示；仍有未完成步骤（重规划上限触发）时标记部分完成并加前缀。
        """
        if state.get("needs_clarification"):
            answer = state.get("clarification") or CLARIFICATION_PROMPT
            return {"final_answer": answer, "partial": False}

        partial = bool(self._pending_steps(state))
        answer = self._compose_answer(state.get("agent_outputs", {}), partial=partial)
        return {"final_answer": answer, "partial": partial}

    @staticmethod
    def _compose_answer(
        agent_outputs: dict[str, dict[str, Any]], *, partial: bool
    ) -> str:
        """将各专家输出组织为最终回答文本。

        仅当**多个**专家参与本轮规划时才以 ``[agent_name]`` 前缀区分各段输出（帮助用户
        辨认多专家聚合结果的来源）；单一专家场景（当前 MVP 阶段每个意图对应单一专家
        步骤的常态）直接返回其 ``summary`` 原文，不携带内部 Agent 标识——面向客户的
        回复不应暴露内部实现细节（如 ``[reception]``）。
        """
        if not agent_outputs:
            body = "未产生任何专家分析结果。"
        elif len(agent_outputs) == 1:
            (output,) = agent_outputs.values()
            body = str(output.get("summary", output))
        else:
            segments = [
                f"[{name}] {output.get('summary', output)}"
                for name, output in agent_outputs.items()
            ]
            body = "\n".join(segments)
        return f"{PARTIAL_ANSWER_PREFIX}{body}" if partial else body

    # -- 纯 Python 编排主循环（设计文档 6.7）--------------------------------

    def run(self, state: AgentState) -> AgentState:
        """以纯 Python 复刻设计文档 6.7 主循环并返回完整状态。

        流程：校验并识别意图 → 若需澄清则直接聚合 → 循环（路由 → 专家 → 反思）
        → 聚合生成最终回答。专家节点使用注入的真实专家（任务 21.2），未注入时回退占位。
        """
        working: dict[str, Any] = dict(state)
        working.update(self.recognize_intent(working))

        if not working.get("needs_clarification"):
            while True:
                nxt = self.route(working)  # type: ignore[arg-type]
                if nxt == "aggregate":
                    break
                working.update(self._run_expert(nxt, working))  # type: ignore[arg-type]
                if self.reflect(working) == "aggregate":  # type: ignore[arg-type]
                    break
                working = self._increment_replan(working)

        working.update(self.aggregate(working))  # type: ignore[arg-type]

        # 聚合后、返回用户前：对含副作用的规划执行 HITL 人工确认（Requirement 4）。
        if self._hitl is not None:
            working.update(self._hitl.run(working))  # type: ignore[arg-type]

        return working  # type: ignore[return-value]

    # -- LangGraph 节点封装 --------------------------------------------------

    def _node_hitl(self, state: AgentState) -> AgentState:
        """HITL 检查点节点：含副作用时人工确认，否则透传（Requirement 4）。"""
        if self._hitl is None:
            return {}
        return self._hitl.run(state)

    def _after_recognize(self, state: AgentState) -> Literal["dispatch", "aggregate"]:
        """意图识别后的分支：需澄清直接聚合，否则进入调度。"""
        return "aggregate" if state.get("needs_clarification") else _DISPATCH_NODE

    def _node_reflect(self, state: AgentState) -> AgentState:
        """反思节点：在决定重规划前累加重规划计数（上限见 :data:`MAX_REPLANS`）。"""
        if not self._pending_steps(state):
            return {}
        count = state.get("replan_count", 0)
        if count < self._max_replans:
            return {"replan_count": count + 1}
        return {}

    def _make_expert_node(self, name: str):
        """构造某类专家 Agent 的图节点。

        注入了对应专家（任务 21.2）时委派给真实专家执行；否则回退到占位专家，
        使编排图在无依赖注入时仍可端到端联通。
        """

        def _node(state: AgentState) -> AgentState:
            return self._run_expert(name, state)

        _node.__name__ = f"expert_{name}"
        return _node

    # -- 内部辅助 ------------------------------------------------------------

    def _run_expert(self, name: str, state: AgentState) -> AgentState:
        """执行专家并返回状态增量。

        优先使用注入的真实专家（任务 21.2，仅经工具层 / 引擎访问数据）；未注入时回退到
        占位专家（标记步骤完成并记录 stub 输出）。两条路径返回的增量形状一致
        （``plan`` / ``agent_outputs``），保持路由 / 反思 / 聚合契约不变。
        """
        expert = self._experts.get(name)
        if expert is not None:
            return expert.run(state)
        return self._run_placeholder_expert(name, state)

    @staticmethod
    def _run_placeholder_expert(name: str, state: AgentState) -> AgentState:
        """占位专家：标记对应步骤完成并记录 stub 输出，返回状态增量。"""
        plan = [dict(step) for step in state.get("plan", [])]
        for step in plan:
            if step.get("agent") == name and step.get("status") != "done":
                step["status"] = "done"
                break
        outputs = dict(state.get("agent_outputs", {}))
        outputs[name] = {
            "status": "stub",
            "summary": f"{name} 专家占位输出（未注入真实专家）。",
        }
        return {"plan": plan, "agent_outputs": outputs}

    def _increment_replan(self, state: dict[str, Any]) -> dict[str, Any]:
        """在纯 Python 主循环中累加重规划计数。"""
        updated = dict(state)
        updated["replan_count"] = updated.get("replan_count", 0) + 1
        return updated

    @staticmethod
    def _pending_steps(state: AgentState) -> list[dict[str, Any]]:
        """返回尚未完成的规划步骤列表。"""
        return [
            step
            for step in state.get("plan", [])
            if step.get("status") != "done"
        ]


def build_supervisor_graph(
    classifier: IntentClassifier | None = None,
    *,
    supervisor: SupervisorAgent | None = None,
    llm_client: CloudLLMClient | None = None,
    experts: Mapping[str, ExpertAgent] | None = None,
    hitl: HITLCheckpoint | None = None,
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    max_replans: int = MAX_REPLANS,
) -> StateGraph:
    """构建带反思循环的 Supervisor 编排 :class:`StateGraph`。

    图结构（对应设计文档 1.3 与 6.7）::

        START → recognize_intent → (dispatch | aggregate)
        dispatch → (analysis | operation | health | supply | marketing | aggregate)
        <expert> → reflect → (dispatch[replan] | aggregate)
        aggregate → END

    专家 Agent 节点接线到注入的真实专家（任务 21.2，仅经工具层 / 引擎访问数据）；未注入
    ``experts`` 时回退到占位专家以保持端到端联通。本函数返回**未编译**的
    :class:`StateGraph`，以便任务 22.x 在编译期接入 checkpointer（thread_id 持久化）与
    HITL 中断。可注入 ``supervisor`` 或 ``classifier``（生产用 Cloud_LLM 驱动分类器，
    测试注入伪实现）。

    Args:
        classifier: 意图分类器；与 ``supervisor`` 二选一。
        supervisor: 预构造的 :class:`SupervisorAgent`；优先于 ``classifier``。
        llm_client: 当未提供 ``classifier`` / ``supervisor`` 时，用于构造默认
            :class:`~app.agents.intent.CloudLLMIntentClassifier` 的 Cloud_LLM 客户端。
        experts: 可选的专家 Agent 映射（名称→:class:`~app.agents.experts.ExpertAgent`），
            经 :func:`~app.agents.experts.build_expert_agents` 装配；仅在未显式提供
            ``supervisor`` 时生效（否则以 ``supervisor`` 自带的专家为准）。
        hitl: 可选的 HITL 检查点（任务 22.3）。注入后在聚合与 END 之间加入 ``hitl`` 节点，
            对含副作用（计费 / 推送 / 转介绍写入）的规划中断并请求人工确认（Requirement 4）；
            仅在未显式提供 ``supervisor`` 时生效（否则以 ``supervisor`` 自带的检查点为准）。
        confidence_threshold: 低置信度阈值（Requirement 1.7）。
        max_replans: 反思重规划次数上限（Requirement 1.3 / 1.8）。

    Returns:
        StateGraph: 未编译的编排图。
    """
    sup = supervisor or SupervisorAgent(
        _resolve_classifier(classifier, llm_client),
        confidence_threshold=confidence_threshold,
        max_replans=max_replans,
        experts=experts,
        hitl=hitl,
    )

    graph: StateGraph = StateGraph(AgentState)
    graph.add_node(
        "recognize_intent", _traced(sup.recognize_intent, agent="supervisor", node="recognize_intent")
    )
    graph.add_node(_DISPATCH_NODE, _passthrough)
    for name in EXPERT_INTENTS:
        graph.add_node(
            name, _traced(sup._make_expert_node(name), agent=name, node=f"expert_{name}")
        )
    graph.add_node("reflect", _traced(sup._node_reflect, agent="supervisor", node="reflect"))
    graph.add_node("aggregate", _traced(sup.aggregate, agent="supervisor", node="aggregate"))
    # 仅当注入了 HITL 检查点时才加入 hitl 节点（Requirement 4）。
    hitl_enabled = sup._hitl is not None
    if hitl_enabled:
        graph.add_node(_HITL_NODE, _traced(sup._node_hitl, agent="supervisor", node="hitl"))

    graph.add_edge(START, "recognize_intent")
    graph.add_conditional_edges(
        "recognize_intent",
        sup._after_recognize,
        {_DISPATCH_NODE: _DISPATCH_NODE, "aggregate": "aggregate"},
    )
    route_map: dict[str, str] = {name: name for name in EXPERT_INTENTS}
    route_map["aggregate"] = "aggregate"
    graph.add_conditional_edges(_DISPATCH_NODE, sup.route, route_map)
    for name in EXPERT_INTENTS:
        graph.add_edge(name, "reflect")
    graph.add_conditional_edges(
        "reflect",
        sup.reflect,
        {"replan": _DISPATCH_NODE, "aggregate": "aggregate"},
    )
    # 聚合后：有 HITL 则经检查点再返回用户，否则直接结束。
    if hitl_enabled:
        graph.add_edge("aggregate", _HITL_NODE)
        graph.add_edge(_HITL_NODE, END)
    else:
        graph.add_edge("aggregate", END)
    return graph


def compile_supervisor_graph(
    classifier: IntentClassifier | None = None,
    *,
    supervisor: SupervisorAgent | None = None,
    llm_client: CloudLLMClient | None = None,
    experts: Mapping[str, ExpertAgent] | None = None,
    hitl: HITLCheckpoint | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    max_replans: int = MAX_REPLANS,
) -> CompiledStateGraph:
    """编译带 checkpointer 的 Supervisor 编排图，支持按 ``thread_id`` 多轮持久化。

    在 :func:`build_supervisor_graph` 之上接入 LangGraph checkpointer（Requirement 3）：

    - 以 ``config={"configurable": {"thread_id": <id>}}`` 调用时，图会在每轮结束后按
      ``thread_id`` **持久化对话状态**，并在同一 ``thread_id`` 的后续轮次**加载**该状态
      作为上下文（Requirement 3.1 / 3.3、Correctness Property 9）。
    - 携带**无任何持久化状态**的 ``thread_id`` 时，LangGraph 以空会话初始化该线程状态
      （Requirement 3.4）。
    - 默认使用内存 checkpointer :class:`~langgraph.checkpoint.memory.MemorySaver`，可注入
      其他实现（如 SQLite / Postgres saver）以在进程重启后仍可恢复；测试注入
      ``MemorySaver`` 即可在无网络 / 无数据库下验证多轮状态一致性。

    专家 Agent 的接线与 :func:`build_supervisor_graph` 一致（未注入 ``experts`` 时回退到
    占位专家）。多轮 What-if 模拟由运营专家
    :class:`~app.agents.experts.OperationAgent` 基于持久化的上一轮结果执行
    （Requirement 3.2 / 3.5）。

    Args:
        classifier: 意图分类器；与 ``supervisor`` 二选一。
        supervisor: 预构造的 :class:`SupervisorAgent`；优先于 ``classifier``。
        llm_client: 构造默认 Cloud_LLM 意图分类器所需的客户端（三者均缺省时报错）。
        experts: 可选的专家 Agent 映射（名称→:class:`~app.agents.experts.ExpertAgent`）。
        hitl: 可选的 HITL 检查点（任务 22.3）：含副作用规划在返回用户前经人工确认
            （Requirement 4）；仅在未显式提供 ``supervisor`` 时生效。
        checkpointer: LangGraph checkpointer；``None`` 时默认 :class:`MemorySaver`。
        confidence_threshold: 低置信度阈值（Requirement 1.7）。
        max_replans: 反思重规划次数上限（Requirement 1.3 / 1.8）。

    Returns:
        CompiledStateGraph: 已编译、可用 ``thread_id`` 配置多轮调用的图。
    """
    graph = build_supervisor_graph(
        classifier,
        supervisor=supervisor,
        llm_client=llm_client,
        experts=experts,
        hitl=hitl,
        confidence_threshold=confidence_threshold,
        max_replans=max_replans,
    )
    saver = checkpointer if checkpointer is not None else MemorySaver()
    return graph.compile(checkpointer=saver)


def _passthrough(state: AgentState) -> AgentState:
    """调度节点：不修改状态，仅作为路由 / 重规划回边的汇聚点。"""
    return {}


def _traced(node_fn: Any, *, agent: str, node: str) -> Any:
    """包裹 LangGraph 节点函数，在当前活动决策链（若有）中记录一个跨度（Requirement 18.2）。

    无活动决策链时（未经 :meth:`DecisionChainTracer.trace` 包裹的调用，如直接单元测试
    某个节点）直接透传执行，不产生任何副作用，因此不影响既有测试对节点函数的直接调用。
    仅记录状态增量的**键名**作为输出摘要（而非完整状态），避免把整轮对话历史 / 客户原文
    重复写入每个节点跨度（trace 顶层已携带一次完整请求输入，见组合根接线）。
    """

    def _wrapped(state: AgentState) -> AgentState:
        chain = current_chain()
        if chain is None:
            return node_fn(state)
        with chain.span(node=node, agent=agent) as handle:
            delta = node_fn(state)
            handle.set_output({"changed_keys": sorted(delta.keys())} if delta else {})
            return delta

    return _wrapped


def _resolve_classifier(
    classifier: IntentClassifier | None, llm_client: CloudLLMClient | None
) -> IntentClassifier:
    """解析意图分类器：优先使用注入实例，否则基于注入的 Cloud_LLM 客户端构造默认实现。"""
    if classifier is not None:
        return classifier
    if llm_client is not None:
        return CloudLLMIntentClassifier(llm_client)
    raise ValueError(
        "build_supervisor_graph 需要注入 classifier、supervisor 或 llm_client 之一。"
    )
