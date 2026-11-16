/** Task history in the sidebar, backed by the canonical workspace session runtime. */

import {
  focusWorkspaceAiComposer,
  getWorkspaceAiComposerInput,
  mountWorkspaceAiComposer,
  resizeWorkspaceAiComposer,
  syncWorkspaceAiComposerSendState,
  workspaceAiComposerMode,
} from './ai-composer';
import {
  AiSessionPreview,
  createAiSessionRecord,
  deleteAiSessionRecord,
  fetchAiSessionPreviews,
  normalizeSessionId,
  sessionTitle,
} from './conversation-sessions';
import { $, showToast } from './infrastructure';
import { getFeatureRegistry, registerFeatures } from '../shared/feature-registry';
import { mountComponent } from '../shared/component-bridge';
import type { KotoConversationList } from './components/koto-conversation-list';

const workspaceApi = getFeatureRegistry();

interface RefreshOptions {
  silent?: boolean;
}

interface NewSessionOptions {
  focus?: boolean;
  toast?: boolean;
}

let _activeAiSessionId = String(getFeatureRegistry()._hostSessionId || '').trim();
let _sessions: AiSessionPreview[] = [];
let _refreshPromise: Promise<AiSessionPreview[]> | null = null;
let _bound = false;
let _sessionActionsBusy = false;

/** Reference to the Lit component, set after mount. */
let _componentEl: KotoConversationList | null = null;

function _activeSessionMeta(): AiSessionPreview | null {
  const id = normalizeSessionId(_activeAiSessionId);
  return _sessions.find((session) => session.id === id) || (id ? { id, title: sessionTitle(null, id) } : null);
}

function _focusComposer(): void {
  focusWorkspaceAiComposer('chat');
}

function _setChatHeader(sessionId?: string): void {
  const id = normalizeSessionId(sessionId || _activeAiSessionId);
  const meta = _sessions.find((session) => session.id === id) || (id ? { id, title: sessionTitle(null, id) } : null);
  const title = $('wa-ai-chat-title');
  const subtitle = $('wa-ai-chat-subtitle');
  if (title) title.textContent = !Number(meta?.message_count || 0) && /^对话_\d/.test(id)
    ? '新任务' : sessionTitle(meta, _activeAiSessionId) || '新任务';
  if (subtitle) {
    const count = Number(meta && meta.message_count || 0);
    const taskCount = Number(meta && meta.task_count || 0);
    const parts = [
      count ? `${count} 条消息` : '',
      taskCount ? `${taskCount} 个任务` : '',
    ].filter(Boolean);
    subtitle.textContent = parts.length ? parts.join(' · ') : '与 Koto 一起完成工作';
  }
}

/** Push current state into the Lit component for reactive rendering. */
function _updateComponent(): void {
  if (!_componentEl) return;
  _componentEl.loading = false;
  _componentEl.sessions = _sessions;
  _componentEl.activeSessionId = _activeAiSessionId;
}

function _syncSessionActionState(): void {
  const button = document.getElementById('koto-new-task') as HTMLButtonElement | null;
  if (button) button.disabled = _sessionActionsBusy;
}

export function showAiSessionList(): void {
  document.getElementById('wa-ai-session-list-view')?.scrollIntoView({ block: 'nearest' });
  _updateComponent();
}

export function showAiChat(): void {
  _showChatView();
  workspaceApi.showConversationLayout?.();
  _focusComposer();
}

function _showChatView(): void {
  const chatView = $('wa-ai-chat-view');
  if (chatView) chatView.hidden = false;
  mountWorkspaceAiComposer('chat');
}

export async function refreshAiSessions(options: RefreshOptions = {}): Promise<AiSessionPreview[]> {
  if (options.silent) {
    try {
      _sessions = await fetchAiSessionPreviews();
      if (_componentEl) _componentEl.errorText = '';
      _updateComponent();
    } catch (_) {
      if (_componentEl) { _componentEl.loading = false; _componentEl.errorText = '任务加载失败'; }
    }
    return _sessions;
  }
  if (_refreshPromise) return _refreshPromise;
  _sessionActionsBusy = true;
  _syncSessionActionState();
  _refreshPromise = fetchAiSessionPreviews()
    .then((sessions) => {
      _sessions = sessions;
      if (_componentEl) _componentEl.errorText = '';
      return sessions;
    })
    .catch((error) => {
      if (_componentEl) _componentEl.errorText = '任务加载失败';
      throw error;
    })
    .finally(() => {
      _refreshPromise = null;
      _sessionActionsBusy = false;
      _syncSessionActionState();
      _updateComponent();
    });
  return _refreshPromise;
}

export async function openAiSession(sessionId: string, options: { silent?: boolean; force?: boolean } = {}): Promise<any> {
  const normalized = normalizeSessionId(sessionId);
  if (!normalized) return null;
  if (!options.force && normalized === _activeAiSessionId) {
    _showChatView();
    _updateComponent();
    return null;
  }
  _activeAiSessionId = normalized;
  _updateComponent();
  _showChatView();
  workspaceApi.showConversationLayout?.();
  workspaceApi.closeMobileFiles?.();
  workspaceApi.closeWorkspaceNavigation?.();
  _setChatHeader(normalized);
  _focusComposer();

  const api = getFeatureRegistry();
  const loadSession = typeof api.useHostSession === 'function'
    ? api.useHostSession
    : api.loadChatSession;
  if (typeof loadSession === 'function') {
    try {
      await loadSession(normalized, { force: true });
    } catch (_) { /* session runtime handles its own errors */ }
  }
  return null;
}

export async function deleteAiSession(sessionId: string): Promise<void> {
  const normalized = normalizeSessionId(sessionId);
  if (!normalized || _sessionActionsBusy) return;
  if (!window.confirm('删除这个任务及其对话记录？此操作无法撤销。')) return;
  _sessionActionsBusy = true;
  _syncSessionActionState();
  try {
    await deleteAiSessionRecord(normalized);
    _sessions = _sessions.filter((s) => s.id !== normalized);
    if (_activeAiSessionId === normalized) {
      _activeAiSessionId = _sessions[0]?.id || '';
      if (!_activeAiSessionId) _showChatView();
      else _setChatHeader(_activeAiSessionId);
    }
    _updateComponent();
    showToast('对话已删除', 'info');
  } catch (error: any) {
    showToast(error && error.message ? error.message : '删除对话失败', 'error');
  } finally {
    _sessionActionsBusy = false;
    _syncSessionActionState();
  }
}

export async function clearAiSessions(): Promise<void> {
  if (_sessionActionsBusy || !_sessions.length) return;
  const count = _sessions.length;
  if (!window.confirm(`确认清除全部 ${count} 条历史对话？此操作不可撤销。`)) return;
  _sessionActionsBusy = true;
  _syncSessionActionState();
  try {
    for (const session of _sessions) {
      await deleteAiSessionRecord(session.id).catch(() => {});
    }
    _sessions = [];
    _activeAiSessionId = '';
    _updateComponent();
    _showChatView();
    showToast('全部对话已清除', 'info');
  } catch (error: any) {
    showToast(error && error.message ? error.message : '清除失败', 'error');
  } finally {
    _sessionActionsBusy = false;
    _syncSessionActionState();
  }
}

export async function newAiSession(options: NewSessionOptions = {}): Promise<any> {
  if (_sessionActionsBusy) return null;
  _sessionActionsBusy = true;
  _syncSessionActionState();
  try {
    const newId = await createAiSessionRecord();
    if (options.toast !== false) showToast('新对话已创建', 'success');
    await refreshAiSessions({ silent: true });
    await openAiSession(newId, { force: true });
    if (options.focus !== false) _focusComposer();
    return newId;
  } catch (error: any) {
    showToast(error && error.message ? error.message : '创建新对话失败', 'error');
    return null;
  } finally {
    _sessionActionsBusy = false;
    _syncSessionActionState();
  }
}

async function submitUnifiedAiComposer(): Promise<any> {
  if (typeof workspaceApi.sendMessage === 'function') return workspaceApi.sendMessage();
  return null;
}

export function sendSessionListComposer(): void {
  void submitUnifiedAiComposer();
}

function handleUnifiedComposerKeydown(event: KeyboardEvent): void {
  if (event.isComposing || event.keyCode === 229) return;
  workspaceApi.handleInputKeydown?.(event);
}

export function handleSessionListComposerKeydown(event: KeyboardEvent): void {
  handleUnifiedComposerKeydown(event);
}

function _bindComponentEvents(): void {
  if (_bound || !_componentEl) return;
  _bound = true;

  _componentEl.addEventListener('koto-session-select', (e) => {
    const sessionId = (e as CustomEvent).detail?.sessionId;
    if (sessionId) openAiSession(sessionId, { force: true }).catch(() => {});
  });

  _componentEl.addEventListener('koto-session-delete', (e) => {
    const sessionId = (e as CustomEvent).detail?.sessionId;
    if (sessionId) deleteAiSession(sessionId).catch(() => {});
  });

  _componentEl.addEventListener('koto-session-refresh', () => {
    refreshAiSessions().catch(() => {});
  });

  const input = getWorkspaceAiComposerInput();
  if (input) {
    input.addEventListener('input', () => {
      resizeWorkspaceAiComposer(input);
      syncWorkspaceAiComposerSendState(workspaceAiComposerMode());
    });
    resizeWorkspaceAiComposer(input);
    syncWorkspaceAiComposerSendState(workspaceAiComposerMode());
  }
}

export function syncAiSessionSelection(sessionId: string, options: { showChat?: boolean } = {}): void {
  const normalized = normalizeSessionId(sessionId);
  if (!normalized) return;
  _activeAiSessionId = normalized;
  if (options.showChat !== false) _showChatView();
  else _setChatHeader(normalized);
  _updateComponent();
}

function _initAiSessionBrowser(): void {
  const container = $('wa-ai-session-list');
  if (!container) return;

  container.replaceChildren();
  _componentEl = mountComponent<KotoConversationList>(
    'koto-conversation-list',
    container,
    { sessions: _sessions, activeSessionId: _activeAiSessionId },
  );

  _bindComponentEvents();
  _showChatView();
  _setChatHeader(_activeAiSessionId);
  refreshAiSessions({ silent: true }).catch(() => {});
}

registerFeatures({
  showAiSessionList,
  showAiChat,
  refreshAiSessions,
  openAiSession,
  deleteAiSession,
  clearAiSessions,
  newAiSession,
  submitUnifiedAiComposer,
  handleUnifiedComposerKeydown,
  sendSessionListComposer,
  handleSessionListComposerKeydown,
  _syncAiSessionSelection: syncAiSessionSelection,
  _activeAiSessionMeta: _activeSessionMeta,
});

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', _initAiSessionBrowser);
} else {
  _initAiSessionBrowser();
}
