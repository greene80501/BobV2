from __future__ import annotations

import sys
from types import SimpleNamespace

from bob.config.schema import BobConfig
from bob.protocol.config_types import WebSearchMode
from bob.tools import web_search as web_search_module


class _DummySession:
    def __init__(self) -> None:
        self.config = BobConfig()


class _DummyContext:
    def __init__(self) -> None:
        self._session = _DummySession()


def test_bob_config_enables_live_web_search_by_default() -> None:
    config = BobConfig()

    assert config.network_access is True
    assert config.web_search_mode == WebSearchMode.LIVE
    assert config.web_search.default_max_results == 10


async def _fake_run_single_query(
    query: str,
    *,
    max_results: int,
    providers: list[str],
    allowed_domains: list[str] | None,
    brave_key: str,
    serp_key: str,
    proxy: str,
) -> dict[str, object]:
    return {
        "query": query,
        "provider": providers[0],
        "results": [
            {
                "title": f"title for {query}",
                "href": f"https://example.com/{query.replace(' ', '-')}",
                "body": f"snippet for {query}",
            }
        ],
        "errors": [],
    }


class _FakeAsyncClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


async def _fake_fetch_page_excerpt(client, url: str, *, timeout_seconds: float, max_chars: int = 6000) -> str:
    return f"fetched {url}"


def test_web_search_handler_supports_multi_query_and_page_fetch(monkeypatch) -> None:
    monkeypatch.setattr(web_search_module, "_run_single_query", _fake_run_single_query)
    monkeypatch.setattr(web_search_module, "_fetch_page_excerpt", _fake_fetch_page_excerpt)
    monkeypatch.setitem(
        sys.modules,
        "httpx",
        SimpleNamespace(AsyncClient=lambda **kwargs: _FakeAsyncClient()),
    )

    import asyncio

    out = asyncio.run(
        web_search_module.web_search_handler(
            {
                "queries": ["bob tui bugs", "kimi provider reliability"],
                "fetch_pages": True,
                "fetch_per_query": 1,
                "providers": ["ddg"],
            },
            _DummyContext(),
        )
    )

    assert "Web research results (2 queries)" in out
    assert "title for bob tui bugs" in out
    assert "title for kimi provider reliability" in out
    assert "Fetched content excerpt:" in out
    assert "fetched https://example.com/bob-tui-bugs" in out


def test_web_search_handler_rejects_missing_queries() -> None:
    import asyncio

    out = asyncio.run(web_search_module.web_search_handler({}, _DummyContext()))

    assert out == "Error: query or queries is required"
