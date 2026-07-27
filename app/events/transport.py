"""事件总线传输层抽象（Redis Stream 语义）。

任务 11.1 只关注"发布 + 多消费者分发（至少一次投递）"，因此本模块把底层传输
抽象为 :class:`StreamTransport` 协议，采用 **Redis Stream** 的核心语义：

- ``append``       : 向某个 stream 追加一条消息，返回单调递增的消息 ID（对应 ``XADD``）。
- ``ensure_group`` : 幂等创建消费者组，新组从"当前末尾"开始消费（对应 ``XGROUP CREATE ... $``）。
- ``read_new``     : 为某消费者组读取尚未投递的新消息（对应 ``XREADGROUP > ``），
  被读取的消息进入该组的待确认列表（PEL）。
- ``ack``          : 确认某条消息已被某组成功处理（对应 ``XACK``），从 PEL 移除。

Redis Stream 的关键性质是 **多消费者组扇出**：同一 stream 的每个消费者组都会独立地
收到全部消息，从而支持"一份事件分发给 Agent 触发器 / 特征更新 / 通知推送 / 审计日志
四类消费者"。确认（ack）语义则提供 **至少一次投递**——未确认的消息不会被丢弃。

该抽象使 :class:`~app.events.bus.EventBus` 与具体传输解耦：生产环境使用
:class:`RedisStreamTransport`（真实 Redis），测试可注入 :class:`InMemoryStreamTransport`
（进程内内存实现），无需连接实时 Redis。

注意：消费失败重试与死信队列（DLQ）属于任务 11.2，不在本模块范围内。
"""

from __future__ import annotations

import itertools
import threading
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:  # pragma: no cover - 仅类型检查期使用
    from collections.abc import Mapping


# stream 消息：(消息 ID, 字段字典)。字段值均为字符串，贴合 Redis Stream 语义。
StreamMessage = tuple[str, dict[str, str]]


@runtime_checkable
class StreamTransport(Protocol):
    """事件总线底层传输协议（Redis Stream 语义）。

    实现须保证：同一 stream 上的多个消费者组彼此独立地收到全部消息（扇出），
    且消息在被 ``ack`` 之前保持"待确认"，以支持至少一次投递。
    """

    def append(self, stream: str, fields: "Mapping[str, str]") -> str:
        """向 ``stream`` 追加一条消息，返回其消息 ID（等价 ``XADD``）。"""
        ...

    def ensure_group(self, stream: str, group: str) -> None:
        """幂等创建消费者组；已存在则为空操作（等价 ``XGROUP CREATE`` + ``MKSTREAM``）。"""
        ...

    def read_new(
        self, stream: str, group: str, consumer: str, count: int
    ) -> list[StreamMessage]:
        """为 ``group`` 读取至多 ``count`` 条未投递消息（等价 ``XREADGROUP > ``）。

        被读取的消息进入该组待确认列表（PEL），在 ``ack`` 前视为处理中。
        """
        ...

    def ack(self, stream: str, group: str, message_id: str) -> int:
        """确认 ``group`` 已处理 ``message_id``（等价 ``XACK``），返回被确认的条数。"""
        ...


class InMemoryStreamTransport:
    """进程内的 Redis Stream 语义实现，供测试注入（无需实时 Redis）。

    维护每个 stream 的有序消息列表、每个消费者组的读取游标与待确认列表（PEL）。
    线程安全（以简单互斥锁保护），消息 ID 采用单调递增的 ``"<seq>-0"`` 形式。
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._streams: dict[str, list[StreamMessage]] = {}
        self._seq = itertools.count(1)
        # (stream, group) -> 已投递到的下标（游标）。
        self._cursors: dict[tuple[str, str], int] = {}
        # (stream, group) -> 待确认消息 ID 集合（PEL）。
        self._pending: dict[tuple[str, str], set[str]] = {}

    def append(self, stream: str, fields: "Mapping[str, str]") -> str:
        with self._lock:
            message_id = f"{next(self._seq)}-0"
            self._streams.setdefault(stream, []).append((message_id, dict(fields)))
            return message_id

    def ensure_group(self, stream: str, group: str) -> None:
        with self._lock:
            self._streams.setdefault(stream, [])
            key = (stream, group)
            if key not in self._cursors:
                # 新组从当前末尾开始消费（等价 XGROUP CREATE ... $）。
                self._cursors[key] = len(self._streams[stream])
                self._pending[key] = set()

    def read_new(
        self, stream: str, group: str, consumer: str, count: int
    ) -> list[StreamMessage]:
        with self._lock:
            key = (stream, group)
            if key not in self._cursors:
                raise KeyError(f"消费者组不存在: stream={stream!r} group={group!r}")
            messages = self._streams.get(stream, [])
            start = self._cursors[key]
            end = min(start + max(count, 0), len(messages))
            batch = messages[start:end]
            self._cursors[key] = end
            for message_id, _ in batch:
                self._pending[key].add(message_id)
            # 返回副本，避免调用方修改内部状态。
            return [(mid, dict(fields)) for mid, fields in batch]

    def ack(self, stream: str, group: str, message_id: str) -> int:
        with self._lock:
            key = (stream, group)
            pending = self._pending.get(key)
            if pending and message_id in pending:
                pending.discard(message_id)
                return 1
            return 0

    # --- 供测试内省的辅助方法（非协议要求） ---------------------------------

    def pending_ids(self, stream: str, group: str) -> set[str]:
        """返回某组当前待确认（未 ack）的消息 ID 集合。"""
        with self._lock:
            return set(self._pending.get((stream, group), set()))

    def stream_length(self, stream: str) -> int:
        """返回某 stream 当前消息条数。"""
        with self._lock:
            return len(self._streams.get(stream, []))


class RedisStreamTransport:
    """基于真实 Redis 客户端的 Stream 传输实现。

    仅封装任务 11.1 所需的四个原语（XADD / XGROUP CREATE / XREADGROUP / XACK）。
    ``redis_client`` 需为 ``redis.Redis`` 实例（``decode_responses=True`` 时字段为
    字符串）。构造时不建立连接，首次调用相关命令时才与服务端交互。
    """

    def __init__(self, redis_client: object) -> None:
        self._redis = redis_client

    def append(self, stream: str, fields: "Mapping[str, str]") -> str:
        message_id = self._redis.xadd(stream, dict(fields))  # type: ignore[attr-defined]
        return message_id.decode() if isinstance(message_id, bytes) else str(message_id)

    def ensure_group(self, stream: str, group: str) -> None:
        try:
            # mkstream=True：stream 不存在时一并创建；id="$"：仅消费新消息。
            self._redis.xgroup_create(stream, group, id="$", mkstream=True)  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001 - Redis 客户端异常类型随版本而异
            # 组已存在（BUSYGROUP）视为幂等成功；其余异常向上抛出。
            if "BUSYGROUP" not in str(exc):
                raise

    def read_new(
        self, stream: str, group: str, consumer: str, count: int
    ) -> list[StreamMessage]:
        # ">" 表示只取该组从未投递过的新消息。
        response = self._redis.xreadgroup(  # type: ignore[attr-defined]
            group, consumer, {stream: ">"}, count=count
        )
        return list(_iter_xreadgroup(response))

    def ack(self, stream: str, group: str, message_id: str) -> int:
        return int(self._redis.xack(stream, group, message_id))  # type: ignore[attr-defined]


def _decode(value: object) -> str:
    """将 Redis 返回的 bytes/str 统一为 str。"""
    return value.decode() if isinstance(value, bytes) else str(value)


def _iter_xreadgroup(response: object):
    """解析 ``XREADGROUP`` 响应为 :data:`StreamMessage` 序列。

    兼容 ``decode_responses`` 为 True/False 两种客户端配置。
    """
    if not response:
        return
    for _stream_name, entries in response:  # type: ignore[misc]
        for message_id, raw_fields in entries:
            fields = {
                _decode(k): _decode(v) for k, v in dict(raw_fields).items()
            }
            yield (_decode(message_id), fields)
