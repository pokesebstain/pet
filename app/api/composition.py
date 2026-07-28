"""应用组合根（Composition Root）——接线业务引擎、事件总线、工具层与 AI 中枢（任务 24.1）。

对应设计文档 "Architecture / 1.1 总体分层架构"（``API Gateway / BFF`` → 业务后端 / AI 中枢）
与 Requirement 1.1（意图识别与多智能体编排）、5.1（多租户隔离与统一工具层）。

本模块把此前各任务实现的、彼此独立的组件在**同一处**装配为一个可用的应用图谱，
从而**消除孤立组件**（design.md 图 1.1 中 ``GW → Backend`` / ``GW → SUP`` /
``SUP → Experts → Tool Layer → Backend/DB`` 的接线关系）：

- **AI 决策中枢**：:func:`~app.agents.supervisor.compile_supervisor_graph` 编译带
  ``thread_id`` 持久化（Requirement 3）与可选 HITL 检查点（Requirement 4）的 Supervisor 图，
  并接线五个真实专家 Agent（:func:`~app.agents.experts.build_expert_agents`）。
- **业务引擎**：LTV / 供应链 / 健康数据中台 / 健康 Agent / 订阅 / 生态合作网络。
- **事件总线**：:class:`~app.events.EventBus`（默认内存传输），健康 Agent 与订阅 / 生态
  引擎均以其为发布端。
- **工具层 / RAG / Text2SQL / LLM**：统一工具层的租户隔离、pgvector RAG 检索、Text2SQL
  生成 + 安全执行、云端 LLM 客户端。

**可测试性（无外部依赖）**：所有外部依赖（数据库、Redis、云端 LLM、pgvector）均经协议
抽象并提供**内存 / 伪实现**默认值，因此本组合根可在**无实时网络 / 数据库 / LLM** 的
情况下完整构造，并用 FastAPI ``TestClient`` 端到端测试。生产环境可通过
:func:`build_composition` 的注入点替换为真实实现（真实 LLM 传输、pgvector 后端、
数据库 Engine 等）。
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.agents import (
    CloudLLMIntentClassifier,
    HITLCheckpoint,
    HealthAgent,
    IntentClassifier,
    InMemoryAlertTaskSink,
    InMemoryHealthMetricReader,
    MarketingAgent,
    build_expert_agents,
    compile_supervisor_graph,
)
from app.agents.experts import ExpertAgent
from app.agents.reception import ReceptionAgent
from app.core.config import Settings, get_settings
from app.engines import (
    EcosystemNetwork,
    InMemoryCustomerDirectory,
    InMemoryCustomerFeatureProvider,
    InMemoryPartnerHospitalProvider,
    InMemoryPetDirectory,
    InMemoryPlanStore,
    InMemoryReferralStore,
    InMemorySalesHistoryProvider,
    InMemorySkuMasterProvider,
    InMemorySubscriptionStore,
    LTVEngine,
    SubscriptionEngine,
    SupplyChainEngine,
)
from app.engines.scheduling_db import build_db_scheduling_engine
from app.engines.subscription import ChargeOutcome
from app.events import EventBus, InMemoryStreamTransport
from app.llm.client import CloudLLMClient, LLMTransport
from app.llm.errors import LLMUnavailableError
from app.llm.transport import build_llm_transport
from app.observability.langfuse_client import build_langfuse_client
from app.observability.tracing import (
    DecisionChainTracer,
    InMemoryTracingBackend,
    LangFuseBackend,
    TracingBackend,
)
from app.rag.retriever import RAGRetriever
from app.text2sql import SafeSQLExecutor, Text2SQLGenerator
from app.wecom import (
    HttpTransport,
    ReplySender,
    WeComInboundGateway,
)

__all__ = [
    "AppComposition",
    "build_composition",
]


# --------------------------------------------------------------------------- #
# 无外部依赖时使用的安全默认伪实现
# --------------------------------------------------------------------------- #
class _UnavailableLLMTransport:
    """默认云端 LLM 传输：无真实网络时始终判定为不可用。

    抛出 :class:`~app.llm.errors.LLMUnavailableError`，使
    :class:`~app.llm.client.CloudLLMClient` 走既定的退避 / 熔断 / 受限模板降级路径
    （Requirement 20）。因此在未注入真实传输时，应用仍可完整构造并运行——依赖 LLM 的
    能力优雅降级，而非在装配期崩溃。生产环境经 :func:`build_composition` 注入真实传输。
    """

    def generate(self, prompt: str, *, timeout: float) -> str:  # noqa: ARG002
        raise LLMUnavailableError("默认组合根未注入真实云端 LLM 传输实现。")


class _HashingEmbeddingProvider:
    """确定性文本向量化提供者（无网络）。

    基于字符散列生成固定维度向量，仅用于在无真实 embedding 服务时让 RAG 检索链路可运行 /
    可测试。生产环境应注入基于云端 embedding 服务的实现。
    """

    def __init__(self, dimensions: int = 16) -> None:
        self._dims = max(int(dimensions), 1)

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self._dims
        for index, char in enumerate(text or ""):
            vector[index % self._dims] += float(ord(char) % 17)
        return vector


class _StubSQLRunner:
    """默认底层 SQL 执行器：无数据库时返回空结果集。

    满足 :class:`~app.text2sql.SQLRunner` 协议签名，使 Text2SQL 安全执行链路在无实时
    数据库时仍可构造 / 联通（三重校验 → 执行控制）。生产环境经
    :func:`app.text2sql.build_engine_runner` 绑定真实 Engine。
    """

    def __call__(
        self, tenant_id: str, sql: str, *, timeout_seconds: float
    ) -> list[Any]:  # noqa: ARG002
        return []


class _AlwaysSuccessPaymentGateway:
    """默认收单网关伪实现：不对接任何真实收单系统。

    仅用于让订阅引擎可被完整装配（不产生孤立组件）。真实扣费始终经订阅引擎的
    HITL 审批闸门把关（默认拒绝），本伪实现不会在无批准时被调用。
    """

    def charge(self, subscription: Any, plan: Any) -> ChargeOutcome:  # noqa: ARG002
        return ChargeOutcome(success=True, transaction_id="stub-txn")


class _TracedSupervisorGraph:
    """包裹已编译 Supervisor 图，在每次 ``invoke`` 外层开启一条决策链追溯。

    对应 Requirement 18.2：为每次 Supervisor 决策留存包含关联 trace ID、请求输入、
    参与决策的各 Agent 标识、各决策节点输出与起止时间戳的追溯记录。Supervisor 内部各
    节点（意图识别 / 各专家 / 反思 / 聚合 / HITL）已通过
    :func:`~app.agents.supervisor._traced` 在活动决策链上下文中记录跨度；本包装器仅
    负责开启 / 关闭该上下文并落盘到追溯后端，对调用方（BFF 路由 / 企业微信网关）保持
    与原始 :class:`~langgraph.graph.state.CompiledStateGraph` 一致的 ``invoke`` 接口，
    因此可透明替换，不影响既有调用方代码。
    """

    def __init__(self, graph: Any, tracer: DecisionChainTracer) -> None:
        self._graph = graph
        self._tracer = tracer

    def invoke(self, state: Mapping[str, Any], config: Mapping[str, Any] | None = None) -> Any:
        tenant_id = state.get("tenant_id") if isinstance(state, Mapping) else None
        thread_id = None
        if config:
            thread_id = (config.get("configurable") or {}).get("thread_id")
        request_input = _latest_message_text(state)
        with self._tracer.trace(
            request_input=request_input, tenant_id=tenant_id, session_id=thread_id
        ) as chain:
            result = self._graph.invoke(state, config=config)
            if isinstance(result, Mapping):
                chain.set_output(result.get("final_answer"))
            return result

    def __getattr__(self, name: str) -> Any:
        # 透传其它未显式包装的方法/属性（如测试中可能访问的 get_graph 等），
        # 保持与原生 CompiledStateGraph 的最大兼容性。
        return getattr(self._graph, name)


def _latest_message_text(state: Mapping[str, Any]) -> str | None:
    """从初始状态中提取最近一条用户消息文本，作为决策链的 ``request_input``。

    兼容 ``(role, text)`` 元组与 ``{"role":..., "content":...}`` 字典两种消息形态
    （与 :mod:`app.agents.intent` 的 ``_latest_user_text`` 保持一致的兼容策略）。
    """
    if not isinstance(state, Mapping):
        return None
    messages = state.get("messages") or []
    for message in reversed(list(messages)):
        if isinstance(message, tuple) and len(message) == 2:
            text = str(message[1])
            if text.strip():
                return text
        elif isinstance(message, dict):
            text = str(message.get("content", ""))
            if text.strip():
                return text
    return None


def _build_tracer(settings: Settings) -> DecisionChainTracer:
    """按配置构造决策链追溯器：配置了 LangFuse 时上报云端，否则回退进程内后端。

    未配置 ``PETOPS_LANGFUSE_PUBLIC_KEY`` / ``PETOPS_LANGFUSE_SECRET_KEY`` 时使用
    :class:`~app.observability.tracing.InMemoryTracingBackend`（不影响任何现有功能，
    仅追溯记录不出站，可经 :meth:`DecisionChainTracer.backend` 在测试中内省）。
    """
    langfuse_client = build_langfuse_client(settings.langfuse)
    backend: TracingBackend
    if langfuse_client is not None:
        backend = LangFuseBackend(client=langfuse_client)
    else:
        backend = InMemoryTracingBackend()
    return DecisionChainTracer(backend)


# --------------------------------------------------------------------------- #
# 组合根
# --------------------------------------------------------------------------- #
@dataclass
class AppComposition:
    """已装配的应用组件图谱（供 BFF 路由与依赖注入使用）。

    该对象由 :func:`build_composition` 构造，聚合业务引擎、事件总线、工具 / RAG / Text2SQL
    层与编译后的 Supervisor 图。BFF 路由仅依赖本对象，从而与具体实现解耦。
    """

    settings: Settings
    event_bus: EventBus
    llm_client: CloudLLMClient
    ltv_engine: LTVEngine
    supply_engine: SupplyChainEngine
    health_agent: HealthAgent
    subscription_engine: SubscriptionEngine
    ecosystem_network: EcosystemNetwork
    marketing_agent: MarketingAgent
    text2sql_generator: Text2SQLGenerator
    sql_executor: SafeSQLExecutor
    rag_retriever: RAGRetriever
    classifier: IntentClassifier
    experts: Mapping[str, ExpertAgent]
    supervisor_graph: Any
    #: 可选的接待预约 Agent（企业微信洗护预约，Requirement 21）；仅在注入 DB Engine 时装配。
    reception_agent: ExpertAgent | None = None
    #: 可选的数据库 Engine（注入后工具层经其在 RLS 上下文内访问数据）；默认无（内存模式）。
    db_engine: Any | None = None
    #: 企业微信入站网关（Requirement 21）；仅在配置了 WeCom 时装配，否则为 ``None``，
    #: 此时 ``/wecom/callback`` 路由返回 503（不影响 /health 等其它路由）。
    wecom_gateway: WeComInboundGateway | None = None
    #: 决策链追溯器（Requirement 18.2 / 18.3）；配置了 LangFuse 时上报云端，否则为进程内
    #: 后端。供诊断 / 测试内省最近一次决策链，不影响主业务流程。
    tracer: DecisionChainTracer | None = None

    def component_status(self) -> dict[str, bool]:
        """返回各关键组件是否已装配，供就绪检查（readiness）内省。"""
        return {
            "event_bus": self.event_bus is not None,
            "supervisor_graph": self.supervisor_graph is not None,
            "ltv_engine": self.ltv_engine is not None,
            "supply_engine": self.supply_engine is not None,
            "health_agent": self.health_agent is not None,
            "subscription_engine": self.subscription_engine is not None,
            "ecosystem_network": self.ecosystem_network is not None,
            "marketing_agent": self.marketing_agent is not None,
            "text2sql": self.text2sql_generator is not None and self.sql_executor is not None,
            "rag_retriever": self.rag_retriever is not None,
            "experts": bool(self.experts),
        }


def build_composition(
    *,
    settings: Settings | None = None,
    classifier: IntentClassifier | None = None,
    experts: Mapping[str, ExpertAgent] | None = None,
    hitl: HITLCheckpoint | None = None,
    checkpointer: Any | None = None,
    llm_transport: LLMTransport | None = None,
    llm_client: CloudLLMClient | None = None,
    event_bus: EventBus | None = None,
    rag_retriever: RAGRetriever | None = None,
    reception_agent: ExpertAgent | None = None,
    db_engine: Any | None = None,
    wecom_gateway: WeComInboundGateway | None = None,
    wecom_reply_sender: ReplySender | None = None,
    wecom_http_transport: HttpTransport | None = None,
    tracer: DecisionChainTracer | None = None,
) -> AppComposition:
    """装配并返回 :class:`AppComposition`。

    默认在**无外部依赖**下构造（内存事件总线、降级 LLM、空 pgvector 后端、空数据库），
    使应用可被 ``TestClient`` 完整测试；生产环境经各注入点替换为真实实现。

    Args:
        settings: 应用配置；默认取进程内缓存单例 :func:`~app.core.config.get_settings`。
        classifier: 意图分类器；默认基于 ``llm_client`` 的
            :class:`~app.agents.intent.CloudLLMIntentClassifier`。
        experts: 专家 Agent 映射；默认经 :func:`~app.agents.experts.build_expert_agents`
            接线到装配好的真实引擎 / 工具。
        hitl: 可选 HITL 检查点（Requirement 4）；注入后含副作用规划在返回用户前经人工确认。
        checkpointer: LangGraph checkpointer；默认内存实现（``thread_id`` 持久化）。
        llm_transport: 云端 LLM 传输实现；默认降级传输（无真实网络）。
        llm_client: 直接注入的云端 LLM 客户端（优先于 ``llm_transport``）。
        event_bus: 事件总线；默认内存传输的 :class:`~app.events.EventBus`。
        rag_retriever: RAG 检索器；默认空 pgvector 内存后端。
        db_engine: 可选 SQLAlchemy Engine（注入后工具层经其在 RLS 上下文内访问数据）。
        wecom_gateway: 可选企业微信入站网关；缺省时若配置了 WeCom（``settings.wecom``），
            自动以真实 :class:`~app.wecom.crypto.WeComCryptoCodec` + 本组合根的 Supervisor
            图装配，否则为 ``None``（``/wecom/callback`` 路由返回 503）。
        wecom_reply_sender: 可选企业微信出站回复发送器（:class:`~app.wecom.ReplySender`）；
            注入后网关在返回回复文本的同时经其推送回客户，实现"客户消息 → 自动预约 →
            回复回推客户"闭环。缺省时若 WeCom 出站已配置（secret + agent_id），自动以默认
            urllib 传输装配 :class:`~app.wecom.WeComMessageSender`。
        wecom_http_transport: 可选 HTTP 传输实现，用于装配默认出站发送器（便于测试注入
            无网络伪实现）；缺省使用标准库 urllib 传输。
        tracer: 可选决策链追溯器（Requirement 18.2 / 18.3）；缺省按配置自动构造
            （配了 LangFuse 则上报云端，否则回退进程内后端）。

    Returns:
        AppComposition: 已装配的组件图谱。
    """
    resolved_settings = settings or get_settings()

    # --- 事件总线（默认内存传输）------------------------------------------ #
    bus = event_bus or EventBus(InMemoryStreamTransport())

    # --- 云端 LLM 客户端 --------------------------------------------------- #
    # 传输层优先级：显式注入 > 按配置构造的真实 HTTP 传输（配了 api_key）> 降级桩。
    resolved_transport = llm_transport
    if resolved_transport is None:
        resolved_transport = build_llm_transport(resolved_settings.llm) or _UnavailableLLMTransport()
    client = llm_client or CloudLLMClient(
        transport=resolved_transport,
        settings=resolved_settings.llm,
    )

    # --- 业务引擎（默认内存数据提供者）------------------------------------ #
    ltv_engine = LTVEngine(InMemoryCustomerFeatureProvider())
    supply_engine = SupplyChainEngine(
        InMemorySalesHistoryProvider(), InMemorySkuMasterProvider()
    )
    health_agent = HealthAgent(
        InMemoryHealthMetricReader(), bus, InMemoryAlertTaskSink()
    )
    subscription_engine = SubscriptionEngine(
        InMemoryPlanStore(),
        InMemorySubscriptionStore(),
        _AlwaysSuccessPaymentGateway(),
        bus,
    )
    ecosystem_network = EcosystemNetwork(
        InMemoryPartnerHospitalProvider(),
        InMemoryCustomerDirectory(),
        InMemoryPetDirectory(),
        InMemoryReferralStore(),
        bus,
    )

    # --- 工具 / RAG / Text2SQL 层 ----------------------------------------- #
    retriever = rag_retriever or RAGRetriever()
    text2sql_generator = Text2SQLGenerator(client)
    sql_executor = SafeSQLExecutor(_StubSQLRunner())
    marketing_agent = MarketingAgent(client, retriever, _HashingEmbeddingProvider())

    # --- 接待预约 Agent（企业微信洗护预约，Requirement 21 / 设计 14）---------- #
    # 有真实数据库 Engine 时接线 PostgreSQL 后端排期引擎 + 客户 / 宠物消解，构造真实
    # 接待预约 Agent；无 Engine（测试 / 内存模式）时不注册，reception 意图回退占位专家。
    resolved_reception = reception_agent
    if resolved_reception is None and db_engine is not None:
        # 时段粒度 60 分钟，与门店服务时长一致（设计 14 / 产品参数）。
        components = build_db_scheduling_engine(db_engine)
        resolved_reception = ReceptionAgent(
            client,
            components.engine,
            slot_locks=components.slot_locks,
            appointment_writer=components.appointment_writer,
            event_bus=bus,
            pet_resolver=components.pet_resolver,
            onboarding_writer=components.onboarding_writer,
        )

    # --- 专家 Agent 与 AI 决策中枢 ---------------------------------------- #
    resolved_experts: Mapping[str, ExpertAgent] = experts or build_expert_agents(
        text2sql_generator=text2sql_generator,
        sql_executor=sql_executor,
        ltv_engine=ltv_engine,
        health_agent=health_agent,
        supply_engine=supply_engine,
        marketing_agent=marketing_agent,
        reception_agent=resolved_reception,
    )
    resolved_classifier = classifier or CloudLLMIntentClassifier(client)

    compiled_graph = compile_supervisor_graph(
        classifier=resolved_classifier,
        experts=resolved_experts,
        hitl=hitl,
        checkpointer=checkpointer,
    )

    # --- 决策链追溯（Requirement 18.2 / 18.3：LangFuse Cloud 或进程内回退）--- #
    resolved_tracer = tracer or _build_tracer(resolved_settings)
    supervisor_graph = _TracedSupervisorGraph(compiled_graph, resolved_tracer)

    # --- 企业微信入站网关（仅在配置了 WeCom 时装配）--------------------- #
    resolved_wecom_gateway = wecom_gateway or _build_wecom_gateway(
        resolved_settings,
        supervisor_graph,
        reply_sender=wecom_reply_sender,
        http_transport=wecom_http_transport,
    )

    return AppComposition(
        settings=resolved_settings,
        event_bus=bus,
        llm_client=client,
        ltv_engine=ltv_engine,
        supply_engine=supply_engine,
        health_agent=health_agent,
        subscription_engine=subscription_engine,
        ecosystem_network=ecosystem_network,
        marketing_agent=marketing_agent,
        text2sql_generator=text2sql_generator,
        sql_executor=sql_executor,
        rag_retriever=retriever,
        classifier=resolved_classifier,
        experts=resolved_experts,
        supervisor_graph=supervisor_graph,
        reception_agent=resolved_reception,
        db_engine=db_engine,
        wecom_gateway=resolved_wecom_gateway,
        tracer=resolved_tracer,
    )


def _build_wecom_gateway(
    settings: Settings,
    supervisor_graph: Any,
    *,
    reply_sender: ReplySender | None = None,
    http_transport: HttpTransport | None = None,
) -> WeComInboundGateway | None:
    """按配置装配企业微信入站网关；未配置 WeCom 时返回 ``None``。

    仅当 ``settings.wecom`` 提供了 corp_id + token + encoding_aes_key 时才构造真实的
    :class:`~app.wecom.crypto.WeComCryptoCodec` 并接线到 Supervisor 图；否则返回 ``None``，
    使应用在未配置 WeCom 时仍能正常构造 / 启动（/wecom/callback 路由此时返回 503）。

    出站回复：显式注入的 ``reply_sender`` 优先；否则当出站已配置（secret + agent_id）时，
    自动以默认 urllib 传输（或注入的 ``http_transport``）装配
    :class:`~app.wecom.WeComMessageSender`，从而实现回复回推客户闭环。
    """
    wecom = getattr(settings, "wecom", None)
    if wecom is None or not wecom.is_configured:
        return None
    # 延迟导入，避免在无 WeCom 场景下引入 cryptography 依赖。
    from app.wecom.crypto import WeComCryptoCodec, WeComCryptoError

    try:
        codec = WeComCryptoCodec(
            corp_id=wecom.corp_id,
            token=wecom.token.get_secret_value(),
            encoding_aes_key=wecom.encoding_aes_key.get_secret_value(),
            # 运行时租户与种子数据保持一致：默认租户（PETOPS_DEFAULT_TENANT_ID）优先，
            # 缺省回退 corp_id（编解码器内部默认）。
            default_tenant_id=settings.resolved_default_tenant_id or None,
        )
    except (WeComCryptoError, ValueError) as exc:
        # 企业微信是可选集成：配置无效（如占位/非法 EncodingAESKey）时记日志并跳过，
        # 不阻断整个应用启动。/wecom/callback 路由此时返回 503，其它功能不受影响。
        logging.getLogger(__name__).warning(
            "企业微信配置无效，已跳过入站网关装配（/wecom/callback 将返回 503）：%s", exc
        )
        return None

    resolved_sender = reply_sender or _build_wecom_reply_sender(
        wecom, http_transport=http_transport
    )
    # 启动期打印 Token / EncodingAESKey 的长度 + 指纹（前 4 字符 / 密钥字节前 8 位十六进制），
    # 不泄露完整密钥，但足以核对当前生效配置是否与企业微信后台一致、以及容器是否已
    # 加载最新 .env（排查"后台改了密钥但容器仍用旧值"这类问题）。
    logging.getLogger(__name__).info(
        "企业微信入站网关已装配：corp_id=%s token_len=%d token_prefix=%s "
        "aes_key_fingerprint=%s",
        wecom.corp_id,
        len(wecom.token.get_secret_value()),
        wecom.token.get_secret_value()[:4],
        codec.aes_key_fingerprint(),
    )
    return WeComInboundGateway(
        codec, supervisor_graph, reply_sender=resolved_sender
    )


def _build_wecom_reply_sender(
    wecom: Any, *, http_transport: HttpTransport | None = None
) -> ReplySender | None:
    """按配置装配企业微信出站回复发送器；出站未配置时返回 ``None``。

    需要 secret + agent_id（``is_outbound_configured``）；缺省使用标准库 urllib 传输
    （不引入三方 HTTP 依赖），可经 ``http_transport`` 注入无网络伪实现以便测试。
    """
    if not getattr(wecom, "is_outbound_configured", False):
        return None
    # 延迟导入，保持无 WeCom 出站场景的最小依赖面。
    from app.wecom.sender import (
        AppMessageSendStrategy,
        UrllibHttpTransport,
        WeComAccessTokenManager,
        WeComMessageSender,
    )

    transport = http_transport or UrllibHttpTransport()
    token_manager = WeComAccessTokenManager(
        corp_id=wecom.corp_id,
        secret=wecom.secret.get_secret_value(),
        transport=transport,
        base_url=wecom.api_base_url,
    )
    strategy = AppMessageSendStrategy(agent_id=int(wecom.agent_id))
    return WeComMessageSender(
        token_manager=token_manager,
        transport=transport,
        strategy=strategy,
        base_url=wecom.api_base_url,
    )
