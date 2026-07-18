/**
 * Koto Session Bridge Module — session management, API bridge, project management
 */

import { csrfFetch } from '../shared/csrf';

export interface KotoSessionBridge {
  getSession(): string;
  setSession(sessionName: string | null): void;
  refreshSessions(): Promise<void>;
}

// ── State ──
let currentSession: string | null = null;
let currentProject: string = localStorage.getItem('koto.currentProject') || 'default';

const _DEFAULT_PROJECT_OPTIONS: Array<{ key: string; label: string }> = [
  { key: 'default', label: '默认项目' },
  { key: 'work', label: '工作' },
  { key: 'study', label: '学习' },
  { key: 'life', label: '生活' }
];

// ── Session state management ──
const sessionStates = new Map<string, { isGenerating: boolean; abortController: AbortController | null; taskId?: string | null }>();
const sessionDomCache = new Map<string, DocumentFragment>();
const isScrollLocked = false;

export { currentSession, sessionStates, sessionDomCache, isScrollLocked };
(window as any).currentSession = currentSession;

export function getProjectOptions(): Array<{ key: string; label: string }> {
  try {
    const stored = localStorage.getItem('koto.projectOptions');
    if (stored) {
      const parsed = JSON.parse(stored);
      if (Array.isArray(parsed) && parsed.length > 0) {
        if (!parsed.some((p: { key: string }) => p.key === 'default')) {
          parsed.unshift({ key: 'default', label: '默认项目' });
        }
        return parsed;
      }
    }
  } catch (e) { /* ignore */ }
  return _DEFAULT_PROJECT_OPTIONS.map(p => ({ ...p }));
}

export function saveProjectOptions(opts: Array<{ key: string; label: string }>): void {
  localStorage.setItem('koto.projectOptions', JSON.stringify(opts));
}

export function getCurrentProject(): string {
  return currentProject;
}

export function setCurrentProject(projectKey: string): void {
  currentProject = String(projectKey || 'default');
  localStorage.setItem('koto.currentProject', currentProject);
  (window as any).currentProject = currentProject;
}

export function getProjectSessionPrefix(projectKey: string = currentProject): string {
  return projectKey === 'default' ? '' : `proj_${projectKey}__`;
}

export function listProjectSessions(allSessions: string[]): string[] {
  const list = Array.isArray(allSessions) ? allSessions : [];
  const prefix = getProjectSessionPrefix();
  if (!prefix) {
    return list.filter((name: string) => !/^proj_[a-z0-9_-]+__/.test(String(name || '')));
  }
  return list.filter((name: string) => String(name || '').startsWith(prefix));
}

export function toProjectSessionName(rawName: string, projectKey: string = currentProject): string {
  const clean = String(rawName || '').trim();
  if (!clean) return clean;
  const prefix = getProjectSessionPrefix(projectKey);
  return prefix ? `${prefix}${clean}` : clean;
}

export function toSessionDisplayName(sessionName: string): string {
  const text = String(sessionName || '');
  const prefix = getProjectSessionPrefix();
  if (prefix && text.startsWith(prefix)) return text.slice(prefix.length);
  return text;
}

// ── Session state getters/setters ──
export function getSessionState(sessionName: string): { isGenerating: boolean; abortController: AbortController | null; taskId?: string | null } {
  if (!sessionStates.has(sessionName)) {
    sessionStates.set(sessionName, { isGenerating: false, abortController: null });
  }
  return sessionStates.get(sessionName)!;
}

export function setSessionGenerating(sessionName: string, isGenerating: boolean): void {
  const state = getSessionState(sessionName);
  state.isGenerating = isGenerating;
}

export function isSessionGenerating(sessionName: string): boolean {
  const state = getSessionState(sessionName);
  return state.isGenerating;
}

export function setSessionAbortController(sessionName: string, controller: AbortController | null): void {
  const state = getSessionState(sessionName);
  state.abortController = controller;
}

export function getSessionAbortController(sessionName: string): AbortController | null {
  const state = getSessionState(sessionName);
  return state.abortController;
}

export function setSessionTaskId(sessionName: string, taskId: string | null): void {
  const state = getSessionState(sessionName);
  state.taskId = taskId || null;
}

export function getSessionTaskId(sessionName: string): string | null {
  const state = getSessionState(sessionName);
  return state.taskId || null;
}

function isSessionLoadInterruption(error: unknown): boolean {
  const text = String(error instanceof Error ? error.message : error || '').trim();
  return /failed to fetch|networkerror|aborted|load failed/i.test(text);
}

// ── Session list / rendering ──
export async function loadSessions(): Promise<void> {
  try {
    const response = await fetch('/api/sessions?preview=1');
    const data = await response.json();
    const raw = data.sessions || [];
    (window as any)._allSessions = raw.map((s: string | { id: string }) => typeof s === 'string' ? s : s.id);
    (window as any)._sessionPreviews = {};
    raw.forEach((s: string | { id: string; preview?: string; mtime?: number }) => {
      if (typeof s === 'object' && s.id) {
        (window as any)._sessionPreviews[s.id] = { preview: s.preview || '', mtime: s.mtime || 0 };
      }
    });
    (window as any)._projectSessions = listProjectSessions((window as any)._allSessions);
    const q = document.getElementById('sessionSearchInput') as HTMLInputElement | null;
    const query = q ? q.value.trim() : '';
    renderSessions(query
      ? (window as any)._projectSessions.filter((s: string) => toSessionDisplayName(s).toLowerCase().includes(query.toLowerCase()))
      : (window as any)._projectSessions);
  } catch (error) {
    if (isSessionLoadInterruption(error)) {
      console.debug('Session list refresh interrupted:', error);
      return;
    }
    console.error('Failed to load sessions:', error);
  }
}

export function filterSessions(query: string): void {
  const all = (window as any)._projectSessions || [];
  const filtered = query.trim()
    ? all.filter((s: string) => toSessionDisplayName(s).toLowerCase().includes(query.trim().toLowerCase()))
    : all;
  renderSessions(filtered);
}

export function renderSessions(sessions: string[]): void {
  const container = document.getElementById('sessionsList');
  if (!container) return;

  if (sessions.length === 0) {
    container.innerHTML = `
      <div style="text-align: center; padding: 20px; color: var(--text-muted);">
        <p>\u6682\u65e0\u5bf9\u8bdd</p>
        <p style="font-size: 12px; margin-top: 8px;">\u70b9\u51fb\u201c+ \u65b0\u5bf9\u8bdd\u201d\u5f00\u59cb</p>
      </div>`;
    return;
  }

  container.innerHTML = sessions.map((session: string) => {
    const meta = ((window as any)._sessionPreviews || {})[session] || {};
    const preview = meta.preview || '';
    return `
      <div class="session-item ${currentSession === session ? 'active' : ''}"
           data-session="${(window as any).escapeHtml(session)}">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
        </svg>
        <div class="session-item-body">
          <div class="session-item-top">
            <span class="session-name">${(window as any).escapeHtml(toSessionDisplayName(session))}</span>
          </div>
          ${preview ? `<span class="session-preview">${(window as any).escapeHtml(preview)}</span>` : ''}
        </div>
        <button class="session-rename-btn" data-session="${(window as any).escapeHtml(session)}" onclick="renameSession(this.dataset.session, event)" title="\u91cd\u547d\u540d\u5bf9\u8bdd">\u270e</button>
        <button class="session-delete-btn" data-session="${(window as any).escapeHtml(session)}" onclick="deleteSession(this.dataset.session, event)" title="\u5220\u9664\u5bf9\u8bdd">\u2715</button>
      </div>`;
  }).join('');

  container.querySelectorAll('.session-item').forEach((el: Element) => {
    const htmlEl = el as HTMLElement;
    el.addEventListener('click', function(this: HTMLElement, e: Event) {
      if ((e.target as HTMLElement)?.closest('.session-rename-btn') || (e.target as HTMLElement)?.closest('.session-delete-btn')) return;
      if (el.querySelector('.session-name-input')) return;
      if (typeof (window as any).selectSession === 'function') {
        (window as any).selectSession(htmlEl.dataset.session);
      }
    });
  });
}

export function _syncSessionSelectionUi(sessionName: string): void {
  const chatTitle = document.getElementById('chatTitle');
  if (chatTitle) chatTitle.textContent = toSessionDisplayName(sessionName);
  document.querySelectorAll('.session-item').forEach((item: Element) => {
    item.classList.remove('active');
    if ((item as HTMLElement).dataset.session === sessionName) {
      item.classList.add('active');
    }
  });
}

// ── Session CRUD ──
export async function createNewSession(name: string | null = null): Promise<void> {
  if (!name) {
    if (typeof (window as any).showNewSessionModal === 'function') {
      (window as any).showNewSessionModal();
    }
    return;
  }
  try {
    const projectName = toProjectSessionName(name);
    const response = await csrfFetch('/api/sessions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: projectName })
    });
    if (response.ok) {
      const data = await response.json();
      if (data.success) {
        currentSession = data.session;
        const chatTitle = document.getElementById('chatTitle');
        if (chatTitle) chatTitle.textContent = toSessionDisplayName(data.session);
        loadSessions();
        const container = document.getElementById('chatMessages');
        if (container) container.innerHTML = '';
      }
    }
  } catch (error) {
    console.error('Failed to create session:', error);
  }
}

export async function confirmNewSession(): Promise<void> {
  const nameInput = document.getElementById('newSessionName') as HTMLInputElement | null;
  const name = nameInput?.value.trim();
  if (!name) return;
  try {
    const response = await csrfFetch('/api/sessions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: toProjectSessionName(name) })
    });
    const data = await response.json();
    if (data.success) {
      if (typeof (window as any).closeModal === 'function') (window as any).closeModal();
      await loadSessions();
      if (typeof (window as any).selectSession === 'function') (window as any).selectSession(data.session);
    }
  } catch (error) {
    console.error('Failed to create session:', error);
  }
}

export function showNewSessionModal(): void {
  if (typeof (window as any).switchToChatView === 'function') (window as any).switchToChatView();
  const modal = document.getElementById('newSessionModal');
  if (modal) modal.classList.add('active');
  const input = document.getElementById('newSessionName') as HTMLInputElement | null;
  if (input) { input.value = ''; input.focus(); }
}

export function closeModal(): void {
  const modal = document.getElementById('newSessionModal');
  if (modal) modal.classList.remove('active');
}

export async function deleteSession(sessionName: string, event?: Event): Promise<void> {
  if (event) event.stopPropagation();
  if (!sessionName) return;
  if (!confirm(`确认删除对话 "${toSessionDisplayName(sessionName)}"？`)) return;
  if (isSessionGenerating(sessionName)) {
    const controller = getSessionAbortController(sessionName);
    if (controller) controller.abort();
    setSessionGenerating(sessionName, false);
  }
  try {
    const response = await csrfFetch(`/api/sessions/${encodeURIComponent(sessionName)}`, { method: 'DELETE' });
    const data = await response.json();
    if (data.success) {
      document.querySelectorAll('.session-item').forEach((item: Element) => {
        if ((item as HTMLElement).dataset.session === sessionName) item.remove();
      });
      if (currentSession === sessionName) {
        currentSession = null;
        const chatTitle = document.getElementById('chatTitle');
        if (chatTitle) chatTitle.textContent = 'Koto';
        const container = document.getElementById('chatMessages');
        if (container) container.querySelectorAll('.message, .chat-date-sep').forEach((el: Element) => el.remove());
        const ws = document.getElementById('welcomeScreen');
        if (ws) ws.style.display = 'block';
        if (typeof (window as any).renderWelcomeScreen === 'function') (window as any).renderWelcomeScreen();
      }
    }
  } catch (error) {
    console.error('Failed to delete session:', error);
  }
}

export async function deleteCurrentSession(): Promise<void> {
  return deleteSession(currentSession || '', undefined);
}

export async function renameSession(sessionName: string, event?: Event): Promise<void> {
  if (event) event.stopPropagation();
  const item = document.querySelector(`.session-item[data-session="${CSS.escape(sessionName)}"]`) as HTMLElement | null;
  if (!item) return;
  const nameSpan = item.querySelector('.session-name') as HTMLElement | null;
  if (!nameSpan) return;
  const oldName = nameSpan.textContent || '';

  const input = document.createElement('input');
  input.className = 'session-name-input';
  input.value = oldName;
  nameSpan.replaceWith(input);
  input.focus();
  input.select();
  input.addEventListener('click', (e: Event) => e.stopPropagation());

  let committed = false;

  async function commit(): Promise<void> {
    if (committed) return;
    committed = true;
    const newName = input.value.trim();
    const restore = () => {
      const span = document.createElement('span');
      span.className = 'session-name';
      span.textContent = oldName;
      input.replaceWith(span);
    };
    if (!newName || newName === oldName) { restore(); return; }
    const fullNewName = toProjectSessionName(newName);
    try {
      const resp = await csrfFetch(`/api/sessions/${encodeURIComponent(sessionName)}/rename`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ new_name: fullNewName }),
      });
      const data = await resp.json();
      if (data.success) {
        const newSession = data.new_session;
        if (currentSession === sessionName) {
          currentSession = newSession;
          const chatTitle = document.getElementById('chatTitle');
          if (chatTitle) chatTitle.textContent = toSessionDisplayName(newSession);
        }
        document.querySelectorAll('.session-item').forEach((el: Element) => {
          if ((el as HTMLElement).dataset.session === sessionName) {
            (el as HTMLElement).dataset.session = newSession;
            const nameEl = el.querySelector('.session-name');
            if (nameEl) nameEl.textContent = toSessionDisplayName(newSession);
          }
        });
      } else {
        restore();
      }
    } catch (e) {
      restore();
    }
  }

  input.addEventListener('blur', commit);
  input.addEventListener('keydown', (e: KeyboardEvent) => {
    if (e.key === 'Enter') { e.preventDefault(); commit(); }
    if (e.key === 'Escape') { committed = true; input.value = oldName; commit(); }
  });
}

// ── Project selector ──
export function initProjectSelector(): void {
  const select = document.getElementById('projectSelect') as HTMLSelectElement | null;
  if (!select) return;
  const options = getProjectOptions();
  if (!options.some(p => p.key === currentProject)) {
    setCurrentProject('default');
  }
  select.innerHTML = options.map(project =>
    `<option value="${(window as any).escapeHtml(project.key)}">${(window as any).escapeHtml(project.label)}</option>`
  ).join('');
  select.value = currentProject;
  select.onchange = async (e: Event) => {
    setCurrentProject((e.target as HTMLSelectElement).value || 'default');
    if (typeof (window as any).goToWelcome === 'function') (window as any).goToWelcome();
    await loadSessions();
  };
}

export function _isSidebarOverlayMode(): boolean {
  try {
    return window.matchMedia('(max-width: 1200px)').matches;
  } catch (_) {
    return false;
  }
}

export function _syncSidebarState(options: { forceOpenOverlay?: boolean } = {}): void {
  const sidebar = document.getElementById('sidebar');
  if (!sidebar) return;
  const isOverlay = _isSidebarOverlayMode();
  if (isOverlay) {
    sidebar.classList.add('overlay');
    sidebar.classList.remove('expanded');
    if (options.forceOpenOverlay) sidebar.classList.add('open');
  } else {
    sidebar.classList.remove('overlay', 'open');
    sidebar.classList.add('expanded');
  }
}

export function toggleSidebar(): void {
  const sidebar = document.getElementById('sidebar');
  if (!sidebar) return;
  if (_isSidebarOverlayMode()) {
    sidebar.classList.toggle('open');
  } else {
    sidebar.classList.toggle('expanded');
  }
}

export function toggleSidebarSearch(): void {
  const searchBar = document.getElementById('sessionSearchBar');
  if (!searchBar) return;
  const isVisible = searchBar.style.display !== 'none';
  searchBar.style.display = isVisible ? 'none' : 'block';
  if (!isVisible) {
    const input = document.getElementById('sessionSearchInput') as HTMLInputElement | null;
    if (input) input.focus();
  }
}

// ── KotoSessionBridge ──
export const KotoSessionBridge: KotoSessionBridge = {
  getSession() {
    return currentSession || '';
  },
  setSession(sessionName: string | null) {
    currentSession = sessionName || null;
    if (currentSession) _syncSessionSelectionUi(currentSession);
    if ((window as any).WA && typeof (window as any).WA.useHostSession === 'function') {
      (window as any).WA.useHostSession(currentSession || '', { force: true });
    }
  },
  refreshSessions() {
    return typeof loadSessions === 'function' ? loadSessions() : Promise.resolve();
  },
};

// ── Backward compat ──
(window as any).KotoSessionBridge = KotoSessionBridge;
(window as any).loadSessions = loadSessions;
(window as any).filterSessions = filterSessions;
(window as any).renderSessions = renderSessions;
(window as any).createNewSession = createNewSession;
(window as any).confirmNewSession = confirmNewSession;
(window as any).showNewSessionModal = showNewSessionModal;
(window as any).closeModal = closeModal;
(window as any).deleteSession = deleteSession;
(window as any).deleteCurrentSession = deleteCurrentSession;
(window as any).renameSession = renameSession;
(window as any).initProjectSelector = initProjectSelector;
(window as any).toggleSidebar = toggleSidebar;
(window as any).toggleSidebarSearch = toggleSidebarSearch;
(window as any).toSessionDisplayName = toSessionDisplayName;
(window as any).toProjectSessionName = toProjectSessionName;
(window as any).getProjectSessionPrefix = getProjectSessionPrefix;
(window as any).listProjectSessions = listProjectSessions;
(window as any).getProjectOptions = getProjectOptions;
(window as any).saveProjectOptions = saveProjectOptions;
(window as any).getCurrentProject = getCurrentProject;
(window as any).setCurrentProject = setCurrentProject;
(window as any).currentProject = currentProject;
