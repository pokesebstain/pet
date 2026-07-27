"""统一工具层（Tool Layer）：受控、可审计、租户隔离的数据与模型访问能力。

任务 7.1 提供工具层基础框架与 ``tenant_id`` 强制注入：所有数据访问工具经此处封装的
调用入口访问数据，在 PostgreSQL 行级安全（RLS）之上叠加应用侧的租户校验与结果截断，
杜绝跨租户数据泄露（Correctness Property 1，Requirements 5.1、5.2、5.4、5.5、2.7）。

任务 7.3 提供敏感数据脱敏工具（手机号 / 身份证号 / 银行卡号的展示与存储掩码，
Requirements 20.3、20.6）。
"""

from app.tools.base import (
    MAX_RESULT_ROWS,
    TENANT_ID_FIELD,
    ToolResult,
    build_tenant_scoped_langchain_tool,
    build_tool_result,
    enforce_tenant_isolation,
    extract_tenant_id,
    require_tenant_context,
    run_tenant_scoped_query,
    tenant_scoped_tool,
    truncate_rows,
)
from app.tools.masking import (
    MASK_CHAR,
    MaskMode,
    SensitiveKind,
    mask_bank_card,
    mask_fields,
    mask_national_id,
    mask_phone,
    mask_sensitive,
)
from app.tools.scheduling_tools import (
    APPOINTMENT_BOOK_TOOL_NAME,
    SCHEDULE_QUERY_TOOL_NAME,
    WECOM_REPLY_TOOL_NAME,
    build_appointment_book_tool,
    build_schedule_query_tool,
    build_wecom_reply_tool,
)

__all__ = [
    # 7.1 工具层基础框架与租户隔离
    "MAX_RESULT_ROWS",
    "TENANT_ID_FIELD",
    "ToolResult",
    "require_tenant_context",
    "extract_tenant_id",
    "enforce_tenant_isolation",
    "truncate_rows",
    "build_tool_result",
    "tenant_scoped_tool",
    "run_tenant_scoped_query",
    "build_tenant_scoped_langchain_tool",
    # 7.3 敏感数据脱敏
    "MASK_CHAR",
    "MaskMode",
    "SensitiveKind",
    "mask_phone",
    "mask_national_id",
    "mask_bank_card",
    "mask_sensitive",
    "mask_fields",
    # 27.3 预约相关工具（Tool Layer 扩展）
    "SCHEDULE_QUERY_TOOL_NAME",
    "APPOINTMENT_BOOK_TOOL_NAME",
    "WECOM_REPLY_TOOL_NAME",
    "build_schedule_query_tool",
    "build_appointment_book_tool",
    "build_wecom_reply_tool",
]
