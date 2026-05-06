from __future__ import annotations

from types import SimpleNamespace

from bob.core.image_payloads import select_image_detail_level


def test_select_image_detail_level_prefers_low_when_context_is_near_limit() -> None:
    from bob.core import image_payloads as ip

    session = SimpleNamespace(
        context_manager=SimpleNamespace(approx_token_count=lambda: 149_000),
    )
    budget = SimpleNamespace(compact_trigger_tokens=150_000)

    original = ip.compute_context_budget
    try:
        ip.compute_context_budget = lambda _session: budget
        assert select_image_detail_level(session=session, prompt_text="check the page design") == "low"
    finally:
        ip.compute_context_budget = original


def test_select_image_detail_level_prefers_high_for_visual_requests_when_budget_allows() -> None:
    from bob.core import image_payloads as ip

    session = SimpleNamespace(
        context_manager=SimpleNamespace(approx_token_count=lambda: 20_000),
    )
    budget = SimpleNamespace(compact_trigger_tokens=150_000)

    original = ip.compute_context_budget
    try:
        ip.compute_context_budget = lambda _session: budget
        assert select_image_detail_level(session=session, prompt_text="rank the UI design from this screenshot") == "high"
    finally:
        ip.compute_context_budget = original


def test_select_image_detail_level_defaults_to_requested_level() -> None:
    assert select_image_detail_level(requested="medium") == "medium"
