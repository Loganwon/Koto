/**
 * File System Actions — Multi-select, keyboard shortcuts, find bar, new file/folder, open folder.
 * Workspace file actions.
 */

import { _escHtml, showToast, _FOLDER_SVG, _FOLDER_OPEN_SVG, _DEFAULT_FILE_SVG } from './infrastructure';
import { state } from './state';
import { getWorkspaceApi } from '../shared/workspace-api';

const workspaceApi = getWorkspaceApi();

// ── Interfaces ──

export interface SelectModeConfig {
  selectMode: boolean;
  count: number;
}

// ── Is Absolute Path ──

function _isAbsolutePath(rawPath: string): boolean {
  return /^(?:[a-zA-Z]:[\\/]|\/|\\\\)/.test(String(rawPath || '').trim());
}

// ── CSRF Fetch ──

function _csrfFetch(url: string, options: any = {}): Promise<Response> {
  if (typeof workspaceApi._csrfFetch === 'function') {
    return workspaceApi._csrfFetch(url, options);
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
    workspaceApi.openWorkspaceFile(path);
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
    if (typeof workspaceApi._doSearch === 'function') {
      workspaceApi._doSearch();
    }
  } else {
    if (typeof workspaceApi._renderBrowserTree === 'function') {
      workspaceApi._renderBrowserTree();
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
        if (typeof workspaceApi._removeOpenTabAfterFileDeleted === 'function') {
          await workspaceApi._removeOpenTabAfterFileDeleted(p);
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
  if (typeof workspaceApi.refreshFiles === 'function') {
    await workspaceApi.refreshFiles();
  }
}

async function sendSelectedToAI(): Promise<void> {
  const paths = [...state.selectedFiles];
  if (!paths.length) return;
  const attachFn = workspaceApi.attachFilesToTask;
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
      if (typeof workspaceApi._softRefreshBrowser === 'function') {
        await workspaceApi._softRefreshBrowser();
      }
    } else {
      if (typeof workspaceApi.refreshFiles === 'function') {
        await workspaceApi.refreshFiles();
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
    if (typeof workspaceApi.refreshFiles === 'function') {
      await workspaceApi.refreshFiles();
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
      if (typeof workspaceApi.saveFile === 'function') {
        workspaceApi.saveFile();
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
      if (typeof workspaceApi._closeTab === 'function') {
        workspaceApi._closeTab(state.activeTabPath);
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
      if (typeof workspaceApi._tabClick === 'function') {
        workspaceApi._tabClick(state.openTabs[next].path);
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
      } else if (typeof workspaceApi.saveFile === 'function') {
        workspaceApi.saveFile();
      }
      return;
    }

    // Escape: close find bars
    if (e.key === 'Escape') {
      const docxBar = document.getElementById('wa-docx-find-bar');
      const pptxBar = document.getElementById('wa-pptx-find-bar');
      if (docxBar && docxBar.style.display !== 'none') {
        e.stopPropagation();
        if (typeof workspaceApi.docxFindClose === 'function') {
          workspaceApi.docxFindClose();
        }
        return;
      }
      if (pptxBar && pptxBar.style.display !== 'none') {
        e.stopPropagation();
        if (typeof workspaceApi.pptxFindClose === 'function') {
          workspaceApi.pptxFindClose();
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
      if (replaceMode && typeof workspaceApi.docxToggleReplace === 'function') {
        workspaceApi.docxToggleReplace(true);
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
      if (replaceMode && typeof workspaceApi.pptxToggleReplace === 'function') {
        workspaceApi.pptxToggleReplace(true);
      }
      const inp = document.getElementById('wa-pptx-find-input') as HTMLInputElement | null;
      if (inp) {
        inp.focus();
        inp.select();
      }
    }
  } else if (ft === 'pdf') {
    if (typeof workspaceApi.pdfSearchOpen === 'function') {
      workspaceApi.pdfSearchOpen();
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

const wa = workspaceApi;

wa._fileRowClick = _fileRowClick;
wa._toggleFileCheck = _toggleFileCheck;
wa._toggleBrowserCheck = _toggleBrowserCheck;
wa._updateSelectBar = _updateSelectBar;
wa.toggleSelectMode = toggleSelectMode;
wa.selectAll = selectAll;
wa.deleteSelected = deleteSelected;
wa.sendSelectedToAI = sendSelectedToAI;
wa.startNewFile = startNewFile;
wa.startNewFolder = startNewFolder;
wa.openFolderAsWorkspace = openFolderAsWorkspace;
wa.closeFolderOverlay = closeFolderOverlay;
wa.confirmOpenFolder = confirmOpenFolder;
wa.browseForFolder = browseForFolder;
wa.toggleFolder = toggleFolder;
