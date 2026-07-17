import {
  isFileTaskFailureStatus,
  isFileTaskWaitingStatus,
} from './file-task-status';

const USER_DETAIL_ROLE_PREFIXES = [
  'tool:',
  'file-change:',
  'code:',
  'read-files',
  'plan.checked',
  'plan.gated',
  'supervisor.intervention:',
  'supervisor.step_verified:',
  'step.result:',
  'check.finished',
  'image-insert-guard-recovery',
  'task-heartbeat',
  'stream-reconnect',
];

function normalizedStatus(payload: Record<string, any>): string {
  return String(
    payload.status
    || payload.terminal_status
    || payload.outcome
    || '',
  ).trim().toLowerCase();
}

function isAttentionPayload(payload: Record<string, any>): boolean {
  const status = normalizedStatus(payload);
  return payload.passed === false
    || payload.success === false
    || payload.blocked === true
    || payload.awaiting_confirmation === true
    || isFileTaskFailureStatus(status)
    || isFileTaskWaitingStatus(status)
    || status === 'replan';
}

export function shouldRenderTaskDetailEvent(
  eventType: string,
  payload: Record<string, any> = {},
): boolean {
  const type = String(eventType || '').trim().toLowerCase();
  if (!type) return false;
  if ([
    'tool.started',
    'tool.finished',
    'file.changed',
    'read.changed',
    'code_summary',
    'error',
    'supervisor.intervention',
  ].includes(type)) return true;
  if ([
    'plan.checked',
    'plan.gated',
    'supervisor.step_verified',
    'step.finished',
    'step.result',
    'check.finished',
  ].includes(type)) return isAttentionPayload(payload);
  return false;
}

export function taskDetailRoleIsUserVisible(role: string): boolean {
  const normalized = String(role || '').trim();
  return USER_DETAIL_ROLE_PREFIXES.some((prefix) => normalized.startsWith(prefix));
}

export function markTaskDetailRow(
  row: HTMLElement | null,
  role: string,
): HTMLElement | null {
  if (!row) return null;
  row.dataset.taskDetailVisibility = taskDetailRoleIsUserVisible(role)
    ? 'user'
    : 'internal';
  return row;
}
