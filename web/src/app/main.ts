/**
 * Koto Main Module — app initialization, boot sequence, core utilities
 */

import { csrfFetch } from '../shared/csrf';
import { debugLog } from '../shared/debug';
import { closeModal as closeSharedModal, isModalOpen, openModal } from '../shared/modal-state';
import { closeActiveSidePanel } from '../shared/side-panels';
import { appendToUiPortal } from '../shared/ui-scale';
import { getFeatureRegistry } from '../shared/feature-registry';
import { installDynamicActionController } from './dynamic-action-controller';
import { renderStartupShell, startPostPaintHydration } from '../shared/startup-sequence';

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

getFeatureRegistry()._cleanupAppListeners = function() {
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

// ── Global state initialization ──
getFeatureRegistry().currentSession = null;
getFeatureRegistry().selectedFiles = [];
getFeatureRegistry().setupComplete = false;
getFeatureRegistry().lockedTaskType = null;
getFeatureRegistry().isScrollLocked = false;

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
  if (getFeatureRegistry() && typeof getFeatureRegistry().getUnsavedTabs === 'function') {
    const unsaved = getFeatureRegistry().getUnsavedTabs();
    if (unsaved.length > 0) {
      let decision: string = 'discard';
      if (typeof getFeatureRegistry().showCloseWarning === 'function') {
        decision = await getFeatureRegistry().showCloseWarning(unsaved);
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
  appendToUiPortal(overlay);
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
    appendToUiPortal(stack);
  }
  const notification = document.createElement('div');
  notification.className = `notification notification-${type}`;
  notification.innerHTML = `<span>${escHtml(message)}</span><button class="notif-dismiss" data-koto-action="dismiss" title="关闭">×</button>`;
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
    getFeatureRegistry().currentBrowsePath = path;
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
    const parent = data.parent ? `<div class="folder-path-row" data-koto-action="load-folder" data-path="${encodeURIComponent(String(data.parent))}" style="cursor:pointer;padding:6px 10px;color:var(--accent-primary);">.. 上一级</div>` : '<div class="folder-path-row" data-koto-action="load-drives" style="cursor:pointer;padding:6px 10px;color:var(--accent-primary);">磁盘与快速访问</div>';
    listEl.innerHTML = parent + folders.map((entry: any) => {
        return `<div class="folder-entry" data-koto-action="load-folder" data-path="${encodeURIComponent(entry.path || '')}" style="cursor:pointer;padding:6px 10px;display:flex;align-items:center;gap:8px;"><span>📁</span><span style="flex:1;">${escHtml(entry.name || '')}</span><button data-koto-action="select-folder" data-path="${encodeURIComponent(entry.path || '')}" style="padding:2px 8px;font-size:11px;">选择</button></div>`;
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
      const icon = entry.type === 'quick' ? '📁' : '💽';
      return `<div class="folder-entry drive-entry" data-koto-action="load-folder" data-path="${encodeURIComponent(entry.path || '')}" style="cursor:pointer;padding:8px 10px;"><span>${icon}</span><span>${escHtml(entry.name || entry.path || '')}</span></div>`;
    }).join('');
  } catch (e) { /* ignore */ }
}

export function selectFolderEntry(path: string): void {
  if (getFeatureRegistry().currentBrowseTarget === 'setup_workspace') {
    const input = document.getElementById('setupWorkspacePath') as HTMLInputElement | null;
    if (input) input.value = path;
  }
  const manualInput = document.getElementById('manualPathInput') as HTMLInputElement | null;
  if (manualInput) manualInput.value = path;
}

export function confirmFolderSelection(): void {
  const path = (document.getElementById('manualPathInput') as HTMLInputElement)?.value || '';
  if (getFeatureRegistry().currentBrowseTarget === 'setup_workspace') {
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
    if (event.shiftKey && typeof getFeatureRegistry().chatSearchPrev === 'function') getFeatureRegistry().chatSearchPrev();
    else if (typeof getFeatureRegistry().chatSearchNext === 'function') getFeatureRegistry().chatSearchNext();
  } else if (event.key === 'Escape' && typeof getFeatureRegistry().closeChatSearch === 'function') {
    getFeatureRegistry().closeChatSearch();
  }
}import { closeArtifactPanel, closeArtifacts, copyArtifactContent, downloadArtifact, openArtifactPanel, switchArtifactTab } from './artifact-panel';
export * from './artifact-panel';


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
        session_name: getFeatureRegistry().currentSession || 'default',
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
  listEl.innerHTML = memories.map((m: any) => `<div class="memory-item"><div class="memory-content"><div>${escHtml(m.content)}</div><div class="memory-meta">${m.created_at} · ${m.category}</div></div><button class="memory-delete-btn" data-koto-action="delete-memory" data-memory-id="${Number(m.id)}" title="忘记"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg></button></div>`).join('');
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
  const btn = document.querySelector('[data-koto-action="import-profile-memories"]') as HTMLButtonElement | null;
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
  const btn = document.querySelector('[data-koto-action="batch-extract-memories"]') as HTMLButtonElement | null;
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
  if (e.key === 'Escape' && closeActiveManagedModal()) {
    e.preventDefault();
    return;
  }
  if (document.querySelector('.modal-overlay.active')) return;
  if (e.key === 'Escape' && closeActiveSidePanel()) { e.preventDefault(); return; }
  if (e.key === 'Escape' && getFeatureRegistry().currentSession && typeof getFeatureRegistry().isSessionGenerating === 'function' && getFeatureRegistry().isSessionGenerating(getFeatureRegistry().currentSession)) {
    e.preventDefault(); document.getElementById('wa-send-btn')?.click(); return;
  }
  if ((e.ctrlKey || e.metaKey) && e.key === 'k') { e.preventDefault(); if (typeof getFeatureRegistry().showNewSessionModal === 'function') getFeatureRegistry().showNewSessionModal(); return; }
  if ((e.ctrlKey || e.metaKey) && e.key === 'b') { e.preventDefault(); if (typeof getFeatureRegistry().toggleSidebar === 'function') getFeatureRegistry().toggleSidebar(); return; }
  if ((e.ctrlKey || e.metaKey) && e.key === ',') { e.preventDefault(); if (typeof getFeatureRegistry().openSettings === 'function') getFeatureRegistry().openSettings(); return; }
  if ((e.ctrlKey || e.metaKey) && e.key === '/') { e.preventDefault(); if (typeof getFeatureRegistry().toggleHotkeySheet === 'function') getFeatureRegistry().toggleHotkeySheet(); return; }
  if ((e.ctrlKey || e.metaKey) && e.key === 'f') {
    if ((document.activeElement as HTMLElement)?.id !== 'wa-user-input') {
      e.preventDefault();
      const hasMessages = document.querySelectorAll('#chatMessages .message').length > 0;
      if (hasMessages) { if (typeof getFeatureRegistry().openChatSearch === 'function') getFeatureRegistry().openChatSearch(); }
      else { if (typeof getFeatureRegistry().toggleSidebarSearch === 'function') getFeatureRegistry().toggleSidebarSearch(); }
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
    appendToUiPortal(overlay);
    const cleanup = () => overlay.remove();
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
    appendToUiPortal(overlay);
    dialog.querySelectorAll('.agent-choice-option').forEach((btn, idx) => {
      (btn as HTMLElement).onclick = () => { const selected = options[idx]; overlay.remove(); resolve({ displayText: `✅ 您选择了: **${selected.label}**`, selected: selected.value }); };
    });
    const cancelBtn = dialog.querySelector('[data-agent-action="cancel"]') as HTMLButtonElement | null; if (cancelBtn) cancelBtn.onclick = () => { overlay.remove(); resolve({ displayText: `❌ 已取消选择`, selected: '__cancelled__' }); };
    overlay.onclick = (e: Event) => { if (e.target === overlay) { overlay.remove(); resolve(null); } };
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
    if (typeof getFeatureRegistry().scrollToBottomForce === 'function') getFeatureRegistry().scrollToBottomForce();
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
    if (chatMessages) chatMessages.insertAdjacentHTML('beforeend', getFeatureRegistry().renderMessage?.('assistant', data.brief, { task: 'MORNING_BRIEF' }) || '');
    if (typeof getFeatureRegistry().scrollToBottomForce === 'function') getFeatureRegistry().scrollToBottomForce();
    showNotification('晨间简报已生成', 'success', 1800);
  } catch (err: any) { showNotification(`晨间简报生成失败: ${err.message || err}`, 'error', 2600); }
  finally { const btn = document.getElementById('morningBriefBtn') as HTMLButtonElement | null; if (btn) { btn.disabled = false; btn.textContent = '🌅 简报'; } }
}

// ── Catalog Schedule Wizard ──
const managedModalIds = ['catalogWizardModal'] as const;

function setManagedModalOpen(modalId: string, open: boolean): void {
  if (open) openModal(modalId);
  else closeSharedModal(modalId);
}

function closeActiveManagedModal(): boolean {
  const activeModalId = managedModalIds.find(
    modalId => isModalOpen(modalId)
  );
  if (activeModalId) {
    setManagedModalOpen(activeModalId, false);
    return true;
  }
  return false;
}

export function openCatalogWizard(): void {
  setManagedModalOpen('catalogWizardModal', true);
}

export function closeCatalogWizard(): void {
  setManagedModalOpen('catalogWizardModal', false);
}

export const closeCatalogScheduleWizard = closeCatalogWizard;

export async function saveCatalogScheduleWizard(): Promise<void> {
  closeCatalogWizard();
  showNotification('定时自动整理已移除，请在需要时手动执行整理。', 'info');
}

// ── Console init message ──
// Koto App loaded

// ── DOMContentLoaded initialization ──
document.addEventListener('DOMContentLoaded', () => {
  installDynamicActionController();
  renderStartupShell();
  // Non-critical subsystems deferred to idle ? reduces Time-To-Interactive
  batchInit([
    () => { if (typeof getFeatureRegistry().checkSetupStatus === 'function') getFeatureRegistry().checkSetupStatus(); },
    () => { if (typeof getFeatureRegistry()._syncSidebarState === 'function') getFeatureRegistry()._syncSidebarState({ forceOpenOverlay: true }); },
    () => { if (typeof getFeatureRegistry().initProjectSelector === 'function') getFeatureRegistry().initProjectSelector(); },
    () => { if (typeof getFeatureRegistry().loadSessions === 'function') getFeatureRegistry().loadSessions(); },
    () => { if (typeof getFeatureRegistry().checkStatus === 'function') getFeatureRegistry().checkStatus(); },
    () => { if (typeof getFeatureRegistry().initCapabilityButtons === 'function') getFeatureRegistry().initCapabilityButtons(); },
  ]);
  const newSessionInput = document.getElementById('newSessionName');
  if (newSessionInput) newSessionInput.addEventListener('keydown', (e: Event) => { if ((e as KeyboardEvent).key === 'Enter') { e.preventDefault(); if (typeof getFeatureRegistry().confirmNewSession === 'function') getFeatureRegistry().confirmNewSession(); } });
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
    if (((getFeatureRegistry().currentSettings?.appearance?.theme || 'light') === 'auto') && typeof getFeatureRegistry().applyTheme === 'function') getFeatureRegistry().applyTheme('auto');
  });
  deferInit(() => { if (typeof getFeatureRegistry().initProactiveUI === 'function') getFeatureRegistry().initProactiveUI(); });
  deferInit(() => { if (typeof getFeatureRegistry().initScrollBehavior === 'function') getFeatureRegistry().initScrollBehavior(); });
  window.addEventListener('keydown', (e: KeyboardEvent) => { if (typeof getFeatureRegistry().handleGlobalKeyDown === 'function') getFeatureRegistry().handleGlobalKeyDown(e); });
  window.addEventListener('resize', () => { if (typeof getFeatureRegistry()._syncSidebarState === 'function') getFeatureRegistry()._syncSidebarState(); });
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
  startPostPaintHydration();
});

// ── Backward compat window assignments ──

import { deferInit, batchInit } from '../shared/init-deferred';
import { escHtml } from '../shared/sanitize';
getFeatureRegistry().hideStartupSplash = hideStartupSplash;
getFeatureRegistry().showNotification = showNotification;
getFeatureRegistry().KotoDialog = KotoDialog;
getFeatureRegistry().kotoAlert = kotoAlert;
getFeatureRegistry().kotoConfirm = kotoConfirm;
getFeatureRegistry().kotoPrompt = kotoPrompt;
getFeatureRegistry().handleGlobalKeyDown = handleGlobalKeyDown;
getFeatureRegistry().minimizeWindow = minimizeWindow;
getFeatureRegistry().maximizeWindow = maximizeWindow;
getFeatureRegistry().closeWindow = closeWindow;
getFeatureRegistry().switchToMiniMode = switchToMiniMode;
getFeatureRegistry().chatSearchNavKey = chatSearchNavKey;
getFeatureRegistry().loadFolderList = loadFolderList;
getFeatureRegistry().loadFolderDrives = loadFolderDrives;
getFeatureRegistry().selectFolderEntry = selectFolderEntry;
getFeatureRegistry().confirmFolderSelection = confirmFolderSelection;
getFeatureRegistry().openArtifactPanel = openArtifactPanel;
getFeatureRegistry().closeArtifactPanel = closeArtifactPanel;
getFeatureRegistry().switchArtifactTab = switchArtifactTab;
getFeatureRegistry().copyArtifactContent = copyArtifactContent;
getFeatureRegistry().downloadArtifact = downloadArtifact;
getFeatureRegistry().closeArtifacts = closeArtifacts;
getFeatureRegistry().initProactiveUI = initProactiveUI;
getFeatureRegistry().sendRating = sendRating;
getFeatureRegistry().loadMemories = loadMemories;
getFeatureRegistry().addNewMemory = addNewMemory;
getFeatureRegistry().deleteMemory = deleteMemory;
getFeatureRegistry().importProfileMemories = importProfileMemories;
getFeatureRegistry().batchExtractMemories = batchExtractMemories;
getFeatureRegistry().showAgentConfirmDialog = showAgentConfirmDialog;
getFeatureRegistry().showAgentChoiceDialog = showAgentChoiceDialog;
getFeatureRegistry().extractMeetingActions = extractMeetingActions;
getFeatureRegistry().createReminderFromAction = createReminderFromAction;
getFeatureRegistry().generateMorningBrief = generateMorningBrief;
getFeatureRegistry().openCatalogWizard = openCatalogWizard;
getFeatureRegistry().closeCatalogWizard = closeCatalogWizard;
getFeatureRegistry().closeCatalogScheduleWizard = closeCatalogScheduleWizard;
getFeatureRegistry().saveCatalogScheduleWizard = saveCatalogScheduleWizard;
getFeatureRegistry().escapeHtml = escHtml;
