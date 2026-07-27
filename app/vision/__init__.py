"""视觉健康检测抽象层，本次由第三方 API（宠智灵 / 百目魔君）实现。"""

# --- 任务 20.1：Vision_Provider 抽象与第三方实现（append-only） --------------
from app.vision.errors import (
    ImageInvalidError,
    VisionError,
    VisionTimeoutError,
    VisionUnavailableError,
)
from app.vision.provider import (
    BYTES_PER_MB,
    INITIAL_BACKOFF_SECONDS,
    JPEG_MAGIC,
    MAX_BACKOFF_SECONDS,
    PNG_MAGIC,
    Clock,
    DetectionItem,
    ImageFormat,
    PetImage,
    SystemClock,
    ThirdPartyVision,
    VisionProvider,
    VisionResult,
    VisionTransport,
    get_vision_provider,
    normalize_detections,
    validate_image,
)

__all__ = [
    # 错误
    "VisionError",
    "ImageInvalidError",
    "VisionUnavailableError",
    "VisionTimeoutError",
    # 抽象与实现
    "VisionProvider",
    "ThirdPartyVision",
    "get_vision_provider",
    "VisionTransport",
    # 模型
    "PetImage",
    "ImageFormat",
    "DetectionItem",
    "VisionResult",
    # 校验与归一化
    "validate_image",
    "normalize_detections",
    # 时钟
    "Clock",
    "SystemClock",
    # 常量
    "INITIAL_BACKOFF_SECONDS",
    "MAX_BACKOFF_SECONDS",
    "BYTES_PER_MB",
    "JPEG_MAGIC",
    "PNG_MAGIC",
]
