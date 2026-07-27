"""五个专家 Agent 的真实实现（对应设计文档 组件 2「专家 Agent 层」，任务 21.2）。

对应设计文档 "Components and Interfaces / 组件 2：专家 Agent 层" 与 "组件 3：统一工具层"，
以及 1.3 多智能体拓扑图。实现 Requirement 2.4 / 2.5（Analysis_Agent 数据洞察 / 空结果说明）。

设计约束（重要）：**每个专家 Agent 只经工具层 / 已实现的引擎访问数据与模型**（设计文档
"每个 Agent 只通过统一工具层访问数据与模型"）。因此本模块的每个 Agent 都不直接触碰
数据库 / 网络，而是接线到已实现的：

- Text2SQL 生成 + 三重校验执行（:mod:`app.text2sql`）——Analysis_Agent。
- LTV 引擎与流失预测（:class:`~app.engines.ltv_engine.LTVEngine`）——Operation_Agent。
- 健康异常趋势检测（:class:`~app.agents.health.HealthAgent`）——Health_Agent。
- 供应链引擎（:class:`~app.engines.supply_chain.SupplyChainEngine`）——Supply_Agent。
- 营销内容生成（:class:`~app.agents.marketing.MarketingAgent`）——Marketing_Agent。

所有依赖都通过构造函数注入，因此测试可注入内存假实现（无网络 / 无数据库）。

**统一接口**（对应设计文档 ``ExpertAgent`` 协议）：每个 Agent 都暴露 ``name`` 与
``run(state) -> AgentState``，其中 ``run`` 返回**状态增量**：将对应规划步骤标记为完成，
并把该 Agent 的结构化输出写入 ``agent_outputs[name]``（含供聚合使用的 ``summary`` 字段）。
该增量形状与任务 21.1 的占位实现完全一致，从而**保持 Supervisor 的路由 / 反思 / 聚合
契约**（``route`` 依据未完成步骤选路、``reflect`` 依据未完成步骤判定、``aggregate`` 读取
``summary`` 组织回答）。
"""

from __future__ import annotations

import re
from statistics import fmean
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

from app.agents.health import HealthAgent, HealthAlert
from app.agents.marketing import ContentGenerationResult, MarketingAgent, MarketingError
from app.agents.state import AgentState
from app.core.errors import TenantContextMissingError
from app.engines.errors import (
    AuthorizationError,
    DataNotFoundError,
    EngineError,
    InvalidParameterError,
)
from app.engines.ltv import DEFAULT_HORIZON_MONTHS
from app.engines.ltv_engine import SEGMENT_CHURN_RISK, LTVEngine, Segment
from app.engines.supply_chain import (
    DEFAULT_SERVICE_LEVEL,
    RestockDecision,
    SupplyChainEngine,
)
from app.text2sql import ExecutionOutcome, SafeSQLExecutor, Text2SQLError, Text2SQLGenerator
from app.tools.base import MAX_RESULT_ROWS, ToolResult

__all__ = [
    "ExpertAgent",
    "AnalysisAgent",
    "OperationAgent",
    "HealthExpertAgent",
    "SupplyAgent",
    "MarketingExpertAgent",
    "build_expert_agents",
    "record_expert_output",
    "NO_MATCH_EXPLANATION",
    "MISSING_INPUT_MESSAGE",
    "NO_PREVIOUS_RESULT_MESSAGE",
    "DEFAULT_WHATIF_DISCOUNT",
    "RECALL_SENSITIVITY",
    "WHATIF_KEYWORDS",
]

#: 查询成功但结果集为空时的无匹配说明（Requirement 2.5）。
NO_MATCH_EXPLANATION = "查询执行成功，但没有匹配的数据。"

#: 缺少必要输入时返回的说明（各 Agent 在无可用参数时优雅降级）。
MISSING_INPUT_MESSAGE = "缺少执行该专家任务所需的输入参数。"

#: What-if 假设但当前会话无可供推演的上轮结果时的拒绝提示（Requirement 3.5）。
NO_PREVIOUS_RESULT_MESSAGE = (
    "当前会话中不存在可供推演的上轮结果，无法执行 What-if 模拟。"
    "请先发起一轮分析（如筛选目标客户名单）后再进行假设推演。"
)

#: 未显式给出折扣时的默认 What-if 折扣（0.8 = 8 折，即客户支付 80%）。
DEFAULT_WHATIF_DISCOUNT = 0.8

#: 召回率对营销让利强度的敏感系数（用于将让利强度映射为召回率，结果最终夹取到 [0, 1]）。
RECALL_SENSITIVITY = 2.0

#: 触发 What-if 假设推演的关键词（Requirement 3.2）。
WHATIF_KEYWORDS: tuple[str, ...] = (
    "如果",
    "假设",
    "预计",
    "挽回",
    "召回",
    "模拟",
    "推演",
    "what-if",
    "what if",
    "whatif",
)

#: 解析 "N 折" 折扣的正则（如 "8折" → 0.8，"8.5折" → 0.85）。
_DISCOUNT_ZHE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*折")

#: 解析 "N% off" / "打N折优惠" 之外的百分比让利（如 "立减20%" → 支付 0.8）。
_DISCOUNT_PERCENT_OFF_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%\s*off", re.IGNORECASE)


@runtime_checkable
class ExpertAgent(Protocol):
    """专家 Agent 统一接口（对应设计文档 组件 2 ``ExpertAgent`` 协议）。

    每个专家 Agent 仅经工具层 / 引擎访问数据，``run`` 返回一个**状态增量**：标记对应
    规划步骤完成并记录本 Agent 的输出。
    """

    name: str

    def run(self, state: AgentState) -> AgentState:  # pragma: no cover - 协议声明
        """执行专家任务并返回状态增量（``plan`` 与 ``agent_outputs``）。"""
        ...


# --------------------------------------------------------------------------- #
# 共享辅助：标记步骤完成 + 记录输出（保持与 21.1 占位实现一致的增量形状）
# --------------------------------------------------------------------------- #
def record_expert_output(
    name: str, state: AgentState, output: dict[str, Any]
) -> AgentState:
    """将某专家的输出写入状态增量：标记其规划步骤完成并记录 ``agent_outputs[name]``。

    该函数复刻任务 21.1 中 ``SupervisorAgent._run_expert`` 的增量形状（``plan`` 与
    ``agent_outputs``），确保 Supervisor 的路由 / 反思 / 聚合契约不变。

    Args:
        name: 专家 Agent 名（五类意图之一）。
        state: 当前全局状态。
        output: 该 Agent 的结构化输出（应包含供聚合使用的 ``summary`` 字段）。

    Returns:
        仅含变更字段（``plan`` / ``agent_outputs``）的状态增量。
    """
    plan = [dict(step) for step in state.get("plan", [])]
    for step in plan:
        if step.get("agent") == name and step.get("status") != "done":
            step["status"] = "done"
            break
    outputs = dict(state.get("agent_outputs", {}))
    outputs[name] = output
    return {"plan": plan, "agent_outputs": outputs}


def _tenant_id(state: AgentState) -> str:
    """读取并归一化状态中的租户上下文；缺失或为空时抛租户上下文缺失错误。"""
    tenant_id = state.get("tenant_id")
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise TenantContextMissingError("专家 Agent 处理前要求非空 tenant_id。")
    return tenant_id


def _latest_user_text(messages: Sequence[Any]) -> str:
    """从对话历史中提取最近一条用户文本（兼容元组 / 字典 / 带 ``content`` 的对象）。"""
    for message in reversed(list(messages)):
        if isinstance(message, tuple) and len(message) == 2:
            role, content = message
            if str(role).lower() in ("", "user", "human"):
                text = str(content)
                if text.strip():
                    return text
            continue
        if isinstance(message, dict):
            text = str(message.get("content", ""))
            if text.strip():
                return text
            continue
        content = getattr(message, "content", None)
        if content is not None and str(content).strip():
            return str(content)
    return ""


def _agent_params(state: AgentState, name: str) -> dict[str, Any]:
    """提取某专家的规划步骤参数。

    支持两种承载方式：步骤内的 ``params`` 子字典，或直接内联在步骤上的额外键
    （``agent`` / ``status`` 之外的键）。找不到步骤时返回空字典。
    """
    for step in state.get("plan", []):
        if step.get("agent") != name:
            continue
        params = step.get("params")
        if isinstance(params, dict):
            return dict(params)
        return {
            key: value
            for key, value in step.items()
            if key not in ("agent", "status")
        }
    return {}


# --------------------------------------------------------------------------- #
# Analysis_Agent：Text2SQL + 数据洞察（Requirement 2.4 / 2.5）
# --------------------------------------------------------------------------- #
class AnalysisAgent:
    """分析专家：经 Text2SQL 生成 → 三重校验执行 → 返回结果集 + 洞察 / 空结果说明。

    仅经工具层访问数据：SQL 由注入的 :class:`~app.text2sql.Text2SQLGenerator` 生成，
    再交由注入的 :class:`~app.text2sql.SafeSQLExecutor`（白名单 / 只读 / RLS 三重校验 +
    租户隔离 + 截断）执行，Agent 本身不直接连接数据库。

    Requirement 2.4：执行成功且结果集非空时，返回数据结果集及**至少一条**基于结果集
    内容的洞察（洞察列表非空）。
    Requirement 2.5：执行成功但结果集为空时，返回空结果集及无匹配数据的说明。
    """

    name = "analysis"

    def __init__(
        self,
        generator: Text2SQLGenerator,
        executor: SafeSQLExecutor,
    ) -> None:
        self._generator = generator
        self._executor = executor

    def run(self, state: AgentState) -> AgentState:
        output = self.analyze(_latest_user_text(state.get("messages", [])), _tenant_id(state))
        return record_expert_output(self.name, state, output)

    def analyze(self, natural_language: str, tenant_id: str) -> dict[str, Any]:
        """生成并安全执行分析查询，返回结构化输出。

        Args:
            natural_language: 用户的自然语言分析问题。
            tenant_id: 当前租户上下文。

        Returns:
            结构化输出字典，``status`` 为 ``ok`` / ``empty`` / ``rejected`` /
            ``timeout`` / ``generation_failed`` / ``no_query`` 之一。
        """
        if not natural_language.strip():
            return {
                "status": "no_query",
                "summary": "未提供可分析的自然语言问题。",
                "rows": [],
                "row_count": 0,
                "insights": [],
            }

        try:
            generated = self._generator.generate(natural_language)
        except Text2SQLError as exc:
            return {
                "status": "generation_failed",
                "summary": f"Text2SQL 生成失败：{exc}",
                "rows": [],
                "row_count": 0,
                "insights": [],
            }

        execution = self._executor.run(
            natural_language=natural_language,
            sql=generated.sql,
            tenant_id=tenant_id,
        )

        if execution.outcome is ExecutionOutcome.EXECUTED:
            result = execution.result
            assert result is not None  # EXECUTED 必有结果
            if result.row_count > 0:
                insights = _derive_insights(result)
                return {
                    "status": "ok",
                    "summary": insights[0],
                    "sql": generated.sql,
                    "rows": result.rows,
                    "row_count": result.row_count,
                    "truncated": result.truncated,
                    "insights": insights,
                }
            # Requirement 2.5：结果集为空 → 空结果集 + 无匹配说明。
            return {
                "status": "empty",
                "summary": NO_MATCH_EXPLANATION,
                "sql": generated.sql,
                "rows": [],
                "row_count": 0,
                "truncated": False,
                "insights": [],
                "explanation": NO_MATCH_EXPLANATION,
            }

        if execution.outcome is ExecutionOutcome.TIMEOUT:
            return {
                "status": "timeout",
                "summary": execution.clarification or "查询执行超时，未产生任何数据库变更。",
                "rows": [],
                "row_count": 0,
                "insights": [],
            }

        # ExecutionOutcome.REJECTED：三重校验失败，返回澄清 + 受限模板回退。
        return {
            "status": "rejected",
            "summary": execution.clarification or "生成的 SQL 未通过安全校验，已拒绝执行。",
            "rows": [],
            "row_count": 0,
            "insights": [],
            "fallback": execution.fallback_text,
        }


def _derive_insights(result: ToolResult) -> list[str]:
    """基于结果集内容派生至少一条数据洞察（Requirement 2.4）。

    始终返回非空列表：首条为总体记录数洞察；如发生截断追加截断提示；若首行为可读取
    字段的记录，追加一条基于首行字段的洞察。
    """
    insights: list[str] = [f"查询共返回 {result.row_count} 条记录。"]
    if result.truncated:
        insights.append(
            f"结果集超过 {MAX_RESULT_ROWS} 行上限，已截断为前 {result.row_count} 条。"
        )
    first = result.rows[0]
    fields = _record_fields(first)
    if fields:
        preview = "、".join(f"{key}={value!r}" for key, value in fields[:3])
        insights.append(f"示例记录：{preview}。")
    return insights


def _record_fields(record: Any) -> list[tuple[str, Any]]:
    """从一条记录中提取可读字段（兼容映射与对象），用于洞察示例。"""
    if isinstance(record, Mapping):
        return list(record.items())
    if hasattr(record, "_asdict"):  # namedtuple / Row
        return list(record._asdict().items())
    if hasattr(record, "__dict__") and vars(record):
        return list(vars(record).items())
    return []


# --------------------------------------------------------------------------- #
# Operation_Agent：流失 / 召回 + LTV 决策
# --------------------------------------------------------------------------- #
class OperationAgent:
    """运营专家：复用 LTV 引擎（含流失预测）对客户分层并给出召回建议。

    仅经注入的 :class:`~app.engines.ltv_engine.LTVEngine` 访问客户价值 / 流失分数
    （LTVEngine 内部复用 :func:`~app.engines.churn.predict_churn`），据此识别流失风险
    客户并给出召回决策。

    **多轮有状态 What-if 模拟（Requirement 3.2 / 3.5）**：在同一 ``thread_id`` 的后续
    轮次中，运营专家可基于**上一轮持久化的结果**（如上一轮筛选出的客户名单与其价值 /
    流失分数）对营销假设（如"发 8 折券"）进行推演，返回取值范围为 [0, 1] 的预计召回率
    与大于等于 0 的预计 GMV（Requirement 3.2）。当会话中不存在可供推演的上轮结果时，
    拒绝该模拟请求并返回缺少上轮结果的提示（Requirement 3.5）。
    """

    name = "operation"

    def __init__(
        self,
        ltv_engine: LTVEngine,
        *,
        horizon_months: int = DEFAULT_HORIZON_MONTHS,
    ) -> None:
        self._ltv_engine = ltv_engine
        self._horizon_months = horizon_months

    def run(self, state: AgentState) -> AgentState:
        params = _agent_params(state, self.name)
        message = _latest_user_text(state.get("messages", []))
        is_what_if, discount = self._resolve_what_if(message, params)

        if is_what_if:
            # 多轮 What-if：基于上一轮持久化结果推演（Requirement 3.2 / 3.5）。
            previous = params.get("previous_result")
            if previous is None:
                previous = _find_previous_result(state)
            output = self.simulate_what_if(previous, discount=discount)
        else:
            customer_ids = _as_str_list(params.get("customer_ids"))
            horizon = params.get("horizon_months", self._horizon_months)
            output = self.decide(customer_ids, horizon_months=horizon)
        return record_expert_output(self.name, state, output)

    # ------------------------------------------------------------------ #
    # What-if 假设推演（Requirement 3.2 / 3.5）
    # ------------------------------------------------------------------ #
    def simulate_what_if(
        self,
        previous_result: Mapping[str, Any] | None,
        *,
        discount: float | None = None,
    ) -> dict[str, Any]:
        """基于上一轮持久化结果对营销让利假设进行推演。

        推演模型（确定性、无网络）：设折扣 ``d ∈ (0, 1]``（如 0.8 表示客户支付 80%），
        让利强度 ``incentive = 1 - d ∈ [0, 1]``；结合上一轮名单的平均流失倾向
        ``avg_churn ∈ [0, 1]`` 得到预计召回率
        ``recall = clamp(incentive · RECALL_SENSITIVITY · avg_churn, 0, 1)``，因此
        **召回率恒落在 [0, 1]**（Requirement 3.2）。预计 GMV
        ``gmv = recall · N · avg_ltv · d``，其中 ``N`` 为名单规模、``avg_ltv ≥ 0``，
        各因子非负故 **GMV 恒大于等于 0**（Requirement 3.2）。

        Args:
            previous_result: 上一轮持久化结果（含 ``segments`` 客户价值 / 流失分数）。
            discount: 折扣系数（客户支付比例，取值 (0, 1]）；``None`` 时用
                :data:`DEFAULT_WHATIF_DISCOUNT`。

        Returns:
            结构化输出：``status`` 为 ``ok`` 时含 ``predicted_recall`` ∈ [0, 1] 与
            ``predicted_gmv`` ≥ 0；无上轮结果时 ``status`` 为 ``no_previous_result``
            （Requirement 3.5）。
        """
        customers = _extract_previous_customers(previous_result)
        if not customers:
            # Requirement 3.5：无可供推演的上轮结果 → 拒绝并提示。
            return {
                "status": "no_previous_result",
                "summary": NO_PREVIOUS_RESULT_MESSAGE,
                "predicted_recall": None,
                "predicted_gmv": None,
            }

        d = DEFAULT_WHATIF_DISCOUNT if discount is None else float(discount)
        d = _clamp(d, 0.0, 1.0)
        incentive = _clamp(1.0 - d, 0.0, 1.0)

        avg_churn = _clamp(fmean(c["churn_score"] for c in customers), 0.0, 1.0)
        avg_ltv = max(fmean(c["ltv"] for c in customers), 0.0)

        # 预计召回率恒 ∈ [0, 1]（Requirement 3.2）。
        predicted_recall = _clamp(incentive * RECALL_SENSITIVITY * avg_churn, 0.0, 1.0)
        recovered = predicted_recall * len(customers)
        # 预计 GMV 恒 ≥ 0（recall∈[0,1]、N≥0、avg_ltv≥0、d∈[0,1] 皆非负）。
        predicted_gmv = max(recovered * avg_ltv * d, 0.0)

        summary = (
            f"若对 {len(customers)} 位目标客户发放 {d * 10:g} 折券，"
            f"预计召回率约 {predicted_recall:.1%}（约挽回 {recovered:.1f} 位），"
            f"预计新增 GMV 约 {predicted_gmv:.2f} 元。"
        )
        return {
            "status": "ok",
            "summary": summary,
            "what_if": True,
            "discount": d,
            "target_customer_count": len(customers),
            "predicted_recall": predicted_recall,
            "predicted_recovered_customers": recovered,
            "predicted_gmv": predicted_gmv,
        }

    @staticmethod
    def _resolve_what_if(
        message: str, params: Mapping[str, Any]
    ) -> tuple[bool, float | None]:
        """判定本轮是否为 What-if 假设推演并解析折扣。

        触发条件（任一）：规划步骤显式携带 ``what_if=True`` / ``discount`` /
        ``previous_result``，或最近一条用户消息命中 :data:`WHATIF_KEYWORDS`。
        """
        explicit = (
            bool(params.get("what_if"))
            or params.get("discount") is not None
            or params.get("previous_result") is not None
        )
        discount = params.get("discount")
        if discount is not None:
            discount = float(discount)

        keyword_hit = _matches_what_if(message)
        if not explicit and not keyword_hit:
            return False, None

        if discount is None:
            discount = _parse_discount(message)
        return True, discount

    def decide(
        self,
        customer_ids: Sequence[str],
        *,
        horizon_months: int | None = None,
    ) -> dict[str, Any]:
        """对给定客户分层并识别流失风险客户，给出召回建议。"""
        if not customer_ids:
            return {
                "status": "no_input",
                "summary": MISSING_INPUT_MESSAGE + "（需要 customer_ids）",
                "segments": [],
            }
        horizon = self._horizon_months if horizon_months is None else horizon_months
        try:
            segments = self._ltv_engine.segment_customers(customer_ids, horizon)
        except (InvalidParameterError, DataNotFoundError, AuthorizationError) as exc:
            return {
                "status": "error",
                "summary": f"客户分层失败：{exc}",
                "segments": [],
            }

        at_risk = [seg for seg in segments if seg.segment == SEGMENT_CHURN_RISK]
        summary = (
            f"已对 {len(segments)} 位客户分层，其中 {len(at_risk)} 位为流失风险，"
            f"建议对流失风险客户开展召回。"
        )
        return {
            "status": "ok",
            "summary": summary,
            "horizon_months": horizon,
            "segments": [_segment_dict(seg) for seg in segments],
            "at_risk_customer_ids": [seg.customer_id for seg in at_risk],
        }


def _segment_dict(segment: Segment) -> dict[str, Any]:
    """将 :class:`~app.engines.ltv_engine.Segment` 转为可序列化字典。"""
    return {
        "customer_id": segment.customer_id,
        "ltv": segment.ltv,
        "churn_score": segment.churn_score,
        "segment": segment.segment,
        "tier_rank": segment.tier_rank,
    }


def _clamp(value: float, low: float, high: float) -> float:
    """将数值夹取到 [low, high] 闭区间。"""
    return max(low, min(high, value))


def _find_previous_result(state: AgentState) -> dict[str, Any] | None:
    """从持久化状态中定位可供 What-if 推演的上一轮结果（Requirement 3.1 / 3.2）。

    优先取运营专家上一轮携带客户名单（``segments``）的输出；否则回退到任一携带
    ``segments`` 的专家输出。均无则返回 ``None``（触发 Requirement 3.5 的拒绝路径）。
    """
    outputs = state.get("agent_outputs", {})
    if not isinstance(outputs, Mapping):
        return None
    preferred = outputs.get(OperationAgent.name)
    if isinstance(preferred, Mapping) and preferred.get("segments"):
        return dict(preferred)
    for candidate in outputs.values():
        if isinstance(candidate, Mapping) and candidate.get("segments"):
            return dict(candidate)
    return None


def _extract_previous_customers(
    previous_result: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    """从上一轮结果中提取带 ``ltv`` / ``churn_score`` 的客户记录。

    若结果标注了 ``at_risk_customer_ids``，则优先聚焦这批流失风险客户（召回券的目标
    对象）；否则采用全部客户名单。缺失字段以安全默认值补齐（``ltv=0``、``churn=0``）。
    """
    if not isinstance(previous_result, Mapping):
        return []
    segments = previous_result.get("segments")
    if not isinstance(segments, Sequence) or isinstance(segments, (str, bytes)):
        return []

    at_risk = previous_result.get("at_risk_customer_ids")
    at_risk_set = set(_as_str_list(at_risk)) if at_risk else set()

    customers: list[dict[str, Any]] = []
    for seg in segments:
        if not isinstance(seg, Mapping):
            continue
        if at_risk_set and str(seg.get("customer_id")) not in at_risk_set:
            continue
        customers.append(
            {
                "customer_id": str(seg.get("customer_id", "")),
                "ltv": max(_as_float(seg.get("ltv"), 0.0), 0.0),
                "churn_score": _clamp(_as_float(seg.get("churn_score"), 0.0), 0.0, 1.0),
            }
        )
    return customers


def _matches_what_if(message: str) -> bool:
    """判断消息是否命中 What-if 假设推演关键词。"""
    if not message:
        return False
    lowered = message.lower()
    return any(keyword in message or keyword in lowered for keyword in WHATIF_KEYWORDS)


def _parse_discount(message: str) -> float | None:
    """从消息中解析折扣系数（客户支付比例，取值 (0, 1]）。

    支持 "N 折"（如 "8折" → 0.8）与 "N% off"（如 "20% off" → 支付 0.8）两类表达；
    无法解析时返回 ``None``（调用方回退到默认折扣）。
    """
    match = _DISCOUNT_ZHE_RE.search(message)
    if match:
        value = float(match.group(1)) / 10.0
        if 0.0 < value <= 1.0:
            return value
    match = _DISCOUNT_PERCENT_OFF_RE.search(message)
    if match:
        off = float(match.group(1)) / 100.0
        value = 1.0 - off
        if 0.0 < value <= 1.0:
            return value
    return None


def _as_float(value: Any, default: float) -> float:
    """安全地将任意值转为 float；失败时返回默认值。"""
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


# --------------------------------------------------------------------------- #
# Health_Agent：健康趋势 / 预警（复用已实现 HealthAgent）
# --------------------------------------------------------------------------- #
class HealthExpertAgent:
    """健康专家：复用已实现的 :class:`~app.agents.health.HealthAgent` 做异常趋势检测。

    经注入的 HealthAgent（其时序读取 / 事件发布 / 任务下沉均已协议化，可用内存假实现）
    对目标宠物执行最近 30 天异常趋势检测并汇总预警。
    """

    name = "health"

    def __init__(self, health_agent: HealthAgent) -> None:
        self._health_agent = health_agent

    def run(self, state: AgentState) -> AgentState:
        params = _agent_params(state, self.name)
        pet_id = str(params.get("pet_id") or "").strip()
        output = self.assess(pet_id, _tenant_id(state))
        return record_expert_output(self.name, state, output)

    def assess(self, pet_id: str, tenant_id: str) -> dict[str, Any]:
        """对目标宠物执行健康异常趋势检测并汇总结果。"""
        if not pet_id:
            return {
                "status": "no_input",
                "summary": MISSING_INPUT_MESSAGE + "（需要 pet_id）",
                "alerts": [],
            }
        try:
            alerts = self._health_agent.detect(pet_id, tenant_id)
        except EngineError as exc:
            return {
                "status": "error",
                "summary": f"健康检测失败：{exc}",
                "alerts": [],
            }

        if not alerts:
            return {
                "status": "ok",
                "summary": f"宠物 {pet_id} 最近未检测到健康异常趋势。",
                "alerts": [],
            }
        summary = (
            f"宠物 {pet_id} 检测到 {len(alerts)} 条健康异常预警，"
            f"最高级别为 {_highest_level(alerts)}。"
        )
        return {
            "status": "alert",
            "summary": summary,
            "alerts": [_alert_dict(alert) for alert in alerts],
        }


def _highest_level(alerts: Sequence[HealthAlert]) -> str:
    """返回预警集合中的最高级别标签（高 > 中 > 低）。"""
    order = {"低": 0, "中": 1, "高": 2}
    highest = max(alerts, key=lambda a: order.get(a.level.value, 0))
    return highest.level.value


def _alert_dict(alert: HealthAlert) -> dict[str, Any]:
    """将 :class:`~app.agents.health.HealthAlert` 转为可序列化字典。"""
    return {
        "pet_id": alert.pet_id,
        "metric": alert.metric,
        "level": alert.level.value,
        "drop_ratio": alert.drop_ratio,
        "reason": alert.reason,
    }


# --------------------------------------------------------------------------- #
# Supply_Agent：补货 / 定价（复用 SupplyChainEngine）
# --------------------------------------------------------------------------- #
class SupplyAgent:
    """供应链专家：复用 :class:`~app.engines.supply_chain.SupplyChainEngine` 做补货判定。

    经注入的供应链引擎（销量 / SKU 主数据均协议化，可用内存假实现）对目标 SKU 评估
    "预测需求 + 安全库存 vs 当前库存"，给出补货建议。
    """

    name = "supply"

    def __init__(
        self,
        supply_engine: SupplyChainEngine,
        *,
        service_level: float = DEFAULT_SERVICE_LEVEL,
    ) -> None:
        self._supply_engine = supply_engine
        self._service_level = service_level

    def run(self, state: AgentState) -> AgentState:
        params = _agent_params(state, self.name)
        sku_id = str(params.get("sku_id") or "").strip()
        horizon_days = params.get("horizon_days", 14)
        service_level = params.get("service_level", self._service_level)
        output = self.plan_restock(sku_id, horizon_days, service_level)
        return record_expert_output(self.name, state, output)

    def plan_restock(
        self,
        sku_id: str,
        horizon_days: int,
        service_level: float | None = None,
    ) -> dict[str, Any]:
        """评估 SKU 补货需求并给出建议补货量。"""
        if not sku_id:
            return {
                "status": "no_input",
                "summary": MISSING_INPUT_MESSAGE + "（需要 sku_id）",
            }
        level = self._service_level if service_level is None else service_level
        try:
            decision = self._supply_engine.evaluate_restock(
                sku_id, horizon_days, level
            )
        except (InvalidParameterError, DataNotFoundError) as exc:
            return {
                "status": "error",
                "summary": f"补货判定失败：{exc}",
            }
        return {
            "status": "ok",
            "summary": _restock_summary(decision),
            "decision": _restock_dict(decision),
        }


def _restock_summary(decision: RestockDecision) -> str:
    """构造补货判定的可读摘要。"""
    if decision.needs_restock:
        return (
            f"SKU {decision.sku_id} 需补货：未来 {decision.horizon_days} 天预测需求 "
            f"{decision.predicted_demand:.1f} + 安全库存 {decision.safety_stock:.1f} "
            f"超过当前库存 {decision.current_stock:g}，建议补货 "
            f"{decision.suggested_order_quantity:.1f}。"
        )
    return (
        f"SKU {decision.sku_id} 库存充足：当前库存 {decision.current_stock:g} 可覆盖未来 "
        f"{decision.horizon_days} 天的预测需求与安全库存，暂无需补货。"
    )


def _restock_dict(decision: RestockDecision) -> dict[str, Any]:
    """将 :class:`~app.engines.supply_chain.RestockDecision` 转为可序列化字典。"""
    return {
        "sku_id": decision.sku_id,
        "horizon_days": decision.horizon_days,
        "predicted_demand": decision.predicted_demand,
        "safety_stock": decision.safety_stock,
        "reorder_point": decision.reorder_point,
        "current_stock": decision.current_stock,
        "needs_restock": decision.needs_restock,
        "suggested_order_quantity": decision.suggested_order_quantity,
        "degraded": decision.degraded,
    }


# --------------------------------------------------------------------------- #
# Marketing_Agent：内容 / 活动策划（复用已实现 MarketingAgent）
# --------------------------------------------------------------------------- #
class MarketingExpertAgent:
    """营销专家：复用已实现的 :class:`~app.agents.marketing.MarketingAgent` 生成内容。

    经注入的 MarketingAgent（Cloud_LLM + RAG，均协议化可注入伪实现）在当前租户 +
    平台共享范围内生成营销 / 社区内容。
    """

    name = "marketing"

    def __init__(
        self,
        marketing_agent: MarketingAgent,
        *,
        require_references: bool = True,
    ) -> None:
        self._marketing_agent = marketing_agent
        self._require_references = require_references

    def run(self, state: AgentState) -> AgentState:
        request = _latest_user_text(state.get("messages", []))
        params = _agent_params(state, self.name)
        require_references = params.get("require_references", self._require_references)
        output = self.create_content(
            request, _tenant_id(state), require_references=require_references
        )
        return record_expert_output(self.name, state, output)

    def create_content(
        self,
        request: str,
        tenant_id: str,
        *,
        require_references: bool = True,
    ) -> dict[str, Any]:
        """生成营销 / 社区内容，返回结构化输出。"""
        if not request.strip():
            return {
                "status": "no_input",
                "summary": MISSING_INPUT_MESSAGE + "（需要内容生成请求）",
            }
        try:
            result: ContentGenerationResult = self._marketing_agent.generate_content(
                request,
                tenant_id=tenant_id,
                require_references=require_references,
            )
        except MarketingError as exc:
            return {
                "status": "error",
                "summary": f"内容生成失败：{exc}",
            }

        if result.success:
            return {
                "status": "ok",
                "summary": result.content,
                "content": result.content,
                "references": [chunk.chunk_id for chunk in result.references],
            }
        # LLM 失败 / 缺参考片段：返回失败提示，不臆造内容。
        return {
            "status": result.status.value,
            "summary": result.message,
        }


# --------------------------------------------------------------------------- #
# 工厂：装配五个专家 Agent 映射
# --------------------------------------------------------------------------- #
def build_expert_agents(
    *,
    text2sql_generator: Text2SQLGenerator,
    sql_executor: SafeSQLExecutor,
    ltv_engine: LTVEngine,
    health_agent: HealthAgent,
    supply_engine: SupplyChainEngine,
    marketing_agent: MarketingAgent,
    reception_agent: ExpertAgent | None = None,
) -> dict[str, ExpertAgent]:
    """装配专家 Agent 的名称→实例映射，供 :func:`build_supervisor_graph` 注入。

    所有依赖均由调用方注入（生产用真实引擎 / 客户端，测试用内存假实现），使 Supervisor
    编排图可接线到真实专家而不引入任何网络 / 数据库耦合。

    Args:
        reception_agent: 可选的接待预约专家（:class:`~app.agents.reception.ReceptionAgent`，
            任务 27.3）。以**预构造实例**注入（而非在此构造），既保持向后兼容，又避免
            与 :mod:`app.agents.reception`（其复用本模块的 :func:`record_expert_output`）
            形成循环导入。注入后经其 ``name``（``"reception"``）登记到映射，从而 Supervisor
            可将 ``reception`` 意图路由至它（Requirement 21.1）；未注入时映射不含该键，
            ``reception`` 意图回退到占位专家，行为与既有一致。
    """
    experts: dict[str, ExpertAgent] = {
        AnalysisAgent.name: AnalysisAgent(text2sql_generator, sql_executor),
        OperationAgent.name: OperationAgent(ltv_engine),
        HealthExpertAgent.name: HealthExpertAgent(health_agent),
        SupplyAgent.name: SupplyAgent(supply_engine),
        MarketingExpertAgent.name: MarketingExpertAgent(marketing_agent),
    }
    if reception_agent is not None:
        experts[reception_agent.name] = reception_agent
    return experts


def _as_str_list(value: Any) -> list[str]:
    """将任意值归一化为字符串列表（None → 空列表；标量 → 单元素列表）。"""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, Sequence):
        return [str(item) for item in value]
    return [str(value)]
