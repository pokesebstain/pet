"""占位 smoke 测试：验证项目骨架、包导入与配置加载可用。"""

from __future__ import annotations

import importlib

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.core.config import Environment, Settings, get_settings

# 项目应存在的子包（每个含 __init__.py）。
_SUBPACKAGES = [
    "app",
    "app.core",
    "app.models",
    "app.tools",
    "app.agents",
    "app.engines",
    "app.events",
    "app.rag",
    "app.vision",
    "app.observability",
]


@pytest.mark.parametrize("module_name", _SUBPACKAGES)
def test_subpackages_importable(module_name: str) -> None:
    """每个子包都应可被导入。"""
    module = importlib.import_module(module_name)
    assert module is not None


def test_settings_defaults_and_dsn() -> None:
    """默认配置应可实例化，且各外部依赖连接串可构造。

    显式传入 ``environment``：本机 / CI 的 ``.env`` 可能配置了
    ``PETOPS_ENVIRONMENT=prod``（部署态），该值会被 ``Settings()`` 按预期加载，
    与本测试要验证的"字段默认值/类型"这一独立事实无关，因此这里显式指定而不依赖
    ``.env`` 恰好为空。
    """
    settings = Settings(environment=Environment.DEV)
    assert settings.environment == Environment.DEV
    assert settings.database.dsn.startswith("postgresql+psycopg://")
    assert settings.redis.url.startswith("redis://")
    assert settings.llm.timeout_seconds > 0
    assert settings.vision.max_image_mb == 10


def test_settings_environment_switch(test_settings: Settings) -> None:
    """test_settings fixture 应将环境切换到 TEST。"""
    assert test_settings.environment == Environment.TEST
    assert not test_settings.is_production


def test_get_settings_is_cached() -> None:
    """get_settings 应返回进程内缓存单例。"""
    get_settings.cache_clear()
    assert get_settings() is get_settings()


@pytest.mark.property
@given(port=st.integers(min_value=1, max_value=65535))
def test_database_port_accepts_valid_range(port: int) -> None:
    """属性占位：合法端口范围内构造配置应成功且回填一致。"""
    settings = Settings(database={"port": port})
    assert settings.database.port == port
