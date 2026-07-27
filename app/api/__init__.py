"""API Gateway / BFF 层（任务 24.1）。

对应设计文档 "Architecture / 1.1 总体分层架构" 的接入层
``API Gateway / BFF（FastAPI Router + Auth + RLS 上下文）``。本包把此前各任务实现的
业务引擎、事件总线、统一工具层与 AI 决策中枢在**组合根**（:mod:`app.api.composition`）
中装配为一个可运行的应用，并经 FastAPI 路由（:mod:`app.api.app`）对外提供：

- 请求 ``tenant_id`` 的提取、校验与 **RLS 上下文注入**（:mod:`app.api.auth`，Requirement 5.1）；
- 将自然语言请求转发至 Supervisor 的端点，支持 ``thread_id`` 多轮会话（Requirement 1.1 / 3）；
- 存活 / 就绪探针。

所有外部依赖均以内存 / 伪实现为默认值，因此应用可在无实时网络 / 数据库 / LLM 的情况下
构造并用 FastAPI ``TestClient`` 端到端测试；生产环境经组合根注入点替换为真实实现。
"""

from app.api.app import (
    AgentQueryRequest,
    AgentQueryResponse,
    create_app,
)
from app.api.auth import (
    TENANT_ID_HEADER,
    current_tenant_id,
    extract_request_tenant_id,
    require_tenant,
    rls_context,
)
from app.api.composition import AppComposition, build_composition

__all__ = [
    # 应用工厂与请求 / 响应模型
    "create_app",
    "AgentQueryRequest",
    "AgentQueryResponse",
    # 认证与 RLS 上下文注入
    "TENANT_ID_HEADER",
    "current_tenant_id",
    "extract_request_tenant_id",
    "require_tenant",
    "rls_context",
    # 组合根
    "AppComposition",
    "build_composition",
]
