"""Hermetic production Flask/Kernel acceptance runs in its own runtime process."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def test_production_flask_kernel_and_document_roundtrip(tmp_path: Path):
    root = Path(__file__).resolve().parents[2]
    state = tmp_path / "standalone-runtime"
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    result = subprocess.run(
        [
            sys.executable,
            "-u",
            str(root / "scripts" / "standalone_acceptance.py"),
            "--http-only",
            "--state-dir",
            str(state),
        ],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, (result.stdout + "\n" + result.stderr)[-14000:]
    evidence = json.loads((state / "results.json").read_text(encoding="utf-8"))
    assert evidence["mode"] == "production-flask-kernel-fixture-provider"
    assert len(evidence["passed"]) >= 6
    assert evidence["provider_calls"] >= 6
    assert evidence["browser_verified"] is False
