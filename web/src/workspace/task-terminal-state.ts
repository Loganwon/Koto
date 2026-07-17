import {
  isFileTaskConfirmationStatus,
  normalizeFileTaskTerminalStatus,
} from './file-task-status';
import type { TaskRunRecoveryCard } from './task-run-recovery';

export type TaskTerminalStepState = 'done' | 'running' | 'failed';

export interface TaskTerminalStateResult {
  status: string;
  terminal_status: string;
  completed_task: boolean;
}

export interface TaskTerminalProjection {
  terminalStatus: string;
  statusText: string;
  title: string;
  cardClass: 'done' | 'failed' | 'cancelled';
  executeStepState: TaskTerminalStepState;
  runStepState: TaskTerminalStepState;
  checkStepState: TaskTerminalStepState;
  processStateText: string;
  collapseProcess: boolean;
}

export type TaskTerminalCard = TaskRunRecoveryCard;

export function taskTerminalProjection(
  result: TaskTerminalStateResult,
  semanticTitle = '',
): TaskTerminalProjection {
  const status = String(result && result.status || 'done').trim() || 'done';
  const terminalStatus = normalizeFileTaskTerminalStatus(
    result && result.terminal_status || '',
  ) || (status === 'error' ? 'failed'
    : (status === 'cancelled' ? 'cancelled'
      : (status === 'pending' ? 'waiting' : 'completed')));
  const confirmation = isFileTaskConfirmationStatus(terminalStatus);
  const title = String(semanticTitle || '').trim() || (
    status === 'pending' ? (confirmation ? '等待确认' : '任务进行中')
      : (status === 'error' ? '任务未完成'
        : (status === 'cancelled' ? '任务已取消' : '任务完成'))
  );

  return {
    terminalStatus,
    statusText: status === 'cancelled' ? '已取消'
      : (status === 'error' ? '执行失败'
        : (status === 'pending' ? (confirmation ? '待确认' : '处理中') : '已完成')),
    title,
    cardClass: status === 'error' ? 'failed'
      : (status === 'cancelled' ? 'cancelled' : 'done'),
    executeStepState: status === 'error' ? 'failed'
      : (status === 'pending' ? 'running' : 'done'),
    runStepState: status === 'error' ? 'failed' : 'done',
    checkStepState: status === 'error' ? 'failed'
      : (status === 'pending' ? 'running' : 'done'),
    processStateText: status === 'error' ? '未完成'
      : (status === 'pending' ? (confirmation ? '待确认' : '进行中') : '已完成'),
    collapseProcess: status !== 'error' && status !== 'pending',
  };
}

export function prepareTaskCardForActiveRun(card: HTMLElement): void {
  if (!card) return;
  card.classList.remove('pending', 'done', 'failed', 'cancelled');
  card.classList.add('streaming');
}

export function applyTaskTerminalCardPresentation(
  card: HTMLElement,
  projection: TaskTerminalProjection,
): void {
  if (!card) return;
  card.dataset.taskTerminalStatus = projection.terminalStatus;
  const title = card.querySelector('.wa-task-title');
  if (title) title.textContent = projection.title;

  card.classList.remove('streaming', 'pending', 'done', 'failed', 'cancelled');
  card.classList.add(projection.cardClass);

  const process = card.querySelector('[data-role="process"]') as HTMLDetailsElement | null;
  if (process) {
    process.open = !projection.collapseProcess;
    const titleEl = process.querySelector('[data-role="process-title"]');
    if (titleEl) {
      const artifactCount = card.querySelectorAll(
        '[data-role="process"] .wa-task-artifact-row',
      ).length;
      const suffix = projection.collapseProcess && artifactCount > 0
        ? ` · ${artifactCount}个产出`
        : '';
      titleEl.textContent = '查看执行详情' + suffix;
    }
    const state = process.querySelector('[data-role="process-state"]');
    if (state) state.textContent = projection.processStateText;
  }

  const cancelButton = card.querySelector('[data-role="cancel"]') as HTMLElement | null;
  if (cancelButton) {
    cancelButton.textContent = '关闭';
    cancelButton.dataset.action = 'close';
  }
}

export function compactTerminalProcess(
  card: HTMLElement,
  result: TaskTerminalStateResult,
): void {
  if (!card) return;
  const plan = card.querySelector('[data-role="plan"]') as HTMLElement | null;
  if (plan && result.status === 'done') {
    plan.querySelectorAll('.wa-task-plan-steps > li').forEach((node) => {
      node.classList.remove('wa-task-plan-step-active');
      node.classList.add('wa-task-plan-step-done');
    });
  }
  card.querySelectorAll(
    '[data-role="steps"] .wa-task-step[data-step-id="run"]',
  ).forEach((node) => node.remove());
  card.querySelectorAll('[data-role="steps"] .wa-task-step').forEach((node) => {
    const step = node as HTMLElement;
    const body = step.querySelector('.wa-task-step-body') as HTMLElement | null;
    if (!body) return;
    body.querySelectorAll<HTMLElement>('.wa-task-row').forEach((row) => {
      if (row.dataset.taskDetailVisibility !== 'user') row.remove();
    });
    const hasRows = !!body.querySelector('.wa-task-row');
    const hasArtifacts = !!step.querySelector(
      '.wa-task-artifacts .wa-task-artifact',
    );
    if (!hasRows && !hasArtifacts) step.remove();
  });
}

export function scheduleTaskLiveProgressCollapse(card: HTMLElement): void {
  const host = document.getElementById('wa-task-live-progress');
  if (!host) return;
  const terminalStatus = normalizeFileTaskTerminalStatus(
    card && card.dataset && card.dataset.taskTerminalStatus || '',
  );
  if (isFileTaskConfirmationStatus(terminalStatus)) return;
  const currentTimer = (host as any)._waCollapseTimer;
  if (currentTimer) window.clearTimeout(currentTimer);
  (host as any)._waCollapseTimer = window.setTimeout(() => {
    const activeRun = document.querySelector(
      '.wa-task-run.streaming:not([data-history-snapshot="true"])',
    );
    if (!activeRun) host.hidden = true;
  }, 1600);
}

export function persistTerminalTaskCard(
  card: TaskTerminalCard,
  persist: ((_card: TaskTerminalCard) => unknown) | null,
): void {
  const persistNow = (): void => {
    if (
      !persist
      || !card
      || card.dataset.taskTerminalPersisted === 'true'
      || card.dataset.historySnapshot === 'true'
    ) return;
    Promise.resolve(persist(card)).catch(() => { /* best effort */ });
  };

  if (typeof card._terminalSnapshotHandler === 'function') {
    try { card._terminalSnapshotHandler(card); } catch { /* best effort */ }
    window.setTimeout(persistNow, 1000);
    return;
  }
  persistNow();
}
