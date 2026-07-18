# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Runtime service accessors that do not depend on the ``web.app`` bridge."""

from __future__ import annotations

from typing import Any


def get_behavior_monitor() -> Any:
    from web.lazy_loaders.monitoring_services import get_behavior_monitor as _get_service

    return _get_service()


def get_suggestion_engine() -> Any:
    from web.lazy_loaders.monitoring_services import get_suggestion_engine as _get_service

    return _get_service()


def get_insight_reporter() -> Any:
    from web.lazy_loaders.monitoring_services import get_insight_reporter as _get_service

    return _get_service()


def get_notification_manager() -> Any:
    from web.lazy_loaders.monitoring_services import get_notification_manager as _get_service

    return _get_service()


def get_proactive_dialogue() -> Any:
    from web.lazy_loaders.monitoring_services import get_proactive_dialogue as _get_service

    return _get_service()


def get_context_awareness() -> Any:
    from web.lazy_loaders.monitoring_services import get_context_awareness as _get_service

    return _get_service()


def get_trigger_system() -> Any:
    from web.lazy_loaders.monitoring_services import get_trigger_system as _get_service

    return _get_service()


def get_auto_execution() -> Any:
    from web.lazy_loaders.monitoring_services import get_auto_execution as _get_service

    return _get_service()


def get_knowledge_graph() -> Any:
    from web.lazy_loaders.knowledge_services import get_knowledge_graph as _get_service

    return _get_service()


def get_file_editor() -> Any:
    from web.lazy_loaders.file_services import get_file_editor as _get_service

    return _get_service()


def get_file_indexer() -> Any:
    from web.lazy_loaders.file_services import get_file_indexer as _get_service

    return _get_service()


def get_concept_extractor() -> Any:
    from web.lazy_loaders.knowledge_services import get_concept_extractor as _get_service

    return _get_service()


def get_file_organizer() -> Any:
    from web.lazy_loaders.file_services import get_file_organizer as _get_service

    return _get_service()


def get_file_analyzer() -> Any:
    from web.lazy_loaders.file_services import get_file_analyzer as _get_service

    return _get_service()


def get_batch_ops_manager() -> Any:
    from web.lazy_loaders.file_services import get_batch_ops_manager as _get_service

    return _get_service()


def get_organize_root() -> str:
    from web.shared import get_organize_root as _get_service

    return str(_get_service() or "")
