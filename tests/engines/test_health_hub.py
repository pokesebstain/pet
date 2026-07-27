"""健康数据中台单元测试（任务 15.1 / Requirements 9.1, 9.2）。

覆盖：
- 校验通过 → 写入时序仓库 + 发布 ``health_data_ingested`` 事件（9.1）。
- 缺 ``tenant_id`` / 数值越界（体重 ≤ 0、活动时长 < 0、进食量 < 0）→ 拒绝写入、
  时序表保持不变、不发布事件、返回校验错误（9.2）。
- 5 秒预算：开启 ``enforce_deadline`` 且超时抛错。

依赖经内存假实现注入（:class:`InMemoryHealthMetricRepository` +
:class:`InMemoryStreamTransport`），无需实时 TimescaleDB / Redis。

异常趋势检测（``health_alert``）属任务 15.2，不在本文件范围。
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.engines.health import (
    HEALTH_DATA_INGESTED_EVENT,
    HealthDataHub,
    HealthDataIngestTimeoutError,
    HealthDataValidationError,
    InMemoryHealthMetricRepository,
)
from app.events.bus import DEFAULT_STREAM, ConsumerGroup, EventBus
from app.events.transport import InMemoryStreamTransport
from app.models import DomainEvent, HealthMetric

TENANT = "tenant-1"
PET = "pet-1"


def _hub_and_deps(**kwargs) -> tuple[HealthDataHub, InMemoryHealthMetricRepository, InMemoryStreamTransport]:
    repo = InMemoryHealthMetricRepository()
    transport = InMemoryStreamTransport()
    bus = EventBus(transport)
    hub = HealthDataHub(repo, bus, **kwargs)
    return hub, repo, transport


def _valid_metric_mapping() -> dict:
    return {
        "tenant_id": TENANT,
        "ts": datetime(2024, 1, 1, tzinfo=timezone.utc),
        "weight_kg": 12.5,
        "activity_minutes": 45.0,
        "food_intake_g": 300.0,
    }


def _captured_events(transport: InMemoryStreamTransport) -> list[DomainEvent]:
    """读取审计日志消费者组收到的全部领域事件。"""
    messages = transport.read_new(DEFAULT_STREAM, ConsumerGroup.AUDIT_LOG.value, "t", 100)
    return [EventBus._deserialize(fields) for _mid, fields in messages]


# --- 9.1 校验通过：写入 + 发布事件 ----------------------------------------


def test_valid_ingest_writes_and_publishes() -> None:
    hub, repo, transport = _hub_and_deps()

    event = hub.ingest(PET, _valid_metric_mapping())

    # 写入时序仓库。
    assert len(repo) == 1
    written = repo.rows[0]
    assert written.pet_id == PET
    assert written.tenant_id == TENANT
    assert written.weight_kg == 12.5

    # 返回并发布 health_data_ingested 事件。
    assert isinstance(event, DomainEvent)
    assert event.event_type == HEALTH_DATA_INGESTED_EVENT
    assert event.tenant_id == TENANT

    published = _captured_events(transport)
    assert len(published) == 1
    assert published[0].event_type == HEALTH_DATA_INGESTED_EVENT
    assert published[0].payload["pet_id"] == PET
    assert published[0].payload["weight_kg"] == 12.5


def test_valid_ingest_accepts_health_metric_model() -> None:
    hub, repo, transport = _hub_and_deps()
    metric = HealthMetric(pet_id=PET, **_valid_metric_mapping())

    event = hub.ingest(PET, metric)

    assert len(repo) == 1
    assert event.event_type == HEALTH_DATA_INGESTED_EVENT
    assert len(_captured_events(transport)) == 1


def test_pet_id_defaults_from_argument_when_mapping_omits_it() -> None:
    hub, repo, _ = _hub_and_deps()
    hub.ingest(PET, _valid_metric_mapping())  # mapping has no pet_id
    assert repo.rows[0].pet_id == PET


# --- 9.2 校验失败：拒绝写入、不发事件、返回错误 --------------------------


@pytest.mark.parametrize(
    "mutation",
    [
        {"tenant_id": ""},        # 缺失 / 空 tenant_id
        {"tenant_id": "   "},     # 纯空白 tenant_id
        {"weight_kg": 0.0},       # 体重 ≤ 0
        {"weight_kg": -1.0},      # 体重为负
        {"activity_minutes": -5.0},  # 活动时长为负
        {"food_intake_g": -1.0},  # 进食量为负
    ],
)
def test_invalid_data_rejected_without_side_effects(mutation: dict) -> None:
    hub, repo, transport = _hub_and_deps()
    payload = _valid_metric_mapping()
    payload.update(mutation)

    with pytest.raises(HealthDataValidationError):
        hub.ingest(PET, payload)

    # 时序表保持不变，且未发布任何事件。
    assert len(repo) == 0
    assert transport.stream_length(DEFAULT_STREAM) == 0
    assert _captured_events(transport) == []


def test_non_mapping_metrics_rejected() -> None:
    hub, repo, transport = _hub_and_deps()
    with pytest.raises(HealthDataValidationError):
        hub.ingest(PET, "not-a-mapping")  # type: ignore[arg-type]
    assert len(repo) == 0
    assert transport.stream_length(DEFAULT_STREAM) == 0


def test_pet_id_mismatch_with_model_rejected() -> None:
    hub, repo, transport = _hub_and_deps()
    metric = HealthMetric(pet_id="other-pet", **_valid_metric_mapping())
    with pytest.raises(HealthDataValidationError):
        hub.ingest(PET, metric)
    assert len(repo) == 0
    assert transport.stream_length(DEFAULT_STREAM) == 0


# --- 9.1 时间预算 ----------------------------------------------------------


def test_deadline_exceeded_raises_when_enforced() -> None:
    # clock 每次调用推进时间，使 elapsed 判定不受影响；这里用极小预算 + 真实耗时。
    hub, _, _ = _hub_and_deps(enforce_deadline=True, deadline_seconds=-1.0)
    with pytest.raises(HealthDataIngestTimeoutError):
        hub.ingest(PET, _valid_metric_mapping())


def test_deadline_not_enforced_by_default() -> None:
    hub, repo, _ = _hub_and_deps(deadline_seconds=-1.0)  # enforce_deadline defaults False
    event = hub.ingest(PET, _valid_metric_mapping())
    assert event.event_type == HEALTH_DATA_INGESTED_EVENT
    assert len(repo) == 1
