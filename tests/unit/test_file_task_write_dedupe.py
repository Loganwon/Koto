from __future__ import annotations

from pathlib import Path


def test_mutating_batch_dedupe_is_owned_by_kernel_guard() -> None:
    source = Path("app/core/agent/kernel/guard.py").read_text(encoding="utf-8")

    assert "nonrepeatable_names" in source
    assert "mutating tool call cannot be repeated" in source
