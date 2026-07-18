/**
 * Right-panel AI conversation browser.
 * Presents chat sessions as a VS Code/Codex-style history list, then opens the
 * existing workspace conversation runtime for the selected session.
 */

import {
  focusWorkspaceAiComposer,
  getWorkspaceAiComposerInput,
  getWorkspaceAiComposerSendButton,
  mountWorkspaceAiComposer,
  resizeWorkspaceAiComposer,
  setWorkspaceAiComposerValue,
  syncWorkspaceAiComposerSendState,
  workspaceAiComposerMode,
} from './ai-composer';
import {
  AiSessionPreview,
  createAiSessionRecord,
  deleteAiSessionRecord,
  fetchAiSessionPreviews,
  formatSessionTime,
  normalizeSessionId,
  sessionTitle,
  taskStatusLabel,
} from './conversation-sessions';
import { $, _CHAT_SVG, _TRASH_SVG, _escHtml, showToast } from './infrastructure';
import { getWorkspaceApi, publishWorkspaceApi } from '../shared/workspace-api';

const workspaceApi = getWorkspaceApi();

interface RefreshOptions {
  silent?: boolean;
}

interface NewSessionOptions {
  focus?: boolean;
  toast?: boolean;
}

let _activeAiSessionId = String((window as any)._hostSessionId || '').trim();
let _sessions: AiSessionPreview[] = [];
let _refreshPromise: Promise<AiSessionPreview[]> | null = null;
let _bound = false;
let _sessionsExpanded = false;
let _sessionActionsBusy = false;

const _SESSION_PREVIEW_LIMIT = 5;

function _activeSessionMeta(): AiSessionPreview | null {
  const id = normalizeSessionId(_activeAiSessionId);
  return _sessions.find((session) => session.id === id) || (id ? { id, title: sessionTitle(null, id) } : null);
}

function _focusComposer(): void {
  focusWorkspaceAiComposer('chat');
}

function _closeSkillLibrary(): void {
  if (typeof workspaceApi.closeSkillLibrary === 'function') {
    try {
      workspaceApi.closeSkillLibrary();
    } catch (_) { /* noop */ }
  }
}

function _setActivityActive(id: string): void {
  document.querySelectorAll('.activity-btn').forEach((button) => button.classList.remove('active'));
  const target = document.getElementById(id);
  if (target) target.classList.add('active');
}

function _setChatHeader(sessionId?: string): void {
  const id = normalizeSessionId(sessionId || _activeAiSessionId);
  const meta = _sessions.find((session) => session.id === id) || (id ? { id, title: sessionTitle(null, id) } : null);
  const title = $('wa-ai-chat-title');
  const subtitle = $('wa-ai-chat-subtitle');
  if (title) title.textContent = sessionTitle(meta, _activeAiSessionId) || 'Koto AI';
  if (subtitle) {
    const count = Number(meta && meta.message_count || 0);
    const taskCount = Number(meta && meta.task_count || 0);
    const parts = [
      count ? `${count} 条消息` : '',
      taskCount ? `${taskCount} 个任务` : '',
    ].filter(Boolean);
    subtitle.textContent = parts.length ? parts.join(' · ') : '新对话 · 输入问题或拖入文件开始';
  }
}

function _renderLoading(): void {
  const list = $('wa-ai-session-list');
  if (!list) return;
  list.innerHTML = '<div class="wa-ai-session-state">正在读取对话...</div>';
  _syncSessionActionState();
}

function _renderEmpty(message = '发送第一条消息开始对话'): void {
  const list = $('wa-ai-session-list');
  if (!list) return;
  list.innerHTML = `
    <div class="wa-ai-session-empty">
      <strong>${_escHtml(message)}</strong>
      <span>在输入框输入即可开始新对话；附加文件后会进入文件任务流程。</span>
    </div>`;
  _syncSessionActionState();
}

function _syncSessionActionState(): void {
  const clearButton = $('wa-ai-session-clear') as HTMLButtonElement | null;
  const refreshButton = $('wa-ai-session-refresh') as HTMLButtonElement | null;
  const summary = $('wa-ai-session-summary');
  const totalTasks = _sessions.reduce((sum, session) => sum + Math.max(0, Number(session.task_count || 0)), 0);
  if (summary) {
    summary.textContent = _sessions.length
      ? `${_sessions.length} 条对话${totalTasks ? ` · ${totalTasks} 个任务` : ''}`
      : 'AI 工作区';
  }
  if (clearButton) {
    clearButton.disabled = _sessionActionsBusy || !_sessions.length;
    clearButton.classList.toggle('is-busy', _sessionActionsBusy);
  }
  if (refreshButton) {
    refreshButton.disabled = _sessionActionsBusy;
    refreshButton.classList.toggle('is-busy', !!_refreshPromise);
  }
}

function _renderSessions(): void {
  const list = $('wa-ai-session-list');
  if (!list) return;
  if (!_sessions.length) {
    _renderEmpty();
    return;
  }
  const visibleSessions = _sessionsExpanded ? _sessions : _sessions.slice(0, _SESSION_PREVIEW_LIMIT);
  const hiddenCount = Math.max(0, _sessions.length - visibleSessions.length);
  const sessionHtml = visibleSessions.map((session) => {
    const active = session.id === _activeAiSessionId ? ' is-active' : '';
    const taskTitle = String(session.latest_task_title || '').trim();
    const title = taskTitle || sessionTitle(session, _activeAiSessionId);
    const preview = session.preview || '（空消息）';
    const time = formatSessionTime(session);
    const count = Number(session.message_count || 0);
    const countText = count ? `${count} 条消息` : '空会话';
    const taskCount = Number(session.task_count || 0);
    const hasTaskFlow = Boolean(session.has_task_flow || taskCount);
    const taskStatus = String(session.latest_task_status || '').trim().toLowerCase();
    const taskBadge = hasTaskFlow
      ? `<span class="wa-ai-session-task-badge" data-status="${_escHtml(taskStatus || 'task')}">${_escHtml(taskCount > 1 ? `任务 ${taskCount} · ${taskStatusLabel(taskStatus)}` : taskStatusLabel(taskStatus))}</span>`
      : '';
    return `
      <div role="button" tabindex="0" class="wa-ai-session-item${hasTaskFlow ? ' has-task-flow' : ''}${active}" data-ai-session-id="${_escHtml(session.id)}" data-task-count="${_escHtml(String(taskCount))}" data-latest-task-title="${_escHtml(taskTitle)}" data-latest-task-status="${_escHtml(taskStatus)}" title="${_escHtml(title)}">
        <span class="wa-ai-session-icon">${_CHAT_SVG}</span>
        <span class="wa-ai-session-main">
          <span class="wa-ai-session-top">
            <span class="wa-ai-session-name">${_escHtml(title)}</span>
            ${time ? `<span class="wa-ai-session-time">${_escHtml(time)}</span>` : ''}
          </span>
          <span class="wa-ai-session-preview">${_escHtml(preview)}</span>
          <span class="wa-ai-session-meta-row">
            <span class="wa-ai-session-count">${_escHtml(countText)}</span>
            ${taskBadge}
          </span>
        </span>
        <button type="button" class="wa-ai-session-delete" data-ai-session-delete="${_escHtml(session.id)}" title="删除对话" aria-label="删除对话 ${_escHtml(title)}">${_TRASH_SVG}</button>
      </div>`;
  }).join('');
  const expandHtml = _sessions.length > _SESSION_PREVIEW_LIMIT
    ? `<button type="button" class="wa-ai-session-expand" data-ai-session-expand="${_sessionsExpanded ? '0' : '1'}">${_escHtml(_sessionsExpanded ? '收起历史' : `展开 ${hiddenCount} 条历史`)}</button>`
    : '';
  list.innerHTML = sessionHtml + expandHtml;
  _syncSessionActionState();
  _setChatHeader();
}

function _openLatestTaskFlowForSession(sessionId: string): void {
  const session = _sessions.find((item) => item.id === normalizeSessionId(sessionId));
  const taskId = String(session && session.latest_task_id || '').trim();
  if (!taskId) return;
  _syncHistoricalTaskLiveProgress(session);
  if (typeof workspaceApi.openTaskWorkbenchForCurrentRun !== 'function') return;
  window.setTimeout(() => {
    workspaceApi.openTaskWorkbenchForCurrentRun({
      taskId,
      runId: String(session && session.latest_task_run_id || '').trim(),
      scroll: false,
    });
  }, 0);
}

function _syncHistoricalTaskLiveProgress(session?: AiSessionPreview): void {
  const host = $('wa-task-live-progress') as HTMLElement | null;
  if (!host || !session) return;
  const status = String(session.latest_task_status || '').trim().toLowerCase() || 'completed';
  const statusText = taskStatusLabel(status);
  host.hidden = false;
  host.dataset.status = status;
  const statusEl = host.querySelector('[data-role="live-status"]');
  const phaseEl = host.querySelector('[data-role="live-phase"]');
  const planEl = host.querySelector('[data-role="live-plan"]') as HTMLElement | null;
  const valueEl = host.querySelector('[data-role="live-progress-value"]');
  const fillEl = host.querySelector('[data-role="live-progress-fill"]') as HTMLElement | null;
  if (statusEl) statusEl.textContent = statusText;
  if (phaseEl) phaseEl.textContent = '任务流程';
  if (planEl) {
    planEl.textContent = '历史任务';
    planEl.style.display = '';
  }
  if (valueEl) valueEl.textContent = status === 'running' ? '继续观察步骤' : '查看执行过程';
  if (fillEl) fillEl.style.width = status === 'running' ? '55%' : '100%';
}

function _showChatView(): void {
  _closeSkillLibrary();
  _setActivityActive('navAiSessionsBtn');
  const listView = $('wa-ai-session-list-view');
  const chatView = $('wa-ai-chat-view');
  if (listView) listView.hidden = true;
  if (chatView) chatView.hidden = false;
  mountWorkspaceAiComposer('chat');
  _setChatHeader();
}

/**
 * The activity-bar AI entry is a conversation entry point, not a history
 * browser.  Keep the history list behind the back button in the chat header.
 */
export function showAiChat(): void {
  _showChatView();
  _focusComposer();
}

export function showAiSessionList(): void {
  _closeSkillLibrary();
  _setActivityActive('navAiSessionsBtn');
  const listView = $('wa-ai-session-list-view');
  const chatView = $('wa-ai-chat-view');
  if (chatView) chatView.hidden = true;
  if (listView) listView.hidden = false;
  mountWorkspaceAiComposer('sessionList');
  refreshAiSessions({ silent: true }).catch(() => {});
}

export async function refreshAiSessions(options: RefreshOptions = {}): Promise<AiSessionPreview[]> {
  if (!options.silent) _closeSkillLibrary();
  if (_refreshPromise) return _refreshPromise;
  const list = $('wa-ai-session-list');
  if (list && (!options.silent || !list.children.length)) _renderLoading();
  _syncSessionActionState();
  _refreshPromise = fetchAiSessionPreviews()
    .then((sessions) => {
      _sessions = sessions;
      _renderSessions();
      return _sessions;
    })
    .catch((error) => {
      console.warn('[WA] AI sessions load failed:', error);
      if (list) _renderEmpty('读取对话失败');
      return _sessions;
    })
    .finally(() => {
      _refreshPromise = null;
      _syncSessionActionState();
    });
  return _refreshPromise;
}

export async function openAiSession(sessionId: string, options: RefreshOptions & { force?: boolean } = {}): Promise<any> {
  const normalized = normalizeSessionId(sessionId);
  if (!normalized) return null;
  _activeAiSessionId = normalized;
  _showChatView();
  _renderSessions();

  if (typeof workspaceApi.useHostSession === 'function') {
    const opened = await workspaceApi.useHostSession(normalized, { force: options.force !== false });
    _openLatestTaskFlowForSession(normalized);
    return opened;
  }
  _openLatestTaskFlowForSession(normalized);
  return null;
}

export async function deleteAiSession(sessionId: string): Promise<boolean> {
  const normalized = normalizeSessionId(sessionId);
  if (!normalized) return false;
  const title = sessionTitle(_sessions.find((session) => session.id === normalized) || { id: normalized }, _activeAiSessionId);
  if (!window.confirm(`确认删除对话「${title}」？此操作不可撤销。`)) return false;
  try {
    await deleteAiSessionRecord(normalized);
    const wasActive = normalized === normalizeSessionId(_activeAiSessionId);
    _sessions = _sessions.filter((session) => session.id !== normalized);
    if (wasActive) {
      const next = _sessions[0];
      if (next) {
        _activeAiSessionId = next.id;
        if (typeof workspaceApi.useHostSession === 'function') {
          await workspaceApi.useHostSession(next.id, { force: true });
        }
      } else {
        _activeAiSessionId = '';
        const runtime = workspaceApi.getWorkspaceConversationRuntime?.();
        if (runtime && typeof runtime.reset === 'function') runtime.reset();
      }
      showAiSessionList();
    } else {
      _renderSessions();
    }
    showToast('已删除对话', 'success');
    refreshAiSessions({ silent: true }).catch(() => {});
    return true;
  } catch (error: any) {
    showToast(error && error.message ? error.message : '删除对话失败', 'error');
    return false;
  }
}

export async function clearAiSessions(): Promise<boolean> {
  if (!_sessions.length) {
    showToast('没有可清除的历史对话', 'info');
    return false;
  }
  const count = _sessions.length;
  if (!window.confirm(`确认清除全部 ${count} 条历史对话？此操作不可撤销。`)) return false;

  const sessionsToDelete = _sessions.map((session) => session.id).filter(Boolean);
  const clearButton = $('wa-ai-session-clear') as HTMLButtonElement | null;
  _sessionActionsBusy = true;
  if (clearButton) clearButton.disabled = true;
  _syncSessionActionState();

  const failedIds: string[] = [];
  try {
    for (const sessionId of sessionsToDelete) {
      try {
        await deleteAiSessionRecord(sessionId);
      } catch (error) {
        console.warn('[WA] clear AI session failed:', sessionId, error);
        failedIds.push(sessionId);
      }
    }

    _sessions = failedIds.length
      ? _sessions.filter((session) => failedIds.includes(session.id))
      : [];
    if (!failedIds.length) {
      _activeAiSessionId = '';
      const runtime = workspaceApi.getWorkspaceConversationRuntime?.();
      if (runtime && typeof runtime.reset === 'function') runtime.reset();
    }
    showAiSessionList();
    await refreshAiSessions({ silent: true });

    if (failedIds.length) {
      showToast(`已清除 ${count - failedIds.length} 条，${failedIds.length} 条失败`, 'error');
      return false;
    }
    showToast(`已清除 ${count} 条历史对话`, 'success');
    return true;
  } finally {
    _sessionActionsBusy = false;
    _syncSessionActionState();
  }
}

export async function newAiSession(options: NewSessionOptions = {}): Promise<any> {
  _closeSkillLibrary();
  try {
    const sessionId = await createAiSessionRecord();
    await refreshAiSessions({ silent: true });
    const opened = await openAiSession(sessionId, { force: true });
    if (options.toast !== false) showToast('新对话已创建，在下方输入框开始吧。', 'success');
    if (options.focus !== false) _focusComposer();
    return opened;
  } catch (error: any) {
    showToast(error && error.message ? error.message : '创建对话失败', 'error');
    return null;
  }
}

export async function submitUnifiedAiComposer(): Promise<any> {
  const mode = workspaceAiComposerMode();
  if (mode !== 'sessionList') {
    if (typeof workspaceApi.sendMessage === 'function') return workspaceApi.sendMessage();
    return null;
  }

  const input = getWorkspaceAiComposerInput();
  const text = String(input && input.value || '').trim();
  if (!input || !text) {
    if (input) input.focus();
    syncWorkspaceAiComposerSendState('sessionList');
    return null;
  }

  const sendButton = getWorkspaceAiComposerSendButton();
  input.disabled = true;
  if (sendButton) sendButton.disabled = true;

  try {
    const sessionId = await createAiSessionRecord();
    await refreshAiSessions({ silent: true });
    await openAiSession(sessionId, { force: true });

    input.disabled = false;
    const chatInput = setWorkspaceAiComposerValue('chat', text, { focus: false, dispatchInput: true });
    if (!chatInput) throw new Error('对话输入框未就绪');

    if (typeof workspaceApi.sendMessage !== 'function') throw new Error('模型发送通路未就绪');
    workspaceApi.sendMessage();

    return sessionId;
  } catch (error: any) {
    showToast(error && error.message ? error.message : '新对话发送失败', 'error');
    return null;
  } finally {
    input.disabled = false;
    syncWorkspaceAiComposerSendState(workspaceAiComposerMode());
  }
}

export function sendSessionListComposer(): Promise<any> {
  return submitUnifiedAiComposer();
}

export function handleUnifiedComposerKeydown(event: KeyboardEvent): void {
  const target = event.target as HTMLTextAreaElement | null;
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    submitUnifiedAiComposer().catch(() => {});
    return;
  }
  window.setTimeout(() => {
    if (target && target.tagName === 'TEXTAREA') resizeWorkspaceAiComposer(target);
    syncWorkspaceAiComposerSendState(workspaceAiComposerMode());
  }, 0);
}

export function handleSessionListComposerKeydown(event: KeyboardEvent): void {
  handleUnifiedComposerKeydown(event);
}

function _bindAiSessionBrowser(): void {
  if (_bound) return;
  _bound = true;
  const list = $('wa-ai-session-list');
  if (list) {
    list.addEventListener('click', (event) => {
      const target = event.target as HTMLElement | null;
      const deleteButton = target && target.closest('[data-ai-session-delete]') as HTMLElement | null;
      if (deleteButton) {
        event.preventDefault();
        event.stopPropagation();
        deleteAiSession(deleteButton.dataset.aiSessionDelete || '').catch(() => {});
        return;
      }
      const expandButton = target && target.closest('[data-ai-session-expand]') as HTMLElement | null;
      if (expandButton) {
        event.preventDefault();
        _sessionsExpanded = expandButton.dataset.aiSessionExpand === '1';
        _renderSessions();
        return;
      }
      const item = target && target.closest('[data-ai-session-id]') as HTMLElement | null;
      const sessionId = item ? item.dataset.aiSessionId || '' : '';
      if (sessionId) openAiSession(sessionId, { force: true }).catch(() => {});
    });
    list.addEventListener('keydown', (event) => {
      const keyboardEvent = event as KeyboardEvent;
      if (keyboardEvent.key !== 'Enter' && keyboardEvent.key !== ' ') return;
      const target = keyboardEvent.target as HTMLElement | null;
      const item = target && target.closest('[data-ai-session-id]') as HTMLElement | null;
      if (!item || target?.closest('[data-ai-session-delete]')) return;
      keyboardEvent.preventDefault();
      openAiSession(item.dataset.aiSessionId || '', { force: true }).catch(() => {});
    });
  }
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
  _renderSessions();
}

function _initAiSessionBrowser(): void {
  if (!$('wa-ai-session-list-view')) return;
  _bindAiSessionBrowser();
  _showChatView();
  _setChatHeader(_activeAiSessionId);
  refreshAiSessions({ silent: true }).catch(() => {});
}

publishWorkspaceApi({
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
