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
    persistence = _read("web/src/workspace/task-card-persistence.ts")
    conversation = _read("web/src/workspace/conversation.ts")
    sessions = _read("web/blueprints/sessions.py")

    assert "export function taskCardPersistenceStructure(" in persistence
    assert "metadata.test_structure = persistenceStructure;" in dispatcher
    assert "taskCardPersistenceStructure," in dispatcher
    assert "publishWorkspaceApi({ taskCardTestStructure });" not in dispatcher
    assert "schema: 'koto_ai_task_chain_test_v1'" in persistence
    assert "final_summary: finalSummary" in persistence
    assert "工作区输入框 -> AI 意图判断 -> 文件任务流 -> 监管执行" in persistence
    assert "function renderTestStructure(" in conversation
    assert "执行过程" in conversation
    assert "没有额外细节。" in conversation
    assert "wa-task-process-step" in conversation
    assert "wa-task-final-answer" in conversation
    assert "technical_entrypoint" in conversation
    assert "turn.test_structure" in conversation
    assert '"test_structure"' in sessions

    task_runner = _read("web/src/workspace/task-runner.ts")
    task_run_events = _read("web/src/workspace/task-run-event-handlers.ts")
    task_plan_presentation = _read(
        "web/src/workspace/task-plan-presentation.ts"
    )
    task_plan_events = _read(
        "web/src/workspace/task-plan-event-handlers.ts"
    )
    task_final_report = _read("web/src/workspace/task-final-report.ts")
    task_result_presentation = _read(
        "web/src/workspace/task-result-presentation.ts"
    )
    task_terminal_state = _read(
        "web/src/workspace/task-terminal-state.ts"
    )
    task_stage_presentation = _read(
        "web/src/workspace/task-stage-presentation.ts"
    )
    task_step_dom = _read("web/src/workspace/task-step-dom.ts")
    task_performance = _read("web/src/workspace/task-performance.ts")
    file_task_status = _read("web/src/workspace/file-task-status.ts")
    assert "from './task-final-report';" in task_run_events
    assert "export function renderTaskFinalReport(" in task_final_report
    assert "export function normalizeTaskFinalReportMarkdown(" in task_final_report
    assert "export function renderReadableMarkdownFallback(" in task_final_report
    assert "from './task-terminal-state';" in task_runner
    assert "export function compactTerminalProcess(" in task_terminal_state
    assert "function compactTerminalProcess(" not in task_runner
    assert "from './task-performance';" in task_runner
    assert "export function taskPerformanceSummary(" in task_performance
    assert "export function updateTaskPerformanceDataset(" in task_performance
    assert "export function updateModelSummaryState(" in task_performance
    assert "export function updateTaskPerformanceRow(" in task_performance
    assert "function updateTaskPerformanceRow(" not in task_runner
    assert "card.dataset.taskPerformance" in task_performance
    assert "route_decision_ms" in task_performance
    assert "intent_adjudication_ms" in task_performance
    assert "function taskResultNeedsAttention(" not in task_runner
    assert "function taskResultOutcomeCopy(" not in task_runner
    assert "export function taskResultOutcomeCopy(" in task_result_presentation
    assert "needsAttention ? '需处理'" not in task_runner
    assert "export function ensureTaskReportAfterProcess<" in task_stage_presentation
    assert "function ensureTaskReportAfterProcess(" not in task_runner
    assert "export function terminalAnswerText(" in task_final_report
    assert "function taskCompletionBannerHtml(" not in task_runner
    assert "export function taskCompletionBannerHtml(" in task_result_presentation
    assert "function announceTaskCompletion<" in task_run_events
    assert "function announceTaskCompletion(" not in task_runner
    assert "renderWorkspaceMarkdown(text)" in task_final_report
    assert "(window as any)._waRenderMarkdown" not in task_final_report
    assert "wa-task-final-report" in task_result_presentation
    assert (
        "export function shouldShowSupervisorAuditInResult("
        in task_plan_presentation
    )
    assert "function shouldShowSupervisorAuditInResult(" not in task_runner
    assert "shouldShowSupervisorAuditInResult(data)" in task_run_events
    assert "|| shouldShowSupervisorAuditInResult(data)" in task_run_events
    assert "renderTaskContextDetails(card)" in task_run_events
    assert "taskTerminalSummaryHtml({" in task_run_events
    assert "renderTaskFinalReport(state.visibleSummary)" in task_result_presentation
    assert "fileTaskOutcomeCopy" in task_result_presentation
    assert "任务已完成，结果和产物已就绪" in file_task_status
    assert "needs_attention" not in file_task_status
    assert (
        "if (normalized === 'context_summary_fallback') return '需复核';"
        in file_task_status
    )
    assert "模型未返回完整答案；当前仅显示基于已读上下文的临时摘要。" in file_task_status
    assert (
        "report.scrollIntoView({ behavior: 'smooth', block: 'nearest' });"
        in task_run_events
    )
    assert "wa-task-step-detail" in task_step_dom
    assert 'data-role="process"' in task_stage_presentation
    assert "ensureTaskReportAfterProcess(card);" in task_stage_presentation
    assert "runtime.ensureTaskReportAfterProcess(card);" not in task_stage_presentation
    assert "createTaskPlanEventHandlers" in task_runner
    assert (
        "'supervisor.step_verified': handleSupervisorStepVerified"
        in task_plan_events
    )
    assert "terminalAnswerText(" in dispatcher
    assert "function terminalTaskAnswer(" not in dispatcher
    assert "function terminalTaskTextValue(" not in dispatcher
    assert "from './task-final-report';" in dispatcher
    assert "dataset.taskFinalAnswer || dataset.taskSummary" in dispatcher
    assert "wa-task-final-answer-title" in conversation
    assert "function taskPlanSummaryFromElement(" in conversation
    assert "task_plan_summary: taskPlanSummary" in conversation
    assert "turn.task_plan_summary" in conversation


def test_compact_task_card_keeps_process_steps_visible_before_summary() -> None:
    css = _read("web/static/css/workspace-task-flow.css")

    hidden_blocks = re.findall(r"\{[^{}]*display\s*:\s*none\s*!important[^{}]*\}", css)
    assert not any('[data-role="plan"]' in block for block in hidden_blocks)
    assert not any('[data-role="steps"]' in block for block in hidden_blocks)

    task_presentation = _body_between(
        _read("web/src/workspace/task-stage-presentation.ts"),
        "  function makeRunCard(",
        "  function resetCanonicalTaskStageState(",
    )
    assert "ensureTaskStageOverview(card);" in task_presentation
    process_index = task_presentation.index('data-role="process"')
    summary_index = task_presentation.index('data-role="summary"')
    assert process_index < summary_index

    assert ".wa-task-run {" in css
    assert "flex-direction: column;" in css
    assert ".wa-task-stage-overview" in css
    assert ".wa-task-stage-track" in css
    assert ".wa-task-stage-current" in css
    assert ".wa-task-process" in css
    assert '.wa-task-row[data-task-detail-visibility="internal"]' in css
    assert ".wa-task-row.wa-task-performance" not in css
    assert "order: 10;" in css
    assert ".wa-task-summary" in css
    assert "order: 20;" in css


def test_task_card_uses_one_canonical_five_stage_projection() -> None:
    runner = _read("web/src/workspace/task-runner.ts")
    stage_presentation = _read("web/src/workspace/task-stage-presentation.ts")
    stage_state = _read("web/src/workspace/task-stage-state.ts")
    plan_events = _read("web/src/workspace/task-plan-event-handlers.ts")
    layout = _read("web/src/workspace/task-report-layout.ts")
    stream = _read("web/file_task_stream.py")
    css = _read("web/static/css/workspace-task-flow.css")

    assert "{ id: 'deliver', title: '交付结果'" in layout
    assert "export function taskStageProjectionFromEvent(" in stage_state
    assert "event.ui_state" in stage_state
    assert "createTaskStagePresentation" in runner
    assert "function applyCanonicalTaskStageState(" in stage_presentation
    assert "taskStageProjectionFromEvent(event)" in stage_presentation
    assert "projection.detailMode || 'replace'" in stage_presentation
    event_handler_start = plan_events.index(
        "export function createTaskPlanEventHandlers"
    )
    event_handlers = plan_events[event_handler_start:]
    assert "runtime.setTaskCurrentStage" not in event_handlers
    assert "handleEvent_progress" not in runner
    assert "_file_task_frontend_progress" not in stream
    assert '"type": "progress"' not in stream
    assert 'data-role="ui-progress"' not in runner
    assert ".wa-task-progress" not in css
    assert "grid-template-columns: repeat(5, minmax(0, 1fr));" in css
    assert 'aria-live="polite" aria-atomic="true"' in stage_presentation
    assert 'aria-label="任务阶段" aria-live="polite"' not in stage_presentation


def test_task_stream_feedback_uses_stable_wait_tiers_and_real_reconnect_states() -> None:
    lifecycle = _read("web/src/workspace/task-stream-lifecycle.ts")
    transport = _read("web/src/workspace/task-stream-transport.ts")
    feedback = _read("web/src/workspace/task-stream-feedback.ts")

    assert "taskWaitFeedback(idleMs)" in lifecycle
    assert "feedback.level === current.waitNoticeLevel" in lifecycle
    assert "已经 ' + secs + ' 秒" not in lifecycle
    assert "runtime.showReconnectNotice(streamingCard, 'failed')" in transport
    assert "runtime.showReconnectNotice(card, 'recovering')" in transport
    assert "当前步骤耗时较长，任务仍在运行。" in feedback
    assert "暂时无法同步最新进度，后台任务状态已保留。" in feedback


def test_task_card_uses_one_state_driven_primary_action_area() -> None:
    runner = _read("web/src/workspace/task-runner.ts")
    lifecycle = _read("web/src/workspace/task-stream-lifecycle.ts")
    stage_presentation = _read("web/src/workspace/task-stage-presentation.ts")
    result_presentation = _read(
        "web/src/workspace/task-result-presentation.ts"
    )
    css = _read("web/static/css/workspace-task-flow.css")

    assert 'data-role="task-primary-action"' in stage_presentation
    assert 'data-role="cancel"' not in stage_presentation
    assert "export function syncTaskPrimaryAction(" in result_presentation
    assert "function syncTaskPrimaryAction(" not in runner
    assert "taskPrimaryActionHtml({" in result_presentation
    assert "state.streamConnectionState === 'failed'" in result_presentation
    assert (
        "isFileTaskConfirmationStatus(terminal) && state.pendingResumePayload"
        in result_presentation
    )
    assert "state.streaming && !terminal" in result_presentation
    assert (
        "state.pendingResumePayload && isFileTaskConfirmationStatus(terminal)"
        in result_presentation
    )
    assert "const finalizeCancellation = (card: TCard): void =>" in lifecycle
    assert "card._abortFileTaskStream();" in lifecycle
    assert "finalizeCancellation: finalizeTaskCancellation," in runner
    assert ".wa-task-primary-action" in css
    assert ".wa-task-primary-button" in css


def test_visible_task_card_hides_duplicate_global_progress_indicator() -> None:
    stage_presentation = _read(
        "web/src/workspace/task-stage-presentation.ts"
    )

    assert (
        "function taskCardIsVisibleInViewport(card: TCard): boolean"
        in stage_presentation
    )
    assert "if (taskCardIsVisibleInViewport(card)) {" in stage_presentation
    assert "host.dataset.inlineOwner = 'true';" in stage_presentation


def test_task_result_css_has_one_owner_and_stable_load_order() -> None:
    workspace = _read("web/static/css/workspace.css")
    results = _read("web/static/css/workspace-task-results.css")
    index = _read("web/templates/index.html")

    for selector in (
        ".wa-task-final-report {",
        ".wa-task-completion-banner {",
        ".wa-task-interaction-card {",
        ".wa-task-artifact-summary-card {",
        ".wa-task-final-answer {",
        ".wa-task-result-context-body {",
    ):
        assert selector in results
        assert selector not in workspace

    assert (
        index.index("css/workspace.css")
        < index.index("css/workspace-task-flow.css")
        < index.index("css/workspace-task-results.css")
        < index.index("css/workspace-ai-panel.css")
    )


def test_task_flow_css_has_one_owner_and_stable_load_order() -> None:
    workspace = _read("web/static/css/workspace.css")
    flow = _read("web/static/css/workspace-task-flow.css")
    index = _read("web/templates/index.html")

    for selector in (
        ".wa-task-run {",
        ".wa-task-stage-overview {",
        ".wa-task-header {",
        ".wa-task-plan {",
        ".wa-task-step {",
        ".wa-task-row {",
        ".wa-task-artifacts {",
        ".wa-task-actions {",
        "#wa-ai-messages .wa-task-run.is-compact {",
        "#wa-ai-messages .wa-task-history-badge {",
    ):
        assert selector in flow
        assert selector not in workspace

    for retired_selector in (
        ".wa-task-confirmed-plan",
        ".wa-task-process-to-result",
        ".wa-task-evidence",
        ".wa-task-confidence-bar",
        ".wa-task-file-main",
        ".wa-task-warning",
        ".wa-task-report-header",
        ".wa-task-report-section",
    ):
        assert retired_selector not in workspace
        assert retired_selector not in flow

    assert (
        index.index("css/workspace.css")
        < index.index("css/workspace-task-flow.css")
        < index.index("css/workspace-task-results.css")
        < index.index("css/workspace-ai-panel.css")
    )


def test_task_result_summary_uses_one_canonical_artifact_list() -> None:
    task_runner = _read("web/src/workspace/task-runner.ts")
    run_events = _read("web/src/workspace/task-run-event-handlers.ts")
    presentation = _read("web/src/workspace/task-result-presentation.ts")

    assert (
        "const canonical = path.replace(/^workspace\\//i, '').toLowerCase();"
        in presentation
    )
    assert "const visibleLimit = 3;" in presentation
    assert "artifacts.length - visibleLimit" in presentation
    assert "runtime.getState(card)" in run_events
    assert "String(state.artifactsHtml || '')" in presentation
    assert "artifactsHtml," in run_events
    assert "renderTaskResultSummaryBar(card, result)" not in task_runner
    assert "wa-task-result-summary-bar" not in task_runner


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
    step_dom = _read("web/src/workspace/task-step-dom.ts")
    tool_output = _read("web/src/workspace/task-tool-output.ts")
    execution_events = _read(
        "web/src/workspace/task-execution-event-handlers.ts"
    )
    presentation = _read("web/src/workspace/task-plan-presentation.ts")

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

    assert "from './task-step-labels';" in step_dom
    assert "taskToolLabel(toolName)" in execution_events
    assert "from './task-step-labels';" in tool_output
    assert "isInternalTaskTool(name)" in tool_output
    assert "isReadTaskTool(name)" in tool_output
    assert "taskPlanViolationLabel(" in presentation


def test_task_runner_uses_shared_final_report_helpers() -> None:
    runner = _read("web/src/workspace/task-runner.ts")
    run_events = _read("web/src/workspace/task-run-event-handlers.ts")
    final_report = _read("web/src/workspace/task-final-report.ts")
    result_presentation = _read(
        "web/src/workspace/task-result-presentation.ts"
    )

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

    assert "from './task-final-report';" in run_events
    assert "renderTaskFinalReport(state.visibleSummary)" in result_presentation
    assert "terminalAnswerText(data, result.summary)" in run_events
    assert "renderWorkspaceMarkdown(text)" in final_report
    assert "(window as any)._waRenderMarkdown" not in final_report


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
        "export function updateTaskPerformanceRow(",
        "export function updateModelSummaryState(",
    ]:
        assert exported in performance

    assert "from './task-performance';" in runner
    assert "const next = updateTaskPerformanceDataset(current, data);" in performance
    assert "createModelSummaryState" not in runner
    assert "updateModelSummaryState" not in runner
    assert "route_decision_ms" in performance
    assert "intent_adjudication_ms" in performance


def test_task_detail_policy_hides_internal_events_and_keeps_user_evidence() -> None:
    runner = _read("web/src/workspace/task-runner.ts")
    step_dom = _read("web/src/workspace/task-step-dom.ts")
    plan_events = _read("web/src/workspace/task-plan-event-handlers.ts")
    verification_events = _read(
        "web/src/workspace/task-verification-event-handlers.ts"
    )
    policy = _read("web/src/workspace/task-detail-policy.ts")
    terminal_state = _read("web/src/workspace/task-terminal-state.ts")
    css = _read("web/static/css/workspace-task-flow.css")

    assert "export function shouldRenderTaskDetailEvent(" in policy
    assert "export function markTaskDetailRow(" in policy
    assert "'tool.started'" in policy
    assert "'file.changed'" in policy
    assert "'supervisor.status'" not in policy
    assert "'model.call.started'" not in policy
    assert "markTaskDetailRow(row, key);" in step_dom
    assert "data-task-detail-visibility" in css
    assert "state.modelSummaryRows" not in runner
    assert "state.readSummaries" not in runner
    assert "'model:call'" not in runner
    assert "upsertStepSingletonRow(step, 'run.started'" not in runner
    assert "upsertStepSingletonRow(step, 'check.started'" not in runner
    assert "shouldRenderTaskDetailEvent('step.result', data)" in verification_events
    assert "shouldRenderTaskDetailEvent('check.finished', data)" in verification_events
    assert "shouldRenderTaskDetailEvent('plan.checked', data)" in plan_events
    assert "shouldRenderTaskDetailEvent('plan.gated', data)" in plan_events
    assert "wa-task-plan-steps" in plan_events
    assert "body.innerHTML =" not in _body_between(
        terminal_state,
        "export function compactTerminalProcess(",
        "export function scheduleTaskLiveProgressCollapse(",
    )


def test_task_runner_uses_shared_interaction_summary_helpers() -> None:
    runner = _read("web/src/workspace/task-runner.ts")
    run_events = _read("web/src/workspace/task-run-event-handlers.ts")
    run_context = _read("web/src/workspace/task-run-context.ts")
    interaction = _read("web/src/workspace/task-interaction-summary.ts")

    for local_helper in [
        "function firstContextText(",
        "function taskContextSummaryText(",
        "function renderTaskInteractionLine(",
        "function renderTaskUnderstandingCard(",
        "function renderTaskMemoryCard(",
        "function renderTaskContextDetails(",
    ]:
        assert local_helper not in runner

    for exported in [
        "export function taskContextSummaryText(",
        "export function renderTaskInteractionLine(",
        "export function renderTaskUnderstandingCard(",
        "export function renderTaskMemoryCard(",
        "export function renderTaskContextDetails(",
    ]:
        assert exported in interaction

    assert "from './task-interaction-summary';" in runner
    assert "const contextSummary = taskContextSummaryText(taskContext);" in run_context
    assert "const html = renderTaskContextDetails(card);" in interaction
    assert "contextHtml: renderTaskContextDetails(card)" in run_events
    assert ".replace(/\\s+(?:最终)?结果\\s*[:：][\\s\\S]*$/u, '')" in interaction
    assert ':scope > [data-role="task-context"]' in interaction
    assert ':scope > [data-role="task-understanding"]' in interaction
    assert ':scope > [data-role="task-memory-summary"]' in interaction
    assert "export function syncTaskInteractionSummary<" in interaction
    assert "function syncTaskInteractionSummary(" not in runner
    assert "publishWorkspaceApi({" in runner
    published = runner.split("publishWorkspaceApi({", 1)[1].split("});", 1)[0]
    assert "syncTaskInteractionSummary" not in published


def test_task_runner_has_no_dead_presentation_helpers() -> None:
    runner = _read("web/src/workspace/task-runner.ts")
    result_presentation = _read(
        "web/src/workspace/task-result-presentation.ts"
    )

    for removed_helper in [
        "function eventPayload(",
        "function normalizeTaskContractText(",
        "function rowsColsText(",
        "function isReviewChangePayload(",
        "function upsertMultiTargetTerminalRow(",
        "function renderPlanStepItem(",
    ]:
        assert removed_helper not in runner

    assert "const questionText = completed ? '询问结果' : '追问原因';" not in runner
    assert (
        "const questionText = completed ? '询问结果' : '追问原因';"
        in result_presentation
    )
    assert (
        "const actionHint = completed ? '任务已完成，后续操作会作为新请求发送。' : '可继续补充要求或重新处理。';"
        in result_presentation
    )
    assert (
        "const row = upsertStepSingletonRow(step, tag, 'tool-start', content);"
        not in runner
    )
    assert "const row = upsertStepSingletonRow(step, tag, kind, content);" not in runner


def test_task_runner_plan_event_split_cannot_regress() -> None:
    runner = _read("web/src/workspace/task-runner.ts")
    plan_events = _read("web/src/workspace/task-plan-event-handlers.ts")
    stage_presentation = _read(
        "web/src/workspace/task-stage-presentation.ts"
    )

    assert len(runner.splitlines()) <= 1850
    assert "createTaskPlanEventHandlers<TaskCardElement>" in runner
    assert "createTaskStagePresentation<TaskCardElement, FileTaskUiState>" in runner
    assert "...PLAN_EVENT_HANDLERS" in runner
    assert "export function createTaskPlanEventHandlers" in plan_events
    assert "export function taskStepIdFromEvent" in plan_events
    assert "export function createTaskStagePresentation" in stage_presentation
    assert "function makeRunCard(" not in runner
    assert "function syncTaskStageOverview(" not in runner
    assert "function applyCanonicalTaskStageState(" not in runner
    for local_handler in (
        "function handleEvent_task_classified",
        "function handleEvent_plan_checked",
        "function handleEvent_plan_gated",
        "function handleEvent_supervisor_status",
        "function handleEvent_supervisor_intervention",
        "function handleEvent_supervisor_step_verified",
        "function handleEvent_decision_made",
        "function handleEvent_workflow_state",
    ):
        assert local_handler not in runner


def test_task_result_presentation_has_one_pure_owner() -> None:
    runner = _read("web/src/workspace/task-runner.ts")
    presentation = _read("web/src/workspace/task-result-presentation.ts")

    assert "from './task-result-presentation';" in runner
    for helper in (
        "taskArtifactItems",
        "taskArtifactsSummaryHtml",
        "taskResultRequiresUserConfirmation",
        "taskResultOutcomeCopy",
        "terminalStepSummary",
        "taskCompletionBannerHtml",
        "taskResultActionsHtml",
        "taskPrimaryActionHtml",
        "taskTerminalSummaryHtml",
    ):
        assert f"export function {helper}(" in presentation
        assert f"function {helper}(" not in runner

    assert "document." not in presentation
    assert "window." not in presentation
    assert "fetch(" not in presentation
    assert "正在恢复任务进度" not in runner
    assert "当前步骤已暂停，确认后继续" not in runner
    assert "任务已完成，后续操作会作为新请求发送。" not in runner


def test_task_runner_file_change_state_has_one_pure_owner() -> None:
    runner = _read("web/src/workspace/task-runner.ts")
    run_events = _read("web/src/workspace/task-run-event-handlers.ts")
    file_change_state = _read("web/src/workspace/task-file-change-state.ts")

    assert "from './task-file-change-state';" in run_events
    for helper in (
        "taskFileEventPath",
        "taskFileChangeDescriptor",
        "recordTaskFileChange",
        "recordTaskFileRefresh",
        "finalTaskOutputPath",
        "registerFinalTaskOutput",
    ):
        assert f"export function {helper}(" in file_change_state
        assert f"function {helper}(" not in runner
        assert f"function {helper}(" not in run_events

    assert "document." not in file_change_state
    assert "window." not in file_change_state
    assert "fetch(" not in file_change_state
    assert "fileChangeKeys.has(" not in runner
    assert len(runner.splitlines()) <= 1800


def test_task_runner_execution_evidence_handlers_have_one_owner() -> None:
    runner = _read("web/src/workspace/task-runner.ts")
    handlers = _read("web/src/workspace/task-execution-event-handlers.ts")

    assert "from './task-execution-event-handlers';" in runner
    assert "createTaskExecutionEventHandlers<" in runner
    assert "...EXECUTION_EVENT_HANDLERS" in runner
    assert "export function createTaskExecutionEventHandlers<" in handlers
    for event_name in (
        "'model.call.started'",
        "'model.call.finished'",
        "'tool.started'",
        "'tool.finished'",
        "'file.changed'",
        "'read.changed'",
        "code_summary",
        "file_refresh",
    ):
        assert event_name in handlers

    for local_handler in (
        "handleEvent_model_call_started",
        "handleEvent_model_call_finished",
        "handleEvent_tool_started",
        "handleEvent_tool_finished",
        "handleEvent_file_changed",
        "handleEvent_read_changed",
        "handleEvent_code_summary",
        "handleEvent_file_refresh",
    ):
        assert local_handler not in runner

    assert "readKeys.has(path)" not in runner
    assert "codeSummaryRows.has(codeKey)" not in runner
    assert len(runner.splitlines()) <= 1200


def test_task_runner_verification_handlers_have_one_owner() -> None:
    runner = _read("web/src/workspace/task-runner.ts")
    handlers = _read("web/src/workspace/task-verification-event-handlers.ts")

    assert "from './task-verification-event-handlers';" in runner
    assert "createTaskVerificationEventHandlers<" in runner
    assert "...VERIFICATION_EVENT_HANDLERS" in runner
    assert "export function createTaskVerificationEventHandlers<" in handlers
    for event_name in (
        "model_summary",
        "'step.started'",
        "'step.finished'",
        "'step.result'",
        "'check.started'",
        "'check.finished'",
    ):
        assert event_name in handlers

    for local_handler in (
        "handleEvent_model_summary",
        "handleEvent_step_started",
        "handleEvent_step_result",
        "handleEvent_check_started",
        "handleEvent_check_finished",
    ):
        assert local_handler not in runner


def test_task_runner_terminal_handlers_have_one_finish_owner() -> None:
    runner = _read("web/src/workspace/task-runner.ts")
    handlers = _read("web/src/workspace/task-terminal-event-handlers.ts")

    assert "from './task-terminal-event-handlers';" in runner
    assert "createTaskTerminalEventHandlers<" in runner
    assert "...TERMINAL_EVENT_HANDLERS" in runner
    assert "export function createTaskTerminalEventHandlers<" in handlers
    assert "'run.cancelled': handleCancelled" in handlers
    assert "error: handleError" in handlers
    assert "handleEvent_run_cancelled" not in runner
    assert "handleEvent_error" not in runner
    assert "syncTaskLiveProgress(" not in handlers


def test_task_runner_run_lifecycle_has_one_event_owner() -> None:
    runner = _read("web/src/workspace/task-runner.ts")
    handlers = _read("web/src/workspace/task-run-event-handlers.ts")

    assert "from './task-run-event-handlers';" in runner
    assert "createTaskRunEventHandlers<" in runner
    assert "...RUN_EVENT_HANDLERS" in runner
    assert "export function createTaskRunEventHandlers<" in handlers
    assert "'run.started': handleStarted" in handlers
    assert "'run.finished': handleFinished" in handlers
    assert "finish: RUN_EVENT_HANDLERS['run.finished']" in runner
    assert "function handleEvent_run_started" not in runner
    assert "function handleEvent_run_finished" not in runner
    assert "function openFinalTaskOutput" not in runner
    assert "function announceTaskCompletion" not in runner
    assert "function taskTerminalResult" not in runner
    assert "export function taskTerminalResult<" in handlers


def test_task_runner_run_context_has_one_dataset_owner() -> None:
    runner = _read("web/src/workspace/task-runner.ts")
    context = _read("web/src/workspace/task-run-context.ts")

    assert "from './task-run-context';" in runner
    assert "createTaskRunContextUpdater<TaskCardElement>({" in runner
    assert "export function createTaskRunContextUpdater<" in context
    assert "export function decodeTaskRequestPayload(" in context
    assert "export function decodeTaskArtifactResult(" in context
    assert "runtime.encodeTaskContract(taskContract)" in context
    assert "encodeTaskContract," in runner
    assert "function setTaskRunContext(" not in runner
    assert "function decodeTaskRequestPayload(" not in runner
    assert "function decodeTaskArtifactResult(" not in runner
    assert "workspaceApi.encodeTaskContract" not in runner


def test_task_runner_ui_state_has_one_hydration_owner() -> None:
    runner = _read("web/src/workspace/task-runner.ts")
    ui_state = _read("web/src/workspace/task-ui-state.ts")

    assert "from './task-ui-state';" in runner
    assert "export interface FileTaskUiState" in ui_state
    assert "export function createFileTaskUiState(" in ui_state
    assert "export function hydrateTaskUiStateFromDom(" in ui_state
    assert "export function ensureTaskUiState(" in ui_state
    assert "export function noteTaskStreamIssue(" in ui_state
    assert "interface FileTaskUiState" not in runner
    assert "function hydrateTaskUiStateFromDom(" not in runner
    assert "function ensureTaskUiState(" not in runner
    assert "function noteStreamIssue(" not in runner


def test_task_dispatcher_payload_contract_has_one_pure_function_owner() -> None:
    dispatcher = _read("web/src/workspace/task-dispatcher.ts")
    payload = _read("web/src/workspace/task-dispatcher-payload.ts")

    assert "from './task-dispatcher-payload';" in dispatcher
    for helper in (
        "cloneTaskPayload",
        "compactJsonValue",
        "compactFollowupTaskFile",
        "compactTaskContext",
        "compactFollowupTaskPayload",
        "compactPendingResumePayload",
        "buildTaskContextPackage",
    ):
        assert f"export function {helper}(" in payload
        assert f"function {helper}(" not in dispatcher

    assert "document." not in payload
    assert "window." not in payload
    assert "fetch(" not in payload


def test_task_dispatcher_file_context_and_target_inference_have_pure_owners() -> None:
    dispatcher = _read("web/src/workspace/task-dispatcher.ts")
    file_contract = _read("web/src/workspace/task-file-contract.ts")
    workspace_context = _read("web/src/workspace/task-workspace-context.ts")
    target_inference = _read("web/src/workspace/task-target-inference.ts")

    assert "from './task-file-contract';" in dispatcher
    assert "from './task-workspace-context';" in dispatcher
    assert "from './task-target-inference';" in dispatcher
    assert "export interface TaskFileInfo" in file_contract
    assert "export function buildWorkspaceRouteFiles(" in workspace_context
    assert "export function buildCurrentOpenTaskFile(" in workspace_context
    assert (
        "export function buildWorkspaceChatFileContextValue("
        in workspace_context
    )
    assert (
        "export function inferAttachedWriteTargetFile("
        in target_inference
    )
    assert (
        "export function explicitWriteTargetPathFromText("
        in target_inference
    )

    for source in (file_contract, workspace_context, target_inference):
        assert "document." not in source
        assert "window." not in source
        assert "fetch(" not in source

    assert "function inferAttachedWriteTargetFile(" not in dispatcher
    assert "function explicitWriteTargetPathFromText(" not in dispatcher
    assert len(dispatcher.splitlines()) <= 1300


def test_task_dispatcher_routing_decisions_have_one_pure_owner() -> None:
    dispatcher = _read("web/src/workspace/task-dispatcher.ts")
    routing = _read("web/src/workspace/task-routing-decision.ts")

    assert "from './task-routing-decision';" in dispatcher
    for helper in (
        "deterministicWorkspaceRouteDecision",
        "fileTaskRouteDecision",
        "isDirectWorkspaceResponse",
        "normalizeFileTaskRoutingDecision",
        "normalizeWorkspaceRouteDecision",
        "shouldBypassWorkspaceRoute",
        "shouldForceFileTaskForWorkspaceContext",
    ):
        assert f"export function {helper}(" in routing
        assert f"function {helper}(" not in dispatcher

    assert "document." not in routing
    assert "window." not in routing
    assert "fetch(" not in routing
    assert len(dispatcher.splitlines()) <= 1150


def test_task_dispatcher_direct_chat_stream_has_one_transport_owner() -> None:
    dispatcher = _read("web/src/workspace/task-dispatcher.ts")
    direct_chat = _read("web/src/workspace/task-direct-chat.ts")

    assert "from './task-direct-chat';" in dispatcher
    assert "createWorkspaceChatStreamer({" in dispatcher
    assert "export function createWorkspaceChatStreamer(" in direct_chat
    assert "export function parseWorkspaceSseEvents(" in direct_chat
    assert "export function appendWorkspaceChatEvents(" in direct_chat
    assert "buffer += decoder.decode();" in direct_chat
    assert "function parseWorkspaceSseEvents(" not in dispatcher
    assert "function streamWorkspaceChatRoute(" not in dispatcher
    assert "'/api/chat/stream'" not in dispatcher
    assert len(dispatcher.splitlines()) <= 1000


def test_task_runner_stream_events_have_one_dispatch_owner() -> None:
    runner = _read("web/src/workspace/task-runner.ts")
    dispatch = _read("web/src/workspace/file-task-dispatch.ts")

    assert "from './file-task-dispatch';" in runner
    assert "createFileTaskEventController<TaskCardElement, FileTaskUiState>({" in runner
    assert "export function createFileTaskEventController<" in dispatch
    assert "export function fileTaskEventSequence(" in dispatch
    assert "event.event_seq || payload.seq || payload.event_seq" in dispatch
    assert "duplicate-event-${eventKey}" in dispatch
    assert "out-of-order-event-${runId}-${seq}" in dispatch
    assert "missing-event-${runId}-${state.lastEventSeq}-${seq}" in dispatch
    assert "function streamEventSeq(" not in runner
    assert "function shouldDispatchStreamEvent(" not in runner
    assert "function dispatchEventToCard(" not in runner
    assert "function processFileTaskStreamEvent(" not in runner


def test_task_runner_stream_lifecycle_has_one_owner() -> None:
    runner = _read("web/src/workspace/task-runner.ts")
    lifecycle = _read("web/src/workspace/task-stream-lifecycle.ts")

    assert "from './task-stream-lifecycle';" in runner
    assert "createTaskStreamLifecycle<TaskCardElement, FileTaskUiState>({" in runner
    assert "export function createTaskStreamLifecycle<" in lifecycle
    assert "export async function consumeTaskEventStream(" in lifecycle
    assert "export function installTaskCancelHandler<" in lifecycle
    assert "taskWaitFeedback(idleMs)" in lifecycle
    assert "const finalizeCancellation = (card: TCard): void =>" in lifecycle
    assert "function startTaskHeartbeat(" not in runner
    assert "function finalizeTaskCancellation(" not in runner
    assert "while (true) {\n    const chunk = await reader.read();" not in runner
    assert len(runner.splitlines()) <= 1700


def test_task_runner_recovery_and_snapshot_lifecycle_have_one_owner() -> None:
    runner = _read("web/src/workspace/task-runner.ts")
    recovery = _read("web/src/workspace/task-run-recovery.ts")

    assert "from './task-run-recovery';" in runner
    assert "createTaskRunRecovery<TaskCardElement>({" in runner
    assert "export function createTaskRunRecovery<" in recovery
    assert "export function notifyTaskCardSnapshot<" in recovery
    assert "export function installTerminalSnapshotHandler<" in recovery
    assert "const markTaskRunCardAsHistory = (" in recovery
    assert "const restoreTaskRunCard = (" in recovery
    assert "const resumePersistedFileTask = (" in recovery
    assert "function markTaskRunCardAsHistory(" not in runner
    assert "function restoreTaskRunCard(" not in runner
    assert "function resumePersistedFileTask(" not in runner
    assert "_terminalSnapshotHandler" not in runner
    assert "_terminalSnapshotHandler" in recovery
    assert len(runner.splitlines()) <= 1450


def test_task_runner_terminal_state_has_one_owner() -> None:
    runner = _read("web/src/workspace/task-runner.ts")
    run_events = _read("web/src/workspace/task-run-event-handlers.ts")
    terminal_state = _read("web/src/workspace/task-terminal-state.ts")
    transport = _read("web/src/workspace/task-stream-transport.ts")

    assert "from './task-terminal-state';" in runner
    assert "from './task-terminal-state';" in run_events
    for helper in (
        "applyTaskTerminalCardPresentation",
        "compactTerminalProcess",
        "persistTerminalTaskCard",
        "scheduleTaskLiveProgressCollapse",
        "taskTerminalProjection",
    ):
        assert f"{helper}," in run_events
        assert f"export function {helper}(" in terminal_state

    assert "prepareTaskCardForActiveRun," in runner
    assert "prepareTaskCardForActiveRun," in run_events
    assert "export function prepareTaskCardForActiveRun(" in terminal_state

    assert "card.classList.remove('streaming', 'pending', 'done', 'failed', 'cancelled');" in terminal_state
    assert run_events.count("prepareTaskCardForActiveRun(card);") >= 1
    assert "prepareActive: prepareTaskCardForActiveRun" in runner
    assert "runtime.prepareActive(card);" in transport
    assert "card.classList.add('streaming');" not in runner
    assert "function compactTerminalProcess(" not in runner
    assert "function scheduleTaskLiveProgressCollapse(" not in runner
    assert "card.dataset.taskTerminalStatus = result.terminal_status" not in runner
    assert len(runner.splitlines()) <= 1450


def test_task_runner_step_dom_has_one_owner() -> None:
    runner = _read("web/src/workspace/task-runner.ts")
    step_dom = _read("web/src/workspace/task-step-dom.ts")

    assert "from './task-step-dom';" in runner
    for helper in (
        "appendTaskStepRow",
        "ensureTaskStep",
        "markTaskStepDone",
        "markTaskStepFailed",
        "markTaskStepRunning",
        "removeTaskStepRow",
        "setTaskStatus",
        "taskStageStep",
        "upsertTaskStepSingletonRow",
    ):
        assert f"export function {helper}(" in step_dom

    assert "removeStatusRow: (card, role) => removeTaskStepRow(card, 'run', role)" in runner
    assert "function ensureStep(" not in runner
    assert "function markStepRunning(" not in runner
    assert "function markStepDone(" not in runner
    assert "function markStepFailed(" not in runner
    assert "function appendRow(" not in runner
    assert "function upsertStepSingletonRow(" not in runner
    assert "function removeTaskRunStatusRow(" not in runner
    assert len(runner.splitlines()) <= 750


def test_task_runner_card_interactions_have_one_owner() -> None:
    runner = _read("web/src/workspace/task-runner.ts")
    interactions = _read("web/src/workspace/task-card-interactions.ts")

    assert "from './task-card-interactions';" in runner
    assert "createTaskCardInteractionController<TaskCardElement>({" in runner
    assert "export function createTaskCardInteractionController<" in interactions
    assert "export interface TaskCardInteractionActions<" in interactions
    assert "bindTaskCardInteractionActions," in runner
    assert "bindTaskCardInteractionActions({" in runner
    assert "resumePersistedTask: resumePersistedFileTask" in runner
    assert "attachRunCardBehaviorImpl" not in runner
    for selector in (
        "[data-task-followup-action]",
        "[data-task-artifacts-open]",
        "[data-task-artifact-resume]",
        "[data-task-stream-retry]",
        '[data-role="cancel"]',
    ):
        assert selector in interactions
        assert selector not in runner

    assert "beginTaskResultFollowup({" in interactions
    assert "task artifact resume parse failed" in interactions
    assert "task stream retry failed" in interactions
    assert "card.addEventListener('click'" in interactions
    assert "card.addEventListener('click'" not in runner
    assert "type TaskCardElement = TaskUiStateCard;" in runner
    assert "export type TaskCardElement" not in runner
    for stale_field in (
        "_progressRow?:",
        "_multiTargetTerminalRow?:",
        "_stepResultRow?:",
        "_completedChunkRows?:",
        "_singletonRows?:",
        "_fileRefreshHashes?:",
    ):
        assert stale_field not in runner
    assert len(runner.splitlines()) <= 650


def test_task_runner_stream_transport_has_one_owner() -> None:
    runner = _read("web/src/workspace/task-runner.ts")
    transport = _read("web/src/workspace/task-stream-transport.ts")

    assert "from './task-stream-transport';" in runner
    assert "createTaskStreamTransport<" in runner
    assert "TaskRunTerminalResult<TaskCardElement>" in runner
    assert "export function createTaskStreamTransport<" in transport
    assert "setResumePersistedTask(resumePersistedFileTask);" in runner
    for helper in (
        "createFileTaskId",
        "createFileTaskRunId",
        "scheduleTaskStream",
        "appendTaskRunCardIfDetached",
        "streamTaskSse",
        "streamTaskFlow",
    ):
        assert f"function {helper}(" in transport
        assert f"function {helper}(" not in runner

    assert "runtime.csrfFetch('/api/editor/ai/task-stream'" in transport
    assert "consumeTaskEventStream(reader" in transport
    assert "installTaskCancelHandler(" in transport
    assert "installTerminalSnapshotHandler(" in transport
    assert "任务状态流已断开，正在保留后台任务状态。" in transport
    assert "任务状态流已断开，正在保留后台任务状态。" not in runner
    assert len(runner.splitlines()) <= 450


def test_task_runner_local_presentation_bridges_use_existing_owners() -> None:
    runner = _read("web/src/workspace/task-runner.ts")
    performance = _read("web/src/workspace/task-performance.ts")
    interaction = _read("web/src/workspace/task-interaction-summary.ts")
    result = _read("web/src/workspace/task-result-presentation.ts")
    stage = _read("web/src/workspace/task-stage-presentation.ts")

    assert "export function updateTaskPerformanceRow(" in performance
    assert "export function syncTaskInteractionSummary<" in interaction
    assert "export function syncTaskPrimaryAction(" in result
    assert "export function ensureTaskReportAfterProcess<" in stage
    assert "export function restoreTaskStageStatus<" in stage
    for local_helper in (
        "function updateTaskPerformanceRow(",
        "function syncTaskInteractionSummary(",
        "function syncTaskPrimaryAction(",
        "function ensureTaskReportAfterProcess(",
        "function restoreTaskStageStatus(",
    ):
        assert local_helper not in runner

    assert "syncInteractionSummary: syncTaskInteractionSummary" in runner
    assert "ensureReport: ensureTaskReportAfterProcess" in runner
    assert "restoreTaskStageStatus(card, setStatus)" in runner
    assert len(runner.splitlines()) <= 350


def test_task_runner_assembly_has_no_dead_bindings() -> None:
    runner = _read("web/src/workspace/task-runner.ts")

    assert "taskResultRequiresUserConfirmation" not in runner
    assert "clearTransientFeedback:" not in runner
    assert "clearTaskTransientFeedback" not in runner
    assert "const renderPlanIntoCard" not in runner
    assert "renderPlanIntoCard: renderPlanIntoTaskCard" in runner
    assert runner.count("normalizeWorkspacePath: normalizeWorkspaceFilePath") == 2
    assert "showReconnectNotice: showTaskStreamReconnectNotice" in runner
    assert "export type TerminalResult" not in runner
    assert len(runner.splitlines()) <= 300
