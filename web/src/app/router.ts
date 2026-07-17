/**
 * Koto Router Module — navigation, view switching, welcome screen, workspace, projects
 */

import {
  getCurrentProject,
  getProjectOptions,
  initProjectSelector,
  saveProjectOptions,
  setCurrentProject,
} from './session-bridge';

export function goToWelcome(): void {
  if (typeof (window as any).switchToChatView === 'function') (window as any).switchToChatView();
  const currentSession = (window as any).currentSession;
  if (currentSession && typeof (window as any).isSessionGenerating === 'function' && (window as any).isSessionGenerating(currentSession)) {
    const controller = (window as any).getSessionAbortController?.(currentSession);
    if (controller) {
      // Aborting previous session
      controller.abort();
    }
    if (typeof (window as any).setSessionGenerating === 'function') {
      (window as any).setSessionGenerating(currentSession, false);
    }
    const sessionDomCache = (window as any).sessionDomCache;
    if (sessionDomCache) sessionDomCache.delete(currentSession);
  }

  (window as any).currentSession = null;
  (window as any).isScrollLocked = false;
  const chatTitle = document.getElementById('chatTitle');
  if (chatTitle) chatTitle.textContent = 'Koto';

  document.querySelectorAll('.session-item').forEach((item: Element) => {
    item.classList.remove('active');
  });

  const container = document.getElementById('chatMessages');
  const ws = document.getElementById('welcomeScreen');
  if (ws) ws.style.display = 'block';
  if (container) container.querySelectorAll('.message, .chat-date-sep').forEach((msg: Element) => msg.remove());

  renderWelcomeScreen();

  (window as any).lockedTaskType = null;
  document.querySelectorAll('.capability').forEach((c: Element) => c.classList.remove('selected'));
  if (typeof (window as any).updateTaskIndicator === 'function') (window as any).updateTaskIndicator(null);
}

export function renderWelcomeScreen(): void {
  const h = new Date().getHours();
  const greeting = h < 5 ? '夜深了，还在呢🌙' : h < 12 ? '早上好，有什么需要帮忙？☀️' : h < 18 ? '下午好，有什么需要帮忙？' : '晚上好，有什么需要帮忙？🌟';
  const greetEl = document.getElementById('welcomeGreeting');
  if (greetEl) greetEl.textContent = greeting;
}

export async function selectSession(sessionName: string): Promise<void> {
  const currentSession = (window as any).currentSession;
  if (currentSession && currentSession !== sessionName && typeof (window as any).isSessionGenerating === 'function' && (window as any).isSessionGenerating(currentSession)) {
    const chatContainer = document.getElementById('chatMessages');
    const frag = document.createDocumentFragment();
    if (chatContainer) {
      chatContainer.querySelectorAll('.message, .chat-date-sep').forEach((node: Element) => frag.appendChild(node));
    }
    const sessionDomCache = (window as any).sessionDomCache;
    if (sessionDomCache) sessionDomCache.set(currentSession, frag);
  }

  const workspaceView = document.getElementById('workspaceView');
  const workspaceOpen = !!(workspaceView && workspaceView.style.display !== 'none');
  if (!workspaceOpen && typeof (window as any).switchToChatView === 'function') (window as any).switchToChatView();

  (window as any).currentSession = sessionName;
  if (typeof (window as any)._syncSessionSelectionUi === 'function') (window as any)._syncSessionSelectionUi(sessionName);
  if (workspaceOpen && (window as any).WA && typeof (window as any).WA.useHostSession === 'function') {
    (window as any).WA.useHostSession(sessionName, { force: true });
  }

  const chatContainer = document.getElementById('chatMessages');
  if (typeof (window as any).isSessionGenerating === 'function' && (window as any).isSessionGenerating(sessionName)) {
    const sessionDomCache = (window as any).sessionDomCache;
    if (sessionDomCache && sessionDomCache.has(sessionName)) {
      const frag = sessionDomCache.get(sessionName);
      sessionDomCache.delete(sessionName);
      if (chatContainer) {
        chatContainer.querySelectorAll('.message, .chat-date-sep').forEach((el: Element) => el.remove());
      }
      const ws = document.getElementById('welcomeScreen');
      if (ws) ws.style.display = 'none';
      if (chatContainer) chatContainer.appendChild(frag);
      scrollToBottomForce();
    }
  } else {
    try {
      const response = await fetch(`/api/sessions/${encodeURIComponent(sessionName)}`);
      const data = await response.json();
      if (typeof (window as any).renderChatHistory === 'function') {
        (window as any).renderChatHistory(data.history);
      }
    } catch (error) {
      console.error('Failed to load session:', error);
    }
  }
}

export function scrollToBottom(): void {
  const isScrollLocked = (window as any).isScrollLocked;
  if (isScrollLocked) return;
  const container = document.getElementById('chatMessages');
  if (container) container.scrollTop = container.scrollHeight;
}

export function scrollToBottomForce(): void {
  (window as any).isScrollLocked = false;
  const container = document.getElementById('chatMessages');
  if (container) {
    container.scrollTop = container.scrollHeight;
    updateBackToBottomBtn();
  }
}

export function initScrollBehavior(): void {
  const container = document.getElementById('chatMessages');
  if (!container) return;
  container.addEventListener('scroll', () => {
    const distFromBottom = container.scrollHeight - container.scrollTop - container.clientHeight;
    (window as any).isScrollLocked = distFromBottom > 80;
    updateBackToBottomBtn();
  });
}

export function updateBackToBottomBtn(): void {
  const btn = document.getElementById('backToBottomBtn');
  if (!btn) return;
  const container = document.getElementById('chatMessages');
  if (!container) return;
  const distFromBottom = container.scrollHeight - container.scrollTop - container.clientHeight;
  const currentSession = (window as any).currentSession;
  const isGenerating = currentSession && typeof (window as any).isSessionGenerating === 'function' && (window as any).isSessionGenerating(currentSession);
  btn.style.display = (distFromBottom > 80 && isGenerating) ? 'flex' : 'none';
}

// ── Projects Manager ──
export function openProjectsManager(): void {
  const panel = document.getElementById('projectsManagerModal');
  if (!panel) return;
  panel.classList.add('active');
  panel.setAttribute('aria-hidden', 'false');
  _renderProjectsList();
  requestAnimationFrame(() => {
    (document.getElementById('newProjectNameInput') as HTMLInputElement | null)?.focus();
  });
}

export function closeProjectsManager(): void {
  const panel = document.getElementById('projectsManagerModal');
  if (!panel) return;
  panel.classList.remove('active');
  panel.setAttribute('aria-hidden', 'true');
}

function _renderProjectsList(): void {
  const list = document.getElementById('projectsManagerList');
  if (!list) return;
  const options = getProjectOptions();
  list.replaceChildren();

  options.forEach((project) => {
    const row = document.createElement('div');
    row.className = 'proj-mgr-item';

    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'proj-mgr-name';
    input.value = project.label;
    input.dataset.key = project.key;
    input.placeholder = '项目名称';
    input.setAttribute('aria-label', `${project.label}项目名称`);
    input.addEventListener('change', () => _saveProjectLabel(input));
    row.appendChild(input);

    if (project.key === 'default') {
      const marker = document.createElement('span');
      marker.className = 'proj-mgr-default';
      marker.textContent = '默认';
      row.appendChild(marker);
    } else {
      const removeButton = document.createElement('button');
      removeButton.type = 'button';
      removeButton.className = 'proj-mgr-del';
      removeButton.title = '删除项目';
      removeButton.setAttribute('aria-label', `删除项目 ${project.label}`);
      removeButton.textContent = '×';
      removeButton.addEventListener('click', () => deleteProjectEntry(project.key));
      row.appendChild(removeButton);
    }

    list.appendChild(row);
  });
}

function _saveProjectLabel(input: HTMLInputElement): void {
  const key = input.dataset.key;
  const label = input.value.trim();
  if (!key || !label) return;
  const options = getProjectOptions();
  const entry = options.find((p: { key: string }) => p.key === key);
  if (entry) entry.label = label;
  saveProjectOptions(options);
  initProjectSelector();
}

export function deleteProjectEntry(key: string): void {
  if (key === 'default') return;
  const options = getProjectOptions();
  const filtered = options.filter((p: { key: string }) => p.key !== key);
  saveProjectOptions(filtered);
  const currentProject = getCurrentProject();
  if (currentProject === key) {
    setCurrentProject('default');
  }
  initProjectSelector();
  _renderProjectsList();
}

export function addProjectEntry(): void {
  const input = document.getElementById('newProjectNameInput') as HTMLInputElement | null;
  const label = input?.value.trim() || '新项目';
  const newKey = 'proj_' + Date.now().toString(36);
  const options = getProjectOptions();
  options.push({ key: newKey, label });
  saveProjectOptions(options);
  initProjectSelector();
  if (input) input.value = '';
  _renderProjectsList();
  input?.focus();
}

// ── Backward compat ──
(window as any).goToWelcome = goToWelcome;
(window as any).renderWelcomeScreen = renderWelcomeScreen;
(window as any).selectSession = selectSession;
(window as any).scrollToBottom = scrollToBottom;
(window as any).scrollToBottomForce = scrollToBottomForce;
(window as any).initScrollBehavior = initScrollBehavior;
(window as any).updateBackToBottomBtn = updateBackToBottomBtn;
(window as any).openProjectsManager = openProjectsManager;
(window as any).closeProjectsManager = closeProjectsManager;
(window as any).deleteProjectEntry = deleteProjectEntry;
(window as any).addProjectEntry = addProjectEntry;
