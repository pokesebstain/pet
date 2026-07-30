"""接待预约 Agent 的客户 / 宠物消解接线测试（任务 26.2 / 27.3）。

验证注入 ``pet_resolver`` 后的行为（无需数据库，消解器用内存伪实现）：

- 恰好一只宠物：即使 LLM 未消解出宠物标识，也回填该宠物并回填客户标识后自动预约；
- 多只宠物且无法唯一确定：请客户指明（不预约）；
- 零只宠物 / 找不到客户：相应澄清（不预约）；
- 多只宠物但 LLM 已消解到名下某只：采用之并自动预约。

另覆盖 Requirement 25（找不到会员时自动建档，见文末 ``_FakeOnboardingWriter`` 相关测试）：
- 未注入 ``onboarding_writer``：保持既有行为（:data:`NO_CUSTOMER_REPLY`，不建档）；
- 注入后且能从对话抽取姓名 + 宠物名：自动建档并在同一轮直接完成预约；
- 仅提供其一：请客户补充缺失的那一项（不重复问已提供的部分）。
"""

from __future__ import annotations

import json
from datetime import datetime, time

from app.agents.reception import (
    MULTIPLE_PETS_REPLY,
    NO_CUSTOMER_REPLY,
    ONBOARDING_MISSING_CUSTOMER_NAME_REPLY,
    ONBOARDING_MISSING_PET_NAME_REPLY,
    NO_PET_REPLY,
    ReceptionAgent,
)
from app.agents.state import new_state
from app.engines.scheduling import (
    InMemoryBusinessHoursProvider,
    InMemoryResourceProvider,
    InMemoryTransactionalSlotStore,
    SchedulingEngine,
)
from app.engines.scheduling_db import PetResolution
from app.llm.client import CloudLLMClient, RestrictedTemplateQuery
from app.models import DomainEvent
from app.models.scheduling import ServiceType

TENANT = "store-001"
EXT = "wm-tester"
SERVICE = ServiceType.GROOMING
SLOT_START = datetime(2024, 1, 6, 14, 0)  # 周六
SLOT_END = datetime(2024, 1, 6, 15, 0)


class _CannedTransport:
    def __init__(self, text: str) -> None:
        self._text = text

    def generate(self, prompt: str, *, timeout: float) -> str:
        return self._text


class _RecordingBus:
    def __init__(self) -> None:
        self.events: list[DomainEvent] = []

    def publish(self, event: DomainEvent) -> str:
        self.events.append(event)
        return event.event_id


class _FakeResolver:
    def __init__(self, resolution: PetResolution) -> None:
        self._resolution = resolution
        self.calls: list[tuple[str, str]] = []

    def resolve(self, tenant_id: str, external_user_id: str) -> PetResolution:
        self.calls.append((tenant_id, external_user_id))
        return self._resolution


class _RoutingTransport:
    """按 prompt 是否含建档系统提示关键词路由到不同预设返回值的伪传输层。

    ``parse_booking_intent`` 与 ``extract_onboarding_info`` 共用同一个 LLM 客户端 /
    传输层，但两者的系统提示与期望 JSON 结构不同；用固定文本的传输层无法同时满足
    两者，需按 prompt 内容路由。
    """

    def __init__(self, booking_text: str, onboarding_text: str) -> None:
        self._booking_text = booking_text
        self._onboarding_text = onboarding_text

    def generate(self, prompt: str, *, timeout: float) -> str:
        if "建档" in prompt or "customer_name" in prompt:
            return self._onboarding_text
        return self._booking_text


class _ConditionalOnboardingTransport:
    """按 prompt 是否含真实姓名 / 宠物名返回不同 onboarding 抽取结果的伪传输层。

    用于多轮建档测试：仅当用户消息中**确实包含**姓名 / 宠物名时才返回抽取成功，
    否则返回 ``{None, None}``，避免伪传输层在仅含"想给狗洗澡"这种预约意图的输入
    上"幻觉"出姓名 / 宠物名。
    """

    def __init__(
        self,
        *,
        booking_text: str,
        onboarding_text_with_names: str,
        onboarding_text_without_names: str,
        customer_keyword: str = "王炳杰",
        pet_keyword: str = "绒绒",
    ) -> None:
        self._booking_text = booking_text
        self._onboarding_text_with = onboarding_text_with_names
        self._onboarding_text_without = onboarding_text_without_names
        self._customer_keyword = customer_keyword
        self._pet_keyword = pet_keyword

    def generate(self, prompt: str, *, timeout: float) -> str:
        if "建档" in prompt or "customer_name" in prompt:
            # 关键词检查必须针对用户**实际输入**而非 prompt 整体：少样本本身
            # 就含"王炳杰/绒绒"，直接 substring 匹配会误命中。prompt 模板把真实
            # 输入放在最后一段 ``User: ...`` 后接 ``Assistant:``，据此切片判断。
            user_input = self._extract_user_input(prompt)
            has_names = (
                self._customer_keyword in user_input
                and self._pet_keyword in user_input
            )
            return (
                self._onboarding_text_with
                if has_names
                else self._onboarding_text_without
            )
        return self._booking_text

    @staticmethod
    def _extract_user_input(prompt: str) -> str:
        """从 prompt 模板中提取末尾 ``User:`` 段的真实用户输入。

        ``CloudLLMClient.build_prompt`` 把系统提示与少样本放在前面，最后一段
        ``User: <input>`` 后接 ``Assistant:``，据此切片能避开少样本里的关键词污染。
        """
        tail = prompt.rsplit("User:", 1)[-1]
        # 去掉 ``Assistant:`` 之后的部分（如有）
        return tail.split("Assistant:", 1)[0]


class _FakeOnboardingWriter:
    """内存伪建档 writer：记录调用参数，返回固定的新建客户 / 宠物标识。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, str]] = []
        self.update_calls: list[dict[str, str | None]] = []
        self.update_result = PetResolution(customer_id="new-cust-1", pet_ids=["new-pet-1"])

    def create(
        self, tenant_id, external_user_id, customer_name, pet_name, **_profile  # noqa: ANN001
    ):
        self.calls.append((tenant_id, external_user_id, customer_name, pet_name))
        return PetResolution(customer_id="new-cust-1", pet_ids=["new-pet-1"])

    def update(self, tenant_id, customer_id, pet_id, **profile):  # noqa: ANN001
        self.update_calls.append(
            {"tenant_id": tenant_id, "customer_id": customer_id, "pet_id": pet_id, **profile}
        )
        return self.update_result


def _slots_json(*, pet_id=None, ambiguous=True, confidence=0.95) -> str:
    return json.dumps(
        {
            "service_type": "grooming",
            "pet_id": pet_id,
            "pet_ref": "我家狗",
            "requested_start": "2024-01-06T14:00:00",
            "requested_end": "2024-01-06T15:00:00",
            "confidence": confidence,
            "ambiguous": ambiguous,
        }
    )


def _slots_json_null_service(*, pet_id=None, requested_start=None) -> str:
    """构造 service_type 为 null 的预约意图（模拟 LLM 漏识别"洗澡→洗护"）。"""
    return json.dumps(
        {
            "service_type": None,
            "pet_id": pet_id,
            "pet_ref": "狗",
            "requested_start": requested_start,
            "requested_end": None,
            "confidence": 0.6,
            "ambiguous": True,
        }
    )


def _make_agent(
    canned: str,
    resolver: _FakeResolver,
    bus: _RecordingBus,
    *,
    onboarding_writer: _FakeOnboardingWriter | None = None,
    transport: object | None = None,
) -> ReceptionAgent:
    llm = CloudLLMClient(
        transport=transport or _CannedTransport(canned),
        template_query=RestrictedTemplateQuery(),
        timeout_seconds=10.0,
        max_retries=0,
    )
    hours = InMemoryBusinessHoursProvider()
    for wd in range(7):
        hours.set_weekday(TENANT, wd, time(9, 0), time(19, 0))
    resources = InMemoryResourceProvider()
    resources.set_capacity(TENANT, SERVICE, 1)
    store = InMemoryTransactionalSlotStore()
    engine = SchedulingEngine(hours, resources, store, slot_minutes=60)
    return ReceptionAgent(
        llm,
        engine,
        slot_locks=store,
        appointment_writer=store,
        event_bus=bus,
        pet_resolver=resolver,
        onboarding_writer=onboarding_writer,
    )


def _state(text: str = "周六下午两点给狗洗澡") -> dict:
    st = new_state(TENANT, messages=[("user", text)])
    st["external_user_id"] = EXT  # type: ignore[typeddict-unknown-key]
    return st


def test_single_pet_auto_books_with_resolved_ids() -> None:
    resolver = _FakeResolver(PetResolution(customer_id="cust-1", pet_ids=["pet-1"]))
    bus = _RecordingBus()
    agent = _make_agent(_slots_json(pet_id=None, ambiguous=True), resolver, bus)

    delta = agent.run(_state())

    output = delta["agent_outputs"]["reception"]
    assert output["status"] == "booked"
    appt = output["appointment"]
    assert appt is not None
    assert appt["customer_id"] == "cust-1"
    assert appt["pet_id"] == "pet-1"
    assert resolver.calls == [(TENANT, EXT)]


def test_multiple_pets_requests_clarification() -> None:
    resolver = _FakeResolver(
        PetResolution(customer_id="cust-1", pet_ids=["pet-a", "pet-b"])
    )
    bus = _RecordingBus()
    agent = _make_agent(_slots_json(pet_id=None), resolver, bus)

    delta = agent.run(_state())

    output = delta["agent_outputs"]["reception"]
    assert output["status"] == "needs_clarification"
    assert output["reply_text"] == MULTIPLE_PETS_REPLY
    assert bus.events == []  # 未预约


def test_multiple_pets_uses_llm_resolved_pet_when_valid() -> None:
    resolver = _FakeResolver(
        PetResolution(customer_id="cust-1", pet_ids=["pet-a", "pet-b"])
    )
    bus = _RecordingBus()
    # LLM 消解到名下的 pet-b（属于该客户）→ 采用之并预约。
    agent = _make_agent(_slots_json(pet_id="pet-b", ambiguous=False), resolver, bus)

    delta = agent.run(_state())

    output = delta["agent_outputs"]["reception"]
    assert output["status"] == "booked"
    assert output["appointment"]["pet_id"] == "pet-b"


def test_zero_pets_requests_clarification() -> None:
    resolver = _FakeResolver(PetResolution(customer_id="cust-1", pet_ids=[]))
    bus = _RecordingBus()
    agent = _make_agent(_slots_json(), resolver, bus)

    delta = agent.run(_state())

    output = delta["agent_outputs"]["reception"]
    assert output["status"] == "needs_clarification"
    assert output["reply_text"] == NO_PET_REPLY
    assert bus.events == []


def test_unknown_customer_requests_clarification() -> None:
    """未注入 onboarding_writer 时保持既有行为：直接拒绝，不建档。"""
    resolver = _FakeResolver(PetResolution(customer_id=None, pet_ids=[]))
    bus = _RecordingBus()
    agent = _make_agent(_slots_json(), resolver, bus)

    delta = agent.run(_state())

    output = delta["agent_outputs"]["reception"]
    assert output["status"] == "needs_clarification"
    assert output["reply_text"] == NO_CUSTOMER_REPLY
    assert bus.events == []


# --------------------------------------------------------------------------- #
# 自动建档（Requirement 25：找不到会员时仅采集姓名 + 宠物名即建档）
# --------------------------------------------------------------------------- #
def test_unknown_customer_onboards_and_books_when_names_provided() -> None:
    """注入 onboarding_writer 且能抽取姓名 + 宠物名时：自动建档并在同一轮完成预约。"""
    resolver = _FakeResolver(PetResolution(customer_id=None, pet_ids=[]))
    bus = _RecordingBus()
    writer = _FakeOnboardingWriter()
    transport = _RoutingTransport(
        booking_text=_slots_json(pet_id=None, ambiguous=True),
        onboarding_text=json.dumps(
            {"customer_name": "王炳杰", "pet_name": "绒绒"}
        ),
    )
    agent = _make_agent(
        "", resolver, bus, onboarding_writer=writer, transport=transport
    )

    delta = agent.run(_state("想约周六下午两点给绒绒洗澡，我叫王炳杰"))

    assert writer.calls == [(TENANT, EXT, "王炳杰", "绒绒")]
    output = delta["agent_outputs"]["reception"]
    assert output["status"] == "booked"
    assert output["appointment"]["customer_id"] == "new-cust-1"
    assert output["appointment"]["pet_id"] == "new-pet-1"
    assert "已为您建立会员档案（王炳杰 / 绒绒）" in output["reply_text"]


def test_unknown_customer_missing_pet_name_asks_for_it_only() -> None:
    """已提供姓名但未提供宠物名时：仅追问宠物名（不重复问姓名）。"""
    resolver = _FakeResolver(PetResolution(customer_id=None, pet_ids=[]))
    bus = _RecordingBus()
    writer = _FakeOnboardingWriter()
    transport = _RoutingTransport(
        booking_text=_slots_json(pet_id=None, ambiguous=True),
        onboarding_text=json.dumps({"customer_name": "王炳杰", "pet_name": None}),
    )
    agent = _make_agent(
        "", resolver, bus, onboarding_writer=writer, transport=transport
    )

    delta = agent.run(_state("我叫王炳杰"))

    output = delta["agent_outputs"]["reception"]
    assert output["status"] == "needs_clarification"
    assert output["reply_text"] == ONBOARDING_MISSING_PET_NAME_REPLY
    assert writer.calls == []  # 未建档


def test_unknown_customer_missing_customer_name_asks_for_it_only() -> None:
    """已提供宠物名但未提供姓名时：仅追问姓名（不重复问宠物名）。"""
    resolver = _FakeResolver(PetResolution(customer_id=None, pet_ids=[]))
    bus = _RecordingBus()
    writer = _FakeOnboardingWriter()
    transport = _RoutingTransport(
        booking_text=_slots_json(pet_id=None, ambiguous=True),
        onboarding_text=json.dumps({"customer_name": None, "pet_name": "绒绒"}),
    )
    agent = _make_agent(
        "", resolver, bus, onboarding_writer=writer, transport=transport
    )

    delta = agent.run(_state("我家狗叫绒绒"))

    output = delta["agent_outputs"]["reception"]
    assert output["status"] == "needs_clarification"
    assert output["reply_text"] == ONBOARDING_MISSING_CUSTOMER_NAME_REPLY
    assert writer.calls == []


def test_external_user_id_survives_full_supervisor_graph_invoke() -> None:
    """回归测试：``external_user_id`` / ``customer_id`` 必须在 ``AgentState`` TypedDict
    中显式声明，否则 LangGraph 按 schema 驱动状态通道，会在 ``graph.invoke()`` 时静默
    丢弃未声明的键——导致接待预约 Agent 的 ``pet_resolver`` 永远收不到企业微信外部联系人
    标识，宠物消解完全不生效（表现为无论客户是谁都反复追问"具体是哪只宠物"）。

    经**完整编译后的 Supervisor 图**（而非直接调用 ``agent.run``）验证，因为该 bug只有
    在状态经 LangGraph 的 channel 机制传递时才会触发，直接函数调用不会暴露此问题。
    """
    from app.agents.intent import IntentResult
    from app.agents.supervisor import build_supervisor_graph

    resolver = _FakeResolver(PetResolution(customer_id="cust-1", pet_ids=["pet-1"]))
    bus = _RecordingBus()
    agent = _make_agent(_slots_json(pet_id=None, ambiguous=True), resolver, bus)

    class _FixedReceptionIntent:
        def classify(self, messages, *, timeout=None):  # noqa: ANN001
            return IntentResult(intent="reception", confidence=0.95)

    graph = build_supervisor_graph(
        classifier=_FixedReceptionIntent(), experts={"reception": agent}
    ).compile()

    state = new_state(TENANT, messages=[("user", "周六下午两点给狗洗澡")])
    state["external_user_id"] = EXT  # type: ignore[typeddict-unknown-key]

    result = graph.invoke(state)

    assert resolver.calls == [(TENANT, EXT)]
    output = result["agent_outputs"]["reception"]
    assert output["status"] == "booked"
    assert output["appointment"]["customer_id"] == "cust-1"


# --------------------------------------------------------------------------- #
# 防御性服务类型兜底（LLM 偶发将"洗澡"判为 service_type=null 时的关键词回填）
# --------------------------------------------------------------------------- #
def test_onboarding_backfills_service_type_from_keywords_when_llm_returns_null() -> None:
    """LLM 返回 service_type=null 但全量对话出现"洗澡"时：建档成功后应回填为 grooming。

    回归用户实际场景：
      客户："想约周六下午给狗洗澡"  → LLM 漏识别 service_type
      客户："王炳杰，狗狗叫绒绒"   → onboarding 抽取到姓名+宠物名
    预期：建档成功后，仅追问具体时间点（不再重复列出已被告知的洗护/药浴）。
    """
    resolver = _FakeResolver(PetResolution(customer_id=None, pet_ids=[]))
    bus = _RecordingBus()
    writer = _FakeOnboardingWriter()
    # 基于输入是否包含真实姓名/宠物名决定 onboarding_text 返回：避免在仅含"洗澡"
    # 的输入上被伪传输层"幻觉"出王炳杰/绒绒。
    transport = _ConditionalOnboardingTransport(
        booking_text=_slots_json_null_service(),
        onboarding_text_with_names=json.dumps(
            {"customer_name": "王炳杰", "pet_name": "绒绒"}
        ),
        onboarding_text_without_names=json.dumps(
            {"customer_name": None, "pet_name": None}
        ),
    )
    agent = _make_agent(
        "", resolver, bus, onboarding_writer=writer, transport=transport
    )

    # 第一轮：仅预约需求，无姓名/宠物名 → 应走 ONBOARDING_ASK_REPLY
    delta = agent.run(_state("想约周六下午给狗洗澡"))
    output = delta["agent_outputs"]["reception"]
    assert output["status"] == "needs_clarification"
    assert "小主您好" in output["reply_text"]
    assert writer.calls == []

    # 第二轮：补充姓名+宠物名；state 带上前一轮历史模拟真实多轮对话
    state = new_state(
        TENANT, messages=[("user", "想约周六下午给狗洗澡"), ("user", "王炳杰，狗狗叫绒绒")]
    )
    state["external_user_id"] = EXT  # type: ignore[typeddict-unknown-key]
    delta = agent.run(state)

    assert writer.calls == [(TENANT, EXT, "王炳杰", "绒绒")]
    output = delta["agent_outputs"]["reception"]
    # 建档成功后澄清文案应只问具体时间点，不应再次列出"服务类型（洗护/药浴）"。
    assert "已为您建立会员档案（王炳杰 / 绒绒）" in output["reply_text"]
    assert "服务类型" not in output["reply_text"], (
        "修复后不应再重复问已被告知过的服务类型；"
        f"实际 reply_text={output['reply_text']!r}"
    )
    assert "具体几点" in output["reply_text"]


def test_onboarding_does_not_override_llm_provided_service_type() -> None:
    """LLM 已给出 medical_bath 时：关键词兜底不应覆盖 LLM 判定。"""
    resolver = _FakeResolver(PetResolution(customer_id=None, pet_ids=[]))
    bus = _RecordingBus()
    writer = _FakeOnboardingWriter()
    medical_bath_json = json.dumps(
        {
            "service_type": "medical_bath",
            "pet_id": None,
            "pet_ref": "绒绒",
            "requested_start": None,
            "requested_end": None,
            "confidence": 0.85,
            "ambiguous": True,
        }
    )
    transport = _RoutingTransport(
        booking_text=medical_bath_json,
        onboarding_text=json.dumps(
            {"customer_name": "王炳杰", "pet_name": "绒绒"}
        ),
    )
    agent = _make_agent(
        "", resolver, bus, onboarding_writer=writer, transport=transport
    )

    state = new_state(
        TENANT,
        messages=[("user", "想约周六下午给绒绒做药浴"), ("user", "王炳杰，狗狗叫绒绒")],
    )
    state["external_user_id"] = EXT  # type: ignore[typeddict-unknown-key]
    delta = agent.run(state)

    assert writer.calls == [(TENANT, EXT, "王炳杰", "绒绒")]
    output = delta["agent_outputs"]["reception"]
    # 应走澄清分支（因为 LLM 已给出 medical_bath，时间仍缺），但不应被"洗澡"覆盖。
    assert output["status"] == "needs_clarification"
    assert "已为您建立会员档案（王炳杰 / 绒绒）" in output["reply_text"]
    assert "服务类型" not in output["reply_text"]


def test_coerce_service_type_from_keywords_unit() -> None:
    """单元测试：关键词兜底函数正确识别"洗澡/药浴/美容/grooming"等高确定性信号。"""
    from app.agents.reception import _coerce_service_type_from_keywords

    assert _coerce_service_type_from_keywords("想给狗洗澡") == ServiceType.GROOMING
    assert _coerce_service_type_from_keywords("预约洗护") == ServiceType.GROOMING
    assert _coerce_service_type_from_keywords("grooming please") == ServiceType.GROOMING
    assert _coerce_service_type_from_keywords("美容 SPA") == ServiceType.GROOMING
    # "药浴"优先级高于"洗澡"（同时出现时取 medical_bath）。
    assert _coerce_service_type_from_keywords("药浴跟洗澡都行") == ServiceType.MEDICAL_BATH
    assert _coerce_service_type_from_keywords("皮肤药浴") == ServiceType.MEDICAL_BATH
    # 没有服务关键词 → None，不臆造。
    assert _coerce_service_type_from_keywords("周六下午两点") is None
    assert _coerce_service_type_from_keywords("") is None
    # 与洗无关的字不应误命中。
    assert _coerce_service_type_from_keywords("洗一下手") is None


# --------------------------------------------------------------------------- #
# 当前日期注入到 system prompt（避免 LLM 误用少样本里的旧年份）
# --------------------------------------------------------------------------- #
class _DateCapturingTransport:
    """捕获实际下发给 LLM 的 prompt，用于断言"当前日期"已注入。"""

    def __init__(self, canned: str) -> None:
        self._canned = canned
        self.last_prompt: str | None = None

    def generate(self, prompt: str, *, timeout: float) -> str:
        self.last_prompt = prompt
        return self._canned


def test_parse_booking_intent_injects_current_date_into_system_prompt() -> None:
    """parse_booking_intent 调用时应在 system_prompt 里看到注入的当前日期。

    回归用户实际场景：今天 2026-07-28（周二）→ "本周六下午4点" 应被解析为
    2026-08-01T16:00:00，而非误用少样本里的 2024-01-06。
    """
    from datetime import datetime

    fixed_now = datetime(2026, 7, 28, 12, 0, 0)
    transport = _DateCapturingTransport(canned=_slots_json(pet_id=None, ambiguous=True))

    resolver = _FakeResolver(PetResolution(customer_id="cust-1", pet_ids=["pet-1"]))
    bus = _RecordingBus()
    agent = _make_agent(_slots_json(), resolver, bus, transport=transport)
    agent._now_provider = lambda: fixed_now  # type: ignore[method-assign]

    agent.run(_state("本周六下午4点给狗洗澡"))

    assert transport.last_prompt is not None
    assert "当前日期：2026-07-28" in transport.last_prompt, (
        "系统提示应包含注入的当前日期，作为 LLM 解析相对时间的锚点；"
        f"实际 prompt={transport.last_prompt[:300]!r}"
    )


def test_booking_confirmation_uses_injected_date_not_stale_few_shot() -> None:
    """回归：预约确认回复里的日期应反映当前日期，而不是少样本里的 2024-01-06。

    完整链路模拟：客户先说"想约周六下午给狗洗澡"（第一轮走 ONBOARDING_ASK_REPLY），
    再补"王炳杰，狗狗叫绒绒"（建档），最后确认"周六下午4点"（第二轮完成预约）。
    预期：确认文案里的日期为 2026-08-01 16:00-17:00（基于 2026-07-28 周二）。
    """
    from datetime import datetime

    fixed_now = datetime(2026, 7, 28, 12, 0, 0)
    # 第二轮的预约意图输出：LLM 已正确换算到 2026-08-01T16:00:00
    correct_date_slots = json.dumps(
        {
            "service_type": "grooming",
            "pet_id": "pet-1",
            "pet_ref": "绒绒",
            "requested_start": "2026-08-01T16:00:00",
            "requested_end": "2026-08-01T17:00:00",
            "confidence": 0.95,
            "ambiguous": False,
        }
    )
    resolver = _FakeResolver(PetResolution(customer_id=None, pet_ids=[]))
    bus = _RecordingBus()
    writer = _FakeOnboardingWriter()
    transport = _ConditionalOnboardingTransport(
        booking_text=correct_date_slots,
        onboarding_text_with_names=json.dumps(
            {"customer_name": "王炳杰", "pet_name": "绒绒"}
        ),
        onboarding_text_without_names=json.dumps(
            {"customer_name": None, "pet_name": None}
        ),
    )
    agent = _make_agent(
        "", resolver, bus, onboarding_writer=writer, transport=transport
    )
    agent._now_provider = lambda: fixed_now  # type: ignore[method-assign]

    state = new_state(
        TENANT,
        messages=[("user", "想约周六下午给狗洗澡"), ("user", "王炳杰，狗狗叫绒绒")],
    )
    state["external_user_id"] = EXT  # type: ignore[typeddict-unknown-key]
    delta = agent.run(state)

    output = delta["agent_outputs"]["reception"]
    assert output["status"] == "booked"
    assert "2026-08-01 16:00-17:00" in output["reply_text"], (
        "预约确认文案应反映当前日期解析后的真实日期，而非少样本里的旧年份；"
        f"实际 reply_text={output['reply_text']!r}"
    )


# --------------------------------------------------------------------------- #
# Requirement 26.3：预约提示含 JSON 示例时不得向宠物消解流程外溢异常
# --------------------------------------------------------------------------- #
def test_pet_resolution_continues_when_booking_prompt_contains_json_examples() -> None:
    """结构化示例应安全保留，且槽位解析后仍可完成客户/宠物消解与预约。"""
    resolver = _FakeResolver(PetResolution(customer_id="cust-1", pet_ids=["pet-1"]))
    bus = _RecordingBus()
    agent = _make_agent(_slots_json(pet_id=None, ambiguous=True), resolver, bus)

    delta = agent.run(_state("周六下午两点给狗洗澡"))

    output = delta["agent_outputs"]["reception"]
    assert output["status"] == "booked"
    assert output["appointment"]["customer_id"] == "cust-1"
    assert output["appointment"]["pet_id"] == "pet-1"
    assert resolver.calls == [(TENANT, EXT)]


def test_pending_onboarding_keeps_service_intent_while_collecting_remaining_fields() -> None:
    """Requirement 26.6：补档与已有预约并行，不能因资料待完善阻塞服务。"""
    resolver = _FakeResolver(
        PetResolution(
            customer_id="new-cust-1",
            pet_ids=["new-pet-1"],
            onboarding_pending=True,
            missing_profile_fields=("species", "breed"),
        )
    )
    bus = _RecordingBus()
    writer = _FakeOnboardingWriter()
    writer.update_result = PetResolution(
        customer_id="new-cust-1",
        pet_ids=["new-pet-1"],
        onboarding_pending=True,
        missing_profile_fields=("species", "breed"),
    )
    transport = _RoutingTransport(
        booking_text=_slots_json(pet_id=None, ambiguous=True),
        onboarding_text=json.dumps(
            {"customer_name": "李姐", "pet_name": "豆豆", "phone": "13800000000", "species": None, "breed": None}
        ),
    )
    agent = _make_agent("", resolver, bus, onboarding_writer=writer, transport=transport)
    state = _state("想给豆豆预约洗澡，手机号13800000000")
    state["channel"] = "wechat_public"
    state["customer_facing"] = True

    delta = agent.run(state)

    assert writer.update_calls[0]["phone"] == "13800000000"
    assert writer.update_calls[0]["species"] is None
    assert writer.update_calls[0]["breed"] is None
    assert delta["onboarding_pending"] is True
    assert "预约洗澡" in delta["pending_service_request"]
    output = delta["agent_outputs"]["reception"]
    assert output["status"] == "booked"
    assert "物种" in output["reply_text"]
    assert bus.events and bus.events[0].event_type == "appointment_booked"


def test_pending_onboarding_continues_complete_booking_before_profile_is_complete() -> None:
    """Requirement 26.6：姓名和宠物名已建档时，待补资料不能阻塞已有预约。"""
    resolver = _FakeResolver(
        PetResolution(
            customer_id="new-cust-1",
            pet_ids=["new-pet-1"],
            onboarding_pending=True,
            missing_profile_fields=("phone", "species", "breed"),
        )
    )
    bus = _RecordingBus()
    writer = _FakeOnboardingWriter()
    writer.update_result = PetResolution(
        customer_id="new-cust-1",
        pet_ids=["new-pet-1"],
        onboarding_pending=True,
        missing_profile_fields=("phone", "species", "breed"),
    )
    transport = _RoutingTransport(
        booking_text=_slots_json(pet_id=None, ambiguous=True),
        onboarding_text=json.dumps(
            {
                "customer_name": "李姐",
                "pet_name": "豆豆",
                "phone": None,
                "species": None,
                "breed": None,
            }
        ),
    )
    agent = _make_agent("", resolver, bus, onboarding_writer=writer, transport=transport)
    state = _state("想给豆豆预约周六下午两点洗澡")
    state["channel"] = "wechat_public"
    state["customer_facing"] = True

    delta = agent.run(state)

    output = delta["agent_outputs"]["reception"]
    assert output["status"] == "booked"
    assert output["appointment"]["customer_id"] == "new-cust-1"
    assert output["appointment"]["pet_id"] == "new-pet-1"
    assert "手机号" in output["reply_text"]
    assert "物种" in output["reply_text"]
    assert "无需重新说明" in output["reply_text"]
    assert delta["onboarding_pending"] is True
    assert "预约周六下午两点洗澡" in delta["pending_service_request"]
    assert bus.events
