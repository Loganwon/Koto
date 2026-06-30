# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence

from app.core.agent._file_task_stepwise_helpers import (
    looks_like_windowed_pdf_task,
    stepwise_docx_polish_step_index,
    stepwise_docx_polish_window_paragraphs,
    stepwise_pdf_step_index,
    stepwise_pdf_window_pages,
)
from app.core.agent.file_task_checkpoint_options import workflow_checkpoint_from_options
from app.core.agent.file_task_contract import (
    FileTaskClassification,
    FileTaskFile,
    FileTaskRequest,
)
from app.core.agent.file_task_tool_catalog import is_write_tool


def _file_type(file_info: FileTaskFile) -> str:
    explicit = str(getattr(file_info, "type", "") or "").strip().lower().lstrip(".")
    if explicit:
        return explicit
    return Path(str(file_info.path or file_info.name or "")).suffix.lower().lstrip(".")


def _file_ref(file_info: FileTaskFile) -> Dict[str, Any]:
    return {
        "path": file_info.path,
        "name": file_info.name or Path(str(file_info.path or "")).name,
        "type": _file_type(file_info),
        "target": bool(file_info.target),
    }


def _clean_text(value: Any, limit: int = 0) -> str:
    text = str(value or "").strip()
    if limit and len(text) > limit:
        return text[: limit - 3] + "..."
    return text


def _options(request: FileTaskRequest) -> Dict[str, Any]:
    return dict(request.options or {}) if isinstance(request.options, dict) else {}


def _workflow_resume_options(request: FileTaskRequest) -> Dict[str, Any]:
    return workflow_checkpoint_from_options(_options(request))


def workflow_resume_control(request: FileTaskRequest) -> Dict[str, Any]:
    return _workflow_resume_options(request)


def _workflow_checkpoint(
    request: FileTaskRequest,
    classification: FileTaskClassification,
) -> Dict[str, Any]:
    resume_control = _workflow_resume_options(request)
    followup = _options(request).get("followup_context")
    followup_context = dict(followup) if isinstance(followup, dict) else {}
    checkpoint: Dict[str, Any] = {
        "status": "active",
        "policy": str(resume_control.get("policy") or "").strip(),
        "adapter": str(resume_control.get("adapter") or "").strip(),
        "step_index": _int_or_zero(resume_control.get("step_index")),
        "source_path": str(resume_control.get("source_path") or "").strip(),
        "target_path": str(
            resume_control.get("target_path") or request.target_path or ""
        ).strip(),
        "original_task": str(
            resume_control.get("original_task") or request.task or ""
        ).strip(),
        "request_kind": classification.request_kind,
    }
    for key in ("batch_index", "total_batches"):
        if resume_control.get(key) not in ("", None):
            checkpoint[key] = resume_control.get(key)
    if followup_context:
        checkpoint["followup_action"] = str(
            followup_context.get("followup_action") or ""
        ).strip()
        stepwise = followup_context.get("stepwise")
        if isinstance(stepwise, Mapping):
            checkpoint["completed_window"] = str(
                stepwise.get("completed_page_range") or ""
            ).strip()
            checkpoint["next_window"] = str(
                stepwise.get("next_page_range") or ""
            ).strip()
    if not checkpoint["policy"] and not checkpoint["adapter"]:
        checkpoint["status"] = "stateless"
    return {key: value for key, value in checkpoint.items() if value not in ("", None)}


def _int_or_zero(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except Exception:
        return 0


def _pdf_window(request: FileTaskRequest, file_info: FileTaskFile) -> Dict[str, Any]:
    size = stepwise_pdf_window_pages(request)
    step_index = stepwise_pdf_step_index(request)
    start = 1 + step_index * size
    end = start + size - 1
    return {
        "file_type": "pdf",
        "path": file_info.path or file_info.name,
        "unit": "page",
        "window_size": size,
        "step_index": step_index,
        "current": {"start": start, "end": end},
        "next": {"start": end + 1, "end": end + size},
        "strategy": "page_window",
    }


def _docx_window(request: FileTaskRequest, file_info: FileTaskFile) -> Dict[str, Any]:
    size = stepwise_docx_polish_window_paragraphs(request)
    step_index = stepwise_docx_polish_step_index(request)
    start = 1 + step_index * size
    end = start + size - 1
    return {
        "file_type": _file_type(file_info),
        "path": file_info.path or file_info.name,
        "unit": "paragraph",
        "window_size": size,
        "step_index": step_index,
        "current": {"start": start, "end": end},
        "next": {"start": end + 1, "end": end + size},
        "strategy": "paragraph_window",
    }


def _ppt_window(request: FileTaskRequest, file_info: FileTaskFile) -> Dict[str, Any]:
    resume_control = _workflow_resume_options(request)
    try:
        size = max(1, min(int(resume_control.get("window_slides") or 5), 20))
    except Exception:
        size = 5
    step_index = _int_or_zero(resume_control.get("step_index"))
    start = 1 + step_index * size
    end = start + size - 1
    return {
        "file_type": _file_type(file_info),
        "path": file_info.path or file_info.name,
        "unit": "slide",
        "window_size": size,
        "step_index": step_index,
        "current": {"start": start, "end": end},
        "next": {"start": end + 1, "end": end + size},
        "strategy": "slide_window",
    }


def _xlsx_window(request: FileTaskRequest, file_info: FileTaskFile) -> Dict[str, Any]:
    resume_control = _workflow_resume_options(request)
    step_index = _int_or_zero(resume_control.get("step_index"))
    return {
        "file_type": _file_type(file_info),
        "path": file_info.path or file_info.name,
        "unit": "sheet",
        "window_size": 1,
        "step_index": step_index,
        "current": {"sheet_index": step_index},
        "next": {"sheet_index": step_index + 1},
        "strategy": "sheet_window",
    }


def large_file_windows(
    request: FileTaskRequest,
    files: Sequence[FileTaskFile],
    recipe_skeleton: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    windows: List[Dict[str, Any]] = []
    resume_control = _workflow_resume_options(request)
    has_resume_control = bool(resume_control)
    recipe_id = str(recipe_skeleton.get("recipe_id") or "").strip()
    for file_info in files:
        suffix = _file_type(file_info)
        if suffix == "pdf" and (
            has_resume_control
            or looks_like_windowed_pdf_task(request, dict(recipe_skeleton))
        ):
            windows.append(_pdf_window(request, file_info))
        elif suffix in {"doc", "docx"} and (
            has_resume_control or recipe_id == "long_docx_stepwise_polish_writeback"
        ):
            windows.append(_docx_window(request, file_info))
        elif suffix in {"ppt", "pptx"} and has_resume_control:
            windows.append(_ppt_window(request, file_info))
        elif suffix in {"xls", "xlsx", "xlsm"} and has_resume_control:
            windows.append(_xlsx_window(request, file_info))
    return windows


def _step_id(value: Any, fallback: str) -> str:
    text = _clean_text(value, 64)
    if not text:
        text = fallback
    return (
        text.replace(" ", "_")
        .replace(".", "_")
        .replace("/", "_")
        .replace("\\", "_")
        .lower()
    )[:64]


def _stage_for_tool(tool_name: str, *, write_intent: bool) -> str:
    tool = str(tool_name or "").strip()
    if (
        tool == "parse_file_to_text"
        or tool.startswith("read_")
        or tool.startswith("inspect_")
    ):
        return "reading"
    if tool == "verify_task_completion":
        return "verifying"
    if is_write_tool(tool):
        return "writing"
    return "analyzing" if write_intent else "answering"


def _allowed_tools_for_stage(
    stage: str,
    recipe_skeleton: Mapping[str, Any],
) -> List[str]:
    allowed = [
        str(item).strip()
        for item in recipe_skeleton.get("allowed_tools") or []
        if str(item or "").strip()
    ]
    if stage == "reading":
        return [
            item
            for item in allowed
            if item == "parse_file_to_text"
            or item.startswith("read_")
            or item.startswith("inspect_")
        ]
    if stage == "writing":
        write_tools = [item for item in allowed if is_write_tool(item)]
        return write_tools or [
            str(item).strip()
            for item in recipe_skeleton.get("required_tools") or []
            if str(item or "").strip()
        ]
    if stage == "verifying":
        return [item for item in allowed if item == "verify_task_completion"]
    return allowed[:8]


def _append_plan_step(
    steps: List[Dict[str, Any]],
    *,
    step_id: str,
    title: str,
    stage: str,
    required: bool = True,
    expected_result: str = "",
    allowed_tools: Sequence[str] | None = None,
) -> None:
    if any(str(item.get("id") or "") == step_id for item in steps):
        return
    step: Dict[str, Any] = {
        "id": step_id,
        "title": title,
        "stage": stage,
        "required": bool(required),
        "status": "pending",
    }
    tools = [
        str(item).strip() for item in (allowed_tools or []) if str(item or "").strip()
    ]
    if tools:
        step["allowed_tools"] = tools[:12]
    if expected_result:
        step["expected_result"] = expected_result
    steps.append(step)


def build_task_plan(
    request: FileTaskRequest,
    files: Sequence[FileTaskFile],
    classification: FileTaskClassification,
    recipe_skeleton: Mapping[str, Any],
    completion_contract: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    write_intent = bool(classification.write_intent)
    required_steps = [
        dict(step)
        for step in recipe_skeleton.get("required_steps") or []
        if isinstance(step, Mapping)
    ]
    required_tools = [
        str(item).strip()
        for item in recipe_skeleton.get("required_tools") or []
        if str(item or "").strip()
    ]
    steps: List[Dict[str, Any]] = []
    _append_plan_step(
        steps,
        step_id="read_context",
        title="读取显式上下文",
        stage="reading",
        required=True,
        expected_result="读取用户显式提供、选择或点名的文件上下文。",
        allowed_tools=_allowed_tools_for_stage("reading", recipe_skeleton),
    )
    for index, raw_step in enumerate(required_steps[:8], start=1):
        tool = _clean_text(raw_step.get("tool") or raw_step.get("tool_name"), 120)
        raw_id = _step_id(raw_step.get("id"), f"recipe_step_{index}")
        if not tool and raw_id in {"context", "execute", "check"}:
            continue
        stage = _clean_text(raw_step.get("stage"), 40) or _stage_for_tool(
            tool,
            write_intent=write_intent,
        )
        _append_plan_step(
            steps,
            step_id=raw_id,
            title=_clean_text(
                raw_step.get("title") or raw_step.get("name") or raw_step.get("step"),
                160,
            )
            or ("写入目标文件" if stage == "writing" else "执行任务步骤"),
            stage=stage,
            required=bool(raw_step.get("required", True)),
            expected_result=_clean_text(
                raw_step.get("expected_result") or raw_step.get("expected"), 360
            ),
            allowed_tools=(
                [tool] if tool else _allowed_tools_for_stage(stage, recipe_skeleton)
            ),
        )
    _append_plan_step(
        steps,
        step_id="model_reasoning",
        title="分析并选择工具",
        stage="analyzing" if write_intent else "answering",
        required=True,
        expected_result="模型基于上下文和工具目录选择下一步，不让关键词旁路改写主线。",
        allowed_tools=_allowed_tools_for_stage("analyzing", recipe_skeleton),
    )
    if write_intent:
        write_tools = [tool for tool in required_tools if is_write_tool(tool)]
        if not write_tools:
            write_tools = _allowed_tools_for_stage("writing", recipe_skeleton)
        _append_plan_step(
            steps,
            step_id="write_output",
            title="写入目标文件",
            stage="writing",
            required=True,
            expected_result="产生 file.changed 事件和可核验的写入指标。",
            allowed_tools=write_tools,
        )
    _append_plan_step(
        steps,
        step_id="verify_outputs",
        title="核验结果",
        stage="verifying",
        required=True,
        expected_result="检查必需文件变更、质量门和剩余动作。",
        allowed_tools=_allowed_tools_for_stage("verifying", recipe_skeleton),
    )
    file_count_by_type: Dict[str, int] = {}
    for file_info in files:
        suffix = _file_type(file_info)
        if suffix:
            file_count_by_type[suffix] = file_count_by_type.get(suffix, 0) + 1
    return {
        "version": "task_plan_v1",
        "goal": _clean_text(request.task, 800),
        "policy": "model_primary_supervised_mainline",
        "mainline_locked": True,
        "model_controls": "choose_tools_and_arguments_within_allowed_plan",
        "recipe_id": str(recipe_skeleton.get("recipe_id") or "generic_file_task"),
        "write_intent": write_intent,
        "target_path": request.target_path,
        "file_count_by_type": file_count_by_type,
        "steps": steps,
        "completion_contract": dict(
            completion_contract or recipe_skeleton.get("completion_check") or {}
        ),
    }


def build_workflow_state(
    request: FileTaskRequest,
    files: Sequence[FileTaskFile],
    classification: FileTaskClassification,
    recipe_skeleton: Mapping[str, Any],
    completion_contract: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    targets = [_file_ref(item) for item in files if item.target]
    sources = [_file_ref(item) for item in files if not item.target]
    windows = large_file_windows(request, files, recipe_skeleton)
    state: Dict[str, Any] = {
        "version": "file_task_workflow_state_v1",
        "run_id": request.run_id,
        "session_id": request.session_id,
        "mainline": {
            "request_kind": classification.request_kind,
            "task_family": classification.task_family,
            "operation_kind": classification.operation_kind,
            "execution_mode": classification.execution_mode,
            "output_mode": classification.output_mode,
            "write_intent": bool(classification.write_intent),
            "selected_recipe": classification.selected_recipe,
        },
        "files": {
            "sources": sources,
            "targets": targets,
            "all": [_file_ref(item) for item in files],
        },
        "checkpoint": _workflow_checkpoint(request, classification),
        "large_file_windows": windows,
        "task_plan": build_task_plan(
            request,
            files,
            classification,
            recipe_skeleton,
            completion_contract=completion_contract,
        ),
        "reason_codes": [
            "workflow_state:v1",
            *[code for code in classification.reason_codes if str(code or "").strip()],
        ],
    }
    if windows:
        state["reason_codes"].append("unified_large_file_window:v1")
    return state


def supervisor_status_payload(
    workflow_state: Mapping[str, Any],
    *,
    stage: str,
    summary: str = "",
    active_step_id: str = "",
    completed_step_ids: Sequence[str] | None = None,
    file_changes: Sequence[Mapping[str, Any]] | None = None,
    check_payload: Mapping[str, Any] | None = None,
    supervisor_audit: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    task_plan = workflow_state.get("task_plan")
    plan = dict(task_plan) if isinstance(task_plan, Mapping) else {}
    raw_steps = plan.get("steps") if isinstance(plan.get("steps"), list) else []
    completed = {str(item) for item in (completed_step_ids or []) if str(item)}
    if file_changes:
        completed.add("write_output")
    if isinstance(check_payload, Mapping) and check_payload:
        completed.add("verify_outputs")
    updated_steps: List[Dict[str, Any]] = []
    required_total = 0
    required_done = 0
    for raw in raw_steps:
        if not isinstance(raw, Mapping):
            continue
        step = dict(raw)
        step_id = str(step.get("id") or "").strip()
        if bool(step.get("required", True)):
            required_total += 1
        if step_id and step_id in completed:
            step["status"] = "completed"
            if bool(step.get("required", True)):
                required_done += 1
        elif active_step_id and step_id == active_step_id:
            step["status"] = "running"
        else:
            step["status"] = str(step.get("status") or "pending")
        updated_steps.append(step)
    plan["steps"] = updated_steps
    audit_payload = (
        dict(supervisor_audit)
        if isinstance(supervisor_audit, Mapping)
        else (
            dict(workflow_state.get("supervisor_audit") or {})
            if isinstance(workflow_state.get("supervisor_audit"), Mapping)
            else {}
        )
    )
    return {
        "stage": _clean_text(stage, 40) or "planned",
        "summary": _clean_text(summary or audit_payload.get("summary"), 500),
        "mainline_locked": bool(plan.get("mainline_locked", True)),
        "task_plan": plan,
        "completion": {
            "required_completed": required_done,
            "required_total": required_total,
        },
        "workflow_state": dict(workflow_state),
        **({"supervisor_audit": audit_payload} if audit_payload else {}),
    }


def attach_workflow_checkpoint(
    artifact: Dict[str, Any],
    workflow_state: Mapping[str, Any],
) -> Dict[str, Any]:
    if not isinstance(artifact, dict):
        return {}
    payload = dict(artifact)
    checkpoint = workflow_state.get("checkpoint")
    windows = workflow_state.get("large_file_windows")
    if isinstance(checkpoint, Mapping) and checkpoint:
        payload["workflow_checkpoint"] = _resume_checkpoint_from_artifact(
            payload,
            checkpoint,
        )
    if isinstance(windows, list) and windows:
        payload["large_file_windows"] = [
            dict(item) for item in windows if isinstance(item, dict)
        ]
    return payload


def _resume_checkpoint_from_artifact(
    artifact: Mapping[str, Any],
    current_checkpoint: Mapping[str, Any],
) -> Dict[str, Any]:
    checkpoint = dict(current_checkpoint)
    resume_request = artifact.get("resume_request")
    resume_options = (
        resume_request.get("options")
        if isinstance(resume_request, Mapping)
        and isinstance(resume_request.get("options"), Mapping)
        else {}
    )
    resume_control = workflow_checkpoint_from_options(resume_options)
    if isinstance(resume_control, Mapping):
        for key in (
            "adapter",
            "policy",
            "step_index",
            "window_pages",
            "window_paragraphs",
            "window_slides",
            "source_path",
            "target_path",
            "original_task",
            "route",
            "batch_index",
            "total_batches",
        ):
            if key in resume_control and resume_control.get(key) not in ("", None):
                checkpoint[key] = resume_control.get(key)
    if artifact.get("next_step_index") is not None:
        checkpoint["step_index"] = _int_or_zero(artifact.get("next_step_index"))
    if artifact.get("next_page_range"):
        checkpoint["next_window"] = str(artifact.get("next_page_range") or "").strip()
    if artifact.get("completed_page_range"):
        checkpoint["completed_window"] = str(
            artifact.get("completed_page_range") or ""
        ).strip()
    for key in (
        "window_pages",
        "window_paragraphs",
        "window_slides",
        "source_path",
        "target_path",
        "original_task",
        "route",
        "batch_index",
        "total_batches",
    ):
        if artifact.get(key) not in ("", None):
            checkpoint[key] = artifact.get(key)
    checkpoint["status"] = "awaiting_resume"
    checkpoint["source"] = "workflow_checkpoint"
    return {key: value for key, value in checkpoint.items() if value not in ("", None)}


def _checkpoint_from_options(options: Mapping[str, Any]) -> Dict[str, Any]:
    direct = options.get("workflow_checkpoint")
    if isinstance(direct, Mapping):
        return dict(direct)
    state = options.get("workflow_state")
    if isinstance(state, Mapping) and isinstance(state.get("checkpoint"), Mapping):
        return dict(state.get("checkpoint") or {})
    return {}


def request_with_workflow_checkpoint(request: FileTaskRequest) -> FileTaskRequest:
    options = _options(request)
    checkpoint = _checkpoint_from_options(options)
    if not checkpoint:
        if "batch_control" not in options:
            return request
        normalized_options = dict(options)
        normalized_options.pop("batch_control", None)
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
            options=normalized_options,
        )
    resume_control = {
        "adapter": str(checkpoint.get("adapter") or "generic_tool_loop").strip(),
        "policy": str(checkpoint.get("policy") or "confirm_each_step").strip(),
        "step_index": _int_or_zero(checkpoint.get("step_index")),
        "source": "workflow_checkpoint",
    }
    for key in (
        "window_pages",
        "window_paragraphs",
        "window_slides",
        "source_path",
        "target_path",
        "original_task",
        "route",
        "batch_index",
        "total_batches",
    ):
        if checkpoint.get(key) not in ("", None):
            resume_control[key] = checkpoint.get(key)
    normalized_options = dict(options)
    normalized_options.pop("batch_control", None)
    normalized_options["workflow_checkpoint"] = resume_control
    normalized_options["workflow_checkpoint_normalized"] = True
    target_path = str(
        checkpoint.get("target_path") or request.target_path or ""
    ).strip()
    return FileTaskRequest(
        task=request.task,
        run_id=request.run_id,
        session_id=request.session_id,
        files=list(request.files),
        current_file=request.current_file,
        selection=request.selection,
        selection_source=request.selection_source,
        target_path=target_path,
        model_mode=request.model_mode,
        model_id=request.model_id,
        history=list(request.history),
        options=normalized_options,
    )


def window_read_args_for_file(
    workflow_state: Mapping[str, Any],
    file_info: FileTaskFile,
    *,
    default_max_chars: int,
) -> Dict[str, Any]:
    path = str(file_info.path or file_info.name or "").strip()
    if not path:
        return {}
    windows = workflow_state.get("large_file_windows")
    if not isinstance(windows, list):
        return {}
    normalized_path = path.replace("\\", "/").lower()
    for item in windows:
        if not isinstance(item, Mapping):
            continue
        window_path = str(item.get("path") or "").replace("\\", "/").lower()
        if not window_path or window_path != normalized_path:
            continue
        unit = str(item.get("unit") or "").strip().lower()
        current = (
            item.get("current") if isinstance(item.get("current"), Mapping) else {}
        )
        if unit == "page":
            return {
                "path": path,
                "max_chars": min(default_max_chars, 9000),
                "start_page": int(current.get("start") or 1),
                "end_page": int(current.get("end") or current.get("start") or 1),
            }
        if unit in {"paragraph", "slide"}:
            return {
                "path": path,
                "max_chars": min(default_max_chars, 9000),
                "window_unit": unit,
                "start": int(current.get("start") or 1),
                "end": int(current.get("end") or current.get("start") or 1),
            }
        if unit == "sheet":
            return {
                "path": path,
                "max_chars": min(default_max_chars, 12000),
                "window_unit": "sheet",
                "sheet_index": int(current.get("sheet_index") or 0),
            }
    return {}
