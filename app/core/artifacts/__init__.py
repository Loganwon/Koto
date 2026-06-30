# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Shared artifact result contract for Koto task outputs."""

from __future__ import annotations

from app.core.artifacts.models import (
    Artifact,
    ArtifactResult,
    ExecutionLog,
    FileChange,
    SourceRef,
    build_background_artifact_result,
    build_file_task_artifact_result,
)

__all__ = [
    "Artifact",
    "ArtifactResult",
    "ExecutionLog",
    "FileChange",
    "SourceRef",
    "build_background_artifact_result",
    "build_file_task_artifact_result",
]
