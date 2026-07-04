# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

from app.core.agent.file_task_contract import (
    FileTaskEvent,
    FileTaskLedger,
    FileTaskRequest,
)


class FileTaskDocAnnotateRunner:
    def __init__(self, runtime: Any) -> None:
        self._runtime = runtime

    def stream_bridge_execution(
        self,
        ledger: FileTaskLedger,
        request: FileTaskRequest,
        *,
        classification_payload: Dict[str, Any],
        intent_plan_payload: Dict[str, Any],
        requirements_payload: Dict[str, Any],
        plan_check_payload: Dict[str, Any],
        recipe_skeleton: Dict[str, Any],
        completion_contract_payload: Dict[str, Any],
        workflow_state: Dict[str, Any],
        constraint_audit: Dict[str, Any],
        quick_action_mode: str,
    ) -> Iterable[FileTaskEvent]:
        from app.core.agent import file_task_doc_annotate_boundary

        terminal_event: Optional[FileTaskEvent] = None
        for bridge_event in file_task_doc_annotate_boundary.stream_bridge_request(
            request,
            workspace_root=self._runtime._workspace_root,
            gemini_client=self._runtime._gemini_client,
        ):
            if self._runtime._is_cancelled(request):
                yield self._runtime._cancelled_event(ledger, request)
                return

            payload = (
                dict(bridge_event.payload)
                if isinstance(bridge_event.payload, dict)
                else {}
            )
            if bridge_event.type in {"run.started", "plan.created"}:
                continue
            if bridge_event.type == "run.finished":
                payload.update(
                    {
                        "mode": "whitebox_v1",
                        "execution_mode": "doc_annotate_bridge",
                        "task": request.task,
                        "quick_action_mode": quick_action_mode,
                        "intent_plan": intent_plan_payload,
                        "requirements": requirements_payload,
                        "plan_check": plan_check_payload,
                        "recipe_skeleton": recipe_skeleton,
                        "completion_contract": completion_contract_payload,
                        "workflow_state": workflow_state,
                        "constraint_audit": constraint_audit,
                        **classification_payload,
                    }
                )
                terminal_event = ledger.event(
                    "run.finished",
                    payload,
                    step_id=bridge_event.step_id,
                )
                continue
            if bridge_event.type == "run.error":
                payload.setdefault("execution_mode", "doc_annotate_bridge")
                terminal_event = ledger.event(
                    "run.error",
                    payload,
                    step_id=bridge_event.step_id,
                )
                continue
            yield ledger.event(
                bridge_event.type,
                payload,
                step_id=bridge_event.step_id,
            )

        if terminal_event is not None:
            yield terminal_event


__all__ = ["FileTaskDocAnnotateRunner"]
