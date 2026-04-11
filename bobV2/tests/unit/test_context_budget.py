from __future__ import annotations

from types import SimpleNamespace

from bob.core.context_budget import compute_context_budget, should_compact


class _FakeCatalog:
    def __init__(self, window: int | None):
        self._window = window

    def get_context_window(self, _model_id: str):
        return self._window


def test_compute_context_budget_uses_model_window(monkeypatch):
    from bob.core import context_budget as cb

    monkeypatch.setattr(cb, "get_catalog", lambda: _FakeCatalog(200_000))
    cfg = SimpleNamespace(
        model="gpt-test",
        max_context_tokens=0,
        effective_context_window_percent=0.85,
        compact_reserve_output_tokens=12_000,
        compact_trigger_buffer_tokens=8_000,
    )
    session = SimpleNamespace(config=cfg)
    budget = compute_context_budget(session)

    assert budget.model_context_window == 200_000
    assert budget.effective_context_window == 158_000
    assert budget.compact_trigger_tokens == 150_000


def test_should_compact_respects_override_threshold():
    from bob.core.context_budget import ContextBudget

    budget = ContextBudget(
        model_context_window=200_000,
        effective_context_window=160_000,
        compact_trigger_tokens=152_000,
        reserve_output_tokens=12_000,
        trigger_buffer_tokens=8_000,
    )
    assert should_compact(110_000, budget, configured_threshold=100_000)
    assert not should_compact(90_000, budget, configured_threshold=100_000)
    assert should_compact(153_000, budget, configured_threshold=0)

