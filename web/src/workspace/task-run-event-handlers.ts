import {
  fileTaskTerminalUiStatus,
  normalizeFileTaskTerminalStatus,
} from './file-task-status';
import { terminalAnswerText } from './task-final-report';
import { renderTaskContextDetails } from './task-interaction-summary';
import { normalizedTaskLifecyclePayload } from './task-lifecycle-payload';
import {
  shouldShowSupervisorAuditInResult,
  supervisorAuditHtml,
} from './task-plan-presentation';
import {
  taskArtifactsSummaryHtml,
  taskResultActionsHtml,
  taskResultOutcomeCopy,
  taskTerminalSummaryHtml,
  terminalStepSummary,
} from './task-result-presentation';
import { registerFinalTaskOutput } from './task-file-change-state';
import {
  applyTaskTerminalCardPresentation,
  compactTerminalProcess,
  persistTerminalTaskCard,
  prepareTaskCardForActiveRun,
  scheduleTaskLiveProgressCollapse,
  taskTerminalProjection,
  type TaskTerminalCard,
} from './task-terminal-state';

export interface TaskRunEventCard extends TaskTerminalCard {
  _fatalErrorText?: string;
}

export interface TaskRunEventUiState {
  fileChanges: any[];
}

export interface TaskRunTerminalResult<TCard extends TaskRunEventCard> {
  summary: string;
  status: string;
  task_id: string;
  run_id: string;
  loadingEl: TCard | null;
  terminal_status: string;
  completed_task: boolean;
}

export type TaskRunEventHandler<TCard extends TaskRunEventCard> = (
  _card: TCard,
  _event: Record<string, any>,
  _payload: Record<string, any>,
) => void;

export interface TaskRunEventRuntime<
  TCard extends TaskRunEventCard,
  TState extends TaskRunEventUiState,
> {
  getState: (_card: TCard) => TState;
  ensureReport: (_card: TCard) => unknown;
  setRunContext: TaskRunEventHandler<TCard>;
  taskStageStep: (_card: TCard, _stepId: string) => HTMLElement;
  markStepRunning: (_step: HTMLElement) => void;
  markStepDone: (_step: HTMLElement) => void;
  markStepFailed: (_step: HTMLElement) => void;
  setCurrentStage: (_card: TCard, _stageId: string, _detail?: string) => void;
  setStatus: (_card: TCard, _text: string) => void;
  updatePerformance: (_card: TCard, _data: Record<string, any>) => void;
  startHeartbeat: (_card: TCard) => void;
  stopHeartbeat: (_card: TCard) => void;
  syncLiveProgress: (_card: TCard) => void;
  decodeArtifactResult: (_card: TCard) => Record<string, any> | null;
  normalizeWorkspacePath: (_value: unknown) => string;
  reloadFileByPath: (_path: string, _force: boolean) => unknown;
  persistTerminalCard: (_card: TaskTerminalCard) => unknown;
  showToast: (
    _message: string,
    _type: 'error' | 'warning' | 'success' | 'info',
    _duration: number,
  ) => void;
}

function boolAttr(value: unknown): boolean {
  return String(value || '').trim().toLowerCase() === 'true';
}

export function taskTerminalResult<TCard extends TaskRunEventCard>(
  card: TCard,
  fallbackSummary = '',
): TaskRunTerminalResult<TCard> {
  const dataset = card && card.dataset ? card.dataset : {};
  const terminalStatus = normalizeFileTaskTerminalStatus(
    dataset.taskTerminalStatus || '',
  );
  const failureSummary = String(dataset.taskFailureSummary || '').trim();
  const explicitSummary = String(
    failureSummary
    || fallbackSummary
    || dataset.taskFinalAnswer
    || dataset.taskSummary
    || '',
  ).trim();
  const fatalSummary = String(card && card._fatalErrorText || '').trim();
  const completedTask = Object.prototype.hasOwnProperty.call(dataset, 'taskCompleted')
    ? boolAttr(dataset.taskCompleted)
    : ['completed', 'done', 'verified'].includes(terminalStatus);
  const status = fileTaskTerminalUiStatus(
    terminalStatus,
    completedTask,
    fatalSummary,
  );
  return {
    summary: explicitSummary || fatalSummary || '文件任务流已结束。',
    status,
    task_id: String(dataset.taskId || '').trim(),
    run_id: String(dataset.taskRunId || '').trim(),
    loadingEl: card || null,
    terminal_status: terminalStatus,
    completed_task: completedTask,
  };
}

function announceTaskCompletion<TCard extends TaskRunEventCard>(
  runtime: TaskRunEventRuntime<TCard, TaskRunEventUiState>,
  card: TCard,
  result: TaskRunTerminalResult<TCard>,
  report: HTMLElement | null,
): void {
  if (!card || card.dataset.historySnapshot === 'true' || !card.isConnected) return;
  const status = String(result && result.status || 'done').trim() || 'done';
  if (card.dataset.taskCompletionAnnounced === status) return;
  card.dataset.taskCompletionAnnounced = status;
  const copy = taskResultOutcomeCopy(result);
  runtime.showToast(
    copy.toast,
    copy.toastType,
    copy.toastType === 'error' ? 3600 : 3200,
  );
  window.requestAnimationFrame(() => {
    if (!report || !report.isConnected) return;
    report.classList.add('is-revealed');
    if (typeof report.scrollIntoView === 'function') {
      report.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  });
}

function openFinalTaskOutput<
  TCard extends TaskRunEventCard,
  TState extends TaskRunEventUiState,
>(
  runtime: TaskRunEventRuntime<TCard, TState>,
  card: TCard,
  data: Record<string, any>,
  result: TaskRunTerminalResult<TCard>,
): void {
  const artifactResult = data.artifact_result && typeof data.artifact_result === 'object'
    ? data.artifact_result
    : runtime.decodeArtifactResult(card);
  const path = registerFinalTaskOutput(
    card,
    data,
    result,
    artifactResult,
    runtime.getState(card).fileChanges,
    runtime.normalizeWorkspacePath,
  );
  if (!path) return;
  window.setTimeout(() => {
    Promise.resolve(runtime.reloadFileByPath(path, true)).catch((error) => {
      console.warn('[FileTask] final output open failed:', error);
    });
  }, 0);
}

export function createTaskRunEventHandlers<
  TCard extends TaskRunEventCard,
  TState extends TaskRunEventUiState,
>(
  runtime: TaskRunEventRuntime<TCard, TState>,
): Record<string, TaskRunEventHandler<TCard>> {
  const handleStarted: TaskRunEventHandler<TCard> = (card, evt, payload) => {
    const data = normalizedTaskLifecyclePayload(payload);
    runtime.setRunContext(card, evt, payload);
    prepareTaskCardForActiveRun(card);
    runtime.markStepRunning(runtime.taskStageStep(card, 'route'));
    runtime.updatePerformance(card, data);
    runtime.startHeartbeat(card);
    if (data.tool_use_id) {
      card.dataset.taskToolUseId = String(data.tool_use_id || '').trim();
    }
  };

  const handleFinished: TaskRunEventHandler<TCard> = (card, evt, payload) => {
    const data = normalizedTaskLifecyclePayload(payload);
    runtime.ensureReport(card);
    runtime.setRunContext(card, evt, payload);
    runtime.stopHeartbeat(card);
    const executeStep = runtime.taskStageStep(card, 'execute');
    const planStep = card.querySelector(
      '[data-role="steps"] .wa-task-step[data-step-id="plan"]',
    ) as HTMLElement | null;
    if (planStep && !planStep.classList.contains('failed')) {
      runtime.markStepDone(planStep);
    }
    const checkStep = runtime.taskStageStep(card, 'check');
    const terminalAnswer = terminalAnswerText(data, terminalAnswerText(payload, ''));
    const result = taskTerminalResult(
      card,
      terminalAnswer || '文件任务流已结束。',
    );
    const projection = taskTerminalProjection(
      result,
      String(card.dataset.taskTitle || '').trim(),
    );
    card.dataset.taskTerminalStatus = projection.terminalStatus;
    runtime.setCurrentStage(card, 'check', terminalStepSummary(result));
    if (projection.executeStepState === 'failed') runtime.markStepFailed(executeStep);
    else if (projection.executeStepState === 'running') runtime.markStepRunning(executeStep);
    else runtime.markStepDone(executeStep);

    const runStep = card.querySelector(
      '[data-role="steps"] .wa-task-step[data-step-id="run"]',
    ) as HTMLElement | null;
    if (runStep) {
      if (projection.runStepState === 'failed') runtime.markStepFailed(runStep);
      else runtime.markStepDone(runStep);
    }
    if (projection.checkStepState === 'failed') runtime.markStepFailed(checkStep);
    else if (projection.checkStepState === 'running') runtime.markStepRunning(checkStep);
    else runtime.markStepDone(checkStep);

    runtime.setStatus(card, projection.statusText);
    compactTerminalProcess(card, result);
    runtime.updatePerformance(card, data);
    applyTaskTerminalCardPresentation(card, projection);

    const summaryContainer = card.querySelector(
      '[data-role="summary"]',
    ) as HTMLElement | null;
    let finalReportEl: HTMLElement | null = null;
    if (summaryContainer) {
      const finalReport = terminalAnswerText(data, result.summary);
      const visibleSummary = finalReport || terminalStepSummary(result);
      const state = runtime.getState(card);
      const artifactsHtml = taskArtifactsSummaryHtml(
        runtime.decodeArtifactResult(card),
        state.fileChanges,
      );
      const auditHtml = (
        result.status === 'error'
        || shouldShowSupervisorAuditInResult(data)
      ) ? supervisorAuditHtml(data) : '';
      summaryContainer.innerHTML = taskTerminalSummaryHtml({
        result,
        visibleSummary,
        artifactsHtml,
        auditHtml,
        contextHtml: renderTaskContextDetails(card),
        actionsHtml: taskResultActionsHtml({
          terminalStatus: String(card.dataset.taskTerminalStatus || ''),
          completedTask: String(card.dataset.taskCompleted || '').trim().toLowerCase() !== 'false',
          pendingResumePayload: String(card.dataset.taskPendingResumePayload || '').trim(),
          taskRequest: String(card.dataset.taskRequest || '').trim(),
          pendingLabel: String(card.dataset.taskPendingResumeLabel || '').trim(),
          quickActionMode: String(card.dataset.taskQuickActionMode || '').trim(),
          canApply: boolAttr(card.dataset.taskIntentCanApply),
          requiresConfirmation: boolAttr(card.dataset.taskIntentRequiresConfirmation),
          outputMode: String(card.dataset.taskOutputMode || '').trim().toLowerCase(),
        }),
      });
      summaryContainer.hidden = false;
      finalReportEl = summaryContainer.querySelector(
        '[data-role="final-report"]',
      ) as HTMLElement | null;
      card.dataset.taskSummary = visibleSummary;
      card.dataset.taskFinalAnswer = visibleSummary;
    }

    const loadedSummary = terminalAnswerText(data, result.summary);
    card.dataset.taskSummary = loadedSummary || card.dataset.taskSummary || '';
    card.dataset.taskFinalAnswer = loadedSummary
      || card.dataset.taskFinalAnswer
      || card.dataset.taskSummary
      || '';
    runtime.syncLiveProgress(card);
    scheduleTaskLiveProgressCollapse(card);
    announceTaskCompletion(
      runtime as TaskRunEventRuntime<TCard, TaskRunEventUiState>,
      card,
      result,
      finalReportEl,
    );
    openFinalTaskOutput(runtime, card, data, result);
    persistTerminalTaskCard(card, runtime.persistTerminalCard);
  };

  return {
    'run.started': handleStarted,
    'run.finished': handleFinished,
  };
}
