# -*- coding: utf-8 -*-
from __future__ import annotations


def test_search_backend_extracts_duckduckgo_results(monkeypatch):
    from web import search_backend

    class _Response:
        text = """
        <div class="result">
          <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fnews">Example News</a>
          <div class="result__snippet">A current result snippet.</div>
        </div>
        """
        content = text.encode()

        @staticmethod
        def raise_for_status():
            return None

    monkeypatch.setattr(search_backend.requests, "get", lambda *a, **k: _Response())

    results = search_backend.search_web("example")

    assert results == [
        {
            "id": 1,
            "title": "Example News",
            "url": "https://example.com/news",
            "domain": "example.com",
            "snippet": "A current result snippet.",
        }
    ]


def test_web_searcher_synthesizes_retrieved_sources(monkeypatch):
    import web.search_backend
    from app.core.llm import provider_factory
    from web.web_searcher import WebSearcher

    sources = [
        {
            "id": 1,
            "title": "Source",
            "url": "https://example.com",
            "domain": "example.com",
            "snippet": "Gold is 100.",
        }
    ]

    class _Provider:
        def generate_content(self, **kwargs):
            assert "Gold is 100" in kwargs["prompt"]
            return {"content": "当前金价为 100。[1]"}

    monkeypatch.setattr(web.search_backend, "search_web", lambda query: sources)
    monkeypatch.setattr(provider_factory, "get_llm_provider", lambda **kwargs: _Provider())

    result = WebSearcher.search_with_grounding("当前金价")

    assert result["success"] is True
    assert result["response"] == "当前金价为 100。[1]"
    assert result["sources"] == sources
