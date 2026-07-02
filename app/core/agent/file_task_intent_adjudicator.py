from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List

from app.core.agent.file_task_contract import (
    FileTaskClassification,
    FileTaskFile,
    FileTaskRequest,
)
from app.core.agent.file_task_decision_context import trusted_file_task_routing_decision
from app.core.agent.file_task_intent_adjudication import (
    intent_adjudicator_messages,
    intent_adjudicator_system_prompt,
    normalize_intent_adjudication_response,
)
from app.core.agent.file_task_runtime_utils import _preview

ShouldAdjudicate = Callable[[FileTaskRequest, List[FileTaskFile], FileTaskClassification], bool]
ModelCaller = Callable[..., Dict[str, Any]]


def request_without_default_intent_adjudicator(
    request: FileTaskRequest,
) -> FileTaskRequest:
    options = dict(request.options or {}) if isinstance(request.options, dict) else {}
    options.pop("enable_ai_intent_adjudicator", None)
    return FileTaskRequest(
        task=request.task,
        run_id=request.run_id,
        session_id=request.session_id,
        files=list(request.files),
        current_file=request.current_file,
        selection=request.selection,
        selection_source=request.selection_source,
        target_path=request.target_path,
        model_mode=request.model_mode,
        model_id=request.model_id,
        history=list(request.history),
        options=options,
        routing_decision=request.routing_decision,
    )


def should_adjudicate_trusted_route(
    request: FileTaskRequest,
    files: List[FileTaskFile],
    classification: FileTaskClassification,
    *,
    should_adjudicate: ShouldAdjudicate,
) -> bool:
    route_probe = request_without_default_intent_adjudicator(request)
    return should_adjudicate(route_probe, files, classification)


def trusted_route_adjudication_payload(request: FileTaskRequest) -> Dict[str, Any]:
    trusted_route = trusted_file_task_routing_decision(request)
    if trusted_route is None:
        return {}
    return {
        "source": "workspace_route_decision",
        "status": "trusted_file_task_route",
        "route": trusted_route.route,
        "route_kind": trusted_route.route_kind,
        "task_type": trusted_route.task_type,
        "confidence": trusted_route.confidence,
        "reason": trusted_route.reason,
    }


def task_classifier_fast_path(request: FileTaskRequest) -> Dict[str, Any]:
    try:
        from app.core.routing.task_classifier import TaskClassifier

        tc_type, tc_conf = TaskClassifier.classify(str(request.task)[:500])
    except Exception:
        return {}
    if tc_conf > 0.80 and tc_type not in ("CHAT",):
        return {
            "source": "task_classifier_fast_path",
            "adjudicated_type": tc_type,
            "confidence": tc_conf,
            "reason": "high-confidence ML classification",
        }
    return {}


def adjudicate_intent_if_needed(
    *,
    request: FileTaskRequest,
    files: List[FileTaskFile],
    classification: FileTaskClassification,
    should_adjudicate: ShouldAdjudicate,
    call_model: ModelCaller,
    logger: logging.Logger,
) -> Dict[str, Any]:
    trusted_route = trusted_file_task_routing_decision(request)
    if trusted_route is not None and not should_adjudicate_trusted_route(
        request,
        files,
        classification,
        should_adjudicate=should_adjudicate,
    ):
        return trusted_route_adjudication_payload(request)

    if trusted_route is None:
        fast_path = task_classifier_fast_path(request)
        if fast_path:
            return fast_path

    if not should_adjudicate(request, files, classification):
        return {}
    try:
        response = call_model(
            request=request,
            messages=intent_adjudicator_messages(request, files, classification),
            system=intent_adjudicator_system_prompt(),
            tools=[],
        )
    except Exception as exc:
        logger.warning("[FileTaskRuntime] intent adjudicator unavailable: %s", exc)
        return {
            "source": "ai_intent_adjudicator",
            "status": "unavailable",
            "error": _preview(str(exc), 240),
        }

    return normalize_intent_adjudication_response(response)
