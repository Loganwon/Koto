/**
 * Right-panel AI conversation browser.
 * Presents chat sessions as a VS Code/Codex-style history list, then opens the
 * existing workspace conversation runtime for the selected session.
 */

import { $, _CHAT_SVG, _TRASH_SVG, _csrfFetch, _escHtml, showToast } from './infrastructure';

interface AiSessionPreview {
  id: string;
  title?: string;
  preview?: string;
  message_count?: number;
  last_role?: string;
  updated_at?: string;
  mtime?: number;
  task_count?: number;
  has_task_flow?: boolean;
  latest_task_status?: string;
  latest_task_id?: string;
  latest_task_run_id?: string;
}

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

const _PLUS_SVG = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14"/><path d="M5 12h14"/></svg>';
const _REFRESH_SVG = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 0 1-15.5 6.2"/><path d="M3 12A9 9 0 0 1 18.5 5.8"/><path d="M18 2v4h4"/><path d="M6 22v-4H2"/></svg>';
const _SESSION_PREVIEW_LIMIT = 5;

function _normalizeSessionId(value: unknown): string {
  return String(value || '').trim().replace(/\.json$/i, '');
}

function _displaySessionName(sessionId: string): string {
  const bridgeName = (window as any).toSessionDisplayName;
  if (typeof bridgeName === 'function') {
    try {
      const label = String(bridgeName(sessionId) || '').trim();
      if (label) return label;
    } catch (_) { /* noop */ }
  }
  return sessionId.replace(/^chat_/, '对话 ').replace(/_/g, ' ');
}

function _sessionTitle(session: AiSessionPreview | null): string {
  const title = String(session && session.title || '').trim();
  if (title && title !== session?.id) return title;
  return _displaySessionName(session ? session.id : _activeAiSessionId);
}

function _formatSessionTime(session: AiSessionPreview): string {
  const raw = String(session.updated_at || '').trim();
  const stamp = raw ? Date.parse(raw) : (Number(session.mtime || 0) ? Number(session.mtime) * 1000 : 0);
  if (!stamp || Number.isNaN(stamp)) return '';
  const now = Date.now();
  const diff = Math.max(0, now - stamp);
  const minute = 60 * 1000;
  const hour = 60 * minute;
  const day = 24 * hour;
  if (diff < hour) return `${Math.max(1, Math.floor(diff / minute))} 分钟前`;
  if (diff < day) return `${Math.floor(diff / hour)} 小时前`;
  const date = new Date(stamp);
  return `${date.getMonth() + 1}/${date.getDate()}`;
}

function _taskStatusLabel(status: string): string {
  const normalized = String(status || '').trim().toLowerCase();
  if (normalized === 'completed') return '已完成';
  if (normalized === 'running') return '进行中';
  if (normalized === 'failed') return '失败';
  if (normalized === 'cancelled') return '已取消';
  return '任务';
}

function _normalizeSession(raw: unknown): AiSessionPreview | null {
  if (typeof raw === 'string') {
    const id = _normalizeSessionId(raw);
    return id ? { id, title: _displaySessionName(id), preview: '' } : null;
  }
  if (!raw || typeof raw !== 'object') return null;
  const record = raw as Record<string, any>;
  const id = _normalizeSessionId(record.id || record.session || record.name);
  if (!id) return null;
  return {
    id,
    title: String(record.title || '').trim() || _displaySessionName(id),
    preview: String(record.preview || '').trim(),
    message_count: Number(record.message_count || record.count || 0),
    last_role: String(record.last_role || '').trim(),
    updated_at: String(record.updated_at || '').trim(),
    mtime: Number(record.mtime || 0),
    task_count: Number(record.task_count || 0),
    has_task_flow: Boolean(record.has_task_flow || Number(record.task_count || 0)),
    latest_task_status: String(record.latest_task_status || '').trim(),
    latest_task_id: String(record.latest_task_id || '').trim(),
    latest_task_run_id: String(record.latest_task_run_id || '').trim(),
  };
}

function _activeSessionMeta(): AiSessionPreview | null {
  const id = _normalizeSessionId(_activeAiSessionId);
  return _sessions.find((session) => session.id === id) || (id ? { id, title: _displaySessionName(id) } : null);
}

function _focusComposer(): void {
  const input = $('wa-user-input') as HTMLTextAreaElement | null;
  if (!input) return;
  try {
    input.focus();
    const len = input.value.length;
    input.setSelectionRange(len, len);
  } catch (_) { /* noop */ }
}

function _sessionListInput(): HTMLTextAreaElement | null {
  return $('wa-session-list-input') as HTMLTextAreaElement | null;
}

function _resizeTextarea(input: HTMLTextAreaElement | null, maxHeight: number): void {
  if (!input) return;
  input.style.height = 'auto';
  input.style.height = Math.min(input.scrollHeight, maxHeight) + 'px';
  input.style.overflowY = input.scrollHeight > maxHeight ? 'auto' : 'hidden';
}

function _resizeSessionListComposer(): void {
  _resizeTextarea(_sessionListInput(), 220);
}

function _syncSessionListSendState(): void {
  const input = _sessionListInput();
  const button = $('wa-session-list-send') as HTMLButtonElement | null;
  if (!button) return;
  button.disabled = !input || input.disabled || !input.value.trim();
}

function _closeSkillLibrary(): void {
  const WA = (window as any).WA || {};
  if (typeof WA.closeSkillLibrary === 'function') {
    try {
      WA.closeSkillLibrary();
      return;
    } catch (_) { /* noop */ }
  }
  const library = $('wa-skill-library');
  if (library) {
    library.classList.remove('open');
    library.innerHTML = '';
  }
}

function _setActivityActive(id: string): void {
  document.querySelectorAll('.activity-btn').forEach((button) => button.classList.remove('active'));
  const target = document.getElementById(id);
  if (target) target.classList.add('active');
}

function _setChatHeader(sessionId?: string): void {
  const id = _normalizeSessionId(sessionId || _activeAiSessionId);
  const meta = _sessions.find((session) => session.id === id) || (id ? { id, title: _displaySessionName(id) } : null);
  const title = $('wa-ai-chat-title');
  const subtitle = $('wa-ai-chat-subtitle');
  if (title) title.textContent = _sessionTitle(meta);
  if (subtitle) {
    const count = Number(meta && meta.message_count || 0);
    const taskCount = Number(meta && meta.task_count || 0);
    const parts = [
      count ? `${count} 条消息` : '',
      taskCount ? `${taskCount} 个任务` : '',
    ].filter(Boolean);
    subtitle.textContent = parts.length ? parts.join(' · ') : '新对话 · 直接输入问题或附加文件';
  }
}

function _renderLoading(): void {
  const list = $('wa-ai-session-list');
  if (!list) return;
  list.innerHTML = '<div class="wa-ai-session-state">正在读取对话...</div>';
}

function _renderEmpty(message = '暂无对话与任务'): void {
  const list = $('wa-ai-session-list');
  if (!list) return;
  list.innerHTML = `
    <div class="wa-ai-session-empty">
      <strong>${_escHtml(message)}</strong>
      <span>在底部输入即可开始新对话；附加文件后会进入文件任务流程。</span>
    </div>`;
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
    const title = _sessionTitle(session);
    const preview = session.preview || '暂无消息';
    const time = _formatSessionTime(session);
    const count = Number(session.message_count || 0);
    const countText = count ? `${count} 条消息` : '空会话';
    const taskCount = Number(session.task_count || 0);
    const hasTaskFlow = Boolean(session.has_task_flow || taskCount);
    const taskStatus = String(session.latest_task_status || '').trim().toLowerCase();
    const taskBadge = hasTaskFlow
      ? `<span class="wa-ai-session-task-badge" data-status="${_escHtml(taskStatus || 'task')}">${_escHtml(taskCount > 1 ? `任务 ${taskCount} · ${_taskStatusLabel(taskStatus)}` : _taskStatusLabel(taskStatus))}</span>`
      : '';
    return `
      <div role="button" tabindex="0" class="wa-ai-session-item${hasTaskFlow ? ' has-task-flow' : ''}${active}" data-ai-session-id="${_escHtml(session.id)}" data-task-count="${_escHtml(String(taskCount))}" data-latest-task-status="${_escHtml(taskStatus)}" title="${_escHtml(title)}">
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
  _setChatHeader();
}

function _openLatestTaskFlowForSession(sessionId: string): void {
  const session = _sessions.find((item) => item.id === _normalizeSessionId(sessionId));
  const taskId = String(session && session.latest_task_id || '').trim();
  if (!taskId) return;
  _syncHistoricalTaskLiveProgress(session);
  const WA = (window as any).WA || {};
  if (typeof WA.openTaskWorkbenchForCurrentRun !== 'function') return;
  window.setTimeout(() => {
    WA.openTaskWorkbenchForCurrentRun({
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
  const statusText = _taskStatusLabel(status);
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
  if (valueEl) valueEl.textContent = status === 'running' ? '继续观察步骤' : '查看下方步骤';
  if (fillEl) fillEl.style.width = status === 'running' ? '55%' : '100%';
}

function _showChatView(): void {
  _closeSkillLibrary();
  _setActivityActive('navAiSessionsBtn');
  const listView = $('wa-ai-session-list-view');
  const chatView = $('wa-ai-chat-view');
  if (listView) listView.hidden = true;
  if (chatView) chatView.hidden = false;
  _setChatHeader();
}

export function showAiSessionList(): void {
  _closeSkillLibrary();
  _setActivityActive('navAiSessionsBtn');
  const listView = $('wa-ai-session-list-view');
  const chatView = $('wa-ai-chat-view');
  if (chatView) chatView.hidden = true;
  if (listView) listView.hidden = false;
  refreshAiSessions({ silent: true }).catch(() => {});
}

export async function refreshAiSessions(options: RefreshOptions = {}): Promise<AiSessionPreview[]> {
  if (!options.silent) _closeSkillLibrary();
  if (_refreshPromise) return _refreshPromise;
  const list = $('wa-ai-session-list');
  if (list && (!options.silent || !list.children.length)) _renderLoading();
  _refreshPromise = fetch('/api/sessions?preview=1', { cache: 'no-store' })
    .then(async (response) => {
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json().catch(() => null);
      const raw = data && Array.isArray(data.sessions) ? data.sessions : [];
      _sessions = raw.map(_normalizeSession).filter(Boolean) as AiSessionPreview[];
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
    });
  return _refreshPromise;
}

export async function openAiSession(sessionId: string, options: RefreshOptions & { force?: boolean } = {}): Promise<any> {
  const normalized = _normalizeSessionId(sessionId);
  if (!normalized) return null;
  _activeAiSessionId = normalized;
  _showChatView();
  _renderSessions();

  const WA = (window as any).WA || {};
  if (typeof WA.useHostSession === 'function') {
    const opened = await WA.useHostSession(normalized, { force: options.force !== false });
    _openLatestTaskFlowForSession(normalized);
    return opened;
  }
  _openLatestTaskFlowForSession(normalized);
  return null;
}

export async function deleteAiSession(sessionId: string): Promise<boolean> {
  const normalized = _normalizeSessionId(sessionId);
  if (!normalized) return false;
  const title = _sessionTitle(_sessions.find((session) => session.id === normalized) || { id: normalized });
  if (!window.confirm(`确认删除对话「${title}」？此操作不可撤销。`)) return false;
  try {
    const response = await _csrfFetch(`/api/sessions/${encodeURIComponent(normalized)}`, { method: 'DELETE' });
    const data = await response.json().catch(() => null);
    if (!response.ok || !data || data.success === false) {
      throw new Error(data && data.error ? data.error : '删除对话失败');
    }
    const wasActive = normalized === _normalizeSessionId(_activeAiSessionId);
    _sessions = _sessions.filter((session) => session.id !== normalized);
    if (wasActive) {
      const next = _sessions[0];
      if (next) {
        _activeAiSessionId = next.id;
        const WA = (window as any).WA || {};
        if (typeof WA.useHostSession === 'function') {
          await WA.useHostSession(next.id, { force: true });
        }
      } else {
        _activeAiSessionId = '';
        const runtime = (window as any)._waConversationRuntime;
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

async function _createAiSessionRecord(): Promise<string> {
  const now = new Date();
  const pad = (value: number) => String(value).padStart(2, '0');
  const name = `对话_${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}_${pad(now.getHours())}${pad(now.getMinutes())}`;
  const response = await _csrfFetch('/api/sessions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  });
  const data = await response.json().catch(() => null);
  if (!response.ok || !data || data.success === false) {
    throw new Error(data && data.error ? data.error : '创建对话失败');
  }
  return _normalizeSessionId(data.session || name) || name;
}

export async function newAiSession(options: NewSessionOptions = {}): Promise<any> {
  _closeSkillLibrary();
  try {
    const sessionId = await _createAiSessionRecord();
    await refreshAiSessions({ silent: true });
    const opened = await openAiSession(sessionId, { force: true });
    if (options.toast !== false) showToast('新对话已创建，直接输入问题或附加文件即可开始。', 'success');
    if (options.focus !== false) _focusComposer();
    return opened;
  } catch (error: any) {
    showToast(error && error.message ? error.message : '创建对话失败', 'error');
    return null;
  }
}

export async function sendSessionListComposer(): Promise<any> {
  const listInput = _sessionListInput();
  const text = String(listInput && listInput.value || '').trim();
  if (!listInput || !text) {
    if (listInput) listInput.focus();
    _syncSessionListSendState();
    return null;
  }

  const sendButton = $('wa-session-list-send') as HTMLButtonElement | null;
  listInput.disabled = true;
  if (sendButton) sendButton.disabled = true;

  try {
    const sessionId = await _createAiSessionRecord();
    await refreshAiSessions({ silent: true });
    await openAiSession(sessionId, { force: true });

    const chatInput = $('wa-user-input') as HTMLTextAreaElement | null;
    if (!chatInput) throw new Error('对话输入框未就绪');
    chatInput.value = text;
    _resizeTextarea(chatInput, 360);
    chatInput.dispatchEvent(new Event('input', { bubbles: true }));

    const WA = (window as any).WA || {};
    if (typeof WA.sendMessage !== 'function') throw new Error('模型发送通路未就绪');
    WA.sendMessage();

    listInput.value = '';
    _resizeSessionListComposer();
    return sessionId;
  } catch (error: any) {
    showToast(error && error.message ? error.message : '新对话发送失败', 'error');
    return null;
  } finally {
    listInput.disabled = false;
    _syncSessionListSendState();
  }
}

export function handleSessionListComposerKeydown(event: KeyboardEvent): void {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    sendSessionListComposer().catch(() => {});
    return;
  }
  window.setTimeout(() => {
    _resizeSessionListComposer();
    _syncSessionListSendState();
  }, 0);
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
  const listInput = _sessionListInput();
  if (listInput) {
    listInput.addEventListener('input', () => {
      _resizeSessionListComposer();
      _syncSessionListSendState();
    });
    _resizeSessionListComposer();
    _syncSessionListSendState();
  }
}

export function syncAiSessionSelection(sessionId: string, options: { showChat?: boolean } = {}): void {
  const normalized = _normalizeSessionId(sessionId);
  if (!normalized) return;
  _activeAiSessionId = normalized;
  if (options.showChat !== false) _showChatView();
  else _setChatHeader(normalized);
  _renderSessions();
}

function _initAiSessionBrowser(): void {
  if (!$('wa-ai-session-list-view')) return;
  _bindAiSessionBrowser();
  _setChatHeader(_activeAiSessionId);
  refreshAiSessions({ silent: true }).catch(() => {});
}

if (typeof window !== 'undefined') {
  (window as any).WA = (window as any).WA || {};
  (window as any).WA.showAiSessionList = showAiSessionList;
  (window as any).WA.refreshAiSessions = refreshAiSessions;
  (window as any).WA.openAiSession = openAiSession;
  (window as any).WA.deleteAiSession = deleteAiSession;
  (window as any).WA.newAiSession = newAiSession;
  (window as any).WA.sendSessionListComposer = sendSessionListComposer;
  (window as any).WA.handleSessionListComposerKeydown = handleSessionListComposerKeydown;
  (window as any).WA._syncAiSessionSelection = syncAiSessionSelection;
  (window as any).WA._activeAiSessionMeta = _activeSessionMeta;
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', _initAiSessionBrowser);
} else {
  _initAiSessionBrowser();
}
