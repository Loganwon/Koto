# -*- coding: utf-8 -*-
"""Regression tests retained from the 2026-03-22 architecture work."""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.unit
class TestKernelAgentService:
    """The Kernel facade, not a generic container, owns the Agent instance."""

    @pytest.fixture(autouse=True)
    def reset_agent_instance(self):
        from app.core.agent.kernel_agent_service import reset_kernel_agent_for_tests

        reset_kernel_agent_for_tests()
        yield
        reset_kernel_agent_for_tests()

    def test_factory_builds_agent(self):
        import app.core.agent.kernel_agent_service as service

        sentinel = MagicMock(name="kernel_agent")
        with patch.object(service, "create_agent", return_value=sentinel) as factory:
            assert service.get_kernel_agent() is sentinel
        factory.assert_called_once_with(tool_profile="core", addon_tool_names=())

    def test_result_is_cached(self):
        import app.core.agent.kernel_agent_service as service

        sentinel = MagicMock(name="kernel_agent")
        with patch.object(service, "create_agent", return_value=sentinel) as factory:
            first = service.get_kernel_agent()
            second = service.get_kernel_agent()
        assert first is second is sentinel
        factory.assert_called_once_with(tool_profile="core", addon_tool_names=())

    def test_reset_allows_reconstruction(self):
        import app.core.agent.kernel_agent_service as service

        first = MagicMock(name="first")
        second = MagicMock(name="second")
        with patch.object(service, "create_agent", side_effect=[first, second]):
            assert service.get_kernel_agent() is first
            service.reset_kernel_agent_for_tests()
            assert service.get_kernel_agent() is second

    def test_local_and_cloud_configs_are_separate(self):
        import app.core.agent.kernel_agent_service as service

        cloud = MagicMock(name="cloud")
        local = MagicMock(name="local")
        with patch.object(service, "create_agent", return_value=cloud), patch.object(
            service, "create_local_agent", return_value=local
        ):
            assert service.get_kernel_agent() is cloud
            assert service.get_kernel_agent(local=True) is local
            assert service.get_kernel_agent(local=True) is local


_BARE_EXCEPT_PASS_RE = re.compile(
    r"except\s*(?:Exception|BaseException)?\s*:\s*\n\s+pass\s*(?:#.*)?$",
    re.MULTILINE,
)


def _load_source(module_path: str) -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / module_path).read_text(encoding="utf-8")


@pytest.mark.unit
class TestNoBareSilentExceptions:
    """Key runtime files must not silently swallow broad exceptions."""

    def _assert_no_bare_pass(self, rel_path: str):
        matches = _BARE_EXCEPT_PASS_RE.findall(_load_source(rel_path))
        assert matches == [], f"{rel_path} contains broad except-pass blocks"

    def test_kernel_agent_service_no_bare_except_pass(self):
        self._assert_no_bare_pass("app/core/agent/kernel_agent_service.py")

    def test_retired_multi_agent_module_stays_deleted(self):
        root = Path(__file__).resolve().parents[2]
        assert not (root / "app/core/agent/multi_agent.py").exists()

    def test_web_app_no_bare_except_pass(self):
        self._assert_no_bare_pass("web/app.py")

    def test_key_files_log_silenced_exceptions(self):
        paths = (
            "app/core/agent/kernel_agent_service.py",
            "web/app.py",
        )
        assert any("Silenced exception caught" in _load_source(path) for path in paths)
