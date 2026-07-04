/**
 * Settings & Model Management — auto-save toggle, theme, model labels.
 * Workspace model settings and provider controls.
 */

declare function $(id: string): HTMLElement | null;
declare var state: any;
declare var _waAiResultsRuntime: any;
declare var _waQuickActionRuntime: any;
declare var _waConversationRuntime: any;
declare var _waTaskDispatcher: any;

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
  const active = document.querySelector('.wa-model-mode-toggle-btn.active') as HTMLElement;
  if (active) active.focus();
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
  'deepseek-v4-pro': 'DeepSeek V4 Pro',
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
  if (modelId === 'gemini') return 'DeepSeek';  // legacy compat
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
    return _modelDisplayName('deepseek-v4-pro', 'DeepSeek V4 Pro');
  }

  if (state.lockedModel !== 'local' && state._activeRoute?.modelId && state._activeRoute.modelId !== 'local') {
    return _coerceModelLabel(state._activeRoute.modelDisplay, '') || _modelDisplayName(state._activeRoute.modelId, state._activeRoute.modelId);
  }

  const mappedFileTaskModel = state._modelMap?.FILE_TASK || state._modelMap?.DOC_ANNOTATE || state._modelMap?.FILE_GEN || state._modelMap?.AGENT || state._modelMap?.CHAT || '';
  if (mappedFileTaskModel) return _modelDisplayName(mappedFileTaskModel, mappedFileTaskModel);

  return _modelDisplayName('deepseek-v4-pro', 'DeepSeek V4 Pro');
}

export function _syncModelStatusUi(): void {
  const badge = $('wa-ai-model-badge');
  const deepseekModelEl = $('wa-model-mode-deepseek-model');
  const localModelEl = $('wa-model-mode-local-model');
  const routeInfo = $('wa-ai-route-info');
  const explicitCloudModel = _selectedCloudModelId();
  const activeRoute = state._activeRoute || null;
  const deepseekModelHint = _modelDisplayName('deepseek-v4-pro', 'DeepSeek V4 Pro');
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
  document.querySelectorAll('.wa-model-mode-toggle-btn[data-model-mode]').forEach((button) => {
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
    .catch((error) => {
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
      const localButton = document.getElementById('wa-model-mode-local-btn') as HTMLButtonElement | null;
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

export function _syncLockedModelFromServer(): Promise<any> {
  return fetch('/api/local-model/status', { cache: 'no-store' })
    .then((response) => (response.ok ? response.json() : null))
    .then((data) => {
      if (!data || data.success === false) return null;
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
        state.lockedModel = serverLockedModel;
        localStorage.setItem('wa_locked_model', serverLockedModel);
        _clearActiveRoute();
      }
      if (serverMode === 'deepseek') {
        state._cloudProvider = serverMode;
      }
      if (data.mode === 'local') {
        state._hasExplicitModelChoice = true;
        if (data.model) state._localRuntimeModel = data.model;
      }
      _syncModelStatusUi();
      return data;
    })
    .catch(() => null);
}

export function initSocket(): void {
  const storedLockedModel = localStorage.getItem('wa_locked_model');
  if (storedLockedModel !== state.lockedModel) {
    localStorage.setItem('wa_locked_model', state.lockedModel);
    _clearActiveRoute();
  }
  localStorage.removeItem('wa_ai_output_mode');
  _syncModelStatusUi();
  _refreshModelCatalog();
  _syncLockedModelFromServer().finally(() => {
    _checkOllamaStatus();
  });
}

export function setUseLocalModel(useLocal: boolean): void {
  _setWorkspaceModelMode(useLocal ? 'local' : (state._cloudProvider || 'deepseek'));
}

export function setLockedModel(val: string): void {
  _setWorkspaceModelMode(val);
}

function _setWorkspaceModelMode(mode: string): void {
  const normalized = _normalizeWorkspaceModelMode(mode, 'deepseek');
  const newModel = normalized === 'cloud' ? 'deepseek' : normalized;
  state.lockedModel = newModel;
  if (newModel === 'deepseek') state._cloudProvider = newModel;
  state._hasExplicitModelChoice = true;
  state._modelChoicePendingMode = newModel;
  state._modelChoiceUpdatedAt = Date.now();
  localStorage.setItem('wa_locked_model', newModel);
  localStorage.setItem('wa_model_choice_explicit', '1');
  _clearActiveRoute();
  _syncModelStatusUi();
  _checkOllamaStatus();
  _csrfFetch('/api/local-model/switch', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mode: newModel }),
  }).then(() => _refreshModelCatalog(true))
    .catch(() => {/* silent */});
}

// ── Backward compat ──
if (typeof window !== 'undefined') {
  (window as any).WA = (window as any).WA || {};
  (window as any).WA.toggleSettings = toggleSettings;
  (window as any).WA.toggleSkillLibrary = toggleSkillLibrary;
  (window as any).WA.closeSkillLibrary = closeSkillLibrary;
  (window as any).WA.toggleWorkflowPanel = toggleWorkflowPanel;
  (window as any).WA.toggleTheme = toggleTheme;
  (window as any).WA.setUseLocalModel = setUseLocalModel;
  (window as any).WA.setLockedModel = setLockedModel;
  (window as any).WA.refreshModelCatalog = (force: boolean = true) => _refreshModelCatalog(force);
  (window as any).WA.checkOllamaStatus = _checkOllamaStatus;
  (window as any).WA.syncLockedModelFromServer = _syncLockedModelFromServer;
  (window as any).WA.initSocket = initSocket;
  (window as any).initSocket = initSocket;
}

initSocket();
