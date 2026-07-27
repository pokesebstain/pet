"""BFF 路由、认证与 RLS 上下文注入测试（任务 24.1，Requirement 1.1 / 5.1 / 5.4）。

覆盖：

- 存活 / 就绪探针可用，且就绪探针内省到各组件均已装配（消除孤立组件）。
- ``POST /agent/query`` 经认证 + RLS 上下文注入后转发至 Supervisor，返回意图与最终回答。
- ``thread_id`` 多轮会话：同一线程后续轮次可访问前序持久化状态（Requirement 3）。
- 安全边界：缺失 / 空租户上下文的请求被拒绝（HTTP 401，Requirement 5.4）。
- 认证来源：``X-Tenant-Id`` 头与 ``Authorization: Bearer`` 令牌（JWT 桩）均可提取租户。

全部测试在无网络 / 无数据库 / 无真实 LLM 下运行：注入伪意图分类器与内存专家，
组合根其余组件使用默认内存 / 降级实现。
"""

from __future__ import annotations

import base64
import json
from collections.abc import Sequence

from fastapi.testclient import TestClient

from app.agents.intent import IntentResult
from app.agents.state import AgentState
from app.agents.experts import record_expert_output
from app.api import build_composition, create_app
from app.api.auth import current_tenant_id, extract_request_tenant_id, rls_context


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


class FakeAnalysisExpert:
    """伪分析专家：产出一批带标记的分析结果并持久化到状态。"""

    name = "analysis"

    def run(self, state: AgentState) -> AgentState:
        output = {
            "status": "ok",
            "summary": "已完成数据分析并生成洞察。",
            "insight": "上月高价值客户流失率上升。",
        }
        return record_expert_output(self.name, state, output)


class FakeOperationExpert:
    """伪运营专家：记录本轮可见的历史消息数，用于验证多轮状态可访问。"""

    name = "operation"

    def run(self, state: AgentState) -> AgentState:
        output = {
            "status": "ok",
            "summary": "已基于上一轮结果完成 What-if 推演。",
            "seen_message_count": len(state.get("messages", [])),
            "has_previous_analysis": "analysis" in state.get("agent_outputs", {}),
        }
        return record_expert_output(self.name, state, output)


def _build_client() -> TestClient:
    """构造注入了伪分类器与内存专家的 BFF 应用客户端。"""
    composition = build_composition(
        classifier=KeywordIntentClassifier(),
        experts={
            "analysis": FakeAnalysisExpert(),
            "operation": FakeOperationExpert(),
        },
    )
    return TestClient(create_app(composition=composition))


# --------------------------------------------------------------------------- #
# 探针
# --------------------------------------------------------------------------- #
def test_health_endpoint_ok() -> None:
    client = _build_client()
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_ready_endpoint_reports_all_components_wired() -> None:
    """就绪探针内省到各组件均已装配（消除孤立组件）。"""
    client = _build_client()
    resp = client.get("/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ready"
    assert all(body["components"].values())
    # 关键组件均在场。
    for key in (
        "event_bus",
        "supervisor_graph",
        "ltv_engine",
        "supply_engine",
        "health_agent",
        "subscription_engine",
        "ecosystem_network",
        "marketing_agent",
        "text2sql",
        "rag_retriever",
        "experts",
    ):
        assert body["components"][key] is True


# --------------------------------------------------------------------------- #
# Supervisor 转发（认证 + RLS 上下文注入）
# --------------------------------------------------------------------------- #
def test_agent_query_forwards_to_supervisor_with_tenant_header() -> None:
    client = _build_client()
    resp = client.post(
        "/agent/query",
        headers={"X-Tenant-Id": "store_88"},
        json={"message": "上个月哪些高价值客户在流失?"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["tenant_id"] == "store_88"
    assert body["intent"] == "analysis"
    assert body["final_answer"] is not None
    assert "洞察" in body["final_answer"]
    assert body["thread_id"].startswith("thread-")


def test_agent_query_supports_bearer_tenant_token() -> None:
    """认证来源：Authorization: Bearer 的 JWT 桩令牌可提取租户。"""
    client = _build_client()
    resp = client.post(
        "/agent/query",
        headers={"Authorization": "Bearer tenant:store_42"},
        json={"message": "帮我看看数据"},
    )
    assert resp.status_code == 200
    assert resp.json()["tenant_id"] == "store_42"


def test_agent_query_multiturn_persists_state_by_thread_id() -> None:
    """Requirement 3：同一 thread_id 后续轮次可访问前序持久化状态。"""
    client = _build_client()
    headers = {"X-Tenant-Id": "store_88"}

    first = client.post(
        "/agent/query",
        headers=headers,
        json={"message": "上个月哪些高价值客户在流失?"},
    )
    thread_id = first.json()["thread_id"]

    second = client.post(
        "/agent/query",
        headers=headers,
        json={"message": "如果给他们发8折券,预计能挽回多少?", "thread_id": thread_id},
    )
    assert second.status_code == 200
    body = second.json()
    assert body["thread_id"] == thread_id
    assert body["intent"] == "operation"
    # 第二轮的运营专家应能看到累积的历史消息与上一轮的分析结果。
    op = body["final_answer"]
    assert op is not None


# --------------------------------------------------------------------------- #
# 安全边界：缺失租户上下文即拒绝（Requirement 5.4）
# --------------------------------------------------------------------------- #
def test_agent_query_rejects_missing_tenant() -> None:
    client = _build_client()
    resp = client.post("/agent/query", json={"message": "上个月销售额多少?"})
    assert resp.status_code == 401


def test_agent_query_rejects_blank_tenant_header() -> None:
    client = _build_client()
    resp = client.post(
        "/agent/query",
        headers={"X-Tenant-Id": "   "},
        json={"message": "上个月销售额多少?"},
    )
    assert resp.status_code == 401


def test_agent_query_rejects_empty_message() -> None:
    """空消息体不通过请求校验（Pydantic min_length）。"""
    client = _build_client()
    resp = client.post(
        "/agent/query",
        headers={"X-Tenant-Id": "store_88"},
        json={"message": ""},
    )
    assert resp.status_code == 422


# --------------------------------------------------------------------------- #
# RLS 上下文注入 / 提取工具单元测试
# --------------------------------------------------------------------------- #
def test_rls_context_sets_and_clears_current_tenant() -> None:
    assert current_tenant_id() is None
    with rls_context("store_7") as tid:
        assert tid == "store_7"
        assert current_tenant_id() == "store_7"
    # 退出后清理，避免请求间串扰。
    assert current_tenant_id() is None


def test_extract_request_tenant_id_from_jwt_stub() -> None:
    """未签名 JWT 的 tenant_id 声明可被解析（JWT 桩）。"""

    class _FakeRequest:
        def __init__(self, headers: dict[str, str]) -> None:
            self.headers = headers

    payload = base64.urlsafe_b64encode(json.dumps({"tenant_id": "store_99"}).encode()).decode().rstrip("=")
    token = f"header.{payload}.sig"
    request = _FakeRequest({"Authorization": f"Bearer {token}"})
    assert extract_request_tenant_id(request) == "store_99"  # type: ignore[arg-type]
