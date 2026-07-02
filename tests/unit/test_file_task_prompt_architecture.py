# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _body_between(source: str, start_marker: str, end_marker: str) -> str:
    start = source.index(start_marker)
    end = source.index(end_marker, start)
    return source[start:end]
def test_file_task_doc_annotate_request_detection_is_extracted_from_runtime() -> None:
    runtime = _read("app/core/agent/file_task_runtime.py")
    helper = _read("app/core/agent/file_task_doc_annotate_request.py")
    classify_body = _body_between(
        runtime,
        "    def _classify_request(",
        "    def _effective_planner_classification(",
    )

    assert "from app.core.agent.file_task_doc_annotate_request import" in runtime
    assert "def _is_docx_annotation_request(" not in runtime
    assert "def _is_docx_clear_review_request(" not in runtime
    assert "def _docx_annotation_has_contract(" not in runtime
    assert "_is_docx_annotation_request" not in runtime
    assert "_is_docx_clear_review_request" not in runtime
    assert "_classification_contract_docx_annotation_has_contract" not in runtime
    assert "is_docx_annotation_request=_doc_annotate_is_annotation_request" in classify_body
    assert "is_docx_clear_review_request=_doc_annotate_is_clear_review_request" in classify_body
    assert "docx_annotation_has_contract=_doc_annotate_contract_for_request" in runtime
    assert "docx_annotation_has_contract=_doc_annotate_has_request_contract" in runtime
    assert "def is_docx_annotation_request(" in helper
    assert "def is_docx_clear_review_request(" in helper
    assert "def docx_annotation_has_request_contract(" in helper
    assert "def docx_annotation_contract_for_request(" in helper
    assert "has_explicit_docx_review_intent(" in helper
    assert "looks_like_docx_review_clear_request(" in helper
    assert "looks_like_direct_docx_rewrite_request(" in helper
    assert "looks_like_multi_file_compare_request(" in helper


def test_file_task_docx_prompt_guidance_is_extracted_from_runtime() -> None:
    runtime = _read("app/core/agent/file_task_runtime.py")
    helper = _read("app/core/agent/file_task_docx_guidance.py")
    system_guidance = _read("app/core/agent/file_task_system_prompt_guidance.py")
    system_prompt_body = _body_between(
        runtime,
        "    def _build_system_prompt(",
        "    def _build_messages(",
    )

    assert "from app.core.agent.file_task_docx_guidance import" not in runtime
    assert "build_docx_prompt_guidance(" not in system_prompt_body
    assert "build_docx_prompt_guidance(" in system_guidance
    assert "_prompt_docx_compare_annotate_guidance" not in runtime
    assert "_prompt_single_docx_annotate_guidance" not in runtime
    assert "_prompt_clear_docx_review_guidance" not in runtime
    assert "target_docx =" not in system_prompt_body
    assert "docx_files =" not in system_prompt_body
    assert "def build_docx_prompt_guidance(" in helper
    assert "class DocxPromptGuidance" in helper
    assert "_prompt_docx_compare_annotate_guidance(" in helper
    assert "_prompt_single_docx_annotate_guidance(" in helper
    assert "_prompt_clear_docx_review_guidance(" in helper


def test_file_task_system_prompt_guidance_is_extracted_from_runtime() -> None:
    runtime = _read("app/core/agent/file_task_runtime.py")
    helper = _read("app/core/agent/file_task_system_prompt_guidance.py")
    builder = _read("app/core/agent/file_task_system_prompt_builder.py")
    system_prompt_body = _body_between(
        runtime,
        "    def _build_system_prompt(",
        "    def _build_messages(",
    )

    assert "from app.core.agent.file_task_system_prompt_guidance import" not in runtime
    assert "build_file_task_system_prompt_guidance(" not in system_prompt_body
    assert "build_file_task_system_prompt_guidance(" in builder
    assert "_prompt_financial_chart_docx_guidance" not in runtime
    assert "_prompt_followup_guidance" not in runtime
    assert "financial_chart_docx_guidance = _prompt" not in system_prompt_body
    assert "followup_guidance = _prompt" not in system_prompt_body
    assert "class FileTaskSystemPromptGuidance" in helper
    assert "def build_file_task_system_prompt_guidance(" in helper
    assert "_prompt_financial_chart_docx_guidance(" in helper
    assert "_prompt_followup_guidance(" in helper


def test_file_task_system_prompt_payload_is_extracted_from_runtime() -> None:
    runtime = _read("app/core/agent/file_task_runtime.py")
    helper = _read("app/core/agent/file_task_system_prompt_payload.py")
    builder = _read("app/core/agent/file_task_system_prompt_builder.py")
    system_prompt_body = _body_between(
        runtime,
        "    def _build_system_prompt(",
        "    def _build_messages(",
    )

    assert "from app.core.agent.file_task_system_prompt_payload import" not in runtime
    assert "build_file_task_system_prompt_payload(" not in system_prompt_body
    assert "build_file_task_system_prompt_payload(" in builder
    assert "file_list = (" not in system_prompt_body
    assert "known_gap_text =" not in system_prompt_body
    assert "capability_text =" not in system_prompt_body
    assert "supported_file_workflows()" not in system_prompt_body
    assert "build_request_capability_profiles(request)" not in system_prompt_body
    assert "class FileTaskSystemPromptPayload" in helper
    assert "def build_file_task_system_prompt_payload(" in helper
    assert "def explicit_file_list(" in helper
    assert "def capability_profiles_text(" in helper
    assert "def known_tool_gap_text(" in helper


def test_file_task_system_prompt_builder_is_extracted_from_runtime() -> None:
    runtime = _read("app/core/agent/file_task_runtime.py")
    helper = _read("app/core/agent/file_task_system_prompt_builder.py")
    system_prompt_body = _body_between(
        runtime,
        "    def _build_system_prompt(",
        "    def _build_messages(",
    )

    assert "from app.core.agent.file_task_system_prompt_builder import" in runtime
    assert "build_file_task_runtime_system_prompt(" in system_prompt_body
    assert "_build_file_task_system_prompt(" not in system_prompt_body
    assert "prompt_payload =" not in system_prompt_body
    assert "prompt_guidance =" not in system_prompt_body
    assert "skeleton = recipe_skeleton" not in system_prompt_body
    assert "build_recipe_skeleton(" not in system_prompt_body
    assert "def build_file_task_runtime_system_prompt(" in helper
    assert "build_file_task_system_prompt(" in helper
    assert "build_file_task_system_prompt_payload(" in helper
    assert "build_file_task_system_prompt_guidance(" in helper


def test_file_task_system_prompt_keeps_relative_outputs_in_input_directory() -> None:
    helper = _read("app/core/agent/file_task_system_prompt.py")

    assert "相对输出文件名" in helper
    assert "默认把输出文件写入该输入目录" in helper
    assert "不要写到 workspace 根目录" in helper


def test_file_task_message_payload_is_extracted_from_runtime() -> None:
    runtime = _read("app/core/agent/file_task_runtime.py")
    helper = _read("app/core/agent/file_task_message_payload.py")
    messages_body = _body_between(
        runtime,
        "    def _build_messages(",
        "    def _followup_context(",
    )

    assert "from app.core.agent.file_task_message_payload import" in runtime
    assert "build_file_task_runtime_messages(" in messages_body
    assert "_build_file_task_messages(" not in messages_body
    assert "capability_profiles =" not in messages_body
    assert "followup_context =" not in messages_body
    assert "skeleton = recipe_skeleton" not in messages_body
    assert "build_request_capability_profiles(request)" not in messages_body
    assert "build_recipe_skeleton(" not in messages_body
    assert "def build_file_task_runtime_messages(" in helper
    assert "build_file_task_messages(" in helper
    assert "build_request_capability_profiles(request)" in helper
    assert "followup_context(request)" in helper
    assert "build_recipe_skeleton(" in helper

