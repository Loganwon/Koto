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
    lockedModel: localStorage.getItem('wa_locked_model') || 'auto',  // preferred AI model
    _streamAbortCtrl: null,  // AbortController for the active chat stream
    _recentOpen: true,     // recent files section expanded state
    _workspacePath: '',    // absolute workspace root path for openRecentFile comparison
    // ── File system browser state (replaces single-workspace tree) ──
    _browserRoots: null,       // {drives:[...], quick_access:[...]} loaded once
    _browserExpanded: new Set(), // set of absolute paths currently expanded
    _browserCache: {},         // absPath → entries[] | 'loading'
    _fsClipboard: null,        // {path, name, mode:'copy'|'cut'} for copy/cut/paste
    _searchFilter: 'all',      // active type filter chip: 'all'|'文档'|'表格'|'图片'|'代码'|'其他'
    _searchActive: false,      // true when showing flat search results
    _browserSort: localStorage.getItem('wa_browser_sort') || 'name',  // 'name'|'date'|'type'
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
    _updateStatusBar();
  }

  async function _switchToTab(path) {
    if (state.activeTabPath === path) return;

    // Serialize + cache current tab before switching
    if (state.activeEditor && state.activeTabPath) {
      const curTab = state.openTabs.find(t => t.path === state.activeTabPath);
      if (curTab && state.fileType !== 'pdf') {
        curTab.cache = state.activeEditor.serialize();
      }
      // Serialize into cache so we can restore when switching back — no disk write
      try {
            state.activeEditor.destroy();
          } catch(e) {
            console.error('Editor destroy failed:', e);
            const canvas = document.getElementById('wa-canvas');
            if (canvas) canvas.innerHTML = '';
          }
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
    const _saveAsBtn = $('wa-saveas-btn'); if (_saveAsBtn) _saveAsBtn.disabled = (tab.fileType === 'pdf');
    const _archBtn1 = $('wa-archive-btn'); if (_archBtn1) _archBtn1.disabled = false;
    const _histBtn  = $('wa-history-btn'); if (_histBtn) _histBtn.disabled = false;
    _updateSubjectBar(tab.name, tab.fileType);
    toggleWorkspace(true);

    // Show PDF/DOCX zoom control only when the relevant file type is open
    const _pdfZoomCtrl = $('wa-pdf-zoom-ctrl');
    if (_pdfZoomCtrl) _pdfZoomCtrl.style.display = (tab.fileType === 'pdf') ? 'flex' : 'none';
    const _docxZoomCtrl = $('wa-docx-zoom-ctrl');
    if (_docxZoomCtrl) _docxZoomCtrl.style.display = (tab.fileType === 'docx') ? 'flex' : 'none';

    // Guard: wait for the target editor container to be fully laid out before
    // mounting dimension-sensitive editors (mirrors the same guard in Router.load).
    await _waitForEditorLayout(tab.fileType);

    const data = tab.cache;
    if (tab.fileType === 'docx') {
      await _ensureWangEditor();
      state.activeEditor = new KotoDocxEditor();
      // Use cache if it has real content, otherwise fall back to server HTML
      const docxHtml = (data && typeof data === 'string' && data.replace(/<p><br\s*\/?><\/p>/gi,'').trim()) ? data : tab.serverData.html;
      state.activeEditor.render(docxHtml);
    } else if (tab.fileType === 'xlsx') {
      await _ensureUniverSheets();
      state.activeEditor = new KotoXlsxEditor();
      // cache is {snapshot: IWorkbookData, _images} from serialize(); fall back to serverData
      const xlsxData = _ensureWorkbookDefaults((data && data.snapshot) ? data.snapshot : tab.serverData);
      state.activeEditor.render(xlsxData);
    } else if (tab.fileType === 'pptx') {
      state.activeEditor = new KotoPptxEditor();
      state.activeEditor.render(data !== null && data !== undefined ? data : tab.serverData);
    } else if (tab.fileType === 'pdf') {
      await _ensurePdfJS();
      state.activeEditor = new KotoPdfViewer();
      state.activeEditor.render(tab.serverData.raw_url, tab.serverData.pages);
    } else if (tab.fileType === 'text' || tab.fileType === 'code') {
      state.activeEditor = new KotoTextEditor(tab.fileType);
      state.activeEditor.render(data !== null && data !== undefined ? data : tab.serverData);
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

    // Warn before discarding unsaved changes
    if (tab.modified) {
      if (!confirm(`"${tab.name}" 有未保存的修改，关闭后将丢失。\n是否继续关闭？`)) return;
    }

    const isActive = tab.path === state.activeTabPath;

    if (isActive) {
      if (state.activeEditor) {
        try {
            state.activeEditor.destroy();
          } catch(e) {
            console.error('Editor destroy failed:', e);
            const canvas = document.getElementById('wa-canvas');
            if (canvas) canvas.innerHTML = '';
          }
        state.activeEditor = null;
      }
      state.activeTabPath = null;
      state.fileId = null;
      state.fileType = null;
      state.fileName = null;
      state.wsSourcePath = null;
      $('wa-file-name').textContent = '全格式 AI 工作区';
      $('wa-save-btn').disabled = true;
      const _saBtn1 = $('wa-saveas-btn'); if (_saBtn1) _saBtn1.disabled = true;
      const _archBtn2 = $('wa-archive-btn'); if (_archBtn2) _archBtn2.disabled = true;
      _updateSubjectBar(null, null);
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

  /**
   * Wait until the editor container for a given fileType has non-zero layout
   * dimensions and is visible in the DOM.  Returns a Promise that resolves when
   * the container is ready, or rejects after `timeoutMs`.
   *
   * This guards against the embedded-mode race where #workspaceView transitions
   * from display:none → flex immediately before Router.load or _switchToTab
   * attempts to mount Univer or the PPTX canvas — both requiring real pixel
   * dimensions to initialise correctly.
   *
   * @param {string} fileType  – 'xlsx' | 'pptx' | any other type (resolves immediately)
   * @param {number} timeoutMs – max wait (default 800 ms)
   */
  function _waitForEditorLayout(fileType, timeoutMs = 800) {
    const containerId = fileType === 'xlsx' ? 'wa-xlsx-editor'
                      : fileType === 'pptx' ? 'wa-pptx-editor'
                      : null;
    if (!containerId) return Promise.resolve();  // DOCX / PDF don't have layout deps
    return new Promise((resolve, reject) => {
      const deadline = Date.now() + timeoutMs;
      function check() {
        const el = document.getElementById(containerId);
        if (el && el.offsetWidth > 0 && el.offsetHeight > 0) {
          resolve();
          return;
        }
        if (Date.now() >= deadline) {
          console.warn('[WA] _waitForEditorLayout timeout for', containerId,
            'offsetW:', el ? el.offsetWidth : 'null',
            'offsetH:', el ? el.offsetHeight : 'null');
          resolve();  // proceed anyway — editors have their own fallback retries
          return;
        }
        requestAnimationFrame(check);
      }
      requestAnimationFrame(check);
    });
  }

  function showToast(msg, type = 'success', duration = 3000) {
    const t = $('wa-toast');
    t.textContent = msg;
    t.className = type + ' show';
    setTimeout(() => { t.className = t.className.replace('show', ''); }, duration);
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

  // ── Additional file type SVGs (code / image / text) ──────────────────────
  const _CODE_SVG = `<svg viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg"><path d="M3 2h7l3 3v9a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1z" fill="#519aba"/><path d="M10 2v3h3" fill="none" stroke="white" stroke-width="0.7" opacity="0.5"/><text x="3" y="12" font-size="5" font-family="monospace" fill="white" opacity="0.9">&lt;/&gt;</text></svg>`;
  const _MD_SVG = `<svg viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg"><path d="M3 2h7l3 3v9a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1z" fill="#5c6bc0"/><path d="M10 2v3h3" fill="none" stroke="white" stroke-width="0.7" opacity="0.5"/><path d="M4 10V6l1.5 2L7 6v4" stroke="white" stroke-width="0.9" fill="none"/><path d="M8.5 6v4M11 6l-1.5 2.5L11 10" stroke="white" stroke-width="0.9" fill="none"/></svg>`;
  const _IMG_SVG = `<svg viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg"><rect x="1.5" y="2.5" width="13" height="11" rx="1" fill="#4caf50"/><circle cx="5" cy="6" r="1.2" fill="white" opacity="0.9"/><path d="M1.5 10l3.5-3 3 3.5 2.5-2 3 3.5" stroke="white" stroke-width="0.9" fill="none" opacity="0.85"/></svg>`;
  const _TXT_SVG = `<svg viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg"><path d="M3 2h7l3 3v9a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1z" fill="#75828d"/><path d="M10 2v3h3" fill="none" stroke="white" stroke-width="0.7" opacity="0.5"/><rect x="4" y="6" width="5" height="0.9" rx="0.3" fill="white" opacity="0.7"/><rect x="4" y="8" width="5" height="0.9" rx="0.3" fill="white" opacity="0.7"/><rect x="4" y="10" width="3.5" height="0.9" rx="0.3" fill="white" opacity="0.5"/></svg>`;

  // VS Code-style SVG file type icons
  const _FILE_SVGS = {
    docx: `<svg viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg"><rect x="2" y="1" width="9" height="13" rx="1" fill="#2b579a"/><path d="M11 1l3 3v10H11V1z" fill="#1a3f6f"/><path d="M11 1v3h3" fill="none" stroke="white" stroke-width="0.5" opacity="0.4"/><rect x="4" y="5" width="5" height="1" rx="0.4" fill="white" opacity="0.85"/><rect x="4" y="7" width="5" height="1" rx="0.4" fill="white" opacity="0.85"/><rect x="4" y="9" width="3.5" height="1" rx="0.4" fill="white" opacity="0.6"/></svg>`,
    xlsx: `<svg viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg"><rect x="2" y="1" width="9" height="13" rx="1" fill="#217346"/><path d="M11 1l3 3v10H11V1z" fill="#165b32"/><path d="M4.5 5.5l1.5 2-1.5 2M7 5.5l1.5 2-1.5 2" stroke="white" stroke-width="0.9" stroke-linecap="round" fill="none" opacity="0.85"/></svg>`,
    pptx: `<svg viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg"><rect x="2" y="1" width="9" height="13" rx="1" fill="#c43e1c"/><path d="M11 1l3 3v10H11V1z" fill="#8c2d13"/><rect x="3.5" y="4.5" width="6" height="3.5" rx="0.5" fill="white" opacity="0.7"/><rect x="3.5" y="9.5" width="5" height="0.8" rx="0.3" fill="white" opacity="0.5"/><rect x="3.5" y="11" width="3.5" height="0.8" rx="0.3" fill="white" opacity="0.5"/></svg>`,
    pdf: `<svg viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg"><rect x="2" y="1" width="9" height="13" rx="1" fill="#e74c3c"/><path d="M11 1l3 3v10H11V1z" fill="#a93226"/><text x="3.2" y="10.5" font-size="4.5" font-family="sans-serif" font-weight="bold" fill="white" opacity="0.9">PDF</text></svg>`,
  };
  const _DEFAULT_FILE_SVG = `<svg viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg"><path d="M3 2h7l3 3v9a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1z" fill="#75828d"/><path d="M10 2v3h3" fill="none" stroke="white" stroke-width="0.7" opacity="0.5"/></svg>`;
  // Extend _FILE_SVGS with additional types after definition
  function _resolveFileIcon(ext, category) {
    const s = _FILE_SVGS[ext];
    if (s) return `<span class="wa-file-icon">${s}</span>`;
    if (category === 'code') return `<span class="wa-file-icon">${_CODE_SVG}</span>`;
    if (category === 'image') return `<span class="wa-file-icon">${_IMG_SVG}</span>`;
    if (ext === 'md' || ext === 'markdown') return `<span class="wa-file-icon">${_MD_SVG}</span>`;
    if (category === 'text') return `<span class="wa-file-icon">${_TXT_SVG}</span>`;
    return `<span class="wa-file-icon">${_DEFAULT_FILE_SVG}</span>`;
  }
  const _FOLDER_OPEN_SVG = `<svg viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg"><path d="M1.5 4a1 1 0 0 1 1-1H5.6l1.2 1.5H13.5a1 1 0 0 1 1 1v6a1 1 0 0 1-1 1h-11a1 1 0 0 1-1-1V4z" fill="#dcb67a"/><path d="M1.5 6.5h13" stroke="white" stroke-width="0.5" opacity="0.3"/></svg>`;
  const _FOLDER_SVG = `<svg viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg"><path d="M1.5 4a1 1 0 0 1 1-1H5.6l1.2 1.5H13.5a1 1 0 0 1 1 1v6a1 1 0 0 1-1 1h-11a1 1 0 0 1-1-1V4z" fill="#c09a5a"/></svg>`;
  function _fileIcon(ext, category) { return _resolveFileIcon(ext, category); }

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
    // Update workspace metadata then soft-refresh the FS browser.
    // (Kept for backward compatibility — called after file ops like rename/delete/create.)
    try {
      const res = await fetch('/api/v1/workspace/current_dir');
      if (res.ok) {
        const d = await res.json();
        state._workspaceName = d.name || 'workspace';
        state._workspacePath = d.path || '';
        _renderWorkspaceRoot();
      } else { throw new Error(res.status); }
    } catch (err) {
      console.error('Fetch dir error', err);
      showToast('获取工作区目录网络异常...', 'error');
    }
    await _softRefreshBrowser();
  }

  function _renderWorkspaceRoot() {
    const el = $('wa-ws-root-label');
    if (el) {
      el.textContent = (state._workspaceName || 'workspace').toUpperCase();
      el.title = state._workspacePath || '';
    }
    const pt = $('wa-panel-title-ws');
    if (pt) pt.textContent = state._workspaceName || 'workspace';
  }

  function _renderWorkspaceTree() {
    // No-op: replaced by _renderBrowserTree() in full-FS browser mode.
    // Kept so existing call sites don't throw.
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
    if (!state.searchQuery) {
      state._searchActive = false;
      _renderBrowserTree();
    } else {
      _doSearch();
    }
  };

  window.WA.setSearchFilter = (cat) => {
    state._searchFilter = cat;
    document.querySelectorAll('.wa-filter-chip').forEach(el => {
      el.classList.toggle('active', el.dataset.cat === cat);
    });
    if (state.searchQuery) _doSearch();
    else { state._searchActive = false; _renderBrowserTree(); }
  };

  window.WA.clearSearch = () => {
    const input = $('wa-search');
    if (input) input.value = '';
    WA.filterFiles('');
  };

  window.WA.toggleSection = (id) => {
    state.sectionOpen[id] = !state.sectionOpen[id];
    localStorage.setItem('wa_sections', JSON.stringify(state.sectionOpen));
    if (id === 'myworkspace') {
      _toggleMyWorkspaceSection();
    } else if (id === 'tmpworkspace') {
      _toggleTempWorkspaceSection();
    } else {
      _renderWorkspaceTree();
    }
  };

  // ── Recent files section  ─────────────────────────────────────────────────
  // Tracks user-opened files in localStorage (not system mtime).
  const _WA_RECENT_KEY = 'wa_user_recent_v1';

  function _trackUserOpen(path) {
    if (!path) return;
    const name = path.split(/[\\/]/).pop() || path;
    try {
      const list = JSON.parse(localStorage.getItem(_WA_RECENT_KEY) || '[]');
      const filtered = list.filter(f => f.path !== path);
      filtered.unshift({ path, name, ts: Date.now() });
      localStorage.setItem(_WA_RECENT_KEY, JSON.stringify(filtered.slice(0, 30)));
    } catch(e) {}
  }

  async function loadRecentFiles() {
    const list = document.getElementById('wa-recent-list');
    if (!list) return;
    let userRecent = [];
    // Phase 4: try backend first (richer metadata)
    try {
      const res = await fetch('/api/files/recent?days=30&limit=20');
      if (res.ok) {
        const d = await res.json();
        if (d.files && d.files.length) {
          const backendPaths = new Set(d.files.map(f => f.path));
          const localExtra = (() => { try { return JSON.parse(localStorage.getItem(_WA_RECENT_KEY) || '[]'); } catch(_) { return []; } })();
          userRecent = [
            ...d.files.map(f => ({
              path: f.path, name: f.name,
              ts: ((f.mtime || 0) * 1000) || Date.now(),
              category: f.category, size_bytes: f.size_bytes,
            })),
            ...localExtra.filter(f => !backendPaths.has(f.path)).slice(0, 5),
          ].slice(0, 20);
        }
      }
    } catch (_) {}
    // Fallback to localStorage
    if (!userRecent.length) {
      try { userRecent = JSON.parse(localStorage.getItem(_WA_RECENT_KEY) || '[]'); } catch(_) {}
    }
    if (!userRecent.length) {
      list.innerHTML = '<div class="wa-empty-row">暂无最近文件</div>';
      return;
    }
    list.innerHTML = userRecent.slice(0, 20).map(f => {
      const name = f.name || (f.path || '').split(/[\\/]/).pop() || '';
      const ext  = (name.includes('.') ? name.split('.').pop() : '').toLowerCase();
      const icon = _fileIcon(ext, f.category || null);
      const date = f.ts ? new Date(f.ts).toLocaleDateString('zh-CN') : '';
      const size = f.size_bytes ? ' · ' + _formatSize(f.size_bytes) : '';
      const supported = _isSupportedExt(ext);
      return `<div class="wa-file-item" title="${_escHtml(f.path || '')}"
        data-path="${_escHtml(f.path || '')}" data-supported="${supported}"
        onclick="WA.openRecentFile(${JSON.stringify(f.path || '')})"
        oncontextmenu="event.preventDefault();event.stopPropagation();WA._showBrowserCtx(event,this)">
        <span style="padding-left:8px"></span>
        ${icon}
        <span class="wa-file-label">${_escHtml(name)}</span>
        <span class="wa-recent-date">${date}${size}</span>
      </div>`;
    }).join('');
  }

  window.WA.openRecentFile = async (filePath) => {
    if (!filePath) return;
    _trackUserOpen(filePath);  // record user-open event immediately
    // Check if this path is inside the workspace — if so use normal open
    const workspacePath = (state._workspacePath || '').replace(/\\/g, '/');
    const normalizedPath = filePath.replace(/\\/g, '/');
    const isInWorkspace = workspacePath && normalizedPath.startsWith(workspacePath);
    if (isInWorkspace) {
      // Derive relative path within workspace
      const rel = normalizedPath.slice(workspacePath.length).replace(/^\//, '');
      WA.openWorkspaceFile(rel);
      return;
    }
    // External file — open via open_file_by_path endpoint
    try {
      showToast('加载文件…', 'info');
      const res = await fetch('/api/v1/workspace/open_file_by_path', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: filePath }),
      });
      const d = await res.json();
      if (!res.ok) throw new Error(d.error || '打开失败');
      if (d.file_id && window.WA._openParsedFile) {
        WA._openParsedFile(d);
      } else {
        showToast('文件已在工作站中加载', 'success');
      }
    } catch (e) {
      showToast(e.message, 'error');
    }
  };

  window.WA.refreshRecent = () => loadRecentFiles();

  window.WA.toggleRecentSection = () => {
    state._recentOpen = !state._recentOpen;
    const list = document.getElementById('wa-recent-list');
    const arrow = document.getElementById('wa-recent-arrow');
    if (list) list.style.display = state._recentOpen ? '' : 'none';
    if (arrow) arrow.classList.toggle('open', state._recentOpen);
  };

  // ── My Workspace: pinned files ─────────────────────────────────────────────
  const _MYWS_KEY = 'wa_my_workspace_v1';

  function _loadMyWorkspace() {
    try { return JSON.parse(localStorage.getItem(_MYWS_KEY) || '[]'); } catch(e) { return []; }
  }
  function _saveMyWorkspace(list) {
    localStorage.setItem(_MYWS_KEY, JSON.stringify(list));
  }

  function _toggleMyWorkspaceSection() {
    const open = state.sectionOpen.myworkspace !== false;
    const list = $('wa-myws-list');
    const empty = $('wa-myws-empty');
    const arrow = $('wa-myws-arrow');
    if (arrow) arrow.classList.toggle('open', open);
    if (list) list.style.display = open ? '' : 'none';
    if (empty) empty.style.display = open && !_loadMyWorkspace().length ? '' : 'none';
  }

  function _renderMyWorkspace() {
    const list = $('wa-myws-list');
    const empty = $('wa-myws-empty');
    const badge = $('wa-myws-badge');
    if (!list) return;
    const files = _loadMyWorkspace();
    if (badge) badge.textContent = files.length || '';
    const isOpen = state.sectionOpen.myworkspace !== false;
    if (!isOpen) { list.style.display = 'none'; if (empty) empty.style.display = 'none'; return; }
    if (!files.length) {
      list.innerHTML = '';
      list.style.display = 'none';
      if (empty) empty.style.display = '';
      return;
    }
    if (empty) empty.style.display = 'none';
    list.style.display = '';
    list.innerHTML = files.map(f => {
      const pathEsc = _escHtml(f.path);
      const nameEsc = _escHtml(f.name);
      const icon = _fileIcon(f.ext || f.name.split('.').pop() || '');
      const active = state.activeTabPath === f.path ? ' active' : '';
      return `<div class="wa-myws-item${active}" data-path="${pathEsc}" title="${pathEsc}"
        onclick="WA.openBrowserFile('${f.path.replace(/\\/g,'\\\\').replace(/'/g,"\\'")}', true)"
        draggable="true">
        ${icon}<span class="wa-file-label">${nameEsc}</span>
        <button class="wa-myws-remove" onclick="event.stopPropagation();WA.removeFromMyWorkspace('${f.path.replace(/\\/g,'\\\\').replace(/'/g,"\\'")}')" title="从工作区移除">×</button>
      </div>`;
    }).join('');
    // Add dragstart for files in My Workspace
    list.querySelectorAll('.wa-myws-item[draggable]').forEach(el => {
      el.addEventListener('dragstart', (e) => {
        const p = el.dataset.path;
        e.dataTransfer.effectAllowed = 'copyMove';
        e.dataTransfer.setData('application/wa-file-path', p);
        e.dataTransfer.setData('text/plain', p);
        el.classList.add('dragging');
        document.body.classList.add('wa-file-dragging');
      });
      el.addEventListener('dragend', () => {
        el.classList.remove('dragging');
        document.body.classList.remove('wa-file-dragging');
      });
    });
  }

  window.WA.addToMyWorkspace = (path) => {
    if (!path) {
      // No path provided — use current file
      path = state.activeTabPath || (state.wsSourcePath);
    }
    if (!path) { showToast('请先打开一个文件', 'info'); return; }
    const name = path.split(/[\\/]/).pop() || path;
    const ext = name.includes('.') ? name.split('.').pop().toLowerCase() : '';
    const files = _loadMyWorkspace();
    if (files.some(f => f.path === path)) { showToast(`"${name}" 已在工作区中`, 'info'); return; }
    files.push({ path, name, ext, addedAt: Date.now() });
    _saveMyWorkspace(files);
    _renderMyWorkspace();
    showToast(`"${name}" 已加入工作区`, 'success');
  };

  window.WA.removeFromMyWorkspace = (path) => {
    const files = _loadMyWorkspace().filter(f => f.path !== path);
    _saveMyWorkspace(files);
    _renderMyWorkspace();
  };

  // ── Temp Workspace: session-only in-memory file list ─────────────────────
  // Files are NOT persisted to localStorage; they live only in state._tempWorkspace
  // and cleared when Koto closes.
  state._tempWorkspace = [];  // [{path, name, ext, addedAt}]

  function _toggleTempWorkspaceSection() {
    const open = state.sectionOpen.tmpworkspace !== false;
    const list = $('wa-tmpws-list');
    const empty = $('wa-tmpws-empty');
    const arrow = $('wa-tmpws-arrow');
    if (arrow) arrow.classList.toggle('open', open);
    if (list) list.style.display = open ? '' : 'none';
    if (empty) empty.style.display = open && !state._tempWorkspace.length ? '' : 'none';
  }

  function _renderTempWorkspace() {
    const list = $('wa-tmpws-list');
    const empty = $('wa-tmpws-empty');
    const badge = $('wa-tmpws-badge');
    if (!list) return;
    const files = state._tempWorkspace;
    if (badge) badge.textContent = files.length || '';
    const isOpen = state.sectionOpen.tmpworkspace !== false;
    if (!isOpen) { list.style.display = 'none'; if (empty) empty.style.display = 'none'; return; }
    if (!files.length) {
      list.innerHTML = '';
      list.style.display = 'none';
      if (empty) empty.style.display = '';
      return;
    }
    if (empty) empty.style.display = 'none';
    list.style.display = '';
    list.innerHTML = files.map(f => {
      const pathEsc = _escHtml(f.path);
      const nameEsc = _escHtml(f.name);
      const icon = _fileIcon(f.ext || f.name.split('.').pop() || '');
      const active = state.activeTabPath === f.path ? ' active' : '';
      const pathJs = f.path.replace(/\\/g,'\\\\').replace(/'/g,"\\'");
      return `<div class="wa-myws-item${active}" data-path="${pathEsc}" title="${pathEsc}"
        onclick="WA.openBrowserFile('${pathJs}', true)"
        draggable="true">
        ${icon}<span class="wa-file-label">${nameEsc}</span>
        <button class="wa-myws-remove" onclick="event.stopPropagation();WA.removeFromTempWorkspace('${pathJs}')" title="从临时工作区移除">×</button>
      </div>`;
    }).join('');
    list.querySelectorAll('.wa-myws-item[draggable]').forEach(el => {
      el.addEventListener('dragstart', (e) => {
        const p = el.dataset.path;
        e.dataTransfer.effectAllowed = 'copyMove';
        e.dataTransfer.setData('application/wa-file-path', p);
        e.dataTransfer.setData('text/plain', p);
        el.classList.add('dragging');
        document.body.classList.add('wa-file-dragging');
      });
      el.addEventListener('dragend', () => {
        el.classList.remove('dragging');
        document.body.classList.remove('wa-file-dragging');
      });
    });
  }

  window.WA.addToTempWorkspace = (path) => {
    if (!path) {
      path = state.activeTabPath || state.wsSourcePath;
    }
    if (!path) { showToast('请先打开一个文件', 'info'); return; }
    const name = path.split(/[\\/]/).pop() || path;
    const ext = name.includes('.') ? name.split('.').pop().toLowerCase() : '';
    if (state._tempWorkspace.some(f => f.path === path)) {
      showToast(`"${name}" 已在临时工作区中`, 'info');
      return;
    }
    state._tempWorkspace.push({ path, name, ext, addedAt: Date.now() });
    _renderTempWorkspace();
    // Open the file in a tab so it's loaded into memory
    WA.openBrowserFile(path, true);
    showToast(`"${name}" 已加入临时工作区`, 'success');
  };

  window.WA.removeFromTempWorkspace = (path) => {
    state._tempWorkspace = state._tempWorkspace.filter(f => f.path !== path);
    _renderTempWorkspace();
  };

  window.WA.clearTempWorkspace = () => {
    if (!state._tempWorkspace.length) return;
    if (!confirm('确认清空临时工作区？已打开的标签页不受影响。')) return;
    state._tempWorkspace = [];
    _renderTempWorkspace();
    showToast('临时工作区已清空', 'info');
  };

  // ── AI multi-file context ─────────────────────────────────────────────────
  state._aiFileContext = [];  // [{path, name, content}]
  state._aiTargetFileIdx = -1; // index into _aiFileContext designated as write-back target (-1 = none)

  function _renderAIFileChips() {
    const wrap = $('wa-ai-file-chips');
    const list = $('wa-ai-file-chip-list');
    const hint = $('wa-ai-attached-hint');
    const hintLabel = $('wa-ai-attached-label');
    if (!wrap || !list) return;
    const n = state._aiFileContext.length;
    const tIdx = state._aiTargetFileIdx;
    const targetFile = (tIdx >= 0 && tIdx < n) ? state._aiFileContext[tIdx] : null;

    if (!n) {
      wrap.style.display = 'none';
      if (hint) hint.style.display = 'none';
      // Clear AI-queued markers on file tree items
      document.querySelectorAll('.wa-file-item.ai-queued').forEach(el => el.classList.remove('ai-queued'));
      _restoreDefaultQuickActions();
      // Hide multi-doc extras
      const ssr = $('wa-source-search-row'); if (ssr) ssr.style.display = 'none';
      const mda = $('wa-multidoc-actions');  if (mda) mda.style.display = 'none';
      // Restore file context indicator now that no docs are attached
      _updateSubjectBar(state.fileName, state.fileType);
      return;
    }

    // Dynamic header
    const headerEl = wrap.querySelector('.wa-ai-file-chips-header');
    if (headerEl) {
      const targetHint = targetFile ? `<span class="wa-target-hint"> · 目标: ${_escHtml(targetFile.name)}</span>` : '';
      headerEl.innerHTML =
        `<div class="wa-multidoc-title">` +
        `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>` +
        `<span>分析文档</span><span class="wa-multi-doc-badge">${n}</span>${targetHint}</div>` +
        `<button onclick="WA.clearAIFileContext()" title="清除全部附加文件">全部移除</button>`;
    }

    wrap.style.display = '';
    list.innerHTML = state._aiFileContext.map((f, i) => {
      const isTarget = (i === tIdx);
      const isLoading = !!f.loading;
      const icon = _fileIcon(f.name.split('.').pop() || '');
      const chars = (f.content || '').length;
      const sizeLabel = isLoading ? '读取中…' : (chars < 1000 ? chars + ' 字' : (chars / 1000).toFixed(1) + 'k字');
      const pinTitle = isTarget ? '取消目标文件' : '设为修改目标文件';
      return `<div class="wa-ctx-file-row${isTarget ? ' ai-target' : ''}${isLoading ? ' loading' : ''}" title="${_escHtml(f.path)}">` +
        `<span class="ctx-row-icon">${icon}</span>` +
        `<span class="ctx-row-name">${_escHtml(f.name)}</span>` +
        `<span class="ctx-row-size">${sizeLabel}</span>` +
        (isLoading ? '' : `<button class="ctx-row-pin${isTarget ? ' active' : ''}" onclick="WA.setAITargetFile(${i})" title="${pinTitle}">📌</button>`) +
        (isLoading ? '' : `<span class="ctx-row-remove" onclick="WA.removeAIFileContext(${i})" title="移除">×</span>`) +
        `</div>`;
    }).join('');

    // Input-area hint bar (Multi-line unified design)
    if (hint && hintLabel) {
      let fileListHtml = state._aiFileContext.map(f => {
        if (!f) return '';
        return `<div style="margin-bottom:2px; opacity:0.85; display:-webkit-box; -webkit-line-clamp:1; -webkit-box-orient:vertical; overflow:hidden;">📄 ${_escHtml(f.name || '未知文件')}</div>`;
      }).join('');
      if (targetFile && targetFile.name) {
        hintLabel.innerHTML = `<div style="font-weight:600;margin-bottom:4px;color:var(--text);font-size:11px;">分析并修改：</div>${fileListHtml}`;
      } else {
        hintLabel.innerHTML = `<div style="font-weight:600;margin-bottom:4px;color:var(--text);font-size:11px;">当前分析：</div>${fileListHtml}`;
      }
      hint.style.display = 'flex';
      // Update context indicator to show file count (don't hide it)
      const _ctxInd = $('wa-context-indicator');
      const _ctxLbl = $('wa-ctx-label');
      if (_ctxInd && _ctxLbl) {
        _ctxLbl.innerHTML = `已附加 <b style="color:var(--text);font-weight:600">${n} 份文件</b>`;
        _ctxInd.style.display = 'flex';
      }
    }

    // Update quick-action bar for multi-doc mode
    if (n >= 2) {
      _renderMultiDocQuickActions(n, targetFile);
    } else {
      _restoreDefaultQuickActions();
    }

    // Show source search + multi-doc action buttons whenever files are attached
    const ssr = $('wa-source-search-row'); if (ssr) ssr.style.display = '';
    const mda = $('wa-multidoc-actions');  if (mda) mda.style.display = 'flex';

    // Mark queued files in the browser file tree
    document.querySelectorAll('.wa-file-item.ai-queued').forEach(el => el.classList.remove('ai-queued'));
    state._aiFileContext.forEach(f => {
      const el = document.querySelector(`.wa-file-item[data-path="${CSS.escape(f.path)}"]`);
      if (el) el.classList.add('ai-queued');
    });
  }

  // Replace quick-actions bar with multi-doc oriented buttons
  function _renderMultiDocQuickActions(n, targetFile) {
    const bar = $('wa-quick-actions');
    if (!bar) return;
    const tName = targetFile ? targetFile.name : null;
    const btns = [
      { label: '📊 对比差异', prompt: `请对比这${n}份文件的主要内容差异，列出相同点和不同点` },
      { label: '🔍 查找引用', prompt: `请分析这${n}份文件之间是否存在引用或描述关系，列出具体对应内容` },
      {
        label: tName ? `✏️ 同步到 ${tName}` : '✏️ 同步内容',
        prompt: tName
          ? `请分析参考文件中有哪些内容需要同步更新到目标文件"${tName}"中，给出具体的逐条修改建议`
          : `请分析这${n}份文件中有哪些内容需要互相同步更新，给出具体修改建议`
      },
      { label: '📋 综合摘要', prompt: `请综合这${n}份文件的核心内容，生成一份结构化摘要` },
    ];
    bar.innerHTML = btns.map(b =>
      `<button class="wa-quick-btn multi-doc" data-prompt="${_escHtml(b.prompt)}">${b.label}</button>`
    ).join('');
    bar.querySelectorAll('.wa-quick-btn.multi-doc').forEach(btn => {
      btn.addEventListener('click', () => WA.quickAction(btn.dataset.prompt));
    });
  }

  // Restore the default single-doc quick-action buttons
  function _restoreDefaultQuickActions() {
    const bar = $('wa-quick-actions');
    if (!bar || !bar.querySelector('.wa-quick-btn.multi-doc')) return; // nothing to restore
    bar.innerHTML =
      `<button class="wa-quick-btn" onclick="WA.quickAction('请帮我润色当前内容')">润色</button>` +
      `<button class="wa-quick-btn" onclick="WA.quickAction('请帮我总结文档要点')">总结</button>` +
      `<button class="wa-quick-btn" onclick="WA.quickAction('请检查语法和错别字')">检查</button>` +
      `<button class="wa-quick-btn" onclick="WA.quickAction('请翻译选中内容为英文')">翻译</button>` +
      `<button class="wa-quick-btn chart-btn" onclick="WA.sendQuickAction('可视化')" title="将选中数据用 Python 可视化为图表">可视化</button>`;
  }

  window.WA.removeAIFileContext = (idx) => {
    state._aiFileContext.splice(idx, 1);
    // Adjust target index after removal
    if (state._aiTargetFileIdx === idx) state._aiTargetFileIdx = -1;
    else if (state._aiTargetFileIdx > idx) state._aiTargetFileIdx--;
    _renderAIFileChips();
  };

  window.WA.clearAIFileContext = () => {
    state._aiFileContext = [];
    state._aiTargetFileIdx = -1;
    _renderAIFileChips();
  };

  // Set or toggle the write-back target file
  window.WA.setAITargetFile = (idx) => {
    state._aiTargetFileIdx = (state._aiTargetFileIdx === idx) ? -1 : idx;
    _renderAIFileChips();
    const f = state._aiTargetFileIdx >= 0 ? state._aiFileContext[state._aiTargetFileIdx] : null;
    if (f) showToast(`"${f.name}" 已设为修改目标文件`, 'success');
    else showToast('已取消目标文件设置', 'info');
  };

  async function _addFileToAIContext(absPath) {
    const name = absPath.split(/[\\/]/).pop() || absPath;
    // Don't add duplicates
    if (state._aiFileContext.some(f => f.path === absPath)) {
      showToast(`"${name}" 已在分析列表中`, 'info');
      return;
    }
    // Push a loading placeholder immediately so the user sees the file row at once
    state._aiFileContext.push({ path: absPath, name, content: null, loading: true });
    _renderAIFileChips();
    try {
      // Download the raw file bytes, then parse via the upload endpoint
      const rawRes = await fetch('/api/v1/workspace/serve_abs?path=' + encodeURIComponent(absPath));
      if (!rawRes.ok) throw new Error(`HTTP ${rawRes.status}`);
      const blob = await rawRes.blob();
      const formData = new FormData();
      formData.append('file', blob, name);
      const parseRes = await fetch('/api/v1/workspace/open_file', { method: 'POST', body: formData });
      if (!parseRes.ok) throw new Error(`Parse HTTP ${parseRes.status}`);
      const data = await parseRes.json();
      // Extract text content from the parsed data
      let content = '';
      if (typeof data.data === 'string') {
        content = data.data;
      } else if (data.data && data.data.html) {
        const tmp = document.createElement('div');
        tmp.innerHTML = data.data.html;
        content = tmp.textContent || tmp.innerText || '';
      } else if (data.data && typeof data.data === 'object') {
        content = JSON.stringify(data.data).substring(0, 8000);
      }
      const MAX_FILE_CONTEXT = 6000;
      if (content.length > MAX_FILE_CONTEXT) {
        content = content.substring(0, MAX_FILE_CONTEXT) + '\n…[内容过长已截断]';
      }
      // Replace the loading placeholder with real content
      const placeholder = state._aiFileContext.find(f => f.path === absPath);
      if (placeholder) { placeholder.content = content; delete placeholder.loading; }
      _renderAIFileChips();
      showToast(`"${name}" 已添加到 AI 分析`, 'success');
    } catch (e) {
      // Remove placeholder on failure
      state._aiFileContext = state._aiFileContext.filter(f => f.path !== absPath);
      _renderAIFileChips();
      showToast(`无法读取 "${name}": ${e.message}`, 'error');
    }
  }

  window.WA.cycleSortOrder = () => {
    const order = ['name', 'date', 'type'];
    const idx = order.indexOf(state.sortBy);
    state.sortBy = order[(idx + 1) % order.length];
    localStorage.setItem('wa_sort_by', state.sortBy);
    _renderWorkspaceTree();
  };

  // ── Browser sort ──────────────────────────────────────────────────────────
  window.WA.cycleBrowserSort = () => {
    const order = ['name', 'date', 'type'];
    const labels = { name: '名称', date: '日期', type: '类型' };
    const idx = order.indexOf(state._browserSort);
    state._browserSort = order[(idx + 1) % order.length];
    localStorage.setItem('wa_browser_sort', state._browserSort);
    const btn = $('wa-browser-sort-btn');
    if (btn) btn.textContent = '\u21d5 ' + labels[state._browserSort];
    for (const p in state._browserCache) {
      if (Array.isArray(state._browserCache[p]))
        state._browserCache[p] = _applyBrowserSort(state._browserCache[p]);
    }
    _renderBrowserTree();
  };

  function _applyBrowserSort(entries) {
    if (!entries || !Array.isArray(entries)) return entries;
    const isF = e => e.type === 'folder' || e.type === 'drive' || e.type === 'quick';
    const folders = entries.filter(isF);
    const files   = entries.filter(e => !isF(e));
    const sortKey = state._browserSort || 'name';
    const cmp = (a, b) => {
      if (sortKey === 'date') return (b.mtime || 0) - (a.mtime || 0);
      if (sortKey === 'type') {
        const ec = (a.ext || '').localeCompare(b.ext || '');
        if (ec !== 0) return ec;
      }
      return a.name.localeCompare(b.name, 'zh');
    };
    return [...folders.sort((a,b)=>a.name.localeCompare(b.name,'zh')), ...files.sort(cmp)];
  }

  // ── Helper: extension support + size formatting ───────────────────────────
  function _isSupportedExt(ext) {
    const s = new Set(['docx','doc','xlsx','xls','pptx','ppt','pdf','txt','md','markdown']);
    return s.has((ext || '').toLowerCase().replace(/^\./, ''));
  }

  function _formatSize(bytes) {
    if (!bytes || bytes < 0) return '';
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / 1048576).toFixed(1) + ' MB';
  }

  // ── System-wide file search (via /api/files/search) ───────────────────────
  async function _doSearch() {
    state._searchActive = true;
    const q = state.searchQuery;
    const cat = state._searchFilter !== 'all' ? state._searchFilter : '';
    const list = $('wa-files-list');
    if (!list) return;
    list.innerHTML = '<div class="wa-loading-row" style="padding:12px 8px;display:flex;align-items:center;gap:8px">' +
      '<span class="wa-spinner"></span>搜索中…</div>';
    try {
      const params = new URLSearchParams({ limit: '60' });
      if (q) params.set('q', q);
      if (cat) params.set('category', cat);
      const res = await fetch('/api/files/search?' + params);
      if (!res.ok) throw new Error('HTTP ' + res.status);
      const d = await res.json();
      _renderSearchResults(d.results || [], q);
    } catch (e) {
      if (list) list.innerHTML = `<div class="wa-empty-row" style="padding:12px 8px">搜索失败: ${_escHtml(e.message)}</div>`;
    }
  }

  function _renderSearchResults(results, query) {
    const list = $('wa-files-list');
    if (!list) return;
    const header = '<div class="wa-search-header">' +
      `<span>找到 ${results.length} 个文件${query ? ' &middot; "' + _escHtml(query) + '"' : ''}</span>` +
      '<button onclick="WA.clearSearch()">&#8592; 返回浏览</button>' +
      '</div>';
    if (!results.length) {
      list.innerHTML = header + '<div style="padding:20px 12px;text-align:center;color:var(--text-muted);font-size:12px">' +
        '未找到匹配的文件<br><span style="font-size:11px;margin-top:4px;display:block">尝试其他关键词或调整类型过滤</span></div>';
      return;
    }
    const rows = results.map(f => {
      const name = f.name || (f.path || '').split(/[\\/]/).pop();
      const ext  = (name.includes('.') ? name.split('.').pop() : '').toLowerCase();
      const path = f.path || '';
      const dir  = path.replace(/[\\/][^\\/]+$/, '');
      const cat  = f.category || '';
      const size = f.size_bytes ? _formatSize(f.size_bytes) : '';
      const supported = _isSupportedExt(ext);
      const unsupported = supported ? '' : ' wa-unsupported';
      const checkHtml = state.selectMode
        ? '<input type="checkbox" class="wa-file-check" onclick="event.stopPropagation();WA._toggleBrowserCheck(this)">'
        : '';
      return `<div class="wa-file-item file${unsupported}" style="padding-left:8px"` +
        ` data-path="${_escHtml(path)}" data-supported="${supported}"` +
        ` onclick="WA.openBrowserFile(this.dataset.path,this.dataset.supported!=='false')"` +
        ` oncontextmenu="event.preventDefault();event.stopPropagation();WA._showBrowserCtx(event,this)"` +
        ` title="${_escHtml(path)}">` +
        `${checkHtml}${_fileIcon(ext, cat)}` +
        `<span class="wa-file-label">${_escHtml(name)}</span>` +
        `<span class="wa-search-dir" title="${_escHtml(dir)}">${_escHtml(dir)}</span>` +
        `${size ? `<span class="wa-recent-date">${size}</span>` : ''}` +
        `<div class="wa-file-actions"><button onclick="event.stopPropagation();WA._showBrowserCtx(event,this.closest('.wa-file-item'))" title="更多">${_MORE_BTN_SVG}</button></div>` +
        '</div>';
    });
    list.innerHTML = header + rows.join('');
  }

  // ══════════════════════════════════════════════════════════════════════════
  // ── Full Local-Filesystem Browser (VS Code Explorer style) ───────────────
  // ══════════════════════════════════════════════════════════════════════════

  /**
   * Initial load: fetch drives + quick-access, auto-expand workspace folder.
   * Replaces the old single-workspace tree on init.
   */
  async function loadFileBrowser() {
    const list = $('wa-files-list');
    if (list) list.innerHTML = '<div class="wa-loading-row">正在读取文件系统…</div>';
    try {
      // 1. Workspace metadata (for section label + recent-file path comparison)
      const wsMeta = await fetch('/api/v1/workspace/current_dir')
        .then(r => r.ok ? r.json() : null).catch(() => null);
      if (wsMeta) {
        state._workspaceName = wsMeta.name || 'workspace';
        state._workspacePath = wsMeta.path || '';
        _renderWorkspaceRoot();
      }
      // 2. Roots (drives + quick access)
      const res = await fetch('/api/v1/workspace/browse_local');
      if (!res.ok) throw new Error('HTTP ' + res.status);
      const data = await res.json();
      state._browserRoots = data;
      // 3. Auto-expand the Koto workspace folder
      const wsEntry = (data.quick_access || []).find(q => q.name === 'Koto 工作区');
      if (wsEntry && !state._browserExpanded.has(wsEntry.path)) {
        state._browserExpanded.add(wsEntry.path);
        state._browserCache[wsEntry.path] = 'loading';
      }
      _renderBrowserTree();
      // 4. Load workspace children
      if (wsEntry && state._browserCache[wsEntry.path] === 'loading') {
        const cr = await fetch('/api/v1/workspace/browse_local?path=' + encodeURIComponent(wsEntry.path));
        const cd = await cr.json();
        state._browserCache[wsEntry.path] = cd.entries || [];
        _renderBrowserTree();
      }
    } catch (e) {
      const l = $('wa-files-list');
      if (l) l.innerHTML = `<div class="wa-empty-row">加载失败: ${e.message}</div>`;
    }
  }

  /**
   * Soft-refresh: preserve expanded state but re-fetch all open folder contents.
   * Called after file create/delete/rename operations.
   */
  async function _softRefreshBrowser() {
    const expanded = Array.from(state._browserExpanded);
    for (const p of expanded) state._browserCache[p] = 'loading';
    _renderBrowserTree();
    await Promise.all(expanded.map(async absPath => {
      try {
        const r = await fetch('/api/v1/workspace/browse_local?path=' + encodeURIComponent(absPath));
        state._browserCache[absPath] = r.ok ? (await r.json()).entries || [] : [];
      } catch (_) { state._browserCache[absPath] = []; }
    }));
    _renderBrowserTree();
  }

  /** Render the full browser tree into #wa-files-list. */
  function _renderBrowserTree() {
    const list = $('wa-files-list');
    if (!list) return;
    if (!state._browserRoots) {
      list.innerHTML = '<div class="wa-loading-row">正在读取文件系统…</div>';
      return;
    }
    const r = state._browserRoots;
    const rows = [];
    if (r.quick_access?.length) {
      rows.push(`<div class="wa-browser-group-label">快速访问</div>`);
      r.quick_access.forEach(qa => _renderBrowserEntry(qa, 0, rows));
    }
    if (r.drives?.length) {
      rows.push(`<div class="wa-browser-group-label">此电脑</div>`);
      r.drives.forEach(d => _renderBrowserEntry(d, 0, rows));
    }
    const _savedScroll = list.scrollTop;
    list.innerHTML = rows.join('');
    list.scrollTop = _savedScroll;
    // Restore active file highlight
    if (state.activeTabPath) {
      const el = list.querySelector(`[data-path="${CSS.escape(state.activeTabPath)}"]`);
      if (el) el.classList.add('active');
    }
  }

  /** Recursively render one tree entry (folder or file) into the rows array. */
  const _MORE_BTN_SVG = `<svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor"><circle cx="8" cy="2.5" r="1.5"/><circle cx="8" cy="8" r="1.5"/><circle cx="8" cy="13.5" r="1.5"/></svg>`;

  function _renderBrowserEntry(entry, depth, rows) {
    const pad = depth * 16 + 8;
    const absPath = entry.path;
    const isFolder = entry.type === 'folder' || entry.type === 'drive' || entry.type === 'quick';

    if (isFolder) {
      const isExpanded = state._browserExpanded.has(absPath);
      const folderSvg = isExpanded ? _FOLDER_OPEN_SVG : _FOLDER_SVG;
      rows.push(
        `<div class="wa-file-item folder" style="padding-left:${pad}px" ` +
        `data-path="${_escHtml(absPath)}" ` +
        `onclick="WA.toggleBrowserFolder(this.dataset.path)" ` +
        `oncontextmenu="event.preventDefault();event.stopPropagation();WA._showBrowserCtx(event,this)">` +
        `<span class="wa-folder-arrow${isExpanded ? ' open' : ''}">›</span>` +
        `<span class="wa-file-icon">${folderSvg}</span>` +
        `<span class="wa-file-label">${_escHtml(entry.name)}</span>` +
        `<div class="wa-file-actions"><button onclick="event.stopPropagation();WA._showBrowserCtx(event,this.closest('.wa-file-item'))" title="更多操作">${_MORE_BTN_SVG}</button></div>` +
        `</div>`
      );
      if (isExpanded) {
        const ch = state._browserCache[absPath];
        if (ch === 'loading') {
          rows.push(`<div class="wa-loading-row" style="padding-left:${pad + 24}px">加载中…</div>`);
        } else if (!ch || ch.length === 0) {
          rows.push(`<div class="wa-empty-row" style="padding-left:${pad + 24}px">（空文件夹）</div>`);
        } else {
          ch.forEach(c => _renderBrowserEntry(c, depth + 1, rows));
        }
      }
    } else {
      const ext = entry.ext || '';
      const supported = entry.supported !== false;
      const unsupported = !supported ? ' wa-unsupported' : '';
      const isActive = state.activeTabPath === absPath ? ' active' : '';
      const checkHtml = state.selectMode
        ? '<input type="checkbox" class="wa-file-check" onclick="event.stopPropagation();WA._toggleBrowserCheck(this)">'
        : '';
      rows.push(
        `<div class="wa-file-item file${isActive}${unsupported}" style="padding-left:${pad}px" ` +
        `data-path="${_escHtml(absPath)}" data-supported="${supported}" ` +
        `draggable="true" ` +
        `onclick="WA.openBrowserFile(this.dataset.path, this.dataset.supported !== 'false')" ` +
        `oncontextmenu="event.preventDefault();event.stopPropagation();WA._showBrowserCtx(event,this)" ` +
        `ondragstart="event.dataTransfer.effectAllowed='copyMove';event.dataTransfer.setData('application/wa-file-path',this.dataset.path);event.dataTransfer.setData('text/plain',this.dataset.path);this.classList.add('dragging');document.body.classList.add('wa-file-dragging')" ` +
        `ondragend="this.classList.remove('dragging');document.body.classList.remove('wa-file-dragging')" ` +
        `title="${_escHtml(entry.name)}">` +
        `${checkHtml}${_fileIcon(ext, entry.category)}` +
        `<span class="wa-file-label">${_escHtml(entry.name)}</span>` +
        `<div class="wa-file-actions"><button onclick="event.stopPropagation();WA._showBrowserCtx(event,this.closest('.wa-file-item'))" title="更多操作">${_MORE_BTN_SVG}</button></div>` +
        `</div>`
      );
    }
  }

  /** Toggle expand/collapse of a folder in the browser. Lazy-loads on first expand. */
  window.WA.toggleBrowserFolder = async (absPath) => {
    if (state._browserExpanded.has(absPath)) {
      state._browserExpanded.delete(absPath);
      _renderBrowserTree();
      return;
    }
    state._browserExpanded.add(absPath);
    if (!state._browserCache[absPath] || state._browserCache[absPath] === 'loading') {
      state._browserCache[absPath] = 'loading';
      _renderBrowserTree();
      try {
        const res = await fetch('/api/v1/workspace/browse_local?path=' + encodeURIComponent(absPath));
        const data = await res.json();
        if (!res.ok) { showToast(data.error || '无法读取文件夹', 'error'); state._browserCache[absPath] = []; }
        else state._browserCache[absPath] = data.entries || [];
      } catch (e) { state._browserCache[absPath] = []; showToast(e.message, 'error'); }
    }
    _renderBrowserTree();
  };

  /** Open a file from the browser by absolute path. */
  window.WA.openBrowserFile = async (absPath, supported = true) => {
    if (!supported) {
      showToast('此格式暂不支持在线编辑，已触发本地打开', 'info');
      fetch('/api/v1/workspace/open-native', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: absPath }),
      }).catch(() => {});
      return;
    }
    // If an existing tab for this path has user-generated edits (cache !== null),
    // or is already the active tab, just switch to it without re-reading from disk.
    // Otherwise (no edits / stale serverData), discard the stale tab entry and
    // re-load fresh from disk — this fixes the case where the workspace file was
    // updated externally or a previous parse produced corrupt/empty data.
    const _existingTab = state.openTabs.find(t => t.path === absPath);
    if (_existingTab) {
      if (_existingTab.cache !== null || state.activeTabPath === absPath) {
        await _switchToTab(absPath);
        return;
      }
      // Stale tab with no user edits — drop it and re-load below
      const _staleIdx = state.openTabs.findIndex(t => t.path === absPath);
      if (_staleIdx >= 0) state.openTabs.splice(_staleIdx, 1);
    }
    const baseName = absPath.replace(/\\/g, '/').split('/').pop() || absPath;
    _trackUserOpen(absPath);
    showToast('正在加载 ' + baseName, 'info');
    try {
      const res = await fetch('/api/v1/workspace/serve_abs?path=' + encodeURIComponent(absPath));
      if (!res.ok) throw new Error('HTTP ' + res.status);
      const blob = await res.blob();
      const file = new File([blob], baseName);
      file._wsPath = absPath;   // use abs path so tabs track by abs path
      file._absPath = absPath;  // flag: opened from browser (not workspace-relative)
      await Router.load(file);
      loadRecentFiles();
      _renderBrowserTree();     // refresh active highlight
    } catch (e) { showToast('无法打开文件: ' + e.message, 'error'); }
  };

  // ── File-browser context menu ─────────────────────────────────────────────
  let _fsBrowserCtxTarget = { path: null, name: null, isFolder: false, supported: true };

  window.WA._showBrowserCtx = (event, el) => {
    if (!el) return;
    event.preventDefault();
    event.stopPropagation();
    const absPath = el.dataset.path;
    if (!absPath) return;
    const name = el.querySelector('.wa-file-label')?.textContent || absPath.split(/[\\/]/).pop();
    const isFolder = el.classList.contains('folder');
    const supported = el.dataset.supported !== 'false';
    _fsBrowserCtxTarget = { path: absPath, name, isFolder, supported };

    const menu = document.getElementById('wa-ctx-menu');
    if (!menu) return;

    const clip = state._fsClipboard;
    const SVG = {
      open:   `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>`,
      copy:   `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>`,
      cut:    `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="6" cy="20" r="3"/><circle cx="6" cy="4" r="3"/><line x1="20" y1="4" x2="8.12" y2="15.88"/><line x1="14.47" y1="14.48" x2="20" y2="20"/><line x1="8.12" y1="8.12" x2="12" y2="12"/></svg>`,
      paste:  `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><rect x="8" y="2" width="8" height="4" rx="1"/></svg>`,
      rename: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>`,
      newf:   `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="12" y1="18" x2="12" y2="12"/><line x1="9" y1="15" x2="15" y2="15"/></svg>`,
      newdir: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/><line x1="12" y1="11" x2="12" y2="17"/><line x1="9" y1="14" x2="15" y2="14"/></svg>`,
      ai:     `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>`,
      del:    `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4h6v2"/></svg>`,
    };

    let html = '';
    if (isFolder) {
      html += `<div class="wa-ctx-item" onclick="WA._fsBrowserNewFile();_closeCtxMenu()">${SVG.newf} 新建文件</div>`;
      html += `<div class="wa-ctx-item" onclick="WA._fsBrowserNewFolder();_closeCtxMenu()">${SVG.newdir} 新建子文件夹</div>`;
      html += `<div class="wa-ctx-separator"></div>`;
      if (clip) {
        html += `<div class="wa-ctx-item" onclick="WA._fsBrowserPaste();_closeCtxMenu()">${SVG.paste} 粘贴 <span style="font-size:11px;color:var(--text-muted);margin-left:4px">${_escHtml(clip.name)}</span></div>`;
        html += `<div class="wa-ctx-separator"></div>`;
      }
      html += `<div class="wa-ctx-item" onclick="WA._fsBrowserRename();_closeCtxMenu()">${SVG.rename} 重命名</div>`;
      html += `<div class="wa-ctx-separator"></div>`;
      html += `<div class="wa-ctx-item danger" onclick="WA._fsBrowserDelete();_closeCtxMenu()">${SVG.del} 删除文件夹</div>`;
    } else {
      html += `<div class="wa-ctx-item" onclick="WA._fsBrowserOpen();_closeCtxMenu()">${SVG.open} ${supported ? '打开' : '本地打开'}</div>`;
      html += `<div class="wa-ctx-separator"></div>`;
      html += `<div class="wa-ctx-item" onclick="WA._fsBrowserAddToTempWorkspace();_closeCtxMenu()">${SVG.newf} 加入临时工作区</div>`;
      html += `<div class="wa-ctx-item" onclick="WA._fsBrowserAddToWorkspace();_closeCtxMenu()">${SVG.newf} 加入我的工作区</div>`;
      html += `<div class="wa-ctx-item" onclick="WA._fsBrowserSendToAI();_closeCtxMenu()">${SVG.ai} 发送给AI分析</div>`;
      html += `<div class="wa-ctx-separator"></div>`;
      html += `<div class="wa-ctx-item" onclick="WA._fsBrowserCopy();_closeCtxMenu()">${SVG.copy} 复制</div>`;
      html += `<div class="wa-ctx-item" onclick="WA._fsBrowserCut();_closeCtxMenu()">${SVG.cut} 剪切</div>`;
      if (clip && !isFolder) {
        // paste next to file = paste into same dir
        html += `<div class="wa-ctx-item" onclick="WA._fsBrowserPaste();_closeCtxMenu()">${SVG.paste} 粘贴到此处</div>`;
      }
      html += `<div class="wa-ctx-separator"></div>`;
      html += `<div class="wa-ctx-item" onclick="WA._fsBrowserRename();_closeCtxMenu()">${SVG.rename} 重命名</div>`;
      if (supported) {
        html += `<div class="wa-ctx-separator"></div>`;
        html += `<div class="wa-ctx-item" onclick="WA._fsBrowserAISummary();_closeCtxMenu()">${SVG.ai} AI 概括</div>`;
      }
      html += `<div class="wa-ctx-separator"></div>`;
      html += `<div class="wa-ctx-item" onclick="WA._fsBrowserCopyPath();_closeCtxMenu()">${SVG.copy} 复制路径</div>`;
      html += `<div class="wa-ctx-separator"></div>`;
      html += `<div class="wa-ctx-item danger" onclick="WA._fsBrowserDelete();_closeCtxMenu()">${SVG.del} 删除</div>`;
    }
    menu.innerHTML = html;
    // Show at (0,0) hidden — browser computes real layout; no flash because paint
    // is batched until after this synchronous handler returns.
    menu.classList.add('open');
    menu.style.visibility = 'hidden';
    menu.style.top  = '0px';
    menu.style.left = '0px';
    void menu.getBoundingClientRect(); // force synchronous reflow
    const menuH = menu.scrollHeight || menu.offsetHeight ||
      (menu.querySelectorAll('.wa-ctx-item').length * 28 +
       menu.querySelectorAll('.wa-ctx-separator').length * 7 + 8);
    const menuW = menu.offsetWidth || 180;
    menu.style.visibility = '';
    const vw = window.innerWidth, vh = window.innerHeight;
    let x, y;
    if (event.type === 'click') {
      const btn = event.target.closest('button');
      if (btn) {
        const btnRect = btn.getBoundingClientRect();
        x = btnRect.right - menuW;
        // Enough room below button? show below; otherwise flip above
        y = (btnRect.bottom + menuH + 4 <= vh)
          ? btnRect.bottom + 2
          : Math.max(4, btnRect.top - menuH - 2);
      } else {
        x = event.clientX;
        y = (event.clientY + menuH + 4 <= vh)
          ? event.clientY
          : Math.max(4, event.clientY - menuH);
      }
    } else {
      x = event.clientX;
      y = (event.clientY + menuH + 4 <= vh)
        ? event.clientY
        : Math.max(4, event.clientY - menuH);
    }
    if (x + menuW > vw) x = vw - menuW - 4;
    if (x < 4) x = 4;
    // Final safety clamp — catches edge cases where menuH was mis-measured
    if (y + menuH > vh - 2) y = Math.max(4, vh - menuH - 4);
    if (y < 4) y = 4;
    menu.style.left = x + 'px';
    menu.style.top  = y + 'px';
  };

  // ── Browser context menu actions ──────────────────────────────────────────

  window.WA._fsBrowserOpen = () => {
    const { path, supported } = _fsBrowserCtxTarget;
    if (!path) return;
    WA.openBrowserFile(path, supported);
  };

  window.WA._fsBrowserAddToWorkspace = () => {
    const { path } = _fsBrowserCtxTarget;
    if (path) WA.addToMyWorkspace(path);
  };

  window.WA._fsBrowserAddToTempWorkspace = () => {
    const { path } = _fsBrowserCtxTarget;
    if (path) WA.addToTempWorkspace(path);
  };

  window.WA._fsBrowserSendToAI = () => {
    const { path } = _fsBrowserCtxTarget;
    if (!path) return;
    _addFileToAIContext(path);
    // Expand the AI panel (same experience as dragging a file onto it)
    _expandWAPanel();
    // Focus the chat input so the user can immediately type a question
    const input = $('wa-user-input');
    if (input) setTimeout(() => input.focus(), 150);
  };

  window.WA._fsBrowserCopy = () => {
    const { path, name } = _fsBrowserCtxTarget;
    if (!path) return;
    state._fsClipboard = { path, name, mode: 'copy' };
    showToast('"' + name + '" 已复制', 'success');
  };

  window.WA._fsBrowserCut = () => {
    const { path, name } = _fsBrowserCtxTarget;
    if (!path) return;
    state._fsClipboard = { path, name, mode: 'cut' };
    // Dim the item to signal it's being moved
    const el = document.querySelector(`.wa-file-item[data-path="${CSS.escape(path)}"]`);
    if (el) el.style.opacity = '0.45';
    showToast('"' + name + '" 准备移动', 'info');
  };

  window.WA._fsBrowserPaste = async () => {
    const clip = state._fsClipboard;
    if (!clip) return;
    const { path: target, isFolder } = _fsBrowserCtxTarget;
    // dst_dir: if target is a folder, paste into it; otherwise paste into its parent
    const dstDir = isFolder ? target : target.replace(/[\\/][^\\/]+$/, '');
    try {
      const res = await fetch('/api/v1/workspace/fs_copy', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ src: clip.path, dst_dir: dstDir, move: clip.mode === 'cut' }),
      });
      const json = await res.json();
      if (!res.ok) throw new Error(json.error || '操作失败');
      if (clip.mode === 'cut') state._fsClipboard = null;
      showToast('已粘贴 "' + clip.name + '"', 'success');
      // Invalidate cache for dst folder and re-expand it
      delete state._browserCache[dstDir];
      if (state._browserExpanded.has(dstDir)) state._browserExpanded.delete(dstDir);
      state._browserExpanded.add(dstDir);
      await _softRefreshBrowser();
    } catch (e) { showToast(e.message, 'error'); }
  };

  window.WA._fsBrowserCopyPath = () => {
    const { path } = _fsBrowserCtxTarget;
    if (!path) return;
    navigator.clipboard.writeText(path)
      .then(() => showToast('路径已复制', 'success'))
      .catch(() => showToast(path, 'info'));
  };

  window.WA._fsBrowserRename = () => {
    const { path, name, isFolder } = _fsBrowserCtxTarget;
    if (!path) return;
    const item = document.querySelector(`.wa-file-item[data-path="${CSS.escape(path)}"]`);
    if (!item) return;
    const labelSpan = item.querySelector('.wa-file-label');
    if (!labelSpan) return;
    const stem = (!isFolder && name.includes('.')) ? name.slice(0, name.lastIndexOf('.')) : name;
    const input = document.createElement('input');
    input.className = 'wa-rename-input';
    input.value = stem;
    labelSpan.replaceWith(input);
    input.focus(); input.select();
    const commit = async () => {
      const newName = input.value.trim();
      if (!newName || newName === stem) { _softRefreshBrowser(); return; }
      try {
        const res = await fetch('/api/v1/workspace/fs_rename', {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path, name: newName }),
        });
        const json = await res.json();
        if (!res.ok) throw new Error(json.error || '重命名失败');
        showToast('已重命名为 ' + json.name, 'success');
      } catch (e) { showToast(e.message, 'error'); }
      // Invalidate parent folder cache
      const parent = path.replace(/[\\/][^\\/]+$/, '');
      delete state._browserCache[parent];
      await _softRefreshBrowser();
    };
    input.addEventListener('keydown', e => {
      if (e.key === 'Enter') { e.preventDefault(); commit(); }
      if (e.key === 'Escape') { _softRefreshBrowser(); }
    });
    input.addEventListener('blur', commit);
  };

  window.WA._fsBrowserDelete = async () => {
    const { path, name, isFolder } = _fsBrowserCtxTarget;
    if (!path) return;
    const msg = isFolder
      ? `确定要删除文件夹 "${name}" 及其所有内容吗？此操作不可撤销。`
      : `确定要删除 "${name}" 吗？`;
    if (!confirm(msg)) return;
    try {
      const res = await fetch('/api/v1/workspace/fs_delete?path=' + encodeURIComponent(path), { method: 'DELETE' });
      const json = await res.json();
      if (!res.ok) throw new Error(json.error || '删除失败');
      showToast('已删除 "' + name + '"', 'success');
      // Remove from open tabs if it was open
      const tabIdx = state.openTabs.findIndex(t => t.path === path);
      if (tabIdx >= 0) {
        const wasActive = state.openTabs[tabIdx].path === state.activeTabPath;
        if (wasActive && state.activeEditor) {
          try {
            state.activeEditor.destroy();
          } catch(e) {
            console.error('Editor destroy failed:', e);
            const canvas = document.getElementById('wa-canvas');
            if (canvas) canvas.innerHTML = '';
          }
          state.activeEditor = null; state.activeTabPath = null;
          state.fileId = null; state.fileType = null; state.fileName = null;
          const canvas = document.getElementById('wa-canvas');
          if (canvas) canvas.innerHTML = '';
        }
        state.openTabs.splice(tabIdx, 1);
        WA._renderTabs();
      }
      // Invalidate parent cache
      const parent = path.replace(/[\\/][^\\/]+$/, '');
      delete state._browserCache[parent];
      if (state._browserExpanded.has(path)) state._browserExpanded.delete(path);
      await _softRefreshBrowser();
    } catch (e) { showToast(e.message, 'error'); }
  };

  window.WA._fsBrowserNewFile = () => {
    const { path } = _fsBrowserCtxTarget;
    if (!path) return;
    WA.startNewFile(path);
  };

  window.WA._fsBrowserNewFolder = () => {
    const { path } = _fsBrowserCtxTarget;
    if (!path) return;
    WA.startNewFolder(path);
  };

  window.WA._fsBrowserAISummary = async () => {
    const { path, supported } = _fsBrowserCtxTarget;
    if (!path || !supported) return;
    // Open the file first, then send summary request to AI
    await WA.openBrowserFile(path, true);
    // Small delay to let the editor finish rendering
    setTimeout(() => {
      const input = document.getElementById('wa-user-input');
      if (input) {
        input.value = '请帮我概括这份文件的主要内容，列出核心要点。';
        WA.sendMessage();
      }
    }, 600);
  };

  // ──────────────────────────────────────────────────────────────────────────

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
          try {
            state.activeEditor.destroy();
          } catch(e) {
            console.error('Editor destroy failed:', e);
            const canvas = document.getElementById('wa-canvas');
            if (canvas) canvas.innerHTML = '';
          }
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
          const _saBtn2 = $('wa-saveas-btn'); if (_saBtn2) _saBtn2.disabled = true;
        }
      }
      showToast('已删除 ' + filepath.split('/').pop(), 'success');
      loadWorkspaceFiles();
    } catch (e) {
      showToast(e.message, 'error');
    }
  };

  // ── Multi-select helpers ──────────────────────────────────────────────
  window.WA._fileRowClick = (event, path, supported = true) => {
    if (state.selectMode) {
      const cb = event.currentTarget.querySelector('.wa-file-check');
      const checked = !cb.checked;
      cb.checked = checked;
      WA._toggleFileCheck(cb, path);
    } else if (supported) {
      WA.openWorkspaceFile(path);
    } else {
      // Not directly editable — offer native open
      showToast('此格式暂不支持在线编辑，已触发本地打开', 'info');
      fetch('/api/v1/workspace/open-native', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path }),
      }).catch(() => {});
    }
  };

  window.WA._toggleFileCheck = (cb, path) => {
    cb.checked ? state.selectedFiles.add(path) : state.selectedFiles.delete(path);
    cb.closest('.wa-file-item').classList.toggle('selected', cb.checked);
    WA._updateSelectBar();
  };

  // For FS browser: reads path from data-path attribute (avoids quote-escaping)
  window.WA._toggleBrowserCheck = (cb) => {
    const path = cb.closest('.wa-file-item')?.dataset.path;
    if (!path) return;
    cb.checked ? state.selectedFiles.add(path) : state.selectedFiles.delete(path);
    cb.closest('.wa-file-item').classList.toggle('selected', cb.checked);
    WA._updateSelectBar();
  };

  window.WA._updateSelectBar = () => {
    const n = state.selectedFiles.size;
    document.getElementById('wa-select-count').textContent = n + ' 已选';
    const btn = document.getElementById('wa-delete-selected');
    if (btn) { btn.disabled = n === 0; }
    const sendBtn = document.getElementById('wa-send-selected-ai');
    if (sendBtn) { sendBtn.disabled = n === 0; }
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
        // Use fs_delete for absolute paths (browser), workspace delete for relative paths
        const isAbs = /^[A-Za-z]:[/\\]|\//.test(p);
        const delUrl = isAbs
          ? '/api/v1/workspace/fs_delete?path=' + encodeURIComponent(p)
          : '/api/v1/workspace/file?path='       + encodeURIComponent(p);
        const res = await fetch(delUrl, { method: 'DELETE' });
        if (!res.ok) failed++;
      } catch { failed++; }
    }
    showToast(failed ? `已删除 ${paths.length - failed} 个，${failed} 个失败` : `已删除 ${paths.length} 个文件`, failed ? 'error' : 'success');
    WA.toggleSelectMode();
    await loadWorkspaceFiles();
  };

  // ── My Files (我的文件) — bridge to full FileHub panel ───────────────────
  window.WA.sendSelectedToAI = async () => {
    const paths = [...state.selectedFiles];
    if (!paths.length) return;
    let added = 0, skipped = 0;
    for (const p of paths) {
      // Only accept files with supported extensions
      const ext = p.split(/[\\/]/).pop().includes('.')
        ? p.split('.').pop().toLowerCase() : '';
      if (!_isSupportedExt(ext)) { skipped++; continue; }
      if (state._aiFileContext.some(f => f.path === p)) { skipped++; continue; }
      await _addFileToAIContext(p);
      added++;
    }
    if (added > 0) {
      showToast(`已将 ${added} 个文件发送给AI助手`, 'success');
      // Scroll AI panel into focus
      const aiPanel = document.getElementById('wa-ai');
      if (aiPanel) aiPanel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    } else {
      showToast(skipped ? '所选文件均已在分析列表中或格式不支持' : '没有可发送的文件', 'info');
    }
    WA.toggleSelectMode();
  };

  window.WA.openMyFiles = () => {
    // When embedded inside index.html, openFileHubModal() is a global function
    if (typeof window.openFileHubModal === 'function') {
      window.openFileHubModal();
    } else {
      // Standalone page: navigate to main app and auto-open the panel
      window.location.href = '/?my_files=1';
    }
  };

  // ── Archive / organize panel ─────────────────────────────────────────────
  let _archiveMode = 'auto';

  window.WA.showArchivePanel = () => {
    const overlay = document.getElementById('wa-archive-overlay');
    if (!overlay) return;
    const srcInput = document.getElementById('wa-archive-src');
    if (srcInput && !srcInput.value && state._workspacePath)
      srcInput.value = state._workspacePath;
    const resultEl = document.getElementById('wa-archive-result');
    if (resultEl) resultEl.innerHTML = '';
    WA._setArchiveMode(_archiveMode);
    overlay.style.display = 'flex';
  };

  window.WA.hideArchivePanel = () => {
    const el = document.getElementById('wa-archive-overlay');
    if (el) el.style.display = 'none';
  };

  window.WA._setArchiveMode = (mode) => {
    _archiveMode = mode;
    const btnAuto   = document.getElementById('wa-archive-mode-auto');
    const btnCustom = document.getElementById('wa-archive-mode-custom');
    if (btnAuto)   btnAuto.className   = mode === 'auto'   ? 'wa-btn primary' : 'wa-btn';
    if (btnCustom) btnCustom.className = mode === 'custom' ? 'wa-btn primary' : 'wa-btn';
  };

  window.WA._archivePickFolder = async (inputId) => {
    try {
      const res = await fetch('/api/files/pick-folder');
      const d = await res.json();
      if (d.path) { const el = document.getElementById(inputId); if (el) el.value = d.path; }
    } catch (_) { /* user cancelled or not available */ }
  };

  window.WA._doArchive = async () => {
    const srcEl    = document.getElementById('wa-archive-src');
    const resultEl = document.getElementById('wa-archive-result');
    const startBtn = document.getElementById('wa-archive-start-btn');
    if (!srcEl || !resultEl) return;
    const src = srcEl.value.trim();
    if (!src) { srcEl.focus(); showToast('请先填写源文件夹路径', 'error'); return; }
    if (startBtn) startBtn.disabled = true;
    resultEl.innerHTML = '<div class="wa-loading-row" style="display:flex;align-items:center;gap:8px;padding:12px">' +
      '<span class="wa-spinner"></span>归档中，请稍候…</div>';
    try {
      const res = await fetch('/api/files/archive', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source_dir: src, mode: _archiveMode, recursive: true, rules: [] }),
      });
      const d = await res.json();
      if (!res.ok || d.error) throw new Error(d.error || res.statusText);
      // Group by target folder
      const byFolder = {};
      (d.report || []).forEach(item => {
        if (!byFolder[item.folder]) byFolder[item.folder] = [];
        byFolder[item.folder].push((item.src || '').split(/[\\/]/).pop());
      });
      const cards = Object.entries(byFolder).map(([folder, files]) =>
        `<div class="wa-archive-group">` +
        `<div class="wa-archive-group-title">${_FOLDER_SVG} ${_escHtml(folder)} <span class="wa-section-badge">${files.length}</span></div>` +
        `<div class="wa-archive-group-files">${files.slice(0,6).map(f=>`<span>${_escHtml(f)}</span>`).join('')}` +
        `${files.length > 6 ? `<span style="color:var(--text-muted)">…另 ${files.length-6} 个</span>` : ''}</div>` +
        `</div>`
      ).join('');
      resultEl.innerHTML =
        `<div class="wa-archive-success">` +
        `<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">` +
        `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#34d399" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>` +
        `<strong>归档完成</strong><span style="color:var(--text-muted);font-size:12px;margin-left:4px">共 ${d.total} 个文件，成功 ${d.copied} 个</span></div>` +
        `<div style="font-size:11px;color:var(--text-muted);margin-bottom:8px">目标：${_escHtml(d.dest_dir)}</div>` +
        cards + `</div>`;
      delete state._browserCache[d.dest_dir];
      state._browserExpanded.add(d.dest_dir);
      _softRefreshBrowser();
    } catch (e) {
      resultEl.innerHTML = `<div class="wa-empty-row" style="color:var(--danger)">归档失败：${_escHtml(e.message)}</div>`;
    } finally {
      if (startBtn) startBtn.disabled = false;
    }
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
    // Show at (0,0) hidden — browser computes real layout; no flash because paint
    // is batched until after this synchronous handler returns.
    menu.classList.add('open');
    menu.style.visibility = 'hidden';
    menu.style.top  = '0px';
    menu.style.left = '0px';
    void menu.getBoundingClientRect(); // force synchronous reflow
    const menuH2 = menu.scrollHeight || menu.offsetHeight ||
      (menu.querySelectorAll('.wa-ctx-item').length * 28 +
       menu.querySelectorAll('.wa-ctx-separator').length * 7 + 8);
    const menuW2 = menu.offsetWidth || 180;
    menu.style.visibility = '';
    const vw = window.innerWidth, vh = window.innerHeight;
    let x = event.clientX;
    // Enough room below cursor? show below; otherwise flip above
    let y = (event.clientY + menuH2 + 4 <= vh)
      ? event.clientY
      : Math.max(4, event.clientY - menuH2);
    // Clamp within left panel
    const leftPanel = document.getElementById('wa-left');
    if (leftPanel) {
      const lRect = leftPanel.getBoundingClientRect();
      if (x + menuW2 > lRect.right) x = lRect.right - menuW2 - 4;
      if (x < lRect.left) x = lRect.left + 4;
    }
    if (x + menuW2 > vw) x = vw - menuW2 - 4;
    if (x < 4) x = 4;
    if (y + menuH2 > vh - 2) y = Math.max(4, vh - menuH2 - 4);
    if (y < 4) y = 4;
    menu.style.left = x + 'px';
    menu.style.top = y + 'px';
  };

  function _closeCtxMenu() {
    const menu = document.getElementById('wa-ctx-menu');
    if (menu) menu.classList.remove('open');
  }
  // Expose for inline onclick handlers in context menu items
  window._closeCtxMenu = _closeCtxMenu;

  document.addEventListener('click', (e) => {
    // Don't close when clicking on a menu item — let the item's onclick fire first
    if (!e.target.closest('#wa-ctx-menu')) _closeCtxMenu();
  }, true);
  document.addEventListener('keydown', e => { if (e.key === 'Escape') _closeCtxMenu(); });
  // Use capture:true so this fires BEFORE WangEditor can call stopPropagation().
  // Guard: only intercept Ctrl+S when the workspace panel is actually visible,
  // so this does not block Ctrl+S in the chat or other views.
  document.addEventListener('keydown', e => {
    if ((e.ctrlKey || e.metaKey) && e.key === 's') {
      const wsView = document.getElementById('workspaceView');
      if (!wsView || wsView.style.display === 'none' || wsView.classList.contains('hidden')) return;
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
    menu.innerHTML = `
      <div class="wa-ctx-item" onclick="WA.startNewFile('${path.replace(/'/g,"\\'")}');_closeCtxMenu()">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="12" y1="18" x2="12" y2="12"/><line x1="9" y1="15" x2="15" y2="15"/></svg>
        新建文件
      </div>
      <div class="wa-ctx-item" onclick="WA.startNewFolder('${path.replace(/'/g,"\\'")}');_closeCtxMenu()">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/><line x1="12" y1="11" x2="12" y2="17"/><line x1="9" y1="14" x2="15" y2="14"/></svg>
        新建子文件夹
      </div>
      <div class="wa-ctx-separator"></div>
      <div class="wa-ctx-item" onclick="WA._ctxFolderRename()">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
        重命名
      </div>
      <div class="wa-ctx-separator"></div>
      <div class="wa-ctx-item danger" onclick="WA._ctxFolderDelete()">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4h6v2"/></svg>
        删除文件夹
      </div>`;
    // Measure actual height before positioning (same pattern as _showBrowserCtx)
    menu.classList.add('open');
    menu.style.visibility = 'hidden';
    menu.style.top  = '0px';
    menu.style.left = '0px';
    void menu.getBoundingClientRect();
    const menuH3 = menu.scrollHeight || menu.offsetHeight ||
      (menu.querySelectorAll('.wa-ctx-item').length * 28 +
       menu.querySelectorAll('.wa-ctx-separator').length * 7 + 8);
    const menuW3 = menu.offsetWidth || 180;
    menu.style.visibility = '';
    const vw = window.innerWidth, vh = window.innerHeight;
    let x = event.clientX;
    // Flip above cursor if not enough room below
    let y = (event.clientY + menuH3 + 4 <= vh)
      ? event.clientY
      : Math.max(4, event.clientY - menuH3);
    // Clamp menu within the left panel
    const leftPanel = document.getElementById('wa-left');
    if (leftPanel) {
      const lRect = leftPanel.getBoundingClientRect();
      if (x + menuW3 > lRect.right) x = lRect.right - menuW3 - 4;
      if (x < lRect.left) x = lRect.left + 4;
    }
    if (x + menuW3 > vw) x = vw - menuW3 - 4;
    if (x < 4) x = 4;
    if (y + menuH3 > vh - 2) y = Math.max(4, vh - menuH3 - 4);
    if (y < 4) y = 4;
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

  // ── Create new file / folder (VS Code inline input pattern) ──────────────

  window.WA.startNewFile = (folderPath) => {
    _insertNewItemInput(folderPath, 'file');
  };

  window.WA.startNewFolder = (parentPath) => {
    _insertNewItemInput(parentPath, 'folder');
  };

  function _insertNewItemInput(parentPath, kind) {
    // Open the folder so the input is visible
    const fileIcon = kind === 'folder'
      ? `<span class="wa-file-icon">${_FOLDER_SVG}</span>`
      : `<span class="wa-file-icon">${_DEFAULT_FILE_SVG}</span>`;

    const row = document.createElement('div');
    row.className = 'wa-file-item wa-new-item-row';

    // Calculate depth from parent
    let depth = 0;
    if (parentPath) {
      const parentEl = document.querySelector(`.wa-file-item[data-path="${CSS.escape(parentPath)}"]`);
      if (parentEl) depth = parseInt(parentEl.dataset.depth || '0', 10) + 1;
    }
    row.innerHTML = `<span class="wa-tree-indent" style="padding-left:${depth * 16 + 8}px"></span>${fileIcon}`;

    const input = document.createElement('input');
    input.className = 'wa-rename-input wa-new-item-input';
    input.placeholder = kind === 'folder' ? '文件夹名称' : '文件名.txt';
    row.appendChild(input);

    // Find insertion point — inside the folder's children, or at the top of the list
    let inserted = false;
    if (parentPath) {
      const folderGroup = document.querySelector(`.wa-folder-group[data-folder="${CSS.escape(parentPath)}"]`);
      if (folderGroup) {
        const childrenEl = folderGroup.querySelector('.wa-folder-children');
        if (childrenEl) {
          // Ensure the folder is open
          childrenEl.style.display = 'block';
          const arrowEl = folderGroup.querySelector('.wa-folder-arrow');
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
      if (!name) { row.remove(); return; }
      try {
        const endpoint = kind === 'folder' ? '/api/v1/workspace/create_folder' : '/api/v1/workspace/create_file';
        const body = kind === 'folder'
          ? { parent: parentPath || '', name }
          : { folder: parentPath || '', name };
        const res = await fetch(endpoint, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
        const json = await res.json();
        if (!res.ok) throw new Error(json.error || '创建失败');
        showToast(`"${name}" 已创建`, 'success');
      } catch (e) {
        showToast(e.message, 'error');
      }
      row.remove();
      await loadWorkspaceFiles();
    };

    let committed = false;
    input.addEventListener('keydown', e => {
      if (e.key === 'Enter') { e.preventDefault(); if (!committed) { committed = true; commit(); } }
      if (e.key === 'Escape') { row.remove(); }
    });
    input.addEventListener('blur', () => { if (!committed) { committed = true; commit(); } });
  }

  // ── Open Folder as Workspace (VS Code "Open Folder" shortcut) ────────────

  window.WA.openFolderAsWorkspace = () => {
    const overlay = document.getElementById('wa-open-folder-overlay');
    if (overlay) overlay.style.display = '';
  };

  window.WA.closeFolderOverlay = () => {
    const overlay = document.getElementById('wa-open-folder-overlay');
    if (overlay) overlay.style.display = 'none';
  };

  window.WA.confirmOpenFolder = async () => {
    const input = document.getElementById('wa-open-folder-path');
    if (!input) return;
    const path = input.value.trim();
    if (!path) return;
    try {
      const res = await fetch('/api/v1/workspace/set_workspace_dir', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path }),
      });
      const json = await res.json();
      if (!res.ok) throw new Error(json.error || '切换失败');
      showToast(`工作区已切换到 "${json.name}"`, 'success');
      WA.closeFolderOverlay();
      await loadWorkspaceFiles();
    } catch (e) {
      showToast(e.message, 'error');
    }
  };

  // Also wire Browse button to pick a folder (File System Access API)
  window.WA.browseForFolder = async () => {
    if (window.showDirectoryPicker) {
      try {
        const dir = await window.showDirectoryPicker({ mode: 'readwrite' });
        const input = document.getElementById('wa-open-folder-path');
        if (input) {
          // We only get a virtual handle here; show the folder name as hint
          input.value = dir.name;
          input.placeholder = dir.name;
          showToast('已选择文件夹: ' + dir.name + ' （请确认系统路径）', 'info');
        }
      } catch (e) { /* user cancelled */ }
    } else {
      showToast('浏览器不支持文件夹选择，请直接粘贴路径', 'info');
    }
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
      _trackUserOpen(path);  // still track re-opens as user intent
      await _switchToTab(path);
      return;
    }
    const baseName = path.split('/').pop();
    _trackUserOpen(path);   // record before fetch so it's captured even if load fails
    showToast('正在加载 ' + baseName, 'success');
    try {
      const encodedPath = path.split('/').map(p => encodeURIComponent(p)).join('/');
      const res = await fetch('/api/v1/workspace/file/' + encodedPath);
      if (!res.ok) throw new Error('File not found');
      const blob = await res.blob();
      const file = new File([blob], baseName);
      file._wsPath = path;
      await Router.load(file);
      loadRecentFiles();   // refresh recent list after successful open
    } catch (e) {
      console.error('[WA openWorkspaceFile]', e);
      showToast('无法打开文件: ' + e.message, 'error');
    }
  };

  // ── Global Selection Tooltip ──
  let lastSelectionText = "";
  let _draggingChartSrc = null;
  let _draggingChartName = null;

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

  // Briefly highlight newly accepted AI text using CSS Custom Highlight API.
  // Highlights the first matching text node in the editor (3-second green flash).
  // Non-destructive — does NOT modify any DOM or editor state.
  function _applyTemporaryHighlight(textToFind) {
    if (!textToFind || !window.CSS || !CSS.highlights) return;
    try {
      const container = document.getElementById('wa-docx-editor') ||
                        document.getElementById('wa-workspace') || document.body;
      const ranges = [];
      const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT, null, false);
      let node;
      while ((node = walker.nextNode())) {
        const text = node.nodeValue || '';
        let idx = 0;
        while ((idx = text.indexOf(textToFind, idx)) !== -1) {
          const r = document.createRange();
          r.setStart(node, idx);
          r.setEnd(node, idx + textToFind.length);
          ranges.push(r);
          idx += textToFind.length;
        }
      }
      if (ranges.length) {
        CSS.highlights.set('wa-accepted-highlight', new Highlight(...ranges));
        setTimeout(() => { try { CSS.highlights.delete('wa-accepted-highlight'); } catch(e) {} }, 3000);
      }
    } catch(e) { console.warn('[WA highlight]', e); }
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

  // ── Show/hide the persistent analysis-subject bar ──
  // Called whenever a file is opened or closed so the user always knows
  // which file the AI is currently working on.
  function _updateSubjectBar(fileName, fileType) {
    // Keep the legacy subject-bar hidden — context is shown in the input-area indicator instead
    const bar = $('wa-subject-bar');
    if (bar) bar.style.display = 'none';

    const ctx = $('wa-context-indicator');
    const ctxL = $('wa-ctx-label');

    if (!fileName) {
      if (ctx) ctx.style.display = 'none';
      return;
    }

    if (ctx && ctxL) {
      if (!state._aiFileContext || state._aiFileContext.length === 0) {
        ctxL.innerHTML = `当前分析：<b style="color:var(--text);font-weight:600">${_escHtml(fileName)}</b>`;
        ctx.style.display = 'flex';
      } else {
        ctx.style.display = 'none';
      }
    }
  }

  // ── Extract PPTX table shape data as tab-separated text (for AI actions) ──
  function _extractPptxTableText(shape) {
    const rows = shape.table_rows || 0;
    const cols = shape.table_cols || 0;
    const cellDataMap = {};
    (shape.cells || []).forEach(c => { cellDataMap[c.row + '_' + c.col] = c; });
    const lines = [];
    for (let r = 0; r < rows; r++) {
      const rowData = [];
      for (let c = 0; c < cols; c++) {
        const cell = cellDataMap[r + '_' + c];
        rowData.push((cell && cell.text) ? cell.text.replace(/[\t\n]/g, ' ').trim() : '');
      }
      lines.push(rowData.join('\t'));
    }
    return lines.join('\n');
  }

  // ── Extract an HTML <table> DOM element as tab-separated text ──────────────
  function _extractHtmlTableText(tblEl) {
    const lines = [];
    for (let r = 0; r < tblEl.rows.length; r++) {
      const row = tblEl.rows[r];
      const cells = [];
      for (let c = 0; c < row.cells.length; c++) {
        cells.push(row.cells[c].textContent.trim().replace(/[\t\n]/g, ' '));
      }
      lines.push(cells.join('\t'));
    }
    return lines.join('\n');
  }

  // ── Show #wa-pdf-tooltip positioned near a DOM element (for table shapes) ──
  function _showTableTooltipNear(el) {
    const tt = $('wa-pdf-tooltip');
    if (!tt || !el) return;
    const rect = el.getBoundingClientRect();
    const GAP = 6;
    const vw = window.innerWidth;
    tt.style.visibility = 'hidden';
    tt.style.display = 'flex';
    const ttW = tt.offsetWidth || 260;
    tt.style.display = 'none';
    tt.style.visibility = '';
    const cx = rect.left + rect.width / 2;
    let left = cx - ttW / 2;
    left = Math.max(8, Math.min(left, vw - ttW - 8));
    let top = rect.top - 42 - GAP;
    if (top < 8) top = rect.bottom + GAP;
    tt.style.left = left + 'px';
    tt.style.top = top + 'px';
    tt.style.display = 'flex';
  }

  // ── Position #wa-pdf-tooltip below the WangEditor format bar (or below the
  //    selection when no format bar is present, e.g. PDF/PPTX).
  //    Uses getBoundingClientRect() so coords are always viewport-relative,
  //    which is correct for position:fixed elements (fixes pageX/pageY bug).
  function _positionSelectionToolbar(mouseEvent) {
    const tt = $('wa-pdf-tooltip');
    if (!tt) return;
    const winSel = window.getSelection();
    if (!winSel || winSel.rangeCount === 0) return;

    // ── Check selection geometry FIRST before mutating display state ──
    // (avoids the bug where early-return leaves toolbar stuck at display:none)
    const rect = winSel.getRangeAt(0).getBoundingClientRect();
    if (!rect || (rect.width === 0 && rect.height === 0)) return;

    // Measure the toolbar dimensions (visibility trick avoids layout flash)
    tt.style.visibility = 'hidden';
    tt.style.display = 'flex';
    const ttW = tt.offsetWidth || 220;
    const ttH = tt.offsetHeight || 36;
    tt.style.display = 'none';
    tt.style.visibility = '';

    const GAP = 8;
    const vw = window.innerWidth;
    const vh = window.innerHeight;

    // Horizontal: center on the selection bounding box (reliable for any selection shape).
    // Using mouse clientX caused drift when the user finished dragging at an edge.
    const cx = rect.left + rect.width / 2;
    let left = cx - ttW / 2;
    left = Math.max(8, Math.min(left, vw - ttW - 8));

    // Vertical: prefer ABOVE the selection top so the toolbar sits where the user's
    // eye is (start of the selection), not at the bottom where they released the mouse.
    // For long multi-paragraph selections, mouseEvent.clientY (mouse-release) can be
    // hundreds of px below the readable content, giving the appearance of "far away".
    let top = rect.top - ttH - GAP;
    if (top < 8) top = rect.bottom + GAP;      // no room above → drop below selection
    if (top + ttH > vh - 8) top = Math.max(8, rect.top - ttH - GAP); // clamp viewport bottom

    tt.style.left = left + 'px';
    tt.style.top  = top  + 'px';
    tt.style.display = 'flex';
  }

  document.addEventListener('mouseup', (e) => {
    if (e.target.id === 'wa-pdf-tooltip') return;
    
    if (state.fileType === 'xlsx') return;

    const sel = window.getSelection().toString().trim();
    const tt = $('wa-pdf-tooltip');
    
    if (sel && sel.length > 0) {
      lastSelectionText = sel;
      _positionSelectionToolbar(e);

      // Update character count badge in tooltip
      const countEl = $('wa-tooltip-count');
      if (countEl) countEl.textContent = `${sel.replace(/\s/g, '').length}字`;

      // If the chip is already showing (prior pinned context), update it immediately
      // so user sees the new selection reflected without needing to click the chat input again
      if ($('wa-selection-chip').style.display !== 'none') {
        _saveEditorRange();
        _pinSelectionChip(sel);
        _clearPinnedHighlight();
        _applyPinnedHighlight();
      }

      // Live-update the context indicator to show selected text preview (always)
      const ctx2 = $('wa-context-indicator');
      const ctxL2 = $('wa-ctx-label');
      if (ctx2 && ctxL2) {
        const preview = sel.length > 60 ? sel.substring(0, 60) + '…' : sel;
        ctxL2.innerHTML = `已选中：<b style="color:var(--primary,#7c6af5);font-weight:600">${_escHtml(preview)}</b>`;
        ctx2.style.display = 'flex';
      }
    } else {
      // ── PPTX table shape selected: expose its data to AI quick-actions ──
      if (state.fileType === 'pptx' && state.activeEditor && state.activeEditor._lastTableText) {
        lastSelectionText = state.activeEditor._lastTableText;
        const countEl = $('wa-tooltip-count');
        if (countEl) countEl.textContent = `${state.activeEditor._lastTableRows}×${state.activeEditor._lastTableCols} 表格`;
        _showTableTooltipNear(state.activeEditor._selShape);
        return;
      }
      // ── DOCX table: cursor clicked inside a table cell with no text selection ──
      if (state.fileType === 'docx' && e.target && e.target.closest) {
        const tbl = e.target.closest('#wa-editor-content table');
        if (tbl) {
          const tableText = _extractHtmlTableText(tbl);
          if (tableText) {
            lastSelectionText = tableText;
            const rows = tbl.rows.length;
            const cols = rows > 0 ? tbl.rows[0].cells.length : 0;
            const countEl = $('wa-tooltip-count');
            if (countEl) countEl.textContent = `${rows}×${cols} 表格`;
            _showTableTooltipNear(tbl);
            // Update context indicator
            const ctx2 = $('wa-context-indicator');
            const ctxL2 = $('wa-ctx-label');
            if (ctx2 && ctxL2) {
              ctxL2.innerHTML = `已选中：<b style="color:var(--primary,#7c6af5);font-weight:600">${rows}×${cols} 表格</b>`;
              ctx2.style.display = 'flex';
            }
            return;
          }
        }
      }
      tt.style.display = 'none';
      lastSelectionText = "";
      // Revert context indicator: multi-doc count or single file name
      const ctx3 = $('wa-context-indicator');
      const ctxL3 = $('wa-ctx-label');
      if (ctx3 && ctxL3) {
        const nFiles = state._aiFileContext ? state._aiFileContext.length : 0;
        if (nFiles > 0) {
          ctxL3.innerHTML = `已附加 <b style="color:var(--text);font-weight:600">${nFiles} 份文件</b>`;
          ctx3.style.display = 'flex';
        } else {
          _updateSubjectBar(state.fileName, state.fileType);
        }
      }
    }
  });

  document.addEventListener('mousedown', (e) => {
    // Use closest() so clicks on child buttons inside the toolbar don't dismiss it
    if (!e.target.closest('#wa-pdf-tooltip')) {
       $('wa-pdf-tooltip').style.display = 'none';
    }
  });

  // Hide the selection toolbar on any scroll so it never blocks the AI panel
  document.addEventListener('scroll', () => {
    $('wa-pdf-tooltip').style.display = 'none';
    lastSelectionText = '';
  }, true);
  const _waAiMsgs = $('wa-ai-messages');
  if (_waAiMsgs) {
    _waAiMsgs.addEventListener('wheel', (e) => {
      const tt = $('wa-pdf-tooltip');
      if (tt && tt.style.display !== 'none') {
        tt.style.display = 'none';
        lastSelectionText = '';
      }
    }, { passive: true });
  }
  // Catch-all: if the selection tooltip is visible anywhere on the page and the
  // user wheels (even if the tooltip is z-index-stacked over the AI panel and
  // intercepts the event before it reaches #wa-ai-messages), hide it immediately
  // so the next wheel tick goes straight to the intended scrollable element.
  document.addEventListener('wheel', () => {
    const tt = $('wa-pdf-tooltip');
    if (tt && tt.style.display !== 'none') {
      tt.style.display = 'none';
      lastSelectionText = '';
    }
  }, { passive: true, capture: true });

  window.WA.sendQuickAction = (action) => {
    let sel = lastSelectionText;
    if (state.fileType === 'xlsx' && state.activeEditor) {
      const rangeText = state.activeEditor.getContent();
      if (rangeText && !rangeText.includes('未选中区域')) sel = rangeText;
    }
    if (!sel) { showToast('请先选中文字', 'info'); return; }

    $('wa-pdf-tooltip').style.display = 'none';
    // Save WangEditor Slate selection BEFORE clearing browser selection, so
    // acceptProposal can restore it for an in-place, Undo-safe replacement.
    _saveEditorRange();
    state.pinnedSelection = sel;
    // Clear the browser text selection so the mouseup handler won't
    // re-show the tooltip over the document while the result is loading.
    lastSelectionText = '';
    try { window.getSelection()?.removeAllRanges(); } catch (_) {}

    const ACTION_LABELS = {
      '润色': '润色优化', '翻译': '翻译（中英互译）', '总结': '总结要点',
      '续写': '续写', '改写': '改写', '解释': '解释分析', '可视化': '数据可视化',
    };

    const msgs = $('wa-ai-messages');
    const preview = sel.length > 60 ? sel.substring(0, 60) + '…' : sel;
    const uMsg = document.createElement('div');
    uMsg.className = 'wa-msg user';
    uMsg.textContent = `${action}：${preview}`;
    msgs.appendChild(uMsg);

    const loadingEl = document.createElement('div');
    loadingEl.className = 'wa-msg ai streaming';
    loadingEl.innerHTML = '<span class="wa-progress-text">⏳ 处理中…</span>';
    msgs.appendChild(loadingEl);
    msgs.scrollTop = msgs.scrollHeight;

    state.lastPinnedSel = sel;
    // Read-only actions: show result as chat message, not as a proposal card
    const READ_ONLY_QUICK_ACTIONS = new Set(['总结', '解释', '翻译']);
    fetch('/api/v1/workspace/quick-action', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        action,
        text: sel,
        file_type: state.fileType || 'general',
        locked_model: state.lockedModel || 'auto',
      }),
    })
    .then(r => r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)))
    .then(data => {
      loadingEl.remove();
      // Notify user about model used
      if (data.used_local_model) {
        const noteEl = document.createElement('div');
        noteEl.className = 'wa-msg system';
        const _userChoseLocal = (state.lockedModel === 'local');
        noteEl.style.cssText = _userChoseLocal
          ? 'background:rgba(80,160,80,0.08);border-left:3px solid #52a052;padding:5px 8px;font-size:11px;color:#3a7a3a;border-radius:3px;'
          : 'background:rgba(255,171,0,0.1);border-left:3px solid #ffab00;padding:5px 8px;font-size:11px;color:#a07800;border-radius:3px;';
        noteEl.textContent = _userChoseLocal
          ? '🦙 本次由本地模型 (Ollama) 生成'
          : '⚠️ 云端 AI 暂时不可用，本次由本地模型 (Ollama) 处理，结果质量可能略有差异。';
        msgs.appendChild(noteEl);
      }
      // ── Chart result ──
      if (data.type === 'chart_result') {
        if (data.error) {
          const errEl = document.createElement('div');
          errEl.className = 'wa-msg ai';
          errEl.textContent = `❌ 图表生成失败：${data.error}`;
          msgs.appendChild(errEl);
          if (data.code) {
            const pre = document.createElement('pre');
            pre.className = 'wa-msg ai wa-code-block';
            pre.textContent = data.code;
            msgs.appendChild(pre);
          }
        } else {
          if (data.code) {
            const codeWrap = document.createElement('div');
            codeWrap.className = 'wa-msg ai wa-chart-code';
            codeWrap.innerHTML = `<details><summary>🐍 查看生成的代码</summary><pre>${data.code.replace(/</g,'&lt;').replace(/>/g,'&gt;')}</pre></details>`;
            msgs.appendChild(codeWrap);
          }
          (data.images || []).forEach(({ name, data: b64 }) => {
            const ext = (name || 'chart.png').split('.').pop().toLowerCase();
            const mime = ext === 'svg' ? 'image/svg+xml' : `image/${ext}`;
            const imgSrc = `data:${mime};base64,${b64}`;
            msgs.appendChild(_makeWAChartImageWrap(imgSrc, name || 'chart.png'));
          });
          if (!data.images || data.images.length === 0) {
            const noImg = document.createElement('div');
            noImg.className = 'wa-msg ai';
            noImg.textContent = '⚠️ 代码已执行，但未生成图片，请查看代码';
            msgs.appendChild(noImg);
          }
        }
        msgs.scrollTop = msgs.scrollHeight;
        return;
      }
      if (data.result) {
        if (READ_ONLY_QUICK_ACTIONS.has(action)) {
          // Read-only result: show as AI message only, no proposal card
          const aiEl = document.createElement('div');
          aiEl.className = 'wa-msg ai';
          const renderMd = (t) => {
            if (window.marked) { try { return window.marked.parse(t || ''); } catch(e) {} }
            return (t || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\n/g,'<br>');
          };
          aiEl.innerHTML = renderMd(data.result);
          msgs.appendChild(aiEl);
        } else {
          _handleProposals({
            proposals: [{
              id: 'qa_' + Date.now(),
              original_text: sel,
              proposed_text: data.result,
              rationale: ACTION_LABELS[action] || action,
            }],
          });
        }
      } else {
        const errEl = document.createElement('div');
        errEl.className = 'wa-msg ai';
        errEl.textContent = data.error || '❌ 快速处理失败，请稍后重试';
        msgs.appendChild(errEl);
      }
      msgs.scrollTop = msgs.scrollHeight;
    })
    .catch(err => {
      loadingEl.remove();
      const errEl = document.createElement('div');
      errEl.className = 'wa-msg ai';
      errEl.textContent = `❌ 网络错误：${err.message}`;
      msgs.appendChild(errEl);
      msgs.scrollTop = msgs.scrollHeight;
    });
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
    // Auto-expand AI panel when transferring selection
    _expandWAPanel();
    $('wa-user-input').focus();
  };

  // Auto-expand the right AI panel if it's collapsed
  function _expandWAPanel() {
    const panel = $('wa-ai');
    if (!panel) return;
    const gutter = panel.previousElementSibling;
    if (gutter && gutter.classList.contains('gutter')) {
      if (panel.offsetWidth < 80) {
        // panel is near-collapsed: restore to 30% size via Split.js
        try { window._waSplit && window._waSplit.setSizes([15, 55, 30]); } catch {}
      }
    }
  }

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
  window._waSplit = Split(['#wa-left', '#wa-canvas', '#wa-ai'], {
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
      this._zoom = 100;
      $(this.containerId).classList.add('active');

      // Ctrl+Wheel zoom
      this._wheelHandler = (e) => {
        if (!e.ctrlKey && !e.metaKey) return;
        e.preventDefault();
        const delta = e.deltaY > 0 ? -10 : 10;
        this.setZoom(this._zoom + delta);
      };
      $(this.containerId).addEventListener('wheel', this._wheelHandler, { passive: false });
    }

    render(html) {
      // Safely destroy previous instances first
      if (this._mutationObs) { this._mutationObs.disconnect(); this._mutationObs = null; }
      if (this._hoverbarObs) { this._hoverbarObs.disconnect(); this._hoverbarObs = null; }
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
          // Text hoverbar: inline formatting when text is selected
          // Table hoverbar: row/col/merge actions when cursor is inside a table cell
          hoverbarKeys: {
            'text': {
              menuKeys: [
                // PROTECTED(format-hoverbar): keep font controls for DOCX quick formatting.
                'fontFamily', 'fontSize',
                'divider',
                'bold', 'underline', 'italic', 'through', 'code',
                'divider',
                'color', 'bgColor', 'clearStyle',
                'divider',
                'insertLink',
              ],
            },
            'table': {
              menuKeys: [
                'tableHeader', 'tableFullWidth',
                'insertTableRow', 'deleteTableRow',
                'insertTableCol', 'deleteTableCol',
                'mergeTableCell', 'splitTableCell',
                'divider',
                'deleteTable',
              ],
            },
          },
          MENU_CONF: {
            uploadImage: { base64LimitSize: 5 * 1024 * 1024 },
            insertImage: { checkImage(src) { return true; } },
            // Allow any table size up to 20×20
            insertTable: { maxRow: 20, maxCol: 20 },
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
        config: {
          excludeKeys: ['fullScreen'],
          // Explicitly include all table-related toolbar groups
          insertKeys: {
            index: 999,
            keys: ['insertTable', 'tableHeader', 'tableFullWidth',
                   'mergeTableCell', 'splitTableCell',
                   'insertTableRow', 'deleteTableRow',
                   'insertTableCol', 'deleteTableCol',
                   'deleteTable'],
          },
        }
      });

      // MutationObserver as backup — fires even when WangEditor doesn't trigger onChange.
      // Attach after createEditor() so WangEditor has created its DOM.

      // Apply current zoom immediately after editor DOM is created
      const scrollElNow = ct.querySelector('.w-e-scroll');
      if (scrollElNow && this._zoom !== 100) scrollElNow.style.zoom = this._zoom / 100;

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

        // ── Scroll stabiliser: prevent Slate scrollIntoView() jumps on blank clicks ──
        // Slate fires scrollIntoView() on every selection change, jumping the viewport
        // when the user clicks in blank page margins.  Fix: save scrollTop on every
        // mousedown; restore it if a scroll event fires within 300 ms AND the delta is
        // large enough to be a programmatic jump (> 80 px), not a deliberate scroll.
        const scrollEl = ct.querySelector('.w-e-scroll');
        if (scrollEl) {
          scrollEl.style.overflowAnchor = 'none';
          scrollEl.style.scrollBehavior = 'auto';
          let _savedScroll = 0;
          let _lockScroll  = false;
          editable.addEventListener('mousedown', () => {
            _savedScroll = scrollEl.scrollTop;
            _lockScroll  = true;
            setTimeout(() => { _lockScroll = false; }, 300);
          }, { passive: true });
          scrollEl.addEventListener('scroll', () => {
            if (_lockScroll && Math.abs(scrollEl.scrollTop - _savedScroll) > 80) {
              scrollEl.scrollTop = _savedScroll;
            }
          }, { passive: true });
        }

        // ── Table column drag-resize ──────────────────────────────────────────
        // CSS sets table-layout:fixed so column widths stick; the right-edge of
        // every td/th shows a resize cursor (via ::after handle in workspace.css).
        let _colResize = null;
        editable.addEventListener('mousedown', (ev) => {
          const cell = ev.target.closest('td, th');
          if (!cell) return;
          const rect = cell.getBoundingClientRect();
          if (ev.clientX < rect.right - 6) return;   // only the 6 px right-edge zone
          const table = cell.closest('table');
          if (!table) return;
          ev.preventDefault();
          ev.stopPropagation();
          const ci = cell.cellIndex;
          const cols = Array.from(table.rows).map(r => r.cells[ci]).filter(Boolean);
          _colResize = { cols, startX: ev.clientX, startWidths: cols.map(c => c.offsetWidth) };
        });
        document.addEventListener('mousemove', (ev) => {
          if (!_colResize) return;
          const delta = ev.clientX - _colResize.startX;
          _colResize.cols.forEach((c, i) => {
            c.style.width = Math.max(32, _colResize.startWidths[i] + delta) + 'px';
          });
        });
        document.addEventListener('mouseup', () => { _colResize = null; });

        // ── Hoverbar 定位修复：保证字体格式工具栏显示在选中文本上方而不遮住文字 ──
        // WangEditor v5 使用 getClientRects()[0]（仅首行）定位 hoverbar，导致
        // 多行选区时工具栏出现在选中文字内部。此 MutationObserver 在 hoverbar 显示
        // 时用完整选区的 getBoundingClientRect() 将其重新定位到选区正上方。
        const _hoverCtEl = ct.querySelector('.w-e-text-container');
        if (_hoverCtEl) {
          const _repositionHoverbar = () => {
            // WangEditor may show/hide the hoverbar by toggling inline style (display)
            // OR by adding/removing a CSS class — query the bar regardless of method.
            const bar = _hoverCtEl.querySelector('.w-e-bar');
            // offsetHeight === 0 means the element is display:none or has no height → hidden
            if (!bar || bar.offsetHeight === 0) return;
            // When CSS zoom is applied to .w-e-scroll, getBoundingClientRect() may return
            // pre-zoom layout coordinates (browser-specific), making newTop huge → bar flies off-screen.
            // Skip repositioning in that case; WangEditor's default positioning takes over.
            const scrollEl = _hoverCtEl.querySelector('.w-e-scroll');
            if (scrollEl && Math.abs((parseFloat(scrollEl.style.zoom) || 1) - 1) > 0.01) return;
            const winSel = window.getSelection();
            // 只对文字选择生效；表格/图片 hoverbar 保持 WangEditor 原位
            if (!winSel || winSel.rangeCount === 0 || !winSel.toString().trim()) return;
            const selRect = winSel.getRangeAt(0).getBoundingClientRect();
            if (!selRect || selRect.height === 0) return;
            const ctRect = _hoverCtEl.getBoundingClientRect();
            const barH = bar.offsetHeight || 36;
            const GAP = 6;
            // 将 hoverbar 底边定位在选区顶边上方 GAP px 处
            const newTop = selRect.top - ctRect.top - barH - GAP;
            bar.style.setProperty('top', `${Math.max(2, newTop)}px`, 'important');
            bar.style.removeProperty('bottom');
          };
          this._hoverbarObs = new MutationObserver(_repositionHoverbar);
          this._hoverbarObs.observe(_hoverCtEl, {
            subtree: true,
            attributes: true,
            // No attributeFilter: observe ALL attribute changes (class, style, etc.)
            // WangEditor v5 shows the bar via inline style (display:block), not a CSS class,
            // so filtering on 'class' alone would cause the observer to never fire.
            childList: true,
          });
        }
      }, 300);
    }

    setZoom(pct) {
      this._zoom = Math.max(50, Math.min(200, pct));
      const scrollEl = document.querySelector('#wa-docx-editor .w-e-scroll');
      if (scrollEl) scrollEl.style.zoom = this._zoom / 100;
      _updateDocxZoomUI(this._zoom);
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
      if (cmd.type === 'replace_all') {
        // Full document replacement — rebuild editor with new HTML content
        this.render(cmd.value || '');
        showToast('AI 已替换文档内容', 'success');
        WA.scheduleAutoSave && WA.scheduleAutoSave();
        return;
      }
      if (cmd.type === 'replace_text') {
        const original = cmd.original || '';
        const proposed = cmd.value || '';
        if (!original) return;

        // Convert plain-text AI reply to safe HTML for WangEditor insertion.
        // Handles multi-paragraph replies by wrapping lines in <p> tags.
        const _toInsertHtml = (text) => {
          if (!text) return '';
          if (text.trimStart().startsWith('<')) return text;  // already HTML
          const paras = text.split(/\n{2,}/).filter(p => p.trim());
          if (paras.length > 1) {
            return paras.map(p => '<p>' + p.replace(/\n/g, '<br>') + '</p>').join('');
          }
          return text.replace(/\n/g, '<br>');
        };

        let replaced = false;
        let usedSlate = false;

        // ── Strategy 1: Restore Slate selection then dangerouslyInsertHtml ────
        // Preserves Undo history — Ctrl+Z works after this path.
        if (this._savedRange) {
          try {
            this.editor.focus();
            this.editor.select(this._savedRange);
            const selText = (this.editor.getSelectionText() || '').replace(/\s+/g, ' ').trim();
            const origNorm = original.replace(/\s+/g, ' ').trim();
            // Accept if the restored selection overlaps the original text enough
            const selOk = selText && (
              selText === origNorm ||
              origNorm.startsWith(selText.substring(0, Math.min(15, selText.length))) ||
              selText.startsWith(origNorm.substring(0, Math.min(15, origNorm.length)))
            );
            if (selOk) {
              this.editor.dangerouslyInsertHtml(_toInsertHtml(proposed));
              this._savedRange = null;
              replaced = true;
              usedSlate = true;
            }
          } catch (e) {
            console.warn('[WA replace_text] slate path failed:', e);
          }
        }

        // ── Strategy 2: HTML-level replacement (destroys Undo history) ────────
        // Handles both single-paragraph and multi-paragraph selections.
        // Multi-paragraph: browser getSelection gives \n, but HTML has </p><p>.
        if (!replaced) {
          try {
            const currentHtml = (() => { try { return this.editor.getHtml(); } catch(e) { return this._lastHtml || ''; } })();

            // 2a: direct string match (works for single-paragraph selections)
            let newHtml = currentHtml.includes(original)
              ? currentHtml.split(original).join(proposed)
              : currentHtml;

            // 2b: paragraph-boundary aware regex for multi-paragraph selections
            if (newHtml === currentHtml) {
              const lines = original.split('\n').filter(l => l.trim());
              if (lines.length > 1) {
                const escapedLines = lines.map(l => l.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
                const flexRe = new RegExp(
                  escapedLines.join('(?:\\s*</p>\\s*<p[^>]*>\\s*|\\s*<br\\s*/?>\\s*|[\\s\\u3000])+'),
                  'g'
                );
                const candidate = currentHtml.replace(flexRe, () => proposed);
                if (candidate !== currentHtml) newHtml = candidate;
              }
            }

            if (newHtml !== currentHtml) {
              this.render(newHtml);
              replaced = true;
            }
          } catch (e) {
            console.warn('[WA replace_text] html path failed:', e);
          }
        }

        if (!replaced) {
          showToast('未在文档中找到原文', 'info');
          return;
        }

        showToast('AI 已更新文档', 'success');
        if (typeof WA.scheduleAutoSave === 'function') WA.scheduleAutoSave();

        // Brief green highlight on the newly inserted text (3 s, CSS-only, non-destructive)
        const plainProposed = proposed.replace(/<[^>]+>/g, '').trim();
        if (plainProposed) {
          // Use the first meaningful sentence/clause (≤30 chars) as the search token.
          const firstToken = plainProposed
            .split(/[。！？.!?\n]/)
            .map(s => s.trim())
            .find(s => s.length >= 4) || plainProposed.substring(0, 30);
          // Delay: Slate path is synchronous, HTML render needs DOM rebuild time.
          setTimeout(() => _applyTemporaryHighlight(firstToken), usedSlate ? 60 : 350);
        }
        return;
      }
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

    replaceSelectionWith(mode, pinnedText, newText) {
      const clean = typeof newText === 'string' ? newText : String(newText || '');
      if (mode === 'append') {
        this.applyToolCall({ type: 'insert_text', value: '\n' + clean });
      } else {
        if (pinnedText) {
          this.applyToolCall({ type: 'replace_text', original: pinnedText, value: clean });
        } else {
          this.applyToolCall({ type: 'set_html', value: clean });
        }
      }
    }

    destroy() {
      if (this._mutationObs) { this._mutationObs.disconnect(); this._mutationObs = null; }
      if (this._hoverbarObs) { this._hoverbarObs.disconnect(); this._hoverbarObs = null; }
      if (this.editor) { try { this.editor.destroy(); } catch(e) {} }
      if (this.toolbar) { try { this.toolbar.destroy(); } catch(e) {} }
      this.editor = null;
      this.toolbar = null;
      const wrapper = $(this.containerId);
      if (wrapper) {
        wrapper.removeEventListener('wheel', this._wheelHandler);
        wrapper.classList.remove('active');
      }
    }
  }

  class KotoXlsxEditor {
    constructor() {
      this.containerId = 'wa-xlsx-editor';
      this._containerId = 'wa-xlsx-sheet';
      this._api = null;       // FUniver instance
      this._images = [];      // [{src, x, y, w, h}] overlay images for export
      $(this.containerId).classList.add('active');
    }

    render(workbookData) {
      // Destroy previous Univer instance if any
      if (this._api) {
        try { window.KotoSheetsAPI.dispose(); } catch (e) {}
        this._api = null;
      }

      const wrapper = $(this.containerId);
      wrapper.innerHTML = '';

      // Univer Sheets container — fills entire wrapper (Univer renders its own toolbar inside)
      const sheetEl = document.createElement('div');
      sheetEl.id = this._containerId;
      sheetEl.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;';
      wrapper.appendChild(sheetEl);

      // Mount Univer Sheets after two rAF ticks to ensure container is laid out.
      // If the wrapper still has zero dimensions (e.g. embedded-mode layout not
      // yet flushed) we poll until real dimensions appear before calling create().
      const _doMount = () => {
        if (!window.KotoSheetsAPI) {
          sheetEl.innerHTML = '<div style="padding:24px;color:#e74c3c;font-size:13px;">Univer Sheets 模块未就绪，请刷新页面重试</div>';
          return;
        }
        // Diagnostic: log container dimensions
        const rect = sheetEl.getBoundingClientRect();
        console.log('[KotoXlsxEditor] sheetEl rect:', rect.width.toFixed(0) + 'x' + rect.height.toFixed(0),
          'offsetW:', sheetEl.offsetWidth, 'offsetH:', sheetEl.offsetHeight,
          'inDOM:', document.body.contains(sheetEl));
        try {
          this._api = window.KotoSheetsAPI.create(sheetEl, workbookData);

          // Trigger Univer's internal ResizeObserver to recalculate canvas dimensions.
          // Univer watches the container element via ResizeObserver (not window.resize).
          // We briefly nudge the container size to guarantee a ResizeObserver callback
          // fires after React has fully mounted and the container has real dimensions.
          setTimeout(() => {
            const w = sheetEl.offsetWidth;
            const h = sheetEl.offsetHeight;
            if (w > 0 && h > 0) {
              sheetEl.style.width = (w + 1) + 'px';
              requestAnimationFrame(() => { sheetEl.style.width = ''; });
            }
          }, 100);

          // Wire selection → AI panel context chip
          window.KotoSheetsAPI.onSelectionChange(() => {
            const text = window.KotoSheetsAPI.getSelectionText();
            if (text) {
              lastSelectionText = `[当前选中表格数据]:\n${text}\n`;
            }
          });
        } catch (err) {
          console.error('[KotoXlsxEditor] Univer Sheets 初始化失败', err);
          sheetEl.innerHTML = `<div style="padding:24px;color:#e74c3c;font-size:13px;">表格引擎加载失败: ${err.message}</div>`;
        }
      };

      // Poll for real container size; fall back to immediate mount if already laid out.
      const _mountDeadline = Date.now() + 800;
      const _tryMount = () => {
        requestAnimationFrame(() => {
          requestAnimationFrame(() => {
            if (sheetEl.offsetWidth > 0 && sheetEl.offsetHeight > 0) {
              _doMount();
            } else if (Date.now() < _mountDeadline) {
              console.warn('[KotoXlsxEditor] 容器尺寸为零，等待布局…');
              setTimeout(_tryMount, 50);
            } else {
              console.error('[KotoXlsxEditor] 容器尺寸为零且超时 — 强制挂载');
              _doMount();  // mount anyway; nudge mechanism will attempt a resize recovery
            }
          });
        });
      };
      _tryMount();
    }

    getContent() {
      if (!window.KotoSheetsAPI || !window.KotoSheetsAPI.isReady()) return '';
      const text = window.KotoSheetsAPI.getSelectionText();
      if (text) return `[当前选中表格数据]:\n${text}\n`;
      return '[当前表格未选中区域，请提示用户框选数据]';
    }

    getCSV() {
      if (!window.KotoSheetsAPI || !window.KotoSheetsAPI.isReady()) return '';
      return window.KotoSheetsAPI.getActiveSheetCSV();
    }

    serialize() {
      const snapshot = (window.KotoSheetsAPI && window.KotoSheetsAPI.isReady())
        ? window.KotoSheetsAPI.getSnapshot()
        : null;
      return { snapshot, _images: this._images };
    }

    applyToolCall(cmd) {
      if (!window.KotoSheetsAPI || !window.KotoSheetsAPI.isReady()) return;
      if (cmd.type === 'set_cell') {
        window.KotoSheetsAPI.setCellValue(cmd.r, cmd.c, cmd.value);
        showToast(`AI 已更新单元格 (${cmd.r}, ${cmd.c})`, 'success');
        WA.scheduleAutoSave();
      } else if (cmd.type === 'set_cells' && Array.isArray(cmd.cells)) {
        cmd.cells.forEach(cell => window.KotoSheetsAPI.setCellValue(cell.r, cell.c, cell.value));
        showToast(`AI 已批量更新 ${cmd.cells.length} 个单元格`, 'success');
        WA.scheduleAutoSave();
      }
    }

    destroy() {
      if (window.KotoSheetsAPI) {
        try { window.KotoSheetsAPI.dispose(); } catch (e) {}
      }
      this._api = null;
      const wrapper = $(this.containerId);
      if (wrapper) wrapper.classList.remove('active');
    }
  }

  // ── Colour contrast utility (module-level, used by KotoPptxEditor) ────────
  // Returns perceived luminance [0..1] from a CSS hex colour like '#3a2b1c'.
  function _hexLuma(hex) {
    if (!hex || hex.length < 7) return 1;
    const r = parseInt(hex.slice(1,3),16)/255;
    const g = parseInt(hex.slice(3,5),16)/255;
    const b = parseInt(hex.slice(5,7),16)/255;
    const toLinear = c => c <= 0.04045 ? c/12.92 : Math.pow((c+0.055)/1.055, 2.4);
    return 0.2126*toLinear(r) + 0.7152*toLinear(g) + 0.0722*toLinear(b);
  }
  // Return a safe foreground colour: if fgHex is light AND bgHex is also light,
  // switch to dark text so it remains readable.
  function _safeTextColor(fgHex, bgHex) {
    if (!fgHex) return null;
    const fgL = _hexLuma(fgHex);
    const bgL = _hexLuma(bgHex || '#ffffff');
    // Both near-white → force dark text
    if (fgL > 0.7 && bgL > 0.7) return '#1a1a1a';
    // Both near-black → force light text
    if (fgL < 0.15 && bgL < 0.15) return '#e8e8e8';
    return fgHex;
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
      // Ensure every slide has .index (backend uses slide_index; AI tool calls match on .index)
      this.data.slides.forEach((s, i) => { if (s.index === undefined) s.index = s.slide_index ?? i; });
      this._curIdx = 0;
      this._buildThumbs();
      this._initKeyHandler();
      const zoomSlider = $('wa-pptx-zoom');
      if (zoomSlider) { zoomSlider.value = 75; this._zoom = 0.75; }
      // Defer first render until after the browser has laid out the flex container
      // so that #wa-pptx-slide-area.clientWidth is non-zero.
      // If the area is still zero-width (embedded-mode layout not flushed yet),
      // poll until real dimensions appear before the first real render.
      const _pptxMountDeadline = Date.now() + 800;
      const _tryPptxRender = () => {
        requestAnimationFrame(() => {
          const area = $('wa-pptx-slide-area');
          const rawW = area ? area.clientWidth : 0;
          if (rawW > 48) {
            this._renderSlide(0);
            WA.pptxZoom && WA.pptxZoom(75);
          } else if (Date.now() < _pptxMountDeadline) {
            console.warn('[KotoPptxEditor] slide-area 宽度为零，等待布局…', rawW);
            setTimeout(_tryPptxRender, 50);
          } else {
            // Deadline reached — render anyway (will use fallback width logic inside _renderSlide)
            console.error('[KotoPptxEditor] slide-area 宽度为零且超时 — 强制渲染');
            this._renderSlide(0);
            WA.pptxZoom && WA.pptxZoom(75);
            // Secondary recovery: re-render once layout is available in next frame
            setTimeout(() => { this._renderSlide(this._curIdx); }, 200);
          }
        });
      };
      _tryPptxRender();
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
      const slideArea = $('wa-pptx-slide-area');
      if (slideArea && this._pptxWheelHandler) slideArea.removeEventListener('wheel', this._pptxWheelHandler);
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

      // Ctrl+Wheel zoom on the slide area
      const slideArea = $('wa-pptx-slide-area');
      if (slideArea) {
        this._pptxWheelHandler = (e) => {
          if (!e.ctrlKey && !e.metaKey) return;
          e.preventDefault();
          const curPct = Math.round((this._zoom || 0.75) * 100);
          const delta = e.deltaY > 0 ? -5 : 5;
          const newPct = Math.max(40, Math.min(150, curPct + delta));
          const slider = $('wa-pptx-zoom');
          if (slider) slider.value = newPct;
          WA.pptxZoom(newPct);
        };
        slideArea.addEventListener('wheel', this._pptxWheelHandler, { passive: false });
      }

      // Save selection range so toolbar interactions (font-size select, etc.) don't lose it.
      // Also update the format toolbar to reflect the run at the current cursor/selection start.
      this._selChangeHandler = () => {
        if (!this._editMode) return;
        const sel = window.getSelection();
        if (sel && sel.rangeCount > 0) {
          const r = sel.getRangeAt(0);
          const anchorEl = r.startContainer.nodeType === 3 ? r.startContainer.parentElement : r.startContainer;
          if (anchorEl && anchorEl.classList && anchorEl.classList.contains('wa-pptx-run')) {
            if (!r.isCollapsed) this._savedRange = r.cloneRange();
            // Update toolbar to reflect run at cursor/selection start
            this._activeSpan = anchorEl;
            const _pi = parseInt(anchorEl.dataset.pi), _ri = parseInt(anchorEl.dataset.ri);
            const _slide = this.data && this.data.slides[this._curIdx];
            const _shp = _slide && (_slide.shapes || []).find(s => s.id === parseInt(anchorEl.dataset.shapeId));
            if (_shp && _shp.paragraphs[_pi]) {
              const _run = (_shp.paragraphs[_pi].runs || [])[_ri];
              if (_run) {
                if ($('wa-pptx-bold'))      $('wa-pptx-bold').classList.toggle('active', !!_run.bold);
                if ($('wa-pptx-italic'))    $('wa-pptx-italic').classList.toggle('active', !!_run.italic);
                if ($('wa-pptx-underline')) $('wa-pptx-underline').classList.toggle('active', !!_run.underline);
                if ($('wa-pptx-fontsize') && _run.size) $('wa-pptx-fontsize').value = Math.round(_run.size);
                if ($('wa-pptx-fontname') && _run.fontName) $('wa-pptx-fontname').value = _run.fontName;
                if ($('wa-pptx-fontcolor') && _run.color) {
                  $('wa-pptx-fontcolor').value = _run.color.startsWith('#') ? _run.color : '#000000';
                  const _sw = $('wa-pptx-fontcolor-swatch');
                  if (_sw) _sw.style.background = _run.color;
                }
              }
            }
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
          const thumbBg = shape.fill || slide.background || '#ffffff';
          shape.paragraphs.forEach(para => {
            const lineText = (para.runs || []).map(r => r.text).join('');
            if (!lineText.trim()) { ty += 4; return; }
            const fr = para.runs[0] || {};
            // Fixed scale: pt size relative to standard 540pt slide height
            const defaultThumbPt = shape.is_title ? 28 : 14;
            const px = Math.max(Math.round((fr.size || defaultThumbPt) * sh / 540), 5);
            ctx.font = (fr.bold ? 'bold ' : '') + px + 'px ' + (fr.fontName || 'sans-serif');
            ctx.fillStyle = _safeTextColor(fr.color, thumbBg) || (_hexLuma(thumbBg) < 0.4 ? '#f0f0f0' : '#222');
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
      // Guard against zero clientWidth (may happen before layout completes).
      // Fall back to 700px which gives a 16:9 canvas at 75% zoom.
      const rawW = area ? area.clientWidth : 0;
      const availW = (rawW > 48 ? rawW : 700) - 48;
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
      this._scale = scale;  // store for use by _selectShape/_startResize

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
          // Pick a default text color that contrasts with the EFFECTIVE background:
          // shape fill (if present) takes priority over the slide background.
          // This handles the common case of colored header bars / dark-filled shapes
          // where the theme text is white but shape.fill is dark.
          const effectiveBg = shape.fill || slide.background || '#ffffff';
          const bgLuma = _hexLuma(effectiveBg);
          const defaultTextColor = bgLuma < 0.4 ? '#f0f0f0' : '#1a1a1a';
          const inner = document.createElement('div');
          inner.className = 'wa-pptx-inner';
          inner.style.cssText = `width:100%;height:100%;padding:4px 6px;box-sizing:border-box;overflow:hidden;display:flex;flex-direction:column;color:${defaultTextColor};`;
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
              const defaultPt = shape.is_title ? 36 : 18;
              span.style.fontSize = Math.max(Math.round((run.size || defaultPt) * scale * 12700), 6) + 'px';
              if (run.bold)      span.style.fontWeight = 'bold';
              if (run.italic)    span.style.fontStyle = 'italic';
              if (run.underline) span.style.textDecoration = 'underline';
              if (run.fontName)  span.style.fontFamily = run.fontName;
              if (run.color) {
                const safe = _safeTextColor(run.color, effectiveBg);
                if (safe) span.style.color = safe;
              }
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
          // Sync all run text to data model when inner (the contentEditable container) fires input.
          inner.addEventListener('input', () => {
            inner.querySelectorAll('.wa-pptx-run').forEach(span => {
              const pi = parseInt(span.dataset.pi), ri = parseInt(span.dataset.ri);
              if (shape.paragraphs[pi] && shape.paragraphs[pi].runs && shape.paragraphs[pi].runs[ri]) {
                shape.paragraphs[pi].runs[ri].text = span.textContent;
              }
            });
            this._redrawThumb(idx);
            WA.scheduleAutoSave();
          });
          // Prevent Enter from inserting raw DOM nodes; Escape exits edit mode.
          inner.addEventListener('keydown', ev => {
            if (ev.key === 'Enter') ev.preventDefault();
            if (ev.key === 'Escape') { ev.stopPropagation(); this._exitEditMode(); }
          });
          el.appendChild(inner);
          // Belt-and-suspenders: stop mousedown from reaching shape's move handler
          // when already in edit mode for this shape (prevents move during text drag).
          inner.addEventListener('mousedown', ev => {
            if (this._editMode && this._selShape === el) ev.stopPropagation();
          });
          // Cursor: border zone → 'move', interior → 'text' (only when selected & not editing)
          el.addEventListener('mousemove', ev => {
            if (ev.target.classList && ev.target.classList.contains('wa-pptx-handle')) return;
            if (this._editMode && this._selShape === el) { el.style.cursor = 'text'; return; }
            if (this._selShape !== el) { el.style.cursor = 'text'; return; }
            const _r = el.getBoundingClientRect(), _B = 8;
            const _onBord = ev.clientX < _r.left + _B || ev.clientX > _r.right - _B ||
                            ev.clientY < _r.top  + _B || ev.clientY > _r.bottom - _B;
            el.style.cursor = _onBord ? 'move' : 'text';
          });
          el.addEventListener('mousedown', e => {
            if (this._insertMode) return;
            // In edit mode on this shape: let browser (and inner) handle cursor/text-selection
            if (this._editMode && this._selShape === el) return;
            e.stopPropagation();
            // Office PPT model: border zone → move shape; interior → enter text editing
            const rect = el.getBoundingClientRect();
            const BORDER_T = 8;
            const onBorder = e.clientX < rect.left + BORDER_T || e.clientX > rect.right - BORDER_T ||
                             e.clientY < rect.top + BORDER_T  || e.clientY > rect.bottom - BORDER_T;
            const wasSelected = (this._selShape === el);
            this._selectShape(el, shape);
            if (!onBorder && wasSelected) {
              // Interior click on already-selected text shape → enter edit mode, no shape-drag
              this._startMove(e, el, shape, canvas, scale, true, false);
            } else {
              // Border click or first click on shape → select + allow drag
              this._startMove(e, el, shape, canvas, scale, false);
            }
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
          // Cursor: border zone → 'move', interior → 'default' (only when selected)
          el.addEventListener('mousemove', ev => {
            if (ev.target.classList && ev.target.classList.contains('wa-pptx-handle')) return;
            if (this._selShape !== el) { el.style.cursor = 'default'; return; }
            const _r = el.getBoundingClientRect(), _B = 8;
            const _onBord = ev.clientX < _r.left + _B || ev.clientX > _r.right - _B ||
                            ev.clientY < _r.top  + _B || ev.clientY > _r.bottom - _B;
            el.style.cursor = _onBord ? 'move' : 'default';
          });
          el.addEventListener('mousedown', e => {
            if (this._insertMode) return;
            this._selectShape(el, shape);
            this._startMove(e, el, shape, canvas, scale);
          });
        } else if (shape._type === 'TABLE' && shape.cells) {
          // ── Table shape ──────────────────────────────────────────────────
          const rows = shape.table_rows || 0;
          const cols = shape.table_cols || 0;
          // Keep a mutable map to cell data objects so input handlers update shape.cells in place
          const cellDataMap = {};
          (shape.cells || []).forEach(c => { cellDataMap[c.row + '_' + c.col] = c; });
          const tbl = document.createElement('table');
          tbl.style.cssText = 'width:100%;height:100%;border-collapse:collapse;table-layout:fixed;';
          const baseFontPx = Math.max(Math.round(10 * 12700 * scale), 6);
          for (let r = 0; r < rows; r++) {
            const tr = document.createElement('tr');
            for (let c = 0; c < cols; c++) {
              const td = document.createElement('td');
              td.className = 'wa-pptx-cell';
              td.dataset.row = r;
              td.dataset.col = c;
              td.contentEditable = 'false';
              td.style.cssText = `border:1px solid #d0d0d0;padding:2px 4px;overflow:hidden;font-size:${baseFontPx}px;vertical-align:top;word-break:break-word;outline:none;`;
              const cellData = cellDataMap[r + '_' + c];
              td.textContent = (cellData && cellData.text) || '';
              td.addEventListener('input', () => {
                if (cellData) {
                  cellData.text = td.textContent;
                } else {
                  // Defensive: cell not in original data — create entry
                  const newCell = { row: r, col: c, text: td.textContent };
                  shape.cells.push(newCell);
                  cellDataMap[r + '_' + c] = newCell;
                }
                WA.scheduleAutoSave();
              });
              td.addEventListener('keydown', e => {
                if (e.key === 'Escape') {
                  this._exitEditMode();
                  e.preventDefault();
                } else if (e.key === 'Tab') {
                  e.preventDefault();
                  const allCells = Array.from(tbl.querySelectorAll('.wa-pptx-cell'));
                  const tdIdx = allCells.indexOf(td);
                  const next = allCells[e.shiftKey ? tdIdx - 1 : tdIdx + 1];
                  if (next) { next.focus(); this._activeSpan = next; }
                }
              });
              td.addEventListener('focus', () => {
                this._selectShape(el, shape);
                this._activeSpan = td;
              });
              tr.appendChild(td);
            }
            tbl.appendChild(tr);
          }
          el.appendChild(tbl);
          el.style.overflow = 'hidden';
          el.style.cursor = 'default';
          // Cursor: border zone → 'move' (only when selected)
          el.addEventListener('mousemove', ev => {
            if (ev.target.classList && ev.target.classList.contains('wa-pptx-handle')) return;
            if (this._editMode && this._selShape === el) return;  // let browser handle inside table
            if (this._selShape !== el) { el.style.cursor = 'default'; return; }
            const _r = el.getBoundingClientRect(), _B = 8;
            const _onBord = ev.clientX < _r.left + _B || ev.clientX > _r.right - _B ||
                            ev.clientY < _r.top  + _B || ev.clientY > _r.bottom - _B;
            el.style.cursor = _onBord ? 'move' : 'default';
          });
          // Stop mousedown from propagating to the move handler when already editing this table
          tbl.addEventListener('mousedown', ev => {
            if (this._editMode && this._selShape === el) ev.stopPropagation();
          });
          el.addEventListener('mousedown', e => {
            if (this._insertMode) return;
            if (this._editMode && this._selShape === el) return;
            this._selectShape(el, shape);
            this._startMove(e, el, shape, canvas, scale);
          });
          el.addEventListener('dblclick', e => {
            if (this._insertMode) return;
            e.stopPropagation();
            // Enter table edit mode: make all cells editable
            if (this._editMode && this._selShape === el) return;
            this._editMode = true;
            el.classList.add('wa-pptx-editing');
            el.querySelectorAll('.wa-pptx-cell').forEach(td => { td.contentEditable = 'true'; });
            // Try to focus the cell that was double-clicked
            const target = e.target.closest('.wa-pptx-cell');
            const focusCell = target || el.querySelector('.wa-pptx-cell');
            if (focusCell) { focusCell.focus(); this._activeSpan = focusCell; }
          });
        } else if (shape._type === 'CHART') {
          // ── Chart shape — show a visible placeholder (no chart lib available)
          el.style.background = '#f0f4f8';
          el.style.border = '1px dashed #a0aec0';
          el.style.display = 'flex';
          el.style.alignItems = 'center';
          el.style.justifyContent = 'center';
          el.style.color = '#718096';
          el.style.fontSize = Math.max(Math.round(11 * scale * 12700), 8) + 'px';
          el.style.userSelect = 'none';
          el.textContent = `[图表]`;
          el.style.pointerEvents = 'none';
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

    // ── Resize shape ─────────────────────────────────────────────────────────

    _startResize(e, el, shape, canvas, scale, handleType) {
      const startX = e.clientX, startY = e.clientY;
      const startLeft = el.offsetLeft, startTop = el.offsetTop;
      const startW = el.offsetWidth, startH = el.offsetHeight;
      const pxW = canvas.offsetWidth, pxH = canvas.offsetHeight;
      const MIN_W = 30, MIN_H = 20;

      const onMove = (ev) => {
        const dx = ev.clientX - startX, dy = ev.clientY - startY;
        let newLeft = startLeft, newTop = startTop;
        let newW = startW, newH = startH;

        if (handleType.includes('e')) newW = Math.max(MIN_W, startW + dx);
        if (handleType.includes('s')) newH = Math.max(MIN_H, startH + dy);
        if (handleType.includes('w')) {
          newW = Math.max(MIN_W, startW - dx);
          newLeft = startLeft + startW - newW;
        }
        if (handleType.includes('n')) {
          newH = Math.max(MIN_H, startH - dy);
          newTop = startTop + startH - newH;
        }
        // Clamp to canvas bounds
        newLeft = Math.max(0, Math.min(pxW - MIN_W, newLeft));
        newTop  = Math.max(0, Math.min(pxH - MIN_H, newTop));

        el.style.left   = newLeft + 'px';
        el.style.top    = newTop  + 'px';
        el.style.width  = newW    + 'px';
        el.style.height = newH    + 'px';
      };

      const onUp = () => {
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
        // Write back to data model in EMU
        shape.left   = Math.round(parseInt(el.style.left)   / scale);
        shape.top    = Math.round(parseInt(el.style.top)    / scale);
        shape.width  = Math.round(parseInt(el.style.width)  / scale);
        shape.height = Math.round(parseInt(el.style.height) / scale);
        this._redrawThumb(this._curIdx);
        WA.scheduleAutoSave();
      };

      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
    }

    // ── Drag to move ─────────────────────────────────────────────────────────

    _startMove(e, el, shape, canvas, scale, enterEditOnClick = false, allowDrag = true) {
      // preventDefault/stopPropagation only happen once movement exceeds threshold.
      e.stopPropagation();

      const startX = e.clientX, startY = e.clientY;
      const origLeft = el.offsetLeft, origTop = el.offsetTop;
      const pxW = canvas.offsetWidth, pxH = canvas.offsetHeight;
      let moved = false;

      const onMove = (ev) => {
        const dx = ev.clientX - startX, dy = ev.clientY - startY;
        if (Math.abs(dx) < 4 && Math.abs(dy) < 4) return;
        if (!allowDrag) return;  // interior text click — don't drag shape
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
      const _inner = el.querySelector('.wa-pptx-inner');
      if (_inner) {
        _inner.contentEditable = 'true';
        _inner.querySelectorAll('.wa-pptx-run').forEach(s => s.removeAttribute('contenteditable'));
      } else {
        el.querySelectorAll('.wa-pptx-run').forEach(s => { s.contentEditable = 'true'; });
      }

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
      // Add 8 resize handles (CSS positions them at corners + edge midpoints)
      const _canvas = $('wa-pptx-slide-canvas');
      ['nw','n','ne','e','se','s','sw','w'].forEach(hType => {
        const hEl = document.createElement('div');
        hEl.className = 'wa-pptx-handle';
        hEl.dataset.h = hType;
        hEl.addEventListener('mousedown', e => {
          e.stopPropagation();
          e.preventDefault();
          this._startResize(e, el, shape, _canvas, this._scale || 1, hType);
        });
        el.appendChild(hEl);
      });
      // Store table data so the mouseup handler can expose it to AI quick-actions
      if (shape && shape._type === 'TABLE' && shape.cells) {
        this._lastTableText = _extractPptxTableText(shape);
        this._lastTableRows = shape.table_rows || 0;
        this._lastTableCols = shape.table_cols || 0;
      } else {
        this._lastTableText = null;
        this._lastTableRows = 0;
        this._lastTableCols = 0;
      }
    }

    _clearSelection() {
      if (this._selShape) {
        this._selShape.classList.remove('wa-pptx-selected');
        // Remove resize handles
        this._selShape.querySelectorAll('.wa-pptx-handle').forEach(h => h.remove());
        this._selShape.style.overflow = 'hidden';
        const _inner = this._selShape.querySelector('.wa-pptx-inner');
        if (_inner) {
          _inner.contentEditable = 'false';
          _inner.querySelectorAll('.wa-pptx-run').forEach(s => { s.contentEditable = 'false'; });
        } else {
          this._selShape.querySelectorAll('.wa-pptx-run').forEach(s => { s.contentEditable = 'false'; });
        }
        this._selShape.querySelectorAll('.wa-pptx-cell').forEach(td => { td.contentEditable = 'false'; td.blur(); });
        this._selShape = null;
      }
      this._editMode = false;
      this._lastTableText = null;
      this._lastTableRows = 0;
      this._lastTableCols = 0;
    }

    _enterEditMode(el) {
      if (this._editMode && this._selShape === el) return;  // already editing this shape
      this._editMode = true;
      el.classList.add('wa-pptx-editing');
      // Make inner container the single contentEditable region so cross-run/line selection works
      const _inner = el.querySelector('.wa-pptx-inner');
      if (_inner) {
        _inner.contentEditable = 'true';
        _inner.querySelectorAll('.wa-pptx-run').forEach(s => s.removeAttribute('contenteditable'));
      } else {
        el.querySelectorAll('.wa-pptx-run').forEach(s => { s.contentEditable = 'true'; });
      }
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
        const _inner = this._selShape.querySelector('.wa-pptx-inner');
        if (_inner) {
          _inner.contentEditable = 'false';
          _inner.querySelectorAll('.wa-pptx-run').forEach(s => { s.contentEditable = 'false'; s.blur(); });
        } else {
          this._selShape.querySelectorAll('.wa-pptx-run').forEach(s => { s.contentEditable = 'false'; s.blur(); });
        }
        this._selShape.querySelectorAll('.wa-pptx-cell').forEach(td => {
          td.contentEditable = 'false';
          td.blur();
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
      this._scale = 1.0;  // user zoom multiplier (1.0 = auto-fit)
      this._pdfDoc = null;
      this._pdfUrl = null;
      $(this.containerId).classList.add('active');
      $(this.containerId).addEventListener('mouseup', this.handleMouseUp.bind(this));
      document.addEventListener('mousedown', this.hideTooltip);

      // Ctrl+Wheel zoom
      this._wheelHandler = (e) => {
        if (!e.ctrlKey && !e.metaKey) return;
        e.preventDefault();
        const delta = e.deltaY > 0 ? -0.1 : 0.1;
        const newScale = Math.max(0.5, Math.min(3.0, this._scale + delta));
        this.setZoom(Math.round(newScale * 100));
      };
      $(this.containerId).addEventListener('wheel', this._wheelHandler, { passive: false });
    }

    async render(pdfUrl, pagesData) {
      this._pdfUrl = pdfUrl;
      this.pdfUrl = pdfUrl;
      this._scale = 1.0;
      await this._doRender();
      _updatePdfZoomUI(100);
    }

    async _doRender() {
      const pdfUrl = this._pdfUrl;
      const c = $(this.containerId);
      c.innerHTML = '';

      // Render PDF using PDF.js
      if (typeof pdfjsLib === 'undefined') {
         c.innerHTML = '<div style="color:var(--danger)">PDF.js 加载失败</div>';
         return;
      }

      try {
         if (!this._pdfDoc || this._pdfDoc._url !== pdfUrl) {
           const loadingTask = pdfjsLib.getDocument(pdfUrl);
           this._pdfDoc = await loadingTask.promise;
           this._pdfDoc._url = pdfUrl;
         }
         const pdf = this._pdfDoc;

         const dpr = window.devicePixelRatio || 1;
         // Always render at 2× minimum for crisp text on all displays
         const quality = Math.max(2, dpr);
         const containerW = (c.clientWidth || 800) - 32;
         for (let i = 1; i <= pdf.numPages; i++) {
            const page = await pdf.getPage(i);
            const baseViewport = page.getViewport({ scale: 1 });
            // fitScale: page → container CSS pixels (no artificial floor; allows shrink-to-fit)
            const fitScale = (containerW / baseViewport.width) * this._scale;
            // High-quality off-screen viewport (quality× physical resolution)
            const renderViewport = page.getViewport({ scale: fitScale * quality });

            const wrap = document.createElement('div');
            wrap.className = 'wa-pdf-page-wrap';
            wrap.id = `pdf-page-${i}`;

            const canvas = document.createElement('canvas');
            const context = canvas.getContext('2d');
            // Physical canvas = full quality resolution
            canvas.width  = Math.floor(renderViewport.width);
            canvas.height = Math.floor(renderViewport.height);
            // CSS display size = exactly fitScale (no CSS max-width distortion)
            canvas.style.width  = Math.floor(baseViewport.width  * fitScale) + 'px';
            canvas.style.height = Math.floor(baseViewport.height * fitScale) + 'px';

            wrap.appendChild(canvas);
            c.appendChild(wrap);

            await page.render({ canvasContext: context, viewport: renderViewport }).promise;
         }
      } catch (e) {
         c.innerHTML = `<div style="color:var(--danger)">PDF 渲染报错: ${e.message}</div>`;
      }
    }

    setZoom(pct) {
      this._scale = Math.max(50, Math.min(300, pct)) / 100;
      _updatePdfZoomUI(Math.round(this._scale * 100));
      this._doRender();
    }

    handleMouseUp(e) {
      const sel = window.getSelection().toString().trim();
      if (sel) {
         _positionSelectionToolbar(e);
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
      $(this.containerId).removeEventListener('wheel', this._wheelHandler);
      document.removeEventListener('mousedown', this.hideTooltip);
    }
  }

  // ── Plain Text / Code editor ─────────────────────────────────────────────
  class KotoTextEditor {
    constructor(fileType) {
      this._fileType = fileType; // 'text' | 'code'
      this._ta = $('wa-text-content');
      this._badge = $('wa-text-lang-badge');
      $('wa-text-editor').classList.add('active');
      this._ta.addEventListener('input', () => WA.scheduleAutoSave());
    }

    render(data) {
      const content = (data && typeof data === 'object') ? (data.content || '') : (data || '');
      const lang    = (data && typeof data === 'object') ? (data.language || '') : '';
      this._ta.value = content;
      if (this._badge) {
        this._badge.textContent = lang ? lang.toUpperCase() : 'TXT';
        this._badge.style.display = lang ? 'block' : 'none';
      }
      this._ta.focus();
    }

    getContent() { return this._ta.value; }

    serialize() { return this._ta.value; }

    applyToolCall(cmd) {
      if (cmd.type === 'set_html' || cmd.type === 'set_text') {
        this._ta.value = cmd.value || '';
        WA.scheduleAutoSave();
      }
    }

    destroy() {
      $('wa-text-editor').classList.remove('active');
      if (this._badge) { this._badge.textContent = ''; this._badge.style.display = 'none'; }
    }
  }

  // Update the PDF zoom label and slider in the status bar
  function _updatePdfZoomUI(pct) {
    const label = $('wa-pdf-zoom-label');
    const slider = $('wa-pdf-zoom');
    if (label) label.textContent = pct + '%';
    if (slider) slider.value = pct;
  }

  // Update the DOCX zoom label and slider in the status bar
  function _updateDocxZoomUI(pct) {
    const label = $('wa-docx-zoom-label');
    const slider = $('wa-docx-zoom');
    if (label) label.textContent = pct + '%';
    if (slider) slider.value = pct;
  }

  // ── Lazy CDN loader for editing libraries (needed in embedded mode) ──────
  // In standalone /workspace-assistant the HTML already loads these from CDN.
  // In embedded mode (inside index.html) they are absent and must be injected.
  const _libsLoaded = { wang: false, sheets: false, pdfjs: false };

  // Ensure all IWorkbookData required fields are present before passing to Univer.
  // Univer silently fails to render when `appVersion` or `locale` is missing.
  function _ensureWorkbookDefaults(wb) {
    if (!wb || typeof wb !== 'object') return wb;
    return Object.assign({ appVersion: '0.5.0', locale: 'zh-CN', styles: {}, resources: [] }, wb);
  }

  function _injectCSS(href) {
    if (document.querySelector(`link[href="${href}"]`)) return;
    const l = document.createElement('link');
    l.rel = 'stylesheet';
    l.href = href;
    document.head.appendChild(l);
  }

  function _loadScript(src, timeout) {
    timeout = timeout || 20000;
    return new Promise((resolve, reject) => {
      if (document.querySelector(`script[src="${src}"]`)) { resolve(); return; }
      const s = document.createElement('script');
      s.src = src;
      const timer = setTimeout(() => {
        s.onload = s.onerror = null;
        reject(new Error(`CDN 加载超时(${src.split('/').pop()})`));
      }, timeout);
      s.onload = () => { clearTimeout(timer); resolve(); };
      s.onerror = () => { clearTimeout(timer); reject(new Error(`CDN 加载失败(${src.split('/').pop()})`)); };
      document.head.appendChild(s);
    });
  }

  async function _ensureWangEditor() {
    if (window.wangEditor || _libsLoaded.wang) return;
    _injectCSS('https://cdn.jsdelivr.net/npm/@wangeditor/editor@latest/dist/css/style.css');
    await _loadScript('https://cdn.jsdelivr.net/npm/@wangeditor/editor@latest/dist/index.js');
    _libsLoaded.wang = true;
  }

  async function _ensureUniverSheets() {
    if (_libsLoaded.sheets) return;
    _injectCSS('/editor/assets/sheets-main.css');
    // sheets-main.js is an ESM module; must load with type="module"
    await new Promise((resolve, reject) => {
      const src = '/editor/assets/sheets-main.js';
      if (document.querySelector(`script[src="${src}"]`)) {
        // Script tag already exists but module may still be initializing — poll for KotoSheetsAPI
        const deadline = Date.now() + 5000;
        const poll = () => {
          if (window.KotoSheetsAPI) { resolve(); return; }
          if (Date.now() > deadline) { reject(new Error('Univer Sheets 初始化超时')); return; }
          setTimeout(poll, 50);
        };
        poll();
        return;
      }
      const s = document.createElement('script');
      s.type = 'module';
      s.src = src;
      const timer = setTimeout(() => {
        s.onload = s.onerror = null;
        reject(new Error('Univer Sheets 加载超时'));
      }, 30000);
      s.onload = () => {
        clearTimeout(timer);
        // ESM onload fires when the script executes, but KotoSheetsAPI may not be set yet — poll
        const deadline = Date.now() + 5000;
        const poll = () => {
          if (window.KotoSheetsAPI) { resolve(); return; }
          if (Date.now() > deadline) { reject(new Error('Univer Sheets 初始化超时')); return; }
          setTimeout(poll, 50);
        };
        poll();
      };
      s.onerror = () => { clearTimeout(timer); reject(new Error('Univer Sheets 加载失败')); };
      document.head.appendChild(s);
    });
    _libsLoaded.sheets = true;
  }

  async function _ensurePdfJS() {
    if (window.pdfjsLib || _libsLoaded.pdfjs) return;
    await _loadScript('https://cdn.jsdelivr.net/npm/pdfjs-dist@3.11.174/build/pdf.min.js');
    if (window.pdfjsLib) {
      window.pdfjsLib.GlobalWorkerOptions.workerSrc =
        'https://cdn.jsdelivr.net/npm/pdfjs-dist@3.11.174/build/pdf.worker.min.js';
    }
    _libsLoaded.pdfjs = true;
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
         const _saBtn3 = $('wa-saveas-btn'); if (_saBtn3) _saBtn3.disabled = (state.fileType === 'pdf');
         const _archBtn3 = $('wa-archive-btn'); if (_archBtn3) _archBtn3.disabled = false;
         _updateSubjectBar(state.fileName, state.fileType);

         // Show PDF/DOCX zoom control only when the relevant file type is open
         const pdfZoomCtrl = $('wa-pdf-zoom-ctrl');
         if (pdfZoomCtrl) pdfZoomCtrl.style.display = (state.fileType === 'pdf') ? 'flex' : 'none';
         const docxZoomCtrl = $('wa-docx-zoom-ctrl');
         if (docxZoomCtrl) docxZoomCtrl.style.display = (state.fileType === 'docx') ? 'flex' : 'none';

         // Destroy old editor if it was a different file (not a tab switch)
         if (state.activeEditor) {
           try {
            state.activeEditor.destroy();
          } catch(e) {
            console.error('Editor destroy failed:', e);
            const canvas = document.getElementById('wa-canvas');
            if (canvas) canvas.innerHTML = '';
          }
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

         // Wait for the editor container to have real layout dimensions before
         // initialising dimension-sensitive editors (Univer Sheets / PPTX canvas).
         // Critical in embedded mode: #workspaceView just transitioned from
         // display:none and the browser may not have flushed CSS layout yet.
         await _waitForEditorLayout(state.fileType);

         if (state.fileType === 'docx') {
            await _ensureWangEditor();
            state.activeEditor = new KotoDocxEditor();
            state.activeEditor.render(json.data.html);
         } else if (state.fileType === 'xlsx') {
            await _ensureUniverSheets();
            state.activeEditor = new KotoXlsxEditor();
            state.activeEditor.render(_ensureWorkbookDefaults(json.data));
            // Surface formula loss warning from backend
            if (json.data && json.data._warnings && json.data._warnings.length) {
              json.data._warnings.forEach(msg => {
                showToast('⚠️ ' + msg, 'warning', 8000);
              });
            }
         } else if (state.fileType === 'pptx') {
            state.activeEditor = new KotoPptxEditor();
            state.activeEditor.render(json.data);
         } else if (state.fileType === 'pdf') {
            await _ensurePdfJS();
            state.activeEditor = new KotoPdfViewer();
            state.activeEditor.render(json.data.raw_url, json.data.pages);
         } else if (state.fileType === 'text' || state.fileType === 'code') {
            state.activeEditor = new KotoTextEditor(state.fileType);
            state.activeEditor.render(json.data);
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

  // ── Unified AI Chat Stream (backed by /api/chat/stream) ─────────────────

  /** Toggle send / stop button visibility while a stream is active. */
  function _setStreamBtn(streaming) {
    const sendBtn = $('wa-send-btn');
    const stopBtn = $('wa-stop-btn');
    if (sendBtn) sendBtn.style.display = streaming ? 'none' : '';
    if (stopBtn) stopBtn.style.display = streaming ? '' : 'none';
  }

  /** Abort the currently active AI stream (if any). */
  window.WA.stopStream = () => {
    if (state._streamAbortCtrl) state._streamAbortCtrl.abort();
  };

  function _waSession() {
    return 'workspace_' + (state.fileId || 'default');
  }

  /**
   * Stream a message through /api/chat/stream (same endpoint as main Koto chat).
   * Handles token/progress/done/error events and extracts TOOL calls + proposals.
   * @param {string}  message   Full message body (includes document context prefix)
   * @param {Element} loadingEl  The streaming bubble element already in the DOM
   * @param {Object}  opts       { task?, model? }
   */
  async function _waSendToChat(message, loadingEl, opts) {
    opts = opts || {};
    const msgs = $('wa-ai-messages');
    let fullText = '';
    let streamBuffer = '';
    const renderMd = (text) => {
      if (window.marked) { try { return window.marked.parse(text || ''); } catch(e) {} }
      return (text || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\n/g,'<br>');
    };
    const payload = {
      session:     _waSession(),
      message:     message,
      locked_task: opts.task || 'CHAT',
      locked_model: opts.model || state.lockedModel || 'auto',
      // Document-edit context — instructs backend to use proposals system prompt
      doc_edit:    opts.doc_edit  || false,
      doc_file_type: opts.file_type || '',
      doc_has_sel: opts.has_sel   || false,
    };
    try {
      const ctrl = new AbortController();
      state._streamAbortCtrl = ctrl;
      _setStreamBtn(true);
      const resp = await fetch('/api/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        signal: ctrl.signal,
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${resp.statusText}`);
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        streamBuffer += decoder.decode(value, { stream: true });
        const lines = streamBuffer.split('\n');
        streamBuffer = lines.pop();
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          try {
            const evt = JSON.parse(line.slice(6));
            if (evt.type === 'token') {
              fullText += evt.content || '';
              const visible = fullText
                .replace(/<TOOL>[\s\S]*?<\/TOOL>/g, '')
                .replace(/\n?\{"proposals"\s*:\s*\[[\s\S]*?\]\s*\}\s*$/m, '')
                .trim();
              if (loadingEl) {
                loadingEl.innerHTML = _parseCitations(renderMd(visible)) + '<span class="typing-cursor">▊</span>';
              }
              msgs.scrollTop = msgs.scrollHeight;
            } else if (evt.type === 'progress') {
              if (!fullText && loadingEl && !loadingEl.querySelector('.wa-progress-text')) {
                loadingEl.innerHTML = `<span class="wa-progress-text">⏳ ${_escHtml(evt.message || '处理中…')}</span>`;
              }
            } else if (evt.type === 'done') {
              if (loadingEl) {
                loadingEl.classList.remove('streaming');
                const visible = fullText
                  .replace(/<TOOL>[\s\S]*?<\/TOOL>/g, '')
                  .replace(/\n?\{"proposals"\s*:\s*\[[\s\S]*?\]\s*\}\s*$/m, '')
                  .trim();
                const finalText = visible || evt.content || '';
                loadingEl.innerHTML = _parseCitations(renderMd(finalText));
                if (finalText) {
                  loadingEl.dataset.rawText = finalText;
                  state.conversation.push({ role: 'assistant', content: finalText });
                }
              }
              msgs.scrollTop = msgs.scrollHeight;
              // Extract and apply TOOL calls
              const toolMatches = [...fullText.matchAll(/<TOOL>([\s\S]*?)<\/TOOL>/g)];
              toolMatches.forEach(m => {
                try { _handleToolCall(JSON.parse(m[1].trim())); } catch(e) { /* ignore */ }
              });
              // Extract proposals JSON block
              let proposalsRendered = false;
              const propMatch = fullText.match(/\{"proposals"\s*:\s*\[[\s\S]*?\]\s*\}/);
              if (propMatch) {
                try {
                  const propData = JSON.parse(propMatch[0]);
                  if (Array.isArray(propData.proposals) && propData.proposals.length) {
                    _handleProposals(propData);
                    proposalsRendered = true;
                  }
                } catch(e) { /* ignore */ }
              }
              // Show AI action bar only for write-intent replies. Translation and
              // other read-only requests should stay in preview mode.
              const _canApply = !proposalsRendered && opts.allow_apply !== false && loadingEl && loadingEl.dataset.rawText && state.activeEditor;
              if (_canApply) {
                // Snapshot state at response-complete time so buttons remain
                // correct even if the user sends another message before clicking.
                const _barSnap = {
                  pinnedSel:  state.lastPinnedSel,
                  toolCall:   state.pendingToolCall,
                  outputMode: state.aiOutputMode,
                  allowWrite: true,
                };
                msgs.appendChild(_makeAIActionBar(_barSnap));
                // Scroll to show the action bar — it was appended AFTER the
                // earlier scrollTop call so without this it renders off-screen.
                requestAnimationFrame(() => { msgs.scrollTop = msgs.scrollHeight; });
              }
              state.isLoading = false;
              return;
            } else if (evt.type === 'error') {
              if (loadingEl) {
                loadingEl.classList.remove('streaming');
                loadingEl.innerHTML = `<span style="color:var(--error,#ef4444)">❌ ${_escHtml(evt.message || 'AI 处理失败')}</span>`;
              }
              state.isLoading = false;
              return;
            }
            // agent_step, agent_thought etc. — silently ignore in workspace mode
          } catch(e) { /* ignore malformed SSE line */ }
        }
      }
      // Stream ended without 'done' — finalize gracefully
      if (loadingEl && loadingEl.classList.contains('streaming')) {
        loadingEl.classList.remove('streaming');
        const visible = fullText.replace(/<TOOL>[\s\S]*?<\/TOOL>/g, '').trim();
        if (visible) {
          loadingEl.innerHTML = renderMd(visible);
          state.conversation.push({ role: 'assistant', content: visible });
        }
      }
      state.isLoading = false;
    } catch (err) {
      if (err.name === 'AbortError') {
        // User cancelled — finalize the streaming bubble gracefully
        if (loadingEl) {
          loadingEl.classList.remove('streaming');
          if (!loadingEl.textContent.trim()) loadingEl.textContent = '[已取消]';
          else loadingEl.innerHTML += '<span style="color:var(--muted,#888);font-size:11px"> [已取消]</span>';
        }
      } else {
        console.error('[WorkspaceAI] Chat stream error:', err);
        if (loadingEl) {
          loadingEl.classList.remove('streaming');
          loadingEl.textContent = `❌ 网络错误：${err.message}`;
        }
      }
      state.isLoading = false;
    } finally {
      state._streamAbortCtrl = null;
      _setStreamBtn(false);
    }
  }

  function _handleProposals(data) {
     const msgs = $('wa-ai-messages');
     const proposals = data.proposals || [];
     if (!proposals.length) return;
     state._activeProposals = proposals;
     if (proposals.length > 1) msgs.appendChild(_makeProposalBatchBar(proposals));
     proposals.forEach((p, i) => msgs.appendChild(_makeProposalCard(p, i, proposals.length)));
     // Use rAF so the browser finishes laying out the (potentially tall) proposal
     // cards before we measure scrollHeight — otherwise scrollHeight is stale and
     // the viewport lands in the middle of the content instead of the bottom.
     requestAnimationFrame(() => { msgs.scrollTop = msgs.scrollHeight; });
  }

  function _handleToolCall(cmd) {
     const msgs = $('wa-ai-messages');
     if (state.aiOutputMode === 'inline') {
        // ALWAYS store as pending — never auto-apply. User confirms via action bar.
        state.pendingToolCall = cmd;
     } else {
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
  }

  function _makeWAChartImageWrap(imgSrc, fileName) {
     const imgWrap = document.createElement('div');
     imgWrap.className = 'wa-msg ai wa-chart-img-wrap';
     const img = document.createElement('img');
     img.className = 'wa-chart-img wa-chart-img-draggable';
     img.src = imgSrc;
     img.alt = fileName || 'chart.png';
     img.draggable = true;
     img.title = '拖动到左侧文档即可插入';
     img.addEventListener('dragstart', (e) => {
        e.dataTransfer.effectAllowed = 'copy';
        e.dataTransfer.setData('application/wa-chart-image', imgSrc);
        e.dataTransfer.setData('application/wa-chart-name', fileName || 'chart.png');
        _draggingChartSrc = imgSrc;
        _draggingChartName = fileName || 'chart.png';
        const overlay = $('wa-ai-img-drop-hint');
        if (overlay) overlay.classList.add('active');
     });
     img.addEventListener('dragend', () => {
        _draggingChartSrc = null;
        _draggingChartName = null;
        const overlay = $('wa-ai-img-drop-hint');
        if (overlay) overlay.classList.remove('active');
     });
     imgWrap.appendChild(img);
     const hint = document.createElement('div');
     hint.className = 'wa-chart-drag-hint';
     hint.textContent = '· 拖入文档 ·';
     imgWrap.appendChild(hint);
     const bar = document.createElement('div');
     bar.className = 'wa-chart-img-bar';
     const openBtn = document.createElement('button');
     openBtn.className = 'wa-action-btn secondary';
     openBtn.textContent = '🖼 查看';
     openBtn.title = '在新标签页打开（可直接右键复制）';
     openBtn.addEventListener('click', () => {
        if (imgSrc.startsWith('data:')) {
           try {
              const [head, b64] = imgSrc.split(',');
              const mimeType = head.split(':')[1].split(';')[0];
              const binary = atob(b64);
              const arr = new Uint8Array(binary.length);
              for (let i = 0; i < binary.length; i++) arr[i] = binary.charCodeAt(i);
              const blob = new Blob([arr], { type: mimeType });
              const blobUrl = URL.createObjectURL(blob);
              window.open(blobUrl, '_blank');
              setTimeout(() => URL.revokeObjectURL(blobUrl), 60000);
           } catch (_) { window.open(imgSrc, '_blank'); }
        } else {
           window.open(imgSrc, '_blank');
        }
     });
     const dlBtn = document.createElement('button');
     dlBtn.className = 'wa-action-btn';
     dlBtn.textContent = '💾 下载';
     dlBtn.addEventListener('click', () => {
        const a = document.createElement('a');
        a.href = imgSrc;
        a.download = fileName || 'chart.png';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        dlBtn.textContent = '✅ 下载中';
        setTimeout(() => { dlBtn.textContent = '💾 下载'; }, 2000);
     });
     bar.appendChild(openBtn);
     bar.appendChild(dlBtn);
     imgWrap.appendChild(bar);
     return imgWrap;
  }

  function _makeAIImgDraggable(img, imgSrc) {
     img.draggable = true;
     img.style.cursor = 'grab';
     img.addEventListener('dragstart', (e) => {
        e.dataTransfer.effectAllowed = 'copy';
        e.dataTransfer.setData('application/wa-chart-image', imgSrc);
        e.dataTransfer.setData('application/wa-chart-name', img.alt || 'image.png');
        _draggingChartSrc = imgSrc;
        _draggingChartName = img.alt || 'image.png';
        const overlay = $('wa-ai-img-drop-hint');
        if (overlay) overlay.classList.add('active');
     });
     img.addEventListener('dragend', () => {
        _draggingChartSrc = null;
        _draggingChartName = null;
        const overlay = $('wa-ai-img-drop-hint');
        if (overlay) overlay.classList.remove('active');
     });
  }

  function _handleCodeResult(result) {
     const msgs = $('wa-ai-messages');
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
     const files = result.files || {};
     const fileNames = Object.keys(files);
     if (fileNames.length > 0) {
        fileNames.forEach(fname => {
           msgs.appendChild(_makeWAChartImageWrap(files[fname], fname));
        });
     } else if (!result.error) {
        const okDiv = document.createElement('div');
        okDiv.className = 'wa-msg ai';
        okDiv.textContent = '✅ 代码执行完成，但未生成图片文件。请确保代码中有 plt.savefig("chart.png") 或 ggsave("chart.png")。';
        msgs.appendChild(okDiv);
     }
     msgs.scrollTop = msgs.scrollHeight;
  }

  // ── Chart / code execution SSE (backed by /api/editor/ai/chart) ──
  async function _sendViaSSEChart(payload) {
    let buffer = '';
    // Map old payload fields to new endpoint schema
    const body = {
      data_context: payload.csv_data || payload.prompt || '',
      instruction: payload.prompt || '',
      lang: payload.language || 'python',
    };
    try {
      const resp = await fetch('/api/editor/ai/chart', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${resp.statusText}`);
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop();
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          try {
            const evt = JSON.parse(line.slice(6));
            const msgs = $('wa-ai-messages');
            switch (evt.type) {
              case 'status':
              case 'info': {
                let last = msgs.lastElementChild;
                if (!last || !last.classList.contains('streaming')) {
                  last = document.createElement('div');
                  last.className = 'wa-msg ai streaming';
                  msgs.appendChild(last);
                }
                last.textContent = evt.text || '';
                msgs.scrollTop = msgs.scrollHeight;
                break;
              }
              case 'code': {
                const last = msgs.lastElementChild;
                if (last && last.classList.contains('streaming')) last.classList.remove('streaming');
                const codeEl = document.createElement('div');
                codeEl.className = 'wa-msg ai';
                codeEl.innerHTML = `<details><summary>📄 生成的代码</summary><pre style="white-space:pre-wrap;font-size:12px">${evt.text.replace(/</g,'&lt;').replace(/>/g,'&gt;')}</pre></details>`;
                msgs.appendChild(codeEl);
                msgs.scrollTop = msgs.scrollHeight;
                break;
              }
              case 'image': {
                const imgEl = document.createElement('div');
                imgEl.className = 'wa-msg ai';
                imgEl.innerHTML = `<img src="data:image/png;base64,${evt.data}" style="max-width:100%;border-radius:6px" alt="${evt.name||'chart'}">`;
                msgs.appendChild(imgEl);
                msgs.scrollTop = msgs.scrollHeight;
                break;
              }
              case 'stdout':
              case 'stderr': {
                if (evt.text && evt.text.trim()) {
                  const outEl = document.createElement('div');
                  outEl.className = 'wa-msg ai';
                  outEl.innerHTML = `<pre style="white-space:pre-wrap;font-size:11px;color:${evt.type==='stderr'?'#e57373':'#888'}">${evt.text.replace(/</g,'&lt;')}</pre>`;
                  msgs.appendChild(outEl);
                  msgs.scrollTop = msgs.scrollHeight;
                }
                break;
              }
              case 'done': {
                const last = msgs.lastElementChild;
                if (last && last.classList.contains('streaming')) last.classList.remove('streaming');
                state.isLoading = false;
                break;
              }
              case 'error': {
                const last = msgs.lastElementChild;
                if (last && last.classList.contains('streaming')) last.classList.remove('streaming');
                const errEl = document.createElement('div');
                errEl.className = 'wa-msg ai';
                errEl.textContent = evt.text || evt.message || '❌ 图表生成失败';
                msgs.appendChild(errEl);
                msgs.scrollTop = msgs.scrollHeight;
                state.isLoading = false;
                break;
              }
            }
          } catch(e) { /* ignore malformed SSE line */ }
        }
      }
    } catch (err) {
      console.error('[WorkspaceAI] Chart exec error:', err);
      const msgs = $('wa-ai-messages');
      const last = msgs.lastElementChild;
      if (last && last.classList.contains('streaming')) last.classList.remove('streaming');
      const errEl = document.createElement('div');
      errEl.className = 'wa-msg ai';
      errEl.textContent = `❌ 网络错误：${err.message}`;
      msgs.appendChild(errEl);
      msgs.scrollTop = msgs.scrollHeight;
      state.isLoading = false;
    }
  }

  // ── AI init ───────────────────────────────────────────────────────────────
  function initSocket() {
    const badge = $('wa-ai-model-badge');
    if (state.lockedModel === 'local') {
      if (badge) badge.textContent = 'Ollama ●';
    } else {
      if (badge) badge.textContent = 'Koto AI ●';
      const sel = document.getElementById('wa-model-select');
      if (sel) sel.value = state.lockedModel || 'auto';
      if (state.lockedModel && state.lockedModel !== 'auto') WA.setLockedModel(state.lockedModel);
    }
    // Restore local model toggle button active state
    const isLocal = state.lockedModel === 'local';
    document.querySelectorAll('[data-local-mode]').forEach(btn => {
      btn.classList.toggle('active', (btn.dataset.localMode === 'on') === isLocal);
    });
    // Restore output mode toggle button active state
    document.querySelectorAll('.wa-output-mode-toggle button[data-mode]').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.mode === state.aiOutputMode);
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
      // Clear server-side session so AI won't recall previous turns after user clears chat
      fetch(`/api/sessions/${encodeURIComponent(_waSession())}`, { method: 'DELETE' }).catch(() => {});
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

  window.WA.pdfZoom = (val) => {
     if (state.activeEditor && state.activeEditor.setZoom)
       state.activeEditor.setZoom(parseInt(val));
  };

  window.WA.docxZoom = (val) => {
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
       _sendViaSSEChart({
          prompt: desc,
          file_type: state.fileType || 'xlsx',
          file_id: state.fileId || '',
          language: _chartLang,
          csv_data: csvData,
       });
     }

     doChartSend();
  };

  // Close dialog on backdrop click
  $('wa-chart-dialog').addEventListener('click', (e) => {
     if (e.target === $('wa-chart-dialog')) WA.closeChartDialog();
  });

  // ── Proposal Diff Card System ──────────────────────────────────────────────

  /** Simple word-level diff for inline display */
  function _computeInlineDiff(original, proposed) {
    // Strip HTML tags for comparison
    const stripHtml = (s) => s.replace(/<[^>]+>/g, '').trim();
    const origText = stripHtml(original);
    const propText = stripHtml(proposed);
    if (origText === propText) return '<span class="wa-diff-same">' + _escHtml(propText) + '</span>';

    // Simple sentence-level diff
    const origSents = origText.split(/([。！？.!?\n]+)/).filter(Boolean);
    const propSents = propText.split(/([。！？.!?\n]+)/).filter(Boolean);

    // If short enough, show full before/after
    if (origText.length < 500 && propText.length < 500) {
      return '<div class="wa-diff-block del"><span class="wa-diff-label">原文</span>' + _escHtml(origText) + '</div>' +
             '<div class="wa-diff-block add"><span class="wa-diff-label">修改</span>' + _escHtml(propText) + '</div>';
    }

    // For longer texts, show truncated
    const truncOrig = origText.length > 300 ? origText.substring(0, 300) + '…' : origText;
    const truncProp = propText.length > 300 ? propText.substring(0, 300) + '…' : propText;
    return '<div class="wa-diff-block del"><span class="wa-diff-label">原文</span>' + _escHtml(truncOrig) + '</div>' +
           '<div class="wa-diff-block add"><span class="wa-diff-label">修改</span>' + _escHtml(truncProp) + '</div>';
  }

  function _escHtml(s) {
    return (s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  function _proposalCanApply(proposal) {
    if (!proposal) return false;
    if (proposal.read_only || proposal.apply_disabled) return false;
    const rationale = (proposal.rationale || '').replace(/<[^>]+>/g, '').trim();
    const actionType = String(proposal.action || proposal.action_type || '').trim();
    if (/翻译/.test(rationale) || /translate/i.test(actionType)) return false;
    return !!(proposal.tool_call || (proposal.original_text && proposal.proposed_text));
  }

  function _makeProposalCard(proposal, index, total) {
    const card = document.createElement('div');
    card.className = 'wa-proposal-card';
    card.dataset.proposalId = proposal.id;
    card.dataset.index = index;
    const canApply = _proposalCanApply(proposal);
    card.dataset.canApply = canApply ? '1' : '0';

    const header = document.createElement('div');
    header.className = 'wa-proposal-header';
    header.innerHTML = `<span class="wa-proposal-badge">修改建议 ${index + 1}${total > 1 ? '/' + total : ''}</span>`;

    const diffView = document.createElement('div');
    diffView.className = 'wa-proposal-diff';
    diffView.innerHTML = _computeInlineDiff(proposal.original_text, proposal.proposed_text);

    // Rationale (AI explanation), truncated
    const rationale = document.createElement('div');
    rationale.className = 'wa-proposal-rationale';
    const rText = (proposal.rationale || '').replace(/<[^>]+>/g, '').trim();
    if (rText && rText.length > 5) {
      rationale.innerHTML = '💡 ' + _escHtml(rText.length > 150 ? rText.substring(0, 150) + '…' : rText);
    }

    const actions = document.createElement('div');
    actions.className = 'wa-proposal-actions';
    actions.innerHTML = canApply
      ? `<button class="wa-proposal-btn accept" onclick="WA.acceptProposal('${proposal.id}',this)">✅ 接受</button>` +
        `<button class="wa-proposal-btn reject" onclick="WA.rejectProposal('${proposal.id}',this)">❌ 拒绝</button>` +
        `<button class="wa-proposal-btn modify" onclick="WA.modifyProposal('${proposal.id}',this)">✏️ 再修改</button>`
      : `<button class="wa-proposal-btn reject" onclick="WA.rejectProposal('${proposal.id}',this)">关闭</button>`;

    card.appendChild(header);
    card.appendChild(diffView);
    if (rText && rText.length > 5) card.appendChild(rationale);
    card.appendChild(actions);
    return card;
  }

  function _makeProposalBatchBar(proposals) {
    const bar = document.createElement('div');
    bar.className = 'wa-proposal-batch-bar';
    const actionableCount = proposals.filter(_proposalCanApply).length;
    const tIdx = state._aiTargetFileIdx;
    const targetFile = (tIdx >= 0 && tIdx < state._aiFileContext.length) ? state._aiFileContext[tIdx] : null;
    const canDownload = actionableCount > 0 && targetFile && /\.(docx|txt|md)$/i.test(targetFile.name);
    const downloadBtn = canDownload
      ? `<button class="wa-proposal-btn download small" onclick="WA.downloadPatchedFile()" title="将全部修改应用到目标文件并下载">⬇ 应用并下载 ${_escHtml(targetFile.name)}</button>`
      : '';
    bar.innerHTML =
      `<span class="wa-proposal-batch-label">共 ${proposals.length} 条修改建议</span>` +
      '<span class="wa-proposal-batch-counter" id="wa-proposal-counter">0/' + actionableCount + ' 已处理</span>' +
      (actionableCount > 0 ? '<button class="wa-proposal-btn accept small" onclick="WA.batchAcceptAll()">全部接受</button>' : '') +
      '<button class="wa-proposal-btn reject small" onclick="WA.batchRejectAll()">全部拒绝</button>' +
      downloadBtn;
    return bar;
  }

  function _updateProposalCounter() {
    const counter = document.getElementById('wa-proposal-counter');
    if (!counter) return;
    const all = document.querySelectorAll('.wa-proposal-card[data-can-apply="1"]');
    const done = document.querySelectorAll('.wa-proposal-card[data-can-apply="1"].accepted, .wa-proposal-card[data-can-apply="1"].rejected');
    counter.textContent = `${done.length}/${all.length} 已处理`;
  }

  window.WA.acceptProposal = (proposalId, btn) => {
    const card = btn.closest('.wa-proposal-card');
    if (!card || card.classList.contains('accepted') || card.classList.contains('rejected')) return;
    const proposals = state._activeProposals || [];
    const proposal = proposals.find(p => p.id === proposalId);
    if (!proposal) return;
    if (!_proposalCanApply(proposal)) {
      showToast('该结果仅供查看，不支持直接写入文档', 'info');
      return;
    }

    if (state.activeEditor) {
      try {
        if (proposal.tool_call) {
          // Server-provided tool call (e.g. from socket_handler agent_proposals)
          state.activeEditor.applyToolCall(proposal.tool_call);
        } else if (proposal.original_text && proposal.proposed_text) {
          // Proposals built on the frontend (quick actions: translate / rewrite / etc.)
          // have no tool_call — synthesise a replace_text command.
          const proposedPlain = (proposal.proposed_text || '').replace(/<[^>]+>/g, '').trim();
          state.activeEditor.applyToolCall({
            type: 'replace_text',
            original: proposal.original_text,
            value: proposedPlain || proposal.proposed_text,
          });
        }
      } catch(e) {
        console.warn('acceptProposal applyToolCall failed:', e);
      }
    }

    card.classList.add('accepted');
    showToast('已接受修改', 'success');
    WA.scheduleAutoSave();
    _updateProposalCounter();
  };

  window.WA.rejectProposal = (proposalId, btn) => {
    const card = btn.closest('.wa-proposal-card');
    if (!card || card.classList.contains('accepted') || card.classList.contains('rejected')) return;
    card.classList.add('rejected');
    showToast('已拒绝修改', 'info');
    _updateProposalCounter();
  };

  window.WA.modifyProposal = (proposalId, btn) => {
    const card = btn.closest('.wa-proposal-card');
    if (!card) return;
    // Check if input already open
    if (card.querySelector('.wa-proposal-modify-input')) return;

    const proposals = state._activeProposals || [];
    const proposal = proposals.find(p => p.id === proposalId);
    if (!proposal) return;
    if (!_proposalCanApply(proposal)) {
      showToast('该结果仅供查看，不支持继续修改并写回文档', 'info');
      return;
    }

    const inputWrap = document.createElement('div');
    inputWrap.className = 'wa-proposal-modify-input';
    inputWrap.innerHTML =
      '<textarea class="wa-proposal-modify-textarea" placeholder="输入修改意见，如：语气再正式一些…" rows="2"></textarea>' +
      '<div class="wa-proposal-modify-actions">' +
      `<button class="wa-proposal-btn accept small" onclick="WA._submitModify('${proposalId}',this)">发送</button>` +
      '<button class="wa-proposal-btn reject small" onclick="this.closest(\'.wa-proposal-modify-input\').remove()">取消</button>' +
      '</div>';
    card.appendChild(inputWrap);
    inputWrap.querySelector('textarea').focus();
  };

  window.WA._submitModify = (proposalId, btn) => {
    const card = btn.closest('.wa-proposal-card');
    const textarea = card.querySelector('.wa-proposal-modify-textarea');
    const feedback = textarea ? textarea.value.trim() : '';
    if (!feedback) return;

    const proposals = state._activeProposals || [];
    const proposal = proposals.find(p => p.id === proposalId);
    if (!proposal) return;

    // Remove input
    const inputWrap = card.querySelector('.wa-proposal-modify-input');
    if (inputWrap) inputWrap.remove();
    card.classList.add('rejected');
    _updateProposalCounter();

    // Send a new message with context from this proposal
    const input = $('wa-user-input');
    const modifyPrompt = `请重新修改以下内容。\n原文：「${proposal.original_text.substring(0, 200)}」\n上次修改为：「${(proposal.proposed_text || '').replace(/<[^>]+>/g, '').substring(0, 200)}」\n用户反馈：${feedback}`;
    input.value = modifyPrompt;

    // Re-pin the original selection so the next response also gets proposal cards
    state.pinnedSelection = proposal.original_text;
    WA.sendMessage();
  };

  window.WA.batchAcceptAll = () => {
    document.querySelectorAll('.wa-proposal-card:not(.accepted):not(.rejected)').forEach(card => {
      const btn = card.querySelector('.wa-proposal-btn.accept');
      if (btn) btn.click();
    });
  };

  window.WA.batchRejectAll = () => {
    document.querySelectorAll('.wa-proposal-card:not(.accepted):not(.rejected)').forEach(card => {
      const btn = card.querySelector('.wa-proposal-btn.reject');
      if (btn) btn.click();
    });
  };

  // Download a patched copy of the target file (DOCX / TXT / MD) with all accepted (or provided) proposals applied
  window.WA.downloadPatchedFile = async (specificProposals) => {
    const tIdx = state._aiTargetFileIdx;
    const targetFile = (tIdx >= 0 && tIdx < state._aiFileContext.length) ? state._aiFileContext[tIdx] : null;
    if (!targetFile) {
      showToast('请先设置目标文件（点击文件旁的📌）', 'warn');
      return;
    }
    const proposals = (specificProposals || state._activeProposals || []).filter(_proposalCanApply);
    if (!proposals.length) {
      showToast('没有可应用的修改建议', 'warn');
      return;
    }
    showToast(`正在生成修改后的文件…`, 'info');
    try {
      const res = await fetch('/api/v1/workspace/patch_file', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          path: targetFile.path,
          proposals: proposals.map(p => ({
            original_text: p.original_text,
            proposed_text: p.proposed_text,
          })),
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error || `HTTP ${res.status}`);
      }
      const blob = await res.blob();
      const cdHeader = res.headers.get('Content-Disposition') || '';
      const fnMatch = cdHeader.match(/filename\*?=(?:UTF-8'')?([^;]+)/i);
      const dlName = fnMatch ? decodeURIComponent(fnMatch[1].replace(/"/g, '')) : `修改后_${targetFile.name}`;
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = dlName;
      document.body.appendChild(a);
      a.click();
      setTimeout(() => { URL.revokeObjectURL(url); a.remove(); }, 2000);
      showToast(`已下载: ${dlName}`, 'success');
    } catch (e) {
      showToast(`下载失败: ${e.message}`, 'error');
    }
  };

  // ═══════════════════════════════════════════════════════════════════════════
  // ── NotebookLM-style features ─────────────────────────────────────────────
  // ═══════════════════════════════════════════════════════════════════════════

  // ── Cross-source keyword search ───────────────────────────────────────────
  let _sourceSearchTimer = null;
  window.WA.doSourceSearch = (query) => {
    const clearBtn = $('wa-source-clear-btn');
    if (clearBtn) clearBtn.style.display = query ? '' : 'none';
    clearTimeout(_sourceSearchTimer);
    if (!query || query.length < 2) {
      const r = $('wa-source-search-results');
      if (r) { r.innerHTML = ''; r.style.display = 'none'; }
      return;
    }
    _sourceSearchTimer = setTimeout(() => _runSourceSearch(query), 280);
  };

  function _runSourceSearch(query) {
    const results = $('wa-source-search-results');
    if (!results) return;
    const files = state._aiFileContext || [];
    const qLower = query.toLowerCase();
    const matches = [];

    files.forEach(f => {
      const content = f.content || '';
      let pos = 0;
      while (matches.length < 20) {
        const idx = content.toLowerCase().indexOf(qLower, pos);
        if (idx === -1) break;
        const start = Math.max(0, idx - 50);
        const end = Math.min(content.length, idx + query.length + 80);
        const excerpt = content.slice(start, end);
        const highlighted = excerpt.replace(
          new RegExp(_escRegex(query), 'gi'),
          m => `<mark>${_escHtml(m)}</mark>`
        );
        matches.push({ name: f.name, excerpt: highlighted, charOffset: idx, file: f });
        pos = idx + 1;
      }
    });

    if (!matches.length) {
      results.innerHTML = `<div class="wa-source-no-result">未找到"${_escHtml(query)}"相关内容</div>`;
      results.style.display = '';
      return;
    }

    results.innerHTML = matches.slice(0, 12).map((m, i) =>
      `<div class="wa-source-result-item" data-idx="${i}" onclick="WA._sourceResultClick(this)">` +
      `<span class="wa-src-result-file">${_fileIcon(m.name.split('.').pop())} ${_escHtml(m.name)}</span>` +
      `<span class="wa-src-result-text">…${m.excerpt}…</span>` +
      `</div>`
    ).join('');
    // Store hit data for click handler
    results._hitData = matches.slice(0, 12);
    results.style.display = '';
  }

  window.WA._sourceResultClick = (el) => {
    const results = $('wa-source-search-results');
    const idx = parseInt(el.dataset.idx || '0', 10);
    const hit = results && results._hitData && results._hitData[idx];
    if (!hit) return;
    const query = ($('wa-source-search-input') || {}).value || '';
    // Pre-fill the chat input with a grounded query
    const input = $('wa-user-input');
    if (input) {
      input.value = `关于"${query}"，${hit.name}中提到了什么？请引用原文并分析。`;
      input.focus();
    }
    window.WA.clearSourceSearch();
  };

  window.WA.clearSourceSearch = () => {
    const inp = $('wa-source-search-input');
    if (inp) inp.value = '';
    const r = $('wa-source-search-results');
    if (r) { r.innerHTML = ''; r.style.display = 'none'; }
    const cb = $('wa-source-clear-btn');
    if (cb) cb.style.display = 'none';
  };

  function _escRegex(s) {
    return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  }

  // ── Key Topic Extraction ──────────────────────────────────────────────────
  window.WA.extractTopics = async () => {
    if (!state._aiFileContext.length) { showToast('请先附加文件', 'warn'); return; }
    const bar = $('wa-topic-chips-bar');
    const list = $('wa-topic-chips-list');
    if (!bar || !list) return;
    list.innerHTML = '<span class="wa-spinner-sm"></span> 提炼中…';
    bar.style.display = 'flex';

    const combined = state._aiFileContext.map(f =>
      `=== ${f.name} ===\n${(f.content || '').slice(0, 8000)}`
    ).join('\n\n');

    // Use the chat endpoint for topic extraction
    const prompt = `请从以下资料中提炼6-10个核心主题或关键概念，仅用JSON数组回复，格式:["主题1","主题2",...]\n\n${combined}`;
    try {
      const res = await fetch('/api/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session: _waSession(),
          message: prompt,
          locked_task: 'CHAT',
          locked_model: state.lockedModel || 'auto',
        }),
      });
      let fullText = '';
      const reader = res.body.getReader();
      const dec = new TextDecoder();
      let buf = '';
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const lines = buf.split('\n');
        buf = lines.pop();
        for (const ln of lines) {
          if (!ln.startsWith('data: ')) continue;
          try {
            const evt = JSON.parse(ln.slice(6));
            if (evt.type === 'token') fullText += evt.content || '';
            if (evt.type === 'done') break;
          } catch(e) {}
        }
      }
      // Parse JSON array
      const m = fullText.match(/\[[\s\S]*?\]/);
      const topics = m ? JSON.parse(m[0]) : [];
      if (!topics.length) throw new Error('未提取到主题');
      list.innerHTML = topics.map(t =>
        `<button class="wa-topic-chip" onclick="WA._topicClick(this)">${_escHtml(t)}</button>`
      ).join('');
    } catch(e) {
      list.innerHTML = `<span style="color:var(--error,red)">提炼失败: ${_escHtml(e.message)}</span>`;
    }
  };

  window.WA._topicClick = (btn) => {
    const topic = btn.textContent;
    const input = $('wa-user-input');
    if (input) {
      input.value = `请详细介绍「${topic}」，并引用附加文件中的具体内容作为依据，标注来源文件名。`;
      input.focus();
    }
  };

  window.WA.closeTopicBar = () => {
    const bar = $('wa-topic-chips-bar');
    if (bar) bar.style.display = 'none';
  };

  // ── Grounded Citation: inject source labeling into multi-doc prompt ────────
  // Called inside sendMessage() — appends instruction to prompt.
  function _citationInstruction() {
    return '\n\n【重要】：在引用各文件中的具体内容时，请在引用后附上来源标注，格式为 `[来源: 文件名]`，以便用户溯源核查。';
  }

  // Parse AI response text and replace [来源: xxx] with clickable citation chips
  function _parseCitations(html) {
    return html.replace(
      /\[来源[:：]\s*([^\]]{1,60})\]/g,
      (_, srcName) =>
        `<span class="wa-citation-chip" onclick="WA._citationClick('${_escHtml(srcName.trim())}')" title="点击查看来源">📌 ${_escHtml(srcName.trim())}</span>`
    );
  }

  window.WA._citationClick = (fileName) => {
    const file = state._aiFileContext.find(
      f => f.name === fileName || f.name.toLowerCase() === fileName.toLowerCase()
    );
    if (!file) { showToast(`未找到文件 "${fileName}"`, 'warn'); return; }
    // Show the source in the preview drawer
    const preview = $('wa-source-preview');
    const label = $('wa-source-preview-label');
    const body = $('wa-source-preview-body');
    if (!preview || !body) return;
    label.textContent = `📌 ${file.name}`;
    body.innerHTML = `<pre class="wa-source-pre">${_escHtml((file.content || '').slice(0, 3000))}${file.content && file.content.length > 3000 ? '…' : ''}</pre>`;
    preview.style.display = '';
    preview.scrollTop = 0;
  };

  window.WA.closeSourcePreview = () => {
    const el = $('wa-source-preview');
    if (el) el.style.display = 'none';
  };

  // ── Audio Overview ────────────────────────────────────────────────────────
  window.WA.openAudioOverview = async () => {
    const files = state._aiFileContext;
    if (!files.length) { showToast('请先附加文件', 'warn'); return; }
    const modal = $('wa-audio-modal');
    const body = $('wa-audio-modal-body');
    if (!modal || !body) return;
    body.innerHTML = '<div class="wa-audio-loading"><span class="wa-spinner"></span> 正在生成脚本…</div>';
    modal.style.display = '';

    try {
      const res = await fetch('/api/v1/workspace/audio_overview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          files: files.map(f => ({ name: f.name, content: (f.content || '').slice(0, 8000) })),
          session_id: _waSession(),
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const reader = res.body.getReader();
      const dec = new TextDecoder();
      let buf = '';
      let script = null;

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const lines = buf.split('\n');
        buf = lines.pop();
        for (const ln of lines) {
          if (!ln.startsWith('data: ')) continue;
          try {
            const evt = JSON.parse(ln.slice(6));
            if (evt.event === 'script') {
              script = evt.data;
              body.innerHTML = _renderAudioScript(script, null);
            } else if (evt.event === 'audio_url') {
              if (evt.data) {
                body.innerHTML = _renderAudioScript(script, evt.data);
              }
            } else if (evt.event === 'error') {
              body.innerHTML = `<div style="color:var(--error,red);padding:16px">❌ ${_escHtml(evt.data)}</div>`;
            }
          } catch(e) {}
        }
      }
      if (!script) body.innerHTML = '<div class="wa-audio-loading">⚠ 未收到脚本</div>';
    } catch(e) {
      if (body) body.innerHTML = `<div style="color:var(--error,red);padding:16px">❌ ${_escHtml(e.message)}</div>`;
    }
  };

  function _renderAudioScript(lines, audioUrl) {
    const scriptHtml = (lines || []).map(l => {
      const isA = l.speaker === 'Host A';
      return `<div class="wa-audio-line ${isA ? 'host-a' : 'host-b'}">` +
        `<span class="wa-audio-name">${isA ? '主播 A' : '主播 B'}</span>` +
        `<span class="wa-audio-text">${_escHtml(l.text)}</span>` +
        `</div>`;
    }).join('');

    const playerHtml = audioUrl
      ? `<div class="wa-audio-player-wrap"><audio controls src="${_escHtml(audioUrl)}" class="wa-audio-player"></audio></div>`
      : `<div class="wa-audio-no-tts">💬 脚本已生成，音频合成需要 edge-tts 库（<code>pip install edge-tts</code>）</div>`;

    return `${playerHtml}<div class="wa-audio-script">${scriptHtml}</div>`;
  }

  window.WA.closeAudioModal = () => {
    const el = $('wa-audio-modal');
    if (el) el.style.display = 'none';
  };

  // ── Notebook Guide ────────────────────────────────────────────────────────
  window.WA.openNotebookGuide = async () => {
    const files = state._aiFileContext;
    if (!files.length) { showToast('请先附加文件', 'warn'); return; }
    const drawer = $('wa-notebook-guide');
    const body = $('wa-notebook-body');
    if (!drawer || !body) return;
    body.innerHTML = '<div class="wa-audio-loading"><span class="wa-spinner"></span> 正在生成学习包…</div>';
    drawer.style.display = '';

    try {
      const res = await fetch('/api/v1/workspace/notebook_guide', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          files: files.map(f => ({ name: f.name, content: (f.content || '').slice(0, 8000) })),
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);

      // Clear loading, prepare cards container
      body.innerHTML = '';

      const LABELS = {
        summary: '📋 执行摘要', points: '🎯 关键要点',
        faq: '❓ 常见问答', glossary: '📖 核心词汇',
      };

      const reader = res.body.getReader();
      const dec = new TextDecoder();
      let buf = '';
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const lines = buf.split('\n');
        buf = lines.pop();
        for (const ln of lines) {
          if (!ln.startsWith('data: ')) continue;
          try {
            const evt = JSON.parse(ln.slice(6));
            if (evt.section === 'done') break;
            if (evt.section === 'error') {
              body.innerHTML += `<div style="color:var(--error,red);padding:10px">❌ ${_escHtml(evt.content)}</div>`;
              break;
            }
            if (!LABELS[evt.section]) continue;
            const renderMd = (t) => {
              if (window.marked) { try { return window.marked.parse(t || ''); } catch(e) {} }
              return `<pre>${_escHtml(t)}</pre>`;
            };
            const card = document.createElement('div');
            card.className = 'wa-nb-card';
            card.innerHTML =
              `<div class="wa-nb-card-header" onclick="this.parentElement.classList.toggle('collapsed')">` +
              `<span>${LABELS[evt.section]}</span>` +
              `<div class="wa-nb-card-btns">` +
              `<button class="wa-nb-copy-btn" onclick="event.stopPropagation();WA._copyNbSection(this)" title="复制">📋</button>` +
              `<button class="wa-nb-send-btn" onclick="event.stopPropagation();WA._sendNbSection(this)" title="发送到AI">💬</button>` +
              `<span class="wa-nb-chevron">▾</span></div></div>` +
              `<div class="wa-nb-card-body" data-raw="${_escHtml(evt.content)}">${renderMd(evt.content)}</div>`;
            body.appendChild(card);
          } catch(e) {}
        }
      }
      if (!body.children.length) {
        body.innerHTML = '<div class="wa-audio-loading">⚠ 未收到内容</div>';
      }
    } catch(e) {
      if (body) body.innerHTML = `<div style="color:var(--error,red);padding:16px">❌ ${_escHtml(e.message)}</div>`;
    }
  };

  window.WA._copyNbSection = async (btn) => {
    const body = btn.closest('.wa-nb-card').querySelector('.wa-nb-card-body');
    if (!body) return;
    try {
      await navigator.clipboard.writeText(body.dataset.raw || body.textContent);
      showToast('已复制', 'success');
    } catch(e) { showToast('复制失败', 'warn'); }
  };

  window.WA._sendNbSection = (btn) => {
    const body = btn.closest('.wa-nb-card').querySelector('.wa-nb-card-body');
    if (!body) return;
    const input = $('wa-user-input');
    if (input) { input.value = (body.dataset.raw || body.textContent).slice(0, 500); input.focus(); }
    WA.closeNotebookGuide();
  };

  window.WA.closeNotebookGuide = () => {
    const el = $('wa-notebook-guide');
    if (el) el.style.display = 'none';
  };

  // ── AI Response Action Bar ─────────────────────────────────────────────────
  // snapshot = { pinnedSel, toolCall, outputMode } — captured at response-complete
  // time so UI buttons are isolated from subsequent state changes.
  function _makeAIActionBar(snapshot) {
    const bar = document.createElement('div');
    bar.className = 'wa-ai-action-bar';

    const label = document.createElement('span');
    label.className = 'wa-ai-action-label';
    label.textContent = 'AI 回复了，如何处理？';
    bar.appendChild(label);

    const _btn = (text, extraCls, mode) => {
      const b = document.createElement('button');
      b.className = 'wa-ai-action-btn' + (extraCls ? ' ' + extraCls : '');
      b.textContent = text;
      b.addEventListener('click', () => _execWriteToDoc(mode, snapshot, bar));
      return b;
    };

    if (snapshot.pinnedSel) {
      // Has a pinned text selection — offer targeted replace
      bar.appendChild(_btn('✅ 替换选区', 'primary', 'replace'));
      bar.appendChild(_btn('📎 插入到后面', '', 'append'));
    } else if (snapshot.toolCall) {
      // No pinned selection but AI produced a structured tool call
      // (e.g. full-doc polish in 写入文档 mode) — allow applying it
      bar.appendChild(_btn('✅ 应用到文档', 'primary', 'replace'));
      bar.appendChild(_btn('📎 插入到末尾', '', 'append'));
    } else if (snapshot.outputMode && snapshot.outputMode !== 'chat') {
      // In "写入文档" mode — offer direct write even without explicit selection/tool call
      bar.appendChild(_btn('✅ 写入文档', 'primary', 'replace'));
      bar.appendChild(_btn('📎 插入到末尾', '', 'append'));
    } else {
      // Pure chat reply with no selection and no tool call
      bar.appendChild(_btn('📎 插入到文档末尾', 'primary', 'append'));
    }
    bar.appendChild(_btn('👁 仅查看', 'muted', 'view'));
    return bar;
  }

  // Isolated apply function — reads exclusively from the closed-over snapshot,
  // never from global state, so it is safe to call at any time after creation.
  function _execWriteToDoc(mode, snapshot, bar) {
    if (mode !== 'view') {
      // Locate the AI message immediately preceding this action bar
      let msgEl = bar.previousElementSibling;
      while (msgEl && !msgEl.classList.contains('wa-msg')) {
        msgEl = msgEl.previousElementSibling;
      }
      const rawText = (msgEl && msgEl.dataset.rawText) ? msgEl.dataset.rawText
                    : (msgEl ? msgEl.textContent : '');

      const editor = state.activeEditor;
      const tc     = snapshot.toolCall;
      const sel    = snapshot.pinnedSel;

      if (tc && editor) {
        // AI produced a structured tool call — most reliable path
        if (mode === 'replace') {
          editor.applyToolCall(tc);
        } else if (mode === 'append') {
          if (editor.appendToolCall) {
            editor.appendToolCall(tc);
          } else {
            editor.applyToolCall(tc);
          }
        }
      } else if (sel && editor && typeof editor.replaceSelectionWith === 'function') {
        // No tool call but original pinned selection is known
        editor.replaceSelectionWith(mode, sel, rawText);
      } else if (sel) {
        showToast('无法定位原始选区，已复制到剪贴板', 'info');
        navigator.clipboard && navigator.clipboard.writeText(rawText).catch(() => {});
      } else if (editor) {
        // No selection and no tool call — full-doc replace or append
        if (mode === 'replace') {
          // Convert markdown AI text to HTML and replace entire document content
          const htmlVal = window.marked ? window.marked.parse(rawText) : ('<p>' + rawText.replace(/\n/g, '</p><p>') + '</p>');
          editor.applyToolCall({ type: 'replace_all', value: htmlVal });
        } else {
          editor.applyToolCall({ type: 'insert_text', value: '\n' + rawText });
        }
        WA.scheduleAutoSave && WA.scheduleAutoSave();
      }
    }
    bar.remove();
  }

  // Legacy entry point kept for backward compatibility (quick-action cards may call this).
  window.WA.applyAIResponse = (mode, btn) => {
    const bar = btn.closest('.wa-ai-action-bar');
    if (!bar) return;
    _execWriteToDoc(mode, {
      pinnedSel:  state.lastPinnedSel,
      toolCall:   state.pendingToolCall,
      outputMode: state.aiOutputMode,
    }, bar);
    state.pendingToolCall = null;
    state.lastPinnedSel = null;
  };

  window.WA.sendMessage = () => {
      const input = $('wa-user-input');
      const text = input.value.trim();
      if (!text || state.isLoading) return;

      // Capture and clear pinned selection before rendering
      const pinnedSel = state.pinnedSelection;
      state.lastPinnedSel = pinnedSel || null;
      state.pendingToolCall = null;
      if (pinnedSel) WA.clearSelection();

      const msgs = $('wa-ai-messages');

      // Add user message bubble — with optional Copilot-style quote block
      const uMsg = document.createElement('div');
      uMsg.className = 'wa-msg user';
      // Show attached files indicator in the message
      if (state._aiFileContext && state._aiFileContext.length) {
        const filesNote = document.createElement('div');
        filesNote.className = 'wa-msg-files-note';
        filesNote.textContent = `📎 ${state._aiFileContext.map(f => f.name).join(', ')}`;
        uMsg.appendChild(filesNote);
      }
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

      // Add streaming bubble
      const loadingEl = document.createElement('div');
      loadingEl.className = 'wa-msg ai streaming';
      msgs.appendChild(loadingEl);
      msgs.scrollTop = msgs.scrollHeight;

      input.value = '';
      input.style.height = 'auto';

      const MAX_CONTEXT = 6000;
      let contextRaw = state.activeEditor ? state.activeEditor.getContent() : '';
      const context = contextRaw.length > MAX_CONTEXT
          ? contextRaw.substring(0, MAX_CONTEXT) + '\n…[内容过长已截断，请缩小选区]'
          : contextRaw;
      const fileType = state.fileType || 'general';

      // Build full message with document context + tool/proposal format instructions
      // NOTE: defined at function scope so it's accessible both inside and outside the if block below
      const _isTranslateIntent = (t) => /翻译|中译英|英译中|译成|翻成|translate/i.test(t || '');
      const _isReadOnlyIntent = (t) => {
        if (_isTranslateIntent(t)) return true;
        const roRe = /总结|摘要|分析|解释|讲解|简介|介绍|是什么|描述|概括|审阅/;
        const modRe = /修改|改写|润色|删除|替换|更正|修复|优化|重写|调整|纠正|校对|添加|插入|精简|压缩|扩充|完善|补充|修订|转换|改进/;
        return !pinnedSel && roRe.test(t) && !modRe.test(t);
      };
      let fullMessage = text;
      if (state.fileName && context) {
        const selHint = pinnedSel
          ? `\n\n[用户选中的文字]\n"${pinnedSel.length > 500 ? pinnedSel.substring(0, 500) + '…' : pinnedSel}"\n`
          : '';
        // Only inject modification proposal hint for queries that intend to edit the document
        // Skip for read-only intents (summarize, analyze, explain, translate for reference, etc.)
        const _isReadOnly = _isReadOnlyIntent(text);
        let toolHint = '';
        if (state.aiOutputMode !== 'chat' && !_isReadOnly) {
          if (fileType === 'docx') {
            toolHint = '\n\n如需修改文档，在回复末尾另起一行输出 JSON 提案（不要 Markdown 代码块）：\n{"proposals":[{"id":"p1","original_text":"被替换的原文","proposed_text":"修改后内容","rationale":"修改理由"}]}\n如有多处修改，并列多条。不需要修改时不要输出该 JSON。';
          } else if (fileType === 'xlsx') {
            toolHint = '\n\n如需修改表格单元格，在回复末尾输出 JSON 提案：\n{"proposals":[{"id":"p1","original_text":"原値","proposed_text":"新値","rationale":"理由","tool":{"type":"set_cell","r":行号,"c":列号,"value":"新値"}}]}';
          } else if (fileType === 'pptx') {
            toolHint = '\n\n如需修改幻灯片文字，在回复末尾输出 JSON 提案：\n{"proposals":[{"id":"p1","original_text":"原文","proposed_text":"新内容","rationale":"理由","tool":{"type":"set_pptx_text","slide_index":0,"shape_id":1,"value":"新内容"}}]}';
          }
        }
        fullMessage = `[工作区文档助手模式]\n当前文件: ${state.fileName} (${fileType})\n\n文档内容:\n${context}${selHint}${toolHint}\n\n用户指令: ${text}`;
      }

      // Append multi-file context if files have been dragged to the AI panel
      if (state._aiFileContext && state._aiFileContext.length) {
        const tIdx = state._aiTargetFileIdx;
        const targetFile = (tIdx >= 0 && tIdx < state._aiFileContext.length) ? state._aiFileContext[tIdx] : null;

        if (targetFile) {
          // Target-file mode: label target vs reference files clearly
          const refFiles = state._aiFileContext
            .map((f, i) => ({ ...f, i }))
            .filter(f => f.i !== tIdx);
          const targetBlock = `\n\n--- 目标文件（待修改）: ${targetFile.name} ---\n${targetFile.content}`;
          const refBlocks = refFiles.map((f, ri) =>
            `\n\n--- 参考文件 ${ri + 1}: ${f.name} ---\n${f.content}`
          ).join('');
          fullMessage =
            `[多文档内容同步模式]\n目标文件: ${targetFile.name} | 参考文件: ${refFiles.map(f => f.name).join(', ')}` +
            (state.fileName ? `\n\n--- 当前编辑文件: ${state.fileName} (${fileType}) ---\n${context || '(无内容)'}` : '') +
            targetBlock + refBlocks +
            (pinnedSel ? `\n\n[用户选中的文字]\n"${pinnedSel.length > 500 ? pinnedSel.substring(0, 500) + '…' : pinnedSel}"` : '') +
            `\n\n请根据参考文件的内容，分析目标文件"${targetFile.name}"需要做哪些更新，并以JSON格式给出proposals修改建议（original_text / proposed_text），以便用户直接应用。${_citationInstruction()}\n\n用户指令: ${text}`;
        } else {
          // Pure analysis mode (no write-back target)
          const fileBlocks = state._aiFileContext.map((f, i) =>
            `\n\n--- 附加文件 ${i + 1}: ${f.name} ---\n${f.content}`
          ).join('');
          fullMessage = `[多文档分析模式]\n共 ${state._aiFileContext.length + (state.fileName ? 1 : 0)} 份文件` +
            (state.fileName ? `\n\n--- 当前编辑文件: ${state.fileName} (${fileType}) ---\n${context || '(无内容)'}` : '') +
            fileBlocks +
            (pinnedSel ? `\n\n[用户选中的文字]\n"${pinnedSel.length > 500 ? pinnedSel.substring(0, 500) + '…' : pinnedSel}"` : '') +
            _citationInstruction() +
            `\n\n用户指令: ${text}`;
        }
      }

      state.conversation.push({ role: 'user', content: text });
      state.isLoading = true;

      // Pass doc_edit context so backend can inject the right system prompt
      const _isDocEdit = !!(state.fileName && state.aiOutputMode !== 'chat' && !_isReadOnlyIntent(text));
      _waSendToChat(fullMessage, loadingEl, {
        model:    state.lockedModel || 'auto',
        doc_edit: _isDocEdit,
        file_type: state.fileType || '',
        has_sel:  !!pinnedSel,
        allow_apply: !_isReadOnlyIntent(text),
      });
  };

  // ── Auto-save ──────────────────────────────────────────────────────────────
  let _autoSaveTimer = null;
  let _autoSaveEnabled = localStorage.getItem('wa_autosave') === 'on';

  window.WA.toggleAutoSave = () => {
    _autoSaveEnabled = !_autoSaveEnabled;
    localStorage.setItem('wa_autosave', _autoSaveEnabled ? 'on' : 'off');
    const btn = $('wa-autosave-toggle');
    if (btn) btn.classList.toggle('toggle-on', _autoSaveEnabled);
    const status = $('wa-autosave-status');
    if (status) {
      status.className = _autoSaveEnabled ? 'saved' : '';
      status.textContent = _autoSaveEnabled ? '自动保存已开启' : '自动保存已关闭';
      setTimeout(() => { if (status) { status.className = ''; status.textContent = ''; } }, 2000);
    }
  };

  window.WA.setOutputMode = (mode) => {
    state.aiOutputMode = mode;
    localStorage.setItem('wa_ai_output_mode', mode);
    // Update toggle buttons if any exist
    document.querySelectorAll('.wa-output-mode-btn').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.mode === mode);
    });
    // Sync the output-mode toggle buttons in settings panel
    document.querySelectorAll('.wa-output-mode-toggle button[data-mode]').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.mode === mode);
    });
  };

  window.WA.toggleSettings = () => {
    const panel = document.getElementById('wa-ai-settings-panel');
    if (!panel) return;
    const isOpen = panel.classList.toggle('open');
    if (isOpen) _checkOllamaStatus();
  };

  function _checkOllamaStatus() {
    fetch('/api/v1/workspace/ollama-status')
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        const row = document.getElementById('wa-ollama-status-row');
        const txt = document.getElementById('wa-ollama-status-text');
        const onBtn = document.getElementById('wa-local-on-btn');
        if (!row || !txt) return;
        if (data && data.running) {
          row.style.display = 'block';
          txt.textContent = `✅ Ollama 运行中 (${data.model || 'qwen3:8b'})`;
          if (onBtn) { onBtn.disabled = false; onBtn.title = '使用本地 Ollama 模型'; }
        } else {
          row.style.display = 'block';
          txt.textContent = '⚠️ Ollama 未运行，无法切换到本地模型';
          if (onBtn) { onBtn.disabled = true; onBtn.title = '请先启动 Ollama'; }
        }
      })
      .catch(() => {});
  }

  window.WA.setUseLocalModel = (useLocal) => {
    const newModel = useLocal ? 'local' : 'auto';
    state.lockedModel = newModel;
    localStorage.setItem('wa_locked_model', newModel);
    // Update local model toggle buttons
    document.querySelectorAll('[data-local-mode]').forEach(btn => {
      btn.classList.toggle('active', (btn.dataset.localMode === 'on') === useLocal);
    });
    // Update model badge
    const badge = document.getElementById('wa-ai-model-badge');
    if (badge) badge.textContent = useLocal ? 'Ollama ●' : 'Koto AI ●';
    // Reset cloud model select to auto if switching to local
    const sel = document.getElementById('wa-model-select');
    if (sel && useLocal) sel.value = 'auto';
    // Persist to server so file-editor AI (editor_ai_stream) also respects the choice
    fetch('/api/local-model/switch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode: newModel === 'local' ? 'local' : 'cloud' }),
    }).catch(() => {/* silent — localStorage state still works for chat/stream path */});
  };

  window.WA.setLockedModel = (val) => {
    state.lockedModel = val || 'auto';
    localStorage.setItem('wa_locked_model', state.lockedModel);
    // If user picks a cloud model, turn off local-model toggle
    if (state.lockedModel !== 'local') {
      document.querySelectorAll('[data-local-mode]').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.localMode === 'off');
      });
    }
    const badge = $('wa-ai-model-badge');
    if (badge) {
      const MODEL_LABELS = {
        'auto': 'Koto AI ●',
        'local': 'Ollama ●',
        'gemini-3-flash-preview': 'Flash ●',
        'gemini-3-pro-preview': 'Pro ●',
        'gemini-3.1-pro-preview': 'Pro 3.1 ●',
      };
      badge.textContent = MODEL_LABELS[state.lockedModel] || (state.lockedModel + ' ●');
    }
    const sel = document.getElementById('wa-model-select');
    if (sel && sel.value !== state.lockedModel) sel.value = state.lockedModel;
  };

  window.WA.scheduleAutoSave = () => {
    if (!state.fileId || !state.fileType || state.fileType === 'pdf') return;
    // Mark active tab as modified (dirty indicator)
    const tab = state.openTabs.find(t => t.path === state.activeTabPath);
    if (tab && !tab.modified) { tab.modified = true; _renderTabs(); }
    // If auto-save is enabled, schedule a disk write after 2 s of inactivity
    if (_autoSaveEnabled) {
      clearTimeout(_autoSaveTimer);
      const status = $('wa-autosave-status');
      if (status) { status.className = 'saving'; status.textContent = '保存中…'; }
      _autoSaveTimer = setTimeout(WA.autoSave, 2000);
    }
  };

  // autoSave: called by the timer when auto-save is ON — saves to workspace in-place.
  window.WA.autoSave = async () => {
    if (!state.activeEditor || !state.fileId || !state.fileType || state.fileType === 'pdf') return;
    const status = $('wa-autosave-status');
    try {
      const data = state.activeEditor.serialize();
      // Always update in-memory cache
      const tab = state.openTabs.find(t => t.path === state.activeTabPath);
      if (tab && data) {
        tab.cache = data;
        if (state.fileType === 'docx' && tab.serverData) tab.serverData.html = data;
      }
      // Write to workspace
      const res = await fetch('/api/v1/workspace/auto_save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          file_type: state.fileType,
          file_id: state.fileId,
          ws_source_path: state.wsSourcePath || null,
          explicit: true,
          data,
        }),
      });
      if (!res.ok) throw new Error((await res.json()).error || '自动保存失败');
      const json = await res.json();
      if (tab) { tab.modified = false; _renderTabs(); }
      if (status) {
        status.className = 'saved';
        status.textContent = `✓ 已自动保存 ${json.saved_at}`;
        setTimeout(() => { if (status) { status.className = ''; status.textContent = ''; } }, 4000);
      }
    } catch (e) {
      if (status) { status.className = ''; status.textContent = ''; }
      console.warn('[AutoSave]', e.message);
    }
  };

  // Warn before page unload if any open tab has unsaved changes
  window.addEventListener('beforeunload', (e) => {
    if (state.openTabs.some(t => t.modified)) {
      e.preventDefault();
      e.returnValue = '';
    }
  });

  // ── Close-warning API (called by app.js / pywebview close flow) ────────────

  /**
   * Returns an array of {path, name} for every open tab that has unsaved changes.
   * Called by app.js closeWindow() before destroying the pywebview window.
   */
  window.WA.getUnsavedTabs = () => {
    return state.openTabs.filter(t => t.modified).map(t => ({ path: t.path, name: t.name }));
  };

  /**
   * Show the close-warning modal.  Resolves to 'save', 'discard', or 'cancel'.
   * The caller (closeWindow in app.js) awaits this promise before deciding
   * whether to actually destroy the window.
   */
  window.WA.showCloseWarning = (unsavedTabs) => {
    return new Promise((resolve) => {
      const overlay = $('wa-close-warn-overlay');
      const listEl  = $('wa-close-warn-list');
      if (!overlay || !listEl) { resolve('discard'); return; }
      listEl.innerHTML = unsavedTabs.map(t => `<li>${_escHtml(t.name)}</li>`).join('');
      overlay.style.display = 'flex';
      // Store resolve so buttons can call it
      overlay._resolve = resolve;
    });
  };

  window.WA._closeWarnCancel = () => {
    const overlay = $('wa-close-warn-overlay');
    if (overlay) { overlay.style.display = 'none'; if (overlay._resolve) overlay._resolve('cancel'); }
  };

  window.WA._closeWarnDiscard = () => {
    const overlay = $('wa-close-warn-overlay');
    if (overlay) {
      overlay.style.display = 'none';
      if (overlay._resolve) overlay._resolve('discard');
    }
  };

  window.WA._closeWarnSaveAll = async () => {
    const overlay = $('wa-close-warn-overlay');
    if (overlay) overlay.style.display = 'none';
    // Try to save the currently active tab (most common case)
    // For a full save-all, iterate modified tabs
    const modifiedTabs = state.openTabs.filter(t => t.modified);
    for (const tab of modifiedTabs) {
      try {
        // Switch to the tab and trigger save
        await _switchToTab(tab.path);
        if (state.activeEditor) {
          const data = state.activeEditor.serialize();
          await fetch('/api/v1/workspace/auto_save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              file_type: tab.fileType,
              file_id: tab.fileId,
              ws_source_path: tab.path || null,
              explicit: true,
              data,
            }),
          });
          tab.modified = false;
        }
      } catch (e) {
        console.warn('[CloseWarn] Save failed for', tab.name, e);
      }
    }
    _renderTabs();
    if (overlay && overlay._resolve) overlay._resolve('save');
  };


  const _MIME = {
    docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    xlsx: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    pptx: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
  };

  let _isSaving = false;

  // ── Shared: serialize + POST to workspace, then write bytes to a given fsHandle ──
  async function _doSave(fsHandle) {
    const _saveTabPath  = state.activeTabPath;
    const _saveTab      = state.openTabs.find(t => t.path === _saveTabPath);
    const _saveFileId   = state.fileId;
    const _saveFileType = state.fileType;
    const _saveWsPath   = state.wsSourcePath;

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
    // Refresh the recent-files list so FileHub shows the updated mtime.
    setTimeout(() => { try { loadRecentFiles(); } catch(e) {} }, 800);
    if (fsHandle) {
      const rawRes = await fetch(`/api/v1/workspace/raw/${_saveFileId}?_=${Date.now()}`);
      if (rawRes.ok) {
        const bytes = await rawRes.arrayBuffer();
        await _writeToFileHandle(fsHandle, bytes);
      } else {
        showToast('已保存到工作区 (无法写回原始位置)', 'success');
        return;
      }
    }
    showToast('✓ 已保存', 'success');
  }

  // 保存 — save directly to the original local file (Ctrl+S)
  // If the file was opened from disk, writes back via its FileSystemFileHandle.
  // Otherwise saves to Koto workspace only.
  window.WA.saveFile = async () => {
    if (!state.activeEditor || !state.fileType || state.fileType === 'pdf') return;
    if (_isSaving) return;
    _isSaving = true;
    const btn     = $('wa-save-btn');
    const btnAs   = $('wa-saveas-btn');
    btn.disabled  = true;
    if (btnAs) btnAs.disabled = true;
    try {
      const _saveTab      = state.openTabs.find(t => t.path === state.activeTabPath);
      const _saveWsPath    = state.wsSourcePath;
      const _saveFsHandle  = (_saveTab && _saveTab.fsHandle) || _fsHandleMap.get(_saveWsPath) || null;
      await _doSave(_saveFsHandle);
    } catch(e) {
      showToast(e.message, 'error');
    } finally {
      _isSaving = false;
      const isPdf = (state.fileType === 'pdf');
      btn.disabled    = isPdf;
      if (btnAs) btnAs.disabled = isPdf;
    }
  };

  // 另存为 — always shows the system file picker so the user can choose a new path
  window.WA.saveAs = async () => {
    if (!state.activeEditor || !state.fileType || state.fileType === 'pdf') return;
    if (_isSaving) return;
    // Must acquire picker BEFORE any await while user-gesture is live
    if (!window.showSaveFilePicker) {
      showToast('当前环境不支持文件保存对话框，请使用"保存"', 'error');
      return;
    }
    const ext  = (state.wsSourcePath || state.fileName || 'file.docx').split('.').pop().toLowerCase();
    const mime = _MIME[ext] || 'application/octet-stream';
    let _saveFsHandle;
    try {
      _saveFsHandle = await window.showSaveFilePicker({
        suggestedName: state.fileName || state.wsSourcePath || `document.${ext}`,
        types: [{ description: '文档', accept: { [mime]: ['.' + ext] } }],
        excludeAcceptAllOption: false,
      });
    } catch(pickerErr) {
      if (pickerErr.name === 'AbortError') return; // user cancelled
      showToast('无法打开保存对话框: ' + pickerErr.message, 'error');
      return;
    }
    _isSaving = true;
    const btn     = $('wa-save-btn');
    const btnAs   = $('wa-saveas-btn');
    btn.disabled  = true;
    if (btnAs) btnAs.disabled = true;
    // Update stored handle so future Ctrl+S goes to this new location
    const _saveTab    = state.openTabs.find(t => t.path === state.activeTabPath);
    const _saveWsPath = state.wsSourcePath;
    if (_saveTab) _saveTab.fsHandle = _saveFsHandle;
    _fsHandleMap.set(_saveWsPath, _saveFsHandle);
    try {
      await _doSave(_saveFsHandle);
    } catch(e) {
      showToast(e.message, 'error');
    } finally {
      _isSaving = false;
      const isPdf = (state.fileType === 'pdf');
      btn.disabled    = isPdf;
      if (btnAs) btnAs.disabled = isPdf;
    }
  };

  // ── Phase D: Archive current file ───────────────────────────────────────
  window.WA.toggleArchivePopover = () => {
    const pop = document.getElementById('wa-archive-popover');
    if (!pop) return;
    const visible = pop.style.display !== 'none';
    pop.style.display = visible ? 'none' : 'block';
    if (!visible) {
      // Close on outside click
      const handler = (e) => {
        if (!pop.contains(e.target) && !document.getElementById('wa-archive-btn').contains(e.target)) {
          pop.style.display = 'none';
          document.removeEventListener('click', handler, true);
        }
      };
      setTimeout(() => document.addEventListener('click', handler, true), 10);
    }
  };

  window.WA.archiveCurrent = async (category) => {
    const pop = document.getElementById('wa-archive-popover');
    if (pop) pop.style.display = 'none';
    if (!state.wsSourcePath) { showToast('当前没有打开文件', 'error'); return; }
    const ext = (state.wsSourcePath || '').split('.').pop().toLowerCase();
    try {
      const res = await fetch('/api/files/archive', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          mode: 'custom',
          rules: [{ pattern: `*.${ext}`, target: category }],
          files: [state.wsSourcePath],
        }),
      });
      const d = await res.json();
      if (!res.ok) throw new Error(d.error || '归档失败');
      const moved = d.report?.find?.(r => r.moved > 0);
      if (moved) {
        showToast(`✓ 已归档到「${category}」文件夹`, 'success');
        // Refresh registry so FileHub shows updated location
        setTimeout(() => { try { if (window.WA && WA.refreshRecent) WA.refreshRecent(); } catch(e) {} }, 600);
      } else {
        showToast(d.message || '归档完成', 'success');
      }
    } catch (e) {
      showToast('归档失败: ' + e.message, 'error');
    }
  };

  // ── Version History ──
  window.WA.toggleHistoryPopover = () => {
    const pop = document.getElementById('wa-history-popover');
    if (!pop) return;
    const visible = pop.style.display !== 'none';
    pop.style.display = visible ? 'none' : 'block';
    if (!visible) {
      _loadVersionHistory();
      const handler = (e) => {
        if (!pop.contains(e.target) && !document.getElementById('wa-history-btn').contains(e.target)) {
          pop.style.display = 'none';
          document.removeEventListener('click', handler, true);
        }
      };
      setTimeout(() => document.addEventListener('click', handler, true), 10);
    }
  };

  async function _loadVersionHistory() {
    const listEl = document.getElementById('wa-history-list');
    if (!listEl) return;
    if (!state.wsSourcePath) { listEl.innerHTML = '<span style="color:var(--text-muted);">当前没有打开的文件</span>'; return; }
    listEl.innerHTML = '<span style="color:var(--text-muted);">加载中…</span>';
    try {
      const r = await fetch('/api/v1/workspace/versions?path=' + encodeURIComponent(state.wsSourcePath));
      if (!r.ok) throw new Error('HTTP ' + r.status);
      const d = await r.json();
      const versions = d.versions || [];
      if (!versions.length) { listEl.innerHTML = '<span style="color:var(--text-muted);">暂无历史版本，保存文件后会自动创建快照</span>'; return; }
      const _fmtSize = b => b > 1048576 ? (b/1048576).toFixed(1)+' MB' : Math.round(b/1024)+' KB';
      listEl.innerHTML = versions.map(v => {
        const snapArg   = JSON.stringify(v.snap_path).replace(/"/g, '&quot;');
        const targetArg = JSON.stringify(state.wsSourcePath).replace(/"/g, '&quot;');
        return `<div style="display:flex;align-items:center;justify-content:space-between;padding:7px 6px;border-radius:7px;transition:background 0.1s;cursor:default;"
              onmouseover="this.style.background='var(--bg-secondary)'" onmouseout="this.style.background=''">
            <div>
              <div style="font-size:13px;font-weight:500;color:var(--text-primary);">${v.saved_at || v.name}</div>
              <div style="font-size:11px;color:var(--text-muted);">${_fmtSize(v.size_bytes||0)}</div>
            </div>
            <button onclick="_waRestoreVersion(${snapArg}, ${targetArg})"
              style="font-size:11px;padding:3px 8px;border-radius:6px;border:1px solid var(--border-color);background:var(--bg-primary);color:var(--text-secondary);cursor:pointer;transition:all 0.12s;"
              onmouseover="this.style.background='var(--accent-primary)';this.style.color='#fff';this.style.borderColor='var(--accent-primary)'"
              onmouseout="this.style.background='var(--bg-primary)';this.style.color='var(--text-secondary)';this.style.borderColor='var(--border-color)'">
              恢复
            </button>
          </div>`;
      }).join('');
    } catch (e) {
      listEl.innerHTML = `<span style="color:var(--text-muted);">加载失败: ${e.message}</span>`;
    }
  }

  window._waRestoreVersion = async (snapPath, targetPath) => {
    if (!confirm(`将文件恢复到该版本？当前未保存的更改会丢失。`)) return;
    try {
      const r = await fetch('/api/v1/workspace/restore-version', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ snap_path: snapPath, target_path: targetPath }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || '恢复失败');
      document.getElementById('wa-history-popover').style.display = 'none';
      showToast('✓ 已恢复，正在重新加载…', 'success');
      // Reload the file in the editor after a short delay
      setTimeout(async () => {
        if (state.wsSourcePath) {
          const currentPath = state.wsSourcePath;
          await Router.load({ name: currentPath.split(/[\\/]/).pop(), _waPath: currentPath });
        }
      }, 800);
    } catch (e) {
      showToast('恢复失败: ' + e.message, 'error');
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

  // Drop zone for chart images: wire the pre-existing overlay element
  // (pointer-events cover the full canvas when a chart drag is active,
  //  bypassing WangEditor's own drag handlers)
  const _dropHintOverlay = $('wa-ai-img-drop-hint');
  if (_dropHintOverlay) {
    _dropHintOverlay.addEventListener('dragover', (e) => {
      e.preventDefault();
      e.dataTransfer.dropEffect = 'copy';
    });
    _dropHintOverlay.addEventListener('drop', (e) => {
      e.preventDefault();
      _dropHintOverlay.classList.remove('active');
      const src = _draggingChartSrc;
      _draggingChartSrc = null;
      _draggingChartName = null;
      if (src && state.activeEditor) {
        state.activeEditor.applyToolCall({ type: 'insert_image', src });
        showToast('图表已插入文档', 'success');
      }
    });
  }

  // Init
  initSocket();
  // loadFileBrowser / loadRecentFiles are deferred to first open (openInMainView)
  // to avoid issuing API requests before the user has ever opened the workspace panel.
  _renderMyWorkspace();
  _renderTempWorkspace();
  // Sync auto-save toggle appearance
  (() => { const btn = $('wa-autosave-toggle'); if (btn && _autoSaveEnabled) btn.classList.add('toggle-on'); })();

  // ── My Workspace: drag-drop to add files ──
  const mywsList = $('wa-myws-list');
  const mywsEmpty = $('wa-myws-empty');
  [mywsList, mywsEmpty].forEach(el => {
    if (!el) return;
    el.addEventListener('dragover', (e) => {
      if (e.dataTransfer.types.includes('application/wa-file-path') || e.dataTransfer.types.includes('Files')) {
        e.preventDefault();
        e.dataTransfer.dropEffect = 'copy';
        if (mywsList) mywsList.classList.add('drag-over');
      }
    });
    el.addEventListener('dragleave', (e) => {
      if (!el.contains(e.relatedTarget)) {
        if (mywsList) mywsList.classList.remove('drag-over');
      }
    });
    el.addEventListener('drop', (e) => {
      e.preventDefault();
      if (mywsList) mywsList.classList.remove('drag-over');
      const filePath = e.dataTransfer.getData('application/wa-file-path');
      if (filePath) {
        WA.addToMyWorkspace(filePath);
      }
    });
  });

  // ── Temp Workspace: drag-drop to add files ──
  const tmpwsList = $('wa-tmpws-list');
  const tmpwsEmpty = $('wa-tmpws-empty');
  [tmpwsList, tmpwsEmpty].forEach(el => {
    if (!el) return;
    el.addEventListener('dragover', (e) => {
      if (e.dataTransfer.types.includes('application/wa-file-path') || e.dataTransfer.types.includes('Files')) {
        e.preventDefault();
        e.dataTransfer.dropEffect = 'copy';
        if (tmpwsList) tmpwsList.classList.add('drag-over');
      }
    });
    el.addEventListener('dragleave', (e) => {
      if (!el.contains(e.relatedTarget)) {
        if (tmpwsList) tmpwsList.classList.remove('drag-over');
      }
    });
    el.addEventListener('drop', (e) => {
      e.preventDefault();
      if (tmpwsList) tmpwsList.classList.remove('drag-over');
      const filePath = e.dataTransfer.getData('application/wa-file-path');
      if (filePath) {
        WA.addToTempWorkspace(filePath);
      }
    });
  });

  // ── AI Panel: drag-drop files for multi-doc context ──
  const aiPanel = $('wa-ai');
  const aiDropOverlay = $('wa-ai-file-drop');
  const canvasShield = $('wa-drag-canvas-shield');

  // Track file drags globally so we can show the canvas shield
  // (prevents rich editors like WangEditor/Univer from swallowing drag events)
  document.addEventListener('dragstart', (e) => {
    if (e.dataTransfer.types && e.dataTransfer.types.includes
        ? e.dataTransfer.types.includes('application/wa-file-path')
        : false) return; // already handled by ondragstart
    // ondragstart fires before dragstart, so check if this element is a file item
    if (e.target && e.target.dataset && e.target.dataset.path) {
      document.body.classList.add('wa-file-dragging');
    }
  });
  document.addEventListener('dragend', () => {
    document.body.classList.remove('wa-file-dragging');
    if (aiDropOverlay) {
      aiDropOverlay.style.display = 'none';
      aiDropOverlay.classList.remove('active');
    }
  });

  function _isFileDrag(e) {
    try { return e.dataTransfer.types.includes('application/wa-file-path'); } catch (_) { return false; }
  }

  function _showAIOverlay() {
    if (!aiDropOverlay) return;
    aiDropOverlay.style.display = 'flex';
    aiDropOverlay.classList.add('active');
  }
  function _hideAIOverlay() {
    if (!aiDropOverlay) return;
    aiDropOverlay.style.display = 'none';
    aiDropOverlay.classList.remove('active');
  }

  if (aiPanel) {
    let _aiDragCounter = 0;

    aiPanel.addEventListener('dragenter', (e) => {
      if (!_isFileDrag(e)) return;
      e.preventDefault();
      _aiDragCounter++;
      _showAIOverlay();
    });
    aiPanel.addEventListener('dragover', (e) => {
      if (!_isFileDrag(e)) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = 'copy';
    });
    aiPanel.addEventListener('dragleave', (e) => {
      if (!_isFileDrag(e)) return;
      _aiDragCounter--;
      if (_aiDragCounter <= 0) {
        _aiDragCounter = 0;
        _hideAIOverlay();
      }
    });
    aiPanel.addEventListener('drop', (e) => {
      _aiDragCounter = 0;
      _hideAIOverlay();
      document.body.classList.remove('wa-file-dragging');
      const filePath = e.dataTransfer.getData('application/wa-file-path');
      if (filePath) {
        e.preventDefault();
        e.stopPropagation();
        _addFileToAIContext(filePath);
        const input = $('wa-user-input');
        if (input) setTimeout(() => input.focus(), 150);
      }
    });
  }

  // The overlay itself also receives drag events (when pointer-events:all is active)
  // providing a direct drop target that doesn't depend on bubbling
  if (aiDropOverlay) {
    aiDropOverlay.addEventListener('dragover', (e) => {
      if (!_isFileDrag(e)) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = 'copy';
    });
    aiDropOverlay.addEventListener('drop', (e) => {
      _hideAIOverlay();
      document.body.classList.remove('wa-file-dragging');
      const filePath = e.dataTransfer.getData('application/wa-file-path');
      if (filePath) {
        e.preventDefault();
        e.stopPropagation();
        _addFileToAIContext(filePath);
        const input = $('wa-user-input');
        if (input) setTimeout(() => input.focus(), 150);
      }
    });
  }

  // Canvas shield: pass dragover through so the drag stays alive while over the editor,
  // but the shield itself is not a drop target (drops just fall through after drag ends)
  if (canvasShield) {
    canvasShield.addEventListener('dragover', (e) => { e.preventDefault(); e.dataTransfer.dropEffect = 'copy'; });
  }

  // ── Local file / folder pickers ──
  const localFileInput = $('wa-local-file-input');
  const localFolderInput = $('wa-local-folder-input');

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

  // ── File menu ──────────────────────────────────────────────────────────────
  window.WA.toggleFileMenu = function () {
    const dd  = $('wa-file-dropdown');
    const btn = $('wa-ribbon-file-btn');
    if (!dd) return;
    const isOpen = dd.style.display !== 'none';
    dd.style.display = isOpen ? 'none' : 'block';
    if (btn) btn.classList.toggle('open', !isOpen);
  };
  window.WA._closeFileMenu = function () {
    const dd  = $('wa-file-dropdown');
    const btn = $('wa-ribbon-file-btn');
    if (dd)  dd.style.display = 'none';
    if (btn) btn.classList.remove('open');
  };
  window.WA._openLocalFile   = function () { _openFilePicker(); };
  window.WA._openLocalFolder = function () {
    const input = $('wa-local-folder-input');
    if (input) input.click();
  };
  window.WA._menuCloseFile = function () {
    if (state.activeTabPath) WA._closeTab(state.activeTabPath);
  };

  // Close file dropdown when clicking outside
  document.addEventListener('click', (e) => {
    if (!e.target.closest('#wa-file-menu-wrap')) WA._closeFileMenu();
  });

  // ── Status bar ─────────────────────────────────────────────────────────────
  function _updateStatusBar() {
    const ftEl  = $('wa-status-filetype');
    const modEl = $('wa-status-modified');
    const sb    = $('wa-status-bar');
    if (!ftEl) return;
    const TYPE_LABELS = { docx: 'Word \u6587\u6863', xlsx: 'Excel \u5de5\u4f5c\u7c3f', pptx: 'PowerPoint \u6f14\u793a\u6587\u7a3f', pdf: 'PDF \u6587\u6863' };
    ftEl.textContent = state.fileType ? (TYPE_LABELS[state.fileType] || state.fileType.toUpperCase()) : '';
    const tab = state.openTabs.find(t => t.path === state.activeTabPath);
    if (modEl) modEl.style.display = (tab && tab.modified) ? '' : 'none';
    if (sb)    sb.style.display    = (state.fileType === 'pptx') ? 'none' : '';
  }

  window.WA.openInMainView = function () {
    const chatView = document.getElementById('chatView');
    const wsView   = document.getElementById('workspaceView');
    if (!wsView) {
      // Fallback: no embedded container → open standalone tab
      window.open('/workspace-assistant', '_blank');
      return;
    }
    // Highlight active nav button (sidebar stays visible)
    document.querySelectorAll('.sb-nav-item').forEach(el => el.classList.remove('active'));
    const navBtn = document.getElementById('navWorkspaceBtn');
    if (navBtn) navBtn.classList.add('active');
    // Swap views
    if (chatView) chatView.style.display = 'none';
    wsView.style.display = 'flex';
    localStorage.setItem('koto.inWorkspace', '1');
    // Load workspace files on first open (idempotent: skip if already loaded)
    if (typeof loadFileBrowser === 'function' && !window._WA_fileBrowserLoaded) {
      window._WA_fileBrowserLoaded = true;
      loadFileBrowser();
      if (typeof loadRecentFiles === 'function') loadRecentFiles();
    }

    // If an XLSX/PPTX editor is already mounted, trigger a reflow so it can
    // recover from a prior zero-size render that may have occurred while the
    // workspace panel was hidden (display:none → flex just happened above).
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        if (!state.activeEditor) return;
        if (state.fileType === 'xlsx') {
          const sheetEl = document.getElementById('wa-xlsx-sheet');
          if (sheetEl && sheetEl.offsetWidth > 0) {
            // Nudge container to fire Univer's internal ResizeObserver
            const w = sheetEl.offsetWidth;
            sheetEl.style.width = (w + 1) + 'px';
            requestAnimationFrame(() => { sheetEl.style.width = ''; });
          }
        } else if (state.fileType === 'pptx') {
          const area = document.getElementById('wa-pptx-slide-area');
          if (area && area.clientWidth > 48 && state.activeEditor._renderSlide) {
            state.activeEditor._renderSlide(state.activeEditor._curIdx || 0);
          }
        }
      });
    });
  };

  window.WA.closeInMainView = function () {
    const chatView = document.getElementById('chatView');
    const wsView   = document.getElementById('workspaceView');
    if (wsView)   wsView.style.display   = 'none';
    if (chatView) chatView.style.display = '';
    localStorage.removeItem('koto.inWorkspace');
    // Remove active state from workspace nav button
    const navBtn = document.getElementById('navWorkspaceBtn');
    if (navBtn) navBtn.classList.remove('active');
  };

  // Toggle workspace open/close — called by the sidebar nav button
  window.WA.toggleMainView = function () {
    const wsView = document.getElementById('workspaceView');
    if (wsView && wsView.style.display !== 'none') {
      window.WA.closeInMainView();
    } else {
      window.WA.openInMainView();
    }
  };

  // Bridge: app.js calls window.switchToChatView() when selecting a session
  // while the workspace is open — this closes workspace and shows chat
  window.switchToChatView = function () {
    const wsView = document.getElementById('workspaceView');
    if (wsView && wsView.style.display !== 'none') {
      window.WA.closeInMainView();
    }
  };

  // ── File-browser keyboard shortcuts (Windows-style) ───────────────────────
  // Track whether mouse is inside the left file panel
  let _waLeftActive = false;

  // Update hover target + panel-active flag via event delegation on document
  document.addEventListener('mouseover', (e) => {
    const leftPanel = document.getElementById('wa-left');
    if (!leftPanel || !leftPanel.contains(e.target)) return;
    _waLeftActive = true;
    const item = e.target.closest('.wa-file-item');
    if (item && item.dataset.path) {
      const path = item.dataset.path;
      const name = item.querySelector('.wa-file-label')?.textContent?.trim()
                   || path.split(/[\\/]/).pop();
      const isFolder = item.classList.contains('folder');
      const supported = item.dataset.supported !== 'false';
      _fsBrowserCtxTarget = { path, name, isFolder, supported };
    }
  });

  document.addEventListener('mouseout', (e) => {
    const leftPanel = document.getElementById('wa-left');
    if (!leftPanel) return;
    // Only deactivate when mouse truly leaves the panel
    if (leftPanel.contains(e.target) && !leftPanel.contains(e.relatedTarget)) {
      _waLeftActive = false;
    }
  });

  // Keep _waLeftActive when user clicks inside left panel (so keyboard works
  // even after moving the mouse slightly outside, VS Code-style)
  document.addEventListener('click', (e) => {
    const leftPanel = document.getElementById('wa-left');
    if (!leftPanel) return;
    if (leftPanel.contains(e.target)) {
      _waLeftActive = true;
    } else if (!e.target.closest('#wa-ctx-menu')) {
      _waLeftActive = false;
    }
  });

  // Keyboard handler — fires when panel is active and no input is focused
  document.addEventListener('keydown', (e) => {
    if (!_waLeftActive) return;
    // Don't intercept when the user is typing in an input / rename field
    const focused = document.activeElement;
    if (focused && (
      focused.tagName === 'INPUT' ||
      focused.tagName === 'TEXTAREA' ||
      focused.isContentEditable ||
      focused.classList.contains('wa-rename-input')
    )) return;

    const { path, isFolder, supported } = _fsBrowserCtxTarget;

    // Ctrl+C — Copy
    if ((e.ctrlKey || e.metaKey) && e.key === 'c' && path) {
      e.preventDefault();
      WA._fsBrowserCopy();
      return;
    }
    // Ctrl+X — Cut
    if ((e.ctrlKey || e.metaKey) && e.key === 'x' && path) {
      e.preventDefault();
      WA._fsBrowserCut();
      return;
    }
    // Ctrl+V — Paste
    if ((e.ctrlKey || e.metaKey) && e.key === 'v') {
      if (!state._fsClipboard) return;
      e.preventDefault();
      WA._fsBrowserPaste();
      return;
    }
    // F2 — Rename
    if (e.key === 'F2' && path) {
      e.preventDefault();
      WA._fsBrowserRename();
      return;
    }
    // Delete — Delete
    if (e.key === 'Delete' && path) {
      e.preventDefault();
      WA._fsBrowserDelete();
      return;
    }
    // Enter — Open file (not folders)
    if (e.key === 'Enter' && path && !isFolder) {
      e.preventDefault();
      WA._fsBrowserOpen();
      return;
    }
    // Ctrl+D — Duplicate (copy then paste into same folder)
    if ((e.ctrlKey || e.metaKey) && e.key === 'd' && path) {
      e.preventDefault();
      WA._fsBrowserCopy();
      // Paste into the same folder immediately
      setTimeout(() => WA._fsBrowserPaste(), 50);
      return;
    }
    // Ctrl+Shift+C — Copy path to clipboard
    if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key === 'C' && path) {
      e.preventDefault();
      WA._fsBrowserCopyPath();
      return;
    }
  });

})();
