# -*- coding: utf-8 -*-
"""Run-owned staging and commit helpers for generated file-task artifacts."""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

_CHANGE_PATH_FIELDS = (
    "path",
    "file_path",
    "output_path",
    "target_path",
    "destination",
    "revised_file",
)


def resolved_write_path(path: str) -> Path:
    """Resolve a write target through the canonical task-tool workspace owner."""
    try:
        from app.core.agent import task_tools

        resolved = task_tools._resolve_path(  # type: ignore[attr-defined]
            path,
            must_exist=False,
        )
    except Exception:
        resolved = ""
    return Path(str(resolved or path)).resolve()


def run_scoped_staging_path(
    request: Any,
    target_path: str,
    *,
    marker: str = "koto-partial",
) -> Path:
    """Return a hidden, run-owned staging path beside the final target."""
    target = resolved_write_path(target_path)
    run_token = (
        re.sub(
            r"[^A-Za-z0-9_-]+",
            "_",
            str(getattr(request, "run_id", "") or "run"),
        ).strip("_")[:48]
        or "run"
    )
    suffix = target.suffix
    return target.with_name(f".{target.stem}.{run_token}.{marker}{suffix}")


def cleanup_run_owned_paths(
    staging_path: Path,
    candidate_paths: Iterable[Path] = (),
    *,
    preexisting_paths: Iterable[Path] = (),
) -> None:
    """Delete only staging/new artifacts owned by the current failed run."""
    preserved = {Path(path) for path in preexisting_paths}
    for path in [Path(staging_path), *(Path(item) for item in candidate_paths)]:
        if path in preserved:
            continue
        try:
            if path.is_file():
                path.unlink()
        except OSError as exc:
            logger.warning(
                "failed to remove incomplete file-task artifact %s: %s",
                path,
                exc,
            )


def commit_staged_artifact(staging_path: Path, target_path: str) -> bool:
    """Atomically publish a completed staging artifact."""
    if not staging_path.is_file():
        return False
    try:
        target = resolved_write_path(target_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staging_path, target)
        return True
    except OSError as exc:
        logger.warning(
            "file-task artifact commit failed for %s: %s",
            target_path,
            exc,
        )
        return False


def committed_file_changes(
    changes: Iterable[Dict[str, Any]],
    *,
    staging_path: Path,
    target_path: str,
) -> List[Dict[str, Any]]:
    """Rewrite staged change paths to the final public target."""
    staging_key = os.path.normcase(os.path.normpath(str(staging_path)))
    committed: List[Dict[str, Any]] = []
    for raw_change in changes:
        if not isinstance(raw_change, dict):
            continue
        change = dict(raw_change)
        for key in _CHANGE_PATH_FIELDS:
            value = str(change.get(key) or "").strip()
            if not value:
                continue
            resolved_key = os.path.normcase(
                os.path.normpath(str(Path(value).resolve()))
            )
            if resolved_key == staging_key:
                change[key] = target_path
        committed.append(change)
    return committed


__all__ = [
    "cleanup_run_owned_paths",
    "commit_staged_artifact",
    "committed_file_changes",
    "resolved_write_path",
    "run_scoped_staging_path",
]
