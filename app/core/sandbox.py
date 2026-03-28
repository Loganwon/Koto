# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
Koto Sandbox — safe subprocess-based Python/R execution.

Runs code in a separate process with:
  - A fresh temp directory as cwd (cleaned up after)
  - A configurable timeout (default 30 s)
  - Captured stdout / stderr
  - Auto-detection of generated image files; returned as base64 data-URIs

Return schema (always a dict):
  {
    "stdout":  str,
    "stderr":  str,
    "error":   str | None,   # set only on timeout / env failures
    "files":   { "filename.png": "data:image/png;base64,..." }
  }
"""

from __future__ import annotations

import base64
import logging
import mimetypes
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict

logger = logging.getLogger(__name__)

_TIMEOUT = 60  # seconds
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".svg", ".gif", ".pdf"}

# Matplotlib non-interactive backend — must be set before any matplotlib import
_MATPLOTLIB_PREAMBLE = "import matplotlib; matplotlib.use('Agg')\n"


def _collect_files(tmpdir: Path) -> Dict[str, str]:
    """Return base64 data-URIs for every image written to tmpdir."""
    result: Dict[str, str] = {}
    for p in sorted(tmpdir.iterdir()):
        if p.suffix.lower() in _IMAGE_EXTS and p.is_file():
            mime, _ = mimetypes.guess_type(str(p))
            mime = mime or "image/png"
            b64 = base64.b64encode(p.read_bytes()).decode()
            result[p.name] = f"data:{mime};base64,{b64}"
    return result


def run_python(code: str, timeout: int = _TIMEOUT) -> dict:
    """
    Execute Python *code* in a subprocess with the venv interpreter.
    Returns the standard result dict.
    """
    with tempfile.TemporaryDirectory(prefix="koto_sandbox_") as tmpdir:
        script_path = Path(tmpdir) / "_script.py"
        # Inject matplotlib Agg backend preamble for headless chart saving
        full_code = _MATPLOTLIB_PREAMBLE + code
        script_path.write_text(full_code, encoding="utf-8")

        env = {**os.environ, "MPLBACKEND": "Agg"}
        try:
            proc = subprocess.run(
                [sys.executable, str(script_path)],
                cwd=tmpdir,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            )
            files = _collect_files(Path(tmpdir))
            return {
                "stdout": proc.stdout,
                "stderr": proc.stderr,
                "error": None if proc.returncode == 0 else f"Exit code {proc.returncode}",
                "files": files,
            }
        except subprocess.TimeoutExpired:
            return {"stdout": "", "stderr": "", "error": f"执行超时（>{timeout}s）", "files": {}}
        except Exception as exc:
            logger.exception("[Sandbox] run_python failed: %s", exc)
            return {"stdout": "", "stderr": "", "error": str(exc), "files": {}}


def run_r(code: str, timeout: int = _TIMEOUT) -> dict:
    """
    Execute R *code* in a subprocess (requires Rscript on PATH).
    Returns the standard result dict.
    """
    import shutil

    rscript = shutil.which("Rscript")
    if not rscript:
        return {
            "stdout": "",
            "stderr": "",
            "error": "R 未安装或 Rscript 不在 PATH 中。请安装 R (https://cran.r-project.org)。",
            "files": {},
        }

    with tempfile.TemporaryDirectory(prefix="koto_sandbox_r_") as tmpdir:
        script_path = Path(tmpdir) / "_script.R"
        # Set working dir inside R script so ggsave / png() land in tmpdir
        preamble = f'setwd("{tmpdir.replace(chr(92), "/")}")\n'
        script_path.write_text(preamble + code, encoding="utf-8")

        try:
            proc = subprocess.run(
                [rscript, "--vanilla", str(script_path)],
                cwd=tmpdir,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=os.environ,
            )
            files = _collect_files(Path(tmpdir))
            return {
                "stdout": proc.stdout,
                "stderr": proc.stderr,
                "error": None if proc.returncode == 0 else f"Exit code {proc.returncode}",
                "files": files,
            }
        except subprocess.TimeoutExpired:
            return {"stdout": "", "stderr": "", "error": f"执行超时（>{timeout}s）", "files": {}}
        except Exception as exc:
            logger.exception("[Sandbox] run_r failed: %s", exc)
            return {"stdout": "", "stderr": "", "error": str(exc), "files": {}}
