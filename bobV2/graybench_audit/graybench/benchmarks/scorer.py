"""Result aggregation and comparison utilities."""

import json
from typing import Optional
from ..db import runs_db


def get_run_summary(run_id: str) -> Optional[dict]:
    """Get a formatted summary of a benchmark run."""
    run = runs_db.get_run(run_id)
    if not run:
        return None
    tasks = runs_db.get_tasks(run_id)
    config = json.loads(run["config_json"]) if run.get("config_json") else {}
    environment = json.loads(run["environment_json"]) if run.get("environment_json") else {}
    return {
        "run_id": run["run_id"],
        "benchmark": run["benchmark"],
        "model": f"{run['model_provider']}/{run['model_id']}",
        "route": run["route"],
        "status": run["status"],
        "score": run["score"],
        "passed": run["passed_tasks"],
        "failed": run["failed_tasks"],
        "total": run["total_tasks"],
        "cost_usd": run["total_cost_usd"],
        "tokens": run["total_tokens"],
        "duration_s": run["total_duration_s"],
        "created_at": run["created_at"],
        "config": config,
        "environment": environment,
        "tasks": tasks,
    }


def compare_runs(run_id_1: str, run_id_2: str) -> dict:
    """Compare two benchmark runs side by side."""
    s1 = get_run_summary(run_id_1)
    s2 = get_run_summary(run_id_2)
    if not s1 or not s2:
        return {"error": "One or both runs not found"}

    # Build task-level comparison
    tasks_1 = {t["task_id"]: t for t in s1["tasks"]}
    tasks_2 = {t["task_id"]: t for t in s2["tasks"]}
    all_task_ids = sorted(set(tasks_1.keys()) | set(tasks_2.keys()))

    task_comparison = []
    for tid in all_task_ids:
        t1 = tasks_1.get(tid, {})
        t2 = tasks_2.get(tid, {})
        task_comparison.append({
            "task_id": tid,
            "run_1_passed": t1.get("passed"),
            "run_1_score": t1.get("score"),
            "run_2_passed": t2.get("passed"),
            "run_2_score": t2.get("score"),
        })

    return {
        "run_1": {k: v for k, v in s1.items() if k != "tasks"},
        "run_2": {k: v for k, v in s2.items() if k != "tasks"},
        "task_comparison": task_comparison,
    }
