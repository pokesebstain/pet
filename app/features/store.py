"""特征存储 Feature Store（对应设计文档 7.2 特征存储共享，Requirement 19）。

为 LTV / churn / demand 三类模型提供统一的特征读写接口，并区分：

- **在线通道（online）**：由 Redis 支撑的低延迟读写，目标 P99 < 100ms，供实时推理。
- **离线通道（offline）**：由数据库（如 PostgreSQL）支撑的持久化读写，作为特征真值来源。

核心不变量与降级策略（与设计 / 需求一致）：

- 一致性（19.3）：``write`` 会将同一 :class:`FeatureVector` 同时写入在线与离线通道，
  因此对同一实体的同一特征，在线通道与离线通道返回一致的特征值。
- 缺失默认（19.4）：请求的特征缺失时，使用默认值填充并**打标**（记录被默认的特征名），
  同时**触发离线特征回填**且**不中断当前请求**。
- 在线降级（19.5）：在线通道（Redis）不可用时，自动降级回退到离线通道读取特征。

为便于在无实时 Redis / 数据库的情况下测试，在线与离线后端均被抽象为协议
（:class:`OnlineFeatureBackend` / :class:`OfflineFeatureBackend`）。本模块内置纯内存实现
（:class:`InMemoryOnlineBackend` / :class:`InMemoryOfflineBackend`）作为默认与测试替身，
并提供 :class:`RedisOnlineBackend` 作为生产在线通道实现（延迟导入 ``redis``）。
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal, Protocol, runtime_checkable

from app.models.timeseries import FeatureVector

#: 缺失特征时使用的默认特征值（Requirements 19.4）。
DEFAULT_FEATURE_VALUE = 0.0

#: 未显式指定 ``feature_group`` 时使用的默认特征组名。
DEFAULT_FEATURE_GROUP = "default"


class FeatureStoreError(Exception):
    """特征存储错误基类。"""


class OnlineBackendUnavailable(FeatureStoreError):
    """在线通道（Redis）不可用错误。

    在线后端在连接 / 读写失败时抛出该错误，:class:`FeatureStore` 据此降级到离线通道。
    """


class FeatureNotFoundError(FeatureStoreError):
    """特征缺失且无法回填默认值错误。

    当既无任何已存特征、又未指定需要的特征名（``required_features``）以决定默认值时抛出。
    """


# --------------------------------------------------------------------------- #
# 后端抽象协议
# --------------------------------------------------------------------------- #
@runtime_checkable
class OnlineFeatureBackend(Protocol):
    """在线特征后端协议（低延迟，Redis 支撑）。"""

    def read(
        self, tenant_id: str, entity_id: str, feature_group: str
    ) -> dict[str, float] | None:  # pragma: no cover - 协议声明
        """读取在线特征；无对应条目返回 ``None``；通道不可用抛 :class:`OnlineBackendUnavailable`。"""
        ...

    def write(self, fv: FeatureVector) -> None:  # pragma: no cover - 协议声明
        """写入在线特征；通道不可用抛 :class:`OnlineBackendUnavailable`。"""
        ...


@runtime_checkable
class OfflineFeatureBackend(Protocol):
    """离线特征后端协议（持久化真值来源，数据库支撑）。"""

    def read(
        self, tenant_id: str, entity_id: str, feature_group: str
    ) -> FeatureVector | None:  # pragma: no cover - 协议声明
        """读取离线特征向量；无对应条目返回 ``None``。"""
        ...

    def write(self, fv: FeatureVector) -> None:  # pragma: no cover - 协议声明
        """写入离线特征向量。"""
        ...


# --------------------------------------------------------------------------- #
# 结果与回填请求
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class FeatureFetchResult:
    """特征读取结果，携带被默认（打标）的特征名与数据来源通道。"""

    features: dict[str, float]
    #: 因缺失而被默认值填充并打标的特征名（Requirements 19.4）。
    defaulted: tuple[str, ...] = ()
    #: 实际取数通道：``online`` 或 ``offline``（降级时为 ``offline``）。
    source: Literal["online", "offline"] = "offline"

    @property
    def is_complete(self) -> bool:
        """是否所有请求特征均命中真实值（无任何默认打标）。"""
        return not self.defaulted


@dataclass(frozen=True)
class BackfillRequest:
    """离线特征回填请求，在特征缺失被默认时生成（Requirements 19.4）。"""

    tenant_id: str
    entity_id: str
    feature_group: str
    missing_features: tuple[str, ...]
    requested_at: datetime


# --------------------------------------------------------------------------- #
# 内存后端实现（默认 / 测试替身）
# --------------------------------------------------------------------------- #
def _key(tenant_id: str, entity_id: str, feature_group: str) -> tuple[str, str, str]:
    return (tenant_id, entity_id, feature_group)


class InMemoryOfflineBackend:
    """纯内存离线后端：以字典持久化 :class:`FeatureVector`，用作默认真值来源与测试替身。"""

    def __init__(self) -> None:
        self._store: dict[tuple[str, str, str], FeatureVector] = {}

    def read(
        self, tenant_id: str, entity_id: str, feature_group: str
    ) -> FeatureVector | None:
        fv = self._store.get(_key(tenant_id, entity_id, feature_group))
        # 返回拷贝，避免调用方修改内部状态。
        return fv.model_copy(deep=True) if fv is not None else None

    def write(self, fv: FeatureVector) -> None:
        self._store[_key(fv.tenant_id, fv.entity_id, fv.feature_group)] = fv.model_copy(
            deep=True
        )


class InMemoryOnlineBackend:
    """纯内存在线后端：以字典模拟 Redis 在线通道，用作默认与测试替身。

    通过 :meth:`set_available` 可模拟 Redis 不可用，以验证降级路径（Requirements 19.5）。
    """

    def __init__(self, *, available: bool = True) -> None:
        self._store: dict[tuple[str, str, str], dict[str, float]] = {}
        self._available = available

    def set_available(self, available: bool) -> None:
        """模拟在线通道可用性切换，用于测试降级。"""
        self._available = available

    def _ensure_available(self) -> None:
        if not self._available:
            raise OnlineBackendUnavailable("在线特征通道（Redis）不可用")

    def read(
        self, tenant_id: str, entity_id: str, feature_group: str
    ) -> dict[str, float] | None:
        self._ensure_available()
        features = self._store.get(_key(tenant_id, entity_id, feature_group))
        return dict(features) if features is not None else None

    def write(self, fv: FeatureVector) -> None:
        self._ensure_available()
        self._store[_key(fv.tenant_id, fv.entity_id, fv.feature_group)] = dict(fv.features)


class RedisOnlineBackend:
    """基于 Redis 的在线特征后端，支撑低延迟（目标 <100ms）在线读写。

    特征以 JSON 存储于键 ``feat:{tenant_id}:{entity_id}:{feature_group}``。
    任一 Redis 连接 / 通信异常都会被转换为 :class:`OnlineBackendUnavailable`，
    以便 :class:`FeatureStore` 触发降级（Requirements 19.5）。

    ``redis`` 依赖延迟导入，保证在无 Redis 环境下本模块仍可正常导入与测试。
    """

    def __init__(self, client: object) -> None:
        #: 期望为 ``redis.Redis`` 实例（鸭子类型：需支持 ``get`` / ``set``）。
        self._client = client

    @classmethod
    def from_url(cls, url: str) -> RedisOnlineBackend:
        """由连接串创建后端（延迟导入 ``redis``）。"""
        try:
            import redis  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - 依赖缺失路径
            raise OnlineBackendUnavailable("未安装 redis 依赖") from exc
        return cls(redis.Redis.from_url(url, decode_responses=True))

    @staticmethod
    def _redis_key(tenant_id: str, entity_id: str, feature_group: str) -> str:
        return f"feat:{tenant_id}:{entity_id}:{feature_group}"

    def read(
        self, tenant_id: str, entity_id: str, feature_group: str
    ) -> dict[str, float] | None:
        import json

        key = self._redis_key(tenant_id, entity_id, feature_group)
        try:
            raw = self._client.get(key)  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001 - 归一化为通道不可用
            raise OnlineBackendUnavailable("Redis 在线通道读取失败") from exc
        if raw is None:
            return None
        data = json.loads(raw)
        return {str(k): float(v) for k, v in data.items()}

    def write(self, fv: FeatureVector) -> None:
        import json

        key = self._redis_key(fv.tenant_id, fv.entity_id, fv.feature_group)
        try:
            self._client.set(key, json.dumps(fv.features))  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001 - 归一化为通道不可用
            raise OnlineBackendUnavailable("Redis 在线通道写入失败") from exc


# 触发离线回填的回调签名：接收一个 :class:`BackfillRequest`。
BackfillHandler = Callable[[BackfillRequest], None]


# --------------------------------------------------------------------------- #
# Feature Store
# --------------------------------------------------------------------------- #
class FeatureStore:
    """统一特征存储：为 LTV / churn / demand 模型提供在线 / 离线读写接口。

    Args:
        offline: 离线后端（真值来源）。缺省使用内存实现。
        online: 在线后端（低延迟）。缺省使用内存实现；传 ``None`` 表示仅离线。
        backfill_handler: 缺失特征被默认时触发的离线回填回调；缺省将请求追加到
            内部队列（可经 :attr:`backfill_queue` 观察）。
        default_value: 缺失特征的默认填充值（Requirements 19.4）。
    """

    def __init__(
        self,
        offline: OfflineFeatureBackend | None = None,
        online: OnlineFeatureBackend | None = None,
        *,
        backfill_handler: BackfillHandler | None = None,
        default_value: float = DEFAULT_FEATURE_VALUE,
    ) -> None:
        self._offline: OfflineFeatureBackend = offline or InMemoryOfflineBackend()
        # 显式区分“未传（用内存默认）”与“显式传 None（仅离线）”。
        self._online: OnlineFeatureBackend | None
        if online is None and offline is None:
            self._online = InMemoryOnlineBackend()
        else:
            self._online = online
        self._default_value = default_value
        self._backfill_queue: list[BackfillRequest] = []
        self._backfill_handler = backfill_handler or self._backfill_queue.append

    @property
    def backfill_queue(self) -> list[BackfillRequest]:
        """默认回填处理器累积的回填请求（用于观测 / 测试）。"""
        return self._backfill_queue

    # ---- 写入 ---------------------------------------------------------- #
    def write(self, fv: FeatureVector) -> None:
        """写入特征向量到离线与在线两条通道（Requirements 19.1 / 19.3）。

        离线通道为真值来源，必须成功；在线通道写入失败（Redis 不可用）不影响写入语义，
        仅记录为在线通道暂不可用（后续读取将自动降级到离线）。
        """
        self._offline.write(fv)
        if self._online is not None:
            try:
                self._online.write(fv)
            except OnlineBackendUnavailable:
                # 在线通道不可用不阻断写入；离线为真值来源。
                pass

    # ---- 读取 ---------------------------------------------------------- #
    def get(
        self,
        entity_id: str,
        feature_group: str,
        *,
        tenant_id: str,
        required_features: Iterable[str] | None = None,
        defaults: Mapping[str, float] | None = None,
    ) -> FeatureVector:
        """从离线通道读取特征向量（Requirements 19.1）。

        缺失 ``required_features`` 中的特征时使用默认值填充并打标、触发离线回填、
        不中断请求（Requirements 19.4）。

        Raises:
            FeatureNotFoundError: 无任何已存特征且未指定 ``required_features``。
        """
        result = self.fetch_offline(
            entity_id,
            feature_group,
            tenant_id=tenant_id,
            required_features=required_features,
            defaults=defaults,
        )
        return FeatureVector(
            entity_id=entity_id,
            tenant_id=tenant_id,
            feature_group=feature_group,
            features=result.features,
            computed_at=datetime.now(tz=timezone.utc),
        )

    def get_online(
        self,
        entity_id: str,
        feature_group: str = DEFAULT_FEATURE_GROUP,
        *,
        tenant_id: str,
        required_features: Iterable[str] | None = None,
        defaults: Mapping[str, float] | None = None,
    ) -> dict[str, float]:
        """从在线通道（Redis）读取低延迟特征，返回特征字典（Requirements 19.2）。

        在线通道不可用时自动降级到离线通道（Requirements 19.5）；缺失特征使用默认值
        填充并打标、触发离线回填（Requirements 19.4）。需要区分来源 / 打标信息时，
        请改用 :meth:`fetch_online`。
        """
        return self.fetch_online(
            entity_id,
            feature_group,
            tenant_id=tenant_id,
            required_features=required_features,
            defaults=defaults,
        ).features

    # ---- 富结果读取（携带来源 / 打标） --------------------------------- #
    def fetch_offline(
        self,
        entity_id: str,
        feature_group: str,
        *,
        tenant_id: str,
        required_features: Iterable[str] | None = None,
        defaults: Mapping[str, float] | None = None,
    ) -> FeatureFetchResult:
        """离线读取并返回携带来源 / 打标信息的结果。"""
        fv = self._offline.read(tenant_id, entity_id, feature_group)
        base = dict(fv.features) if fv is not None else None
        return self._assemble(
            base=base,
            source="offline",
            tenant_id=tenant_id,
            entity_id=entity_id,
            feature_group=feature_group,
            required_features=required_features,
            defaults=defaults,
        )

    def fetch_online(
        self,
        entity_id: str,
        feature_group: str = DEFAULT_FEATURE_GROUP,
        *,
        tenant_id: str,
        required_features: Iterable[str] | None = None,
        defaults: Mapping[str, float] | None = None,
    ) -> FeatureFetchResult:
        """在线读取并返回结果；Redis 不可用或无在线后端时降级到离线（Requirements 19.5）。"""
        base: dict[str, float] | None = None
        source: Literal["online", "offline"] = "online"

        if self._online is None:
            source = "offline"
        else:
            try:
                base = self._online.read(tenant_id, entity_id, feature_group)
            except OnlineBackendUnavailable:
                # 在线通道不可用 → 降级到离线通道。
                source = "offline"

        if source == "offline" or base is None:
            # 在线未命中或已降级：回退离线读取以保证一致性并补齐真值。
            offline_fv = self._offline.read(tenant_id, entity_id, feature_group)
            if offline_fv is not None:
                base = dict(offline_fv.features)
                if source != "offline":
                    # 在线无条目但离线有：以离线值为准并标记来源为离线。
                    source = "offline"
            elif source == "online":
                # 在线可用但无条目、离线亦无：保持在线来源，走默认填充。
                base = None

        return self._assemble(
            base=base,
            source=source,
            tenant_id=tenant_id,
            entity_id=entity_id,
            feature_group=feature_group,
            required_features=required_features,
            defaults=defaults,
        )

    # ---- 内部：组装结果 + 默认填充 + 触发回填 -------------------------- #
    def _assemble(
        self,
        *,
        base: dict[str, float] | None,
        source: Literal["online", "offline"],
        tenant_id: str,
        entity_id: str,
        feature_group: str,
        required_features: Iterable[str] | None,
        defaults: Mapping[str, float] | None,
    ) -> FeatureFetchResult:
        required = list(required_features) if required_features is not None else []

        if base is None and not required:
            # 无任何已存特征、且未声明所需特征 → 无从决定默认值。
            raise FeatureNotFoundError(
                f"实体 {entity_id} 在特征组 {feature_group} 无任何特征，且未指定 required_features"
            )

        features: dict[str, float] = dict(base) if base else {}
        defaulted: list[str] = []
        for name in required:
            if name not in features:
                fallback = self._default_value
                if defaults is not None and name in defaults:
                    fallback = defaults[name]
                features[name] = fallback
                defaulted.append(name)

        if defaulted:
            # 缺失特征：打标 + 触发离线回填，且不中断当前请求（Requirements 19.4）。
            self._trigger_backfill(
                tenant_id=tenant_id,
                entity_id=entity_id,
                feature_group=feature_group,
                missing=tuple(defaulted),
            )

        return FeatureFetchResult(
            features=features, defaulted=tuple(defaulted), source=source
        )

    def _trigger_backfill(
        self,
        *,
        tenant_id: str,
        entity_id: str,
        feature_group: str,
        missing: tuple[str, ...],
    ) -> None:
        request = BackfillRequest(
            tenant_id=tenant_id,
            entity_id=entity_id,
            feature_group=feature_group,
            missing_features=missing,
            requested_at=datetime.now(tz=timezone.utc),
        )
        self._backfill_handler(request)
