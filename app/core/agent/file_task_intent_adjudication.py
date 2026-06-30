# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
from __future__ import annotations

import json
from typing import Any

from app.core.agent.file_task_contract import (
    FileTaskClassification,
    FileTaskFile,
    FileTaskRequest,
)
from app.core.agent.file_task_runtime_utils import _preview
from app.core.agent.tool_design_protocol import extract_first_json_value


def classification_task_text(
    request: FileTaskRequest, resume_control: dict[str, Any]
) -> str:
    task_text = str(request.task or "").strip()
    original_task = ""
    if isinstance(resume_control, dict):
        original_task = str(resume_control.get("original_task") or "").strip()
    if original_task and original_task not in task_text:
        return f"{task_text}\n原始分步任务：{original_task}".strip()
    return task_text


def request_with_task(
    request: FileTaskRequest,
    task_text: str,
) -> FileTaskRequest:
    if str(task_text or "") == str(request.task or ""):
        return request
    return FileTaskRequest(
        task=task_text,
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
        options=dict(request.options),
    )


def intent_adjudicator_system_prompt() -> str:
    return (
        "你是 Koto 文件助手的任务意图裁判。你不执行任务，只判断用户希望产生什么结果。\n"
        "请严格区分：\n"
        "1. answer_only：只回答，不改文件。\n"
        "2. analyze_then_confirm：先分析建议，再等用户确认是否应用到文件。\n"
        "3. edit_file：直接修改当前/目标文件。\n"
        "4. create_file：创建新文件。\n"
        "5. resume_stepwise：继续上一步分步任务。\n"
        "6. diagnose_failure：解释任务为什么失败或上一轮哪里不对。\n"
        "判断规则：\n"
        "- “改、换、应用、写入、创建、美化、更新、删除、插入、套用、换成”通常是写入。\n"
        "- “看看、分析、建议、为什么、哪里有问题”通常是只读、先分析后确认或诊断。\n"
        "- “继续”要结合上一轮任务状态；没有上一轮状态时不要臆造。\n"
        "- 明确的“不写入、不修改、只分析、只给答案”必须覆盖其他写入词。\n"
        "- 如果入口模式和用户正文冲突，优先判断用户正文真正要求的产物。\n"
        "只输出严格 JSON，不要输出 Markdown 或解释文本。"
    )


def should_adjudicate_intent(
    *,
    request: FileTaskRequest,
    classification: FileTaskClassification,
    readonly_write_negation: bool,
    explicit_output_mode: str,
    has_target_context: bool,
) -> bool:
    options = request.options if isinstance(request.options, dict) else {}
    if bool(options.get("disable_ai_intent_adjudicator")):
        return False
    if any(
        key in options
        for key in ("planner_backend", "planner_policy", "planner_command")
    ):
        return False
    if str(options.get("quick_action_mode") or "").strip().lower() == "simple":
        return False
    if bool(options.get("enable_ai_intent_adjudicator")):
        return True
    task_text = str(request.task or "").strip()
    if not task_text:
        return False
    if classification.request_kind == "resume":
        return False
    if classification.selected_recipe in {
        "long_pdf_stepwise_docx_summary",
        "financial_xlsx_docx_report",
        "docx_clear_review_marks",
    }:
        return False
    if classification.diagnostic_request or readonly_write_negation:
        return False
    explicit_mode = str(explicit_output_mode or "").strip().lower()
    if classification.selected_recipe and not explicit_mode:
        return False
    if explicit_mode == "answer" and classification.write_intent:
        return True
    if explicit_mode == "hybrid" and classification.write_intent:
        return True
    if not has_target_context:
        return False
    lowered = task_text.lower()
    ambiguity_markers = (
        "看看",
        "看下",
        "帮我看",
        "建议",
        "怎么改",
        "如何改",
        "优化",
        "风格",
        "主题",
        "配色",
        "好看",
        "美化",
        "调整",
        "改进",
        "review",
        "suggest",
        "style",
        "theme",
    )
    if any(marker in lowered for marker in ambiguity_markers):
        return True
    return False


def intent_adjudicator_messages(
    request: FileTaskRequest,
    files: list[FileTaskFile],
    classification: FileTaskClassification,
) -> list[dict[str, Any]]:
    file_payload = [file_info.public_dict() for file_info in files[:8]]
    payload = {
        "task": request.task,
        "target_path": request.target_path,
        "files": file_payload,
        "entry_options": (
            dict(request.options) if isinstance(request.options, dict) else {}
        ),
        "rule_classification": classification.public_dict(),
        "required_json_schema": {
            "intent": "answer_only | analyze_then_confirm | edit_file | create_file | resume_stepwise | diagnose_failure",
            "confidence": "0.0-1.0",
            "should_write": "boolean",
            "needs_clarification": "boolean",
            "target_file_type": "string",
            "operation": "short operation name",
            "reason": "brief reason",
        },
    }
    return [
        {
            "role": "user",
            "content": json.dumps(payload, ensure_ascii=False),
        }
    ]


def normalize_intent_adjudication_response(response: Any) -> dict[str, Any]:
    content = (
        str(response.get("content") or response.get("text") or "").strip()
        if isinstance(response, dict)
        else str(response or "").strip()
    )
    candidate: Any = None
    if isinstance(response, dict):
        for key in ("intent_adjudication", "intent", "classification"):
            if isinstance(response.get(key), dict):
                candidate = response.get(key)
                break
    if candidate is None:
        candidate = extract_first_json_value(content)
    if not isinstance(candidate, dict):
        return {
            "source": "ai_intent_adjudicator",
            "status": "invalid",
            "raw_preview": _preview(content, 360),
        }
    intent = str(candidate.get("intent") or "").strip().lower()
    confidence = _safe_float(candidate.get("confidence"), 0.0)
    return {
        "source": "ai_intent_adjudicator",
        "status": "ok" if intent else "invalid",
        "intent": intent,
        "confidence": max(0.0, min(1.0, confidence)),
        "should_write": bool(candidate.get("should_write")),
        "needs_clarification": bool(candidate.get("needs_clarification")),
        "target_file_type": str(candidate.get("target_file_type") or "")
        .strip()
        .lower()
        .lstrip("."),
        "operation": str(candidate.get("operation") or "").strip()[:120],
        "reason": str(candidate.get("reason") or "").strip()[:500],
    }


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
