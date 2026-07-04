# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _body_between(source: str, start_marker: str, end_marker: str) -> str:
    start = source.index(start_marker)
    end = source.index(end_marker, start)
    return source[start:end]


def test_history_records_show_structured_task_chain_verification() -> None:
    dispatcher = _read("web/src/workspace/task-dispatcher.ts")
    conversation = _read("web/src/workspace/conversation.ts")
    sessions = _read("web/blueprints/sessions.py")

    assert "function taskCardTestStructure(" in dispatcher
    assert "metadata.test_structure = testStructure;" in dispatcher
    assert "schema: 'koto_ai_task_chain_test_v1'" in dispatcher
    assert "final_summary: finalSummary" in dispatcher
    assert "工作区输入框 -> AI 意图判断 -> 文件任务流 -> 监管执行" in dispatcher
    assert "function renderTestStructure(" in conversation
    assert "执行过程" in conversation
    assert "本轮结论：" in conversation
    assert "wa-task-process-step" in conversation
    assert "wa-task-final-answer" in conversation
    assert "technical_entrypoint" in conversation
    assert "turn.test_structure" in conversation
    assert '"test_structure"' in sessions

    task_runner = _read("web/src/workspace/task-runner.ts")
    task_final_report = _read("web/src/workspace/task-final-report.ts")
    task_performance = _read("web/src/workspace/task-performance.ts")
    file_task_status = _read("web/src/workspace/file-task-status.ts")
    assert "from './task-final-report';" in task_runner
    assert "export function renderTaskFinalReport(" in task_final_report
    assert "export function normalizeTaskFinalReportMarkdown(" in task_final_report
    assert "export function renderReadableMarkdownFallback(" in task_final_report
    assert "function compactTerminalProcess(" in task_runner
    assert "from './task-performance';" in task_runner
    assert "export function taskPerformanceSummary(" in task_performance
    assert "export function updateTaskPerformanceDataset(" in task_performance
    assert "export function updateModelSummaryState(" in task_performance
    assert "function updateTaskPerformanceRow(" in task_runner
    assert "card.dataset.taskPerformance" in task_runner
    assert "route_decision_ms" in task_performance
    assert "intent_adjudication_ms" in task_performance
    assert "function taskResultNeedsAttention(" in task_runner
    assert "function taskResultOutcomeCopy(" in task_runner
    assert "needsAttention ? '需处理'" in task_runner
    assert "任务需要处理，进度已保留。" in task_runner
    assert "function ensureTaskReportAfterProcess(" in task_runner
    assert "export function terminalAnswerText(" in task_final_report
    assert "function taskCompletionBannerHtml(" in task_runner
    assert "function announceTaskCompletion(" in task_runner
    assert "(window as any)._waRenderMarkdown" in task_final_report
    assert "wa-task-final-report" in task_runner
    assert "const auditHtml = supervisorAuditHtml(data);" in task_runner
    assert 'class="wa-task-final-report-title">总结与回答</div>' in task_runner
    assert "renderTaskFinalReport(visibleSummary)" in task_runner
    assert "fileTaskOutcomeCopy" in task_runner
    assert "任务已完成，结果已显示在步骤下方" in file_task_status
    assert "if (normalized === 'needs_attention') return '需处理';" in file_task_status
    assert "if (normalized === 'context_summary_fallback') return '需复核';" in file_task_status
    assert "模型未返回完整答案；当前仅显示基于已读上下文的临时摘要。" in task_runner
    assert "report.scrollIntoView({ behavior: 'smooth', block: 'nearest' });" in task_runner
    assert "wa-task-step-detail" in task_runner
    assert "data-role=\"process\"" in task_runner
    assert "ensureTaskReportAfterProcess(card);" in task_runner
    assert "ensureTaskReportAfterProcess(cardEl);" in task_runner
    assert "handleEvent_supervisor_step_verified" in task_runner
    assert "'supervisor.step_verified': handleEvent_supervisor_step_verified" in task_runner
    assert "function terminalTaskAnswer(" in dispatcher
    assert "dataset.taskFinalAnswer || dataset.taskSummary" in dispatcher
    assert "wa-task-final-answer-title" in conversation


def test_compact_task_card_keeps_process_steps_visible_before_summary() -> None:
    css = _read("web/static/css/workspace.css")

    hidden_blocks = re.findall(r"\{[^{}]*display\s*:\s*none\s*!important[^{}]*\}", css)
    assert not any('[data-role="plan"]' in block for block in hidden_blocks)
    assert not any('[data-role="steps"]' in block for block in hidden_blocks)

    task_runner = _body_between(
        _read("web/src/workspace/task-runner.ts"),
        "function makeRunCard(",
        "function ensureTaskLiveProgressHost()",
    )
    process_index = task_runner.index('data-role="process"')
    summary_index = task_runner.index('data-role="summary"')
    assert process_index < summary_index

    assert ".wa-task-run {" in css
    assert "flex-direction: column;" in css
    assert ".wa-task-process" in css
    assert ".wa-task-row.wa-task-performance" in css
    assert "order: 10;" in css
    assert ".wa-task-summary" in css
    assert "order: 20;" in css


def test_task_workbench_uses_shared_report_layout_helpers() -> None:
    workbench = _read("web/src/workspace/task-workbench.ts")
    layout = _read("web/src/workspace/task-report-layout.ts")

    for exported in [
        "export function taskReportCompactText(",
        "export function taskReportUniqueTexts(",
        "export function taskReportStageFromStep(",
        "export function taskReportStatusClass(",
        "export function taskReportStageActionText(",
        "export function taskReportStageStatusText(",
    ]:
        assert exported in layout

    for local_helper in [
        "function compactText(",
        "function uniqueTexts(",
        "function stageFromStep(",
        "function statusClass(",
        "function stageActionText(",
        "const STEP_STAGE_BY_ID",
    ]:
        assert local_helper not in workbench

    assert "taskReportCompactText as compactText" in workbench
    assert "taskReportUniqueTexts as uniqueTexts" in workbench
    assert "taskReportStageFromStep as stageFromStep" in workbench
    assert "taskReportStatusClass as statusClass" in workbench
    assert "taskReportStageActionText as stageActionText" in workbench


def test_task_runner_uses_shared_step_label_helpers() -> None:
    runner = _read("web/src/workspace/task-runner.ts")
    labels = _read("web/src/workspace/task-step-labels.ts")

    for local_table in [
        "const TOOL_LABELS",
        "const INTERNAL_TOOL_NAMES",
        "const ALWAYS_SUPPRESS_TOOL_FINISHED_NAMES",
        "const READ_TOOL_NAMES",
        "const EXTRA_STEP_TITLES",
        "const PLAN_VIOLATION_LABELS",
    ]:
        assert local_table not in runner
        assert local_table in labels

    for exported in [
        "export function taskToolLabel(",
        "export function isInternalTaskTool(",
        "export function shouldAlwaysSuppressTaskToolFinished(",
        "export function isReadTaskTool(",
        "export function taskStepTitle(",
        "export function taskPlanViolationLabel(",
    ]:
        assert exported in labels

    assert "from './task-step-labels';" in runner
    assert "taskToolLabel(toolName)" in runner
    assert "isInternalTaskTool(name)" in runner
    assert "isReadTaskTool(name)" in runner
    assert "taskPlanViolationLabel(" in runner


def test_task_runner_uses_shared_final_report_helpers() -> None:
    runner = _read("web/src/workspace/task-runner.ts")
    final_report = _read("web/src/workspace/task-final-report.ts")

    for local_helper in [
        "function previewText(",
        "function looksLikeFullAnswerText(",
        "function compactFlowSummary(",
        "function terminalTextValue(",
        "function terminalAnswerText(",
        "function renderTaskFinalReport(",
        "function normalizeTaskFinalReportMarkdown(",
        "function renderReadableMarkdownFallback(",
    ]:
        assert local_helper not in runner
        assert local_helper.replace("function ", "export function ") in final_report

    assert "from './task-final-report';" in runner
    assert "renderTaskFinalReport(visibleSummary)" in runner
    assert "terminalAnswerText(data, result.summary)" in runner
    assert "(window as any)._waRenderMarkdown" in final_report


def test_task_runner_uses_shared_performance_helpers() -> None:
    runner = _read("web/src/workspace/task-runner.ts")
    performance = _read("web/src/workspace/task-performance.ts")

    for local_helper in [
        "function taskPerformanceSource(",
        "function taskPerformanceFromCard(",
        "function taskPerformanceMs(",
        "function taskPerformanceDuration(",
        "function taskPerformanceSummary(",
    ]:
        assert local_helper not in runner

    for exported in [
        "export interface ModelSummaryState",
        "export function createModelSummaryState(",
        "export function taskPerformanceSource(",
        "export function taskPerformanceSummary(",
        "export function updateTaskPerformanceDataset(",
        "export function updateModelSummaryState(",
    ]:
        assert exported in performance

    assert "from './task-performance';" in runner
    assert "modelSummary: createModelSummaryState()" in runner
    assert "const next = updateTaskPerformanceDataset(current, data);" in runner
    assert "const summary = updateModelSummaryState(state.modelSummary, data);" in runner
    assert "route_decision_ms" in performance
    assert "intent_adjudication_ms" in performance
