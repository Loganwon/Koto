/**
 * Settings & Model Management — auto-save toggle, theme, model labels.
 * Workspace model settings and provider controls.
 */

import { publishWorkspaceApi } from '../shared/workspace-api';

declare function $(id: string): HTMLElement | null;
declare let state: any;
declare let _waAiResultsRuntime: any;
declare let _waQuickActionRuntime: any;
declare let _waConversationRuntime: any;
declare let _waTaskDispatcher: any;

declare function _csrfFetch(url: string, init?: RequestInit): Promise<Response>;
declare function _normalizeWorkspaceModelMode(mode: string, fallback: string): string;
declare function _setStreamBtn(streaming: boolean): void;

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
  const active = _modelControlsRoot()?.querySelector('.wa-model-mode-toggle-btn.active') as HTMLElement | null;
  if (active) active.focus();
}

function _modelControlsRoot(): HTMLElement | null {
  return document.getElementById('wa-ai-input-area');
}

function _bindModelModeControls(): void {
  const root = _modelControlsRoot();
  if (!root || root.dataset.modelControlsBound === 'true') return;

  root.dataset.modelControlsBound = 'true';
  root.addEventListener('click', (event) => {
    const target = event.target;
    if (!(target instanceof Element)) return;
    const button = target.closest<HTMLButtonElement>('.wa-model-mode-toggle-btn[data-model-mode]');
    if (!button || !root.contains(button) || button.disabled) return;

    const mode = String(button.dataset.modelMode || '').trim();
    if (!mode) return;
    event.preventDefault();
    setLockedModel(mode);
  });
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
  const routeInfo = $('wa-ai-route-info');
  const explicitCloudModel = _selectedCloudModelId();
  const activeRoute = state._activeRoute || null;
  const deepseekModelHint = _modelDisplayName('deepseek-chat', 'DeepSeek Chat');
  const localModelHint = state._localRuntimeModel || '\u672a\u542f\u52a8';
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
    localModelEl.textContent = localModelHint;
    localModelEl.title = `\u672c\u5730\u6a21\u578b\uff1a${localModelHint}`;
    localModelEl.hidden = false;
  }
  controlsRoot?.querySelectorAll('.wa-model-mode-toggle-btn[data-model-mode]').forEach((button) => {
    const btn = button as HTMLElement;
    const isActive = btn.dataset.modelMode === activeMode;
    btn.classList.toggle('active', isActive);
    const buttonTitle = btn.dataset.modelMode === 'local'
      ? `\u672c\u5730\u6a21\u578b\uff1a${localModelHint}`
      : `DeepSeek \u6587\u4ef6\u4efb\u52a1\u6a21\u578b\uff1a${deepseekModelHint}`;
    btn.title = buttonTitle;
    const sub = btn.querySelector('.wa-model-mode-sub') as HTMLElement | null;
    if (sub && sub !== deepseekModelEl && sub !== localModelEl) {
      sub.textContent = btn.dataset.modelMode === 'local' ? localModelHint : deepseekModelHint;
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

  window.addEventListener('koto:local-model-changed', (event: Event) => {
    const model = _normalizeLocalRuntimeModelLabel((event as CustomEvent<any>).detail?.model);
    if (!model) return;
    state._localRuntimeModel = model;
    _syncModelStatusUi();
  });

  window.addEventListener('koto:model-mode-changed', (event: Event) => {
    const mode = String((event as CustomEvent<any>).detail?.mode || '').trim();
    if (!mode) return;
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

  _csrfFetch('/api/local-model/switch', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mode: newModel }),
  }).then(async (response) => {
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.success === false) throw new Error(data.error || '模型模式切换失败');
    state._modelChoicePendingMode = '';
    if (data.model) state._localRuntimeModel = _normalizeLocalRuntimeModelLabel(data.model);
    window.dispatchEvent(new CustomEvent('koto:model-mode-changed', {
      detail: { mode: data.mode || newModel, source: 'workspace' },
    }));
    window.dispatchEvent(new CustomEvent('koto:local-model-changed', {
      detail: { model: data.model || '', source: 'workspace' },
    }));
    return _refreshModelCatalog(true);
  }).catch((error: any) => {
    if (state.lockedModel === newModel) _applyWorkspaceModelMode(previousModel);
    state._modelChoicePendingMode = '';
    if (typeof (window as any).showNotification === 'function') {
      (window as any).showNotification(error?.message || '模型模式切换失败', 'error', 3000);
    }
  });
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
