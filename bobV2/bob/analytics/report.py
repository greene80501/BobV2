from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional

from bob.analytics.db import AnalyticsDB
from bob.rollout.recorder import load_rollout


@dataclass
class RecentTurnSummary:
    turn_id: Optional[str]
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cached_input_tokens: int
    total_cost_usd: float
    latency_ms: Optional[int]
    changed_files: list[str]
    timestamp: str


@dataclass
class ModelBreakdownEntry:
    model: str
    turns: int
    total_tokens: int
    total_cost_usd: float


@dataclass
class ToolBreakdownEntry:
    name: str
    count: int = 0
    failures: int = 0
    total_duration_ms: int = 0
    max_duration_ms: int = 0

    @property
    def avg_duration_ms(self) -> float:
        if self.count <= 0:
            return 0.0
        return self.total_duration_ms / self.count


@dataclass
class CompactionSummary:
    total: int = 0
    successful: int = 0
    failed: int = 0
    reduction_tokens: int = 0
    average_reduction_pct: Optional[float] = None
    best_reduction_pct: Optional[float] = None
    last_summary: Optional[str] = None
    reasons: dict[str, int] | None = None


@dataclass
class ApprovalSummary:
    exec_requested: int = 0
    exec_approved: int = 0
    exec_denied: int = 0
    exec_aborted: int = 0
    network_requested: int = 0


@dataclass
class BudgetSummary:
    peak_fraction_used: Optional[float] = None
    peak_used_tokens: int = 0
    peak_budget_tokens: int = 0


@dataclass
class AnalyticsReport:
    session_id: str
    model: Optional[str]
    cwd: Optional[str]
    rollout_path: Optional[str]
    turns: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cached_input_tokens: int
    total_cost_usd: float
    avg_latency_ms: Optional[float]
    avg_tokens_per_turn: float
    max_turn_tokens: int
    max_turn_latency_ms: int
    unique_changed_files: int
    recent_turns: list[RecentTurnSummary]
    model_breakdown: list[ModelBreakdownEntry]
    tool_calls: int
    tool_failures: int
    unique_tools: int
    avg_tool_duration_ms: Optional[float]
    shell_commands: int
    agent_spawns: int
    agent_completions: int
    tool_breakdown: list[ToolBreakdownEntry]
    compaction: CompactionSummary
    approvals: ApprovalSummary
    budget: BudgetSummary

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


async def build_session_report(
    *,
    session_id: str,
    analytics_db: AnalyticsDB,
    rollout_path: Path | None,
    model: Optional[str] = None,
    cwd: Optional[str] = None,
) -> AnalyticsReport:
    totals = await analytics_db.session_totals(session_id)
    turn_rows = await analytics_db.turn_history(session_id)
    model_rows = await analytics_db.model_breakdown(session_id)

    recent_turns = [_turn_row_to_summary(row) for row in turn_rows[:5]]
    max_turn_tokens = max((int(row.get("total_tokens") or 0) for row in turn_rows), default=0)
    max_turn_latency_ms = max((int(row.get("latency_ms") or 0) for row in turn_rows), default=0)

    changed_files: set[str] = set()
    for row in turn_rows:
        for path in _parse_changed_files(row.get("changed_files")):
            changed_files.add(path)

    rollout_records = await load_rollout(rollout_path) if rollout_path else []
    rollout_metrics = _aggregate_rollout_metrics(rollout_records)

    if model is None and recent_turns:
        model = recent_turns[0].model

    turns = int(totals.get("turns", 0) or 0)
    total_tokens = int(totals.get("total_tokens", 0) or 0)
    total_tool_duration = sum(entry.total_duration_ms for entry in rollout_metrics["tool_breakdown"])
    tool_calls = int(rollout_metrics["tool_calls"])
    avg_tool_duration_ms = (total_tool_duration / tool_calls) if tool_calls > 0 else None

    return AnalyticsReport(
        session_id=session_id,
        model=model,
        cwd=cwd,
        rollout_path=str(rollout_path) if rollout_path else None,
        turns=turns,
        input_tokens=int(totals.get("input_tokens", 0) or 0),
        output_tokens=int(totals.get("output_tokens", 0) or 0),
        total_tokens=total_tokens,
        cached_input_tokens=int(totals.get("cached_input_tokens", 0) or 0),
        total_cost_usd=float(totals.get("total_cost_usd", 0.0) or 0.0),
        avg_latency_ms=totals.get("avg_latency_ms"),
        avg_tokens_per_turn=(total_tokens / turns) if turns > 0 else 0.0,
        max_turn_tokens=max_turn_tokens,
        max_turn_latency_ms=max_turn_latency_ms,
        unique_changed_files=len(changed_files),
        recent_turns=recent_turns,
        model_breakdown=[
            ModelBreakdownEntry(
                model=str(row.get("model") or "unknown"),
                turns=int(row.get("turns") or 0),
                total_tokens=int(row.get("total_tokens") or 0),
                total_cost_usd=float(row.get("total_cost_usd") or 0.0),
            )
            for row in model_rows
        ],
        tool_calls=tool_calls,
        tool_failures=int(rollout_metrics["tool_failures"]),
        unique_tools=len(rollout_metrics["tool_breakdown"]),
        avg_tool_duration_ms=avg_tool_duration_ms,
        shell_commands=int(rollout_metrics["shell_commands"]),
        agent_spawns=int(rollout_metrics["agent_spawns"]),
        agent_completions=int(rollout_metrics["agent_completions"]),
        tool_breakdown=rollout_metrics["tool_breakdown"],
        compaction=rollout_metrics["compaction"],
        approvals=rollout_metrics["approvals"],
        budget=rollout_metrics["budget"],
    )


def _turn_row_to_summary(row: dict[str, Any]) -> RecentTurnSummary:
    return RecentTurnSummary(
        turn_id=row.get("turn_id"),
        model=str(row.get("model") or "unknown"),
        input_tokens=int(row.get("input_tokens") or 0),
        output_tokens=int(row.get("output_tokens") or 0),
        total_tokens=int(row.get("total_tokens") or 0),
        cached_input_tokens=int(row.get("cached_input_tokens") or 0),
        total_cost_usd=float(row.get("total_cost_usd") or 0.0),
        latency_ms=int(row["latency_ms"]) if row.get("latency_ms") is not None else None,
        changed_files=_parse_changed_files(row.get("changed_files")),
        timestamp=str(row.get("timestamp") or ""),
    )


def _parse_changed_files(raw: Any) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(item) for item in raw]
    if isinstance(raw, str):
        try:
            loaded = json.loads(raw)
        except json.JSONDecodeError:
            return []
        if isinstance(loaded, list):
            return [str(item) for item in loaded]
    return []


def _aggregate_rollout_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    tool_entries: dict[str, ToolBreakdownEntry] = {}
    counted_tool_calls: set[str] = set()
    tool_failures = 0
    shell_commands = 0
    agent_spawns = 0
    agent_completions = 0
    reason_counts: dict[str, int] = defaultdict(int)
    compaction_total = 0
    compaction_success = 0
    compaction_failure = 0
    compaction_reduction_tokens = 0
    compaction_reduction_pcts: list[float] = []
    last_compaction_summary: Optional[str] = None
    exec_requested = 0
    exec_approved = 0
    exec_denied = 0
    exec_aborted = 0
    network_requested = 0
    peak_fraction_used: Optional[float] = None
    peak_used_tokens = 0
    peak_budget_tokens = 0

    for record in records:
        rec_type = str(record.get("type") or "")
        data = record.get("data")
        payload = data if isinstance(data, dict) else record

        if rec_type == "tool_call_started":
            call_id = str(payload.get("tool_call_id") or "")
            tool_name = str(payload.get("tool_name") or "unknown")
            if call_id not in counted_tool_calls:
                counted_tool_calls.add(call_id)
                entry = tool_entries.setdefault(tool_name, ToolBreakdownEntry(name=tool_name))
                entry.count += 1

        elif rec_type == "tool_call_completed":
            call_id = str(payload.get("tool_call_id") or "")
            tool_name = str(payload.get("tool_name") or "unknown")
            entry = tool_entries.setdefault(tool_name, ToolBreakdownEntry(name=tool_name))
            if call_id and call_id not in counted_tool_calls:
                counted_tool_calls.add(call_id)
                entry.count += 1
            duration_ms = int(payload.get("duration_ms") or 0)
            entry.total_duration_ms += duration_ms
            entry.max_duration_ms = max(entry.max_duration_ms, duration_ms)
            output = payload.get("output")
            failed = bool(payload.get("error")) or (
                isinstance(output, str) and output.startswith("Error:")
            )
            if failed:
                entry.failures += 1
                tool_failures += 1

        elif rec_type == "exec_started":
            shell_commands += 1

        elif rec_type == "agent_spawned":
            agent_spawns += 1

        elif rec_type == "agent_completed":
            agent_completions += 1

        elif rec_type == "context_compaction":
            compaction_total += 1
            reason = str(payload.get("reason") or "unknown")
            reason_counts[reason] += 1
            before = int(payload.get("token_before") or 0)
            after = int(payload.get("token_after") or 0)
            success = bool(payload.get("success"))
            if success:
                compaction_success += 1
                reduction = max(0, before - after)
                compaction_reduction_tokens += reduction
                if before > 0:
                    compaction_reduction_pcts.append((reduction / before) * 100.0)
                last_compaction_summary = f"{reason}: -{reduction:,} tokens"
            else:
                compaction_failure += 1
                last_compaction_summary = f"{reason}: failed"

        elif rec_type == "exec_approval_requested":
            exec_requested += 1

        elif rec_type == "exec_approval_resolved":
            decision = str(payload.get("decision") or "")
            if decision in {"approved", "approved_for_session"}:
                exec_approved += 1
            elif decision == "denied":
                exec_denied += 1
            elif decision == "abort":
                exec_aborted += 1

        elif rec_type == "network_approval_requested":
            network_requested += 1

        elif rec_type == "token_budget":
            fraction = payload.get("fraction_used")
            used_tokens = int(payload.get("used_tokens") or 0)
            budget_tokens = int(payload.get("budget_tokens") or 0)
            if fraction is not None and (
                peak_fraction_used is None or float(fraction) > peak_fraction_used
            ):
                peak_fraction_used = float(fraction)
                peak_used_tokens = used_tokens
                peak_budget_tokens = budget_tokens

    tool_breakdown = sorted(
        tool_entries.values(),
        key=lambda entry: (-entry.count, -entry.total_duration_ms, entry.name),
    )

    return {
        "tool_calls": len(counted_tool_calls),
        "tool_failures": tool_failures,
        "shell_commands": shell_commands,
        "agent_spawns": agent_spawns,
        "agent_completions": agent_completions,
        "tool_breakdown": tool_breakdown,
        "compaction": CompactionSummary(
            total=compaction_total,
            successful=compaction_success,
            failed=compaction_failure,
            reduction_tokens=compaction_reduction_tokens,
            average_reduction_pct=(
                sum(compaction_reduction_pcts) / len(compaction_reduction_pcts)
                if compaction_reduction_pcts else None
            ),
            best_reduction_pct=max(compaction_reduction_pcts) if compaction_reduction_pcts else None,
            last_summary=last_compaction_summary,
            reasons=dict(reason_counts),
        ),
        "approvals": ApprovalSummary(
            exec_requested=exec_requested,
            exec_approved=exec_approved,
            exec_denied=exec_denied,
            exec_aborted=exec_aborted,
            network_requested=network_requested,
        ),
        "budget": BudgetSummary(
            peak_fraction_used=peak_fraction_used,
            peak_used_tokens=peak_used_tokens,
            peak_budget_tokens=peak_budget_tokens,
        ),
    }
