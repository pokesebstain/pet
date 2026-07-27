"""pytest 与 hypothesis 测试脚手架的公共 fixtures 与配置。"""

from __future__ import annotations

import os

import pytest
from hypothesis import HealthCheck, settings

from app.core.config import Environment, Settings, get_settings

# 注册 hypothesis 配置档：CI 使用更多样例，本地默认使用较快档位。
settings.register_profile(
    "ci",
    max_examples=200,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.register_profile("dev", max_examples=50)
settings.load_profile(os.getenv("HYPOTHESIS_PROFILE", "dev"))


@pytest.fixture()
def test_settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    """返回强制切换到 TEST 环境的配置实例。

    通过清理 `get_settings` 缓存并注入环境变量，验证按环境切换能力。
    """
    monkeypatch.setenv("PETOPS_ENVIRONMENT", Environment.TEST.value)
    get_settings.cache_clear()
    try:
        yield get_settings()
    finally:
        get_settings.cache_clear()
