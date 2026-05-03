from __future__ import annotations

from pathlib import Path

import pytest

from bob.analytics.db import AnalyticsDB
from bob.analytics.report import build_session_report


@pytest.mark.asyncio
async def test_build_session_report_aggregates_db_and_rollout(tmp_path: Path) -> None:
    db = AnalyticsDB(tmp_path / "analytics.db")
    await db.setup()
    await db.record_turn(
        session_id="s1",
        turn_id="t1",
        model="gpt-4o-mini",
        input_tokens=120,
        output_tokens=30,
        total_tokens=150,
        cached_input_tokens=20,
        total_cost_usd=0.0123,
        latency_ms=950,
        changed_files=["a.py", "b.py"],
    )
    await db.record_turn(
        session_id="s1",
        turn_id="t2",
        model="gpt-4o-mini",
        input_tokens=200,
        output_tokens=80,
        total_tokens=280,
        cached_input_tokens=50,
        total_cost_usd=0.0345,
        latency_ms=1200,
        changed_files=["b.py", "c.py"],
    )

    rollout_path = tmp_path / "session.jsonl"
    rollout_path.write_text(
        "\n".join(
            [
                '{"type":"session_meta","session_id":"s1"}',
                '{"type":"tool_call_started","data":{"tool_call_id":"tc1","tool_name":"read_file","tool_input":{}}}',
                '{"type":"tool_call_completed","data":{"tool_call_id":"tc1","tool_name":"read_file","duration_ms":15,"output":"ok"}}',
                '{"type":"tool_call_started","data":{"tool_call_id":"tc2","tool_name":"shell","tool_input":{}}}',
                '{"type":"tool_call_completed","data":{"tool_call_id":"tc2","tool_name":"shell","duration_ms":40,"output":"Error: boom","error":"Error: boom"}}',
                '{"type":"exec_started","data":{"tool_call_id":"tc2","command":["git","status"]}}',
                '{"type":"context_compaction","data":{"reason":"manual","token_before":1000,"token_after":700,"success":true}}',
                '{"type":"exec_approval_requested","data":{"tool_call_id":"tc2"}}',
                '{"type":"exec_approval_resolved","data":{"tool_call_id":"tc2","decision":"approved"}}',
                '{"type":"network_approval_requested","data":{"request_id":"n1","domain":"example.com"}}',
                '{"type":"token_budget","data":{"used_tokens":430,"budget_tokens":2000,"fraction_used":0.215}}',
            ]
        ),
        encoding="utf-8",
    )

    report = await build_session_report(
        session_id="s1",
        analytics_db=db,
        rollout_path=rollout_path,
        model="gpt-4o-mini",
        cwd=str(tmp_path),
    )

    assert report.turns == 2
    assert report.input_tokens == 320
    assert report.output_tokens == 110
    assert report.total_tokens == 430
    assert report.cached_input_tokens == 70
    assert report.tool_calls == 2
    assert report.tool_failures == 1
    assert report.shell_commands == 1
    assert report.compaction.successful == 1
    assert report.compaction.reduction_tokens == 300
    assert report.approvals.exec_requested == 1
    assert report.approvals.exec_approved == 1
    assert report.approvals.network_requested == 1
    assert report.unique_changed_files == 3
    assert report.budget.peak_used_tokens == 430
    assert report.recent_turns[0].turn_id == "t2"
    assert report.tool_breakdown[0].name == "shell"
    assert report.tool_breakdown[1].name == "read_file"
