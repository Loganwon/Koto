/**
 * File System Actions — Multi-select, keyboard shortcuts, find bar, new file/folder, open folder.
 * Extracted from workspace-assistant.js lines 5427-6148.
 */

import { _escHtml, showToast, _FOLDER_SVG, _FOLDER_OPEN_SVG, _DEFAULT_FILE_SVG } from './infrastructure';
import { state } from './state';

// ── Interfaces ──

export interface SelectModeConfig {
  selectMode: boolean;
  count: number;
}

export interface ArchiveConfig {
  mode: string;
  source: string;
  recursive: boolean;
  rules: any[];
}

// ── Is Absolute Path ──

function _isAbsolutePath(rawPath: string): boolean {
  return /^(?:[a-zA-Z]:[\\/]|\/|\\\\)/.test(String(rawPath || '').trim());
}

// ── CSRF Fetch ──

function _csrfFetch(url: string, options: any = {}): Promise<Response> {
  if (typeof (window as any).WA?._csrfFetch === 'function') {
    return (window as any).WA._csrfFetch(url, options);
  }
  return fetch(url, options);
}

// ── Multi-select ──

function _fileRowClick(event: MouseEvent, path: string, supported: boolean = true): void {
  if (state.selectMode) {
    const cb = (event.currentTarget as HTMLElement).querySelector('.wa-file-check') as HTMLInputElement | null;
    if (!cb) return;
    const checked = !cb.checked;
    cb.checked = checked;
    _toggleFileCheck(cb, path);
  } else if (supported) {
    (window as any).WA.openWorkspaceFile(path);
  } else {
    showToast('此格式暂不支持在线编辑：' + (path || '').split(/[\\/]/).pop(), 'info');
  }
}

function _toggleFileCheck(cb: HTMLInputElement, path: string): void {
  cb.checked ? state.selectedFiles.add(path) : state.selectedFiles.delete(path);
  const item = cb.closest('.wa-file-item') as HTMLElement | null;
  if (item) item.classList.toggle('selected', cb.checked);
  _updateSelectBar();
}

function _toggleBrowserCheck(cb: HTMLInputElement): void {
  const path = (cb.closest('.wa-file-item') as HTMLElement)?.dataset.path;
  if (!path) return;
  cb.checked ? state.selectedFiles.add(path) : state.selectedFiles.delete(path);
  const item = cb.closest('.wa-file-item') as HTMLElement | null;
  if (item) item.classList.toggle('selected', cb.checked);
  _updateSelectBar();
}

function _browserFileRowMouseDown(event: MouseEvent, el: HTMLElement): void {
  if (!state.selectMode || !el) return;
  if (event && event.button !== 0) return;
  if (
    event &&
    event.target &&
    (event.target as HTMLElement).closest &&
    (event.target as HTMLElement).closest('.wa-file-check')
  )
    return;
  el.dataset.selectMouseHandled = '1';
  _browserFileRowClick(event, el);
}

function _browserFileRowClick(event: MouseEvent, el: HTMLElement): void {
  if (event) {
    if ((event as any).__waFileRowHandled) return;
    (event as any).__waFileRowHandled = true;
  }
  if (!el) return;
  if (
    event &&
    event.target &&
    (event.target as HTMLElement).closest &&
    (event.target as HTMLElement).closest('.wa-file-check')
  )
    return;
  if (el.dataset.selectMouseHandled === '1' && event && event.type === 'click') {
    delete el.dataset.selectMouseHandled;
    if (event && typeof event.preventDefault === 'function') event.preventDefault();
    if (event && typeof event.stopPropagation === 'function') event.stopPropagation();
    return;
  }
  if (state.selectMode) {
    if (event && typeof event.preventDefault === 'function') event.preventDefault();
    if (event && typeof event.stopPropagation === 'function') event.stopPropagation();
    const cb = el.querySelector('.wa-file-check') as HTMLInputElement | null;
    if (!cb) return;
    cb.checked = !cb.checked;
    _toggleBrowserCheck(cb);
    return;
  }
  if (el.dataset.supported !== 'false') {
    (window as any).WA.openBrowserFile(el.dataset.path, true);
  } else {
    showToast('此格式暂不支持在线编辑：' + (el.dataset.path || '').split(/[\\/]/).pop(), 'info');
  }
}

function _installBrowserFileRowDelegation(): void {
  const doc = document as any;
  if (doc.__waBrowserFileDelegationInstalled) return;
  doc.__waBrowserFileDelegationInstalled = true;
  document.addEventListener('click', (event: MouseEvent) => {
    if ((event as any).__waFileRowHandled) return;
    const list = document.getElementById('wa-files-list') as HTMLElement | null;
    if (!list) return;
    const target = event.target as HTMLElement | null;
    if (!target || typeof target.closest !== 'function') return;
    if (target.closest('.wa-file-check, .wa-file-actions, button, input, textarea, select, a')) return;
    const row = target.closest('.wa-file-item.file') as HTMLElement | null;
    if (!row || !list.contains(row)) return;
    _browserFileRowClick(event, row);
  });
}

function _updateSelectBar(): void {
  const n = state.selectedFiles.size;
  const countEl = document.getElementById('wa-select-count');
  if (countEl) countEl.textContent = n + ' 已选';
  const btn = document.getElementById('wa-delete-selected') as HTMLButtonElement | null;
  if (btn) {
    btn.disabled = n === 0;
  }
  const sendBtn = document.getElementById('wa-send-selected-ai') as HTMLButtonElement | null;
  if (sendBtn) {
    sendBtn.disabled = n === 0;
  }
}

function toggleSelectMode(): void {
  state.selectMode = !state.selectMode;
  state.selectedFiles.clear();
  document.body.classList.toggle('select-mode', state.selectMode);
  const bar = document.getElementById('wa-select-bar');
  const tog = document.getElementById('wa-select-toggle');
  if (bar) bar.style.display = state.selectMode ? 'flex' : 'none';
  if (tog) tog.classList.toggle('active', state.selectMode);
  document.querySelectorAll('.wa-file-check').forEach((cb: any) => {
    cb.checked = false;
  });
  document
    .querySelectorAll('.wa-file-item.selected')
    .forEach((el) => el.classList.remove('selected'));
  _updateSelectBar();
  if (state._searchActive && state.searchQuery) {
    if (typeof (window as any).WA._doSearch === 'function') {
      (window as any).WA._doSearch();
    }
  } else {
    if (typeof (window as any).WA._renderBrowserTree === 'function') {
      (window as any).WA._renderBrowserTree();
    }
  }
}

function selectAll(): void {
  document.querySelectorAll('.wa-file-item.file .wa-file-check').forEach((cb: any) => {
    const path = (cb.closest('.wa-file-item') as HTMLElement).dataset.path;
    if (path) {
      cb.checked = true;
      state.selectedFiles.add(path);
      (cb.closest('.wa-file-item') as HTMLElement).classList.add('selected');
    }
  });
  _updateSelectBar();
}

async function deleteSelected(): Promise<void> {
  const paths = [...state.selectedFiles];
  if (!paths.length) return;
  const openInPaths = paths.filter(
    (p) => state.wsSourcePath && (p === state.wsSourcePath || p.endsWith('/' + state.fileName))
  );
  if (openInPaths.length) {
    if (!confirm(`所选文件中包含当前打开的文件，确定要移入回收站吗？`)) return;
  } else if (!confirm(`确定要将选中的 ${paths.length} 个文件移入回收站吗？`)) return;
  let failed = 0;
  let skippedExternal = 0;
  for (const p of paths) {
    try {
      const isAbs = /^[A-Za-z]:[/\\]|\//.test(p);
      if (isAbs) {
        skippedExternal++;
        continue;
      }
      const res = await _csrfFetch('/api/v1/workspace/file?path=' + encodeURIComponent(p), { method: 'DELETE' });
      if (!res.ok) failed++;
      else {
        if (typeof (window as any).WA?._removeOpenTabAfterFileDeleted === 'function') {
          await (window as any).WA._removeOpenTabAfterFileDeleted(p);
        }
      }
    } catch (_) {
      failed++;
    }
  }
  const deleted = paths.length - failed - skippedExternal;
  const suffix = skippedExternal ? `，已跳过 ${skippedExternal} 个外部文件` : '';
  showToast(
    failed
      ? `已移入回收站 ${deleted} 个，${failed} 个失败${suffix}`
      : `已将 ${deleted} 个文件移入回收站${suffix}`,
    failed ? 'error' : 'success'
  );
  toggleSelectMode();
  if (typeof (window as any).WA?.refreshFiles === 'function') {
    await (window as any).WA.refreshFiles();
  }
}

async function sendSelectedToAI(): Promise<void> {
  const paths = [...state.selectedFiles];
  if (!paths.length) return;
  const attachFn = (window as any).WA.attachFilesToTask;
  if (typeof attachFn !== 'function') {
    showToast('AI 助手未就绪', 'error');
    return;
  }
  const result = await attachFn(paths, {
    source: 'browser_multi_select',
    duplicateToast: false,
  });
  if (result.added > 0) {
    showToast(`已将 ${result.added} 个文件发送给AI助手`, 'success');
    const aiPanel = document.getElementById('wa-ai');
    if (aiPanel) aiPanel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  } else {
    showToast(
      result.skipped ? '所选文件均已在分析列表中或格式不支持' : '没有可发送的文件',
      'info'
    );
  }
  toggleSelectMode();
}

// ── Archive Panel ──

let _archiveMode = 'auto';

function showArchivePanel(): void {
  const overlay = document.getElementById('wa-archive-overlay');
  if (!overlay) return;
  const srcInput = document.getElementById('wa-archive-src') as HTMLInputElement | null;
  if (srcInput && !srcInput.value && state._workspacePath) srcInput.value = state._workspacePath;
  const resultEl = document.getElementById('wa-archive-result');
  if (resultEl) resultEl.innerHTML = '';
  _setArchiveMode(_archiveMode);
  overlay.style.display = 'flex';
}

function hideArchivePanel(): void {
  const el = document.getElementById('wa-archive-overlay');
  if (el) el.style.display = 'none';
}

function _setArchiveMode(mode: string): void {
  _archiveMode = mode;
  const btnAuto = document.getElementById('wa-archive-mode-auto');
  const btnCustom = document.getElementById('wa-archive-mode-custom');
  if (btnAuto) btnAuto.className = mode === 'auto' ? 'wa-btn primary' : 'wa-btn';
  if (btnCustom) btnCustom.className = mode === 'custom' ? 'wa-btn primary' : 'wa-btn';
}

async function _archivePickFolder(inputId: string): Promise<void> {
  try {
    const res = await fetch('/api/files/pick-folder');
    const d = await res.json();
    if (d.path) {
      const el = document.getElementById(inputId) as HTMLInputElement | null;
      if (el) el.value = d.path;
    }
  } catch (_) {
    /* user cancelled or not available */
  }
}

async function _doArchive(): Promise<void> {
  const srcEl = document.getElementById('wa-archive-src') as HTMLInputElement | null;
  const resultEl = document.getElementById('wa-archive-result');
  const startBtn = document.getElementById('wa-archive-start-btn') as HTMLButtonElement | null;
  if (!srcEl || !resultEl) return;
  const src = srcEl.value.trim();
  if (!src) {
    srcEl.focus();
    showToast('请先填写源文件夹路径', 'error');
    return;
  }
  if (startBtn) startBtn.disabled = true;
  resultEl.innerHTML =
    '<div class="wa-loading-row" style="display:flex;align-items:center;gap:8px;padding:12px">' +
    '<span class="wa-spinner"></span>归档中，请稍候…</div>';
  try {
    const res = await _csrfFetch('/api/files/archive', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source_dir: src, mode: _archiveMode, recursive: true, rules: [] }),
    });
    const d = await res.json();
    if (!res.ok || d.error) throw new Error(d.error || res.statusText);
    const byFolder: Record<string, string[]> = {};
    (d.report || []).forEach((item: any) => {
      if (!byFolder[item.folder]) byFolder[item.folder] = [];
      byFolder[item.folder].push((item.src || '').split(/[\\/]/).pop());
    });
    const cards = Object.entries(byFolder)
      .map(
        ([folder, files]) =>
          `<div class="wa-archive-group">` +
          `<div class="wa-archive-group-title">${_FOLDER_SVG} ${_escHtml(folder)} <span class="wa-section-badge">${files.length}</span></div>` +
          `<div class="wa-archive-group-files">${files.slice(0, 6).map((f) => `<span>${_escHtml(f)}</span>`).join('')}` +
          `${files.length > 6 ? `<span style="color:var(--text-muted)">…另 ${files.length - 6} 个</span>` : ''}</div>` +
          `</div>`
      )
      .join('');
    resultEl.innerHTML =
      `<div class="wa-archive-success">` +
      `<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">` +
      `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#34d399" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>` +
      `<strong>归档完成</strong><span style="color:var(--text-muted);font-size:12px;margin-left:4px">共 ${d.total} 个文件，成功 ${d.copied} 个</span></div>` +
      `<div style="font-size:11px;color:var(--text-muted);margin-bottom:8px">目标：${_escHtml(d.dest_dir)}</div>` +
      cards +
      `</div>`;
    delete state._browserCache[d.dest_dir];
    state._browserExpanded.add(d.dest_dir);
    if (typeof (window as any).WA._softRefreshBrowser === 'function') {
      (window as any).WA._softRefreshBrowser();
    }
  } catch (e: any) {
    resultEl.innerHTML = `<div class="wa-empty-row" style="color:var(--danger)">归档失败：${_escHtml(e.message)}</div>`;
  } finally {
    if (startBtn) startBtn.disabled = false;
  }
}

// ── Create new file / folder (VS Code inline input pattern) ──

function _insertNewItemInput(parentPath: string, kind: 'file' | 'folder'): void {
  const fileIcon =
    kind === 'folder'
      ? `<span class="wa-file-icon">${_FOLDER_SVG}</span>`
      : `<span class="wa-file-icon">${_DEFAULT_FILE_SVG}</span>`;

  const row = document.createElement('div');
  row.className = 'wa-file-item wa-new-item-row';

  let depth = 0;
  if (parentPath) {
    const parentEl = document.querySelector(
      `.wa-file-item[data-path="${CSS.escape(parentPath)}"]`
    ) as HTMLElement | null;
    if (parentEl) depth = parseInt(parentEl.dataset.depth || '0', 10) + 1;
  }
  row.innerHTML = `<span class="wa-tree-indent" style="padding-left:${depth * 16 + 8}px"></span>${fileIcon}`;

  const input = document.createElement('input');
  input.className = 'wa-rename-input wa-new-item-input';
  input.placeholder = kind === 'folder' ? '文件夹名称' : '文件名.txt';
  row.appendChild(input);

  let inserted = false;
  if (parentPath) {
    const folderGroup = document.querySelector(
      `.wa-folder-group[data-folder="${CSS.escape(parentPath)}"]`
    ) as HTMLElement | null;
    if (folderGroup) {
      const childrenEl = folderGroup.querySelector('.wa-folder-children') as HTMLElement | null;
      if (childrenEl) {
        childrenEl.style.display = 'block';
        const arrowEl = folderGroup.querySelector('.wa-folder-arrow') as HTMLElement | null;
        if (arrowEl) arrowEl.classList.add('open');
        childrenEl.prepend(row);
        inserted = true;
      }
    }
  }
  if (!inserted) {
    const list = document.getElementById('wa-files-list');
    if (list) list.prepend(row);
  }

  input.focus();

  const commit = async () => {
    const name = input.value.trim();
    if (!name) {
      row.remove();
      return;
    }
    try {
      const isBrowserPath = parentPath && _isAbsolutePath(parentPath);
      const endpoint = isBrowserPath
        ? kind === 'folder'
          ? '/api/v1/fs/create_folder'
          : '/api/v1/fs/create_file'
        : kind === 'folder'
          ? '/api/v1/workspace/create_folder'
          : '/api/v1/workspace/create_file';
      const body = isBrowserPath
        ? { parent: parentPath, name }
        : kind === 'folder'
          ? { parent: parentPath || '', name }
          : { folder: parentPath || '', name };
      const res = await _csrfFetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const json = await res.json();
      if (!res.ok) throw new Error(json.error || '创建失败');
      showToast(`"${name}" 已创建`, 'success');
    } catch (e: any) {
      showToast(e.message, 'error');
    }
    row.remove();
    if (parentPath && _isAbsolutePath(parentPath)) {
      delete state._browserCache[parentPath];
      state._browserExpanded.add(parentPath);
      if (typeof (window as any).WA._softRefreshBrowser === 'function') {
        await (window as any).WA._softRefreshBrowser();
      }
    } else {
      if (typeof (window as any).WA?.refreshFiles === 'function') {
        await (window as any).WA.refreshFiles();
      }
    }
  };

  let committed = false;
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      if (!committed) {
        committed = true;
        commit();
      }
    }
    if (e.key === 'Escape') {
      row.remove();
    }
  });
  input.addEventListener('blur', () => {
    if (!committed) {
      committed = true;
      commit();
    }
  });
}

function startNewFile(folderPath: string): void {
  _insertNewItemInput(folderPath, 'file');
}

function startNewFolder(parentPath: string): void {
  _insertNewItemInput(parentPath, 'folder');
}

// ── Open Folder as Workspace ──

function openFolderAsWorkspace(): void {
  const overlay = document.getElementById('wa-open-folder-overlay');
  if (overlay) overlay.style.display = '';
}

function closeFolderOverlay(): void {
  const overlay = document.getElementById('wa-open-folder-overlay');
  if (overlay) overlay.style.display = 'none';
}

async function confirmOpenFolder(): Promise<void> {
  const input = document.getElementById('wa-open-folder-path') as HTMLInputElement | null;
  if (!input) return;
  const path = input.value.trim();
  if (!path) return;
  try {
    const res = await _csrfFetch('/api/v1/workspace/set_workspace_dir', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path }),
    });
    const json = await res.json();
    if (!res.ok) throw new Error(json.error || '切换失败');
    showToast(`工作区已切换到 "${json.name}"`, 'success');
    closeFolderOverlay();
    if (typeof (window as any).WA?.refreshFiles === 'function') {
      await (window as any).WA.refreshFiles();
    }
  } catch (e: any) {
    showToast(e.message, 'error');
  }
}

async function browseForFolder(): Promise<void> {
  if ((window as any).showDirectoryPicker) {
    try {
      const dir = await (window as any).showDirectoryPicker({ mode: 'readwrite' });
      const input = document.getElementById('wa-open-folder-path') as HTMLInputElement | null;
      if (input) {
        input.value = dir.name;
        input.placeholder = dir.name;
        showToast('已选择文件夹: ' + dir.name + ' （请确认系统路径）', 'info');
      }
    } catch (e) {
      /* user cancelled */
    }
  } else {
    showToast('浏览器不支持文件夹选择，请直接粘贴路径', 'info');
  }
}

// ── Legacy toggle folder (workspace tree) ──

function toggleFolder(el: HTMLElement): void {
  const arrow = el.querySelector('.wa-folder-arrow') as HTMLElement | null;
  const iconEl = el.querySelector('.wa-file-icon') as HTMLElement | null;
  const children = el.nextElementSibling as HTMLElement | null;
  const folderGroup = el.closest('.wa-folder-group') as HTMLElement | null;
  const folderPath = folderGroup?.dataset.folder;
  if (!children) return;
  const isOpen = children.style.display !== 'none';
  if (!isOpen) {
    children.style.display = 'block';
    if (arrow) arrow.classList.add('open');
    if (iconEl) iconEl.innerHTML = _FOLDER_OPEN_SVG;
    if (folderPath) {
      const openFolders = JSON.parse(localStorage.getItem('wa_open_folders') || '{}');
      openFolders[folderPath] = true;
      localStorage.setItem('wa_open_folders', JSON.stringify(openFolders));
    }
  } else {
    children.style.display = 'none';
    if (arrow) arrow.classList.remove('open');
    if (iconEl) iconEl.innerHTML = _FOLDER_SVG;
    if (folderPath) {
      const openFolders = JSON.parse(localStorage.getItem('wa_open_folders') || '{}');
      delete openFolders[folderPath];
      localStorage.setItem('wa_open_folders', JSON.stringify(openFolders));
    }
  }
}

// ── Keyboard Shortcuts ──

document.addEventListener(
  'keydown',
  (e) => {
    const ctrl = e.ctrlKey || e.metaKey;
    const wsView = document.getElementById('workspaceView');
    const wsVisible = wsView && wsView.style.display !== 'none' && !wsView.classList.contains('hidden');

    // Ctrl+S: Save
    if (ctrl && e.key === 's' && !e.shiftKey) {
      if (!wsVisible) return;
      e.preventDefault();
      e.stopPropagation();
      if (typeof (window as any).WA.saveFile === 'function') {
        (window as any).WA.saveFile();
      }
      return;
    }

    // Ctrl+F: Find
    if (ctrl && e.key === 'f' && !e.shiftKey) {
      if (!wsVisible || !state.fileType) return;
      e.preventDefault();
      e.stopPropagation();
      _openFindBar(false);
      return;
    }

    // Ctrl+H: Find & Replace
    if (ctrl && e.key === 'h') {
      if (!wsVisible || !state.fileType) return;
      e.preventDefault();
      e.stopPropagation();
      _openFindBar(true);
      return;
    }

    // Ctrl+W: Close active tab
    if (ctrl && e.key === 'w') {
      if (!wsVisible || !state.activeTabPath) return;
      e.preventDefault();
      e.stopPropagation();
      if (typeof (window as any).WA._closeTab === 'function') {
        (window as any).WA._closeTab(state.activeTabPath);
      }
      return;
    }

    // Ctrl+Tab / Ctrl+Shift+Tab: Cycle tabs
    if (ctrl && e.key === 'Tab') {
      if (!wsVisible || state.openTabs.length < 2) return;
      e.preventDefault();
      e.stopPropagation();
      const cur = state.openTabs.findIndex((t) => t.path === state.activeTabPath);
      const n = state.openTabs.length;
      const next = e.shiftKey ? (cur - 1 + n) % n : (cur + 1) % n;
      if (typeof (window as any).WA._tabClick === 'function') {
        (window as any).WA._tabClick(state.openTabs[next].path);
      }
      return;
    }

    // Ctrl+P: Print / Export
    if (ctrl && e.key === 'p') {
      if (!wsVisible || !state.fileType) return;
      e.preventDefault();
      e.stopPropagation();
      if (
        state.fileType === 'pdf' &&
        state.activeEditor &&
        typeof (state.activeEditor as any)._printPdf === 'function'
      ) {
        (state.activeEditor as any)._printPdf();
      } else if (typeof (window as any).WA.saveFile === 'function') {
        (window as any).WA.saveFile();
      }
      return;
    }

    // Escape: close find bars
    if (e.key === 'Escape') {
      const docxBar = document.getElementById('wa-docx-find-bar');
      const pptxBar = document.getElementById('wa-pptx-find-bar');
      if (docxBar && docxBar.style.display !== 'none') {
        e.stopPropagation();
        if (typeof (window as any).WA?.docxFindClose === 'function') {
          (window as any).WA.docxFindClose();
        }
        return;
      }
      if (pptxBar && pptxBar.style.display !== 'none') {
        e.stopPropagation();
        if (typeof (window as any).WA?.pptxFindClose === 'function') {
          (window as any).WA.pptxFindClose();
        }
      }
    }
  },
  true
);

// ── Find Bar Dispatcher ──

function _openFindBar(replaceMode: boolean): void {
  const ft = state.fileType;
  if (ft === 'docx') {
    const bar = document.getElementById('wa-docx-find-bar');
    if (bar) {
      bar.style.display = '';
      if (replaceMode && typeof (window as any).WA?.docxToggleReplace === 'function') {
        (window as any).WA.docxToggleReplace(true);
      }
      const inp = document.getElementById('wa-docx-find-input') as HTMLInputElement | null;
      if (inp) {
        inp.focus();
        inp.select();
      }
    }
  } else if (ft === 'pptx') {
    const bar = document.getElementById('wa-pptx-find-bar');
    if (bar) {
      bar.style.display = '';
      if (replaceMode && typeof (window as any).WA?.pptxToggleReplace === 'function') {
        (window as any).WA.pptxToggleReplace(true);
      }
      const inp = document.getElementById('wa-pptx-find-input') as HTMLInputElement | null;
      if (inp) {
        inp.focus();
        inp.select();
      }
    }
  } else if (ft === 'pdf') {
    if (typeof (window as any).WA?.pdfSearchOpen === 'function') {
      (window as any).WA.pdfSearchOpen();
    }
    if (replaceMode) showToast('PDF 不支持替换', 'info');
  } else if (ft === 'xlsx') {
    const xlsxEl = document.getElementById('wa-xlsx-editor');
    if (xlsxEl) {
      const ev = new KeyboardEvent('keydown', { key: 'f', ctrlKey: true, bubbles: true, cancelable: true });
      xlsxEl.dispatchEvent(ev);
      if (replaceMode) {
        const evH = new KeyboardEvent('keydown', { key: 'h', ctrlKey: true, bubbles: true, cancelable: true });
        xlsxEl.dispatchEvent(evH);
      }
    }
  }
}

// ── Backward compatibility ──

const wa = (window as any).WA || {};
(window as any).WA = wa;

wa._fileRowClick = _fileRowClick;
wa._toggleFileCheck = _toggleFileCheck;
wa._toggleBrowserCheck = _toggleBrowserCheck;
if (typeof wa._browserFileRowMouseDown !== 'function') wa._browserFileRowMouseDown = _browserFileRowMouseDown;
if (typeof wa._browserFileRowClick !== 'function') wa._browserFileRowClick = _browserFileRowClick;
wa._updateSelectBar = _updateSelectBar;
wa.toggleSelectMode = toggleSelectMode;
wa.selectAll = selectAll;
wa.deleteSelected = deleteSelected;
wa.sendSelectedToAI = sendSelectedToAI;
wa.showArchivePanel = showArchivePanel;
wa.hideArchivePanel = hideArchivePanel;
wa._setArchiveMode = _setArchiveMode;
wa._archivePickFolder = _archivePickFolder;
wa._doArchive = _doArchive;
wa.startNewFile = startNewFile;
wa.startNewFolder = startNewFolder;
wa.openFolderAsWorkspace = openFolderAsWorkspace;
wa.closeFolderOverlay = closeFolderOverlay;
wa.confirmOpenFolder = confirmOpenFolder;
wa.browseForFolder = browseForFolder;
wa.toggleFolder = toggleFolder;

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', _installBrowserFileRowDelegation, { once: true });
} else {
  _installBrowserFileRowDelegation();
}
