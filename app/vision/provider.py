"""Vision_Provider 抽象层与第三方实现（宠智灵 / 百目魔君）。

对应设计文档"微调与模型策略 / 视觉能力抽象层"与 Requirement 17（视觉健康检测）。
本模块实现：

1. **VisionProvider 协议**（Requirement 17.2）：业务代码仅依赖抽象接口
   :class:`VisionProvider`，不感知底层第三方来源；后续可平滑切换到其它实现。
2. **图像校验**（Requirement 17.1 / 17.3）：在发起任何第三方调用**之前**校验图像
   （非缺失、JPEG/PNG、≤ ``max_image_mb`` MB）；不合法则拒绝且**不调用 API**。
3. **第三方实现 ThirdPartyVision**（Requirement 17.1 / 17.4 / 17.5）：校验通过后经
   注入的传输层调用第三方 API，返回含至少一个检测项与置信度 [0,1] 的结果；
   API 不可用 / 超时时**切换备用 provider 或最多 3 次重试排队重发**；重试耗尽仍失败
   则将结果标记为**待人工复核**并**保留原始图像**。
4. **工厂 get_vision_provider**（Requirement 17.2）：按配置返回实现。

范围约束（重要）：视觉能力**仅**经第三方 API 实现，自研 / 微调 YOLO/ViT 不在本次范围。
真实的 HTTP / SDK 调用被抽象在 :class:`VisionTransport` 协议之后，测试可注入伪实现，
在无真实网络的情况下模拟成功 / 超时 / 不可用；时间通过 :class:`Clock` 协议注入，使
退避重试相关测试可快速运行而无需真实等待。
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable

from app.core.config import VisionSettings, get_settings
from app.vision.errors import ImageInvalidError, VisionUnavailableError

__all__ = [
    "Clock",
    "SystemClock",
    "ImageFormat",
    "PetImage",
    "DetectionItem",
    "VisionResult",
    "VisionTransport",
    "VisionProvider",
    "ThirdPartyVision",
    "get_vision_provider",
    "validate_image",
    "normalize_detections",
    "INITIAL_BACKOFF_SECONDS",
    "MAX_BACKOFF_SECONDS",
    "BYTES_PER_MB",
    "JPEG_MAGIC",
    "PNG_MAGIC",
]

# --- 退避常量（Requirement 17.4）--------------------------------------------

#: 重试排队的初始退避等待（秒）。
INITIAL_BACKOFF_SECONDS: float = 1.0
#: 重试排队的退避上限（秒）。
MAX_BACKOFF_SECONDS: float = 8.0
#: 1 MB 对应的字节数，用于图像大小校验。
BYTES_PER_MB: int = 1024 * 1024

#: JPEG 文件的起始魔术字节（SOI 标记 FF D8 FF）。
JPEG_MAGIC: bytes = b"\xff\xd8\xff"
#: PNG 文件的 8 字节签名。
PNG_MAGIC: bytes = b"\x89PNG\r\n\x1a\n"


# --- 时钟抽象（便于快速测试退避重试）----------------------------------------


@runtime_checkable
class Clock(Protocol):
    """时间抽象：提供休眠能力，便于注入伪时钟加速测试。"""

    def sleep(self, seconds: float) -> None:  # pragma: no cover - 协议声明
        """休眠指定秒数（重试排队的退避等待）。"""
        ...


class SystemClock:
    """基于系统时间的默认 :class:`Clock` 实现。"""

    def sleep(self, seconds: float) -> None:
        if seconds > 0:
            time.sleep(seconds)


# --- 图像模型与校验（Requirement 17.1 / 17.3）-------------------------------


class ImageFormat(str, Enum):
    """受支持的图像格式。"""

    JPEG = "jpeg"
    PNG = "png"


@dataclass(frozen=True)
class PetImage:
    """待检测的宠物图像。

    以原始字节承载，使格式（魔术字节）与大小校验可在**不发起网络请求**的前提下
    在本地完成；``filename`` 仅用于日志 / 展示，不参与校验判定。

    Attributes:
        data: 图像原始字节。空字节视为"图像缺失"。
        filename: 可选的原始文件名（仅供参考）。
    """

    data: bytes
    filename: str | None = None

    @property
    def size_bytes(self) -> int:
        return len(self.data)


def _sniff_format(data: bytes) -> ImageFormat | None:
    """通过魔术字节嗅探图像格式；无法识别返回 ``None``。"""
    if data.startswith(JPEG_MAGIC):
        return ImageFormat.JPEG
    if data.startswith(PNG_MAGIC):
        return ImageFormat.PNG
    return None


def validate_image(
    image: PetImage | None,
    *,
    max_image_mb: int,
) -> ImageFormat:
    """校验图像并返回其格式；不合法时抛出 :class:`ImageInvalidError`。

    校验项（Requirement 17.3）：

    - **非缺失**：``image`` 不为 ``None`` 且字节非空。
    - **格式**：起始魔术字节为 JPEG 或 PNG。
    - **大小**：不超过 ``max_image_mb`` MB。

    本函数为纯本地校验，**不发起任何第三方调用**。

    Args:
        image: 待校验图像；``None`` 表示图像缺失。
        max_image_mb: 允许的最大图像大小（MB）。

    Returns:
        ImageFormat: 校验通过时的图像格式。

    Raises:
        ImageInvalidError: 图像缺失、格式非法或超过大小限制。
    """
    if image is None or not image.data:
        raise ImageInvalidError("图像缺失：未提供图像数据。")

    fmt = _sniff_format(image.data)
    if fmt is None:
        raise ImageInvalidError("图像格式无效：仅支持 JPEG 或 PNG。")

    max_bytes = max_image_mb * BYTES_PER_MB
    if image.size_bytes > max_bytes:
        raise ImageInvalidError(
            f"图像过大：{image.size_bytes} 字节超过上限 {max_image_mb} MB。"
        )
    return fmt


# --- 检测结果模型（Requirement 17.1）----------------------------------------


@dataclass(frozen=True)
class DetectionItem:
    """单个检测项及其置信度。

    Attributes:
        label: 检测项名称（如"皮肤异常""眼部分泌物"）。
        confidence: 置信度，取值范围 [0, 1]。
    """

    label: str
    confidence: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("检测项置信度必须落在 [0, 1] 区间内。")

    @classmethod
    def clamped(cls, label: str, confidence: float) -> DetectionItem:
        """构造检测项并将置信度收敛到 [0, 1]，以确保结果不变量成立。"""
        bounded = min(1.0, max(0.0, float(confidence)))
        return cls(label=label, confidence=bounded)


@dataclass(frozen=True)
class VisionResult:
    """视觉检测结果。

    Attributes:
        items: 检测项集合；成功时至少包含一个检测项（Requirement 17.1）。
        provider: 实际产出结果的 provider 名称。
        pending_manual_review: 是否标记为待人工复核（Requirement 17.5）。
        attempts: 实际发起的第三方调用次数（含首次与重试）。
        retained_image: 待人工复核时保留的原始图像（Requirement 17.5）；否则为 ``None``。
    """

    items: tuple[DetectionItem, ...] = ()
    provider: str = ""
    pending_manual_review: bool = False
    attempts: int = 0
    retained_image: PetImage | None = None


def normalize_detections(
    raw_items: Sequence[DetectionItem | tuple[str, float]],
) -> tuple[DetectionItem, ...]:
    """将第三方返回的检测项归一化为置信度落在 [0, 1] 的 :class:`DetectionItem`。

    第三方来源可能返回越界置信度；此处统一收敛到 [0, 1]，以保证结果不变量
    （Requirement 17.1：置信度 ∈ [0, 1]）。
    """
    normalized: list[DetectionItem] = []
    for item in raw_items:
        if isinstance(item, DetectionItem):
            normalized.append(DetectionItem.clamped(item.label, item.confidence))
        else:
            label, confidence = item
            normalized.append(DetectionItem.clamped(label, confidence))
    return tuple(normalized)


# --- 传输层抽象（隔离真实 HTTP / SDK 调用）-----------------------------------


@runtime_checkable
class VisionTransport(Protocol):
    """第三方视觉 API 传输层协议。

    实现者负责真实的 HTTP / SDK 调用，并**必须**在 API 不可用 / 超时时抛出
    :mod:`app.vision.errors` 中定义的异常（``VisionUnavailableError`` /
    ``VisionTimeoutError``）。传输层需自行按 ``timeout`` 约束调用时长。

    范围约束：真实传输实现（宠智灵 / 百目魔君 SDK）不在本任务范围内；本任务仅定义
    抽象接口，使测试可注入伪实现。
    """

    #: provider 名称标识（如 "chongzhiling" / "baimu"）。
    name: str

    def detect(
        self,
        image: PetImage,
        *,
        timeout: float,
    ) -> Sequence[DetectionItem | tuple[str, float]]:  # pragma: no cover - 协议声明
        """调用第三方 API 并返回检测项；失败时抛出
        :class:`~app.vision.errors.VisionUnavailableError` 子类。"""
        ...


# --- VisionProvider 协议（Requirement 17.2）---------------------------------


@runtime_checkable
class VisionProvider(Protocol):
    """视觉能力抽象接口。

    业务代码仅依赖本协议的 :meth:`detect_health`，不感知底层第三方来源
    （Requirement 17.2）。
    """

    def detect_health(self, image: PetImage | None) -> VisionResult:  # pragma: no cover
        """对图像执行健康检测并返回 :class:`VisionResult`。"""
        ...


# --- 第三方实现 -------------------------------------------------------------


class ThirdPartyVision:
    """基于第三方 API（宠智灵 / 百目魔君）的 :class:`VisionProvider` 实现。

    行为契约：

    - **先校验后调用**（Requirement 17.3）：任何第三方调用之前先做图像校验，
      不合法直接抛出 :class:`~app.vision.errors.ImageInvalidError`，绝不触达 API。
    - **成功返回**（Requirement 17.1）：返回含至少一个检测项、置信度 ∈ [0,1] 的结果。
    - **不可用 / 超时的容错**（Requirement 17.4）：在主 provider 与备用 provider
      之间轮换，并以指数退避最多重试 ``max_retries`` 次排队重发。
    - **重试耗尽**（Requirement 17.5）：仍失败则返回 ``pending_manual_review=True``
      并在 ``retained_image`` 中保留原始图像。

    所有外部依赖（传输层、时钟）均可注入，便于在无真实网络的情况下测试。
    """

    def __init__(
        self,
        transport: VisionTransport,
        *,
        backups: Sequence[VisionTransport] | None = None,
        clock: Clock | None = None,
        settings: VisionSettings | None = None,
        timeout_seconds: float | None = None,
        max_retries: int | None = None,
        max_image_mb: int | None = None,
    ) -> None:
        resolved = settings or get_settings().vision
        # 主 provider 在前，备用 provider 依次在后，用于失败时轮换（Requirement 17.4）。
        self._transports: tuple[VisionTransport, ...] = (transport, *(backups or ()))
        self._clock = clock or SystemClock()
        self._timeout = (
            timeout_seconds if timeout_seconds is not None else resolved.timeout_seconds
        )
        self._max_retries = (
            max_retries if max_retries is not None else resolved.max_retries
        )
        self._max_image_mb = (
            max_image_mb if max_image_mb is not None else resolved.max_image_mb
        )

    def detect_health(self, image: PetImage | None) -> VisionResult:
        """执行健康检测；遵循先校验、容错重试、耗尽转人工复核的契约。

        Args:
            image: 待检测图像；``None`` 视为图像缺失。

        Returns:
            VisionResult: 成功结果，或 ``pending_manual_review=True`` 的待复核结果。

        Raises:
            ImageInvalidError: 图像缺失、格式非法或超过大小限制（不调用任何 API）。
        """
        # 步骤一：图像校验先行（Requirement 17.3）——不合法直接拒绝，绝不调用 API。
        validate_image(image, max_image_mb=self._max_image_mb)
        assert image is not None  # validate_image 已保证非缺失

        # 步骤二：调用第三方 API，失败时切换 provider 并按退避重试排队（Requirement 17.4）。
        # 首次调用 + 最多 max_retries 次重试。
        max_attempts = self._max_retries + 1
        transport_count = len(self._transports)
        attempts = 0
        backoff = INITIAL_BACKOFF_SECONDS
        for attempt_index in range(max_attempts):
            transport = self._transports[attempt_index % transport_count]
            attempts += 1
            try:
                raw = transport.detect(image, timeout=self._timeout)
            except VisionUnavailableError:
                # 仍有剩余重试次数：按指数退避等待后切换 / 重试。
                if attempt_index < max_attempts - 1:
                    self._clock.sleep(backoff)
                    backoff = min(backoff * 2.0, MAX_BACKOFF_SECONDS)
                # 否则重试耗尽，退出循环转人工复核。
            else:
                return VisionResult(
                    items=normalize_detections(raw),
                    provider=transport.name,
                    pending_manual_review=False,
                    attempts=attempts,
                    retained_image=None,
                )

        # 步骤三：重试耗尽仍失败——标记待人工复核并保留原始图像（Requirement 17.5）。
        return VisionResult(
            items=(),
            provider=self._transports[0].name,
            pending_manual_review=True,
            attempts=attempts,
            retained_image=image,
        )


# --- 工厂（Requirement 17.2）------------------------------------------------


def get_vision_provider(
    settings: VisionSettings | None = None,
    *,
    transport: VisionTransport | None = None,
    backups: Sequence[VisionTransport] | None = None,
    clock: Clock | None = None,
) -> VisionProvider:
    """按配置返回 :class:`VisionProvider` 实现，业务代码不感知底层来源。

    本次仅提供第三方 API 实现（:class:`ThirdPartyVision`）。真实的 HTTP / SDK 传输实现
    不在本任务范围内，因此传输层通过 ``transport`` / ``backups`` 注入（测试注入伪实现，
    生产环境注入真实 SDK 传输）。

    Args:
        settings: 视觉配置；缺省读取全局配置。
        transport: 主 provider 传输实现（必需，用于实际发起调用）。
        backups: 备用 provider 传输实现序列（可选，用于失败切换）。
        clock: 可注入的时钟（用于加速退避测试）。

    Returns:
        VisionProvider: 视觉检测抽象实现。

    Raises:
        ValueError: 未提供主传输实现时。
    """
    resolved = settings or get_settings().vision
    if transport is None:
        raise ValueError(
            "get_vision_provider 需要注入主 provider 传输实现（transport）；"
            "真实第三方 SDK 传输不在本任务范围内。"
        )
    return ThirdPartyVision(
        transport,
        backups=backups,
        clock=clock,
        settings=resolved,
    )
