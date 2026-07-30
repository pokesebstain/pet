"""公众号宠主上下文与未建档短路测试（Requirement 26.1、26.4、26.6）。"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.api import build_composition
from app.api import wechat_routes
from app.engines.scheduling_db import PetResolution


class _UnknownCustomerResolver:
    def resolve(self, tenant_id: str, external_user_id: str) -> PetResolution:
        assert tenant_id == "store-public"
        assert external_user_id == "openid-new"
        return PetResolution(customer_id=None)


class _RecordingOnboardingReception:
    name = "reception"

    def __init__(self) -> None:
        self.states: list[dict] = []

    def run(self, state):  # noqa: ANN001
        self.states.append(dict(state))
        return {
            "agent_outputs": {
                "reception": {
                    "status": "needs_clarification",
                    "reply_text": "请告诉我您的称呼和宝贝名字。",
                }
            },
            "onboarding_pending": True,
            "pending_service_request": state["pending_service_request"],
        }


class _MustNotClassifyGraph:
    def invoke(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("未建档公众号用户不得进入通用意图识别")


def test_unknown_openid_short_circuits_to_onboarding_with_public_context(monkeypatch) -> None:
    reception = _RecordingOnboardingReception()
    composition = build_composition(
        reception_agent=reception,
        customer_resolver=_UnknownCustomerResolver(),
    )
    composition.supervisor_graph = _MustNotClassifyGraph()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(composition=composition)))
    monkeypatch.setattr(
        wechat_routes,
        "get_settings",
        lambda: SimpleNamespace(resolved_default_tenant_id="store-public"),
    )

    first = asyncio.run(wechat_routes._handle_message(request, "openid-new", "想预约周六给豆豆洗澡"))
    second = asyncio.run(wechat_routes._handle_message(request, "openid-new", "我叫李姐"))

    assert first == "请告诉我您的称呼和宝贝名字。"
    assert second == first
    assert len(reception.states) == 2
    initial, follow_up = reception.states
    assert initial["channel"] == "wechat_public"
    assert initial["customer_facing"] is True
    assert initial["openid"] == "openid-new"
    assert initial["thread_id"] == "wechat:store-public:openid-new"
    assert initial["onboarding_pending"] is True
    assert "想预约周六给豆豆洗澡" in initial["pending_service_request"]
    assert follow_up["messages"][-1]["content"] == "我叫李姐"
    assert "想预约周六给豆豆洗澡" in follow_up["pending_service_request"]


class _FixedIntentClassifier:
    def __init__(self, intent: str | None) -> None:
        self._intent = intent

    def classify(self, _messages, *, timeout: float | None = None):  # noqa: ANN001, ARG002
        from app.agents.intent import IntentResult

        return IntentResult(intent=self._intent, confidence=0.95)


class _FailIfCalledExpert:
    name = "analysis"

    def run(self, _state):  # noqa: ANN001
        raise AssertionError("公众号宠主不得进入内部经营专家")


def test_public_customer_internal_intent_is_not_routed_or_shown() -> None:
    """Requirement 26.2 / 26.7：公众号只允许宠主服务路径，内部意图统一转服务澄清。"""
    from app.agents.intent import PUBLIC_CLARIFICATION_PROMPT
    from app.agents.state import new_state
    from app.agents.supervisor import SupervisorAgent

    supervisor = SupervisorAgent(
        _FixedIntentClassifier("analysis"), experts={"analysis": _FailIfCalledExpert()}
    )
    result = supervisor.run(
        new_state(
            "store-public",
            messages=[{"role": "user", "content": "帮我分析本月客户流失"}],
            channel="wechat_public",
            customer_facing=True,
            customer_id="customer-1",
        )
    )

    assert result["intent"] is None
    assert result["plan"] == []
    assert result["final_answer"] == PUBLIC_CLARIFICATION_PROMPT
    for internal_term in ("数据分析", "客户运营", "库存", "供应链", "营销"):
        assert internal_term not in result["final_answer"]


class _NoAnswerGraph:
    def __init__(self) -> None:
        self.states: list[dict] = []

    def invoke(self, state, config=None):  # noqa: ANN001, ARG002
        self.states.append(dict(state))
        return {}


class _KnownCustomerResolver:
    def resolve(self, tenant_id: str, external_user_id: str) -> PetResolution:
        assert tenant_id == "store-public"
        assert external_user_id == "openid-known"
        return PetResolution(customer_id="customer-known")


def test_known_public_customer_unknown_result_uses_only_service_guidance(monkeypatch) -> None:
    """Requirement 26.2 / 26.7：已建档宠主的无结果兜底不展示经营能力。"""
    graph = _NoAnswerGraph()
    composition = build_composition(customer_resolver=_KnownCustomerResolver())
    composition.supervisor_graph = graph
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(composition=composition)))
    monkeypatch.setattr(
        wechat_routes,
        "get_settings",
        lambda: SimpleNamespace(resolved_default_tenant_id="store-public"),
    )

    reply = asyncio.run(wechat_routes._handle_message(request, "openid-known", "随便问问"))

    assert reply == wechat_routes.PUBLIC_CLARIFICATION_PROMPT
    assert graph.states[0]["channel"] == "wechat_public"
    assert graph.states[0]["customer_facing"] is True
    assert graph.states[0]["customer_id"] == "customer-known"
    for internal_term in ("数据分析", "客户运营", "库存", "供应链", "营销"):
        assert internal_term not in reply


class _CallbackRequest:
    def __init__(self, body: bytes) -> None:
        self._body = body

    async def body(self) -> bytes:
        return self._body


def test_public_callback_exception_logs_correlation_and_returns_service_guidance(
    monkeypatch, caplog
) -> None:
    """Requirement 26.8：异常记录关联标识与详情，宠主只收到可继续的服务引导。"""
    import logging

    async def _raise_processing_error(*_args, **_kwargs):  # noqa: ANN002, ANN003
        raise RuntimeError("simulated callback failure")

    monkeypatch.setattr(wechat_routes, "_get_token", lambda: "test-token")
    monkeypatch.setattr(wechat_routes, "_verify_signature", lambda *_args: True)
    monkeypatch.setattr(wechat_routes, "_handle_message", _raise_processing_error)
    monkeypatch.setattr(
        wechat_routes,
        "get_settings",
        lambda: SimpleNamespace(resolved_default_tenant_id="store-public"),
    )
    request = _CallbackRequest(
        (
            "<xml><ToUserName>store</ToUserName><FromUserName>openid-error</FromUserName>"
            "<MsgType>text</MsgType><Content>想预约洗澡</Content></xml>"
        ).encode("utf-8")
    )

    with caplog.at_level(logging.INFO, logger=wechat_routes.__name__):
        response = asyncio.run(
            wechat_routes.wechat_callback(request, signature="sig", timestamp="1", nonce="2")
        )

    body = response.body.decode("utf-8")
    assert wechat_routes.PUBLIC_ERROR_GUIDANCE in body
    assert "已收到" not in body
    assert "尽快处理" not in body
    assert "correlation_id=wechat_public:" in caplog.text
    assert "simulated callback failure" in caplog.text
    assert "openid-error" not in caplog.text


class _PendingOnboardingResolver:
    def resolve(self, tenant_id: str, external_user_id: str) -> PetResolution:
        assert tenant_id == "store-public"
        assert external_user_id == "openid-health"
        return PetResolution(
            customer_id="customer-health",
            pet_ids=["pet-health"],
            onboarding_pending=True,
            missing_profile_fields=("phone", "species", "breed"),
        )


class _OnboardingThenHealthReception:
    name = "reception"

    def run(self, state):  # noqa: ANN001
        assert state["channel"] == "wechat_public"
        assert state["customer_facing"] is True
        return {
            "customer_id": "customer-health",
            "onboarding_pending": True,
            "pending_service_request": state["pending_service_request"],
            "pending_service_intent": {"service_type": None},
            "agent_outputs": {
                "reception": {
                    "status": "needs_clarification",
                    "reply_text": "请补充宠物资料。",
                }
            },
        }


class _PublicHealthGraph:
    def __init__(self) -> None:
        self.calls: list[tuple[dict, dict]] = []

    def invoke(self, state, config=None):  # noqa: ANN001
        self.calls.append((dict(state), dict(config or {})))
        return {"final_answer": "豆豆的养护问题我会继续帮您分析。"}


def test_pending_onboarding_health_consultation_continues_without_restarting_service(
    monkeypatch,
) -> None:
    """Requirement 26.6：待补档案资料不阻塞已表达的健康咨询。"""
    graph = _PublicHealthGraph()
    composition = build_composition(
        reception_agent=_OnboardingThenHealthReception(),
        customer_resolver=_PendingOnboardingResolver(),
    )
    composition.supervisor_graph = graph
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(composition=composition)))
    monkeypatch.setattr(
        wechat_routes,
        "get_settings",
        lambda: SimpleNamespace(resolved_default_tenant_id="store-public"),
    )

    reply = asyncio.run(
        wechat_routes._handle_message(request, "openid-health", "豆豆一直软便，该怎么养护？")
    )

    assert "养护问题" in reply
    assert "手机号" in reply
    assert "物种" in reply
    assert "品种" in reply
    assert "重新" not in reply
    assert graph.calls
    state, config = graph.calls[0]
    assert state["channel"] == "wechat_public"
    assert state["customer_facing"] is True
    assert config["configurable"]["thread_id"].startswith("wechat_public:")
    assert "openid-health" not in config["configurable"]["thread_id"]
