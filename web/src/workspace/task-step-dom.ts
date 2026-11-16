import { escHtml as esc } from '../shared/sanitize';
import { markTaskDetailRow } from './task-detail-policy';
import { taskStepTitle } from './task-step-labels';

export interface TaskStepCard extends HTMLElement {}

export function setTaskStatus(card: TaskStepCard, text: string): void {
  const status = card.querySelector('[data-role="status"]');
  if (status) status.textContent = text || '';
}

export function setTaskStepTitle(step: HTMLElement, title: string): void {
  if (!step || !title) return;
  const titleEl = step.querySelector('.wa-task-step-title');
  if (titleEl) titleEl.textContent = title;
}

export function ensureTaskStep(
  card: TaskStepCard,
  stepId: string,
  title: string,
): HTMLElement {
  const steps = card.querySelector('[data-role="steps"]') as HTMLElement;
  const safeId = String(stepId || 'run');
  let step = Array.from(steps.children).find(
    (node) => (node as HTMLElement).dataset.stepId === safeId,
  ) as HTMLElement | undefined;
  if (step) {
    setTaskStepTitle(step, title || taskStepTitle(safeId));
    return step;
  }
  step = document.createElement('div');
  step.className = 'wa-task-step pending';
  step.dataset.stepId = safeId;
  step.innerHTML = '<details class="wa-task-step-detail" open>'
    + '<summary class="wa-task-step-head">'
    + '<span class="wa-task-step-dot"></span>'
    + '<span class="wa-task-step-title">'
    + esc(title || safeId)
    + '</span></summary><div class="wa-task-step-body"></div></details>';
  steps.appendChild(step);
  return step;
}

export function markTaskStepRunning(step: HTMLElement): void {
  if (!step) return;
  step.classList.remove('pending', 'done', 'failed');
  step.classList.add('running');
}

export function markTaskStepDone(step: HTMLElement): void {
  if (!step) return;
  step.classList.remove('pending', 'running', 'failed');
  step.classList.add('done');
}

export function markTaskStepFailed(step: HTMLElement): void {
  if (!step) return;
  step.classList.remove('pending', 'running', 'done');
  step.classList.add('failed');
}

export function taskStageStep(
  card: TaskStepCard,
  stepId: string,
): HTMLElement {
  return ensureTaskStep(card, stepId, taskStepTitle(stepId));
}

export function appendTaskStepRow(
  step: HTMLElement,
  kind: string,
  html: string,
  role = '',
): HTMLElement {
  const body = step.querySelector('.wa-task-step-body') as HTMLElement;
  const row = document.createElement('div');
  row.className = (`wa-task-row ${kind || ''}`).trim();
  row.innerHTML = html;
  if (role) {
    row.dataset.role = role;
    markTaskDetailRow(row, role);
  } else {
    row.dataset.taskDetailVisibility = 'internal';
  }
  body.appendChild(row);
  return row;
}

export function upsertTaskStepSingletonRow(
  step: HTMLElement,
  role: string,
  kind: string,
  html: string,
): HTMLElement | null {
  if (!step) return null;
  const key = String(role || 'default').trim() || 'default';
  if (!(step as any)._singletonRows) (step as any)._singletonRows = new Map();
  let row = (step as any)._singletonRows.get(key) as HTMLElement | undefined;
  if (!row) {
    row = appendTaskStepRow(step, kind, '', key);
    (step as any)._singletonRows.set(key, row);
  }
  markTaskDetailRow(row, key);
  row.className = (`wa-task-row ${kind || ''}`).trim();
  row.innerHTML = html;
  return row;
}

export function removeTaskStepRow(
  card: TaskStepCard,
  stepId: string,
  role: string,
): void {
  if (!card) return;
  const step = Array.from(card.querySelectorAll<HTMLElement>(
    '[data-role="steps"] .wa-task-step[data-step-id]',
  )).find((node) => node.dataset.stepId === stepId) || null;
  if (!step) return;
  step.querySelectorAll<HTMLElement>('.wa-task-row[data-role]').forEach((row) => {
    if (row.dataset.role === role) row.remove();
  });
  const singletonRows = (step as any)._singletonRows;
  if (singletonRows && typeof singletonRows.delete === 'function') {
    singletonRows.delete(role);
  }
  if (!step.querySelector('.wa-task-row')) step.remove();
}
