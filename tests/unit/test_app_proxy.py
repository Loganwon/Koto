"""Unit contracts for proxy configuration outside Flask application wiring."""

from __future__ import annotations

import os
from unittest.mock import MagicMock

from web.app_proxy import configure_proxy
from web.llm_runtime_helpers import normalize_proxy_url


def test_configure_proxy_honors_forced_proxy_without_socket_probe() -> None:
    logger = MagicMock()
    previous_http = os.environ.get("HTTP_PROXY")
    previous_https = os.environ.get("HTTPS_PROXY")
    try:
        assert configure_proxy(
            force_proxy="http://forced-proxy:7890",
            settings_manager=MagicMock(),
            normalize_proxy_url=normalize_proxy_url,
            proxy_options=[],
            logger=logger,
        ) == "http://forced-proxy:7890"
        assert os.environ["HTTP_PROXY"] == "http://forced-proxy:7890"
        assert os.environ["HTTPS_PROXY"] == "http://forced-proxy:7890"
    finally:
        if previous_http is None:
            os.environ.pop("HTTP_PROXY", None)
        else:
            os.environ["HTTP_PROXY"] = previous_http
        if previous_https is None:
            os.environ.pop("HTTPS_PROXY", None)
        else:
            os.environ["HTTPS_PROXY"] = previous_https


def test_configure_proxy_clears_environment_when_disabled() -> None:
    settings_manager = MagicMock()
    settings_manager.get.return_value = False
    previous_http = os.environ.get("HTTP_PROXY")
    previous_https = os.environ.get("HTTPS_PROXY")
    try:
        os.environ["HTTP_PROXY"] = "http://stale:8080"
        os.environ["HTTPS_PROXY"] = "http://stale:8080"
        assert configure_proxy(
            force_proxy="",
            settings_manager=settings_manager,
            normalize_proxy_url=normalize_proxy_url,
            proxy_options=[],
            logger=MagicMock(),
        ) is None
        assert "HTTP_PROXY" not in os.environ
        assert "HTTPS_PROXY" not in os.environ
    finally:
        if previous_http is None:
            os.environ.pop("HTTP_PROXY", None)
        else:
            os.environ["HTTP_PROXY"] = previous_http
        if previous_https is None:
            os.environ.pop("HTTPS_PROXY", None)
        else:
            os.environ["HTTPS_PROXY"] = previous_https
