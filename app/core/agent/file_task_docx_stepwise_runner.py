from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Protocol

from app.core.agent.file_task_contract import (
    FileTaskClassification,
    FileTaskEvent,
    FileTaskFile,
    FileTaskIntentPlan,
    FileTaskLedger,
    FileTaskRequest,
)
from app.core.agent.file_task_docx_stepwise import (
    docx_polish_wait_artifact,
    docx_polish_window_prompt,
    parse_polished_docx_paragraphs,
    read_docx_paragraph_window,
    rewrite_docx_paragraph_window,
    simple_polish_docx_paragraph,
    stepwise_docx_polish_target_path,
)
from app.core.agent.file_task_runtime_utils import _preview

logger = logging.getLogger(__name__)

DOCX_STEPWISE_AWAITING_SUMMARY = "当前步骤已写入 DOCX，等待用户说“继续”后处理下一段。"
DOCX_STEPWISE_CHECK_SUMMARY = "当前段落窗口已写回 DOCX，等待用户说“继续”后处理下一段。"
DOCX_STEPWISE_CONTEXT_STEP_ID = "context"
DOCX_STEPWISE_EXECUTE_STEP_ID = "execute"
DOCX_STEPWISE_CHECK_STEP_ID = "check"
DOCX_STEPWISE_READ_TITLE = "读取当前 DOCX 段落窗口"
DOCX_STEPWISE_WRITE_TITLE = "润色并写回当前段落"
DOCX_STEPWISE_READ_DETAIL = "按段落窗口读取 Word 当前步骤内容，不一次性润色全文。"
DOCX_STEPWISE_WRITE_DETAIL = "只处理当前段落窗口，保留文档其他内容。"


@dataclass(frozen=True)
class DocxStepwisePayloadContext:
    request: FileTaskRequest
    quick_action_mode: str
    intent_plan_payload: Dict[str, Any]
    requirements_payload: Dict[str, Any]
    plan_check_payload: Dict[str, Any]
    recipe_skeleton: Dict[str, Any]
    constraint_audit: Dict[str, Any]
    classification_payload: Dict[str, Any]


@dataclass(frozen=True)
class DocxStepwiseRunContext:
    payload_context: DocxStepwisePayloadContext
    target_path: str | None
    file_changes: List[Dict[str, Any]]


@dataclass(frozen=True)
class DocxStepwiseReadResult:
    window: Dict[str, Any] | None
    events: List[FileTaskEvent]
    terminal: bool


@dataclass(frozen=True)
class DocxStepwisePolishResult:
    paragraphs: List[str]
    model_failed: bool


@dataclass(frozen=True)
class DocxStepwiseWriteResult:
    change: Dict[str, Any]
    changed_count: int


def _docx_stepwise_run_finished_payload(
    *,
    payload_context: DocxStepwisePayloadContext,
    summary: str,
    completed_task: bool,
    runtime_payload: Dict[str, Any],
    context: List[Dict[str, Any]] | None = None,
    file_changes: List[Dict[str, Any]] | None = None,
    next_action_artifact: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "task": payload_context.request.task,
        "mode": "whitebox_v1",
        "summary": summary,
        "completed_task": completed_task,
        "context": context or [],
        "file_changes": file_changes or [],
        "runtime": runtime_payload,
        "quick_action_mode": payload_context.quick_action_mode,
        "intent_plan": payload_context.intent_plan_payload,
        "requirements": payload_context.requirements_payload,
        "plan_check": payload_context.plan_check_payload,
        "recipe_skeleton": payload_context.recipe_skeleton,
        "constraint_audit": payload_context.constraint_audit,
        **payload_context.classification_payload,
    }
    if next_action_artifact is not None:
        payload["next_action_artifact"] = next_action_artifact
    return payload


def _docx_stepwise_terminal_event(
    runtime: DocxStepwiseRuntimePort,
    ledger: FileTaskLedger,
    *,
    payload_context: DocxStepwisePayloadContext,
    summary: str,
    terminal_status: str,
    completed_task: bool,
    context: List[Dict[str, Any]] | None = None,
) -> FileTaskEvent:
    runtime_payload = runtime._build_runtime_metadata(
        terminal_status=terminal_status,
        readonly_fallback_used=False,
        model_failed=False,
    )
    return ledger.event(
        "run.finished",
        _docx_stepwise_run_finished_payload(
            payload_context=payload_context,
            summary=summary,
            completed_task=completed_task,
            context=context,
            runtime_payload=runtime_payload,
        ),
    )


def _docx_stepwise_step_started_payload(title: str, detail: str) -> Dict[str, Any]:
    return {"title": title, "detail": detail}


def _docx_stepwise_run_context(
    *,
    request: FileTaskRequest,
    context_files: List[FileTaskFile],
    quick_action_mode: str,
    intent_plan_payload: Dict[str, Any],
    requirements_payload: Dict[str, Any],
    plan_check_payload: Dict[str, Any],
    recipe_skeleton: Dict[str, Any],
    constraint_audit: Dict[str, Any],
    classification_payload: Dict[str, Any],
) -> DocxStepwiseRunContext:
    return DocxStepwiseRunContext(
        payload_context=DocxStepwisePayloadContext(
            request=request,
            quick_action_mode=quick_action_mode,
            intent_plan_payload=intent_plan_payload,
            requirements_payload=requirements_payload,
            plan_check_payload=plan_check_payload,
            recipe_skeleton=recipe_skeleton,
            constraint_audit=constraint_audit,
            classification_payload=classification_payload,
        ),
        target_path=stepwise_docx_polish_target_path(request, context_files),
        file_changes=[],
    )


class DocxStepwiseRuntimePort(Protocol):
    def _build_runtime_metadata(self, **kwargs: Any) -> Dict[str, Any]: ...

    def _build_step_result_payload(self, **kwargs: Any) -> Dict[str, Any]: ...

    def _call_model(self, **kwargs: Any) -> Dict[str, Any]: ...

    def _normalize_model_response(
        self, response: Any, tool_defs: List[Dict[str, Any]]
    ) -> tuple[str, List[Dict[str, Any]]]: ...

    def _evaluate_task_quality_gate(
        self,
        request: FileTaskRequest,
        file_changes: List[Dict[str, Any]],
        *,
        write_intent: bool,
        output_mode: str,
    ) -> Dict[str, Any]: ...


def _docx_stepwise_read_step_result_payload(
    runtime: DocxStepwiseRuntimePort,
    *,
    target_path: str,
    window: Dict[str, Any],
) -> Dict[str, Any]:
    paragraph_text = "\n".join(window["paragraphs"])
    return runtime._build_step_result_payload(
        title="读取当前 DOCX 段落窗口",
        summary=(
            f"已读取第 {window['start_visible_index'] + 1}-"
            f"{window['end_visible_index']} 个非空段落。"
        ),
        status="completed",
        snippet_count=1,
        snippets=[
            {
                "source": Path(target_path).name,
                "path": target_path,
                "preview": _preview(paragraph_text, 500),
                "paragraph_start": window["start_visible_index"] + 1,
                "paragraph_end": window["end_visible_index"],
            }
        ],
    )


def _docx_stepwise_quality_check_payload(
    runtime: DocxStepwiseRuntimePort,
    *,
    request: FileTaskRequest,
    file_changes: List[Dict[str, Any]],
    runtime_payload: Dict[str, Any],
    next_action_artifact: Dict[str, Any],
) -> Dict[str, Any]:
    check_payload = runtime._evaluate_task_quality_gate(
        request,
        file_changes,
        write_intent=True,
        output_mode="write",
    )
    check_payload.update(
        {
            "status": "awaiting_confirmation",
            "summary": DOCX_STEPWISE_CHECK_SUMMARY,
            "next_action_artifact": next_action_artifact,
            "runtime": runtime_payload,
        }
    )
    return check_payload


def _docx_stepwise_write_step_result_payload(
    runtime: DocxStepwiseRuntimePort,
    *,
    change: Dict[str, Any],
    file_changes: List[Dict[str, Any]],
    runtime_payload: Dict[str, Any],
    next_action_artifact: Dict[str, Any],
) -> Dict[str, Any]:
    return runtime._build_step_result_payload(
        title="润色并写回当前段落",
        summary=change["summary"],
        status="completed",
        file_changes=file_changes,
        runtime=runtime_payload,
        next_action_artifact=next_action_artifact,
    )


def _docx_stepwise_check_step_result_payload(
    runtime: DocxStepwiseRuntimePort,
    *,
    file_changes: List[Dict[str, Any]],
    runtime_payload: Dict[str, Any],
    check_payload: Dict[str, Any],
    next_action_artifact: Dict[str, Any],
) -> Dict[str, Any]:
    awaiting_summary = DOCX_STEPWISE_AWAITING_SUMMARY
    return runtime._build_step_result_payload(
        title="核验结果",
        summary=awaiting_summary,
        status="awaiting_confirmation",
        file_changes=file_changes,
        runtime=runtime_payload,
        passed=bool(check_payload.get("passed")),
        next_action_artifact=next_action_artifact,
    )


def _docx_stepwise_read_failed_tool_payload(
    *,
    target_path: str,
    summary: str,
) -> Dict[str, Any]:
    return {
        "tool_name": "read_docx_content",
        "success": False,
        "path": target_path,
        "result_preview": summary,
    }


def _docx_stepwise_read_tool_payload(
    *,
    target_path: str,
    window: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "tool_name": "read_docx_content",
        "success": True,
        "path": target_path,
        "result_preview": _preview("\n".join(window["paragraphs"]), 900),
        "paragraph_start": window["start_visible_index"] + 1,
        "paragraph_end": window["end_visible_index"],
    }


def _docx_stepwise_write_change_payload(
    *,
    target_path: str,
    window: Dict[str, Any],
    changed_count: int,
) -> Dict[str, Any]:
    return {
        "path": target_path,
        "file_type": "docx",
        "operation": "rewrite_docx_paragraph_window",
        "summary": (
            f"已润色并写回第 {window['start_visible_index'] + 1}-"
            f"{window['end_visible_index']} 个非空段落。"
        ),
        "paragraphs_rewritten": changed_count,
        "paragraph_start": window["start_visible_index"] + 1,
        "paragraph_end": window["end_visible_index"],
        "change_type": "modify",
        "focus": True,
    }


def _docx_stepwise_write_tool_payload(
    *,
    change: Dict[str, Any],
    changed_count: int,
) -> Dict[str, Any]:
    return {
        "tool_name": "rewrite_docx_paragraph_window",
        "success": changed_count > 0,
        "path": change["path"],
        "result_preview": change["summary"],
        "paragraphs_rewritten": changed_count,
    }


def _docx_stepwise_read_window(
    runtime: DocxStepwiseRuntimePort,
    ledger: FileTaskLedger,
    *,
    request: FileTaskRequest,
    run_context: DocxStepwiseRunContext,
) -> DocxStepwiseReadResult:
    events = [
        ledger.event(
            "step.started",
            _docx_stepwise_step_started_payload(
                DOCX_STEPWISE_READ_TITLE,
                DOCX_STEPWISE_READ_DETAIL,
            ),
            step_id=DOCX_STEPWISE_CONTEXT_STEP_ID,
        )
    ]
    target_path = run_context.target_path
    if not target_path or not Path(target_path).exists():
        events.append(
            _docx_stepwise_terminal_event(
                runtime,
                ledger,
                payload_context=run_context.payload_context,
                summary="未找到可写回的 DOCX 文件，无法执行分步润色。",
                terminal_status="failed",
                completed_task=False,
            )
        )
        return DocxStepwiseReadResult(window=None, events=events, terminal=True)

    try:
        window = read_docx_paragraph_window(request, target_path)
    except Exception as exc:
        summary = f"读取 DOCX 段落失败：{exc}"
        events.append(
            ledger.event(
                "tool.finished",
                _docx_stepwise_read_failed_tool_payload(
                    target_path=target_path,
                    summary=summary,
                ),
                step_id=DOCX_STEPWISE_CONTEXT_STEP_ID,
            )
        )
        events.append(
            _docx_stepwise_terminal_event(
                runtime,
                ledger,
                payload_context=run_context.payload_context,
                summary=summary,
                terminal_status="failed",
                completed_task=False,
            )
        )
        return DocxStepwiseReadResult(window=None, events=events, terminal=True)

    if not window["paragraphs"]:
        events.append(
            _docx_stepwise_terminal_event(
                runtime,
                ledger,
                payload_context=run_context.payload_context,
                summary="当前 DOCX 没有可润色的剩余段落。",
                terminal_status="verified",
                completed_task=True,
                context=[window],
            )
        )
        return DocxStepwiseReadResult(window=window, events=events, terminal=True)

    events.extend(
        [
            ledger.event(
                "tool.finished",
                _docx_stepwise_read_tool_payload(
                    target_path=target_path,
                    window=window,
                ),
                step_id=DOCX_STEPWISE_CONTEXT_STEP_ID,
            ),
            ledger.event(
                "step.result",
                _docx_stepwise_read_step_result_payload(
                    runtime,
                    target_path=target_path,
                    window=window,
                ),
                step_id=DOCX_STEPWISE_CONTEXT_STEP_ID,
            ),
        ]
    )
    return DocxStepwiseReadResult(window=window, events=events, terminal=False)


def _docx_stepwise_polished_paragraphs(
    runtime: DocxStepwiseRuntimePort,
    *,
    request: FileTaskRequest,
    window: Dict[str, Any],
) -> DocxStepwisePolishResult:
    model_failed = False
    polished: List[str] = []
    try:
        response = runtime._call_model(
            request=request,
            messages=[
                {
                    "role": "user",
                    "content": docx_polish_window_prompt(
                        request, window["paragraphs"]
                    ),
                }
            ],
            system=(
                "你是严谨的中文文档润色助手。只润色用户给出的段落窗口，"
                "保持原意、术语和段落数量；不要扩写成总结，不要添加解释。"
            ),
            tools=[],
        )
        content, _tool_calls = runtime._normalize_model_response(response, [])
        polished = parse_polished_docx_paragraphs(
            content, expected_count=len(window["paragraphs"])
        )
    except Exception as exc:
        model_failed = True
        logger.warning("[FileTaskRuntime] stepwise DOCX polish model failed: %s", exc)

    if not polished:
        polished = [
            simple_polish_docx_paragraph(text)
            for text in window["paragraphs"]
        ]
    return DocxStepwisePolishResult(
        paragraphs=polished,
        model_failed=model_failed,
    )


def _docx_stepwise_writeback(
    *,
    target_path: str,
    window: Dict[str, Any],
    paragraphs: List[str],
) -> DocxStepwiseWriteResult:
    changed_count = rewrite_docx_paragraph_window(
        target_path,
        window["paragraph_indices"],
        paragraphs,
    )
    change = _docx_stepwise_write_change_payload(
        target_path=target_path,
        window=window,
        changed_count=changed_count,
    )
    return DocxStepwiseWriteResult(
        change=change,
        changed_count=changed_count,
    )


class FileTaskDocxStepwiseRunner:
    def __init__(self, runtime: DocxStepwiseRuntimePort) -> None:
        self._runtime = runtime

    def stream_polish_writeback(
        self,
        ledger: FileTaskLedger,
        request: FileTaskRequest,
        context_files: List[FileTaskFile],
        classification: FileTaskClassification,
        intent_plan: FileTaskIntentPlan,
        requirements_payload: Dict[str, Any],
        plan_check_payload: Dict[str, Any],
        recipe_skeleton: Dict[str, Any],
        constraint_audit: Dict[str, Any],
        quick_action_mode: str,
        classification_payload: Dict[str, Any],
        intent_plan_payload: Dict[str, Any],
    ) -> Iterable[FileTaskEvent]:
        del classification, intent_plan
        runtime = self._runtime
        run_context = _docx_stepwise_run_context(
            request=request,
            context_files=context_files,
            quick_action_mode=quick_action_mode,
            intent_plan_payload=intent_plan_payload,
            requirements_payload=requirements_payload,
            plan_check_payload=plan_check_payload,
            recipe_skeleton=recipe_skeleton,
            constraint_audit=constraint_audit,
            classification_payload=classification_payload,
        )

        read_result = _docx_stepwise_read_window(
            runtime,
            ledger,
            request=request,
            run_context=run_context,
        )
        for event in read_result.events:
            yield event
        if read_result.terminal or read_result.window is None:
            return
        window = read_result.window

        yield ledger.event(
            "step.started",
            _docx_stepwise_step_started_payload(
                DOCX_STEPWISE_WRITE_TITLE,
                DOCX_STEPWISE_WRITE_DETAIL,
            ),
            step_id=DOCX_STEPWISE_EXECUTE_STEP_ID,
        )

        polish_result = _docx_stepwise_polished_paragraphs(
            runtime,
            request=request,
            window=window,
        )

        write_result = _docx_stepwise_writeback(
            target_path=run_context.target_path,
            window=window,
            paragraphs=polish_result.paragraphs,
        )
        change = write_result.change
        run_context.file_changes.append(change)
        yield ledger.event(
            "tool.finished",
            _docx_stepwise_write_tool_payload(
                change=change,
                changed_count=write_result.changed_count,
            ),
            step_id=DOCX_STEPWISE_EXECUTE_STEP_ID,
        )
        yield ledger.event(
            "file.changed", change, step_id=DOCX_STEPWISE_EXECUTE_STEP_ID
        )

        next_artifact = docx_polish_wait_artifact(
            request, run_context.target_path, window
        )
        runtime_payload = runtime._build_runtime_metadata(
            terminal_status="awaiting_confirmation",
            readonly_fallback_used=False,
            model_failed=polish_result.model_failed,
        )
        check_payload = _docx_stepwise_quality_check_payload(
            runtime,
            request=request,
            file_changes=run_context.file_changes,
            runtime_payload=runtime_payload,
            next_action_artifact=next_artifact,
        )

        yield ledger.event(
            "step.result",
            _docx_stepwise_write_step_result_payload(
                runtime,
                change=change,
                file_changes=run_context.file_changes,
                runtime_payload=runtime_payload,
                next_action_artifact=next_artifact,
            ),
            step_id=DOCX_STEPWISE_EXECUTE_STEP_ID,
        )
        yield ledger.event(
            "check.completed",
            check_payload,
            step_id=DOCX_STEPWISE_CHECK_STEP_ID,
        )
        yield ledger.event(
            "step.result",
            _docx_stepwise_check_step_result_payload(
                runtime,
                file_changes=run_context.file_changes,
                runtime_payload=runtime_payload,
                check_payload=check_payload,
                next_action_artifact=next_artifact,
            ),
            step_id=DOCX_STEPWISE_CHECK_STEP_ID,
        )
        yield ledger.event(
            "run.finished",
            _docx_stepwise_run_finished_payload(
                payload_context=run_context.payload_context,
                summary=DOCX_STEPWISE_AWAITING_SUMMARY,
                completed_task=True,
                context=[window],
                file_changes=run_context.file_changes,
                runtime_payload=runtime_payload,
                next_action_artifact=next_artifact,
            ),
        )
