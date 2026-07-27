"""健康数据中台（对应设计文档组件 4 `HealthDataHub` 与序列图 2.3）。

本模块实现 :class:`HealthDataHub` 的数据写入与事件发布职责（任务 15.1）：

> 需求 9.1：WHEN 智能设备或 APP 上报体重、活动或饮食数据且数据通过校验，
> THE Health_Data_Hub SHALL 在 5 秒内将数据写入时序表并向 Event_Bus 发布
> ``health_data_ingested`` 事件。
>
> 需求 9.2：IF 上报的健康数据缺少 ``tenant_id`` 或数值超出有效范围（如体重 ≤ 0），
> THEN THE Health_Data_Hub SHALL 拒绝写入、保持时序表不变、不发布事件，并返回
> 指明校验失败原因的错误提示。

设计要点：

- **校验即模型**：健康时序指标复用 :class:`~app.models.timeseries.HealthMetric` 的
  Pydantic 校验（``tenant_id`` 非空、``weight_kg > 0``、活动时长/进食量 ≥ 0）。校验
  失败时抛出 :class:`HealthDataValidationError`，其消息包含底层校验失败原因；此时
  **不** 触达仓库写入、**不** 发布事件（时序表保持不变）。
- **先写后发**：仅当校验通过并成功写入 TimescaleDB 超表后，才向事件总线发布
  ``health_data_ingested`` 事件，保证"未写入即无事件"。
- **依赖注入**：TimescaleDB 写入经 :class:`HealthMetricRepository` 协议抽象，事件发布
  经 :class:`~app.events.bus.EventBus` 注入；从而可用内存假实现
  （:class:`InMemoryHealthMetricRepository` + :class:`~app.events.transport.InMemoryStreamTransport`）
  在无实时数据库 / Redis 的情况下测试。
- **5 秒预算**：写入 + 发布均为同步快操作；:meth:`HealthDataHub.ingest` 记录耗时并在
  超出预算时以 :class:`HealthDataIngestTimeoutError` 提示（默认不启用硬失败，见参数）。

范围约束：本任务 **不** 实现异常趋势检测（``detect_anomaly`` / ``health_alert``），
那属于任务 15.2。
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, Callable, Protocol, runtime_checkable

from pydantic import ValidationError

from app.engines.errors import EngineError, InvalidParameterError
from app.events.bus import EventBus
from app.models import DomainEvent, HealthMetric

__all__ = [
    "HEALTH_DATA_INGESTED_EVENT",
    "INGEST_DEADLINE_SECONDS",
    "HealthDataValidationError",
    "HealthDataIngestTimeoutError",
    "HealthMetricRepository",
    "InMemoryHealthMetricRepository",
    "HealthDataHub",
]

#: 数据写入成功后发布的领域事件类型（设计文档 7.1 关键事件类型之一）。
HEALTH_DATA_INGESTED_EVENT = "health_data_ingested"

#: 需求 9.1 规定的写入 + 发布时间预算（秒）。
INGEST_DEADLINE_SECONDS = 5.0


class HealthDataValidationError(InvalidParameterError):
    """健康数据校验失败错误（需求 9.2）。

    当上报数据缺少 ``tenant_id`` 或数值超出有效范围（体重 ≤ 0、活动时长/进食量 < 0 等）
    时抛出。消息包含底层校验失败原因，供调用方返回给上报方。
    """


class HealthDataIngestTimeoutError(EngineError):
    """写入 + 发布超过时间预算（需求 9.1：5 秒）。

    仅在构造 :class:`HealthDataHub` 时显式开启 ``enforce_deadline`` 才会抛出；
    默认不启用，以免在慢速环境中把已成功的写入误判为失败。
    """


@runtime_checkable
class HealthMetricRepository(Protocol):
    """健康时序指标仓库协议（TimescaleDB 超表 ``health_metrics`` 的写入抽象）。

    抽象掉底层持久化（TimescaleDB / 测试内存实现），仅暴露写入单条指标的能力。
    实现应保证：写入失败时抛出异常（此时上层不会发布事件）。
    """

    def write(self, metric: HealthMetric) -> None:  # pragma: no cover - 协议声明
        """将一条已校验的健康指标写入超表。"""
        ...


class InMemoryHealthMetricRepository:
    """基于内存列表的 :class:`HealthMetricRepository` 假实现，供测试与无数据库场景使用。

    按写入顺序保留全部指标，供测试断言"校验失败时时序表保持不变"。
    """

    def __init__(self) -> None:
        self._rows: list[HealthMetric] = []

    def write(self, metric: HealthMetric) -> None:
        self._rows.append(metric)

    @property
    def rows(self) -> list[HealthMetric]:
        """返回已写入指标的只读副本。"""
        return list(self._rows)

    def __len__(self) -> int:
        return len(self._rows)


class HealthDataHub:
    """健康数据中台：校验上报数据 → 写入 TimescaleDB 超表 → 发布领域事件。"""

    def __init__(
        self,
        repository: HealthMetricRepository,
        event_bus: EventBus,
        *,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
        enforce_deadline: bool = False,
        deadline_seconds: float = INGEST_DEADLINE_SECONDS,
    ) -> None:
        """构造健康数据中台。

        Args:
            repository: 健康时序指标仓库（对应 TimescaleDB 超表写入）。
            event_bus: 事件总线，用于发布 ``health_data_ingested`` 事件。
            clock: 返回当前时间的可调用对象（默认 UTC ``datetime.now``），便于测试。
            id_factory: 生成事件 ID 的可调用对象（默认 ``uuid4`` 十六进制），便于测试。
            enforce_deadline: 为真时，写入 + 发布耗时超过预算将抛
                :class:`HealthDataIngestTimeoutError`（默认关闭）。
            deadline_seconds: 时间预算（秒），默认 :data:`INGEST_DEADLINE_SECONDS`。
        """
        self._repository = repository
        self._event_bus = event_bus
        self._clock = clock or (lambda: datetime.now(tz=timezone.utc))
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)
        self._enforce_deadline = enforce_deadline
        self._deadline_seconds = deadline_seconds

    def ingest(
        self, pet_id: str, metrics: HealthMetric | Mapping[str, Any]
    ) -> DomainEvent:
        """校验并写入一条健康指标，成功后发布 ``health_data_ingested`` 事件。

        ``metrics`` 可为已构造的 :class:`~app.models.timeseries.HealthMetric`，也可为
        字段映射（须含 ``tenant_id``、``ts``、``weight_kg``、``activity_minutes``、
        ``food_intake_g``）。若为映射且未含 ``pet_id``，则以入参 ``pet_id`` 补齐。

        流程：校验 → 写入超表 → 发布事件。任一校验失败即抛
        :class:`HealthDataValidationError`，不写入、不发布（时序表保持不变）。

        Args:
            pet_id: 宠物 ID。
            metrics: 健康指标模型或字段映射。

        Returns:
            已发布的 :class:`~app.models.timeseries.DomainEvent`
            （``event_type == "health_data_ingested"``）。

        Raises:
            HealthDataValidationError: 数据缺 ``tenant_id`` 或数值越界等校验失败。
            HealthDataIngestTimeoutError: 开启 ``enforce_deadline`` 且超出时间预算。
        """
        start = time.monotonic()

        metric = self._validate(pet_id, metrics)

        # 先写后发：仅当写入成功才发布事件，保证"未写入即无事件"。
        self._repository.write(metric)

        event = DomainEvent(
            event_id=self._id_factory(),
            tenant_id=metric.tenant_id,
            event_type=HEALTH_DATA_INGESTED_EVENT,
            payload={
                "pet_id": metric.pet_id,
                "ts": metric.ts.isoformat(),
                "weight_kg": metric.weight_kg,
                "activity_minutes": metric.activity_minutes,
                "food_intake_g": metric.food_intake_g,
            },
            occurred_at=self._clock(),
        )
        self._event_bus.publish(event)

        if self._enforce_deadline:
            elapsed = time.monotonic() - start
            if elapsed > self._deadline_seconds:
                raise HealthDataIngestTimeoutError(
                    f"健康数据写入与事件发布耗时 {elapsed:.3f}s，超过预算 "
                    f"{self._deadline_seconds:.1f}s"
                )

        return event

    def _validate(
        self, pet_id: str, metrics: HealthMetric | Mapping[str, Any]
    ) -> HealthMetric:
        """将入参规整并校验为 :class:`HealthMetric`。

        复用 :class:`HealthMetric` 的 Pydantic 校验（``tenant_id`` 非空、
        ``weight_kg > 0``、活动时长/进食量 ≥ 0）；校验失败转换为
        :class:`HealthDataValidationError`（消息含底层原因）。
        """
        if isinstance(metrics, HealthMetric):
            # 已是模型：pet_id 若显式提供且不一致则拒绝，避免张冠李戴。
            if pet_id is not None and str(pet_id).strip() and metrics.pet_id != pet_id:
                raise HealthDataValidationError(
                    f"pet_id 不一致：入参 {pet_id!r} 与指标 {metrics.pet_id!r} 不符"
                )
            return metrics

        if not isinstance(metrics, Mapping):
            raise HealthDataValidationError(
                "metrics 必须为 HealthMetric 或字段映射"
            )

        data: dict[str, Any] = dict(metrics)
        # 入参 pet_id 优先补齐（映射未显式提供 pet_id 时）。
        data.setdefault("pet_id", pet_id)

        try:
            return HealthMetric.model_validate(data)
        except ValidationError as exc:
            raise HealthDataValidationError(
                f"健康数据校验失败：{exc.errors()}"
            ) from exc
