"""视觉健康检测层共享异常类型。

集中定义 Vision_Provider 抽象层（本次由第三方 API：宠智灵 / 百目魔君 实现）
复用的错误类型，使"图像无效""第三方 API 超时 / 不可用"等情形对上层暴露一致、
可被区分处理的异常。

范围约束：视觉能力仅经第三方 API 在抽象层之后实现，不含任何自研 / 微调视觉模型。
"""

from __future__ import annotations

from app.core.errors import PetOpsError


class VisionError(PetOpsError):
    """视觉检测错误基类。"""


class ImageInvalidError(VisionError, ValueError):
    """图像无效错误（对应 Requirement 17.3）。

    当提交的图像缺失、格式非 JPEG/PNG 或大小超过限制（默认 10 MB）时抛出。
    上层据此拒绝请求并返回图像无效错误，且**绝不调用任何第三方 API**。

    同时继承 :class:`ValueError`，以兼容常见的 ``except ValueError`` 处理路径。
    """


class VisionUnavailableError(VisionError):
    """第三方视觉 API 不可用错误（对应 Requirement 17.4）。

    表示**可重试的外部瞬时故障**（网络错误、5xx、服务不可用等）。
    传输层实现遇到此类故障时应抛出本异常（或其子类），使
    :class:`~app.vision.provider.ThirdPartyVision` 得以切换备用 provider
    或按退避重试排队重发。
    """


class VisionTimeoutError(VisionUnavailableError):
    """第三方视觉 API 响应超时错误（对应 Requirement 17.4：响应超过 30 秒）。

    继承 :class:`VisionUnavailableError`，同样被视为可切换 / 可重试的瞬时故障。
    """
