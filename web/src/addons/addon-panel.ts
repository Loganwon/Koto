import { csrfFetch } from '../shared/csrf';

interface AddonCatalogItem {
  addon_id: string;
  name?: string;
  version?: string;
  health?: string;
  state?: string;
  runtime_admitted?: boolean;
  tools?: string[];
  retrievers?: string[];
  bindings?: Array<{ task_types?: string[] }>;
}

let catalogLoaded = false;

function escapeHtml(value: unknown): string {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function renderAddonCatalog(addons: AddonCatalogItem[], message: string): void {
  const target = document.getElementById('apCatalog');
  const count = document.getElementById('apAddonCount');
  if (count) count.textContent = String(addons.length);
  if (!target) return;
  if (!addons.length) {
    target.innerHTML = `
      <div class="ap-empty">
        <div class="ap-empty-icon">🔌</div>
        <strong>还没有已准入的 Addon</strong>
        <p>${escapeHtml(message || '运行时已经就绪，可以接入工具、RAG、数据库和外部 API。')}</p>
        <a href="/addons" target="_blank">打开 Addon 接入中心 →</a>
      </div>`;
    return;
  }
  target.innerHTML = addons.map(addon => {
    const tools = addon.tools || [];
    const retrievers = addon.retrievers || [];
    const taskTypes = Array.from(new Set(
      (addon.bindings || []).flatMap(binding => binding.task_types || []),
    ));
    return `
      <article class="ap-card">
        <div class="ap-card-head">
          <span class="ap-card-icon">🔌</span>
          <div class="ap-card-title"><strong>${escapeHtml(addon.name || addon.addon_id)}</strong><small>${escapeHtml(addon.addon_id)} · v${escapeHtml(addon.version || '—')}</small></div>
          <span class="ap-health ap-health--${escapeHtml(addon.health || 'unknown')}">${escapeHtml(addon.state || addon.health || 'unknown')}</span>
        </div>
        <div class="ap-contributions">
          <span>🛠 ${tools.length} 工具</span>
          <span>📚 ${retrievers.length} 检索器</span>
        </div>
        ${taskTypes.length ? `<div class="ap-tags">${taskTypes.slice(0, 5).map(item => `<span>${escapeHtml(item)}</span>`).join('')}</div>` : ''}
        <div class="ap-card-detail">${addon.runtime_admitted ? '已进入 Agent · ' : '仅登记 · '}${escapeHtml([...tools, ...retrievers].slice(0, 4).join(' · ') || '尚未声明贡献')}</div>
      </article>`;
  }).join('');
}

async function loadAddonPanel(force = false): Promise<void> {
  if (catalogLoaded && !force) return;
  const statusText = document.getElementById('apRuntimeStatus');
  const runtimeMode = document.getElementById('apRuntimeMode');
  const contributionCount = document.getElementById('apContributionCount');
  if (statusText) statusText.textContent = '正在连接运行时…';
  try {
    const [statusResponse, catalogResponse] = await Promise.all([
      csrfFetch('/api/plugin-protocol'),
      csrfFetch('/api/plugin-protocol/catalog'),
    ]);
    if (!statusResponse.ok || !catalogResponse.ok) {
      throw new Error('Addon API 返回异常');
    }
    const status = await statusResponse.json();
    const catalog = await catalogResponse.json();
    const addons: AddonCatalogItem[] = catalog.addons || [];
    catalogLoaded = true;
    if (statusText) statusText.textContent = status.runtime?.execution ? '运行时已就绪' : '运行时未启用';
    if (runtimeMode) runtimeMode.textContent = status.runtime?.task_routing ? '任务路由开启' : '仅协议校验';
    if (contributionCount) {
      contributionCount.textContent = String(addons.reduce(
        (sum, addon) => sum + (addon.tools?.length || 0) + (addon.retrievers?.length || 0),
        0,
      ));
    }
    renderAddonCatalog(addons, catalog.message || '');
  } catch (error: any) {
    if (statusText) statusText.textContent = '运行时连接失败';
    renderAddonCatalog([], error.message || '无法读取 Addon 状态');
  }
}

function initAddonPanel(): void {
  const title = document.getElementById('capabilityPanelTitle');
  const manage = document.getElementById('capabilityManageLink') as HTMLAnchorElement | null;
  if (title) title.textContent = 'Addon 能力';
  if (manage) {
    manage.href = '/addons';
    manage.title = '打开 Addon 管理中心';
    manage.textContent = '⤢ Addon 管理';
  }
  document.getElementById('apRefreshButton')?.addEventListener('click', () => {
    catalogLoaded = false;
    void loadAddonPanel(true);
  });
  void loadAddonPanel();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initAddonPanel, { once: true });
} else {
  initAddonPanel();
}

export { initAddonPanel, loadAddonPanel };
