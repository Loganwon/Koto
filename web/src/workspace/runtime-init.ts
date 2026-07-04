/**
 * AI Runtime Init & Registration — lazy initialization of AI runtimes,
 * conversation hydration, task registration.
 * Workspace AI runtime initialization.
 */

import { $, _LIGHTBULB_SVG, _PENCIL_SVG, _SLIDES_SVG, showToast, _csrfFetch } from './infrastructure';
import { state, _WA_RUNTIME_SESSION_ID } from './state';
import {
  _computeInlineDiff,
  _createPinnedSelectionContext,
  _getProposalRationaleText,
  _hideWelcome,
  _makeAIActionBar,
  _proposalCanApply,
  _selectionContextText,
  _setStreamBtn,
} from './ai-review';
import { _applyRouteEvent, _selectedCloudModelId } from './model-settings';
import { fileTaskTerminalUiStatus, normalizeFileTaskTerminalStatus } from './file-task-status';

let _waAiResultsRuntime: any = (window as any)._waAiResultsRuntime || null;
let _waQuickActionRuntime: any = (window as any)._waQuickActionRuntime || null;
let _waConversationRuntime: any = (window as any)._waConversationRuntime || null;
let _waTaskDispatcher: any = (window as any)._waTaskDispatcher || null;
let _waQuickActionDispatcherAttached: boolean = Boolean((window as any)._waQuickActionDispatcherAttached);
let _hostSessionId: string = String((window as any)._hostSessionId || '').trim();
let _workspaceTurnPersistQueue: Promise<any> = Promise.resolve();
let _workspaceTurnRetryTimer: number | null = null;
let _workspaceTurnRetrying = false;

const WORKSPACE_TURN_RETRY_KEY = 'wa_workspace_turn_retry_queue_v1';
const WORKSPACE_TURN_RETRY_LIMIT = 20;
const WORKSPACE_TURN_RETRY_SNAPSHOT_LIMIT = 120000;

function _syncRuntimeGlobals(): void {
  (window as any)._waAiResultsRuntime = _waAiResultsRuntime;
  (window as any)._waQuickActionRuntime = _waQuickActionRuntime;
  (window as any)._waConversationRuntime = _waConversationRuntime;
  (window as any)._waTaskDispatcher = _waTaskDispatcher;
  (window as any)._waQuickActionDispatcherAttached = _waQuickActionDispatcherAttached;
  (window as any)._hostSessionId = _hostSessionId;
  (window as any)._WA_RUNTIME_SESSION_ID = _WA_RUNTIME_SESSION_ID;
}

function _sanitizeRenderedHtml(html: string): string {
  const sanitizer = (window as any)._sanitizeRenderedHtml;
  if (typeof sanitizer === 'function') return sanitizer(html);
  return String(html || '')
    .replace(/<script[\s\S]*?>[\s\S]*?<\/script>/gi, '')
    .replace(/\son[a-z]+\s*=\s*(['"]).*?\1/gi, '');
}

export function _waRenderMarkdown(text: string): string {
  if ((window as any).marked) {
    try { return _sanitizeRenderedHtml((window as any).marked.parse(text || '')); } catch (_) { /* noop */ }
  }
  const source = String(text || '').trim().replace(/^(?:---|\*\*\*)\s*\n+(?=#{1,6}\s+)/, '').trim();
  return source
    .split(/\r?\n/)
    .map((line) => {
      const trimmed = line.trim();
      const heading = /^(#{1,4})\s+(.+)$/.exec(trimmed);
      const escaped = trimmed
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/`([^`]+)`/g, '<code>$1</code>')
        .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
      if (heading) {
        const level = Math.min(4, heading[1].length + 1);
        const body = heading[2]
          .replace(/&/g, '&amp;')
          .replace(/</g, '&lt;')
          .replace(/>/g, '&gt;')
          .replace(/`([^`]+)`/g, '<code>$1</code>')
          .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
        return '<h' + level + '>' + body + '</h' + level + '>';
      }
      return escaped;
    })
    .filter(Boolean)
    .join('<br>');
}

function _hostChatSession(): string {
  const bridge = (window as any).KotoSessionBridge;
  if (bridge && typeof bridge.getSession === 'function') {
    const bridged = String(bridge.getSession() || '').trim();
    if (bridged) {
      _hostSessionId = bridged;
      _syncRuntimeGlobals();
      return bridged;
    }
  }
  return String(_hostSessionId || '').trim();
}

export function _waSession(): string {
  return _hostChatSession() || _WA_RUNTIME_SESSION_ID;
}

function _safeJsonClone(value: any): any {
  try { return JSON.parse(JSON.stringify(value || null)); } catch (_) { return null; }
}

function _workspaceTurnPersistKey(payload: Record<string, any>): string {
  const metadata = payload && typeof payload.metadata === 'object' ? payload.metadata : {};
  const explicit = String(metadata.turn_id || metadata.run_id || metadata.task_id || '').trim();
  if (explicit) return explicit;
  return [
    String(payload.user || '').slice(0, 120),
    String(payload.assistant || '').slice(0, 120),
  ].join('|');
}

function _compactRetryPayload(payload: Record<string, any>): Record<string, any> | null {
  const cloned = _safeJsonClone(payload);
  if (!cloned || typeof cloned !== 'object') return null;
  const snapshot = cloned.task_card_snapshot;
  if (snapshot && typeof snapshot === 'object' && typeof snapshot.html === 'string') {
    snapshot.html = snapshot.html.slice(0, WORKSPACE_TURN_RETRY_SNAPSHOT_LIMIT);
  }
  return cloned;
}

function _loadWorkspaceTurnRetryQueue(): Array<Record<string, any>> {
  try {
    const raw = window.localStorage.getItem(WORKSPACE_TURN_RETRY_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed.filter((item) => item && typeof item === 'object') : [];
  } catch (_) {
    return [];
  }
}

function _saveWorkspaceTurnRetryQueue(queue: Array<Record<string, any>>): boolean {
  try {
    window.localStorage.setItem(WORKSPACE_TURN_RETRY_KEY, JSON.stringify(queue.slice(-WORKSPACE_TURN_RETRY_LIMIT)));
    return true;
  } catch (_) {
    return false;
  }
}

function _removeWorkspaceTurnRetry(payload: Record<string, any>): void {
  const key = _workspaceTurnPersistKey(payload);
  if (!key) return;
  const queue = _loadWorkspaceTurnRetryQueue().filter((item) => String(item.key || '') !== key);
  _saveWorkspaceTurnRetryQueue(queue);
}

function _scheduleWorkspaceTurnRetry(delay = 5000): void {
  if (_workspaceTurnRetryTimer !== null) return;
  _workspaceTurnRetryTimer = window.setTimeout(() => {
    _workspaceTurnRetryTimer = null;
    retryWorkspaceConversationPersistence(false).catch((error) => {
      console.warn('[WA] workspace turn retry failed:', error);
    });
  }, Math.max(0, delay));
}

function _queueWorkspaceTurnRetry(payload: Record<string, any>, error?: any): void {
  const retryPayload = _compactRetryPayload(payload);
  if (!retryPayload) return;
  const key = _workspaceTurnPersistKey(retryPayload);
  const queue = _loadWorkspaceTurnRetryQueue().filter((item) => String(item.key || '') !== key);
  queue.push({
    key,
    payload: retryPayload,
    attempts: 0,
    queued_at: new Date().toISOString(),
    last_error: String(error && error.message ? error.message : error || '').slice(0, 240),
  });
  if (!_saveWorkspaceTurnRetryQueue(queue)) {
    console.warn('[WA] workspace turn retry queue storage failed');
    showToast('对话保存失败，本地重试队列空间不足', 'error', 4200);
    return;
  }
  showToast('对话保存失败，已暂存并自动重试', 'warning', 4200);
  _scheduleWorkspaceTurnRetry(2500);
}

export function _waQuickActionModelMode(): string {
  const value = String(state.lockedModel || '').trim().toLowerCase();
  return ['cloud', 'deepseek', 'local'].includes(value) ? value : 'cloud';
}

export function _waSampleTaskContext(text: string, limit: number = 12000): string {
  const content = String(text || '');
  if (content.length <= limit) return content;
  const head = Math.max(Math.floor(limit * 0.7), 1);
  const tail = Math.max(limit - head - 48, 0);
  const marker = '\n\n...[中间内容已省略]...\n\n';
  if (tail <= 0) return content.slice(0, limit);
  return content.slice(0, head) + marker + content.slice(-tail);
}

function _handleProposals(data: any): void {
  const runtime = (window as any)._waAiResultsRuntime;
  if (runtime && typeof runtime.handleProposals === 'function') {
    runtime.handleProposals(data);
  }
}

export function _hydrateAiConversation(force: boolean = false): Promise<any[]> {
  if (!_waConversationRuntime || typeof _waConversationRuntime.hydrate !== 'function') return Promise.resolve([]);
  return _waConversationRuntime.hydrate({
    force,
    sessionId: _waSession(),
  }).then((turns: any[]) => {
    if (!force || state.isLoading) return turns;
    const restore = (window as any).WA && (window as any).WA._restoreActiveFileTasks;
    if (typeof restore !== 'function') return turns;
    return Promise.resolve(restore(force)).then(() => turns);
  });
}

async function _sendWorkspaceConversationTurn(sessionId: string, payload: Record<string, any>): Promise<any> {
  const response = await _csrfFetch(`/api/sessions/${encodeURIComponent(sessionId)}/workspace-turn`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!response.ok) return null;
  const data = await response.json().catch(() => null);
  _applyPersistedTaskMetadata(data, payload);
  const bridge = (window as any).KotoSessionBridge;
  if (bridge && typeof bridge.refreshSessions === 'function') {
    Promise.resolve(bridge.refreshSessions()).catch(() => {});
  }
  const refreshAiSessions = (window as any).WA && (window as any).WA.refreshAiSessions;
  if (typeof refreshAiSessions === 'function') {
    Promise.resolve(refreshAiSessions({ silent: true })).catch(() => {});
  }
  return data;
}

function _sendWorkspaceConversationTurnBeacon(sessionId: string, payload: Record<string, any>): boolean {
  const beacon = typeof navigator !== 'undefined' ? navigator.sendBeacon : null;
  if (typeof beacon !== 'function') return false;
  try {
    const blob = new Blob([JSON.stringify(payload)], { type: 'application/json' });
    return beacon.call(navigator, `/api/sessions/${encodeURIComponent(sessionId)}/workspace-turn`, blob);
  } catch (_) {
    return false;
  }
}

function _isStructuredTerminalWorkspaceTurn(payload: Record<string, any>): boolean {
  const metadata = payload && typeof payload.metadata === 'object' ? payload.metadata : {};
  const partial = String(metadata.partial || '').trim().toLowerCase();
  return !!metadata.test_structure && partial !== 'true' && partial !== '1' && partial !== 'yes';
}

function _cssEscape(value: string): string {
  const css = (window as any).CSS;
  if (css && typeof css.escape === 'function') return css.escape(value);
  return String(value || '').replace(/["\\]/g, '\\$&');
}

function _applyPersistedTaskMetadata(data: any, payload: Record<string, any>): void {
  const taskTitle = String(data && data.task_title || '').trim();
  const memorySummary = String(data && (data.memory_summary || data.model_context_text) || '').trim();
  if (!taskTitle && !memorySummary) return;
  const metadata = payload && payload.metadata && typeof payload.metadata === 'object' ? payload.metadata : {};
  const turnId = String(metadata.turn_id || payload.turn_id || '').trim();
  const runId = String(metadata.run_id || '').trim();
  const selectors = [
    turnId ? `[data-turn-id="${_cssEscape(turnId)}"]` : '',
    runId ? `.wa-task-run[data-task-run-id="${_cssEscape(runId)}"]` : '',
  ].filter(Boolean);
  const card = selectors.length ? document.querySelector(selectors.join(',')) as HTMLElement | null : null;
  if (!card) return;
  if (taskTitle) {
    card.dataset.taskTitle = taskTitle;
    const titleEl = card.querySelector('.wa-task-title');
    if (titleEl) titleEl.textContent = taskTitle;
  }
  if (memorySummary) card.dataset.taskMemorySummary = memorySummary;
  const WA = (window as any).WA;
  if (WA && typeof WA.syncTaskInteractionSummary === 'function') {
    try { WA.syncTaskInteractionSummary(card); } catch (_) { /* noop */ }
  }
}

async function _ensureWorkspacePersistenceSession(): Promise<string> {
  const existing = _hostChatSession();
  if (existing && !/^workspace_runtime_/i.test(existing)) return existing;
  const stamp = new Date().toISOString().replace(/[-:T]/g, '').slice(0, 12);
  const response = await _csrfFetch('/api/sessions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: `对话_${stamp}` }),
  });
  if (!response.ok) return '';
  const data = await response.json().catch(() => null);
  const sessionId = String(data && data.session || '').trim();
  if (!sessionId) return '';
  _hostSessionId = sessionId;
  _syncRuntimeGlobals();
  return sessionId;
}

export async function _persistWorkspaceConversationTurn(record: any): Promise<any> {
  const payload = record && typeof record === 'object' ? record : {};
  const userText = String(payload.user || payload.user_text || '').trim();
  const assistantText = String(payload.assistant || payload.assistant_text || '').trim();
  if (!userText || !assistantText) return null;
  const requestPayload = {
    user: userText,
    assistant: assistantText,
    attachments: Array.isArray(payload.attachments) ? payload.attachments : [],
    task_card_snapshot: payload.task_card_snapshot && typeof payload.task_card_snapshot === 'object'
      ? payload.task_card_snapshot
      : null,
    metadata: Object.assign({ source: 'workspace' }, payload.metadata || {}),
  };
  _workspaceTurnPersistQueue = _workspaceTurnPersistQueue
    .catch(() => null)
    .then(async () => {
      try {
        const sessionId = await _ensureWorkspacePersistenceSession();
        if (!sessionId) {
          _queueWorkspaceTurnRetry(requestPayload, 'missing session');
          return null;
        }
        const first = await _sendWorkspaceConversationTurn(sessionId, requestPayload);
        if (first) {
          _removeWorkspaceTurnRetry(requestPayload);
          return first;
        }
        const second = await _sendWorkspaceConversationTurn(sessionId, requestPayload);
        if (second) {
          _removeWorkspaceTurnRetry(requestPayload);
          return second;
        }
        _queueWorkspaceTurnRetry(requestPayload, 'empty response');
        return null;
      } catch (error) {
        console.warn('[WA] workspace turn persistence failed:', error);
        _queueWorkspaceTurnRetry(requestPayload, error);
        return null;
      }
    });
  return _workspaceTurnPersistQueue;
}

function _decodeTaskPayload(value: string): Record<string, any> | null {
  const text = String(value || '').trim();
  if (!text) return null;
  try {
    const decoded = decodeURIComponent(text);
    const parsed = JSON.parse(decoded);
    return parsed && typeof parsed === 'object' ? parsed : null;
  } catch (_) {
    return null;
  }
}

export function _persistTerminalTaskRunCard(card: HTMLElement | null): Promise<any> {
  if (!card || !(card as any).dataset) return Promise.resolve(null);
  const dataset = (card as HTMLElement).dataset;
  if (dataset.taskTerminalPersisted === 'true') return Promise.resolve(null);
  if (dataset.taskTerminalPersisting === 'true') return Promise.resolve(null);
  const taskPayload = _decodeTaskPayload(dataset.taskFollowupPayload || '') || {};
  const userText = String(dataset.taskRequest || taskPayload.task || '').trim();
  const assistantText = String(dataset.taskFinalAnswer || dataset.taskSummary || '').trim();
  if (!userText || !assistantText) return Promise.resolve(null);
  dataset.taskTerminalPersisting = 'true';
  const WA = (window as any).WA || {};
  const hasCompletedAttr = Object.prototype.hasOwnProperty.call(dataset, 'taskCompleted');
  const completedTask = hasCompletedAttr
    ? String(dataset.taskCompleted || '').trim().toLowerCase() === 'true'
    : ['completed', 'done', 'verified'].includes(normalizeFileTaskTerminalStatus(dataset.taskTerminalStatus || ''));
  const terminalStatus = normalizeFileTaskTerminalStatus(dataset.taskTerminalStatus || (completedTask ? 'completed' : 'needs_attention'));
  const uiStatus = fileTaskTerminalUiStatus(terminalStatus, completedTask);
  const metadata: Record<string, any> = {
    turn_id: String(dataset.turnId || '').trim(),
    task_kind: 'file_task',
    partial: false,
    skip_model_context: false,
    task_title: String(dataset.taskTitle || '').trim() || '文件任务结果',
    task_request: userText,
    status: uiStatus,
    task_terminal_status: terminalStatus,
    completed_task: completedTask,
  };
  if (taskPayload && Object.keys(taskPayload).length) {
    metadata.task_request_payload = taskPayload;
    if (taskPayload.task_context && typeof taskPayload.task_context === 'object') {
      metadata.task_context = taskPayload.task_context;
    }
  }
  if (typeof WA.taskCardTestStructure === 'function') {
    try {
      const structure = WA.taskCardTestStructure(card);
      if (structure) metadata.test_structure = structure;
    } catch (_) { /* noop */ }
  }
  const includeSnapshot = !metadata.test_structure;
  const snapshot = includeSnapshot && card.classList && card.classList.contains('wa-task-run')
    ? {
        html: card.outerHTML,
        fatal_error_text: String((card as any)._fatalErrorText || ''),
      }
    : null;
  return _persistWorkspaceConversationTurn({
    user: userText,
    assistant: assistantText,
    metadata,
    task_card_snapshot: snapshot,
  }).then((result) => {
    if (result) {
      dataset.taskTerminalPersisted = 'true';
      delete dataset.taskTerminalPersisting;
    } else {
      delete dataset.taskTerminalPersisting;
    }
    return result;
  }).catch((error) => {
    delete dataset.taskTerminalPersisting;
    throw error;
  });
}

export async function retryWorkspaceConversationPersistence(notify = true): Promise<number> {
  if (_workspaceTurnRetrying) return 0;
  const queue = _loadWorkspaceTurnRetryQueue();
  if (!queue.length) {
    if (notify) showToast('没有待补保存的对话', 'info', 1800);
    return 0;
  }
  _workspaceTurnRetrying = true;
  let saved = 0;
  const remaining: Array<Record<string, any>> = [];
  try {
    const sessionId = await _ensureWorkspacePersistenceSession();
    if (!sessionId) {
      _scheduleWorkspaceTurnRetry(10000);
      return 0;
    }
    for (const item of queue) {
      const payload = item && item.payload && typeof item.payload === 'object' ? item.payload : null;
      if (!payload) continue;
      const ok = await _sendWorkspaceConversationTurn(sessionId, payload);
      if (ok) {
        saved += 1;
      } else {
        remaining.push(Object.assign({}, item, {
          attempts: Number(item.attempts || 0) + 1,
          last_error: 'retry failed',
        }));
      }
    }
    _saveWorkspaceTurnRetryQueue(remaining);
    if (saved && (notify || !remaining.length)) showToast(`已补保存 ${saved} 条对话`, 'success', 2600);
    if (remaining.length) _scheduleWorkspaceTurnRetry(15000);
    return saved;
  } finally {
    _workspaceTurnRetrying = false;
  }
}

export interface RuntimeConfig {
  state: any;
  getMessagesElement: () => HTMLElement | null;
  getSessionId?: () => string;
  hideWelcome?: () => void;
  renderMarkdown?: (text: string) => string;
  loadSessionHistory?: (sessionId: string) => Promise<any[]>;
  selectionContextText?: (ctx: any) => string;
  createPinnedSelectionContext?: (text: any, sourceMeta?: any) => any;
  showToast?: (message: string, kind?: string, duration?: number) => void;
  scheduleAutoSave?: () => void;
  getUserInputElement?: () => HTMLElement | null;
  sendMessage?: () => void;
  getActiveEditorContent?: () => string;
  sampleTaskContext?: (text: string, limit?: number) => string;
  getModelMode?: () => string;
  getSelectedCloudModelId?: () => string;
  getConversationHistory?: () => any[];
  beginAssistantTaskTurn?: (metadata: any) => any;
  syncAssistantTaskTurn?: (turnId: string, metadata: any) => any;
  appendAssistantTurn?: (text: string, metadata?: any) => any;
  persistTaskTurn?: (record: any) => Promise<any>;
  streamTaskFlow?: (options: any) => any;
  setStreamButton?: (streaming: boolean) => void;
}

export interface TaskEntryRoute {
  match?: (text: string) => boolean;
  handler?: (options: any) => any;
  modelId?: string;
  [key: string]: any;
}

export interface TaskQuickAction {
  action: string;
  handler?: (options: any) => any;
  [key: string]: any;
}

// ── Lazy initialization of all AI runtimes ───────────────────────
export function _initWorkspaceAiRuntimes(): void {
  if (!_waAiResultsRuntime && (window as any).WA && typeof (window as any).WA.createWorkspaceAiResultsRuntime === 'function') {
    _waAiResultsRuntime = (window as any).WA.createWorkspaceAiResultsRuntime({
      state,
      getMessagesElement: () => $('wa-ai-messages'),
      selectionContextText: _selectionContextText,
      createPinnedSelectionContext: _createPinnedSelectionContext,
      showToast,
      scheduleAutoSave: () => (window as any).WA.scheduleAutoSave && (window as any).WA.scheduleAutoSave(),
      getUserInputElement: () => $('wa-user-input'),
      sendMessage: () => (window as any).WA.sendMessage && (window as any).WA.sendMessage(),
      lightbulbIcon: _LIGHTBULB_SVG,
      pencilIcon: _PENCIL_SVG,
      getProposalRationaleText: _getProposalRationaleText,
      proposalCanApply: _proposalCanApply,
      getActiveProposalBatch: () => state._activeProposalBatch,
      acceptProposal: (...args: any[]) => (window as any).WA.acceptProposal(...args),
      rejectProposal: (...args: any[]) => (window as any).WA.rejectProposal(...args),
      modifyProposal: (...args: any[]) => (window as any).WA.modifyProposal(...args),
      submitModify: (...args: any[]) => (window as any).WA._submitModify(...args),
      batchAcceptAll: () => (window as any).WA.batchAcceptAll(),
      batchRejectAll: () => (window as any).WA.batchRejectAll(),
      computeInlineDiff: _computeInlineDiff,
    });
  }

  if (!_waConversationRuntime && (window as any).WA && typeof (window as any).WA.createWorkspaceAiConversation === 'function') {
    _waConversationRuntime = (window as any).WA.createWorkspaceAiConversation({
      state,
      getMessagesElement: () => $('wa-ai-messages'),
      getSessionId: _waSession,
      hideWelcome: _hideWelcome,
      renderMarkdown: _waRenderMarkdown,
      loadSessionHistory: async (sessionId: string) => {
        const normalized = String(sessionId || '').trim();
        if (!normalized || /^workspace_runtime_/i.test(normalized)) return [];
        const response = await fetch(`/api/sessions/${encodeURIComponent(normalized)}`);
        if (!response.ok) return [];
        const data = await response.json().catch(() => null);
        return data && Array.isArray(data.history) ? data.history : [];
      },
    });
  }

  if (!_waTaskDispatcher && (window as any).WA && typeof (window as any).WA.createTaskDispatcher === 'function') {
    _waTaskDispatcher = (window as any).WA.createTaskDispatcher({
      state,
      getActiveEditorContent: () => (state.activeEditor && typeof state.activeEditor.getContent === 'function')
        ? (state.activeEditor.getContent() || '')
        : '',
      sampleTaskContext: _waSampleTaskContext,
      getSessionId: _waSession,
      ensureSessionId: _ensureWorkspacePersistenceSession,
      getModelMode: _waQuickActionModelMode,
      getSelectedCloudModelId: _selectedCloudModelId,
      getConversationHistory: () => _waConversationRuntime && typeof _waConversationRuntime.getHistoryForModel === 'function'
        ? _waConversationRuntime.getHistoryForModel(12)
        : (Array.isArray(state.conversation) ? state.conversation.slice(-12) : []),
      beginAssistantTaskTurn: (metadata: any) => _waConversationRuntime && typeof _waConversationRuntime.beginAssistantTaskTurn === 'function'
        ? _waConversationRuntime.beginAssistantTaskTurn(metadata || {})
        : null,
      syncAssistantTaskTurn: (turnId: string, metadata: any) => _waConversationRuntime && typeof _waConversationRuntime.syncAssistantTaskTurn === 'function'
        ? _waConversationRuntime.syncAssistantTaskTurn(turnId, metadata || {})
        : null,
      appendAssistantTurn: (text: string, metadata: any) => _waConversationRuntime && typeof _waConversationRuntime.appendAssistantTurn === 'function'
        ? _waConversationRuntime.appendAssistantTurn(text, Object.assign({ render: false }, metadata || {}))
        : null,
      persistTaskTurn: _persistWorkspaceConversationTurn,
      streamTaskFlow: (options: any) => (window as any).WA.streamTaskFlow(options),
      setStreamButton: _setStreamBtn,
    });
  }

  if (!_waQuickActionRuntime && (window as any).WA && typeof (window as any).WA.createWorkspaceQuickActionRuntime === 'function') {
    _waQuickActionRuntime = (window as any).WA.createWorkspaceQuickActionRuntime({
      state,
      getMessagesElement: () => $('wa-ai-messages'),
      getModelMode: _waQuickActionModelMode,
      getSelectedCloudModelId: _selectedCloudModelId,
      handleProposals: _handleProposals,
      makeAIActionBar: _makeAIActionBar,
      applyRouteEvent: _applyRouteEvent,
      setPendingToolCall: (parsed: any) => { (state as any).pendingToolCall = parsed; },
      appendAssistantTurn: (text: string, metadata: any) => _waConversationRuntime && typeof _waConversationRuntime.appendAssistantTurn === 'function'
        ? _waConversationRuntime.appendAssistantTurn(text, Object.assign({ render: false }, metadata || {}))
        : null,
      getSessionId: _waSession,
      getConversationHistory: () => _waConversationRuntime && typeof _waConversationRuntime.getHistoryForModel === 'function'
        ? _waConversationRuntime.getHistoryForModel(12)
        : (Array.isArray(state.conversation) ? state.conversation.slice(-12) : []),
      slidesIcon: _SLIDES_SVG,
    });
    _waQuickActionDispatcherAttached = false;
  }

  if (!_waQuickActionDispatcherAttached && _waQuickActionRuntime && _waTaskDispatcher && typeof _waQuickActionRuntime.attachDispatcher === 'function') {
    _waQuickActionRuntime.attachDispatcher(_waTaskDispatcher);
    _waQuickActionDispatcherAttached = true;
  }
  _syncRuntimeGlobals();
}

_initWorkspaceAiRuntimes();
_hydrateAiConversation(true).catch((error: any) => console.warn('[WA] AI history hydrate failed:', error));

// ── Public API ─────────────────────────────────────────────────────

export function hydrateAiHistory(force: boolean = true): Promise<any[]> {
  return _hydrateAiConversation(force);
}

export function useHostSession(sessionId: string, options?: { force?: boolean }): Promise<any[]> {
  _hostSessionId = String(sessionId || '').trim();
  _syncRuntimeGlobals();
  _initWorkspaceAiRuntimes();
  const syncSelection = (window as any).WA && (window as any).WA._syncAiSessionSelection;
  if (_hostSessionId && typeof syncSelection === 'function') {
    syncSelection(_hostSessionId);
  }
  return _hydrateAiConversation(options ? options.force !== false : true);
}

export function registerTaskQuickAction(definition: TaskQuickAction): any {
  _initWorkspaceAiRuntimes();
  if (!_waQuickActionRuntime || typeof _waQuickActionRuntime.registerAction !== 'function') return null;
  return _waQuickActionRuntime.registerAction(definition);
}

export function registerTaskEntryRoute(route: TaskEntryRoute): any {
  _initWorkspaceAiRuntimes();
  if (!_waTaskDispatcher || typeof _waTaskDispatcher.registerMessageRoute !== 'function') return null;
  return _waTaskDispatcher.registerMessageRoute(route);
}

export function registerTaskActionHandler(action: string, handler: (options: any) => any): any {
  _initWorkspaceAiRuntimes();
  if (!_waTaskDispatcher || typeof _waTaskDispatcher.registerQuickActionHandler !== 'function') return null;
  return _waTaskDispatcher.registerQuickActionHandler(action, handler);
}

// ── Backward compat ──
if (typeof window !== 'undefined') {
  (window as any).WA = (window as any).WA || {};
  (window as any).WA.hydrateAiHistory = hydrateAiHistory;
  (window as any).WA.useHostSession = useHostSession;
  (window as any).WA.registerTaskQuickAction = registerTaskQuickAction;
  (window as any).WA.registerTaskEntryRoute = registerTaskEntryRoute;
  (window as any).WA.registerTaskActionHandler = registerTaskActionHandler;
  (window as any).WA._initWorkspaceAiRuntimes = _initWorkspaceAiRuntimes;
  (window as any).WA.retryWorkspaceConversationPersistence = retryWorkspaceConversationPersistence;
  (window as any).WA.persistTerminalTaskRunCard = _persistTerminalTaskRunCard;
  (window as any)._initWorkspaceAiRuntimes = _initWorkspaceAiRuntimes;
  (window as any)._hydrateAiConversation = _hydrateAiConversation;
  (window as any)._waSession = _waSession;
  (window as any)._waRenderMarkdown = _waRenderMarkdown;
  (window as any)._waQuickActionModelMode = _waQuickActionModelMode;
  (window as any)._waSampleTaskContext = _waSampleTaskContext;
  (window as any)._persistWorkspaceConversationTurn = _persistWorkspaceConversationTurn;
  (window as any)._persistTerminalTaskRunCard = _persistTerminalTaskRunCard;
  (window as any)._retryWorkspaceConversationPersistence = retryWorkspaceConversationPersistence;
  window.addEventListener('online', () => _scheduleWorkspaceTurnRetry(1000));
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) _scheduleWorkspaceTurnRetry(1000);
  });
  if (_loadWorkspaceTurnRetryQueue().length) _scheduleWorkspaceTurnRetry(1500);
  _syncRuntimeGlobals();
}
