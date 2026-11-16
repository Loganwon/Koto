import { installErrorBoundary } from '../shared/error-boundary';
import { csrfFetch } from '../shared/csrf';

installErrorBoundary();

const API = {
  status: '/api/plugin-protocol',
  catalog: '/api/plugin-protocol/catalog',
  example: '/api/plugin-protocol/example',
  validate: '/api/plugin-protocol/validate',
  registrations: '/api/plugin-protocol/registrations',
};

let validatedManifest: any = null;

function escapeHtml(value: unknown): string {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

async function jsonRequest(url: string, init: RequestInit = {}): Promise<any> {
  const headers = new Headers(init.headers || {});
  const adminToken = sessionStorage.getItem('koto_addon_admin_token') || '';
  if (adminToken) headers.set('X-Admin-Token', adminToken);
  const response = await csrfFetch(url, { ...init, headers });
  const data = await response.json().catch(() => ({ error: response.statusText }));
  if (!response.ok) throw new Error(data.error || response.statusText);
  return data;
}

function setText(id: string, value: unknown): void {
  const node = document.getElementById(id);
  if (node) node.textContent = String(value ?? '—');
}

function renderCatalog(addons: any[], message: string): void {
  const target = document.getElementById('addon-catalog');
  if (!target) return;
  if (!addons.length) {
    target.className = 'addon-empty';
    target.innerHTML = `<strong>当前没有已准入的 Addon</strong><p>${escapeHtml(message)}</p>`;
    return;
  }
  target.className = 'addon-list';
  target.innerHTML = addons.map(addon => `
    <article class="addon-card">
      <div><strong>${escapeHtml(addon.name || addon.addon_id)}</strong><p>${escapeHtml(addon.addon_id)} · v${escapeHtml(addon.version)}</p></div>
      <span class="health health--${escapeHtml(addon.health)}">${escapeHtml(addon.state || addon.health)}</span>
      <dl>
        <div><dt>工具</dt><dd>${escapeHtml((addon.tools || []).join(', ') || '无')}</dd></div>
        <div><dt>检索器</dt><dd>${escapeHtml((addon.retrievers || []).join(', ') || '无')}</dd></div>
        <div><dt>接入状态</dt><dd>${addon.runtime_admitted ? '已进入 Agent' : '尚未进入 Agent'}${addon.last_error ? ` · ${escapeHtml(addon.last_error)}` : ''}</dd></div>
      </dl>
      <div class="addon-actions"><button data-addon-id="${escapeHtml(addon.addon_id)}" data-addon-enabled="${addon.enabled ? 'false' : 'true'}">${addon.enabled ? '停用' : '申请启用'}</button></div>
    </article>
  `).join('');
}

async function loadRuntime(): Promise<void> {
  try {
    const [status, catalog] = await Promise.all([
      jsonRequest(API.status),
      jsonRequest(API.catalog),
    ]);
    const runtime = status.runtime || {};
    setText('runtime-state', runtime.execution ? '运行时已就绪' : '运行时未启用');
    setText('protocol-version', `v${status.protocol?.version || '—'}`);
    setText('addon-count', catalog.total || 0);
    setText('runtime-mode', runtime.task_routing ? '准入 + 路由 + 执行' : '仅校验');
    setText('contribution-kinds', (status.supported?.contribution_kinds || []).join(' / '));
    setText('runtime-transports', (status.supported?.runtime_enabled_transports || []).join(' / ') || '无');
    renderCatalog(catalog.addons || [], catalog.message || '');
  } catch (error: any) {
    setText('runtime-state', 'Addon 服务不可用');
    renderCatalog([], error.message);
  }
}

function updateSize(label = '尚未校验'): void {
  const input = document.getElementById('manifest-input') as HTMLTextAreaElement | null;
  const bytes = new TextEncoder().encode(input?.value || '').length;
  setText('manifest-size', `${bytes < 1024 ? `${bytes} B` : `${(bytes / 1024).toFixed(1)} KB`} · ${label}`);
}

function renderValidation(data: any, error = ''): void {
  const target = document.getElementById('validation-result');
  if (!target) return;
  if (error) {
    target.innerHTML = `<div class="validation validation--error"><strong>Manifest 未通过</strong><p>${escapeHtml(error)}</p></div>`;
    updateSize('校验未通过');
    return;
  }
  const summary = data.summary || {};
  const permissions = summary.permissions || [];
  const contributions = summary.contributions || [];
  target.innerHTML = `
    <div class="validation validation--ok"><strong>Manifest 符合接入协议</strong><p>${escapeHtml(data.message)}</p></div>
    <h3>${escapeHtml(summary.name || summary.plugin_id)}</h3>
    <p>${escapeHtml(summary.plugin_id)} · v${escapeHtml(summary.version)} · ${escapeHtml(summary.publisher)}</p>
    <h4>权限声明</h4>
    <ul>${permissions.map((item: any) => `<li>${escapeHtml(item.label)} <code>${escapeHtml(item.id)}</code> · ${escapeHtml(item.risk)}</li>`).join('') || '<li>未申请权限</li>'}</ul>
    <h4>能力贡献</h4>
    <ul>${contributions.map((item: any) => `<li>${escapeHtml(item.name)} · ${escapeHtml(item.kind)} · ${escapeHtml((item.capabilities || []).join(', '))}</li>`).join('')}</ul>
  `;
  updateSize('协议校验通过，尚未安装');
}

async function loadExample(): Promise<void> {
  try {
    const data = await jsonRequest(API.example);
    const input = document.getElementById('manifest-input') as HTMLTextAreaElement | null;
    if (input) input.value = JSON.stringify(data.manifest, null, 2);
    const registrationInput = document.getElementById('registration-input') as HTMLTextAreaElement | null;
    if (registrationInput) {
      const { manifest: _manifest, ...registration } = data.registration || {};
      registrationInput.value = JSON.stringify(registration, null, 2);
    }
    validatedManifest = null;
    const registerButton = document.getElementById('register-button') as HTMLButtonElement | null;
    if (registerButton) registerButton.disabled = true;
    updateSize('示例已载入');
  } catch (error: any) {
    renderValidation({}, error.message);
  }
}

async function validateManifest(): Promise<void> {
  const input = document.getElementById('manifest-input') as HTMLTextAreaElement | null;
  const button = document.getElementById('validate-button') as HTMLButtonElement | null;
  let manifest: any;
  try {
    manifest = JSON.parse(input?.value.trim() || '');
  } catch (error: any) {
    renderValidation({}, `JSON 解析失败：${error.message}`);
    return;
  }
  if (button) button.disabled = true;
  try {
    const data = await jsonRequest(API.validate, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ manifest }),
    });
    validatedManifest = data.manifest;
    const registerButton = document.getElementById('register-button') as HTMLButtonElement | null;
    if (registerButton) registerButton.disabled = false;
    renderValidation(data);
  } catch (error: any) {
    validatedManifest = null;
    renderValidation({}, error.message);
  } finally {
    if (button) button.disabled = false;
  }
}

async function registerAddon(): Promise<void> {
  const input = document.getElementById('registration-input') as HTMLTextAreaElement | null;
  const button = document.getElementById('register-button') as HTMLButtonElement | null;
  if (!validatedManifest) {
    renderValidation({}, '请先通过 Manifest 校验。');
    return;
  }
  let registration: any;
  try {
    registration = JSON.parse(input?.value.trim() || '{}');
  } catch (error: any) {
    renderValidation({}, `接入配置 JSON 解析失败：${error.message}`);
    return;
  }
  if (button) button.disabled = true;
  try {
    const data = await jsonRequest(API.registrations, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...registration, manifest: validatedManifest }),
    });
    renderValidation({
      summary: {
        name: data.addon?.name,
        plugin_id: data.addon?.addon_id,
        version: data.addon?.version,
        publisher: data.addon?.publisher,
        permissions: [],
        contributions: [],
      },
      message: data.message,
    });
    await loadRuntime();
  } catch (error: any) {
    renderValidation({}, error.message);
  } finally {
    if (button) button.disabled = false;
  }
}

async function setAddonEnabled(addonId: string, enabled: boolean): Promise<void> {
  try {
    await jsonRequest(`${API.registrations}/${encodeURIComponent(addonId)}/enabled`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled }),
    });
  } catch (error: any) {
    renderValidation({}, error.message);
  } finally {
    await loadRuntime();
  }
}

document.addEventListener('DOMContentLoaded', () => {
  const adminToken = document.getElementById('addon-admin-token') as HTMLInputElement | null;
  if (adminToken) {
    adminToken.value = sessionStorage.getItem('koto_addon_admin_token') || '';
    adminToken.addEventListener('input', () => {
      sessionStorage.setItem('koto_addon_admin_token', adminToken.value.trim());
    });
  }
  document.getElementById('example-button')?.addEventListener('click', loadExample);
  document.getElementById('validate-button')?.addEventListener('click', validateManifest);
  document.getElementById('register-button')?.addEventListener('click', registerAddon);
  document.getElementById('manifest-input')?.addEventListener('input', () => updateSize());
  document.getElementById('addon-catalog')?.addEventListener('click', event => {
    const button = (event.target as HTMLElement).closest<HTMLButtonElement>('button[data-addon-id]');
    if (!button) return;
    void setAddonEnabled(button.dataset.addonId || '', button.dataset.addonEnabled === 'true');
  });
  void loadRuntime();
});
