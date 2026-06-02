# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
SandboxPlugin — Exposes sandbox code execution as Agent tools.

Bridges the existing ``sandbox.py`` (run_python / run_r) into the
Agent ToolRegistry so the LLM can autonomously execute code during
a ReAct loop.  Also provides a restricted shell command tool.
"""

import json
import logging
import os
import shlex
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List

from app.core.agent.base import AgentPlugin

logger = logging.getLogger(__name__)

# ── Shell whitelist ──────────────────────────────────────────────────────
# Only these commands may be executed via run_shell_command.
_SHELL_WHITELIST = frozenset(
    {
        "diff",
        "wc",
        "grep",
        "head",
        "tail",
        "cat",
        "sort",
        "uniq",
        "find",
        "ls",
        "dir",
        "echo",
        "pandoc",
        "file",
        "stat",
        "md5sum",
        "sha256sum",
        "csvtool",
    }
)

_SHELL_TIMEOUT = 30  # seconds


# ── Session temp-dir registry ───────────────────────────────────────────
# Within a single agent task, multiple sandbox calls share the same temp
# directory so intermediate files persist across steps.
_session_dirs: Dict[str, str] = {}


def _get_session_dir(session_id: str | None) -> str | None:
    """Return (and lazily create) a persistent temp dir for a session."""
    if not session_id:
        return None
    if session_id not in _session_dirs:
        d = tempfile.mkdtemp(prefix=f"koto_sandbox_{session_id[:8]}_")
        _session_dirs[session_id] = d
        logger.debug("[SandboxPlugin] Created session dir %s for %s", d, session_id)
    return _session_dirs[session_id]


def cleanup_session(session_id: str):
    """Remove the temp directory for a finished session (best-effort)."""
    d = _session_dirs.pop(session_id, None)
    if d:
        import shutil

        shutil.rmtree(d, ignore_errors=True)
        logger.debug("[SandboxPlugin] Cleaned up session dir %s", d)


class SandboxPlugin(AgentPlugin):
    """Agent tools for sandboxed Python/R/shell execution."""

    def __init__(self, session_id: str | None = None):
        self._session_id = session_id

    @property
    def name(self) -> str:
        return "Sandbox"

    @property
    def description(self) -> str:
        return (
            "Execute Python/R code and restricted shell commands in an "
            "isolated sandbox.  Use for data analysis, chart generation, "
            "text processing, and file transformations."
        )

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "run_python_code",
                "func": self.run_python_code,
                "description": (
                    "Execute Python code in a sandboxed environment.  "
                    "matplotlib figures are auto-captured as PNG images.  "
                    "Returns stdout, stderr, and any generated image files (base64).  "
                    "Use for data analysis, chart generation, calculations, "
                    "and text processing."
                ),
            },
            {
                "name": "run_r_code",
                "func": self.run_r_code,
                "description": (
                    "Execute R code in a sandboxed environment.  "
                    "ggplot2/base graphics are captured as PNG images.  "
                    "Returns stdout, stderr, and generated images.  "
                    "Use when the user specifically requests R or when "
                    "R packages are more appropriate."
                ),
            },
            {
                "name": "run_shell_command",
                "func": self.run_shell_command,
                "description": (
                    "Run a restricted shell command (whitelist: diff, wc, grep, "
                    "head, tail, cat, sort, uniq, find, ls, pandoc, file, stat, "
                    "md5sum, sha256sum).  Use for quick file inspection, diffing, "
                    "and format conversion via pandoc."
                ),
            },
        ]

    # ── Tool implementations ─────────────────────────────────────────────

    def run_python_code(self, code: str, timeout: int = 30) -> str:
        """Execute Python code in sandbox, return formatted result."""
        from app.core.sandbox import run_python

        timeout = min(max(int(timeout), 5), 120)
        work_dir = _get_session_dir(self._session_id)
        result = run_python(code, timeout=timeout, work_dir=work_dir)
        return self._format_result("Python", result)

    def run_r_code(self, code: str, timeout: int = 30) -> str:
        """Execute R code in sandbox, return formatted result."""
        from app.core.sandbox import run_r

        timeout = min(max(int(timeout), 5), 120)
        work_dir = _get_session_dir(self._session_id)
        result = run_r(code, timeout=timeout, work_dir=work_dir)
        return self._format_result("R", result)

    def run_shell_command(self, command: str, timeout: int = 30) -> str:
        """Run a whitelisted shell command."""
        if not command or not command.strip():
            return "Error: empty command"

        # Parse to validate the base command is whitelisted
        try:
            parts = shlex.split(command)
        except ValueError as e:
            return f"Error: invalid command syntax — {e}"

        if not parts:
            return "Error: empty command"

        base_cmd = Path(parts[0]).name.lower()
        if base_cmd not in _SHELL_WHITELIST:
            allowed = ", ".join(sorted(_SHELL_WHITELIST))
            return (
                f"Error: '{base_cmd}' is not allowed.  "
                f"Permitted commands: {allowed}"
            )

        # Block shell metacharacters to prevent injection
        dangerous = set(";&|`$(){}!")
        if any(ch in command for ch in dangerous):
            return "Error: shell metacharacters are not allowed"

        timeout = min(max(int(timeout), 5), 60)

        try:
            result = subprocess.run(
                parts,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=_get_session_dir(self._session_id) or tempfile.gettempdir(),
            )
            out = result.stdout[:65536]
            err = result.stderr[:8192]
            parts_out = []
            if out:
                parts_out.append(f"stdout:\n{out}")
            if err:
                parts_out.append(f"stderr:\n{err}")
            if result.returncode != 0:
                parts_out.append(f"exit code: {result.returncode}")
            return "\n".join(parts_out) if parts_out else "(no output)"
        except subprocess.TimeoutExpired:
            return f"Error: command timed out after {timeout}s"
        except FileNotFoundError:
            return f"Error: command '{base_cmd}' not found on PATH"
        except Exception as e:
            return f"Error: {e}"

    # ── Helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _format_result(lang: str, result: dict) -> str:
        """Format sandbox run_python/run_r result into readable text."""
        parts = []

        if result.get("error"):
            parts.append(f"⚠️ {lang} Error: {result['error']}")

        stdout = (result.get("stdout") or "").strip()
        stderr = (result.get("stderr") or "").strip()

        if stdout:
            parts.append(f"stdout:\n{stdout}")
        if stderr:
            parts.append(f"stderr:\n{stderr}")

        files = result.get("files") or {}
        if files:
            fnames = list(files.keys())
            parts.append(f"Generated {len(fnames)} file(s): {', '.join(fnames)}")
            # Include base64 references so downstream can render them
            for fname, b64 in files.items():
                # Truncate very large payloads in the observation
                preview = b64[:200] + "..." if len(b64) > 200 else b64
                parts.append(f"[file:{fname}] (base64, {len(b64)} chars)")

        if result.get("truncated"):
            parts.append("⚠️ Output was truncated (exceeded size limit)")

        return (
            "\n".join(parts)
            if parts
            else f"{lang} code executed successfully (no output)"
        )
