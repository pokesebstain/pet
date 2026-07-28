"""组合根接待预约接线测试（任务 26 / 27 落地）。

验证：注入 DB Engine 时，组合根装配 PostgreSQL 后端排期引擎并把真实接待预约 Agent
注册进专家映射（``reception`` 意图路由到它）；未注入 Engine 时保持内存模式、不注册。

不建立任何数据库连接：``build_db_scheduling_engine`` 仅包装 Engine 为提供者，构造期不连接，
因此可用哨兵对象代替真实 Engine。
"""

from __future__ import annotations

from app.api.composition import build_composition


def test_reception_registered_when_db_engine_provided() -> None:
    sentinel_engine = object()  # 构造期不会连接，哨兵即可。
    comp = build_composition(db_engine=sentinel_engine)

    assert comp.reception_agent is not None
    assert comp.reception_agent.name == "reception"
    assert "reception" in comp.experts
    assert comp.experts["reception"] is comp.reception_agent


def test_reception_absent_without_db_engine() -> None:
    comp = build_composition()

    assert comp.reception_agent is None
    assert "reception" not in comp.experts


def test_injected_reception_agent_takes_precedence() -> None:
    class _StubReception:
        name = "reception"

        def run(self, state):  # noqa: ANN001, D401
            return {}

    stub = _StubReception()
    comp = build_composition(reception_agent=stub)

    assert comp.reception_agent is stub
    assert comp.experts["reception"] is stub
