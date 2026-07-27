"""健康 Agent：健康异常趋势检测与预警（对应设计文档组件 2 ``HealthAgent`` 与序列图 2.3）。

本模块实现任务 15.2 —— **事件触发的健康异常趋势检测**：

> 需求 9.3：WHEN Event_Bus 接收到 ``health_data_ingested`` 事件，THE Health_Agent SHALL
> 在 30 秒内基于该宠物最近 30 天的时序数据执行异常趋势检测。
>
> 需求 9.4：IF 检测到健康异常趋势（如体重在 7 天内下降超过 10%），THEN THE Health_Agent
> SHALL 向 Event_Bus 发布携带级别为 低、中、高 之一的 ``health_alert`` 事件并生成对应的
> 预警任务。

设计要点：

- **事件消费**：:meth:`HealthAgent.handle_event` 满足 :data:`~app.events.bus.EventHandler`
  签名，可直接注册到 :class:`~app.events.bus.EventBus` 的 ``agent-trigger`` 消费者组。
  仅处理 ``event_type == "health_data_ingested"`` 的事件，其它事件被安全忽略。
- **最近 30 天时序**：经 :class:`HealthMetricReader` 协议读取该宠物在 ``[as_of-30d, as_of]``
  的健康指标序列（TimescaleDB 超表查询的抽象），从而无需实时数据库即可测试。
- **异常趋势规则**：MVP 实现"7 天体重降幅 > 10%"规则——以最近 7 天窗口内的最高体重为
  基线，若最新体重较基线下降超过 10% 即判定异常；降幅越大级别越高（低/中/高）。
- **预警发布 + 任务生成**：检测到异常时向注入的 :class:`~app.events.bus.EventBus`
  发布带级别的 ``health_alert`` 事件，并经 :class:`AlertTaskSink` 生成预警任务。
- **依赖注入**：时序读取、事件发布、任务下沉均以协议抽象注入，可用内存假实现
  （:class:`InMemoryHealthMetricReader` + :class:`InMemoryAlertTaskSink`）在无实时数据库 /
  Redis 的情况下测试。
- **30 秒预算**：读取 + 检测 + 发布均为同步快操作；可选 ``enforce_deadline`` 在超出预算时
  抛 :class:`HealthDetectionTimeoutError`（默认关闭，避免慢速环境误判）。

范围约束：级别为高时经 Ecosystem_Network 生成转介绍建议（需求 9.5）属于任务 17.1，
本任务 **不** 实现转介绍写入。
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Callable, Protocol, runtime_checkable

from app.engines.errors import EngineError
from app.events.bus import EventBus
from app.models import DomainEvent, HealthMetric

__all__ = [
    "HEALTH_DATA_INGESTED_EVENT",
    "HEALTH_ALERT_EVENT",
    "DETECTION_DEADLINE_SECONDS",
    "ANALYSIS_WINDOW_DAYS",
    "WEIGHT_DROP_WINDOW_DAYS",
    "WEIGHT_DROP_THRESHOLD",
    "LEVEL_MEDIUM_THRESHOLD",
    "LEVEL_HIGH_THRESHOLD",
    "HealthAlertLevel",
    "HealthAlert",
    "AlertTask",
    "HealthDetectionTimeoutError",
    "HealthMetricReader",
    "InMemoryHealthMetricReader",
    "AlertTaskSink",
    "InMemoryAlertTaskSink",
    "HealthAgent",
]

#: 触发检测的上游事件类型（由 HealthDataHub 于写入成功后发布，任务 15.1）。
HEALTH_DATA_INGESTED_EVENT = "health_data_ingested"

#: 检测到异常后发布的领域事件类型（设计文档 7.1 关键事件类型之一）。
HEALTH_ALERT_EVENT = "health_alert"

#: 需求 9.3 规定的检测时间预算（秒）。
DETECTION_DEADLINE_SECONDS = 30.0

#: 异常趋势检测所回溯的时序窗口长度（天）——需求 9.3 "最近 30 天"。
ANALYSIS_WINDOW_DAYS = 30

#: 体重降幅规则的观察窗口长度（天）——需求 9.4 "7 天内"。
WEIGHT_DROP_WINDOW_DAYS = 7

#: 体重降幅判定为异常的阈值（比例）——需求 9.4 "下降超过 10%"。
WEIGHT_DROP_THRESHOLD = 0.10

#: 降幅超过该阈值判为"中"级别。
LEVEL_MEDIUM_THRESHOLD = 0.18

#: 降幅超过该阈值判为"高"级别。
LEVEL_HIGH_THRESHOLD = 0.25


class HealthAlertLevel(str, Enum):
    """健康预警级别（需求 9.4：低、中、高 之一）。"""

    LOW = "低"
    MEDIUM = "中"
    HIGH = "高"


class HealthDetectionTimeoutError(EngineError):
    """检测耗时超过时间预算（需求 9.3：30 秒）。

    仅在构造 :class:`HealthAgent` 时显式开启 ``enforce_deadline`` 才会抛出；默认不启用，
    以免在慢速环境中把已完成的检测误判为失败。
    """


@dataclass(frozen=True)
class HealthAlert:
    """一条检测到的健康异常预警。

    Attributes:
        pet_id: 宠物 ID。
        tenant_id: 租户隔离键。
        metric: 触发异常的指标名（本实现为 ``"weight_kg"``）。
        level: 预警级别（低/中/高）。
        drop_ratio: 相对基线的降幅比例（0~1）。
        baseline: 观察窗口内的基线值（最高体重）。
        latest: 最新观测值。
        window_days: 观察窗口长度（天）。
        reason: 人类可读的异常说明。
        detected_at: 检测时刻。
    """

    pet_id: str
    tenant_id: str
    metric: str
    level: HealthAlertLevel
    drop_ratio: float
    baseline: float
    latest: float
    window_days: int
    reason: str
    detected_at: datetime


@dataclass(frozen=True)
class AlertTask:
    """由检测到的预警生成的预警任务（需求 9.4："生成对应的预警任务"）。"""

    task_id: str
    tenant_id: str
    pet_id: str
    level: HealthAlertLevel
    reason: str
    event_id: str
    created_at: datetime


@runtime_checkable
class HealthMetricReader(Protocol):
    """健康时序指标读取协议（TimescaleDB 超表 ``health_metrics`` 的查询抽象）。

    抽象掉底层持久化（TimescaleDB / 测试内存实现），仅暴露"读取某宠物在时间窗口内、
    当前租户范围内的指标序列"的能力。实现应仅返回 ``tenant_id`` 等于入参的记录。
    """

    def recent_metrics(
        self, pet_id: str, tenant_id: str, *, since: datetime, until: datetime
    ) -> list[HealthMetric]:  # pragma: no cover - 协议声明
        """返回 ``[since, until]`` 窗口内、指定宠物与租户的健康指标序列。"""
        ...


class InMemoryHealthMetricReader:
    """基于内存列表的 :class:`HealthMetricReader` 假实现，供测试与无数据库场景使用。"""

    def __init__(self, metrics: list[HealthMetric] | None = None) -> None:
        self._metrics: list[HealthMetric] = list(metrics or [])

    def add(self, metric: HealthMetric) -> None:
        """登记一条指标。"""
        self._metrics.append(metric)

    def recent_metrics(
        self, pet_id: str, tenant_id: str, *, since: datetime, until: datetime
    ) -> list[HealthMetric]:
        return [
            m
            for m in self._metrics
            if m.pet_id == pet_id
            and m.tenant_id == tenant_id
            and since <= m.ts <= until
        ]


@runtime_checkable
class AlertTaskSink(Protocol):
    """预警任务下沉协议：生成 / 登记预警任务（需求 9.4）。"""

    def create_task(self, task: AlertTask) -> None:  # pragma: no cover - 协议声明
        ...


class InMemoryAlertTaskSink:
    """基于内存列表的 :class:`AlertTaskSink` 假实现，供测试与无数据库场景使用。"""

    def __init__(self) -> None:
        self._tasks: list[AlertTask] = []

    def create_task(self, task: AlertTask) -> None:
        self._tasks.append(task)

    @property
    def tasks(self) -> list[AlertTask]:
        """返回已生成预警任务的只读副本。"""
        return list(self._tasks)

    def __len__(self) -> int:
        return len(self._tasks)


class HealthAgent:
    """健康 Agent：消费 ``health_data_ingested`` → 检测异常趋势 → 发布 ``health_alert`` 并生成预警任务。"""

    def __init__(
        self,
        reader: HealthMetricReader,
        event_bus: EventBus,
        alert_task_sink: AlertTaskSink,
        *,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
        analysis_window_days: int = ANALYSIS_WINDOW_DAYS,
        weight_drop_window_days: int = WEIGHT_DROP_WINDOW_DAYS,
        weight_drop_threshold: float = WEIGHT_DROP_THRESHOLD,
        enforce_deadline: bool = False,
        deadline_seconds: float = DETECTION_DEADLINE_SECONDS,
    ) -> None:
        """构造健康 Agent。

        Args:
            reader: 健康时序指标读取器（对应 TimescaleDB 超表查询）。
            event_bus: 事件总线，用于发布 ``health_alert`` 事件。
            alert_task_sink: 预警任务下沉（生成 / 登记预警任务）。
            clock: 返回当前时间的可调用对象（默认 UTC ``datetime.now``），便于测试。
            id_factory: 生成事件 ID / 任务 ID 的可调用对象（默认 ``uuid4`` 十六进制）。
            analysis_window_days: 回溯的时序窗口（天），默认 :data:`ANALYSIS_WINDOW_DAYS`。
            weight_drop_window_days: 体重降幅观察窗口（天），默认
                :data:`WEIGHT_DROP_WINDOW_DAYS`。
            weight_drop_threshold: 体重降幅异常阈值（比例），默认
                :data:`WEIGHT_DROP_THRESHOLD`。
            enforce_deadline: 为真时检测耗时超预算将抛
                :class:`HealthDetectionTimeoutError`（默认关闭）。
            deadline_seconds: 时间预算（秒），默认 :data:`DETECTION_DEADLINE_SECONDS`。
        """
        self._reader = reader
        self._event_bus = event_bus
        self._alert_task_sink = alert_task_sink
        self._clock = clock or (lambda: datetime.now(tz=timezone.utc))
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)
        self._analysis_window_days = analysis_window_days
        self._weight_drop_window_days = weight_drop_window_days
        self._weight_drop_threshold = weight_drop_threshold
        self._enforce_deadline = enforce_deadline
        self._deadline_seconds = deadline_seconds

    # ------------------------------------------------------------------ #
    # 事件消费入口
    # ------------------------------------------------------------------ #
    def handle_event(self, event: DomainEvent) -> list[DomainEvent]:
        """事件总线处理回调（满足 :data:`~app.events.bus.EventHandler` 签名）。

        仅处理 ``health_data_ingested`` 事件；其它事件类型被安全忽略并返回空列表。

        Returns:
            本次处理发布的 ``health_alert`` 事件列表（无异常时为空）。
        """
        if event.event_type != HEALTH_DATA_INGESTED_EVENT:
            return []
        return self.handle_health_data_ingested(event)

    def handle_health_data_ingested(self, event: DomainEvent) -> list[DomainEvent]:
        """消费一个 ``health_data_ingested`` 事件：检测异常并发布预警、生成预警任务。

        从事件 payload 提取 ``pet_id`` 与检测时刻（默认取 payload 中 ``ts`` 或当前时钟），
        基于最近 :data:`ANALYSIS_WINDOW_DAYS` 天时序检测异常趋势；检测到异常则发布带级别的
        ``health_alert`` 事件并生成对应预警任务（需求 9.3 / 9.4）。

        Args:
            event: ``health_data_ingested`` 领域事件。

        Returns:
            已发布的 ``health_alert`` 事件列表（无异常返回空列表）。

        Raises:
            HealthDetectionTimeoutError: 开启 ``enforce_deadline`` 且检测超出时间预算。
        """
        start = time.monotonic()

        pet_id = str(event.payload.get("pet_id") or "").strip()
        as_of = self._resolve_as_of(event)

        published: list[DomainEvent] = []
        if pet_id:
            alerts = self.detect(pet_id, event.tenant_id, as_of=as_of)
            for alert in alerts:
                published.append(self._emit_alert(alert))

        if self._enforce_deadline:
            elapsed = time.monotonic() - start
            if elapsed > self._deadline_seconds:
                raise HealthDetectionTimeoutError(
                    f"健康异常检测耗时 {elapsed:.3f}s，超过预算 "
                    f"{self._deadline_seconds:.1f}s"
                )

        return published

    # ------------------------------------------------------------------ #
    # 检测逻辑
    # ------------------------------------------------------------------ #
    def detect(
        self, pet_id: str, tenant_id: str, *, as_of: datetime | None = None
    ) -> list[HealthAlert]:
        """基于最近 30 天时序检测该宠物的健康异常趋势（需求 9.3 / 9.4）。

        当前实现的规则：**7 天体重降幅 > 10%**。以最近 7 天窗口内的最高体重为基线，
        若最新体重较基线下降超过阈值即判为异常，降幅越大级别越高。

        Args:
            pet_id: 宠物 ID。
            tenant_id: 租户隔离键。
            as_of: 检测参照时刻（默认取当前时钟）；30 天窗口以此为终点回溯。

        Returns:
            检测到的 :class:`HealthAlert` 列表（无异常返回空列表）。
        """
        as_of = as_of or self._clock()
        since = as_of - timedelta(days=self._analysis_window_days)
        series = self._reader.recent_metrics(
            pet_id, tenant_id, since=since, until=as_of
        )

        alerts: list[HealthAlert] = []
        weight_alert = self._detect_weight_drop(pet_id, tenant_id, series, as_of)
        if weight_alert is not None:
            alerts.append(weight_alert)
        return alerts

    def _detect_weight_drop(
        self,
        pet_id: str,
        tenant_id: str,
        series: list[HealthMetric],
        as_of: datetime,
    ) -> HealthAlert | None:
        """检测 7 天体重降幅是否超过阈值。"""
        # 取最近 7 天窗口内的样本，按时间升序排列。
        window_start = as_of - timedelta(days=self._weight_drop_window_days)
        window = sorted(
            (m for m in series if window_start <= m.ts <= as_of),
            key=lambda m: m.ts,
        )
        if len(window) < 2:
            # 样本不足以判定趋势。
            return None

        baseline = max(m.weight_kg for m in window)
        latest = window[-1].weight_kg
        if baseline <= 0:
            return None

        drop_ratio = (baseline - latest) / baseline
        if drop_ratio <= self._weight_drop_threshold:
            return None

        level = self._classify_level(drop_ratio)
        reason = (
            f"宠物 {pet_id} 体重在最近 {self._weight_drop_window_days} 天内由 "
            f"{baseline:.2f}kg 降至 {latest:.2f}kg，降幅 {drop_ratio * 100:.1f}% "
            f"超过 {self._weight_drop_threshold * 100:.0f}% 阈值"
        )
        return HealthAlert(
            pet_id=pet_id,
            tenant_id=tenant_id,
            metric="weight_kg",
            level=level,
            drop_ratio=drop_ratio,
            baseline=baseline,
            latest=latest,
            window_days=self._weight_drop_window_days,
            reason=reason,
            detected_at=as_of,
        )

    def _classify_level(self, drop_ratio: float) -> HealthAlertLevel:
        """按降幅大小映射到预警级别（低/中/高）。"""
        if drop_ratio > LEVEL_HIGH_THRESHOLD:
            return HealthAlertLevel.HIGH
        if drop_ratio > LEVEL_MEDIUM_THRESHOLD:
            return HealthAlertLevel.MEDIUM
        return HealthAlertLevel.LOW

    # ------------------------------------------------------------------ #
    # 预警发布与任务生成
    # ------------------------------------------------------------------ #
    def _emit_alert(self, alert: HealthAlert) -> DomainEvent:
        """发布 ``health_alert`` 事件并生成对应预警任务，返回已发布事件。"""
        event = DomainEvent(
            event_id=self._id_factory(),
            tenant_id=alert.tenant_id,
            event_type=HEALTH_ALERT_EVENT,
            payload={
                "pet_id": alert.pet_id,
                "metric": alert.metric,
                "level": alert.level.value,
                "drop_ratio": alert.drop_ratio,
                "baseline": alert.baseline,
                "latest": alert.latest,
                "window_days": alert.window_days,
                "reason": alert.reason,
                "detected_at": alert.detected_at.isoformat(),
            },
            occurred_at=self._clock(),
        )
        self._event_bus.publish(event)

        # 生成预警任务（需求 9.4）。
        task = AlertTask(
            task_id=self._id_factory(),
            tenant_id=alert.tenant_id,
            pet_id=alert.pet_id,
            level=alert.level,
            reason=alert.reason,
            event_id=event.event_id,
            created_at=self._clock(),
        )
        self._alert_task_sink.create_task(task)

        return event

    # ------------------------------------------------------------------ #
    # 辅助
    # ------------------------------------------------------------------ #
    def _resolve_as_of(self, event: DomainEvent) -> datetime:
        """从事件 payload 解析检测参照时刻，缺失或非法时回退到当前时钟。"""
        raw_ts = event.payload.get("ts")
        if isinstance(raw_ts, str) and raw_ts.strip():
            try:
                return datetime.fromisoformat(raw_ts)
            except ValueError:
                pass
        if isinstance(event.occurred_at, datetime):
            return event.occurred_at
        return self._clock()
