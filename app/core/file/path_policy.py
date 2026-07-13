# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Shared path policy helpers for file services.

This module centralizes low-level path safety decisions while callers keep
their existing API contracts and user-facing error messages.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

WINDOWS_PROTECTED_DIR_NAMES: frozenset[str] = frozenset(
    {
        "windows",
        "system32",
        "syswow64",
        "program files",
        "program files (x86)",
        "system volume information",
    }
)


class PathPolicyError(ValueError):
    """Raised when a path violates the shared file path policy."""


@dataclass(frozen=True)
class FilePathPolicy:
    protected_dir_names: frozenset[str] = WINDOWS_PROTECTED_DIR_NAMES

    def resolve(self, raw_path: str | Path) -> Path:
        return Path(raw_path).resolve()

    def is_outside_protected_dirs(self, raw_path: str | Path) -> bool:
        try:
            lower_parts = {part.lower() for part in self.resolve(raw_path).parts}
        except Exception:
            return False
        return not (lower_parts & self.protected_dir_names)

    def root(self, workspace_dir: str | Path) -> Path:
        return self.resolve(workspace_dir)

    def resolve_under_root(self, root: str | Path, rel_path: str | Path) -> Path:
        root_path = self.root(root)
        # Workspace paths arrive over HTTP and may use Windows separators even
        # when the server runs on Linux.  Normalize before resolving so a
        # payload such as ``..\\secret.txt`` cannot become an ordinary
        # filename on POSIX hosts.
        normalized = str(rel_path).replace("\\", "/")
        if (
            normalized.startswith("/")
            or re.match(r"^[A-Za-z]:/", normalized)
            or any(part == ".." for part in normalized.split("/"))
        ):
            raise PathPolicyError("Path escapes workspace root")

        target = root_path.joinpath(*normalized.split("/")).resolve()
        try:
            target.relative_to(root_path)
        except ValueError as exc:
            raise PathPolicyError("Path escapes workspace root") from exc
        return target


DEFAULT_FILE_PATH_POLICY = FilePathPolicy()
