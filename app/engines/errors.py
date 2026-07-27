"""业务引擎算法层共享异常类型。

集中定义算法层（生命阶段、流失、LTV、需求预测、安全库存、推荐等）复用的错误类型，
使各引擎对"参数无效""数据缺失"等场景抛出一致、可被上层捕获归类的异常。
"""

from __future__ import annotations


class EngineError(Exception):
    """业务引擎错误基类。"""


class InvalidParameterError(EngineError):
    """参数无效错误。

    用于入参越界、类型不符或取值非法（如 `horizon_days` ≤ 0、> 365 或非整数）。
    """


class DataNotFoundError(EngineError):
    """数据缺失错误。

    用于所需历史 / 实体数据不存在（如 SKU 无任何历史销量数据、客户不存在）。
    """


class AuthorizationError(EngineError):
    """越权错误。

    用于跨租户访问：请求所涉实体（客户 / 宠物等）的 ``tenant_id`` 与当前请求上下文的
    ``tenant_id`` 不一致时抛出，调用方据此拒绝该请求且不返回任何业务数据。
    """
