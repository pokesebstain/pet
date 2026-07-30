"""AI 决策中枢的全局状态定义（LangGraph ``AgentState``）。

对应设计文档 "Components and Interfaces / 组件 1：AI 决策中枢" 与 Requirement 1
（意图识别与多智能体编排）。``AgentState`` 是随 ``thread_id`` 持久化、贯穿
Supervisor 与各专家 Agent 的全局状态，支持多轮有状态对话（Requirement 3）。

设计文档记载的核心字段：

- ``tenant_id``：多租户隔离标识（Requirement 1.5 / 1.6，处理前必须非空）。
- ``messages``：累积式对话历史。
- ``intent``：Supervisor 识别出的意图（五类之一或 ``None``）。
- ``plan``：任务规划步骤列表。
- ``agent_outputs``：各专家 Agent 的输出。
- ``pending_action``：待人工确认的副作用动作（HITL，见 Requirement 4）。
- ``final_answer``：聚合后的最终回答。

为支撑意图识别置信度判定（Requirement 1.7）与反思重规划上限（Requirement 1.8），
本模块在设计文档字段基础上补充若干**内部簿记字段**（均为可选，不改变对外语义）：

- ``intent_confidence``：意图识别置信度 [0, 1]。
- ``needs_clarification``：是否需请用户澄清 / 重述。
- ``clarification``：澄清提示文本。
- ``replan_count``：累计重规划次数（上限见 :data:`MAX_REPLANS`）。
- ``partial``：最终结果是否为部分完成（达到重规划上限时置位）。

因包含内部字段，``AgentState`` 声明为 ``total=False``，允许按需填充。
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

__all__ = [
    "AgentState",
    "new_state",
]


class AgentState(TypedDict, total=False):
    """LangGraph 全局状态，随 ``thread_id`` 持久化，支持多轮。

    ``total=False`` 使各字段均为可选，便于按处理阶段增量填充；``messages`` 使用
    ``operator.add`` 归约器，令多轮 / 多节点产生的消息在图中累积而非覆盖。
    """

    # --- 设计文档记载字段 ---------------------------------------------------
    tenant_id: str
    messages: Annotated[list, operator.add]
    intent: str | None
    plan: list[dict[str, Any]]
    agent_outputs: dict[str, dict[str, Any]]
    pending_action: dict[str, Any] | None
    final_answer: str | None

    # --- 内部簿记字段（支撑置信度判定与反思上限）---------------------------
    intent_confidence: float
    needs_clarification: bool
    clarification: str | None
    replan_count: int
    partial: bool

    # --- 企业微信接待预约上下文（Requirement 21）---------------------------
    # 注意：LangGraph 按本 TypedDict 声明的字段驱动状态通道（channel）；未在此声明的
    # 键即使在初始状态字典中赋值，也会在 graph.invoke() 时被静默丢弃（不会报错，只是
    # 消失），导致接待预约 Agent 的 pet_resolver 拿到 None 而无法解析客户/宠物。
    # 这两个字段必须显式声明才能随图执行透传。
    external_user_id: str | None
    customer_id: str | None

    # --- 微信公众号宠主会话 / 渐进式建档上下文（Requirement 26）-----------
    # ``openid`` 保留原始公众号身份；``external_user_id`` 继续兼容企业微信既有调用。
    channel: str | None
    customer_facing: bool
    openid: str | None
    thread_id: str | None
    onboarding_pending: bool
    # 尚待完成的预约或咨询原始诉求与结构化预约意图，供建档后续轮次续接。
    pending_service_request: str | None
    pending_service_intent: dict[str, Any] | None


def new_state(
    tenant_id: str,
    messages: list | None = None,
    **overrides: Any,
) -> AgentState:
    """构造一个字段完整、默认值合理的初始 :class:`AgentState`。

    Args:
        tenant_id: 多租户隔离标识（可为空串，由 Supervisor 在处理前校验）。
        messages: 初始对话历史；``None`` 时初始化为空列表。
        **overrides: 需要覆盖的其他字段。

    Returns:
        AgentState: 已填充默认值的状态字典。
    """
    state: AgentState = {
        "tenant_id": tenant_id,
        "messages": list(messages or []),
        "intent": None,
        "plan": [],
        "agent_outputs": {},
        "pending_action": None,
        "final_answer": None,
        "intent_confidence": 0.0,
        "needs_clarification": False,
        "clarification": None,
        "replan_count": 0,
        "partial": False,
        "channel": None,
        "customer_facing": False,
        "openid": None,
        "thread_id": None,
        "onboarding_pending": False,
        "pending_service_request": None,
        "pending_service_intent": None,
    }
    state.update(overrides)  # type: ignore[typeddict-item]
    return state
