/**
 * Koto Workspace Assistant - Frontend Controllers & Adapters
 * Includes Phase 3 (Polymorphic Adapters) & Phase 4 (Human-AI Link)
 */

window.WA = window.WA || {};

(function() {
  // ── Global State ──
  const state = {
    fileId: null,
    fileType: null,
    fileName: null,
    wsSourcePath: null,  // workspace-relative path of the open file (e.g. "foo.docx")
    activeEditor: null,
    socket: null,
    isLoading: false,
    conversation: [],   // [{role:'user'|'assistant', content:string}] — multi-turn history
    sortBy: localStorage.getItem('wa_sort_by') || 'name',   // 'name' | 'date' | 'type'
    sectionOpen:JSON.parse(localStorage.getItem('wa_sections') || '{"workspace":true}'),
    searchQuery: '',
    _allFiles: [],  // full file tree cached for client-side filter
    pinnedSelection: '',  // text pinned as Copilot-style context chip
    selectMode: false,  // multi-select mode
    selectedFiles: new Set(),  // paths of selected files
    openTabs: [],          // [{path,name,ext,fileType,fileId,serverData,cache,modified}]
    activeTabPath: null,   // path of the currently active tab
    aiOutputMode: localStorage.getItem('wa_ai_output_mode') || 'inline',  // 'inline'|'chat'
  };

  // Persistent fsHandle map — survives tab entry replacement
  const _fsHandleMap = new Map();

  // ── Tab management (VS Code style) ──────────────────────────────────────────

  function _renderTabs() {
    const bar = $('wa-tab-bar');
    if (!bar) return;
    bar.innerHTML = state.openTabs.map(tab => {
      const active = tab.path === state.activeTabPath ? ' active' : '';
      const modified = tab.modified ? ' modified' : '';
      const pathEsc = tab.path.replace(/\\/g, '\\\\').replace(/'/g, "\\'");
      return `<div class="wa-tab${active}${modified}" data-path="${tab.path.replace(/"/g, '&quot;')}"
          onclick="WA._tabClick('${pathEsc}')" title="${tab.name}">
        <span class="tab-icon">${_fileIcon(tab.ext)}</span>
        <span class="tab-label">${tab.name}</span>
        <span class="tab-dirty"></span>
        <button class="tab-close" onclick="event.stopPropagation();WA._closeTab('${pathEsc}')" title="关闭">×</button>
      </div>`;
    }).join('');
  }

  async function _switchToTab(path) {
    if (state.activeTabPath === path) return;

    // Serialize + cache current tab before switching
    if (state.activeEditor && state.activeTabPath) {
      const curTab = state.openTabs.find(t => t.path === state.activeTabPath);
      if (curTab && state.fileType !== 'pdf') {
        curTab.cache = state.activeEditor.serialize();
      }
      // Background disk save (only if cache has actual content)
      if (curTab && state.fileType !== 'pdf' && state.fileId && curTab.cache) {
        clearTimeout(_autoSaveTimer);
        _autoSaveTimer = null;
        const savedCache = curTab.cache;
        const savedType = state.fileType;
        const savedId = state.fileId;
        const savedPath = state.wsSourcePath;
        fetch('/api/v1/workspace/auto_save', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            file_type: savedType,
            file_id: savedId,
            ws_source_path: savedPath || null,
            data: savedCache,
          }),
        }).then(() => { if (curTab) { curTab.modified = false; _renderTabs(); } })
          .catch(e => console.warn('[switchToTab diskSave]', e));
      }
      try { state.activeEditor.destroy(); } catch(e) {}
      state.activeEditor = null;
    }

    state.activeTabPath = path;
    const tab = state.openTabs.find(t => t.path === path);
    if (!tab) return;

    state.fileId = tab.fileId;
    state.fileType = tab.fileType;
    state.fileName = tab.name;
    state.wsSourcePath = tab.path;

    $('wa-file-name').textContent = tab.name;
    $('wa-save-btn').disabled = (tab.fileType === 'pdf');
    toggleWorkspace(true);

    const data = tab.cache;
    if (tab.fileType === 'docx') {
      state.activeEditor = new KotoDocxEditor();
      // Use cache if it has real content, otherwise fall back to server HTML
      const docxHtml = (data && typeof data === 'string' && data.replace(/<p><br\s*\/?><\/p>/gi,'').trim()) ? data : tab.serverData.html;
      state.activeEditor.render(docxHtml);
    } else if (tab.fileType === 'xlsx') {
      state.activeEditor = new KotoXlsxEditor();
      // cache is {sheets, _images} — extract sheets array for render
      const xlsxSheets = data ? (Array.isArray(data) ? data : (data.sheets || data)) : tab.serverData;
      state.activeEditor.render(xlsxSheets);
    } else if (tab.fileType === 'pptx') {
      state.activeEditor = new KotoPptxEditor();
      state.activeEditor.render(data !== null && data !== undefined ? data : tab.serverData);
    } else if (tab.fileType === 'pdf') {
      state.activeEditor = new KotoPdfViewer();
      state.activeEditor.render(tab.serverData.raw_url, tab.serverData.pages);
    }

    _renderTabs();
    // highlight active file in left panel
    document.querySelectorAll('.wa-file-item').forEach(el => {
      el.classList.toggle('active', el.dataset.path === path || el.title === tab.name);
    });
  }

  window.WA._tabClick = async (path) => {
    await _switchToTab(path);
  };

  window.WA._closeTab = async (path) => {
    const idx = state.openTabs.findIndex(t => t.path === path);
    if (idx < 0) return;
    const tab = state.openTabs[idx];

    // Save to disk if modified
    if (tab.modified && tab.fileType !== 'pdf' && tab.fileId) {
      const data = (tab.path === state.activeTabPath && state.activeEditor)
        ? state.activeEditor.serialize()
        : tab.cache;
      if (data) {
        try {
          await fetch('/api/v1/workspace/auto_save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ file_type: tab.fileType, file_id: tab.fileId, ws_source_path: tab.path, data }),
          });
        } catch(e) { console.warn('[closeTab diskSave]', e); }
      }
    }

    const isActive = tab.path === state.activeTabPath;

    if (isActive) {
      if (state.activeEditor) {
        try { state.activeEditor.destroy(); } catch(e) {}
        state.activeEditor = null;
      }
      state.activeTabPath = null;
      state.fileId = null;
      state.fileType = null;
      state.fileName = null;
      state.wsSourcePath = null;
      $('wa-file-name').textContent = '全格式 AI 工作区';
      $('wa-save-btn').disabled = true;
    }

    state.openTabs.splice(idx, 1);

    if (isActive) {
      if (state.openTabs.length > 0) {
        const neighborIdx = Math.min(idx, state.openTabs.length - 1);
        await _switchToTab(state.openTabs[neighborIdx].path);
      } else {
        toggleWorkspace(false);
        _renderTabs();
      }
    } else {
      _renderTabs();
    }
  };

  // ── Utility ──
  const $ = id => document.getElementById(id);

  function showToast(msg, type = 'success') {
    const t = $('wa-toast');
    t.textContent = msg;
    t.className = type + ' show';
    setTimeout(() => { t.className = t.className.replace('show', ''); }, 3000);
  }

  function toggleWorkspace(show) {
    $('wa-drop-zone').classList.toggle('hidden', show);
  }

  function setLoading(show, msg) {
    const overlay = $('wa-canvas-loading');
    const list = $('wa-files-list');
    if (show) {
      if (overlay) {
        overlay.querySelector('.wa-loading-text').textContent = msg || '加载中...';
        overlay.style.display = 'flex';
      }
      if (list) list.classList.add('loading');
    } else {
      if (overlay) overlay.style.display = 'none';
      if (list) list.classList.remove('loading');
    }
  }

  // VS Code-style SVG file type icons
  const _FILE_SVGS = {
    docx: `<svg viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg"><rect x="2" y="1" width="9" height="13" rx="1" fill="#2b579a"/><path d="M11 1l3 3v10H11V1z" fill="#1a3f6f"/><path d="M11 1v3h3" fill="none" stroke="white" stroke-width="0.5" opacity="0.4"/><rect x="4" y="5" width="5" height="1" rx="0.4" fill="white" opacity="0.85"/><rect x="4" y="7" width="5" height="1" rx="0.4" fill="white" opacity="0.85"/><rect x="4" y="9" width="3.5" height="1" rx="0.4" fill="white" opacity="0.6"/></svg>`,
    xlsx: `<svg viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg"><rect x="2" y="1" width="9" height="13" rx="1" fill="#217346"/><path d="M11 1l3 3v10H11V1z" fill="#165b32"/><path d="M4.5 5.5l1.5 2-1.5 2M7 5.5l1.5 2-1.5 2" stroke="white" stroke-width="0.9" stroke-linecap="round" fill="none" opacity="0.85"/></svg>`,
    pptx: `<svg viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg"><rect x="2" y="1" width="9" height="13" rx="1" fill="#c43e1c"/><path d="M11 1l3 3v10H11V1z" fill="#8c2d13"/><rect x="3.5" y="4.5" width="6" height="3.5" rx="0.5" fill="white" opacity="0.7"/><rect x="3.5" y="9.5" width="5" height="0.8" rx="0.3" fill="white" opacity="0.5"/><rect x="3.5" y="11" width="3.5" height="0.8" rx="0.3" fill="white" opacity="0.5"/></svg>`,
    pdf: `<svg viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg"><rect x="2" y="1" width="9" height="13" rx="1" fill="#e74c3c"/><path d="M11 1l3 3v10H11V1z" fill="#a93226"/><text x="3.2" y="10.5" font-size="4.5" font-family="sans-serif" font-weight="bold" fill="white" opacity="0.9">PDF</text></svg>`,
  };
  const _DEFAULT_FILE_SVG = `<svg viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg"><path d="M3 2h7l3 3v9a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1z" fill="#75828d"/><path d="M10 2v3h3" fill="none" stroke="white" stroke-width="0.7" opacity="0.5"/></svg>`;
  const _FOLDER_OPEN_SVG = `<svg viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg"><path d="M1.5 4a1 1 0 0 1 1-1H5.6l1.2 1.5H13.5a1 1 0 0 1 1 1v6a1 1 0 0 1-1 1h-11a1 1 0 0 1-1-1V4z" fill="#dcb67a"/><path d="M1.5 6.5h13" stroke="white" stroke-width="0.5" opacity="0.3"/></svg>`;
  const _FOLDER_SVG = `<svg viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg"><path d="M1.5 4a1 1 0 0 1 1-1H5.6l1.2 1.5H13.5a1 1 0 0 1 1 1v6a1 1 0 0 1-1 1h-11a1 1 0 0 1-1-1V4z" fill="#c09a5a"/></svg>`;
  function _fileIcon(ext) { return `<span class="wa-file-icon">${_FILE_SVGS[ext] || _DEFAULT_FILE_SVG}</span>`; }

  const _EXT_ICON = { 'docx': '📘', 'xlsx': '📗', 'pptx': '📙', 'pdf': '📕' };
  const _SORT_LABELS = { name: '名称', date: '日期', type: '类型' };

  function _applySort(items) {
    const by = state.sortBy;
    return [...items].sort((a, b) => {
      if (a.type !== b.type) return a.type === 'folder' ? -1 : 1;
      if (by === 'date') return (b.mtime || 0) - (a.mtime || 0);
      if (by === 'type') return (a.ext || '').localeCompare(b.ext || '') || a.name.localeCompare(b.name);
      return a.name.localeCompare(b.name);
    });
  }

  function _matchesSearch(item, q) {
    if (!q) return true;
    q = q.toLowerCase();
    if (item.type === 'file') return item.name.toLowerCase().includes(q);
    // For folders: keep if any child matches
    if (item.children) item._filteredChildren = item.children.filter(c => _matchesSearch(c, q));
    return item._filteredChildren && item._filteredChildren.length > 0;
  }

  function _formatDate(mtime) {
    if (!mtime) return '';
    const d = new Date(mtime);
    const now = new Date();
    const diff = (now - d) / 1000;
    if (diff < 60) return '刚才';
    if (diff < 3600) return Math.floor(diff / 60) + '分钟前';
    if (diff < 86400) return Math.floor(diff / 3600) + '小时前';
    if (diff < 7 * 86400) return Math.floor(diff / 86400) + '天前';
    return `${d.getMonth() + 1}/${d.getDate()}`;
  }

  async function loadWorkspaceFiles() {
    const list = $('wa-files-list');
    if (!list) return;
    try {
      const res = await fetch('/api/v1/workspace/list_files');
      const data = await res.json();

      state._allFiles = data.files || [];
      _renderWorkspaceTree();
    } catch (e) {
      console.error('Failed to load files', e);
    }
  }

  function _renderWorkspaceTree() {
    const list = $('wa-files-list');
    if (!list) return;

    // Apply search filter
    const q = state.searchQuery;
    let items = state._allFiles;
    if (q) {
      items = items.filter(i => _matchesSearch(i, q));
    }

    // Update workspace section visibility
    list.style.display = state.sectionOpen.workspace ? '' : 'none';
    const arrow = $('wa-ws-arrow');
    if (arrow) arrow.className = 'wa-section-arrow' + (state.sectionOpen.workspace ? ' open' : '');

    // Update sort button label
    const sortBtn = $('wa-sort-btn');
    if (sortBtn) sortBtn.title = '切换排序: ' + _SORT_LABELS[state.sortBy];

    // Count total files in tree
    const countFiles = (arr) => arr.reduce((n, i) => n + (i.type === 'file' ? 1 : countFiles(i.children || [])), 0);
    const badge = $('wa-ws-badge');
    if (badge) badge.textContent = countFiles(state._allFiles) || '';

    if (!items.length) {
      list.innerHTML = q
        ? `<div style="padding:16px 12px;color:var(--text-muted);font-size:12px;text-align:center;">未找到 "${q}"</div>`
        : '<div style="padding:20px 12px;color:var(--text-muted);font-size:12px;text-align:center;">暂无文件<br>点击 + 或拖拽添加</div>';
      return;
    }

    function renderTree(rawItems, depth = 0) {
      const openFolders = JSON.parse(localStorage.getItem('wa_open_folders') || '{}');
      const sorted = _applySort(rawItems);
      return sorted.map(item => {
        if (item.type === 'folder') {
          const children = q ? (item._filteredChildren || []) : (item.children || []);
          const childrenHtml = renderTree(children, depth + 1);
          const isOpen = q ? true : !!openFolders[item.path];
          const folderIconSvg = isOpen ? _FOLDER_OPEN_SVG : _FOLDER_SVG;
          const folderPathEsc = item.path.replace(/'/g, "\\'");
          const folderNameEsc = item.name.replace(/'/g, "\\'");
          return `<div class="wa-folder-group" data-folder="${item.path}">
            <div class="wa-file-item folder" data-depth="${depth}" data-path="${folderPathEsc}"
                onclick="WA.toggleFolder(this)"
                oncontextmenu="WA._showFolderCtxMenu(event,'${folderPathEsc}','${folderNameEsc}')">
              <span class="wa-folder-arrow${isOpen ? ' open' : ''}">›</span>
              <span class="wa-file-icon">${folderIconSvg}</span>
              <span class="wa-file-label">${item.name}</span>
            </div>
            <div class="wa-folder-children" style="display:${isOpen ? 'block' : 'none'};">${childrenHtml}</div>
          </div>`;
        } else {
          const esc = item.path.replace(/'/g, "\\'");
          const nameEsc = item.name.replace(/'/g, "\\'");
          const isActive = (state.fileName && item.name === state.fileName) ? ' active' : '';
          const meta = [item.size, _formatDate(item.mtime)].filter(Boolean).join(' · ');
          return `<div class="wa-file-item file${isActive}" data-depth="${depth}" data-path="${esc}"
              onclick="WA._fileRowClick(event,'${esc}')"
              oncontextmenu="WA._showCtxMenu(event,'${esc}','${nameEsc}')"
              title="${item.name}${meta ? '\n' + meta : ''}">
            <input type="checkbox" class="wa-file-check" onclick="event.stopPropagation();WA._toggleFileCheck(this,'${esc}')">
            ${_fileIcon(item.ext)}
            <span class="wa-file-label">${item.name}</span>
            ${meta ? `<span class="wa-file-meta">${meta}</span>` : ''}
            <div class="wa-file-actions">
              <button onclick="event.stopPropagation();WA.renameWorkspaceFile('${esc}','${nameEsc}')" title="重命名">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
              </button>
              <button class="del" onclick="event.stopPropagation();WA.deleteWorkspaceFile('${esc}')" title="删除">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/></svg>
              </button>
            </div>
          </div>`;
        }
      }).join('');
    }

    list.innerHTML = renderTree(items);
    // restore checkboxes if still in select mode
    if (state.selectMode) {
      list.querySelectorAll('.wa-file-item.file').forEach(el => {
        const p = el.dataset.path;
        if (p && state.selectedFiles.has(p)) {
          el.classList.add('selected');
          const cb = el.querySelector('.wa-file-check');
          if (cb) cb.checked = true;
        }
      });
    }
  }

  window.WA.refreshFiles = async () => {
    const btn = document.querySelector('.wa-icon-btn');
    if (btn) { btn.classList.add('spinning'); setTimeout(() => btn.classList.remove('spinning'), 700); }
    await loadWorkspaceFiles();
  };

  window.WA.filterFiles = (q) => {
    state.searchQuery = q.trim();
    const clear = $('wa-search-clear');
    if (clear) clear.style.display = state.searchQuery ? '' : 'none';
    _renderWorkspaceTree();
  };

  window.WA.clearSearch = () => {
    const input = $('wa-search');
    if (input) input.value = '';
    WA.filterFiles('');
  };

  window.WA.toggleSection = (id) => {
    state.sectionOpen[id] = !state.sectionOpen[id];
    localStorage.setItem('wa_sections', JSON.stringify(state.sectionOpen));
    _renderWorkspaceTree();
  };

  window.WA.cycleSortOrder = () => {
    const order = ['name', 'date', 'type'];
    const idx = order.indexOf(state.sortBy);
    state.sortBy = order[(idx + 1) % order.length];
    localStorage.setItem('wa_sort_by', state.sortBy);
    _renderWorkspaceTree();
  };

  window.WA.renameWorkspaceFile = async (path, currentName) => {
    // Find the file item and do inline editing
    const item = document.querySelector(`.wa-file-item[data-path="${CSS.escape(path)}"]`);
    if (!item) return;
    const labelSpan = item.querySelector('.wa-file-label');
    if (!labelSpan) return;

    const stem = currentName.includes('.') ? currentName.slice(0, currentName.lastIndexOf('.')) : currentName;
    const input = document.createElement('input');
    input.className = 'wa-rename-input';
    input.value = stem;
    labelSpan.replaceWith(input);
    input.focus();
    input.select();

    const commit = async () => {
      const newName = input.value.trim();
      if (!newName || newName === stem) { await loadWorkspaceFiles(); return; }
      try {
        const res = await fetch('/api/v1/workspace/rename', {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path, name: newName }),
        });
        const json = await res.json();
        if (!res.ok) throw new Error(json.error || '重命名失败');
        showToast('已重命名为 ' + json.name, 'success');
      } catch (e) {
        showToast(e.message, 'error');
      }
      await loadWorkspaceFiles();
    };

    input.addEventListener('keydown', e => {
      if (e.key === 'Enter') { e.preventDefault(); commit(); }
      if (e.key === 'Escape') { loadWorkspaceFiles(); }
    });
    input.addEventListener('blur', commit);
  };

  window.WA.deleteWorkspaceFile = async (filepath) => {
    if (!confirm(`确定要删除 "${filepath.split('/').pop()}" 吗？`)) return;
    try {
      const res = await fetch('/api/v1/workspace/file?path=' + encodeURIComponent(filepath), { method: 'DELETE' });
      const json = await res.json();
      if (!res.ok) {
        if (res.status === 404) {
          loadWorkspaceFiles();
          showToast('文件已不存在，已从列表移除', 'info');
        } else {
          throw new Error(json.error || '删除失败');
        }
        return;
      }
      // Remove from open tabs so auto-save can't recreate the file
      const tabIdx = state.openTabs.findIndex(t => t.path === filepath);
      if (tabIdx >= 0) {
        const wasActive = state.openTabs[tabIdx].path === state.activeTabPath;
        if (wasActive && state.activeEditor) {
          try { state.activeEditor.destroy(); } catch(e) {}
          state.activeEditor = null;
          state.activeTabPath = null;
          state.fileId = null;
          state.fileType = null;
          state.fileName = null;
          state.wsSourcePath = null;
        }
        state.openTabs.splice(tabIdx, 1);
        clearTimeout(_autoSaveTimer);
        _autoSaveTimer = null;
        _renderTabs();
        if (state.openTabs.length > 0) {
          await _switchToTab(state.openTabs[Math.max(0, tabIdx - 1)].path);
        } else {
          toggleWorkspace(false);
          $('wa-file-name').textContent = '全格式 AI 工作区';
          $('wa-save-btn').disabled = true;
        }
      }
      showToast('已删除 ' + filepath.split('/').pop(), 'success');
      loadWorkspaceFiles();
    } catch (e) {
      showToast(e.message, 'error');
    }
  };

  // ── Multi-select helpers ──────────────────────────────────────────────
  window.WA._fileRowClick = (event, path) => {
    if (state.selectMode) {
      const cb = event.currentTarget.querySelector('.wa-file-check');
      const checked = !cb.checked;
      cb.checked = checked;
      WA._toggleFileCheck(cb, path);
    } else {
      WA.openWorkspaceFile(path);
    }
  };

  window.WA._toggleFileCheck = (cb, path) => {
    cb.checked ? state.selectedFiles.add(path) : state.selectedFiles.delete(path);
    cb.closest('.wa-file-item').classList.toggle('selected', cb.checked);
    WA._updateSelectBar();
  };

  window.WA._updateSelectBar = () => {
    const n = state.selectedFiles.size;
    document.getElementById('wa-select-count').textContent = n + ' 已选';
    const btn = document.getElementById('wa-delete-selected');
    if (btn) { btn.disabled = n === 0; }
  };

  window.WA.toggleSelectMode = () => {
    state.selectMode = !state.selectMode;
    state.selectedFiles.clear();
    document.body.classList.toggle('select-mode', state.selectMode);
    const bar = document.getElementById('wa-select-bar');
    const tog = document.getElementById('wa-select-toggle');
    if (bar) bar.style.display = state.selectMode ? 'flex' : 'none';
    if (tog) tog.classList.toggle('active', state.selectMode);
    // uncheck all checkboxes
    document.querySelectorAll('.wa-file-check').forEach(cb => { cb.checked = false; });
    document.querySelectorAll('.wa-file-item.selected').forEach(el => el.classList.remove('selected'));
    WA._updateSelectBar();
  };

  window.WA.selectAll = () => {
    document.querySelectorAll('.wa-file-item.file .wa-file-check').forEach(cb => {
      const path = cb.closest('.wa-file-item').dataset.path;
      if (path) { cb.checked = true; state.selectedFiles.add(path); cb.closest('.wa-file-item').classList.add('selected'); }
    });
    WA._updateSelectBar();
  };

  window.WA.deleteSelected = async () => {
    const paths = [...state.selectedFiles];
    if (!paths.length) return;
    const openInPaths = paths.filter(p => state.wsSourcePath && (p === state.wsSourcePath || p.endsWith('/' + state.fileName)));
    if (openInPaths.length) {
      if (!confirm(`所选文件中包含当前打开的文件，确定要删除吗？`)) return;
    } else if (!confirm(`确定要删除选中的 ${paths.length} 个文件吗？`)) return;
    let failed = 0;
    for (const p of paths) {
      try {
        const res = await fetch('/api/v1/workspace/file?path=' + encodeURIComponent(p), { method: 'DELETE' });
        if (!res.ok) failed++;
      } catch { failed++; }
    }
    showToast(failed ? `已删除 ${paths.length - failed} 个，${failed} 个失败` : `已删除 ${paths.length} 个文件`, failed ? 'error' : 'success');
    WA.toggleSelectMode();
    await loadWorkspaceFiles();
  };

  // ── Context menu ──────────────────────────────────────────────────────
  let _ctxTarget = { path: null, name: null };

  window.WA._showCtxMenu = (event, path, name) => {
    event.preventDefault();
    event.stopPropagation();
    _ctxTarget = { path, name };
    const menu = document.getElementById('wa-ctx-menu');
    if (!menu) return;
    // Always rebuild for files so folder menu doesn't bleed over
    menu.innerHTML = `
      <div class="wa-ctx-item" onclick="WA._ctxOpen()">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
        打开
      </div>
      <div class="wa-ctx-separator"></div>
      <div class="wa-ctx-item" onclick="WA._ctxRename()">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
        重命名
      </div>
      <div class="wa-ctx-item" onclick="WA._ctxCopyPath()">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
        复制路径
      </div>
      <div class="wa-ctx-separator"></div>
      <div class="wa-ctx-item danger" onclick="WA._ctxDelete()">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4h6v2"/></svg>
        删除
      </div>`;
    menu.classList.add('open');
    const vw = window.innerWidth, vh = window.innerHeight;
    let x = event.clientX, y = event.clientY;
    if (x + 180 > vw) x = vw - 184;
    if (y + 180 > vh) y = vh - 184;
    menu.style.left = x + 'px';
    menu.style.top = y + 'px';
  };

  function _closeCtxMenu() {
    const menu = document.getElementById('wa-ctx-menu');
    if (menu) menu.classList.remove('open');
  }

  document.addEventListener('click', (e) => {
    // Don't close when clicking on a menu item — let the item's onclick fire first
    if (!e.target.closest('#wa-ctx-menu')) _closeCtxMenu();
  }, true);
  document.addEventListener('keydown', e => { if (e.key === 'Escape') _closeCtxMenu(); });
  // Use capture:true so this fires BEFORE WangEditor can call stopPropagation()
  document.addEventListener('keydown', e => {
    if ((e.ctrlKey || e.metaKey) && e.key === 's') {
      e.preventDefault();
      e.stopPropagation();
      WA.saveFile();
    }
  }, true);

  window.WA._ctxOpen = () => { _closeCtxMenu(); if (_ctxTarget.path) WA.openWorkspaceFile(_ctxTarget.path); };
  window.WA._ctxRename = () => { _closeCtxMenu(); if (_ctxTarget.path) WA.renameWorkspaceFile(_ctxTarget.path, _ctxTarget.name); };
  window.WA._ctxCopyPath = () => {
    _closeCtxMenu();
    if (_ctxTarget.path) {
      navigator.clipboard.writeText(_ctxTarget.path).then(() => showToast('路径已复制', 'success')).catch(() => showToast(_ctxTarget.path, 'info'));
    }
  };
  window.WA._ctxDelete = () => { _closeCtxMenu(); if (_ctxTarget.path) WA.deleteWorkspaceFile(_ctxTarget.path); };

  window.WA._showFolderCtxMenu = (event, path, name) => {
    event.preventDefault();
    event.stopPropagation();
    _ctxTarget = { path, name };
    const menu = document.getElementById('wa-ctx-menu');
    if (!menu) return;
    // Build folder-specific menu items inline
    menu.innerHTML = `
      <div class="wa-ctx-item" onclick="WA._ctxFolderRename()">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
        重命名文件夹
      </div>
      <div class="wa-ctx-separator"></div>
      <div class="wa-ctx-item danger" onclick="WA._ctxFolderDelete()">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4h6v2"/></svg>
        删除文件夹
      </div>`;
    menu.classList.add('open');
    const vw = window.innerWidth, vh = window.innerHeight;
    let x = event.clientX, y = event.clientY;
    if (x + 180 > vw) x = vw - 184;
    if (y + 120 > vh) y = vh - 124;
    menu.style.left = x + 'px';
    menu.style.top = y + 'px';
  };

  window.WA._ctxFolderRename = () => {
    _closeCtxMenu();
    if (!_ctxTarget.path) return;
    WA.renameFolderWorkspace(_ctxTarget.path, _ctxTarget.name);
  };

  window.WA._ctxFolderDelete = () => {
    _closeCtxMenu();
    if (!_ctxTarget.path) return;
    WA.deleteFolderWorkspace(_ctxTarget.path, _ctxTarget.name);
  };

  window.WA.deleteFolderWorkspace = async (folderPath, folderName) => {
    const name = folderName || folderPath.split('/').pop();
    if (!confirm(`确定要删除文件夹 "${name}" 及其所有内容吗？此操作不可撤销。`)) return;
    try {
      const res = await fetch('/api/v1/workspace/folder?path=' + encodeURIComponent(folderPath), { method: 'DELETE' });
      const json = await res.json();
      if (!res.ok) throw new Error(json.error || '删除失败');
      showToast(`已删除文件夹 "${name}"`, 'success');
      await loadWorkspaceFiles();
    } catch (e) {
      showToast(e.message, 'error');
    }
  };

  window.WA.renameFolderWorkspace = async (path, currentName) => {
    const item = document.querySelector(`.wa-file-item.folder[data-path="${CSS.escape(path)}"]`);
    if (!item) return;
    const labelSpan = item.querySelector('.wa-file-label');
    if (!labelSpan) return;

    const input = document.createElement('input');
    input.className = 'wa-rename-input';
    input.value = currentName;
    labelSpan.replaceWith(input);
    input.focus();
    input.select();

    const commit = async () => {
      const newName = input.value.trim();
      if (!newName || newName === currentName) { await loadWorkspaceFiles(); return; }
      try {
        const res = await fetch('/api/v1/workspace/rename', {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path, name: newName }),
        });
        const json = await res.json();
        if (!res.ok) throw new Error(json.error || '重命名失败');
        showToast('已重命名为 ' + json.name, 'success');
      } catch (e) {
        showToast(e.message, 'error');
      }
      await loadWorkspaceFiles();
    };

    input.addEventListener('keydown', e => {
      if (e.key === 'Enter') { e.preventDefault(); commit(); }
      if (e.key === 'Escape') { loadWorkspaceFiles(); }
    });
    input.addEventListener('blur', commit);
  };

  window.WA.toggleFolder = (el) => {
    const arrow = el.querySelector('.wa-folder-arrow');
    const iconEl = el.querySelector('.wa-file-icon');
    const children = el.nextElementSibling;
    const folderPath = el.closest('.wa-folder-group') && el.closest('.wa-folder-group').dataset.folder;
    const isOpen = children.style.display !== 'none';
    if (!isOpen) {
      children.style.display = 'block';
      arrow.classList.add('open');
      if (iconEl) iconEl.innerHTML = _FOLDER_OPEN_SVG;
      if (folderPath) {
        const openFolders = JSON.parse(localStorage.getItem('wa_open_folders') || '{}');
        openFolders[folderPath] = true;
        localStorage.setItem('wa_open_folders', JSON.stringify(openFolders));
      }
    } else {
      children.style.display = 'none';
      arrow.classList.remove('open');
      if (iconEl) iconEl.innerHTML = _FOLDER_SVG;
      if (folderPath) {
        const openFolders = JSON.parse(localStorage.getItem('wa_open_folders') || '{}');
        delete openFolders[folderPath];
        localStorage.setItem('wa_open_folders', JSON.stringify(openFolders));
      }
    }
  };

  window.WA.openWorkspaceFile = async (path) => {
    // If already open in a tab, switch instantly (no server fetch)
    if (state.openTabs.some(t => t.path === path)) {
      await _switchToTab(path);
      return;
    }
    const baseName = path.split('/').pop();
    showToast('正在加载 ' + baseName, 'success');
    try {
      const encodedPath = path.split('/').map(p => encodeURIComponent(p)).join('/');
      const res = await fetch('/api/v1/workspace/file/' + encodedPath);
      if (!res.ok) throw new Error('File not found');
      const blob = await res.blob();
      const file = new File([blob], baseName);
      file._wsPath = path;
      await Router.load(file);
    } catch (e) {
      console.error('[WA openWorkspaceFile]', e);
      showToast('无法打开文件: ' + e.message, 'error');
    }
  };

  // ── Global Selection Tooltip ──
  let lastSelectionText = "";

  // CSS Custom Highlights API — non-destructively marks pinned selection in doc
  // Supported: Chrome 105+, Edge 105+, Safari 17.2+
  function _applyPinnedHighlight() {
    if (!window.CSS || !CSS.highlights) return;
    const sel = window.getSelection();
    if (!sel || sel.rangeCount === 0) return;
    try {
      const range = sel.getRangeAt(0).cloneRange();
      CSS.highlights.set('wa-pinned', new Highlight(range));
    } catch (e) { /* ignore if API unavailable */ }
  }

  function _clearPinnedHighlight() {
    if (window.CSS && CSS.highlights) CSS.highlights.delete('wa-pinned');
  }

  // Update the selection chip UI with new text (used in multiple places)
  function _pinSelectionChip(text) {
    state.pinnedSelection = text;
    const preview = text.length > 200 ? text.substring(0, 200) + '…' : text;
    $('wa-selection-preview').textContent = preview;
    $('wa-selection-chip').style.display = 'flex';
  }

  // Save WangEditor Slate selection before focus leaves the editor
  function _saveEditorRange() {
    if (state.activeEditor && state.activeEditor.editor && state.fileType === 'docx') {
      const slateSelection = state.activeEditor.editor.selection;
      if (slateSelection) {
        state.activeEditor._savedRange = JSON.parse(JSON.stringify(slateSelection));
      }
    }
  }

  document.addEventListener('mouseup', (e) => {
    if (e.target.id === 'wa-pdf-tooltip') return;
    
    // For Luckysheet, we handle selection inside the editor class hook
    if (state.fileType === 'xlsx') return;

    const sel = window.getSelection().toString().trim();
    const tt = $('wa-pdf-tooltip');
    
    if (sel && sel.length > 0) {
      lastSelectionText = sel;
      tt.style.display = 'flex';
      tt.style.left = e.pageX + 10 + 'px';
      tt.style.top = e.pageY + 10 + 'px';

      // If the chip is already showing (prior pinned context), update it immediately
      // so user sees the new selection reflected without needing to click the chat input again
      if ($('wa-selection-chip').style.display !== 'none') {
        _saveEditorRange();
        _pinSelectionChip(sel);
        _clearPinnedHighlight();
        _applyPinnedHighlight();
      }
    } else {
      tt.style.display = 'none';
      lastSelectionText = "";
    }
  });

  document.addEventListener('mousedown', (e) => {
    // Use closest() so clicks on child buttons inside the toolbar don't dismiss it
    if (!e.target.closest('#wa-pdf-tooltip')) {
       $('wa-pdf-tooltip').style.display = 'none';
    }
  });

  window.WA.sendQuickAction = (action) => {
    let sel = lastSelectionText;
    if (state.fileType === 'xlsx' && state.activeEditor) {
      const rangeText = state.activeEditor.getContent();
      if (!rangeText.includes('未选中区域')) {
         sel = "当前选中表格内容已附加";
      }
    }
    if (sel) {
      WA.quickAction(`请${action}以下内容：\n\n"${sel}"`);
      $('wa-pdf-tooltip').style.display = 'none';
    }
  };

  window.WA.sendSelectionToAI = () => {
    let sel = lastSelectionText;
    if (state.fileType === 'xlsx' && state.activeEditor) {
      const rangeText = state.activeEditor.getContent();
      if (!rangeText.includes('未选中区域')) sel = rangeText;
    }
    if (!sel) return;
    _saveEditorRange();
    _applyPinnedHighlight();
    // Pin as Copilot-style chip — user types their question separately
    _pinSelectionChip(sel);
    $('wa-pdf-tooltip').style.display = 'none';
    $('wa-user-input').focus();
  };

  window.WA.clearSelection = () => {
    state.pinnedSelection = '';
    lastSelectionText = '';
    $('wa-selection-chip').style.display = 'none';
    _clearPinnedHighlight();
  };

  // Auto-pin selection when user clicks/focuses the chat input.
  // The browser clears document selection on click, so we capture it here
  // before it disappears — same effect as clicking "💬 转交 AI" manually.
  const _waInput = $('wa-user-input');
  if (_waInput) {
    _waInput.addEventListener('mousedown', () => {
      if (lastSelectionText) {
        // Always update chip — reselecting new text replaces the old context
        _saveEditorRange();
        // For PPTX: save which shape/slide the selection is in so replaceSelectionWith works
        if (state.fileType === 'pptx' && state.activeEditor) {
          const span = document.activeElement;
          if (span && span.classList.contains('wa-pptx-run')) {
            state.activeEditor._pinnedShapeId = parseInt(span.dataset.shapeId);
            state.activeEditor._pinnedSlideIdx = state.activeEditor._curIdx;
          }
        }
        _applyPinnedHighlight();
        _pinSelectionChip(lastSelectionText);
        $('wa-pdf-tooltip').style.display = 'none';
      }
    });
  }

  // ── Split.js Init ──
  Split(['#wa-left', '#wa-canvas', '#wa-ai'], {
    sizes: [15, 55, 30],
    minSize: [150, 400, 250],
    gutterSize: 6,
    snapOffset: 0
  });

  // ── Editor Adapters (Phase 3) ──

  class KotoDocxEditor {
    constructor() {
      this.containerId = 'wa-docx-editor';
      this.editor = null;
      this.toolbar = null;
      $(this.containerId).classList.add('active');
    }

    render(html) {
      // Safely destroy previous instances first
      if (this._mutationObs) { this._mutationObs.disconnect(); this._mutationObs = null; }
      if (this.editor) { try { this.editor.destroy(); } catch(e) { console.warn('[WangEditor destroy]', e); } }
      if (this.toolbar) { try { this.toolbar.destroy(); } catch(e) {} }
      this.editor = null;
      this.toolbar = null;

      // CRITICAL: Always recreate inner containers.
      // WangEditor modifies/replaces the selector's children on destroy().
      this._lastHtml = html;  // Fallback / initial snapshot

      const wrapper = $(this.containerId);
      wrapper.innerHTML = '';
      const tb = document.createElement('div');
      tb.id = 'wa-editor-toolbar';
      const ct = document.createElement('div');
      ct.id = 'wa-editor-content';
      wrapper.appendChild(tb);
      wrapper.appendChild(ct);

      const { createEditor, createToolbar } = window.wangEditor;
      this.editor = createEditor({
        selector: '#wa-editor-content',
        html: html,
        config: {
          placeholder: '开始编辑文档...',
          hoverbarKeys: {},
          MENU_CONF: {
            uploadImage: { base64LimitSize: 5 * 1024 * 1024 },
            insertImage: { checkImage(src) { return true; } },
          },
          onChange: (editor) => {
            // WangEditor v5 passes the editor instance as argument — use it directly.
            try {
              const h = editor.getHtml();
              const stripped = h.replace(/<p><br\s*\/?><\/p>/gi, '').replace(/<p>\s*<\/p>/gi, '').trim();
              if (stripped) this._lastHtml = h;
            } catch(e) {}
            WA.scheduleAutoSave();
          },
        }
      });
      this.toolbar = createToolbar({
        editor: this.editor,
        selector: '#wa-editor-toolbar',
        config: { excludeKeys: ['fullScreen'] }
      });

      // MutationObserver as backup — fires even when WangEditor doesn't trigger onChange.
      // Attach after createEditor() so WangEditor has created its DOM.
      setTimeout(() => {
        if (!this.editor) return;
        const editable = ct.querySelector('[contenteditable="true"]');
        if (!editable) return;
        this._mutationObs = new MutationObserver(() => {
          if (!this.editor) return;
          try {
            const h = this.editor.getHtml();
            const s = h.replace(/<p><br\s*\/?><\/p>/gi, '').replace(/<p>\s*<\/p>/gi, '').trim();
            if (s) this._lastHtml = h;
          } catch(e) {}
        });
        this._mutationObs.observe(editable, { childList: true, subtree: true, characterData: true });
      }, 300);
    }

    getContent() {
      if (!this.editor) return "";
      const selected = this.editor.getSelectionText();
      if (selected) return `[当前选中文本]:\n${selected}\n`;
      return `[文档全文]:\n${this.editor.getText()}\n`;
    }

    serialize() {
      if (!this.editor) return this._lastHtml || "";
      // Prefer MutationObserver-tracked _lastHtml — it's updated synchronously on every DOM change.
      // getHtml() is called as a secondary source in case _lastHtml is stale.
      const domHtml = this._lastHtml || "";
      const editorHtml = (() => { try { return this.editor.getHtml(); } catch(e) { return ""; } })();
      // Pick whichever is longer (more content) — MutationObserver runs async so
      // on the very first save _lastHtml may still be initial; editor.getHtml() is always current.
      const best = (editorHtml.length >= domHtml.length) ? editorHtml : domHtml;
      const stripped = best.replace(/<p><br\s*\/?><\/p>/gi, '').replace(/<p>\s*<\/p>/gi, '').trim();
      return stripped ? best : (domHtml || editorHtml || "");
    }

    applyToolCall(cmd) {
      if (!this.editor) return;
      if (cmd.type === 'set_html' || cmd.type === 'insert_text') {
        const val = cmd.value || '';
        // Restore editor focus so WangEditor re-activates its saved Slate selection/cursor.
        // Without this, dangerouslyInsertHtml has no target and silently does nothing.
        this.editor.focus();
        this.editor.dangerouslyInsertHtml(val);
        this._savedRange = null;
        showToast('AI 已更新文档', 'success');
        WA.scheduleAutoSave();
      }
    }

    destroy() {
      if (this._mutationObs) { this._mutationObs.disconnect(); this._mutationObs = null; }
      if (this.editor) { try { this.editor.destroy(); } catch(e) {} }
      if (this.toolbar) { try { this.toolbar.destroy(); } catch(e) {} }
      this.editor = null;
      this.toolbar = null;
      const wrapper = $(this.containerId);
      if (wrapper) wrapper.classList.remove('active');
    }
  }

  class KotoXlsxEditor {
    constructor() {
      this.containerId = 'wa-xlsx-editor';
      this.created = false;
      this._images = [];   // [{src, x, y, w, h}] for export
      $(this.containerId).classList.add('active');
    }

    render(sheetsJson) {
      // Only destroy if we actually created a sheet (prevents double-destroy error)
      if (this.created) {
        try { window.luckysheet.destroy(); } catch(e) { console.warn('[Luckysheet destroy]', e); }
        this.created = false;
      }
      // Clear stale DOM left by previous Luckysheet instance
      const wrapper = $(this.containerId);
      wrapper.innerHTML = '';

      // ── Image insertion toolbar ──
      const imgBar = document.createElement('div');
      imgBar.className = 'wa-xlsx-imgbar';
      imgBar.innerHTML = `<button class="wa-xlsx-imgbtn" title="插入图片到表格">🖼 插入图片</button>`;
      wrapper.appendChild(imgBar);

      // Sheet container (luckysheet needs a named ID)
      const sheetEl = document.createElement('div');
      sheetEl.id = 'wa-xlsx-sheet';
      sheetEl.style.position = 'relative';
      sheetEl.style.width = '100%';
      sheetEl.style.height = '100%';
      wrapper.appendChild(sheetEl);

      // Image overlay layer (sits on top of sheet)
      const overlayLayer = document.createElement('div');
      overlayLayer.id = 'wa-xlsx-img-layer';
      overlayLayer.style.cssText = 'position:absolute;top:0;left:0;width:100%;height:100%;pointer-events:none;z-index:10;';
      sheetEl.appendChild(overlayLayer);

      window.luckysheet.create({
        container: 'wa-xlsx-sheet',
        lang: 'zh',
        data: sheetsJson,
        showinfobar: false,
        showsheetbar: true,
        showstatisticBar: false,
        sheetFormulaBar: false,
        hook: {
           rangeSelect: (sheet, range) => {
              const tt = $('wa-pdf-tooltip');
              tt.style.display = 'flex';
              tt.style.left = '50%';
              tt.style.top = '100px';
              lastSelectionText = '表格数据';
           }
        }
      });
      this.created = true;

      // Wire up image button
      imgBar.querySelector('.wa-xlsx-imgbtn').addEventListener('click', () => {
        const input = document.createElement('input');
        input.type = 'file';
        input.accept = 'image/png,image/jpeg,image/gif,image/webp';
        input.onchange = (e) => {
          const file = e.target.files[0];
          if (!file) return;
          if (file.size > 5 * 1024 * 1024) { showToast('图片不能超过 5 MB', 'error'); return; }
          const reader = new FileReader();
          reader.onload = (ev) => {
            const src = ev.target.result;
            this._addImageOverlay(src, overlayLayer);
          };
          reader.readAsDataURL(file);
        };
        input.click();
      });
    }

    _addImageOverlay(src, layer) {
      const imgData = { src, x: 20, y: 20, w: 200, h: 150 };
      this._images.push(imgData);
      const idx = this._images.length - 1;

      const wrap = document.createElement('div');
      wrap.style.cssText = `position:absolute;left:${imgData.x}px;top:${imgData.y}px;width:${imgData.w}px;height:${imgData.h}px;pointer-events:all;cursor:move;border:2px dashed #4a9eff;box-sizing:border-box;`;
      const img = document.createElement('img');
      img.src = src;
      img.style.cssText = 'width:100%;height:100%;object-fit:contain;display:block;user-select:none;';
      img.draggable = false;

      // Delete handle
      const del = document.createElement('div');
      del.textContent = '×';
      del.style.cssText = 'position:absolute;top:-10px;right:-10px;width:20px;height:20px;background:#e74c3c;color:#fff;border-radius:50%;text-align:center;line-height:20px;font-size:14px;cursor:pointer;z-index:2;';
      del.onclick = () => { wrap.remove(); this._images.splice(idx, 1); };

      // Resize handle
      const rsz = document.createElement('div');
      rsz.style.cssText = 'position:absolute;bottom:0;right:0;width:12px;height:12px;background:#4a9eff;cursor:se-resize;';

      wrap.appendChild(img);
      wrap.appendChild(del);
      wrap.appendChild(rsz);
      layer.appendChild(wrap);

      // Drag to move
      let dragging = false, ox = 0, oy = 0;
      wrap.addEventListener('mousedown', (e) => {
        if (e.target === rsz || e.target === del) return;
        dragging = true; ox = e.clientX - imgData.x; oy = e.clientY - imgData.y;
        e.preventDefault();
      });
      document.addEventListener('mousemove', (e) => {
        if (!dragging) return;
        imgData.x = e.clientX - ox; imgData.y = e.clientY - oy;
        wrap.style.left = imgData.x + 'px'; wrap.style.top = imgData.y + 'px';
      });
      document.addEventListener('mouseup', () => { dragging = false; });

      // Resize
      let resizing = false, rx = 0, ry = 0, rw = 0, rh = 0;
      rsz.addEventListener('mousedown', (e) => {
        resizing = true; rx = e.clientX; ry = e.clientY; rw = imgData.w; rh = imgData.h;
        e.stopPropagation(); e.preventDefault();
      });
      document.addEventListener('mousemove', (e) => {
        if (!resizing) return;
        imgData.w = Math.max(40, rw + e.clientX - rx);
        imgData.h = Math.max(30, rh + e.clientY - ry);
        wrap.style.width = imgData.w + 'px'; wrap.style.height = imgData.h + 'px';
      });
      document.addEventListener('mouseup', () => { resizing = false; });

      showToast('图片已插入，可拖动调整位置', 'success');
    }

    getContent() {
      if (!window.luckysheet) return "";
      // 获取当前选区数据
      const range = window.luckysheet.getRangeValue();
      if (range && range.length > 0) {
        const text = range.map(row => row.map(cell => cell ? cell.v : '').join('\t')).join('\n');
        return `[当前选中表格数据]:\n${text}\n`;
      }
      return `[当前表格未选中区域，请提示用户框选数据]`;
    }

    // Export all data from the active sheet as CSV (for chart context)
    getCSV() {
      if (!window.luckysheet) return '';
      try {
        const sheets = window.luckysheet.getluckysheetfile();
        const active = sheets.find(s => s.status === 1) || sheets[0];
        if (!active || !active.celldata) return '';
        // Build a 2D array
        const cells = {};
        let maxRow = 0, maxCol = 0;
        for (const cell of active.celldata) {
          const r = cell.r, c = cell.c;
          if (r > maxRow) maxRow = r;
          if (c > maxCol) maxCol = c;
          cells[`${r}_${c}`] = cell.v ? (cell.v.m || cell.v.v || '') : '';
        }
        const rows = [];
        for (let r = 0; r <= maxRow; r++) {
          const row = [];
          for (let c = 0; c <= maxCol; c++) {
            const v = String(cells[`${r}_${c}`] ?? '');
            row.push(v.includes(',') ? `"${v}"` : v);
          }
          rows.push(row.join(','));
        }
        return rows.join('\n');
      } catch (e) {
        return '';
      }
    }

    serialize() {
      const sheets = window.luckysheet ? window.luckysheet.getluckysheetfile() : [];
      return { sheets, _images: this._images };
    }

    applyToolCall(cmd) {
      if (cmd.type === 'set_cell' && window.luckysheet) {
        window.luckysheet.setCellValue(cmd.r, cmd.c, cmd.value);
        showToast(`AI 已更新单元格 (${cmd.r}, ${cmd.c})`, 'success');
        WA.scheduleAutoSave();
      } else if (cmd.type === 'set_cells' && window.luckysheet && Array.isArray(cmd.cells)) {
        cmd.cells.forEach(cell => {
          window.luckysheet.setCellValue(cell.r, cell.c, cell.value);
        });
        showToast(`AI 已批量更新 ${cmd.cells.length} 个单元格`, 'success');
        WA.scheduleAutoSave();
      }
    }

    destroy() {
      if (this.created) {
        try { window.luckysheet.destroy(); } catch(e) { console.warn('[Luckysheet destroy]', e); }
        this.created = false;
      }
      $(this.containerId).classList.remove('active');
    }
  }

  class KotoPptxEditor {
    constructor() {
      this.data = null;
      this._curIdx = 0;
      this._selShape = null;
      this._activeSpan = null;   // last focused run span — persists when toolbar takes focus
      this._insertMode = false;  // true while user is drawing a new text box
      this._editMode = false;    // true when double-clicked into text editing (like PowerPoint)
      this._savedRange = null;   // saved selection range — survives toolbar interactions
      this._canvasMousedownFn = null;  // stored so we can remove stale listeners on re-render
      this._canvasCtxMenuFn = null;
      $('wa-pptx-editor').classList.add('active');
    }

    render(richData) {
      if (Array.isArray(richData)) {
        this.data = this._legacyToRich(richData);
      } else {
        // Normalize snake_case keys returned by Python backend to camelCase used internally
        this.data = {
          slideWidthEmu:  richData.slideWidthEmu  || richData.slide_width_emu  || 9144000,
          slideHeightEmu: richData.slideHeightEmu || richData.slide_height_emu || 6858000,
          slides: richData.slides || [],
        };
      }
      this._curIdx = 0;
      this._buildThumbs();
      this._initKeyHandler();
      const zoomSlider = $('wa-pptx-zoom');
      if (zoomSlider) { zoomSlider.value = 75; this._zoom = 0.75; }
      // Defer first render until after the browser has laid out the flex container
      // so that #wa-pptx-slide-area.clientWidth is non-zero.
      requestAnimationFrame(() => { this._renderSlide(0); WA.pptxZoom && WA.pptxZoom(75); });
    }

    serialize() { return this.data; }

    getContent() {
      // Serialize full current slide with shape IDs so AI can target the right shape
      const slide = this.data && this.data.slides[this._curIdx];
      if (!slide) return '[PPT 大纲未加载]';
      const lines = [];
      (slide.shapes || []).forEach(s => {
        if (s.has_text && s.paragraphs) {
          const text = s.paragraphs.map(p => (p.runs || []).map(r => r.text).join('')).join('\n');
          if (text.trim()) lines.push(`[shape_id=${s.id} name="${s.name}"]: ${text}`);
        }
      });
      return lines.length
        ? `[PPT幻灯片${this._curIdx + 1}内容, slide_index=${this._curIdx}]\n${lines.join('\n')}`
        : `[幻灯片${this._curIdx + 1}无文字内容, slide_index=${this._curIdx}]`;
    }

    applyToolCall(cmd) {
      if (cmd.type !== 'set_pptx_text') return;
      const slide = this.data.slides.find(s => s.index === cmd.slide_index);
      if (!slide) return;
      const shape = slide.shapes.find(s => s.id === cmd.shape_id);
      if (!shape || !shape.paragraphs) return;
      // Preserve formatting from the first run, then replace ALL content
      const refPara = shape.paragraphs[0] || { align: 'LEFT', runs: [] };
      const refRun = (refPara.runs && refPara.runs[0]) || {};
      const newLines = cmd.value.split('\n');
      shape.paragraphs = newLines.map((line, i) => ({
        align: (shape.paragraphs[i] && shape.paragraphs[i].align) || refPara.align || 'LEFT',
        runs: [{ text: line, bold: refRun.bold, italic: refRun.italic,
                 underline: refRun.underline, size: refRun.size,
                 color: refRun.color, fontName: refRun.fontName }],
      }));
      if (this._curIdx === cmd.slide_index) this._renderSlide(cmd.slide_index);
      this._redrawThumb(cmd.slide_index);
      showToast('AI 已更新 PPT 文本', 'success');
      WA.scheduleAutoSave();
    }

    appendToolCall(cmd) {
      if (cmd.type !== 'set_pptx_text') return;
      const slide = this.data.slides.find(s => s.index === cmd.slide_index);
      if (!slide) return;
      const shape = slide.shapes.find(s => s.id === cmd.shape_id);
      if (!shape || !shape.paragraphs) return;
      const lastPara = shape.paragraphs[shape.paragraphs.length - 1];
      const refRun = (lastPara && lastPara.runs && lastPara.runs[0]) || {};
      shape.paragraphs.push({
        runs: [{ text: cmd.value, bold: refRun.bold || false, italic: refRun.italic || false,
                 underline: refRun.underline || false, size: refRun.size || 14,
                 color: refRun.color, fontName: refRun.fontName }],
        align: (lastPara && lastPara.align) || 'LEFT',
      });
      if (this._curIdx === cmd.slide_index) this._renderSlide(cmd.slide_index);
      this._redrawThumb(cmd.slide_index);
      showToast('AI 已追加文本', 'success');
      WA.scheduleAutoSave();
    }

    // Fallback when AI replies plain text (no tool call): use pinned shape context
    replaceSelectionWith(mode, _pinnedText, newText) {
      const shapeId = this._pinnedShapeId;
      const slideIdx = (this._pinnedSlideIdx !== undefined) ? this._pinnedSlideIdx : this._curIdx;
      if (!shapeId) { showToast('请先在幻灯片中选中文字', 'info'); return; }
      const cmd = { type: 'set_pptx_text', slide_index: slideIdx, shape_id: shapeId, value: newText };
      if (mode === 'append') {
        this.appendToolCall(cmd);
      } else {
        this.applyToolCall(cmd);
      }
    }

    destroy() {
      $('wa-pptx-editor').classList.remove('active');
      $('wa-pptx-thumbstrip').innerHTML = '';
      const canvas = $('wa-pptx-slide-canvas');
      if (canvas) canvas.innerHTML = '';
      this._closeCtxMenu();
      document.removeEventListener('keydown', this._keyHandler);
      if (this._selChangeHandler) document.removeEventListener('selectionchange', this._selChangeHandler);
      this.data = null;
    }

    // ── Delete / Duplicate shape ──────────────────────────────────────────────

    deleteShape(shapeId) {
      const slide = this.data.slides[this._curIdx];
      const idx = (slide.shapes || []).findIndex(s => s.id === shapeId);
      if (idx < 0) return;
      slide.shapes.splice(idx, 1);
      this._selShape = null;
      this._activeSpan = null;
      this._renderSlide(this._curIdx);
      this._redrawThumb(this._curIdx);
      WA.scheduleAutoSave();
    }

    deleteSelected() {
      if (!this._selShape) { showToast('请先单击选中一个形状', 'info'); return; }
      const id = parseInt(this._selShape.dataset.shapeId);
      this.deleteShape(id);
    }

    duplicateShape(shapeId) {
      const slide = this.data.slides[this._curIdx];
      const orig = (slide.shapes || []).find(s => s.id === shapeId);
      if (!orig) return;
      const copy = JSON.parse(JSON.stringify(orig));
      copy.id = -(Date.now() % 100000000);
      copy.left += 457200;   // offset 0.5 inch right
      copy.top  += 457200;
      copy.z_order = (slide.shapes.reduce((m, s) => Math.max(m, s.z_order), 0)) + 1;
      slide.shapes.push(copy);
      this._renderSlide(this._curIdx);
      this._redrawThumb(this._curIdx);
      WA.scheduleAutoSave();
    }

    // ── Right-click context menu ──────────────────────────────────────────────

    _showCtxMenu(x, y, shape) {
      this._closeCtxMenu();
      const menu = $('wa-pptx-ctx');
      if (!menu) return;
      const items = [
        { label: '✏️  编辑文字',  action: () => {
            const shapeEl = document.querySelector(`.wa-pptx-shape[data-shape-id="${shape.id}"]`);
            if (shapeEl) this._enterEditMode(shapeEl);
        }},
        { sep: true },
        { label: '⧉  复制形状',  action: () => this.duplicateShape(shape.id) },
        { sep: true },
        { label: '↑  上移一层',  action: () => this._reorder(shape.id, +1) },
        { label: '↓  下移一层',  action: () => this._reorder(shape.id, -1) },
        { sep: true },
        { label: '🗑  删除形状',  danger: true, action: () => this.deleteShape(shape.id) },
      ];

      menu.innerHTML = '';
      items.forEach(item => {
        if (item.sep) {
          const d = document.createElement('div'); d.className = 'wa-pptx-ctx-sep'; menu.appendChild(d);
        } else {
          const div = document.createElement('div');
          div.className = 'wa-pptx-ctx-item' + (item.danger ? ' danger' : '');
          div.textContent = item.label;
          div.addEventListener('mousedown', e => { e.stopPropagation(); item.action(); this._closeCtxMenu(); });
          menu.appendChild(div);
        }
      });

      // Clamp to viewport
      menu.style.display = 'block';
      const vw = window.innerWidth, vh = window.innerHeight;
      const mw = menu.offsetWidth, mh = menu.offsetHeight;
      menu.style.left = Math.min(x, vw - mw - 8) + 'px';
      menu.style.top  = Math.min(y, vh - mh - 8) + 'px';
    }

    _closeCtxMenu() {
      const menu = $('wa-pptx-ctx');
      if (menu) menu.style.display = 'none';
    }

    _showThumbCtxMenu(x, y, idx) {
      this._closeCtxMenu();
      const menu = $('wa-pptx-ctx');
      if (!menu) return;
      const total = this.data.slides.length;
      const items = [
        { label: '➕  新建幻灯片', action: () => WA.pptxAddSlide() },
        { sep: true },
        { label: '🗑  删除此幻灯片', danger: true,
          action: () => { if (total > 1) WA.pptxDelSlide(); else showToast('至少保留一张幻灯片', 'error'); }
        },
      ];
      menu.innerHTML = '';
      items.forEach(item => {
        if (item.sep) {
          const d = document.createElement('div'); d.className = 'wa-pptx-ctx-sep'; menu.appendChild(d);
        } else {
          const div = document.createElement('div');
          div.className = 'wa-pptx-ctx-item' + (item.danger ? ' danger' : '');
          div.textContent = item.label;
          div.addEventListener('mousedown', e => { e.stopPropagation(); item.action(); this._closeCtxMenu(); });
          menu.appendChild(div);
        }
      });
      menu.style.display = 'block';
      const vw = window.innerWidth, vh = window.innerHeight;
      const mw = menu.offsetWidth, mh = menu.offsetHeight;
      menu.style.left = Math.min(x, vw - mw - 8) + 'px';
      menu.style.top  = Math.min(y, vh - mh - 8) + 'px';
    }

    _reorder(shapeId, delta) {
      const slide = this.data.slides[this._curIdx];
      const shape = (slide.shapes || []).find(s => s.id === shapeId);
      if (!shape) return;
      shape.z_order = Math.max(0, shape.z_order + delta);
      this._renderSlide(this._curIdx);
      WA.scheduleAutoSave();
    }

    // ── Keyboard handler ─────────────────────────────────────────────────────

    _initKeyHandler() {
      this._keyHandler = (e) => {
        // Only act when PPTX editor is active and focus is NOT in a text run
        if (!$('wa-pptx-editor').classList.contains('active')) return;
        const active = document.activeElement;
        const inRun = active && active.classList.contains('wa-pptx-run');
        if (e.key === 'Escape') {
          this._closeCtxMenu();
          if (this._editMode) {
            this._exitEditMode();  // exit text editing, stay selected
          } else {
            this._clearSelection();
          }
          return;
        }
        if ((e.key === 'Delete' || e.key === 'Backspace') && !this._editMode) {
          e.preventDefault();
          if (this._selShape) {
            this.deleteSelected();
          } else {
            WA.pptxDelSlide();  // Delete key with no shape selected → delete slide
          }
        }
      };
      document.addEventListener('keydown', this._keyHandler);

      // Save selection range so toolbar interactions (font-size select, etc.) don't lose it
      this._selChangeHandler = () => {
        if (!this._editMode) return;
        const sel = window.getSelection();
        if (sel && sel.rangeCount > 0 && !sel.isCollapsed) {
          const r = sel.getRangeAt(0);
          const startEl = r.startContainer.nodeType === 3 ? r.startContainer.parentElement : r.startContainer;
          if (startEl && startEl.classList && startEl.classList.contains('wa-pptx-run')) {
            this._savedRange = r.cloneRange();
          }
        } else {
          // Collapsed or no selection — only clear saved range when still in edit mode focus
          const active = document.activeElement;
          if (!active || !active.classList.contains('wa-pptx-run')) {
            // Focus left the canvas — keep saved range so toolbar can use it
          } else {
            this._savedRange = null;
          }
        }
      };
      document.addEventListener('selectionchange', this._selChangeHandler);
    }

    _buildThumbs() {
      const strip = $('wa-pptx-thumbstrip');
      strip.innerHTML = '';
      this.data.slides.forEach((slide, idx) => {
        const wrap = document.createElement('div');
        wrap.className = 'wa-pptx-thumb-wrap';
        wrap.dataset.idx = idx;
        const numSpan = document.createElement('span');
        numSpan.className = 'wa-pptx-thumb-idx';
        numSpan.textContent = idx + 1;
        const thumb = document.createElement('div');
        thumb.className = 'wa-pptx-thumb' + (idx === 0 ? ' active' : '');
        const cv = document.createElement('canvas');
        cv.width = 148;
        cv.height = Math.round(148 * this.data.slideHeightEmu / this.data.slideWidthEmu);
        this._drawThumbCanvas(cv, slide);
        thumb.appendChild(cv);
        wrap.appendChild(numSpan);
        wrap.appendChild(thumb);
        wrap.onclick = () => this._renderSlide(idx);
        wrap.oncontextmenu = (e) => {
          e.preventDefault();
          this._renderSlide(idx);
          this._showThumbCtxMenu(e.clientX, e.clientY, idx);
        };
        strip.appendChild(wrap);
      });
    }

    _drawThumbCanvas(cv, slide) {
      const ctx = cv.getContext('2d');
      const sw = cv.width, sh = cv.height;
      const sW = this.data.slideWidthEmu, sH = this.data.slideHeightEmu;
      const scX = sw / sW, scY = sh / sH;
      ctx.fillStyle = slide.background || '#ffffff';
      ctx.fillRect(0, 0, sw, sh);
      (slide.shapes || []).forEach(shape => {
        const x = shape.left * scX, y = shape.top * scY;
        const w = shape.width * scX, h = shape.height * scY;
        if (shape.fill) { ctx.fillStyle = shape.fill; ctx.fillRect(x, y, w, h); }
        // ── Picture: draw image asynchronously onto this canvas ──
        if (shape._type === 'PICTURE' && shape.image_b64) {
          const img = new Image();
          img.onload = () => { ctx.drawImage(img, x, y, w, h); };
          img.src = shape.image_b64;
          // Draw a light grey placeholder immediately (visible before image loads)
          ctx.fillStyle = '#e8e8e8';
          ctx.fillRect(x, y, w, h);
          return;
        }
        // ── Table: draw a simple grid placeholder ──
        if (shape._type === 'TABLE' && shape.cells) {
          ctx.strokeStyle = '#bbb';
          ctx.lineWidth = 0.5;
          ctx.strokeRect(x, y, w, h);
          ctx.fillStyle = '#f5f5f5';
          ctx.fillRect(x, y, w, h);
          return;
        }
        if (shape.has_text && shape.paragraphs) {
          ctx.save(); ctx.beginPath(); ctx.rect(x, y, w, h); ctx.clip();
          let ty = y + 2;
          shape.paragraphs.forEach(para => {
            const lineText = (para.runs || []).map(r => r.text).join('');
            if (!lineText.trim()) { ty += 4; return; }
            const fr = para.runs[0] || {};
            // Fixed scale: pt size relative to standard 540pt slide height
            const px = Math.max(Math.round((fr.size || 12) * sh / 540), 5);
            ctx.font = (fr.bold ? 'bold ' : '') + px + 'px sans-serif';
            ctx.fillStyle = fr.color || '#222';
            ctx.fillText(lineText, x + 2, ty + px);
            ty += px * 1.35;
          });
          ctx.restore();
        }
      });
    }

    _redrawThumb(idx) {
      const thumbs = document.querySelectorAll('.wa-pptx-thumb canvas');
      if (thumbs[idx]) this._drawThumbCanvas(thumbs[idx], this.data.slides[idx]);
    }

    _renderSlide(idx) {
      this._curIdx = idx;
      this._selShape = null;
      this._activeSpan = null;
      this._savedRange = null;   // clear stale selection when slide is re-rendered
      document.querySelectorAll('.wa-pptx-thumb').forEach((el, i) =>
        el.classList.toggle('active', i === idx));
      $('wa-pptx-prev').disabled = (idx === 0);
      $('wa-pptx-next').disabled = (idx === this.data.slides.length - 1);
      const counter = (idx + 1) + ' / ' + this.data.slides.length;
      if ($('wa-pptx-slide-counter')) $('wa-pptx-slide-counter').textContent = counter;

      const slide = this.data.slides[idx];
      const sW = this.data.slideWidthEmu, sH = this.data.slideHeightEmu;
      const area = $('wa-pptx-slide-area');
      const availW = (area ? area.clientWidth : 700) - 48;
      const baseWidth = Math.min(availW, 960);
      const displayWidth = Math.round(baseWidth * (this._zoom || 1));
      const scale = displayWidth / sW;
      const pxW = displayWidth;
      const pxH = Math.round(sH * scale);

      const canvas = $('wa-pptx-slide-canvas');
      canvas.style.width  = pxW + 'px';
      canvas.style.height = pxH + 'px';
      canvas.style.background = slide.background || '#ffffff';
      canvas.innerHTML = '';

      // Ascending z_order: low z = back (appended first), high z = front (appended last, on top in DOM)
      (slide.shapes || []).sort((a, b) => a.z_order - b.z_order).forEach(shape => {
        const el = document.createElement('div');
        el.className = 'wa-pptx-shape';
        el.dataset.shapeId = shape.id;
        el.style.position = 'absolute';
        el.style.left   = Math.round(shape.left   * scale) + 'px';
        el.style.top    = Math.round(shape.top    * scale) + 'px';
        el.style.width  = Math.round(shape.width  * scale) + 'px';
        el.style.height = Math.round(shape.height * scale) + 'px';
        el.style.overflow = 'hidden';
        el.style.boxSizing = 'border-box';
        el.style.zIndex = shape.z_order;   // explicit stacking in case of overlaps
        if (shape.fill) el.style.background = shape.fill;

        if (shape.has_text && shape.paragraphs) {
          el.style.cursor = 'text';
          const inner = document.createElement('div');
          inner.style.cssText = 'width:100%;height:100%;padding:4px 6px;box-sizing:border-box;overflow:hidden;display:flex;flex-direction:column;color:#1a1a1a;';
          shape.paragraphs.forEach((para, pi) => {
            const pEl = document.createElement('div');
            pEl.style.lineHeight = '1.3';
            pEl.style.textAlign = (para.align || 'LEFT').toLowerCase();
            pEl.style.wordBreak = 'break-word';
            pEl.style.minHeight = '1.2em';   // ensures empty paragraphs have clickable height
            (para.runs || []).forEach((run, ri) => {
              const span = document.createElement('span');
              span.className = 'wa-pptx-run';
              span.tabIndex = -1;               // ensures programmatic focus() always works
              span.contentEditable = 'false';   // read-only until double-click enters edit mode
              span.dataset.shapeId = shape.id;
              span.dataset.pi = pi;
              span.dataset.ri = ri;
              span.textContent = run.text;
              span.style.outline = 'none';
              span.style.display = 'inline';
              span.style.whiteSpace = 'pre-wrap';
              span.style.fontSize = Math.max(Math.round((run.size || 14) * scale * 12700), 6) + 'px';
              if (run.bold)      span.style.fontWeight = 'bold';
              if (run.italic)    span.style.fontStyle = 'italic';
              if (run.underline) span.style.textDecoration = 'underline';
              if (run.color)     span.style.color = run.color;
              span.addEventListener('input', () => {
                run.text = span.textContent;
                this._redrawThumb(idx);
                WA.scheduleAutoSave();
              });
              span.addEventListener('focus', () => this._onRunFocus(el, shape, pi, ri, run));
              span.addEventListener('keydown', e => { if (e.key === 'Escape') { this._exitEditMode(); } });
              pEl.appendChild(span);
            });
            if (!(para.runs || []).length) pEl.appendChild(document.createElement('br'));
            inner.appendChild(pEl);
          });
          el.appendChild(inner);
          // Belt-and-suspenders: stop mousedown from reaching shape's move handler
          // when already in edit mode for this shape (prevents move during text drag).
          inner.addEventListener('mousedown', ev => {
            if (this._editMode && this._selShape === el) ev.stopPropagation();
          });
          el.addEventListener('mousedown', e => {
            if (this._insertMode) return;
            // In edit mode on this shape: let browser handle cursor/text-selection
            if (this._editMode && this._selShape === el) return;
            // Track if shape was already selected — a click without drag will enter edit mode
            const enterEdit = shape.has_text && (this._selShape === el) && !this._editMode;
            this._selectShape(el, shape);
            this._startMove(e, el, shape, canvas, scale, enterEdit);
          });
          el.addEventListener('dblclick', e => {
            if (this._insertMode) return;
            e.stopPropagation();
            this._enterEditMode(el);
          });
        } else if (shape._type === 'PICTURE' && shape.image_b64) {
          // ── Image shape ─────────────────────────────────────────────────
          const img = document.createElement('img');
          img.src = shape.image_b64;
          img.style.width = '100%';
          img.style.height = '100%';
          img.style.objectFit = 'contain';
          img.style.display = 'block';
          img.style.pointerEvents = 'none'; // let mousedown fall through to el
          img.draggable = false;
          el.appendChild(img);
          el.style.cursor = 'default';
          el.addEventListener('mousedown', e => {
            if (this._insertMode) return;
            this._selectShape(el, shape);
            this._startMove(e, el, shape, canvas, scale);
          });
        } else if (shape._type === 'TABLE' && shape.cells) {
          // ── Table shape ──────────────────────────────────────────────────
          const rows = shape.table_rows || 0;
          const cols = shape.table_cols || 0;
          const cellMap = {};
          (shape.cells || []).forEach(c => { cellMap[c.row + '_' + c.col] = c.text; });
          const tbl = document.createElement('table');
          tbl.style.cssText = 'width:100%;height:100%;border-collapse:collapse;table-layout:fixed;pointer-events:none;';
          // scale = px/EMU; 12pt at 96dpi ≈ 16px; use pt * 96/72 * scale * EMU_PER_PT
          // Simplified: pt * 12700 EMU/pt * scale (px/EMU) = pt * scale * 12700
          // BUT scale is already ~1.5e-4 so correct formula: 12pt * scale EMU/px = 12*scale*1EMU→
          // Correct: 1pt = 12700 EMU; fontSize_px = pt * 12700 * scale
          const baseFontPx = Math.max(Math.round(10 * 12700 * scale), 6);
          for (let r = 0; r < rows; r++) {
            const tr = document.createElement('tr');
            for (let c = 0; c < cols; c++) {
              const td = document.createElement('td');
              td.style.cssText = `border:1px solid #d0d0d0;padding:2px 4px;overflow:hidden;font-size:${baseFontPx}px;vertical-align:top;word-break:break-word;`;
              td.textContent = cellMap[r + '_' + c] || '';
              tr.appendChild(td);
            }
            tbl.appendChild(tr);
          }
          el.appendChild(tbl);
          el.style.overflow = 'hidden';
          el.addEventListener('mousedown', e => {
            if (this._insertMode) return;
            this._selectShape(el, shape);
            this._startMove(e, el, shape, canvas, scale);
          });
        } else {
          // ── Unknown / connector / group — render invisibly (no dashed box clutter)
          el.style.opacity = '0';
          el.style.pointerEvents = 'none';
        }
        canvas.appendChild(el);

        // Right-click context menu on every shape
        el.addEventListener('contextmenu', e => {
          e.preventDefault();
          e.stopPropagation();
          this._selectShape(el, shape);
          this._showCtxMenu(e.clientX, e.clientY, shape);
        });
      });

      // Remove stale listeners from previous renders before adding new ones
      if (this._canvasMousedownFn) canvas.removeEventListener('mousedown', this._canvasMousedownFn);
      if (this._canvasCtxMenuFn)   canvas.removeEventListener('contextmenu', this._canvasCtxMenuFn);
      this._canvasMousedownFn = e => {
        this._closeCtxMenu();
        if (this._insertMode) {
          this._startInsert(e, canvas, scale);
        } else if (e.target === canvas) {
          this._clearSelection();
        }
      };
      this._canvasCtxMenuFn = e => {
        if (e.target === canvas) { e.preventDefault(); this._closeCtxMenu(); }
      };
      canvas.addEventListener('mousedown', this._canvasMousedownFn);
      canvas.addEventListener('contextmenu', this._canvasCtxMenuFn);

      if (this._insertMode) canvas.style.cursor = 'crosshair';
    }

    // ── Insert text box ──────────────────────────────────────────────────────

    insertTextBox(leftEmu, topEmu, wEmu, hEmu) {
      const newId = -(Date.now() % 100000000);  // negative = new (backend creates it)
      this.data.slides[this._curIdx].shapes.push({
        id: newId, name: 'Text Box', type: 'TEXT_BOX',
        left: leftEmu, top: topEmu,
        width: Math.max(wEmu, 914400),    // min 1 inch wide
        height: Math.max(hEmu, 457200),   // min 0.5 inch tall
        z_order: 999, has_text: true, fill: null,
        paragraphs: [{ align: 'LEFT', runs: [{ text: '' }] }],
      });
      this._renderSlide(this._curIdx);
      this._redrawThumb(this._curIdx);
      // Auto-enter edit mode for newly created text box (double-rAF ensures DOM is fully laid out)
      requestAnimationFrame(() => requestAnimationFrame(() => {
        const span = document.querySelector(`.wa-pptx-run[data-shape-id="${newId}"]`);
        if (span) {
          const shapeEl = span.closest('.wa-pptx-shape');
          if (shapeEl) { this._selectShape(shapeEl, null); this._enterEditMode(shapeEl); }
          this._activeSpan = span;
        }
      }));
      WA.scheduleAutoSave();
    }

    _startInsert(e, canvas, scale) {
      e.preventDefault();
      const rect = canvas.getBoundingClientRect();
      const startX = e.clientX - rect.left;
      const startY = e.clientY - rect.top;

      const overlay = document.createElement('div');
      overlay.style.cssText = 'position:absolute;border:2px dashed #0078d4;background:rgba(0,120,212,.06);pointer-events:none;box-sizing:border-box;z-index:999;';
      overlay.style.left = startX + 'px'; overlay.style.top = startY + 'px';
      overlay.style.width = '0px'; overlay.style.height = '0px';
      canvas.appendChild(overlay);

      const onMove = (ev) => {
        const x = ev.clientX - rect.left, y = ev.clientY - rect.top;
        overlay.style.left   = Math.min(x, startX) + 'px';
        overlay.style.top    = Math.min(y, startY) + 'px';
        overlay.style.width  = Math.abs(x - startX) + 'px';
        overlay.style.height = Math.abs(y - startY) + 'px';
      };

      const onUp = (ev) => {
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
        overlay.remove();

        const x = ev.clientX - rect.left, y = ev.clientY - rect.top;
        const lPx = Math.min(x, startX), tPx = Math.min(y, startY);
        const wPx = Math.abs(x - startX), hPx = Math.abs(y - startY);

        // px → EMU  (scale = baseW / slideWidthEmu, so emu = px / scale)
        const leftEmu = Math.round(lPx / scale);
        const topEmu  = Math.round(tPx / scale);
        // If drag was tiny (just a click), use a default 3" × 1" box
        const wEmu = wPx > 20 ? Math.round(wPx / scale) : 2743200;
        const hEmu = hPx > 10 ? Math.round(hPx / scale) : 914400;

        this._insertMode = false;
        canvas.style.cursor = '';
        const btn = $('wa-pptx-insert-tb');
        if (btn) btn.classList.remove('active');

        this.insertTextBox(leftEmu, topEmu, wEmu, hEmu);
      };

      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
    }

    // ── Drag to move ─────────────────────────────────────────────────────────

    _startMove(e, el, shape, canvas, scale, enterEditOnClick = false) {
      // preventDefault/stopPropagation only happen once movement exceeds threshold.
      e.stopPropagation();

      const startX = e.clientX, startY = e.clientY;
      const origLeft = el.offsetLeft, origTop = el.offsetTop;
      const pxW = canvas.offsetWidth, pxH = canvas.offsetHeight;
      let moved = false;

      const onMove = (ev) => {
        const dx = ev.clientX - startX, dy = ev.clientY - startY;
        if (Math.abs(dx) < 4 && Math.abs(dy) < 4) return;
        ev.preventDefault();
        if (!moved) { window.getSelection && window.getSelection().removeAllRanges(); }
        moved = true;
        el.style.cursor = 'grabbing';
        const newL = Math.max(0, Math.min(pxW - el.offsetWidth,  origLeft + dx));
        const newT = Math.max(0, Math.min(pxH - el.offsetHeight, origTop  + dy));
        el.style.left = newL + 'px';
        el.style.top  = newT + 'px';
      };

      const onUp = (ev) => {
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
        el.style.cursor = shape.has_text ? 'text' : '';
        if (moved) {
          // Write back to data model in EMU
          shape.left = Math.round(parseInt(el.style.left)  / scale);
          shape.top  = Math.round(parseInt(el.style.top)   / scale);
          this._redrawThumb(this._curIdx);
          WA.scheduleAutoSave();
        } else if (enterEditOnClick && shape.has_text && !this._editMode) {
          // Click (no drag) on an already-selected text shape → enter edit mode.
          // Place cursor at click position using caretRangeFromPoint for precision.
          this._enterEditModeAtPoint(el, ev.clientX, ev.clientY);
        }
      };

      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
    }

    // Enter edit mode and try to place the cursor at (x, y) screen coordinates.
    _enterEditModeAtPoint(el, x, y) {
      if (this._editMode && this._selShape === el) return;
      this._editMode = true;
      el.classList.add('wa-pptx-editing');
      el.querySelectorAll('.wa-pptx-run').forEach(s => { s.contentEditable = 'true'; });

      // Attempt precise caret placement at click point
      let placed = false;
      try {
        let range = null;
        if (document.caretRangeFromPoint) {
          range = document.caretRangeFromPoint(x, y);
        } else if (document.caretPositionFromPoint) {
          const pos = document.caretPositionFromPoint(x, y);
          if (pos) { range = document.createRange(); range.setStart(pos.offsetNode, pos.offset); range.collapse(true); }
        }
        if (range) {
          const node = range.startContainer;
          const span = node.nodeType === 3 ? node.parentElement : node;
          if (span && span.classList && span.classList.contains('wa-pptx-run')) {
            const sel = window.getSelection();
            sel.removeAllRanges();
            sel.addRange(range);
            span.focus();
            this._activeSpan = span;
            placed = true;
          }
        }
      } catch (_) { /* ignore */ }

      if (!placed) {
        const first = el.querySelector('.wa-pptx-run');
        if (first) { first.focus(); this._activeSpan = first; }
      }
    }

    _selectShape(el, shape) {
      if (el === this._selShape) return;  // already selected — don't wipe edit mode
      this._clearSelection();
      this._selShape = el;
      el.classList.add('wa-pptx-selected');
    }

    _clearSelection() {
      if (this._selShape) {
        this._selShape.classList.remove('wa-pptx-selected');
        this._selShape.querySelectorAll('.wa-pptx-run').forEach(s => { s.contentEditable = 'false'; });
        this._selShape = null;
      }
      this._editMode = false;
    }

    _enterEditMode(el) {
      if (this._editMode && this._selShape === el) return;  // already editing this shape
      this._editMode = true;
      el.classList.add('wa-pptx-editing');
      el.querySelectorAll('.wa-pptx-run').forEach(s => { s.contentEditable = 'true'; });
      const first = el.querySelector('.wa-pptx-run');
      if (first) {
        first.focus();
        this._activeSpan = first;
        // Explicitly place cursor at end of span so empty spans are reliably typeable
        try {
          const r = document.createRange();
          r.selectNodeContents(first);
          r.collapse(false);   // collapse to end
          const sel = window.getSelection();
          if (sel) { sel.removeAllRanges(); sel.addRange(r); }
        } catch (_) {}
      }
    }

    _exitEditMode() {
      if (this._selShape) {
        this._selShape.classList.remove('wa-pptx-editing');
        this._selShape.querySelectorAll('.wa-pptx-run').forEach(s => {
          s.contentEditable = 'false';
          s.blur();
        });
      }
      this._editMode = false;
    }

    _onRunFocus(shapeEl, shape, pi, ri, run) {
      this._activeSpan = document.activeElement;  // save before focus can move to toolbar
      this._selectShape(shapeEl, shape);
      if ($('wa-pptx-bold'))      $('wa-pptx-bold').classList.toggle('active', !!run.bold);
      if ($('wa-pptx-italic'))    $('wa-pptx-italic').classList.toggle('active', !!run.italic);
      if ($('wa-pptx-underline')) $('wa-pptx-underline').classList.toggle('active', !!run.underline);
      if ($('wa-pptx-fontsize') && run.size) $('wa-pptx-fontsize').value = Math.round(run.size);
      if ($('wa-pptx-fontname') && run.fontName) $('wa-pptx-fontname').value = run.fontName;
      if ($('wa-pptx-fontcolor') && run.color) {
        $('wa-pptx-fontcolor').value = run.color.startsWith('#') ? run.color : '#000000';
        const sw = $('wa-pptx-fontcolor-swatch');
        if (sw) sw.style.background = run.color;
      }
    }

    // Apply a single property to a run data object (no DOM update)
    _applyRunProp(run, prop, value) {
      if (prop === 'bold')      run.bold      = value;
      else if (prop === 'italic')    run.italic    = value;
      else if (prop === 'underline') run.underline = value;
      else if (prop === 'size')      run.size      = parseFloat(value);
      else if (prop === 'fontName')  run.fontName  = value;
      else if (prop === 'color')     run.color     = value;
    }

    applyFormat(prop, value) {
      const slide = this.data.slides[this._curIdx];
      // Prefer _savedRange (set by selectionchange handler) so toolbar clicks don't lose selection
      const browserSel = window.getSelection && window.getSelection();
      const activeRange = (this._savedRange && !this._savedRange.collapsed)
        ? this._savedRange
        : (browserSel && browserSel.rangeCount > 0 && !browserSel.isCollapsed ? browserSel.getRangeAt(0) : null);
      const sel = activeRange ? { isCollapsed: false, rangeCount: 1, getRangeAt: () => activeRange,
        containsNode: (n, p) => browserSel ? browserSel.containsNode(n, p) : activeRange.intersectsNode(n) } : null;

      // ── Case 1: partial selection within ONE span → split run ──────────────
      if (sel && !sel.isCollapsed && sel.rangeCount > 0) {
        const range = sel.getRangeAt(0);
        const startSpan = range.startContainer.nodeType === Node.TEXT_NODE
          ? range.startContainer.parentElement : range.startContainer;
        const endSpan   = range.endContainer.nodeType === Node.TEXT_NODE
          ? range.endContainer.parentElement   : range.endContainer;

        if (startSpan === endSpan && startSpan.classList.contains('wa-pptx-run')) {
          const shapeId = parseInt(startSpan.dataset.shapeId);
          const pi      = parseInt(startSpan.dataset.pi);
          const ri      = parseInt(startSpan.dataset.ri);
          const shape   = (slide.shapes || []).find(s => s.id === shapeId);
          const para    = shape && shape.paragraphs[pi];
          const run     = para && para.runs[ri];
          if (run) {
            const s = range.startOffset, e = range.endOffset;
            const text = run.text;
            // Determine toggle value from current run state
            if (prop === 'bold')      value = !run.bold;
            else if (prop === 'italic')    value = !run.italic;
            else if (prop === 'underline') value = !run.underline;

            if (s === 0 && e === text.length) {
              // Whole span selected — just apply to the run in-place, no split needed
              this._applyRunProp(run, prop, value);
              startSpan.style.fontWeight      = run.bold      ? 'bold'      : '';
              startSpan.style.fontStyle       = run.italic    ? 'italic'    : '';
              startSpan.style.textDecoration  = run.underline ? 'underline' : '';
              if (prop === 'size') {
                const scaleW = parseFloat($('wa-pptx-slide-canvas').style.width) / this.data.slideWidthEmu;
                startSpan.style.fontSize = Math.max(Math.round(run.size * scaleW * 12700), 6) + 'px';
              }
              if (prop === 'fontName') startSpan.style.fontFamily = value;
              if (prop === 'color')    startSpan.style.color = value;
            } else {
              // Partial selection — split into up to 3 sub-runs
              const newRuns = [];
              if (s > 0) newRuns.push({ ...run, text: text.slice(0, s) });
              const mid = { ...run, text: text.slice(s, e) };
              this._applyRunProp(mid, prop, value);
              newRuns.push(mid);
              if (e < text.length) newRuns.push({ ...run, text: text.slice(e) });
              para.runs.splice(ri, 1, ...newRuns);
              this._renderSlide(this._curIdx);
            }
            WA.scheduleAutoSave();
            return;
          }
        }
      }

      // ── Case 2: multi-span selection, focused span, or whole shape ──────────
      const selSpans = [];
      if (sel && !sel.isCollapsed && this._selShape) {
        this._selShape.querySelectorAll('.wa-pptx-run').forEach(s => {
          if (sel.containsNode(s, true)) selSpans.push(s);
        });
      }
      const spansToFormat = selSpans.length > 0
        ? selSpans
        : (this._activeSpan && this._activeSpan.classList.contains('wa-pptx-run'))
            ? [this._activeSpan]
            : (this._selShape ? Array.from(this._selShape.querySelectorAll('.wa-pptx-run')) : []);

      if (!spansToFormat.length) return;

      // For toggle props on multiple spans, determine direction from the first run
      let toggleVal = value;
      spansToFormat.forEach((active, idx) => {
        const shapeId = parseInt(active.dataset.shapeId);
        const pi      = parseInt(active.dataset.pi);
        const ri      = parseInt(active.dataset.ri);
        const shape   = (slide.shapes || []).find(s => s.id === shapeId);
        if (!shape) return;
        const run = shape.paragraphs[pi] && shape.paragraphs[pi].runs[ri];
        if (!run) return;

        // On the first run, fix the toggle direction and reuse for others
        if (idx === 0 && (prop === 'bold' || prop === 'italic' || prop === 'underline')) {
          toggleVal = !run[prop];
        }
        const fVal = (prop === 'bold' || prop === 'italic' || prop === 'underline') ? toggleVal : value;
        this._applyRunProp(run, prop, fVal);

        // Live DOM update (no full re-render needed)
        active.style.fontWeight     = run.bold      ? 'bold'      : '';
        active.style.fontStyle      = run.italic    ? 'italic'    : '';
        active.style.textDecoration = run.underline ? 'underline' : '';
        if (prop === 'size') {
          const scaleW = parseFloat($('wa-pptx-slide-canvas').style.width) / this.data.slideWidthEmu;
          active.style.fontSize = Math.max(Math.round(run.size * scaleW * 12700), 6) + 'px';
        }
        if (prop === 'align') {
          shape.paragraphs[pi].align = value.toUpperCase();
          if (active.parentElement) active.parentElement.style.textAlign = value;
        }
        if (prop === 'fontName') active.style.fontFamily = value;
        if (prop === 'color')    active.style.color = value;
      });
      // Sync toolbar state for the first formatted span
      const firstRun = (() => {
        if (!spansToFormat[0]) return null;
        const sp = spansToFormat[0];
        const shape = (slide.shapes || []).find(s => s.id === parseInt(sp.dataset.shapeId));
        const pi = parseInt(sp.dataset.pi), ri = parseInt(sp.dataset.ri);
        return shape && shape.paragraphs[pi] && shape.paragraphs[pi].runs[ri];
      })();
      if (firstRun) {
        if ($('wa-pptx-bold'))      $('wa-pptx-bold').classList.toggle('active',      !!firstRun.bold);
        if ($('wa-pptx-italic'))    $('wa-pptx-italic').classList.toggle('active',    !!firstRun.italic);
        if ($('wa-pptx-underline')) $('wa-pptx-underline').classList.toggle('active', !!firstRun.underline);
      }
      WA.scheduleAutoSave();
    }

    setZoom(pct) {
      this._zoom = pct / 100;
      this._renderSlide(this._curIdx);
    }

    _legacyToRich(arr) {
      return {
        slideWidthEmu: 9144000, slideHeightEmu: 6858000,
        slides: arr.map(s => ({
          index: s.slide_index,
          background: '#ffffff',
          shapes: s.texts.map(t => ({
            id: t.shape_id, name: t.shape_name, type: 'AUTO_SHAPE',
            left: 0, top: t.is_title ? 0 : 1500000,
            width: 8000000, height: 1200000,
            z_order: 0, has_text: true, fill: null,
            paragraphs: [{ align: 'LEFT', runs: [{ text: t.text }] }]
          }))
        }))
      };
    }
  }
  class KotoPdfViewer {
    constructor() {
      this.containerId = 'wa-pdf-viewer';
      this.pdfUrl = null;
      $(this.containerId).classList.add('active');
      $(this.containerId).addEventListener('mouseup', this.handleMouseUp.bind(this));
      document.addEventListener('mousedown', this.hideTooltip);
    }

    async render(pdfUrl, pagesData) {
      this.pdfUrl = pdfUrl;
      const c = $(this.containerId);
      c.innerHTML = '';

      // Render PDF using PDF.js
      if (typeof pdfjsLib === 'undefined') {
         c.innerHTML = '<div style="color:var(--danger)">PDF.js 加载失败</div>';
         return;
      }

      try {
         const loadingTask = pdfjsLib.getDocument(pdfUrl);
         const pdf = await loadingTask.promise;
         
         for (let i = 1; i <= pdf.numPages; i++) {
            const page = await pdf.getPage(i);
            const scale = 1.5;
            const viewport = page.getViewport({ scale });
            
            const wrap = document.createElement('div');
            wrap.className = 'wa-pdf-page-wrap';
            wrap.id = `pdf-page-${i}`;
            
            const canvas = document.createElement('canvas');
            const context = canvas.getContext('2d');
            canvas.height = viewport.height;
            canvas.width = viewport.width;
            
            wrap.appendChild(canvas);
            c.appendChild(wrap);
            
            await page.render({ canvasContext: context, viewport }).promise;
         }
      } catch (e) {
         c.innerHTML = `<div style="color:var(--danger)">PDF 渲染报错: ${e.message}</div>`;
      }
    }

    handleMouseUp(e) {
      const sel = window.getSelection().toString().trim();
      if (sel) {
         const tt = $('wa-pdf-tooltip');
         tt.style.display = 'block';
         tt.style.left = e.pageX + 10 + 'px';
         tt.style.top = e.pageY + 10 + 'px';
      }
    }

    hideTooltip(e) {
      if(e.target.id !== 'wa-pdf-tooltip') {
         $('wa-pdf-tooltip').style.display = 'none';
      }
    }

    getContent() {
      const sel = window.getSelection().toString().trim();
      return sel ? `[选中的 PDF 文本]:\n${sel}\n` : `[未选中任何 PDF 文本]`;
    }

    serialize() { return null; } // PDF is readonly
    applyToolCall(cmd) {} // Readonly

    destroy() {
      $(this.containerId).classList.remove('active');
      $(this.containerId).innerHTML = '';
      $(this.containerId).removeEventListener('mouseup', this.handleMouseUp);
      document.removeEventListener('mousedown', this.hideTooltip);
    }
  }

  // ── Main Router ──
  const Router = {
    load: async (file) => {
      if (state.isLoading) {
        showToast('文件正在加载中，请稍候...', 'error');
        return;
      }
      state.isLoading = true;
      setLoading(true, `正在打开 ${file.name}…`);
      $('upload-progress').style.width = '30%';
      const formData = new FormData();
      formData.append('file', file);
      // Tell server not to re-copy if this file already lives in the workspace
      if (file._wsPath) formData.append('ws_path', file._wsPath);

      try {
         const res = await fetch('/api/v1/workspace/open_file', {
            method: 'POST',
            body: formData
         });
         const json = await res.json();
         if (!res.ok) throw new Error(json.error || '上传失败');

         $('upload-progress').style.width = '100%';

         state.fileId = json.file_id;
         state.fileType = json.file_type;
         state.fileName = json.file_name;
         const ext = json.file_name.split('.').pop().toLowerCase();
         const wsPath = file._wsPath || json.file_name;   // no uploads/ prefix
         state.wsSourcePath = wsPath;
         state.activeTabPath = wsPath;
         $('wa-file-name').textContent = state.fileName;
         $('wa-save-btn').disabled = (state.fileType === 'pdf');

         // Destroy old editor if it was a different file (not a tab switch)
         if (state.activeEditor) {
           try { state.activeEditor.destroy(); } catch(e) { console.warn('[destroy old editor]', e); }
         }
         state.activeEditor = null;

         // Create/update tab entry
         const existingTabIdx = state.openTabs.findIndex(t => t.path === wsPath);
         const tabEntry = {
           path: wsPath,
           name: json.file_name,
           ext,
           fileType: json.file_type,
           fileId: json.file_id,
           serverData: json.data,
           cache: null,
           modified: false,
           fsHandle: file._fsHandle || null,  // FileSystemFileHandle for write-back to original path
         };
         // Persist fsHandle so it survives tab replacement
         if (file._fsHandle) _fsHandleMap.set(wsPath, file._fsHandle);
         if (existingTabIdx >= 0) {
           state.openTabs[existingTabIdx] = tabEntry;
         } else {
           state.openTabs.push(tabEntry);
         }

         toggleWorkspace(true);

         if (state.fileType === 'docx') {
            state.activeEditor = new KotoDocxEditor();
            state.activeEditor.render(json.data.html);
         } else if (state.fileType === 'xlsx') {
            state.activeEditor = new KotoXlsxEditor();
            state.activeEditor.render(json.data);
         } else if (state.fileType === 'pptx') {
            state.activeEditor = new KotoPptxEditor();
            state.activeEditor.render(json.data);
         } else if (state.fileType === 'pdf') {
            state.activeEditor = new KotoPdfViewer();
            state.activeEditor.render(json.data.raw_url, json.data.pages);
         }

         _renderTabs();
         // Refresh left panel to highlight/show newly-added file
         setTimeout(loadWorkspaceFiles, 600);

      } catch (err) {
         console.error('[WA Router.load]', err);
         showToast(err.message, 'error');
         $('upload-progress').style.width = '0%';
      } finally {
         state.isLoading = false;
         setLoading(false);
      }
    }
  };

  // ── AI Socket Connection (Phase 4) ──
  function initSocket() {
     if (typeof io === 'undefined') {
         // Socket.IO script not loaded yet — retry in 500ms
         console.warn('Socket.IO not ready, retrying in 500ms...');
         const badge = $('wa-ai-model-badge');
         if (badge) badge.textContent = 'Koto AI ⧐';
         setTimeout(initSocket, 500);
         return;
     }
     const badge = $('wa-ai-model-badge');
     if (badge) badge.textContent = 'Koto AI ⧐';
     state.socket = io('/doc', {
       transports: ['polling', 'websocket'],
       reconnection: true,
       reconnectionAttempts: Infinity,
       reconnectionDelay: 1000,
       reconnectionDelayMax: 5000,
     });
     
     state.socket.on('connect', () => {
       const b = $('wa-ai-model-badge');
       if (b) b.textContent = 'Koto AI ●';
     });
     state.socket.on('connect_error', (err) => {
       console.warn('WA Socket connect_error:', err.message);
       const b = $('wa-ai-model-badge');
       if (b) b.textContent = 'Koto AI ○';
     });
     state.socket.on('disconnect', (reason) => {
       console.warn('WA Socket disconnected:', reason);
       const b = $('wa-ai-model-badge');
       if (b) b.textContent = 'Koto AI ○';
     });
     state.socket.on('reconnect', () => {
       const b = $('wa-ai-model-badge');
       if (b) b.textContent = 'Koto AI ●';
     });
     
     state.socket.on('agent_stream_chunk', (data) => {
        const msgs = $('wa-ai-messages');
        let last = msgs.lastElementChild;
        if (!last || !last.classList.contains('streaming')) {
           last = document.createElement('div');
           last.className = 'wa-msg ai streaming';
           last.dataset.raw = '';   // accumulate raw Markdown here
           msgs.appendChild(last);
        }
        last.dataset.raw = (last.dataset.raw || '') + data.chunk;
        // Live preview: strip TOOL blocks for display
        const visible = last.dataset.raw.replace(/<TOOL>.*?<\/TOOL>/gs, '').trim();
        last.textContent = visible;
        msgs.scrollTop = msgs.scrollHeight;
     });

     state.socket.on('agent_task_complete', (data) => {
        const msgs = $('wa-ai-messages');
        const last = msgs.lastElementChild;
        const renderMd = (text) => {
           if (window.marked) {
              try { return window.marked.parse(text || ''); } catch(e) {}
           }
           return (text || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\n/g,'<br>');
        };
        let finalMsgEl = null;
        if (last && last.classList.contains('streaming')) {
           last.classList.remove('streaming');
           const finalText = data.result || '';
           last.innerHTML = renderMd(finalText);
           delete last.dataset.raw;
           finalMsgEl = last;
        } else if (data.result) {
           const msg = document.createElement('div');
           msg.className = 'wa-msg ai';
           msg.innerHTML = renderMd(data.result);
           msgs.appendChild(msg);
           finalMsgEl = msg;
        }
        if (data.result) {
           state.conversation.push({ role: 'assistant', content: data.result });
        }
        state.isLoading = false;
        // Show action bar only when user had a pinned selection (needs user decision).
        // Plain tool-call (no selection) was already auto-applied via doc_tool_call handler.
        if (finalMsgEl && state.lastPinnedSel) {
           finalMsgEl.dataset.rawText = data.result || '';
           msgs.appendChild(_makeAIActionBar());
        }
        msgs.scrollTop = msgs.scrollHeight;
     });

     state.socket.on('doc_tool_call', (cmd) => {
        const msgs = $('wa-ai-messages');
        if (state.aiOutputMode === 'inline') {
           if (!state.lastPinnedSel && state.activeEditor) {
              // No user selection — auto-apply directly into the document
              const note = document.createElement('div');
              note.className = 'wa-tool-notification';
              note.innerHTML = `✨ <b>AI 已写入文档</b>: ${cmd.type}`;
              msgs.appendChild(note);
              try { state.activeEditor.applyToolCall(cmd); } catch(e) { console.warn('applyToolCall failed:', e); }
              state.pendingToolCall = null;
           } else {
              // User had a pinned selection — store and let the action bar handle it
              state.pendingToolCall = cmd;
           }
        } else {
           // Chat-only mode: render HTML content as an in-chat preview instead of writing to document
           if ((cmd.type === 'set_html' || cmd.type === 'insert_text') && cmd.value) {
              const preview = document.createElement('div');
              preview.className = 'wa-msg ai wa-tool-preview';
              preview.innerHTML = cmd.value;
              msgs.appendChild(preview);
           } else if (cmd.type === 'insert_image' && (cmd.src || cmd.value)) {
              const preview = document.createElement('div');
              preview.className = 'wa-msg ai wa-tool-preview';
              const img = document.createElement('img');
              const imgSrc = cmd.src || cmd.value;
              img.src = imgSrc;
              img.style.cssText = 'max-width:100%;border-radius:6px;border:1px solid var(--border)';
              _makeAIImgDraggable(img, imgSrc);
              const dragHint2 = document.createElement('div');
              dragHint2.className = 'wa-chart-drag-hint';
              dragHint2.textContent = '拖动图片即可投放到文档';
              preview.appendChild(img);
              preview.appendChild(dragHint2);
              msgs.appendChild(preview);
           }
        }
        msgs.scrollTop = msgs.scrollHeight;
     });

     // ── Code / Chart execution result ──
     state.socket.on('code_result', (result) => {
        const msgs = $('wa-ai-messages');

        // Remove any streaming placeholder
        const last = msgs.lastElementChild;
        if (last && last.classList.contains('streaming')) {
           last.classList.remove('streaming');
           if (!last.textContent.trim()) last.remove();
        }

        if (result.error) {
           const errDiv = document.createElement('div');
           errDiv.className = 'wa-msg ai';
           errDiv.textContent = `❌ 执行错误：${result.error}`;
           if (result.stderr) errDiv.textContent += `\n\n${result.stderr}`;
           msgs.appendChild(errDiv);
        } else if (result.stdout) {
           const outDiv = document.createElement('div');
           outDiv.className = 'wa-msg-code';
           outDiv.textContent = result.stdout;
           msgs.appendChild(outDiv);
        }

        // Show generated chart images
        const files = result.files || {};
        const fileNames = Object.keys(files);
        if (fileNames.length > 0) {
           fileNames.forEach(fname => {
              const wrapper = document.createElement('div');
              wrapper.className = 'wa-chart-result';
              const img = document.createElement('img');
              img.src = files[fname];
              img.alt = fname;
              const caption = document.createElement('div');
              caption.className = 'wa-chart-caption';
              caption.textContent = fname;
              const dl = document.createElement('div');
              dl.className = 'wa-chart-download';
              dl.textContent = '⬇ 下载图表';
              dl.onclick = () => {
                 const a = document.createElement('a');
                 a.href = files[fname];
                 a.download = fname;
                 a.click();
              };
              wrapper.appendChild(img);
              wrapper.appendChild(caption);
              wrapper.appendChild(dl);
              msgs.appendChild(wrapper);
           });
        } else if (!result.error) {
           const okDiv = document.createElement('div');
           okDiv.className = 'wa-msg ai';
           okDiv.textContent = '✅ 代码执行完成，但未生成图片文件。请确保代码中有 plt.savefig("chart.png") 或 ggsave("chart.png")。';
           msgs.appendChild(okDiv);
        }

        msgs.scrollTop = msgs.scrollHeight;
     });
  }

  // ── Exports to Window ──
  
  window.WA.handleInputKeydown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
       e.preventDefault();
       WA.sendMessage();
    }
  };

  window.WA.quickAction = (text) => {
      $('wa-user-input').value = text;
      WA.sendMessage();
  };

  window.WA.clearChat = () => {
      const msgs = $('wa-ai-messages');
      msgs.innerHTML = '<div class="wa-msg ai">对话已清空。你好！我是 Koto AI 助手，随时可以帮你处理文档内容。</div>';
      state.conversation = [];
  };

  window.WA.pptxSync = (ta) => {
     if(state.activeEditor && state.activeEditor.sync) {
        state.activeEditor.sync(ta);
     }
  };

  window.WA.pptxNav = (delta) => {
     if(state.activeEditor && state.activeEditor._renderSlide) {
        const next = state.activeEditor._curIdx + delta;
        if(next >= 0 && next < state.activeEditor.data.slides.length) {
           state.activeEditor._renderSlide(next);
        }
     }
  };

  window.WA.pptxFmt = (cmd) => {
     if (state.activeEditor && state.activeEditor.applyFormat)
       state.activeEditor.applyFormat(cmd);
  };

  window.WA.pptxAlign = (align) => {
     if (state.activeEditor && state.activeEditor.applyFormat)
       state.activeEditor.applyFormat('align', align);
  };

  window.WA.pptxFontSize = (size) => {
     if (state.activeEditor && state.activeEditor.applyFormat)
       state.activeEditor.applyFormat('size', size);
  };

  window.WA.pptxFontName = (val) => {
     if (state.activeEditor && state.activeEditor.applyFormat)
       state.activeEditor.applyFormat('fontName', val);
  };

  window.WA.pptxFontColor = (val) => {
     const swatch = $('wa-pptx-fontcolor-swatch');
     if (swatch) swatch.style.background = val;
     if (state.activeEditor && state.activeEditor.applyFormat)
       state.activeEditor.applyFormat('color', val);
  };

  window.WA.pptxZoom = (val) => {
     const label = $('wa-pptx-zoom-label');
     if (label) label.textContent = val + '%';
     if (state.activeEditor && state.activeEditor.setZoom)
       state.activeEditor.setZoom(parseInt(val));
  };

  window.WA.pptxDelShape = () => {
     const ed = state.activeEditor;
     if (ed && ed.deleteSelected) ed.deleteSelected();
  };

  window.WA.pptxSwitchTab = (btn, tabName) => {
     document.querySelectorAll('.wa-pptx-rtab').forEach(t => t.classList.remove('active'));
     btn.classList.add('active');
     const toolbar = document.getElementById('wa-pptx-toolbar');
     if (!toolbar) return;
     toolbar.querySelectorAll('[data-tab]').forEach(el => {
       el.style.display = (el.dataset.tab === tabName) ? '' : 'none';
     });
  };

  window.WA.pptxInsertMode = () => {
     const ed = state.activeEditor;
     if (!ed || !ed.data) return;
     ed._insertMode = !ed._insertMode;
     const btn = $('wa-pptx-insert-tb');
     if (btn) btn.classList.toggle('active', ed._insertMode);
     const canvas = $('wa-pptx-slide-canvas');
     if (canvas) canvas.style.cursor = ed._insertMode ? 'crosshair' : '';
     // Reset any focus-scroll that may have shifted #wa-pptx-main
     const mainEl = $('wa-pptx-main');
     if (mainEl) { mainEl.scrollLeft = 0; mainEl.scrollTop = 0; }
     if (ed._insertMode) showToast('在幻灯片上拖拽绘制文本框', 'info');
  };

  window.WA.pptxAddSlide = () => {
     const ed = state.activeEditor;
     if (!ed || !ed.data) return;
     const newIdx = ed.data.slides.length;
     const sW = ed.data.slideWidthEmu  || 9144000;
     const sH = ed.data.slideHeightEmu || 6858000;
     // Default title + body layout matching standard slide proportions
     ed.data.slides.push({
       index: newIdx, background: '#ffffff',
       shapes: [
         {
           id: -(Date.now() % 100000000),
           name: 'Title', type: 'TEXT_BOX',
           left: Math.round(sW * 0.05), top: Math.round(sH * 0.06),
           width: Math.round(sW * 0.9), height: Math.round(sH * 0.18),
           z_order: 1, has_text: true, fill: null,
           paragraphs: [{ align: 'CENTER', runs: [{ text: '点击输入标题', size: 36, bold: true }] }],
         },
         {
           id: -(Date.now() % 100000000) - 1,
           name: 'Content', type: 'TEXT_BOX',
           left: Math.round(sW * 0.05), top: Math.round(sH * 0.30),
           width: Math.round(sW * 0.9), height: Math.round(sH * 0.60),
           z_order: 2, has_text: true, fill: null,
           paragraphs: [{ align: 'LEFT', runs: [{ text: '点击输入内容', size: 24 }] }],
         },
       ],
     });
     ed._buildThumbs();
     ed._renderSlide(newIdx);
     WA.scheduleAutoSave();
  };

  window.WA.pptxDelSlide = () => {
     const ed = state.activeEditor;
     if (!ed || !ed.data || ed.data.slides.length <= 1) { showToast('至少保留一张幻灯片', 'error'); return; }
     const deletedIdx = ed._curIdx;
     ed.data.slides.splice(deletedIdx, 1);
     ed.data.slides.forEach((s, i) => { s.index = i; });
     const newIdx = Math.min(deletedIdx, ed.data.slides.length - 1);
     ed._buildThumbs();
     ed._renderSlide(newIdx);
     WA.scheduleAutoSave();
     showToast(`已删除第 ${deletedIdx + 1} 张幻灯片`, 'info');
  };

  window.WA.pptxSave = () => {
     if (state.activeEditor && state.activeEditor.serialize) {
        WA.saveFile();
     }
  };

  window.WA.pptxDownload = () => {
     if (state.fileId) {
        WA.saveFile().then(() => {
           const a = document.createElement('a');
           a.href = `/api/v1/workspace/download/${state.fileId}`;
           a.download = state.fileName || 'presentation.pptx';
           a.click();
        }).catch(() => {});
     }
  };

  function autoResize(ta) {
    ta.style.height = 'auto';
    ta.style.height = ta.scrollHeight + 'px';
  }

  // ── Chart generation dialog ──
  let _chartLang = 'python';

  window.WA.openChartDialog = (lang) => {
     _chartLang = lang;
     $('wa-chart-dialog-title').textContent = lang === 'python' ? '📊 Python 画图 (matplotlib)' : '📈 R 画图 (ggplot2)';
     // Show data hint
     const hasXlsx = state.fileType === 'xlsx';
     $('wa-chart-data-hint').textContent = hasXlsx
       ? '💡 将自动附上当前表格的全量数据'
       : '💡 请在描述中说明数据或粘贴 CSV';
     $('wa-chart-prompt').value = '';
     $('wa-chart-dialog').classList.add('open');
     setTimeout(() => $('wa-chart-prompt').focus(), 50);
  };

  window.WA.closeChartDialog = () => {
     $('wa-chart-dialog').classList.remove('open');
  };

  window.WA.submitChartRequest = () => {
     const desc = $('wa-chart-prompt').value.trim();
     if (!desc) { showToast('请输入图表描述', 'error'); return; }
     WA.closeChartDialog();

     // Get CSV data if xlsx
     let csvData = '';
     if (state.fileType === 'xlsx' && state.activeEditor && state.activeEditor.getCSV) {
        csvData = state.activeEditor.getCSV();
     }

     const msgs = $('wa-ai-messages');
     // User bubble
     const uMsg = document.createElement('div');
     uMsg.className = 'wa-msg user';
     uMsg.textContent = `📊 ${_chartLang.toUpperCase()} 画图：${desc}`;
     msgs.appendChild(uMsg);
     // Loading bubble
     const loadingMsg = document.createElement('div');
     loadingMsg.className = 'wa-msg ai streaming';
     loadingMsg.textContent = '';
     msgs.appendChild(loadingMsg);
     msgs.scrollTop = msgs.scrollHeight;

     function doChartSend() {
       if (!state.socket || !state.socket.connected) {
          loadingMsg.classList.remove('streaming');
          loadingMsg.textContent = '⚠️ AI 连接未就绪，请确保网络正常并刷新页面重试。';
          return;
       }
       state.socket.emit('doc_ai_request', {
          prompt: desc,
          file_type: state.fileType || 'xlsx',
          file_id: state.fileId || '',
          language: _chartLang,
          csv_data: csvData,
       });
     }

     if (state.socket && state.socket.connected) {
       doChartSend();
     } else {
       let waited = 0;
       const waitChart = setInterval(() => {
         waited += 200;
         if (state.socket && state.socket.connected) {
           clearInterval(waitChart);
           doChartSend();
         } else if (waited >= 5000) {
           clearInterval(waitChart);
           doChartSend();
         }
       }, 200);
     }
  };

  // Close dialog on backdrop click
  $('wa-chart-dialog').addEventListener('click', (e) => {
     if (e.target === $('wa-chart-dialog')) WA.closeChartDialog();
  });

  // ── AI Response Action Bar ─────────────────────────────────────────────────
  function _makeAIActionBar() {
    const bar = document.createElement('div');
    bar.className = 'wa-ai-action-bar';
    bar.innerHTML =
      '<span class="wa-ai-action-label">AI \u56de\u590d\u4e86\uff0c\u5982\u4f55\u5904\u7406\uff1f</span>' +
      '<button class="wa-ai-action-btn primary" onclick="WA.applyAIResponse(\'replace\',this)">\u2705 \u66ff\u6362\u9009\u533a</button>' +
      '<button class="wa-ai-action-btn" onclick="WA.applyAIResponse(\'append\',this)">\ud83d\udcce \u63d2\u5165\u5230\u540e\u9762</button>' +
      '<button class="wa-ai-action-btn muted" onclick="WA.applyAIResponse(\'view\',this)">\ud83d\udc41 \u4ec5\u67e5\u770b</button>';
    return bar;
  }

  window.WA.applyAIResponse = (mode, btn) => {
    const bar = btn.closest('.wa-ai-action-bar');
    if (!bar) return;
    // Locate the AI message immediately before the action bar
    let msgEl = bar.previousElementSibling;
    while (msgEl && !msgEl.classList.contains('wa-msg')) {
      msgEl = msgEl.previousElementSibling;
    }
    const rawText = (msgEl && msgEl.dataset.rawText) ? msgEl.dataset.rawText
                  : (msgEl ? msgEl.textContent : '');

    if (mode !== 'view') {
      if (state.pendingToolCall && state.activeEditor) {
        if (mode === 'replace') {
          state.activeEditor.applyToolCall(state.pendingToolCall);
        } else if (mode === 'append') {
          if (state.activeEditor.appendToolCall) {
            state.activeEditor.appendToolCall(state.pendingToolCall);
          } else {
            state.activeEditor.applyToolCall(state.pendingToolCall);
          }
        }
      } else if (state.lastPinnedSel && state.activeEditor &&
                 typeof state.activeEditor.replaceSelectionWith === 'function') {
        state.activeEditor.replaceSelectionWith(mode, state.lastPinnedSel, rawText);
      } else if (state.lastPinnedSel) {
        showToast('\u65e0\u6cd5\u5b9a\u4f4d\u539f\u59cb\u9009\u533a\uff0c\u5df2\u590d\u5236\u5230\u526a\u8d34\u677f', 'info');
        navigator.clipboard && navigator.clipboard.writeText(rawText).catch(() => {});
      }
    }
    state.pendingToolCall = null;
    state.lastPinnedSel = null;
    bar.remove();
  };

  window.WA.sendMessage = () => {
      const input = $('wa-user-input');
      const text = input.value.trim();
      if (!text) return;

      // Capture and clear pinned selection before rendering
      const pinnedSel = state.pinnedSelection;
      state.lastPinnedSel = pinnedSel || null;
      state.pendingToolCall = null;
      if (pinnedSel) WA.clearSelection();

      const msgs = $('wa-ai-messages');

      // Add user message bubble — with optional Copilot-style quote block
      const uMsg = document.createElement('div');
      uMsg.className = 'wa-msg user';
      if (pinnedSel) {
        const quote = document.createElement('div');
        quote.className = 'wa-msg-quote';
        quote.textContent = pinnedSel.length > 240 ? pinnedSel.substring(0, 240) + '…' : pinnedSel;
        uMsg.appendChild(quote);
        const content = document.createElement('div');
        content.textContent = text;
        uMsg.appendChild(content);
      } else {
        uMsg.textContent = text;
      }
      msgs.appendChild(uMsg);

      // Add loading bubble
      const loadingMsg = document.createElement('div');
      loadingMsg.className = 'wa-msg ai streaming';
      loadingMsg.textContent = '';
      msgs.appendChild(loadingMsg);
      msgs.scrollTop = msgs.scrollHeight;

      input.value = '';
      input.style.height = 'auto';

      const MAX_CONTEXT = 6000;  // ~1500 tokens — prevents stream timeout on large docs
      let contextRaw = state.activeEditor ? state.activeEditor.getContent() : '';
      const context = contextRaw.length > MAX_CONTEXT
          ? contextRaw.substring(0, MAX_CONTEXT) + '\n…[内容过长已截断，请缩小选区]'
          : contextRaw;
      const fileType = state.fileType || 'general';
      // Detect active selection: use pinnedSel for PPTX (no .editor on that class),
      // or the WangEditor selection API for DOCX/XLSX
      const hasSelection = !!(pinnedSel) ||
          !!(state.activeEditor && state.activeEditor.editor &&
             typeof state.activeEditor.editor.getSelectionText === 'function' &&
             state.activeEditor.editor.getSelectionText());

      if (context) {
        $('wa-context-indicator').style.display = 'flex';
        setTimeout(() => $('wa-context-indicator').style.display = 'none', 3000);
      }

      // Push user message to conversation history before sending
      state.conversation.push({ role: 'user', content: text });
      state.isLoading = true;

      // If socket not yet connected, wait up to 5s then send
      function doSend() {
        if (!state.socket || !state.socket.connected) {
            loadingMsg.classList.remove('streaming');
            loadingMsg.textContent = '⚠️ AI 连接未就绪，请确保网络正常并刷新页面重试。';
            msgs.scrollTop = msgs.scrollHeight;
            state.isLoading = false;
            return;
        }
        state.socket.emit('doc_ai_request', {
           prompt: text,
           context: context,
           selection: pinnedSel,
           file_type: fileType,
           file_id: state.fileId || '',
           file_name: state.fileName || '',
           history: state.conversation.slice(-20),
           has_selection: hasSelection,
           output_mode: state.aiOutputMode,
        });
      }

      if (state.socket && state.socket.connected) {
        doSend();
      } else {
        // Wait up to 5s for socket to connect
        let waited = 0;
        const waitInterval = setInterval(() => {
          waited += 200;
          if (state.socket && state.socket.connected) {
            clearInterval(waitInterval);
            doSend();
          } else if (waited >= 5000) {
            clearInterval(waitInterval);
            doSend(); // will show the error message
          }
        }, 200);
      }
  };

  // ── Auto-save ──────────────────────────────────────────────────────────────
  let _autoSaveTimer = null;

  window.WA.setOutputMode = (mode) => {
    state.aiOutputMode = mode;
    localStorage.setItem('wa_ai_output_mode', mode);
    // Update toggle buttons if any exist
    document.querySelectorAll('.wa-output-mode-btn').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.mode === mode);
    });
  };

  window.WA.scheduleAutoSave = () => {
    if (!state.fileId || !state.fileType || state.fileType === 'pdf') return;
    // Mark active tab as modified (dirty indicator)
    const tab = state.openTabs.find(t => t.path === state.activeTabPath);
    if (tab && !tab.modified) { tab.modified = true; _renderTabs(); }
    clearTimeout(_autoSaveTimer);
    const status = $('wa-autosave-status');
    if (status) { status.className = 'saving'; status.textContent = '保存中…'; }
    _autoSaveTimer = setTimeout(WA.autoSave, 2000);
  };

  window.WA.autoSave = async () => {
    if (!state.activeEditor || !state.fileId || !state.fileType || state.fileType === 'pdf') return;
    const status = $('wa-autosave-status');
    try {
      const data = state.activeEditor.serialize();
      const res = await fetch('/api/v1/workspace/auto_save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          file_type: state.fileType,
          file_id: state.fileId,
          ws_source_path: state.wsSourcePath || null,  // write back to original file
          data,
        }),
      });
      if (!res.ok) throw new Error((await res.json()).error || '自动保存失败');
      const json = await res.json();
      const tab = state.openTabs.find(t => t.path === state.activeTabPath);
      if (tab) {
        tab.modified = false;
        if (state.fileType === 'docx' && tab.serverData && data) tab.serverData.html = data;
        _renderTabs();
      }
      if (status) {
        status.className = 'saved';
        status.textContent = `✓ 已保存 ${json.saved_at}`;
        setTimeout(() => { if (status) { status.className = ''; status.textContent = ''; } }, 4000);
      }
    } catch (e) {
      if (status) { status.className = ''; status.textContent = ''; }
      console.warn('[AutoSave]', e.message);
    }
  };

  // MIME types for showSaveFilePicker
  const _MIME = {
    docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    xlsx: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    pptx: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
  };

  let _isSaving = false;
  window.WA.saveFile = async () => {
     if (!state.activeEditor || !state.fileType || state.fileType === 'pdf') return;
     if (_isSaving) return;
     _isSaving = true;
     const btn = $('wa-save-btn');
     btn.disabled = true;
     btn.innerHTML = '保存中...';

     // Capture all mutable state NOW, before any awaits
     const _saveTabPath  = state.activeTabPath;
     const _saveTab      = state.openTabs.find(t => t.path === _saveTabPath);
     const _saveFileId   = state.fileId;
     const _saveFileType = state.fileType;
     const _saveWsPath   = state.wsSourcePath;
     let   _saveFsHandle = (_saveTab && _saveTab.fsHandle) || _fsHandleMap.get(_saveWsPath) || null;

     try {
         // ── Acquire a FileSystemFileHandle if we don't have one yet ──
         // This must happen BEFORE any other await so the browser's user-gesture
         // activation (from Ctrl+S) is still live when showSaveFilePicker is called.
         if (!_saveFsHandle && window.showSaveFilePicker && _saveFileType !== 'pdf') {
           try {
             const ext  = (_saveWsPath || state.fileName || 'file.docx').split('.').pop().toLowerCase();
             const mime = _MIME[ext] || 'application/octet-stream';
             _saveFsHandle = await window.showSaveFilePicker({
               suggestedName: state.fileName || _saveWsPath || `document.${ext}`,
               types: [{ description: '文档', accept: { [mime]: ['.' + ext] } }],
               excludeAcceptAllOption: false,
             });
             // Persist so every future Ctrl+S reuses the same location
             if (_saveTab) _saveTab.fsHandle = _saveFsHandle;
             _fsHandleMap.set(_saveWsPath, _saveFsHandle);
           } catch (pickerErr) {
             if (pickerErr.name === 'AbortError') return; // user cancelled — do nothing
             console.warn('[saveFile] showSaveFilePicker:', pickerErr);
             // not fatal — fall through and do workspace-only save
           }
         }

         const data = state.activeEditor.serialize();
         const res = await fetch('/api/v1/workspace/auto_save', {
             method: 'POST',
             headers: { 'Content-Type': 'application/json' },
             body: JSON.stringify({
               file_type: _saveFileType,
               file_id: _saveFileId,
               ws_source_path: _saveWsPath || null,
               explicit: true,
               data,
             }),
         });

         if (!res.ok) {
             const json = await res.json();
             throw new Error(json.error || '保存失败');
         }

         await res.json();
         if (_saveTab) {
           _saveTab.modified = false;
           if (_saveFileType === 'docx' && _saveTab.serverData) _saveTab.serverData.html = data;
           _renderTabs();
         }

         // Write the saved bytes to the chosen local file
         if (_saveFsHandle) {
           try {
             const rawRes = await fetch(`/api/v1/workspace/raw/${_saveFileId}?_=${Date.now()}`);
             if (rawRes.ok) {
               const bytes = await rawRes.arrayBuffer();
               await _writeToFileHandle(_saveFsHandle, bytes);
               showToast('✓ 已保存', 'success');
             } else {
               showToast('已保存到工作区 (无法写回原始位置)', 'success');
             }
           } catch (fsErr) {
             console.warn('[saveFile] FileSystem write failed:', fsErr);
             showToast('已保存到工作区 (原始文件写入失败)', 'success');
           }
         } else {
           showToast(`已保存`, 'success');
         }
     } catch(e) {
         showToast(e.message, 'error');
     } finally {
         _isSaving = false;
         btn.disabled = false;
         btn.innerHTML = `<svg width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg> 保存`;
     }
  };

  // ── Drag & Drop Events ──
  // ── File System Access API helpers ──
  // When a file is opened via the picker we store its FileSystemFileHandle so Ctrl+S
  // can write bytes directly back to the user's original file on disk.
  async function _openFilePicker() {
    if (window.showOpenFilePicker) {
      try {
        const handles = await window.showOpenFilePicker({
          multiple: false,
          types: [{ description: 'Documents', accept: {
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx'],
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
            'application/vnd.openxmlformats-officedocument.presentationml.presentation': ['.pptx'],
            'application/pdf': ['.pdf'],
          }}],
        });
        if (!handles.length) return;
        const handle = handles[0];
        const file = await handle.getFile();
        file._fsHandle = handle;  // attach handle so Router.load can store it
        Router.load(file);
      } catch (e) {
        if (e.name !== 'AbortError') showToast('无法打开文件: ' + e.message, 'error');
      }
    } else {
      fileInput.click();
    }
  }

  // Write bytes to the stored FileSystemFileHandle (original file on disk)
  async function _writeToFileHandle(handle, bytes) {
    const writable = await handle.createWritable();
    await writable.write(bytes);
    await writable.close();
  }

  function loadFiles(files) {
    Array.from(files).forEach(f => Router.load(f));
  }

  // Center drop zone (shown before any file is opened)
  const dropZone = $('wa-drop-inner');
  const fileInput = $('wa-file-input');

  dropZone.addEventListener('dragover', (e) => { e.preventDefault(); dropZone.classList.add('drag-over'); });
  dropZone.addEventListener('dragleave', () => dropZone.classList.remove('drag-over'));
  dropZone.addEventListener('drop', (e) => {
     e.preventDefault();
     dropZone.classList.remove('drag-over');
     if (e.dataTransfer.files.length) loadFiles(e.dataTransfer.files);
  });
  dropZone.addEventListener('click', () => _openFilePicker());
  fileInput.addEventListener('change', (e) => { if (e.target.files.length) loadFiles(e.target.files); });

  // Left panel drop zone
  const leftDrop = $('wa-left-drop');
  const fileInputLeft = $('wa-file-input-left');

  leftDrop.addEventListener('dragover', (e) => { e.preventDefault(); leftDrop.classList.add('drag-over'); });
  leftDrop.addEventListener('dragleave', () => leftDrop.classList.remove('drag-over'));
  leftDrop.addEventListener('drop', (e) => {
     e.preventDefault();
     leftDrop.classList.remove('drag-over');
     if (e.dataTransfer.files.length) loadFiles(e.dataTransfer.files);
  });
  leftDrop.addEventListener('click', () => _openFilePicker());
  fileInputLeft.addEventListener('change', (e) => { if (e.target.files.length) loadFiles(e.target.files); });

  // Whole-canvas drag-drop (works even when a file is already open)
  const canvas = $('wa-canvas');
  canvas.addEventListener('dragover', (e) => { e.preventDefault(); });
  canvas.addEventListener('drop', (e) => {
    e.preventDefault();
    if (e.dataTransfer.files.length) loadFiles(e.dataTransfer.files);
  });

  // Init
  initSocket();
  loadWorkspaceFiles();

  // ── Local file / folder pickers ──
  const localFileInput = $('wa-local-file-input');
  const localFolderInput = $('wa-local-folder-input');

  $('wa-pick-local-file-btn').addEventListener('click', () => _openFilePicker());
  $('wa-pick-local-folder-btn').addEventListener('click', () => localFolderInput.click());

  localFileInput.addEventListener('change', (e) => {
    if (e.target.files.length) loadFiles(e.target.files);
    e.target.value = '';
  });

  localFolderInput.addEventListener('change', (e) => {
    const files = Array.from(e.target.files).filter(f => {
      const ext = f.name.split('.').pop().toLowerCase();
      return ['docx', 'xlsx', 'pptx', 'pdf'].includes(ext);
    });
    if (!files.length) { showToast('未找到支持的文件格式', 'error'); e.target.value = ''; return; }
    // Show folder contents in a picker-style list so user chooses which to open
    const pick = document.createElement('div');
    pick.style.cssText = 'position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);background:var(--surface2);border:1px solid var(--border);border-radius:10px;padding:16px;min-width:280px;max-height:60vh;overflow-y:auto;z-index:9999;box-shadow:0 8px 32px rgba(0,0,0,.5)';
    pick.innerHTML = `<div style="font-weight:700;margin-bottom:10px;font-size:13px">📁 选择要打开的文件</div>` +
      files.map((f, i) => {
        const icon = _EXT_ICON[f.name.split('.').pop().toLowerCase()] || '📄';
        return `<div onclick="window._pickFolderFile(${i})" style="padding:7px 10px;border-radius:6px;cursor:pointer;font-size:12px;display:flex;align-items:center;gap:8px;transition:.15s" onmouseover="this.style.background='var(--hover)'" onmouseout="this.style.background=''">${icon} ${f.name}</div>`;
      }).join('') +
      `<div onclick="document.body.removeChild(this.closest('[style*=fixed]'))" style="margin-top:10px;text-align:right;font-size:12px;color:var(--text-muted);cursor:pointer">取消</div>`;
    document.body.appendChild(pick);
    window._pickFolderFile = (i) => {
      document.body.removeChild(pick);
      Router.load(files[i]);
      e.target.value = '';
    };
  });

  // ─── Embedded-mode public API (文件工作站嵌入主窗口) ──────────────────────
  // Detects whether this script is loaded inside /app (index.html) which
  // contains #workspaceView, or on the standalone /workspace-assistant page.
  const _isEmbedded = !!document.getElementById('workspaceView');

  window.WA.openInMainView = function () {
    const shell    = document.querySelector('.app-shell');
    const chatView = document.getElementById('chatView');
    const wsView   = document.getElementById('workspaceView');
    if (!wsView) {
      // Fallback: no embedded container → open standalone tab
      window.open('/workspace-assistant', '_blank');
      return;
    }
    // Collapse left sidebar so workspace gets full width
    if (shell && !shell.classList.contains('sidebar-collapsed')) {
      if (typeof toggleSidebar === 'function') toggleSidebar();
      else shell.classList.add('sidebar-collapsed');
    }
    // Highlight active nav button
    document.querySelectorAll('.sb-nav-item').forEach(el => el.classList.remove('active'));
    const navBtn = document.getElementById('navWorkspaceBtn');
    if (navBtn) navBtn.classList.add('active');
    // Swap views
    if (chatView) chatView.style.display = 'none';
    wsView.style.display = 'flex';
    localStorage.setItem('koto.inWorkspace', '1');
    // Load workspace files on first open
    if (typeof loadWorkspaceFiles === 'function') loadWorkspaceFiles();
  };

  window.WA.closeInMainView = function () {
    const chatView = document.getElementById('chatView');
    const wsView   = document.getElementById('workspaceView');
    if (wsView)   wsView.style.display   = 'none';
    if (chatView) chatView.style.display = '';
    localStorage.removeItem('koto.inWorkspace');
    // Restore nav highlight
    document.querySelectorAll('.sb-nav-item').forEach(el => el.classList.remove('active'));
  };

  // Auto-restore workspace view after page reload while user was in workspace
  if (_isEmbedded && localStorage.getItem('koto.inWorkspace') === '1') {
    requestAnimationFrame(() => window.WA.openInMainView());
  }

})();
