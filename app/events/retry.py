"""消费失败重试与死信队列（DLQ）——任务 11.2。

对应设计文档 "七、事件驱动数据架构" 的故障处理策略（事件消费失败 → 进入 DLQ → 告警），
落实需求 18.4 / 18.5：

- 18.4：IF 事件消费失败，THEN THE Event_Bus SHALL 以指数退避策略对该事件最多重试 3 次。
- 18.5：IF 事件在重试 3 次后仍消费失败，THEN THE Event_Bus SHALL 将该事件转入死信队列
  （DLQ），保留原始事件内容，并在 60 秒内向运营方触发告警。

设计要点与可测试性：

- **指数退避**：:class:`RetryPolicy` 计算第 n 次重试的退避时长（初始 ``base_delay``、每次
  乘以 ``factor``、上限 ``max_delay``），与 LLM 客户端（需求 20.1）一致，默认 1s→2s→…→8s。
- **时钟与告警可注入**：真实等待与真实告警会拖慢并复杂化测试，故把 "睡眠函数"（``sleep``）
  与 "时钟"（``clock``）以及告警器（:class:`Alerter`）都做成可注入依赖。测试注入无操作的
  ``sleep`` 与内存告警器/DLQ，即可在毫秒级验证重试次数、DLQ 内容与 60s 告警 SLA，且无需
  连接实时 Redis。
- **原始内容保留**：转入 DLQ 的 :class:`DeadLetter` 直接持有原始 :class:`DomainEvent`
  对象（不做有损转换），满足 "保留原始事件内容"。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Protocol, runtime_checkable

from app.models import DomainEvent

# 墙钟时间源：用于判定 "60 秒内告警" 的 SLA，可注入以便测试确定性。
Clock = Callable[[], datetime]
# 退避等待函数：默认 ``time.sleep``；测试可注入无操作实现以避免真实等待。
Sleeper = Callable[[float], None]

#: 需求 18.5 规定的告警时限：转入 DLQ 后 60 秒内触发告警。
ALERT_SLA_SECONDS = 60.0


def default_clock() -> datetime:
    """默认时钟：返回带时区的当前 UTC 时间。"""
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class RetryPolicy:
    """指数退避重试策略（需求 18.4：最多重试 3 次）。

    约定 ``max_retries`` 为 "重试次数"（不含首次尝试），因此一个事件的总尝试次数为
    ``max_retries + 1``。第 ``n`` 次重试（``n`` 从 1 计）的退避时长为::

        min(base_delay * factor ** (n - 1), max_delay)

    默认 1s → 2s → 4s（上限 8s），与云端 LLM 重试（需求 20.1）保持一致。
    """

    max_retries: int = 3
    base_delay: float = 1.0
    factor: float = 2.0
    max_delay: float = 8.0

    def __post_init__(self) -> None:
        if self.max_retries < 0:
            raise ValueError("max_retries 不能为负数")
        if self.base_delay < 0 or self.max_delay < 0:
            raise ValueError("退避时长不能为负数")
        if self.factor < 1:
            raise ValueError("factor 应 ≥ 1，否则退避不会增长")

    def backoff(self, attempt: int) -> float:
        """返回第 ``attempt`` 次重试（1 起）的退避秒数，封顶于 ``max_delay``。"""
        if attempt < 1:
            raise ValueError("attempt 从 1 开始计数")
        delay = self.base_delay * (self.factor ** (attempt - 1))
        return min(delay, self.max_delay)

    def delays(self) -> list[float]:
        """按序返回全部重试的退避时长（长度 == ``max_retries``）。"""
        return [self.backoff(n) for n in range(1, self.max_retries + 1)]


@dataclass(frozen=True)
class DeadLetter:
    """转入 DLQ 的死信记录，完整保留原始事件内容与失败上下文（需求 18.5）。"""

    event: DomainEvent          # 原始事件内容（无损保留）
    consumer_group: str         # 消费失败所在的消费者组
    attempts: int               # 总尝试次数（含首次，== max_retries + 1）
    error: str                  # 最后一次失败的错误信息
    failed_at: datetime         # 判定消费失败、转入 DLQ 的时刻


@runtime_checkable
class DeadLetterQueue(Protocol):
    """死信队列协议：接收并保存无法消费的事件。"""

    def put(self, record: DeadLetter) -> None:
        """将一条死信记录写入 DLQ。"""
        ...


@runtime_checkable
class Alerter(Protocol):
    """告警器协议：在事件转入 DLQ 后向运营方触发告警。"""

    def alert(self, record: DeadLetter, *, raised_at: datetime) -> None:
        """就某条死信记录触发告警；``raised_at`` 为告警触发时刻。"""
        ...


class InMemoryDeadLetterQueue:
    """进程内 DLQ 实现，供测试注入（无需实时 Redis）。"""

    def __init__(self) -> None:
        self._records: list[DeadLetter] = []

    def put(self, record: DeadLetter) -> None:
        self._records.append(record)

    @property
    def records(self) -> list[DeadLetter]:
        """返回当前 DLQ 中全部死信记录的副本。"""
        return list(self._records)

    def __len__(self) -> int:
        return len(self._records)


@dataclass
class RaisedAlert:
    """一次已触发的告警记录，供测试内省告警内容与时延。"""

    dead_letter: DeadLetter
    raised_at: datetime

    def latency_seconds(self) -> float:
        """从 "判定失败" 到 "触发告警" 的时延（秒），用于校验 60s SLA。"""
        return (self.raised_at - self.dead_letter.failed_at).total_seconds()


class RecordingAlerter:
    """进程内告警器实现，记录全部告警，供测试注入与断言。"""

    def __init__(self) -> None:
        self._alerts: list[RaisedAlert] = []

    def alert(self, record: DeadLetter, *, raised_at: datetime) -> None:
        self._alerts.append(RaisedAlert(dead_letter=record, raised_at=raised_at))

    @property
    def alerts(self) -> list[RaisedAlert]:
        return list(self._alerts)

    def __len__(self) -> int:
        return len(self._alerts)


@dataclass
class RetryOutcome:
    """一次 "带重试的消费" 的结果，供调用方与测试内省。"""

    succeeded: bool
    attempts: int                    # 实际尝试次数（含首次）
    dead_lettered: bool = False
    alerted: bool = False
    alert_latency_seconds: float | None = None  # 触发告警的时延（秒）
    error: str | None = None         # 最终失败的错误信息（若有）


@dataclass
class RetryingConsumer:
    """在消费者处理回调之上叠加 "指数退避重试 + DLQ + 告警" 的执行器。

    行为（需求 18.4 / 18.5）：

    1. 首次尝试调用 ``handler(event)``；失败则按 :class:`RetryPolicy` 退避后重试，最多
       ``policy.max_retries`` 次。
    2. 任一尝试成功即返回成功结果。
    3. 全部尝试耗尽仍失败：构造 :class:`DeadLetter`（保留原始事件），写入 DLQ，并立即触发
       告警。由于告警在转入 DLQ 后同步触发，其时延远小于 60s，满足需求 18.5 的 SLA。

    依赖注入：``sleep`` 与 ``clock`` 均可替换，测试可注入无操作 ``sleep`` 与确定性时钟，
    从而快速、可重复地验证重试次数、DLQ 内容与告警时延，无需真实等待或实时 Redis。
    """

    dead_letter_queue: DeadLetterQueue
    alerter: Alerter
    policy: RetryPolicy = field(default_factory=RetryPolicy)
    sleep: Sleeper = time.sleep
    clock: Clock = default_clock

    def consume(
        self,
        handler: Callable[[DomainEvent], None],
        event: DomainEvent,
        consumer_group: str,
    ) -> RetryOutcome:
        """以重试 / DLQ / 告警语义消费单个事件。"""
        total_attempts = self.policy.max_retries + 1
        last_error: Exception | None = None

        for attempt in range(total_attempts):
            try:
                handler(event)
                return RetryOutcome(succeeded=True, attempts=attempt + 1)
            except Exception as exc:  # noqa: BLE001 - 消费失败需按策略重试/转 DLQ
                last_error = exc
                # 仍有重试机会：按退避时长等待后再试。
                if attempt < self.policy.max_retries:
                    self.sleep(self.policy.backoff(attempt + 1))

        # 重试耗尽 → 转入 DLQ 并告警（需求 18.5）。
        failed_at = self.clock()
        record = DeadLetter(
            event=event,
            consumer_group=consumer_group,
            attempts=total_attempts,
            error=str(last_error),
            failed_at=failed_at,
        )
        self.dead_letter_queue.put(record)

        raised_at = self.clock()
        self.alerter.alert(record, raised_at=raised_at)
        latency = (raised_at - failed_at).total_seconds()

        return RetryOutcome(
            succeeded=False,
            attempts=total_attempts,
            dead_lettered=True,
            alerted=True,
            alert_latency_seconds=latency,
            error=str(last_error),
        )
