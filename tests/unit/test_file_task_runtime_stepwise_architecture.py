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


def test_file_task_runtime_phase_modules_do_not_import_runtime_facade() -> None:
    """Keep the extracted phases acyclic and independently importable."""
    runtime = _read("app/core/agent/file_task_runtime.py")
    phase_modules = (
        "file_task_context_read.py",
        "file_task_execution_loop.py",
        "file_task_finalization.py",
        "file_task_planning.py",
        "file_task_plan_presentation.py",
    )

    assert "from app.core.agent.file_task_context_read import FileTaskContextReadPhase" in runtime
    assert "from app.core.agent.file_task_execution_loop import FileTaskExecutionLoop" in runtime
    assert "from app.core.agent.file_task_finalization import FileTaskFinalizationPhase" in runtime
    assert "from app.core.agent.file_task_planning import FileTaskPlanningPhase" in runtime
    assert "from app.core.agent.file_task_plan_presentation import" in runtime

    for module_name in phase_modules:
        source = _read(f"app/core/agent/{module_name}")
        assert "from app.core.agent.file_task_runtime import" not in source
        assert "import app.core.agent.file_task_runtime" not in source


def test_file_task_doc_annotate_bridge_fallback_is_extracted_from_runtime() -> None:
    runtime = _read("app/core/agent/file_task_runtime.py")
    planning = _read("app/core/agent/file_task_planning.py")
    helper = _read("app/core/agent/file_task_doc_annotate_fallback.py")
    body = _body_between(
        planning,
        "        write_intent = execution_context.write_intent",
        "        bridge_execution_mode = classification.execution_mode == \"doc_annotate_bridge\"",
    )

    assert "from app.core.agent.file_task_doc_annotate_fallback import" not in runtime
    assert "from app.core.agent.file_task_planning import FileTaskPlanningPhase" in runtime
    assert "from app.core.agent.file_task_doc_annotate_fallback import" in planning
    assert "apply_doc_annotate_bridge_fallback(" in body
    assert "file_task_doc_annotate_boundary.should_use_bridge_execution" not in body
    assert "doc_annotate_bridge_execution_fallback" not in body
    assert "def apply_doc_annotate_bridge_fallback(" in helper
    assert "file_task_doc_annotate_boundary.should_use_bridge_execution" in helper
    assert "doc_annotate_bridge_execution_fallback" in helper


def test_file_task_readonly_answer_only_loop_guard_is_extracted_from_runtime() -> None:
    runtime = _read("app/core/agent/file_task_runtime.py")
    execution_loop = _read("app/core/agent/file_task_execution_loop.py")
    helper = _read("app/core/agent/file_task_readonly_loop_guard.py")
    loop_body = _body_between(
        execution_loop,
        "        for round_index in range(1, repair_round_limit + 1):",
        "            batch_signature = runtime._tool_batch_signature(tool_calls)",
    )
    duplicate_body = _body_between(
        execution_loop,
        "            if batch_signature and batch_signature == last_tool_batch_signature:",
        "                if (",
    )

    assert "from app.core.agent.file_task_readonly_loop_guard import" in runtime
    assert "from app.core.agent.file_task_execution_loop import FileTaskExecutionLoop" in runtime
    assert "_readonly_answer_only_round(" in loop_body
    assert "_readonly_discard_answer_only_tool_calls(" in loop_body
    assert "_readonly_should_retry_answer_guard(" in loop_body
    assert "_readonly_should_retry_duplicate_guard(" in duplicate_body
    assert "_readonly_should_retry_write_duplicate_guard(" in duplicate_body
    assert "_readonly_duplicate_guard_reminder(" in duplicate_body
    assert "_readonly_duplicate_final_summary(" in duplicate_body
    assert "_readonly_supervisor_guard_tool_payload(" in duplicate_body
    assert "_readonly_duplicate_guard_tool_payload(" in duplicate_body
    assert "active_tool_defs = [] if answer_only_round else tool_defs" not in loop_body
    assert "discarded_answer_only_tool_calls = len(tool_calls)" not in loop_body
    assert "已读取内容，正在生成可见分析结果。" not in loop_body
    assert "不要再次调用任何工具" not in duplicate_body
    assert "已读取上下文，但模型未生成可见分析结果。" not in duplicate_body
    assert "监管层已要求模型回到计划主线" not in duplicate_body
    assert "避免重复写入" not in duplicate_body
    assert '"tool_name": "supervisor_guard"' not in duplicate_body
    assert '"tool_name": "duplicate_guard"' not in duplicate_body
    assert "class AnswerOnlyRound" in helper
    assert "class AnswerOnlyToolCalls" in helper
    assert "def answer_only_round(" in helper
    assert "def discard_answer_only_tool_calls(" in helper
    assert "def should_retry_readonly_answer_guard(" in helper
    assert "def should_retry_readonly_duplicate_guard(" in helper
    assert "def readonly_duplicate_guard_reminder(" in helper
    assert "def readonly_duplicate_final_summary(" in helper
    assert "def should_retry_write_duplicate_guard(" in helper
    assert "def supervisor_guard_tool_payload(" in helper
    assert "def duplicate_guard_tool_payload(" in helper
    assert "不要再次调用任何工具" in helper
    assert "已读取上下文" in helper
    assert "模型未生成可见分析结果" in helper
    assert "生成可见分析结果" in helper
    assert "监管层已要求模型回到计划主线" in helper
    assert "避免重复写入" in helper
    assert '"tool_name": "supervisor_guard"' in helper
    assert '"tool_name": "duplicate_guard"' in helper


def test_file_task_native_stepwise_pdf_guard_payload_is_extracted_from_runtime() -> None:
    runtime = _read("app/core/agent/file_task_runtime.py")
    helper = _read("app/core/agent/_file_task_stepwise_helpers.py")
    native_write_body = _body_between(
        runtime,
        "    def _write_stepwise_pdf_docx_native(",
        "    def _stepwise_docx_target_path(",
    )

    assert (
        "native_stepwise_pdf_text_quality_guard_payload as "
        "_native_stepwise_pdf_text_quality_guard_payload"
    ) in runtime
    assert "_native_stepwise_pdf_text_quality_guard_payload(" in native_write_body
    assert "当前 PDF 页窗文本质量不足" not in native_write_body
    assert '"tool_name": "supervisor_guard"' not in native_write_body
    assert "def native_stepwise_pdf_text_quality_guard_payload(" in helper
    assert "当前 PDF 页窗文本质量不足" in helper
    assert '"tool_name": "supervisor_guard"' in helper
    assert '"native_stepwise": True' in helper


def test_file_task_stepwise_docx_target_path_is_extracted_from_runtime() -> None:
    runtime = _read("app/core/agent/file_task_runtime.py")
    helper = _read("app/core/agent/_file_task_stepwise_helpers.py")
    target_body = _body_between(
        runtime,
        "    def _stepwise_docx_target_path(",
        "    def _tool_args_docx_paragraph_count(",
    )

    assert "stepwise_docx_target_path as _stepwise_docx_target_path" in runtime
    assert "return _stepwise_docx_target_path(request, files)" in target_body
    assert "_first_context_file(" not in target_body
    assert "_分步总结.docx" not in target_body
    assert "def stepwise_docx_target_path(" in helper
    assert "_分步总结.docx" in helper
    assert "file_task_suffix(file_info) == \"docx\"" in helper


def test_file_task_docx_stepwise_polish_runner_is_extracted_from_runtime() -> None:
    runtime = _read("app/core/agent/file_task_runtime.py")
    runner = _read("app/core/agent/file_task_docx_stepwise_runner.py")
    wrapper_body = _body_between(
        runtime,
        "    def _stream_long_docx_stepwise_polish_writeback(",
        "    def _run_builtin_tool(",
    )
    stream_body = runner.split("    def stream_polish_writeback(", 1)[1]
    read_helper_body = _body_between(
        runner,
        "def _docx_stepwise_read_window(",
        "def _docx_stepwise_polished_paragraphs(",
    )

    assert "FileTaskDocxStepwiseRunner" in wrapper_body
    assert "stream_polish_writeback(" in wrapper_body
    assert "from app.core.agent.file_task_docx_stepwise import" not in runtime
    assert "class DocxStepwiseRuntimePort(Protocol)" in runner
    assert "def _build_runtime_metadata(" in runner
    assert "def _build_step_result_payload(" in runner
    assert "def _call_model(" in runner
    assert "def _normalize_model_response(" in runner
    assert "def _evaluate_task_quality_gate(" in runner
    assert "def __init__(self, runtime: DocxStepwiseRuntimePort)" in runner
    assert "@dataclass(frozen=True)" in runner
    assert "class DocxStepwisePayloadContext:" in runner
    assert "class DocxStepwiseRunContext:" in runner
    assert "class DocxStepwiseReadResult:" in runner
    assert "def _docx_stepwise_run_context(" in runner
    assert "run_context = _docx_stepwise_run_context(" in runner
    assert "def _docx_stepwise_read_window(" in runner
    assert "read_result = _docx_stepwise_read_window(" in stream_body
    assert "for event in read_result.events:" in stream_body
    assert "if read_result.terminal or read_result.window is None:" in stream_body
    assert "window = read_result.window" in stream_body
    assert "target_path=stepwise_docx_polish_target_path(request, context_files)" in runner
    assert "file_changes=[]" in runner
    assert "payload_context = DocxStepwisePayloadContext(" not in runner
    assert "file_changes: List[Dict[str, Any]] = []" not in runner
    assert "def _docx_stepwise_run_finished_payload(" in runner
    assert "payload_context: DocxStepwisePayloadContext" in runner
    assert "def _docx_stepwise_terminal_event(" in runner
    assert runner.count("_docx_stepwise_run_finished_payload(") == 3
    assert runner.count("_docx_stepwise_terminal_event(") == 4
    assert runner.count("payload_context=payload_context") == 1
    assert runner.count("payload_context=run_context.payload_context") == 4
    assert "run_context.target_path" in stream_body
    assert "run_context.file_changes" in stream_body
    assert "stepwise_docx_polish_target_path(request, context_files)" not in stream_body
    assert "read_docx_paragraph_window(" not in stream_body
    assert "_docx_stepwise_read_failed_tool_payload(" not in stream_body
    assert "_docx_stepwise_read_tool_payload(" not in stream_body
    assert "_docx_stepwise_read_step_result_payload(" not in stream_body
    assert runner.count('"completed_task": completed_task') == 1
    assert runner.count('"quick_action_mode": payload_context.quick_action_mode') == 1
    assert runner.count("runtime._build_runtime_metadata(") == 2
    assert "DOCX_STEPWISE_AWAITING_SUMMARY" in runner
    assert "DOCX_STEPWISE_CHECK_SUMMARY" in runner
    assert 'DOCX_STEPWISE_CONTEXT_STEP_ID = "context"' in runner
    assert 'DOCX_STEPWISE_EXECUTE_STEP_ID = "execute"' in runner
    assert 'DOCX_STEPWISE_CHECK_STEP_ID = "check"' in runner
    assert 'DOCX_STEPWISE_READ_TITLE = "读取当前 DOCX 段落窗口"' in runner
    assert 'DOCX_STEPWISE_WRITE_TITLE = "润色并写回当前段落"' in runner
    assert "DOCX_STEPWISE_READ_DETAIL" in runner
    assert "DOCX_STEPWISE_WRITE_DETAIL" in runner
    assert "def _docx_stepwise_step_started_payload(" in runner
    assert runner.count("_docx_stepwise_step_started_payload(") == 3
    assert "context_step_id" not in runner
    assert "execute_step_id" not in runner
    assert "check_step_id" not in runner
    assert "step_id=DOCX_STEPWISE_CONTEXT_STEP_ID" in read_helper_body
    assert "step_id=DOCX_STEPWISE_EXECUTE_STEP_ID" in stream_body
    assert "step_id=DOCX_STEPWISE_CHECK_STEP_ID" in stream_body
    assert "def _docx_stepwise_read_step_result_payload(" in runner
    assert "def _docx_stepwise_quality_check_payload(" in runner
    assert "def _docx_stepwise_write_step_result_payload(" in runner
    assert "def _docx_stepwise_check_step_result_payload(" in runner
    assert "_docx_stepwise_read_step_result_payload(" in runner
    assert "_docx_stepwise_quality_check_payload(" in runner
    assert "_docx_stepwise_write_step_result_payload(" in runner
    assert "_docx_stepwise_check_step_result_payload(" in runner
    assert runner.count("runtime._build_step_result_payload(") == 3
    assert runner.count("runtime._evaluate_task_quality_gate(") == 1
    assert runner.count('"summary": DOCX_STEPWISE_CHECK_SUMMARY') == 1
    assert runner.count("summary=DOCX_STEPWISE_AWAITING_SUMMARY") == 1
    assert "def _docx_stepwise_read_failed_tool_payload(" in runner
    assert "def _docx_stepwise_read_tool_payload(" in runner
    assert "def _docx_stepwise_write_change_payload(" in runner
    assert "def _docx_stepwise_write_tool_payload(" in runner
    assert "class DocxStepwisePolishResult:" in runner
    assert "def _docx_stepwise_polished_paragraphs(" in runner
    assert "class DocxStepwiseWriteResult:" in runner
    assert "def _docx_stepwise_writeback(" in runner
    assert "_docx_stepwise_read_failed_tool_payload(" in runner
    assert "_docx_stepwise_read_tool_payload(" in runner
    assert "change = _docx_stepwise_write_change_payload(" in runner
    assert "_docx_stepwise_write_tool_payload(" in runner
    assert "polish_result = _docx_stepwise_polished_paragraphs(" in runner
    assert "write_result = _docx_stepwise_writeback(" in runner
    assert "polish_result.paragraphs" in runner
    assert "change = write_result.change" in runner
    assert "changed_count=write_result.changed_count" in runner
    assert "model_failed=polish_result.model_failed" in runner
    assert "change = {" not in runner
    assert runner.count('"tool_name": "read_docx_content"') == 2
    assert runner.count('"tool_name": "rewrite_docx_paragraph_window"') == 1
    assert runner.count("rewrite_docx_paragraph_window(") == 1
    assert runner.count("runtime._call_model(") == 1
    assert runner.count("runtime._normalize_model_response(") == 1
    assert "runtime._call_model(" not in stream_body
    assert "runtime._normalize_model_response(" not in stream_body
    assert "parse_polished_docx_paragraphs(" not in stream_body
    assert "simple_polish_docx_paragraph(text)" not in stream_body
    assert "rewrite_docx_paragraph_window(" not in stream_body
    assert "changed_count = rewrite_docx_paragraph_window(" not in stream_body
    assert stream_body.count("_docx_stepwise_run_finished_payload(") == 1
    assert "runtime._build_runtime_metadata(" in stream_body
    assert 'terminal_status="failed"' in read_helper_body
    assert 'terminal_status="verified"' in read_helper_body
    assert '"detail": "按段落窗口读取 Word 当前步骤内容' not in stream_body
    assert '"detail": "只处理当前段落窗口' not in stream_body
    assert "读取当前 DOCX 段落窗口" not in wrapper_body
    assert "润色并写回当前段落" not in wrapper_body
    assert "rewrite_docx_paragraph_window" not in wrapper_body
    assert "class FileTaskDocxStepwiseRunner" in runner
    assert "def stream_polish_writeback(" in runner
    assert "from app.core.agent.file_task_docx_stepwise import" in runner
    assert "stepwise_docx_polish_target_path(request, context_files)" in runner
    assert "read_docx_paragraph_window(request, target_path)" in runner
    assert "docx_polish_window_prompt(" in runner
    assert "parse_polished_docx_paragraphs(" in runner
    assert "simple_polish_docx_paragraph(text)" in runner
    assert "rewrite_docx_paragraph_window(" in runner
    assert "docx_polish_wait_artifact(" in runner
    assert "读取当前 DOCX 段落窗口" in runner
    assert "润色并写回当前段落" in runner
    assert "rewrite_docx_paragraph_window" in runner


def test_file_task_stepwise_docx_content_quality_guard_is_extracted_from_runtime() -> None:
    runtime = _read("app/core/agent/file_task_runtime.py")
    helper = _read("app/core/agent/_file_task_stepwise_helpers.py")
    wrapper_body = _body_between(
        runtime,
        "    def _stepwise_docx_content_quality_block_message(",
        "    def _stepwise_docx_wait_artifact(",
    )

    assert (
        "stepwise_docx_content_quality_block_message as "
        "_stepwise_docx_content_quality_block_message"
    ) in runtime
    assert "_stepwise_docx_content_quality_block_message(snippets, text)" in wrapper_body
    assert "当前分步 DOCX 正文为空" not in wrapper_body
    assert "文档识别\\s*/\\s*核心要点" not in wrapper_body
    assert "DOCX 页窗标签与当前读取窗口不一致" not in wrapper_body
    assert "当前分步 DOCX 正文存在重复段落" not in wrapper_body
    assert "def stepwise_docx_content_quality_block_message(" in helper
    assert "当前分步 DOCX 正文为空" in helper
    assert "文档识别\\s*/\\s*核心要点" in helper
    assert "DOCX 页窗标签与当前读取窗口不一致" in helper
    assert "当前分步 DOCX 正文存在重复段落" in helper


def test_file_task_stepwise_docx_wait_artifact_is_extracted_from_runtime() -> None:
    runtime = _read("app/core/agent/file_task_runtime.py")
    helper = _read("app/core/agent/_file_task_stepwise_helpers.py")
    wrapper_body = _body_between(
        runtime,
        "    def _stepwise_docx_wait_artifact(",
        "    def _stepwise_pdf_fallback_paragraphs(",
    )

    assert "stepwise_docx_wait_artifact as _stepwise_docx_wait_artifact" in runtime
    assert "return _stepwise_docx_wait_artifact(" in wrapper_body
    assert '"artifact_type": "koto_stepwise_resume_v1"' not in wrapper_body
    assert '"route": "long_pdf_stepwise_docx_summary"' not in wrapper_body
    assert '"followup_action": "resume"' not in wrapper_body
    assert "def stepwise_docx_wait_artifact(" in helper
    assert '"artifact_type": "koto_stepwise_resume_v1"' in helper
    assert '"route": "long_pdf_stepwise_docx_summary"' in helper
    assert '"followup_action": "resume"' in helper


def test_file_task_stepwise_pdf_fallback_paragraphs_are_extracted_from_runtime() -> None:
    runtime = _read("app/core/agent/file_task_runtime.py")
    helper = _read("app/core/agent/_file_task_stepwise_helpers.py")
    fallback_body = _body_between(
        runtime,
        "    def _stepwise_pdf_fallback_paragraphs(",
        "    def _fallback_readonly_summary(",
    )

    assert (
        "stepwise_pdf_fallback_paragraphs as _stepwise_pdf_fallback_paragraphs"
        in runtime
    )
    assert (
        "stepwise_pdf_fallback_insights as _stepwise_pdf_fallback_insights"
        in runtime
    )
    assert "return _stepwise_pdf_fallback_paragraphs(pdf_snippet, exc)" in fallback_body
    assert "return _stepwise_pdf_fallback_insights(preview)" in fallback_body
    assert "当前页窗摘要（" not in fallback_body
    assert "当前页窗可读内容集中在" not in fallback_body
    assert "def stepwise_pdf_fallback_paragraphs(" in helper
    assert "def stepwise_pdf_fallback_insights(" in helper
    assert "当前页窗摘要（" in helper
    assert "当前页窗可读内容集中在" in helper


def test_file_task_stepwise_docx_write_guard_is_extracted_from_runtime() -> None:
    runtime = _read("app/core/agent/file_task_runtime.py")
    helper = _read("app/core/agent/_file_task_stepwise_helpers.py")
    wrapper_body = _body_between(
        runtime,
        "    def _stepwise_docx_write_block_message(",
        "    def _stepwise_docx_content_quality_block_message(",
    )

    assert (
        "stepwise_docx_write_block_message as _stepwise_docx_write_block_message"
        in runtime
    )
    assert "return _stepwise_docx_write_block_message(" in wrapper_body
    assert "当前 PDF 页窗的可提取文本质量不足" not in wrapper_body
    assert "write_docx_content 的 paragraphs 不能包含 Markdown 标题符号" not in wrapper_body
    assert "DOCX 正文不能包含任务进度" not in wrapper_body
    assert "def stepwise_docx_write_block_message(" in helper
    assert "def latest_pdf_snippet_quality(" in helper
    assert "def tool_args_docx_paragraph_text(" in helper
    assert "当前 PDF 页窗的可提取文本质量不足" in helper
    assert "write_docx_content 的 paragraphs 不能包含 Markdown 标题符号" in helper
    assert "DOCX 正文不能包含任务进度" in helper
    assert "stepwise_docx_content_quality_block_message(snippets, text)" in helper


def test_file_task_local_docx_edit_guard_is_extracted_from_runtime() -> None:
    runtime = _read("app/core/agent/file_task_runtime.py")
    helper = _read("app/core/agent/file_task_docx_edit_guard.py")
    count_body = _body_between(
        runtime,
        "    def _tool_args_docx_paragraph_count(",
        "    def _local_docx_edit_block_message(",
    )
    local_body = _body_between(
        runtime,
        "    def _local_docx_edit_block_message(",
        "    def _stepwise_docx_write_block_message(",
    )

    assert "from app.core.agent.file_task_docx_edit_guard import" in runtime
    assert "return _docx_edit_paragraph_count(tool_args)" in count_body
    assert "return _docx_edit_local_block_message(" in local_body
    assert "只追加" not in local_body
    assert "保留已有表格" not in local_body
    assert "DOCX 局部编辑" not in local_body
    assert "insert_docx_paragraph(path=目标 DOCX" not in local_body
    assert "def tool_args_docx_paragraph_count(" in helper
    assert "def local_docx_edit_block_message(" in helper
    assert "只追加" in helper
    assert "保留已有表格" in helper
    assert "DOCX 局部编辑" in helper
    assert "insert_docx_paragraph(path=目标 DOCX" in helper
