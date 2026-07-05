/**
 * Drag-and-Drop & Embedded Mode — AI panel drag-drop, openInMainView, closeInMainView,
 * Ctrl+K focus, file-browser keyboard shortcuts, save caret sync, auto-restore.
 * Embedded workspace layout helpers.
 */

import { _initSplit } from './panel-layout';
import { _addLocalFilesToAIContext, _attachFilesToTask } from '../workspace/ai-context';

declare function $(id: string): HTMLElement | null;
declare let state: any;
declare let WA: any;
declare function showToast(message: string, kind?: string, duration?: number): void;
declare function loadFiles(files: FileList | File[]): void;
declare function loadFileBrowser(): void;
declare function _openFilePicker(opts?: any): void;

export interface DragDropConfig {
  files: File[];
  kind: string;
}

export interface EmbeddedState {
  isEmbedded: boolean;
  workspaceVisible: boolean;
  splitInitialized: boolean;
}

export interface AIAttachmentDropPayload {
  kind: 'workspace' | 'local' | null;
  filePath?: string;
  files?: File[];
}

let _fsBrowserCtxTarget: { path: string; name: string; isFolder: boolean; supported: boolean } = {
  path: '',
  name: '',
  isFolder: false,
  supported: true,
};

// ── Image file extensions ──
export const _IMG_DROP_EXTS: Set<string> = new Set(['png','jpg','jpeg','gif','bmp','webp','svg']);

export function _hasImageFiles(dt: DataTransfer): boolean {
  if (!dt || !dt.files || !dt.files.length) return false;
  for (let i = 0; i < dt.files.length; i++) {
    const f = dt.files[i];
    const ext = (f.name || '').split('.').pop()!.toLowerCase();
    if (_IMG_DROP_EXTS.has(ext) || (f.type && f.type.startsWith('image/'))) return true;
  }
  return false;
}

// ── AI Panel drag-drop ───────────────────────────────────────────

function _dataTransferTypes(e: DragEvent): string[] {
  try {
    return Array.from((e && e.dataTransfer && e.dataTransfer.types) || []);
  } catch (_) {
    return [];
  }
}

export function _isAIAttachmentDrag(e: DragEvent): boolean {
  try {
    const types = _dataTransferTypes(e);
    if (types.includes('application/wa-file-path')) return true;
    return !!(e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length);
  } catch (_) {
    return false;
  }
}

export function _getAIAttachmentDropPayload(e: DragEvent): AIAttachmentDropPayload {
  try {
    const filePath = e.dataTransfer!.getData('application/wa-file-path');
    if (filePath) return { kind: 'workspace', filePath };
    const files = Array.from(e.dataTransfer!.files || []).filter(Boolean);
    if (files.length) return { kind: 'local', files };
  } catch (e) { console.warn("[Koto]", e) }
  return { kind: null };
}

function _showAIOverlay(aiDropOverlay: HTMLElement | null): void {
  if (!aiDropOverlay) return;
  aiDropOverlay.style.display = 'flex';
  aiDropOverlay.classList.add('active');
}

function _hideAIOverlay(aiDropOverlay: HTMLElement | null): void {
  if (!aiDropOverlay) return;
  aiDropOverlay.style.display = 'none';
  aiDropOverlay.classList.remove('active');
}

function _isAiSessionListVisible(): boolean {
  const listView = document.getElementById('wa-ai-session-list-view');
  return !!listView && !listView.hidden;
}

function _focusVisibleAIComposer(): void {
  const inputId = _isAiSessionListVisible() ? 'wa-session-list-input' : 'wa-user-input';
  const input = document.getElementById(inputId) as HTMLTextAreaElement | HTMLInputElement | null;
  if (!input) return;
  window.setTimeout(() => {
    try {
      input.focus();
    } catch (_) {
      /* noop */
    }
  }, 150);
}

async function _handleAIAttachmentDrop(e: DragEvent, source: string, aiDropOverlay: HTMLElement | null): Promise<boolean> {
  const payload = _getAIAttachmentDropPayload(e);
  if (!payload.kind) return false;
  e.preventDefault();
  e.stopPropagation();
  _hideAIOverlay(aiDropOverlay);
  document.body.classList.remove('wa-file-dragging');
  if (payload.kind === 'workspace' && payload.filePath) {
    await _attachFilesToTask([payload.filePath], { source, focusInput: !_isAiSessionListVisible() });
  } else if (payload.kind === 'local' && payload.files) {
    await _addLocalFilesToAIContext(payload.files);
  }
  _focusVisibleAIComposer();
  return true;
}

function _initAIAttachmentDrops(): void {
  const aiPanel = document.getElementById('wa-ai');
  const aiDropOverlay = document.getElementById('wa-ai-file-drop');

  if (aiPanel) {
    let aiDragCounter = 0;
    aiPanel.addEventListener('dragenter', (event) => {
      if (!_isAIAttachmentDrag(event)) return;
      event.preventDefault();
      aiDragCounter++;
      _showAIOverlay(aiDropOverlay);
    });
    aiPanel.addEventListener('dragover', (event) => {
      if (!_isAIAttachmentDrag(event)) return;
      event.preventDefault();
      if (event.dataTransfer) event.dataTransfer.dropEffect = 'copy';
    });
    aiPanel.addEventListener('dragleave', (event) => {
      if (!_isAIAttachmentDrag(event)) return;
      aiDragCounter--;
      if (aiDragCounter <= 0) {
        aiDragCounter = 0;
        _hideAIOverlay(aiDropOverlay);
      }
    });
    aiPanel.addEventListener('drop', async (event) => {
      aiDragCounter = 0;
      await _handleAIAttachmentDrop(event, 'ai_panel_drop', aiDropOverlay);
    });
  }

  if (aiDropOverlay) {
    aiDropOverlay.addEventListener('dragover', (event) => {
      if (!_isAIAttachmentDrag(event)) return;
      event.preventDefault();
      if (event.dataTransfer) event.dataTransfer.dropEffect = 'copy';
    });
    aiDropOverlay.addEventListener('drop', async (event) => {
      await _handleAIAttachmentDrop(event, 'ai_overlay_drop', aiDropOverlay);
    });
  }

  const aiInputArea = document.getElementById('wa-ai-input-area');
  const aiInputBox = aiInputArea ? aiInputArea.querySelector('.wa-input-box') as HTMLElement | null : null;
  const aiInput = document.getElementById('wa-user-input');
  const sessionListComposer = document.getElementById('wa-ai-session-list-composer');
  const sessionListInput = document.getElementById('wa-session-list-input');
  [aiInputArea, aiInputBox, aiInput, sessionListComposer, sessionListInput].forEach((dropTarget) => {
    if (!dropTarget) return;
    dropTarget.addEventListener('dragenter', (event) => {
      if (!_isAIAttachmentDrag(event as DragEvent)) return;
      event.preventDefault();
      if (aiInputBox) aiInputBox.classList.add('wa-input-drag-over');
      if (sessionListComposer) sessionListComposer.classList.add('wa-session-list-drag-over');
    });
    dropTarget.addEventListener('dragover', (event) => {
      const dragEvent = event as DragEvent;
      if (!_isAIAttachmentDrag(dragEvent)) return;
      dragEvent.preventDefault();
      dragEvent.stopPropagation();
      if (dragEvent.dataTransfer) dragEvent.dataTransfer.dropEffect = 'copy';
      if (aiInputBox) aiInputBox.classList.add('wa-input-drag-over');
      if (sessionListComposer) sessionListComposer.classList.add('wa-session-list-drag-over');
    });
    dropTarget.addEventListener('dragleave', (event) => {
      const dragEvent = event as DragEvent;
      if (!aiInputArea || aiInputArea.contains(dragEvent.relatedTarget as Node | null)) return;
      if (aiInputBox) aiInputBox.classList.remove('wa-input-drag-over');
      if (sessionListComposer && !sessionListComposer.contains(dragEvent.relatedTarget as Node | null)) {
        sessionListComposer.classList.remove('wa-session-list-drag-over');
      }
    });
    dropTarget.addEventListener('drop', async (event) => {
      const dragEvent = event as DragEvent;
      if (aiInputBox) aiInputBox.classList.remove('wa-input-drag-over');
      if (sessionListComposer) sessionListComposer.classList.remove('wa-session-list-drag-over');
      await _handleAIAttachmentDrop(dragEvent, 'ai_input_drop', aiDropOverlay);
    });
  });

  document.querySelectorAll('.wa-ctx-drop-hint').forEach((hintEl) => {
    hintEl.setAttribute('role', 'button');
    hintEl.setAttribute('tabindex', '0');
    hintEl.addEventListener('click', () => {
      if (typeof (window as any).WA?.pickAIContextFiles === 'function') (window as any).WA.pickAIContextFiles();
    });
    hintEl.addEventListener('keydown', (event) => {
      const keyboardEvent = event as KeyboardEvent;
      if (keyboardEvent.key === 'Enter' || keyboardEvent.key === ' ') {
        keyboardEvent.preventDefault();
        if (typeof (window as any).WA?.pickAIContextFiles === 'function') (window as any).WA.pickAIContextFiles();
      }
    });
  });
}

_initAIAttachmentDrops();

// ── Embedded-mode public API ────────────────�─────────────────────

export const _isEmbedded: boolean = !!document.getElementById('workspaceView');

function setMainViewActive(view: HTMLElement | null, active: boolean): void {
  if (!view) return;
  view.style.display = active ? '' : 'none';
  view.setAttribute('aria-hidden', active ? 'false' : 'true');
  if (active) {
    view.removeAttribute('inert');
  } else {
    view.setAttribute('inert', '');
  }
  (view as any).inert = !active;
}

export function toggleFileMenu(): void {
  const dd = $('wa-file-dropdown');
  const btn = $('wa-ribbon-file-btn');
  if (!dd) return;
  const isOpen = dd.style.display !== 'none';
  dd.style.display = isOpen ? 'none' : 'block';
  if (btn) btn.classList.toggle('open', !isOpen);
}

export function _closeFileMenu(): void {
  const dd = $('wa-file-dropdown');
  const btn = $('wa-ribbon-file-btn');
  if (dd) dd.style.display = 'none';
  if (btn) btn.classList.remove('open');
}

function _closeAuxiliaryPanels(): void {
  if (typeof (window as any).closeSettings === 'function') {
    try { (window as any).closeSettings(); } catch {}
  } else {
    document.getElementById('settingsPanel')?.classList.remove('active');
    document.body.classList.remove('settings-panel-open');
  }
  if (typeof (window as any).closeSkillsPanel === 'function') {
    try { (window as any).closeSkillsPanel(); } catch {}
  } else {
    document.getElementById('skillsPanel')?.classList.remove('active');
    document.body.classList.remove('skills-panel-open');
  }
  const cowork = (window as any).CoworkPanel;
  if (cowork && typeof cowork.close === 'function') {
    try { cowork.close(); } catch {}
  } else {
    document.getElementById('coworkPanel')?.classList.remove('active');
  }
}

function _setActivityActive(id: string): void {
  document.querySelectorAll('.sb-nav-item').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.activity-btn').forEach(el => el.classList.remove('active'));
  const target = document.getElementById(id);
  if (target) target.classList.add('active');
}

export function openInMainView(): void {
  const chatView = document.getElementById('chatView');
  const wsView = document.getElementById('workspaceView');
  if (!wsView) {
    window.open('/', '_blank');
    return;
  }
  _closeAuxiliaryPanels();
  document.documentElement.classList.add('koto-unified-workspace');
  document.body.classList.add('koto-unified-workspace');
  const shell = document.querySelector('.app-shell');
  if (shell) shell.classList.add('koto-unified-workspace');
  _setActivityActive('navWorkspaceBtn');
  setMainViewActive(chatView, false);
  setMainViewActive(wsView, true);
  wsView.style.display = 'flex';
  localStorage.setItem('koto.inWorkspace', '1');
  if ((window as any).KotoSessionBridge && typeof (window as any).KotoSessionBridge.getSession === 'function') {
    (window as any).WA.useHostSession((window as any).KotoSessionBridge.getSession(), { force: true });
  }

  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      _initSplit();
      if ((window as any)._waSplit) {
        let sizes = [68, 32];
        try {
          const raw = localStorage.getItem('wa_split_sizes_embedded');
          const parsed = raw ? JSON.parse(raw) : null;
          if (Array.isArray(parsed) && parsed.length === 2) sizes = parsed;
        } catch {}
        try { (window as any)._waSplit.setSizes(sizes); } catch {}
      }
    });
  });
  if ((window as any).WA && typeof (window as any).WA.loadFileBrowser === 'function' && !(window as any)._WA_fileBrowserLoaded) {
    (window as any)._WA_fileBrowserLoaded = true;
    (window as any).WA.loadFileBrowser();
    if (typeof (window as any).WA.refreshRecent === 'function') (window as any).WA.refreshRecent();
  }

  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      if (!state.activeEditor) return;
      if (state.fileType === 'xlsx') {
        const sheetEl = document.getElementById('wa-xlsx-sheet');
        if (sheetEl && sheetEl.offsetWidth > 0) {
          const w = sheetEl.offsetWidth;
          sheetEl.style.width = (w + 1) + 'px';
          requestAnimationFrame(() => {
            const dz = parseFloat(sheetEl.dataset.dpiZoom || '0');
            sheetEl.style.width = dz > 1 ? (dz * 100) + '%' : '';
          });
        }
      } else if (state.fileType === 'pptx') {
        const area = document.getElementById('wa-pptx-slide-area');
        if (area && area.clientWidth > 48 && state.activeEditor._renderSlide) {
          state.activeEditor._renderSlide(state.activeEditor._curIdx || 0);
        }
      }
    });
  });
}

export function showFileWorkspace(): void {
  openInMainView();
  _setActivityActive('navWorkspaceBtn');
  requestAnimationFrame(() => {
    const search = document.getElementById('wa-search') as HTMLInputElement | null;
    const fileTree = document.getElementById('wa-browser-tree') as HTMLElement | null;
    if (search) {
      try { search.focus({ preventScroll: true }); } catch { search.focus(); }
    } else if (fileTree) {
      fileTree.scrollIntoView({ block: 'nearest' });
    }
  });
}

export function showAiWorkspace(): void {
  openInMainView();
  if (typeof (window as any).WA?.showAiSessionList === 'function') {
    (window as any).WA.showAiSessionList();
  }
  _setActivityActive('navAiSessionsBtn');
  requestAnimationFrame(() => {
    const sessionList = document.getElementById('wa-ai-session-list') as HTMLElement | null;
    const userInput = document.getElementById('wa-user-input') as HTMLTextAreaElement | null;
    if (sessionList && !document.getElementById('wa-ai-chat-view')?.hasAttribute('hidden')) return;
    if (sessionList) sessionList.scrollIntoView({ block: 'nearest' });
    else if (userInput) {
      try { userInput.focus({ preventScroll: true }); } catch { userInput.focus(); }
    }
  });
}

export function closeInMainView(): void {
  const chatView = document.getElementById('chatView');
  const wsView = document.getElementById('workspaceView');
  setMainViewActive(wsView, false);
  setMainViewActive(chatView, true);
  localStorage.removeItem('koto.inWorkspace');
  const navBtn = document.getElementById('navWorkspaceBtn');
  if (navBtn) navBtn.classList.remove('active');
}

export function toggleMainView(): void {
  openInMainView();
}

export function switchToChatView(): void {
  showAiWorkspace();
}

// ── Tile-browser keyboard shortcuts ─────────────�─────────────────
let _waLeftActive: boolean = false;

document.addEventListener('mouseover', (e) => {
  const leftPanel = document.getElementById('wa-left');
  if (!leftPanel || !leftPanel.contains(e.target as Node)) return;
  _waLeftActive = true;
  const item = (e.target as HTMLElement).closest('.wa-file-item');
  if (item && (item as HTMLElement).dataset.path) {
    const path = (item as HTMLElement).dataset.path!;
    const name = (item as HTMLElement).querySelector('.wa-file-label')?.textContent?.trim()
                 || path.split(/[\\/]/).pop() || '';
    const isFolder = (item as HTMLElement).classList.contains('folder');
    const supported = (item as HTMLElement).dataset.supported !== 'false';
    _fsBrowserCtxTarget = { path, name, isFolder, supported };
  }
});

document.addEventListener('mouseout', (e) => {
  const leftPanel = document.getElementById('wa-left');
  if (!leftPanel) return;
  if (leftPanel.contains(e.target as Node) && !leftPanel.contains(e.relatedTarget as Node)) {
    _waLeftActive = false;
  }
});

document.addEventListener('click', (e) => {
  const leftPanel = document.getElementById('wa-left');
  if (!leftPanel) return;
  if (leftPanel.contains(e.target as Node)) {
    _waLeftActive = true;
  } else if (!(e.target as HTMLElement).closest('#wa-ctx-menu')) {
    _waLeftActive = false;
  }
});

document.addEventListener('keydown', (e) => {
  if (!_waLeftActive) return;
  const focused = document.activeElement;
  if (focused && (
    focused.tagName === 'INPUT' ||
    focused.tagName === 'TEXTAREA' ||
    (focused as HTMLElement).isContentEditable ||
    (focused as HTMLElement).classList.contains('wa-rename-input')
  )) return;

  const { path, isFolder } = _fsBrowserCtxTarget || {};

  if (e.key === 'Enter' && path && !isFolder) {
    e.preventDefault();
    WA._fsBrowserOpen();
    return;
  }
  if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key === 'C' && path) {
    e.preventDefault();
    WA._fsBrowserCopyPath();
    return;
  }
});

// ── Ctrl+K — Focus chat input ─────────────────────────────────────
document.addEventListener('keydown', (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
    const f = document.activeElement;
    if (f && (f as HTMLElement).isContentEditable) return;
    e.preventDefault();
    const waInput = $('wa-user-input') as HTMLElement;
    if (waInput) waInput.focus();
  }
});

// ── Save caret button sync ────────────────────────────────────────
(function _syncSaveCaret() {
  const saveBtn = $('wa-save-btn') as HTMLButtonElement;
  const caret = $('wa-save-caret') as HTMLButtonElement;
  if (!saveBtn || !caret) return;
  const sync = () => { caret.disabled = saveBtn.disabled; };
  sync();
  new MutationObserver(sync).observe(saveBtn, { attributes: true, attributeFilter: ['disabled'] });
})();

// ── Auto-restore embedded workspace view on page reload ──────────
if (document.getElementById('workspaceView')) {
  requestAnimationFrame(() => {
    if (typeof (window as any).WA?.openInMainView === 'function') {
      (window as any).WA.openInMainView();
    }
  });
} else if (!document.getElementById('workspaceView')) {
  requestAnimationFrame(() => {
    if ((window as any).WA && typeof (window as any).WA.loadFileBrowser === 'function' && !(window as any)._WA_fileBrowserLoaded) {
      (window as any)._WA_fileBrowserLoaded = true;
      (window as any).WA.loadFileBrowser();
      if ((window as any).WA && typeof (window as any).WA.refreshRecent === 'function') {
        (window as any).WA.refreshRecent();
      }
    }
  });
}

// ── Backward compat ──
if (typeof window !== 'undefined') {
  (window as any).WA = (window as any).WA || {};
  (window as any).WA.toggleFileMenu = toggleFileMenu;
  (window as any).WA._closeFileMenu = _closeFileMenu;
  (window as any).WA.openInMainView = openInMainView;
  (window as any).WA.closeInMainView = closeInMainView;
  (window as any).WA.toggleMainView = toggleMainView;
  (window as any).WA.showFileWorkspace = showFileWorkspace;
  (window as any).WA.showAiWorkspace = showAiWorkspace;
  (window as any).switchToChatView = switchToChatView;
}
