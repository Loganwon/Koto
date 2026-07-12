# -*- coding: utf-8 -*-
"""Explicit file-context reading phase for the whitebox task runtime."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List

from app.core.agent._file_task_stepwise_helpers import (
    file_task_suffix as _file_task_suffix,
    looks_like_windowed_pdf_task as _looks_like_windowed_pdf_task,
    pdf_context_read_args as _pdf_context_read_args,
    pdf_text_quality as _pdf_text_quality,
    should_force_pdf_tool_read as _should_force_pdf_tool_read,
)
from app.core.agent.file_task_contract import FileTaskEvent
from app.core.agent.file_task_runtime_utils import _is_error_result, _preview
from app.core.agent.file_task_workflow_state import (
    supervisor_status_payload,
    window_read_args_for_file,
)

logger = logging.getLogger(__name__)


@dataclass
class FileTaskContextReadResult:
    cancelled: bool
    snippets: List[Dict[str, Any]]


class FileTaskContextReadPhase:
    """Read only explicit task context through a FileTaskRuntime port."""

    def __init__(self, runtime: Any):
        self._runtime = runtime

    def stream(
        self,
        *,
        ledger: Any,
        request: Any,
        context_files: List[Any],
        recipe_skeleton: Dict[str, Any],
        workflow_state: Dict[str, Any],
        executor: Any,
        read_limit: int,
    ) -> Iterable[FileTaskEvent]:
        runtime = self._runtime
        snippets: List[Dict[str, Any]] = []

        def _result(*, cancelled: bool = False) -> FileTaskContextReadResult:
            return FileTaskContextReadResult(cancelled=cancelled, snippets=snippets)
        context_step_id = "context"
        if runtime._is_cancelled(request):
            yield runtime._cancelled_event(ledger, request)
            return _result(cancelled=True)
        yield ledger.event(
            "step.started",
            {
                "title": "读取显式上下文",
                "detail": "只使用用户附加、选中或明确指向的文件。",
            },
            step_id=context_step_id,
        )

        snippets = []
        if request.selection:
            snippets.append(
                {
                    "source": request.selection_source or "selection",
                    "preview": _preview(request.selection, 500),
                    "chars": len(request.selection),
                }
            )
            yield ledger.event(
                "tool.finished",
                {
                    "tool_name": "selection_context",
                    "success": True,
                    "result_preview": _preview(request.selection, 500),
                },
                step_id=context_step_id,
            )

        for file_info in context_files:
            if runtime._is_cancelled(request):
                yield runtime._cancelled_event(ledger, request)
                return _result(cancelled=True)
            if runtime._should_skip_uncreated_target_context(request, file_info):
                continue
            if (
                _looks_like_windowed_pdf_task(request, recipe_skeleton)
                and file_info.target
                and _file_task_suffix(file_info) in {"doc", "docx"}
            ):
                continue
            force_pdf_tool_read = _should_force_pdf_tool_read(
                request, file_info, recipe_skeleton
            )
            if file_info.content and not force_pdf_tool_read:
                snippets.append(
                    {
                        "source": file_info.name or file_info.path,
                        "path": file_info.path,
                        "preview": _preview(file_info.content, 500),
                        "chars": len(file_info.content),
                    }
                )
                yield ledger.event(
                    "tool.finished",
                    {
                        "tool_name": "provided_file_context",
                        "success": True,
                        "path": file_info.path,
                        "result_preview": _preview(file_info.content, 500),
                    },
                    step_id=context_step_id,
                )
                continue

            if not file_info.path:
                continue
            window_args = window_read_args_for_file(
                workflow_state,
                file_info,
                default_max_chars=read_limit,
            )
            args = window_args or (
                _pdf_context_read_args(request, file_info, recipe_skeleton)
                if force_pdf_tool_read
                else {"path": file_info.path, "max_chars": read_limit}
            )
            yield ledger.event(
                "tool.started",
                {
                    "tool_name": "parse_file_to_text",
                    "tool_args": args,
                },
                step_id=context_step_id,
            )
            try:
                result = executor("parse_file_to_text", args)
                success = not _is_error_result(result)
                if (
                    success
                    and force_pdf_tool_read
                    and args.get("start_page")
                    and not _pdf_text_quality(result).get("usable")
                ):
                    window_pages = max(
                        1,
                        int(args.get("end_page") or args.get("start_page") or 1)
                        - int(args.get("start_page") or 1)
                        + 1,
                    )
                    for _retry_index in range(3):
                        retry_args = dict(args)
                        retry_start = int(retry_args.get("start_page") or 1) + (
                            window_pages * (_retry_index + 1)
                        )
                        retry_args["start_page"] = retry_start
                        retry_args["end_page"] = retry_start + window_pages - 1
                        retry_result = executor("parse_file_to_text", retry_args)
                        if _is_error_result(retry_result):
                            continue
                        if _pdf_text_quality(retry_result).get("usable"):
                            args = retry_args
                            result = retry_result
                            success = True
                            break
            except Exception as exc:
                result = str(exc)
                success = False
                logger.warning("[FileTaskRuntime] parse_file_to_text failed: %s", exc)
            yield ledger.event(
                "tool.finished",
                {
                    "tool_name": "parse_file_to_text",
                    "success": success,
                    "result_preview": _preview(result),
                },
                step_id=context_step_id,
            )
            if success:
                snippet = {
                    "source": file_info.name or file_info.path,
                    "path": file_info.path,
                    "preview": _preview(result, 500),
                    "chars": len(str(result or "")),
                }
                if str(Path(str(file_info.path or "")).suffix).lower() == ".pdf":
                    if args.get("start_page"):
                        snippet["start_page"] = int(args.get("start_page") or 1)
                    if args.get("end_page"):
                        snippet["end_page"] = int(args.get("end_page") or 0)
                    snippet["_raw_text"] = str(result or "")
                window_unit = str(args.get("window_unit") or "").strip()
                if window_unit:
                    snippet["window_unit"] = window_unit
                    if args.get("start"):
                        snippet["window_start"] = int(args.get("start") or 1)
                    if args.get("end"):
                        snippet["window_end"] = int(args.get("end") or 0)
                    if "sheet_index" in args:
                        snippet["sheet_index"] = int(args.get("sheet_index") or 0)
                snippets.append(snippet)

        context_summary = (
            f"已整理 {len(snippets)} 份上下文片段。" if snippets else "没有显式文件或选区可读取。"
        )
        yield ledger.event(
            "step.finished",
            {
                "summary": context_summary,
            },
            step_id=context_step_id,
        )
        yield ledger.event(
            "step.result",
            runtime._build_step_result_payload(
                title="读取显式上下文",
                summary=context_summary,
                status="completed" if snippets else "needs_attention",
                snippet_count=len(snippets),
                snippets=snippets,
            ),
            step_id=context_step_id,
        )
        yield ledger.event(
            "supervisor.status",
            supervisor_status_payload(
                workflow_state,
                stage="reading",
                summary=context_summary,
                active_step_id="model_reasoning",
                completed_step_ids=["read_context"],
            ),
            step_id=context_step_id,
        )

        return _result()
