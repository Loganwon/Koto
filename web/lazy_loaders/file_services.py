# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary

from web.config import get_organize_root
from web.lazy_loaders.registry import _lazy_cache, _lazy_load


def get_file_organizer():
    if "file_organizer" not in _lazy_cache:
        try:
            from web.file_organizer import FileOrganizer
        except ImportError:
            from file_organizer import FileOrganizer
        _lazy_cache["file_organizer"] = FileOrganizer(get_organize_root())
    return _lazy_cache["file_organizer"]


def get_file_analyzer():
    return _lazy_load("file_analyzer", "file_analyzer", "FileAnalyzer")


def get_batch_ops_manager():
    return _lazy_load("batch_ops", "batch_file_ops", "BatchFileOpsManager")


def get_file_editor():
    return _lazy_load("file_editor", "file_editor", "FileEditor")


def get_file_indexer():
    return _lazy_load("file_indexer", "file_indexer", "FileIndexer")
