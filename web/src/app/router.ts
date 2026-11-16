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
import { getFeatureRegistry } from '../shared/feature-registry';
import { getActiveKotoMessageContainer } from '../shared/active-composer';

export function goToWelcome(): void {
  const api = getFeatureRegistry();
  void api.newAiSession?.({ toast: false });
  api.showConversationLayout?.();
}

export function renderWelcomeScreen(): void {
  const title = document.querySelector('#wa-ai-welcome .wa-welcome-title');
  if (title) title.textContent = '今天要完成什么？';
}

export async function selectSession(sessionName: string): Promise<void> {
  const api = getFeatureRegistry();
  if (typeof api.openAiSession === 'function') await api.openAiSession(sessionName, { force: true });
  else await api.useHostSession?.(sessionName, { force: true });
  api.currentSession = sessionName;
}

export function scrollToBottom(): void {
  const isScrollLocked = getFeatureRegistry().isScrollLocked;
  if (isScrollLocked) return;
  const container = getActiveKotoMessageContainer();
  if (container) container.scrollTop = container.scrollHeight;
}

export function scrollToBottomForce(): void {
  getFeatureRegistry().isScrollLocked = false;
  const container = getActiveKotoMessageContainer();
  if (container) {
    container.scrollTop = container.scrollHeight;
    updateBackToBottomBtn();
  }
}

const scrollBehaviorContainers = new WeakSet<HTMLElement>();

export function initScrollBehavior(): void {
  const container = getActiveKotoMessageContainer();
  if (!container || scrollBehaviorContainers.has(container)) return;
  scrollBehaviorContainers.add(container);
  container.addEventListener('scroll', () => {
    const distFromBottom = container.scrollHeight - container.scrollTop - container.clientHeight;
    getFeatureRegistry().isScrollLocked = distFromBottom > 80;
    updateBackToBottomBtn();
  });
}

export function updateBackToBottomBtn(): void {
  const btn = document.getElementById('backToBottomBtn');
  if (!btn) return;
  const container = getActiveKotoMessageContainer();
  if (!container) return;
  const distFromBottom = container.scrollHeight - container.scrollTop - container.clientHeight;
  const currentSession = getFeatureRegistry().currentSession;
  const isGenerating = currentSession && typeof getFeatureRegistry().isSessionGenerating === 'function' && getFeatureRegistry().isSessionGenerating(currentSession);
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
getFeatureRegistry().goToWelcome = goToWelcome;
getFeatureRegistry().renderWelcomeScreen = renderWelcomeScreen;
getFeatureRegistry().selectSession = selectSession;
getFeatureRegistry().scrollToBottom = scrollToBottom;
getFeatureRegistry().scrollToBottomForce = scrollToBottomForce;
getFeatureRegistry().initScrollBehavior = initScrollBehavior;
getFeatureRegistry().updateBackToBottomBtn = updateBackToBottomBtn;
getFeatureRegistry().openProjectsManager = openProjectsManager;
getFeatureRegistry().closeProjectsManager = closeProjectsManager;
getFeatureRegistry().deleteProjectEntry = deleteProjectEntry;
getFeatureRegistry().addProjectEntry = addProjectEntry;
