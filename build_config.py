"""Shared build configuration for Koto packaging helpers."""

from __future__ import annotations

from pathlib import Path


PROTECTED_DIRS: tuple[str, ...] = (
    "app/core/agent",
    "app/core/llm",
    "app/core/memory",
    "app/core/workflow",
    "app/core/skills",
    "app/core/learning",
    "app/core/routing",
    "app/core/goal",
    "app/core/tasks",
)


def protected_dir_paths(root: str | Path) -> set[str]:
    """Return normalized absolute protected directory paths for PyInstaller."""

    root_path = Path(root).resolve()
    return {str((root_path / rel_path).resolve()) for rel_path in PROTECTED_DIRS}
