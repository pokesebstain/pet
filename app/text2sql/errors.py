"""Text2SQL 生成层共享异常类型。

集中定义基于 Cloud_LLM 的 Text2SQL **生成**阶段（任务 9.1）复用的错误类型。

范围约束（重要）：
- 本层仅负责**生成**候选只读 SQL，不承担 SQL 白名单 / 只读 / RLS 三重校验与执行
  （由任务 9.2 负责）。
- 生成经**云端 LLM**（通义千问 / 智谱 GLM）结合提示工程 / 少样本实现，不含任何模型微调。
"""

from __future__ import annotations

from app.core.errors import PetOpsError


class Text2SQLError(PetOpsError):
    """Text2SQL 生成错误基类。"""


class Text2SQLGenerationTimeoutError(Text2SQLError):
    """Text2SQL 生成超出时间预算错误。

    当生成候选 SQL 的整体耗时超过生成预算（默认 30 秒，对应 Requirement 2.1）时抛出。
    """


class Text2SQLUnavailableError(Text2SQLError):
    """Cloud_LLM 不可用导致无法生成候选 SQL 错误。

    当底层 :class:`~app.llm.client.CloudLLMClient` 因重试耗尽 / 熔断而降级
    （返回受限模板或请用户重述的提示）时，本层无法产出有效的候选 SQL，据此抛出。
    后续校验 / 执行层（任务 9.2）不应收到非 SQL 文本。
    """


# --- 任务 9.2：SQL 三重校验与执行控制错误 ------------------------------------


class SQLValidationError(Text2SQLError):
    """SQL 三重校验失败错误基类（任务 9.2）。

    当候选 SQL 未通过 SQL 白名单 / 只读约束 / RLS 三重校验中的任一项时抛出。校验层
    **不**执行任何 SQL、**不**对数据库产生变更（Requirements 2.2、2.3、20.2、
    Correctness Property 11）。

    Attributes:
        check: 失败所属的校验类别，取值为 ``"whitelist"`` / ``"read_only"`` / ``"rls"``。
    """

    #: 失败所属的校验类别（子类覆盖）。
    check: str = "unknown"

    def __init__(self, message: str, *, check: str | None = None) -> None:
        super().__init__(message)
        if check is not None:
            self.check = check


class SQLNotReadOnlyError(SQLValidationError):
    """只读约束校验失败错误。

    候选 SQL 含写操作（INSERT/UPDATE/DELETE/MERGE）、DDL（CREATE/DROP/ALTER/TRUNCATE）、
    会话 / 权限命令（SET/GRANT 等），或为多语句 / 无法解析时抛出（Requirement 2.3）。
    """

    check = "read_only"


class SQLWhitelistError(SQLValidationError):
    """白名单校验失败错误。

    候选 SQL 引用了不在固定 Schema（:mod:`app.db.metadata`）白名单内的表或列时抛出
    （Requirement 2.3）。
    """

    check = "whitelist"


class SQLRLSValidationError(SQLValidationError):
    """RLS 校验失败错误。

    候选 SQL 无法在有效的租户 RLS 上下文内执行（租户上下文缺失 / 为空）时抛出
    （Requirements 2.2、5.4）。实际 RLS 过滤由数据库层强制，本校验确保执行前存在
    有效租户上下文。
    """

    check = "rls"


class SQLExecutionTimeoutError(Text2SQLError):
    """SQL 执行超时错误。

    候选 SQL 执行耗时超过预算（默认 30 秒，Requirement 2.6）被终止时抛出。终止后
    **不**对数据库产生任何变更，返回查询超时错误。
    """
