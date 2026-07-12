# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Shared path resolution helpers for agent tools/plugins."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, Sequence


def default_search_roots(extra_roots: Iterable[str] | None = None) -> list[str]:
    """Return canonical search roots for resolving user-provided file paths."""
    cwd = os.path.abspath(os.getcwd())
    candidates = [
        cwd,
        os.path.join(cwd, "workspace"),
        os.path.join(cwd, "uploads"),
        os.path.join(cwd, "dist"),
    ]
    if extra_roots:
        candidates.extend(str(p) for p in extra_roots)

    roots: list[str] = []
    for c in candidates:
        c_abs = os.path.abspath(os.path.expandvars(os.path.expanduser(str(c))))
        if os.path.isdir(c_abs) and c_abs not in roots:
            roots.append(c_abs)
    return roots


def is_within_roots(path: str, roots: Sequence[str]) -> bool:
    """Return True if ``path`` is within at least one of ``roots``."""
    real = os.path.realpath(os.path.abspath(path))
    for root in roots:
        base = os.path.realpath(os.path.abspath(root))
        try:
            common = os.path.commonpath([real, base])
        except ValueError:
            continue
        if common == base:
            return True
    return False


def has_parent_path_segment(path: str) -> bool:
    """Return whether a relative path tries to traverse through ``..``."""
    return any(
        part == ".." for part in str(path or "").replace("\\", "/").split("/")
    )


def resolve_existing_path(
    user_path: str,
    *,
    roots: Sequence[str] | None = None,
    filename_recursive_search: bool = True,
) -> tuple[str | None, str | None]:
    """Resolve a user-provided path to an existing absolute file path.

    Resolution order:
    1) absolute path if exists
    2) direct relative to current working directory
    3) relative under each root
    4) recursive filename lookup in roots (if basename only)
    """
    raw = (user_path or "").strip().strip('"').strip("'")
    if not raw:
        return None, "empty path"

    expanded = os.path.expandvars(os.path.expanduser(raw))

    if os.path.isabs(expanded):
        abs_path = os.path.abspath(expanded)
        if os.path.isfile(abs_path):
            return abs_path, None
        return None, f"file not found: {abs_path}"

    direct = os.path.abspath(expanded)
    if os.path.isfile(direct):
        return direct, None

    search_roots = list(roots) if roots is not None else default_search_roots()

    for root in search_roots:
        p = os.path.abspath(os.path.join(root, expanded))
        if os.path.isfile(p):
            return p, None

    if filename_recursive_search and not any(sep in expanded for sep in ("/", "\\")):
        target = expanded.lower()
        matches: list[str] = []
        for root in search_roots:
            for cur, _, files in os.walk(root):
                for name in files:
                    if name.lower() == target:
                        matches.append(os.path.join(cur, name))
                        if len(matches) >= 5:
                            break
                if len(matches) >= 5:
                    break
            if len(matches) >= 5:
                break

        if matches:
            matches.sort(key=lambda x: (len(Path(x).parts), len(x), x.lower()))
            return os.path.abspath(matches[0]), None

    roots_desc = (
        ", ".join(search_roots) if search_roots else os.path.abspath(os.getcwd())
    )
    return None, f"file not found: {user_path}; searched in: {roots_desc}"
