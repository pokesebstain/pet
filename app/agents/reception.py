"""接待预约 Agent（对应设计文档 14.3 组件 B ``Reception_Agent``，任务 27.2）。

本模块实现**接待预约 Agent** —— 一个遵循既有 :class:`~app.agents.experts.ExpertAgent`
协议（``name`` + ``run(state)`` 返回状态增量）的新专家 Agent，负责：

1. **预约意图抽取** :meth:`ReceptionAgent.parse_booking_intent`（对应设计 14.7.1）：
   经注入的 :class:`~app.llm.client.CloudLLMClient`（**提示工程 / 少样本，不微调**）在
   10 秒预算内从对话文本抽取 :class:`~app.models.scheduling.BookingIntent`（服务类型、
   目标宠物、期望时间），``confidence`` 夹取到 ``[0, 1]``；服务类型 / 宠物 / 时间任一
   缺失或无法消解时置 ``ambiguous = True``（Requirement 21.4 / 21.5）。

2. **自动预约门控** :func:`should_auto_book`（对应设计 14.6）：依据（意图是否歧义、
   置信度是否达阈值、租户是否开启自动预约、时段是否有剩余容量）将请求判定为
   ``AUTO_BOOK`` / ``FULL_SUGGEST`` / ``NEEDS_CLARIFICATION`` / ``NEEDS_HITL`` 之一。

3. **接待编排** :meth:`ReceptionAgent.handle_booking`（对应设计 14.7.5）：
   - 可用且明确 → 经 :meth:`SchedulingEngine.book_appointment` 原子写入并回复确认；
   - 满档 → 回复当日排期现状 + 至多 N 个备选时段（Requirement 23.1，门控 22.5）；
   - 歧义 / 缺槽位 → 请客户澄清；
   - 低置信 / 租户关闭自动预约 → 转 HITL 检查点（复用既有 ``pending_action`` 机制，
     Requirement 22.5）。
   - 缺失 / 空 ``tenant_id`` → 拒绝处理、不返回预约结果（Requirement 21.6 / 24.3）。

设计约束（重要）：意图抽取经**云端 LLM + 提示工程 / 少样本**实现，**不含任何模型微调**。
Agent 仅经注入的 LLM 客户端与排期引擎访问模型 / 数据，因此测试可注入伪实现（无网络 /
无数据库）。原子写入路径的三个协作者（时段行级锁 / 预约写入器 / 事件发布器）亦通过构造
函数注入，可复用排期引擎测试中的 :class:`~app.engines.scheduling.InMemoryTransactionalSlotStore`。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Protocol, Sequence, runtime_checkable

from app.agents.experts import record_expert_output
from app.agents.state import AgentState
from app.core.errors import TenantContextMissingError
from app.engines.scheduling import (
    AppointmentWriter,
    BookingEventPublisher,
    SchedulingEngine,
    SlotAvailability,
    SlotFullError,
    SlotLockManager,
)
from app.llm.client import CloudLLMClient, FewShotExample, ResponseSource
from app.models.scheduling import (
    Appointment,
    BookingIntent,
    BookingOutcome,
    BookingRequest,
    ServiceType,
    TimeSlot,
)
from app.observability.metrics import BOOKING_OUTCOMES_TOTAL

__all__ = [
    "BookingDecision",
    "ReceptionConfig",
    "ReceptionAgent",
    "should_auto_book",
    "DEFAULT_INTENT_CONFIDENCE_THRESHOLD",
    "DEFAULT_SUGGESTION_COUNT",
    "DEFAULT_SEARCH_HORIZON_DAYS",
    "DEFAULT_SLOT_MINUTES",
    "DEFAULT_INTENT_TIME_BUDGET_SECONDS",
    "BOOKING_INTENT_SYSTEM_PROMPT",
    "BOOKING_INTENT_FEW_SHOTS",
    "NEEDS_HITL_REPLY",
    "TENANT_MISSING_REPLY",
    "NO_ALTERNATIVES_REPLY",
    "NO_CUSTOMER_REPLY",
    "ONBOARDING_ASK_REPLY",
    "ONBOARDING_MISSING_PET_NAME_REPLY",
    "ONBOARDING_MISSING_CUSTOMER_NAME_REPLY",
    "OnboardingInfo",
    "OnboardingWriter",
    "NO_PET_REPLY",
    "MULTIPLE_PETS_REPLY",
    "PetResolver",
    "PetResolutionResult",
]

#: 自动预约要求的意图置信度阈值（设计 14.3 组件 B 默认值）。
DEFAULT_INTENT_CONFIDENCE_THRESHOLD: float = 0.7

#: 满档时返回的备选时段数量上限（设计 14.3 组件 B 默认值）。
DEFAULT_SUGGESTION_COUNT: int = 3

#: 备选时段搜索范围（天）。
DEFAULT_SEARCH_HORIZON_DAYS: int = 7

#: 期望时间缺少结束时刻时，默认服务时长（分钟）。
DEFAULT_SLOT_MINUTES: int = 60

#: 意图抽取时间预算（秒，Requirement 21.4："10 秒内"）。
DEFAULT_INTENT_TIME_BUDGET_SECONDS: float = 10.0

#: 转 HITL 时面向客户的回复文案。
NEEDS_HITL_REPLY: str = "已收到您的预约需求，正在为您转人工确认，请稍候。"

#: 租户上下文缺失时的回复文案（Requirement 21.6）。
TENANT_MISSING_REPLY: str = "无法处理该预约请求：缺少有效的门店（租户）上下文。"

#: 搜索范围内无任何可约时段时的提示（Requirement 23.3）。
NO_ALTERNATIVES_REPLY: str = "非常抱歉，近期暂无可预约的时段，请您稍后再试或联系门店。"

#: 无法由企业微信外部联系人消解到会员时的提示（未注入 ``onboarding_writer`` 时的兜底；
#: 注入后改为走自动建档路径，提示改为 :data:`ONBOARDING_ASK_REPLY`，见 Requirement 25）。
NO_CUSTOMER_REPLY: str = "未能识别您的会员身份，请先在门店绑定或联系门店工作人员协助预约。"

#: 找不到会员档案且已注入建档 writer 时，请客户补充建档所需信息的提示（Requirement 25）。
#: 语气模仿宠物店老板与客户沟通：亲切、口语化，开头以"小主您好"问好。
ONBOARDING_ASK_REPLY: str = (
    "小主您好～这边暂时没查到您的会员档案呢，为了顺利帮您把预约安排上，"
    "麻烦告诉我您的称呼和宝贝的名字就好啦（例如：李姐，豆豆）。"
    "手机号这些信息到店再补也完全 OK 的～"
)

#: 已提供姓名但仍无法确定宠物名时的追问提示。
ONBOARDING_MISSING_PET_NAME_REPLY: str = "请告知您的宠物名字，以便为它建立档案。"

#: 已提供宠物名但仍无法确定客户姓名时的追问提示。
ONBOARDING_MISSING_CUSTOMER_NAME_REPLY: str = "请告知您的姓名，以便为您建立会员档案。"

#: 会员名下无宠物档案时的提示（零只宠物 → 无法确定预约对象）。
NO_PET_REPLY: str = "未查询到您名下的宠物档案，请先到店建档或联系门店，我们再为您安排洗护。"

#: 会员名下有多只宠物、无法唯一确定时请客户指明（多只宠物 → 请澄清）。
MULTIPLE_PETS_REPLY: str = "您名下登记了多只宠物，请告诉我这次是给哪一只安排洗护？"


@runtime_checkable
class PetResolutionResult(Protocol):
    """客户 / 宠物消解结果的结构协议（由 DB 后端消解器结构化满足）。"""

    customer_id: str | None
    pet_ids: list[str]


@runtime_checkable
class PetResolver(Protocol):
    """由租户 + 企业微信外部联系人标识消解下单客户及其宠物的协议。

    生产环境由 :class:`~app.engines.scheduling_db.DbCustomerPetResolver`（经 RLS 查询
    ``customers`` / ``pets``）实现；测试可注入内存伪实现。未注入时接待预约 Agent 保持
    既有行为（宠物标识完全来自 LLM 抽取）。
    """

    def resolve(
        self, tenant_id: str, external_user_id: str
    ) -> PetResolutionResult:  # pragma: no cover - 协议声明
        ...


@dataclass(frozen=True)
class OnboardingInfo:
    """企业微信自动建档所需的最小信息（Requirement 25）：客户姓名 + 宠物名。

    手机号 / 宠物出生日期 / 体重等**不在此采集**，留空由店员到店后核实补全
    （避免臆造占位数据污染下游生命阶段判断 / 健康分析引擎，见迁移 008）。
    """

    customer_name: str | None = None
    pet_name: str | None = None

    @property
    def is_complete(self) -> bool:
        """姓名与宠物名均已获取，可执行建档。"""
        return bool(self.customer_name) and bool(self.pet_name)


@runtime_checkable
class OnboardingWriter(Protocol):
    """按最小信息（姓名 + 宠物名）自动建档客户与宠物的协议（Requirement 25）。

    生产环境由 :class:`~app.engines.scheduling_db.DbOnboardingWriter`（写入
    ``customers`` / ``pets``，``onboarding_pending=True``，并绑定
    ``wecom_external_id``）实现；测试可注入内存伪实现。未注入时接待预约 Agent 保持既有
    行为（找不到会员时直接以 :data:`NO_CUSTOMER_REPLY` 拒绝，不建档）。
    """

    def create(
        self,
        tenant_id: str,
        external_user_id: str,
        customer_name: str,
        pet_name: str,
    ) -> PetResolutionResult:  # pragma: no cover - 协议声明
        """建档并返回新建的客户 / 宠物标识（结构同 :class:`PetResolutionResult`）。"""
        ...


class BookingDecision(str, Enum):
    """自动预约门控判定结果（对应设计 14.6 ``should_auto_book`` 返回值）。"""

    #: 可用且明确 → 自动写入预约。
    AUTO_BOOK = "auto_book"
    #: 满档 → 回复排期现状 + 备选时段建议。
    FULL_SUGGEST = "full_suggest"
    #: 槽位缺失 / 歧义 → 请客户澄清。
    NEEDS_CLARIFICATION = "needs_clarification"
    #: 低置信 / 租户关闭自动预约 → 转 HITL 检查点。
    NEEDS_HITL = "needs_hitl"


@dataclass(frozen=True)
class ReceptionConfig:
    """接待预约门控配置（设计 14.3 组件 B 构造参数 + 14.6 门控阈值）。

    Attributes:
        auto_book_enabled: 租户是否开启"空档即自动预约"（关闭则一律转 HITL）。
        intent_confidence_threshold: 自动预约要求的最低意图置信度。
        suggestion_count: 满档时返回的备选时段数量上限。
        search_horizon_days: 备选时段搜索范围（天）。
        slot_minutes: 期望时间缺结束时刻时默认服务时长（分钟）。
    """

    auto_book_enabled: bool = True
    intent_confidence_threshold: float = DEFAULT_INTENT_CONFIDENCE_THRESHOLD
    suggestion_count: int = DEFAULT_SUGGESTION_COUNT
    search_horizon_days: int = DEFAULT_SEARCH_HORIZON_DAYS
    slot_minutes: int = DEFAULT_SLOT_MINUTES


# --------------------------------------------------------------------------- #
# 提示工程 / 少样本（预约意图抽取，不微调）
# --------------------------------------------------------------------------- #
BOOKING_INTENT_SYSTEM_PROMPT: str = (
    "你是宠物店的预约接待助手。客户消息可能包含同一次预约的多轮历史（按时间顺序、"
    "每行一条），请综合全部历史行抽取洗护/药浴预约意图：后面的行是对前面信息的补充，"
    "不是替换，例如前一行已说明是洗澡、当前行仅补充宠物与时间，仍应视为服务类型已"
    "明确（洗护），不要因为当前行未提及而判定缺失。\n"
    "【服务类型识别规则——必须严格遵守】\n"
    "1. 客户只要在任一行中提到\"洗澡\"/\"洗护\"/\"美容\"或对应英文 \"grooming\"，"
    "service_type 必须输出 \"grooming\"，不得输出 null；这是高确定性信号，"
    "不应被任何后续行的\"补充信息\"覆盖为 null。\n"
    "2. 仅当客户明确提到\"药浴\"（含\"药\"/\"皮肤治疗\"等明示医学诉求）"
    "才输出 \"medical_bath\"；\"药浴\"优先级高于\"洗澡\"（同一文本中同时出现时取 medical_bath）。\n"
    "3. service_type 仅在客户**完全没有提到任何服务关键词**时才输出 null。\n"
    "时间维度：客户说\"周六下午\"等相对时间而无具体日期时，requested_start 可输出 null "
    "（时间确实不明），但 service_type 绝不能因此被错判。"
    "仅输出 JSON，字段如下："
    '{"service_type": <"grooming"（洗护/洗澡）或 "medical_bath"（药浴）或 null>, '
    '"pet_id": <消解到的宠物标识或 null>, '
    '"pet_ref": <客户对宠物的原始指代或 null>, '
    '"requested_start": <ISO8601 期望开始时间或 null>, '
    '"requested_end": <ISO8601 期望结束时间或 null>, '
    '"confidence": <0 到 1 之间的小数>, '
    '"ambiguous": <true/false，服务类型/宠物/时间任一缺失或存在歧义时为 true>}。'
    "无法确定的字段输出 null；同一客户名下多只宠物无法消解或时间表述模糊时 ambiguous 置 true。"
)

#: 建档信息抽取系统提示（Requirement 25：仅采集姓名 + 宠物名，不臆造其它字段）。
ONBOARDING_INFO_SYSTEM_PROMPT: str = (
    "你是宠物店的接待助手。客户消息可能包含同一次建档对话的多轮历史（按时间顺序、"
    "每行一条），请从中抽取客户姓名与宠物名字，仅输出 JSON："
    '{"customer_name": <客户姓名或 null>, "pet_name": <宠物名字或 null>}。'
    "无法确定的字段输出 null，不要臆造姓名；客户姓名与宠物名通常以逗号/顿号/空格分隔，"
    "如\"李姐，豆豆\"表示客户称呼李姐、宠物名豆豆。"
)

#: 建档信息抽取少样本示例。
#: 示例贴合宠物店主与客户日常沟通的真实口吻：客户常用"X姐/X哥"或昵称自称，
#: 宠物常用昵称而非正名，避免示例过于正式（张三/旺财这种一看就是占位）。
ONBOARDING_INFO_FEW_SHOTS: tuple[FewShotExample, ...] = (
    FewShotExample(
        user="李姐，豆豆",
        assistant='{"customer_name": "李姐", "pet_name": "豆豆"}',
    ),
    FewShotExample(
        user="我叫王炳杰\n我家狗叫绒绒",
        assistant='{"customer_name": "王炳杰", "pet_name": "绒绒"}',
    ),
    FewShotExample(
        user="奶茶",
        assistant='{"customer_name": null, "pet_name": "奶茶"}',
    ),
)

#: 预约意图抽取少样本示例，帮助 Cloud_LLM 稳定输出结构化槽位。
BOOKING_INTENT_FEW_SHOTS: tuple[FewShotExample, ...] = (
    FewShotExample(
        user="我想周六下午两点带我家金毛去洗澡",
        assistant=(
            '{"service_type": "grooming", "pet_id": "pet-golden", '
            '"pet_ref": "我家金毛", "requested_start": "2024-01-06T14:00:00", '
            '"requested_end": "2024-01-06T15:00:00", "confidence": 0.93, '
            '"ambiguous": false}'
        ),
    ),
    FewShotExample(
        user="帮我家狗预约洗护",
        assistant=(
            '{"service_type": "grooming", "pet_id": null, "pet_ref": "我家狗", '
            '"requested_start": null, "requested_end": null, "confidence": 0.55, '
            '"ambiguous": true}'
        ),
    ),
    FewShotExample(
        # 多轮累积示例：第一行已说明服务与时间但宠物指代模糊；第二行补充宠物名与精确
        # 时间，未重复提及服务类型——仍应综合两行判定服务类型已明确（洗护）。宠物标识
        # 消解由下游 pet_resolver（企业微信客户→客户/宠物档案）负责，此处 pet_id 留空
        # 属预期；ambiguous 仍为 true（因宠物尚未消解到具体 ID），但 service_type /
        # requested_start 均不再是 null，避免下游误判"服务类型/时间缺失"而重复追问。
        user="想约周六下午给狗洗澡\n绒绒，下午4点",
        assistant=(
            '{"service_type": "grooming", "pet_id": null, "pet_ref": "绒绒", '
            '"requested_start": "2024-01-06T16:00:00", '
            '"requested_end": "2024-01-06T17:00:00", "confidence": 0.9, '
            '"ambiguous": true}'
        ),
    ),
)


# --------------------------------------------------------------------------- #
# 门控判定（设计 14.6）
# --------------------------------------------------------------------------- #
def should_auto_book(
    intent: BookingIntent,
    availability: SlotAvailability | None,
    config: ReceptionConfig,
) -> BookingDecision:
    """自动预约门控判定（对应设计 14.6 ``should_auto_book``）。

    判定顺序（与设计伪代码一致）：

    1. 租户关闭自动预约 → :attr:`BookingDecision.NEEDS_HITL`。
    2. 意图歧义 → :attr:`BookingDecision.NEEDS_CLARIFICATION`（请客户澄清）。
    3. 置信度低于阈值 → :attr:`BookingDecision.NEEDS_HITL`。
    4. 服务类型 / 宠物 / 期望时间任一缺失 → :attr:`BookingDecision.NEEDS_CLARIFICATION`。
    5. 时段无剩余容量（或可用性未知）→ :attr:`BookingDecision.FULL_SUGGEST`。
    6. 其余（可用且明确）→ :attr:`BookingDecision.AUTO_BOOK`。

    Args:
        intent: 抽取出的预约意图。
        availability: 目标时段可用性；槽位不完整时可为 ``None``。
        config: 门控配置。

    Returns:
        BookingDecision: 四类门控结果之一。
    """
    if not config.auto_book_enabled:
        return BookingDecision.NEEDS_HITL
    if intent.ambiguous:
        return BookingDecision.NEEDS_CLARIFICATION
    if intent.confidence < config.intent_confidence_threshold:
        return BookingDecision.NEEDS_HITL
    if (
        intent.service_type is None
        or intent.pet_id is None
        or intent.requested_start is None
    ):
        return BookingDecision.NEEDS_CLARIFICATION
    # 时段满档或（防御性）可用性未知 / 越营业时间 → 走满档建议路径。
    if availability is None or not availability.in_business_hours:
        return BookingDecision.FULL_SUGGEST
    if availability.available <= 0:
        return BookingDecision.FULL_SUGGEST
    return BookingDecision.AUTO_BOOK


class ReceptionAgent:
    """接待预约 Agent（设计 14.3 组件 B），遵循 :class:`ExpertAgent` 协议。

    Args:
        llm_client: 云端 LLM 客户端（提示工程 / 少样本抽取预约槽位，不微调）。
        scheduling_engine: 排期引擎（可用性检查 / 某日排期 / 备选建议 / 原子预约）。
        config: 门控配置；未提供时用 ``ReceptionConfig`` 的默认值，可用下列关键字覆盖。
        auto_book_enabled / intent_confidence_threshold / suggestion_count: 便捷覆盖项
            （当未显式传入 ``config`` 时生效），与设计 14.3 组件 B 构造签名一致。
        slot_locks / appointment_writer / event_bus: 原子写入预约所需的三个协作者
            （复刻 ``SELECT … FOR UPDATE`` 行级锁 / 事务内 INSERT / 领域事件发布）。
            自动预约需三者齐备；缺任一时自动降级为转 HITL（避免误写）。
        time_budget_seconds: 意图抽取时间预算（秒，Requirement 21.4）。
    """

    name = "reception"

    def __init__(
        self,
        llm_client: CloudLLMClient,
        scheduling_engine: SchedulingEngine,
        *,
        config: ReceptionConfig | None = None,
        auto_book_enabled: bool = True,
        intent_confidence_threshold: float = DEFAULT_INTENT_CONFIDENCE_THRESHOLD,
        suggestion_count: int = DEFAULT_SUGGESTION_COUNT,
        slot_locks: SlotLockManager | None = None,
        appointment_writer: AppointmentWriter | None = None,
        event_bus: BookingEventPublisher | None = None,
        pet_resolver: PetResolver | None = None,
        onboarding_writer: OnboardingWriter | None = None,
        time_budget_seconds: float = DEFAULT_INTENT_TIME_BUDGET_SECONDS,
        system_prompt: str = BOOKING_INTENT_SYSTEM_PROMPT,
        few_shots: Sequence[FewShotExample] = BOOKING_INTENT_FEW_SHOTS,
        onboarding_system_prompt: str = ONBOARDING_INFO_SYSTEM_PROMPT,
        onboarding_few_shots: Sequence[FewShotExample] = ONBOARDING_INFO_FEW_SHOTS,
    ) -> None:
        self._llm = llm_client
        self._scheduling = scheduling_engine
        self._config = config or ReceptionConfig(
            auto_book_enabled=auto_book_enabled,
            intent_confidence_threshold=intent_confidence_threshold,
            suggestion_count=suggestion_count,
        )
        self._slot_locks = slot_locks
        self._appointment_writer = appointment_writer
        self._event_bus = event_bus
        self._pet_resolver = pet_resolver
        self._onboarding_writer = onboarding_writer
        self._time_budget = float(time_budget_seconds)
        self._system_prompt = system_prompt
        self._few_shots = tuple(few_shots)
        self._onboarding_system_prompt = onboarding_system_prompt
        self._onboarding_few_shots = tuple(onboarding_few_shots)

    # ------------------------------------------------------------------ #
    # ExpertAgent 协议入口
    # ------------------------------------------------------------------ #
    def run(self, state: AgentState) -> AgentState:
        """遵循 ExpertAgent 协议：抽取意图 → 编排预约 → 返回状态增量。

        缺失 / 空 ``tenant_id`` 时**优雅拒绝**：返回 ``status="rejected"`` 的接待输出，
        不抛错、不产生任何预约结果（Requirement 21.6）。转 HITL 时在增量中写入
        ``pending_action``（复用既有 HITL 中断 / 恢复机制）。
        """
        tenant_id = state.get("tenant_id")
        if not _is_valid_tenant(tenant_id):
            outcome = BookingOutcome(status="rejected", reply_text=TENANT_MISSING_REPLY)
            return record_expert_output(self.name, state, _outcome_to_output(outcome))

        # 拼接**本线程全部历史**用户消息（而非仅最新一条）用于槽位抽取：企业微信
        # 场景下客户往往分多轮补充信息（如第一轮说明服务与时间、第二轮才补充宠物），
        # 若仅看最新一条会丢失早前已明确的槽位，导致重复追问已经回答过的问题。
        text = _all_user_text(state.get("messages", []))
        intent = self.parse_booking_intent(text, tenant_id)  # type: ignore[arg-type]

        # 若注入了客户 / 宠物消解器：由企业微信外部联系人解析下单客户与宠物。
        # 恰好一只宠物 → 注入宠物标识并回填客户标识；零只 / 多只 → 请客户澄清（不预约）。
        if self._pet_resolver is not None:
            resolved = self._resolve_customer_and_pet(intent, tenant_id, state)  # type: ignore[arg-type]
            if isinstance(resolved, BookingOutcome):
                return record_expert_output(
                    self.name, state, _outcome_to_output(resolved)
                )
            intent, state = resolved

        outcome = self.handle_booking(intent, state)

        delta = record_expert_output(self.name, state, _outcome_to_output(outcome))
        if outcome.status == "needs_hitl":
            delta["pending_action"] = self._build_booking_action(intent, state)
        return delta

    # ------------------------------------------------------------------ #
    # 客户 / 宠物消解（DB 后端；仅在注入 pet_resolver 时启用）
    # ------------------------------------------------------------------ #
    def _resolve_customer_and_pet(
        self, intent: BookingIntent, tenant_id: str, state: AgentState
    ) -> "tuple[BookingIntent, AgentState] | BookingOutcome":
        """经消解器解析客户 / 宠物，回填意图与状态；无法唯一确定时返回澄清结果。

        Returns:
            - ``(enriched_intent, enriched_state)``：找到客户且恰好一只宠物（或 LLM 已
              消解到该客户名下的某只宠物）时，注入宠物标识并把解析出的 ``customer_id``
              回填到状态；
            - :class:`BookingOutcome`（``needs_clarification``）：找不到客户、名下无宠物
              或有多只宠物且无法唯一确定时，请客户澄清（不预约）。
        """
        external_user_id = _external_user_id(state)
        if not external_user_id:
            # 无外部联系人标识（如非企业微信入站）：保持既有行为，不做消解。
            return intent, state

        resolution = self._pet_resolver.resolve(tenant_id, external_user_id)  # type: ignore[union-attr]
        if resolution.customer_id is None:
            if self._onboarding_writer is not None:
                return self._onboard_new_customer(
                    intent, tenant_id, external_user_id, state
                )
            return BookingOutcome(
                status="needs_clarification", reply_text=NO_CUSTOMER_REPLY
            )

        enriched_state: AgentState = {**state, "customer_id": resolution.customer_id}  # type: ignore[assignment]
        pet_ids = list(resolution.pet_ids)

        if len(pet_ids) == 0:
            return BookingOutcome(
                status="needs_clarification", reply_text=NO_PET_REPLY
            )
        if len(pet_ids) == 1:
            return self._enrich_intent_pet(intent, pet_ids[0]), enriched_state
        # 多只宠物：若 LLM 已消解到该客户名下的某只，采用之；否则请客户指明。
        if intent.pet_id in pet_ids:
            return self._enrich_intent_pet(intent, intent.pet_id), enriched_state
        return BookingOutcome(
            status="needs_clarification", reply_text=MULTIPLE_PETS_REPLY
        )

    # ------------------------------------------------------------------ #
    # 自动建档（Requirement 25：找不到会员时仅采集姓名 + 宠物名即建档）
    # ------------------------------------------------------------------ #
    def _onboard_new_customer(
        self,
        intent: BookingIntent,
        tenant_id: str,
        external_user_id: str,
        state: AgentState,
    ) -> BookingOutcome:
        """未识别到会员档案时，经对话历史抽取姓名 + 宠物名并自动建档。

        经**本线程全部历史**用户消息（而非仅最新一条）抽取，使客户分多轮提供信息
        （如先说预约需求、被追问后再补充姓名与宠物名）时也能被正确识别，不会重复
        追问已经提供过的部分（与 :meth:`parse_booking_intent` 的多轮拼接策略一致）。

        Returns:
            - 姓名 + 宠物名均已获取：建档成功，返回把 :class:`OnboardingWriter` 建档的
              宠物标识注入原意图后 **重新走一次预约编排**（:meth:`handle_booking`）的
              结果——即建档成功可在同一轮内直接完成预约，不强制多问一轮。
            - 任一缺失：请客户补充缺失的那一项（不重复问已提供的部分）。
        """
        text = _all_user_text(state.get("messages", []))
        info = self.extract_onboarding_info(text)

        if not info.is_complete:
            if info.pet_name and not info.customer_name:
                reply = ONBOARDING_MISSING_CUSTOMER_NAME_REPLY
            elif info.customer_name and not info.pet_name:
                reply = ONBOARDING_MISSING_PET_NAME_REPLY
            else:
                reply = ONBOARDING_ASK_REPLY
            return BookingOutcome(status="needs_clarification", reply_text=reply)

        resolution = self._onboarding_writer.create(  # type: ignore[union-attr]
            tenant_id, external_user_id, info.customer_name, info.pet_name  # type: ignore[arg-type]
        )
        enriched_state: AgentState = {**state, "customer_id": resolution.customer_id}  # type: ignore[assignment]
        # 防御性服务类型兜底：LLM 在多轮场景下偶发将"洗澡"判为 service_type=null，
        # 而本轮 onboarding 才拿到姓名+宠物名，正是客户首次完整表达意图的时机。
        # 仅在 LLM 未给出时按全量历史关键词回填，不覆盖 LLM 已给出的判断。
        if intent.service_type is None:
            inferred = _coerce_service_type_from_keywords(text)
            if inferred is not None:
                intent = intent.model_copy(update={"service_type": inferred})
        enriched_intent = self._enrich_intent_pet(intent, resolution.pet_ids[0])
        outcome = self.handle_booking(enriched_intent, enriched_state)
        # 建档成功的确认前缀：即便随后走澄清 / 满档 / HITL 分支，也让客户知道档案已建好。
        return outcome.model_copy(
            update={
                "reply_text": f"已为您建立会员档案（{info.customer_name} / {info.pet_name}）。"
                + outcome.reply_text
            }
        )

    def extract_onboarding_info(self, text: str) -> OnboardingInfo:
        """经 Cloud_LLM 提示工程 / 少样本从对话文本抽取建档信息（不微调）。

        任一降级（模板 / 重述）或空文本均视为无法抽取（两字段皆 ``None``），交由调用方
        请客户补充，不臆造姓名。
        """
        if not text or not text.strip():
            return OnboardingInfo()
        response = self._llm.complete(
            text,
            system_prompt=self._onboarding_system_prompt,
            examples=self._onboarding_few_shots,
        )
        if response.source is not ResponseSource.LLM:
            return OnboardingInfo()
        payload = _extract_json(response.text)
        if payload is None:
            return OnboardingInfo()
        return OnboardingInfo(
            customer_name=_coerce_optional_str(payload.get("customer_name")),
            pet_name=_coerce_optional_str(payload.get("pet_name")),
        )

    @staticmethod
    def _enrich_intent_pet(intent: BookingIntent, pet_id: str) -> BookingIntent:
        """把消解出的宠物标识注入意图，并据此重算 ``ambiguous``（清除宠物歧义）。

        重算后 ``ambiguous`` 仅由服务类型 / 期望时间是否缺失决定，与
        :meth:`_parse_intent_payload` 的判定口径一致（宠物已消解，不再是歧义源）。
        """
        ambiguous = intent.service_type is None or intent.requested_start is None
        return intent.model_copy(update={"pet_id": pet_id, "ambiguous": ambiguous})

    # ------------------------------------------------------------------ #
    # 预约意图抽取（设计 14.7.1，Requirement 21.4 / 21.5）
    # ------------------------------------------------------------------ #
    def parse_booking_intent(self, text: str, tenant_id: str) -> BookingIntent:
        """经 Cloud_LLM 提示工程 / 少样本抽取预约意图（不微调，10s 预算）。

        Args:
            text: 客户自然语言消息。
            tenant_id: 当前门店（租户）上下文；缺失或为空时拒绝（Requirement 21.6）。

        Returns:
            BookingIntent: ``confidence`` 恒 ∈ [0, 1]；服务类型 / 宠物 / 时间任一缺失或
            无法消解时 ``ambiguous = True``（Requirement 21.5）。纯读取、无副作用。

        Raises:
            TenantContextMissingError: ``tenant_id`` 缺失或为空（Requirement 21.6）。
        """
        _require_tenant(tenant_id)
        if not text or not text.strip():
            # 无可解析文本：视为完全歧义，置信度 0（不臆造槽位）。
            return BookingIntent(confidence=0.0, ambiguous=True)

        started = time.monotonic()
        response = self._llm.complete(
            text, system_prompt=self._system_prompt, examples=self._few_shots
        )
        elapsed = time.monotonic() - started
        # 10 秒预算守卫（Requirement 21.4）：超预算按无法可靠抽取处理，不臆造槽位。
        if elapsed > self._time_budget:
            return BookingIntent(confidence=0.0, ambiguous=True)

        # 任一降级（模板 / 重述）都无法提供可靠槽位 → 标记歧义交由澄清 / HITL 路径。
        if response.source is not ResponseSource.LLM:
            return BookingIntent(confidence=0.0, ambiguous=True)

        return self._parse_intent_payload(response.text)

    def _parse_intent_payload(self, text: str) -> BookingIntent:
        """解析 Cloud_LLM 返回的结构化槽位 JSON，构造 :class:`BookingIntent`。"""
        payload = _extract_json(text)
        if payload is None:
            return BookingIntent(confidence=0.0, ambiguous=True)

        service_type = _coerce_service_type(payload.get("service_type"))
        pet_id = _coerce_optional_str(payload.get("pet_id"))
        pet_ref = _coerce_optional_str(payload.get("pet_ref"))
        requested_start = _coerce_datetime(payload.get("requested_start"))
        requested_end = _coerce_datetime(payload.get("requested_end"))
        if requested_start is not None and requested_end is None:
            requested_end = requested_start + timedelta(minutes=self._config.slot_minutes)
        confidence = _clamp(_coerce_float(payload.get("confidence"), 0.0), 0.0, 1.0)

        # 歧义判定（设计 14.7.1）：LLM 显式标记，或服务类型 / 时间 / 宠物任一无法确定。
        ambiguous = (
            bool(payload.get("ambiguous", False))
            or service_type is None
            or requested_start is None
            or pet_id is None
        )

        return BookingIntent(
            service_type=service_type,
            pet_ref=pet_ref,
            pet_id=pet_id,
            requested_start=requested_start,
            requested_end=requested_end,
            confidence=confidence,
            ambiguous=ambiguous,
        )

    # ------------------------------------------------------------------ #
    # 接待编排主流程（设计 14.7.5）
    # ------------------------------------------------------------------ #
    def handle_booking(self, intent: BookingIntent, state: AgentState) -> BookingOutcome:
        """按门控判定编排：自动预约 / 满档建议 / 请澄清 / 转 HITL。

        Args:
            intent: 抽取出的预约意图。
            state: 全局状态（须携带非空 ``tenant_id``）。

        Returns:
            BookingOutcome: 含面向客户的回复文案与结构化结果。

        Raises:
            TenantContextMissingError: ``state.tenant_id`` 缺失或为空（Requirement 21.6 / 24.3）。
        """
        tenant_id = state.get("tenant_id")
        _require_tenant(tenant_id)
        assert tenant_id is not None  # 已由 _require_tenant 保证

        availability = self._maybe_check_availability(intent, tenant_id)
        decision = should_auto_book(intent, availability, self._config)
        BOOKING_OUTCOMES_TOTAL.labels(decision=decision.value).inc()

        if decision is BookingDecision.NEEDS_CLARIFICATION:
            return BookingOutcome(
                status="needs_clarification",
                reply_text=_ask_missing_slots(intent),
            )
        if decision is BookingDecision.NEEDS_HITL:
            return BookingOutcome(status="needs_hitl", reply_text=NEEDS_HITL_REPLY)
        if decision is BookingDecision.FULL_SUGGEST:
            return self._full_suggest(intent, tenant_id)
        # AUTO_BOOK：可用且明确 → 原子写入预约。
        return self._auto_book(intent, state, tenant_id)

    # ------------------------------------------------------------------ #
    # 内部：可用性检查
    # ------------------------------------------------------------------ #
    def _maybe_check_availability(
        self, intent: BookingIntent, tenant_id: str
    ) -> SlotAvailability | None:
        """槽位完整时检查目标时段可用性；否则返回 ``None``（交由门控请澄清）。"""
        if (
            intent.service_type is None
            or intent.requested_start is None
            or intent.requested_end is None
        ):
            return None
        return self._scheduling.check_availability(
            tenant_id, intent.service_type, intent.requested_start, intent.requested_end
        )

    # ------------------------------------------------------------------ #
    # 内部：满档 → 排期现状 + 备选建议（Requirement 23.1 / 23.2 / 23.3）
    # ------------------------------------------------------------------ #
    def _full_suggest(self, intent: BookingIntent, tenant_id: str) -> BookingOutcome:
        """满档路径：回复当日排期现状并给出至多 N 个真实可用备选时段。"""
        assert intent.service_type is not None and intent.requested_start is not None
        schedule = self._scheduling.get_day_schedule(
            tenant_id, intent.service_type, intent.requested_start.date()
        )
        alternatives = self._scheduling.suggest_alternatives(
            tenant_id,
            intent.service_type,
            intent.requested_start,
            self._config.suggestion_count,
            self._config.search_horizon_days,
        )
        return BookingOutcome(
            status="full",
            current_schedule=schedule,
            alternatives=alternatives,
            reply_text=_render_full_reply(schedule, alternatives),
        )

    # ------------------------------------------------------------------ #
    # 内部：自动预约（Requirement 22.1）
    # ------------------------------------------------------------------ #
    def _auto_book(
        self, intent: BookingIntent, state: AgentState, tenant_id: str
    ) -> BookingOutcome:
        """自动预约路径：构造请求并经排期引擎原子写入，回复确认文案。

        写入协作者（行级锁 / 写入器 / 事件发布）缺失时降级为转 HITL；写入时若因并发争抢
        导致满档（:class:`SlotFullError`），回退到满档建议路径（Requirement 22.2 / 23.4）。
        """
        if (
            self._slot_locks is None
            or self._appointment_writer is None
            or self._event_bus is None
        ):
            # 无法自动写入（缺协作者）：安全降级为转 HITL，避免误订。
            return BookingOutcome(status="needs_hitl", reply_text=NEEDS_HITL_REPLY)

        customer_id = _customer_id(state)
        if not customer_id or not intent.pet_id:
            # 缺客户标识 / 宠物标识：请客户补充。
            return BookingOutcome(
                status="needs_clarification", reply_text=_ask_missing_slots(intent)
            )

        assert intent.service_type is not None
        assert intent.requested_start is not None and intent.requested_end is not None

        request = BookingRequest(
            tenant_id=tenant_id,
            customer_id=customer_id,
            pet_id=intent.pet_id,
            service_type=intent.service_type,
            start_at=intent.requested_start,
            end_at=intent.requested_end,
        )
        try:
            appointment: Appointment = self._scheduling.book_appointment(
                request,
                context_tenant_id=tenant_id,
                slot_locks=self._slot_locks,
                appointment_writer=self._appointment_writer,
                event_bus=self._event_bus,
            )
        except SlotFullError:
            # 并发争抢导致满档：回退为满档建议（回复现状 + 备选）。
            return self._full_suggest(intent, tenant_id)

        return BookingOutcome(
            status="booked",
            appointment=appointment,
            reply_text=_render_confirm_reply(appointment),
        )

    # ------------------------------------------------------------------ #
    # 内部：构造转 HITL 的待确认动作（复用既有 pending_action 机制）
    # ------------------------------------------------------------------ #
    def _build_booking_action(
        self, intent: BookingIntent, state: AgentState
    ) -> dict[str, Any]:
        """构造展示给用户 / 老板端的待确认预约动作（含动作类型、目标、影响范围）。"""
        start = intent.requested_start.isoformat() if intent.requested_start else None
        end = intent.requested_end.isoformat() if intent.requested_end else None
        return {
            "action_type": "appointment_book",
            "target": {
                "tenant_id": state.get("tenant_id"),
                "customer_id": _customer_id(state),
                "pet_id": intent.pet_id,
                "service_type": (
                    intent.service_type.value if intent.service_type else None
                ),
                "start_at": start,
                "end_at": end,
            },
            "impact_scope": "single_appointment",
            "status": "pending_approval",
            "executed": False,
        }


# --------------------------------------------------------------------------- #
# 回复文案渲染
# --------------------------------------------------------------------------- #
def _ask_missing_slots(intent: BookingIntent) -> str:
    """构造请客户补充缺失 / 歧义槽位的澄清文案。

    语气以宠物店老板口吻与客户沟通，开头"小主您好"；只问**当前确实缺失**的项，
    不重复列出已被客户告知过的服务 / 宠物 / 时间。
    """
    missing: list[str] = []
    if intent.service_type is None:
        missing.append("服务类型（洗护 / 药浴）")
    if intent.pet_id is None:
        missing.append("具体是哪只宠物")
    if intent.requested_start is None:
        missing.append("期望的到店时间")
    if not missing:
        # 歧义但槽位齐全（如多宠物无法消解）：请客户进一步确认。
        return "小主您好～为了帮您准确预约，麻烦再确认一下具体的宠物与到店时间。"
    # 仅缺期望时间（service_type 已知为洗护/药浴，pet_id 已知）→ 直接问"具体几点"。
    # 这是建档成功后最常见的澄清场景：客户已说"周六下午给狗洗澡"，只差具体时间点。
    if (
        intent.service_type is not None
        and intent.pet_id is not None
        and intent.requested_start is None
    ):
        return "小主您好～您这边大概具体几点能到店呢？告诉我一个时间点我帮您安排～"
    return "小主您好～为了帮您完成预约，请补充：" + "、".join(missing) + "。"


def _render_full_reply(
    schedule: Sequence[TimeSlot], alternatives: Sequence[TimeSlot]
) -> str:
    """构造满档回复：当日排期占用现状 + 备选时段建议（Requirement 23.1 / 23.3）。"""
    if not alternatives:
        return NO_ALTERNATIVES_REPLY
    booked = sum(1 for slot in schedule if slot.available <= 0)
    header = (
        f"您期望的时段已约满（当日 {len(schedule)} 个时段中有 {booked} 个已满）。"
        "为您推荐以下就近可约时段："
    )
    lines = [
        f"{index}. {_format_slot(slot)}"
        for index, slot in enumerate(alternatives, start=1)
    ]
    return header + "\n" + "\n".join(lines)


def _render_confirm_reply(appointment: Appointment) -> str:
    """构造自动预约成功的确认回复。"""
    return (
        "已为您预约成功！服务："
        f"{_service_label(appointment.service_type)}，时间："
        f"{_format_range(appointment.start_at, appointment.end_at)}。期待您的到来。"
    )


def _format_slot(slot: TimeSlot) -> str:
    return f"{_format_range(slot.start_at, slot.end_at)}（剩余 {slot.available} 个名额）"


def _format_range(start_at: datetime, end_at: datetime) -> str:
    return f"{start_at.strftime('%Y-%m-%d %H:%M')}-{end_at.strftime('%H:%M')}"


def _service_label(service_type: ServiceType) -> str:
    return {"grooming": "洗护", "medical_bath": "药浴"}.get(
        service_type.value, service_type.value
    )


# --------------------------------------------------------------------------- #
# 输出增量映射
# --------------------------------------------------------------------------- #
def _outcome_to_output(outcome: BookingOutcome) -> dict[str, Any]:
    """将 :class:`BookingOutcome` 转为专家输出增量（含供聚合使用的 ``summary``）。"""
    return {
        "status": outcome.status,
        "summary": outcome.reply_text,
        "reply_text": outcome.reply_text,
        "appointment": (
            outcome.appointment.model_dump(mode="json")
            if outcome.appointment is not None
            else None
        ),
        "alternatives": [slot.model_dump(mode="json") for slot in outcome.alternatives],
        "current_schedule": [
            slot.model_dump(mode="json") for slot in outcome.current_schedule
        ],
    }


# --------------------------------------------------------------------------- #
# 辅助函数
# --------------------------------------------------------------------------- #
def _is_valid_tenant(tenant_id: object) -> bool:
    return isinstance(tenant_id, str) and bool(tenant_id.strip())


def _require_tenant(tenant_id: object) -> None:
    """校验租户上下文；缺失或为空时抛 :class:`TenantContextMissingError`（Req 21.6 / 24.3）。"""
    if not _is_valid_tenant(tenant_id):
        raise TenantContextMissingError(
            "接待预约要求非空 tenant_id：缺少门店（租户）上下文，拒绝处理预约请求。"
        )


def _customer_id(state: AgentState) -> str:
    """从状态提取客户标识（企业微信外部用户），兼容多种承载键。"""
    for key in ("customer_id", "external_user_id", "customer"):
        value = state.get(key)  # type: ignore[call-overload]
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _external_user_id(state: AgentState) -> str:
    """提取企业微信外部联系人标识，用于客户 / 宠物消解（优先 external_user_id）。"""
    for key in ("external_user_id", "customer_id", "customer"):
        value = state.get(key)  # type: ignore[call-overload]
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _latest_user_text(messages: Sequence[Any]) -> str:
    """从对话历史中提取最近一条用户文本（兼容元组 / 字典 / 带 ``content`` 的对象）。"""
    for message in reversed(list(messages)):
        if isinstance(message, tuple) and len(message) == 2:
            text = str(message[1])
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


def _message_text(message: Any) -> str:
    """提取单条消息的文本（兼容元组 / 字典 / 带 ``content`` 的对象），无法提取时返回空串。"""
    if isinstance(message, tuple) and len(message) == 2:
        return str(message[1])
    if isinstance(message, dict):
        return str(message.get("content", ""))
    content = getattr(message, "content", None)
    if content is not None:
        return str(content)
    return ""


def _all_user_text(messages: Sequence[Any]) -> str:
    """拼接本线程**全部**用户消息文本（按时间顺序，早→晚），用于多轮槽位抽取。

    企业微信客户常分多轮补充预约信息（先说服务与时间，再补宠物，或反之）；仅看最新
    一条会丢失早前已明确的槽位，导致重复追问。拼接全部历史后交给 LLM 一次性抽取，
    使后一轮能"记住"前一轮已确认的信息（配合少样本提示，模型可综合多行文本判断）。
    空文本行会被跳过；结果为空时返回空串（按无输入处理，进入完全歧义分支）。
    """
    lines = [text for m in messages if (text := _message_text(m).strip())]
    return "\n".join(lines)


def _extract_json(text: str) -> dict | None:
    """从文本中提取首个 JSON 对象；无有效对象时返回 ``None``。"""
    if not text:
        return None
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except (ValueError, TypeError):
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            parsed = json.loads(text[start : end + 1])
            return parsed if isinstance(parsed, dict) else None
        except (ValueError, TypeError):
            return None
    return None


def _coerce_service_type(value: object) -> ServiceType | None:
    """将槽位中的服务类型安全转为 :class:`ServiceType`；无法识别时返回 ``None``。"""
    if value is None:
        return None
    try:
        return ServiceType(str(value).strip().lower())
    except ValueError:
        return None


#: 关键词 → 服务类型 的兜底映射（防御 LLM 漏识别"洗澡/药浴"等高确定性信号）。
#: 用于 :func:`_coerce_service_type_from_keywords`，仅在 LLM 未给出 service_type 时回填，
#: 不覆盖 LLM 已给出的判断（避免与 LLM 的多轮综合判定冲突）。
_SERVICE_TYPE_KEYWORDS: tuple[tuple[ServiceType, tuple[str, ...]], ...] = (
    (ServiceType.MEDICAL_BATH, ("药浴",)),
    # 洗护相关：包含"洗护"/"洗澡"/"美容"/"grooming"等都映射到 grooming。
    # "洗" 单字易误命中（如"洗一下手"），故不放宽到单字。
    (ServiceType.GROOMING, ("洗护", "洗澡", "美容", "grooming")),
)


def _coerce_service_type_from_keywords(text: str) -> ServiceType | None:
    """从对话全文扫描服务类型关键词，命中即返回 :class:`ServiceType`，否则 ``None``。

    优先级：medical_bath 优先（药浴是高特异度信号，不会被一般"洗澡"覆盖）；
    grooming 次之。同一类别多关键词命中以最先出现的为准；任一类别命中即返回。
    文本为空或未命中任何关键词时返回 ``None``，不臆造。
    """
    if not text:
        return None
    lowered = text.casefold()
    for service_type, keywords in _SERVICE_TYPE_KEYWORDS:
        for keyword in keywords:
            if keyword and keyword.casefold() in lowered:
                return service_type
    return None


def _coerce_optional_str(value: object) -> str | None:
    """将槽位字段安全转为非空字符串；缺失 / 空白时返回 ``None``。"""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coerce_datetime(value: object) -> datetime | None:
    """将 ISO8601 字符串安全解析为 :class:`datetime`；无法解析时返回 ``None``。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _coerce_float(value: object, default: float) -> float:
    """将任意值安全转为 float；失败时返回默认值。"""
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, low: float, high: float) -> float:
    """将数值夹取到 [low, high] 闭区间。"""
    return max(low, min(high, value))
