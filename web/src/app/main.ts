/**
 * Koto Main Module — app initialization, boot sequence, core utilities
 */

import { csrfFetch } from '../shared/csrf';
import { debugLog } from '../shared/debug';
import { closeActiveSidePanel } from '../shared/side-panels';

// ── Event listener lifecycle ──
let _appDocListeners: Array<{ type: string; listener: EventListener; options?: any }> = [];
const _appOrigAdd = document.addEventListener.bind(document);
const _appOrigRemove = document.removeEventListener.bind(document);

document.addEventListener = function(type: string, listener: EventListener, options?: any) {
  _appDocListeners.push({ type, listener, options });
  return _appOrigAdd(type, listener, options);
};
document.removeEventListener = function(type: string, listener: EventListener, options?: any) {
  _appDocListeners = _appDocListeners.filter(e => !(e.type === type && e.listener === listener));
  return _appOrigRemove(type, listener, options);
};

(window as any)._cleanupAppListeners = function() {
  let c = 0;
  while (_appDocListeners.length) {
    const e = _appDocListeners.pop()!;
    try { _appOrigRemove(e.type, e.listener, e.options); c++; } catch (_) { /* allowed to fail */ }
  }
  document.addEventListener = function(type: string, listener: EventListener, options?: any) {
    _appDocListeners.push({ type, listener, options });
    return _appOrigAdd(type, listener, options);
  };
  if (c) debugLog('App', 'Cleaned up ' + c + ' listeners');
};

// ── Safe DOM helper ──
function $appEl(id: string | HTMLElement): HTMLElement | null {
  const el = typeof id === 'string' ? document.getElementById(id) : id;
  if (!el && typeof id === 'string' && id.length > 0) console.warn('[App] Missing element: #' + id);
  return el as HTMLElement | null;
}

// ── Global state initialization ──
(window as any).currentSession = null;
(window as any).selectedFiles = [];
(window as any).setupComplete = false;
(window as any).lockedTaskType = null;
(window as any).selectedModel = 'auto';
(window as any).enableMiniGame = true;
(window as any).isScrollLocked = false;

// ── Window controls ──
export async function minimizeWindow(): Promise<void> {
  if ((window as any).pywebview && (window as any).pywebview.api && (window as any).pywebview.api.minimize) {
    await (window as any).pywebview.api.minimize();
  }
}

export async function maximizeWindow(): Promise<void> {
  if ((window as any).pywebview && (window as any).pywebview.api && (window as any).pywebview.api.maximize) {
    await (window as any).pywebview.api.maximize();
  }
}

export async function closeWindow(): Promise<void> {
  if ((window as any).WA && typeof (window as any).WA.getUnsavedTabs === 'function') {
    const unsaved = (window as any).WA.getUnsavedTabs();
    if (unsaved.length > 0) {
      let decision: string = 'discard';
      if (typeof (window as any).WA.showCloseWarning === 'function') {
        decision = await (window as any).WA.showCloseWarning(unsaved);
      } else {
        const names = unsaved.map((t: any) => t.name).join('\n  - ');
        const ok = confirm(`文件助手中有未保存的文件：\n  - ${names}\n\n直接关闭将丢失修改，是否继续？`);
        decision = ok ? 'discard' : 'cancel';
      }
      if (decision === 'cancel') return;
    }
  }
  if ((window as any).pywebview && (window as any).pywebview.api && (window as any).pywebview.api.close) {
    await (window as any).pywebview.api.close();
  } else {
    window.close();
  }
}

// ── Escape HTML ──


// ── KotoDialog ──
interface KotoDialogOptions {
  title?: string;
  message?: string;
  type?: 'info' | 'warn' | 'error';
  input?: boolean;
  inputValue?: string;
  inputPlaceholder?: string;
  confirmText?: string;
  cancelText?: string | null;
  onConfirm?: (val?: any) => void;
  onCancel?: () => void;
}

export function KotoDialog(options: KotoDialogOptions): void {
  const existing = document.querySelector('.koto-dialog-overlay');
  if (existing) existing.remove();
  const overlay = document.createElement('div');
  overlay.className = 'koto-dialog-overlay';
  const dlg = document.createElement('div');
  dlg.className = 'koto-dialog';
  const iconMap: Record<string, string> = { info: '💬', warn: '⚠️', error: '❌' };
  const icon = iconMap[options.type || 'info'] || '💬';
  let inputHTML = '';
  if (options.input) {
    inputHTML = `<input class="koto-dialog-input" placeholder="${escHtml(options.inputPlaceholder || '')}" value="${escHtml(options.inputValue || '')}">`;
  }
  dlg.innerHTML = `<div class="koto-dialog-icon">${icon}</div><div class="koto-dialog-title">${escHtml(options.title || '提示')}</div><div class="koto-dialog-msg">${escHtml(options.message || '')}</div>${inputHTML}<div class="koto-dialog-btns">${options.cancelText !== null ? `<button class="koto-dialog-cancel">${escHtml(options.cancelText || '取消')}</button>` : ''}<button class="koto-dialog-confirm">${escHtml(options.confirmText || '确定')}</button></div>`;
  overlay.appendChild(dlg);
  document.body.appendChild(overlay);
  requestAnimationFrame(() => overlay.classList.add('koto-dialog-visible'));
  const inputEl = dlg.querySelector('.koto-dialog-input') as HTMLInputElement | null;
  const close = (confirmed: boolean) => {
    overlay.classList.remove('koto-dialog-visible');
    setTimeout(() => overlay.remove(), 250);
    if (confirmed && options.onConfirm) options.onConfirm(inputEl ? inputEl.value : true);
    if (!confirmed && options.onCancel) options.onCancel();
  };
  (dlg.querySelector('.koto-dialog-confirm') as HTMLElement).onclick = () => close(true);
  const cancelBtn = dlg.querySelector('.koto-dialog-cancel') as HTMLElement | null;
  if (cancelBtn) cancelBtn.onclick = () => close(false);
  overlay.onclick = (e: Event) => { if (e.target === overlay) close(false); };
  if (inputEl) { inputEl.focus(); inputEl.onkeydown = (e: KeyboardEvent) => { if (e.key === 'Enter') close(true); if (e.key === 'Escape') close(false); }; }
  document.addEventListener('keydown', function _kd(e: KeyboardEvent) { if (e.key === 'Escape') { close(false); document.removeEventListener('keydown', _kd); } });
}

export function kotoAlert(msg: string, title?: string): Promise<void> {
  return new Promise(r => KotoDialog({ title: title || '提示', message: msg, type: 'info', cancelText: null, onConfirm: r }));
}

export function kotoConfirm(msg: string, title?: string): Promise<boolean> {
  return new Promise(r => KotoDialog({ title: title || '确认', message: msg, type: 'warn', onConfirm: () => r(true), onCancel: () => r(false) }));
}

export function kotoPrompt(msg: string, defaultValue?: string): Promise<string | null> {
  return new Promise(r => KotoDialog({ title: '输入', message: msg, input: true, inputValue: defaultValue || '', onConfirm: (v: string) => r(v), onCancel: () => r(null) }));
}

// ── Notification ──
export function showNotification(message: string, type: string = 'info', duration: number = 3000): void {
  let stack = document.getElementById('notificationStack');
  if (!stack) {
    stack = document.createElement('div');
    stack.id = 'notificationStack';
    document.body.appendChild(stack);
  }
  const notification = document.createElement('div');
  notification.className = `notification notification-${type}`;
  notification.innerHTML = `<span>${escHtml(message)}</span><button class="notif-dismiss" onclick="this.parentElement.remove()" title="关闭">×</button>`;
  stack.appendChild(notification);
  setTimeout(() => {
    if (notification.parentElement) { notification.classList.add('notif-hiding'); setTimeout(() => notification.remove(), 300); }
  }, duration);
}

// ── Startup splash ──
export function hideStartupSplash(): void {
  const splash = document.getElementById('startupSplash');
  if (!splash) return;
  splash.classList.add('hidden');
  setTimeout(() => splash.remove(), 300);
  document.body.classList.remove('loading');
}

// ── Folder Browser ──
export async function loadFolderList(path: string): Promise<void> {
  try {
    const resp = await fetch('/api/browse?path=' + encodeURIComponent(path));
    const data = await resp.json();
    const listEl = document.getElementById('folderList');
    if (!listEl) return;
    (window as any).currentBrowsePath = path;
    const manualInput = document.getElementById('manualPathInput') as HTMLInputElement | null;
    if (manualInput) manualInput.value = path;
    const folders = data.folders || [];
    if (data.error) {
      listEl.innerHTML = `<div style="padding:20px;text-align:center;color:var(--accent-danger);">${escHtml(data.error)}</div>`;
      return;
    }
    if (!folders.length) {
      listEl.innerHTML = '<div style="padding:20px;text-align:center;color:var(--text-muted);">此文件夹为空</div>';
      return;
    }
    const parent = data.parent ? `<div class="folder-path-row" onclick="loadFolderList('${String(data.parent).replace(/\\/g, '\\\\').replace(/'/g, "\\'")}')" style="cursor:pointer;padding:6px 10px;color:var(--accent-primary);">.. 上一级</div>` : '<div class="folder-path-row" onclick="loadFolderDrives()" style="cursor:pointer;padding:6px 10px;color:var(--accent-primary);">磁盘与快速访问</div>';
    listEl.innerHTML = parent + folders.map((entry: any) => {
        const safePath = String(entry.path || '').replace(/\\/g, '\\\\').replace(/'/g, "\\'");
        return `<div class="folder-entry" onclick="loadFolderList('${safePath}')" ondblclick="selectFolderEntry('${safePath}')" style="cursor:pointer;padding:6px 10px;display:flex;align-items:center;gap:8px;"><span>📁</span><span style="flex:1;">${escHtml(entry.name || '')}</span><button onclick="event.stopPropagation();selectFolderEntry('${safePath}')" style="padding:2px 8px;font-size:11px;">选择</button></div>`;
      }).join('');
  } catch (e) { /* ignore */ }
}

export async function loadFolderDrives(): Promise<void> {
  try {
    const resp = await fetch('/api/browse/drives');
    const data = await resp.json();
    const listEl = document.getElementById('folderList');
    if (!listEl) return;
    const drives = (data.drives || []).map((d: any) => typeof d === 'string' ? { name: d, path: d } : d);
    const quick = data.quick_access || [];
    const entries = [...quick, ...drives];
    listEl.innerHTML = entries.map((entry: any) => {
      const path = String(entry.path || entry.name || '').replace(/\\/g, '\\\\').replace(/'/g, "\\'");
      const icon = entry.type === 'quick' ? '📁' : '💽';
      return `<div class="folder-entry drive-entry" onclick="loadFolderList('${path}')" style="cursor:pointer;padding:8px 10px;"><span>${icon}</span><span>${escHtml(entry.name || entry.path || '')}</span></div>`;
    }).join('');
  } catch (e) { /* ignore */ }
}

export function selectFolderEntry(path: string): void {
  if ((window as any).currentBrowseTarget === 'setup_workspace') {
    const input = document.getElementById('setupWorkspacePath') as HTMLInputElement | null;
    if (input) input.value = path;
  }
  const manualInput = document.getElementById('manualPathInput') as HTMLInputElement | null;
  if (manualInput) manualInput.value = path;
}

export function confirmFolderSelection(): void {
  const path = (document.getElementById('manualPathInput') as HTMLInputElement)?.value || '';
  if ((window as any).currentBrowseTarget === 'setup_workspace') {
    const input = document.getElementById('setupWorkspacePath') as HTMLInputElement | null;
    if (input) input.value = path;
  }
  const modal = document.getElementById('folderModal');
  if (modal) modal.classList.remove('active');
}

// ── Shell compatibility actions ──
export async function switchToMiniMode(): Promise<void> {
  try {
    const response = await csrfFetch('/api/window/switch-to-mini', { method: 'POST' });
    const data = await response.json();
    if (data.success) return;
  } catch (error) {
    console.warn('[switchToMiniMode] HTTP fallback:', error);
  }
  if ((window as any).pywebview?.api?.switch_to_mini) {
    try { await (window as any).pywebview.api.switch_to_mini(); return; } catch {}
  }
  document.body.style.transition = 'opacity 0.15s ease-out';
  document.body.style.opacity = '0';
  setTimeout(() => { window.location.href = '/mini'; }, 150);
}

export function chatSearchNavKey(event: KeyboardEvent): void {
  if (event.key === 'Enter') {
    event.preventDefault();
    if (event.shiftKey && typeof (window as any).chatSearchPrev === 'function') (window as any).chatSearchPrev();
    else if (typeof (window as any).chatSearchNext === 'function') (window as any).chatSearchNext();
  } else if (event.key === 'Escape' && typeof (window as any).closeChatSearch === 'function') {
    (window as any).closeChatSearch();
  }
}

// ── Artifacts Panel ──
const currentArtifact: { code: string; lang: string; title: string } = { code: '', lang: 'plaintext', title: 'Artifact' };

export function openArtifactPanel(): void {
  const panel = document.getElementById('artifactsPanel');
  if (!panel) return;
  panel.classList.toggle('active');
}

export function closeArtifactPanel(): void {
  const panel = document.getElementById('artifactsPanel');
  if (panel) panel.classList.remove('active');
}

export function switchArtifactTab(tab: 'preview' | 'code'): void {
  document.querySelectorAll('.artifact-tab-btn').forEach(btn => btn.classList.toggle('active', (btn as HTMLElement).dataset.tab === tab));
  const previewEl = document.getElementById('artifactPreview');
  const codeEl = document.getElementById('artifactCode');
  if (previewEl) previewEl.style.display = tab === 'preview' ? '' : 'none';
  if (codeEl) codeEl.style.display = tab === 'code' ? '' : 'none';
  if (tab === 'preview') renderArtifactPreview();
  else renderArtifactCode();
}

function renderArtifactPreview(): void {
  const el = document.getElementById('artifactPreview');
  if (!el) return;
  const { code, lang } = currentArtifact;
  if (['html', 'htm'].includes(lang)) {
    el.innerHTML = '<iframe sandbox="allow-scripts allow-same-origin" style="width:100%;height:calc(100vh - 100px);border:none;border-radius:8px;background:#fff;"></iframe>';
    const iframe = el.querySelector('iframe') as HTMLIFrameElement | null;
    if (iframe) iframe.srcdoc = code;
    return;
  }
  if (lang === 'svg' || code.trim().startsWith('<svg')) {
    el.innerHTML = `<div style="text-align:center;padding:20px;">${code}</div>`;
    return;
  }
  el.innerHTML = `<pre style="white-space:pre-wrap;margin:0;">${escHtml(code)}</pre>`;
}

function renderArtifactCode(): void {
  const el = document.getElementById('artifactCode');
  if (!el) return;
  el.innerHTML = `<textarea class="artifact-editor" spellcheck="false" style="width:100%;height:calc(100vh - 140px);background:var(--code-bg);color:var(--code-text);border:none;padding:18px;font-family:monospace;font-size:13px;line-height:1.6;resize:none;outline:none;">${escHtml(currentArtifact.code)}</textarea>`;
  const textarea = el.querySelector('textarea') as HTMLTextAreaElement | null;
  if (textarea) textarea.oninput = () => { currentArtifact.code = textarea.value; };
}

export async function copyArtifactContent(): Promise<void> {
  try {
    await navigator.clipboard.writeText(currentArtifact.code || '');
    showNotification('已复制 Artifact', 'success', 1500);
  } catch (error: any) {
    showNotification('复制失败: ' + (error.message || error), 'error');
  }
}

export function downloadArtifact(): void {
  const extMap: Record<string, string> = { python: 'py', javascript: 'js', typescript: 'ts', html: 'html', css: 'css', json: 'json', markdown: 'md', svg: 'svg' };
  const ext = extMap[currentArtifact.lang] || 'txt';
  const blob = new Blob([currentArtifact.code || ''], { type: 'text/plain;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `artifact.${ext}`;
  a.click();
  URL.revokeObjectURL(url);
}

export function closeArtifacts(): void {
  closeArtifactPanel();
}

// ── Proactive UI ──
export function initProactiveUI(): void {
  // Initialize proactive UI elements if present
}

// ── Send Rating ──
export async function sendRating(msgId: string, userMsg: string, assistantMsg: string, taskType: string, rating: string, btn: HTMLElement): Promise<void> {
  try {
    const resp = await csrfFetch('/api/response/rate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        msg_id: msgId,
        stars: rating === 'up' ? 5 : 1,
        session_name: (window as any).currentSession || 'default',
        user_input: userMsg,
        ai_response: assistantMsg,
        task_type: taskType || 'CHAT',
      }),
    });
    const data = await resp.json();
    if (data.success) {
      btn.classList.add('rated');
      setTimeout(() => btn.classList.remove('rated'), 1500);
    }
  } catch (e) { /* ignore */ }
}

// ── Memory Management ──
export async function loadMemories(): Promise<void> {
  const listEl = document.getElementById('memoryList');
  if (!listEl) return;
  listEl.innerHTML = '<div class="memory-empty">正在加载记忆...</div>';
  try {
    const response = await fetch('/api/memories');
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const memories = await response.json();
    renderMemories(memories);
  } catch (e: any) {
    listEl.innerHTML = `<div class="memory-empty" style="color:var(--accent-danger)">加载失败: ${e.message}</div>`;
  }
}

function renderMemories(memories: any[]): void {
  const listEl = document.getElementById('memoryList');
  if (!listEl) return;
  if (!memories || memories.length === 0) {
    listEl.innerHTML = '<div class="memory-empty">暂无长期记忆。Koto 会自动记住重要信息，或手动添加。</div>';
    return;
  }
  listEl.innerHTML = memories.map((m: any) => `<div class="memory-item"><div class="memory-content"><div>${escHtml(m.content)}</div><div class="memory-meta">${m.created_at} · ${m.category}</div></div><button class="memory-delete-btn" onclick="deleteMemory(${m.id})" title="忘记"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg></button></div>`).join('');
}

export async function addNewMemory(): Promise<void> {
  const input = document.getElementById('newMemoryInput') as HTMLInputElement;
  const content = input.value.trim();
  if (!content) return;
  try {
    const response = await csrfFetch('/api/memories', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ content, category: 'user_preference' }) });
    if (response.ok) { input.value = ''; loadMemories(); }
    else { showNotification(`添加失败 (${response.status})`, 'error'); }
  } catch (e: any) { showNotification(`添加失败: ${e.message}`, 'error'); }
}

export async function deleteMemory(id: number): Promise<void> {
  if (!confirm('确定要忘记这条记忆吗？')) return;
  try {
    const response = await csrfFetch(`/api/memories/${id}`, { method: 'DELETE' });
    if (response.ok) { loadMemories(); } else { showNotification(`删除失败 (${response.status})`, 'error'); }
  } catch (e: any) { showNotification(`删除失败: ${e.message}`, 'error'); }
}

export async function importProfileMemories(): Promise<void> {
  const btn = document.querySelector('[onclick="importProfileMemories()"]') as HTMLButtonElement | null;
  const origText = btn ? btn.textContent : '';
  if (btn) { btn.disabled = true; btn.textContent = '⏳ 导入中...'; }
  try {
    const response = await csrfFetch('/api/memories/import-profile', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
    const result = await response.json();
    if (result.success) { loadMemories(); if (btn) { btn.textContent = `✅ 导入了 ${result.added} 条`; } setTimeout(() => { if (btn) { btn.disabled = false; btn.textContent = origText; } }, 3000); }
    else { showNotification(`导入失败: ${result.error || '未知错误'}`, 'error'); if (btn) { btn.disabled = false; btn.textContent = origText; } }
  } catch (e: any) { showNotification(`导入失败: ${e.message}`, 'error'); if (btn) { btn.disabled = false; btn.textContent = origText; } }
}

export async function batchExtractMemories(): Promise<void> {
  const btn = document.querySelector('[onclick="batchExtractMemories()"]') as HTMLButtonElement | null;
  const origText = btn ? btn.textContent : '';
  if (btn) { btn.disabled = true; btn.textContent = '⏳ 提取中（约30秒）...'; }
  try {
    const response = await csrfFetch('/api/memories/batch-extract', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ max_turns: 60, max_files: 10 }) });
    const result = await response.json();
    if (result.success) {
      if (btn) { btn.textContent = '✅ 后台提取中...'; }
      setTimeout(() => { loadMemories(); if (btn) { btn.disabled = false; btn.textContent = origText; } }, 30000);
    } else { showNotification(`提取失败: ${result.error || '未知错误'}`, 'error'); if (btn) { btn.disabled = false; btn.textContent = origText; } }
  } catch (e: any) { showNotification(`提取失败: ${e.message}`, 'error'); if (btn) { btn.disabled = false; btn.textContent = origText; } }
}

// ── Shadow Memory ──
export async function loadShadowMemories(): Promise<void> {
  const listEl = document.getElementById('shadowMemoryList');
  if (!listEl) return;
  listEl.innerHTML = '<div class="memory-empty" style="font-size:12px;color:var(--text-muted);">正在加载...</div>';
  try {
    const resp = await fetch('/api/shadow/memories');
    if (!resp.ok) throw new Error('HTTP ' + resp.status);
    const data = await resp.json();
    if (!data.ok) throw new Error(data.error || '加载失败');
    renderShadowMemories(data.data || []);
  } catch (e: any) { listEl.innerHTML = `<div class="memory-empty" style="font-size:12px;color:var(--accent-danger)">加载失败: ${e.message}</div>`; }
}

function renderShadowMemories(memories: any[]): void {
  const listEl = document.getElementById('shadowMemoryList');
  if (!listEl) return;
  if (!memories || memories.length === 0) { listEl.innerHTML = '<div class="memory-empty" style="font-size:12px;color:var(--text-muted);">暂无影子记忆。</div>'; return; }
  const sorted = [...memories].sort((a, b) => (b.created_at || '').localeCompare(a.created_at || ''));
  listEl.innerHTML = sorted.map((m: any) => `<div class="memory-item"><div><div>${escHtml(m.content)}</div><div>${escHtml(m.created_at || '')} · ${m.source === 'shadow' ? '🤖 自动' : '✍️ 手动'} · ${escHtml(m.category || '')}</div></div><button onclick="deleteShadowMemory('${m.id}')">✕</button></div>`).join('');
}

export async function deleteShadowMemory(id: string): Promise<void> {
  try {
    await csrfFetch(`/api/shadow/memories/${id}`, { method: 'DELETE' });
    loadShadowMemories();
  } catch (e) { /* ignore */ }
}

export async function addShadowMemory(): Promise<void> {
  const input = document.getElementById('newShadowMemoryInput') as HTMLInputElement;
  const content = input.value.trim();
  if (!content) return;
  try {
    const resp = await csrfFetch('/api/shadow/memories', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ content }) });
    if (resp.ok) { input.value = ''; loadShadowMemories(); } else { showNotification('添加失败', 'error'); }
  } catch (e) { showNotification('添加失败', 'error'); }
}

// ── Shadow Watcher ──
let _shadowPending: any[] = [];
let _shadowCurrentIdx: number = 0;
let _pendingShadowContext: any = null;

export async function shadowPollPending(): Promise<void> {
  try {
    const resp = await fetch('/api/shadow/pending');
    if (!resp.ok) return;
    const data = await resp.json();
    if (!data.ok) return;
    _shadowPending = data.data || [];
    _shadowCurrentIdx = 0;
    _shadowUpdateBanner();
    _shadowUpdateBadge();
  } catch (e) { /* ignore */ }
}

function _shadowUpdateBadge(): void {
  const badge = document.getElementById('shadowBadge');
  if (!badge) return;
  const count = _shadowPending.length;
  badge.textContent = String(count);
  badge.style.display = count > 0 ? '' : 'none';
}

function _shadowUpdateBanner(): void {
  const banner = document.getElementById('shadowBanner');
  if (!banner) return;
  if (!_shadowPending.length) { banner.style.display = 'none'; const rb = document.getElementById('shadowRetryBtn'); if (rb) rb.remove(); return; }
  const msg = _shadowPending[_shadowCurrentIdx];
  if (!msg) return;
  banner.style.display = 'flex';
  const textEl = document.getElementById('shadowBannerText'); if (textEl) textEl.textContent = msg.content;
  const countEl = document.getElementById('shadowBannerCount');
  const hasMulti = _shadowPending.length > 1;
  if (countEl) countEl.textContent = hasMulti ? `消息 ${_shadowCurrentIdx + 1} / ${_shadowPending.length}` : '';
  const navBtns = banner.querySelectorAll('button');
  navBtns.forEach(btn => { if (btn.textContent === '‹' || btn.textContent === '›') btn.style.display = hasMulti ? '' : 'none'; });
  banner.dataset.msgId = msg.id;
  const existingRetryBtn = document.getElementById('shadowRetryBtn');
  if (existingRetryBtn) existingRetryBtn.remove();
  if (msg.type === 'failed_retry' && msg.task_id) {
    const retryBtn = document.createElement('button');
    retryBtn.id = 'shadowRetryBtn';
    retryBtn.textContent = '🔄 立即重试';
    retryBtn.style.cssText = 'padding:4px 12px;border:none;border-radius:6px;background:#10b981;color:#fff;cursor:pointer;font-size:12px;flex-shrink:0;';
    retryBtn.addEventListener('click', () => shadowRetryFailedTask(msg.task_id, msg.id));
    banner.appendChild(retryBtn);
  }
}

export async function shadowRetryFailedTask(taskId: string, msgId: string): Promise<void> {
  try {
    const resp = await fetch(`/api/shadow/retry-context/${encodeURIComponent(taskId)}`);
    const data = await resp.json();
    if (!data.ok || !data.data?.original_text) { showNotification('获取不到原始请求内容', 'warning'); return; }
    const originalText = data.data.original_text;
    try { await csrfFetch(`/api/shadow/dismiss/${msgId}`, { method: 'POST' }); } catch (e) {}
    _shadowPending = _shadowPending.filter(m => m.id !== msgId);
    _shadowCurrentIdx = Math.min(_shadowCurrentIdx, Math.max(0, _shadowPending.length - 1));
    _shadowUpdateBanner(); _shadowUpdateBadge();
    const inputEl = document.getElementById('messageInput') as HTMLInputElement | null;
    if (inputEl) { inputEl.value = originalText; inputEl.dispatchEvent(new Event('input')); setTimeout(() => document.getElementById('sendBtn')?.click(), 80); }
    else { showNotification('请在对话框中重新输入：' + originalText.slice(0, 60), 'info', 5000); }
  } catch (e) { showNotification('重试失败', 'error'); }
}

export function shadowNextMsg(): void {
  if (_shadowPending.length < 2) return;
  _shadowCurrentIdx = (_shadowCurrentIdx + 1) % _shadowPending.length;
  _shadowUpdateBanner();
}

export function shadowPrevMsg(): void {
  if (_shadowPending.length < 2) return;
  _shadowCurrentIdx = (_shadowCurrentIdx - 1 + _shadowPending.length) % _shadowPending.length;
  _shadowUpdateBanner();
}

export async function shadowDismissCurrent(): Promise<void> {
  const banner = document.getElementById('shadowBanner');
  const msgId = banner?.dataset?.msgId;
  if (!msgId) return;
  try { await csrfFetch(`/api/shadow/dismiss/${msgId}`, { method: 'POST' }); } catch (e) {}
  _shadowPending = _shadowPending.filter(m => m.id !== msgId);
  _shadowCurrentIdx = Math.min(_shadowCurrentIdx, Math.max(0, _shadowPending.length - 1));
  _shadowUpdateBanner(); _shadowUpdateBadge();
}

export async function shadowDismissAll(): Promise<void> {
  try { await csrfFetch('/api/shadow/dismiss-all', { method: 'POST' }); } catch (e) {}
  _shadowPending = []; _shadowUpdateBanner(); _shadowUpdateBadge();
}

export function shadowReply(): void {
  const banner = document.getElementById('shadowBanner');
  const msgId = banner?.dataset?.msgId;
  const msg = _shadowPending.find(m => m.id === msgId);
  if (!msg) return;
  _pendingShadowContext = { id: msg.id, content: msg.content, type: msg.type };
  _showShadowReplyHint(msg.content);
  const input = document.getElementById('messageInput') as HTMLInputElement | null;
  if (input) { input.value = ''; input.focus(); }
  shadowDismissCurrent();
}

function _showShadowReplyHint(content: string): void { /* UI hint rendering */ }

export function _cancelShadowReply(): void { _pendingShadowContext = null; const hint = document.getElementById('shadowReplyHint'); if (hint) hint.remove(); }

export function openShadowPanel(): void {
  if (typeof (window as any).openSettings === 'function') {
    (window as any).openSettings();
    setTimeout(() => { const el = document.querySelector('.settings-section:has(#shadowWatcherToggle)'); if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' }); }, 200);
  }
}

export async function loadShadowStatus(): Promise<void> {
  try {
    const resp = await fetch('/api/shadow/status');
    if (!resp.ok) return;
    const data = await resp.json();
    if (!data.ok) return;
    const s = data.data;
    const toggle = document.getElementById('shadowWatcherToggle') as HTMLInputElement | null;
    const label = document.getElementById('shadowWatcherLabel');
    if (toggle) toggle.checked = !!s.enabled;
    if (label) label.textContent = s.enabled ? '影子追踪已开启' : '影子追踪已关闭';
    const cardsEl = document.getElementById('shadowSummaryCards');
    if (cardsEl) {
      cardsEl.style.display = '';
      const topics = (s.top_topics || []).map((t: any) => `<span style="background:var(--bg-hover);border-radius:4px;padding:2px 6px;font-size:11px;">${escHtml(t.topic)} ×${t.count}</span>`).join(' ');
      cardsEl.innerHTML = `<div style="display:flex;flex-wrap:wrap;gap:10px;font-size:12px;color:var(--text-muted);"><span>📊 已观察 <strong>${s.total_observations || 0}</strong> 次对话</span><span>🔥 连续 <strong>${s.streak_days || 0}</strong> 天</span><span>📌 开放任务 <strong>${s.open_tasks_count || 0}</strong> 项</span><span>💬 待推送 <strong>${s.pending_messages || 0}</strong> 条</span></div>${topics ? `<div style="margin-top:6px;display:flex;flex-wrap:wrap;gap:4px;">${topics}</div>` : ''}`;
    }
    await loadShadowOpenTasks();
    await loadShadowMemories();
  } catch (e) { /* ignore */ }
}

export async function toggleShadowWatcher(enabled: boolean): Promise<void> {
  const label = document.getElementById('shadowWatcherLabel');
  try {
    const resp = await csrfFetch('/api/shadow/toggle', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled }) });
    const data = await resp.json();
    if (!data.ok) throw new Error(data.error || '操作失败');
    if (label) label.textContent = enabled ? '影子追踪已开启' : '影子追踪已关闭';
  } catch (e: any) {
    showNotification('切换失败: ' + e.message, 'error');
    const toggle = document.getElementById('shadowWatcherToggle') as HTMLInputElement | null;
    if (toggle) toggle.checked = !enabled;
  }
}

export async function shadowForceTick(): Promise<void> {
  try {
    const resp = await csrfFetch('/api/shadow/tick', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ force: true }) });
    const data = await resp.json();
    if (!data.ok) throw new Error(data.error || '检查失败');
    const count = (data.data?.messages || []).length;
    if (count > 0) { await shadowPollPending(); showNotification(`✅ 检查完成，生成 ${count} 条主动消息。`, 'success'); }
    else { showNotification('✅ 检查完成，当前暂无需要主动推送的内容。', 'info'); }
    await loadShadowStatus();
  } catch (e: any) { showNotification('检查失败: ' + e.message, 'error'); }
}

export async function loadShadowOpenTasks(): Promise<void> {
  const el = document.getElementById('shadowOpenTasksList');
  if (!el) return;
  try {
    const resp = await fetch('/api/shadow/open-tasks');
    const data = await resp.json();
    if (!data.ok || !data.data?.length) { el.innerHTML = ''; return; }
    el.innerHTML = data.data.slice(0, 5).map((t: any) => `<div style="display:flex;align-items:center;gap:6px;margin-top:4px;font-size:12px;"><span>📌</span><span style="flex:1;">${escHtml(t.text.slice(0, 60))}${t.text.length > 60 ? '…' : ''}</span><button onclick="shadowMarkTaskDone('${t.id}')">✓</button></div>`).join('');
  } catch (e) { el.innerHTML = ''; }
}

export async function shadowMarkTaskDone(taskId: string): Promise<void> {
  try { await csrfFetch(`/api/shadow/dismiss-task/${taskId}`, { method: 'POST' }); await loadShadowOpenTasks(); await loadShadowStatus(); } catch (e) { /* ignore */ }
}

// ── Key handlers ──
export function handleKeyDown(event: KeyboardEvent): void {
  const slash = document.getElementById('slashPalette');
  if (slash && slash.style.display !== 'none') {
    const items = [...slash.querySelectorAll('.slash-item')];
    if (event.key === 'ArrowDown') { event.preventDefault(); /* handled in chat-ui */ return; }
    if (event.key === 'ArrowUp') { event.preventDefault(); /* handled in chat-ui */ return; }
    if (event.key === 'Escape') { if (typeof (window as any).hideSlashPalette === 'function') (window as any).hideSlashPalette(); return; }
  }
  const suggest = document.getElementById('atFileSuggest');
  if (suggest && suggest.style.display !== 'none') {
    if (event.key === 'Escape') { if (typeof (window as any).hideAtSuggest === 'function') (window as any).hideAtSuggest(); return; }
  }
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    sendMessage(event);
  }
}

// ── Global shortcuts ──
export function handleGlobalKeyDown(e: KeyboardEvent): void {
  if (document.querySelector('.modal-overlay.active')) return;
  if (e.key === 'Escape' && closeActiveSidePanel()) { e.preventDefault(); return; }
  if (e.key === 'Escape' && (window as any).currentSession && typeof (window as any).isSessionGenerating === 'function' && (window as any).isSessionGenerating((window as any).currentSession)) {
    e.preventDefault(); document.getElementById('sendBtn')?.click(); return;
  }
  if ((e.ctrlKey || e.metaKey) && e.key === 'k') { e.preventDefault(); if (typeof (window as any).showNewSessionModal === 'function') (window as any).showNewSessionModal(); return; }
  if ((e.ctrlKey || e.metaKey) && e.key === 'b') { e.preventDefault(); if (typeof (window as any).toggleSidebar === 'function') (window as any).toggleSidebar(); return; }
  if ((e.ctrlKey || e.metaKey) && e.key === ',') { e.preventDefault(); if (typeof (window as any).openSettings === 'function') (window as any).openSettings(); return; }
  if ((e.ctrlKey || e.metaKey) && e.key === '/') { e.preventDefault(); if (typeof (window as any).toggleHotkeySheet === 'function') (window as any).toggleHotkeySheet(); return; }
  if ((e.ctrlKey || e.metaKey) && e.key === 'f') {
    if ((document.activeElement as HTMLElement)?.id !== 'messageInput') {
      e.preventDefault();
      const hasMessages = document.querySelectorAll('#chatMessages .message').length > 0;
      if (hasMessages) { if (typeof (window as any).openChatSearch === 'function') (window as any).openChatSearch(); }
      else { if (typeof (window as any).toggleSidebarSearch === 'function') (window as any).toggleSidebarSearch(); }
    }
    return;
  }
}

// ── Agent Confirmation Dialogs ──
export async function showAgentConfirmDialog(toolName: string, toolArgs: any, reason: string): Promise<{ confirmed: boolean; message: string }> {
  return new Promise((resolve) => {
    const TIMEOUT = 60;
    let remaining = TIMEOUT;
    const overlay = document.createElement('div');
    overlay.className = 'agent-dialog-overlay';
    const dialog = document.createElement('div');
    dialog.className = 'agent-confirm-dialog';
    const argsHtml = Object.entries(toolArgs).map(([key, value]) => `<div><strong>${key}:</strong> ${escHtml(String(value))}</div>`).join('');
    dialog.innerHTML = `<h3 style="margin-top:0;">🤖 Agent需要确认</h3><p>${escHtml(reason || '即将执行以下操作：')}</p><div class="agent-args"><div class="tool-label" style="margin-bottom:8px;">🔧 工具: ${escHtml(toolName)}</div><div>${argsHtml}</div></div><div class="agent-confirm-countdown" id="confirm-countdown">${remaining}s 后自动跳过</div><div style="display:flex;gap:12px;justify-content:flex-end;margin-top:16px;"><button id="agent-confirm-no" style="padding:8px 20px;border-radius:6px;border:1px solid var(--border-color);background:transparent;cursor:pointer;">取消</button><button id="agent-confirm-yes" style="padding:8px 20px;border-radius:6px;border:none;background:#4CAF50;color:white;font-weight:bold;cursor:pointer;">确认执行</button></div>`;
    overlay.appendChild(dialog);
    document.body.appendChild(overlay);
    const cleanup = () => { if (document.body.contains(overlay)) document.body.removeChild(overlay); };
    const timer = setInterval(() => {
      remaining--;
      const countdownEl = document.getElementById('confirm-countdown'); if (countdownEl) countdownEl.textContent = `${remaining}s 后自动跳过`;
      if (remaining <= 0) { clearInterval(timer); cleanup(); resolve({ confirmed: false, message: `⏰ 确认超时，已跳过 \`${toolName}\`` }); }
    }, 1000);
    const yesBtn = document.getElementById('agent-confirm-yes'); const noBtn = document.getElementById('agent-confirm-no');
    if (yesBtn) yesBtn.onclick = () => { clearInterval(timer); cleanup(); resolve({ confirmed: true, message: `✅ 已确认执行 \`${toolName}\`` }); };
    if (noBtn) noBtn.onclick = () => { clearInterval(timer); cleanup(); resolve({ confirmed: false, message: `❌ 已取消 \`${toolName}\`` }); };
    overlay.onclick = (e: Event) => { if (e.target === overlay) { clearInterval(timer); cleanup(); resolve({ confirmed: false, message: `❌ 已取消 \`${toolName}\`` }); } };
  });
}

export async function showAgentChoiceDialog(question: string, options: Array<{ label: string; value: string }>): Promise<{ displayText: string; selected: string | null } | null> {
  return new Promise((resolve) => {
    const overlay = document.createElement('div');
    overlay.className = 'agent-dialog-overlay';
    const dialog = document.createElement('div');
    dialog.className = 'agent-choice-dialog';
    const optionsHtml = options.map((opt, idx) => `<button class="agent-choice-option" data-value="${escHtml(opt.value)}">${idx + 1}. ${escHtml(opt.label)}</button>`).join('');
    dialog.innerHTML = `<h3 style="margin-top:0;">🤖 Agent需要您的选择</h3><p>${escHtml(question)}</p><div>${optionsHtml}</div><div style="text-align:center;margin-top:16px;"><button id="agent-choice-cancel">取消</button></div>`;
    overlay.appendChild(dialog);
    document.body.appendChild(overlay);
    dialog.querySelectorAll('.agent-choice-option').forEach((btn, idx) => {
      (btn as HTMLElement).onclick = () => { const selected = options[idx]; document.body.removeChild(overlay); resolve({ displayText: `✅ 您选择了: **${selected.label}**`, selected: selected.value }); };
    });
    const cancelBtn = document.getElementById('agent-choice-cancel'); if (cancelBtn) cancelBtn.onclick = () => { document.body.removeChild(overlay); resolve({ displayText: `❌ 已取消选择`, selected: '__cancelled__' }); };
    overlay.onclick = (e: Event) => { if (e.target === overlay) { document.body.removeChild(overlay); resolve(null); } };
  });
}

// ── Meeting Actions ──
export async function extractMeetingActions(): Promise<void> {
  const transcript = prompt('请粘贴会议转录/纪要文本（建议 300 字以上）:');
  if (!transcript || !transcript.trim()) return;
  const btn = document.getElementById('meetingActionsBtn') as HTMLButtonElement | null;
  try {
    if (btn) { btn.disabled = true; btn.textContent = '⏳ 提取中'; }
    const resp = await csrfFetch('/api/speech/extract-actions', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text: transcript }) });
    const data = await resp.json();
    if (!resp.ok || !data.success) throw new Error(data.error || '行动项提取失败');
    const summary = (data.summary || '').trim();
    const decisions = Array.isArray(data.decisions) ? data.decisions : [];
    const actions = Array.isArray(data.action_items) ? data.action_items : [];
    const esc = (s: string) => (s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    let actionsHtml = '';
    if (actions.length) {
      actionsHtml = '<table class="meeting-actions-table"><thead><tr><th>任务</th><th>负责人</th><th>截止日期</th><th>优先级</th></tr></thead><tbody>' +
        actions.map((item: any) => `<tr><td>${esc(item.task || '')}</td><td>${esc(item.owner || '待定')}</td><td>${esc(item.due_date || '待定')}</td><td>${(item.priority || 'medium').toLowerCase() === 'high' ? '高' : (item.priority || 'medium').toLowerCase() === 'low' ? '低' : '中'}</td></tr>`).join('') + '</tbody></table>';
    }
    const html = `<div class="meeting-actions-card"><div class="meeting-actions-header">📝 会议提炼结果</div><div><strong>摘要</strong><p>${esc(summary)}</p></div>${decisions.length ? '<div><strong>关键决策</strong><ul>' + decisions.map((d: string) => `<li>${esc(d)}</li>`).join('') + '</ul></div>' : ''}<div><strong>行动项</strong>${actionsHtml || '（未提取到）'}</div></div>`;
    const msgDiv = document.createElement('div'); msgDiv.className = 'message assistant-message'; msgDiv.innerHTML = html;
    const chatMessages = document.getElementById('chatMessages'); const welcome = document.getElementById('welcomeScreen');
    if (welcome) welcome.style.display = 'none';
    if (chatMessages) chatMessages.appendChild(msgDiv);
    if (typeof (window as any).scrollToBottomForce === 'function') (window as any).scrollToBottomForce();
    showNotification('会议行动项提取完成', 'success', 1800);
  } catch (err: any) { showNotification(`会议提炼失败: ${err.message || err}`, 'error', 2600); }
  finally { if (btn) { btn.disabled = false; btn.textContent = '📝 会议提炼'; } }
}

export async function createReminderFromAction(task: string, dueDate: string, btnEl?: HTMLElement): Promise<void> {
  let isoTime: string | null = null;
  const dateMatch = dueDate && dueDate.match(/(\d{4})-(\d{2})-(\d{2})/);
  if (dateMatch) isoTime = `${dateMatch[0]}T09:00:00`;
  try {
    if (btnEl) { (btnEl as HTMLButtonElement).disabled = true; btnEl.textContent = '⏳'; }
    const body: any = { title: `📋 ${task}`, message: `会议行动项：${task}（截止：${dueDate}）`, icon: 'task' };
    if (isoTime) body.time = isoTime; else body.seconds = 3600;
    const resp = await csrfFetch('/api/reminders/add', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    const data = await resp.json();
    if (!resp.ok || !data.success) throw new Error(data.error || '添加失败');
    if (btnEl) { btnEl.textContent = '✅ 已创建'; btnEl.classList.add('reminder-done'); }
    showNotification(`提醒已创建：${task}`, 'success', 2000);
  } catch (err: any) { if (btnEl) { (btnEl as HTMLButtonElement).disabled = false; btnEl.textContent = '📅 创建提醒'; } showNotification(`创建提醒失败: ${err.message}`, 'error'); }
}

// ── Morning Brief ──
export async function generateMorningBrief(): Promise<void> {
  try {
    const btn = document.getElementById('morningBriefBtn') as HTMLButtonElement | null;
    if (btn) { btn.disabled = true; btn.textContent = '⏳ 生成中'; }
    const resp = await fetch('/api/telegram/brief/preview');
    const data = await resp.json();
    if (!resp.ok || data.error || !data.brief) throw new Error(data.error || '简报生成失败');
    const chatMessages = document.getElementById('chatMessages'); const welcome = document.getElementById('welcomeScreen');
    if (welcome) welcome.style.display = 'none';
    if (chatMessages) chatMessages.insertAdjacentHTML('beforeend', (window as any).renderMessage?.('assistant', data.brief, { task: 'MORNING_BRIEF' }) || '');
    if (typeof (window as any).scrollToBottomForce === 'function') (window as any).scrollToBottomForce();
    showNotification('晨间简报已生成', 'success', 1800);
  } catch (err: any) { showNotification(`晨间简报生成失败: ${err.message || err}`, 'error', 2600); }
  finally { const btn = document.getElementById('morningBriefBtn') as HTMLButtonElement | null; if (btn) { btn.disabled = false; btn.textContent = '🌅 简报'; } }
}

// ── Document Suggestions ──
const suggestionState: { filePath: string; suggestions: any[]; abort?: AbortController | null } = {
  filePath: '',
  suggestions: [],
  abort: null,
};

export function openSuggestionPanel(filePath: string, requirement: string): void {
  const panel = document.getElementById('suggestionPanelModal');
  if (!panel) return;
  panel.style.display = 'flex';
  loadSuggestions(filePath, requirement);
}

export async function loadSuggestions(filePath: string, requirement: string): Promise<void> {
  suggestionState.filePath = filePath;
  suggestionState.suggestions = [];
  if (suggestionState.abort) suggestionState.abort.abort();
  suggestionState.abort = new AbortController();
  const list = document.getElementById('suggestionList');
  const progress = document.getElementById('suggestionProgressText');
  const fill = document.getElementById('suggestionProgressFill') as HTMLElement | null;
  if (list) list.innerHTML = '<div class="suggestion-empty"><p>正在分析文档...</p></div>';
  if (progress) progress.textContent = '准备分析...';
  if (fill) fill.style.width = '0%';
  try {
    const resp = await csrfFetch('/api/document/suggest-stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ file_path: filePath, requirement }),
      signal: suggestionState.abort.signal,
    });
    if (!resp.ok) throw new Error('HTTP ' + resp.status);
    if (!resp.body) throw new Error('浏览器不支持流式响应');
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const events = buffer.split('\n\n');
      buffer = events.pop() || '';
      for (const raw of events) handleSuggestionSse(raw);
    }
    renderSuggestionList();
    if (progress) progress.textContent = suggestionState.suggestions.length ? '分析完成' : '暂无修改建议';
    if (fill) fill.style.width = '100%';
  } catch (e: any) {
    if (e.name === 'AbortError') return;
    if (list) list.innerHTML = `<div class="suggestion-empty"><p>分析失败：${escHtml(e.message || String(e))}</p></div>`;
  }
}

export function applySuggestion(action: string): void { /* apply suggestion action */ }

function handleSuggestionSse(raw: string): void {
  const lines = raw.split('\n');
  let eventType = '';
  let eventData = '';
  for (const line of lines) {
    if (line.startsWith('event: ')) eventType = line.slice(7).trim();
    else if (line.startsWith('data: ')) eventData += line.slice(6);
  }
  if (!eventData) return;
  let data: any;
  try { data = JSON.parse(eventData); } catch { return; }
  const progress = document.getElementById('suggestionProgressText');
  const fill = document.getElementById('suggestionProgressFill') as HTMLElement | null;
  if (eventType === 'progress') {
    if (progress) progress.textContent = data.message || data.status || '分析中...';
    if (fill && data.progress != null) fill.style.width = `${Math.max(0, Math.min(100, Number(data.progress)))}%`;
    return;
  }
  if (eventType === 'suggestion' || data.suggestion) {
    const item = data.suggestion || data;
    item.id = item.id || `suggestion-${suggestionState.suggestions.length + 1}`;
    item.accepted = item.accepted !== false;
    suggestionState.suggestions.push(item);
    renderSuggestionList();
  }
}

function renderSuggestionList(): void {
  const list = document.getElementById('suggestionList');
  if (!list) return;
  if (!suggestionState.suggestions.length) {
    list.innerHTML = '<div class="suggestion-empty"><p>暂无修改建议</p></div>';
    return;
  }
  list.innerHTML = suggestionState.suggestions.map((s, index) => {
    const title = s.title || s.type || `建议 ${index + 1}`;
    const original = s.original_text || s.original || s['原文'] || '';
    const replacement = s.suggested_text || s.replacement || s['修改'] || '';
    const reason = s.reason || s.description || s.explanation || '';
    return `<div class="suggestion-card ${s.accepted ? 'accepted' : 'rejected'}" id="suggestion-${escHtml(s.id)}"><div class="suggestion-title">${escHtml(title)}</div><div class="suggestion-desc">${escHtml(reason)}</div>${original ? `<div class="suggestion-desc">原文：${escHtml(original)}</div>` : ''}${replacement ? `<div class="suggestion-desc">修改：${escHtml(replacement)}</div>` : ''}<div class="suggestion-actions"><button class="btn-sm btn-accept ${s.accepted ? 'active' : ''}" onclick="acceptSuggestion('${escHtml(s.id)}')">接受</button><button class="btn-sm btn-reject ${!s.accepted ? 'active' : ''}" onclick="rejectSuggestion('${escHtml(s.id)}')">拒绝</button></div></div>`;
  }).join('');
}

export function acceptSuggestion(id: string): void {
  const item = suggestionState.suggestions.find(s => String(s.id) === String(id));
  if (item) { item.accepted = true; renderSuggestionList(); }
}

export function rejectSuggestion(id: string): void {
  const item = suggestionState.suggestions.find(s => String(s.id) === String(id));
  if (item) { item.accepted = false; renderSuggestionList(); }
}

export function acceptAllSuggestions(): void {
  suggestionState.suggestions.forEach(s => { s.accepted = true; });
  renderSuggestionList();
}

export function rejectAllSuggestions(): void {
  suggestionState.suggestions.forEach(s => { s.accepted = false; });
  renderSuggestionList();
}

export function closeSuggestionPanel(): void {
  if (suggestionState.abort) suggestionState.abort.abort();
  document.getElementById('suggestionPanelModal')!.style.display = 'none';
}

export async function applySuggestions(): Promise<void> {
  const accepted = suggestionState.suggestions.filter(s => s.accepted);
  if (!accepted.length) {
    showNotification('请先选择要接受的修改', 'warning');
    return;
  }
  try {
    const resp = await csrfFetch('/api/document/apply-suggestions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ file_path: suggestionState.filePath, suggestions: accepted }),
    });
    const result = await resp.json();
    if (!resp.ok || !result.success) throw new Error(result.error || '应用失败');
    showNotification(`已应用 ${result.applied_count || accepted.length} 处修改`, 'success', 4000);
    closeSuggestionPanel();
  } catch (error: any) {
    showNotification('应用失败: ' + (error.message || error), 'error');
  }
}

const PROACTIVE_USER_ID = 'default';

export function openTriggerPanel(): void {
  const modal = document.getElementById('triggerPanelModal');
  if (modal) modal.style.display = 'flex';
}

export function closeTriggerPanel(): void {
  const modal = document.getElementById('triggerPanelModal');
  if (modal) modal.style.display = 'none';
}

export async function startTriggerMonitoring(): Promise<void> {
  const interval = parseInt(((document.getElementById('triggerIntervalInput') as HTMLInputElement | null)?.value || '300'), 10) || 300;
  try {
    await fetch('/api/triggers/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: PROACTIVE_USER_ID, interval }),
    });
    showNotification('触发监控已启动', 'success', 1500);
  } catch (error: any) {
    showNotification('启动失败: ' + (error.message || error), 'error');
  }
}

export async function stopTriggerMonitoring(): Promise<void> {
  try {
    await csrfFetch('/api/triggers/stop', { method: 'POST' });
    showNotification('触发监控已停止', 'warning', 1500);
  } catch (error: any) {
    showNotification('停止失败: ' + (error.message || error), 'error');
  }
}

export async function runTriggerEvaluation(): Promise<void> {
  const decisionEl = document.getElementById('triggerDecision');
  if (decisionEl) decisionEl.textContent = '评估中...';
  try {
    const response = await csrfFetch('/api/triggers/evaluate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: PROACTIVE_USER_ID, execute: false }),
    });
    const data = await response.json();
    if (!response.ok || data.success === false) throw new Error(data.error || '评估失败');
    const decision = data.decision || data.data || {};
    if (decisionEl) {
      decisionEl.innerHTML = decision.reason
        ? `<strong>${escHtml(decision.reason)}</strong><br>类型: ${escHtml(decision.interaction_type || '')} · 优先级: ${escHtml(decision.priority || '')}`
        : '暂无触发结果';
    }
  } catch (error: any) {
    if (decisionEl) decisionEl.textContent = '评估失败: ' + (error.message || error);
  }
}

// ── Catalog Schedule Wizard ──
export function openCatalogWizard(): void {
  const modal = document.getElementById('catalogWizardModal') || document.getElementById('catalogScheduleModal');
  if (modal) modal.style.display = 'flex';
}

export function closeCatalogWizard(): void {
  const modal = document.getElementById('catalogWizardModal') || document.getElementById('catalogScheduleModal');
  if (modal) modal.style.display = 'none';
}

export const closeCatalogScheduleWizard = closeCatalogWizard;

export async function saveCatalogScheduleWizard(): Promise<void> {
  const sourceDir = ((document.getElementById('cwSourceDir') as HTMLInputElement | null)?.value || '').trim();
  const hours = Math.max(1, parseInt(((document.getElementById('cwIntervalHours') as HTMLInputElement | null)?.value || '6'), 10) || 6);
  if (!sourceDir) { showNotification('请输入要整理的目录路径', 'warning'); return; }
  try {
    const resp = await csrfFetch('/api/jobs/triggers', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: '下载目录自动整理',
        trigger_type: 'interval',
        job_type: 'auto_catalog',
        job_payload: { source_dir: sourceDir },
        enabled: true,
        config: { interval_seconds: hours * 3600 },
      }),
    });
    const data = await resp.json();
    if (!resp.ok || data.ok === false) throw new Error(data.error || '创建失败');
    closeCatalogWizard();
    if (typeof (window as any).loadTriggers === 'function') await (window as any).loadTriggers();
    showNotification('定时整理已启用', 'success');
  } catch (error: any) {
    showNotification('启用失败: ' + (error.message || error), 'error');
  }
}

export async function openCreateBindingModal(): Promise<void> {
  const select = document.getElementById('cbSkillId') as HTMLSelectElement | null;
  if (select) {
    let skills: any[] = [];
    if (typeof (window as any).getSpSkills === 'function') skills = (window as any).getSpSkills() || [];
    if (!skills.length) {
      try {
        const resp = await fetch('/api/skills');
        const data = await resp.json();
        skills = data.skills || data.data || [];
      } catch {}
    }
    select.innerHTML = skills.map(skill => `<option value="${escHtml(skill.id)}">${escHtml((skill.icon || '') + ' ' + (skill.name || skill.id))}</option>`).join('') || '<option value="">请先加载 Skill 列表</option>';
  }
  const patterns = document.getElementById('cbPatterns') as HTMLInputElement | null;
  const turns = document.getElementById('cbTurns') as HTMLInputElement | null;
  if (patterns) patterns.value = '';
  if (turns) turns.value = '1';
  const modal = document.getElementById('createBindingModal');
  if (modal) modal.style.display = 'flex';
}

export function closeCreateBindingModal(): void {
  const modal = document.getElementById('createBindingModal');
  if (modal) modal.style.display = 'none';
}

export async function saveCreateBinding(): Promise<void> {
  const skillId = ((document.getElementById('cbSkillId') as HTMLSelectElement | null)?.value || '').trim();
  const rawPatterns = ((document.getElementById('cbPatterns') as HTMLInputElement | null)?.value || '').trim();
  const turns = parseInt(((document.getElementById('cbTurns') as HTMLInputElement | null)?.value || '1'), 10) || 1;
  const patterns = rawPatterns.split(/[,，]+/).map(s => s.trim()).filter(Boolean);
  if (!skillId) { showNotification('请选择一个 Skill', 'warning'); return; }
  if (!patterns.length) { showNotification('请至少输入一个关键词', 'warning'); return; }
  try {
    const resp = await csrfFetch(`/api/skills/${encodeURIComponent(skillId)}/bindings/intent`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ patterns, auto_disable_after_turns: turns }),
    });
    const data = await resp.json();
    if (!resp.ok || data.success === false) throw new Error(data.error || '创建失败');
    closeCreateBindingModal();
    if (typeof (window as any).loadSkillBindings === 'function') await (window as any).loadSkillBindings();
    showNotification('意图绑定已创建', 'success');
  } catch (error: any) {
    showNotification('创建失败: ' + (error.message || error), 'error');
  }
}

export function openCreateTriggerModal(): void {
  const setValue = (id: string, value: string) => { const el = document.getElementById(id) as HTMLInputElement | HTMLSelectElement | null; if (el) el.value = value; };
  setValue('ctName', '');
  setValue('ctType', 'interval');
  setValue('ctJobType', 'agent_query');
  setValue('ctQuery', '');
  setValue('ctIntervalSecs', '3600');
  setValue('ctCronTime', '09:00');
  onCreateTriggerTypeChange();
  const modal = document.getElementById('createTriggerModal');
  if (modal) modal.style.display = 'flex';
}

export function closeCreateTriggerModal(): void {
  const modal = document.getElementById('createTriggerModal');
  if (modal) modal.style.display = 'none';
}

export function onCreateTriggerTypeChange(): void {
  const type = (document.getElementById('ctType') as HTMLSelectElement | null)?.value || 'interval';
  const interval = document.getElementById('ctConfigInterval');
  const cron = document.getElementById('ctConfigCron');
  if (interval) interval.style.display = type === 'interval' ? '' : 'none';
  if (cron) cron.style.display = type === 'cron' ? '' : 'none';
}

export async function saveCreateTrigger(): Promise<void> {
  const name = ((document.getElementById('ctName') as HTMLInputElement | null)?.value || '').trim() || 'Koto 触发器';
  const triggerType = (document.getElementById('ctType') as HTMLSelectElement | null)?.value || 'interval';
  const jobType = (document.getElementById('ctJobType') as HTMLSelectElement | null)?.value || 'agent_query';
  const query = ((document.getElementById('ctQuery') as HTMLTextAreaElement | null)?.value || '').trim();
  const config = triggerType === 'interval'
    ? { interval_seconds: Math.max(60, parseInt(((document.getElementById('ctIntervalSecs') as HTMLInputElement | null)?.value || '3600'), 10) || 3600) }
    : triggerType === 'cron'
      ? { time: (document.getElementById('ctCronTime') as HTMLInputElement | null)?.value || '09:00' }
      : {};
  try {
    const resp = await csrfFetch('/api/jobs/triggers', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, trigger_type: triggerType, job_type: jobType, job_payload: query ? { query } : {}, enabled: false, config }),
    });
    const data = await resp.json();
    if (!resp.ok || data.ok === false) throw new Error(data.error || '创建失败');
    closeCreateTriggerModal();
    if (typeof (window as any).loadTriggers === 'function') await (window as any).loadTriggers();
    showNotification('触发器已创建', 'success');
  } catch (error: any) {
    showNotification('创建失败: ' + (error.message || error), 'error');
  }
}

export function openCreateSkillModal(): void {
  ['csName', 'csDesc', 'csPrompt'].forEach(id => { const el = document.getElementById(id) as HTMLInputElement | HTMLTextAreaElement | null; if (el) el.value = ''; });
  const icon = document.getElementById('csIcon') as HTMLInputElement | null;
  const category = document.getElementById('csCategory') as HTMLSelectElement | null;
  if (icon) icon.value = '🤖';
  if (category) category.value = 'custom';
  const modal = document.getElementById('createSkillModal');
  if (modal) modal.style.display = 'flex';
}

export function closeCreateSkillModal(): void {
  const modal = document.getElementById('createSkillModal');
  if (modal) modal.style.display = 'none';
}

function slugifySkillName(name: string): string {
  const ascii = name.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
  return ascii || 'custom_skill_' + Date.now();
}

export async function saveCreateSkill(): Promise<void> {
  const name = ((document.getElementById('csName') as HTMLInputElement | null)?.value || '').trim();
  const description = ((document.getElementById('csDesc') as HTMLInputElement | null)?.value || '').trim();
  const prompt = ((document.getElementById('csPrompt') as HTMLTextAreaElement | null)?.value || '').trim();
  const icon = ((document.getElementById('csIcon') as HTMLInputElement | null)?.value || '🤖').trim();
  const category = (document.getElementById('csCategory') as HTMLSelectElement | null)?.value || 'custom';
  if (!name) { showNotification('请输入技能名称', 'warning'); return; }
  try {
    const resp = await csrfFetch('/api/skillmarket/install', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        id: slugifySkillName(name),
        name,
        icon,
        description,
        category,
        prompt: prompt || `你是${name}。${description}`,
        skill_nature: 'custom',
        enabled: true,
        tags: [category],
      }),
    });
    const data = await resp.json();
    if (!resp.ok || data.success === false) throw new Error(data.error || '创建失败');
    closeCreateSkillModal();
    if (typeof (window as any).spLoadSkills === 'function') await (window as any).spLoadSkills();
    if (typeof (window as any).loadSkills === 'function') await (window as any).loadSkills();
    showNotification('Skill 已创建', 'success');
  } catch (error: any) {
    showNotification('创建失败: ' + (error.message || error), 'error');
  }
}

// ── Send Message (main entry for form submit) ──
export async function sendMessage(event: Event): Promise<void> {
  event.preventDefault();

  const input = document.getElementById('messageInput') as HTMLTextAreaElement | null;
  const sendBtn = document.getElementById('sendBtn') as HTMLButtonElement | null;
  const container = document.getElementById('chatMessages');
  if (!input || !container) return;

  const message = input.value.trim();
  const selectedFiles: File[] = Array.isArray((window as any).selectedFiles) ? (window as any).selectedFiles : [];
  let sessionName = (window as any).currentSession || '';

  if (sessionName && typeof (window as any).isSessionGenerating === 'function' && (window as any).isSessionGenerating(sessionName)) {
    sendBtn?.setAttribute('disabled', 'true');
    const controller = (window as any).getSessionAbortController?.(sessionName);
    if (controller) controller.abort();
    try {
      await fetch('/api/chat/interrupt', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session: sessionName,
          task_id: (window as any).getSessionTaskId?.(sessionName) || null,
        }),
      });
    } catch (e) { logger.warn("general", "Caught error", e) }
    if (sendBtn) sendBtn.disabled = false;
    return;
  }

  if (!message && selectedFiles.length === 0) return;

  if (!sessionName && typeof (window as any).createNewSession === 'function') {
    const generatedName = typeof (window as any).generateSessionName === 'function'
      ? (window as any).generateSessionName(message || '新对话')
      : (message || '新对话').slice(0, 24);
    await (window as any).createNewSession(generatedName);
    sessionName = (window as any).currentSession || '';
    if (sessionName && (window as any)._newlyCreatedSessions instanceof Set) {
      (window as any)._newlyCreatedSessions.add(sessionName);
    }
  }

  input.value = '';
  input.style.height = 'auto';
  const welcome = container.querySelector('.welcome-screen, #welcomeScreen') as HTMLElement | null;
  if (welcome) welcome.remove();

  const renderMessageFn = (window as any).renderMessage;
  if (typeof renderMessageFn === 'function') {
    container.insertAdjacentHTML('beforeend', renderMessageFn('user', message || '(附件)', { attachments: selectedFiles.map(f => ({ name: f.name, type: f.type, size: f.size })) }));
  }
  (window as any).scrollToBottomForce?.();

  let taskInfo: any = null;
  let taskType = (window as any).lockedTaskType || null;
  const modelToUse = (window as any).selectedModel || 'auto';

  // Client-side heuristic pre-classification — skips /api/analyze round-trip
  // for high-confidence matches, reducing perceived latency by ~200-500ms.
  const preClass = !taskType ? preClassifyTask(
    message,
    selectedFiles.length > 0,
    selectedFiles.length === 1 ? selectedFiles[0].type : (selectedFiles.length > 1 ? 'multiple' : '')
  ) : null;

  if (preClass && preClass.confidence === 'high') {
    taskType = preClass.task;
    (window as any).showLoading?.(taskType + ' 任务处理中...', '');
  } else {
    try {
      (window as any).showLoading?.('分析任务类型...', '');
      const analyzeResp = await fetch('/api/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message,
          locked_task: taskType,
          locked_model: modelToUse,
          has_file: selectedFiles.length > 0,
          file_type: selectedFiles.length === 1 ? selectedFiles[0].type : (selectedFiles.length > 1 ? 'multiple' : ''),
        }),
      });
      taskInfo = await analyzeResp.json().catch((): any => null);
      taskType = taskType || taskInfo?.task || null;
      const modelDisplay = taskInfo?.model_speed ? taskInfo.model_name + ' ' + taskInfo.model_speed : (taskInfo?.model_name || '');
      (window as any).showLoading?.(taskType + ' 任务处理中...', modelDisplay);
    } catch (_) {
      (window as any).showLoading?.('Koto 正在思考...', '');
    }
  }

  const thisSession = sessionName || (window as any).currentSession || 'default';
  const abortController = new AbortController();
  (window as any).setSessionGenerating?.(thisSession, true);
  (window as any).setSessionAbortController?.(thisSession, abortController);
  if (sendBtn) {
    sendBtn.classList.add('generating');
    sendBtn.disabled = false;
    sendBtn.title = '停止生成';
  }

  const msgId = `msg-${Date.now()}`;
  const msgDiv = document.createElement('div');
  msgDiv.className = 'message assistant';
  msgDiv.id = msgId;
  msgDiv.innerHTML = `
    <div class="message-avatar"><img src="/static/assets/koto_chat_icon.png" alt="Koto" class="avatar-img"></div>
    <div class="message-content">
      <div class="message-header">
        <span class="message-sender">Koto</span>
        <div class="message-meta"><span class="time-info" id="${msgId}-time">...</span></div>
      </div>
      <div class="message-body" id="${msgId}-body"><span class="typing-cursor">▊</span></div>
    </div>`;
  container.appendChild(msgDiv);
  (window as any).scrollToBottom?.();

  const bodyEl = document.getElementById(`${msgId}-body`) as HTMLElement | null;
  const timeEl = document.getElementById(`${msgId}-time`) as HTMLElement | null;
  const startedAt = Date.now();
  let fullText = '';

  const safeHtml = (value: any) => typeof (window as any).escapeHtml === 'function'
    ? (window as any).escapeHtml(String(value || ''))
    : escHtml(String(value || ''));
  const parse = (text: string) => {
    try {
      return typeof (window as any).parseMarkdown === 'function'
        ? (window as any).parseMarkdown(text)
        : `<div class="markdown-fallback" style="white-space:pre-wrap;">${safeHtml(text)}</div>`;
    } catch (_) {
      return `<div class="markdown-fallback" style="white-space:pre-wrap;">${safeHtml(text)}</div>`;
    }
  };
  // SSE pipeline replaces inline normalizeEvent/applyStreamEvent (extracted to shared/sse-pipeline.ts)
  const pipeline = new SseStreamRenderer({
    bodyEl: bodyEl!,
    safeHtml,
    parseMd: parse,
    onScrollToBottom: () => { (window as any).scrollToBottom?.(); },
  });
  const applyStreamEvent = (data: any) => {
    if (!bodyEl) return;
    // Sync fullText for auto-title and other consumers
    pipeline.normalizeAndApply(data);
    fullText = pipeline.fullText;
    // Delegate progress UI to global helpers
    if (data.type === 'progress') {
      (window as any).showMiniGame?.();
      (window as any).showLoading?.(data.message || '???...', data.detail || '');
    }
  };

  try {
    let response: Response;
    if (selectedFiles.length > 0) {
      const formData = new FormData();
      formData.append('session', thisSession);
      formData.append('message', message);
      formData.append('locked_task', taskType || '');
      formData.append('locked_model', modelToUse || 'auto');
      selectedFiles.forEach(file => formData.append('file', file));
      response = await fetch('/api/chat/file', { method: 'POST', body: formData, signal: abortController.signal });
      (window as any).removeFile?.();
    } else {
      const useUnifiedAgentStream = String(taskType || '').toUpperCase() === 'AGENT';
      const streamEndpoint = useUnifiedAgentStream ? '/api/agent/process-stream' : '/api/chat/stream';
      const contextFiles = Array.isArray((window as any)._kotoContextFiles) ? (window as any)._kotoContextFiles.map((f: any) => f.path) : [];
      const payload = useUnifiedAgentStream
        ? { request: message, context: { history: [] as any[] }, session_id: thisSession, model: modelToUse || 'gemini-3-flash-preview', ...(contextFiles.length ? { context_files: contextFiles } : {}) }
        : { session: thisSession, message, locked_task: taskType, locked_model: modelToUse, ...(contextFiles.length ? { context_files: contextFiles } : {}) };
      response = await fetch(streamEndpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        signal: abortController.signal,
      });
    }
    if (!response.ok) throw new Error(`HTTP ${response.status}: ${response.statusText}`);

    const contentType = response.headers.get('Content-Type') || '';
    if (!response.body || !contentType.includes('text/event-stream')) {
      const data = await response.json().catch(() => ({}));
      fullText = data.response || data.content || data.message || '';
      pipeline.reset();
      pipeline.fullText = fullText;
      if (bodyEl) pipeline.finalize();
    } else {
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let streamBuffer = '';
      let done = false;
      while (!done) {
        const chunk = await reader.read();
        done = chunk.done;
        if (chunk.value) {
          streamBuffer += decoder.decode(chunk.value, { stream: true });
          const lines = streamBuffer.split('\n');
          streamBuffer = lines.pop() || '';
          for (const line of lines) {
            if (!line.startsWith('data: ')) continue;
            const raw = line.slice(6).trim();
            if (!raw || raw === '[DONE]') { done = true; continue; }
            try { applyStreamEvent(JSON.parse(raw)); } catch (e) { logger.warn("general", "Caught error", e) }
          }
        }
      }
      if (bodyEl) pipeline.finalize();
    }
    if (timeEl) timeEl.textContent = `${Math.max(1, Math.round((Date.now() - startedAt) / 1000))}s`;
    if ((window as any)._newlyCreatedSessions instanceof Set && (window as any)._newlyCreatedSessions.has(thisSession) && typeof (window as any).autoTitleSession === 'function') {
      (window as any).autoTitleSession(thisSession, message, fullText);
    }
  } catch (error: any) {
    if (bodyEl) {
      const aborted = error?.name === 'AbortError';
      bodyEl.innerHTML = `<div class="${aborted ? 'warning-message' : 'error-message'}">${safeHtml(aborted ? '已停止生成' : `请求失败：${error?.message || error}`)}</div>`;
    }
  } finally {
    (window as any).hideLoading?.();
    (window as any).hideMiniGame?.();
    (window as any).setSessionGenerating?.(thisSession, false);
    (window as any).setSessionAbortController?.(thisSession, null);
    if (sendBtn) {
      sendBtn.classList.remove('generating');
      sendBtn.disabled = false;
      sendBtn.title = '发送';
    }
    (window as any).scrollToBottom?.();
  }
}

// ── Console init message ──
// Koto App loaded

// ── DOMContentLoaded initialization ──
document.addEventListener('DOMContentLoaded', async () => {
  if (typeof (window as any).hideStartupSplash === 'function') (window as any).hideStartupSplash();
  if (typeof (window as any).loadSettings === 'function') await (window as any).loadSettings();
  const theme = ((window as any).currentSettings?.appearance?.theme || 'light');
  if (typeof (window as any).applyTheme === 'function') (window as any).applyTheme(theme);
  if (typeof (window as any).updateThemeSelector === 'function') (window as any).updateThemeSelector(theme);
  const serverZoom = parseFloat(((window as any).currentSettings?.appearance?.ui_zoom || '1'));
  if (typeof (window as any).setUIZoom === 'function') (window as any).setUIZoom(String(serverZoom), true);
  if (typeof (window as any).renderWelcomeScreen === 'function') (window as any).renderWelcomeScreen();
  // Non-critical subsystems deferred to idle ? reduces Time-To-Interactive
  batchInit([
    () => { if (typeof (window as any).checkSetupStatus === 'function') (window as any).checkSetupStatus(); },
    () => { if (typeof (window as any)._syncSidebarState === 'function') (window as any)._syncSidebarState({ forceOpenOverlay: true }); },
    () => { if (typeof (window as any).initProjectSelector === 'function') (window as any).initProjectSelector(); },
    () => { if (typeof (window as any).loadSessions === 'function') (window as any).loadSessions(); },
    () => { if (typeof (window as any).checkStatus === 'function') (window as any).checkStatus(); },
    () => { if (typeof (window as any).initCapabilityButtons === 'function') (window as any).initCapabilityButtons(); },
  ]);
  if ((window as any).currentSettings?.ai) { (window as any).selectedModel = (window as any).currentSettings.ai.default_model || 'auto'; }
  const newSessionInput = document.getElementById('newSessionName');
  if (newSessionInput) newSessionInput.addEventListener('keydown', (e: Event) => { if ((e as KeyboardEvent).key === 'Enter') { e.preventDefault(); if (typeof (window as any).confirmNewSession === 'function') (window as any).confirmNewSession(); } });
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e: MediaQueryListEvent) => {
    if ((((window as any).currentSettings?.appearance?.theme || 'light') === 'auto') && typeof (window as any).applyTheme === 'function') (window as any).applyTheme('auto');
  });
  deferInit(() => { if (typeof (window as any).initProactiveUI === 'function') (window as any).initProactiveUI(); });
  deferInit(() => { if (typeof (window as any).initScrollBehavior === 'function') (window as any).initScrollBehavior(); });
  window.addEventListener('keydown', (e: KeyboardEvent) => { if (typeof (window as any).handleGlobalKeyDown === 'function') (window as any).handleGlobalKeyDown(e); });
  window.addEventListener('resize', () => { if (typeof (window as any)._syncSidebarState === 'function') (window as any)._syncSidebarState(); });
  document.addEventListener('click', (e: MouseEvent) => {
    const a = (e.target as HTMLElement)?.closest('a[data-ext="1"], a[href^="http://"], a[href^="https://"]');
    if (!a) return;
    const anchor = a as HTMLAnchorElement;
    if (anchor.target === '_blank' && !(window as any).pywebview) return;
    e.preventDefault();
    const url = anchor.href;
    if ((window as any).pywebview && (window as any).pywebview.api && (window as any).pywebview.api.open_url) {
      (window as any).pywebview.api.open_url(url);
    } else { window.open(url, '_blank', 'noopener,noreferrer'); }
  });
  setTimeout(() => { if (typeof (window as any).shadowPollPending === 'function') (window as any).shadowPollPending(); setInterval(() => { if (typeof (window as any).shadowPollPending === 'function') (window as any).shadowPollPending(); }, 5 * 60 * 1000); }, 3000);
});

// ── Backward compat window assignments ──

import { deferInit, batchInit } from '../shared/init-deferred';
import { SseStreamRenderer } from '../shared/sse-pipeline';
import { preClassifyTask } from '../shared/task-preclassify';
import { escHtml } from '../shared/sanitize';
import { logger } from '../shared/logger';
(window as any).hideStartupSplash = hideStartupSplash;
(window as any).showNotification = showNotification;
(window as any).KotoDialog = KotoDialog;
(window as any).kotoAlert = kotoAlert;
(window as any).kotoConfirm = kotoConfirm;
(window as any).kotoPrompt = kotoPrompt;
(window as any).handleKeyDown = handleKeyDown;
(window as any).handleGlobalKeyDown = handleGlobalKeyDown;
(window as any).minimizeWindow = minimizeWindow;
(window as any).maximizeWindow = maximizeWindow;
(window as any).closeWindow = closeWindow;
(window as any).switchToMiniMode = switchToMiniMode;
(window as any).chatSearchNavKey = chatSearchNavKey;
(window as any).loadFolderList = loadFolderList;
(window as any).loadFolderDrives = loadFolderDrives;
(window as any).selectFolderEntry = selectFolderEntry;
(window as any).confirmFolderSelection = confirmFolderSelection;
(window as any).openArtifactPanel = openArtifactPanel;
(window as any).closeArtifactPanel = closeArtifactPanel;
(window as any).switchArtifactTab = switchArtifactTab;
(window as any).copyArtifactContent = copyArtifactContent;
(window as any).downloadArtifact = downloadArtifact;
(window as any).closeArtifacts = closeArtifacts;
(window as any).initProactiveUI = initProactiveUI;
(window as any).sendRating = sendRating;
(window as any).loadMemories = loadMemories;
(window as any).addNewMemory = addNewMemory;
(window as any).deleteMemory = deleteMemory;
(window as any).importProfileMemories = importProfileMemories;
(window as any).batchExtractMemories = batchExtractMemories;
(window as any).loadShadowMemories = loadShadowMemories;
(window as any).deleteShadowMemory = deleteShadowMemory;
(window as any).addShadowMemory = addShadowMemory;
(window as any).shadowPollPending = shadowPollPending;
(window as any).shadowNextMsg = shadowNextMsg;
(window as any).shadowPrevMsg = shadowPrevMsg;
(window as any).shadowDismissCurrent = shadowDismissCurrent;
(window as any).shadowDismissAll = shadowDismissAll;
(window as any).shadowReply = shadowReply;
(window as any)._cancelShadowReply = _cancelShadowReply;
(window as any).openShadowPanel = openShadowPanel;
(window as any).loadShadowStatus = loadShadowStatus;
(window as any).toggleShadowWatcher = toggleShadowWatcher;
(window as any).shadowForceTick = shadowForceTick;
(window as any).shadowRetryFailedTask = shadowRetryFailedTask;
(window as any).loadShadowOpenTasks = loadShadowOpenTasks;
(window as any).shadowMarkTaskDone = shadowMarkTaskDone;
(window as any).showAgentConfirmDialog = showAgentConfirmDialog;
(window as any).showAgentChoiceDialog = showAgentChoiceDialog;
(window as any).extractMeetingActions = extractMeetingActions;
(window as any).createReminderFromAction = createReminderFromAction;
(window as any).generateMorningBrief = generateMorningBrief;
(window as any).openSuggestionPanel = openSuggestionPanel;
(window as any).loadSuggestions = loadSuggestions;
(window as any).applySuggestion = applySuggestion;
(window as any).acceptSuggestion = acceptSuggestion;
(window as any).rejectSuggestion = rejectSuggestion;
(window as any).acceptAllSuggestions = acceptAllSuggestions;
(window as any).rejectAllSuggestions = rejectAllSuggestions;
(window as any).closeSuggestionPanel = closeSuggestionPanel;
(window as any).applySuggestions = applySuggestions;
(window as any).openTriggerPanel = openTriggerPanel;
(window as any).closeTriggerPanel = closeTriggerPanel;
(window as any).startTriggerMonitoring = startTriggerMonitoring;
(window as any).stopTriggerMonitoring = stopTriggerMonitoring;
(window as any).runTriggerEvaluation = runTriggerEvaluation;
(window as any).openCatalogWizard = openCatalogWizard;
(window as any).closeCatalogWizard = closeCatalogWizard;
(window as any).closeCatalogScheduleWizard = closeCatalogScheduleWizard;
(window as any).saveCatalogScheduleWizard = saveCatalogScheduleWizard;
(window as any).openCreateBindingModal = openCreateBindingModal;
(window as any).closeCreateBindingModal = closeCreateBindingModal;
(window as any).saveCreateBinding = saveCreateBinding;
(window as any).openCreateTriggerModal = openCreateTriggerModal;
(window as any).closeCreateTriggerModal = closeCreateTriggerModal;
(window as any).onCreateTriggerTypeChange = onCreateTriggerTypeChange;
(window as any).saveCreateTrigger = saveCreateTrigger;
(window as any).openCreateSkillModal = openCreateSkillModal;
(window as any).closeCreateSkillModal = closeCreateSkillModal;
(window as any).saveCreateSkill = saveCreateSkill;
(window as any).sendMessage = sendMessage;
(window as any).escapeHtml = escHtml;
(window as any)._pendingShadowContext = _pendingShadowContext;
