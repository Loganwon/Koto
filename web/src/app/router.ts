/**
 * Koto Router Module — navigation, view switching, welcome screen, workspace, projects
 */

export function goToWelcome(): void {
  if (typeof (window as any).switchToChatView === 'function') (window as any).switchToChatView();
  const currentSession = (window as any).currentSession;
  if (currentSession && typeof (window as any).isSessionGenerating === 'function' && (window as any).isSessionGenerating(currentSession)) {
    const controller = (window as any).getSessionAbortController?.(currentSession);
    if (controller) {
      console.log(`[CLEANUP] Aborting previous session ${currentSession}`);
      controller.abort();
    }
    if (typeof (window as any).setSessionGenerating === 'function') {
      (window as any).setSessionGenerating(currentSession, false);
    }
    const sessionDomCache = (window as any).sessionDomCache;
    if (sessionDomCache) sessionDomCache.delete(currentSession);
  }

  const sendBtn = document.getElementById('sendBtn');
  if (sendBtn) {
    sendBtn.classList.remove('generating');
    (sendBtn as HTMLButtonElement).disabled = false;
    sendBtn.title = '发送';
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

  const sb = document.getElementById('sendBtn') as HTMLButtonElement | null;
  if (sb) {
    if (typeof (window as any).isSessionGenerating === 'function' && (window as any).isSessionGenerating(sessionName)) {
      sb.classList.add('generating');
      sb.disabled = false;
      sb.title = '停止生成';
    } else {
      sb.classList.remove('generating');
      sb.disabled = false;
      sb.title = '发送';
    }
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
  if (panel) panel.style.display = 'flex';
  _renderProjectsList();
}

export function closeProjectsManager(): void {
  const panel = document.getElementById('projectsManagerModal');
  if (panel) panel.style.display = 'none';
}

function _renderProjectsList(): void {
  const list = document.getElementById('projectsList');
  if (!list) return;
  const options = typeof (window as any).getProjectOptions === 'function' ? (window as any).getProjectOptions() : [];
  const currentProject = (window as any).currentProject || 'default';
  list.innerHTML = options.map((p: { key: string; label: string }) => `
    <div class="project-entry">
      <input type="text" value="${(window as any).escapeHtml?.(p.label) || p.label}" data-key="${(window as any).escapeHtml?.(p.key) || p.key}" onchange="_saveProjectLabel(this)" placeholder="项目名称">
      ${p.key !== 'default' ? `<button onclick="deleteProjectEntry('${(window as any).escapeHtml?.(p.key) || p.key}')" class="ghost-btn" title="删除项目">✕</button>` : '<span style="font-size:11px;opacity:.5;">默认</span>'}
    </div>`).join('');
}

function _saveProjectLabel(input: HTMLInputElement): void {
  const key = input.dataset.key;
  const label = input.value.trim();
  if (!key || !label) return;
  const options = typeof (window as any).getProjectOptions === 'function' ? (window as any).getProjectOptions() : [];
  const entry = options.find((p: { key: string }) => p.key === key);
  if (entry) entry.label = label;
  if (typeof (window as any).saveProjectOptions === 'function') (window as any).saveProjectOptions(options);
  if (typeof (window as any).initProjectSelector === 'function') (window as any).initProjectSelector();
}

export function deleteProjectEntry(key: string): void {
  if (key === 'default') return;
  const options = typeof (window as any).getProjectOptions === 'function' ? (window as any).getProjectOptions() : [];
  const filtered = options.filter((p: { key: string }) => p.key !== key);
  if (typeof (window as any).saveProjectOptions === 'function') (window as any).saveProjectOptions(filtered);
  const currentProject = (window as any).currentProject;
  if (currentProject === key) {
    (window as any).currentProject = 'default';
    localStorage.setItem('koto.currentProject', 'default');
  }
  if (typeof (window as any).initProjectSelector === 'function') (window as any).initProjectSelector();
  _renderProjectsList();
}

export function addProjectEntry(): void {
  const newKey = 'proj_' + Date.now().toString(36);
  const options = typeof (window as any).getProjectOptions === 'function' ? (window as any).getProjectOptions() : [];
  options.push({ key: newKey, label: '新项目' });
  if (typeof (window as any).saveProjectOptions === 'function') (window as any).saveProjectOptions(options);
  if (typeof (window as any).initProjectSelector === 'function') (window as any).initProjectSelector();
  _renderProjectsList();
}

// ── Workspace ──
export function openWorkspaceFolder(): void {
  toggleWorkspace();
  if (typeof (window as any).showNotification === 'function') (window as any).showNotification('已展开 Koto 工作区', 'info', 2000);
}

export function toggleWorkspace(): void {
  const panel = document.getElementById('workspacePanel');
  if (!panel) return;
  panel.classList.toggle('active');
  if (panel.classList.contains('active')) {
    loadWorkspaceFiles();
  }
}

export async function loadWorkspaceFiles(): Promise<void> {
  try {
    const response = await fetch('/api/workspace');
    const data = await response.json();
    const container = document.getElementById('workspaceFiles');
    if (!container) return;
    if (data.files.length === 0) {
      container.innerHTML = `<div style="text-align: center; padding: 20px; color: var(--text-muted);"><p>No files yet</p></div>`;
      return;
    }
    container.innerHTML = data.files.map((file: string) => `
      <a href="/api/workspace/${file}" target="_blank" class="workspace-file">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
          <polyline points="14 2 14 8 20 8"></polyline>
        </svg>
        <span>${(window as any).escapeHtml?.(file) || file}</span>
      </a>`).join('');
  } catch (error) {
    console.error('Failed to load workspace files:', error);
  }
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
(window as any).openWorkspaceFolder = openWorkspaceFolder;
(window as any).toggleWorkspace = toggleWorkspace;
(window as any).loadWorkspaceFiles = loadWorkspaceFiles;
