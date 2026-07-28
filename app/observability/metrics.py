"""Prometheus 指标埋点（应用运行时监控）。

对应用户明确要求补齐的链路监控缺口：此前仅有决策链追溯（LangSmith / LangFuse，见
:mod:`app.observability.tracing`）的数据模型，但**没有任何**请求耗时 / 错误率 /
LLM 调用成功率等运行时指标可供监控告警。本模块补齐该缺口。

设计要点
--------
- **零外部依赖风险**：``prometheus_client`` 是进程内指标注册表，不需要任何网络调用；
  即便未部署 Prometheus 抓取端，埋点本身也不会影响应用可用性。
- **单门店部署约束（2C2G）**：仅暴露 ``/metrics`` 文本端点供外部 Prometheus /
  Grafana Cloud Agent 拉取，**不在本机额外起 Prometheus / Grafana 容器**（内存余量不足）。
- **埋点范围**：
  - HTTP 请求耗时 / 状态码（``petops_http_request_duration_seconds`` /
    ``petops_http_requests_total``）。
  - 云端 LLM 调用结果（``petops_llm_requests_total``，按 ``outcome`` 维度：
    ``success`` / ``timeout`` / ``rate_limited`` / ``unavailable`` / ``degraded``）。
  - Supervisor 意图识别分布（``petops_intent_total``，按 ``intent`` 维度，
    ``unknown`` 表示无法归类，Requirement 1.7）。
  - 接待预约结果分布（``petops_booking_outcomes_total``，按 ``decision`` 维度：
    ``auto_book`` / ``full_suggest`` / ``needs_clarification`` / ``needs_hitl``）。
  - 企业微信回调结果（``petops_wecom_callback_total``，按 ``outcome`` 维度）。

安全：``/metrics`` 不含任何租户业务数据（无 PII），仅为聚合计数 / 耗时分布。
"""

from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

__all__ = [
    "CONTENT_TYPE_LATEST",
    "render_latest",
    "HTTP_REQUEST_DURATION",
    "HTTP_REQUESTS_TOTAL",
    "LLM_REQUESTS_TOTAL",
    "INTENT_TOTAL",
    "BOOKING_OUTCOMES_TOTAL",
    "WECOM_CALLBACK_TOTAL",
]

# --- HTTP 层 -----------------------------------------------------------------
HTTP_REQUEST_DURATION = Histogram(
    "petops_http_request_duration_seconds",
    "HTTP 请求处理耗时（秒）。",
    labelnames=("method", "path", "status"),
)

HTTP_REQUESTS_TOTAL = Counter(
    "petops_http_requests_total",
    "HTTP 请求总数。",
    labelnames=("method", "path", "status"),
)

# --- 云端 LLM 层（Requirement 20：退避 / 熔断 / 降级）------------------------
LLM_REQUESTS_TOTAL = Counter(
    "petops_llm_requests_total",
    "云端 LLM 调用结果计数（按结果类型）。",
    labelnames=("outcome",),  # success / timeout / rate_limited / unavailable / degraded
)

# --- Supervisor 意图识别（Requirement 1.1 / 1.7）----------------------------
INTENT_TOTAL = Counter(
    "petops_intent_total",
    "Supervisor 意图识别结果计数（按识别到的意图，unknown 表示无法归类）。",
    labelnames=("intent",),
)

# --- 接待预约门控结果（设计 14.6）-------------------------------------------
BOOKING_OUTCOMES_TOTAL = Counter(
    "petops_booking_outcomes_total",
    "接待预约门控判定结果计数。",
    labelnames=("decision",),  # auto_book / full_suggest / needs_clarification / needs_hitl
)

# --- 企业微信回调（Requirement 21）------------------------------------------
WECOM_CALLBACK_TOTAL = Counter(
    "petops_wecom_callback_total",
    "企业微信回调处理结果计数。",
    labelnames=("outcome",),  # forwarded / deduplicated / rejected / error
)


def render_latest() -> bytes:
    """渲染当前进程指标注册表为 Prometheus 文本暴露格式。"""
    return generate_latest()
