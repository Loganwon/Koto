import { taskReportCompactText, taskReportStageTitle } from './task-report-layout';
import type { TaskStageProjection, TaskStageUiStatus } from './task-stage-state';

const JOURNAL_EVENT_TYPES = new Set([
  'run.started',
  'task.classified',
  'plan.checked',
  'plan.gated',
  'plan.created',
  'plan.proposed',
  'workflow.state',
  'supervisor.status',
  'supervisor.intervention',
  'decision.made',
  'plan.step_started',
  'plan.step_finished',
  'model.call.started',
  'model.call.finished',
  'step.started',
  'step.finished',
  'step.result',
  'tool.started',
  'tool.finished',
  'read.changed',
  'file.changed',
  'code_summary',
  'supervisor.step_verified',
  'check.started',
  'check.finished',
  'run.finished',
  'run.cancelled',
]);

const COMPLETION_EVENT_TYPES = new Set([
  'task.classified',
  'plan.checked',
  'plan.gated',
  'plan.created',
  'plan.proposed',
  'plan.step_finished',
  'model.call.finished',
  'step.finished',
  'step.result',
  'tool.finished',
  'read.changed',
  'file.changed',
  'code_summary',
  'supervisor.step_verified',
  'check.finished',
  'run.finished',
  'run.cancelled',
]);

const COALESCED_STATUS_EVENT_TYPES = new Set([
  'plan.checked',
  'plan.gated',
  'workflow.state',
  'supervisor.status',
  'decision.made',
  'model.call.started',
  'model.call.finished',
  'supervisor.step_verified',
  'check.started',
  'check.finished',
]);

const INTERNAL_SUCCESS_EVENT_TYPES = new Set([
  'workflow.state',
  'decision.made',
  'model.call.started',
  'check.started',
]);

const INTERNAL_SUCCESS_TOOLS = new Set([
  'list_workspace_files',
  'model_message',
  'provided_file_context',
  'selection_context',
  'verify_task_completion',
]);

const MAX_JOURNAL_ENTRIES = 60;
const TERMINAL_VISIBLE_ENTRIES = 3;
const PERSISTED_JOURNAL_ENTRIES = 30;
let journalListSequence = 0;

export type TaskProgressJournalStatus = 'running' | 'done' | 'warning' | 'failed' | 'waiting' | 'cancelled';

export interface TaskProgressJournalEntry {
  stage: string;
  title: string;
  status: TaskProgressJournalStatus;
}

function eventPayload(event: Record<string, any>): Record<string, any> {
  return event && event.payload && typeof event.payload === 'object'
    ? event.payload
    : {};
}

function journalStatus(
  type: string,
  status: TaskStageUiStatus,
): TaskProgressJournalStatus {
  if (status === 'failed') return 'failed';
  if (status === 'warning') return 'warning';
  if (status === 'waiting') return 'waiting';
  if (status === 'cancelled') return 'cancelled';
  if (status === 'succeeded' || COMPLETION_EVENT_TYPES.has(type)) return 'done';
  return 'running';
}

function journalKey(event: Record<string, any>, projection: TaskStageProjection): string {
  const type = String(event.type || '').trim().toLowerCase();
  const payload = eventPayload(event);
  const stepId = String(event.step_id || payload.step_id || payload.step || payload.step_index || '').trim();
  const toolId = String(
    payload.tool_use_id
    || payload.execution_id
    || payload.call_id
    || payload.tool_name
    || payload.tool
    || '',
  ).trim();
  const filePath = String(payload.path || payload.file_path || payload.file || '').trim();
  if (type === 'run.started' || type === 'run.finished' || type === 'run.cancelled') return 'run';
  if (type === 'task.classified') return 'route';
  if (type === 'plan.created' || type === 'plan.proposed') return 'plan';
  if (type === 'plan.checked' || type === 'plan.gated') return 'plan-check';
  if (type === 'workflow.state') return 'workflow-state';
  if (type === 'decision.made') return 'decision';
  if (type.startsWith('plan.step_')) return `plan-step:${stepId || projection.title}`;
  if (type.startsWith('model.call.')) return `model:${toolId || stepId || 'active'}`;
  if (type.startsWith('step.')) return `step:${stepId || projection.title}`;
  if (type.startsWith('tool.')) return `tool:${toolId || projection.title}`;
  if (type === 'read.changed') return `read:${filePath || projection.title}`;
  if (type === 'file.changed' || type === 'code_summary') return `file:${filePath || projection.title}`;
  if (type === 'check.started' || type === 'check.finished') return 'check';
  return `${type}:${stepId || toolId || projection.stageId}`;
}

function shouldRecord(
  event: Record<string, any>,
  projection: TaskStageProjection,
): boolean {
  const type = String(event && event.type || '').trim().toLowerCase();
  const payload = eventPayload(event);
  const status = projection.status;
  const exceptional = ['warning', 'failed', 'waiting', 'cancelled'].includes(status);
  const stepId = String(event.step_id || payload.step_id || '').trim().toLowerCase();
  if (INTERNAL_SUCCESS_EVENT_TYPES.has(type) && !exceptional) return false;
  if (type === 'model.call.finished' && !exceptional) return false;
  if (type === 'supervisor.step_verified' && !exceptional) return false;
  if (type === 'supervisor.status') {
    const stage = String(payload.stage || '').trim().toLowerCase();
    if (stage !== 'repairing' && !exceptional) return false;
  }
  if (type === 'tool.started' || type === 'tool.finished') {
    const toolName = String(payload.tool_name || payload.tool || '').trim().toLowerCase();
    if (INTERNAL_SUCCESS_TOOLS.has(toolName) && !exceptional) return false;
  }
  if (type.startsWith('step.') && ['execute', 'check'].includes(stepId) && !exceptional) return false;
  return JOURNAL_EVENT_TYPES.has(type)
    || type.startsWith('repair.')
    || type.startsWith('degradation.');
}

function isEmptyOptionalContextResult(event: Record<string, any>): boolean {
  const type = String(event && event.type || '').trim().toLowerCase();
  if (type !== 'step.finished' && type !== 'step.result') return false;
  const payload = eventPayload(event);
  const stepId = String(event.step_id || payload.step_id || '').trim().toLowerCase();
  if (stepId !== 'context' && stepId !== 'read_context') return false;
  const status = String(payload.status || '').trim().toLowerCase();
  const summary = String(payload.summary || payload.text || '').trim();
  return status === 'skipped' || summary.includes('没有显式文件或选区可读取');
}

function syncJournalCount(card: HTMLElement, list: HTMLOListElement): void {
  const nextCount = list.children.length;
  card.dataset.taskProgressJournalCount = String(nextCount);
  const count = card.querySelector('[data-role="stage-journal-count"]');
  if (count) count.textContent = `${nextCount} 条`;
  syncTerminalToggle(card, nextCount);
}

function syncTerminalToggle(card: HTMLElement, count: number): void {
  const journal = card.querySelector('[data-role="stage-journal"]') as HTMLElement | null;
  const toggle = card.querySelector('[data-task-progress-toggle]') as HTMLButtonElement | null;
  if (!journal || !toggle) return;
  const terminal = journal.dataset.terminal === 'true';
  const expanded = journal.dataset.expanded === 'true';
  toggle.hidden = !terminal || count <= TERMINAL_VISIBLE_ENTRIES;
  toggle.setAttribute('aria-expanded', expanded ? 'true' : 'false');
  toggle.textContent = expanded ? '收起进展' : `查看全部 ${count} 条`;
}

function markerText(status: TaskProgressJournalStatus): string {
  if (status === 'done') return '✓';
  if (status === 'failed') return '!';
  if (status === 'waiting') return '…';
  if (status === 'cancelled') return '×';
  if (status === 'warning') return '!';
  return '•';
}

export function taskProgressJournalMarkup(): string {
  journalListSequence += 1;
  const listId = `wa-task-progress-list-${journalListSequence}`;
  return '<div class="wa-task-progress-journal" data-role="stage-journal">'
    + '<div class="wa-task-progress-journal-head">'
      + '<span>实时进展</span>'
      + '<span class="wa-task-progress-journal-meta">'
        + '<span data-role="stage-journal-count">0 条</span>'
        + `<button type="button" data-task-progress-toggle hidden aria-expanded="false" aria-controls="${listId}">查看全部</button>`
      + '</span>'
    + '</div>'
    + `<ol id="${listId}" data-role="stage-journal-list" aria-label="任务实时进展"></ol>`
  + '</div>';
}

export function resetTaskProgressJournal(card: HTMLElement): void {
  const list = card.querySelector('[data-role="stage-journal-list"]');
  if (list) list.replaceChildren();
  const count = card.querySelector('[data-role="stage-journal-count"]');
  if (count) count.textContent = '0 条';
  const journal = card.querySelector('[data-role="stage-journal"]') as HTMLElement | null;
  if (journal) {
    delete journal.dataset.terminal;
    delete journal.dataset.expanded;
  }
  const toggle = card.querySelector('[data-task-progress-toggle]') as HTMLButtonElement | null;
  if (toggle) {
    toggle.hidden = true;
    toggle.setAttribute('aria-expanded', 'false');
    toggle.textContent = '查看全部';
  }
  delete card.dataset.taskProgressJournalCount;
}

export function setTaskProgressJournalTerminal(
  card: HTMLElement,
  terminal = true,
): void {
  const journal = card.querySelector('[data-role="stage-journal"]') as HTMLElement | null;
  const list = card.querySelector('[data-role="stage-journal-list"]') as HTMLOListElement | null;
  if (!journal || !list) return;
  if (terminal) {
    journal.dataset.terminal = 'true';
    journal.dataset.expanded = 'false';
  } else {
    delete journal.dataset.terminal;
    delete journal.dataset.expanded;
  }
  syncTerminalToggle(card, list.children.length);
}

export function toggleTaskProgressJournal(card: HTMLElement): void {
  const journal = card.querySelector('[data-role="stage-journal"]') as HTMLElement | null;
  const list = card.querySelector('[data-role="stage-journal-list"]') as HTMLOListElement | null;
  if (!journal || !list || journal.dataset.terminal !== 'true') return;
  journal.dataset.expanded = journal.dataset.expanded === 'true' ? 'false' : 'true';
  syncTerminalToggle(card, list.children.length);
}

export function taskProgressJournalEntries(
  card: HTMLElement,
  limit = PERSISTED_JOURNAL_ENTRIES,
): TaskProgressJournalEntry[] {
  const entries = Array.from(card.querySelectorAll('.wa-task-progress-entry'));
  const safeLimit = Math.max(1, Math.min(PERSISTED_JOURNAL_ENTRIES, Number(limit) || PERSISTED_JOURNAL_ENTRIES));
  return entries.slice(-safeLimit).map((node) => {
    const element = node as HTMLElement;
    const rawStatus = String(element.dataset.status || 'running').trim().toLowerCase();
    const status = ['done', 'warning', 'failed', 'waiting', 'cancelled'].includes(rawStatus)
      ? rawStatus as TaskProgressJournalStatus
      : 'running';
    return {
      stage: taskReportCompactText(
        element.querySelector('.wa-task-progress-stage')?.textContent || '任务',
        40,
      ),
      title: taskReportCompactText(
        element.querySelector('strong')?.textContent || '',
        120,
      ),
      status,
    };
  }).filter((entry) => entry.title);
}

export function recordTaskProgress(
  card: HTMLElement,
  event: Record<string, any>,
  projection: TaskStageProjection,
): void {
  const list = card.querySelector('[data-role="stage-journal-list"]') as HTMLOListElement | null;
  if (!list) return;
  const type = String(event.type || '').trim().toLowerCase();
  const key = journalKey(event, projection);
  if (isEmptyOptionalContextResult(event)) {
    Array.from(list.children).find(
      (node) => (node as HTMLElement).dataset.progressKey === key,
    )?.remove();
    syncJournalCount(card, list);
    return;
  }
  if (!shouldRecord(event, projection)) return;
  if (type === 'file.changed' || type === 'code_summary') {
    const completedTool = Array.from(list.children).reverse().find((node) => {
      const element = node as HTMLElement;
      return String(element.dataset.progressKey || '').startsWith('tool:')
        && element.dataset.status === 'done';
    });
    completedTool?.remove();
  }
  const signature = `${projection.stageId}:${taskReportCompactText(projection.title, 120)}`;
  const status = journalStatus(type, projection.status);
  let item = Array.from(list.children).find(
    (node) => (node as HTMLElement).dataset.progressKey === key,
  ) as HTMLLIElement | undefined;
  if (!item && COALESCED_STATUS_EVENT_TYPES.has(type)) {
    item = Array.from(list.children).find(
      (node) => (node as HTMLElement).dataset.progressSignature === signature,
    ) as HTMLLIElement | undefined;
  }
  const isNew = !item;
  if (!item) {
    item = document.createElement('li');
    item.dataset.progressKey = key;
    item.innerHTML = '<span class="wa-task-progress-marker" aria-hidden="true"></span>'
      + '<span class="wa-task-progress-copy">'
        + '<span class="wa-task-progress-stage"></span>'
        + '<strong></strong>'
      + '</span>';
    list.appendChild(item);
  }
  item.dataset.progressKey = key;
  item.dataset.progressSignature = signature;
  item.className = `wa-task-progress-entry ${status}`;
  item.dataset.status = status;
  const marker = item.querySelector('.wa-task-progress-marker');
  const stage = item.querySelector('.wa-task-progress-stage');
  const title = item.querySelector('strong');
  if (marker) marker.textContent = markerText(status);
  if (stage) stage.textContent = taskReportStageTitle(projection.stageId, '任务');
  if (title) title.textContent = taskReportCompactText(projection.title, 120);
  if (!isNew) list.appendChild(item);

  while (list.children.length > MAX_JOURNAL_ENTRIES) {
    list.firstElementChild?.remove();
  }
  syncJournalCount(card, list);
  list.scrollTop = list.scrollHeight;
}
