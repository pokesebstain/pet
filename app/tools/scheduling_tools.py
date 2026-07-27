"""企业微信预约相关工具（统一工具层扩展，任务 27.3）。

对应设计文档 **14.3 组件 D：预约相关工具（Tool Layer 扩展）** 与 **14.2 复用表**：在既有
统一工具层（:mod:`app.tools.base`）之上新增三件预约相关工具，全部经既有 ``tenant_id``
强制注入与结果集租户校验（应用侧 RLS 纵深防御，Requirement 24.2 / Correctness Property 1 /
17）：

- :func:`build_schedule_query_tool` → ``schedule_query_tool``（**只读**）：查询某日排期与
  容量（Requirement 23.1）。经排期引擎 :meth:`~app.engines.scheduling.SchedulingEngine.get_day_schedule`
  获取时段，返回前逐条校验每个 :class:`~app.models.scheduling.TimeSlot` 的 ``tenant_id``
  与请求上下文一致（越界即阻断整个结果集）。
- :func:`build_appointment_book_tool` → ``appointment_book_tool``（**副作用**）：原子写入
  预约（经 :meth:`~app.engines.scheduling.SchedulingEngine.book_appointment`，Requirement 22.1）。
  可**自动执行**（``auto_execute=True``，门控见设计 14.6）或**经 HITL**（``auto_execute=False``
  时不写入、返回待确认动作，复用既有 ``pending_action`` 中断 / 恢复机制，Requirement 22.5）。
  写入前将请求 ``tenant_id`` **强制归一**为上下文 ``tenant_id``（RLS 注入），写入后再次校验
  落库记录的 ``tenant_id``（Requirement 24.2）。
- :func:`build_wecom_reply_tool` → ``wecom_reply_tool``（**副作用**）：经企业微信通道向客户
  回复文本（Requirement 21.1）。扩展自既有企业微信推送通道（复用
  :class:`~app.wecom.gateway.ReplySender` 出站发送器）。

设计与可测性约束：所有外部协作者（排期引擎、时段行级锁 / 写入器 / 事件发布器、企业微信
出站发送器）均经**工厂函数注入**，因此工具可在无实时数据库 / 无企业微信网络的情况下用内存
假实现（如 :class:`~app.engines.scheduling.InMemoryTransactionalSlotStore` 与伪 ReplySender）
完整测试。每件工具均以 LangChain ``@tool`` 入口暴露，Agent 调用时必须携带 ``tenant_id``；
``tenant_id`` 缺失 / 为空时在触碰任何数据源 / 发送通道前即拒绝
（:class:`~app.core.errors.TenantContextMissingError`，Requirement 21.6 / 24.2）。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Protocol, runtime_checkable

from app.engines.scheduling import (
    AppointmentWriter,
    BookingEventPublisher,
    SchedulingEngine,
    SlotFullError,
    SlotLockManager,
)
from app.models.scheduling import BookingRequest, ServiceType
from app.tools.base import (
    MAX_RESULT_ROWS,
    enforce_tenant_isolation,
    require_tenant_context,
    truncate_rows,
)

__all__ = [
    "ReplyChannel",
    "build_schedule_query_tool",
    "build_appointment_book_tool",
    "build_wecom_reply_tool",
    "SCHEDULE_QUERY_TOOL_NAME",
    "APPOINTMENT_BOOK_TOOL_NAME",
    "WECOM_REPLY_TOOL_NAME",
]

#: 三件工具的稳定名称（供 Supervisor / Agent 路由与 LLM 函数调用识别）。
SCHEDULE_QUERY_TOOL_NAME = "schedule_query_tool"
APPOINTMENT_BOOK_TOOL_NAME = "appointment_book_tool"
WECOM_REPLY_TOOL_NAME = "wecom_reply_tool"


@runtime_checkable
class ReplyChannel(Protocol):
    """企业微信出站回复通道协议（与 :class:`~app.wecom.gateway.ReplySender` 结构化一致）。

    ``send(tenant_id, external_user_id, text)`` 向指定门店（租户）下的外部联系人推送文本。
    """

    def send(
        self, tenant_id: str, external_user_id: str, text: str
    ) -> None:  # pragma: no cover - 协议声明
        ...


# --------------------------------------------------------------------------- #
# schedule_query_tool（只读，Requirement 23.1 / 24.2）
# --------------------------------------------------------------------------- #
def build_schedule_query_tool(
    scheduling_engine: SchedulingEngine,
    *,
    max_rows: int = MAX_RESULT_ROWS,
) -> Any:
    """构建只读的 ``schedule_query_tool``（查询某日排期与容量）。

    返回的 LangChain ``@tool`` 入口签名为 ``(tenant_id: str, service_type: str, day: str)``：
    先经 :func:`require_tenant_context` 校验并归一化 ``tenant_id``（缺失即拒绝，不触碰引擎），
    再经注入的排期引擎查询当日各时段容量 / 已订数，返回前逐条校验每个时段的 ``tenant_id``
    与上下文一致（越界阻断整个结果集），并按 ``max_rows`` 截断打标。

    Args:
        scheduling_engine: 排期引擎（可用性 / 某日排期查询来源）。
        max_rows: 返回时段行数上限。

    Returns:
        LangChain ``StructuredTool``（只读，无副作用）。
    """
    from langchain_core.tools import tool as langchain_tool

    @langchain_tool(
        SCHEDULE_QUERY_TOOL_NAME,
        description="查询某日排期与容量（只读，经 RLS 强制注入 tenant_id）。",
    )
    def _entry(tenant_id: str, service_type: str, day: str) -> dict[str, Any]:
        normalized = require_tenant_context(tenant_id)
        svc = _coerce_service_type(service_type)
        target_day = _coerce_date(day)
        slots = scheduling_engine.get_day_schedule(normalized, svc, target_day)
        # 应用侧 RLS 纵深防御：逐条校验时段租户归属（Requirement 24.2）。
        enforce_tenant_isolation(slots, normalized)
        kept, truncated = truncate_rows(list(slots), max_rows)
        return {
            "tenant_id": normalized,
            "service_type": svc.value,
            "day": target_day.isoformat(),
            "row_count": len(kept),
            "truncated": truncated,
            "rows": [slot.model_dump(mode="json") for slot in kept],
        }

    return _entry


# --------------------------------------------------------------------------- #
# appointment_book_tool（副作用：自动执行或转 HITL，Requirement 22.1 / 22.5 / 24.2）
# --------------------------------------------------------------------------- #
def build_appointment_book_tool(
    scheduling_engine: SchedulingEngine,
    *,
    slot_locks: SlotLockManager,
    appointment_writer: AppointmentWriter,
    event_bus: BookingEventPublisher,
) -> Any:
    """构建副作用工具 ``appointment_book_tool``（原子写入预约或转 HITL）。

    返回的 LangChain ``@tool`` 入口签名为 ``(tenant_id: str, req: dict, auto_execute: bool)``：

    1. 经 :func:`require_tenant_context` 校验并归一化 ``tenant_id``（缺失即拒绝，不写入）。
    2. **RLS 注入**：将 ``req["tenant_id"]`` **强制**归一为上下文 ``tenant_id``，杜绝跨租户
       写入（Requirement 24.2）。
    3. ``auto_execute=False``（门控未通过 / 边界动作）：**不写入**，返回待人工确认的
       ``pending_action``（复用既有 HITL ``pending_action`` 机制，Requirement 22.5）。
    4. ``auto_execute=True``（门控通过）：经 :meth:`SchedulingEngine.book_appointment` 在时段
       行级锁下原子写入一条 CONFIRMED 预约（Requirement 22.1）；满档
       （:class:`~app.engines.scheduling.SlotFullError`）时不写入并返回 ``full`` 状态。
       写入成功后再次校验落库记录 ``tenant_id`` 与上下文一致（Requirement 24.2）。

    Args:
        scheduling_engine: 排期引擎（提供 ``book_appointment``）。
        slot_locks: 时段行级锁管理器（复刻 ``SELECT … FOR UPDATE``）。
        appointment_writer: 预约写入器（等价事务内 INSERT）。
        event_bus: 领域事件发布器（预约成功 / 满档事件）。

    Returns:
        LangChain ``StructuredTool``（副作用工具）。
    """
    from langchain_core.tools import tool as langchain_tool

    @langchain_tool(
        APPOINTMENT_BOOK_TOOL_NAME,
        description=(
            "原子写入预约（经 Scheduling_Engine.book_appointment）。副作用工具：门控通过时"
            "自动执行（auto_execute=True），否则转 HITL 人工确认（auto_execute=False）。"
        ),
    )
    def _entry(
        tenant_id: str, req: dict[str, Any], auto_execute: bool = True
    ) -> dict[str, Any]:
        normalized = require_tenant_context(tenant_id)
        # RLS 注入：强制请求租户 = 上下文租户，防止跨租户写入（Requirement 24.2）。
        payload = dict(req)
        payload["tenant_id"] = normalized
        request = BookingRequest(**payload)

        if not auto_execute:
            # 门控未通过 / 边界动作：不写入，转 HITL 待确认（Requirement 22.5）。
            return {
                "tenant_id": normalized,
                "executed": False,
                "status": "pending_hitl",
                "pending_action": _booking_pending_action(request),
            }

        try:
            appointment = scheduling_engine.book_appointment(
                request,
                context_tenant_id=normalized,
                slot_locks=slot_locks,
                appointment_writer=appointment_writer,
                event_bus=event_bus,
            )
        except SlotFullError:
            # 满档（含并发争抢失败）：无写入，交由上层回复现状 + 备选（Requirement 22.2 / 23.4）。
            return {
                "tenant_id": normalized,
                "executed": False,
                "status": "full",
                "appointment": None,
            }

        # 落库记录租户校验（Requirement 24.2 / Property 17）。
        enforce_tenant_isolation([appointment], normalized)
        return {
            "tenant_id": normalized,
            "executed": True,
            "status": "booked",
            "appointment": appointment.model_dump(mode="json"),
        }

    return _entry


# --------------------------------------------------------------------------- #
# wecom_reply_tool（副作用：企业微信出站回复，Requirement 21.1）
# --------------------------------------------------------------------------- #
def build_wecom_reply_tool(reply_channel: ReplyChannel) -> Any:
    """构建副作用工具 ``wecom_reply_tool``（经企业微信通道向客户回复文本）。

    返回的 LangChain ``@tool`` 入口签名为 ``(tenant_id: str, external_user_id: str, text: str)``：
    先经 :func:`require_tenant_context` 校验并归一化 ``tenant_id``（缺失即拒绝，不发送），再经
    注入的出站发送器推送文本。扩展自既有企业微信推送通道（复用
    :class:`~app.wecom.gateway.ReplySender`）。

    Args:
        reply_channel: 企业微信出站回复通道（:class:`ReplyChannel`）。

    Returns:
        LangChain ``StructuredTool``（副作用工具）。
    """
    from langchain_core.tools import tool as langchain_tool

    @langchain_tool(
        WECOM_REPLY_TOOL_NAME,
        description="经企业微信通道向客户回复文本消息（副作用，扩展既有企业微信推送通道）。",
    )
    def _entry(tenant_id: str, external_user_id: str, text: str) -> dict[str, Any]:
        normalized = require_tenant_context(tenant_id)
        reply_channel.send(normalized, external_user_id, text)
        return {
            "tenant_id": normalized,
            "external_user_id": external_user_id,
            "sent": True,
        }

    return _entry


# --------------------------------------------------------------------------- #
# 辅助
# --------------------------------------------------------------------------- #
def _booking_pending_action(request: BookingRequest) -> dict[str, Any]:
    """构造转 HITL 的待确认预约动作（复用既有 ``pending_action`` 结构）。"""
    return {
        "action_type": "appointment_book",
        "target": {
            "tenant_id": request.tenant_id,
            "customer_id": request.customer_id,
            "pet_id": request.pet_id,
            "service_type": request.service_type.value,
            "start_at": request.start_at.isoformat(),
            "end_at": request.end_at.isoformat(),
        },
        "impact_scope": "single_appointment",
        "status": "pending_approval",
        "executed": False,
    }


def _coerce_service_type(value: Any) -> ServiceType:
    """将服务类型入参安全转为 :class:`ServiceType`（已是枚举则透传）。"""
    if isinstance(value, ServiceType):
        return value
    return ServiceType(str(value).strip().lower())


def _coerce_date(value: Any) -> date:
    """将日期入参安全转为 :class:`date`（支持 ``date`` / ``datetime`` / ISO8601 字符串）。"""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value).strip())
