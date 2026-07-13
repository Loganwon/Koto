/**
 * Koto Settings Module — settings panel, user preferences, setup wizard
 */

import { csrfFetch } from '../shared/csrf';
import { markSidePanelClosed, markSidePanelOpen } from '../shared/side-panels';

interface KotoSettings {
  storage?: { workspace_dir?: string; documents_dir?: string; images_dir?: string; chats_dir?: string };
  appearance?: { theme?: string; ui_zoom?: string };
  ai?: { cloud_provider?: string; show_thinking?: boolean; show_task_type?: boolean; auto_save_files?: boolean; enable_mini_game?: boolean; use_local_only?: boolean; local_model?: string };
  local_model?: string;
  proxy?: { enabled?: boolean; manual_proxy?: string };
}

let currentSettings: KotoSettings | null = null;
let currentBrowseTarget: string | null = null;
let currentBrowsePath: string = '';
let allLocalModels: string[] = [];
(window as any).currentSettings = currentSettings;
(window as any).browseHomeDir = '';

export async function loadSettings(): Promise<void> {
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      const response = await fetch('/api/settings');
      if (response.ok) {
        currentSettings = await response.json();
        (window as any).currentSettings = currentSettings;
        applySettingsToUI();
        return;
      }
    } catch (error) { /* retry */ }
    if (attempt < 2) await new Promise(r => setTimeout(r, 500));
  }
  console.error('Failed to load settings after all retries');
}

export function applySettingsToUI(): void {
  if (!currentSettings) return;
  const s = currentSettings;
  const setVal = (id: string, val: string) => { const el = document.getElementById(id); if (el) (el as HTMLInputElement).value = val || ''; };
  setVal('settingWorkspaceDir', s.storage?.workspace_dir || '');
  setVal('settingDocumentsDir', s.storage?.documents_dir || '');
  setVal('settingImagesDir', s.storage?.images_dir || '');
  setVal('settingChatsDir', s.storage?.chats_dir || '');
  (window as any).browseHomeDir = s.storage?.workspace_dir || '';

  const currentTheme = s.appearance?.theme || 'light';
  if (typeof (window as any).updateThemeSelector === 'function') (window as any).updateThemeSelector(currentTheme);
  if (typeof (window as any).applyTheme === 'function') (window as any).applyTheme(currentTheme);
  localStorage.setItem('koto.theme', currentTheme);

  const cloudProviderEl = document.getElementById('settingCloudProvider') as HTMLSelectElement | null;
  if (cloudProviderEl) { cloudProviderEl.value = 'deepseek'; syncCloudProviderUi('deepseek'); }

  const showThinkingCheckbox = document.getElementById('settingShowThinking') as HTMLInputElement | null;
  if (showThinkingCheckbox) showThinkingCheckbox.checked = s.ai?.show_thinking === true;

  const showTaskTypeCheckbox = document.getElementById('settingShowTaskType') as HTMLInputElement | null;
  if (showTaskTypeCheckbox) showTaskTypeCheckbox.checked = s.ai?.show_task_type === true;

  const autoSaveFilesCheckbox = document.getElementById('settingAutoSaveFiles') as HTMLInputElement | null;
  if (autoSaveFilesCheckbox) autoSaveFilesCheckbox.checked = s.ai?.auto_save_files !== false;

  const miniGameCheckbox = document.getElementById('settingEnableMiniGame') as HTMLInputElement | null;
  if (miniGameCheckbox) {
    const isEnabled = s.ai?.enable_mini_game !== false;
    miniGameCheckbox.checked = isEnabled;
    (window as any).enableMiniGame = isEnabled;
  }

  const localOnlyEl = document.getElementById('settingLocalOnly') as HTMLInputElement | null;
  if (localOnlyEl) localOnlyEl.checked = s.ai?.use_local_only === true;

  const savedZoom = parseFloat(String(s.appearance?.ui_zoom || '1'));
  if (Number.isFinite(savedZoom) && typeof (window as any).setUIZoom === 'function') {
    (window as any).setUIZoom(String(savedZoom), true);
  }

  const proxyEnabledEl = document.getElementById('settingProxyEnabled') as HTMLInputElement | null;
  if (proxyEnabledEl) proxyEnabledEl.checked = s.proxy?.enabled !== false;
  setVal('settingManualProxy', s.proxy?.manual_proxy || '');
}

function setActivityActive(id: string): void {
  document.querySelectorAll('.activity-btn').forEach((button) => button.classList.remove('active'));
  const target = document.getElementById(id);
  if (target) target.classList.add('active');
}

function isUnifiedWorkspace(): boolean {
  return document.body.classList.contains('koto-unified-workspace')
    || document.documentElement.classList.contains('koto-unified-workspace');
}

export function openSettings(): void {
  if (typeof (window as any).closeSkillsPanel === 'function') (window as any).closeSkillsPanel();
  loadSettings();
  if (typeof (window as any).loadSkills === 'function') (window as any).loadSkills();
  if (typeof (window as any).loadSkillBindings === 'function') (window as any).loadSkillBindings();
  if (typeof (window as any).loadTriggers === 'function') (window as any).loadTriggers();
  if (typeof (window as any).loadShadowStatus === 'function') (window as any).loadShadowStatus();
  if (typeof (window as any).detectLocalModels === 'function') (window as any).detectLocalModels();
  const panel = document.getElementById('settingsPanel');
  if (panel) panel.classList.add('active');
  document.body.classList.add('settings-panel-open');
  markSidePanelOpen('settingsPanel');
  setActivityActive('navSettingsBtn');
}

export function closeSettings(): void {
  const panel = document.getElementById('settingsPanel');
  if (panel) panel.classList.remove('active');
  document.body.classList.remove('settings-panel-open');
  markSidePanelClosed('settingsPanel');
  const navBtn = document.getElementById('navSettingsBtn');
  if (navBtn) navBtn.classList.remove('active');
  if (isUnifiedWorkspace()) setActivityActive('navWorkspaceBtn');
}

export function toggleSettings(): void {
  const panel = document.getElementById('settingsPanel');
  if (panel && panel.classList.contains('active')) {
    closeSettings();
  } else {
    openSettings();
  }
}

export function syncCloudProviderUi(provider: string): void {
  const normalized = 'deepseek';
  const desc = document.getElementById('settingsApiKeyDesc');
  const hint = document.getElementById('settingCloudProviderHint');
  const input = document.getElementById('settingsApiKeyInput') as HTMLInputElement | null;
  const providerEl = document.getElementById('settingCloudProvider') as HTMLSelectElement | null;
  if (providerEl) providerEl.value = normalized;
  if (desc) desc.innerHTML = '更新 DeepSeek API 密钥。选择 DeepSeek 后，云端任务流默认使用 DeepSeek Chat。';
  if (hint) hint.textContent = '云端模式下使用 DeepSeek Chat，支持文字对话、代码和文件任务规划。';
  if (input) input.placeholder = '粘贴 DeepSeek API Key…';
}

export async function onCloudProviderChange(provider: string): Promise<void> {
  const normalized = 'deepseek';
  syncCloudProviderUi(normalized);
  await updateSetting('ai', 'cloud_provider', normalized);
  if (normalized === 'deepseek') { await updateSetting('ai', 'deepseek_model', 'deepseek-chat'); }
  csrfFetch('/api/local-model/switch', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ mode: 'cloud' }) }).catch(() => {});
  if ((window as any).WA && typeof (window as any).WA.refreshModelCatalog === 'function') { (window as any).WA.refreshModelCatalog(true); }
}

export async function saveSettingsApiKey(): Promise<void> {
  const input = document.getElementById('settingsApiKeyInput') as HTMLInputElement | null;
  const status = document.getElementById('settingsApiKeyStatus');
  const providerEl = document.getElementById('settingCloudProvider') as HTMLSelectElement | null;
  const provider = 'deepseek';
  const apiKey = input?.value.trim();
  if (!apiKey || apiKey.length < 10) {
    if (status) { status.textContent = '❌ 请输入有效的 API Key'; status.style.color = 'var(--accent-error, #ef4444)'; }
    return;
  }
  if (status) { status.textContent = '⏳ 正在保存…'; status.style.color = 'var(--text-secondary)'; }
  try {
    const res = await csrfFetch('/api/setup/apikey', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ api_key: apiKey, provider }) });
    const data = await res.json();
    if (data.success) {
      if (status) { status.textContent = '✅ 已保存，正在生效…'; status.style.color = 'var(--accent-primary, #10b981)'; }
      if (input) input.value = '';
      const banner = document.getElementById('apiKeyBanner');
      if (banner) banner.style.display = 'none';
      setTimeout(() => { if (status) status.textContent = ''; }, 3000);
    } else {
      if (status) { status.textContent = '❌ ' + (data.error || '保存失败'); status.style.color = 'var(--accent-error, #ef4444)'; }
    }
  } catch (e: any) {
    if (status) { status.textContent = '❌ 网络错误: ' + e.message; status.style.color = 'var(--accent-error, #ef4444)'; }
  }
}

function rememberSetting(category: string, key: string, value: any): void {
  currentSettings = {
    ...(currentSettings || {}),
    [category]: {
      ...(((currentSettings as any)?.[category]) || {}),
      [key]: value,
    },
  };
  (window as any).currentSettings = currentSettings;
}

export async function updateSetting(category: string, key: string, value: any): Promise<boolean> {
  try {
    const response = await csrfFetch('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ category, key, value })
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.success === false) {
      throw new Error(data.error || '设置保存失败');
    }
    rememberSetting(category, key, value);
    return true;
  } catch (e: any) {
    if (typeof (window as any).showNotification === 'function') {
      (window as any).showNotification(e?.message || '设置保存失败', 'error', 2200);
    }
    console.warn('Failed to update setting', category, key, e);
    return false;
  }
}

export async function onBooleanSettingChange(input: HTMLInputElement, category: string, key: string): Promise<void> {
  const nextValue = input.checked;
  const previousValue = typeof (currentSettings as any)?.[category]?.[key] === 'boolean'
    ? (currentSettings as any)[category][key]
    : !nextValue;
  const saved = await updateSetting(category, key, nextValue);
  if (!saved) {
    input.checked = previousValue;
    return;
  }
  if (category === 'ai' && key === 'enable_mini_game') {
    (window as any).enableMiniGame = nextValue;
    if (!nextValue) (window as any).hideMiniGame?.();
  }
}

export function applyLocalOnlyMode(enabled: boolean): void {
  // The workspace owns the visible chat-mode control.  Settings only
  // publishes confirmed server state, avoiding a second mode-switch request.
  window.dispatchEvent(new CustomEvent('koto:model-mode-changed', {
    detail: { mode: enabled ? 'local' : 'cloud', source: 'settings' },
  }));
}

function syncLocalOnlyControlFromWorkspace(event: Event): void {
  const mode = String((event as CustomEvent<any>).detail?.mode || '').trim().toLowerCase();
  if (!mode) return;
  const enabled = mode === 'local';
  const localOnlyEl = document.getElementById('settingLocalOnly') as HTMLInputElement | null;
  if (localOnlyEl) localOnlyEl.checked = enabled;
  if (currentSettings) {
    currentSettings.ai = { ...(currentSettings.ai || {}), use_local_only: enabled };
    (window as any).currentSettings = currentSettings;
  }
}

window.addEventListener('koto:model-mode-changed', syncLocalOnlyControlFromWorkspace);

export async function onLocalOnlyChange(enabled: boolean): Promise<void> {
  const localOnlyEl = document.getElementById('settingLocalOnly') as HTMLInputElement | null;
  const selectEl = document.getElementById('settingLocalModel') as HTMLSelectElement | null;

  if (enabled) {
    try {
      const resp = await fetch('/api/local-model/list');
      const data = await resp.json().catch(() => ({}));
      const models = Array.isArray(data.models) ? data.models : [];
      const ollamaOk = data.success !== false && models.length > 0;
      if (!ollamaOk) {
        if (localOnlyEl) localOnlyEl.checked = false;
        applyLocalOnlyMode(false);
        const errMsg = String(data.error || '').trim();
        const msg = errMsg.includes('正在启动')
          ? '⚠️ Ollama 正在启动，请稍候再试。'
          : errMsg.includes('未安装')
            ? '⚠️ Ollama 未安装。请访问 ollama.com 下载安装后再开启本地模式。'
            : '⚠️ Ollama 未运行。请先启动 Ollama，再开启本地模式。';
        if (typeof (window as any).showNotification === 'function') {
          (window as any).showNotification(msg, 'warning', 6000);
        }
        return;
      }
      if (!selectEl || !selectEl.value) {
        if (localOnlyEl) localOnlyEl.checked = false;
        applyLocalOnlyMode(false);
        if (typeof (window as any).showNotification === 'function') {
          (window as any).showNotification('⚠️ 请先在下方选择一个本地模型', 'warning', 4000);
        }
        const pickerRow = document.getElementById('localModelPickerRow');
        if (pickerRow) pickerRow.style.display = '';
        detectLocalModels();
        return;
      }
    } catch (_) {
      if (localOnlyEl) localOnlyEl.checked = false;
      applyLocalOnlyMode(false);
      if (typeof (window as any).showNotification === 'function') {
        (window as any).showNotification('⚠️ 无法检测 Ollama 状态，请确认 Ollama 已启动', 'warning', 5000);
      }
      return;
    }
  }

  const modelTag = selectEl?.value || currentSettings?.local_model || currentSettings?.ai?.local_model || '';
  const previousEnabled = currentSettings?.ai?.use_local_only === true;
  let runtimeSwitched = false;
  try {
    const response = await csrfFetch('/api/local-model/switch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(enabled ? { mode: 'local', model_tag: modelTag } : { mode: 'cloud' }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.success === false) throw new Error(data.error || '本地模型切换失败');
    runtimeSwitched = true;
    if (currentSettings) {
      currentSettings.ai = { ...(currentSettings.ai || {}), use_local_only: enabled };
      (window as any).currentSettings = currentSettings;
    }
    applyLocalOnlyMode(enabled);
    window.dispatchEvent(new CustomEvent('koto:local-model-changed', {
      detail: { model: data.model || modelTag, source: 'settings' },
    }));
  } catch (error: any) {
    if (localOnlyEl) localOnlyEl.checked = previousEnabled;
    applyLocalOnlyMode(previousEnabled);
    if (runtimeSwitched) {
      void csrfFetch('/api/local-model/switch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(previousEnabled ? { mode: 'local', model_tag: modelTag } : { mode: 'cloud' }),
      });
    }
    if (typeof (window as any).showNotification === 'function') {
      (window as any).showNotification(error?.message || '本地模型切换失败', 'error', 4000);
    }
  }
}

export function filterLocalModels(query: string): void {
  const q = String(query || '').trim().toLowerCase();
  renderLocalModelOptions(q);
}

export async function detectLocalModels(): Promise<void> {
  const hintEl = document.getElementById('localModelHint');
  const badgeEl = document.getElementById('ollamaStatusBadge');
  if (hintEl) hintEl.textContent = '检测中...';
  if (badgeEl) {
    badgeEl.textContent = '检测中...';
    (badgeEl as HTMLElement).style.color = 'var(--text-secondary)';
  }
  try {
    const resp = await fetch('/api/local-model/list');
    const data = await resp.json();
    const container = document.getElementById('localModelsList');
    const models = Array.isArray(data.models) ? data.models.map((m: any) => String(m.name || m || '').trim()).filter(Boolean) : [];
    allLocalModels = models;
    renderLocalModelOptions((document.getElementById('localModelSearch') as HTMLInputElement | null)?.value || '');
    if (container) {
      container.innerHTML = models.length
        ? models.map((m: string) => `<div style="font-size:12px;padding:4px 0;">${escHtml(m)}</div>`).join('')
        : '<div style="color:var(--text-muted);font-size:12px;">未检测到本地模型</div>';
    }
    if (badgeEl) {
      badgeEl.textContent = models.length ? `${models.length} 个模型` : '未检测到';
      (badgeEl as HTMLElement).style.color = models.length ? '#5cb85c' : '#e87979';
    }
    if (hintEl) {
      const error = String(data.error || '').trim();
      hintEl.textContent = models.length ? `共检测到 ${models.length} 个本地模型` : (error || '未检测到已安装的 Ollama 模型');
    }
  } catch (e: any) {
    allLocalModels = [];
    renderLocalModelOptions('');
    if (badgeEl) {
      badgeEl.textContent = 'Ollama 未运行';
      (badgeEl as HTMLElement).style.color = '#e87979';
    }
    if (hintEl) hintEl.textContent = `检测失败: ${e?.message || e}`;
  }
}

function renderLocalModelOptions(query: string): void {
  const selectEl = document.getElementById('settingLocalModel') as HTMLSelectElement | null;
  const hintEl = document.getElementById('localModelHint');
  if (!selectEl) return;
  const q = String(query || '').trim().toLowerCase();
  const filtered = q ? allLocalModels.filter((model) => model.toLowerCase().includes(q)) : allLocalModels;
  const saved = currentSettings?.ai?.local_model || currentSettings?.local_model || '';
  if (!filtered.length) {
    selectEl.innerHTML = `<option value="">${allLocalModels.length ? '— 无匹配模型 —' : '— 检测后选择 —'}</option>`;
    if (hintEl && allLocalModels.length) hintEl.textContent = `无匹配结果（共 ${allLocalModels.length} 个模型）`;
    return;
  }
  selectEl.innerHTML = filtered.map((model) => {
    const selected = model === saved ? ' selected' : '';
    return `<option value="${escHtml(model)}"${selected}>${escHtml(model)}</option>`;
  }).join('');
  if (!selectEl.value && filtered[0]) selectEl.value = filtered[0];
  if (hintEl) hintEl.textContent = q ? `过滤结果：${filtered.length} / ${allLocalModels.length} 个模型` : `共 ${filtered.length} 个本地模型`;
}

export async function onLocalModelChange(modelTag: string): Promise<void> {
  const nextModel = String(modelTag || '').trim();
  if (!nextModel) return;
  try {
    const localOnly = (document.getElementById('settingLocalOnly') as HTMLInputElement | null)?.checked === true;
    // Always use the model-switch endpoint.  It atomically mirrors the
    // top-level runtime model and ai.local_model while preserving the current
    // local/cloud mode when no mode is supplied.  Going through updateSetting
    // here left the runtime source stale whenever local-only was unchecked.
    const resp = await csrfFetch('/api/local-model/switch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model_tag: nextModel }),
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok || data.success === false) throw new Error(data.error || '本地模型保存失败');
    if (currentSettings) {
      currentSettings.local_model = nextModel;
      currentSettings.ai = { ...(currentSettings.ai || {}), local_model: nextModel };
      (window as any).currentSettings = currentSettings;
    }
    window.dispatchEvent(new CustomEvent('koto:local-model-changed', {
      detail: { model: data.model || nextModel, source: 'settings' },
    }));
    if (typeof (window as any).showNotification === 'function') {
      (window as any).showNotification(localOnly ? `已切换本地模型：${nextModel}` : `已保存本地模型：${nextModel}`, 'success', 1800);
    }
  } catch (error: any) {
    if (typeof (window as any).showNotification === 'function') (window as any).showNotification(error?.message || '本地模型切换失败', 'error', 3000);
  }
}

// ── Setup Wizard ──
let setupCloudProvider: string = 'deepseek';

export async function checkSetupStatus(): Promise<void> {
  try {
    const response = await fetch('/api/setup/status');
    const data = await response.json();
    selectSetupProvider('deepseek');
    if (!data.initialized || !data.has_api_key) { showSetupWizard(); } else { (window as any).setupComplete = true; }
  } catch (error) { /* ignore */ }
}

export function showSetupWizard(): void {
  const wizard = document.getElementById('setupWizard');
  const step1 = document.getElementById('setupStep1');
  if (wizard) wizard.classList.add('active');
  if (step1) step1.classList.add('active');
}

export function hideSetupWizard(): void {
  const wizard = document.getElementById('setupWizard');
  if (wizard) wizard.classList.remove('active');
}

export function selectSetupProvider(provider: string): void {
  const normalized = 'deepseek';
  setupCloudProvider = normalized;
  const deepseekBtn = document.getElementById('setupProviderDeepSeek');
  const desc = document.getElementById('setupApiProviderDesc');
  const input = document.getElementById('setupApiKey') as HTMLInputElement | null;
  const status = document.getElementById('step1Status');
  if (deepseekBtn) deepseekBtn.classList.toggle('active', normalized === 'deepseek');
  if (desc) desc.innerHTML = '从 <a href="https://platform.deepseek.com/api_keys" target="_blank">DeepSeek 开放平台</a> 获取 API Key';
  if (input) input.placeholder = '粘贴 DeepSeek API Key...';
  if (status) { status.textContent = ''; status.className = 'step-status'; }
}

export async function saveApiKey(): Promise<void> {
  const apiKey = (document.getElementById('setupApiKey') as HTMLInputElement).value.trim();
  const status = document.getElementById('step1Status');
  if (!apiKey || apiKey.length < 10) { if (status) { status.textContent = '❌ 请输入有效的 API Key'; status.className = 'step-status error'; } return; }
  if (status) { status.textContent = '⏳ 正在验证...'; status.className = 'step-status loading'; }
  try {
    const response = await csrfFetch('/api/setup/apikey', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ api_key: apiKey, provider: setupCloudProvider }) });
    const data = await response.json();
    if (data.success) {
      if (status) { status.textContent = '✅ DeepSeek API Key 已保存'; status.className = 'step-status success'; }
      const step1 = document.getElementById('setupStep1'); const step2 = document.getElementById('setupStep2');
      if (step1) { step1.classList.remove('active'); step1.classList.add('completed'); }
      if (step2) step2.classList.add('active');
    } else {
      if (status) { status.textContent = '❌ ' + (data.error || '保存失败'); status.className = 'step-status error'; }
    }
  } catch (error) { if (status) { status.textContent = '❌ 网络错误'; status.className = 'step-status error'; } }
}

export async function useActivationCode(): Promise<void> {
  const code = ((document.getElementById('setupActivateCode') as HTMLInputElement)?.value || '').trim().toUpperCase();
  const status = document.getElementById('step1ActivateStatus');
  if (!code) { if (status) { status.textContent = '❌ 请输入激活码'; status.className = 'step-status error'; } return; }
  if (status) { status.textContent = '⏳ 正在验证激活码...'; status.className = 'step-status loading'; }
  try {
    const res = await csrfFetch('/api/setup/activate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ code }) });
    const data = await res.json();
    if (data.success) {
      if (status) { status.textContent = '✅ 激活成功！'; status.className = 'step-status success'; }
      setTimeout(() => {
        const step1 = document.getElementById('setupStep1'); const step2 = document.getElementById('setupStep2');
        if (step1) { step1.classList.remove('active'); step1.classList.add('completed'); }
        if (step2) step2.classList.add('active');
      }, 800);
    } else { if (status) { status.textContent = '❌ ' + (data.error || '激活失败'); status.className = 'step-status error'; } }
  } catch (err) { if (status) { status.textContent = '❌ 网络错误，请重试'; status.className = 'step-status error'; } }
}

export async function saveWorkspace(): Promise<void> {
  const workspacePath = (document.getElementById('setupWorkspacePath') as HTMLInputElement).value.trim();
  const status = document.getElementById('step2Status');
  if (status) { status.textContent = '⏳ 正在创建工作区...'; status.className = 'step-status loading'; }
  try {
    const response = await csrfFetch('/api/setup/workspace', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path: workspacePath }) });
    const data = await response.json();
    if (data.success) {
      if (status) { status.textContent = '✅ 工作区已创建: ' + data.path; status.className = 'step-status success'; }
      const step2 = document.getElementById('setupStep2'); const step3 = document.getElementById('setupStep3');
      if (step2) { step2.classList.remove('active'); step2.classList.add('completed'); }
      if (step3) step3.classList.add('active');
    } else { if (status) { status.textContent = '❌ ' + (data.error || '创建失败'); status.className = 'step-status error'; } }
  } catch (error) { if (status) { status.textContent = '❌ 网络错误'; status.className = 'step-status error'; } }
}

export async function testConnection(): Promise<void> {
  const status = document.getElementById('step3Status');
  if (status) { status.textContent = '⏳ 正在测试连接...'; status.className = 'step-status loading'; }
  try {
    const response = await fetch('/api/setup/test');
    const data = await response.json();
    if (data.success) {
      if (status) { status.textContent = `✅ 连接成功! (${data.latency}s) - ${data.message}`; status.className = 'step-status success'; }
      const step3 = document.getElementById('setupStep3');
      const startBtn = document.getElementById('startKotoBtn') as HTMLButtonElement | null;
      if (step3) { step3.classList.remove('active'); step3.classList.add('completed'); }
      if (startBtn) startBtn.disabled = false;
    } else { if (status) { status.textContent = '❌ ' + (data.error || '连接失败'); status.className = 'step-status error'; } }
  } catch (error: any) { if (status) { status.textContent = '❌ 网络错误: ' + error.message; status.className = 'step-status error'; } }
}

export async function activateWithCode(): Promise<void> {
  const codeInput = document.getElementById('activationCode') as HTMLInputElement;
  const code = codeInput.value.trim();
  const status = document.getElementById('step1Status');
  if (!code) { if (status) { status.textContent = '❌ 请输入激活码'; status.className = 'step-status error'; } return; }
  if (status) { status.textContent = '⏳ 正在验证激活码...'; status.className = 'step-status loading'; }
  try {
    const response = await csrfFetch('/api/setup/activate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ code }) });
    const data = await response.json();
    if (data.success) {
      if (status) { status.textContent = '✅ 激活成功！正在启动 Koto...'; status.className = 'step-status success'; }
      setTimeout(() => { (window as any).setupComplete = true; hideSetupWizard(); if (typeof (window as any).loadSessions === 'function') (window as any).loadSessions(); if (typeof (window as any).checkStatus === 'function') (window as any).checkStatus(); }, 800);
    } else { if (status) { status.textContent = '❌ ' + (data.error || '激活失败'); status.className = 'step-status error'; } }
  } catch (error) { if (status) { status.textContent = '❌ 网络错误'; status.className = 'step-status error'; } }
}

export function skipSetup(): void {
  if (confirm('跳过设置可能导致部分功能无法使用，确定要跳过吗？')) {
    hideSetupWizard();
    const banner = document.getElementById('apiKeyBanner');
    if (banner) banner.style.display = 'flex';
  }
}

export function dismissApiKeyBanner(): void {
  const banner = document.getElementById('apiKeyBanner');
  if (banner) banner.style.display = 'none';
}

export function finishSetup(): void {
  (window as any).setupComplete = true;
  hideSetupWizard();
  if (typeof (window as any).loadSessions === 'function') (window as any).loadSessions();
  if (typeof (window as any).checkStatus === 'function') (window as any).checkStatus();
}

export function browseSetupFolder(): void {
  currentBrowseTarget = 'setup_workspace';
  const pathInput = document.getElementById('setupWorkspacePath') as HTMLInputElement | null;
  const startPath = pathInput?.value.trim() || (window as any).browseHomeDir || '';
  currentBrowsePath = startPath;
  const manualPathInput = document.getElementById('manualPathInput') as HTMLInputElement | null;
  if (manualPathInput) manualPathInput.value = startPath;
  if (startPath) {
    if (typeof (window as any).loadFolderList === 'function') (window as any).loadFolderList(startPath);
  } else {
    if (typeof (window as any).loadFolderDrives === 'function') (window as any).loadFolderDrives();
  }
  const folderModal = document.getElementById('folderModal');
  if (folderModal) folderModal.classList.add('active');
}

export function browseFolder(target: string): void {
  currentBrowseTarget = target;
  (window as any).currentBrowseTarget = target;
  const field = document.getElementById(`setting${target.split('_').map(part => part ? part[0].toUpperCase() + part.slice(1) : '').join('')}`) as HTMLInputElement | null;
  const explicitMap: Record<string, string> = {
    workspace_dir: 'settingWorkspaceDir',
    documents_dir: 'settingDocumentsDir',
    images_dir: 'settingImagesDir',
    chats_dir: 'settingChatsDir',
  };
  const input = document.getElementById(explicitMap[target] || '') as HTMLInputElement | null;
  const startPath = (input || field)?.value.trim() || (window as any).browseHomeDir || '';
  currentBrowsePath = startPath;
  (window as any).currentBrowsePath = startPath;
  const manualPathInput = document.getElementById('manualPathInput') as HTMLInputElement | null;
  if (manualPathInput) manualPathInput.value = startPath;
  if (startPath && typeof (window as any).loadFolderList === 'function') {
    (window as any).loadFolderList(startPath);
  } else if (typeof (window as any).loadFolderDrives === 'function') {
    (window as any).loadFolderDrives();
  }
  document.getElementById('folderModal')?.classList.add('active');
}

export function closeFolderModal(): void {
  document.getElementById('folderModal')?.classList.remove('active');
  currentBrowseTarget = null;
  (window as any).currentBrowseTarget = null;
}

export async function confirmFolderSelect(): Promise<void> {
  const path = ((document.getElementById('manualPathInput') as HTMLInputElement | null)?.value || '').trim();
  const target = currentBrowseTarget || (window as any).currentBrowseTarget;
  if (!path || !target) return;
  if (target === 'setup_workspace') {
    const input = document.getElementById('setupWorkspacePath') as HTMLInputElement | null;
    if (input) input.value = path;
    closeFolderModal();
    return;
  }
  await updateSetting('storage', target, path);
  const inputMap: Record<string, string> = {
    workspace_dir: 'settingWorkspaceDir',
    documents_dir: 'settingDocumentsDir',
    images_dir: 'settingImagesDir',
    chats_dir: 'settingChatsDir',
  };
  const input = document.getElementById(inputMap[target] || '') as HTMLInputElement | null;
  if (input) input.value = path;
  closeFolderModal();
}

// ── Status / Latency ──
export function getLatencyClass(latencyMs: number | null): string {
  if (latencyMs == null) return '';
  if (latencyMs < 500) return 'good';
  if (latencyMs < 1500) return 'ok';
  return 'slow';
}

export function formatLatency(providerData: any): string {
  if (!providerData) return '--';
  if (providerData.error === 'checking') return '检查中';
  if (providerData.reachable && providerData.latency_ms != null) return `${providerData.latency_ms}ms`;
  if (providerData.error === 'timeout') return '超时';
  return '不可达';
}

export function updateLatencyProvider(provider: string, providerData: any): void {
  const id = 'Deepseek';
  const row = document.getElementById(`latency${id}`);
  const value = document.getElementById(`latency${id}Val`);
  const bar = document.getElementById(`latency${id}Bar`);
  const latencyMs = providerData && providerData.reachable ? providerData.latency_ms : null;
  const latencyClass = getLatencyClass(latencyMs);
  if (value) value.textContent = formatLatency(providerData);
  if (bar) { bar.className = `latency-bar-fill ${latencyClass}`.trim(); bar.style.width = latencyMs == null ? '0%' : `${Math.max(8, Math.min(100, latencyMs / 20))}%`; }
  if (row) { row.classList.toggle('offline', !(providerData && providerData.reachable)); }
}

export function updateLatencyDetail(results: any): void {
  updateLatencyProvider('deepseek', results && results.deepseek);
}

export function toggleLatencyDetail(event?: Event): void {
  if (event) event.stopPropagation();
  const detail = document.getElementById('latencyDetail');
  if (!detail) return;
  const willOpen = !detail.classList.contains('open');
  if (willOpen) {
    updateLatencyDetail((window as any)._lastCloudLatency || { deepseek: { reachable: false, error: 'checking' } });
    checkStatus();
  }
  const leftSlot = document.getElementById('wa-left-latency-slot');
  if (leftSlot && detail.parentElement !== leftSlot) {
    leftSlot.appendChild(detail);
  }
  if (detail) detail.style.display = willOpen ? 'block' : 'none';
  detail.classList.toggle('open', willOpen);
  const arrow = document.querySelector('.status-expand-arrow'); if (arrow) arrow.classList.toggle('open', willOpen);
  const indicator = document.getElementById('statusIndicator'); if (indicator) indicator.setAttribute('aria-expanded', willOpen ? 'true' : 'false');
}

export async function checkStatus(): Promise<void> {
  const dot = document.querySelector('.status-dot');
  const text = document.querySelector('.status-text');

  try {
    const response = await fetch('/api/ping');
    const data = await response.json();
    if (data.status === 'ok') {
      if (dot) { dot.classList.add('online'); dot.classList.remove('offline'); }
      if (text) text.textContent = data.ollama ? '🦙 ...' : '...';
    } else {
      if (dot) { dot.classList.add('offline'); dot.classList.remove('online'); }
      if (text) text.textContent = 'Offline';
    }
  } catch (error) {
    if (dot) { dot.classList.add('offline'); dot.classList.remove('online'); }
    if (text) text.textContent = 'Error';
  }

  const noticeBar = document.getElementById('wechat-notice-bar');
  try {
    const cResp = await fetch('/api/ping/cloud/all', { signal: AbortSignal.timeout(12000) });
    if (cResp.ok) {
      const cloud = await cResp.json();
      (window as any)._lastCloudLatency = cloud;
      updateLatencyDetail(cloud);
      const providerOrder = ['deepseek'];
      const reachable = providerOrder.map(p => cloud && cloud[p]).filter((item: any) => item && item.reachable && item.latency_ms != null);
      const ollamaHint = text?.textContent?.startsWith('🦙') ? ' | 🦙' : '';
      if (reachable.length) {
        const fastest = reachable.reduce((best: any, item: any) => item.latency_ms < best.latency_ms ? item : best);
        if (text) text.textContent = `☁ ${fastest.latency_ms}ms${ollamaHint}`;
        if (noticeBar) noticeBar.style.display = 'none';
      } else {
        if (text) text.textContent = `☁ 超时${ollamaHint}`;
        if (noticeBar) noticeBar.style.display = 'block';
      }
    } else { if (noticeBar) noticeBar.style.display = 'block'; }
  } catch (_) {
    updateLatencyDetail((window as any)._lastCloudLatency || {});
    if (noticeBar) noticeBar.style.display = 'block';
  }

  try {
    const mResp = await fetch('/api/ops/metrics', { signal: AbortSignal.timeout(3000) });
    if (mResp.ok) {
      const m = await mResp.json();
      const trigEnabled = (m.triggers && m.triggers.enabled) || 0;
      const pill = document.getElementById('jobsRunningPill'); if (pill) pill.style.display = 'none';
      const badge = document.getElementById('opsStatusBadge');
      if (badge && trigEnabled > 0) { badge.textContent = `${trigEnabled} 触发器活跃`; badge.style.display = 'block'; }
      else if (badge) badge.style.display = 'none';
    }
  } catch (_) { /* ignore */ }
}

// ── Batch Jobs Panel ──
const batchJobsState = { timer: null as ReturnType<typeof setInterval> | null };

export function openBatchJobsPanel(): void {
  const modal = document.getElementById('batchPanelModal');
  if (modal) modal.style.display = 'flex';
  refreshBatchJobs();
  if (batchJobsState.timer) clearInterval(batchJobsState.timer);
  batchJobsState.timer = setInterval(refreshBatchJobs, 2000);
}

export function closeBatchJobsPanel(): void {
  const modal = document.getElementById('batchPanelModal');
  if (modal) modal.style.display = 'none';
  if (batchJobsState.timer) { clearInterval(batchJobsState.timer); batchJobsState.timer = null; }
}

export async function refreshBatchJobs(): Promise<void> {
  try {
    const response = await fetch('/api/batch/jobs');
    const data = await response.json();
    if (!data.success) return;
    const listEl = document.getElementById('batchJobsList');
    const jobs = data.jobs || [];
    if (!listEl) return;
    if (jobs.length === 0) { listEl.innerHTML = '<div class="batch-empty">暂无任务</div>'; return; }
    listEl.innerHTML = jobs.map((job: any) => {
      const total = job.total_items || 0;
      const processed = job.processed_items || 0;
      const percent = total > 0 ? Math.round((processed / total) * 100) : 0;
      const outputDir = job.output_dir || '';
      const encodedOutput = encodeURIComponent(outputDir);
      const status = job.status || 'unknown';
      return `<div class="batch-job-card"><div class="batch-job-title">${escHtml(job.name || job.job_id)}</div><div class="batch-job-meta"><span>状态: ${escHtml(status)}</span><span>${processed}/${total}</span></div><div class="batch-job-progress"><div class="batch-job-progress-fill" style="width:${percent}%"></div></div><div class="batch-job-meta" style="margin-top:6px;"><span>${escHtml(outputDir)}</span><button class="ghost-btn" style="padding:2px 8px;font-size:12px;" onclick="openPath('${encodedOutput}')">复制路径</button></div></div>`;
    }).join('');
  } catch (error) { /* ignore */ }
}

export async function resetSettings(): Promise<void> {
  if (!confirm('确定要重置所有设置为默认值吗？')) return;
  try {
    const response = await csrfFetch('/api/settings/reset', { method: 'POST' });
    const data = await response.json();
    if (!response.ok || data.success === false) throw new Error(data.error || '重置失败');
    await loadSettings();
    if (typeof (window as any).showNotification === 'function') {
      (window as any).showNotification('设置已恢复默认', 'success', 1800);
    }
  } catch (error: any) {
    if (typeof (window as any).showNotification === 'function') {
      (window as any).showNotification('重置失败: ' + (error.message || error), 'error');
    }
  }
}

export async function bootstrapTriggers(force: boolean = false): Promise<void> {
  const label = force ? '重建' : '初始化';
  if (force && !confirm('确定重建所有推荐触发器吗？已有推荐触发器将被替换。')) return;
  try {
    const resp = await csrfFetch('/api/jobs/triggers/bootstrap', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ force }),
    });
    const data = await resp.json();
    if (!resp.ok || data.ok === false) throw new Error(data.error || '操作失败');
    if (typeof (window as any).loadTriggers === 'function') await (window as any).loadTriggers();
    if (typeof (window as any).showNotification === 'function') {
      const created = (data.data && data.data.created || []).length;
      const skipped = (data.data && data.data.skipped || []).length;
      (window as any).showNotification(`${label}完成：创建 ${created}，跳过 ${skipped}`, 'success', 2200);
    }
  } catch (error: any) {
    if (typeof (window as any).showNotification === 'function') {
      (window as any).showNotification(`${label}失败: ` + (error.message || error), 'error');
    }
  }
}

export async function shadowOpenObservations(): Promise<void> {
  try {
    const resp = await fetch('/api/shadow/observations');
    const data = await resp.json();
    if (!resp.ok || data.ok === false) throw new Error(data.error || '获取失败');
    const obs = data.data || {};
    const topics = Object.entries(obs.topics || {})
      .sort((a: any, b: any) => Number(b[1]) - Number(a[1]))
      .slice(0, 10)
      .map(([key, value]) => `${key}x${value}`)
      .join(', ');
    const hours = Object.entries(obs.active_hours || {})
      .sort((a: any, b: any) => Number(a[0]) - Number(b[0]))
      .map(([hour, count]) => `${hour}时:${count}`)
      .join('  ');
    const detail = [
      `总观察次数: ${obs.total_observations || 0}`,
      `连续天数: ${obs.streak?.days || 0}`,
      `活跃时段: ${hours || '暂无记录'}`,
      `话题词频: ${topics || '暂无'}`,
      `开放任务: ${(obs.open_tasks || []).filter((task: any) => !task.done).length} 项待处理`,
      `最后活跃: ${obs.last_seen || '无'}`,
    ].join('\n');
    if (typeof (window as any).showNotification === 'function') {
      (window as any).showNotification(detail, 'info', 8000);
    } else {
      alert(detail);
    }
  } catch (error: any) {
    if (typeof (window as any).showNotification === 'function') {
      (window as any).showNotification('获取失败: ' + (error.message || error), 'error');
    }
  }
}

function openPath(path: string): void { if (path) copyPathToClipboard(decodeURIComponent(path), '输出路径'); }

function copyPathToClipboard(path: string, label: string = '路径'): void {
  navigator.clipboard.writeText(path).then(() => {
    if (typeof (window as any).showNotification === 'function') (window as any).showNotification(`已复制${label}`, 'success', 1500);
  }).catch(() => { prompt(`复制${label}：`, path); });
}

function escHtml(str: string): string {
  return String(str || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// ── Backward compat ──
(window as any).loadSettings = loadSettings;
(window as any).applySettingsToUI = applySettingsToUI;
(window as any).openSettings = openSettings;
(window as any).closeSettings = closeSettings;
(window as any).toggleSettings = toggleSettings;
(window as any).syncCloudProviderUi = syncCloudProviderUi;
(window as any).onCloudProviderChange = onCloudProviderChange;
(window as any).saveSettingsApiKey = saveSettingsApiKey;
(window as any).updateSetting = updateSetting;
(window as any).onBooleanSettingChange = onBooleanSettingChange;
(window as any).applyLocalOnlyMode = applyLocalOnlyMode;
(window as any).onLocalOnlyChange = onLocalOnlyChange;
(window as any).filterLocalModels = filterLocalModels;
(window as any).detectLocalModels = detectLocalModels;
(window as any).onLocalModelChange = onLocalModelChange;
(window as any).checkSetupStatus = checkSetupStatus;
(window as any).showSetupWizard = showSetupWizard;
(window as any).hideSetupWizard = hideSetupWizard;
(window as any).selectSetupProvider = selectSetupProvider;
(window as any).saveApiKey = saveApiKey;
(window as any).useActivationCode = useActivationCode;
(window as any).saveWorkspace = saveWorkspace;
(window as any).testConnection = testConnection;
(window as any).activateWithCode = activateWithCode;
(window as any).skipSetup = skipSetup;
(window as any).dismissApiKeyBanner = dismissApiKeyBanner;
(window as any).finishSetup = finishSetup;
(window as any).browseSetupFolder = browseSetupFolder;
(window as any).browseFolder = browseFolder;
(window as any).closeFolderModal = closeFolderModal;
(window as any).confirmFolderSelect = confirmFolderSelect;
(window as any).checkStatus = checkStatus;
(window as any).updateLatencyDetail = updateLatencyDetail;
(window as any).toggleLatencyDetail = toggleLatencyDetail;
(window as any).openBatchJobsPanel = openBatchJobsPanel;
(window as any).closeBatchJobsPanel = closeBatchJobsPanel;
(window as any).refreshBatchJobs = refreshBatchJobs;
(window as any).resetSettings = resetSettings;
(window as any).bootstrapTriggers = bootstrapTriggers;
(window as any).shadowOpenObservations = shadowOpenObservations;
(window as any).currentSettings = currentSettings;
(window as any).currentBrowseTarget = currentBrowseTarget;
(window as any).currentBrowsePath = currentBrowsePath;
