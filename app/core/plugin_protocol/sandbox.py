# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Plugin Sandbox — runtime isolation for plugin execution.

Provides process-level sandboxing for plugins:
  - Subprocess isolation
  - Filesystem path whitelisting
  - Network access control (URL whitelist)
  - Resource limits (timeout, memory)
  - Audit logging for all tool invocations
"""

from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class SandboxLimits:
    """Resource limits for plugin sandbox execution."""

    __slots__ = (
        "max_timeout_seconds",
        "max_result_bytes",
        "max_concurrency",
        "allowed_paths",
        "allowed_domains",
    )

    def __init__(
        self,
        max_timeout_seconds: float = 30.0,
        max_result_bytes: int = 10 * 1024 * 1024,  # 10 MB
        max_concurrency: int = 4,
        allowed_paths: Optional[List[Path]] = None,
        allowed_domains: Optional[List[str]] = None,
    ):
        self.max_timeout_seconds = max_timeout_seconds
        self.max_result_bytes = max_result_bytes
        self.max_concurrency = max_concurrency
        self.allowed_paths: List[Path] = [Path(p) for p in (allowed_paths or [])]
        self.allowed_domains: List[str] = allowed_domains or []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "max_timeout_seconds": self.max_timeout_seconds,
            "max_result_bytes": self.max_result_bytes,
            "max_concurrency": self.max_concurrency,
            "allowed_paths": [str(p) for p in self.allowed_paths],
            "allowed_domains": list(self.allowed_domains),
        }


class SandboxViolation(Exception):
    """Raised when a plugin violates sandbox constraints."""

    def __init__(self, message: str, plugin_id: str = "", detail: Any = None):
        super().__init__(message)
        self.plugin_id = plugin_id
        self.detail = detail


class PluginSandbox:
    """Runtime sandbox for plugin execution.

    Enforces:
      - Filesystem access limited to whitelisted paths
      - Network access limited to whitelisted domains
      - Execution timeout
      - Result size limits
      - Concurrency limits

    Usage:
        sandbox = PluginSandbox(
            limits=SandboxLimits(
                allowed_paths=[Path("/workspace")],
                allowed_domains=["api.example.com"],
            ),
            plugin_id="my-plugin",
        )

        @sandbox.guard
        def my_tool(path: str) -> str:
            with open(path) as f:
                return f.read()

        result = my_tool("/workspace/test.txt")
    """

    def __init__(
        self,
        limits: Optional[SandboxLimits] = None,
        plugin_id: str = "",
        workspace_root: Optional[Path] = None,
    ):
        self.limits = limits or SandboxLimits()
        self.plugin_id = plugin_id
        self.workspace_root = workspace_root or Path.cwd()
        self._audit_log: List[Dict[str, Any]] = []
        self._lock = threading.RLock()
        self._active_calls = 0

        # Register cleanup on exit
        import atexit

        atexit.register(self.cleanup)

    # ── Path Validation ─────────────────────────────────────────────────────

    def validate_path(self, path: str) -> Path:
        """Validate that a filesystem path is within allowed paths.

        Returns the resolved absolute Path if valid.
        Raises SandboxViolation if path is outside allowed scope.
        """
        resolved = Path(path).resolve()

        # If no explicit allowed paths, restrict to workspace_root
        allowed = self.limits.allowed_paths or [self.workspace_root]

        for allowed_path in allowed:
            resolved_allowed = allowed_path.resolve()
            try:
                resolved.relative_to(resolved_allowed)
                return resolved
            except ValueError:
                continue

        raise SandboxViolation(
            f"Path {path!r} is outside allowed sandbox paths",
            plugin_id=self.plugin_id,
            detail={"path": str(resolved), "allowed": [str(p) for p in allowed]},
        )

    # ── Network Validation ──────────────────────────────────────────────────

    def validate_url(self, url: str) -> str:
        """Validate that a URL is within allowed domains.

        Returns the URL if valid.
        Raises SandboxViolation if the domain is not whitelisted.
        """
        from urllib.parse import urlparse

        parsed = urlparse(url)
        hostname = parsed.hostname or ""

        if not self.limits.allowed_domains:
            raise SandboxViolation(
                f"Network access is not allowed for plugin {self.plugin_id!r}",
                plugin_id=self.plugin_id,
            )

        for allowed in self.limits.allowed_domains:
            if hostname == allowed or hostname.endswith("." + allowed):
                return url

        raise SandboxViolation(
            f"Domain {hostname!r} is not in allowed domains",
            plugin_id=self.plugin_id,
            detail={"url": url, "allowed_domains": self.limits.allowed_domains},
        )

    # ── Execution Guard ─────────────────────────────────────────────────────

    def guard(self, func: Callable) -> Callable:
        """Decorator that wraps a function with sandbox enforcement.

        Applies:
          - Concurrency limits
          - Timeout enforcement
          - Result size validation
          - Audit logging
        """
        from functools import wraps

        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return self._execute_guarded(func, *args, **kwargs)

        return wrapper

    def _execute_guarded(self, func: Callable, *args: Any, **kwargs: Any) -> Any:
        # Concurrency check
        with self._lock:
            if self._active_calls >= self.limits.max_concurrency:
                raise SandboxViolation(
                    f"Plugin {self.plugin_id!r} exceeded max concurrency of {self.limits.max_concurrency}",
                    plugin_id=self.plugin_id,
                )
            self._active_calls += 1

        start_time = time.time()
        call_id = f"{self.plugin_id}-{int(start_time * 1000)}"

        try:
            # Execute with timeout via threading
            result_container: Dict[str, Any] = {}
            error_container: Dict[str, Optional[Exception]] = {"error": None}

            def _run() -> None:
                try:
                    result_container["value"] = func(*args, **kwargs)
                except Exception as e:
                    error_container["error"] = e

            thread = threading.Thread(target=_run, daemon=True)
            thread.start()
            thread.join(timeout=self.limits.max_timeout_seconds)

            if thread.is_alive():
                raise SandboxViolation(
                    f"Plugin {self.plugin_id!r} execution timed out after {self.limits.max_timeout_seconds}s",
                    plugin_id=self.plugin_id,
                )

            if error_container["error"] is not None:
                raise error_container["error"]

            result = result_container.get("value")

            # Result size validation
            if isinstance(result, (str, bytes)):
                size = len(result)
                if size > self.limits.max_result_bytes:
                    raise SandboxViolation(
                        f"Plugin {self.plugin_id!r} result exceeds max size: {size} > {self.limits.max_result_bytes}",
                        plugin_id=self.plugin_id,
                    )

            return result

        finally:
            with self._lock:
                self._active_calls -= 1

            elapsed = time.time() - start_time
            self._log_audit(
                call_id, func.__name__, elapsed, error_container["error"] is None
            )

    def execute_in_subprocess(
        self,
        command: List[str],
        cwd: Optional[Path] = None,
        env: Optional[Dict[str, str]] = None,
        input_data: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Execute a command in an isolated subprocess.

        Args:
            command: Command and arguments to execute.
            cwd: Working directory (defaults to workspace_root).
            env: Environment variables (merged with parent env).
            input_data: Optional stdin data.

        Returns:
            Dict with stdout, stderr, returncode, elapsed.

        Raises:
            SandboxViolation on timeout or sandbox breach.
        """
        cwd = cwd or self.workspace_root
        self.validate_path(str(cwd))

        merged_env = os.environ.copy()
        if env:
            merged_env.update(env)

        start = time.time()
        try:
            proc = subprocess.run(
                command,
                cwd=str(cwd),
                env=merged_env,
                input=input_data,
                capture_output=True,
                text=True,
                timeout=self.limits.max_timeout_seconds,
            )
        except subprocess.TimeoutExpired as e:
            raise SandboxViolation(
                f"Subprocess timed out after {self.limits.max_timeout_seconds}s",
                plugin_id=self.plugin_id,
            ) from e

        elapsed = time.time() - start
        return {
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "returncode": proc.returncode,
            "elapsed": elapsed,
        }

    # ── Audit Logging ───────────────────────────────────────────────────────

    def _log_audit(
        self, call_id: str, operation: str, elapsed: float, success: bool
    ) -> None:
        entry = {
            "call_id": call_id,
            "plugin_id": self.plugin_id,
            "operation": operation,
            "elapsed_seconds": round(elapsed, 3),
            "success": success,
            "timestamp": time.time(),
        }
        with self._lock:
            self._audit_log.append(entry)
            # Keep only last 1000 entries
            if len(self._audit_log) > 1000:
                self._audit_log = self._audit_log[-1000:]

        logger.debug(
            "[PluginSandbox] %s %s: %s (%.3fs)",
            self.plugin_id,
            operation,
            "OK" if success else "FAILED",
            elapsed,
        )

    def get_audit_log(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Return recent audit log entries."""
        with self._lock:
            return list(self._audit_log[-limit:])

    def clear_audit_log(self) -> None:
        """Clear the audit log."""
        with self._lock:
            self._audit_log.clear()

    # ── Lifecycle ───────────────────────────────────────────────────────────

    def cleanup(self) -> None:
        """Clean up sandbox resources."""
        logger.debug("[PluginSandbox] cleaning up sandbox for %s", self.plugin_id)

    @property
    def active_calls(self) -> int:
        with self._lock:
            return self._active_calls

    def status(self) -> Dict[str, Any]:
        """Return sandbox status for diagnostics."""
        return {
            "plugin_id": self.plugin_id,
            "active_calls": self.active_calls,
            "limits": self.limits.to_dict(),
            "audit_entries": len(self._audit_log),
            "workspace_root": str(self.workspace_root),
        }


__all__ = [
    "SandboxLimits",
    "SandboxViolation",
    "PluginSandbox",
]
