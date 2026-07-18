import { normalizedTaskLifecyclePayload } from './task-lifecycle-payload';
import { taskToolLabel } from './task-step-labels';
import {
  appendToolArtifacts,
  resultPreviewHtml,
  shouldSuppressToolFinished,
  shouldSuppressToolStart,
} from './task-tool-output';
import {
  recordTaskFileChange,
  recordTaskFileRefresh,
  taskFileChangeDescriptor,
  taskFileEventPath,
  TaskFileChangeStore,
} from './task-file-change-state';
import { escHtml as esc } from '../shared/sanitize';

export interface TaskExecutionEvidenceState extends TaskFileChangeStore {
  readKeys: Set<string>;
  codeSummaryRows: Map<string, HTMLElement>;
}

export interface TaskExecutionEvidenceCard extends HTMLElement {
  _fileRefreshHashes?: Map<string, string>;
}

export interface TaskExecutionEventRuntime<
  TCard extends TaskExecutionEvidenceCard,
  TState extends TaskExecutionEvidenceState,
> {
  getState: (_card: TCard) => TState;
  taskStageStep: (_card: TCard, _stepId: string) => HTMLElement;
  markStepRunning: (_step: HTMLElement) => void;
  upsertStepRow: (
    _step: HTMLElement,
    _role: string,
    _kind: string,
    _html: string,
  ) => HTMLElement | null;
  appendRow: (
    _step: HTMLElement,
    _kind: string,
    _html: string,
    _role?: string,
  ) => HTMLElement;
  setRunContext: (
    _card: TCard,
    _event: Record<string, any>,
    _payload: Record<string, any>,
  ) => void;
  normalizeWorkspacePath: (_path: string) => string;
  markExternalFileChange?: (_path: string) => void;
  requestFileBrowserRefresh?: () => void;
}

export type TaskExecutionEventHandler<TCard extends TaskExecutionEvidenceCard> = (
  _card: TCard,
  _event: Record<string, any>,
  _payload: Record<string, any>,
) => void;

export function createTaskExecutionEventHandlers<
  TCard extends TaskExecutionEvidenceCard,
  TState extends TaskExecutionEvidenceState,
>(runtime: TaskExecutionEventRuntime<TCard, TState>): Record<string, TaskExecutionEventHandler<TCard>> {
  const markExecuteRunning = (card: TCard): HTMLElement => {
    const step = runtime.taskStageStep(card, 'execute');
    runtime.markStepRunning(step);
    return step;
  };

  const refreshWorkspaceFile = (path: string): void => {
    if (runtime.markExternalFileChange) runtime.markExternalFileChange(path);
    if (runtime.requestFileBrowserRefresh) runtime.requestFileBrowserRefresh();
  };

  const handleModelCall = (card: TCard): void => {
    markExecuteRunning(card);
  };

  const handleToolStarted: TaskExecutionEventHandler<TCard> = (card, _evt, payload) => {
    const data = normalizedTaskLifecyclePayload(payload);
    if (shouldSuppressToolStart(data)) return;
    const step = markExecuteRunning(card);
    const toolName = String(data.tool_name || '');
    const toolTitle = data.tool_title || taskToolLabel(toolName);
    const content = '<span class="wa-task-chip">' + esc(toolTitle) + '</span>'
      + esc('准备执行');
    const tag = 'tool:' + toolName + ':'
      + String(data.tool_use_id || data.execution_id || '');
    runtime.upsertStepRow(step, tag, 'tool-start', content);
  };

  const handleToolFinished: TaskExecutionEventHandler<TCard> = (card, evt, payload) => {
    const data = normalizedTaskLifecyclePayload(payload);
    runtime.setRunContext(card, evt, payload);
    const toolName = String(data.tool_name || '');
    const finished = data.success !== false && !data.blocked && !data.skipped;
    if (toolName === 'image_insert_guard' && !finished) {
      const step = markExecuteRunning(card);
      card.dataset.taskImageInsertGuardPending = 'true';
      runtime.upsertStepRow(
        step,
        'image-insert-guard-recovery',
        'warn',
        '<span class="wa-task-chip warn">' + esc('补充图表') + '</span>'
          + esc('正在将已生成图表写入 Word'),
      );
      return;
    }
    if (shouldSuppressToolFinished(data)) return;
    const step = markExecuteRunning(card);
    const toolTitle = data.tool_title || taskToolLabel(toolName);
    const tag = 'tool:' + toolName + ':'
      + String(data.tool_use_id || data.execution_id || '');
    const kind = data.blocked || data.tool_name === 'ask_user'
      ? 'warn'
      : (finished ? 'tool-finished' : 'tool-error');
    const icon = data.skipped ? '跳过'
      : (data.blocked ? '阻断' : (finished ? '完成' : '失败'));
    const preview = resultPreviewHtml(data);
    const fallbackText = String(data.error || '').trim();
    const content = '<span class="wa-task-chip '
      + (data.blocked ? 'warn' : (finished ? 'success' : '')) + '">'
      + esc(icon) + ' ' + esc(toolTitle) + '</span>'
      + (preview || esc(fallbackText));
    runtime.upsertStepRow(step, tag, kind, content);
    appendToolArtifacts(step, data);
  };

  const handleFileChanged: TaskExecutionEventHandler<TCard> = (card, _evt, payload) => {
    const data = normalizedTaskLifecyclePayload(payload);
    const step = markExecuteRunning(card);
    const change = taskFileChangeDescriptor(data, runtime.normalizeWorkspacePath);
    if (!change) return;
    refreshWorkspaceFile(change.refreshPath || change.path);
    const state = runtime.getState(card);
    if (!recordTaskFileChange(state, change)) return;
    const label = change.changeType === 'created' ? '创建'
      : (change.changeType === 'deleted' ? '删除' : '修改');
    const content = '<span class="wa-task-chip success">' + esc(label) + '</span>'
      + '<a class="wa-task-file-link" href="javascript:void(0)" data-file-path="'
      + esc(change.path) + '">' + esc(change.shortPath) + '</a>';
    runtime.appendRow(step, 'tool-finished', content, `file-change:${change.key}`);
  };

  const handleReadChanged: TaskExecutionEventHandler<TCard> = (card, _evt, payload) => {
    const data = normalizedTaskLifecyclePayload(payload);
    const step = runtime.taskStageStep(card, 'context');
    runtime.markStepRunning(step);
    const path = String(data.path || data.file_path || data.entry || '').trim();
    if (!path) return;
    const state = runtime.getState(card);
    if (state.readKeys.has(path)) return;
    state.readKeys.add(path);
    const readPaths = Array.from(state.readKeys);
    const links = readPaths.slice(0, 3).map((item) => {
      const name = item.split('/').pop() || item;
      return '<a class="wa-task-file-link" href="javascript:void(0)" data-file-path="'
        + esc(item) + '">' + esc(name) + '</a>';
    }).join('、');
    const more = readPaths.length > 3 ? ` 等 ${readPaths.length} 个文件` : '';
    runtime.upsertStepRow(
      step,
      'read-files',
      'tool-start',
      '<span class="wa-task-chip">读取</span>已读取：' + links + esc(more),
    );
  };

  const handleCodeSummary: TaskExecutionEventHandler<TCard> = (card, _evt, payload) => {
    const data = normalizedTaskLifecyclePayload(payload);
    const step = markExecuteRunning(card);
    const state = runtime.getState(card);
    const file = String(data.file || data.path || '').trim();
    const action = String(data.action || data.change_type || 'write').trim();
    const summary = String(data.summary || data.text || '').trim();
    if (!file && !summary) return;
    const codeKey = 'code:' + (file || 'file:' + Date.now());
    if (!file || state.codeSummaryRows.has(codeKey)) return;
    const shortFile = file.split('/').pop() || file;
    const content = '<span class="wa-task-chip success">'
      + esc(action === 'delete' ? '删除' : '写入') + '</span>'
      + '<a class="wa-task-file-link" href="javascript:void(0)" data-file-path="'
      + esc(file) + '">' + esc(shortFile) + '</a>';
    const row = runtime.appendRow(step, 'tool-finished', content, codeKey);
    state.codeSummaryRows.set(codeKey, row);
    card.dataset.taskCompleted = 'true';
  };

  const handleFileRefresh: TaskExecutionEventHandler<TCard> = (card, _evt, payload) => {
    const data = normalizedTaskLifecyclePayload(payload);
    const eventPath = taskFileEventPath(
      data.path || data.file_path,
      '',
      runtime.normalizeWorkspacePath,
    );
    if (!eventPath) return;
    refreshWorkspaceFile(eventPath.refreshPath || eventPath.path);
    recordTaskFileRefresh(card, eventPath, data.file_refresh_hash);
  };

  return {
    'model.call.started': handleModelCall,
    'model.call.finished': handleModelCall,
    'tool.started': handleToolStarted,
    'tool.finished': handleToolFinished,
    'file.changed': handleFileChanged,
    'read.changed': handleReadChanged,
    code_summary: handleCodeSummary,
    file_refresh: handleFileRefresh,
  };
}
