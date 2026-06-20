# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary

from web.lazy_loaders.registry import _lazy_cache, _lazy_load
from web.lazy_loaders.file_services import (
    get_file_organizer,
    get_file_analyzer,
    get_batch_ops_manager,
    get_file_editor,
    get_file_indexer,
)
from web.lazy_loaders.knowledge_services import (
    get_concept_extractor,
    get_knowledge_graph,
)
from web.lazy_loaders.monitoring_services import (
    get_behavior_monitor,
    get_suggestion_engine,
    get_insight_reporter,
    get_notification_manager,
    get_proactive_dialogue,
    get_context_awareness,
    get_auto_execution,
    get_trigger_system,
)

__all__ = [
    "_lazy_cache",
    "_lazy_load",
    "get_file_organizer",
    "get_file_analyzer",
    "get_batch_ops_manager",
    "get_file_editor",
    "get_file_indexer",
    "get_concept_extractor",
    "get_knowledge_graph",
    "get_behavior_monitor",
    "get_suggestion_engine",
    "get_insight_reporter",
    "get_notification_manager",
    "get_proactive_dialogue",
    "get_context_awareness",
    "get_auto_execution",
    "get_trigger_system",
]
