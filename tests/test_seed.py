"""单门店种子例程单元测试（``app.db.seed``）。

无需运行中的 PostgreSQL：种子使用 PostgreSQL 专有的 ``INSERT … ON CONFLICT`` 语义，
因此用**间谍连接**断言其在 ``tenant_session`` 内注入租户上下文并对营业时间 / 资源 /
（演示）客户 / 宠物发出了幂等插入；并验证未配置默认租户时 ``seed_from_settings`` 跳过。
"""

from __future__ import annotations

from sqlalchemy.dialects import postgresql

from app.core.config import Settings
from app.db.metadata import SESSION_TENANT_VARIABLE
from app.db.seed import (
    DEMO_CUSTOMER_ID,
    DEMO_PET_ID,
    seed_from_settings,
    seed_single_store,
)

TENANT = "store-001"


class _SpyResult:
    rowcount = 1

    def scalar_one(self) -> int:
        return 0

    def first(self):
        return None


class _SpyTxn:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _SpyConn:
    def __init__(self) -> None:
        self.statements: list = []
        self.params: list = []

    def begin(self):
        return _SpyTxn()

    def execute(self, statement, parameters=None):
        self.statements.append(statement)
        self.params.append(parameters)
        return _SpyResult()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _SpyEngine:
    def __init__(self) -> None:
        self.connection = _SpyConn()
        self.disposed = False

    def connect(self):
        return self.connection

    def dispose(self) -> None:
        self.disposed = True


def _render(statement) -> str:
    return str(statement.compile(dialect=postgresql.dialect()))


def test_seed_single_store_writes_hours_resources_and_demo() -> None:
    engine = _SpyEngine()

    counts = seed_single_store(
        engine, TENANT, seed_demo=True, demo_external_id="wm-tester"
    )

    # 幂等插入的计数（间谍 rowcount=1）：7 天营业时间 + 2 个资源 + 1 客户 + 1 宠物。
    assert counts == {
        "business_hours": 7,
        "resources": 2,
        "customers": 1,
        "pets": 1,
    }

    joined = "\n".join(_render(s) for s in engine.connection.statements)
    # 租户上下文注入。
    assert any(
        p and p.get("tenant_id") == TENANT and p.get("var_name") == SESSION_TENANT_VARIABLE
        for p in engine.connection.params
    )
    # 幂等语义 + 目标表。
    assert "INSERT INTO business_hours" in joined
    assert "INSERT INTO grooming_resources" in joined
    assert "INSERT INTO customers" in joined
    assert "INSERT INTO pets" in joined
    assert "ON CONFLICT" in joined
    # 演示标识内联在 INSERT 语句的绑定值中（渲染为字面量后可见）。
    rendered_literals = "\n".join(
        str(
            s.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )
        for s in engine.connection.statements
        if not hasattr(s, "text")  # 跳过 set_config 文本语句
    )
    assert DEMO_CUSTOMER_ID in rendered_literals
    assert DEMO_PET_ID in rendered_literals
    assert "wm-tester" in rendered_literals


def test_seed_single_store_base_only_skips_demo() -> None:
    engine = _SpyEngine()
    counts = seed_single_store(engine, TENANT)  # seed_demo=False
    assert counts["customers"] == 0
    assert counts["pets"] == 0
    assert counts["business_hours"] == 7
    assert counts["resources"] == 2


def test_seed_from_settings_skips_when_no_tenant_configured() -> None:
    engine = _SpyEngine()
    # 默认租户为空（无 PETOPS_DEFAULT_TENANT_ID、无企业微信 corp_id）。
    settings = Settings(default_tenant_id="")
    result = seed_from_settings(settings, engine=engine)
    assert result is None
    # 未配置租户：不触碰注入的 Engine。
    assert engine.connection.statements == []


def test_seed_from_settings_runs_for_configured_tenant() -> None:
    engine = _SpyEngine()
    settings = Settings(default_tenant_id="store-x")
    result = seed_from_settings(settings, engine=engine)
    assert result is not None
    assert result["business_hours"] == 7
    # 注入的 Engine 由调用方持有，不应被 dispose。
    assert engine.disposed is False
