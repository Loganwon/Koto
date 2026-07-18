/**
 * Koto Marketplace Module — skills management, bindings, triggers, filehub
 */

import { csrfFetch } from '../shared/csrf';
import { closeModal, openModal } from '../shared/modal-state';

// ── Skills Management ──
let _allSkills: any[] = [];
let _currentSkillFilter: string = 'all';
let _editingSkillId: string | null = null;

const SKILL_CATEGORY_LABELS: Record<string, string> = { behavior: '⚙️ 行为', style: '🎨 风格', domain: '🔬 领域' };
const SKILL_CAT_COLORS: Record<string, string> = { behavior: '#4a9eff', style: '#e06c75', domain: '#98c379' };

const _csrfFetch = csrfFetch;

function _html(s: any): string {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function _inlineArg(s: any): string {
  return String(s ?? '').replace(/\\/g, '\\\\').replace(/'/g, "\\'").replace(/\r?\n/g, ' ');
}

export async function loadSkills(): Promise<void> {
  const listEl = document.getElementById('skillsList');
  if (!listEl) return;
  listEl.innerHTML = '<div class="memory-empty">正在加载 Skills…</div>';
  try {
    const resp = await fetch('/api/skills');
    if (!resp.ok) throw new Error('HTTP ' + resp.status);
    const data = await resp.json();
    if (!data.success) throw new Error(data.error || '加载失败');
    _allSkills = data.skills || [];
    renderSkills(_currentSkillFilter);
  } catch (e: any) {
    listEl.innerHTML = `<div class="memory-empty" style="color:var(--error-color)">⚠️ Skills 加载失败: ${e.message}</div>`;
  }
}

export function renderSkills(filter: string): void {
  _currentSkillFilter = filter;
  const listEl = document.getElementById('skillsList');
  if (!listEl || !_allSkills.length) return;
  document.querySelectorAll('.skill-tab').forEach((btn: Element) => {
    const btnFilter = (btn.textContent || '').includes('行为') ? 'behavior' : (btn.textContent || '').includes('风格') ? 'style' : (btn.textContent || '').includes('领域') ? 'domain' : 'all';
    btn.classList.toggle('active', btnFilter === filter);
  });
  const filtered = filter === 'all' ? _allSkills : _allSkills.filter(s => s.category === filter);
  if (!filtered.length) { listEl.innerHTML = '<div class="memory-empty">该分类暂无 Skill</div>'; return; }
  listEl.innerHTML = filtered.map((skill: any) => {
    const scope = skill.task_types && skill.task_types.length ? skill.task_types.join(' · ') : '全任务类型';
    const catColor = SKILL_CAT_COLORS[skill.category] || '#aaa';
    const customTag = skill.has_custom_prompt ? '<span style="font-size:10px;color:var(--accent);margin-left:4px;">✏️已自定义</span>' : '';
    return `<div class="skill-card ${skill.enabled ? 'active' : ''}" data-id="${skill.id}" data-category="${skill.category}"><div class="skill-card-header"><span class="skill-icon">${skill.icon}</span><div class="skill-info"><span class="skill-name">${skill.name}${customTag}</span><span class="skill-scope" style="border-left:2px solid ${catColor};padding-left:5px;">${SKILL_CATEGORY_LABELS[skill.category] || skill.category} &nbsp;·&nbsp; ${scope}</span></div>${skill.is_builtin ? '' : `<button class="skill-gear-btn" onclick="event.stopPropagation();openSkillEditor('${skill.id}')" title="编辑 Prompt">⚙</button>`}<label class="toggle" title="${skill.enabled ? '点击禁用' : '点击启用'}"><input type="checkbox" ${skill.enabled ? 'checked' : ''} onchange="toggleSkill('${skill.id}', this.checked)"><span class="toggle-slider"></span></label></div><p class="skill-desc">${skill.description}</p></div>`;
  }).join('');
}

export function filterSkills(category: string): void { renderSkills(category); }

export async function toggleSkill(skillId: string, enabled: boolean): Promise<void> {
  const card = document.querySelector(`.skill-card[data-id="${skillId}"]`);
  if (card) card.classList.toggle('active', enabled);
  const skill = _allSkills.find(s => s.id === skillId);
  if (skill) skill.enabled = enabled;
  try {
    const resp = await _csrfFetch(`/api/skills/${encodeURIComponent(skillId)}/toggle`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled }) });
    const data = await resp.json();
    if (!data.success) throw new Error(data.error || '操作失败');
    if (typeof (window as any).refreshActiveSkills === 'function') (window as any).refreshActiveSkills();
  } catch (e: any) {
    if (card) card.classList.toggle('active', !enabled);
    if (skill) skill.enabled = !enabled;
    if (typeof (window as any).showNotification === 'function') (window as any).showNotification('切换失败: ' + e.message, 'error');
  }
}

// ── Skill Editor ──
const _SKE_THEMES: Record<string, Record<string, string> | null> = {
  none: null,
  mystic_purple: { '--bg-primary': '#110820', '--bg-secondary': '#1a1135', '--bg-tertiary': '#221848', '--bg-card': 'rgba(192,132,252,0.10)', '--accent-primary': '#d8a4ff', '--accent-secondary': '#f0a0ff', '--accent-gradient': 'linear-gradient(135deg,#d8a4ff,#f0a0ff)', '--border-color': 'rgba(192,132,252,0.28)', '--text-primary': '#f4ecff', '--text-secondary': '#d4b8f0', '--text-muted': '#a888cc', '--user-msg-bg': 'linear-gradient(135deg,rgba(192,132,252,0.28),rgba(232,121,249,0.22))', '--assistant-msg-bg': 'rgba(192,132,252,0.13)' },
  ocean_blue: { '--bg-primary': '#0d1b2e', '--bg-secondary': '#112240', '--bg-tertiary': '#1a3050', '--bg-card': 'rgba(56,189,248,0.09)', '--accent-primary': '#38bdf8', '--accent-secondary': '#7dd3fc', '--accent-gradient': 'linear-gradient(135deg,#38bdf8,#818cf8)', '--border-color': 'rgba(56,189,248,0.25)', '--text-primary': '#e2f0ff', '--text-secondary': '#93c5fd', '--text-muted': '#5fa8d3', '--user-msg-bg': 'linear-gradient(135deg,rgba(56,189,248,0.22),rgba(129,140,248,0.18))', '--assistant-msg-bg': 'rgba(56,189,248,0.10)' },
  amber_gold: { '--bg-primary': '#0c0e14', '--bg-secondary': '#13161f', '--bg-tertiary': '#1a1e2e', '--bg-card': 'rgba(251,191,36,0.08)', '--accent-primary': '#fbbf24', '--accent-secondary': '#f59e0b', '--accent-gradient': 'linear-gradient(135deg,#fbbf24,#f97316)', '--border-color': 'rgba(251,191,36,0.22)', '--text-primary': '#f0ead6', '--text-secondary': '#d4b483', '--text-muted': '#8a7355', '--user-msg-bg': 'linear-gradient(135deg,rgba(251,191,36,0.20),rgba(249,115,22,0.15))', '--assistant-msg-bg': 'rgba(251,191,36,0.08)' },
  rose_pink: { '--bg-primary': '#1a0e14', '--bg-secondary': '#241018', '--bg-tertiary': '#2e1520', '--bg-card': 'rgba(244,114,182,0.09)', '--accent-primary': '#f472b6', '--accent-secondary': '#fb7185', '--accent-gradient': 'linear-gradient(135deg,#f472b6,#fb7185)', '--border-color': 'rgba(244,114,182,0.25)', '--text-primary': '#fce7f3', '--text-secondary': '#f9a8d4', '--text-muted': '#a0527a', '--user-msg-bg': 'linear-gradient(135deg,rgba(244,114,182,0.22),rgba(251,113,133,0.16))', '--assistant-msg-bg': 'rgba(244,114,182,0.09)' },
  cyan_space: { '--bg-primary': '#0a0f1a', '--bg-secondary': '#0f1726', '--bg-tertiary': '#162035', '--bg-card': 'rgba(34,211,238,0.08)', '--accent-primary': '#22d3ee', '--accent-secondary': '#67e8f9', '--accent-gradient': 'linear-gradient(135deg,#22d3ee,#818cf8)', '--border-color': 'rgba(34,211,238,0.22)', '--text-primary': '#e0f7ff', '--text-secondary': '#a5f3fc', '--text-muted': '#4fa8bf', '--user-msg-bg': 'linear-gradient(135deg,rgba(34,211,238,0.20),rgba(129,140,248,0.15))', '--assistant-msg-bg': 'rgba(34,211,238,0.08)' },
  forest_green: { '--bg-primary': '#0a1a10', '--bg-secondary': '#0f2218', '--bg-tertiary': '#152e1e', '--bg-card': 'rgba(52,211,153,0.09)', '--accent-primary': '#34d399', '--accent-secondary': '#6ee7b7', '--accent-gradient': 'linear-gradient(135deg,#34d399,#10b981)', '--border-color': 'rgba(52,211,153,0.22)', '--text-primary': '#e0fff0', '--text-secondary': '#a7f3d0', '--text-muted': '#4da87a', '--user-msg-bg': 'linear-gradient(135deg,rgba(52,211,153,0.20),rgba(16,185,129,0.15))', '--assistant-msg-bg': 'rgba(52,211,153,0.08)' },
  fire_red: { '--bg-primary': '#1a0a0a', '--bg-secondary': '#261010', '--bg-tertiary': '#321515', '--bg-card': 'rgba(251,146,60,0.09)', '--accent-primary': '#fb923c', '--accent-secondary': '#f97316', '--accent-gradient': 'linear-gradient(135deg,#fb923c,#dc2626)', '--border-color': 'rgba(251,146,60,0.25)', '--text-primary': '#fff1e6', '--text-secondary': '#fcd4a8', '--text-muted': '#a06040', '--user-msg-bg': 'linear-gradient(135deg,rgba(251,146,60,0.22),rgba(220,38,38,0.15))', '--assistant-msg-bg': 'rgba(251,146,60,0.08)' },
};

export function openSkillEditor(skillId: string): void {
  const spSkills = typeof (window as any).getSpSkills === 'function' ? (window as any).getSpSkills() : [];
  const skill = _allSkills.find(s => s.id === skillId) || spSkills.find((s: any) => s.id === skillId);
  if (!skill) return;
  _editingSkillId = skillId;
  const skeIcon = document.getElementById('skeIcon'); if (skeIcon) skeIcon.textContent = skill.icon || '🤖';
  const skeTitle = document.getElementById('skeTitle'); if (skeTitle) skeTitle.textContent = skill.name;
  const catLabels: Record<string, string> = { behavior: '⚙️ 行为', style: '🎨 风格', domain: '🔬 领域', custom: '🔧 自定义', workflow: '⚡ 工作流', memory: '🧠 记忆' };
  const skeMeta = document.getElementById('skeMeta'); if (skeMeta) skeMeta.textContent = (catLabels[skill.category] || skill.category) + (skill.is_builtin ? '  ·  内置 Skill' : '  ·  自定义 Skill');
  const editorContent = document.getElementById('skillEditorContent') as HTMLTextAreaElement | null;
  if (editorContent) { editorContent.value = skill.prompt || ''; skeUpdateCount(); }
  const skeAiDesc = document.getElementById('skeAiDesc') as HTMLTextAreaElement | null; if (skeAiDesc) skeAiDesc.value = '';
  const skeAiPreview = document.getElementById('skeAiPreview'); if (skeAiPreview) skeAiPreview.style.display = 'none';
  const skeExtractZone = document.getElementById('skeExtractZone'); if (skeExtractZone) skeExtractZone.style.display = 'none';
  const skeExtractMsg = document.getElementById('skeExtractMsg'); if (skeExtractMsg) skeExtractMsg.textContent = '';
  skeLoadUiTab(skill.ui_config || {}, skill.ui_extensions || {});
  skeSwitchTab('edit');
  openModal('skillEditorModal', { initialFocus: '#skillEditorContent' });
}

export function closeSkillEditor(): void {
  closeModal('skillEditorModal');
  _editingSkillId = null;
}

export function skeUpdateCount(): void {
  const el = document.getElementById('skeCharCount');
  const ta = document.getElementById('skillEditorContent') as HTMLTextAreaElement | null;
  if (el && ta) el.textContent = String(ta.value.length);
}

export function skeSwitchTab(tab: string): void {
  ['edit', 'ai', 'extract', 'ui'].forEach(t => {
    const btn = document.querySelector(`.ske-tab[data-tab="${t}"]`); if (btn) btn.classList.toggle('active', t === tab);
    const body = document.getElementById('skeTab' + t.charAt(0).toUpperCase() + t.slice(1)); if (body) body.style.display = t === tab ? 'block' : 'none';
  });
  if (tab === 'extract') skeLoadSessions();
}

export async function skeGeneratePrompt(): Promise<void> {
  const desc = ((document.getElementById('skeAiDesc') as HTMLTextAreaElement)?.value || '').trim();
  if (!desc) { if (typeof (window as any).showNotification === 'function') (window as any).showNotification('请先描述你的需求', 'warn'); return; }
  const previewEl = document.getElementById('skeAiPreview');
  const previewContent = document.getElementById('skeAiPreviewContent');
  if (previewEl) previewEl.style.display = 'block';
  if (previewContent) previewContent.textContent = '⏳ AI 正在生成…';
  try {
    const resp = await _csrfFetch('/api/skillmarket/preview-prompt', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ description: desc }) });
    const data = await resp.json();
    if (!data.success) throw new Error(data.error || '生成失败');
    if (previewContent) previewContent.textContent = data.prompt || data.system_prompt || '（空）';
  } catch (e: any) { if (previewContent) previewContent.textContent = '⚠️ ' + e.message; }
}

export function skeApplyGenerated(): void {
  const previewContent = document.getElementById('skeAiPreviewContent');
  const text = previewContent?.textContent || '';
  if (!text || text.startsWith('⏳') || text.startsWith('⚠️')) return;
  const editor = document.getElementById('skillEditorContent') as HTMLTextAreaElement | null;
  if (editor) { editor.value = text; skeUpdateCount(); }
  skeSwitchTab('edit');
}

let _skeSelectedSession: string | null = null;

export async function skeLoadSessions(): Promise<void> {
  const list = document.getElementById('skeSessionList');
  if (!list) return;
  list.innerHTML = '<div style="color:#6c7a91;font-size:12px;padding:6px;">正在加载对话列表…</div>';
  try {
    const resp = await fetch('/api/skillmarket/sessions');
    const data = await resp.json();
    const sessions = data.sessions || [];
    if (!sessions.length) { list.innerHTML = '<div style="color:#6c7a91;font-size:12px;padding:6px;">暂无对话记录，请先进行一些对话。</div>'; return; }
    list.innerHTML = sessions.map((s: any) => `<div class="ske-session-item" data-sid="${s.id}" onclick="skeSelectSession('${s.id}', this)">💬 ${s.title || s.id}<span style="float:right;color:#4a5568;font-size:10px;">${s.message_count || 0} 条</span></div>`).join('');
  } catch (e: any) { list.innerHTML = `<div style="color:#e06c75;font-size:12px;padding:6px;">⚠️ ${e.message}</div>`; }
}

export function skeSelectSession(sessionId: string, el: HTMLElement): void {
  _skeSelectedSession = sessionId;
  document.querySelectorAll('.ske-session-item').forEach(i => i.classList.remove('selected'));
  el.classList.add('selected');
  const extractZone = document.getElementById('skeExtractZone'); if (extractZone) extractZone.style.display = 'block';
  const extractMsg = document.getElementById('skeExtractMsg'); if (extractMsg) extractMsg.textContent = '';
}

export async function skeExtractFromSession(): Promise<void> {
  if (!_skeSelectedSession || !_editingSkillId) return;
  const msgEl = document.getElementById('skeExtractMsg');
  const btn = document.querySelector('#skeExtractZone .ske-extract-btn') as HTMLButtonElement | null;
  if (btn) btn.disabled = true;
  if (msgEl) { msgEl.style.color = '#6c7a91'; msgEl.textContent = '⏳ AI 正在分析对话风格…'; }
  try {
    const resp = await _csrfFetch('/api/skillmarket/from-session', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ session_id: _skeSelectedSession, skill_name: _editingSkillId, icon: '', auto_enable: false }) });
    const data = await resp.json();
    if (!data.success) throw new Error(data.error || '提取失败');
    const prompt = data.prompt || data.skill?.prompt || '';
    const editor = document.getElementById('skillEditorContent') as HTMLTextAreaElement | null;
    if (editor) { editor.value = prompt; skeUpdateCount(); }
    skeSwitchTab('edit');
    if (msgEl) msgEl.textContent = '';
  } catch (e: any) { if (msgEl) { msgEl.style.color = '#e06c75'; msgEl.textContent = '⚠️ ' + e.message; } }
  finally { if (btn) btn.disabled = false; }
}

export async function saveSkillPromptEdit(): Promise<void> {
  if (!_editingSkillId) return;
  const prompt = (document.getElementById('skillEditorContent') as HTMLTextAreaElement).value;
  try {
    const resp = await _csrfFetch(`/api/skills/${encodeURIComponent(_editingSkillId)}/prompt`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ prompt }) });
    const data = await resp.json();
    if (!data.success) throw new Error(data.error);
    const uiPayload = skeCollectUiConfig();
    const hasUiChanges = Object.keys(uiPayload.ui_config || {}).length > 0 || (uiPayload.ui_extensions?.action_buttons || []).length > 0;
    if (hasUiChanges) {
      const permissions: string[] = [];
      if (uiPayload.ui_config?.css_vars || uiPayload.ui_config?.theme) permissions.push('ui_style');
      if ((uiPayload.ui_extensions?.action_buttons || []).length > 0) permissions.push('ui_interactive');
      await _csrfFetch(`/api/skills/${encodeURIComponent(_editingSkillId)}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...uiPayload, permissions }) });
    }
    const skill = _allSkills.find(s => s.id === _editingSkillId);
    if (skill) { skill.prompt = prompt; skill.has_custom_prompt = prompt.trim() !== ''; if (hasUiChanges) { skill.ui_config = uiPayload.ui_config; skill.ui_extensions = uiPayload.ui_extensions; } }
    closeSkillEditor();
    renderSkills(_currentSkillFilter);
    if (typeof (window as any).spRenderCards === 'function') (window as any).spRenderCards();
    if (typeof (window as any).SkillUI === 'object') (window as any).SkillUI.refresh();
  } catch (e: any) { if (typeof (window as any).showNotification === 'function') (window as any).showNotification('保存失败: ' + e.message, 'error'); }
}

export async function resetSkillPromptEdit(): Promise<void> {
  if (!_editingSkillId) return;
  if (!confirm('确定恢复该 Skill 的默认 Prompt 吗？')) return;
  try {
    const resp = await _csrfFetch(`/api/skills/${encodeURIComponent(_editingSkillId)}/reset`, { method: 'POST' });
    const data = await resp.json();
    if (!data.success) throw new Error(data.error);
    const listResp = await fetch('/api/skills');
    const listData = await listResp.json();
    if (listData.success) { _allSkills = listData.skills; const skill = _allSkills.find(s => s.id === _editingSkillId); if (skill) { const editor = document.getElementById('skillEditorContent') as HTMLTextAreaElement | null; if (editor) { editor.value = skill.prompt || ''; skeUpdateCount(); } } }
    renderSkills(_currentSkillFilter);
  } catch (e: any) { if (typeof (window as any).showNotification === 'function') (window as any).showNotification('恢复失败: ' + e.message, 'error'); }
}

// ── Skill Editor UI Tab ──
export function skePickTheme(el: HTMLElement): void {
  document.querySelectorAll('#skeColorSwatches .ske-swatch').forEach(s => s.classList.remove('active'));
  el.classList.add('active');
}

export function skeLoadUiTab(uiConfig: any, uiExt: any): void {
  const cssVars = uiConfig.css_vars || {};
  let matchedKey = 'none';
  if (cssVars['--accent-primary']) {
    for (const [key, vars] of Object.entries(_SKE_THEMES)) {
      if (vars && vars['--accent-primary'] === cssVars['--accent-primary']) { matchedKey = key; break; }
    }
  }
  document.querySelectorAll('#skeColorSwatches .ske-swatch').forEach(s => {
    s.classList.toggle('active', s.getAttribute('data-theme-key') === matchedKey);
  });
  const overlayEl = document.getElementById('skeOverlayEffect') as HTMLInputElement | null; if (overlayEl) overlayEl.value = uiConfig.overlay_effect || '';
  const f = (id: string, val: string) => { const el = document.getElementById(id) as HTMLInputElement | null; if (el) el.value = val || ''; };
  f('skeTitleText', uiConfig.title_text || ''); f('skeSubtitleText', uiConfig.subtitle_text || '');
  f('skePlaceholderText', uiConfig.input_placeholder || ''); f('skeWelcomeText', uiConfig.welcome_text || '');
  f('skeAssistantPrefix', uiConfig.assistant_prefix || '');
  const buttons = (uiExt.action_buttons || []).filter((b: any) => b.id !== 'open_dice');
  const listEl = document.getElementById('skeActionBtnList'); if (listEl) { listEl.innerHTML = ''; buttons.forEach((b: any) => skeAddActionBtn(b.label || '', b.message || '')); }
}

export function skeAddActionBtn(label: string, message: string): void {
  const listEl = document.getElementById('skeActionBtnList');
  if (!listEl) return;
  const row = document.createElement('div');
  row.className = 'ske-action-btn-row';
  row.innerHTML = `<input type="text" placeholder="按钮名称" value="${_skeEsc(label || '')}"><span class="ske-action-btn-sep">→</span><input type="text" placeholder="点击后发送的消息" value="${_skeEsc(message || '')}"><button class="ske-rm-btn" title="删除" onclick="this.closest('.ske-action-btn-row').remove()">×</button>`;
  listEl.appendChild(row);
}

function _skeEsc(s: string): string { return String(s).replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }

export function skeCollectUiConfig(): any {
  const activeThemeSwatch = document.querySelector('#skeColorSwatches .ske-swatch.active');
  const themeKey = activeThemeSwatch ? activeThemeSwatch.getAttribute('data-theme-key') || 'none' : 'none';
  const cssVars = _SKE_THEMES[themeKey] || null;
  const overlay = (document.getElementById('skeOverlayEffect') as HTMLInputElement)?.value || '';
  const titleT = (document.getElementById('skeTitleText') as HTMLInputElement)?.value || '';
  const subT = (document.getElementById('skeSubtitleText') as HTMLInputElement)?.value || '';
  const phText = (document.getElementById('skePlaceholderText') as HTMLInputElement)?.value || '';
  const welcome = (document.getElementById('skeWelcomeText') as HTMLInputElement)?.value || '';
  const prefix = (document.getElementById('skeAssistantPrefix') as HTMLInputElement)?.value || '';
  const uiConfig: any = {};
  if (cssVars) uiConfig.css_vars = cssVars;
  if (overlay) uiConfig.overlay_effect = overlay;
  if (titleT) uiConfig.title_text = titleT;
  if (subT) uiConfig.subtitle_text = subT;
  if (phText) uiConfig.input_placeholder = phText;
  if (welcome) uiConfig.welcome_text = welcome;
  if (prefix) uiConfig.assistant_prefix = prefix;
  const btnRows = document.querySelectorAll('.ske-action-btn-row');
  const actionButtons: any[] = [];
  btnRows.forEach(row => {
    const inputs = row.querySelectorAll('input');
    if (inputs.length >= 2) {
      const label = (inputs[0] as HTMLInputElement).value.trim();
      const message = (inputs[1] as HTMLInputElement).value.trim();
      if (label) actionButtons.push({ id: 'btn_' + Date.now(), label, message });
    }
  });
  const uiExtensions: any = {};
  if (actionButtons.length) uiExtensions.action_buttons = actionButtons;
  return { ui_config: uiConfig, ui_extensions: uiExtensions };
}

// ── Skill Bindings ──
export async function loadSkillBindings(): Promise<void> {
  const listEl = document.getElementById('skillBindingsList');
  if (!listEl) return;
  try {
    const resp = await fetch('/api/skills/bindings?binding_type=intent');
    const data = await resp.json();
    const bindings = data.bindings || data.data || [];
    if (!bindings.length) { listEl.innerHTML = '<div class="memory-empty">暂无意向绑定</div>'; return; }
    listEl.innerHTML = bindings.map((b: any) => {
      const id = b.binding_id || b.id || '';
      const patterns = Array.isArray(b.intent_patterns) ? b.intent_patterns.join(' / ') : (b.intent || b.pattern || b.binding_type || '—');
      return `<div class="binding-card"><strong>${_html(patterns)}</strong> → ${_html(b.skill_id || '—')}<button onclick="deleteSkillBinding('${_inlineArg(id)}')" style="float:right;">✕</button></div>`;
    }).join('');
  } catch (e) { listEl.innerHTML = '<div class="memory-empty">加载失败</div>'; }
}

export async function deleteSkillBinding(bindingId: string): Promise<void> {
  try {
    await _csrfFetch(`/api/skills/bindings/${encodeURIComponent(bindingId)}`, { method: 'DELETE' });
    loadSkillBindings();
  } catch (e) { /* ignore */ }
}

// ── Backward compat ──
(window as any).loadSkills = loadSkills;
(window as any).renderSkills = renderSkills;
(window as any).filterSkills = filterSkills;
(window as any).toggleSkill = toggleSkill;
(window as any).openSkillEditor = openSkillEditor;
(window as any).closeSkillEditor = closeSkillEditor;
(window as any).skeUpdateCount = skeUpdateCount;
(window as any).skeSwitchTab = skeSwitchTab;
(window as any).skeGeneratePrompt = skeGeneratePrompt;
(window as any).skeApplyGenerated = skeApplyGenerated;
(window as any).skeLoadSessions = skeLoadSessions;
(window as any).skeSelectSession = skeSelectSession;
(window as any).skeExtractFromSession = skeExtractFromSession;
(window as any).saveSkillPromptEdit = saveSkillPromptEdit;
(window as any).resetSkillPromptEdit = resetSkillPromptEdit;
(window as any).skePickTheme = skePickTheme;
(window as any).skeLoadUiTab = skeLoadUiTab;
(window as any).skeAddActionBtn = skeAddActionBtn;
(window as any).skeCollectUiConfig = skeCollectUiConfig;
(window as any).loadSkillBindings = loadSkillBindings;
(window as any).deleteSkillBinding = deleteSkillBinding;
