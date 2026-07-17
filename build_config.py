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

CYTHON_BUILD_RELATIVE_DIR = "build/cython_lib"
CYTHON_EXTENSION_SUFFIXES: tuple[str, ...] = (".pyd", ".so")


def protected_dir_paths(root: str | Path) -> set[str]:
    """Return normalized absolute protected directory paths for PyInstaller."""

    root_path = Path(root).resolve()
    return {str((root_path / rel_path).resolve()) for rel_path in PROTECTED_DIRS}


def cython_build_root(root: str | Path) -> Path:
    """Return the isolated output root for compiled protected modules."""

    return (Path(root).resolve() / CYTHON_BUILD_RELATIVE_DIR).resolve()


def staged_cython_extensions(root: str | Path) -> list[Path]:
    """List compiled protected modules from the isolated build tree."""

    build_root = cython_build_root(root)
    artifacts: list[Path] = []
    for relative_dir in PROTECTED_DIRS:
        staged_dir = build_root / relative_dir
        if not staged_dir.is_dir():
            continue
        artifacts.extend(
            path
            for path in staged_dir.rglob("*")
            if path.is_file() and path.suffix.lower() in CYTHON_EXTENSION_SUFFIXES
        )
    return sorted(artifacts)


def has_staged_cython_extension(root: str | Path, source_file: str | Path) -> bool:
    """Return whether a source module has a matching staged extension."""

    root_path = Path(root).resolve()
    source_path = Path(source_file).resolve()
    try:
        relative_stem = source_path.relative_to(root_path).with_suffix("")
    except ValueError:
        return False
    staged_stem = cython_build_root(root_path) / relative_stem
    return any(
        next(
            staged_stem.parent.glob(f"{staged_stem.name}*{suffix}"),
            None,
        )
        is not None
        for suffix in CYTHON_EXTENSION_SUFFIXES
    )
