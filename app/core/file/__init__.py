# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
from app.core.file.file_registry import FileEntry, FileRegistry, get_file_registry
from app.core.file.file_watcher import FileWatcher, get_file_watcher


def __getattr__(name: str):
    if name == "register_file_tools":
        from app.core.file.file_tools import register_file_tools

        return register_file_tools
    raise AttributeError(name)

__all__ = [
    "FileRegistry",
    "FileEntry",
    "get_file_registry",
    "FileWatcher",
    "get_file_watcher",
    "register_file_tools",
]
