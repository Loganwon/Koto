/**
 * Koto Main Module — app initialization, boot sequence, core utilities
 */

import { csrfFetch } from '../shared/csrf';
import { debugLog } from '../shared/debug';
import { closeModal as closeSharedModal, isModalOpen, openModal } from '../shared/modal-state';
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
if (typeof (window as any).enableMiniGame !== 'boolean') (window as any).enableMiniGame = true;
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
  dlg.innerHTML = `<div class="koto-dialog-icon">${icon}</div><div class="koto-dialog-title">${escHtml(options.title || '提示')}</div><div class="koto-dialog-msg">${escHtml(options.message || '')}</div>${inputHTML}<div class="koto-dialog-btns ui-dialog-actions">${options.cancelText !== null ? `<button class="koto-dialog-cancel ui-dialog-button secondary">${escHtml(options.cancelText || '取消')}</button>` : ''}<button class="koto-dialog-confirm ui-dialog-button primary">${escHtml(options.confirmText || '确定')}</button></div>`;
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

// ── Global shortcuts ──
export function handleGlobalKeyDown(e: KeyboardEvent): void {
  if (e.key === 'Escape' && closeActiveSkillModal()) {
    e.preventDefault();
    return;
  }
  if (document.querySelector('.modal-overlay.active')) return;
  if (e.key === 'Escape' && closeActiveSidePanel()) { e.preventDefault(); return; }
  if (e.key === 'Escape' && (window as any).currentSession && typeof (window as any).isSessionGenerating === 'function' && (window as any).isSessionGenerating((window as any).currentSession)) {
    e.preventDefault(); document.getElementById('wa-send-btn')?.click(); return;
  }
  if ((e.ctrlKey || e.metaKey) && e.key === 'k') { e.preventDefault(); if (typeof (window as any).showNewSessionModal === 'function') (window as any).showNewSessionModal(); return; }
  if ((e.ctrlKey || e.metaKey) && e.key === 'b') { e.preventDefault(); if (typeof (window as any).toggleSidebar === 'function') (window as any).toggleSidebar(); return; }
  if ((e.ctrlKey || e.metaKey) && e.key === ',') { e.preventDefault(); if (typeof (window as any).openSettings === 'function') (window as any).openSettings(); return; }
  if ((e.ctrlKey || e.metaKey) && e.key === '/') { e.preventDefault(); if (typeof (window as any).toggleHotkeySheet === 'function') (window as any).toggleHotkeySheet(); return; }
  if ((e.ctrlKey || e.metaKey) && e.key === 'f') {
    if ((document.activeElement as HTMLElement)?.id !== 'wa-user-input') {
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
    dialog.setAttribute('role', 'dialog');
    dialog.setAttribute('aria-modal', 'true');
    dialog.setAttribute('aria-labelledby', 'agent-confirm-title');
    const argsHtml = Object.entries(toolArgs).map(([key, value]) => `<div><strong>${key}:</strong> ${escHtml(String(value))}</div>`).join('');
    dialog.innerHTML = `<h3 id="agent-confirm-title" class="agent-dialog-title">🤖 Agent需要确认</h3><p>${escHtml(reason || '即将执行以下操作：')}</p><div class="agent-args"><div class="tool-label">🔧 工具: ${escHtml(toolName)}</div><div>${argsHtml}</div></div><div class="agent-confirm-countdown">${remaining}s 后自动跳过</div><div class="ui-dialog-actions"><button type="button" class="ui-dialog-button secondary" data-agent-action="cancel">取消</button><button type="button" class="ui-dialog-button primary" data-agent-action="confirm">确认执行</button></div>`;
    overlay.appendChild(dialog);
    document.body.appendChild(overlay);
    const cleanup = () => { if (document.body.contains(overlay)) document.body.removeChild(overlay); };
    const timer = setInterval(() => {
      remaining--;
      const countdownEl = dialog.querySelector('.agent-confirm-countdown'); if (countdownEl) countdownEl.textContent = `${remaining}s 后自动跳过`;
      if (remaining <= 0) { clearInterval(timer); cleanup(); resolve({ confirmed: false, message: `⏰ 确认超时，已跳过 \`${toolName}\`` }); }
    }, 1000);
    const yesBtn = dialog.querySelector('[data-agent-action="confirm"]') as HTMLButtonElement | null;
    const noBtn = dialog.querySelector('[data-agent-action="cancel"]') as HTMLButtonElement | null;
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
    dialog.setAttribute('role', 'dialog');
    dialog.setAttribute('aria-modal', 'true');
    dialog.setAttribute('aria-labelledby', 'agent-choice-title');
    const optionsHtml = options.map((opt, idx) => `<button type="button" class="agent-choice-option" data-value="${escHtml(opt.value)}">${idx + 1}. ${escHtml(opt.label)}</button>`).join('');
    dialog.innerHTML = `<h3 id="agent-choice-title" class="agent-dialog-title">🤖 Agent需要您的选择</h3><p>${escHtml(question)}</p><div class="agent-choice-options">${optionsHtml}</div><div class="ui-dialog-actions"><button type="button" class="ui-dialog-button secondary" data-agent-action="cancel">取消</button></div>`;
    overlay.appendChild(dialog);
    document.body.appendChild(overlay);
    dialog.querySelectorAll('.agent-choice-option').forEach((btn, idx) => {
      (btn as HTMLElement).onclick = () => { const selected = options[idx]; document.body.removeChild(overlay); resolve({ displayText: `✅ 您选择了: **${selected.label}**`, selected: selected.value }); };
    });
    const cancelBtn = dialog.querySelector('[data-agent-action="cancel"]') as HTMLButtonElement | null; if (cancelBtn) cancelBtn.onclick = () => { document.body.removeChild(overlay); resolve({ displayText: `❌ 已取消选择`, selected: '__cancelled__' }); };
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
const suggestionState: {
  filePath: string;
  suggestions: any[];
  abort?: AbortController | null;
  loading: boolean;
} = {
  filePath: '',
  suggestions: [],
  abort: null,
  loading: false,
};

export function openSuggestionPanel(filePath: string, requirement: string): void {
  const panel = document.getElementById('suggestionPanelModal');
  if (!panel) return;
  panel.classList.add('active');
  panel.setAttribute('aria-hidden', 'false');
  requestAnimationFrame(() => {
    (panel.querySelector('.ui-close-button') as HTMLElement | null)?.focus();
  });
  loadSuggestions(filePath, requirement);
}

function setSuggestionSummaryVisible(showStats: boolean, showFooter = showStats): void {
  document.getElementById('suggestionStats')?.toggleAttribute('hidden', !showStats);
  document.getElementById('suggestionFooter')?.toggleAttribute('hidden', !showFooter);
}

function updateSuggestionSummary(): void {
  const total = suggestionState.suggestions.length;
  const accepted = suggestionState.suggestions.filter(s => s.accepted).length;
  const rejected = total - accepted;
  const totalEl = document.getElementById('totalSuggestions');
  const acceptedEl = document.getElementById('acceptedCount');
  const rejectedEl = document.getElementById('rejectedCount');
  if (totalEl) totalEl.textContent = String(total);
  if (acceptedEl) acceptedEl.textContent = String(accepted);
  if (rejectedEl) rejectedEl.textContent = String(rejected);
  setSuggestionSummaryVisible(total > 0, total > 0 && !suggestionState.loading);
}

export async function loadSuggestions(filePath: string, requirement: string): Promise<void> {
  suggestionState.filePath = filePath;
  suggestionState.suggestions = [];
  suggestionState.loading = true;
  if (suggestionState.abort) suggestionState.abort.abort();
  suggestionState.abort = new AbortController();
  const list = document.getElementById('suggestionList');
  const progress = document.getElementById('suggestionProgressText');
  const fill = document.getElementById('suggestionProgressFill') as HTMLElement | null;
  if (list) list.innerHTML = '<div class="suggestion-empty"><p>正在分析文档...</p></div>';
  if (progress) progress.textContent = '准备分析...';
  if (fill) fill.style.width = '0%';
  setSuggestionSummaryVisible(false);
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
    suggestionState.loading = false;
    suggestionState.abort = null;
    renderSuggestionList();
    if (progress) progress.textContent = suggestionState.suggestions.length ? '分析完成' : '暂无修改建议';
    if (fill) fill.style.width = '100%';
    updateSuggestionSummary();
  } catch (e: any) {
    if (e.name === 'AbortError') return;
    suggestionState.loading = false;
    suggestionState.abort = null;
    if (list) list.innerHTML = `<div class="suggestion-empty"><p>分析失败：${escHtml(e.message || String(e))}</p></div>`;
    if (progress) progress.textContent = '分析失败';
    setSuggestionSummaryVisible(false);
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
    updateSuggestionSummary();
    return;
  }
  list.innerHTML = suggestionState.suggestions.map((s, index) => {
    const title = s.title || s.type || `建议 ${index + 1}`;
    const original = s.original_text || s.original || s['原文'] || '';
    const replacement = s.suggested_text || s.replacement || s['修改'] || '';
    const reason = s.reason || s.description || s.explanation || '';
    return `<div class="suggestion-card ${s.accepted ? 'accepted' : 'rejected'}" id="suggestion-${escHtml(s.id)}"><div class="suggestion-title">${escHtml(title)}</div><div class="suggestion-desc">${escHtml(reason)}</div>${original ? `<div class="suggestion-desc">原文：${escHtml(original)}</div>` : ''}${replacement ? `<div class="suggestion-desc">修改：${escHtml(replacement)}</div>` : ''}<div class="suggestion-actions"><button class="btn-sm btn-accept ${s.accepted ? 'active' : ''}" onclick="acceptSuggestion('${escHtml(s.id)}')">接受</button><button class="btn-sm btn-reject ${!s.accepted ? 'active' : ''}" onclick="rejectSuggestion('${escHtml(s.id)}')">拒绝</button></div></div>`;
  }).join('');
  updateSuggestionSummary();
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
  suggestionState.abort = null;
  suggestionState.loading = false;
  const panel = document.getElementById('suggestionPanelModal');
  if (!panel) return;
  panel.classList.remove('active');
  panel.setAttribute('aria-hidden', 'true');
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

// ── Catalog Schedule Wizard ──
const skillCreationModalIds = [
  'createBindingModal',
  'createSkillModal',
  'catalogWizardModal',
] as const;

function setSkillCreationModalOpen(modalId: string, open: boolean): void {
  if (open) openModal(modalId);
  else closeSharedModal(modalId);
}

function closeActiveSkillModal(): boolean {
  const activeModalId = skillCreationModalIds.find(
    modalId => isModalOpen(modalId)
  );
  if (activeModalId) {
    setSkillCreationModalOpen(activeModalId, false);
    return true;
  }
  if (isModalOpen('skillEditorModal')) {
    const closeSkillEditor = (window as any).closeSkillEditor;
    if (typeof closeSkillEditor === 'function') closeSkillEditor();
    else closeSharedModal('skillEditorModal');
    return true;
  }
  if (isModalOpen('templateUploadModal')) {
    const closeTemplateUpload = (window as any).closeTemplateUpload;
    if (typeof closeTemplateUpload === 'function') closeTemplateUpload();
    else closeSharedModal('templateUploadModal');
    return true;
  }
  return false;
}

export function openCatalogWizard(): void {
  setSkillCreationModalOpen('catalogWizardModal', true);
}

export function closeCatalogWizard(): void {
  setSkillCreationModalOpen('catalogWizardModal', false);
}

export const closeCatalogScheduleWizard = closeCatalogWizard;

export async function saveCatalogScheduleWizard(): Promise<void> {
  closeCatalogWizard();
  showNotification('定时自动整理已移除，请在需要时手动执行整理。', 'info');
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
  setSkillCreationModalOpen('createBindingModal', true);
}

export function closeCreateBindingModal(): void {
  setSkillCreationModalOpen('createBindingModal', false);
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

export function openCreateSkillModal(): void {
  ['csName', 'csDesc', 'csPrompt'].forEach(id => { const el = document.getElementById(id) as HTMLInputElement | HTMLTextAreaElement | null; if (el) el.value = ''; });
  const icon = document.getElementById('csIcon') as HTMLInputElement | null;
  const category = document.getElementById('csCategory') as HTMLSelectElement | null;
  if (icon) icon.value = '🤖';
  if (category) category.value = 'custom';
  setSkillCreationModalOpen('createSkillModal', true);
}

export function closeCreateSkillModal(): void {
  setSkillCreationModalOpen('createSkillModal', false);
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
});

// ── Backward compat window assignments ──

import { deferInit, batchInit } from '../shared/init-deferred';
import { escHtml } from '../shared/sanitize';
import { logger } from '../shared/logger';
(window as any).hideStartupSplash = hideStartupSplash;
(window as any).showNotification = showNotification;
(window as any).KotoDialog = KotoDialog;
(window as any).kotoAlert = kotoAlert;
(window as any).kotoConfirm = kotoConfirm;
(window as any).kotoPrompt = kotoPrompt;
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
(window as any).openCatalogWizard = openCatalogWizard;
(window as any).closeCatalogWizard = closeCatalogWizard;
(window as any).closeCatalogScheduleWizard = closeCatalogScheduleWizard;
(window as any).saveCatalogScheduleWizard = saveCatalogScheduleWizard;
(window as any).openCreateBindingModal = openCreateBindingModal;
(window as any).closeCreateBindingModal = closeCreateBindingModal;
(window as any).saveCreateBinding = saveCreateBinding;
(window as any).openCreateSkillModal = openCreateSkillModal;
(window as any).closeCreateSkillModal = closeCreateSkillModal;
(window as any).saveCreateSkill = saveCreateSkill;
(window as any).escapeHtml = escHtml;
