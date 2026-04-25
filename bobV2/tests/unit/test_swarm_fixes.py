from __future__ import annotations

import pytest

from bob.config.schema import BobConfig
from bob.swarm.apply_bundle import apply_swarm_bundle
from bob.swarm.models import RiskLevel, SwarmPlan, SwarmTask
from bob.swarm.orchestrator import SwarmOrchestrator
from bob.swarm.workspace import IsolatedWorkspace


def test_swarm_bundle_applies_with_hash_check(tmp_path) -> None:
    real = tmp_path / "project"
    real.mkdir()
    source = real / "app.py"
    source.write_text("print('old')\n", encoding="utf-8")

    ws = IsolatedWorkspace(real, ["app.py"])
    try:
        (ws.workspace_dir / "app.py").write_text("print('new')\n", encoding="utf-8")
        bundle, changed = ws.generate_change_bundle(agent_id="a1", role="implementer")
        payload = IsolatedWorkspace.encode_bundles([bundle])

        result = apply_swarm_bundle(payload, real)

        assert changed == ["app.py"]
        assert result["applied"] == 1
        assert result["skipped"] == 0
        assert source.read_text(encoding="utf-8") == "print('new')\n"
    finally:
        ws.cleanup()


def test_swarm_bundle_rejects_conflicted_file(tmp_path) -> None:
    real = tmp_path / "project"
    real.mkdir()
    source = real / "app.py"
    source.write_text("print('old')\n", encoding="utf-8")

    ws = IsolatedWorkspace(real, ["app.py"])
    try:
        (ws.workspace_dir / "app.py").write_text("print('new')\n", encoding="utf-8")
        bundle, _ = ws.generate_change_bundle(agent_id="a1", role="implementer")
        payload = IsolatedWorkspace.encode_bundles([bundle])
        source.write_text("print('changed elsewhere')\n", encoding="utf-8")

        result = apply_swarm_bundle(payload, real)

        assert result["applied"] == 0
        assert result["skipped"] == 1
        assert "conflicted" in result["errors"][0]
        assert source.read_text(encoding="utf-8") == "print('changed elsewhere')\n"
    finally:
        ws.cleanup()


def test_swarm_plan_validation_rejects_cycles() -> None:
    plan = SwarmPlan(
        run_id="r1",
        original_task="x",
        total_agents=2,
        tasks=[
            SwarmTask(id="a", role="implementer", task="a", deps=["b"]),
            SwarmTask(id="b", role="reviewer", task="b", deps=["a"]),
        ],
    )

    with pytest.raises(ValueError, match="dependency cycle"):
        SwarmOrchestrator._validate_plan(plan)


def test_swarm_plan_validation_rejects_readonly_modifications() -> None:
    plan = SwarmPlan(
        run_id="r1",
        original_task="x",
        total_agents=1,
        tasks=[
            SwarmTask(
                id="review",
                role="reviewer",
                task="review",
                risk_level=RiskLevel.LOW,
                files_to_modify=["app.py"],
            ),
        ],
    )

    with pytest.raises(ValueError, match="Read-only"):
        SwarmOrchestrator._validate_plan(plan)


def test_fallback_plan_disables_execution_for_broad_task_by_default() -> None:
    session = type("DummySession", (), {"config": BobConfig(), "bob_home": None})()
    orch = SwarmOrchestrator(session)

    plan = orch._fallback_plan(
        "analyze the entire codebase and refactor all synchronous HTTP calls",
        "r1",
        "findings",
        "planner returned empty output",
        attempts=2,
    )

    assert plan.planner_status == "fallback"
    assert plan.executable is False
    assert "Planner failed after 2 attempt" in plan.planner_error


def test_fallback_plan_allows_execution_for_simple_task() -> None:
    session = type("DummySession", (), {"config": BobConfig(), "bob_home": None})()
    orch = SwarmOrchestrator(session)

    plan = orch._fallback_plan(
        "rename one variable in app.py",
        "r1",
        "findings",
        "planner returned empty output",
        attempts=1,
    )

    assert plan.planner_status == "fallback"
    assert plan.executable is True
