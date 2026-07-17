/**
 * Settings & Model Management — auto-save toggle, theme, model labels.
 * Workspace model settings and provider controls.
 */

import { publishWorkspaceApi } from '../shared/workspace-api';
import { $, _csrfFetch } from './infrastructure';
import { _normalizeWorkspaceModelMode, state as workspaceState } from './state';

const state: any = workspaceState;

const _SUN_SVG = String((window as any)._SUN_SVG || '');
const _MOON_SVG = String((window as any)._MOON_SVG || '');

function _clearActiveRoute(): void {
  state._activeRoute = null;
}

export interface ModelMeta {
  id: string;
  display?: string;
  name?: string;
  label?: string;
  model?: string;
}

export interface ModelStatus {
  mode: string;
  running?: boolean;
  installed?: boolean;
  cloudProvider?: string;
  modelMap?: Record<string, string>;
  availableModels?: ModelMeta[];
  localModel?: string;
}

export interface SettingsState {
  autoSaveEnabled: boolean;
  theme: 'light' | 'dark';
  modelMode: string;
}

export function toggleSettings(): void {
  const trigger = _modelControlsRoot()?.querySelector<HTMLButtonElement>('#wa-model-menu-trigger') || null;
  if (trigger) trigger.focus();
}

function _modelControlsRoot(): HTMLElement | null {
  return document.getElementById('wa-ai-input-area');
}

function _modelMenuElements(): { wrapper: HTMLElement | null; trigger: HTMLButtonElement | null; menu: HTMLElement | null } {
  const controlsRoot = _modelControlsRoot();
  return {
    wrapper: controlsRoot?.querySelector<HTMLElement>('#wa-model-mode-toggle') || null,
    trigger: controlsRoot?.querySelector<HTMLButtonElement>('#wa-model-menu-trigger') || null,
    menu: controlsRoot?.querySelector<HTMLElement>('#wa-model-mode-menu') || null,
  };
}

function _positionModelModeMenu(): void {
  const { trigger, menu } = _modelMenuElements();
  if (!trigger || !menu || menu.hidden) return;

  const viewportPadding = 8;
  const gap = 8;
  menu.style.removeProperty('max-height');
  const triggerRect = trigger.getBoundingClientRect();
  let menuRect = menu.getBoundingClientRect();
  const visualViewport = window.visualViewport;
  const viewportLeft = visualViewport?.offsetLeft || 0;
  const viewportTop = visualViewport?.offsetTop || 0;
  const viewportWidth = visualViewport?.width || window.innerWidth;
  const viewportHeight = visualViewport?.height || window.innerHeight;
  const viewportRight = viewportLeft + viewportWidth;
  const viewportBottom = viewportTop + viewportHeight;
  // Koto applies UI scaling with CSS `zoom`. DOM rectangles are already in
  // visual pixels, while fixed-position left/top values are zoomed again.
  // Convert the desired visual position back into the menu's CSS coordinate
  // space so 110%/120% zoom cannot throw the popover out of the viewport.
  const scaleX = menu.offsetWidth > 0 ? menuRect.width / menu.offsetWidth : 1;
  const scaleY = menu.offsetHeight > 0 ? menuRect.height / menu.offsetHeight : scaleX;
  const availableAbove = Math.max(0, triggerRect.top - viewportTop - gap - viewportPadding);
  const availableBelow = Math.max(0, viewportBottom - triggerRect.bottom - gap - viewportPadding);
  const opensAbove = availableAbove >= menuRect.height
    || (availableBelow < menuRect.height && availableAbove > availableBelow);
  const availableHeight = opensAbove ? availableAbove : availableBelow;
  if (menuRect.height > availableHeight && availableHeight > 0) {
    menu.style.maxHeight = `${Math.floor(availableHeight / (scaleY || 1))}px`;
    menuRect = menu.getBoundingClientRect();
  }

  const left = Math.min(
    Math.max(viewportLeft + viewportPadding, triggerRect.left),
    Math.max(viewportLeft + viewportPadding, viewportRight - menuRect.width - viewportPadding),
  );
  const top = opensAbove
    ? triggerRect.top - menuRect.height - gap
    : triggerRect.bottom + gap;
  const clampedTop = Math.min(
    Math.max(viewportTop + viewportPadding, top),
    Math.max(viewportTop + viewportPadding, viewportBottom - menuRect.height - viewportPadding),
  );

  menu.style.left = `${Math.round(left / (scaleX || 1))}px`;
  menu.style.top = `${Math.round(clampedTop / (scaleY || 1))}px`;
  menu.dataset.placement = opensAbove ? 'top' : 'bottom';
}

function _setModelModeMenuOpen(open: boolean, focusActive: boolean = false): void {
  const { wrapper, trigger, menu } = _modelMenuElements();
  if (!wrapper || !trigger || !menu) return;

  wrapper.classList.toggle('is-open', open);
  trigger.setAttribute('aria-expanded', String(open));
  menu.hidden = !open;
  if (!open) {
    menu.style.removeProperty('left');
    menu.style.removeProperty('top');
    menu.style.removeProperty('max-height');
    menu.removeAttribute('data-placement');
    return;
  }

  _positionModelModeMenu();
  if (focusActive) {
    const active = menu.querySelector<HTMLButtonElement>('.wa-model-mode-toggle-btn.active:not(:disabled)')
      || menu.querySelector<HTMLButtonElement>('.wa-model-mode-toggle-btn:not(:disabled)');
    active?.focus();
  }
}

function _focusAdjacentModelOption(current: HTMLButtonElement, direction: number): void {
  const { menu } = _modelMenuElements();
  if (!menu) return;
  const options = Array.from(menu.querySelectorAll<HTMLButtonElement>('.wa-model-mode-toggle-btn:not(:disabled)'));
  if (!options.length) return;
  if (direction < -1) {
    options[0].focus();
    return;
  }
  if (direction > 1) {
    options[options.length - 1].focus();
    return;
  }
  const currentIndex = options.indexOf(current);
  const nextIndex = currentIndex < 0 ? 0 : (currentIndex + direction + options.length) % options.length;
  options[nextIndex].focus();
}

function _bindModelModeControls(): void {
  const root = _modelControlsRoot();
  if (!root || root.dataset.modelControlsBound === 'true') return;

  root.dataset.modelControlsBound = 'true';
  root.addEventListener('click', (event) => {
    const target = event.target;
    if (!(target instanceof Element)) return;
    const trigger = target.closest<HTMLButtonElement>('#wa-model-menu-trigger');
    if (trigger && root.contains(trigger)) {
      event.preventDefault();
      _setModelModeMenuOpen(trigger.getAttribute('aria-expanded') !== 'true');
      return;
    }
    const button = target.closest<HTMLButtonElement>('.wa-model-mode-toggle-btn[data-model-mode]');
    if (!button || !root.contains(button) || button.disabled) return;

    const mode = String(button.dataset.modelMode || '').trim();
    if (!mode) return;
    event.preventDefault();
    _setModelModeMenuOpen(false);
    _modelMenuElements().trigger?.focus();
    setLockedModel(mode);
  });
  root.addEventListener('keydown', (event) => {
    const target = event.target;
    if (!(target instanceof Element)) return;
    const trigger = target.closest<HTMLButtonElement>('#wa-model-menu-trigger');
    if (trigger && root.contains(trigger) && ['ArrowUp', 'ArrowDown'].includes(event.key)) {
      event.preventDefault();
      _setModelModeMenuOpen(true, true);
      return;
    }
    const option = target.closest<HTMLButtonElement>('.wa-model-mode-toggle-btn[data-model-mode]');
    if (!option || !root.contains(option)) return;
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      _focusAdjacentModelOption(option, event.key === 'ArrowDown' ? 1 : -1);
    } else if (event.key === 'Home' || event.key === 'End') {
      event.preventDefault();
      _focusAdjacentModelOption(option, event.key === 'Home' ? -1000 : 1000);
    } else if (event.key === 'Escape') {
      event.preventDefault();
      _setModelModeMenuOpen(false);
      _modelMenuElements().trigger?.focus();
    } else if (event.key === 'Tab') {
      _setModelModeMenuOpen(false);
    }
  });
  document.addEventListener('pointerdown', (event) => {
    const { wrapper } = _modelMenuElements();
    if (wrapper && !wrapper.contains(event.target as Node)) _setModelModeMenuOpen(false);
  });
  window.addEventListener('resize', () => _setModelModeMenuOpen(false));
  document.addEventListener('scroll', () => _setModelModeMenuOpen(false), true);
}

// ── Skill Library compatibility ──────────────────────────────────
export function closeSkillLibrary(): void {}

export function toggleSkillLibrary(): void {
  const opener = (window as any).openSkillsPanel;
  if (typeof opener === 'function') opener();
}

export function toggleWorkflowPanel(): void {
  toggleSkillLibrary();
}


// ── Theme ─────────────────────────────────────────────────────────
export function toggleTheme(): void {
  const html = document.documentElement;
  const isDark = html.getAttribute('data-wa-theme') === 'dark';
  if (isDark) {
    html.removeAttribute('data-wa-theme');
    localStorage.setItem('koto_theme', 'light');
  } else {
    html.setAttribute('data-wa-theme', 'dark');
    localStorage.setItem('koto_theme', 'dark');
  }
  const btn = document.getElementById('wa-theme-toggle-btn');
  if (btn) btn.innerHTML = isDark ? _SUN_SVG : _MOON_SVG;
}

// Restore theme toggle button label on load
(function _initThemeBtn() {
  const btn = document.getElementById('wa-theme-toggle-btn');
  if (!btn) return;
  const isDark = document.documentElement.getAttribute('data-wa-theme') === 'dark';
  btn.innerHTML = isDark ? _MOON_SVG : _SUN_SVG;
})();

// ── Model Labels & Display ────────────────────────────────────────
export const _MODEL_LABELS: Record<string, string> = {
  cloud: '\u4e91\u7aef',
  local: '\u672c\u5730',
  'deepseek-chat': 'DeepSeek Chat',
  'deepseek-v4-flash': 'DeepSeek V4 Flash',
};

export function _selectedCloudModelId(): string {
  return (state.lockedModel && !['cloud', 'deepseek', 'local'].includes(state.lockedModel))
    ? state.lockedModel
    : '';
}

export function _lookupModelMeta(modelId: string): ModelMeta | null {
  if (!modelId) return null;
  return (state._availableModels || []).find((model: ModelMeta) => model.id === modelId) || null;
}

export function _coerceModelLabel(label: any, fallback: string): string {
  if (typeof label === 'string') {
    const trimmed = label.trim();
    return trimmed || (fallback || '');
  }
  if (label && typeof label === 'object') {
    if (typeof label.display === 'string' && label.display.trim()) return label.display.trim();
    if (typeof label.name === 'string' && label.name.trim()) return label.name.trim();
    if (typeof label.label === 'string' && label.label.trim()) return label.label.trim();
    if (typeof label.id === 'string' && label.id.trim()) return label.id.trim();
    if (typeof label.model === 'string' && label.model.trim()) return label.model.trim();
  }
  if (label == null) return fallback || '';
  return (typeof label === 'number' || typeof label === 'boolean') ? String(label) : (fallback || '');
}

export function _normalizeLocalRuntimeModelLabel(label: any): string {
  const value = _coerceModelLabel(label, '').trim();
  if (!value) return '';
  return value.replace(/\uff08\u672a\u542f\u52a8\uff09$/u, '').replace(/\uff08\u672a\u4e0b\u8f7d\uff09$/u, '').trim();
}

export function _formatLocalRuntimeModelLabel(label: any, options?: { running?: boolean; installed?: boolean }): string {
  const opts = options || {};
  const normalized = _normalizeLocalRuntimeModelLabel(label);
  if (!normalized) return opts.running === false ? '\u672a\u542f\u52a8' : 'Ollama';
  if (opts.running === false) return `${normalized}\uff08\u672a\u542f\u52a8\uff09`;
  if (opts.installed === false) return `${normalized}\uff08\u672a\u4e0b\u8f7d\uff09`;
  return normalized;
}

export function _modelDisplayName(modelId: string, fallback?: string): string {
  if (!modelId) return fallback || '\u4e91\u7aef';
  if (modelId === 'deepseek') return 'DeepSeek';
  if (modelId === 'local') return '\u672c\u5730';
  const meta = _lookupModelMeta(modelId);
  const metaDisplay = _coerceModelLabel(meta && meta.display, '');
  if (metaDisplay) return metaDisplay;
  return _coerceModelLabel(_MODEL_LABELS[modelId], '') || _coerceModelLabel(fallback, '') || _coerceModelLabel(modelId, '');
}

export function _currentCloudModelHint(): string {
  const explicitCloudModel = _selectedCloudModelId();
  if (explicitCloudModel) return _modelDisplayName(explicitCloudModel, explicitCloudModel);

  if (state.lockedModel === 'deepseek') {
    return _modelDisplayName('deepseek-chat', 'DeepSeek Chat');
  }

  if (state.lockedModel !== 'local' && state._activeRoute?.modelId && state._activeRoute.modelId !== 'local') {
    return _coerceModelLabel(state._activeRoute.modelDisplay, '') || _modelDisplayName(state._activeRoute.modelId, state._activeRoute.modelId);
  }

  const mappedFileTaskModel = state._modelMap?.FILE_TASK || state._modelMap?.DOC_ANNOTATE || state._modelMap?.FILE_GEN || state._modelMap?.AGENT || state._modelMap?.CHAT || '';
  if (mappedFileTaskModel) return _modelDisplayName(mappedFileTaskModel, mappedFileTaskModel);

  return _modelDisplayName('deepseek-chat', 'DeepSeek Chat');
}

export function _syncModelStatusUi(): void {
  const controlsRoot = _modelControlsRoot();
  const badge = $('wa-ai-model-badge');
  const deepseekModelEl = controlsRoot?.querySelector<HTMLElement>('#wa-model-mode-deepseek-model') || null;
  const localModelEl = controlsRoot?.querySelector<HTMLElement>('#wa-model-mode-local-model') || null;
  const currentProviderEl = controlsRoot?.querySelector<HTMLElement>('#wa-model-current-provider') || null;
  const currentModelEl = controlsRoot?.querySelector<HTMLElement>('#wa-model-current-model') || null;
  const menuTrigger = controlsRoot?.querySelector<HTMLButtonElement>('#wa-model-menu-trigger') || null;
  const routeInfo = $('wa-ai-route-info');
  const explicitCloudModel = _selectedCloudModelId();
  const activeRoute = state._activeRoute || null;
  const deepseekModelHint = _modelDisplayName('deepseek-chat', 'DeepSeek Chat');
  const localModelHint = state._localRuntimeModel || '\u672a\u542f\u52a8';
  const localCapabilityHint = state._localModelSupportsTools === false
    ? `${localModelHint}\uff08\u4ec5\u9605\u8bfb/\u95ee\u7b54\uff09`
    : localModelHint;
  const lockedMode = _normalizeWorkspaceModelMode(state.lockedModel, 'deepseek');
  const rawActiveMode = lockedMode === 'cloud'
    ? _normalizeWorkspaceModelMode(state._cloudProvider, 'deepseek')
    : lockedMode;
  const activeMode = rawActiveMode === 'cloud' ? 'deepseek' : rawActiveMode;

  const modelLabel = _coerceModelLabel(activeRoute?.modelDisplay, '')
    || (state.lockedModel === 'local'
      ? '\u672c\u5730'
      : state.lockedModel === 'deepseek'
        ? 'DeepSeek'
        : (explicitCloudModel ? _modelDisplayName(explicitCloudModel, explicitCloudModel) : 'DeepSeek'));

  if (badge) {
    badge.textContent = modelLabel;
    badge.title = modelLabel;
  }
  if (deepseekModelEl) {
    deepseekModelEl.textContent = deepseekModelHint;
    deepseekModelEl.title = `DeepSeek \u6587\u4ef6\u4efb\u52a1\u6a21\u578b\uff1a${deepseekModelHint}`;
    deepseekModelEl.hidden = false;
  }
  if (localModelEl) {
    localModelEl.textContent = localCapabilityHint;
    localModelEl.title = state._localModelSupportsTools === false
      ? `\u672c\u5730\u6a21\u578b\uff1a${localModelHint}\u3002\u53ef\u7528\u4e8e\u9605\u8bfb\u548c\u95ee\u7b54\uff0c\u5199\u6587\u4ef6\u4efb\u52a1\u9700\u5207\u6362\u5230\u652f\u6301 tools \u7684\u6a21\u578b\u3002`
      : `\u672c\u5730\u6a21\u578b\uff1a${localModelHint}`;
    localModelEl.hidden = false;
  }
  const currentProviderLabel = activeMode === 'local' ? '\u672c\u5730' : 'DeepSeek';
  const currentModelLabel = activeMode === 'local' ? localCapabilityHint : deepseekModelHint;
  if (currentProviderEl) currentProviderEl.textContent = currentProviderLabel;
  if (currentModelEl) currentModelEl.textContent = currentModelLabel;
  if (menuTrigger) {
    const triggerLabel = `${currentProviderLabel}\uff1a${currentModelLabel}`;
    menuTrigger.title = `\u5f53\u524d\u6a21\u578b\uff1a${triggerLabel}`;
    menuTrigger.setAttribute('aria-label', `\u9009\u62e9 AI \u6a21\u578b\uff0c\u5f53\u524d\u4e3a ${triggerLabel}`);
  }
  controlsRoot?.querySelectorAll('.wa-model-mode-toggle-btn[data-model-mode]').forEach((button) => {
    const btn = button as HTMLElement;
    const isActive = btn.dataset.modelMode === activeMode;
    btn.classList.toggle('active', isActive);
    btn.setAttribute('aria-selected', String(isActive));
    const buttonTitle = btn.dataset.modelMode === 'local'
      ? (state._localModelSupportsTools === false
        ? `\u672c\u5730\u6a21\u578b\uff1a${localModelHint}\u3002\u4ec5\u652f\u6301\u9605\u8bfb/\u95ee\u7b54\u6587\u4ef6\u4efb\u52a1\u3002`
        : `\u672c\u5730\u6a21\u578b\uff1a${localModelHint}`)
      : `DeepSeek \u6587\u4ef6\u4efb\u52a1\u6a21\u578b\uff1a${deepseekModelHint}`;
    btn.title = buttonTitle;
    const sub = btn.querySelector('.wa-model-mode-sub') as HTMLElement | null;
    if (sub && sub !== deepseekModelEl && sub !== localModelEl) {
      sub.textContent = btn.dataset.modelMode === 'local' ? localCapabilityHint : deepseekModelHint;
      sub.hidden = false;
    }
  });

  if (!routeInfo) return;

  const routeBits: string[] = [];
  if (activeRoute && !explicitCloudModel && state.lockedModel !== 'deepseek') {
    routeBits.push('\u81ea\u52a8\u8def\u7531');
  }

  if (activeRoute?.taskDisplay) routeBits.push(activeRoute.taskDisplay);
  if (activeRoute?.routeMethod) routeBits.push(activeRoute.routeMethod);
  if (!activeRoute?.taskDisplay && !activeRoute?.routeMethod && activeRoute?.message) {
    routeBits.push(activeRoute.message);
  }

  if (!routeBits.length) {
    routeInfo.style.display = 'none';
    routeInfo.textContent = '';
    routeInfo.removeAttribute('title');
    return;
  }

  const routeText = routeBits.join(' \u00b7 ');
  routeInfo.style.display = '';
  routeInfo.textContent = routeText;
  routeInfo.title = routeText;
}

export function _applyRouteEvent(evt: any): void {
  if (!evt || typeof evt !== 'object') return;

  const routeModelId = evt.model || (state.lockedModel === 'local' ? 'local' : '');
  const taskDisplay = evt.task_display || evt.task_type || '';
  const routeMethod = evt.route_method || evt.workflow || evt.pattern || '';
  const routeMessage = evt.message || '';

  state._activeRoute = {
    modelId: routeModelId,
    modelDisplay: _coerceModelLabel(evt.model_display, '') || _modelDisplayName(routeModelId, routeModelId || 'Koto AI'),
    taskDisplay,
    routeMethod,
    message: routeMessage,
  };

  _syncModelStatusUi();
}

// ── Model catalog refresh ─────────────────────────────────────────
export function _refreshModelCatalog(force: boolean = false): Promise<any> {
  if (state._modelCatalogPromise && !force) return state._modelCatalogPromise;

  const request = fetch('/api/v1/models', { cache: 'no-store' })
    .then((response) => {
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    })
    .then((data) => {
      state._modelsReady = !!(data && data.ready);
      state._cloudProvider = _normalizeWorkspaceModelMode(data && data.cloud_provider, state._cloudProvider || 'deepseek');
      state._modelMap = (data && data.model_map) || {};
      state._availableModels = Array.isArray(data?.available) ? data.available : [];
      _syncModelStatusUi();
      return data;
    })
    .catch((error: any): any => {
      console.warn('[WA] model catalog fetch failed:', error);
      state._modelsReady = false;
      state._modelMap = {};
      state._availableModels = state._availableModels || [];
      _syncModelStatusUi();
      return null;
    })
    .finally(() => {
      if (state._modelCatalogPromise === request) state._modelCatalogPromise = null;
    });

  state._modelCatalogPromise = request;
  return request;
}

export function _checkOllamaStatus(): void {
  fetch('/api/v1/workspace/ollama-status')
    .then((response) => (response.ok ? response.json() : null))
    .then((data) => {
      const localButton = _modelControlsRoot()?.querySelector<HTMLButtonElement>('#wa-model-mode-local-btn') || null;
      if (!localButton) return;
      const configuredModel = _normalizeLocalRuntimeModelLabel(
        (data && (data.configured_model || data.model)) || state._localRuntimeModel
      );
      const configuredInstalled = !!(!data || data.configured_model_installed !== false);
      state._localModelSupportsTools = data && typeof data.configured_model_supports_tools === 'boolean'
        ? data.configured_model_supports_tools
        : null;
      if (data && data.running) {
        state._localRuntimeModel = _formatLocalRuntimeModelLabel(
          configuredModel || data.model || 'Ollama',
          { running: true, installed: configuredInstalled }
        );
        localButton.disabled = false;
      } else {
        state._localRuntimeModel = _formatLocalRuntimeModelLabel(configuredModel, { running: false });
        localButton.disabled = false;
      }
      _syncModelStatusUi();
    })
    .catch(() => {});
}

function _applyWorkspaceModelMode(mode: string): void {
  const normalized = _normalizeWorkspaceModelMode(mode, 'deepseek');
  const nextMode = normalized === 'cloud' ? 'deepseek' : normalized;
  state.lockedModel = nextMode;
  if (nextMode === 'deepseek') state._cloudProvider = nextMode;
  (window as any)._waLockedModelCache = nextMode;
  _clearActiveRoute();
  _syncModelStatusUi();
}

function _bindSettingsModelBridge(): void {
  const bridgeKey = '__kotoSettingsModelBridgeBound';
  if ((window as any)[bridgeKey]) return;
  (window as any)[bridgeKey] = true;

  window.addEventListener('koto:model-runtime-changed', (event: Event) => {
    const detail = (event as CustomEvent<any>).detail || {};
    const mode = String(detail.mode || '').trim();
    if (!mode) return;
    const model = _normalizeLocalRuntimeModelLabel(detail.localModel || detail.local_model);
    if (model) state._localRuntimeModel = model;
    _applyWorkspaceModelMode(mode);
    _checkOllamaStatus();
  });
}

export function _syncLockedModelFromServer(): Promise<any> {
  return fetch('/api/local-model/status', { cache: 'no-store' })
    .then((response) => (response.ok ? response.json() : null))
    .then((data) => {
      if (!data || data.success === false) return null;
      if (data.model) state._localRuntimeModel = _normalizeLocalRuntimeModelLabel(data.model);
      const serverModeRaw = _normalizeWorkspaceModelMode(data.mode, 'deepseek');
      const serverMode = serverModeRaw === 'cloud' ? 'deepseek' : serverModeRaw;
      const pendingMode = String(state._modelChoicePendingMode || '').trim();
      const pendingAt = Number(state._modelChoiceUpdatedAt || 0);
      const hasFreshLocalChoice = !!(pendingMode && pendingAt && (Date.now() - pendingAt < 5000));
      if (hasFreshLocalChoice && serverMode !== pendingMode) {
        if (serverMode === 'deepseek') {
          state._cloudProvider = serverMode;
        }
        _syncModelStatusUi();
        return data;
      }
      if (pendingMode && serverMode === pendingMode) {
        state._modelChoicePendingMode = '';
      }
      const serverLockedModel = serverMode === 'local' ? 'local' : serverMode;
      if (state.lockedModel !== serverLockedModel) {
        _applyWorkspaceModelMode(serverLockedModel);
      }
      if (serverMode === 'deepseek') {
        state._cloudProvider = serverMode;
      }
      _syncModelStatusUi();
      return data;
    })
    .catch((): any => null);
}

export function initSocket(): void {
  _bindModelModeControls();
  _bindSettingsModelBridge();
  // Retire browser-only model preferences.  The server setting is the one
  // authoritative source shared by chat, file tasks, and the settings panel.
  localStorage.removeItem('wa_locked_model');
  localStorage.removeItem('wa_model_choice_explicit');
  localStorage.removeItem('wa_ai_output_mode');
  _syncModelStatusUi();
  _refreshModelCatalog();
  _syncLockedModelFromServer().finally(() => {
    _checkOllamaStatus();
  });
}

export function setLockedModel(val: string): void {
  _setWorkspaceModelMode(val);
}

export function getLockedModel(): string {
  return state.lockedModel === 'local' ? 'local' : 'auto';
}

function _setWorkspaceModelMode(mode: string): void {
  const normalized = _normalizeWorkspaceModelMode(mode, 'deepseek');
  const newModel = normalized === 'cloud' ? 'deepseek' : normalized;

  // Prevent redundant switches (loop guard during cross-bundle sync)
  if (state.lockedModel === newModel) return;

  const previousModel = state.lockedModel;
  _applyWorkspaceModelMode(newModel);
  state._modelChoicePendingMode = newModel;
  state._modelChoiceUpdatedAt = Date.now();
  _checkOllamaStatus();

  const switchPromise = _csrfFetch('/api/local-model/switch', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mode: newModel }),
  }).then(async (response) => {
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.success === false) throw new Error(data.error || '模型模式切换失败');
    state._modelChoicePendingMode = '';
    if (data.model) state._localRuntimeModel = _normalizeLocalRuntimeModelLabel(data.model);
    window.dispatchEvent(new CustomEvent('koto:model-runtime-changed', {
      detail: { ...(data.active_model || {}), mode: data.mode || newModel, cloudModel: data.cloud_model || 'deepseek-chat', localModel: data.local_model || data.model || '', source: 'workspace' },
    }));
    return _refreshModelCatalog(true);
  }).catch((error: any) => {
    if (state.lockedModel === newModel) _applyWorkspaceModelMode(previousModel);
    state._modelChoicePendingMode = '';
    if (typeof (window as any).showNotification === 'function') {
      (window as any).showNotification(error?.message || '模型模式切换失败', 'error', 3000);
    }
  });
  let trackedPromise: Promise<any>;
  trackedPromise = switchPromise.finally(() => {
    if (state._modelChoicePromise === trackedPromise) state._modelChoicePromise = null;
  });
  state._modelChoicePromise = trackedPromise;
}

// ── Backward compat ──
if (typeof window !== 'undefined') {
  publishWorkspaceApi({
    toggleSettings,
    toggleSkillLibrary,
    closeSkillLibrary,
    toggleWorkflowPanel,
    toggleTheme,
    setLockedModel,
    getLockedModel,
    refreshModelCatalog: (force: boolean = true) => _refreshModelCatalog(force),
    checkOllamaStatus: _checkOllamaStatus,
    syncModelStatusUi: _syncModelStatusUi,
    syncLockedModelFromServer: _syncLockedModelFromServer,
    initSocket,
  });
}

initSocket();
