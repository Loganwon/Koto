import {
  fileTaskOutcomeCopy,
  fileTaskTerminalUiStatus,
  isFileTaskConfirmationStatus,
  isFileTaskIncompleteBlockedStatus,
  normalizeFileTaskTerminalStatus,
} from './file-task-status';
import { renderTaskFinalReport } from './task-final-report';
import { escHtml as esc } from '../shared/sanitize';

export interface TaskResultPresentationState {
  status: string;
  terminal_status: string;
  completed_task: boolean;
}

export interface TaskResultActionState {
  terminalStatus: string;
  completedTask: boolean;
  pendingResumePayload: string;
  taskRequest: string;
  pendingLabel: string;
  quickActionMode: string;
  canApply: boolean;
  requiresConfirmation: boolean;
  outputMode: string;
}

export interface TaskPrimaryActionState {
  historySnapshot: boolean;
  streamConnectionState: string;
  taskId: string;
  terminalStatus: string;
  pendingResumePayload: string;
  pendingResumeLabel: string;
  streaming: boolean;
}

export interface TaskPrimaryActionCard extends HTMLElement {}

export interface TaskPrimaryActionRuntimeState {
  streamConnectionState: string;
}

export interface TaskTerminalSummaryState {
  result: TaskResultPresentationState;
  visibleSummary: string;
  artifactsHtml?: string;
  auditHtml?: string;
  contextHtml?: string;
  actionsHtml?: string;
}

export function normalizeQuickActionMode(value: string): string {
  const normalized = String(value || '').trim().toLowerCase();
  if (normalized === 'simple') return 'answer';
  if (normalized === 'proposal') return 'hybrid';
  return normalized;
}

export function taskArtifactItems(
  artifactResult: Record<string, any> | null,
  fileChanges: any[],
): any[] {
  const artifacts = artifactResult && Array.isArray(artifactResult.artifacts)
    ? artifactResult.artifacts
    : [];
  const changes = Array.isArray(fileChanges) ? fileChanges : [];
  const unique = new Map<string, any>();
  [...artifacts, ...changes.map((change: any) => ({
    path: change && (change.path || change.file_path),
    type: change && (change.type || change.file_type),
    title: change && (change.title || change.name),
  }))].forEach((item: any) => {
    if (!item || typeof item !== 'object') return;
    const path = String(item.path || '').replace(/\\/g, '/').replace(/^\.\//, '').trim();
    const canonical = path.replace(/^workspace\//i, '').toLowerCase();
    const key = canonical || ('title:' + String(item.title || '').trim().toLowerCase());
    if (!key) return;
    const existing = unique.get(key);
    const prefersWorkspacePath = /^workspace\//i.test(path);
    const existingPath = String(existing && existing.path || '').replace(/\\/g, '/');
    if (!existing || (prefersWorkspacePath && !/^workspace\//i.test(existingPath))) {
      unique.set(key, item);
    }
  });
  return Array.from(unique.values());
}

function artifactDisplayName(item: any): string {
  const title = String(item && item.title || '').trim();
  if (title) return title;
  const path = String(item && item.path || '').replace(/\\/g, '/');
  return path.split('/').pop() || path || '任务产物';
}

export function taskArtifactsSummaryHtml(
  artifactResult: Record<string, any> | null,
  fileChanges: any[],
): string {
  const artifacts = taskArtifactItems(artifactResult, fileChanges);
  if (!artifacts.length) return '';
  const visibleLimit = 3;
  const rows = artifacts.slice(0, visibleLimit).map((item: any) => {
    const name = artifactDisplayName(item);
    const path = String(item.path || '').replace(/\\/g, '/').trim();
    const type = String(item.type || '').trim();
    const isTemporary = /(^|\/)(tmp|temp)(\/|$)/i.test(path.replace(/^workspace\//i, ''));
    const meta = [type, isTemporary ? '临时产物' : '工作区文件'].filter(Boolean).join(' · ');
    return '<li title="' + esc(path) + '"><span class="wa-task-artifact-name">' + esc(name) + '</span>'
      + (meta ? '<span class="wa-task-artifact-meta">' + esc(meta) + '</span>' : '')
      + '</li>';
  }).join('');
  const overflow = artifacts.length > visibleLimit
    ? '<div class="wa-task-artifact-overflow">另有 ' + esc(String(artifacts.length - visibleLimit)) + ' 个产物</div>'
    : '';
  return [
    '<div class="wa-task-artifact-summary-card" data-role="artifact-summary">',
    '  <div class="wa-task-artifact-summary-head">',
    '    <strong>任务产物</strong>',
    '    <button type="button" class="wa-task-artifact-open-panel" data-task-artifacts-open="1">查看产物</button>',
    '  </div>',
    '  <ul>',
    rows,
    '  </ul>',
    overflow,
    '</div>',
  ].join('');
}

export function taskResultRequiresUserConfirmation(
  result: TaskResultPresentationState,
): boolean {
  return !!result && isFileTaskConfirmationStatus(result.terminal_status);
}

export function taskResultOutcomeCopy(result: TaskResultPresentationState) {
  return fileTaskOutcomeCopy(
    result && (result.terminal_status || result.status) || 'done',
    taskResultRequiresUserConfirmation(result),
  );
}

export function terminalStepSummary(result: TaskResultPresentationState): string {
  return taskResultOutcomeCopy(result).stepSummary;
}

export function taskCompletionBannerHtml(result: TaskResultPresentationState): string {
  const status = result && result.status ? result.status : 'done';
  if (status === 'done') return '';
  const label = taskResultOutcomeCopy(result);
  return '<div class="wa-task-completion-banner" data-status="' + esc(status) + '" role="status" aria-live="polite">'
    + '<span class="wa-task-completion-icon" aria-hidden="true"></span>'
    + '<span class="wa-task-completion-copy"><strong>' + esc(label.title) + '</strong><span>' + esc(label.detail) + '</span></span>'
    + '</div>';
}

export function taskResultActionsHtml(state: TaskResultActionState): string {
  const terminal = normalizeFileTaskTerminalStatus(state.terminalStatus || '');
  const uiStatus = fileTaskTerminalUiStatus(terminal, state.completedTask);
  const completed = uiStatus === 'done';
  const incompleteBlocked = isFileTaskIncompleteBlockedStatus(terminal, state.completedTask);
  if (state.pendingResumePayload && isFileTaskConfirmationStatus(terminal)) return '';

  const questionText = completed ? '询问结果' : '追问原因';
  let improveText = completed ? '继续处理' : '继续修复';
  const actionHint = completed ? '任务已完成，后续操作会作为新请求发送。' : '可继续补充要求或重新处理。';
  let applyActionHtml = '';
  if (incompleteBlocked) improveText = '重新发起';
  const quickActionMode = normalizeQuickActionMode(state.quickActionMode);
  if (quickActionMode === 'answer') {
    if (!incompleteBlocked) improveText = '继续分析';
  } else if (quickActionMode === 'hybrid') {
    if (!incompleteBlocked) {
      if (state.canApply) {
        improveText = '继续细化方案';
        applyActionHtml = `    <button type="button" class="wa-task-followup-action primary" data-task-followup-action="apply">${esc(state.requiresConfirmation ? '应用建议' : '应用到文件')}</button>`;
      } else if (state.outputMode && state.outputMode !== 'write') {
        improveText = '继续细化';
      }
    }
  } else if (state.pendingLabel && !incompleteBlocked) {
    improveText = state.pendingLabel;
  }

  return [
    '<div class="wa-task-actions">',
    `  <span class="wa-task-action-hint">${esc(actionHint)}</span>`,
    '  <div class="wa-task-action-buttons">',
    applyActionHtml,
    `    <button type="button" class="wa-task-followup-action" data-task-followup-action="question">${esc(questionText)}</button>`,
    `    <button type="button" class="wa-task-followup-action" data-task-followup-action="improve" data-task-followup-request="${esc(state.taskRequest || '')}">${esc(improveText)}</button>`,
    '  </div>',
    '</div>',
  ].join('');
}

export function taskPrimaryActionHtml(state: TaskPrimaryActionState): string {
  if (state.historySnapshot) return '';
  if (state.streamConnectionState === 'recovering') {
    return '<span>正在恢复任务进度</span>'
      + '<button type="button" class="wa-task-primary-button" disabled>正在连接…</button>';
  }
  if (state.streamConnectionState === 'failed' && state.taskId) {
    return '<span>进度同步已中断</span>'
      + '<button type="button" class="wa-task-primary-button" data-task-stream-retry="1">重新连接</button>';
  }
  const terminal = normalizeFileTaskTerminalStatus(state.terminalStatus || '');
  if (isFileTaskConfirmationStatus(terminal) && state.pendingResumePayload) {
    const label = String(state.pendingResumeLabel || '确认并继续').trim() || '确认并继续';
    return '<span>当前步骤已暂停，确认后继续</span>'
      + '<button type="button" class="wa-task-primary-button"'
      + ` data-task-artifact-resume="${esc(state.pendingResumePayload)}"`
      + ` data-task-artifact-label="${esc(label)}">${esc(label)}</button>`;
  }
  if (state.streaming && !terminal) {
    return '<span>任务正在后台执行</span>'
      + '<button type="button" class="wa-task-secondary-button" data-role="cancel" title="取消任务">取消任务</button>';
  }
  return '';
}

export function syncTaskPrimaryAction(
  card: TaskPrimaryActionCard,
  state: TaskPrimaryActionRuntimeState,
): void {
  if (!card) return;
  const host = card.querySelector(
    '[data-role="task-primary-action"]',
  ) as HTMLElement | null;
  if (!host) return;
  const html = taskPrimaryActionHtml({
    historySnapshot: card.dataset.historySnapshot === 'true',
    streamConnectionState: state.streamConnectionState,
    taskId: String(card.dataset.taskId || '').trim(),
    terminalStatus: String(card.dataset.taskTerminalStatus || ''),
    pendingResumePayload: String(
      card.dataset.taskPendingResumePayload || '',
    ).trim(),
    pendingResumeLabel: String(card.dataset.taskPendingResumeLabel || ''),
    streaming: card.classList.contains('streaming'),
  });
  host.innerHTML = html;
  host.hidden = !html;
}

export function taskTerminalSummaryHtml(state: TaskTerminalSummaryState): string {
  return taskCompletionBannerHtml(state.result)
    + '<div class="wa-task-final-report" data-role="final-report" tabindex="-1">'
    + '<div class="wa-task-final-report-title">任务结果</div>'
    + '<div class="wa-task-final-report-content">'
    + renderTaskFinalReport(state.visibleSummary)
    + '</div></div>'
    + String(state.artifactsHtml || '')
    + String(state.auditHtml || '')
    + String(state.contextHtml || '')
    + String(state.actionsHtml || '');
}
