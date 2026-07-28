"""FastAPI 应用工厂与 BFF 路由（任务 24.1，Requirement 1.1 / 5.1）。

对应设计文档 "Architecture / 1.1 总体分层架构" 接入层
``API Gateway / BFF（FastAPI Router + Auth + RLS 上下文）`` 与时序图 2.1
（``GW → SUP: invoke(query, thread_id)``）。

本模块提供 :func:`create_app` 应用工厂，装配以下路由：

- ``GET /health``：存活探针（liveness），无需租户上下文。
- ``GET /ready``：就绪探针（readiness），内省组合根各组件是否已装配。
- ``POST /agent/query``：将自然语言请求经认证 + RLS 上下文注入后转发至 Supervisor
  （:func:`~app.agents.supervisor.compile_supervisor_graph` 编译的图），支持 ``thread_id``
  多轮有状态会话（Requirement 3）。受保护端点强制要求租户上下文，缺失即拒绝（HTTP 401）。

设计要点：路由层不直接构造任何业务组件，仅依赖注入的 :class:`~app.api.composition.AppComposition`
（组合根）。这既消除了组件孤立，也使应用可在**无外部依赖**下用 ``TestClient`` 端到端测试。
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from fastapi import Depends, FastAPI, Request, Response
from pydantic import BaseModel, Field

from app.api.auth import require_tenant
from app.api.composition import AppComposition, build_composition
from app.api.wecom_routes import register_wecom_routes
from app.core.config import get_settings
from app.observability.metrics import (
    CONTENT_TYPE_LATEST,
    HTTP_REQUEST_DURATION,
    HTTP_REQUESTS_TOTAL,
    render_latest,
)

__all__ = [
    "create_app",
    "AgentQueryRequest",
    "AgentQueryResponse",
]


class AgentQueryRequest(BaseModel):
    """向 Supervisor 提交的自然语言请求体。"""

    message: str = Field(..., min_length=1, description="用户的自然语言请求。")
    thread_id: str | None = Field(
        default=None,
        description="多轮会话线程标识；省略时由服务端生成新的线程（Requirement 3）。",
    )


class AgentQueryResponse(BaseModel):
    """Supervisor 处理结果响应体。"""

    thread_id: str = Field(..., description="本轮所属的会话线程标识。")
    tenant_id: str = Field(..., description="经认证并注入 RLS 上下文的租户标识。")
    intent: str | None = Field(default=None, description="Supervisor 识别出的意图。")
    final_answer: str | None = Field(default=None, description="聚合后的最终回答。")
    needs_clarification: bool = Field(
        default=False, description="是否需请用户澄清 / 重述（Requirement 1.7）。"
    )
    partial: bool = Field(
        default=False, description="结果是否为部分完成（Requirement 1.8）。"
    )
    pending_action: dict[str, Any] | None = Field(
        default=None, description="待人工确认 / 已处置的副作用动作（Requirement 4）。"
    )


def create_app(
    *,
    composition: AppComposition | None = None,
    settings: Any | None = None,
    db_engine: Any | None = None,
) -> FastAPI:
    """构造并返回 FastAPI 应用。

    Args:
        composition: 预装配的组合根；省略时经 :func:`~app.api.composition.build_composition`
            构造。
        settings: 传递给默认组合根的配置；仅在未提供 ``composition`` 时生效。
        db_engine: 可选注入的 SQLAlchemy Engine；未显式提供且门店已配置默认租户
            （``PETOPS_DEFAULT_TENANT_ID`` 或企业微信 ``corp_id``）时，自动经
            :func:`~app.db.init.create_db_engine` 构造真实（惰性连接）Engine 并接线
            PostgreSQL 后端排期 + 接待预约 Agent；未配置时回退内存模式（便于测试）。

    Returns:
        FastAPI: 已装配路由与组合根的应用实例。
    """
    if composition is None:
        resolved_settings = settings or get_settings()
        resolved_engine = db_engine
        if resolved_engine is None and resolved_settings.resolved_default_tenant_id:
            # 生产：门店已配置默认租户 → 构造真实 Engine（惰性连接，构造期不建立连接）。
            from app.db.init import create_db_engine

            resolved_engine = create_db_engine(resolved_settings)
        comp = build_composition(settings=resolved_settings, db_engine=resolved_engine)
    else:
        comp = composition

    app = FastAPI(
        title="PetOps 智能宠物店运营大脑平台 BFF",
        version="0.1.0",
        summary="API Gateway / BFF：认证、RLS 上下文注入与 AI 决策中枢转发。",
    )
    app.state.composition = comp

    # ------------------------------------------------------------------ #
    # 请求耗时 / 状态码埋点（Prometheus，链路监控）
    # ------------------------------------------------------------------ #
    @app.middleware("http")
    async def _metrics_middleware(request: Request, call_next: Any) -> Response:
        """记录每个 HTTP 请求的耗时与状态码，暴露于 ``/metrics``。

        不记录请求 / 响应体（避免 PII 泄露），仅记录方法、路径与状态码维度的计数与
        耗时分布。``/metrics`` 自身不纳入统计，避免抓取请求自我污染指标。
        """
        if request.url.path == "/metrics":
            return await call_next(request)
        started = time.monotonic()
        response = await call_next(request)
        elapsed = time.monotonic() - started
        labels = {
            "method": request.method,
            "path": request.url.path,
            "status": str(response.status_code),
        }
        HTTP_REQUEST_DURATION.labels(**labels).observe(elapsed)
        HTTP_REQUESTS_TOTAL.labels(**labels).inc()
        return response

    # ------------------------------------------------------------------ #
    # 健康 / 就绪探针（无需租户上下文）
    # ------------------------------------------------------------------ #
    @app.get("/health", tags=["ops"])
    def health() -> dict[str, str]:
        """存活探针：进程可响应即返回 ok。"""
        return {"status": "ok"}

    @app.get("/metrics", tags=["ops"])
    def metrics() -> Response:
        """Prometheus 指标暴露端点（文本格式）。

        安全：不含任何租户业务数据 / PII，仅聚合计数与耗时分布；建议在 nginx 层限制
        本端点仅供内网 / 监控抓取源访问，不对公网开放（见 ``docker/nginx.conf``）。
        """
        return Response(content=render_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.get("/ready", tags=["ops"])
    def ready(request: Request) -> dict[str, Any]:
        """就绪探针：内省组合根各关键组件是否已装配。"""
        current: AppComposition = request.app.state.composition
        status = current.component_status()
        return {"status": "ready" if all(status.values()) else "degraded", "components": status}

    # ------------------------------------------------------------------ #
    # AI 决策中枢转发（认证 + RLS 上下文注入 + thread_id 多轮）
    # ------------------------------------------------------------------ #
    @app.post("/agent/query", response_model=AgentQueryResponse, tags=["agent"])
    def agent_query(
        payload: AgentQueryRequest,
        request: Request,
        tenant_id: str = Depends(require_tenant),
    ) -> AgentQueryResponse:
        """将自然语言请求转发至 Supervisor，并支持 ``thread_id`` 多轮会话。

        依赖 :func:`~app.api.auth.require_tenant` 完成认证与 RLS 上下文注入：缺失租户上下文
        的请求在进入本处理函数前即被拒绝（HTTP 401）。
        """
        current: AppComposition = request.app.state.composition
        thread_id = payload.thread_id or f"thread-{uuid.uuid4().hex}"

        config = {"configurable": {"thread_id": thread_id}}
        result = current.supervisor_graph.invoke(
            {"tenant_id": tenant_id, "messages": [("user", payload.message)]},
            config=config,
        )

        return AgentQueryResponse(
            thread_id=thread_id,
            tenant_id=tenant_id,
            intent=result.get("intent"),
            final_answer=result.get("final_answer"),
            needs_clarification=bool(result.get("needs_clarification", False)),
            partial=bool(result.get("partial", False)),
            pending_action=result.get("pending_action"),
        )

    # ------------------------------------------------------------------ #
    # 企业微信回调端点（GET 验证握手 / POST 入站消息，Requirement 21）
    # ------------------------------------------------------------------ #
    register_wecom_routes(app)

    return app
