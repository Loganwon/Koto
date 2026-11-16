# Copyright (C) 2024-2026 Koto AI. All rights reserved.
"""Tests for the transport-neutral Kernel web-search boundary."""

import pytest

from app.core.agent.toolkits.builtin.search_plugin import SearchPlugin
from app.core.services.web_search_gateway import (
    configure_web_search_handler,
    get_web_search_handler,
)


@pytest.fixture(autouse=True)
def _restore_search_handler():
    previous = get_web_search_handler()
    try:
        yield
    finally:
        configure_web_search_handler(previous)


def test_search_plugin_reports_unavailable_without_composition_binding() -> None:
    configure_web_search_handler(None)

    assert "unavailable" in SearchPlugin().web_search("latest news").lower()


def test_search_plugin_uses_composition_root_handler_and_formats_sources() -> None:
    configure_web_search_handler(
        lambda query: {
            "success": True,
            "response": f"answer for {query}",
            "sources": [{"id": 1, "title": "Example", "url": "https://example.test"}],
        }
    )

    result = SearchPlugin().web_search("weather")

    assert "answer for weather" in result
    assert "Example https://example.test" in result
