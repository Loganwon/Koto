# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary

from web.lazy_loaders.registry import _lazy_cache


def get_behavior_monitor():
    from web.lazy_loaders.registry import _lazy_load
    return _lazy_load("behavior_monitor", "behavior_monitor", "BehaviorMonitor")


def get_suggestion_engine():
    from web.lazy_loaders.registry import _lazy_load
    return _lazy_load("suggestion_engine", "suggestion_engine", "SuggestionEngine")


def get_insight_reporter():
    from web.lazy_loaders.registry import _lazy_load
    return _lazy_load("insight_reporter", "insight_reporter", "InsightReporter")


def get_notification_manager():
    if "notification_manager" not in _lazy_cache:
        try:
            from app.core.services.notification_manager import get_notification_manager as _get_mgr
        except ImportError:
            from notification_manager import get_notification_manager as _get_mgr
        _lazy_cache["notification_manager"] = _get_mgr()
    return _lazy_cache["notification_manager"]


def get_proactive_dialogue():
    if "proactive_dialogue" not in _lazy_cache:
        try:
            from web.proactive_dialogue import get_proactive_dialogue_engine
        except ImportError:
            from proactive_dialogue import get_proactive_dialogue_engine
        _lazy_cache["proactive_dialogue"] = get_proactive_dialogue_engine(
            notification_manager=get_notification_manager(),
            behavior_monitor=get_behavior_monitor(),
            suggestion_engine=get_suggestion_engine(),
        )
    return _lazy_cache["proactive_dialogue"]


def get_context_awareness():
    if "context_awareness" not in _lazy_cache:
        try:
            from web.context_awareness import get_context_awareness_system
        except ImportError:
            from context_awareness import get_context_awareness_system
        _lazy_cache["context_awareness"] = get_context_awareness_system(
            behavior_monitor=get_behavior_monitor()
        )
    return _lazy_cache["context_awareness"]


def get_auto_execution():
    if "auto_execution" not in _lazy_cache:
        try:
            from web.auto_execution import get_auto_execution_engine
        except ImportError:
            from auto_execution import get_auto_execution_engine
        _lazy_cache["auto_execution"] = get_auto_execution_engine(
            notification_manager=get_notification_manager()
        )
    return _lazy_cache["auto_execution"]


def get_trigger_system():
    import logging
    _app_logger = logging.getLogger("koto.app")

    if "trigger_system" not in _lazy_cache:
        try:
            from web.proactive_trigger import get_trigger_system as _get_trigger_system
        except ImportError:
            from proactive_trigger import get_trigger_system as _get_trigger_system
        _lazy_cache["trigger_system"] = _get_trigger_system(
            behavior_monitor=get_behavior_monitor(),
            context_awareness=get_context_awareness(),
            suggestion_engine=get_suggestion_engine(),
            notification_manager=get_notification_manager(),
            dialogue_engine=get_proactive_dialogue(),
        )
        try:
            _lazy_cache["trigger_system"].start_monitoring(check_interval=300)
        except Exception as _tse:
            _app_logger.warning(f"[TriggerSystem] start_monitoring 失败（非致命）: {_tse}")
    return _lazy_cache["trigger_system"]
