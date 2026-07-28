"""LangFuse Cloud 追溯上报客户端（决策链全链路追溯，Requirement 18.2 / 18.3）。

实现 :class:`~app.observability.tracing.ExternalTracingClient` 协议，将
:class:`~app.observability.tracing.DecisionTrace` 序列化后经 LangFuse **公开 Ingestion
API**（``POST /api/public/ingestion``）批量上报为一条 trace + 若干 span 观测。

设计取舍（重要）：LangFuse 官方 Python SDK v3/v4 已重构为 OpenTelemetry 原生架构（需要
配置 OTEL SpanProcessor、上下文传播等），对本单体应用而言引入成本远超收益。本客户端
改用**标准库 urllib 直接调用 Ingestion API**（Basic Auth：用户名=public_key，
密码=secret_key），零额外依赖、易测试（可注入伪 HTTP 传输）。该 API 目前仍受支持
（官方标注为"推荐迁移到 OTEL 端点"但未废弃移除），足以满足"决策链留痕可查"的需求。

失败处理：上报失败（网络错误 / 非 2xx）**不应影响主业务流程**——追溯上报是可观测性
的旁路能力，因此本客户端在 :meth:`LangFuseHttpClient.submit_trace` 内捕获所有异常并
仅记录日志；:class:`~app.observability.tracing._ExternalBackend` 的重抛语义在组合根侧
按需处理（当前组合根选择静默降级，见 ``build_composition``）。
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from typing import Any

from app.core.config import LangFuseSettings

__all__ = ["LangFuseHttpClient", "build_langfuse_client"]

logger = logging.getLogger(__name__)

_INGESTION_PATH = "/api/public/ingestion"


class LangFuseHttpClient:
    """基于 urllib 的 LangFuse Ingestion API 客户端。

    Args:
        public_key: LangFuse 项目 Public Key（Basic Auth 用户名）。
        secret_key: LangFuse 项目 Secret Key（Basic Auth 密码）。
        host: LangFuse 实例地址（默认 LangFuse Cloud）。
        timeout: HTTP 请求超时（秒）。
    """

    def __init__(
        self, *, public_key: str, secret_key: str, host: str, timeout: float = 5.0
    ) -> None:
        if not public_key.strip() or not secret_key.strip():
            raise ValueError("public_key / secret_key 不可为空。")
        self._public_key = public_key.strip()
        self._secret_key = secret_key.strip()
        self._endpoint = host.rstrip("/") + _INGESTION_PATH
        self._timeout = timeout

    def submit_trace(self, payload: dict[str, Any]) -> None:
        """将序列化后的 :class:`DecisionTrace` 上报为 LangFuse trace + span 批次。

        失败时仅记录日志，不抛出异常（追溯上报失败不应影响业务主流程）。
        """
        try:
            batch = _to_ingestion_batch(payload)
            body = json.dumps({"batch": batch}).encode("utf-8")
            request = urllib.request.Request(
                self._endpoint,
                data=body,
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": _basic_auth_header(self._public_key, self._secret_key),
                },
            )
            with urllib.request.urlopen(request, timeout=self._timeout):
                pass
        except Exception as exc:  # noqa: BLE001 - 追溯旁路失败不应影响主业务流程
            logger.warning(
                "LangFuse 追溯上报失败（trace_id=%s）：%s: %s",
                payload.get("trace_id"),
                type(exc).__name__,
                exc,
            )


def build_langfuse_client(settings: LangFuseSettings) -> LangFuseHttpClient | None:
    """按配置构造 LangFuse 客户端；未配置 public_key/secret_key 时返回 ``None``。"""
    if not settings.is_configured:
        return None
    return LangFuseHttpClient(
        public_key=settings.public_key,
        secret_key=settings.secret_key.get_secret_value(),
        host=settings.host,
        timeout=settings.timeout_seconds,
    )


def _basic_auth_header(username: str, password: str) -> str:
    import base64

    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def _to_ingestion_batch(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """将 :meth:`DecisionTrace.to_dict` 的输出映射为 LangFuse Ingestion 事件批次。

    一条决策链 → 一个 ``trace-create`` 事件（携带 tenant/request_input）+ 每个节点跨度
    一个 ``span-create`` 事件（携带节点名、所属 Agent、输入 / 输出、起止时间、错误信息）。
    """
    trace_id = str(payload.get("trace_id") or uuid.uuid4().hex)
    now_iso = datetime.now(timezone.utc).isoformat()

    events: list[dict[str, Any]] = [
        {
            "id": uuid.uuid4().hex,
            "type": "trace-create",
            "timestamp": now_iso,
            "body": {
                "id": trace_id,
                "name": "petops-decision-chain",
                "input": payload.get("request_input"),
                "output": payload.get("output"),
                "sessionId": payload.get("session_id"),
                "metadata": {"tenant_id": payload.get("tenant_id")},
                "tags": [str(a) for a in payload.get("agents", [])],
            },
        }
    ]

    for span in payload.get("spans", []):
        events.append(
            {
                "id": uuid.uuid4().hex,
                "type": "span-create",
                "timestamp": now_iso,
                "body": {
                    "id": uuid.uuid4().hex,
                    "traceId": trace_id,
                    "name": span.get("node"),
                    "startTime": span.get("started_at"),
                    "endTime": span.get("ended_at"),
                    "input": span.get("input"),
                    "output": span.get("output"),
                    "metadata": {"agent": span.get("agent")},
                    "level": "ERROR" if span.get("error") else "DEFAULT",
                    "statusMessage": span.get("error"),
                },
            }
        )
    return events
