import {
  isFileTaskFailureStatus,
  isFileTaskWaitingStatus,
  normalizeFileTaskTerminalStatus,
} from './file-task-status';
import { compactFlowSummary } from './task-final-report';
import { normalizedTaskLifecyclePayload } from './task-lifecycle-payload';
import { taskStepIdFromEvent } from './task-plan-event-handlers';
import { shouldRenderTaskDetailEvent } from './task-detail-policy';
import { escHtml as esc } from '../shared/sanitize';

export type TaskVerificationEventHandler<TCard extends HTMLElement> = (
  _card: TCard,
  _event: Record<string, any>,
  _payload: Record<string, any>,
) => void;

export interface TaskVerificationEventRuntime<TCard extends HTMLElement> {
  taskStageStep: (_card: TCard, _stepId: string) => HTMLElement;
  markStepDone: (_step: HTMLElement) => void;
  markStepRunning: (_step: HTMLElement) => void;
  markStepFailed: (_step: HTMLElement) => void;
  setRunContext: (
    _card: TCard,
    _event: Record<string, any>,
    _payload: Record<string, any>,
  ) => void;
  upsertStepRow: (
    _step: HTMLElement,
    _role: string,
    _kind: string,
    _html: string,
  ) => HTMLElement | null;
}

export function createTaskVerificationEventHandlers<TCard extends HTMLElement>(
  runtime: TaskVerificationEventRuntime<TCard>,
): Record<string, TaskVerificationEventHandler<TCard>> {
  const markModelSummary: TaskVerificationEventHandler<TCard> = (card) => {
    runtime.markStepRunning(runtime.taskStageStep(card, 'execute'));
  };

  const handleStepStarted: TaskVerificationEventHandler<TCard> = (card, evt, payload) => {
    const data = normalizedTaskLifecyclePayload(payload);
    runtime.markStepRunning(runtime.taskStageStep(card, taskStepIdFromEvent(evt, data)));
  };

  const handleStepResult: TaskVerificationEventHandler<TCard> = (card, evt, payload) => {
    const data = normalizedTaskLifecyclePayload(payload);
    const stepId = taskStepIdFromEvent(evt, data);
    const step = runtime.taskStageStep(card, stepId);
    const status = normalizeFileTaskTerminalStatus(data.status || '');
    const pending = isFileTaskWaitingStatus(status);
    const failed = !pending && isFileTaskFailureStatus(status);
    if (failed) runtime.markStepFailed(step);
    else if (pending) runtime.markStepRunning(step);
    else runtime.markStepDone(step);

    if (!shouldRenderTaskDetailEvent('step.result', data)) return;
    const title = String(data.title || evt.step_id || stepId || '任务步骤').trim();
    const summary = compactFlowSummary(
      String(data.summary || data.text || data.message || '').trim(),
      '已完成',
    );
    const chip = failed ? '需处理' : '待处理';
    runtime.upsertStepRow(
      step,
      `step.result:${stepId}:${title}`,
      failed ? 'warn' : 'progress',
      '<span class="wa-task-chip ' + (failed ? 'warn' : '') + '">'
        + esc(chip) + '</span>' + esc(summary || title),
    );
  };

  const handleCheckStarted: TaskVerificationEventHandler<TCard> = (card, evt, payload) => {
    runtime.setRunContext(card, evt, payload);
    runtime.markStepRunning(runtime.taskStageStep(card, 'check'));
  };

  const handleCheckFinished: TaskVerificationEventHandler<TCard> = (card, evt, payload) => {
    const data = normalizedTaskLifecyclePayload(payload);
    runtime.setRunContext(card, evt, payload);
    const step = runtime.taskStageStep(card, 'check');
    const status = normalizeFileTaskTerminalStatus(data.status || '');
    const waiting = isFileTaskWaitingStatus(status);
    const passed = data.passed !== false && !isFileTaskFailureStatus(status);
    const summary = String(
      data.summary
      || data.message
      || (waiting ? '核验已暂停，等待确认后继续。'
        : (passed ? '结果核验通过。' : '结果核验未通过。')),
    ).trim();
    if (waiting) runtime.markStepRunning(step);
    else if (passed) runtime.markStepDone(step);
    else runtime.markStepFailed(step);

    if (!shouldRenderTaskDetailEvent('check.finished', data)) return;
    runtime.upsertStepRow(
      step,
      'check.finished',
      waiting ? 'progress' : 'warn',
      '<span class="wa-task-chip ' + (waiting ? '' : 'warn') + '">'
        + esc(waiting ? '待确认' : '核验未通过')
        + '</span>' + esc(summary),
    );
  };

  return {
    model_summary: markModelSummary,
    'step.started': handleStepStarted,
    'step.finished': handleStepResult,
    'step.result': handleStepResult,
    'check.started': handleCheckStarted,
    'check.finished': handleCheckFinished,
  };
}
