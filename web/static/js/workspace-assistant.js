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
    filePath: null,      // task/tool-accessible path (workspace path or session temp path)
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
    lockedModel: localStorage.getItem('wa_locked_model') === 'local' ? 'local' : 'auto',  // local or auto only
    _streamAbortCtrl: null,  // AbortController for the active AI task stream
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
    _livePollTimer: null,      // setInterval handle for live folder refresh
    aiDisplayMode: localStorage.getItem('wa_ai_display_mode') || 'panel', // 'panel' | 'inline'
    _availableModels: [],
    _modelMap: {},
    _modelsReady: false,
    _modelCatalogPromise: null,
    _activeRoute: null,
    useAgentMode: localStorage.getItem('wa_use_agent') !== 'off',  // P0: enable agent ReAct loop
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

    // Hide floating toolbars that may be visible from the previous tab's selection
    const _tt = $('wa-pdf-tooltip');
    if (_tt) _tt.style.display = 'none';
    _hideDocxHoverBar();
    const _pptxHb = $('wa-pptx-hoverbar');
    if (_pptxHb) _pptxHb.style.display = 'none';
    // Close find bars from previous tab
    const _dfb = $('wa-docx-find-bar'); if (_dfb) _dfb.style.display = 'none';
    const _pfb = $('wa-pptx-find-bar'); if (_pfb) _pfb.style.display = 'none';

    // Serialize + cache current tab before switching
    if (state.activeEditor && state.activeTabPath) {
      const curTab = state.openTabs.find(t => t.path === state.activeTabPath);
      if (curTab && state.fileType !== 'pdf') {
        const serialized = _serializeEditorForTab(curTab, state.activeEditor);
        if (curTab.fileType !== 'docx') curTab.cache = serialized;
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
    state.filePath = tab.filePath || tab.path || null;
    state.wsSourcePath = tab.path;

    const fileNameEl = $('wa-file-name');
    if (fileNameEl) fileNameEl.textContent = tab.name;
    _syncPrimarySaveButtons(tab);
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
      // Use cache if it has real content, otherwise fall back to server HTML
      const _freshData = tab.cache;
      const docxHtml = (_freshData && typeof _freshData === 'string' && _freshData.replace(/<p><\/p>/gi,'').trim()) ? _freshData : tab.serverData.html;
      await _mountDocxEditor(tab, docxHtml, tab.serverData);
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
    } else if (tab.fileType === 'image') {
      state.activeEditor = new KotoImageViewer();
      state.activeEditor.render(tab.serverData.raw_url);
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
      state.filePath = null;
      state.wsSourcePath = null;
      const fileNameEl = $('wa-file-name');
      if (fileNameEl) fileNameEl.textContent = '全格式 AI 工作区';
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
    const isReady = () => {
      const el = document.getElementById(containerId);
      return !!(el && el.offsetWidth > 0 && el.offsetHeight > 0);
    };
    if (isReady()) return Promise.resolve();
    return new Promise((resolve) => {
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
  const _FOLDER_OPEN_SVG = `<svg viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg"><path d="M1.5 4a1 1 0 0 1 1-1H5.6l1.2 1.5H13.5a1 1 0 0 1 1 1v6a1 1 0 0 1-1 1h-11a1 1 0 0 1-1-1V4z" fill="#5b9bd5"/><path d="M1.5 6.5h13" stroke="white" stroke-width="0.5" opacity="0.35"/></svg>`;
  const _FOLDER_SVG = `<svg viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg"><path d="M1.5 4a1 1 0 0 1 1-1H5.6l1.2 1.5H13.5a1 1 0 0 1 1 1v6a1 1 0 0 1-1 1h-11a1 1 0 0 1-1-1V4z" fill="#4a8fc4"/></svg>`;
  function _fileIcon(ext, category) { return _resolveFileIcon(ext, category); }

  // ── Unified SVG icon system (16×16, 1.5px stroke, currentColor) ──────────
  const _IC = (d, vb = '0 0 16 16') => `<svg viewBox="${vb}" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" xmlns="http://www.w3.org/2000/svg">${d}</svg>`;
  const _IC20 = (d) => _IC(d, '0 0 20 20');
  const _SUN_SVG = _IC(`<circle cx="8" cy="8" r="3"/><path d="M8 1.5v2M8 12.5v2M1.5 8h2M12.5 8h2M3.4 3.4l1.4 1.4M11.2 11.2l1.4 1.4M3.4 12.6l1.4-1.4M11.2 4.8l1.4-1.4"/>`);
  const _MOON_SVG = _IC(`<path d="M13.5 8.5a5.5 5.5 0 1 1-6-6 4 4 0 0 0 6 6z"/>`);
  const _PENCIL_SVG = _IC(`<path d="M11.5 1.5l3 3L5 14H2v-3L11.5 1.5z"/>`);
  const _SEND_SVG = `<svg width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>`;
  const _CHAT_SVG = _IC(`<path d="M2 3h12a1 1 0 0 1 1 1v7a1 1 0 0 1-1 1H5l-3 3V4a1 1 0 0 1 1-1z"/>`);
  const _PAUSE_SVG = _IC(`<rect x="4.25" y="3" width="2.25" height="10" rx="0.8"/><rect x="9.5" y="3" width="2.25" height="10" rx="0.8"/>`);
  const _PIN_SVG = _IC(`<path d="M5 2.5l6 0 0 4.5-1.5 1.5V11H6.5V8.5L5 7z"/><path d="M8 11v3.5"/>`);
  const _TRASH_SVG = _IC(`<path d="M3 4h10M6.5 4V2.5h3V4M5 4v9h6V4"/><path d="M7 7v3.5M9 7v3.5"/>`);
  const _CHART_SVG = _IC(`<rect x="2" y="9" width="3" height="5" rx="0.5"/><rect x="6.5" y="5" width="3" height="9" rx="0.5"/><rect x="11" y="2" width="3" height="12" rx="0.5"/>`);
  const _CLIPBOARD_SVG = _IC(`<rect x="3" y="2" width="10" height="12" rx="1.5"/><path d="M6 2V1h4v1"/><path d="M5.5 6h5M5.5 8.5h5M5.5 11h3"/>`);
  const _SLIDES_SVG = _IC(`<rect x="1.5" y="3" width="13" height="10" rx="1.5"/><path d="M5 7h6M5 9.5h4"/>`);
  const _DOC_SVG = _IC(`<path d="M4 1.5h5.5L13 5v9.5a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1v-13a1 1 0 0 1 1-1z"/><path d="M9.5 1.5V5H13"/><path d="M5.5 8h5M5.5 10.5h3.5"/>`);
  const _CONTRACT_SVG = _IC(`<path d="M4 1.5h8a1 1 0 0 1 1 1v11a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1v-11a1 1 0 0 1 1-1z"/><path d="M5.5 5h5M5.5 7.5h5M5.5 10h3"/><path d="M9 12.5c1-1 2.5-.5 2.5-.5"/>`);
  const _ROBOT_SVG = _IC(`<rect x="3.5" y="4" width="9" height="8" rx="2"/><circle cx="6" cy="8" r="1" fill="currentColor" stroke="none"/><circle cx="10" cy="8" r="1" fill="currentColor" stroke="none"/><path d="M8 1.5v2.5"/><circle cx="8" cy="1.5" r="0.8" fill="currentColor" stroke="none"/><path d="M1.5 8h2M12.5 8h2"/>`);
  const _REFRESH_SVG = _IC(`<path d="M2.5 8a5.5 5.5 0 0 1 9.9-3.2M13.5 8a5.5 5.5 0 0 1-9.9 3.2"/><path d="M12.4 1.5v3.3h-3.3M3.6 14.5v-3.3h3.3"/>`);
  const _MIC_SVG = _IC(`<rect x="5.5" y="2" width="5" height="8" rx="2.5"/><path d="M3 9a5 5 0 0 0 10 0"/><path d="M8 14v1.5"/>`);
  const _BOOKS_SVG = _IC(`<path d="M2 3h3v10H2zM5 3h3v10H5zM8.5 3.5l3-.8 2.6 9.8-3 .8z"/>`);
  const _TAG_SVG = _IC(`<path d="M1.5 2h6l7 6.5-5 5-7-6.5V2z"/><circle cx="4.5" cy="5" r="1" fill="currentColor" stroke="none"/>`);
  const _LIGHTBULB_SVG = _IC(`<path d="M5.5 13.5h5M6 11.5h4"/><path d="M5 9.5C3.5 8.5 3 7 3.5 5.3A4.5 4.5 0 0 1 8 2.5a4.5 4.5 0 0 1 4.5 2.8c.5 1.7 0 3.2-1.5 4.2"/>`);
  const _STOP_SVG = _IC(`<rect x="3" y="3" width="10" height="10" rx="2"/>`);
  const _SORT_SVG = _IC(`<path d="M4 5l4-3 4 3M4 11l4 3 4-3"/>`);
  const _FOLDER_PICK_SVG = _IC(`<path d="M1.5 4a1 1 0 0 1 1-1H5.6l1.2 1.5H13.5a1 1 0 0 1 1 1v6a1 1 0 0 1-1 1h-11a1 1 0 0 1-1-1V4z"/>`);
  const _DOWNLOAD_SVG = _IC(`<path d="M8 2v8.5M4.5 8L8 11.5 11.5 8"/><path d="M2.5 12.5h11"/>`);
  const _CLOUD_UP_SVG = _IC(`<path d="M4 11a3.5 3.5 0 0 1-.5-7A5 5 0 0 1 13 5.5a3 3 0 0 1-.5 6H4z"/><path d="M8 7v5M6 9l2-2 2 2"/>`);
  const _SETTINGS_SVG = _IC(`<circle cx="8" cy="8" r="2"/><path d="M8 1.5v2M8 12.5v2M1.5 8h2M12.5 8h2M3.4 3.4l1.4 1.4M11.2 11.2l1.4 1.4M3.4 12.6l1.4-1.4M11.2 4.8l1.4-1.4"/>`);
  const _CLEAR_CHAT_SVG = _IC(`<path d="M3 4h10M6.5 4V2.5h3V4M5 4v9h6V4"/>`);
  const _MORE_SVG = _IC(`<circle cx="4" cy="8" r="1" fill="currentColor" stroke="none"/><circle cx="8" cy="8" r="1" fill="currentColor" stroke="none"/><circle cx="12" cy="8" r="1" fill="currentColor" stroke="none"/>`);
  const _SEARCH_SVG = _IC(`<circle cx="7" cy="7" r="4.5"/><path d="M10.5 10.5L14 14"/>`);
  const _PLUS_SVG = _IC(`<path d="M8 3v10M3 8h10"/>`);
  const _UPLOAD_SVG = _IC(`<path d="M8 10V2.5M4.5 5.5L8 2l3.5 3.5"/><path d="M2.5 11v2.5h11V11"/>`);
  const _FILE_PLUS_SVG = _IC(`<path d="M4 1.5h5.5L13 5v9.5a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1v-13a1 1 0 0 1 1-1z"/><path d="M9.5 1.5V5H13"/><path d="M8 8v4M6 10h4"/>`);
  const _FOLDER_PLUS_SVG = _IC(`<path d="M1.5 4a1 1 0 0 1 1-1H5.6l1.2 1.5H13.5a1 1 0 0 1 1 1v6a1 1 0 0 1-1 1h-11a1 1 0 0 1-1-1V4z"/><path d="M8 6.5v4M6 8.5h4"/>`);

  const _EXT_ICON = {
    'docx': _FILE_SVGS.docx,
    'xlsx': _FILE_SVGS.xlsx,
    'pptx': _FILE_SVGS.pptx,
    'pdf':  _FILE_SVGS.pdf
  };
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
    const isInWorkspace = workspacePath && (normalizedPath.startsWith(workspacePath + '/') || normalizedPath === workspacePath);
    if (isInWorkspace) {
      // Derive relative path within workspace
      const rel = normalizedPath.slice(workspacePath.length).replace(/^\//, '');
      WA.openWorkspaceFile(rel);
      return;
    }
    // External file — use openBrowserFile (fetches bytes via serve_abs, then parses)
    // open_file_by_path only accepts workspace-relative paths and will 403 on absolute paths
    const _reqExt = filePath.split('.').pop().toLowerCase();
    WA.openBrowserFile(filePath, _isSupportedExt(_reqExt));
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
    if (!wrap || !list) return;
    const n = state._aiFileContext.length;
    const tIdx = state._aiTargetFileIdx;
    const targetFile = (tIdx >= 0 && tIdx < n) ? state._aiFileContext[tIdx] : null;

    if (!n) {
      wrap.style.display = 'none';
      // Clear AI-queued markers on file tree items
      document.querySelectorAll('.wa-file-item.ai-queued').forEach(el => el.classList.remove('ai-queued'));
      _restoreDefaultQuickActions();
      // Restore file context indicator now that no docs are attached
      _updateContextBar();
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
    _hideWelcome();  // hide welcome card once files are attached
    list.innerHTML = state._aiFileContext.map((f, i) => {
      const isTarget = (i === tIdx);
      const isLoading = !!f.loading;
      const icon = _fileIcon(f.name.split('.').pop() || '');
      const chars = f.originalChars != null ? f.originalChars : (f.content || '').length;
      const sizeLabel = isLoading ? '读取中…' : (chars < 1000 ? chars + ' 字' : (chars / 1000).toFixed(1) + 'k字');
      const pinTitle = isTarget ? '取消目标文件' : '设为修改目标文件';
      return `<div class="wa-ctx-file-row${isTarget ? ' ai-target' : ''}${isLoading ? ' loading' : ''}" title="${_escHtml(f.path)}">` +
        `<span class="ctx-row-icon">${icon}</span>` +
        `<span class="ctx-row-name">${_escHtml(f.name)}</span>` +
        `<span class="ctx-row-size">${sizeLabel}</span>` +
        (isLoading ? '' : `<button class="ctx-row-pin${isTarget ? ' active' : ''}" onclick="WA.setAITargetFile(${i})" title="${pinTitle}">${_PIN_SVG}</button>`) +
        (isLoading ? '' : `<span class="ctx-row-remove" onclick="WA.removeAIFileContext(${i})" title="移除">×</span>`) +
        `</div>`;
    }).join('');

    // Update context bar with file count
    _updateContextBar({ files: n });

    // Update quick-action bar for multi-doc mode
    if (n >= 2) {
      _renderMultiDocQuickActions(n, targetFile);
    } else {
      _restoreDefaultQuickActions();
    }

    // Mark queued files in the browser file tree
    document.querySelectorAll('.wa-file-item.ai-queued').forEach(el => el.classList.remove('ai-queued'));
    state._aiFileContext.forEach(f => {
      const el = document.querySelector(`.wa-file-item[data-path="${CSS.escape(f.path)}"]`);
      if (el) el.classList.add('ai-queued');
    });

  }
  function _renderMultiDocQuickActions(n, targetFile) {
    const bar = ($('wa-actions-bar') || $('wa-quick-actions'));
    if (!bar) return;
    const tName = targetFile ? targetFile.name : null;
    const btns = [
      { label: `${_CHART_SVG} 对比差异`, prompt: `请对比这${n}份文件的主要内容差异，列出相同点和不同点` },
      { label: `${_SEARCH_SVG} 查找引用`, prompt: `请分析这${n}份文件之间是否存在引用或描述关系，列出具体对应内容` },
      {
        label: tName ? `${_PENCIL_SVG} 同步到 ${tName}` : `${_PENCIL_SVG} 同步内容`,
        prompt: tName
          ? `请分析参考文件中有哪些内容需要同步更新到目标文件"${tName}"中，给出具体的逐条修改建议`
          : `请分析这${n}份文件中有哪些内容需要互相同步更新，给出具体修改建议`
      },
      { label: `${_CLIPBOARD_SVG} 综合摘要`, prompt: `请综合这${n}份文件的核心内容，生成一份结构化摘要` },
    ];
    bar.innerHTML = btns.map(b =>
      `<button class="wa-quick-btn multi-doc" data-prompt="${_escHtml(b.prompt)}">${b.label}</button>`
    ).join('');
    bar.querySelectorAll('.wa-quick-btn.multi-doc').forEach(btn => {
      btn.addEventListener('click', () => WA.quickAction(btn.dataset.prompt));
    });
    // Append context-aware workflow chips for multi-doc mode
    // (workflows are already shown as suggestion cards in chat area; skip chips here)
  }

  // Restore the default single-doc quick-action buttons
  function _restoreDefaultQuickActions() {
    const bar = ($('wa-actions-bar') || $('wa-quick-actions'));
    if (!bar || !bar.querySelector('.wa-quick-btn.multi-doc')) return; // nothing to restore
    bar.innerHTML =
      `<button class="wa-quick-btn" onclick="WA.quickAction('请帮我润色当前内容，保留原意但让表达更顺滑')">润色表达</button>` +
      `<button class="wa-quick-btn" onclick="WA.quickAction('请帮我总结当前内容，提炼重点和待办事项')">提炼要点</button>` +
      `<button class="wa-quick-btn" onclick="WA.quickAction('请检查当前内容中的语病、歧义和逻辑风险')">检查问题</button>` +
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
        // Format-specific text extraction to avoid counting styling/metadata/base64 as chars
        const _extractStructuredText = (d) => {
          // PPTX: { slides: [{ shapes: [{ paragraphs: [{ runs: [{ text }] }], rows?: [[{paragraphs}]] }] }] }
          if (Array.isArray(d.slides)) {
            const parts = [];
            for (const slide of d.slides) {
              for (const shape of (slide.shapes || [])) {
                for (const para of (shape.paragraphs || [])) {
                  for (const run of (para.runs || [])) { if (run.text) parts.push(run.text); }
                }
                for (const row of (shape.rows || [])) {
                  for (const cell of (row || [])) {
                    for (const para of (cell.paragraphs || [])) {
                      for (const run of (para.runs || [])) { if (run.text) parts.push(run.text); }
                    }
                  }
                }
              }
            }
            return parts.join(' ');
          }
          // XLSX: { sheets: { id: { cellData: { row: { col: { v } } } } } }
          if (d.sheets && typeof d.sheets === 'object') {
            const parts = [];
            for (const sheet of Object.values(d.sheets)) {
              for (const row of Object.values(sheet.cellData || {})) {
                for (const cell of Object.values(row)) {
                  if (cell.v != null) parts.push(String(cell.v));
                }
              }
            }
            return parts.join(' ');
          }
          // Generic fallback: skip base64 / URLs / long encoded strings
          const parts = [];
          const walk = (v) => {
            if (typeof v === 'string' && v.length < 300 && !/^data:|^https?:|^[A-Za-z0-9+/]{50,}/.test(v)) { parts.push(v); }
            else if (Array.isArray(v)) { v.forEach(walk); }
            else if (v && typeof v === 'object') { Object.values(v).forEach(walk); }
          };
          walk(d);
          return parts.join(' ');
        };
        content = _extractStructuredText(data.data);
        if (!content.trim()) content = JSON.stringify(data.data).substring(0, 8000);
      }
      const originalChars = content.length;
      content = _waSampleTaskContext(content);
      // Replace the loading placeholder with real content
      const placeholder = state._aiFileContext.find(f => f.path === absPath);
      if (placeholder) { placeholder.content = content; placeholder.originalChars = originalChars; delete placeholder.loading; }
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
    const s = new Set(['docx','doc','xlsx','xls','pptx','ppt','pdf','txt','md','markdown',
      'png','jpg','jpeg','gif','bmp','webp','svg']);
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
    const list = $('wa-files-list');
    const savedScroll = list ? list.scrollTop : 0;
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
    if (list) requestAnimationFrame(() => { list.scrollTop = savedScroll; });
  }

  /**
   * Live-poll expanded folders for changes every 3 s.
   * Silently updates the cache and re-renders only when entries actually differ.
   */
  let _livePollRunning = false;
  async function _livePollTick() {
    if (_livePollRunning || state._searchActive) return;
    const expanded = Array.from(state._browserExpanded);
    if (!expanded.length) return;
    _livePollRunning = true;
    try {
      let changed = false;
      await Promise.all(expanded.map(async absPath => {
        try {
          const r = await fetch('/api/v1/workspace/browse_local?path=' + encodeURIComponent(absPath));
          if (!r.ok) return;
          const data = await r.json();
          const fresh = data.entries || [];
          const prev = state._browserCache[absPath];
          if (prev === 'loading') return;
          // Compare by stringifying name+mtime pairs (cheap structural check)
          const key = e => e.name + ':' + (e.mtime || 0);
          const prevKey = Array.isArray(prev) ? prev.map(key).join('|') : '';
          const freshKey = fresh.map(key).join('|');
          if (prevKey !== freshKey) { state._browserCache[absPath] = fresh; changed = true; }
        } catch (_) {}
      }));
      if (changed) _renderBrowserTree();
    } finally {
      _livePollRunning = false;
    }
  }

  function _startLivePoll() {
    if (state._livePollTimer) return;
    state._livePollTimer = setInterval(_livePollTick, 3000);
  }

  function _stopLivePoll() {
    if (!state._livePollTimer) return;
    clearInterval(state._livePollTimer);
    state._livePollTimer = null;
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
    requestAnimationFrame(() => { list.scrollTop = _savedScroll; });
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
        `oncontextmenu="event.preventDefault();event.stopPropagation();WA._showBrowserCtx(event,this)" ` +
        `ondragover="event.preventDefault();event.stopPropagation();this.classList.add('wa-drop-target')" ` +
        `ondragleave="this.classList.remove('wa-drop-target')" ` +
        `ondrop="event.preventDefault();event.stopPropagation();this.classList.remove('wa-drop-target');WA._dropOntoFolder(event,this.dataset.path)">` +
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
      if (!state._browserExpanded.size) _stopLivePoll();
      return;
    }
    state._browserExpanded.add(absPath);
    _startLivePoll();
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
    setLoading(true, `正在打开 ${baseName}…`);
    $('upload-progress').style.width = '30%';
    try {
      // Server-side parse — avoids downloading the entire file to the browser.
      // The old serve_abs → blob → Router.load path would cause memory crashes
      // on large files (e.g. PPTX with embedded video).
      const res = await fetch('/api/v1/workspace/open_abs_file', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: absPath }),
      });
      const json = await _safeJson(res);
      if (!res.ok) throw new Error(json.error || 'HTTP ' + res.status);
      $('upload-progress').style.width = '100%';
      await _applyFileJson(json, absPath, null);
      loadRecentFiles();
      _renderBrowserTree();     // refresh active highlight
    } catch (e) { showToast('无法打开文件: ' + e.message, 'error'); }
    finally { setLoading(false); $('upload-progress').style.width = '0%'; }
  };

  /**
   * Handle a drop event onto a folder row.
   * Supports two drop modes:
   *   1. Internal tree drag  — dataTransfer contains 'application/wa-file-path'
   *      → copies the file into the folder via /api/v1/workspace/fs_copy
   *   2. External OS drag    — dataTransfer.files contains file data
   *      → uploads files into the folder via /api/v1/workspace/upload-to-folder
   */
  window.WA._dropOntoFolder = async (event, destPath) => {
    const srcPath = event.dataTransfer.getData('application/wa-file-path');
    if (srcPath) {
      // ── Internal copy ──
      try {
        const r = await fetch('/api/v1/workspace/fs_copy', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ src: srcPath, dst_dir: destPath, move: false }),
        });
        const d = await r.json();
        if (!r.ok) { showToast(d.error || '复制失败', 'error'); return; }
        showToast(`已复制到 ${destPath.split(/[\\/]/).pop()}`, 'success');
      } catch (e) { showToast('复制出错: ' + e.message, 'error'); return; }
    } else if (event.dataTransfer.files && event.dataTransfer.files.length) {
      // ── External OS file drop ──
      const fd = new FormData();
      fd.append('dest_dir', destPath);
      for (const f of event.dataTransfer.files) fd.append('file', f);
      try {
        const r = await fetch('/api/v1/workspace/upload-to-folder', { method: 'POST', body: fd });
        const d = await r.json();
        if (!r.ok) { showToast(d.error || '上传失败', 'error'); return; }
        const names = (d.saved || []).map(s => s.name).join(', ');
        showToast(`已加入：${names}`, 'success');
      } catch (e) { showToast('上传出错: ' + e.message, 'error'); return; }
    } else { return; }
    // Refresh the target folder
    state._browserCache[destPath] = null;
    if (state._browserExpanded.has(destPath)) {
      try {
        const r = await fetch('/api/v1/workspace/browse_local?path=' + encodeURIComponent(destPath));
        state._browserCache[destPath] = r.ok ? (await r.json()).entries || [] : [];
      } catch (_) { state._browserCache[destPath] = []; }
    }
    _renderBrowserTree();
  };

  // ── File-browser context menu ─────────────────────────────────────────────
  let _fsBrowserCtxTarget = { path: null, name: null, isFolder: false, supported: true };

  function _cloneSerializable(value, fallback = null) {
    try {
      return JSON.parse(JSON.stringify(value));
    } catch (_) {
      return fallback;
    }
  }

  function _getDocxRenderOpts(docxData) {
    const data = (docxData && typeof docxData === 'object') ? docxData : {};
    return {
      pageHeightPx:   data.page_height_px   || null,
      pageWidthPx:    data.page_width_px    || null,
      marginTopPx:    data.margin_top_px    || null,
      marginBottomPx: data.margin_bottom_px || null,
      marginLeftPx:   data.margin_left_px   || null,
      marginRightPx:  data.margin_right_px  || null,
      headerHtml:     data.header_html      || '',
      footerHtml:     data.footer_html      || '',
      sections:       Array.isArray(data.sections) ? _cloneSerializable(data.sections, []) : [],
    };
  }

  function _syncDocxOutlineAfterMount(headings) {
    if (Array.isArray(headings)) {
      _setupDocOutline(headings);
      return;
    }
    setTimeout(() => _setupDocOutline([]), 300);
  }

  async function _mountDocxEditor(tab, html, docxData, headings) {
    await _ensureTipTap();
    _ensureDocxProgressiveState(tab);
    state.activeEditor = new KotoDocxEditorLib.KotoTipTapEditor();
    state.activeEditor.render(typeof html === 'string' ? html : '', _getDocxRenderOpts(docxData));
    _syncActiveDocxProgressiveUi(tab);
    _startDocxProgressiveHydration(tab);
    _syncDocxOutlineAfterMount(headings);
    return state.activeEditor;
  }

  function _getDocxProgressiveMeta(docxData) {
    const progressive = docxData && typeof docxData === 'object' ? docxData.progressive : null;
    if (!progressive || typeof progressive !== 'object' || progressive.pending !== true) return null;
    return progressive;
  }

  function _ensureDocxProgressiveState(tab) {
    if (!tab || tab.fileType !== 'docx') return null;
    const meta = _getDocxProgressiveMeta(tab.serverData);
    const existing = (tab._docxProgressive && typeof tab._docxProgressive === 'object') ? tab._docxProgressive : {};
    if (meta) {
      tab._docxProgressive = {
        loading: !!existing.loading,
        complete: !!existing.complete,
        error: existing.error || '',
        promise: existing.promise || null,
        targetPages: meta.target_pages || existing.targetPages || 3,
      };
    } else {
      tab._docxProgressive = {
        loading: false,
        complete: true,
        error: '',
        promise: null,
        targetPages: existing.targetPages || 3,
      };
    }
    return tab._docxProgressive;
  }

  function _isDocxProgressivePendingTab(tab) {
    if (!tab || tab.fileType !== 'docx') return false;
    const progressive = _ensureDocxProgressiveState(tab);
    return !!(progressive && !progressive.complete);
  }

  function _syncPrimarySaveButtons(tab) {
    const activeTab = tab || state.openTabs.find(t => t.path === state.activeTabPath) || null;
    const activeType = activeTab ? activeTab.fileType : state.fileType;
    const disabled = (
      activeType === 'pdf' ||
      activeType === 'image' ||
      _isDocxProgressivePendingTab(activeTab)
    );
    const saveBtn = $('wa-save-btn');
    if (saveBtn) saveBtn.disabled = disabled;
    const saveAsBtn = $('wa-saveas-btn');
    if (saveAsBtn) saveAsBtn.disabled = disabled;
  }

  function _setDocxProgressiveBanner(message, kind) {
    const host = $('wa-docx-editor');
    if (!host) return;
    let banner = host.querySelector('.wa-docx-progressive-banner');
    if (!message) {
      if (banner) banner.remove();
      return;
    }
    if (!banner) {
      banner = document.createElement('div');
      banner.className = 'wa-docx-progressive-banner';
      banner.style.cssText = 'margin:8px 12px 0;padding:8px 12px;border-radius:8px;font-size:12px;line-height:1.4;';
      const anchor = host.querySelector('#wa-editor-content');
      host.insertBefore(banner, anchor || host.firstChild || null);
    }
    banner.textContent = message;
    if (kind === 'error') {
      banner.style.background = 'rgba(220, 38, 38, 0.12)';
      banner.style.border = '1px solid rgba(248, 113, 113, 0.38)';
      banner.style.color = '#fecaca';
    } else {
      banner.style.background = 'rgba(59, 130, 246, 0.12)';
      banner.style.border = '1px solid rgba(96, 165, 250, 0.28)';
      banner.style.color = '#dbeafe';
    }
  }

  function _syncActiveDocxProgressiveUi(tab) {
    if (!tab || tab.fileType !== 'docx' || state.activeTabPath !== tab.path || state.fileType !== 'docx') {
      return;
    }
    const progressive = _ensureDocxProgressiveState(tab);
    const isLocked = !!(progressive && !progressive.complete);
    if (state.activeEditor && state.activeEditor.editor && typeof state.activeEditor.editor.setEditable === 'function') {
      state.activeEditor.editor.setEditable(!isLocked);
    }
    if (isLocked) {
      const msg = progressive.error
        ? 'DOCX 完整内容加载失败，请重新打开文档重试。'
        : `已先渲染前 ${progressive.targetPages || 3} 页，正在后台加载剩余内容，加载完成后即可编辑。`;
      _setDocxProgressiveBanner(msg, progressive.error ? 'error' : 'loading');
    } else {
      _setDocxProgressiveBanner('', 'done');
    }
    _syncPrimarySaveButtons(tab);
  }

  function _ensureDocxCanSave(tab, notify) {
    if (_isDocxProgressivePendingTab(tab)) {
      if (notify) showToast('DOCX 仍在后台加载剩余内容，请稍后再保存。', 'warning');
      return false;
    }
    return true;
  }

  async function _startDocxProgressiveHydration(tab) {
    if (!tab || tab.fileType !== 'docx') return null;
    const meta = _getDocxProgressiveMeta(tab.serverData);
    const progressive = _ensureDocxProgressiveState(tab);
    if (!meta) {
      progressive.complete = true;
      progressive.loading = false;
      progressive.error = '';
      progressive.promise = null;
      _syncActiveDocxProgressiveUi(tab);
      return null;
    }
    if (progressive.complete) {
      _syncActiveDocxProgressiveUi(tab);
      return progressive.promise;
    }
    if (progressive.promise) {
      _syncActiveDocxProgressiveUi(tab);
      return progressive.promise;
    }

    progressive.loading = true;
    progressive.error = '';
    _syncActiveDocxProgressiveUi(tab);

    progressive.promise = (async () => {
      try {
        const res = await fetch('/api/v1/workspace/docx_full', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ file_id: tab.fileId }),
        });
        const json = await _safeJson(res);
        if (!res.ok) throw new Error(json.error || 'DOCX 完整加载失败');

        const fullData = (json && json.data && typeof json.data === 'object') ? json.data : {};
        tab.serverData = fullData;
        tab.cache = null;
        progressive.complete = true;
        progressive.loading = false;
        progressive.error = '';
        progressive.promise = null;

        if (state.activeTabPath === tab.path && state.fileType === 'docx' && state.activeEditor) {
          const scrollEl = $('wa-editor-content');
          const prevScrollTop = scrollEl ? scrollEl.scrollTop : 0;
          state.activeEditor.render(fullData.html || '', _getDocxRenderOpts(fullData));
          requestAnimationFrame(() => {
            const nextScrollEl = $('wa-editor-content');
            if (nextScrollEl) {
              const maxScroll = Math.max(0, nextScrollEl.scrollHeight - nextScrollEl.clientHeight);
              nextScrollEl.scrollTop = Math.min(prevScrollTop, maxScroll);
            }
          });
          _setupDocOutline(fullData.headings || []);
        }
      } catch (err) {
        progressive.loading = false;
        progressive.complete = false;
        progressive.error = String((err && err.message) || err || 'DOCX 完整加载失败');
        progressive.promise = null;
        console.error('[WA DOCX progressive]', err);
        if (state.activeTabPath === tab.path && state.fileType === 'docx') {
          showToast(progressive.error, 'error');
        }
      } finally {
        _syncActiveDocxProgressiveUi(tab);
      }
      return null;
    })();

    return progressive.promise;
  }

  function _cacheDocxTabState(tab, payload) {
    if (!tab || tab.fileType !== 'docx' || !payload || typeof payload !== 'object') return;
    const html = typeof payload.html === 'string' ? payload.html : '';
    const docxData = (tab.serverData && typeof tab.serverData === 'object') ? tab.serverData : {};
    tab.cache = html;
    docxData.html = html;
    docxData.header_html = typeof payload.header_html === 'string' ? payload.header_html : '';
    docxData.footer_html = typeof payload.footer_html === 'string' ? payload.footer_html : '';
    docxData.sections = Array.isArray(payload.sections) ? _cloneSerializable(payload.sections, []) : [];
    if (Object.prototype.hasOwnProperty.call(payload, 'page_width_px')) docxData.page_width_px = payload.page_width_px;
    if (Object.prototype.hasOwnProperty.call(payload, 'page_height_px')) docxData.page_height_px = payload.page_height_px;
    if (Object.prototype.hasOwnProperty.call(payload, 'margin_top_px')) docxData.margin_top_px = payload.margin_top_px;
    if (Object.prototype.hasOwnProperty.call(payload, 'margin_bottom_px')) docxData.margin_bottom_px = payload.margin_bottom_px;
    if (Object.prototype.hasOwnProperty.call(payload, 'margin_left_px')) docxData.margin_left_px = payload.margin_left_px;
    if (Object.prototype.hasOwnProperty.call(payload, 'margin_right_px')) docxData.margin_right_px = payload.margin_right_px;
    tab.serverData = docxData;
  }

  function _serializeEditorForTab(tab, editor) {
    if (!editor || typeof editor.serialize !== 'function') return null;
    if (tab && tab.fileType === 'docx' && typeof editor.getDocxSavePayload === 'function') {
      const payload = editor.getDocxSavePayload();
      _cacheDocxTabState(tab, payload);
      return payload;
    }
    return editor.serialize();
  }

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
    _clampMenuPos(menu); // secondary pass using actual rendered rect
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
          state.fileId = null; state.fileType = null; state.fileName = null; state.filePath = null;
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
          state.filePath = null;
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
          const fileNameEl = $('wa-file-name');
          if (fileNameEl) fileNameEl.textContent = '全格式 AI 工作区';
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
    _clampMenuPos(menu); // secondary pass using actual rendered rect
  };

  function _closeCtxMenu() {
    const menu = document.getElementById('wa-ctx-menu');
    if (menu) menu.classList.remove('open');
  }
  // Expose for inline onclick handlers in context menu items
  window._closeCtxMenu = _closeCtxMenu;

  // Secondary clamp: reads the actual rendered rect after positioning and
  // corrects overflow in all directions. Handles cases where the pre-position
  // height measurement (scrollHeight/offsetHeight) returned 0 or was wrong.
  function _clampMenuPos(menu) {
    const r = menu.getBoundingClientRect();
    const vw2 = window.innerWidth, vh2 = window.innerHeight;
    let t = parseFloat(menu.style.top), l = parseFloat(menu.style.left);
    if (r.bottom > vh2 - 2) t = Math.max(4, t - (r.bottom - vh2 + 4));
    if (r.right  > vw2 - 2) l = Math.max(4, vw2 - r.width - 4);
    if (t < 4) t = 4;
    if (l < 4) l = 4;
    menu.style.top  = t + 'px';
    menu.style.left = l + 'px';
  }

  document.addEventListener('click', (e) => {
    // Don't close when clicking on a menu item — let the item's onclick fire first
    if (!e.target.closest('#wa-ctx-menu')) _closeCtxMenu();
  }, true);
  document.addEventListener('keydown', e => { if (e.key === 'Escape') _closeCtxMenu(); });
  // ── Global workspace keyboard shortcuts ────────────────────────────────────
  // Use capture:true so this fires BEFORE individual editors can call stopPropagation().
  // Guard: only intercept when the workspace panel is actually visible.
  document.addEventListener('keydown', e => {
    const ctrl = e.ctrlKey || e.metaKey;
    const wsView = document.getElementById('workspaceView');
    const wsVisible = wsView && wsView.style.display !== 'none' && !wsView.classList.contains('hidden');

    // ── Ctrl+S: Save ─────────────────────────────────────────────────────
    if (ctrl && e.key === 's' && !e.shiftKey) {
      if (!wsVisible) return;
      e.preventDefault(); e.stopPropagation();
      WA.saveFile();
      return;
    }

    // ── Ctrl+F: Find ─────────────────────────────────────────────────────
    if (ctrl && e.key === 'f' && !e.shiftKey) {
      if (!wsVisible || !state.fileType) return;
      e.preventDefault(); e.stopPropagation();
      _openFindBar(false);
      return;
    }

    // ── Ctrl+H: Find & Replace ───────────────────────────────────────────
    if (ctrl && e.key === 'h') {
      if (!wsVisible || !state.fileType) return;
      e.preventDefault(); e.stopPropagation();
      _openFindBar(true);
      return;
    }

    // ── Ctrl+W: Close active tab ─────────────────────────────────────────
    if (ctrl && e.key === 'w') {
      if (!wsVisible || !state.activeTabPath) return;
      e.preventDefault(); e.stopPropagation();
      WA._closeTab(state.activeTabPath);
      return;
    }

    // ── Ctrl+Tab / Ctrl+Shift+Tab: Cycle tabs ────────────────────────────
    if (ctrl && e.key === 'Tab') {
      if (!wsVisible || state.openTabs.length < 2) return;
      e.preventDefault(); e.stopPropagation();
      const cur = state.openTabs.findIndex(t => t.path === state.activeTabPath);
      const n = state.openTabs.length;
      const next = e.shiftKey ? (cur - 1 + n) % n : (cur + 1) % n;
      _switchToTab(state.openTabs[next].path);
      return;
    }

    // ── Ctrl+P: Print / Export ───────────────────────────────────────────
    if (ctrl && e.key === 'p') {
      if (!wsVisible || !state.fileType) return;
      e.preventDefault(); e.stopPropagation();
      // For PDF: use browser print on the PDF canvas; for others trigger save/download
      if (state.fileType === 'pdf' && state.activeEditor && state.activeEditor._printPdf) {
        state.activeEditor._printPdf();
      } else {
        WA.saveFile();
      }
      return;
    }

    // ── Escape: close find bars ───────────────────────────────────────────
    if (e.key === 'Escape') {
      const docxBar  = document.getElementById('wa-docx-find-bar');
      const pptxBar  = document.getElementById('wa-pptx-find-bar');
      if (docxBar  && docxBar.style.display  !== 'none') { e.stopPropagation(); WA.docxFindClose();  return; }
      if (pptxBar  && pptxBar.style.display  !== 'none') { e.stopPropagation(); WA.pptxFindClose();  return; }
    }
  }, true);

  // ── Find bar open dispatcher ────────────────────────────────────────────────
  function _openFindBar(replaceMode) {
    const ft = state.fileType;
    if (ft === 'docx') {
      const bar = document.getElementById('wa-docx-find-bar');
      if (bar) {
        bar.style.display = '';
        if (replaceMode) WA.docxToggleReplace(true);
        const inp = document.getElementById('wa-docx-find-input');
        if (inp) { inp.focus(); inp.select(); }
      }
    } else if (ft === 'pptx') {
      const bar = document.getElementById('wa-pptx-find-bar');
      if (bar) {
        bar.style.display = '';
        if (replaceMode) WA.pptxToggleReplace(true);
        const inp = document.getElementById('wa-pptx-find-input');
        if (inp) { inp.focus(); inp.select(); }
      }
    } else if (ft === 'pdf') {
      WA.pdfSearchOpen();
      if (replaceMode) showToast('PDF 不支持替换', 'info');
    } else if (ft === 'xlsx') {
      // Dispatch Ctrl+F to the Univer container so its built-in find triggers
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
    _clampMenuPos(menu); // secondary pass using actual rendered rect
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
    if (state.isLoading) { showToast('文件正在加载中，请稍候...', 'error'); return; }
    state.isLoading = true;
    setLoading(true, `正在打开 ${baseName}…`);
    $('upload-progress').style.width = '30%';
    try {
      const res = await fetch('/api/v1/workspace/open_file_by_path', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path }),
      });
      $('upload-progress').style.width = '80%';
      const json = await _safeJson(res);
      if (!res.ok) throw new Error(json.error || '打开失败');
      $('upload-progress').style.width = '100%';
      await _applyFileJson(json, path, null);
      loadRecentFiles();   // refresh recent list after successful open
    } catch (e) {
      console.error('[WA openWorkspaceFile]', e);
      showToast('无法打开文件: ' + e.message, 'error', 8000);
      $('upload-progress').style.width = '0%';
    } finally {
      state.isLoading = false;
      setLoading(false);
    }
  };

  window.WA.reloadFileByPath = async (filePath, supported = true) => {
    if (!filePath) return;
    const workspacePath = (state._workspacePath || '').replace(/\\/g, '/');
    const normalizedPath = String(filePath).replace(/\\/g, '/');
    const isInWorkspace = workspacePath && (
      normalizedPath.startsWith(workspacePath + '/') || normalizedPath === workspacePath
    );

    try {
      let res;
      let json;
      let wsPath = filePath;
      if (isInWorkspace) {
        const relativePath = normalizedPath.slice(workspacePath.length).replace(/^\//, '');
        res = await fetch('/api/v1/workspace/open_file_by_path', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path: relativePath }),
        });
        json = await _safeJson(res);
        wsPath = relativePath;
      } else {
        if (!supported) return;
        res = await fetch('/api/v1/workspace/open_abs_file', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path: filePath }),
        });
        json = await _safeJson(res);
        wsPath = filePath;
      }

      if (!res.ok) throw new Error(json.error || '刷新失败');
      await _applyFileJson(json, wsPath, null);
      loadRecentFiles();
      _renderBrowserTree();
    } catch (e) {
      console.warn('[WA reloadFileByPath]', e);
      throw e;
    }
  };

  // Expose a parsedFile handler so openRecentFile can mount responses directly.
  window.WA._openParsedFile = async (d, wsPath) => {
    if (state.isLoading) { showToast('文件正在加载中，请稍候...', 'error'); return; }
    state.isLoading = true;
    setLoading(true, `正在打开 ${d.file_name || '文件'}…`);
    try {
      await _applyFileJson(d, wsPath || d.file_name, null);
    } catch(e) {
      console.error('[WA _openParsedFile]', e);
      showToast(e.message, 'error');
    } finally {
      state.isLoading = false;
      setLoading(false);
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

  // ── Unified context bar — replaces wa-selection-chip + wa-context-indicator + wa-ai-attached-hint ──
  // opts: { selection?: string, files?: number, table?: string }
  // Call with no args to auto-detect from state; or pass overrides.
  function _updateContextBar(opts) {
    const bar = $('wa-context-bar');
    if (!bar) return;
    const nFiles = (opts && opts.files != null) ? opts.files : (state._aiFileContext ? state._aiFileContext.length : 0);
    const selText = (opts && opts.selection) || '';
    const tableInfo = (opts && opts.table) || '';

    const parts = [];

    // Selection preview
    if (selText) {
      const preview = selText.length > 60 ? selText.substring(0, 60) + '…' : selText;
      parts.push(`<span class="ctx-bar-sel">已选中：<b>${_escHtml(preview)}</b></span>`);
    } else if (tableInfo) {
      parts.push(`<span class="ctx-bar-sel">已选中：<b>${_escHtml(tableInfo)}</b></span>`);
    } else if (state.pinnedSelection) {
      const preview = state.pinnedSelection.length > 60 ? state.pinnedSelection.substring(0, 60) + '…' : state.pinnedSelection;
      parts.push(`<span class="ctx-bar-sel"><span class="ctx-bar-quote"></span>${_escHtml(preview)}<button class="ctx-bar-clear" onclick="WA.clearSelection()" title="取消选区">&times;</button></span>`);
    }

    // File context
    if (nFiles > 0) {
      parts.push(`<span class="ctx-bar-files">已附加 <b>${nFiles} 份文件</b><button class="ctx-bar-clear" onclick="WA.clearAIFileContext()" title="清除文件">&times;</button></span>`);
    }

    if (parts.length) {
      bar.innerHTML = parts.join('<span class="ctx-bar-sep">·</span>');
      bar.style.display = 'flex';
    } else {
      bar.innerHTML = '';
      bar.style.display = 'none';
    }
  }

  // Update the selection chip UI with new text (used in multiple places)
  function _pinSelectionChip(text) {
    state.pinnedSelection = text;
    const preview = text.length > 200 ? text.substring(0, 200) + '…' : text;

    // Update the unified context bar
    _updateContextBar();

    // Also pin in inline AI dialog's chip (if it exists)
    const iaiPreview = $('wa-iai-selection-preview');
    if (iaiPreview) iaiPreview.textContent = preview;
    const iaiChip = $('wa-iai-selection-chip');
    if (iaiChip) iaiChip.style.display = 'flex';
  }

  function _hasUsableDocxSelectionTarget() {
    if (state.fileType !== 'docx' || !state.activeEditor || !state.activeEditor.editor) {
      return false;
    }
    const editorHost = state.activeEditor;
    const selection = editorHost.editor.state && editorHost.editor.state.selection;
    if (selection && selection.from < selection.to) {
      return true;
    }
    const savedSel = editorHost._savedSel;
    if (savedSel && typeof savedSel.from === 'number' && typeof savedSel.to === 'number' && savedSel.from !== savedSel.to) {
      return true;
    }
    return !!editorHost._toolbarSelection;
  }

  function _getDocxSelectionTextForAI() {
    if (state.fileType !== 'docx' || !state.activeEditor || !state.activeEditor.editor) {
      return '';
    }
    if (!_hasUsableDocxSelectionTarget()) {
      return '';
    }
    const _ed = state.activeEditor.editor;
    const _s = _ed.state.selection;
    if (_s.from < _s.to) {
      return (_ed.state.doc.textBetween(_s.from, _s.to, ' ') || '').trim();
    }
    return (lastSelectionText || '').trim();
  }

  function _getLiveEditorSelectionForAI() {
    let sel = lastSelectionText;
    if (state.fileType === 'docx') {
      sel = _getDocxSelectionTextForAI();
    }
    if (!sel && state.fileType === 'xlsx' && state.activeEditor) {
      const rangeText = state.activeEditor.getContent();
      if (rangeText && !rangeText.includes('未选中区域')) sel = rangeText;
    }
    return (sel || '').trim();
  }

  // Save the active DOCX selection before focus leaves the TipTap editor.
  function _saveEditorRange() {
    if (state.activeEditor && state.fileType === 'docx') {
      if (typeof state.activeEditor.saveSelection === 'function') {
        state.activeEditor.saveSelection();
      }
    }
  }

  // ── Show/hide the persistent analysis-subject bar ──
  function _updateSubjectBar(fileName, fileType) {
    // Keep the legacy subject-bar hidden — context is shown in the input-area indicator instead
    const bar = $('wa-subject-bar');
    if (bar) bar.style.display = 'none';

    // ── Footer file chip sync (PEMO-style) ──
    const footerChip = $('wa-footer-file-chip');
    const footerLabel = $('wa-footer-file-label');
    const footerIcon = $('wa-footer-file-icon');
    if (!fileName) {
      if (footerChip) footerChip.style.display = 'none';
    } else if (footerChip && footerLabel) {
      if (footerLabel) footerLabel.textContent = fileName;
      if (footerIcon) {
        const ext = (fileName.split('.').pop() || '').toLowerCase();
        const EXT_COLORS = { docx: '#2563eb', doc: '#2563eb', xlsx: '#16a34a', xls: '#16a34a', pptx: '#dc2626', ppt: '#dc2626', pdf: '#7c3aed', txt: '#6b7280', md: '#6b7280' };
        footerIcon.textContent = ext.toUpperCase().slice(0, 4);
        footerIcon.style.background = EXT_COLORS[ext] || '#6b7280';
      }
      footerChip.style.display = 'flex';
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
    const GAP = 10;
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

  // ══════════════════════════════════════════════════════════════════
  // Selection geometry helper — returns { top, bottom, centerX }
  // in VIEWPORT coordinates, suitable for position:fixed elements.
  //
  // Uses getClientRects() across ALL line fragments and takes the
  // true min-top / max-bottom so multi-line or multi-paragraph
  // selections are handled correctly.
  // ══════════════════════════════════════════════════════════════════
  function _getSelectionViewportBounds() {
    const ws = window.getSelection();
    if (!ws || ws.isCollapsed || !ws.rangeCount) return null;
    const range = ws.getRangeAt(0);

    // Collect the TRUE outermost top/bottom from every line fragment
    let top = Infinity, bottom = -Infinity;
    const rects = range.getClientRects();
    for (let i = 0; i < rects.length; i++) {
      const r = rects[i];
      if (r.height <= 0 || r.width <= 0) continue;
      if (r.top < top) top = r.top;
      if (r.bottom > bottom) bottom = r.bottom;
    }

    // Fallback: bounding rect (works for single-line)
    if (top === Infinity) {
      const br = range.getBoundingClientRect();
      if (!br || br.height <= 0) return null;
      top = br.top;
      bottom = br.bottom;
    }

    // Horizontal centre: prefer editor page element for consistent centering
    let centerX = window.innerWidth / 2;
    const refEl = document.querySelector('#wa-docx-editor .koto-zoom-wrapper')
               || document.querySelector('#wa-docx-editor .ProseMirror')
               || document.querySelector('#wa-pptx-stage')
               || document.querySelector('#wa-pdf-viewer');
    if (refEl) {
      const rr = refEl.getBoundingClientRect();
      centerX = rr.left + rr.width / 2;
    } else {
      // Compute center from the rects themselves
      let minL = Infinity, maxR = -Infinity;
      for (let i = 0; i < rects.length; i++) {
        if (rects[i].height <= 0) continue;
        if (rects[i].left < minL) minL = rects[i].left;
        if (rects[i].right > maxR) maxR = rects[i].right;
      }
      if (minL !== Infinity) centerX = (minL + maxR) / 2;
    }

    return { top, bottom, centerX };
  }

  // ══════════════════════════════════════════════════════════════════
  // Position #wa-pdf-tooltip (AI quick-action bar) BELOW the
  // selection, horizontally centred on the editor page.
  //
  // Optional overrideRect { centerX, top, bottom } — caller can
  // supply pre-computed geometry (e.g. DOCX hoverbar passes its
  // own measurements so both toolbars stay consistent).
  // ══════════════════════════════════════════════════════════════════
  function _positionSelectionToolbar(overrideRect) {
    const tt = $('wa-pdf-tooltip');
    if (!tt) return;

    // Ensure tooltip is at body level so it's never clipped
    if (tt.parentElement !== document.body) {
      document.body.appendChild(tt);
    }

    // ── 1. Resolve geometry ────────────────────────────────────────
    let selTop, selBottom, selCenterX;
    if (overrideRect) {
      selCenterX = overrideRect.centerX;
      selTop     = overrideRect.top;
      selBottom  = overrideRect.bottom;
    } else {
      const bounds = _getSelectionViewportBounds();
      if (!bounds) return;
      selTop     = bounds.top;
      selBottom  = bounds.bottom;
      selCenterX = bounds.centerX;
    }

    // ── 2. Measure toolbar (hidden-show-hidden trick) ──────────────
    tt.style.visibility = 'hidden';
    tt.style.display = 'flex';
    const ttW = tt.offsetWidth || 220;
    const ttH = tt.offsetHeight || 36;
    tt.style.display = 'none';
    tt.style.visibility = '';

    const GAP = 12;
    const vw = window.innerWidth;
    const vh = window.innerHeight;

    // ── 3. Horizontal: centred on editor page ──────────────────────
    let left = selCenterX - ttW / 2;
    left = Math.max(8, Math.min(left, vw - ttW - 8));

    // ── 4. Vertical: prefer BELOW selection, fallback ABOVE ────────
    let top = selBottom + GAP;
    if (top + ttH > vh - 8) top = selTop - ttH - GAP;
    if (top < 8) top = selBottom + GAP;

    // ── 5. Final clamp: always keep visible on screen ──────────────
    top = Math.max(8, Math.min(top, vh - ttH - 8));

    tt.style.left = left + 'px';
    tt.style.top  = top  + 'px';
    tt.style.display = 'flex';
  }

  // Mouse events on editable text may target a Text node.
  // Normalize to an Element so closest() checks are reliable.
  function _evtEl(target) {
    if (!target) return null;
    if (target.nodeType === Node.TEXT_NODE) return target.parentElement;
    return target;
  }

  let _docxNativeSelBottom = 0;  // bottom of selection in viewport px (native range)

  document.addEventListener('mouseup', (e) => {
    const _el = _evtEl(e.target);
    if (e.button === 0) {
      _docxMouseIsDown = false;
      _docxMouseUpY = e.clientY;
      // Capture native selection bounding rect — most accurate visual bottom
      try {
        const _ns = window.getSelection();
        if (_ns && _ns.rangeCount > 0 && !_ns.isCollapsed) {
          const _nr = _ns.getRangeAt(0).getBoundingClientRect();
          if (_nr && _nr.bottom > 0) _docxNativeSelBottom = _nr.bottom;
        }
      } catch (_) {}
    }
    if (e.button === 2) return;                                      // right-click — let contextmenu handler take over
    if ((_el && _el.id === 'wa-pdf-tooltip') || (_el && _el.closest && _el.closest('#wa-pdf-tooltip'))) return;
    if (_el && _el.closest && _el.closest('#wa-docx-hoverbar')) {
      // Clicking hoverbar buttons doesn't go through normal selection check.
      // Schedule a deferred check so we still hide the bar if the selection
      // collapsed as a result of the format operation (e.g. clearMarks, list ops).
      setTimeout(() => {
        const _ws = window.getSelection();
        if (!_ws || _ws.isCollapsed) _resetDocxSelection();
      }, 120);
      return;
    }
    
    if (state.fileType === 'xlsx') return;

    // ── Guard: only show toolbars when mouseup lands inside a file editor area ──
    // ProseMirror retains its selection even when clicking outside the editor,
    // so window.getSelection() returns stale text. Without this check the
    // hoverbar & AI tooltip would reappear after mousedown already hid them.
    const _insideEditor = _el && _el.closest &&
      (_el.closest('#wa-editor-content') ||
       _el.closest('#wa-pdf-viewer') ||
       _el.closest('#wa-pptx-editor') ||
       _el.closest('#wa-pdf-tooltip') ||
       _el.closest('.wa-sel-toolbar'));
    if (!_insideEditor) {
      // Click outside any editor area — hide both toolbars and bail out
      $('wa-pdf-tooltip').style.display = 'none';
      if (state.fileType === 'docx') _resetDocxSelection();
      return;
    }

    // ── DOCX: show both toolbars now that the drag is complete ──────────
    // During the drag _docxMouseIsDown was true so _kotoDocxSelectionChanged
    // skipped showing.  mouseup is the right moment to display them.
    // Click-to-deselect is caught by the collapsed check below.
    if (state.fileType === 'docx') {
      const _dSel = window.getSelection();
      if (!_dSel || _dSel.isCollapsed || !_dSel.toString().trim()) {
        // Collapsed / empty → fall through to else-branch for table handling
      } else {
        _showDocxHoverBar();
      }
    }

    const sel = window.getSelection().toString().trim();
    const tt = $('wa-pdf-tooltip');
    
    if (sel && sel.length > 0) {
      lastSelectionText = sel;
      
      // DOCX positions the AI tooltip together with its format hoverbar.
      // Skip the generic placement here so the DOCX-specific stack isn't overwritten.
      if (state.fileType !== 'docx') {
        // For PPTX the file-specific format hoverbar handles formatting (shown above).
        // The global AI tooltip is shown BELOW the selection so it doesn't cover selected text.
        _positionSelectionToolbar();
      }
      // ── Show PPTX format hoverbar ──
      if (state.fileType === 'pptx') {
        const _fmtSel = window.getSelection();
        if (_fmtSel && _fmtSel.rangeCount > 0) {
          const _pptxCrs = _fmtSel.getRangeAt(0).getClientRects();
          let _pptxFL = null;
          for (let _pi = 0; _pi < _pptxCrs.length; _pi++) {
            if (_pptxCrs[_pi].height > 0) { _pptxFL = _pptxCrs[_pi]; break; }
          }
          if (_pptxFL) {
            const _hb = $('wa-pptx-hoverbar');
            if (_hb) {
              _hb.style.display = 'flex';
              const _hbW = _hb.offsetWidth  || 400;
              const _hbH = _hb.offsetHeight || 34;
              let _hbTop  = _pptxFL.top - _hbH - 8;
              if (_hbTop < 110) _hbTop = _pptxFL.bottom + 8;
              _hbTop = Math.min(_hbTop, window.innerHeight - _hbH - 8);
              _hbTop = Math.max(8, _hbTop);
              let _hbLeft = _pptxFL.left + 100 - _hbW / 2;
              _hbLeft = Math.max(8, Math.min(_hbLeft, window.innerWidth  - _hbW - 8));
              _hb.style.left = _hbLeft + 'px';
              _hb.style.top  = _hbTop  + 'px';
            }
          }
        }
      }

      // Update character count badge in tooltip
      const countEl = $('wa-tooltip-count');
      if (countEl) countEl.textContent = `${sel.replace(/\s/g, '').length}\u5b57`;

      // If the chip is already showing (prior pinned context), update it immediately
      if (state.pinnedSelection) {
        _saveEditorRange();
        _pinSelectionChip(sel);
        _clearPinnedHighlight();
        _applyPinnedHighlight();
      }

      // Live-update the context bar to show selected text preview
      _updateContextBar({ selection: sel });
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
      if (state.fileType === 'docx' && _el && _el.closest) {
        const tbl = _el.closest('#wa-editor-content table');
        if (tbl) {
          _hideDocxHoverBar();  // hide format bar even when clicking into a table cell
          const tableText = _extractHtmlTableText(tbl);
          if (tableText) {
            lastSelectionText = tableText;
            const rows = tbl.rows.length;
            const cols = rows > 0 ? tbl.rows[0].cells.length : 0;
            const countEl = $('wa-tooltip-count');
            if (countEl) countEl.textContent = `${rows}×${cols} 表格`;
            _showTableTooltipNear(tbl);
            _updateContextBar({ table: `${rows}×${cols} 表格` });
            return;
          }
        }
      }
      tt.style.display = 'none';
      _hideDocxHoverBar();   // no selection — hide format bar too
      lastSelectionText = "";
      // Revert context bar: show file count or hide
      _updateContextBar();
      if (!state._aiFileContext || !state._aiFileContext.length) {
        _updateSubjectBar(state.fileName, state.fileType);
      }
    }
  });

  document.addEventListener('mousedown', (e) => {
    const _el = _evtEl(e.target);
    // Only track primary button down when NOT clicking the AI tooltip —
    // clicking tooltip buttons should not suppress the hoverbar show logic.
    if (e.button === 0 && !(_el && _el.closest && _el.closest('#wa-pdf-tooltip'))) _docxMouseIsDown = true;
    // Hide AI toolbar unless clicking on it
    if (!(_el && _el.closest && _el.closest('#wa-pdf-tooltip'))) {
       $('wa-pdf-tooltip').style.display = 'none';
    }
    // Hide DOCX format hoverbar unless clicking on it or its colour picker
    if (_docxHbEl && _docxHbEl.style.display !== 'none') {
      if (!(_el && _el.closest && _el.closest('#wa-docx-hoverbar')) && !(_el && _el.closest && _el.closest('#wa-docx-cp'))) {
        _hideDocxHoverBar();
      }
    }
    // Hide PPTX format hoverbar
    const _pptxHb = $('wa-pptx-hoverbar');
    if (_pptxHb && _pptxHb.style.display !== 'none') {
      if (!(_el && _el.closest && _el.closest('#wa-pptx-hoverbar')) && !(_el && _el.closest && _el.closest('#wa-pptx-cp'))) {
        _pptxHb.style.display = 'none';
      }
    }
  });

  // ── selectionchange: collapse detection ONLY ─────────────────────────
  // TipTap selectionUpdate + mouseup handle SHOWING bars.
  // selectionchange ONLY hides when interaction collapses the selection.
  // Calling _showDocxHoverBar here caused a race: ProseMirror's stale DOM
  // selection re-showed bars that mousedown had just hidden.
  let _selChangeTimer = null;
  document.addEventListener('selectionchange', () => {
    if (state.fileType !== 'docx') return;
    clearTimeout(_selChangeTimer);
    _selChangeTimer = setTimeout(() => {
      // Skip if user is interacting with the AI tooltip or DOCX hoverbar —
      // clicking their buttons collapses the editor selection, but
      // lastSelectionText must survive until the action handler reads it.
      const _ae = document.activeElement;
      if (_ae && (_ae.closest('#wa-pdf-tooltip') || _ae.closest('#wa-docx-hoverbar') || _ae.closest('#wa-docx-cp'))) return;
      // Also skip while mouse is held on the tooltip (mousedown fires before selectionchange resolves)
      if (_docxMouseIsDown && document.querySelector('#wa-pdf-tooltip:hover, #wa-docx-hoverbar:hover')) return;
      const _ws = window.getSelection();
      if (!_ws || _ws.isCollapsed || !_ws.rangeCount) {
        _resetDocxSelection();  // collapsed — always hide
      }
      // Non-collapsed: do nothing — TipTap selectionUpdate + mouseup handle show.
    }, 80);
  });

  // Hide the selection toolbar on any scroll so it never blocks the AI panel
  document.addEventListener('scroll', () => {
    $('wa-pdf-tooltip').style.display = 'none';
    if (state.fileType === 'docx') _resetDocxSelection();
    else lastSelectionText = '';
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

  const _WA_QUICK_ACTION_LABELS = {
    '润色': '润色优化',
    '翻译': '翻译（中英互译）',
    '总结': '总结要点',
    '续写': '续写补全',
    '改写': '改写',
    '解释': '解释分析',
    '检查': '检查建议',
  };
  const _WA_QUICK_ACTION_TO_EDITOR_ACTION = {
    '润色': 'polish',
    '翻译': 'translate',
    '总结': 'summarize',
    '续写': 'continue_writing',
    '改写': 'rewrite',
    '解释': 'explain',
    '检查': 'check',
  };
  const _WA_READ_ONLY_QUICK_ACTIONS = new Set(['总结', '解释', '翻译']);
  const _WA_FULL_DOC_QUICK_ACTIONS = new Set(['总结', '续写', '检查']);

  function _waRenderMarkdown(text) {
    if (window.marked) {
      try { return window.marked.parse(text || ''); } catch (e) {}
    }
    return (text || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/\n/g, '<br>');
  }

  function _waQuickActionModelMode() {
    return state.lockedModel === 'local' ? 'local' : 'auto';
  }

  async function _sendViaEditorActionSSE(payload) {
    const msgs = $('wa-ai-messages');
    const action = payload.action;
    const editorAction = _WA_QUICK_ACTION_TO_EDITOR_ACTION[action];
    const loadingEl = payload.loadingEl;
    const selectionText = payload.selectionText || '';
    const fullDocText = payload.fullDocText || '';
    const hasSelection = !!payload.hasSelection;
    const isReadOnly = _WA_READ_ONLY_QUICK_ACTIONS.has(action);
    let fullText = '';
    let buffer = '';
    let hasStructuredOutput = false;
    let loadingRemoved = false;

    if (!editorAction) throw new Error(`未知动作: ${action}`);

    const appendSystemNote = (text, html) => {
      if (!text && !html) return;
      const noteEl = document.createElement('div');
      noteEl.className = 'wa-msg system';
      noteEl.style.cssText = 'font-size:11px;font-style:italic;opacity:.75;padding:2px 8px;';
      if (html) noteEl.innerHTML = html;
      else noteEl.textContent = text;
      msgs.appendChild(noteEl);
      msgs.scrollTop = msgs.scrollHeight;
    };

    const setProgress = (text) => {
      if (!loadingEl || loadingRemoved || hasStructuredOutput || fullText) return;
      loadingEl.innerHTML = `<span class="wa-progress-text">⏳ ${_escHtml(text || '处理中…')}</span>`;
      msgs.scrollTop = msgs.scrollHeight;
    };

    const renderPlainResult = (resultText) => {
      const trimmed = (resultText || '').trim();
      if (!trimmed) {
        if (loadingEl && !loadingRemoved) {
          loadingEl.classList.remove('streaming');
          loadingEl.textContent = '⚠ AI 未返回有效内容，请重试';
        }
        return;
      }

      if (loadingEl && !loadingRemoved) loadingEl.classList.remove('streaming');

      if (isReadOnly) {
        if (loadingEl && !loadingRemoved) {
          loadingEl.innerHTML = _waRenderMarkdown(trimmed);
          loadingEl.dataset.rawText = trimmed;
        }
        return;
      }

      if (hasSelection) {
        if (loadingEl && !loadingRemoved) {
          loadingEl.remove();
          loadingRemoved = true;
        }
        _handleProposals({
          proposals: [{
            id: 'qa_' + Date.now(),
            original_text: selectionText,
            proposed_text: trimmed,
            rationale: _WA_QUICK_ACTION_LABELS[action] || action,
          }],
        });
        return;
      }

      if (loadingEl && !loadingRemoved) {
        loadingEl.innerHTML = _waRenderMarkdown(trimmed);
        loadingEl.dataset.rawText = trimmed;
      }
      msgs.appendChild(_makeAIActionBar({
        pinnedSel: null,
        toolCall: null,
        outputMode: 'chat',
      }));
      requestAnimationFrame(() => { msgs.scrollTop = msgs.scrollHeight; });
    };

    const ctrl = new AbortController();
    state._streamAbortCtrl = ctrl;
    state.isLoading = true;
    _setStreamBtn(true);

    try {
      const modelId = (state.lockedModel && !['auto', 'local'].includes(state.lockedModel))
        ? state.lockedModel
        : '';
      const resp = await fetch('/api/editor/ai/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          action: editorAction,
          selection: selectionText,
          instruction: '',
          full_text: fullDocText,
          file_type: state.fileType || 'general',
          file_name: state.fileName || '',
          model_mode: _waQuickActionModelMode(),
          model_id: modelId,
          output_mode: isReadOnly ? 'chat' : 'inline',
          session_id: state.fileId ? 'editor_' + state.fileId : '',
        }),
        signal: ctrl.signal,
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${resp.statusText}`);

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split('\n\n');
        buffer = parts.pop() || '';
        for (const part of parts) {
          if (!part.startsWith('data: ')) continue;
          let parsed;
          try { parsed = JSON.parse(part.slice(6)); } catch (e) { continue; }

          if (parsed.type === 'token') {
            fullText += parsed.text || '';
            if (loadingEl && !loadingRemoved && !hasStructuredOutput) {
              loadingEl.innerHTML = _waRenderMarkdown(fullText) + '<span class="typing-cursor">▊</span>';
              msgs.scrollTop = msgs.scrollHeight;
            }
            continue;
          }

          if (parsed.type === 'phase') {
            if ((parsed.status || '') !== 'done') {
              setProgress(parsed.current ? `执行 ${parsed.current}…` : '处理中…');
            }
            continue;
          }

          if (parsed.type === 'plan') {
            setProgress('生成执行计划…');
            continue;
          }

          if (parsed.type === 'step_start') {
            setProgress(parsed.text || '处理中…');
            continue;
          }

          if (parsed.type === 'step_progress') {
            setProgress(parsed.detail || '处理中…');
            continue;
          }

          if (parsed.type === 'step_done') {
            setProgress(parsed.text || '步骤完成');
            continue;
          }

          if (parsed.type === 'thought') {
            setProgress(parsed.text || '处理中…');
            continue;
          }

          if (parsed.type === 'tool_call') {
            setProgress(parsed.tool_name ? `调用 ${parsed.tool_name}…` : '调用工具中…');
            continue;
          }

          if (parsed.type === 'tool_result') {
            setProgress(parsed.result_preview || (parsed.tool_name ? `${parsed.tool_name} 已完成` : '处理中…'));
            continue;
          }

          if (parsed.type === 'info') {
            appendSystemNote(parsed.text || '');
            continue;
          }

          if (parsed.type === 'rag_info') {
            if ((parsed.total_chunks || 0) > 0 && (parsed.retrieved_chunks || 0) > 0) {
              appendSystemNote('', `${_SLIDES_SVG} 长文档检索：已从 <b>${parsed.total_chunks}</b> 段中检索最相关 <b>${parsed.retrieved_chunks}</b> 段`);
            }
            continue;
          }

          if (parsed.type === 'proposals') {
            hasStructuredOutput = true;
            if (loadingEl && !loadingRemoved) {
              loadingEl.remove();
              loadingRemoved = true;
            }
            _handleProposals({
              proposals: parsed.proposals || [],
              summary: parsed.summary || '',
            });
            continue;
          }

          if (parsed.type === 'doc_tool_call') {
            hasStructuredOutput = true;
            state.pendingToolCall = parsed;
            if (loadingEl && !loadingRemoved) {
              loadingEl.classList.remove('streaming');
              const previewText = parsed.value || `已生成文档操作：${parsed.type || 'tool_call'}`;
              loadingEl.innerHTML = _waRenderMarkdown(previewText);
              loadingEl.dataset.rawText = previewText;
            }
            msgs.appendChild(_makeAIActionBar({
              pinnedSel: null,
              toolCall: parsed,
              outputMode: 'inline',
            }));
            requestAnimationFrame(() => { msgs.scrollTop = msgs.scrollHeight; });
            continue;
          }

          if (parsed.type === 'done') {
            if (!hasStructuredOutput) {
              renderPlainResult(parsed.result || fullText);
            } else if (loadingEl && !loadingRemoved) {
              loadingEl.classList.remove('streaming');
            }
            msgs.scrollTop = msgs.scrollHeight;
            return;
          }

          if (parsed.type === 'error') {
            if (loadingEl && !loadingRemoved) {
              loadingEl.classList.remove('streaming');
              loadingEl.textContent = parsed.text || 'AI 处理失败';
            } else {
              const errEl = document.createElement('div');
              errEl.className = 'wa-msg ai';
              errEl.textContent = parsed.text || 'AI 处理失败';
              msgs.appendChild(errEl);
            }
            msgs.scrollTop = msgs.scrollHeight;
            return;
          }
        }
      }

      if (!hasStructuredOutput && fullText) {
        renderPlainResult(fullText);
      } else if (loadingEl && !loadingRemoved && loadingEl.classList.contains('streaming')) {
        loadingEl.classList.remove('streaming');
      }
    } catch (err) {
      if (err.name === 'AbortError') {
        if (loadingEl && !loadingRemoved) {
          loadingEl.classList.remove('streaming');
          loadingEl.textContent = loadingEl.textContent.trim() ? `${loadingEl.textContent} [已取消]` : '[已取消]';
        }
      } else {
        console.error('[WorkspaceAI] Quick-action stream error:', err);
        if (loadingEl && !loadingRemoved) {
          loadingEl.classList.remove('streaming');
          loadingEl.textContent = `网络错误：${err.message}`;
        } else {
          const errEl = document.createElement('div');
          errEl.className = 'wa-msg ai';
          errEl.textContent = `网络错误：${err.message}`;
          msgs.appendChild(errEl);
        }
      }
      msgs.scrollTop = msgs.scrollHeight;
    } finally {
      state.isLoading = false;
      state._streamAbortCtrl = null;
      _setStreamBtn(false);
    }
  }

  window.WA.sendQuickAction = (action) => {
    if (state.isLoading) {
      showToast('请先等待当前任务完成，或点击右下角暂停', 'info');
      return;
    }

    let sel = state.fileType === 'docx' ? _getDocxSelectionTextForAI() : lastSelectionText;
    let hasSelection = !!sel;
    let fullDocText = state.activeEditor ? (state.activeEditor.getContent() || '') : '';

    if (state.fileType === 'xlsx' && state.activeEditor) {
      // Always re-read the active range at click time.
      const rangeText = state.activeEditor.getContent();
      if (rangeText && !rangeText.includes('未选中区域')) {
        sel = rangeText;
        hasSelection = true;
      } else {
        const csv = (state.activeEditor.getCSV && state.activeEditor.getCSV()) || '';
        if (csv.trim()) fullDocText = '[表格全部数据]:\n' + csv;
      }
    }
    if (!hasSelection && state.fileType === 'docx') {
      sel = _getDocxSelectionTextForAI();
      hasSelection = !!sel;
    }

    const canUseFullDocument = _WA_FULL_DOC_QUICK_ACTIONS.has(action) || (action === '可视化' && state.fileType === 'xlsx');
    if (!hasSelection && canUseFullDocument && fullDocText.trim()) {
      sel = fullDocText;
    }

    if (!sel) {
      showToast(canUseFullDocument ? '当前文档为空，暂无可处理内容' : '请先选中文字', 'info');
      return;
    }

    _hideWelcome();
    $('wa-pdf-tooltip').style.display = 'none';
    if (hasSelection) {
      // Save editor selection BEFORE clearing browser selection, so
      // acceptProposal can restore it for an in-place, Undo-safe replacement.
      _saveEditorRange();
      state.pinnedSelection = sel;
    } else {
      state.pinnedSelection = null;
    }
    // Clear the browser text selection so the mouseup handler won't
    // re-show the tooltip over the document while the result is loading.
    lastSelectionText = '';
    try { window.getSelection()?.removeAllRanges(); } catch (_) {}

    const msgs = $('wa-ai-messages');
    const preview = hasSelection
      ? (sel.length > 60 ? sel.substring(0, 60) + '…' : sel)
      : (action === '可视化' ? '当前表格数据' : '全文');
    const uMsg = document.createElement('div');
    uMsg.className = 'wa-msg user';
    uMsg.textContent = `${action}：${preview}`;
    msgs.appendChild(uMsg);

    const loadingEl = document.createElement('div');
    loadingEl.className = 'wa-msg ai streaming';
    loadingEl.innerHTML = '<span class="wa-progress-text">⏳ 处理中…</span>';
    msgs.appendChild(loadingEl);
    msgs.scrollTop = msgs.scrollHeight;

    state.lastPinnedSel = hasSelection ? sel : null;
    state.pendingToolCall = null;

    if (action === '可视化') {
      _sendViaSSEChart({
        csv_data: sel,
        prompt: '请基于当前数据生成最合适、最清晰的图表，并在必要时自动清洗列名与空值。',
        language: 'python',
      });
      return;
    }

    _sendViaEditorActionSSE({
      action,
      selectionText: sel,
      fullDocText,
      hasSelection,
      loadingEl,
    }).catch(err => {
      loadingEl.classList.remove('streaming');
      loadingEl.textContent = `网络错误：${err.message}`;
      msgs.scrollTop = msgs.scrollHeight;
      state.isLoading = false;
      state._streamAbortCtrl = null;
      _setStreamBtn(false);
    });
  };

  window.WA.sendSelectionToAI = () => {
    let sel = state.fileType === 'docx' ? _getDocxSelectionTextForAI() : lastSelectionText;
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

  // Auto-expand the right AI panel if it's collapsed (respects panel-auto-reset setting)
  function _expandWAPanel() {
    if (!_panelAutoReset) return;   // user disabled auto-reset
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
    // Update context bar (selection cleared, may still show file count)
    _updateContextBar();
    // Also clear inline AI chip
    const iaiChip = $('wa-iai-selection-chip');
    if (iaiChip) iaiChip.style.display = 'none';
    _clearPinnedHighlight();
  };

  // Auto-pin selection when user clicks/focuses the chat input.
  // The browser clears document selection on click, so we capture it here
  // before it disappears — same effect as clicking "转交 AI" manually.
  const _waInput = $('wa-user-input');
  if (_waInput) {
    autoResize(_waInput);
    _waInput.addEventListener('input', () => autoResize(_waInput));
    window.addEventListener('resize', () => autoResize(_waInput));
    _waInput.addEventListener('mousedown', () => {
      const liveSelection = _getLiveEditorSelectionForAI();
      if (liveSelection) {
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
        _pinSelectionChip(liveSelection);
        $('wa-pdf-tooltip').style.display = 'none';
      }
    });
  }

  // ── Split.js Init ──
  const _savedSplitSizes = (() => {
    try { const s = localStorage.getItem('wa_split_sizes'); return s ? JSON.parse(s) : null; } catch { return null; }
  })();

  // Wrap Split.js init in a function so it can be deferred in embedded mode
  // (where #workspaceView starts with display:none and elements have 0 size).
  function _initSplit() {
    if (window._waSplit) return; // already initialised
    const left = $('wa-left'), canvas = $('wa-canvas'), ai = $('wa-ai');
    if (!left || !canvas || !ai) return;
    window._waSplit = Split(['#wa-left', '#wa-canvas', '#wa-ai'], {
      sizes: _savedSplitSizes || [15, 55, 30],
      minSize: [150, 400, 250],
      gutterSize: 6,
      snapOffset: 0,
      onDragEnd(sizes) {
        try { localStorage.setItem('wa_split_sizes', JSON.stringify(sizes)); } catch {}
      }
    });
  }

  // Standalone page: init immediately (elements are visible).
  // Embedded mode: defer to openInMainView() when the container becomes visible.
  if (!document.getElementById('workspaceView')) {
    _initSplit();
  }

  // ── Panel auto-reset setting ──
  let _panelAutoReset = localStorage.getItem('wa_panel_autoreset') !== 'off';
  window.WA.setPanelAutoReset = (enabled) => {
    _panelAutoReset = enabled;
    localStorage.setItem('wa_panel_autoreset', enabled ? 'on' : 'off');
    document.getElementById('wa-panel-autoreset-on')?.classList.toggle('active', enabled);
    document.getElementById('wa-panel-autoreset-off')?.classList.toggle('active', !enabled);
  };
  // Sync toggle buttons on load
  (() => {
    document.getElementById('wa-panel-autoreset-on')?.classList.toggle('active', _panelAutoReset);
    document.getElementById('wa-panel-autoreset-off')?.classList.toggle('active', !_panelAutoReset);
  })();

  // ── Editor Adapters (Phase 3) ──

  // ═══════════════════════════════════════════════════════════════
  // DocxReadView — docx-preview 高保真只读渲染器
  // 直接解析 OOXML 保留分页/页眉/页脚/目录/图片定位
  // ═══════════════════════════════════════════════════════════════
  class DocxReadView {
    constructor() {
      this.containerId = 'wa-docx-read-view';
      this._zoom = 100;
      this._styleSlot = null;
      this._renderArea = null;
      this._scrollArea = null;
      this._topbar = null;
      this._pageInfo = null;
      this._imgToolbar = null;
      this._selectedImg = null;

      const host = $(this.containerId);
      host.innerHTML = '';
      host.classList.add('active');

      // Style slot for docx-preview generated styles
      this._styleSlot = document.createElement('style');
      this._styleSlot.id = 'wa-drv-docx-styles';
      document.head.appendChild(this._styleSlot);

      // Top bar with edit button
      this._topbar = document.createElement('div');
      this._topbar.className = 'wa-drv-topbar';
      this._topbar.innerHTML = `
        <button class="wa-drv-edit-btn" title="切换到编辑模式">
          <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor"><path d="M12.1 1.3a1 1 0 0 1 1.4 0l1.2 1.2a1 1 0 0 1 0 1.4l-8.5 8.5-3.1.8a.5.5 0 0 1-.6-.6l.8-3.1 8.8-8.2zm.7 1L4.5 10.6l-.5 1.9 1.9-.5L14.2 3.7l-1.4-1.4z"/></svg>
          编辑
        </button>
        <span class="wa-drv-page-info"></span>
      `;
      host.appendChild(this._topbar);
      this._pageInfo = this._topbar.querySelector('.wa-drv-page-info');

      // Edit button → switch to TipTap
      this._topbar.querySelector('.wa-drv-edit-btn').addEventListener('click', () => {
        if (typeof WA._switchDocxMode === 'function') WA._switchDocxMode('edit');
      });

      // Scroll area
      this._scrollArea = document.createElement('div');
      this._scrollArea.className = 'wa-drv-scroll';
      host.appendChild(this._scrollArea);

      // Render area
      this._renderArea = document.createElement('div');
      this._renderArea.className = 'wa-drv-render';
      this._scrollArea.appendChild(this._renderArea);

      // Image AI toolbar (floating, reused)
      this._imgToolbar = document.createElement('div');
      this._imgToolbar.className = 'wa-drv-img-toolbar';
      this._imgToolbar.innerHTML = `
        <button data-action="describe">描述</button>
        <button data-action="replace">替换</button>
      `;
      host.appendChild(this._imgToolbar);
      this._imgToolbar.addEventListener('click', (e) => {
        const btn = e.target.closest('button[data-action]');
        if (!btn || !this._selectedImg) return;
        const action = btn.dataset.action;
        const src = this._selectedImg.src;
        // Send to AI panel via workspace assistant
        if (typeof WA._sendImageToAI === 'function') {
          WA._sendImageToAI(action, src);
        }
        this._hideImgToolbar();
      });

      // Ctrl+Wheel zoom
      this._wheelHandler = (e) => {
        if (!e.ctrlKey && !e.metaKey) return;
        e.preventDefault();
        const delta = e.deltaY > 0 ? -10 : 10;
        this.setZoom(this._zoom + delta);
      };
      host.addEventListener('wheel', this._wheelHandler, { passive: false });

      // Click on images → show toolbar
      this._renderArea.addEventListener('click', (e) => {
        const img = e.target.closest('img');
        if (img) {
          e.preventDefault();
          this._selectImage(img);
        } else if (!e.target.closest('.wa-drv-img-toolbar')) {
          this._hideImgToolbar();
        }
      });

      // TOC / bookmark link navigation
      this._renderArea.addEventListener('click', (e) => {
        const a = e.target.closest('a[href]');
        if (!a) return;
        const href = a.getAttribute('href') || '';
        if (href.startsWith('#')) {
          // Internal bookmark: scroll to target
          e.preventDefault();
          e.stopPropagation();
          const targetId = href.slice(1);
          // docx-preview outputs bookmarks as <a id="..."> or <a name="...">
          const target = this._renderArea.querySelector(`[id="${CSS.escape(targetId)}"], [name="${CSS.escape(targetId)}"]`);
          if (target) {
            target.scrollIntoView({ behavior: 'smooth', block: 'start' });
          }
        } else if (href.startsWith('http')) {
          // External link: open in new window
          e.preventDefault();
          window.open(href, '_blank', 'noopener');
        } else {
          e.preventDefault(); // block all other navigation
        }
      }, true);
    }

    async render(rawUrl) {
      this._renderArea.innerHTML = '<div class="wa-drv-loading">正在渲染文档…</div>';

      const lib = window.docx;
      if (!lib || typeof lib.renderAsync !== 'function') {
        this._renderArea.innerHTML =
          '<div class="wa-drv-loading" style="color:#f87171">docx-preview 库未加载</div>';
        return;
      }

      try {
        const resp = await fetch(rawUrl);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const buf = await resp.arrayBuffer();

        this._renderArea.innerHTML = '';

        await lib.renderAsync(buf, this._renderArea, this._styleSlot, {
          className: 'docx',
          inWrapper: false,
          ignoreWidth: false,
          ignoreHeight: false,
          ignoreFonts: false,
          breakPages: true,
          useBase64URL: true,
          renderHeaders: true,
          renderFooters: true,
          renderFootnotes: true,
          renderEndnotes: true,
          experimental: true,
        });

        // Page count
        const pages = this._renderArea.querySelectorAll('section.docx');
        if (this._pageInfo) {
          this._pageInfo.textContent = `共 ${pages.length || 1} 页`;
        }

        // Fix wrapNone (anchored) images
        requestAnimationFrame(() => this._fixWrapNoneImages());

        // Allow TOC bookmarks: set tabindex=-1 on all links to prevent focus-stealing
        this._renderArea.querySelectorAll('a').forEach(a => a.setAttribute('tabindex', '-1'));

      } catch (err) {
        console.error('[DocxReadView] render error:', err);
        this._renderArea.innerHTML =
          `<div class="wa-drv-loading" style="color:#f87171">渲染失败：${_escHtml(String(err.message || err))}</div>`;
      }

      if (this._scrollArea) this._scrollArea.scrollTop = 0;
    }

    setZoom(pct) {
      this._zoom = Math.max(50, Math.min(200, pct));
      this._renderArea.style.zoom = this._zoom / 100;
      _updateDocxZoomUI(this._zoom);
    }

    getContent() {
      // Return selected text for AI context, or full doc text
      const sel = window.getSelection();
      if (sel && sel.toString().trim()) {
        return `[当前选中文本]:\n${sel.toString()}\n`;
      }
      return `[文档全文]:\n${this.getFullText()}\n`;
    }

    getFullText() {
      if (!this._renderArea) return '';
      return this._renderArea.innerText || '';
    }

    serialize() {
      return null; // Read-only, no edits to persist
    }

    destroy() {
      const host = $(this.containerId);
      if (host) {
        host.removeEventListener('wheel', this._wheelHandler);
        host.classList.remove('active');
        host.innerHTML = '';
      }
      if (this._styleSlot && this._styleSlot.parentNode) {
        this._styleSlot.parentNode.removeChild(this._styleSlot);
      }
      this._renderArea = null;
      this._scrollArea = null;
      this._topbar = null;
      this._imgToolbar = null;
      this._selectedImg = null;
    }

    // ── Private helpers ──

    _selectImage(img) {
      // Deselect previous
      if (this._selectedImg) this._selectedImg.classList.remove('wa-drv-img-selected');
      this._selectedImg = img;
      img.classList.add('wa-drv-img-selected');

      // Position toolbar above image
      const imgRect = img.getBoundingClientRect();
      const hostRect = $(this.containerId).getBoundingClientRect();
      this._imgToolbar.style.left = (imgRect.left - hostRect.left + imgRect.width / 2 - 60) + 'px';
      this._imgToolbar.style.top = (imgRect.top - hostRect.top - 36) + 'px';
      this._imgToolbar.classList.add('visible');
    }

    _hideImgToolbar() {
      if (this._selectedImg) this._selectedImg.classList.remove('wa-drv-img-selected');
      this._selectedImg = null;
      this._imgToolbar.classList.remove('visible');
    }

    /**
     * Fix docx-preview wrapNone anchored images.
     * Ported from DocxViewer.js — reparents position:relative wrapper divs
     * to section containers with position:absolute for correct page-coordinate positioning.
     */
    _fixWrapNoneImages() {
      if (!this._renderArea) return;
      const zoom = this._zoom / 100;

      this._renderArea.querySelectorAll('section.docx').forEach(section => {
        const secBox = section.getBoundingClientRect();

        const wrapDivs = Array.from(section.querySelectorAll('div[style]')).filter(div => {
          const s = div.style;
          return s.position === 'relative'
            && s.width === '0px'
            && s.height === '0px'
            && s.display === 'block'
            && div.querySelector('img');
        });

        wrapDivs.forEach(div => {
          const divBox = div.getBoundingClientRect();
          const cssLeft = (divBox.left - secBox.left) / zoom;
          const cssTop = (divBox.top - secBox.top) / zoom;

          const img = div.querySelector('img');
          const w = img ? (img.style.width || '') : '';
          const h = img ? (img.style.height || '') : '';

          section.appendChild(div);
          div.style.position = 'absolute';
          div.style.left = cssLeft + 'px';
          div.style.top = cssTop + 'px';
          div.style.width = w;
          div.style.height = h;
        });
      });
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

      const mountSheets = () => {
        if (!window.KotoSheetsAPI) {
          sheetEl.innerHTML = '<div style="padding:24px;color:#e74c3c;font-size:13px;">Univer Sheets 模块未就绪，请刷新页面重试</div>';
          return;
        }

        try {
          this._api = window.KotoSheetsAPI.create(sheetEl, workbookData);
          console.log('[KotoXlsxEditor] Univer Sheets 挂载成功');

          // Fix Windows DPI scaling: WebView2 applies system DPI as browser
          // zoom, distorting coordinates for Univer's canvas, toolbar, and
          // cell editor. CSS counter-zoom on the container neutralises the
          // browser zoom uniformly for all child elements.
          setTimeout(() => {
            const cssW = sheetEl.clientWidth;
            const bcrW = sheetEl.getBoundingClientRect().width;
            if (!cssW || !bcrW) return;
            const browserZoom = bcrW / cssW;

            console.log(`[KotoXlsxEditor] container CSS=${cssW} BCR=${bcrW.toFixed(1)} zoom=${browserZoom.toFixed(3)} DPR=${devicePixelRatio}`);

            if (Math.abs(browserZoom - 1) > 0.05) {
              console.log(`[KotoXlsxEditor] DPI counter-zoom: 1/${browserZoom.toFixed(3)}`);
              sheetEl.style.zoom = String(1 / browserZoom);
              sheetEl.style.width = (browserZoom * 100) + '%';
              sheetEl.style.height = (browserZoom * 100) + '%';
              sheetEl.dataset.dpiZoom = String(browserZoom);
              window.dispatchEvent(new Event('resize'));
            }
          }, 600);

          // Wire selection → AI panel context chip
          window.KotoSheetsAPI.onSelectionChange(() => {
            const text = window.KotoSheetsAPI.getSelectionText();
            if (text) {
              lastSelectionText = `[当前选中表格数据]:\n${text}\n`;
              if (typeof _pinSelectionChip === 'function') {
                _pinSelectionChip(lastSelectionText);
              }
            }
          });
        } catch (err) {
          console.error('[KotoXlsxEditor] Univer Sheets 初始化失败', err);
          sheetEl.innerHTML = `<div style="padding:24px;color:#e74c3c;font-size:13px;">表格引擎加载失败: ${err.message}</div>`;
        }
      };

      if (wrapper.offsetWidth > 0 && wrapper.offsetHeight > 0) {
        mountSheets();
      } else {
        requestAnimationFrame(() => {
          if (wrapper.offsetWidth > 0 && wrapper.offsetHeight > 0) mountSheets();
          else requestAnimationFrame(mountSheets);
        });
      }
    }

    getContent() {
      if (!window.KotoSheetsAPI || !window.KotoSheetsAPI.isReady()) return '';
      // Try fresh selection read at call time
      const text = window.KotoSheetsAPI.getSelectionText();
      if (text && text.trim()) return `[当前选中表格数据]:\n${text}\n`;
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
      // Reset DPI counter-zoom styles
      const sheetEl = $(this._containerId);
      if (sheetEl) {
        sheetEl.style.zoom = '';
        sheetEl.style.width = '';
        sheetEl.style.height = '';
        delete sheetEl.dataset.dpiZoom;
      }
      const wrapper = $(this.containerId);
      if (wrapper) {
        wrapper.classList.remove('active');
      }
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
  /** Build CSS text-decoration value from a run object (underline and/or strikethrough). */
  function _runTextDecoration(run) {
    const parts = [];
    if (run.underline)     parts.push('underline');
    if (run.strikethrough) parts.push('line-through');
    return parts.join(' ') || '';
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
      this._undoStack = [];         // history for Ctrl+Z (shape-level ops)
      this._redoStack = [];         // history for Ctrl+Y / Ctrl+Shift+Z
      this._shapeClipboard = null;  // shape copy buffer for Ctrl+C/V
      this._nudgeTimer = null;      // debounce timer for arrow-key nudge
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
          defaultFontSizePt: richData.defaultFontSizePt || richData.default_font_size_pt || 18,
          defaultTitleFontSizePt: richData.defaultTitleFontSizePt || richData.default_title_font_size_pt || 36,
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
      // The outer file-open path already waited for layout once, so keep the
      // in-editor retry short and only for the residual zero-width race.
      const _pptxMountDeadline = Date.now() + 250;
      const _tryPptxRender = () => {
        const area = $('wa-pptx-slide-area');
        const rawW = area ? area.clientWidth : 0;
        if (rawW > 48) {
          this._renderSlide(0);
          WA.pptxZoom && WA.pptxZoom(75);
        } else if (Date.now() < _pptxMountDeadline) {
          requestAnimationFrame(_tryPptxRender);
        } else {
          // Deadline reached — render anyway (will use fallback width logic inside _renderSlide)
          console.warn('[KotoPptxEditor] slide-area 宽度仍为零，使用回退宽度渲染');
          this._renderSlide(0);
          WA.pptxZoom && WA.pptxZoom(75);
          // Secondary recovery: re-render once layout is available in next frame
          setTimeout(() => { this._renderSlide(this._curIdx); }, 200);
        }
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
      if (cmd.type === 'insert_image') { showToast('PPT 暂不支持直接插入图片', 'info'); return; }
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
      this._pushUndo();
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
      this._pushUndo();
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
        { label: `${_PENCIL_SVG}  编辑文字`,  action: () => {
            const shapeEl = document.querySelector(`.wa-pptx-shape[data-shape-id="${shape.id}"]`);
            if (shapeEl) this._enterEditMode(shapeEl);
        }},
        { sep: true },
        { label: `${_CLIPBOARD_SVG}  复制形状 (Ctrl+C)`,  action: () => {
            this._shapeClipboard = JSON.parse(JSON.stringify(shape));
            showToast('已复制形状', 'info');
        }},
        { label: '⧉  粘贴并偏移 (Ctrl+V)', action: () => {
            if (!this._shapeClipboard) { showToast('剪贴板为空', 'info'); return; }
            this._pushUndo();
            const slide = this.data.slides[this._curIdx];
            const copy = JSON.parse(JSON.stringify(this._shapeClipboard));
            copy.id = -(Date.now() % 100000000);
            copy.left += 457200; copy.top += 457200;
            copy.z_order = (slide.shapes.reduce((m, s) => Math.max(m, s.z_order), 0)) + 1;
            slide.shapes.push(copy);
            this._renderSlide(this._curIdx);
            this._redrawThumb(this._curIdx);
            WA.scheduleAutoSave();
        }},
        { label: '⧉  就地复制',  action: () => this.duplicateShape(shape.id) },
        { sep: true },
        { label: '↑  上移一层',  action: () => this._reorder(shape.id, +1) },
        { label: '↓  下移一层',  action: () => this._reorder(shape.id, -1) },
        { label: '↑↑ 置于顶层',  action: () => this._bringToFront(shape.id) },
        { label: '↓↓ 置于底层',  action: () => this._sendToBack(shape.id) },
        { sep: true },
        { label: `${_TRASH_SVG}  删除形状`,  danger: true, action: () => this.deleteShape(shape.id) },
      ];

      menu.innerHTML = '';
      items.forEach(item => {
        if (item.sep) {
          const d = document.createElement('div'); d.className = 'wa-pptx-ctx-sep'; menu.appendChild(d);
        } else {
          const div = document.createElement('div');
          div.className = 'wa-pptx-ctx-item' + (item.danger ? ' danger' : '');
          div.innerHTML = item.label;
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
        { label: '+  新建幻灯片', action: () => WA.pptxAddSlide() },
        { label: '⧉  复制幻灯片 (Ctrl+Shift+D)', action: () => this._duplicateSlide() },
        { sep: true },
        { label: `${_TRASH_SVG}  删除此幻灯片`, danger: true,
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
          div.innerHTML = item.label;
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
      this._pushUndo();
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
        // Only act when PPTX editor is active
        if (!$('wa-pptx-editor').classList.contains('active')) return;
        const active = document.activeElement;

        // ── Escape ──────────────────────────────────────────────────────────
        if (e.key === 'Escape') {
          this._closeCtxMenu();
          if (this._editMode) {
            this._exitEditMode();  // exit text editing, stay selected
          } else {
            this._clearSelection();
          }
          return;
        }

        // ── Ctrl/Cmd shortcuts (global — work in or out of edit mode) ───────
        const ctrl = e.ctrlKey || e.metaKey;
        if (ctrl) {
          // Ctrl+Z — undo (shape ops; text editing native undo handled by browser)
          if (e.key === 'z' && !e.shiftKey && !this._editMode) {
            e.preventDefault(); this._undo(); return;
          }
          // Ctrl+Y / Ctrl+Shift+Z — redo
          if ((e.key === 'y' || (e.key === 'z' && e.shiftKey)) && !this._editMode) {
            e.preventDefault(); this._redo(); return;
          }
          // Ctrl+B/I/U/S — text formatting (in text edit mode)
          if (this._editMode) {
            if (e.key === 'b') { e.preventDefault(); this.applyFormat('bold');          return; }
            if (e.key === 'i') { e.preventDefault(); this.applyFormat('italic');        return; }
            if (e.key === 'u') { e.preventDefault(); this.applyFormat('underline');     return; }
            if (e.key === '.') { e.preventDefault(); this.applyFormat('strikethrough'); return; }
            // Ctrl+E/L/R/J — alignment shortcuts (in text edit mode)
            if (e.key === 'e') { e.preventDefault(); this.applyFormat('align', 'center');  return; }
            if (e.key === 'l') { e.preventDefault(); this.applyFormat('align', 'left');    return; }
            if (e.key === 'r') { e.preventDefault(); this.applyFormat('align', 'right');   return; }
            if (e.key === 'j') { e.preventDefault(); this.applyFormat('align', 'justify'); return; }
            // Ctrl+Shift+> / Ctrl+Shift+< — increase/decrease font size
            if (e.shiftKey && (e.key === '>' || e.key === '.' || e.code === 'Period')) {
              e.preventDefault(); this._stepFontSize(+1); return;
            }
            if (e.shiftKey && (e.key === '<' || e.key === ',' || e.code === 'Comma')) {
              e.preventDefault(); this._stepFontSize(-1); return;
            }
          }
          // Ctrl+M — new slide
          if (e.key === 'm') { e.preventDefault(); WA.pptxAddSlide(); return; }
          // Ctrl+Shift+D — duplicate slide
          if (e.key === 'd' && e.shiftKey && !this._editMode) {
            e.preventDefault(); this._duplicateSlide(); return;
          }
          // Ctrl+D — duplicate selected shape
          if (e.key === 'd' && !this._editMode && this._selShape) {
            e.preventDefault();
            this.duplicateShape(parseInt(this._selShape.dataset.shapeId));
            return;
          }
          // Ctrl+C — copy selected shape to clipboard buffer
          if (e.key === 'c' && !this._editMode && this._selShape) {
            const slide = this.data.slides[this._curIdx];
            const shape = (slide.shapes || []).find(s => s.id === parseInt(this._selShape.dataset.shapeId));
            if (shape) { this._shapeClipboard = JSON.parse(JSON.stringify(shape)); showToast('已复制形状', 'info'); }
            return;
          }
          // Ctrl+V — paste shape from clipboard buffer
          if (e.key === 'v' && !this._editMode && this._shapeClipboard) {
            e.preventDefault();
            this._pushUndo();
            const slide = this.data.slides[this._curIdx];
            const copy = JSON.parse(JSON.stringify(this._shapeClipboard));
            copy.id = -(Date.now() % 100000000);
            copy.left += 457200; copy.top += 457200;
            copy.z_order = (slide.shapes.reduce((m, s) => Math.max(m, s.z_order), 0)) + 1;
            slide.shapes.push(copy);
            this._renderSlide(this._curIdx);
            this._redrawThumb(this._curIdx);
            WA.scheduleAutoSave();
            return;
          }
          // Ctrl+A — select all shapes (first shape, then cycle)
          if (e.key === 'a' && !this._editMode) {
            e.preventDefault();
            const slide = this.data.slides[this._curIdx];
            if (slide && slide.shapes && slide.shapes.length) {
              const next = this._selShape
                ? ((slide.shapes.findIndex(s => s.id === parseInt(this._selShape.dataset.shapeId)) + 1) % slide.shapes.length)
                : 0;
              const shapeEl = document.querySelector(`.wa-pptx-shape[data-shape-id="${slide.shapes[next].id}"]`);
              if (shapeEl) this._selectShape(shapeEl, slide.shapes[next]);
            }
            return;
          }
          // Ctrl+Shift+] — bring shape forward / Ctrl+Shift+[ — send shape backward
          if (e.shiftKey && (e.key === ']' || e.key === '[') && !this._editMode && this._selShape) {
            e.preventDefault();
            const shapeId = parseInt(this._selShape.dataset.shapeId);
            if (e.key === ']') this._reorder(shapeId, +1);
            else this._reorder(shapeId, -1);
            return;
          }
        }

        // ── Tab / Shift+Tab — cycle through shapes ──────────────────────────
        if (e.key === 'Tab' && !this._editMode) {
          e.preventDefault();
          const slide = this.data.slides[this._curIdx];
          if (!slide || !slide.shapes || !slide.shapes.length) return;
          const curIdx = this._selShape
            ? slide.shapes.findIndex(s => s.id === parseInt(this._selShape.dataset.shapeId))
            : -1;
          const next = e.shiftKey
            ? (curIdx <= 0 ? slide.shapes.length - 1 : curIdx - 1)
            : ((curIdx + 1) % slide.shapes.length);
          const shapeEl = document.querySelector(`.wa-pptx-shape[data-shape-id="${slide.shapes[next].id}"]`);
          if (shapeEl) this._selectShape(shapeEl, slide.shapes[next]);
          return;
        }

        // ── PageUp / PageDown — navigate slides ─────────────────────────────
        if (e.key === 'PageUp') {
          e.preventDefault(); WA.pptxNav(-1); return;
        }
        if (e.key === 'PageDown') {
          e.preventDefault(); WA.pptxNav(1); return;
        }
        if (!this._editMode && this._selShape && ['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.key)) {
          e.preventDefault();
          const step = e.shiftKey ? 9144 : 914;  // 0.1 inch or ~0.01 inch in EMU
          const slide = this.data.slides[this._curIdx];
          const shape = (slide.shapes || []).find(s => s.id === parseInt(this._selShape.dataset.shapeId));
          if (!shape) return;
          // Snapshot BEFORE first nudge in a sequence (debounce: only push once per burst)
          if (!this._nudgeTimer) this._pushUndo();
          if (e.key === 'ArrowLeft')  shape.left -= step;
          if (e.key === 'ArrowRight') shape.left += step;
          if (e.key === 'ArrowUp')    shape.top  -= step;
          if (e.key === 'ArrowDown')  shape.top  += step;
          shape.left = Math.max(0, shape.left);
          shape.top  = Math.max(0, shape.top);
          this._renderSlide(this._curIdx);
          this._redrawThumb(this._curIdx);
          // Debounce auto-save for nudge to avoid hammering on key repeat
          clearTimeout(this._nudgeTimer);
          this._nudgeTimer = setTimeout(() => { this._nudgeTimer = null; WA.scheduleAutoSave(); }, 400);
          return;
        }

        // ── Delete / Backspace — remove shape or slide ───────────────────────
        if ((e.key === 'Delete' || e.key === 'Backspace') && !this._editMode) {
          e.preventDefault();
          if (this._selShape) {
            this.deleteSelected();
          } else {
            WA.pptxDelSlide();  // no shape selected → delete slide
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
                // Sync hover bar format state whenever selection changes inside a run
                if (!r.isCollapsed) this._syncHoverBar(_run);
              }
            }
          }
          // Hide hover bar when selection collapses (no text selected)
          if (r.isCollapsed) this._hideHoverBar();
        } else {
          // Collapsed or no selection — only clear saved range when still in edit mode focus
          const active = document.activeElement;
          if (!active || !active.classList.contains('wa-pptx-run')) {
            // Focus left the canvas — keep saved range so toolbar can use it
          } else {
            this._savedRange = null;
          }
          this._hideHoverBar();
        }
      };
      // Show hover bar when the user finishes text selection (mouseup inside canvas)
      const _hbSlideArea = $('wa-pptx-slide-area');
      if (_hbSlideArea && !this._hbMouseupBound) {
        this._hbMouseupBound = true;
        _hbSlideArea.addEventListener('mouseup', () => {
          setTimeout(() => {
            const sel = window.getSelection();
            if (!sel || sel.isCollapsed || !sel.rangeCount) { this._hideHoverBar(); return; }
            const text = sel.toString().trim();
            if (!text) { this._hideHoverBar(); return; }
            const range = sel.getRangeAt(0);
            if (!_hbSlideArea.contains(range.commonAncestorContainer)) { this._hideHoverBar(); return; }
            this._showHoverBar(range);
            // Sync format state (bold/italic/fontName/size/color) from the active run
            if (typeof this._syncHoverBar === 'function') {
              const activeEl = document.activeElement;
              if (activeEl && activeEl.dataset && activeEl.dataset.ri !== undefined) {
                const pi  = parseInt(activeEl.dataset.pi  ?? 0);
                const ri  = parseInt(activeEl.dataset.ri  ?? 0);
                const slides = this.data && this.data.slides;
                const run = slides && slides[this._curIdx] &&
                            slides[this._curIdx].paragraphs &&
                            slides[this._curIdx].paragraphs[pi] &&
                            slides[this._curIdx].paragraphs[pi].runs &&
                            slides[this._curIdx].paragraphs[pi].runs[ri];
                if (run) this._syncHoverBar(run);
              }
            }
            // ── Also ensure the floating AI quick-action toolbar appears BELOW ──
            // (format bar = above selection, AI bar = below — both coexist without overlap)
            lastSelectionText = text;
            _positionSelectionToolbar();
            const countEl = $('wa-tooltip-count');
            if (countEl) countEl.textContent = `${text.replace(/\s/g, '').length}字`;
            _updateContextBar({ selection: text });
          }, 30);
        });
      }
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
      // Background: try image first, then solid fill
      if (slide.backgroundImage) {
        const bgImg = new Image();
        bgImg.onload = () => {
          ctx.drawImage(bgImg, 0, 0, sw, sh);
          // Re-draw shapes on top after image loads
          this._drawThumbShapes(ctx, sw, sh, scX, scY, slide);
        };
        bgImg.src = slide.backgroundImage;
        // Draw solid fallback immediately while image loads
        ctx.fillStyle = slide.background || '#ffffff';
        ctx.fillRect(0, 0, sw, sh);
      } else {
        ctx.fillStyle = slide.background || '#ffffff';
        ctx.fillRect(0, 0, sw, sh);
      }
      this._drawThumbShapes(ctx, sw, sh, scX, scY, slide);
    }

    _drawThumbShapes(ctx, sw, sh, scX, scY, slide) {
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
      // Background: prefer image > gradient > solid color
      if (slide.backgroundImage) {
        canvas.style.background = `url('${slide.backgroundImage}') center/cover no-repeat`;
      } else if (slide.backgroundGradient) {
        canvas.style.background = slide.backgroundGradient;
      } else {
        canvas.style.background = slide.background || '#ffffff';
      }
      // Sync background swatch in toolbar
      const bgSwatch = $('wa-pptx-bg-swatch');
      if (bgSwatch) {
        if (slide.backgroundImage) {
          bgSwatch.style.backgroundImage = `url('${slide.backgroundImage}')`;
          bgSwatch.style.backgroundSize  = 'cover';
          bgSwatch.style.backgroundColor = '';
        } else {
          bgSwatch.style.backgroundImage = '';
          bgSwatch.style.backgroundColor = slide.background || '#ffffff';
        }
      }
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
        if (shape.rotation) el.style.transform = 'rotate(' + shape.rotation + 'deg)';
        // Fill: gradient > fillImage > solid color
        if (shape.fillGradient)  el.style.background = shape.fillGradient;
        else if (shape.fillImage) el.style.backgroundImage = `url('${shape.fillImage}')`;
        else if (shape.fill)      el.style.background = shape.fill;
        // Border (widthEmu stored in EMU; convert to px using scale)
        if (shape.border && shape.border.widthEmu) {
          const bwPx = Math.max(1, Math.round(shape.border.widthEmu * scale));
          el.style.border = `${bwPx}px solid ${shape.border.color || '#000'}`;
        }
        // Rounded corners for roundRect, snip, etc.
        if (shape.autoShapeType === 'roundRect' && shape.cornerRadiusEmu != null) {
          el.style.borderRadius = Math.round(shape.cornerRadiusEmu * scale) + 'px';
        }

        if (shape.has_text && shape.paragraphs) {
          el.style.cursor = 'text';
          // fontScale from PPTX normAutofit (e.g. 75 = text renders at 75% of declared pt size)
          const fontScaleMult = (shape.fontScale != null) ? shape.fontScale / 100 : 1.0;
          // spAutoFit: text was already fit at save-time — keep fixed dimensions (overflow:hidden)
          // Pick a default text color that contrasts with the EFFECTIVE background:
          // shape fill (if present) takes priority over the slide background.
          // This handles the common case of colored header bars / dark-filled shapes
          // where the theme text is white but shape.fill is dark.
          const effectiveBg = shape.fill || slide.background || '#ffffff';
          const bgLuma = _hexLuma(effectiveBg);
          const defaultTextColor = bgLuma < 0.4 ? '#f0f0f0' : '#1a1a1a';
          const inner = document.createElement('div');
          inner.className = 'wa-pptx-inner';
          // ── Dynamic text insets from PPTX bodyPr (lIns/tIns/rIns/bIns) ──
          const ins = shape.textInsets;
          let padCSS = '4px 6px';
          if (ins) {
            const pT = Math.round(ins.t * scale) + 'px';
            const pR = Math.round(ins.r * scale) + 'px';
            const pB = Math.round(ins.b * scale) + 'px';
            const pL = Math.round(ins.l * scale) + 'px';
            padCSS = `${pT} ${pR} ${pB} ${pL}`;
          }
          // ── Vertical alignment from textAnchor ──
          let justifyContent = 'flex-start';
          if (shape.textAnchor === 'ctr')  justifyContent = 'center';
          else if (shape.textAnchor === 'b') justifyContent = 'flex-end';
          inner.style.cssText = `width:100%;height:100%;padding:${padCSS};box-sizing:border-box;overflow:hidden;display:flex;flex-direction:column;justify-content:${justifyContent};color:${defaultTextColor};`;
          shape.paragraphs.forEach((para, pi) => {
            const pEl = document.createElement('div');
            pEl.className = 'wa-pptx-para';
            // ── Line spacing ──
            if (para.lineSpacing) {
              pEl.style.lineHeight = String(para.lineSpacing);
            } else if (para.lineSpacingPt) {
              pEl.style.lineHeight = Math.round(para.lineSpacingPt * scale * 12700) + 'px';
            } else {
              pEl.style.lineHeight = '1.3';
            }
            pEl.style.textAlign = (para.align || 'LEFT').toLowerCase();
            if (shape.wordWrap === 'none') {
              pEl.style.whiteSpace = 'nowrap';
              pEl.style.wordBreak  = 'normal';
            } else {
              pEl.style.wordBreak = 'break-word';
            }
            pEl.style.minHeight = '1.2em';   // ensures empty paragraphs have clickable height
            // ── Bullet / numbered list ──
            if (para.bullet) {
              pEl.style.paddingLeft = '1.8em';
              pEl.dataset.bullet = typeof para.bullet === 'string' ? para.bullet : '\u2022';
            } else if (para.numbered) {
              pEl.style.paddingLeft = '1.8em';
              pEl.dataset.numbered = '1';
            } else if (para.indent) {
              pEl.style.paddingLeft = (para.indent * 20) + 'px';
            }
            // ── Paragraph spacing (space before / after) ──
            if (para.spaceBefore) {
              pEl.style.marginTop = Math.round(para.spaceBefore * scale * 12700) + 'px';
            } else if (para.spaceBeforePct) {
              pEl.style.marginTop = (para.spaceBeforePct * 100) + '%';
            }
            if (para.spaceAfter) {
              pEl.style.marginBottom = Math.round(para.spaceAfter * scale * 12700) + 'px';
            } else if (para.spaceAfterPct) {
              pEl.style.marginBottom = (para.spaceAfterPct * 100) + '%';
            }
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
              const defaultPt = shape.is_title ? (this.data.defaultTitleFontSizePt || 36) : (this.data.defaultFontSizePt || 18);
              span.style.fontSize = Math.max(Math.round((run.size || defaultPt) * fontScaleMult * scale * 12700), 6) + 'px';
              if (run.bold)      span.style.fontWeight = 'bold';
              if (run.italic)    span.style.fontStyle = 'italic';
              const td = _runTextDecoration(run);
              if (td) span.style.textDecoration = td;
              // Build font-family with CJK fallback chain.
              // eaFontName is the East Asian font (Chinese/Japanese text in PPT often specifies
              // this exclusively). Without it, browsers fall back to a Latin font with completely
              // different glyph widths, causing text wrapping/alignment mismatches.
              if (run.eaFontName || run.fontName) {
                const parts = [];
                if (run.eaFontName) parts.push(`'${run.eaFontName}'`);
                if (run.fontName && run.fontName !== run.eaFontName) parts.push(`'${run.fontName}'`);
                // CJK system font fallbacks: covers most Windows/Mac/Linux setups
                parts.push("'Microsoft YaHei'", "'PingFang SC'", "'Noto Sans CJK SC'", "'SimSun'", 'sans-serif');
                span.style.fontFamily = parts.join(', ');
              }
              if (run.color) {
                const safe = _safeTextColor(run.color, effectiveBg);
                if (safe) span.style.color = safe;
              }
              if (run.superscript) { span.style.verticalAlign = 'super'; span.style.fontSize = Math.max(Math.round((run.size || defaultPt) * fontScaleMult * scale * 12700 * 0.75), 5) + 'px'; }
              if (run.subscript)   { span.style.verticalAlign = 'sub';   span.style.fontSize = Math.max(Math.round((run.size || defaultPt) * fontScaleMult * scale * 12700 * 0.75), 5) + 'px'; }
              if (run.highlight)   span.style.backgroundColor = run.highlight;
              if (run.charSpacing) span.style.letterSpacing = Math.round(run.charSpacing * 127 * scale) + 'px';
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
          // Cursor: border zone → 'move', interior → 'text' (matches PPT: border=move, interior=text)
          el.addEventListener('mousemove', ev => {
            if (ev.target.classList && ev.target.classList.contains('wa-pptx-handle')) return;
            if (this._editMode && this._selShape === el) { el.style.cursor = 'text'; return; }
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
            // PPT model: ONLY the border zone can drag/move the shape.
            // Interior: first click=select, second click=enter text edit. Never drags.
            const rect = el.getBoundingClientRect();
            const BORDER_T = 8;
            const onBorder = e.clientX < rect.left + BORDER_T || e.clientX > rect.right - BORDER_T ||
                             e.clientY < rect.top + BORDER_T  || e.clientY > rect.bottom - BORDER_T;
            const wasSelected = (this._selShape === el);
            this._selectShape(el, shape);
            if (onBorder) {
              // Border zone → drag to move the shape
              this._startMove(e, el, shape, canvas, scale, false, true);
            } else {
              // Interior → NEVER drag; enter text edit on mouseup only if already selected
              this._startMove(e, el, shape, canvas, scale, wasSelected, false);
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
          // Build <colgroup> with per-column proportional widths from parsed col_widths
          const colWidths = shape.col_widths && shape.col_widths.length === cols ? shape.col_widths : null;
          if (colWidths) {
            const totalW = colWidths.reduce((s, w) => s + w, 0) || 1;
            const cg = document.createElement('colgroup');
            colWidths.forEach(w => {
              const col = document.createElement('col');
              col.style.width = (w / totalW * 100).toFixed(2) + '%';
              cg.appendChild(col);
            });
            tbl.appendChild(cg);
          }
          const rowHeights = shape.row_heights && shape.row_heights.length === rows ? shape.row_heights : null;
          const baseFontPx = Math.max(Math.round(10 * 12700 * scale), 6);
          for (let r = 0; r < rows; r++) {
            const tr = document.createElement('tr');
            if (rowHeights) tr.style.height = Math.round(rowHeights[r] * scale) + 'px';
            for (let c = 0; c < cols; c++) {
              const td = document.createElement('td');
              td.className = 'wa-pptx-cell';
              td.dataset.row = r;
              td.dataset.col = c;
              td.contentEditable = 'false';
              const cellData = cellDataMap[r + '_' + c];
              // Per-cell font size overrides the table base if present
              const cellFontPx = cellData && cellData.fontSize
                ? Math.max(Math.round(cellData.fontSize * 12700 * scale), 6)
                : baseFontPx;
              td.style.cssText = `border:1px solid #d0d0d0;padding:2px 4px;overflow:hidden;font-size:${cellFontPx}px;vertical-align:top;word-break:break-word;outline:none;text-align:${(cellData && cellData.align || 'LEFT').toLowerCase()};`;
              if (cellData && cellData.fill)  td.style.backgroundColor = cellData.fill;
              if (cellData && cellData.color) td.style.color = cellData.color;
              if (cellData && cellData.bold)  td.style.fontWeight = 'bold';
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
          // ── Unknown / connector / group — render as thin line (LINE type) or invisible
          if (shape._type === 'LINE') {
            const svgNS = 'http://www.w3.org/2000/svg';
            const svg = document.createElementNS(svgNS, 'svg');
            svg.setAttribute('width',  el.style.width);
            svg.setAttribute('height', el.style.height);
            svg.style.cssText = 'position:absolute;top:0;left:0;overflow:visible;';
            const line = document.createElementNS(svgNS, 'line');
            const _w = Math.round(shape.width  * scale);
            const _h = Math.round(shape.height * scale);
            // Draw diagonal from (0,0) to (w,h); correct for vertical/horizontal lines too
            line.setAttribute('x1', '0'); line.setAttribute('y1', '0');
            line.setAttribute('x2', String(_w || 1)); line.setAttribute('y2', String(_h || 1));
            const lc = (shape.border && shape.border.color) || '#666';
            const lw = shape.border && shape.border.widthEmu
              ? Math.max(1, Math.round(shape.border.widthEmu * scale)) : 1;
            line.setAttribute('stroke', lc);
            line.setAttribute('stroke-width', String(lw));
            svg.appendChild(line);
            el.appendChild(svg);
            el.style.overflow = 'visible';
          } else {
            el.style.opacity = '0';
            el.style.pointerEvents = 'none';
          }
        }
        canvas.appendChild(el);

        // Non-editable background shapes (from slide layout/master): skip all interaction
        if (shape.editable === false) {
          el.style.pointerEvents = 'none';
          el.style.userSelect    = 'none';
          return;
        }

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
        // Snapshot BEFORE writing back (data model still has pre-drag values)
        this._pushUndo();
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
          // Snapshot BEFORE writing back (el.style already updated, data model still old)
          this._pushUndo();
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
      // Show PPTX format hoverbar when a text shape is selected (even without entering edit mode)
      if (shape && shape.has_text) {
        setTimeout(() => {
          const hb = document.getElementById('wa-pptx-hoverbar');
          if (!hb) return;
          const shapeEl = el;
          const rect = shapeEl.getBoundingClientRect();
          const hbW = hb.offsetWidth || 360;
          const hbH = hb.offsetHeight || 30;
          let top = rect.top - hbH - 6;
          if (top < 60) top = rect.bottom + 6;
          let left = rect.left + rect.width / 2 - hbW / 2;
          left = Math.max(8, Math.min(left, window.innerWidth - hbW - 8));
          top = Math.min(top, window.innerHeight - hbH - 8);
          hb.style.left = left + 'px';
          hb.style.top  = top  + 'px';
          hb.style.display = 'flex';
        }, 20);
      } else {
        // Non-text shape selected — hide the format hoverbar if it was open
        this._hideHoverBar();
      }
      // Sync shape format toolbar
      if (shape) {
        const fillSw = $('wa-pptx-shapefill-swatch');
        if (fillSw) fillSw.style.background = shape.fill || '#fff';
        if ($('wa-pptx-shapefill')) $('wa-pptx-shapefill').value = shape.fill || '#ffffff';
        const borderSw = $('wa-pptx-shapeborder-swatch');
        if (borderSw) borderSw.style.background = (shape.border && shape.border.color) || '#000';
        if ($('wa-pptx-shapeborder')) $('wa-pptx-shapeborder').value = (shape.border && shape.border.color) || '#000000';
        if ($('wa-pptx-borderwidth')) $('wa-pptx-borderwidth').value = (shape.border && shape.border.width) || 0;
        // Populate Format tab (size / pos / rotation) from DOM geometry
        const canvasEl = $('wa-pptx-slide-canvas');
        if (canvasEl && el) {
          const scaleW = parseFloat(canvasEl.style.width)  / (this.data.slideWidthEmu  || 1);
          const scaleH = parseFloat(canvasEl.style.height) / (this.data.slideHeightEmu || 1);
          const pxW = Math.round((shape.width  || 0) * scaleW);
          const pxH = Math.round((shape.height || 0) * scaleH);
          const pxX = Math.round((shape.left   || 0) * scaleW);
          const pxY = Math.round((shape.top    || 0) * scaleH);
          if ($('wa-pptx-shapeW'))   $('wa-pptx-shapeW').value   = pxW;
          if ($('wa-pptx-shapeH'))   $('wa-pptx-shapeH').value   = pxH;
          if ($('wa-pptx-shapeX'))   $('wa-pptx-shapeX').value   = pxX;
          if ($('wa-pptx-shapeY'))   $('wa-pptx-shapeY').value   = pxY;
          if ($('wa-pptx-shapeRot')) $('wa-pptx-shapeRot').value = Math.round(shape.rotation || 0);
        }
        if ($('wa-pptx-opacity')) $('wa-pptx-opacity').value = Math.round((shape.opacity !== undefined ? shape.opacity : 1) * 100);
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
      this._hideHoverBar();
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
      this._hideHoverBar();
    }

    // ── Floating format hover bar (文字格式助手) ───────────────────────────────

    _showHoverBar(range) {
      const hb = document.getElementById('wa-pptx-hoverbar');
      if (!hb) return;
      hb.style.display = 'flex';
      let rect = range.getBoundingClientRect();
      // Fallback: getClientRects()[0] for cross-block or single-caret selections
      if (!rect || rect.height === 0) {
        const rects = range.getClientRects();
        for (let i = 0; i < rects.length; i++) {
          if (rects[i].height > 0) { rect = rects[i]; break; }
        }
      }
      // Last resort: anchor to the selected shape element
      if (!rect || rect.height === 0) {
        const shapeEl = this._selShape && document.querySelector(`.wa-pptx-shape[data-si="${this._selShape.shapeIdx ?? ''}"]`);
        if (shapeEl) rect = shapeEl.getBoundingClientRect();
      }
      if (!rect || rect.height === 0) { hb.style.display = 'none'; return; }
      const hbW = hb.offsetWidth || 360;
      const hbH = hb.offsetHeight || 30;
      let top = rect.top - hbH - 6;
      if (top < 60) top = rect.bottom + 6;
      let left = rect.left + rect.width / 2 - hbW / 2;
      left = Math.max(8, Math.min(left, window.innerWidth - hbW - 8));
      top = Math.min(top, window.innerHeight - hbH - 8);
      hb.style.left = left + 'px';
      hb.style.top  = top  + 'px';
    }

    _hideHoverBar() {
      const hb = document.getElementById('wa-pptx-hoverbar');
      if (hb) hb.style.display = 'none';
    }

    _syncHoverBar(run) {
      if (!run) return;
      const hbName = document.getElementById('wa-hb-fontname');
      const hbSize = document.getElementById('wa-hb-fontsize');
      const hbBold = document.getElementById('wa-hb-bold');
      const hbItal = document.getElementById('wa-hb-italic');
      const hbUnd  = document.getElementById('wa-hb-underline');
      const hbSw   = document.getElementById('wa-hb-color-swatch');
      if (hbName && run.fontName) hbName.value = run.fontName;
      if (hbSize && run.size)     hbSize.value  = Math.round(run.size);
      if (hbBold)  hbBold.classList.toggle('active',  !!run.bold);
      if (hbItal)  hbItal.classList.toggle('active',  !!run.italic);
      if (hbUnd)   hbUnd.classList.toggle('active',   !!run.underline);
      if (hbSw && run.color) hbSw.style.background = run.color;
    }

    _onRunFocus(shapeEl, shape, pi, ri, run) {
      this._activeSpan = document.activeElement;  // save before focus can move to toolbar
      this._selectShape(shapeEl, shape);
      if ($('wa-pptx-bold'))        $('wa-pptx-bold').classList.toggle('active',        !!run.bold);
      if ($('wa-pptx-italic'))      $('wa-pptx-italic').classList.toggle('active',      !!run.italic);
      if ($('wa-pptx-underline'))   $('wa-pptx-underline').classList.toggle('active',   !!run.underline);
      if ($('wa-pptx-strike'))      $('wa-pptx-strike').classList.toggle('active',      !!run.strikethrough);
      if ($('wa-pptx-super'))       $('wa-pptx-super').classList.toggle('active',       !!run.superscript);
      if ($('wa-pptx-sub'))         $('wa-pptx-sub').classList.toggle('active',         !!run.subscript);
      const _hsFocus = $('wa-pptx-highlight-swatch');
      if (_hsFocus) _hsFocus.style.background = run.highlight || 'transparent';
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
      if (prop === 'bold')          run.bold          = value;
      else if (prop === 'italic')        run.italic        = value;
      else if (prop === 'underline')     run.underline     = value;
      else if (prop === 'strikethrough') run.strikethrough = value;
      else if (prop === 'superscript')   { run.superscript = value; if (value) run.subscript = false; }
      else if (prop === 'subscript')     { run.subscript   = value; if (value) run.superscript = false; }
      else if (prop === 'highlight')     run.highlight     = value;
      else if (prop === 'size')          run.size          = parseFloat(value);
      else if (prop === 'fontName')      run.fontName      = value;
      else if (prop === 'color')         run.color         = value;
    }

    applyFormat(prop, value) {
      this._pushUndo();
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
            if (prop === 'bold')            value = !run.bold;
            else if (prop === 'italic')         value = !run.italic;
            else if (prop === 'underline')      value = !run.underline;
            else if (prop === 'strikethrough')  value = !run.strikethrough;
            else if (prop === 'superscript')    value = !run.superscript;
            else if (prop === 'subscript')      value = !run.subscript;

            if (s === 0 && e === text.length) {
              // Whole span selected — just apply to the run in-place, no split needed
              this._applyRunProp(run, prop, value);
              startSpan.style.fontWeight      = run.bold      ? 'bold'      : '';
              startSpan.style.fontStyle       = run.italic    ? 'italic'    : '';
              startSpan.style.textDecoration  = _runTextDecoration(run);
              if (prop === 'size') {
                const scaleW = parseFloat($('wa-pptx-slide-canvas').style.width) / this.data.slideWidthEmu;
                startSpan.style.fontSize = Math.max(Math.round(run.size * scaleW * 12700), 6) + 'px';
              }
              if (prop === 'fontName') startSpan.style.fontFamily = value;
              if (prop === 'color')    startSpan.style.color = value;
              if (prop === 'superscript' || prop === 'subscript') {
                startSpan.style.verticalAlign = run.superscript ? 'super' : (run.subscript ? 'sub' : '');
                startSpan.style.fontSize = (run.superscript || run.subscript)
                  ? Math.max(Math.round((run.size || 18) * (parseFloat($('wa-pptx-slide-canvas').style.width) / this.data.slideWidthEmu) * 12700 * 0.75), 5) + 'px'
                  : Math.max(Math.round((run.size || 18) * (parseFloat($('wa-pptx-slide-canvas').style.width) / this.data.slideWidthEmu) * 12700), 6) + 'px';
              }
              if (prop === 'highlight') startSpan.style.backgroundColor = value || '';
              if (prop === 'align') {
                para.align = value.toUpperCase();
                if (startSpan.parentElement) startSpan.parentElement.style.textAlign = value;
              }
              if (prop === 'lineSpacing') {
                para.lineSpacing = value;
                if (startSpan.parentElement) startSpan.parentElement.style.lineHeight = value;
              }
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
        if (idx === 0 && (prop === 'bold' || prop === 'italic' || prop === 'underline' || prop === 'strikethrough' || prop === 'superscript' || prop === 'subscript')) {
          toggleVal = !run[prop];
        }
        const fVal = (prop === 'bold' || prop === 'italic' || prop === 'underline' || prop === 'strikethrough' || prop === 'superscript' || prop === 'subscript') ? toggleVal : value;
        this._applyRunProp(run, prop, fVal);

        // Live DOM update (no full re-render needed)
        active.style.fontWeight     = run.bold      ? 'bold'      : '';
        active.style.fontStyle      = run.italic    ? 'italic'    : '';
        active.style.textDecoration = _runTextDecoration(run);
        if (prop === 'size') {
          const scaleW = parseFloat($('wa-pptx-slide-canvas').style.width) / this.data.slideWidthEmu;
          active.style.fontSize = Math.max(Math.round(run.size * scaleW * 12700), 6) + 'px';
        }
        if (prop === 'fontName') active.style.fontFamily = value;
        if (prop === 'color')    active.style.color = value;
        if (prop === 'superscript' || prop === 'subscript') {
          active.style.verticalAlign = run.superscript ? 'super' : (run.subscript ? 'sub' : '');
          const scaleW = parseFloat($('wa-pptx-slide-canvas').style.width) / this.data.slideWidthEmu;
          active.style.fontSize = (run.superscript || run.subscript)
            ? Math.max(Math.round((run.size || 18) * scaleW * 12700 * 0.75), 5) + 'px'
            : Math.max(Math.round((run.size || 18) * scaleW * 12700), 6) + 'px';
        }
        if (prop === 'highlight') active.style.backgroundColor = fVal || '';
        // Paragraph-level props
        if (prop === 'align') {
          shape.paragraphs[pi].align = fVal.toUpperCase();
          if (active.parentElement) active.parentElement.style.textAlign = fVal;
        }
        if (prop === 'lineSpacing') {
          shape.paragraphs[pi].lineSpacing = fVal;
          if (active.parentElement) active.parentElement.style.lineHeight = fVal;
        }
        if (prop === 'bullet') {
          const para = shape.paragraphs[pi];
          para.bullet = fVal;
          if (fVal) para.numbered = false;
          const pEl = active.parentElement;
          if (pEl) { pEl.style.paddingLeft = fVal ? '1.5em' : ''; pEl.dataset.bullet = fVal ? (typeof fVal === 'string' ? fVal : '•') : ''; }
        }
        if (prop === 'numbered') {
          const para = shape.paragraphs[pi];
          para.numbered = fVal;
          if (fVal) para.bullet = false;
          const pEl = active.parentElement;
          if (pEl) pEl.dataset.numbered = fVal ? '1' : '';
        }
        if (prop === 'indent') {
          const para = shape.paragraphs[pi];
          para.indent = Math.max(0, (para.indent || 0) + (fVal || 0));
          const pEl = active.parentElement;
          if (pEl) pEl.style.paddingLeft = (para.indent * 20) + 'px';
        }
        // Shape-level vertical-align (textAnchor)
        if (prop === 'verticalAlign') {
          const shapeEl = this._selShape;
          if (shapeEl) {
            shape.textAnchor = fVal;
            const inner = shapeEl.querySelector('.wa-pptx-inner');
            if (inner) {
              const jcMap = { t: 'flex-start', ctr: 'center', b: 'flex-end' };
              inner.style.justifyContent = jcMap[fVal] || 'flex-start';
            }
          }
        }
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
        if ($('wa-pptx-strike'))    $('wa-pptx-strike').classList.toggle('active',    !!firstRun.strikethrough);
        if ($('wa-pptx-super'))     $('wa-pptx-super').classList.toggle('active',     !!firstRun.superscript);
        if ($('wa-pptx-sub'))       $('wa-pptx-sub').classList.toggle('active',       !!firstRun.subscript);
        const _hs = $('wa-pptx-highlight-swatch');
        if (_hs) _hs.style.background = firstRun.highlight || 'transparent';
      }
      WA.scheduleAutoSave();
    }

    setZoom(pct) {
      this._zoom = pct / 100;
      this._renderSlide(this._curIdx);
    }

    // ── Font size stepping (Ctrl+Shift+> / <) ────────────────────────────────

    _stepFontSize(dir) {
      const SIZES = [8,9,10,11,12,14,16,18,20,22,24,28,32,36,40,44,48,54,60,66,72,80,88,96];
      // Get current size from active span / savedRange
      const span = this._activeSpan;
      if (!span) return;
      const shapeId = parseInt(span.dataset.shapeId);
      const pi = parseInt(span.dataset.pi), ri = parseInt(span.dataset.ri);
      const slide = this.data.slides[this._curIdx];
      const shape = slide && (slide.shapes || []).find(s => s.id === shapeId);
      const run = shape && shape.paragraphs[pi] && shape.paragraphs[pi].runs[ri];
      if (!run) return;
      const curSize = Math.round(run.size || 18);
      let idx = SIZES.findIndex(s => s >= curSize);
      if (idx === -1) idx = SIZES.length - 1;
      const newIdx = Math.max(0, Math.min(SIZES.length - 1, idx + dir));
      this.applyFormat('size', SIZES[newIdx]);
      // Update toolbar font size display
      if ($('wa-pptx-fontsize')) $('wa-pptx-fontsize').value = SIZES[newIdx];
    }

    // ── Duplicate current slide ──────────────────────────────────────────────

    _duplicateSlide() {
      if (!this.data || !this.data.slides.length) return;
      this._pushUndo();
      const src = this.data.slides[this._curIdx];
      const copy = JSON.parse(JSON.stringify(src));
      // Assign new unique IDs to all shapes
      copy.shapes.forEach(s => { s.id = -(Date.now() % 100000000) - Math.floor(Math.random() * 10000); });
      const insertIdx = this._curIdx + 1;
      this.data.slides.splice(insertIdx, 0, copy);
      this.data.slides.forEach((s, i) => { s.index = i; });
      this._buildThumbs();
      this._renderSlide(insertIdx);
      WA.scheduleAutoSave();
      showToast('已复制幻灯片', 'info');
    }

    // ── Z-order: bring to front / send to back ──────────────────────────────

    _bringToFront(shapeId) {
      this._pushUndo();
      const slide = this.data.slides[this._curIdx];
      const shape = (slide.shapes || []).find(s => s.id === shapeId);
      if (!shape) return;
      shape.z_order = (slide.shapes.reduce((m, s) => Math.max(m, s.z_order), 0)) + 1;
      this._renderSlide(this._curIdx);
      WA.scheduleAutoSave();
    }

    _sendToBack(shapeId) {
      this._pushUndo();
      const slide = this.data.slides[this._curIdx];
      const shape = (slide.shapes || []).find(s => s.id === shapeId);
      if (!shape) return;
      const minZ = slide.shapes.reduce((m, s) => Math.min(m, s.z_order), Infinity);
      shape.z_order = Math.max(0, minZ - 1);
      this._renderSlide(this._curIdx);
      WA.scheduleAutoSave();
    }

    // ── Undo / Redo ──────────────────────────────────────────────────────────

    /** Snapshot current data + slideIdx onto the undo stack before any mutations. */
    _pushUndo() {
      this._undoStack.push({ slideIdx: this._curIdx, data: JSON.parse(JSON.stringify(this.data)) });
      if (this._undoStack.length > 50) this._undoStack.shift();
      this._redoStack = [];
      this._updateUndoRedoUI();
    }

    _undo() {
      if (!this._undoStack.length) return;
      this._redoStack.push({ slideIdx: this._curIdx, data: JSON.parse(JSON.stringify(this.data)) });
      const snap = this._undoStack.pop();
      this.data = snap.data;
      this._selShape = null;
      this._activeSpan = null;
      this._editMode = false;
      this._buildThumbs();
      this._renderSlide(Math.min(snap.slideIdx, this.data.slides.length - 1));
      this._updateUndoRedoUI();
      WA.scheduleAutoSave();
    }

    _redo() {
      if (!this._redoStack.length) return;
      this._undoStack.push({ slideIdx: this._curIdx, data: JSON.parse(JSON.stringify(this.data)) });
      const snap = this._redoStack.pop();
      this.data = snap.data;
      this._selShape = null;
      this._activeSpan = null;
      this._editMode = false;
      this._buildThumbs();
      this._renderSlide(Math.min(snap.slideIdx, this.data.slides.length - 1));
      this._updateUndoRedoUI();
      WA.scheduleAutoSave();
    }

    _updateUndoRedoUI() {
      const u = $('wa-pptx-undo');
      const r = $('wa-pptx-redo');
      if (u) u.disabled = !this._undoStack.length;
      if (r) r.disabled = !this._redoStack.length;
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
  // ═══════════════════════════════════════════════════════════════════════════
  // KotoPdfViewer — Adobe-style PDF viewer with Phase 1-2 features:
  //   Phase 1: Thumbnails sidebar, bookmarks, in-document search (Ctrl+F),
  //            lazy/progressive page loading, metadata display
  //   Phase 2: Annotation layer (highlight/underline/strikethrough/note/draw),
  //            annotation persistence (embed into PDF via backend),
  //            AI-powered auto-annotation
  // ═══════════════════════════════════════════════════════════════════════════
  class KotoPdfViewer {
    constructor() {
      this.containerId   = 'wa-pdf-viewer';
      this._scale        = 1.0;
      this._pdfDoc       = null;
      this._pdfUrl       = null;
      this._pageCount    = 0;
      this._outline      = [];          // [{title, page, children}]
      this._metadata     = {};

      // Annotation state
      this._annotations  = [];          // in-memory annotation list
      this._annotMode    = null;        // 'highlight' | 'underline' | 'strikethrough' | 'note' | 'draw' | 'rect' | 'ellipse' | 'line' | 'arrow' | 'textbox' | 'eraser'
      this._annotColor   = '#FFFF00';   // current annotation color
      this._annotLineWidth = 2;         // line width for shapes and freehand
      this._drawPath     = null;        // active SVG path element during drawing
      this._drawPoints   = [];          // points during freehand draw
      this._shapePreview = null;        // live preview SVG element during shape drag
      this._shapeStart   = null;        // {x, y} drag start point
      this._shapeSvg     = null;        // SVG layer being drawn on
      this._shapePageNum = 0;           // page number being drawn on

      // Search state
      this._searchQuery  = '';
      this._searchPgs    = [];          // [{page, rects:[{x,y,w,h}]}] in CSS px, per match
      this._searchIdx    = -1;

      // Lazy loading
      this._observer     = null;        // IntersectionObserver
      this._renderedPgs  = new Set();   // set of 1-based page nums that have been rendered
      this._textContent  = {};          // page → pdfjsLib textContent (for search)
      this._thumbCanvas  = {};          // page → small canvas element (thumbnails)

      // Sidebar state
      this._sidebarPanel = 'thumbs';    // 'thumbs' | 'bookmarks'

      // Keyboard handler (Ctrl+F)
      this._keyHandler = (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key === 'f') {
          if (state.fileType === 'pdf') {
            e.preventDefault();
            this.searchOpen();
          }
        }
        if (e.key === 'Escape' && state.fileType === 'pdf') {
          this.searchClose();
        }
      };
      document.addEventListener('keydown', this._keyHandler);

      // Wheel zoom
      this._wheelHandler = (e) => {
        if (!e.ctrlKey && !e.metaKey) return;
        e.preventDefault();
        const delta = e.deltaY > 0 ? -10 : 10;
        const newPct = Math.max(50, Math.min(300, Math.round(this._scale * 100) + delta));
        this.setZoom(newPct);
      };

      const container = $(this.containerId);
      container.classList.add('active');
      container.addEventListener('wheel', this._wheelHandler, { passive: false });
      container.addEventListener('mouseup', this._onMouseUp.bind(this));
      container.addEventListener('mousedown', this._onMouseDown.bind(this));
      container.addEventListener('mousemove', this._onMouseMove.bind(this));
      container.addEventListener('scroll', this._onScroll.bind(this), { passive: true });

      document.addEventListener('mousedown', (e) => {
        if (!e.target.closest('#wa-pdf-tooltip')) {
          $('wa-pdf-tooltip').style.display = 'none';
        }
      });

      const outer = $('wa-pdf-editor');
      if (outer) outer.classList.add('active');
    }

    // ─── render ──────────────────────────────────────────────────────────────
    async render(pdfUrl, pagesData) {
      this._pdfUrl    = pdfUrl;
      this._scale     = 1.0;
      this._outline   = (pagesData && pagesData.outline)  || [];
      this._metadata  = (pagesData && pagesData.metadata) || {};
      this._annotations = [];
      this._renderedPgs.clear();
      this._textContent = {};

      _updatePdfZoomUI(100);

      await this._doRender();

      // Load existing annotations if any are embedded in the PDF
      this._loadAnnotationsFromServer();
    }

    // ─── _doRender ───────────────────────────────────────────────────────────
    async _doRender() {
      const pdfUrl = this._pdfUrl;
      const c = $(this.containerId);
      c.innerHTML = '';

      if (typeof pdfjsLib === 'undefined') {
        c.innerHTML = '<div style="color:var(--danger);padding:16px">PDF.js 加载失败</div>';
        return;
      }

      try {
        if (!this._pdfDoc || this._pdfDoc._url !== pdfUrl) {
          const loadingTask = pdfjsLib.getDocument(pdfUrl);
          this._pdfDoc = await loadingTask.promise;
          this._pdfDoc._url = pdfUrl;
        }
        const pdf = this._pdfDoc;
        this._pageCount = pdf.numPages;

        // Containers for deferred render
        this._renderedPgs.clear();
        this._textContent = {};

        // Estimate page size for placeholders (use page 1)
        const firstPage = await pdf.getPage(1);
        const baseVP = firstPage.getViewport({ scale: 1 });
        const containerW = (c.clientWidth || 800) - 32;
        const dpr = window.devicePixelRatio || 1;
        this._quality = Math.max(2, dpr);
        this._containerW = containerW;
        this._baseAspect = baseVP.height / baseVP.width;

        // Build placeholder pages for ALL pages (lazy rendering via IntersectionObserver)
        for (let i = 1; i <= pdf.numPages; i++) {
          const wrap = document.createElement('div');
          wrap.className = 'wa-pdf-page-wrap';
          wrap.id = `pdf-page-${i}`;
          wrap.dataset.page = i;

          // Placeholder canvas with estimated size
          const canvas = document.createElement('canvas');
          const fitScale = (containerW / baseVP.width) * this._scale;
          canvas.style.width  = Math.floor(baseVP.width  * fitScale) + 'px';
          canvas.style.height = Math.floor(baseVP.height * fitScale) + 'px';
          canvas.style.background = '#e8e8e8';
          canvas.style.borderRadius = '2px';
          canvas.width  = 1;  // minimal actual pixels until rendered
          canvas.height = 1;
          wrap.appendChild(canvas);
          c.appendChild(wrap);
        }

        // Disconnect old observer and set up new one
        if (this._observer) this._observer.disconnect();
        this._observer = new IntersectionObserver(
          (entries) => entries.forEach(en => {
            if (en.isIntersecting) {
              const pg = parseInt(en.target.dataset.page, 10);
              if (pg && !this._renderedPgs.has(pg)) {
                this._renderPage(pg);
              }
            }
          }),
          { root: c, rootMargin: '300px 0px 300px 0px', threshold: 0 }
        );
        c.querySelectorAll('.wa-pdf-page-wrap').forEach(el => this._observer.observe(el));

        // Build sidebar
        this._buildThumbs();
        this._buildBookmarks();

        // Update page counter
        this._updatePageCounter(1);

      } catch (e) {
        console.error('[KotoPdfViewer] render error:', e);
        c.innerHTML = `<div style="color:var(--danger);padding:16px">PDF 渲染报错: ${e.message}</div>`;
      }
    }

    // ─── _renderPage ─────────────────────────────────────────────────────────
    async _renderPage(pageNum) {
      if (this._renderedPgs.has(pageNum) || !this._pdfDoc) return;
      this._renderedPgs.add(pageNum);

      const wrap = document.getElementById(`pdf-page-${pageNum}`);
      if (!wrap) return;

      try {
        const pdf = this._pdfDoc;
        const page = await pdf.getPage(pageNum);
        const baseViewport = page.getViewport({ scale: 1 });
        const containerW = this._containerW || 800;
        const quality = this._quality || 2;
        const fitScale = (containerW / baseViewport.width) * this._scale;
        const renderViewport = page.getViewport({ scale: fitScale * quality });
        // textViewport drives both canvas CSS size AND text layer — must be the same object.
        // Using Math.floor() would create a sub-pixel mismatch between span coordinates
        // (float) and the container, causing selection drift and highlight misalignment.
        const textViewport = page.getViewport({ scale: fitScale });
        // Math.ceil: ensures container is never smaller than the viewport coordinate space.
        // A sub-pixel deficit (floor) would cause overflow:hidden to clip rightmost/bottom
        // spans, making those characters unselectable. Ceiling adds at most 1px of safe margin.
        const cssW = Math.ceil(textViewport.width);
        const cssH = Math.ceil(textViewport.height);

        // Replace placeholder canvas with real one
        const canvas = wrap.querySelector('canvas') || document.createElement('canvas');
        const context = canvas.getContext('2d');
        canvas.width  = Math.round(renderViewport.width);
        canvas.height = Math.round(renderViewport.height);
        canvas.style.width  = cssW + 'px';
        canvas.style.height = cssH + 'px';
        canvas.style.background = '';

        if (!wrap.contains(canvas)) wrap.insertBefore(canvas, wrap.firstChild);

        await page.render({ canvasContext: context, viewport: renderViewport }).promise;

        // Add text layer for selection and search
        this._addTextLayer(wrap, page, textViewport, cssW, cssH);

        // Add annotation SVG overlay
        this._addAnnotLayer(wrap, pageNum, cssW, cssH);

        // Re-render annotations for this page
        this._renderAnnotationsOnPage(pageNum);

        // Re-render search highlights
        if (this._searchQuery) this._renderSearchOnPage(pageNum);

        // Extract text for search index (background)
        this._extractPageText(page, pageNum);

        // Update thumbnail if needed (draw on existing thumb canvas)
        this._drawThumbForPage(pageNum, page, baseViewport);

      } catch (e) {
        console.warn(`[KotoPdfViewer] page ${pageNum} render error:`, e);
      }
    }

    // ─── _addTextLayer ───────────────────────────────────────────────────────
    // textViewport must be the SAME viewport used to set canvas CSS width/height.
    // This guarantees span coordinates exactly match the container pixel grid,
    // which is required for correct selection hit-testing and highlight alignment.
    async _addTextLayer(wrap, page, textViewport, cssW, cssH) {
      // Remove old text layer if re-rendering
      const old = wrap.querySelector('.wa-pdf-text-layer');
      if (old) old.remove();

      const div = document.createElement('div');
      div.className = 'wa-pdf-text-layer';
      div.style.width  = cssW + 'px';
      div.style.height = cssH + 'px';
      div.style.setProperty('--scale-factor', textViewport.scale);
      wrap.appendChild(div);

      try {
        const textContent = await page.getTextContent();

        // Use the viewport passed in — do NOT create a new one here.
        // Creating a second getViewport() call may return a slightly different
        // float width/height due to internal rounding, breaking span alignment.
        // pdfjs-dist 3.x API uses "textContent" (resolved object from getTextContent()).
        // "textContentSource" is the 4.x stream API — passing it to 3.x causes an error,
        // which triggers the catch block and sets pointerEvents:none on the layer,
        // making all text unselectable.
        const renderTask = pdfjsLib.renderTextLayer({
          textContent: textContent,
          container: div,
          viewport: textViewport,
        });
        await renderTask.promise;
      } catch (e) {
        // text layer is best-effort — don't block render
        div.style.pointerEvents = 'none';
      }
    }

    // ─── _addAnnotLayer ──────────────────────────────────────────────────────
    _addAnnotLayer(wrap, pageNum, cssW, cssH) {
      const old = wrap.querySelector('.wa-pdf-annot-layer');
      if (old) old.remove();

      const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      svg.classList.add('wa-pdf-annot-layer');
      svg.dataset.page = pageNum;
      svg.setAttribute('width', cssW);
      svg.setAttribute('height', cssH);
      svg.style.width  = cssW + 'px';
      svg.style.height = cssH + 'px';
      wrap.appendChild(svg);

      // Drawing mode pointer events
      svg.addEventListener('mousedown', (e) => {
        if (this._annotMode === 'draw') this._startDraw(e, svg, pageNum);
        else if (this._annotMode === 'note') this._placeNote(e, wrap, pageNum);
      });

      return svg;
    }

    // ─── _extractPageText (async, for search) ────────────────────────────────
    async _extractPageText(page, pageNum) {
      if (this._textContent[pageNum]) return;
      try {
        const tc = await page.getTextContent();
        this._textContent[pageNum] = tc.items.map(it => it.str).join(' ');
      } catch (_) {}
    }

    // ─── _buildThumbs ────────────────────────────────────────────────────────
    async _buildThumbs() {
      const strip = $('wa-pdf-thumbstrip');
      if (!strip) return;
      strip.innerHTML = '';

      const pdf = this._pdfDoc;
      if (!pdf) return;

      for (let i = 1; i <= pdf.numPages; i++) {
        const wrap = document.createElement('div');
        wrap.className = 'wa-pdf-thumb-wrap';

        const thumbDiv = document.createElement('div');
        thumbDiv.className = 'wa-pdf-thumb' + (i === 1 ? ' active' : '');
        thumbDiv.id = `pdf-thumb-${i}`;

        const canvas = document.createElement('canvas');
        canvas.style.display = 'block';
        thumbDiv.appendChild(canvas);

        const idx = document.createElement('span');
        idx.className = 'wa-pdf-thumb-idx';
        idx.textContent = i;

        wrap.appendChild(thumbDiv);
        wrap.appendChild(idx);
        wrap.addEventListener('click', () => this._scrollToPage(i));
        strip.appendChild(wrap);

        // Render thumbnail asynchronously
        this._renderThumb(i, canvas);
      }
    }

    async _renderThumb(pageNum, canvas) {
      try {
        const page = await this._pdfDoc.getPage(pageNum);
        const baseVP = page.getViewport({ scale: 1 });
        const THUMB_W = 148;
        const scale = THUMB_W / baseVP.width;
        const vp = page.getViewport({ scale });
        canvas.width  = Math.floor(vp.width);
        canvas.height = Math.floor(vp.height);
        canvas.style.width  = Math.floor(vp.width) + 'px';
        canvas.style.height = Math.floor(vp.height) + 'px';
        await page.render({ canvasContext: canvas.getContext('2d'), viewport: vp }).promise;
      } catch (_) {}
    }

    _drawThumbForPage(pageNum, page, baseViewport) {
      const thumbDiv = document.getElementById(`pdf-thumb-${pageNum}`);
      if (!thumbDiv) return;
      const canvas = thumbDiv.querySelector('canvas');
      if (!canvas || canvas.width > 1) return; // already rendered by _renderThumb
      this._renderThumb(pageNum, canvas);
    }

    // ─── _buildBookmarks ─────────────────────────────────────────────────────
    _buildBookmarks() {
      const panel = $('wa-pdf-bookmarks');
      if (!panel) return;
      panel.innerHTML = '';

      if (!this._outline || this._outline.length === 0) {
        const empty = document.createElement('div');
        empty.className = 'wa-pdf-bm-empty';
        empty.textContent = '无书签';
        panel.appendChild(empty);
        return;
      }

      const render = (items, container) => {
        items.forEach(item => {
          const div = document.createElement('div');
          div.className = 'wa-pdf-bm-item wa-pdf-bm-children';

          const toggle = document.createElement('span');
          toggle.className = 'wa-pdf-bm-toggle';
          toggle.textContent = item.children && item.children.length ? '▶' : '';

          const label = document.createElement('span');
          label.style.flex = '1';
          label.style.overflow = 'hidden';
          label.style.textOverflow = 'ellipsis';
          label.style.whiteSpace = 'nowrap';
          label.textContent = item.title || '(无标题)';
          label.title = item.title || '';

          const pg = document.createElement('span');
          pg.className = 'wa-pdf-bm-pg';
          if (item.page) pg.textContent = item.page;

          div.appendChild(toggle);
          div.appendChild(label);
          div.appendChild(pg);

          div.addEventListener('click', () => {
            if (item.page) this._scrollToPage(item.page);
          });

          container.appendChild(div);

          if (item.children && item.children.length) {
            const child = document.createElement('div');
            child.className = 'wa-pdf-bm-children';
            child.style.display = 'none';
            render(item.children, child);
            container.appendChild(child);

            toggle.textContent = '▶';
            toggle.style.cursor = 'pointer';
            toggle.addEventListener('click', (e) => {
              e.stopPropagation();
              const isOpen = child.style.display !== 'none';
              child.style.display = isOpen ? 'none' : 'block';
              toggle.textContent = isOpen ? '▶' : '▼';
            });
          }
        });
      };

      render(this._outline, panel);
    }

    // ─── _scrollToPage ───────────────────────────────────────────────────────
    _scrollToPage(pageNum) {
      const wrap = document.getElementById(`pdf-page-${pageNum}`);
      if (wrap) wrap.scrollIntoView({ behavior: 'smooth', block: 'start' });
      this._highlightThumb(pageNum);
    }

    _highlightThumb(pageNum) {
      const strip = $('wa-pdf-thumbstrip');
      if (!strip) return;
      strip.querySelectorAll('.wa-pdf-thumb').forEach(el => el.classList.remove('active'));
      const thumb = document.getElementById(`pdf-thumb-${pageNum}`);
      if (thumb) {
        thumb.classList.add('active');
        thumb.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      }
    }

    _updatePageCounter(pageNum) {
      const counter = $('wa-pdf-page-counter');
      if (counter) counter.textContent = `第 ${pageNum} 页，共 ${this._pageCount} 页`;
    }

    _onScroll() {
      // Find the page whose center is closest to the scroll container center
      const c = $(this.containerId);
      if (!c) return;
      const scrollMid = c.scrollTop + c.clientHeight / 2;
      let bestPage = 1, bestDist = Infinity;
      c.querySelectorAll('.wa-pdf-page-wrap').forEach(el => {
        const pg = parseInt(el.dataset.page, 10);
        const mid = el.offsetTop + el.offsetHeight / 2;
        const dist = Math.abs(mid - scrollMid);
        if (dist < bestDist) { bestDist = dist; bestPage = pg; }
      });
      this._updatePageCounter(bestPage);
      this._highlightThumb(bestPage);
    }

    // ─── zoom ─────────────────────────────────────────────────────────────────
    setZoom(pct) {
      this._scale = Math.max(0.5, Math.min(3.0, pct / 100));
      _updatePdfZoomUI(Math.round(this._scale * 100));
      // Re-render all pages at new scale
      this._renderedPgs.clear();
      const c = $(this.containerId);
      if (c) {
        c.querySelectorAll('.wa-pdf-page-wrap').forEach(el => {
          const pg = parseInt(el.dataset.page, 10);
          // Reset canvas to placeholder
          const cv = el.querySelector('canvas');
          if (cv) {
            cv.style.background = '#f0f0f0';
            cv.width = 1; cv.height = 1;
          }
          const tl = el.querySelector('.wa-pdf-text-layer');
          if (tl) tl.remove();
        });
      }
      // Re-trigger intersection observer
      if (this._observer) {
        this._observer.disconnect();
        if (c) {
          c.querySelectorAll('.wa-pdf-page-wrap').forEach(el => this._observer.observe(el));
        }
      }
    }

    // ─── Sidebar tab switch ───────────────────────────────────────────────────
    sidebarTab(btn) {
      const panel = btn.dataset.panel;
      document.querySelectorAll('.wa-pdf-stab').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      $('wa-pdf-thumbstrip').style.display = panel === 'thumbs' ? 'flex' : 'none';
      $('wa-pdf-bookmarks').style.display  = panel === 'bookmarks' ? 'flex' : 'none';
      this._sidebarPanel = panel;
    }

    toggleSidebar() {
      const sb = $('wa-pdf-sidebar');
      if (!sb) return;
      sb.style.display = sb.style.display === 'none' ? 'flex' : 'none';
    }

    // ─── Search ───────────────────────────────────────────────────────────────
    searchOpen() {
      const bar = $('wa-pdf-search-bar');
      if (!bar) return;
      bar.style.display = 'flex';
      const inp = $('wa-pdf-search-input');
      if (inp) { inp.value = this._searchQuery; inp.focus(); inp.select(); }
    }

    searchClose() {
      const bar = $('wa-pdf-search-bar');
      if (bar) bar.style.display = 'none';
      this._clearSearchHighlights();
      this._searchQuery = '';
      this._searchPgs = [];
      this._searchIdx = -1;
      const cnt = $('wa-pdf-search-count');
      if (cnt) cnt.textContent = '';
    }

    async searchInput(query) {
      this._searchQuery = query;
      this._searchPgs = [];
      this._searchIdx = -1;
      this._clearSearchHighlights();

      if (!query || query.length < 1) {
        const cnt = $('wa-pdf-search-count');
        if (cnt) cnt.textContent = '';
        return;
      }

      // Search all pages that have text content
      const pdf = this._pdfDoc;
      if (!pdf) return;

      const lq = query.toLowerCase();
      let totalMatches = 0;

      for (let pg = 1; pg <= pdf.numPages; pg++) {
        // Ensure we have text for this page
        if (!this._textContent[pg]) {
          try {
            const page = await pdf.getPage(pg);
            const tc = await page.getTextContent();
            this._textContent[pg] = tc.items.map(it => it.str).join(' ');
          } catch (_) { continue; }
        }

        const text = this._textContent[pg] || '';
        let idx = 0;
        let count = 0;
        while ((idx = text.toLowerCase().indexOf(lq, idx)) !== -1) {
          this._searchPgs.push({ page: pg, charIdx: idx, charLen: lq.length });
          idx++;
          count++;
          totalMatches++;
        }
      }

      const cnt = $('wa-pdf-search-count');
      if (cnt) cnt.textContent = totalMatches > 0 ? `${totalMatches} 处` : '未找到';

      if (totalMatches > 0) {
        this._searchIdx = 0;
        this._renderAllSearchHighlights();
        this._scrollToMatch(this._searchIdx);
      }
    }

    searchKeydown(e) {
      if (e.key === 'Enter') {
        e.preventDefault();
        if (e.shiftKey) this.searchPrev();
        else this.searchNext();
      } else if (e.key === 'Escape') {
        this.searchClose();
      }
    }

    searchNext() {
      if (this._searchPgs.length === 0) return;
      this._searchIdx = (this._searchIdx + 1) % this._searchPgs.length;
      this._updateSearchCounter();
      this._scrollToMatch(this._searchIdx);
      this._renderAllSearchHighlights();
    }

    searchPrev() {
      if (this._searchPgs.length === 0) return;
      this._searchIdx = (this._searchIdx - 1 + this._searchPgs.length) % this._searchPgs.length;
      this._updateSearchCounter();
      this._scrollToMatch(this._searchIdx);
      this._renderAllSearchHighlights();
    }

    _updateSearchCounter() {
      const cnt = $('wa-pdf-search-count');
      if (cnt) cnt.textContent = `${this._searchIdx + 1} / ${this._searchPgs.length}`;
    }

    _scrollToMatch(idx) {
      if (idx < 0 || idx >= this._searchPgs.length) return;
      const match = this._searchPgs[idx];
      this._scrollToPage(match.page);
    }

    _renderAllSearchHighlights() {
      const c = $(this.containerId);
      if (!c) return;
      // Clear current highlights
      c.querySelectorAll('.wa-pdf-search-hl').forEach(el => el.remove());
      // Can only do text-position-based highlighting if text layer is active
      // We use a character-position based approach: find all <span> elements
      // in the text layer that contain the query string characters
      this._searchPgs.forEach((match, i) => {
        this._renderSearchOnPage(match.page, match.charIdx, match.charLen, i === this._searchIdx);
      });
    }

    _renderSearchOnPage(pageNum, charIdx, charLen, isCurrent) {
      const wrap = document.getElementById(`pdf-page-${pageNum}`);
      if (!wrap) return;
      const textLayer = wrap.querySelector('.wa-pdf-text-layer');
      if (!textLayer) return;

      // Use range-based highlight: walk text layer spans
      const spans = Array.from(textLayer.querySelectorAll('span'));
      if (!spans.length) return;

      // Build running char offset → span mapping
      let running = 0, startSpan = null, startOff = 0, endSpan = null, endOff = 0;
      for (let i = 0; i < spans.length; i++) {
        const len = spans[i].textContent.length;
        if (startSpan === null && running + len > charIdx) {
          startSpan = spans[i];
          startOff = charIdx - running;
        }
        if (endSpan === null && running + len >= charIdx + charLen) {
          endSpan = spans[i];
          endOff = (charIdx + charLen) - running;
          break;
        }
        running += len;
      }
      if (!startSpan || !endSpan) return;

      try {
        const range = document.createRange();
        range.setStart(startSpan.firstChild || startSpan, Math.min(startOff, (startSpan.firstChild || startSpan).length));
        range.setEnd(endSpan.firstChild || endSpan, Math.min(endOff, (endSpan.firstChild || endSpan).length));
        const rects = Array.from(range.getClientRects());
        const wrapRect = wrap.getBoundingClientRect();

        const svg = wrap.querySelector('.wa-pdf-annot-layer');
        if (!svg) return;

        rects.forEach(r => {
          const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
          rect.setAttribute('x',      r.left - wrapRect.left);
          rect.setAttribute('y',      r.top  - wrapRect.top);
          rect.setAttribute('width',  r.width);
          rect.setAttribute('height', r.height);
          rect.classList.add('wa-pdf-search-hl');
          if (isCurrent) rect.classList.add('current');
          svg.appendChild(rect);
        });
      } catch (_) {}
    }

    _clearSearchHighlights() {
      const c = $(this.containerId);
      if (c) c.querySelectorAll('.wa-pdf-search-hl').forEach(el => el.remove());
    }

    // ─── Annotation toolbar open/close ───────────────────────────────────────
    annotOpen() {
      const bar = $('wa-pdf-annot-bar');
      if (bar) bar.style.display = 'flex';
      // Show annotation buttons in floating toolbar when PDF is open
      const h = $('wa-tooltip-highlight');
      const u = $('wa-tooltip-underline');
      const sep = $('wa-tooltip-annot-sep');
      if (h) h.style.display = '';
      if (u) u.style.display = '';
      if (sep) sep.style.display = '';
    }

    annotClose() {
      const bar = $('wa-pdf-annot-bar');
      if (bar) bar.style.display = 'none';
      this._annotMode = null;
      document.querySelectorAll('.wa-pdf-abt').forEach(b => b.classList.remove('active'));
      // Restore default cursor
      const c = $(this.containerId);
      if (c) c.style.cursor = '';
    }

    setAnnotMode(mode) {
      if (this._annotMode === mode) {
        // Toggle off
        this._annotMode = null;
        document.querySelectorAll('.wa-pdf-abt').forEach(b => b.classList.remove('active'));
        const c = $(this.containerId);
        if (c) c.style.cursor = '';
        return;
      }
      this._annotMode = mode;
      document.querySelectorAll('.wa-pdf-abt').forEach(b => b.classList.remove('active'));
      const activeBtn = document.getElementById(`wa-pdf-abt-${mode}`);
      if (activeBtn) activeBtn.classList.add('active');
      const c = $(this.containerId);
      if (c) {
        const shapeModes = ['draw', 'rect', 'ellipse', 'line', 'arrow'];
        c.style.cursor = shapeModes.includes(mode) ? 'crosshair' :
          mode === 'eraser' ? 'cell' :
          mode === 'textbox' ? 'text' :
          mode === 'note' ? 'cell' : 'text';
      }
    }

    setAnnotColor(hex) {
      this._annotColor = hex;
      const circle = document.getElementById('wa-pdf-annot-color-circle');
      if (circle) circle.setAttribute('fill', hex);
    }

    // ─── Text annotation (highlight / underline / strikethrough) ─────────────
    _onMouseUp(e) {
      const mode = this._annotMode;
      if (mode === 'highlight' || mode === 'underline' || mode === 'strikethrough') {
        const sel = window.getSelection();
        if (sel && sel.toString().trim().length > 0) {
          this._createTextAnnotation(mode);
          return;
        }
      }

      // Default: selection toolbar (AI actions)
      const sel = window.getSelection();
      const txt = sel ? sel.toString().trim() : '';
      if (txt) {
        _positionSelectionToolbar();
      }
    }

    _onMouseDown(e) {
      const wrap = e.target.closest('.wa-pdf-page-wrap');
      if (this._annotMode === 'draw') {
        if (wrap) {
          const pageNum = parseInt(wrap.dataset.page, 10);
          const svg = wrap.querySelector('.wa-pdf-annot-layer');
          if (svg) this._startDraw(e, svg, pageNum);
        }
      } else if (['rect', 'ellipse', 'line', 'arrow'].includes(this._annotMode)) {
        if (wrap) {
          const pageNum = parseInt(wrap.dataset.page, 10);
          const svg = wrap.querySelector('.wa-pdf-annot-layer');
          if (svg) this._startShape(e, svg, pageNum);
        }
      } else if (this._annotMode === 'textbox') {
        if (wrap) {
          const pageNum = parseInt(wrap.dataset.page, 10);
          this._startTextbox(e, wrap, pageNum);
        }
      } else if (this._annotMode === 'eraser') {
        if (wrap) this._handleEraser(e, wrap);
      }
    }

    _onMouseMove(e) {
      if (this._shapePreview && this._shapeStart && ['rect', 'ellipse', 'line', 'arrow'].includes(this._annotMode)) {
        this._moveShape(e);
      } else if (this._drawPath && this._annotMode === 'draw') {
        const wrap = this._drawingWrap;
        if (!wrap) return;
        const rect = wrap.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;
        this._drawPoints.push({ x, y });
        const d = this._drawPoints.map((p, i) => (i === 0 ? `M${p.x},${p.y}` : `L${p.x},${p.y}`)).join(' ');
        this._drawPath.setAttribute('d', d);
      }
    }

    _createTextAnnotation(type) {
      const sel = window.getSelection();
      if (!sel || sel.rangeCount === 0) return;
      const range = sel.getRangeAt(0);
      if (range.collapsed) return;

      // Find which page this selection is in
      const wrap = range.startContainer.parentElement &&
                   range.startContainer.parentElement.closest('.wa-pdf-page-wrap');
      if (!wrap) return;
      const pageNum = parseInt(wrap.dataset.page, 10);
      if (!pageNum) return;

      const rects = Array.from(range.getClientRects());
      const wrapRect = wrap.getBoundingClientRect();
      const pageRects = rects.map(r => ({
        x: r.left - wrapRect.left,
        y: r.top  - wrapRect.top,
        w: r.width,
        h: r.height,
      }));

      const annot = {
        id:    Date.now() + '-' + Math.random().toString(36).slice(2),
        type,
        page:  pageNum,
        rects: pageRects,
        color: this._annotColor,
        text:  sel.toString().trim(),
        timestamp: Date.now(),
      };
      this._annotations.push(annot);
      this._renderAnnotationsOnPage(pageNum);
      sel.removeAllRanges();
    }

    // ─── Note / sticky annotation ─────────────────────────────────────────────
    _placeNote(e, wrap, pageNum) {
      e.preventDefault();
      const rect = wrap.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;

      const annot = {
        id:    Date.now() + '-' + Math.random().toString(36).slice(2),
        type:  'note',
        page:  pageNum,
        x, y,
        text:  '',
        color: this._annotColor,
        timestamp: Date.now(),
      };
      this._annotations.push(annot);
      this._renderAnnotationsOnPage(pageNum);
      // Open the note popup immediately
      const popup = wrap.querySelector(`.wa-pdf-note-popup[data-id="${annot.id}"]`);
      if (popup) popup.querySelector('textarea').focus();
    }

    // ─── Freehand drawing ─────────────────────────────────────────────────────
    _startDraw(e, svg, pageNum) {
      e.preventDefault();
      const rect = svg.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;

      const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      path.classList.add('wa-annot-draw');
      path.setAttribute('stroke', this._annotColor);
      path.setAttribute('stroke-width', String(this._annotLineWidth));
      path.setAttribute('stroke-linecap', 'round');
      path.setAttribute('stroke-linejoin', 'round');
      path.setAttribute('d', `M${x},${y}`);
      svg.appendChild(path);

      this._drawPath   = path;
      this._drawPoints = [{ x, y }];
      this._drawingWrap = svg.closest('.wa-pdf-page-wrap');
      this._drawPageNum = pageNum;

      const endDraw = () => {
        if (!this._drawPath) return;
        if (this._drawPoints.length > 1) {
          const annot = {
            id:        Date.now() + '-' + Math.random().toString(36).slice(2),
            type:      'draw',
            page:      this._drawPageNum,
            points:    this._drawPoints,
            color:     this._annotColor,
            lineWidth: this._annotLineWidth,
            timestamp: Date.now(),
          };
          this._annotations.push(annot);
        } else {
          // Single click — discard
          this._drawPath.remove();
        }
        this._drawPath   = null;
        this._drawPoints = [];
        this._drawingWrap = null;
        document.removeEventListener('mouseup', endDraw);
      };
      document.addEventListener('mouseup', endDraw, { once: true });
    }

    // ─── Shape drawing (rect / ellipse / line / arrow) ─────────────────────────────
    _startShape(e, svg, pageNum) {
      e.preventDefault();
      const svgRect = svg.getBoundingClientRect();
      const x = e.clientX - svgRect.left;
      const y = e.clientY - svgRect.top;
      this._shapeStart   = { x, y };
      this._shapeSvg     = svg;
      this._shapePageNum = pageNum;
      const mode = this._annotMode;
      const ns = 'http://www.w3.org/2000/svg';
      let el;
      if (mode === 'rect') {
        el = document.createElementNS(ns, 'rect');
        el.setAttribute('fill', 'none');
        el.setAttribute('x', x); el.setAttribute('y', y);
        el.setAttribute('width', '1'); el.setAttribute('height', '1');
      } else if (mode === 'ellipse') {
        el = document.createElementNS(ns, 'ellipse');
        el.setAttribute('fill', 'none');
        el.setAttribute('cx', x); el.setAttribute('cy', y);
        el.setAttribute('rx', '1'); el.setAttribute('ry', '1');
      } else if (mode === 'line' || mode === 'arrow') {
        el = document.createElementNS(ns, 'line');
        el.setAttribute('x1', x); el.setAttribute('y1', y);
        el.setAttribute('x2', x); el.setAttribute('y2', y);
      }
      if (el) {
        el.setAttribute('stroke', this._annotColor);
        el.setAttribute('stroke-width', this._annotLineWidth);
        el.classList.add('wa-annot-preview');
        svg.appendChild(el);
        this._shapePreview = el;
      }
      document.addEventListener('mouseup', () => this._finishShape(), { once: true });
    }

    _moveShape(e) {
      if (!this._shapePreview || !this._shapeStart || !this._shapeSvg) return;
      const svgRect = this._shapeSvg.getBoundingClientRect();
      const x2 = e.clientX - svgRect.left;
      const y2 = e.clientY - svgRect.top;
      const { x: x1, y: y1 } = this._shapeStart;
      const mode = this._annotMode;
      if (mode === 'rect') {
        this._shapePreview.setAttribute('x', Math.min(x1, x2));
        this._shapePreview.setAttribute('y', Math.min(y1, y2));
        this._shapePreview.setAttribute('width',  Math.abs(x2 - x1));
        this._shapePreview.setAttribute('height', Math.abs(y2 - y1));
      } else if (mode === 'ellipse') {
        this._shapePreview.setAttribute('cx', (x1 + x2) / 2);
        this._shapePreview.setAttribute('cy', (y1 + y2) / 2);
        this._shapePreview.setAttribute('rx', Math.abs(x2 - x1) / 2);
        this._shapePreview.setAttribute('ry', Math.abs(y2 - y1) / 2);
      } else if (mode === 'line' || mode === 'arrow') {
        this._shapePreview.setAttribute('x2', x2);
        this._shapePreview.setAttribute('y2', y2);
      }
    }

    _finishShape() {
      if (!this._shapePreview || !this._shapeStart) return;
      const mode = this._annotMode;
      let annot = null;
      if (mode === 'rect') {
        const x = parseFloat(this._shapePreview.getAttribute('x'));
        const y = parseFloat(this._shapePreview.getAttribute('y'));
        const w = parseFloat(this._shapePreview.getAttribute('width'));
        const h = parseFloat(this._shapePreview.getAttribute('height'));
        if (w >= 5 && h >= 5) annot = { type: 'rect', x, y, w, h };
      } else if (mode === 'ellipse') {
        const cx = parseFloat(this._shapePreview.getAttribute('cx'));
        const cy = parseFloat(this._shapePreview.getAttribute('cy'));
        const rx = parseFloat(this._shapePreview.getAttribute('rx'));
        const ry = parseFloat(this._shapePreview.getAttribute('ry'));
        if (rx >= 3 && ry >= 3) annot = { type: 'ellipse', cx, cy, rx, ry };
      } else if (mode === 'line' || mode === 'arrow') {
        const x1 = parseFloat(this._shapePreview.getAttribute('x1'));
        const y1 = parseFloat(this._shapePreview.getAttribute('y1'));
        const x2 = parseFloat(this._shapePreview.getAttribute('x2'));
        const y2 = parseFloat(this._shapePreview.getAttribute('y2'));
        const len = Math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2);
        if (len >= 5) annot = { type: mode, x1, y1, x2, y2 };
      }
      this._shapePreview.remove();
      this._shapePreview = null;
      this._shapeStart   = null;
      if (annot) {
        const full = {
          ...annot,
          id:        Date.now() + '-' + Math.random().toString(36).slice(2),
          page:      this._shapePageNum,
          color:     this._annotColor,
          lineWidth: this._annotLineWidth,
          timestamp: Date.now(),
        };
        this._annotations.push(full);
        this._renderAnnotationsOnPage(full.page);
      }
    }

    // ─── Eraser ──────────────────────────────────────────────────────────────
    _handleEraser(e, wrap) {
      const pageNum = parseInt(wrap.dataset.page, 10);
      const wrapRect = wrap.getBoundingClientRect();
      const ex = e.clientX - wrapRect.left;
      const ey = e.clientY - wrapRect.top;
      const HIT = 14;
      const hit = this._annotations.find(a => {
        if (a.page !== pageNum) return false;
        if (a.type === 'rect')    return ex >= a.x - HIT && ex <= a.x + a.w + HIT && ey >= a.y - HIT && ey <= a.y + a.h + HIT;
        if (a.type === 'ellipse') return Math.abs(ex - a.cx) <= a.rx + HIT && Math.abs(ey - a.cy) <= a.ry + HIT;
        if (a.type === 'line' || a.type === 'arrow') {
          const dx = a.x2 - a.x1, dy = a.y2 - a.y1, len2 = dx * dx + dy * dy;
          const t = len2 === 0 ? 0 : Math.max(0, Math.min(1, ((ex - a.x1) * dx + (ey - a.y1) * dy) / len2));
          return Math.sqrt((ex - (a.x1 + t * dx)) ** 2 + (ey - (a.y1 + t * dy)) ** 2) <= HIT;
        }
        if (a.type === 'note')    return Math.sqrt((ex - a.x) ** 2 + (ey - a.y) ** 2) <= HIT + 10;
        if (a.type === 'textbox') return ex >= a.x - HIT && ex <= a.x + a.w + HIT && ey >= a.y - HIT && ey <= a.y + a.h + HIT;
        if (a.type === 'draw')    return a.points && a.points.some(p => Math.sqrt((ex - p.x) ** 2 + (ey - p.y) ** 2) <= HIT);
        if (a.rects)              return a.rects.some(r => ex >= r.x - 2 && ex <= r.x + r.w + 2 && ey >= r.y - 2 && ey <= r.y + r.h + 2);
        return false;
      });
      if (hit) {
        this._deleteAnnotation(hit.id);
        showToast('批注已删除', 'info');
      }
    }

    // ─── Text-box annotation ──────────────────────────────────────────────────
    _startTextbox(e, wrap, pageNum) {
      e.preventDefault();
      const wrapRect = wrap.getBoundingClientRect();
      const x = e.clientX - wrapRect.left;
      const y = e.clientY - wrapRect.top;
      const box = document.createElement('div');
      box.contentEditable = 'true';
      box.className = 'wa-pdf-textbox-edit';
      box.style.cssText = `position:absolute;left:${x}px;top:${y}px;min-width:80px;min-height:22px;
        border:1.5px dashed ${this._annotColor};color:${this._annotColor};font-size:14px;
        background:rgba(255,255,255,.06);outline:none;padding:2px 4px;cursor:text;z-index:100;`;
      wrap.appendChild(box);
      box.focus();
      const commit = () => {
        const text = box.innerText.trim();
        box.remove();
        if (!text) return;
        const annot = {
          id:        Date.now() + '-' + Math.random().toString(36).slice(2),
          type:      'textbox',
          page:      pageNum,
          x, y,
          w:         Math.max(80, box.offsetWidth),
          h:         Math.max(22, box.offsetHeight),
          text,
          fontSize:  14,
          color:     this._annotColor,
          timestamp: Date.now(),
        };
        this._annotations.push(annot);
        this._renderAnnotationsOnPage(pageNum);
      };
      box.addEventListener('blur', commit);
      box.addEventListener('keydown', ke => {
        if (ke.key === 'Escape') { ke.preventDefault(); box.remove(); }
        else if (ke.key === 'Enter' && !ke.shiftKey) { ke.preventDefault(); commit(); }
      });
    }

    // ─── Render annotations on a page ────────────────────────────────────────
    _renderAnnotationsOnPage(pageNum) {
      const wrap = document.getElementById(`pdf-page-${pageNum}`);
      if (!wrap) return;
      const svg = wrap.querySelector('.wa-pdf-annot-layer');
      if (!svg) return;

      // Clear existing annotation elements (keep search highlights)
      svg.querySelectorAll('.wa-annot-hi, .wa-annot-ul, .wa-annot-st, .wa-annot-draw-saved, .wa-annot-shape, .wa-pdf-note-icon').forEach(el => el.remove());
      wrap.querySelectorAll('.wa-pdf-note-popup').forEach(el => el.remove());

      const pageAnnots = this._annotations.filter(a => a.page === pageNum);
      pageAnnots.forEach(annot => {
        if (annot.type === 'highlight' || annot.type === 'underline' || annot.type === 'strikethrough') {
          annot.rects.forEach(r => {
            if (annot.type === 'highlight') {
              const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
              rect.setAttribute('x', r.x); rect.setAttribute('y', r.y);
              rect.setAttribute('width', r.w); rect.setAttribute('height', r.h);
              rect.setAttribute('fill', annot.color);
              rect.classList.add('wa-annot-hi');
              rect.dataset.annotId = annot.id;
              rect.addEventListener('contextmenu', (e) => { e.preventDefault(); this._showAnnotMenu(annot, e); });
              svg.appendChild(rect);
            } else if (annot.type === 'underline') {
              const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
              line.setAttribute('x1', r.x);      line.setAttribute('y1', r.y + r.h);
              line.setAttribute('x2', r.x + r.w); line.setAttribute('y2', r.y + r.h);
              line.setAttribute('stroke', annot.color); line.setAttribute('stroke-width', '1.5');
              line.classList.add('wa-annot-ul');
              line.dataset.annotId = annot.id;
              line.addEventListener('contextmenu', (e) => { e.preventDefault(); this._showAnnotMenu(annot, e); });
              svg.appendChild(line);
            } else if (annot.type === 'strikethrough') {
              const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
              const midY = r.y + r.h * 0.5;
              line.setAttribute('x1', r.x);      line.setAttribute('y1', midY);
              line.setAttribute('x2', r.x + r.w); line.setAttribute('y2', midY);
              line.setAttribute('stroke', annot.color); line.setAttribute('stroke-width', '1.5');
              line.classList.add('wa-annot-st');
              line.dataset.annotId = annot.id;
              line.addEventListener('contextmenu', (e) => { e.preventDefault(); this._showAnnotMenu(annot, e); });
              svg.appendChild(line);
            }
          });
        } else if (annot.type === 'draw') {
          const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
          const d = annot.points.map((p, i) => (i === 0 ? `M${p.x},${p.y}` : `L${p.x},${p.y}`)).join(' ');
          path.setAttribute('d', d);
          path.setAttribute('stroke', annot.color);
          path.setAttribute('stroke-width', String(annot.lineWidth || 2));
          path.setAttribute('stroke-linecap', 'round');
          path.setAttribute('stroke-linejoin', 'round');
          path.setAttribute('fill', 'none');
          path.classList.add('wa-annot-draw', 'wa-annot-draw-saved');
          path.dataset.annotId = annot.id;
          path.addEventListener('contextmenu', (e) => { e.preventDefault(); this._showAnnotMenu(annot, e); });
          svg.appendChild(path);
        } else if (annot.type === 'rect') {
          const el = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
          el.setAttribute('x', annot.x); el.setAttribute('y', annot.y);
          el.setAttribute('width', annot.w); el.setAttribute('height', annot.h);
          el.setAttribute('fill', 'none'); el.setAttribute('stroke', annot.color);
          el.setAttribute('stroke-width', annot.lineWidth || 2);
          el.classList.add('wa-annot-shape'); el.dataset.annotId = annot.id;
          el.addEventListener('contextmenu', (e) => { e.preventDefault(); this._showAnnotMenu(annot, e); });
          svg.appendChild(el);
        } else if (annot.type === 'ellipse') {
          const el = document.createElementNS('http://www.w3.org/2000/svg', 'ellipse');
          el.setAttribute('cx', annot.cx); el.setAttribute('cy', annot.cy);
          el.setAttribute('rx', annot.rx); el.setAttribute('ry', annot.ry);
          el.setAttribute('fill', 'none'); el.setAttribute('stroke', annot.color);
          el.setAttribute('stroke-width', annot.lineWidth || 2);
          el.classList.add('wa-annot-shape'); el.dataset.annotId = annot.id;
          el.addEventListener('contextmenu', (e) => { e.preventDefault(); this._showAnnotMenu(annot, e); });
          svg.appendChild(el);
        } else if (annot.type === 'line') {
          const el = document.createElementNS('http://www.w3.org/2000/svg', 'line');
          el.setAttribute('x1', annot.x1); el.setAttribute('y1', annot.y1);
          el.setAttribute('x2', annot.x2); el.setAttribute('y2', annot.y2);
          el.setAttribute('stroke', annot.color); el.setAttribute('stroke-width', annot.lineWidth || 2);
          el.classList.add('wa-annot-shape'); el.dataset.annotId = annot.id;
          el.addEventListener('contextmenu', (e) => { e.preventDefault(); this._showAnnotMenu(annot, e); });
          svg.appendChild(el);
        } else if (annot.type === 'arrow') {
          const ns = 'http://www.w3.org/2000/svg';
          const markerId = 'arrow-' + annot.id;
          let defs = svg.querySelector('defs');
          if (!defs) { defs = document.createElementNS(ns, 'defs'); svg.prepend(defs); }
          const marker = document.createElementNS(ns, 'marker');
          marker.setAttribute('id', markerId); marker.setAttribute('markerWidth', '10');
          marker.setAttribute('markerHeight', '7'); marker.setAttribute('refX', '9');
          marker.setAttribute('refY', '3.5'); marker.setAttribute('orient', 'auto');
          const poly = document.createElementNS(ns, 'polygon');
          poly.setAttribute('points', '0 0, 10 3.5, 0 7'); poly.setAttribute('fill', annot.color);
          marker.appendChild(poly); defs.appendChild(marker);
          const el = document.createElementNS(ns, 'line');
          el.setAttribute('x1', annot.x1); el.setAttribute('y1', annot.y1);
          el.setAttribute('x2', annot.x2); el.setAttribute('y2', annot.y2);
          el.setAttribute('stroke', annot.color); el.setAttribute('stroke-width', annot.lineWidth || 2);
          el.setAttribute('marker-end', `url(#${markerId})`);
          el.classList.add('wa-annot-shape'); el.dataset.annotId = annot.id;
          el.addEventListener('contextmenu', (e) => { e.preventDefault(); this._showAnnotMenu(annot, e); });
          svg.appendChild(el);
        } else if (annot.type === 'textbox') {
          const ns = 'http://www.w3.org/2000/svg';
          const fo = document.createElementNS(ns, 'foreignObject');
          fo.setAttribute('x', annot.x); fo.setAttribute('y', annot.y);
          fo.setAttribute('width',  annot.w || 120); fo.setAttribute('height', annot.h || 30);
          fo.classList.add('wa-annot-shape'); fo.dataset.annotId = annot.id;
          fo.addEventListener('contextmenu', (e) => { e.preventDefault(); this._showAnnotMenu(annot, e); });
          const div = document.createElement('div');
          div.style.cssText = `font-size:${annot.fontSize || 14}px;color:${annot.color};width:100%;height:100%;overflow:hidden;word-break:break-word;white-space:pre-wrap;`;
          div.textContent = annot.text; fo.appendChild(div); svg.appendChild(fo);
        } else if (annot.type === 'note') {
          // Note icon
          const icon = document.createElement('div');
          icon.className = 'wa-pdf-note-icon';
          icon.style.left = (annot.x - 11) + 'px';
          icon.style.top  = (annot.y - 22) + 'px';
          icon.title = annot.text || '便笺';
          icon.dataset.annotId = annot.id;
          icon.addEventListener('click', (e) => { e.stopPropagation(); this._toggleNotePopup(annot, wrap); });
          wrap.appendChild(icon);

          if (annot._open) this._showNotePopup(annot, wrap, icon);
        }
      });
    }

    _showAnnotMenu(annot, e) {
      // Simple context: delete annotation
      const existing = document.getElementById('wa-pdf-annot-ctx');
      if (existing) existing.remove();

      const menu = document.createElement('div');
      menu.id = 'wa-pdf-annot-ctx';
      menu.style.cssText = `position:fixed;left:${e.clientX}px;top:${e.clientY}px;
        background:var(--surface);border:1px solid var(--border);border-radius:6px;
        padding:4px 0;z-index:99999;box-shadow:0 4px 12px rgba(0,0,0,.25);min-width:130px;`;
      menu.innerHTML = `
        <div style="padding:6px 14px;cursor:pointer;font-size:12.5px;color:var(--text-muted)" id="wa-annt-explain">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right:6px;vertical-align:middle"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>AI 解释
        </div>
        <div style="padding:6px 14px;cursor:pointer;font-size:12.5px;color:#ff7070" id="wa-annt-del">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right:6px;vertical-align:middle"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/></svg>删除批注
        </div>`;

      document.body.appendChild(menu);

      menu.querySelector('#wa-annt-explain').addEventListener('click', () => {
        menu.remove();
        if (annot.text) WA.sendCustomMessage(`请解释以下内容：\n\n"${annot.text}"`);
      });
      menu.querySelector('#wa-annt-del').addEventListener('click', () => {
        menu.remove();
        this._deleteAnnotation(annot.id);
      });

      const closeMenu = (ev) => { if (!menu.contains(ev.target)) { menu.remove(); document.removeEventListener('mousedown', closeMenu); } };
      document.addEventListener('mousedown', closeMenu);
    }

    _deleteAnnotation(id) {
      const annot = this._annotations.find(a => a.id === id);
      if (!annot) return;
      const page = annot.page;
      this._annotations = this._annotations.filter(a => a.id !== id);
      this._renderAnnotationsOnPage(page);
    }

    _toggleNotePopup(annot, wrap) {
      const existing = wrap.querySelector(`.wa-pdf-note-popup[data-id="${annot.id}"]`);
      if (existing) { existing.remove(); annot._open = false; }
      else { annot._open = true; const icon = wrap.querySelector(`.wa-pdf-note-icon[data-annotId="${annot.id}"]`); this._showNotePopup(annot, wrap, icon); }
    }

    _showNotePopup(annot, wrap, icon) {
      const popup = document.createElement('div');
      popup.className = 'wa-pdf-note-popup';
      popup.dataset.id = annot.id;
      const ix = icon ? (parseFloat(icon.style.left) + 11) : annot.x;
      const iy = icon ? (parseFloat(icon.style.top)  + 22) : annot.y;
      popup.style.left = (ix + 8) + 'px';
      popup.style.top  = (iy - 20) + 'px';

      popup.innerHTML = `
        <div class="wa-pdf-note-header" onmousedown="WA._pdfDragNote(event, this.parentElement)">
          <span>便笺</span>
          <button class="wa-pdf-note-close" onmousedown="event.stopPropagation()">✕</button>
        </div>
        <textarea class="wa-pdf-note-body" placeholder="在此输入备注…">${annot.text || ''}</textarea>
        <div class="wa-pdf-note-footer">
          <button class="wa-pdf-note-save">保存</button>
        </div>`;

      popup.querySelector('.wa-pdf-note-close').addEventListener('click', () => {
        popup.remove(); annot._open = false;
      });
      popup.querySelector('.wa-pdf-note-save').addEventListener('click', () => {
        annot.text = popup.querySelector('textarea').value;
        popup.remove(); annot._open = false;
        if (icon) icon.title = annot.text || '便笺';
      });

      wrap.appendChild(popup);
    }

    // ─── Annotate selection from floating toolbar ─────────────────────────────
    annotateSelection(type) {
      if (!this._annotMode) {
        // Temporarily set mode for this one action
        const prevMode = this._annotMode;
        this._annotMode = type;
        this._createTextAnnotation(type);
        this._annotMode = prevMode;
      } else {
        this._createTextAnnotation(type);
      }
      $('wa-pdf-tooltip').style.display = 'none';
    }

    // ─── Save/load annotations via backend ───────────────────────────────────
    async saveAnnotations() {
      if (!state.fileId) return;
      try {
        showToast('正在保存批注到 PDF…', 'info');
        const res = await fetch('/api/v1/workspace/pdf/save_annotations', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ file_id: state.fileId, annotations: this._annotations }),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const blob = await res.blob();
        // Trigger download of the annotated PDF
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = state.fileName || 'annotated.pdf';
        a.click();
        URL.revokeObjectURL(url);
        showToast('批注已嵌入 PDF 并下载', 'success');
      } catch (e) {
        showToast('保存批注失败: ' + e.message, 'error');
      }
    }

    async _loadAnnotationsFromServer() {
      if (!state.fileId) return;
      try {
        const res = await fetch('/api/v1/workspace/pdf/load_annotations/' + state.fileId);
        if (!res.ok) return;
        const json = await res.json();
        if (json.annotations && json.annotations.length > 0) {
          this._annotations = json.annotations;
          // Re-render all loaded pages
          this._renderedPgs.forEach(pg => this._renderAnnotationsOnPage(pg));
        }
      } catch (_) {}
    }

    // ─── AI auto-annotation ───────────────────────────────────────────────────
    async aiAnnotate() {
      const disabledMsg = 'AI 标注功能正在迁移到新的 AI 流程，暂时不可用。请先使用高亮、下划线或删除线手动批注。';
      showToast(disabledMsg, 'warning', 5000);

      const msgs = $('wa-ai-messages');
      if (msgs && !msgs.querySelector('[data-wa-notice="pdf-ai-annotate-disabled"]')) {
        const noteEl = document.createElement('div');
        noteEl.className = 'wa-msg system';
        noteEl.dataset.waNotice = 'pdf-ai-annotate-disabled';
        noteEl.textContent = disabledMsg;
        msgs.appendChild(noteEl);
        msgs.scrollTop = msgs.scrollHeight;
      }

      _expandWAPanel();
    }

    // ─── AI Watermark removal ─────────────────────────────────────────────────
    async pdfRemoveWatermark() {
      if (!state.fileId) { showToast('请先打开一个 PDF 文件', 'warning'); return; }
      const overlay  = document.getElementById('wa-pdf-watermark-overlay');
      const statusEl = document.getElementById('wa-pwm-status');
      const barEl    = document.getElementById('wa-pwm-bar');
      const dlLink   = document.getElementById('wa-pwm-download');
      const resultEl = document.getElementById('wa-pwm-result');
      if (overlay)  { overlay.style.display = 'flex'; overlay.classList.add('open'); }
      if (statusEl) statusEl.textContent = '正在分析 PDF 水印…';
      if (barEl)    barEl.style.width = '20%';
      if (dlLink)   dlLink.style.display = 'none';
      if (resultEl) resultEl.textContent = '';
      try {
        const res = await fetch('/api/v1/workspace/pdf/remove_watermark', {
          method:  'POST',
          headers: { 'Content-Type': 'application/json' },
          body:    JSON.stringify({ file_id: state.fileId, use_ai: true }),
        });
        if (barEl) barEl.style.width = '80%';
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          throw new Error(err.error || `HTTP ${res.status}`);
        }
        const blob = await res.blob();
        if (barEl) barEl.style.width = '100%';
        const url  = URL.createObjectURL(blob);
        const name = (state.fileName || 'watermark_removed.pdf').replace(/\.pdf$/i, '') + '_去水印.pdf';
        if (dlLink) { dlLink.href = url; dlLink.download = name; dlLink.style.display = ''; }
        const removed = res.headers.get('X-Koto-Removed-Count') || '?';
        const method  = res.headers.get('X-Koto-Method') || '';
        if (statusEl) statusEl.textContent = `去水印完成！共处理 ${removed} 处。`;
        if (resultEl) resultEl.textContent = method ? `检测方法：${method}` : '';
        showToast('AI 去水印完成', 'success');
      } catch (err) {
        if (statusEl) statusEl.textContent = '去水印失败：' + err.message;
        if (barEl)    barEl.style.width = '0%';
        showToast('去水印失败: ' + err.message, 'error');
      }
    }

    // ─── Existing interface ───────────────────────────────────────────────────
    handleMouseUp(e) {
      this._onMouseUp(e);
    }

    hideTooltip(e) {
      if (!e.target.closest('#wa-pdf-tooltip')) {
        $('wa-pdf-tooltip').style.display = 'none';
      }
    }

    getContent() {
      const sel = window.getSelection().toString().trim();
      if (sel) return `[选中的 PDF 文本]:\n${sel}\n`;
      // Collect text from rendered pages
      const texts = [];
      for (let pg = 1; pg <= Math.min(3, this._pageCount); pg++) {
        if (this._textContent[pg]) texts.push(`[第${pg}页]\n` + this._textContent[pg].slice(0, 2000));
      }
      return texts.length > 0 ? texts.join('\n\n') : '[PDF 正在加载，暂无文本]';
    }

    serialize() { return null; } // PDF not directly editable

    applyToolCall(cmd) {
      // For AI annotation commands
      if (cmd && cmd.type === 'annotate' && Array.isArray(cmd.annotations)) {
        cmd.annotations.forEach(a => this._annotations.push({
          ...a,
          id: Date.now() + '-' + Math.random().toString(36).slice(2),
          timestamp: Date.now(),
        }));
        this._renderedPgs.forEach(pg => this._renderAnnotationsOnPage(pg));
      }
    }

    destroy() {
      if (this._observer) { this._observer.disconnect(); this._observer = null; }
      document.removeEventListener('keydown', this._keyHandler);

      const c = $(this.containerId);
      if (c) {
        c.classList.remove('active');
        c.innerHTML = '';
        c.removeEventListener('mouseup', this._onMouseUp);
        c.removeEventListener('mousedown', this._onMouseDown);
        c.removeEventListener('mousemove', this._onMouseMove);
        c.removeEventListener('wheel', this._wheelHandler);
      }

      const outer = $('wa-pdf-editor');
      if (outer) outer.classList.remove('active');

      const strip = $('wa-pdf-thumbstrip');
      if (strip) strip.innerHTML = '';

      const searchBar = $('wa-pdf-search-bar');
      if (searchBar) searchBar.style.display = 'none';

      const annotBar = $('wa-pdf-annot-bar');
      if (annotBar) annotBar.style.display = 'none';

      // Hide annotation buttons in floating toolbar
      const h = $('wa-tooltip-highlight');
      const u = $('wa-tooltip-underline');
      const sep = $('wa-tooltip-annot-sep');
      if (h) h.style.display = 'none';
      if (u) u.style.display = 'none';
      if (sep) sep.style.display = 'none';
    }
  }

  // ── Image viewer ─────────────────────────────────────────────────────────
  class KotoImageViewer {
    constructor() {
      this.containerId = 'wa-image-viewer';
      this._scale = 1.0;
      $(this.containerId).classList.add('active');
      this._wheelHandler = (e) => {
        if (!e.ctrlKey && !e.metaKey) return;
        e.preventDefault();
        const delta = e.deltaY > 0 ? -0.1 : 0.1;
        this._scale = Math.max(0.1, Math.min(5.0, this._scale + delta));
        const img = $(this.containerId).querySelector('img');
        if (img) img.style.transform = `scale(${this._scale})`;
      };
      $(this.containerId).addEventListener('wheel', this._wheelHandler, { passive: false });
    }
    render(rawUrl) {
      const c = $(this.containerId);
      this._scale = 1.0;
      c.innerHTML = `<div class="wa-image-wrap"><img src="${rawUrl}" alt="image" draggable="false" /></div>`;
    }
    getContent() { return '[图片文件，无文本内容]'; }
    serialize() { return null; }
    applyToolCall() {}
    destroy() {
      $(this.containerId).classList.remove('active');
      $(this.containerId).innerHTML = '';
      $(this.containerId).removeEventListener('wheel', this._wheelHandler);
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
  const _libsLoaded = { tiptap: false, sheets: false, pdfjs: false };
  const _libLoadPromises = { tiptap: null, sheets: null, pdfjs: null };
  const _assetCacheBust = String(Date.now());

  // Ensure all IWorkbookData required fields are present before passing to Univer.
  // Univer silently fails to render when `appVersion` or `locale` is missing.
  function _ensureWorkbookDefaults(wb) {
    if (!wb || typeof wb !== 'object') return wb;
    return Object.assign({ appVersion: '0.5.0', locale: 'zh-CN', styles: {}, resources: [] }, wb);
  }

  function _injectCSS(href) {
    // Strip query string for dedup check (cache-buster params differ each load)
    const hrefBase = href.split('?')[0];
    if (document.querySelector(`link[href^="${hrefBase}"]`)) return;
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

  async function _ensureTipTap() {
    if (window.KotoDocxEditorLib || _libsLoaded.tiptap) return;
    if (_libLoadPromises.tiptap) return _libLoadPromises.tiptap;
    _libLoadPromises.tiptap = (async () => {
      await _loadScript('/static/js/tiptap-docx-bundle.js?v=' + _assetCacheBust);
      _libsLoaded.tiptap = true;
    })().finally(() => { _libLoadPromises.tiptap = null; });
    return _libLoadPromises.tiptap;
  }

  async function _ensureUniverSheets() {
    if (_libsLoaded.sheets) return;
    if (_libLoadPromises.sheets) return _libLoadPromises.sheets;
    _libLoadPromises.sheets = (async () => {
      // Cache-busting suffix so pywebview/WebView2 always loads the latest build.
      // Keep it stable for the page lifetime so concurrent opens reuse the same promise.
      _injectCSS('/static/univer-dist/assets/sheets-main.css?v=' + _assetCacheBust);
      // sheets-main.js is an IIFE bundle — loads synchronously, no type="module" needed.
      // It sets window.KotoSheetsAPI on execution.
      await _loadScript('/static/univer-dist/assets/sheets-main.js?v=' + _assetCacheBust, 60000);
      if (!window.KotoSheetsAPI) {
        throw new Error('Univer Sheets 加载失败 — window.KotoSheetsAPI 未定义');
      }
      console.log('[WA] KotoSheetsAPI 已就绪');
      _libsLoaded.sheets = true;
    })().finally(() => { _libLoadPromises.sheets = null; });
    return _libLoadPromises.sheets;
  }

  async function _ensurePdfJS() {
    if (window.pdfjsLib || _libsLoaded.pdfjs) return;
    if (_libLoadPromises.pdfjs) return _libLoadPromises.pdfjs;
    _libLoadPromises.pdfjs = (async () => {
      await _loadScript('https://cdn.jsdelivr.net/npm/pdfjs-dist@3.11.174/build/pdf.min.js');
      if (window.pdfjsLib) {
        window.pdfjsLib.GlobalWorkerOptions.workerSrc =
          'https://cdn.jsdelivr.net/npm/pdfjs-dist@3.11.174/build/pdf.worker.min.js';
      }
      _libsLoaded.pdfjs = true;
    })().finally(() => { _libLoadPromises.pdfjs = null; });
    return _libLoadPromises.pdfjs;
  }

  // ── Safe JSON helper — prevents SyntaxError when server returns HTML ────────
  /**
   * Parse the response body as JSON.  If the body is not valid JSON (e.g. the
   * server returned an HTML error page), throw a human-readable Error instead of
   * a raw SyntaxError so that catch handlers can surface a useful message.
   */
  async function _safeJson(res) {
    try {
      return await res.json();
    } catch (_) {
      throw new Error(`HTTP ${res.status}: 服务器返回非 JSON 响应（服务是否正在运行？）`);
    }
  }

  // ── Document Outline / Navigation Panel ─────────────────────────────────
  // Creates a Word-style heading navigation panel for DOCX documents.
  // Sits inside a horizontal wrapper alongside the editor content.
  function _setupDocOutline(headings) {
    const docxEditor = $('wa-docx-editor');
    const edContent  = $('wa-editor-content');
    if (!docxEditor || !edContent) return;

    // Remove previous outline if it exists
    const prevOutline = $('wa-doc-outline');
    if (prevOutline) prevOutline.remove();
    const prevRow = docxEditor.querySelector('.wa-docx-body-row');
    if (prevRow) {
      // Move editor-content back out before removing the row wrapper
      docxEditor.insertBefore(edContent, prevRow);
      prevRow.remove();
    }

    // Fall back to DOM extraction if backend didn't provide headings
    if (!headings || !headings.length) {
      headings = _extractHeadingsFromDOM();
    }

    // Create the outline panel
    const outline = document.createElement('div');
    outline.id = 'wa-doc-outline';
    outline.innerHTML = `
      <div class="wa-outline-header">
        <span>导航</span>
        <button class="wa-outline-close" title="关闭导航">✕</button>
      </div>
      <input class="wa-outline-search" type="text" placeholder="在文档中搜索…" />
      <div class="wa-outline-body"></div>`;

    // Create the horizontal body wrapper
    const bodyRow = document.createElement('div');
    bodyRow.className = 'wa-docx-body-row';
    bodyRow.style.cssText = 'flex:1;min-height:0;display:flex;flex-direction:row;';

    // Insert the wrapper where editor-content was
    docxEditor.insertBefore(bodyRow, edContent);
    bodyRow.appendChild(outline);
    bodyRow.appendChild(edContent);

    // Populate heading items
    const body = outline.querySelector('.wa-outline-body');
    _renderOutlineItems(body, headings);

    // Wire close button
    outline.querySelector('.wa-outline-close').addEventListener('click', () => {
      _toggleDocOutline(false);
    });

    // Wire search/filter
    const searchInput = outline.querySelector('.wa-outline-search');
    searchInput.addEventListener('input', () => {
      const q = searchInput.value.trim().toLowerCase();
      body.querySelectorAll('.wa-outline-item').forEach(el => {
        el.style.display = (!q || el.textContent.toLowerCase().includes(q)) ? '' : 'none';
      });
    });

    // Add toggle button to the page indicator bar (if not already there)
    _ensureOutlineToggleBtn();

    // Auto-show when headings are available so the user sees the navigation
    _toggleDocOutline(headings.length > 0);
  }

  function _extractHeadingsFromDOM() {
    const headings = [];
    const pm = document.querySelector('#wa-docx-editor .ProseMirror');
    if (!pm) return headings;

    // Primary: h1–h6 tags
    pm.querySelectorAll('h1, h2, h3, h4, h5, h6').forEach(el => {
      const level = parseInt(el.tagName[1], 10);
      const text = el.textContent.trim();
      const id = el.getAttribute('id') || '';
      if (text) headings.push({ level, text, id });
    });

    // Fallback: extract from TOC entries (koto-toc-N paragraphs with <a> anchors)
    // Reliable for Chinese documents that use custom/WPS style names instead of Heading 1–6.
    if (!headings.length) {
      pm.querySelectorAll('p[class^="koto-toc-"]').forEach(el => {
        const m = el.className.match(/koto-toc-(\d+)/);
        if (!m) return;
        const level = parseInt(m[1], 10);
        const a = el.querySelector('a');
        if (!a) return;
        const id = (a.getAttribute('href') || '').replace(/^#/, '');
        // Remove the dot-leader spacer span text (empty) and trailing page number
        let text = '';
        a.childNodes.forEach(node => {
          if (node.nodeType === Node.TEXT_NODE) text += node.textContent;
          else if (node.nodeName !== 'SPAN') text += node.textContent;
        });
        text = text.replace(/\s*\d+\s*$/, '').trim();
        if (text) headings.push({ level, text, id });
      });
    }

    return headings;
  }

  function _renderOutlineItems(container, headings) {
    container.innerHTML = '';
    if (!headings.length) {
      container.innerHTML = '<div class="wa-outline-empty">此文档没有标题</div>';
      return;
    }

    // Build a tree structure from the flat heading list.
    // Each node has: { heading, children: [], element }
    const root = { children: [], level: 0 };
    const stack = [root]; // stack of parent nodes

    headings.forEach((h, idx) => {
      const node = { heading: h, children: [], level: h.level, idx };

      // Pop stack until we find a parent with a lower level
      while (stack.length > 1 && stack[stack.length - 1].level >= h.level) {
        stack.pop();
      }
      stack[stack.length - 1].children.push(node);
      stack.push(node);
    });

    // Recursively render the tree
    function _renderTree(parent, parentEl) {
      parent.children.forEach(node => {
        const h = node.heading;

        const wrapper = document.createElement('div');
        wrapper.className = 'wa-outline-node';

        const row = document.createElement('div');
        row.className = `wa-outline-item level-${h.level}`;
        row.dataset.idx = node.idx;
        row.dataset.headingId = h.id || '';
        row.title = h.text;

        // Toggle arrow for items with children
        if (node.children.length > 0) {
          const arrow = document.createElement('span');
          arrow.className = 'wa-outline-arrow expanded';
          arrow.innerHTML = '▾';
          arrow.addEventListener('click', (e) => {
            e.stopPropagation();
            const childContainer = wrapper.querySelector('.wa-outline-children');
            if (childContainer) {
              const collapsed = childContainer.style.display === 'none';
              childContainer.style.display = collapsed ? '' : 'none';
              arrow.classList.toggle('expanded', collapsed);
              arrow.classList.toggle('collapsed', !collapsed);
              arrow.innerHTML = collapsed ? '▾' : '▸';
            }
          });
          row.appendChild(arrow);
        } else {
          // Spacer for alignment
          const spacer = document.createElement('span');
          spacer.className = 'wa-outline-arrow-spacer';
          row.appendChild(spacer);
        }

        const text = document.createElement('span');
        text.className = 'wa-outline-text';
        text.textContent = h.text;
        row.appendChild(text);

        row.addEventListener('click', () => _navigateToHeading(h, row));
        wrapper.appendChild(row);

        // Render children
        if (node.children.length > 0) {
          const childContainer = document.createElement('div');
          childContainer.className = 'wa-outline-children';
          _renderTree(node, childContainer);
          wrapper.appendChild(childContainer);
        }

        parentEl.appendChild(wrapper);
      });
    }

    _renderTree(root, container);
  }

  function _navigateToHeading(heading, itemEl) {
    // Try to find the heading in the ProseMirror DOM
    const pm = document.querySelector('#wa-docx-editor .ProseMirror');
    if (!pm) return;
    let target = null;
    if (heading.id) {
      // IDs may be bookmark IDs like "_Toc198131813" placed on any element
      target = pm.querySelector(`[id="${CSS.escape(heading.id)}"]`);
      // Also try a nested <span id="..."> (bookmarks are sometimes wrapped)
      if (!target) target = pm.querySelector(`span[id="${CSS.escape(heading.id)}"]`);
    }
    if (!target) {
      // Fallback: find an h-tag with matching text
      pm.querySelectorAll('h1,h2,h3,h4,h5,h6').forEach(el => {
        if (!target && el.textContent.trim() === heading.text) target = el;
      });
    }
    if (!target) {
      // Fallback: any element whose text exactly starts with the heading text
      pm.querySelectorAll('p, h1, h2, h3, h4, h5, h6').forEach(el => {
        if (!target && el.textContent.trim().startsWith(heading.text) && heading.text.length > 2) target = el;
      });
    }
    if (target) {
      target.scrollIntoView({ behavior: 'smooth', block: 'center' });
      // Highlight the heading briefly
      target.style.transition = 'background .3s';
      target.style.background = 'rgba(79,126,255,.15)';
      setTimeout(() => { target.style.background = ''; }, 1800);
    }
    // Highlight the nav item
    const body = itemEl.closest('.wa-outline-body');
    if (body) body.querySelectorAll('.wa-outline-item').forEach(el => el.classList.remove('active'));
    itemEl.classList.add('active');
  }

  function _toggleDocOutline(show) {
    const outline = $('wa-doc-outline');
    const btn = document.querySelector('.wa-pi-outline-btn');
    if (!outline) return;
    if (typeof show === 'undefined') {
      show = !outline.classList.contains('active');
    }
    outline.classList.toggle('active', show);
    if (btn) btn.classList.toggle('active', show);
  }

  function _ensureOutlineToggleBtn() {
    const pi = $('wa-docx-page-indicator');
    if (!pi || pi.querySelector('.wa-pi-outline-btn')) return;
    const btn = document.createElement('button');
    btn.className = 'wa-pi-outline-btn';
    btn.title = '文档导航';
    btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor"><path d="M2 3h12v1H2zm0 4h8v1H2zm0 4h10v1H2zM14 7h-2v1h2zm-2 4h2v1h-2z"/></svg><span>导航</span>';
    btn.addEventListener('click', () => _toggleDocOutline());
    // Insert at the start of the page indicator
    pi.insertBefore(btn, pi.firstChild);
  }

  // ── Mount a parsed file response (shared by Router.load + openWorkspaceFile) ─
  /**
   * Apply a parsed-file API response ({file_id, file_type, file_name, data}) to
   * the editor state.  wsPath is the workspace-relative path used for tab identity;
   * fsHandle is a FileSystemFileHandle for write-back to disk (may be null).
   */
  async function _applyFileJson(json, wsPath, fsHandle) {
    state.fileId   = json.file_id;
    state.fileType = json.file_type;
    state.fileName = json.file_name;
    state.filePath = json.temp_path || wsPath || null;
    const ext = json.file_name.split('.').pop().toLowerCase();
    state.wsSourcePath = wsPath;
    state.activeTabPath = wsPath;
    const fileNameEl = $('wa-file-name');
    if (fileNameEl) fileNameEl.textContent = state.fileName;
    const _archBtn = $('wa-archive-btn'); if (_archBtn) _archBtn.disabled = false;
    _updateSubjectBar(state.fileName, state.fileType);

    const pdfZoomCtrl = $('wa-pdf-zoom-ctrl');
    if (pdfZoomCtrl) pdfZoomCtrl.style.display = (state.fileType === 'pdf') ? 'flex' : 'none';
    const docxZoomCtrl = $('wa-docx-zoom-ctrl');
    if (docxZoomCtrl) docxZoomCtrl.style.display = (state.fileType === 'docx') ? 'flex' : 'none';

    if (state.activeEditor) {
      try { state.activeEditor.destroy(); } catch(e) {
        console.error('Editor destroy failed:', e);
        const canvas = document.getElementById('wa-canvas');
        if (canvas) canvas.innerHTML = '';
      }
    }
    state.activeEditor = null;

    const existingTabIdx = state.openTabs.findIndex(t => t.path === wsPath);
    const tabEntry = {
      path: wsPath, name: json.file_name, ext,
      filePath: json.temp_path || wsPath || null,
      fileType: json.file_type, fileId: json.file_id,
      serverData: json.data, cache: null, modified: false,
      fsHandle: fsHandle || null,
    };
    if (fsHandle) _fsHandleMap.set(wsPath, fsHandle);
    if (existingTabIdx >= 0) { state.openTabs[existingTabIdx] = tabEntry; }
    else { state.openTabs.push(tabEntry); }
    _syncPrimarySaveButtons(tabEntry);

    toggleWorkspace(true);
    await _waitForEditorLayout(state.fileType);

    if (state.fileType === 'docx') {
      await _mountDocxEditor(tabEntry, json.data.html, json.data, json.data.headings || []);
    } else if (state.fileType === 'xlsx') {
      await _ensureUniverSheets();
      state.activeEditor = new KotoXlsxEditor();
      state.activeEditor.render(_ensureWorkbookDefaults(json.data));
      if (json.data && json.data._warnings && json.data._warnings.length) {
        json.data._warnings.forEach(msg => { showToast(msg, 'warning', 8000); });
      }
    } else if (state.fileType === 'pptx') {
      state.activeEditor = new KotoPptxEditor();
      state.activeEditor.render(json.data);
    } else if (state.fileType === 'pdf') {
      await _ensurePdfJS();
      state.activeEditor = new KotoPdfViewer();
      state.activeEditor.render(json.data.raw_url, json.data);
    } else if (state.fileType === 'image') {
      state.activeEditor = new KotoImageViewer();
      state.activeEditor.render(json.data.raw_url);
    } else if (state.fileType === 'text' || state.fileType === 'code') {
      state.activeEditor = new KotoTextEditor(state.fileType);
      state.activeEditor.render(json.data);
    }

    _renderTabs();
    setTimeout(loadWorkspaceFiles, 600);
  }

  // ── Main Router (for external / drag-drop files that must be uploaded) ──
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
         const json = await _safeJson(res);
         if (!res.ok) throw new Error(json.error || '上传失败');

         $('upload-progress').style.width = '100%';
         const wsPath = file._wsPath || json.ws_source_path || json.file_name;
         await _applyFileJson(json, wsPath, file._fsHandle || null);

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

  /** Switch the footer send button into a pause state while an AI task is active. */
  function _setStreamBtn(streaming) {
    const sendBtn = $('wa-send-btn');
    if (!sendBtn) return;

    sendBtn.classList.toggle('is-streaming', !!streaming);
    sendBtn.title = streaming ? '停止当前任务' : '发送';
    sendBtn.setAttribute('aria-label', streaming ? '停止当前任务' : '发送');
    sendBtn.innerHTML = streaming ? _PAUSE_SVG : _SEND_SVG;
    sendBtn.onclick = streaming
      ? () => window.WA.stopStream()
      : () => window.WA.sendMessage();
  }

  /** Abort the currently active AI task stream (if any). */
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
      if (!resp.ok) {
        if (resp.status === 404) {
          throw new Error('后端服务未就绪 (404)，请重启应用后重试');
        }
        throw new Error(`HTTP ${resp.status}: ${resp.statusText}`);
      }
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
            if (evt.type === 'classification') {
              _applyRouteEvent(evt);
              continue;
            }
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
              let proposalsRendered = false;
              let proposalData = null;
              const visible = fullText
                .replace(/<TOOL>[\s\S]*?<\/TOOL>/g, '')
                .replace(/\n?\{"proposals"\s*:\s*\[[\s\S]*?\]\s*\}\s*$/m, '')
                .trim();
              const finalText = visible || evt.content || '';
              const propMatch = fullText.match(/\{"proposals"\s*:\s*\[[\s\S]*?\]\s*\}/);
              if (propMatch) {
                try {
                  const parsedProposals = JSON.parse(propMatch[0]);
                  if (Array.isArray(parsedProposals.proposals) && parsedProposals.proposals.length) {
                    proposalData = parsedProposals;
                  }
                } catch(e) { /* ignore */ }
              }
              if (loadingEl) {
                loadingEl.classList.remove('streaming');
                if (proposalData) {
                  // Proposal cards supersede the transient chat bubble.
                  loadingEl.remove();
                } else {
                  loadingEl.innerHTML = _parseCitations(renderMd(finalText));
                  if (finalText) {
                    loadingEl.dataset.rawText = finalText;
                  }
                }
              }
              if (finalText) {
                state.conversation.push({ role: 'assistant', content: finalText });
              }
              msgs.scrollTop = msgs.scrollHeight;
              // Extract and apply TOOL calls
              const toolMatches = [...fullText.matchAll(/<TOOL>([\s\S]*?)<\/TOOL>/g)];
              toolMatches.forEach(m => {
                try { _handleToolCall(JSON.parse(m[1].trim())); } catch(e) { /* ignore */ }
              });
              if (proposalData) {
                _handleProposals(proposalData);
                proposalsRendered = true;
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
                loadingEl.innerHTML = `<span style="color:var(--error,#ef4444)">${_escHtml(evt.message || 'AI 处理失败')}</span>`;
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
          const msg = err.message || String(err);
          if (msg.includes('404')) {
            loadingEl.textContent = '⚠️ 后端接口未就绪，请重启 Koto 后重试';
          } else if (msg.includes('Failed to fetch') || msg.includes('NetworkError')) {
            loadingEl.textContent = '⚠️ 无法连接后端服务，请检查 Koto 是否正在运行';
          } else {
            loadingEl.textContent = `网络错误：${msg}`;
          }
        }
      }
      state.isLoading = false;
    } finally {
      state._streamAbortCtrl = null;
      _setStreamBtn(false);
    }
  }

  function _waInferFileType(pathOrName) {
    const match = String(pathOrName || '').match(/\.([a-z0-9]+)$/i);
    return match ? match[1].toLowerCase() : '';
  }

  function _waSampleTaskContext(text, limit = 12000) {
    const content = String(text || '');
    if (content.length <= limit) return content;
    const head = Math.max(Math.floor(limit * 0.7), 1);
    const tail = Math.max(limit - head - 48, 0);
    const marker = '\n\n...[中间内容已省略]...\n\n';
    if (tail <= 0) return content.slice(0, limit);
    return content.slice(0, head) + marker + content.slice(-tail);
  }

  function _waBuildTaskFiles(currentContent) {
    const files = [];
    const seen = new Set();

    const addFile = (file) => {
      if (!file) return;
      const rawPath = String(file.path || '').trim();
      const rawName = String(file.name || '').trim();
      const key = (rawPath || rawName).toLowerCase();
      if (!key || seen.has(key)) return;
      seen.add(key);
      files.push({
        path: rawPath || rawName || 'current_document',
        name: rawName || (rawPath ? rawPath.split(/[\\/]/).pop() : 'current_document'),
        type: String(file.type || '').trim().toLowerCase() || _waInferFileType(rawPath || rawName),
        content_preview: _waSampleTaskContext(String(file.content_preview || '')),
      });
    };

    if (state.fileName && currentContent) {
      addFile({
        path: state.wsSourcePath || state.filePath || state.fileName || 'current_document',
        name: state.fileName || 'current_document',
        type: state.fileType || _waInferFileType(state.fileName),
        content_preview: currentContent,
      });
    }

    (state._aiFileContext || []).forEach((file) => {
      addFile({
        path: file.path || file.name || '',
        name: file.name || '',
        type: file.type || _waInferFileType(file.path || file.name),
        content_preview: file.content || '',
      });
    });

    return files;
  }

  function _waBuildOpenClawTaskMessage(userText, opts) {
    opts = opts || {};
    const parts = [
      '请按文件任务方式执行下面的请求。优先使用文件工具读取、分析、修改或生成结果文件，而不是把文件内容当作普通聊天文本复述。',
      '你必须对最终文件结果负责：如果任务涉及文档修改，必须实际完成文件写入，并在结束前确认目标文件已经更新。',
      '如果用户只是想打开/查看某个文件，直接调用 open_file_in_editor 工具，无需读取内容或修改文件。',
    ];

    if (opts.currentFileName) {
      parts.push(`当前编辑文件: ${opts.currentFileName}`);
    }

    if (opts.targetFileName) {
      parts.push(`目标文件: ${opts.targetFileName}`);
      if (opts.referenceFileNames && opts.referenceFileNames.length) {
        parts.push(`参考文件: ${opts.referenceFileNames.join(', ')}`);
        parts.push('除非用户明确要求，否则优先围绕目标文件产出修改或结果，参考文件主要用于比对、抽取和校验。');
      }
    } else if (opts.attachedFileNames && opts.attachedFileNames.length) {
      parts.push(`已提供文件: ${opts.attachedFileNames.join(', ')}`);
    }

    if (opts.pinnedSelection) {
      const snippet = opts.pinnedSelection.length > 500
        ? opts.pinnedSelection.substring(0, 500) + '...'
        : opts.pinnedSelection;
      parts.push(`当前重点选中文本:\n${snippet}`);
    }

    parts.push(`用户要求:\n${userText}`);
    return parts.join('\n\n');
  }

  async function _waSendToOpenClawTask(taskText, loadingEl, opts) {
    opts = opts || {};
    const msgs = $('wa-ai-messages');

    // ── Quick-path: pure "open file" intent ──────────────────────────────
    // If the user typed just a filename (or "打开/查看 filename"), skip the
    // full task agent and open the file directly in the editor.
    const _trimmed = String(opts.openIntentText || taskText || '').trim();
    const _openIntent = _trimmed.match(
      /^(?:打开|open|查看|show|打开文件)?\s*([\w\u4e00-\u9fff\u3400-\u4dbf\-. ()（）]+\.(?:docx?|xlsx?|pptx?|pdf|txt|md|csv|json))\s*$/i
    );
    if (_openIntent) {
      const _fname = _openIntent[1].trim();
      if (loadingEl) {
        loadingEl.classList.remove('streaming');
        loadingEl.innerHTML = `<span style="opacity:.7">正在打开 ${_escHtml(_fname)}…</span>`;
      }
      try {
        await Promise.resolve(WA.openWorkspaceFile(_fname));
        if (loadingEl) loadingEl.innerHTML = `✅ 已打开 ${_escHtml(_fname)}`;
      } catch (e) {
        if (loadingEl) loadingEl.innerHTML = `❌ 未找到文件 ${_escHtml(_fname)}`;
      }
      state.isLoading = false;
      _setStreamBtn(false);
      return;
    }
    // ─────────────────────────────────────────────────────────────────────

    let finalAnswer = '';
    let stepCount = 0;
    const startTime = Date.now();
    const taskFiles = _waBuildTaskFiles(opts.currentContent || '');
    const stepEls = new Map();
    let currentStepId = '';

    const renderMd = (text) => {
      if (window.marked) { try { return window.marked.parse(text || ''); } catch(e) {} }
      return (text || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\n/g,'<br>');
    };

    const timelineEl = document.createElement('div');
    timelineEl.className = 'wa-agent-timeline';
    if (loadingEl) {
      loadingEl.innerHTML = '';
      loadingEl.appendChild(timelineEl);
    }

    // Single "thinking" status element that shows the latest model thought
    // (not accumulated — updates in-place so it doesn't clutter the step list)
    let thinkingEl = null;
    function _setThinking(text) {
      if (!text) {
        if (thinkingEl) { thinkingEl.remove(); thinkingEl = null; }
        return;
      }
      if (!thinkingEl) {
        thinkingEl = document.createElement('div');
        thinkingEl.className = 'wa-agent-step step-thinking';
        thinkingEl.innerHTML = '<span class="wa-step-icon">💭</span><span class="wa-step-label"></span>';
        timelineEl.appendChild(thinkingEl);
      }
      const labelEl = thinkingEl.querySelector('.wa-step-label');
      if (labelEl) labelEl.textContent = text.length > 160 ? text.substring(0, 160) + '…' : text;
      // Keep it at the bottom
      timelineEl.appendChild(thinkingEl);
      if (msgs) msgs.scrollTop = msgs.scrollHeight;
    }
    function _clearThinking() {
      if (thinkingEl) { thinkingEl.remove(); thinkingEl = null; }
    }

    let filesModified = 0;
    let filesCreated = 0;
    let chartsGenerated = 0;
    const refreshedPaths = new Set();

    function _addStep(icon, label, cls) {
      const step = document.createElement('div');
      step.className = `wa-agent-step ${cls || ''}`;
      step.innerHTML = `<span class="wa-step-icon">${icon}</span><span class="wa-step-label">${_escHtml(label)}</span>`;
      timelineEl.appendChild(step);
      if (msgs) msgs.scrollTop = msgs.scrollHeight;
      return step;
    }

    function _updateStep(stepEl, icon, label, cls) {
      if (!stepEl) return;
      stepEl.className = `wa-agent-step ${cls || ''}`;
      const iconEl = stepEl.querySelector('.wa-step-icon');
      if (iconEl) iconEl.innerHTML = icon;
      const labelEl = stepEl.querySelector('.wa-step-label');
      if (labelEl) labelEl.textContent = label;
    }

    function _ensureStep(stepId, label, cls, icon) {
      if (stepId && stepEls.has(stepId)) return stepEls.get(stepId);
      const stepEl = _addStep(icon || '⚙️', label, cls || 'step-action');
      if (stepId) stepEls.set(stepId, stepEl);
      return stepEl;
    }

    function _toolPathFromArgs(args) {
      if (!args || typeof args !== 'object') return '';
      return args.path || args.destination || args.file_path || args.source || '';
    }

    function _openFileIfUseful(toolName, toolPath) {
      if (!toolPath) return;
      if (toolName !== 'create_file' && toolName !== 'copy_file') return;
      setTimeout(() => {
        try { WA.openWorkspaceFile(toolPath); } catch(e) { console.warn('[TaskAgent] Auto-open failed:', e); }
      }, 300);
    }

    function _normalizeTaskPath(value) {
      return String(value || '').replace(/\\/g, '/');
    }

    function _refreshChangedFile(filePath, fileType, focus) {
      const normalizedPath = _normalizeTaskPath(filePath);
      if (!normalizedPath) return;
      const currentPath = _normalizeTaskPath(state.wsSourcePath || '');
      const alreadyOpen = (state.openTabs || []).some((tab) => _normalizeTaskPath(tab.path) === normalizedPath);
      if (!focus && normalizedPath !== currentPath && !alreadyOpen) return;
      if (refreshedPaths.has(normalizedPath)) return;
      refreshedPaths.add(normalizedPath);
      const supported = _isSupportedExt(fileType || _waInferFileType(normalizedPath));
      setTimeout(() => {
        Promise.resolve(WA.reloadFileByPath(normalizedPath, supported))
          .catch((error) => console.warn('[TaskAgent] File refresh failed:', error))
          .finally(() => setTimeout(() => refreshedPaths.delete(normalizedPath), 800));
      }, 250);
    }

    function _finalizeTask(summaryText) {
      const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);

      if (finalAnswer) {
        const answerEl = document.createElement('div');
        answerEl.className = 'wa-agent-answer';
        answerEl.innerHTML = _parseCitations(renderMd(finalAnswer));
        if (loadingEl) loadingEl.appendChild(answerEl);
        loadingEl.dataset.rawText = finalAnswer;
        state.conversation.push({ role: 'assistant', content: finalAnswer });
      }

      const footerEl = document.createElement('div');
      footerEl.className = 'wa-agent-footer';
      const footerParts = [`完成 ${stepCount} 步`, `${elapsed}s`, `${taskFiles.length} 文件`];
      if (filesModified > 0) footerParts.push(`修改 ${filesModified} 文件`);
      if (filesCreated > 0) footerParts.push(`生成 ${filesCreated} 文件`);
      if (chartsGenerated > 0) footerParts.push(`生成 ${chartsGenerated} 图表`);
      if (summaryText) footerParts.push(summaryText);
      footerEl.innerHTML = `<span>${footerParts.join(' · ')}</span>`;
      if (loadingEl) loadingEl.appendChild(footerEl);

      if (loadingEl) loadingEl.classList.remove('streaming');
      if (msgs) msgs.scrollTop = msgs.scrollHeight;
      state.isLoading = false;
    }

    try {
      const ctrl = new AbortController();
      state._streamAbortCtrl = ctrl;
      _setStreamBtn(true);

      const lockedModel = opts.model || state.lockedModel || 'auto';
      const payload = {
        action: 'ai_task',
        instruction: taskText,
        session_id: _waSession(),
        model_mode: lockedModel === 'local' ? 'local' : 'auto',
        model_id: (lockedModel && !['auto', 'local'].includes(lockedModel)) ? lockedModel : '',
        file_type: state.fileType || '',
        file_name: state.fileName || '',
        files: taskFiles,
      };

      const resp = await fetch('/api/editor/ai/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        signal: ctrl.signal,
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${resp.statusText}`);

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let streamBuffer = '';

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

            if (evt.type === 'classification') {
              _applyRouteEvent(evt);
              continue;
            }

            if (evt.type === 'thought') {
              const text = evt.text || '';
              if (text) _setThinking(text);
              continue;
            }

            if (evt.type === 'plan_summary') {
              _clearThinking();
              _addStep('📋', evt.text || '已生成执行计划', 'step-planning');
              continue;
            }

            if (evt.type === 'plan') {
              const steps = Array.isArray(evt.steps) ? evt.steps : [];
              const summary = steps
                .map((step) => step.text || step.title || step.label || step.description || '')
                .filter(Boolean)
                .join(' -> ');
              if (summary) {
                _addStep('📋', summary.length > 180 ? summary.substring(0, 180) + '...' : `计划: ${summary}`, 'step-planning');
              }
              continue;
            }

            if (evt.type === 'step_start') {
              _clearThinking();
              stepCount++;
              currentStepId = evt.step_id || `step_${stepCount}`;
              const stepEl = _ensureStep(currentStepId, evt.text || '执行步骤', 'step-action', '⚙️');
              if (!stepEl.querySelector('.wa-step-spinner')) {
                const spinner = document.createElement('span');
                spinner.className = 'wa-step-spinner';
                stepEl.appendChild(spinner);
              }
              continue;
            }

            if (evt.type === 'step_progress') {
              const stepId = evt.step_id || currentStepId || `step_${stepCount || 1}`;
              const stepEl = _ensureStep(stepId, evt.detail || '处理中...', 'step-action', '⚙️');
              _updateStep(stepEl, '⚙️', evt.detail || '处理中...', 'step-action');
              if (!stepEl.querySelector('.wa-step-spinner')) {
                const spinner = document.createElement('span');
                spinner.className = 'wa-step-spinner';
                stepEl.appendChild(spinner);
              }
              continue;
            }

            if (evt.type === 'tool_call') {
              _clearThinking();
              const stepId = evt.step_id || currentStepId || `tool_${stepCount || 1}`;
              const toolName = evt.tool_name || 'tool';
              const toolArgs = evt.tool_args || {};
              const toolLabel = _toolDisplayName(toolName, toolArgs);
              const stepEl = _ensureStep(stepId, `${toolLabel}...`, 'step-action', '⚙️');
              stepEl.dataset.toolName = toolName;
              stepEl.dataset.toolPath = _toolPathFromArgs(toolArgs);
              _updateStep(stepEl, '⚙️', `${toolLabel}...`, 'step-action');
              if (!stepEl.querySelector('.wa-step-spinner')) {
                const spinner = document.createElement('span');
                spinner.className = 'wa-step-spinner';
                stepEl.appendChild(spinner);
              }
              currentStepId = stepId;
              continue;
            }

            if (evt.type === 'tool_result') {
              const stepId = evt.step_id || currentStepId;
              const stepEl = stepId ? stepEls.get(stepId) : null;
              const preview = evt.result_preview || (evt.tool_name ? `${evt.tool_name} 已完成` : '工具执行完成');
              if (/image\(s\) generated/i.test(preview) || /figure_\d+\.png/i.test(preview)) {
                chartsGenerated++;
              }
              if (stepEl) {
                _updateStep(stepEl, '⚙️', preview.length > 140 ? preview.substring(0, 140) + '...' : preview, 'step-action');
              }
              continue;
            }

            if (evt.type === 'file_change') {
              const changedPath = String(evt.path || '').trim();
              const changedName = changedPath ? changedPath.split(/[\\/]/).pop() : '文件';
              const changeType = evt.change_type || 'modify';
              const changeSummary = evt.summary || `${changedName} 已更新`;
              if (changeType === 'open') {
                // Open-only: don't count as modification, just show as navigation
                _clearThinking();
                _addStep('📂', changeSummary, 'step-done');
              } else {
                if (changeType === 'create') filesCreated++;
                else filesModified++;
                _addStep('📝', changeSummary, 'step-done');
              }
              _refreshChangedFile(changedPath, evt.file_type || '', !!evt.focus);
              continue;
            }

            if (evt.type === 'step_done') {
              _clearThinking();
              const stepId = evt.step_id || currentStepId;
              const stepEl = stepId ? stepEls.get(stepId) : null;
              const label = evt.text || (stepEl && stepEl.querySelector('.wa-step-label')
                ? stepEl.querySelector('.wa-step-label').textContent.replace(/\.\.\.$/, '')
                : '步骤完成');
              if (stepEl) {
                _updateStep(stepEl, '✅', label, 'step-done');
                const spinner = stepEl.querySelector('.wa-step-spinner');
                if (spinner) spinner.remove();
                _openFileIfUseful(stepEl.dataset.toolName || '', stepEl.dataset.toolPath || '');
              } else {
                _addStep('✅', label, 'step-done');
              }
              currentStepId = '';
              continue;
            }

            if (evt.type === 'step_error') {
              const stepId = evt.step_id || currentStepId;
              const stepEl = stepId ? stepEls.get(stepId) : null;
              const errorText = evt.error || '步骤执行失败';
              if (stepEl) {
                _updateStep(stepEl, '❌', errorText, 'step-error');
                const spinner = stepEl.querySelector('.wa-step-spinner');
                if (spinner) spinner.remove();
              } else {
                _addStep('❌', errorText, 'step-error');
              }
              continue;
            }

            if (evt.type === 'result') {
              finalAnswer = typeof evt.data === 'string'
                ? evt.data
                : (evt.data && (evt.data.text || evt.data.content || '')) || '';
              continue;
            }

            if (evt.type === 'done') {
              _finalizeTask(evt.summary || '');
              return;
            }

            if (evt.type === 'error') {
              if (loadingEl) {
                loadingEl.classList.remove('streaming');
                loadingEl.innerHTML = `<span style="color:var(--error,#ef4444)">${_escHtml(evt.text || '任务处理失败')}</span>`;
              }
              state.isLoading = false;
              return;
            }
          } catch (e) { /* ignore malformed SSE line */ }
        }
      }

      if (loadingEl && loadingEl.classList.contains('streaming')) {
        _finalizeTask('');
      }
      state.isLoading = false;
    } catch (err) {
      if (err.name === 'AbortError') {
        if (loadingEl) {
          loadingEl.classList.remove('streaming');
          if (!loadingEl.textContent.trim()) loadingEl.textContent = '[已取消]';
          else loadingEl.innerHTML += '<span style="color:var(--muted,#888);font-size:11px"> [已取消]</span>';
        }
      } else {
        console.error('[WorkspaceAI] OpenClaw task error:', err);
        if (loadingEl) {
          loadingEl.classList.remove('streaming');
          loadingEl.textContent = `网络错误：${err.message}`;
        }
      }
      state.isLoading = false;
    } finally {
      state._streamAbortCtrl = null;
      _setStreamBtn(false);
    }
  }

  // ── Agent-backed AI Stream (backed by /agent/chat) ──────────────────────
  //
  // Uses the full Agent ReAct protocol with agent_step / task_final events.
  // Renders THOUGHT → ACTION → OBSERVATION → ANSWER as a step timeline.

  /**
   * Stream a message through /agent/chat (SSE agent_step protocol).
    */
  async function _waSendToAgent(message, loadingEl, opts) {
    opts = opts || {};
    const msgs = $('wa-ai-messages');
    let finalAnswer = '';
    let stepCount = 0;
    const startTime = Date.now();

    const renderMd = (text) => {
      if (window.marked) { try { return window.marked.parse(text || ''); } catch(e) {} }
      return (text || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\n/g,'<br>');
    };

    // Build file_context from current workspace state
    const fileContext = {
      file_id: state.fileId || '',
      file_type: state.fileType || '',
      file_path: state.wsSourcePath || state.filePath || state.fileName || '',
      file_name: state.fileName || '',
      open_tabs: (state.openTabs || []).map(t => t.name || t.id || ''),
      selection: state.lastPinnedSel || '',
      // Paths of files explicitly attached to the AI panel (for tool-based file access)
      analysis_files: (state._aiFileContext || []).map(f => ({ name: f.name, path: f.path })),
    };

    const payload = {
      session_id: _waSession(),
      message: message,
      model: opts.model || state.lockedModel || 'auto',
      task_type: opts.task_type || 'FILE_ASSISTANT',
      file_context: fileContext,
    };

    // ── @File reference extraction ──────────────────────────────
    // Matches @filename.ext patterns in the message (Chinese + ASCII filenames)
    const atFileRe = /@([\w\u4e00-\u9fff\u3400-\u4dbf\-. ()（）]+\.(?:docx?|xlsx?|pptx?|pdf|txt|md|csv|json))/gi;
    const atMatches = message.match(atFileRe);
    if (atMatches && atMatches.length) {
      payload.context_files = atMatches.map(m => m.slice(1).trim());
    }

    // Create a timeline container inside the loading bubble
    const timelineEl = document.createElement('div');
    timelineEl.className = 'wa-agent-timeline';
    if (loadingEl) {
      loadingEl.innerHTML = '';
      loadingEl.appendChild(timelineEl);
    }

    // ── Step 4.1: Track files modified, charts generated ──────────
    let filesModified = 0;
    let filesCreated = 0;
    let chartsGenerated = 0;
    let thinkingEl = null;
    const _fileTrackTools = new Set(['workspace_create_file', 'workspace_save_file', 'editor_apply']);

    function _addStep(icon, label, cls) {
      const step = document.createElement('div');
      step.className = `wa-agent-step ${cls || ''}`;
      step.innerHTML = `<span class="wa-step-icon">${icon}</span><span class="wa-step-label">${_escHtml(label)}</span>`;
      timelineEl.appendChild(step);
      if (msgs) msgs.scrollTop = msgs.scrollHeight;
      return step;
    }

    function _updateStep(stepEl, icon, label, cls) {
      if (!stepEl) return;
      stepEl.className = `wa-agent-step ${cls || ''}`;
      const iconEl = stepEl.querySelector('.wa-step-icon');
      if (iconEl) iconEl.innerHTML = icon;
      const labelEl = stepEl.querySelector('.wa-step-label');
      if (labelEl) labelEl.textContent = label;
    }

    try {
      const ctrl = new AbortController();
      state._streamAbortCtrl = ctrl;
      _setStreamBtn(true);

      // ── Step 4.3: Create pre-agent checkpoint ─────────────────
      let _agentCheckpoint = null;
      if (state.wsSourcePath) {
        try {
          const cpResp = await fetch('/api/v1/workspace/checkpoint', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: state.wsSourcePath, label: 'agent_pre' }),
          });
          if (cpResp.ok) _agentCheckpoint = await cpResp.json();
        } catch (e) { /* non-critical */ }
      }

      const resp = await fetch('/api/agent/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        signal: ctrl.signal,
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${resp.statusText}`);

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let streamBuffer = '';
      let currentActionStep = null;

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

            if (evt.type === 'agent_step' && evt.data) {
              const step = evt.data;
              const stepType = (step.step_type || '').toUpperCase();

              if (stepType === 'THOUGHT') {
                const content = step.content || '';
                const phase = (step.metadata || {}).phase || '';
                if (phase === 'planning') {
                  _addStep('📋', content || '规划任务...', 'step-planning');
                } else if (content) {
                  // Show as updating status, not as an accumulated step
                  if (!thinkingEl) {
                    thinkingEl = _addStep('💭', '', 'step-thinking');
                  }
                  const lbl = thinkingEl.querySelector('.wa-step-label');
                  if (lbl) lbl.textContent = content.length > 160 ? content.substring(0, 160) + '…' : content;
                  timelineEl.appendChild(thinkingEl);
                  if (msgs) msgs.scrollTop = msgs.scrollHeight;
                }
              }

              else if (stepType === 'ACTION') {
                // Clear thinking indicator when real work begins
                if (thinkingEl) { thinkingEl.remove(); thinkingEl = null; }
                stepCount++;
                const toolName = (step.action || {}).tool_name || 'tool';
                const toolArgs = (step.action || {}).tool_args || {};
                const toolLabel = _toolDisplayName(toolName, toolArgs);
                currentActionStep = _addStep('⚙️', `${toolLabel}...`, 'step-action');
                // Store tool info for auto-focus in OBSERVATION handler
                currentActionStep.dataset.toolName = toolName;
                currentActionStep.dataset.toolPath = toolArgs.path || toolArgs.file_path || '';
                // Track file modifications
                if (toolName === 'workspace_create_file') filesCreated++;
                if (_fileTrackTools.has(toolName)) filesModified++;
                // Add a spinner
                const spinner = document.createElement('span');
                spinner.className = 'wa-step-spinner';
                currentActionStep.appendChild(spinner);
              }

              else if (stepType === 'OBSERVATION') {
                if (currentActionStep) {
                  // Update the ACTION step to show completion
                  const labelEl = currentActionStep.querySelector('.wa-step-label');
                  const label = labelEl ? labelEl.textContent.replace('...', '') : '';
                  _updateStep(currentActionStep, '✅', label + ' ✓', 'step-done');
                  const spinner = currentActionStep.querySelector('.wa-step-spinner');
                  if (spinner) spinner.remove();

                  // ── Step 4.2: Auto-focus on created/opened files ──────
                  const prevAction = currentActionStep.dataset;
                  if (prevAction && prevAction.toolName) {
                    const tn = prevAction.toolName;
                    const tp = prevAction.toolPath;
                    if ((tn === 'workspace_create_file' || tn === 'editor_open_file') && tp) {
                      // Defer file opening to avoid blocking the stream
                      setTimeout(() => {
                        try { WA.openWorkspaceFile(tp); } catch(e) { console.warn('[Agent] Auto-open failed:', e); }
                      }, 300);
                    }
                    if (tn === 'editor_apply') {
                      // Flash the editor to show changes were applied
                      const canvas = document.getElementById('wa-canvas');
                      if (canvas) {
                        canvas.style.transition = 'box-shadow 0.3s';
                        canvas.style.boxShadow = 'inset 0 0 30px rgba(255,200,0,0.25)';
                        setTimeout(() => { canvas.style.boxShadow = ''; }, 1200);
                      }
                    }
                  }
                  currentActionStep = null;
                }
                // Detect chart/image outputs in observation content
                const obsText = step.observation || step.content || '';
                const imgMatches = obsText.match(/\[file:(figure_\d+\.png)\]/g);
                if (imgMatches) {
                  chartsGenerated += imgMatches.length;
                }
              }

              else if (stepType === 'ANSWER') {
                finalAnswer = step.content || '';
              }

              else if (stepType === 'ERROR') {
                _addStep('❌', step.content || 'Agent 执行失败', 'step-error');
              }
            }

            else if (evt.type === 'task_final' && evt.data) {
              const result = evt.data.result || finalAnswer || '';
              const meta = evt.data.meta || {};
              const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
              const pipelineStatus = evt.data.status || meta.pipeline_status;
              const resumeToken = evt.data.resume_token || meta.resume_token;

              // Render final answer
              if (result) {
                const answerEl = document.createElement('div');
                answerEl.className = 'wa-agent-answer';
                answerEl.innerHTML = _parseCitations(renderMd(result));
                if (loadingEl) loadingEl.appendChild(answerEl);
                state.conversation.push({ role: 'assistant', content: result });
                loadingEl.dataset.rawText = result;
              }

              // ── Approval gate card ──────────────────────────────
              if (pipelineStatus === 'needs_approval' && resumeToken) {
                const approvalEl = document.createElement('div');
                approvalEl.className = 'wa-approval-card';
                approvalEl.innerHTML = `
                  <div class="wa-approval-header">⏸ 需要确认后继续执行</div>
                  <div class="wa-approval-desc">${_escHtml(meta.approval_desc || '即将执行下一步操作，请确认是否继续。')}</div>
                  <div class="wa-approval-actions">
                    <button class="wa-btn-approve" data-action="approve">✅ 批准继续</button>
                    <button class="wa-btn-reject" data-action="reject">❌ 拒绝</button>
                  </div>
                `;
                if (loadingEl) loadingEl.appendChild(approvalEl);

                approvalEl.querySelector('.wa-btn-approve').addEventListener('click', async () => {
                  approvalEl.innerHTML = '<span style="color:var(--success,#22c55e)">✅ 已批准，继续执行…</span>';
                  try {
                    const resp = await fetch('/api/agent/resume', {
                      method: 'POST',
                      headers: { 'Content-Type': 'application/json' },
                      body: JSON.stringify({ resume_token: resumeToken }),
                    });
                    if (resp.ok) {
                      // TODO: stream continuation results
                      const data = await resp.json();
                      if (data.result) {
                        const contEl = document.createElement('div');
                        contEl.className = 'wa-agent-answer';
                        contEl.innerHTML = renderMd(data.result);
                        loadingEl.appendChild(contEl);
                      }
                    }
                  } catch (e) {
                    approvalEl.innerHTML = `<span style="color:var(--error,#ef4444)">恢复执行失败: ${_escHtml(e.message)}</span>`;
                  }
                });
                approvalEl.querySelector('.wa-btn-reject').addEventListener('click', () => {
                  approvalEl.innerHTML = '<span style="color:var(--muted,#888)">❌ 已拒绝</span>';
                });
              }

              // Render summary footer with enriched stats (Step 4.1)
              const footerEl = document.createElement('div');
              footerEl.className = 'wa-agent-footer';
              let footerParts = [`完成 ${stepCount} 步`, `${elapsed}s`];
              if (filesModified > 0) footerParts.push(`修改 ${filesModified} 文件`);
              if (chartsGenerated > 0) footerParts.push(`生成 ${chartsGenerated} 图表`);
              footerEl.innerHTML = `<span>${footerParts.join(' · ')}</span>`;
              if (meta.skill_id) footerEl.innerHTML += ` · <span class="wa-skill-tag">${_escHtml(meta.skill_id)}</span>`;

              // ── Step 4.3: Undo button when agent modified files ────
              if (filesModified > 0 && _agentCheckpoint && _agentCheckpoint.snap_path) {
                const undoBtn = document.createElement('button');
                undoBtn.className = 'wa-btn-undo-agent';
                undoBtn.textContent = '↩️ 撤销 Agent 修改';
                undoBtn.addEventListener('click', async () => {
                  if (!confirm('将文件恢复到 Agent 操作前的状态？')) return;
                  try {
                    const r = await fetch('/api/v1/workspace/restore-version', {
                      method: 'POST',
                      headers: { 'Content-Type': 'application/json' },
                      body: JSON.stringify({
                        snap_path: _agentCheckpoint.snap_path,
                        target_path: _agentCheckpoint.target_path,
                      }),
                    });
                    if (r.ok) {
                      undoBtn.textContent = '✅ 已恢复';
                      undoBtn.disabled = true;
                      showToast('已恢复到 Agent 操作前的版本', 'success');
                      // Reload the file
                      if (state.wsSourcePath) {
                        setTimeout(() => WA.openWorkspaceFile(state.wsSourcePath), 500);
                      }
                    } else {
                      const d = await r.json();
                      showToast(d.error || '恢复失败', 'error');
                    }
                  } catch (e) {
                    showToast('恢复失败: ' + e.message, 'error');
                  }
                });
                footerEl.appendChild(undoBtn);
              }

              if (loadingEl) loadingEl.appendChild(footerEl);

              if (loadingEl) loadingEl.classList.remove('streaming');
              if (msgs) msgs.scrollTop = msgs.scrollHeight;

              // Show action bar if applicable
              if (result && state.activeEditor && opts.allow_apply !== false) {
                const _barSnap = {
                  pinnedSel: state.lastPinnedSel,
                  toolCall: state.pendingToolCall,
                  outputMode: state.aiOutputMode,
                  allowWrite: true,
                };
                msgs.appendChild(_makeAIActionBar(_barSnap));
                requestAnimationFrame(() => { msgs.scrollTop = msgs.scrollHeight; });
              }

              state.isLoading = false;
              return;
            }

            else if (evt.type === 'error') {
              if (loadingEl) {
                loadingEl.classList.remove('streaming');
                loadingEl.innerHTML = `<span style="color:var(--error,#ef4444)">${_escHtml((evt.data || {}).error || 'Agent 处理失败')}</span>`;
              }
              state.isLoading = false;
              return;
            }
          } catch(e) { /* ignore malformed SSE line */ }
        }
      }

      // Stream ended without task_final — finalize
      if (loadingEl && loadingEl.classList.contains('streaming')) {
        loadingEl.classList.remove('streaming');
        if (finalAnswer) {
          const answerEl = document.createElement('div');
          answerEl.className = 'wa-agent-answer';
          answerEl.innerHTML = renderMd(finalAnswer);
          loadingEl.appendChild(answerEl);
          state.conversation.push({ role: 'assistant', content: finalAnswer });
        }
      }
      state.isLoading = false;
    } catch (err) {
      if (err.name === 'AbortError') {
        if (loadingEl) {
          loadingEl.classList.remove('streaming');
          if (!loadingEl.textContent.trim()) loadingEl.textContent = '[已取消]';
          else loadingEl.innerHTML += '<span style="color:var(--muted,#888);font-size:11px"> [已取消]</span>';
        }
      } else {
        console.error('[WorkspaceAI] Agent stream error:', err);
        if (loadingEl) {
          loadingEl.classList.remove('streaming');
          loadingEl.textContent = `网络错误：${err.message}`;
        }
      }
      state.isLoading = false;
    } finally {
      state._streamAbortCtrl = null;
      _setStreamBtn(false);
    }
  }

  /** Map tool names to user-friendly labels for the agent step timeline. */
  function _toolDisplayName(toolName, args) {
    const nameMap = {
      'run_python_code': '🐍 执行 Python',
      'run_r_code': '📊 执行 R',
      'run_shell_command': '💻 执行命令',
      'list_workspace_files': '📂 浏览工作区文件',
      'parse_file_to_text': '📄 解析文件内容',
      'read_docx_content': '📖 读取 Word 内容',
      'write_docx_content': '📝 写入 Word 内容',
      'insert_excel_as_docx_table': '📄 插入 Word 表格',
      'write_sheet_data': '📊 写入表格数据',
      'create_file': '📝 创建文件',
      'copy_file': '📄 复制文件',
      'llm_extract': '🧠 提取结构化信息',
      'llm_transform': '✍️ 转换文本内容',
      'workspace_list_files': '📂 浏览文件',
      'workspace_read_file': '📖 读取 ' + (args.path || '文件'),
      'workspace_create_file': '📝 创建 ' + (args.path || '文件'),
      'workspace_save_file': '💾 保存 ' + (args.path || '文件'),
      'editor_apply': '✏️ 编辑文档',
      'editor_open_file': '📂 打开 ' + (args.path || '文件'),
      'read_file': '📖 读取文件',
      'write_file': '📝 写入文件',
      'replace_text': '✏️ 替换文本',
      'patch_file': '🔧 修补文件',
      'web_search': '🔍 搜索网络',
      'memory_save': '💾 保存记忆',
      'memory_search': '🔍 搜索记忆',
    };
    return nameMap[toolName] || toolName;
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

  // Pre-upload a base64 chart image to the server immediately on arrival so
  // that by the time the user starts dragging, _draggingChartSrc is a short
  // server URL rather than a 500 KB+ base64 string.  Putting a large base64
  // into dataTransfer.setData() serialises it synchronously through the Windows
  // OLE clipboard — THAT is what freezes the main thread during drag.
  function _preUploadChartImage(imgSrc, imgEl) {
    if (!imgSrc || !imgSrc.startsWith('data:image/')) return;
    fetch('/api/v1/workspace/upload_image', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ data: imgSrc }),
    })
      .then(r => r.ok ? r.json() : null)
      .then(res => {
        if (res && res.url && imgEl) {
          imgEl.dataset.serverUrl = res.url;  // swap in for drag+drop & download
        }
      })
      .catch(() => {});  // silent — base64 fallback still works
  }

  function _makeWAChartImageWrap(imgSrc, fileName) {
     const imgWrap = document.createElement('div');
     imgWrap.className = 'wa-msg ai wa-chart-img-wrap';
     const img = document.createElement('img');
     img.className = 'wa-chart-img';
     img.src = imgSrc;
     img.alt = fileName || 'chart.png';
     img.draggable = false;
     // Start background upload immediately — serverUrl ready for insert button.
     _preUploadChartImage(imgSrc, img);
     imgWrap.appendChild(img);
     const bar = document.createElement('div');
     bar.className = 'wa-chart-img-bar';
     const openBtn = document.createElement('button');
     openBtn.className = 'wa-action-btn secondary';
     openBtn.textContent = '查看';
     openBtn.title = '在新标签页打开（可直接右键复制）';
     openBtn.addEventListener('click', () => {
        // Prefer pre-uploaded server URL (avoids atob/blob on large base64)
        const src = img.dataset.serverUrl || imgSrc;
        if (src.startsWith('data:')) {
           try {
              const [head, b64] = src.split(',');
              const mimeType = head.split(':')[1].split(';')[0];
              const binary = atob(b64);
              const arr = new Uint8Array(binary.length);
              for (let i = 0; i < binary.length; i++) arr[i] = binary.charCodeAt(i);
              const blob = new Blob([arr], { type: mimeType });
              const blobUrl = URL.createObjectURL(blob);
              window.open(blobUrl, '_blank');
              setTimeout(() => URL.revokeObjectURL(blobUrl), 60000);
           } catch (_) { window.open(src, '_blank'); }
        } else {
           window.open(src, '_blank');
        }
     });
     const dlBtn = document.createElement('button');
     dlBtn.className = 'wa-action-btn';
     dlBtn.innerHTML = _DOWNLOAD_SVG + ' 存入工作区';
     dlBtn.title = '保存到工作区 images/ 文件夹';
     dlBtn.addEventListener('click', () => {
        const serverUrl = img.dataset.serverUrl;
        if (!serverUrl) {
          // Not yet uploaded — trigger upload first, then save
          dlBtn.textContent = '⏳ 上传中…';
          dlBtn.disabled = true;
          fetch('/api/v1/workspace/upload_image', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ data: imgSrc }),
          })
            .then(r => r.ok ? r.json() : Promise.reject(r.status))
            .then(res => {
              if (res && res.url) img.dataset.serverUrl = res.url;
              return fetch('/api/v1/workspace/save_to_workspace', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ type: 'image', src_url: res.url, filename: fileName || 'chart.png' }),
              });
            })
            .then(r => r.ok ? r.json() : Promise.reject(r.status))
            .then(res => {
              showToast(`已存入工作区: ${res.ws_path}`, 'success');
              _renderMyWorkspace();
            })
            .catch(() => showToast('保存失败，请重试', 'error'))
            .finally(() => { dlBtn.innerHTML = _DOWNLOAD_SVG + ' 存入工作区'; dlBtn.disabled = false; });
          return;
        }
        dlBtn.textContent = '⏳ 保存中…';
        dlBtn.disabled = true;
        fetch('/api/v1/workspace/save_to_workspace', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ type: 'image', src_url: serverUrl, filename: fileName || 'chart.png' }),
        })
          .then(r => r.ok ? r.json() : Promise.reject(r.status))
          .then(res => {
            showToast(`已存入工作区: ${res.ws_path}`, 'success');
            _renderMyWorkspace();
          })
          .catch(() => showToast('保存失败，请重试', 'error'))
          .finally(() => { dlBtn.innerHTML = _DOWNLOAD_SVG + ' 存入工作区'; dlBtn.disabled = false; });
     });
     const insertBtn = document.createElement('button');
     insertBtn.className = 'wa-action-btn';
     insertBtn.textContent = '插入文档';
     insertBtn.title = '一键插入到当前打开的文档中';
     insertBtn.addEventListener('click', () => {
        if (!state.activeEditor) {
          showToast('请先打开一个文档', 'warning');
          return;
        }
        const serverUrl = img.dataset.serverUrl;
        if (serverUrl) {
          state.activeEditor.applyToolCall({ type: 'insert_image', src: serverUrl, alt: fileName || 'chart.png' });
          showToast('图表已插入文档', 'success');
        } else {
          // Server URL not ready yet — upload now, then insert
          insertBtn.textContent = '⏳ 上传中…';
          insertBtn.disabled = true;
          fetch('/api/v1/workspace/upload_image', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ data: imgSrc }),
          })
            .then(r => r.ok ? r.json() : Promise.reject(r.status))
            .then(res => {
              const url = (res && res.url) ? res.url : imgSrc;
              if (res && res.url) img.dataset.serverUrl = res.url;
              state.activeEditor.applyToolCall({ type: 'insert_image', src: url, alt: fileName || 'chart.png' });
              showToast('图表已插入文档', 'success');
            })
            .catch(() => {
              showToast('图片上传失败，请重试', 'error');
            })
            .finally(() => {
              insertBtn.textContent = '插入文档';
              insertBtn.disabled = false;
            });
        }
     });
     bar.appendChild(openBtn);
     bar.appendChild(dlBtn);
     bar.appendChild(insertBtn);
     imgWrap.appendChild(bar);
     return imgWrap;
  }

  function _makeAIImgDraggable(img, imgSrc) {
     // Drag insertion removed — use the 「插入文档」 button instead.
     _preUploadChartImage(imgSrc, img);
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
        errDiv.textContent = `执行错误：${result.error}`;
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
        okDiv.textContent = '代码执行完成，但未生成图片文件。请确保代码中有 plt.savefig("chart.png") 或 ggsave("chart.png")。';
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
    const ctrl = new AbortController();
    state._streamAbortCtrl = ctrl;
    state.isLoading = true;
    _setStreamBtn(true);
    try {
      const resp = await fetch('/api/editor/ai/chart', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        signal: ctrl.signal,
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
                codeEl.innerHTML = `<details><summary>${_DOC_SVG} 生成的代码</summary><pre style="white-space:pre-wrap;font-size:12px">${evt.text.replace(/</g,'&lt;').replace(/>/g,'&gt;')}</pre></details>`;
                msgs.appendChild(codeEl);
                msgs.scrollTop = msgs.scrollHeight;
                break;
              }
              case 'image': {
                const _ext = (evt.name || 'chart.png').split('.').pop().toLowerCase();
                const _mime = _ext === 'svg' ? 'image/svg+xml' : `image/${_ext}`;
                const _imgSrc = `data:${_mime};base64,${evt.data}`;
                msgs.appendChild(_makeWAChartImageWrap(_imgSrc, evt.name || 'chart.png'));
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
                errEl.textContent = evt.text || evt.message || '图表生成失败';
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
      const msgs = $('wa-ai-messages');
      const last = msgs.lastElementChild;
      if (last && last.classList.contains('streaming')) last.classList.remove('streaming');
      if (err.name === 'AbortError') {
        if (last && !last.textContent.trim()) {
          last.textContent = '[已取消]';
        } else {
          const cancelEl = document.createElement('div');
          cancelEl.className = 'wa-msg ai';
          cancelEl.textContent = '[已取消]';
          msgs.appendChild(cancelEl);
        }
      } else {
        console.error('[WorkspaceAI] Chart exec error:', err);
        const errEl = document.createElement('div');
        errEl.className = 'wa-msg ai';
        errEl.textContent = `网络错误：${err.message}`;
        msgs.appendChild(errEl);
      }
      msgs.scrollTop = msgs.scrollHeight;
    } finally {
      state.isLoading = false;
      state._streamAbortCtrl = null;
      _setStreamBtn(false);
    }
  }

  // ── AI init ───────────────────────────────────────────────────────────────
  function initSocket() {
    const storedLockedModel = localStorage.getItem('wa_locked_model');
    if (storedLockedModel !== state.lockedModel) {
      localStorage.setItem('wa_locked_model', state.lockedModel);
      _clearActiveRoute();
      _syncEditorModelPreference(state.lockedModel, state.lockedModel);
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
    _syncModelStatusUi();
    _refreshModelCatalog();
  }

  // ── Exports to Window ──
  
  window.WA.handleInputKeydown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
       e.preventDefault();
       WA.sendMessage();
    }
  };

  window.WA.quickAction = (text) => {
      // Route the built-in editing actions through the same editor SSE endpoints
      // used by the canonical file assistant, instead of the legacy JSON adapter.
      const ACTION_KEYWORDS = ['润色', '翻译', '总结', '续写', '改写', '解释', '检查', '可视化'];
      const matchedAction = ACTION_KEYWORDS.find(a => (text || '').includes(a));

      // Capture current selection
      let sel = state.fileType === 'docx' ? _getDocxSelectionTextForAI() : lastSelectionText;
      if (!sel && state.fileType === 'xlsx' && state.activeEditor) {
        const rangeText = state.activeEditor.getContent();
        if (rangeText && !rangeText.includes('未选中区域')) sel = rangeText;
      }

      if (matchedAction) {
        lastSelectionText = sel;
        WA.sendQuickAction(matchedAction);
        return;
      }

      // Fallback: pin selection and send through chat stream
      if (sel) {
        _saveEditorRange();
        _applyPinnedHighlight();
        _pinSelectionChip(sel);
      }
      $('wa-user-input').value = text;
      WA.sendMessage();
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
     // Also keep the hoverbar swatch in sync
     const hbSw = $('wa-hb-color-swatch');
     if (hbSw) hbSw.style.background = val;
     if (state.activeEditor && state.activeEditor.applyFormat)
       state.activeEditor.applyFormat('color', val);
  };

  // ── In-page colour picker ── keeps contentEditable selection highlight alive
  // because NO OS dialog is ever opened (all swatches use onmousedown=preventDefault).
  const _CP_COLORS = [
    '#000000','#1f1f1f','#595959','#808080','#a6a6a6','#d9d9d9','#f2f2f2','#ffffff',
    '#c00000','#ff0000','#ff4b4b','#ff6d00','#ff9900','#ffc000','#ffff00','#fff2cc',
    '#375623','#548235','#70ad47','#92d050','#00b050','#008080','#0070c0','#bdd7ee',
    '#1f3864','#2e75b6','#4472c4','#9dc3e6','#7030a0','#984ea3','#c9a0dc','#d9e1f2',
    '#c55a11','#843c0c','#7f1d1d','#002060','#00bcd4','#009688','#4caf50','#607d8b',
  ];

  window.WA.pptxColorPicker = (type, triggerEl) => {
    const palette = $('wa-pptx-cp');
    const grid    = $('wa-pptx-cp-grid');
    if (!palette || !grid) return;
    // Toggle off if same panel already open
    if (palette.style.display !== 'none' && palette.dataset.cpType === type) {
      palette.style.display = 'none'; return;
    }
    palette.dataset.cpType = type;
    // Build swatches – each has mousedown:preventDefault so focus never leaves the text span
    grid.innerHTML = _CP_COLORS.map(c =>
      `<div title="${c}" style="width:18px;height:18px;border-radius:3px;background:${c};cursor:pointer;border:1px solid rgba(255,255,255,.12);box-sizing:border-box"` +
      ` onmousedown="event.preventDefault()" onclick="WA._pptxPickColor('${c}')"></div>`
    ).join('');
    // Position below trigger, clamped to viewport
    if (triggerEl) {
      const r  = triggerEl.getBoundingClientRect();
      const pw = 8 * 18 + 7 * 3 + 16;
      const left = Math.min(r.left, window.innerWidth - pw - 8);
      palette.style.left = Math.max(4, left) + 'px';
      palette.style.top  = (r.bottom + 4) + 'px';
    }
    palette.style.display = 'block';
  };

  window.WA._pptxPickColor = (color, keepOpen) => {
    const palette = $('wa-pptx-cp');
    const type    = palette ? palette.dataset.cpType : '';
    if      (type === 'font')      window.WA.pptxFontColor(color);
    else if (type === 'fill')      window.WA.pptxShapeFill(color);
    else if (type === 'border')    window.WA.pptxShapeBorder(color);
    else if (type === 'highlight') window.WA.pptxHighlightColor(color);
    else if (type === 'bg')        window.WA.pptxBgColor(color);
    const hexEl = $('wa-pptx-cp-hex');
    if (hexEl) hexEl.textContent = color;
    const ci = $('wa-pptx-cp-custom');
    if (ci && /^#[0-9a-f]{6}$/i.test(color)) ci.value = color;
    if (!keepOpen && palette) palette.style.display = 'none';
  };

  // Close palette when clicking anywhere outside it or its trigger buttons
  document.addEventListener('mousedown', (e) => {
    const p = $('wa-pptx-cp');
    if (!p || p.style.display === 'none') return;
    if (p.contains(e.target)) return;
    if (['wa-pptx-color-trigger','wa-pptx-fill-trigger','wa-pptx-border-trigger','wa-hb-color-trigger','wa-pptx-bg-trigger']
        .some(id => e.target.closest && e.target.closest('#' + id))) return;
    p.style.display = 'none';
  }, true);

  // Hide hover bar when clicking outside it (but not when clicking its own buttons)
  document.addEventListener('mousedown', (e) => {
    const hb = $('wa-pptx-hoverbar');
    if (!hb || hb.style.display === 'none') return;
    if (hb.contains(e.target)) return;
    const cp = $('wa-pptx-cp');
    if (cp && cp.contains(e.target)) return; // colour palette – keep bar open
    hb.style.display = 'none';
  }, true);

  // Send selected PPTX text to AI via the hover bar action buttons
  window.WA.pptxHoverAI = (action) => {
    const hb = $('wa-pptx-hoverbar');
    if (hb) hb.style.display = 'none';
    const selText = window.getSelection ? window.getSelection().toString().trim() : '';
    if (selText) lastSelectionText = selText;
    if (!lastSelectionText) { showToast('请先选中文字', 'info'); return; }
    WA.sendQuickAction(action);
  };

  // ── DOCX floating format hoverbar + AI quick-action bar ─────────────────
  //
  // Format bar (#wa-docx-hoverbar) appears BELOW the selection, left-aligned.
  // AI bar (#wa-pdf-tooltip) appears ABOVE the selection, left-aligned.
  // Both use position:fixed attached to document.body.

  let _docxHbEl = null;         // cached ref to #wa-docx-hoverbar
  let _docxCpEl = null;         // cached ref to #wa-docx-cp
  let _docxMouseIsDown = false; // true while primary button held — suppresses mid-drag show
  let _docxMouseUpY = 0;       // viewport Y where user released mouse
  let _docxSelTimer   = null;  // dedupe timer for _kotoDocxSelectionChanged

  // Safety: catch mouseup outside browser window
  window.addEventListener('mouseup', (ev) => { if (ev.button === 0) _docxMouseIsDown = false; }, true);

  // ── Init: find elements and move to body ──────────────────────────
  function _ensureDocxHoverBar() {
    if (_docxHbEl && document.body.contains(_docxHbEl)) return _docxHbEl;
    _docxHbEl = document.getElementById('wa-docx-hoverbar');
    _docxCpEl = document.getElementById('wa-docx-cp');
    if (_docxHbEl && _docxHbEl.parentElement !== document.body) document.body.appendChild(_docxHbEl);
    if (_docxCpEl && _docxCpEl.parentElement !== document.body) document.body.appendChild(_docxCpEl);
    if (_docxCpEl) {
      const grid = document.getElementById('wa-docx-cp-grid');
      if (grid && !grid.hasChildNodes()) {
        const palette = [
          '#000000','#434343','#666666','#999999','#b7b7b7','#cccccc','#d9d9d9','#ffffff',
          '#980000','#ff0000','#ff9900','#ffff00','#00ff00','#00ffff','#4a86e8','#0000ff',
          '#9900ff','#ff00ff','#e6b8af','#f4cccc','#fce5cd','#fff2cc','#d9ead3','#d0e0e3',
          '#c9daf8','#cfe2f3','#d9d2e9','#ead1dc','#dd7e6b','#ea9999','#f9cb9c','#ffe599',
          '#b6d7a8','#a2c4c9','#a4c2f4','#9fc5e8','#b4a7d6','#d5a6bd',
        ];
        palette.forEach(c => {
          const swatch = document.createElement('div');
          swatch.style.cssText = `width:20px;height:20px;border-radius:3px;cursor:pointer;background:${c};border:1px solid var(--border);`;
          swatch.title = c;
          swatch.onclick = () => WA._docxPickColor(c, false);
          grid.appendChild(swatch);
        });
      }
    }
    return _docxHbEl;
  }

  // ── Get selection bounds ────────────────────────────────────────
  function _getDocxNativeSelectionBounds(scopeEl, fallbackLeft) {
    if (!scopeEl || !window.getSelection) return null;

    const sel = window.getSelection();
    if (!sel || sel.rangeCount < 1 || sel.isCollapsed) return null;

    const range = sel.getRangeAt(0);
    let common = range.commonAncestorContainer;
    if (common && common.nodeType === Node.TEXT_NODE) common = common.parentElement;
    if (!common || !scopeEl.contains(common)) return null;

    const rects = Array.from(range.getClientRects ? range.getClientRects() : [])
      .filter(rect => rect && (rect.width > 0 || rect.height > 0));

    let top = Infinity;
    let bottom = -Infinity;
    let anchorRect = null;
    rects.forEach((rect) => {
      if (rect.top < top) top = rect.top;
      if (rect.bottom > bottom || !anchorRect) {
        bottom = rect.bottom;
        anchorRect = rect;
      }
    });

    let rect = range.getBoundingClientRect();
    if ((!rect || (!rect.width && !rect.height)) && rects.length) {
      rect = rects[rects.length - 1];
    }
    if (!rect) return null;

    if (!anchorRect) anchorRect = rect;
    if (top === Infinity) top = rect.top;
    if (bottom <= top) bottom = rect.bottom;
    if (bottom <= top) return null;

    return {
      top,
      bottom,
      left: Math.min(anchorRect.left, fallbackLeft),
      centerX: anchorRect.left + (anchorRect.width / 2),
    };
  }

  function _getDocxSelBounds(ed) {
    const sel = ed.state.selection;
    if (sel.from >= sel.to) return null;

    const pm = ed.view.dom;
    const pmR = pm.getBoundingClientRect();

    const nativeBounds = _getDocxNativeSelectionBounds(pm, pmR.left);
    if (nativeBounds) return nativeBounds;

    // Use coordsAtPos for precise char-level top/bottom
    // sel.to can point to start of NEXT paragraph; use sel.to-1 for last selected char
    try {
      const startC = ed.view.coordsAtPos(sel.from);
      const endC   = ed.view.coordsAtPos(Math.max(sel.from, sel.to - 1));
      if (startC && endC) {
        const top    = Math.min(startC.top, endC.top);
        const bottom = Math.max(startC.bottom, endC.bottom);
        const left   = Math.min(startC.left, endC.left, pmR.left);
        if (bottom > top) {
          return { top, bottom, left, centerX: pmR.left + pmR.width / 2 };
        }
      }
    } catch (_e) {}

    // Fallback: block nodes
    let top = Infinity, bottom = -Infinity;
    ed.state.doc.nodesBetween(sel.from, sel.to, (node, pos) => {
      if (!node.isBlock || node.type.name === 'doc') return;
      const dom = ed.view.nodeDOM(pos);
      if (!dom || dom.nodeType !== Node.ELEMENT_NODE) return;
      const r = dom.getBoundingClientRect();
      if (r.height <= 0) return;
      if (r.top < top) top = r.top;
      if (r.bottom > bottom) bottom = r.bottom;
    });
    if (top === Infinity || bottom <= top) return null;
    return { top, bottom, left: pmR.left, centerX: pmR.left + pmR.width / 2 };
  }

  function _getActiveDocxHdrFtrOverlay() {
    const root = document.getElementById('wa-docx-editor');
    const marked = root && root.querySelector('.koto-hdrftr-overlay.is-active');
    if (marked) return marked;

    const active = document.activeElement;
    if (active && typeof active.closest === 'function') {
      const overlay = active.closest('.koto-hdrftr-overlay');
      if (overlay) return overlay;
    }

    const sel = window.getSelection ? window.getSelection() : null;
    let node = sel ? (sel.focusNode || sel.anchorNode) : null;
    if (node && node.nodeType === Node.TEXT_NODE) node = node.parentElement;
    return node && typeof node.closest === 'function'
      ? node.closest('.koto-hdrftr-overlay')
      : null;
  }

  function _getDocxHdrFtrSelectionInfo() {
    const overlay = _getActiveDocxHdrFtrOverlay();
    if (!overlay || !window.getSelection) return null;
    const sel = window.getSelection();
    if (!sel || sel.rangeCount < 1 || sel.isCollapsed) return null;

    const range = sel.getRangeAt(0);
    let common = range.commonAncestorContainer;
    if (common && common.nodeType === Node.TEXT_NODE) common = common.parentElement;
    if (!common || !overlay.contains(common)) return null;

    const text = sel.toString().trim();
    if (!text) return null;

    let rect = range.getBoundingClientRect();
    if ((!rect || (!rect.width && !rect.height)) && range.getClientRects().length) {
      rect = range.getClientRects()[0];
    }
    if (!rect) return null;

    return {
      overlay,
      text,
      bounds: {
        top: rect.top,
        bottom: rect.bottom,
        left: rect.left,
        centerX: rect.left + (rect.width / 2),
      },
    };
  }

  function _getDocxRibbonToolbar() {
    return document.getElementById('koto-tt-toolbar');
  }

  function _normalizeDocxFontFamilyToken(value) {
    return String(value || '')
      .trim()
      .replace(/^['"]+|['"]+$/g, '')
      .replace(/\s+/g, ' ')
      .toLowerCase();
  }

  const _DOCX_FONT_FAMILIES = [
    { value: 'SimSun', label: '宋体', eastAsian: true, aliases: ['宋体', 'Songti', 'STSong'] },
    { value: 'SimHei', label: '黑体', eastAsian: true, aliases: ['黑体', 'Heiti'] },
    { value: 'Microsoft YaHei', label: '微软雅黑', eastAsian: true, aliases: ['微软雅黑', 'YaHei'] },
    { value: 'KaiTi', label: '楷体', eastAsian: true, aliases: ['楷体', 'KaiTi_GB2312', '楷体_GB2312'] },
    { value: 'FangSong', label: '仿宋', eastAsian: true, aliases: ['仿宋', 'FangSong_GB2312', '仿宋_GB2312'] },
    { value: 'DengXian', label: '等线', eastAsian: true, aliases: ['等线'] },
    { value: 'STZhongsong', label: '华文中宋', eastAsian: true, aliases: ['华文中宋'] },
    { value: 'STKaiti', label: '华文楷体', eastAsian: true, aliases: ['华文楷体'] },
    { value: 'Arial', label: 'Arial', aliases: ['Arial'] },
    { value: 'Calibri', label: 'Calibri', aliases: ['Calibri'] },
    { value: 'Times New Roman', label: 'Times New Roman', aliases: ['Times New Roman'] },
    { value: 'Georgia', label: 'Georgia', aliases: ['Georgia'] },
    { value: 'Verdana', label: 'Verdana', aliases: ['Verdana'] },
  ];

  const _DOCX_FONT_FAMILY_LOOKUP = new Map();
  for (const font of _DOCX_FONT_FAMILIES) {
    for (const alias of [font.value, font.label, ...(font.aliases || [])]) {
      const token = _normalizeDocxFontFamilyToken(alias);
      if (token) _DOCX_FONT_FAMILY_LOOKUP.set(token, font);
    }
  }

  function _splitDocxFontFamilyCandidates(value) {
    return String(value || '')
      .split(',')
      .map(part => part.trim())
      .filter(Boolean);
  }

  function _resolveDocxFontFamily(value, { preferEastAsian = true } = {}) {
    const raw = String(value || '').trim();
    if (!raw) return '';

    const candidates = _splitDocxFontFamilyCandidates(raw);
    const matches = candidates
      .map(candidate => _DOCX_FONT_FAMILY_LOOKUP.get(_normalizeDocxFontFamilyToken(candidate)))
      .filter(Boolean);

    if (matches.length) {
      const preferred = preferEastAsian ? matches.find(font => font.eastAsian) : null;
      return (preferred || matches[0]).value;
    }

    const normalizedRaw = _normalizeDocxFontFamilyToken(raw);
    const exact = _DOCX_FONT_FAMILY_LOOKUP.get(normalizedRaw);
    if (exact) return exact.value;

    const partial = _DOCX_FONT_FAMILIES.find(font => {
      return [font.value, font.label, ...(font.aliases || [])].some(alias => {
        const token = _normalizeDocxFontFamilyToken(alias);
        return token && normalizedRaw.includes(token);
      });
    });
    if (partial) return partial.value;

    return candidates[0].replace(/^['"]+|['"]+$/g, '');
  }

  function _getDocxFontDisplayName(value) {
    const resolved = _resolveDocxFontFamily(value);
    const font = _DOCX_FONT_FAMILIES.find(item => item.value === resolved);
    return font ? font.label : String(value || '').trim();
  }

  function _getDocxFontFamilyOptionValue(rawValue, options) {
    const resolved = _resolveDocxFontFamily(rawValue);
    if (!resolved) return '';

    const normalizedResolved = _normalizeDocxFontFamilyToken(resolved);
    const exact = [...options].find(option => {
      return [_normalizeDocxFontFamilyToken(option.value), _normalizeDocxFontFamilyToken(option.textContent)]
        .includes(normalizedResolved);
    });
    if (exact) return exact.value;

    const aliasMatch = [...options].find(option => {
      const optionValue = option.value || option.textContent || '';
      return _normalizeDocxFontFamilyToken(_resolveDocxFontFamily(optionValue)) === normalizedResolved;
    });
    return aliasMatch ? aliasMatch.value : '';
  }

  function _extractDocxStyleValue(styleText, propertyName) {
    const raw = String(styleText || '');
    if (!raw) return '';
    const match = raw.match(new RegExp(`${propertyName}\\s*:\\s*([^;]+)`, 'i'));
    return match ? match[1].trim() : '';
  }

  function _getDocxBlockTextStyleValue(ed, attrName) {
    const paragraphAttrs = ed.getAttributes('paragraph') || {};
    if (paragraphAttrs[attrName]) return paragraphAttrs[attrName];

    const headingAttrs = ed.getAttributes('heading') || {};
    if (headingAttrs[attrName]) return headingAttrs[attrName];

    const cssProperty = attrName === 'fontFamily'
      ? 'font-family'
      : (attrName === 'fontSize' ? 'font-size' : '');
    if (cssProperty && headingAttrs.style) {
      return _extractDocxStyleValue(headingAttrs.style, cssProperty);
    }
    return '';
  }

  function _dispatchDocxRibbonClick(cmd) {
    const ribbon = _getDocxRibbonToolbar();
    const button = ribbon && ribbon.querySelector(`[data-cmd="${cmd}"]`);
    if (!button) return false;
    button.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
    return true;
  }

  function _dispatchDocxRibbonSelect(cmd, value) {
    const ribbon = _getDocxRibbonToolbar();
    const select = ribbon && ribbon.querySelector(`[data-cmd="${cmd}"]`);
    if (!select) return false;
    const nextValue = cmd === 'setFontFamily' ? _resolveDocxFontFamily(value) : (value || '');
    if (cmd === 'setFontFamily' && nextValue && ![...select.options].some(option => option.value === nextValue)) {
      return false;
    }
    select.value = nextValue || '';
    select.dispatchEvent(new Event('change', { bubbles: true }));
    return true;
  }

  function _syncDocxHoverBarFromRibbon() {
    const ribbon = _getDocxRibbonToolbar();
    if (!ribbon) return false;

    const buttonMap = {
      'wa-dh-bold': 'toggleBold',
      'wa-dh-italic': 'toggleItalic',
      'wa-dh-underline': 'toggleUnderline',
      'wa-dh-strike': 'toggleStrike',
      'wa-dh-align-left': 'setTextAlignLeft',
      'wa-dh-align-center': 'setTextAlignCenter',
      'wa-dh-align-right': 'setTextAlignRight',
    };
    Object.entries(buttonMap).forEach(([hoverId, ribbonCmd]) => {
      const hoverBtn = $(hoverId);
      const ribbonBtn = ribbon.querySelector(`[data-cmd="${ribbonCmd}"]`);
      if (hoverBtn && ribbonBtn) {
        hoverBtn.classList.toggle('active', ribbonBtn.classList.contains('is-active'));
      }
    });

    const fontNameSrc = ribbon.querySelector('[data-cmd="setFontFamily"]');
    const fontNameDst = $('wa-dh-fontname');
    if (fontNameSrc && fontNameDst) {
      const fontNameValue = fontNameSrc.value || '';
      if (fontNameDst.tagName === 'SELECT') {
        fontNameDst.value = _getDocxFontFamilyOptionValue(fontNameValue, fontNameDst.options);
      } else {
        fontNameDst.value = _getDocxFontDisplayName(fontNameValue);
      }
    }

    const fontSizeSrc = ribbon.querySelector('[data-cmd="setFontSize"]');
    const fontSizeDst = $('wa-dh-fontsize');
    if (fontSizeSrc && fontSizeDst) {
      const raw = fontSizeSrc.value || '';
      const numeric = raw ? String(parseFloat(raw)) : '';
      const match = [...fontSizeDst.options].find(o => parseFloat(o.value) === parseFloat(numeric));
      fontSizeDst.value = match ? match.value : (numeric || '');
    }

    const colorSrc = ribbon.querySelector('#tt-color-swatch');
    const colorDst = $('wa-dh-color-swatch');
    if (colorSrc && colorDst) colorDst.style.background = colorSrc.style.background || '#000000';

    const bgSrc = ribbon.querySelector('#tt-bg-swatch');
    const bgDst = $('wa-dh-bg-swatch');
    if (bgSrc && bgDst) bgDst.style.background = bgSrc.style.background || 'transparent';

    return true;
  }

  // ── Show BOTH toolbars ────────────────────────────────────────────
  function _showDocxHoverBar() {
    if (state.fileType !== 'docx') return;
    const hb = _ensureDocxHoverBar();
    if (!hb) return;

    const ed = state.activeEditor && state.activeEditor.editor;
    if (!ed) return;
    const overlaySelection = _getDocxHdrFtrSelectionInfo();
    let bounds = null;
    let selText = '';
    if (overlaySelection) {
      bounds = overlaySelection.bounds;
      selText = overlaySelection.text;
    } else {
      const sel = ed.state.selection;
      if (sel.from >= sel.to) { _resetDocxSelection(); return; }
      bounds = _getDocxSelBounds(ed);
      if (!bounds) { _hideDocxHoverBar(); return; }
      selText = ed.state.doc.textBetween(sel.from, sel.to, ' ').trim();
    }
    if (!selText) { _resetDocxSelection(); return; }

    if (window._docxHoverForceHiddenText === selText) {
      _hideDocxHoverBar();
      return;
    }

    // ── Measure format bar ──────────────────────────────────────────
    hb.style.visibility = 'hidden';
    hb.style.display = 'flex';
    const hbW = hb.offsetWidth  || 420;
    const hbH = hb.offsetHeight || 34;
    hb.style.visibility = '';

    // ── Ribbon height (don't overlap the top toolbar) ───────────────
    const ribbonEl = document.getElementById('koto-tt-toolbar')
                  || document.getElementById('wa-editor-toolbar');
    let ribbonBottom = 80;
    if (ribbonEl) {
      const rr = ribbonEl.getBoundingClientRect();
      if (rr.height > 0) ribbonBottom = rr.bottom;
    }

    const vh = window.innerHeight;
    const vw = window.innerWidth;

    // Prefer the live selection bounds; the mouseup snapshot only bridges transient DOM lag.
    const anchorY = bounds.bottom > 0
      ? bounds.bottom
      : (_docxNativeSelBottom > 0 ? _docxNativeSelBottom : _docxMouseUpY);

    const STACK_GAP = 8;
    const SELECTION_GAP = 2;
    const STACK_RAISE = 85;
    const EDGE_GAP = 6;
    const minTop = Math.max(EDGE_GAP, ribbonBottom + EDGE_GAP);

    // ── Both bars stacked as one group so spacing stays stable ──────
    const tt = $('wa-pdf-tooltip');
    let ttH = 0;
    let ttW = 0;
    if (tt) {
      if (tt.parentElement !== document.body) document.body.appendChild(tt);
      tt.style.visibility = 'hidden';
      tt.style.display = 'flex';
      ttW = tt.offsetWidth  || 220;
      ttH = tt.offsetHeight || 36;
      tt.style.visibility = '';
    }

    const stackHeight = hbH + (tt ? ttH + STACK_GAP : 0);
    const maxStackTop = Math.max(minTop, vh - stackHeight - EDGE_GAP);
    let stackTop = anchorY + SELECTION_GAP - STACK_RAISE;
    if (stackTop + stackHeight > vh - EDGE_GAP) {
      stackTop = bounds.top - stackHeight - SELECTION_GAP;
    }
    stackTop = Math.max(minTop, Math.min(stackTop, maxStackTop));

    if (tt) {
      const aiTop = stackTop;
      const aiLeft = Math.max(8, Math.min(bounds.left, vw - ttW - 8));
      tt.style.left = aiLeft + 'px';
      tt.style.top  = aiTop  + 'px';
    }

    // Format bar: keep a visible gap under the AI bar.
    let fmtTop = stackTop + (tt ? ttH + STACK_GAP : 0);
    let fmtLeft = bounds.left;
    fmtTop = Math.max(minTop, Math.min(fmtTop, vh - hbH - EDGE_GAP));
    fmtLeft = Math.max(4, Math.min(fmtLeft, vw - hbW - 4));

    hb.style.left = fmtLeft + 'px';
    hb.style.top  = fmtTop  + 'px';

    // ── Sync button states ──────────────────────────────────────────
    _syncDocxHoverBar();

    // ── Update selection text & context ──────────────────────────────
    if (selText) {
      lastSelectionText = selText;
      const countEl = $('wa-tooltip-count');
      if (countEl) countEl.textContent = `${selText.replace(/\s/g, '').length}字`;
      _updateContextBar({ selection: selText });
    }
  }

  // ── TipTap callback ───────────────────────────────────────────────
  window._kotoDocxSelectionChanged = () => {
    if (state.fileType !== 'docx') return;
    clearTimeout(_docxSelTimer);
    _docxSelTimer = setTimeout(() => {
      const ed = state.activeEditor && state.activeEditor.editor;
      if (!ed) return;
      const overlaySelection = _getDocxHdrFtrSelectionInfo();
      const hasPmSelection = ed.state.selection.from < ed.state.selection.to;
      if (!overlaySelection && !hasPmSelection) {
        _resetDocxSelection();
      } else if (!_docxMouseIsDown) {
        _showDocxHoverBar();
      }
    }, 50);
  };

  // ── Hide / Reset ──────────────────────────────────────────────────
  function _hideDocxHoverBar() {
    if (_docxHbEl) _docxHbEl.style.display = 'none';
    if (_docxCpEl) _docxCpEl.style.display = 'none';
  }

  function _resetDocxSelection() {
    _docxNativeSelBottom = 0;
    _hideDocxHoverBar();
    const _ttReset = $('wa-pdf-tooltip');
    if (_ttReset) _ttReset.style.display = 'none';
    lastSelectionText = '';
    _updateContextBar();
    if (!state._aiFileContext || !state._aiFileContext.length) {
      _updateSubjectBar(state.fileName, state.fileType);
    }
  }

  // ── Sync format button states from TipTap ─────────────────────────
  function _syncDocxHoverBar() {
    if (_syncDocxHoverBarFromRibbon()) return;

    const ed = state.activeEditor && state.activeEditor.editor;
    if (!ed) return;
    const bold      = ed.isActive('bold');
    const italic    = ed.isActive('italic');
    const underline = ed.isActive('underline');
    const strike    = ed.isActive('strike');
    const attrs     = ed.getAttributes('textStyle') || {};
    const fontName  = attrs.fontFamily || _getDocxBlockTextStyleValue(ed, 'fontFamily') || '';
    const fontSize  = attrs.fontSize  || _getDocxBlockTextStyleValue(ed, 'fontSize') || '';
    const color     = (ed.getAttributes('textStyle') || {}).color || '#000000';

    const dhBold = $('wa-dh-bold');
    const dhItal = $('wa-dh-italic');
    const dhUnd  = $('wa-dh-underline');
    const dhStr  = $('wa-dh-strike');
    if (dhBold) dhBold.classList.toggle('active', bold);
    if (dhItal) dhItal.classList.toggle('active', italic);
    if (dhUnd)  dhUnd.classList.toggle('active',  underline);
    if (dhStr)  dhStr.classList.toggle('active',  strike);

    const dhSuper = $('wa-dh-super');
    const dhSub   = $('wa-dh-sub');
    if (dhSuper) dhSuper.classList.toggle('active', ed.isActive('superscript'));
    if (dhSub)   dhSub.classList.toggle('active',   ed.isActive('subscript'));

    const alignMap = {
      'wa-dh-align-left':    'left',
      'wa-dh-align-center':  'center',
      'wa-dh-align-right':   'right',
      'wa-dh-align-justify': 'justify',
    };
    Object.entries(alignMap).forEach(([elId, val]) => {
      const el = $(elId);
      if (el) el.classList.toggle('active', ed.isActive({ textAlign: val }));
    });

    const fnEl = $('wa-dh-fontname');
    if (fnEl) {
      if (fnEl.tagName === 'SELECT') {
        const optionValue = _getDocxFontFamilyOptionValue(fontName, fnEl.options);
        if (optionValue) {
          fnEl.value = optionValue;
        } else if (fontName) {
          const displayName = _getDocxFontDisplayName(fontName) || fontName;
          const existing = [...fnEl.options].find(o => o.value === fontName);
          if (!existing) {
            const o = document.createElement('option');
            o.value = fontName; o.textContent = displayName; o.dataset.temp = '1';
            fnEl.appendChild(o);
          }
          fnEl.value = fontName;
        } else {
          fnEl.value = '';
        }
        [...fnEl.options].filter(o => o.dataset.temp && o.value !== fnEl.value)
          .forEach(o => o.remove());
      } else {
        fnEl.value = _getDocxFontDisplayName(fontName) || '';
      }
    }

    const fsEl = $('wa-dh-fontsize');
    if (fsEl && fontSize) {
      const numSize = parseFloat(fontSize);
      if (!isNaN(numSize)) {
        const opt = [...fsEl.options].find(o => parseFloat(o.value) === numSize);
        if (opt) fsEl.value = opt.value;
        else { fsEl.value = ''; }
      }
    }

    const sw = $('wa-dh-color-swatch');
    if (sw && color) sw.style.background = color;
  }

  // Toggle formatting from hoverbar buttons
  window.WA.docxHoverFmt = (prop) => {
    const ribbonCmdMap = {
      bold: 'toggleBold',
      italic: 'toggleItalic',
      underline: 'toggleUnderline',
      strike: 'toggleStrike',
      justifyLeft: 'setTextAlignLeft',
      justifyCenter: 'setTextAlignCenter',
      justifyRight: 'setTextAlignRight',
      justify: 'setTextAlignJustify',
      clearMarks: 'unsetAllMarks',
    };
    if (ribbonCmdMap[prop] && _dispatchDocxRibbonClick(ribbonCmdMap[prop])) {
      _syncDocxHoverBar();
      return;
    }

    const ed = state.activeEditor && state.activeEditor.editor;
    if (!ed) return;
    switch (prop) {
      case 'bold':          ed.chain().focus().toggleBold().run(); break;
      case 'italic':        ed.chain().focus().toggleItalic().run(); break;
      case 'underline':     ed.chain().focus().toggleUnderline().run(); break;
      case 'strike':        ed.chain().focus().toggleStrike().run(); break;
      case 'superscript':   ed.chain().focus().toggleSuperscript().run(); break;
      case 'subscript':     ed.chain().focus().toggleSubscript().run(); break;
      case 'justifyLeft':   ed.chain().focus().setTextAlign('left').run(); break;
      case 'justifyCenter': ed.chain().focus().setTextAlign('center').run(); break;
      case 'justifyRight':  ed.chain().focus().setTextAlign('right').run(); break;
      case 'justify':       ed.chain().focus().setTextAlign('justify').run(); break;
      case 'indent':
        if (ed.can().sinkListItem('listItem')) { ed.chain().focus().sinkListItem('listItem').run(); }
        else { ed.chain().focus().indent().run(); }
        break;
      case 'outdent':
        if (ed.can().liftListItem('listItem')) { ed.chain().focus().liftListItem('listItem').run(); }
        else { ed.chain().focus().outdent().run(); }
        break;
      case 'clearMarks':    ed.chain().focus().unsetAllMarks().run(); break;
    }
    _syncDocxHoverBar();
  };

  // Insert or edit hyperlink
  window.WA.docxInsertLink = () => {
    const ed = state.activeEditor && state.activeEditor.editor;
    if (!ed) return;
    const existing = (ed.getAttributes('link') || {}).href || '';
    const url = window.prompt('\u8bf7\u8f93\u5165\u94fe\u63a5\u5730\u5740 (URL):', existing);
    if (url === null) return;  // cancelled
    if (url.trim() === '') {
      ed.chain().focus().unsetLink().run();
    } else {
      const href = /^https?:\/\//i.test(url.trim()) ? url.trim() : 'https://' + url.trim();
      ed.chain().focus().setLink({ href, target: '_blank' }).run();
    }
    _syncDocxHoverBar();
  };

  window.WA.docxHoverFontFamily = (name) => {
    const value = _resolveDocxFontFamily(name.trim());
    if (_dispatchDocxRibbonSelect('setFontFamily', value)) {
      _syncDocxHoverBar();
      return;
    }

    const ed = state.activeEditor && state.activeEditor.editor;
    if (!ed) return;
    if (!value) {
      ed.chain().focus().unsetFontFamily().run();
      return;
    }
    ed.chain().focus().setFontFamily(value).run();
  };

  window.WA.docxHoverFontSize = (size) => {
    if (_dispatchDocxRibbonSelect('setFontSize', size ? `${parseFloat(size)}pt` : '')) {
      _syncDocxHoverBar();
      return;
    }

    const ed = state.activeEditor && state.activeEditor.editor;
    if (!ed || !size) return;
    const sz = parseFloat(size);
    if (isNaN(sz) || sz <= 0) return;
    ed.chain().focus().setFontSize(sz + 'pt').run();
  };

  // Colour picker for DOCX hoverbar
  window.WA.docxColorPicker = (type, triggerEl) => {
    _ensureDocxHoverBar();  // make sure DOM exists
    const palette = _docxCpEl;
    const grid    = palette ? palette.querySelector('#wa-docx-cp-grid') : null;
    if (!palette || !grid) return;
    if (palette.style.display !== 'none' && palette.dataset.cpType === type) {
      palette.style.display = 'none'; return;
    }
    palette.dataset.cpType = type;
    grid.innerHTML = _CP_COLORS.map(c =>
      `<div title="${c}" style="width:18px;height:18px;border-radius:3px;background:${c};cursor:pointer;border:1px solid rgba(255,255,255,.12);box-sizing:border-box"` +
      ` onmousedown="event.preventDefault()" onclick="WA._docxPickColor('${c}')"></div>`
    ).join('');
    if (triggerEl) {
      const r  = triggerEl.getBoundingClientRect();
      const pw = 8 * 18 + 7 * 3 + 16;
      const left = Math.min(r.left, window.innerWidth - pw - 8);
      palette.style.left = Math.max(4, left) + 'px';
      palette.style.top  = (r.bottom + 4) + 'px';
    }
    palette.style.display = 'block';
  };

  window.WA._docxPickColor = (color, keepOpen) => {
    const palette = _docxCpEl;
    const type = palette ? palette.dataset.cpType : '';
    if (typeof window._ttPickColor === 'function') {
      window._ttPickColor(color, keepOpen);
      _syncDocxHoverBar();
      const hexEl = $('wa-docx-cp-hex');
      if (hexEl) hexEl.textContent = color;
      const ci = $('wa-docx-cp-custom');
      if (ci && /^#[0-9a-f]{6}$/i.test(color)) ci.value = color;
      if (!keepOpen && palette) palette.style.display = 'none';
      return;
    }

    const ed = state.activeEditor && state.activeEditor.editor;
    if (ed) {
      if (type === 'font') {
        ed.chain().focus().setColor(color).run();
        const sw = $('wa-dh-color-swatch');
        if (sw) sw.style.background = color;
      } else if (type === 'bg') {
        ed.chain().focus().toggleHighlight({ color }).run();
        const sw = $('wa-dh-bg-swatch');
        if (sw) sw.style.background = color;
      }
    }
    const hexEl = $('wa-docx-cp-hex');
    if (hexEl) hexEl.textContent = color;
    const ci = $('wa-docx-cp-custom');
    if (ci && /^#[0-9a-f]{6}$/i.test(color)) ci.value = color;
    if (!keepOpen && palette) palette.style.display = 'none';
  };

  // Send selected DOCX text to AI via hoverbar action buttons
  window.WA.docxHoverAI = (action) => {
    _hideDocxHoverBar();
    const selText = _getDocxSelectionTextForAI() || (window.getSelection ? window.getSelection().toString().trim() : '');
    if (selText) lastSelectionText = selText;
    if (!lastSelectionText) { showToast('请先选中文字', 'info'); return; }
    WA.sendQuickAction(action);
  };

  // ── Close buttons for toolbars ──────────────────────────────
  window.WA.closeDocxHoverBar = () => {
    // Record the exact selection text so we don't re-show the toolbars for the same selection
    window._docxHoverForceHiddenText = lastSelectionText || (window.getSelection ? window.getSelection().toString().trim() : '');
    _resetDocxSelection();
  };
  window.WA.closeSelectionToolbar = () => {
    window._docxHoverForceHiddenText = lastSelectionText || (window.getSelection ? window.getSelection().toString().trim() : '');
    const tt = $('wa-pdf-tooltip');
    if (tt) tt.style.display = 'none';
    if (state.fileType === 'docx') _resetDocxSelection();
  };

  // ── DOCX hoverbar: hide on click outside (capture phase) ──────
  document.addEventListener('mousedown', (e) => {
    const _el = _evtEl(e.target);
    if (!_docxHbEl || _docxHbEl.style.display === 'none') return;
    if (_el && _docxHbEl.contains(_el)) return;
    if (_el && _docxCpEl && _docxCpEl.contains(_el)) return;
    _hideDocxHoverBar();
  }, true);
  // ── DOCX colour picker: hide on click outside ───────────────────────────
  document.addEventListener('mousedown', (e) => {
    const _el = _evtEl(e.target);
    if (!_docxCpEl || _docxCpEl.style.display === 'none') return;
    if (_el && _docxCpEl.contains(_el)) return;
    if (_el && _el.closest && _el.closest('#wa-dh-color-trigger,#wa-dh-bg-trigger')) return;
    _docxCpEl.style.display = 'none';
  }, true);

  window.WA.pptxLineSpacing = (val) => {
     if (state.activeEditor && state.activeEditor.applyFormat)
       state.activeEditor.applyFormat('lineSpacing', parseFloat(val));
  };

  // ── Slide background: color, image, remove ──────────────────────────────

  window.WA.pptxBgColor = (color) => {
    const ed = state.activeEditor;
    if (!ed) return;
    ed._pushUndo();
    const slide = ed.data.slides[ed._curIdx];
    slide.background = color;
    slide.backgroundGradient = null;
    slide.backgroundImage = null;
    const canvas = $('wa-pptx-slide-canvas');
    if (canvas) canvas.style.background = color;
    const swatch = $('wa-pptx-bg-swatch');
    if (swatch) swatch.style.background = color;
    ed._redrawThumb(ed._curIdx);
    WA.scheduleAutoSave();
  };

  window.WA.pptxSetBgImage = (fileInput) => {
    const ed = state.activeEditor;
    if (!ed || !fileInput.files || !fileInput.files[0]) return;
    const file = fileInput.files[0];
    fileInput.value = '';  // reset so same file can be selected again
    const reader = new FileReader();
    reader.onload = (ev) => {
      const raw = ev.target.result;
      // Client-side compress: resize to max 1920px to keep memory usage low
      const img = new Image();
      img.onload = () => {
        const MAX = 1920;
        let w = img.naturalWidth, h = img.naturalHeight;
        if (w > MAX || h > MAX) {
          const ratio = Math.min(MAX / w, MAX / h);
          w = Math.round(w * ratio);
          h = Math.round(h * ratio);
        }
        const _cv = document.createElement('canvas');
        _cv.width = w; _cv.height = h;
        const _ctx = _cv.getContext('2d');
        _ctx.drawImage(img, 0, 0, w, h);
        const dataUri = _cv.toDataURL('image/jpeg', 0.82);
        ed._pushUndo();
        const slide = ed.data.slides[ed._curIdx];
        slide.backgroundImage = dataUri;
        slide.backgroundGradient = null;
        const canvas = $('wa-pptx-slide-canvas');
        if (canvas) canvas.style.background = `url('${dataUri}') center/cover no-repeat`;
        const swatch = $('wa-pptx-bg-swatch');
        if (swatch) { swatch.style.background = `url('${dataUri}') center/cover`; swatch.style.backgroundSize = 'cover'; }
        ed._redrawThumb(ed._curIdx);
        WA.scheduleAutoSave();
      };
      img.src = raw;
    };
    reader.readAsDataURL(file);
  };

  window.WA.pptxRemoveBg = () => {
    const ed = state.activeEditor;
    if (!ed) return;
    ed._pushUndo();
    const slide = ed.data.slides[ed._curIdx];
    slide.background = '#ffffff';
    slide.backgroundGradient = null;
    slide.backgroundImage = null;
    const canvas = $('wa-pptx-slide-canvas');
    if (canvas) canvas.style.background = '#ffffff';
    const swatch = $('wa-pptx-bg-swatch');
    if (swatch) { swatch.style.background = '#ffffff'; swatch.style.backgroundImage = ''; }
    ed._redrawThumb(ed._curIdx);
    WA.scheduleAutoSave();
  };

  window.WA.pptxShapeFill = (val) => {
     const ed = state.activeEditor;
     if (!ed || !ed._selShape) { showToast('请先选中一个形状', 'info'); return; }
     const swatch = $('wa-pptx-shapefill-swatch');
     if (swatch) swatch.style.background = val;
     ed._pushUndo();
     const shapeId = parseInt(ed._selShape.dataset.shapeId);
     const slide = ed.data.slides[ed._curIdx];
     const shape = (slide.shapes || []).find(s => s.id === shapeId);
     if (shape) {
       shape.fill = val;
       ed._selShape.style.backgroundColor = val;
       WA.scheduleAutoSave();
     }
  };

  window.WA.pptxShapeBorder = (val) => {
     const ed = state.activeEditor;
     if (!ed || !ed._selShape) { showToast('请先选中一个形状', 'info'); return; }
     const swatch = $('wa-pptx-shapeborder-swatch');
     if (swatch) swatch.style.background = val;
     ed._pushUndo();
     const shapeId = parseInt(ed._selShape.dataset.shapeId);
     const slide = ed.data.slides[ed._curIdx];
     const shape = (slide.shapes || []).find(s => s.id === shapeId);
     if (shape) {
       if (!shape.border) shape.border = {};
       shape.border.color = val;
       const w = shape.border.width || 1;
       ed._selShape.style.border = w + 'pt solid ' + val;
       WA.scheduleAutoSave();
     }
  };

  window.WA.pptxBorderWidth = (val) => {
     const ed = state.activeEditor;
     if (!ed || !ed._selShape) return;
     ed._pushUndo();
     const shapeId = parseInt(ed._selShape.dataset.shapeId);
     const slide = ed.data.slides[ed._curIdx];
     const shape = (slide.shapes || []).find(s => s.id === shapeId);
     if (shape) {
       if (!shape.border) shape.border = {};
       shape.border.width = parseFloat(val);
       if (parseFloat(val) === 0) {
         ed._selShape.style.border = 'none';
       } else {
         const c = shape.border.color || '#000000';
         ed._selShape.style.border = val + 'pt solid ' + c;
       }
       WA.scheduleAutoSave();
     }
  };

  window.WA.pptxDupSlide = () => {
     const ed = state.activeEditor;
     if (ed && ed._duplicateSlide) ed._duplicateSlide();
  };

  // ── New toolbar bridge functions ──────────────────────────────────────────

  window.WA.pptxStepFont = (dir) => {
    const ed = state.activeEditor;
    if (ed && ed._stepFontSize) ed._stepFontSize(dir);
  };

  window.WA.pptxClearFormat = () => {
    const ed = state.activeEditor;
    if (!ed) return;
    const slide = ed.data.slides[ed._curIdx];
    const getSpans = () => {
      const sel = window.getSelection && window.getSelection();
      const actRange = (ed._savedRange && !ed._savedRange.collapsed)
        ? ed._savedRange
        : (sel && sel.rangeCount > 0 && !sel.isCollapsed ? sel.getRangeAt(0) : null);
      if (actRange) {
        const arr = [];
        ed._selShape && ed._selShape.querySelectorAll('.wa-pptx-run').forEach(s => {
          if (sel ? sel.containsNode(s, true) : actRange.intersectsNode(s)) arr.push(s);
        });
        if (arr.length) return arr;
      }
      return ed._activeSpan ? [ed._activeSpan]
        : (ed._selShape ? Array.from(ed._selShape.querySelectorAll('.wa-pptx-run')) : []);
    };
    const spans = getSpans();
    if (!spans.length) return;
    ed._pushUndo();
    spans.forEach(sp => {
      const shape = (slide.shapes || []).find(s => s.id === parseInt(sp.dataset.shapeId));
      const run = shape && shape.paragraphs[parseInt(sp.dataset.pi)] && shape.paragraphs[parseInt(sp.dataset.pi)].runs[parseInt(sp.dataset.ri)];
      if (!run) return;
      ['bold','italic','underline','strikethrough','superscript','subscript','highlight','color'].forEach(p => { delete run[p]; });
      sp.style.fontWeight = '';
      sp.style.fontStyle = '';
      sp.style.textDecoration = '';
      sp.style.verticalAlign = '';
      sp.style.backgroundColor = '';
      sp.style.color = '';
      const scaleW = parseFloat($('wa-pptx-slide-canvas').style.width) / ed.data.slideWidthEmu;
      sp.style.fontSize = Math.max(Math.round((run.size || 18) * scaleW * 12700), 6) + 'px';
    });
    WA.scheduleAutoSave();
  };

  window.WA.pptxToggleBullet = () => {
    const ed = state.activeEditor;
    if (!ed || !ed._selShape) return;
    const sp = ed._activeSpan || (ed._selShape && ed._selShape.querySelector('.wa-pptx-run'));
    if (!sp) return;
    const slide = ed.data.slides[ed._curIdx];
    const shape = (slide.shapes || []).find(s => s.id === parseInt(sp.dataset.shapeId));
    const pi = parseInt(sp.dataset.pi);
    const para = shape && shape.paragraphs[pi];
    if (!para) return;
    ed._pushUndo();
    para.bullet = !para.bullet;
    if (para.bullet) para.numbered = false;
    ed._renderSlide(ed._curIdx);
    WA.scheduleAutoSave();
  };

  window.WA.pptxToggleNumbered = () => {
    const ed = state.activeEditor;
    if (!ed || !ed._selShape) return;
    const sp = ed._activeSpan || (ed._selShape && ed._selShape.querySelector('.wa-pptx-run'));
    if (!sp) return;
    const slide = ed.data.slides[ed._curIdx];
    const shape = (slide.shapes || []).find(s => s.id === parseInt(sp.dataset.shapeId));
    const pi = parseInt(sp.dataset.pi);
    const para = shape && shape.paragraphs[pi];
    if (!para) return;
    ed._pushUndo();
    const newVal = !para.numbered;
    para.numbered = newVal;
    if (newVal) para.bullet = false;
    ed._renderSlide(ed._curIdx);
    WA.scheduleAutoSave();
  };

  window.WA.pptxIndent = (dir) => {
    const ed = state.activeEditor;
    if (!ed || !ed._selShape) return;
    const sp = ed._activeSpan || (ed._selShape && ed._selShape.querySelector('.wa-pptx-run'));
    if (!sp) return;
    const slide = ed.data.slides[ed._curIdx];
    const shape = (slide.shapes || []).find(s => s.id === parseInt(sp.dataset.shapeId));
    const pi = parseInt(sp.dataset.pi);
    const para = shape && shape.paragraphs[pi];
    if (!para) return;
    ed._pushUndo();
    para.indent = Math.max(0, (para.indent || 0) + dir);
    const pEl = sp.parentElement;
    if (pEl) pEl.style.paddingLeft = (para.indent * 20) + 'px';
    WA.scheduleAutoSave();
  };

  window.WA.pptxVertAlign = (anchor) => {
    const ed = state.activeEditor;
    if (!ed || !ed._selShape) return;
    const shapeId = parseInt(ed._selShape.dataset.shapeId);
    const slide = ed.data.slides[ed._curIdx];
    const shape = (slide.shapes || []).find(s => s.id === shapeId);
    if (!shape) return;
    ed._pushUndo();
    shape.textAnchor = anchor;
    const inner = ed._selShape.querySelector('.wa-pptx-inner');
    if (inner) {
      const jcMap = { t: 'flex-start', ctr: 'center', b: 'flex-end' };
      inner.style.justifyContent = jcMap[anchor] || 'flex-start';
    }
    WA.scheduleAutoSave();
  };

  window.WA.pptxZOrder = (dir) => {
    const ed = state.activeEditor;
    if (!ed || !ed._selShape) return;
    const shapeId = parseInt(ed._selShape.dataset.shapeId);
    if (dir === 'front' && ed._bringToFront) ed._bringToFront(shapeId);
    else if (dir === 'back' && ed._sendToBack) ed._sendToBack(shapeId);
  };

  window.WA.pptxOpacity = (val) => {
    const ed = state.activeEditor;
    if (!ed || !ed._selShape) return;
    const shapeId = parseInt(ed._selShape.dataset.shapeId);
    const slide = ed.data.slides[ed._curIdx];
    const shape = (slide.shapes || []).find(s => s.id === shapeId);
    if (!shape) return;
    ed._pushUndo();
    shape.opacity = parseFloat(val) / 100;
    ed._selShape.style.opacity = shape.opacity;
    WA.scheduleAutoSave();
  };

  window.WA.pptxInsertImageClick = () => {
    const inp = $('wa-pptx-img-input');
    if (inp) inp.click();
  };

  window.WA.pptxInsertImageFile = (input) => {
    if (!input.files || !input.files[0]) return;
    const ed = state.activeEditor;
    if (!ed) return;
    const file = input.files[0];
    const reader = new FileReader();
    reader.onload = (e) => {
      const b64 = e.target.result; // data:image/...;base64,...
      const slide = ed.data.slides[ed._curIdx];
      if (!slide) return;
      ed._pushUndo();
      const newId = Math.max(0, ...(slide.shapes || []).map(s => s.id || 0)) + 1;
      const img = new Image();
      img.onload = () => {
        const canvasEl = $('wa-pptx-slide-canvas');
        const scaleW = parseFloat(canvasEl.style.width) / ed.data.slideWidthEmu;
        const maxW = ed.data.slideWidthEmu * 0.5;
        const maxH = ed.data.slideHeightEmu * 0.5;
        const ratio = img.naturalWidth / (img.naturalHeight || 1);
        let w = maxW, h = maxW / ratio;
        if (h > maxH) { h = maxH; w = maxH * ratio; }
        const shape = { id: newId, type: 'picture', left: ed.data.slideWidthEmu * 0.25, top: ed.data.slideHeightEmu * 0.25, width: w, height: h, imageBase64: b64 };
        slide.shapes.push(shape);
        ed._renderSlide(ed._curIdx);
        WA.scheduleAutoSave();
      };
      img.src = b64;
    };
    reader.readAsDataURL(file);
    input.value = '';
  };

  window.WA.pptxInsertShape = (type) => {
    const ed = state.activeEditor;
    if (!ed) return;
    const slide = ed.data.slides[ed._curIdx];
    if (!slide) return;
    ed._pushUndo();
    const newId = Math.max(0, ...(slide.shapes || []).map(s => s.id || 0)) + 1;
    const W = ed.data.slideWidthEmu, H = ed.data.slideHeightEmu;
    const shape = {
      id: newId,
      type: 'shape',
      shapeType: type,
      left: W * 0.3, top: H * 0.3,
      width: W * 0.2, height: H * 0.15,
      fill: '#4472C4',
      border: { color: '#2F4E8A', width: 1 },
      paragraphs: [{ runs: [], align: 'CENTER' }]
    };
    if (type === 'line') {
      shape.height = 0;
      shape.top = H * 0.5;
      shape.fill = 'none';
      shape.border = { color: '#4472C4', width: 2 };
    }
    slide.shapes.push(shape);
    ed._renderSlide(ed._curIdx);
    WA.scheduleAutoSave();
  };

  window.WA.pptxSetShapeSize = (dim, val) => {
    const ed = state.activeEditor;
    if (!ed || !ed._selShape) return;
    const px = parseFloat(val);
    if (isNaN(px) || px <= 0) return;
    const shapeId = parseInt(ed._selShape.dataset.shapeId);
    const slide = ed.data.slides[ed._curIdx];
    const shape = (slide.shapes || []).find(s => s.id === shapeId);
    if (!shape) return;
    ed._pushUndo();
    const canvasEl = $('wa-pptx-slide-canvas');
    const scaleW = parseFloat(canvasEl.style.width) / ed.data.slideWidthEmu;
    const scaleH = parseFloat(canvasEl.style.height) / ed.data.slideHeightEmu;
    if (dim === 'w') { shape.width = px / scaleW; ed._selShape.style.width = px + 'px'; }
    else             { shape.height = px / scaleH; ed._selShape.style.height = px + 'px'; }
    WA.scheduleAutoSave();
  };

  window.WA.pptxSetShapePos = (dim, val) => {
    const ed = state.activeEditor;
    if (!ed || !ed._selShape) return;
    const px = parseFloat(val);
    if (isNaN(px)) return;
    const shapeId = parseInt(ed._selShape.dataset.shapeId);
    const slide = ed.data.slides[ed._curIdx];
    const shape = (slide.shapes || []).find(s => s.id === shapeId);
    if (!shape) return;
    ed._pushUndo();
    const canvasEl = $('wa-pptx-slide-canvas');
    const scaleW = parseFloat(canvasEl.style.width) / ed.data.slideWidthEmu;
    const scaleH = parseFloat(canvasEl.style.height) / ed.data.slideHeightEmu;
    if (dim === 'x') { shape.left = px / scaleW;  ed._selShape.style.left = px + 'px'; }
    else             { shape.top  = px / scaleH;  ed._selShape.style.top  = px + 'px'; }
    WA.scheduleAutoSave();
  };

  window.WA.pptxSetShapeRot = (deg) => {
    const ed = state.activeEditor;
    if (!ed || !ed._selShape) return;
    const d = parseFloat(deg);
    if (isNaN(d)) return;
    const shapeId = parseInt(ed._selShape.dataset.shapeId);
    const slide = ed.data.slides[ed._curIdx];
    const shape = (slide.shapes || []).find(s => s.id === shapeId);
    if (!shape) return;
    ed._pushUndo();
    shape.rotation = d;
    ed._selShape.style.transform = 'rotate(' + d + 'deg)';
    WA.scheduleAutoSave();
  };

  window.WA.pptxHighlightColor = (val) => {
    const swatch = $('wa-pptx-highlight-swatch');
    if (swatch) swatch.style.background = val;
    const ed = state.activeEditor;
    if (ed && ed.applyFormat) ed.applyFormat('highlight', val);
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

  // ── PDF Adobe-style toolbar methods ──────────────────────────────────────
  window.WA.pdfSidebarTab = (btn) => {
    if (state.activeEditor && state.activeEditor.sidebarTab) state.activeEditor.sidebarTab(btn);
  };
  window.WA.pdfToggleSidebar = () => {
    if (state.activeEditor && state.activeEditor.toggleSidebar) state.activeEditor.toggleSidebar();
  };
  window.WA.pdfAnnotMode = (mode) => {
    if (state.activeEditor && state.activeEditor.setAnnotMode) state.activeEditor.setAnnotMode(mode);
  };
  window.WA.pdfAnnotColor = (hex) => {
    if (state.activeEditor && state.activeEditor.setAnnotColor) state.activeEditor.setAnnotColor(hex);
  };
  window.WA.pdfAnnotOpen = () => {
    if (state.activeEditor && state.activeEditor.annotOpen) state.activeEditor.annotOpen();
  };
  window.WA.pdfAnnotClose = () => {
    if (state.activeEditor && state.activeEditor.annotClose) state.activeEditor.annotClose();
  };
  window.WA.pdfAnnotateSelection = (type) => {
    if (state.activeEditor && state.activeEditor.annotateSelection) state.activeEditor.annotateSelection(type);
  };
  window.WA.pdfSaveAnnotations = () => {
    if (state.activeEditor && state.activeEditor.saveAnnotations) state.activeEditor.saveAnnotations();
  };
  window.WA.pdfAIAnnotate = () => {
    if (state.activeEditor && state.activeEditor.aiAnnotate) state.activeEditor.aiAnnotate();
  };
  window.WA.pdfLineWidth = (w) => {
    if (state.activeEditor) state.activeEditor._annotLineWidth = parseFloat(w) || 2;
  };
  window.WA.pdfRemoveWatermark = () => {
    if (state.activeEditor && state.activeEditor.pdfRemoveWatermark) state.activeEditor.pdfRemoveWatermark();
  };
  window.WA.pdfWatermarkClose = () => {
    const overlay = document.getElementById('wa-pdf-watermark-overlay');
    if (overlay) { overlay.style.display = 'none'; overlay.classList.remove('open'); }
  };
  window.WA.pdfSearchOpen = () => {
    if (state.activeEditor && state.activeEditor.searchOpen) state.activeEditor.searchOpen();
  };
  window.WA.pdfSearchClose = () => {
    if (state.activeEditor && state.activeEditor.searchClose) state.activeEditor.searchClose();
  };
  window.WA.pdfSearchInput = (val) => {
    if (state.activeEditor && state.activeEditor.searchInput) state.activeEditor.searchInput(val);
  };
  window.WA.pdfSearchKeydown = (e) => {
    if (state.activeEditor && state.activeEditor.searchKeydown) state.activeEditor.searchKeydown(e);
  };
  window.WA.pdfSearchNext = () => {
    if (state.activeEditor && state.activeEditor.searchNext) state.activeEditor.searchNext();
  };
  window.WA.pdfSearchPrev = () => {
    if (state.activeEditor && state.activeEditor.searchPrev) state.activeEditor.searchPrev();
  };

  // ══════════════════════════════════════════════════════════════════════════
  // ── DOCX find / replace (TipTap / ProseMirror) ───────────────────────────
  // ══════════════════════════════════════════════════════════════════════════
  const _docxFind = {
    matches: [],   // [{from, to}]  — ProseMirror document positions
    idx: 0,        // current match index
    marks: [],     // span elements injected for visual highlight (fallback)
    replaceOpen: false,
  };

  // Walk the ProseMirror document, collect all matches of `query`
  function _docxFindAll(query, caseSensitive) {
    const editor = state.activeEditor && state.activeEditor.editor;
    if (!editor || !query) return [];
    const escaped = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const regex = new RegExp(escaped, caseSensitive ? 'g' : 'gi');
    const results = [];
    editor.state.doc.descendants((node, pos) => {
      if (!node.isText || !node.text) return;
      regex.lastIndex = 0;
      let m;
      while ((m = regex.exec(node.text)) !== null) {
        results.push({ from: pos + m.index, to: pos + m.index + m[0].length });
      }
    });
    return results;
  }

  // Navigate to a match: set ProseMirror selection + scroll into view
  function _docxFindGo(matches, idx) {
    const editor = state.activeEditor && state.activeEditor.editor;
    if (!editor || !matches.length) return;
    const { from, to } = matches[idx];
    editor.commands.setTextSelection({ from, to });
    editor.commands.scrollIntoView();
    // Highlight via a wrapper span on the selected text (CSS handles colour)
    // ProseMirror selection already renders with .ProseMirror-selectednode or
    // the ::selection pseudo; we additionally scroll to ensure the element is visible.
  }

  function _docxFindUpdateCount(query) {
    const caseSensitive = (document.getElementById('wa-docx-find-case') || {}).checked;
    _docxFind.matches = _docxFindAll(query, caseSensitive);
    _docxFind.idx = _docxFind.matches.length ? 0 : -1;
    const countEl = document.getElementById('wa-docx-find-count');
    const inp     = document.getElementById('wa-docx-find-input');
    if (countEl) countEl.textContent = _docxFind.matches.length ? `1 / ${_docxFind.matches.length}` : (query ? '无匹配' : '');
    if (inp) inp.classList.toggle('no-match', !!query && !_docxFind.matches.length);
    if (_docxFind.matches.length) _docxFindGo(_docxFind.matches, 0);
  }

  window.WA.docxFindInput = (val) => _docxFindUpdateCount(val.trim());

  window.WA.docxFindNext = () => {
    if (!_docxFind.matches.length) return;
    _docxFind.idx = (_docxFind.idx + 1) % _docxFind.matches.length;
    _docxFindGo(_docxFind.matches, _docxFind.idx);
    const countEl = document.getElementById('wa-docx-find-count');
    if (countEl) countEl.textContent = `${_docxFind.idx + 1} / ${_docxFind.matches.length}`;
  };

  window.WA.docxFindPrev = () => {
    if (!_docxFind.matches.length) return;
    _docxFind.idx = (_docxFind.idx - 1 + _docxFind.matches.length) % _docxFind.matches.length;
    _docxFindGo(_docxFind.matches, _docxFind.idx);
    const countEl = document.getElementById('wa-docx-find-count');
    if (countEl) countEl.textContent = `${_docxFind.idx + 1} / ${_docxFind.matches.length}`;
  };

  window.WA.docxFindKeydown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); WA.docxFindNext(); }
    if (e.key === 'Enter' &&  e.shiftKey) { e.preventDefault(); WA.docxFindPrev(); }
    if (e.key === 'Escape') WA.docxFindClose();
  };

  window.WA.docxFindClose = () => {
    const bar = document.getElementById('wa-docx-find-bar');
    if (bar) bar.style.display = 'none';
    _docxFind.matches = []; _docxFind.idx = -1;
    const inp = document.getElementById('wa-docx-find-input');
    if (inp) { inp.value = ''; inp.classList.remove('no-match'); }
    const countEl = document.getElementById('wa-docx-find-count');
    if (countEl) countEl.textContent = '';
    // Return focus to editor
    const pm = document.querySelector('#wa-docx-editor .ProseMirror');
    if (pm) pm.focus();
  };

  window.WA.docxToggleReplace = (forceOpen) => {
    const row  = document.getElementById('wa-docx-replace-row');
    const btn  = document.getElementById('wa-docx-replace-toggle');
    if (!row) return;
    _docxFind.replaceOpen = (forceOpen === true) ? true : !_docxFind.replaceOpen;
    row.style.display = _docxFind.replaceOpen ? '' : 'none';
    if (btn) btn.classList.toggle('active', _docxFind.replaceOpen);
    if (_docxFind.replaceOpen) {
      const ri = document.getElementById('wa-docx-replace-input');
      if (ri) ri.focus();
    }
  };

  window.WA.docxReplaceNext = () => {
    const editor = state.activeEditor && state.activeEditor.editor;
    if (!editor || !_docxFind.matches.length || _docxFind.idx < 0) return;
    const replaceVal = (document.getElementById('wa-docx-replace-input') || {}).value || '';
    const { from, to } = _docxFind.matches[_docxFind.idx];
    editor.chain().setTextSelection({ from, to }).insertContent(replaceVal).run();
    // Re-run search after replacement
    const query = (document.getElementById('wa-docx-find-input') || {}).value || '';
    _docxFindUpdateCount(query.trim());
  };

  window.WA.docxReplaceAll = () => {
    const editor = state.activeEditor && state.activeEditor.editor;
    if (!editor || !_docxFind.matches.length) return;
    const replaceVal = (document.getElementById('wa-docx-replace-input') || {}).value || '';
    const n = _docxFind.matches.length;
    // Replace from last to first to preserve position offsets
    const sorted = [..._docxFind.matches].sort((a, b) => b.from - a.from);
    editor.chain().focus().run();
    for (const { from, to } of sorted) {
      editor.chain().setTextSelection({ from, to }).insertContent(replaceVal).run();
    }
    showToast(`已替换 ${n} 处`, 'success');
    const query = (document.getElementById('wa-docx-find-input') || {}).value || '';
    _docxFindUpdateCount(query.trim());
  };

  // ══════════════════════════════════════════════════════════════════════════
  // ── PPTX find / replace (slide data search) ──────────────────────────────
  // ══════════════════════════════════════════════════════════════════════════
  const _pptxFind = {
    matches: [],   // [{slideIdx, shapeId, paraIdx, runIdx, charIdx, text, len}]
    idx: 0,
    replaceOpen: false,
  };

  function _pptxFindAll(query, caseSensitive) {
    const ed = state.activeEditor;
    if (!ed || !ed.data || !query) return [];
    const q = caseSensitive ? query : query.toLowerCase();
    const results = [];
    ed.data.slides.forEach((slide, slideIdx) => {
      (slide.shapes || []).forEach(shape => {
        if (!shape.has_text) return;
        (shape.paragraphs || []).forEach((para, paraIdx) => {
          (para.runs || []).forEach((run, runIdx) => {
            const text = run.text || '';
            const t = caseSensitive ? text : text.toLowerCase();
            let ci = 0;
            while ((ci = t.indexOf(q, ci)) !== -1) {
              results.push({ slideIdx, shapeId: shape.id, paraIdx, runIdx, charIdx: ci, len: q.length, displayText: text.substring(ci, ci + q.length) });
              ci++;
            }
          });
        });
      });
    });
    return results;
  }

  function _pptxFindGo(matches, idx) {
    const ed = state.activeEditor;
    if (!ed || !matches.length) return;
    const { slideIdx } = matches[idx];
    if (typeof ed._curIdx !== 'undefined' && ed._curIdx !== slideIdx) {
      // Navigate to the matching slide
      if (typeof WA.pptxNav === 'function') {
        // Use internal navigation
        const delta = slideIdx - ed._curIdx;
        WA.pptxNav(delta);
      }
    }
  }

  function _pptxFindUpdateCount(query) {
    const caseSensitive = (document.getElementById('wa-pptx-find-case') || {}).checked;
    _pptxFind.matches = _pptxFindAll(query, caseSensitive);
    _pptxFind.idx = _pptxFind.matches.length ? 0 : -1;
    const countEl = document.getElementById('wa-pptx-find-count');
    const inp     = document.getElementById('wa-pptx-find-input');
    if (countEl) countEl.textContent = _pptxFind.matches.length ? `1 / ${_pptxFind.matches.length}` : (query ? '无匹配' : '');
    if (inp) inp.classList.toggle('no-match', !!query && !_pptxFind.matches.length);
    if (_pptxFind.matches.length) _pptxFindGo(_pptxFind.matches, 0);
  }

  window.WA.pptxFindInput = (val) => _pptxFindUpdateCount(val.trim());

  window.WA.pptxFindNext = () => {
    if (!_pptxFind.matches.length) return;
    _pptxFind.idx = (_pptxFind.idx + 1) % _pptxFind.matches.length;
    _pptxFindGo(_pptxFind.matches, _pptxFind.idx);
    const countEl = document.getElementById('wa-pptx-find-count');
    if (countEl) countEl.textContent = `${_pptxFind.idx + 1} / ${_pptxFind.matches.length}`;
  };

  window.WA.pptxFindPrev = () => {
    if (!_pptxFind.matches.length) return;
    _pptxFind.idx = (_pptxFind.idx - 1 + _pptxFind.matches.length) % _pptxFind.matches.length;
    _pptxFindGo(_pptxFind.matches, _pptxFind.idx);
    const countEl = document.getElementById('wa-pptx-find-count');
    if (countEl) countEl.textContent = `${_pptxFind.idx + 1} / ${_pptxFind.matches.length}`;
  };

  window.WA.pptxFindKeydown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); WA.pptxFindNext(); }
    if (e.key === 'Enter' &&  e.shiftKey) { e.preventDefault(); WA.pptxFindPrev(); }
    if (e.key === 'Escape') WA.pptxFindClose();
  };

  window.WA.pptxFindClose = () => {
    const bar = document.getElementById('wa-pptx-find-bar');
    if (bar) bar.style.display = 'none';
    _pptxFind.matches = []; _pptxFind.idx = -1;
    const inp = document.getElementById('wa-pptx-find-input');
    if (inp) { inp.value = ''; inp.classList.remove('no-match'); }
    const countEl = document.getElementById('wa-pptx-find-count');
    if (countEl) countEl.textContent = '';
  };

  window.WA.pptxToggleReplace = (forceOpen) => {
    const row = document.getElementById('wa-pptx-replace-row');
    const btn = document.getElementById('wa-pptx-replace-toggle');
    if (!row) return;
    _pptxFind.replaceOpen = (forceOpen === true) ? true : !_pptxFind.replaceOpen;
    row.style.display = _pptxFind.replaceOpen ? '' : 'none';
    if (btn) btn.classList.toggle('active', _pptxFind.replaceOpen);
    if (_pptxFind.replaceOpen) {
      const ri = document.getElementById('wa-pptx-replace-input');
      if (ri) ri.focus();
    }
  };

  // PPTX replace: update the run text directly in slide data
  function _pptxApplyReplace(match, replaceVal) {
    const ed = state.activeEditor;
    if (!ed || !ed.data) return false;
    const slide = ed.data.slides[match.slideIdx];
    if (!slide) return false;
    const shape = (slide.shapes || []).find(s => s.id === match.shapeId);
    if (!shape) return false;
    const para = (shape.paragraphs || [])[match.paraIdx];
    if (!para) return false;
    const run = (para.runs || [])[match.runIdx];
    if (!run) return false;
    // Replace at exact char position
    run.text = run.text.substring(0, match.charIdx) + replaceVal + run.text.substring(match.charIdx + match.len);
    // Re-render the slide and schedule auto-save
    if (ed._curIdx === match.slideIdx && typeof ed._renderSlide === 'function') ed._renderSlide(match.slideIdx);
    if (typeof ed._redrawThumb === 'function') ed._redrawThumb(match.slideIdx);
    WA.scheduleAutoSave();
    return true;
  }

  window.WA.pptxReplaceNext = () => {
    if (!_pptxFind.matches.length || _pptxFind.idx < 0) return;
    const replaceVal = (document.getElementById('wa-pptx-replace-input') || {}).value || '';
    _pptxApplyReplace(_pptxFind.matches[_pptxFind.idx], replaceVal);
    const query = (document.getElementById('wa-pptx-find-input') || {}).value || '';
    _pptxFindUpdateCount(query.trim());
  };

  window.WA.pptxReplaceAll = () => {
    if (!_pptxFind.matches.length) return;
    const replaceVal = (document.getElementById('wa-pptx-replace-input') || {}).value || '';
    const n = _pptxFind.matches.length;
    // Replace in reverse order to keep indices valid
    [..._pptxFind.matches].reverse().forEach(m => _pptxApplyReplace(m, replaceVal));
    showToast(`已替换 ${n} 处`, 'success');
    const query = (document.getElementById('wa-pptx-find-input') || {}).value || '';
    _pptxFindUpdateCount(query.trim());
  };
  // Draggable sticky note helper
  window.WA._pdfDragNote = (e, popup) => {
    e.preventDefault();
    const startX = e.clientX - popup.offsetLeft;
    const startY = e.clientY - popup.offsetTop;
    const move = (ev) => {
      popup.style.left = (ev.clientX - startX) + 'px';
      popup.style.top  = (ev.clientY - startY) + 'px';
    };
    const up = () => { document.removeEventListener('mousemove', move); document.removeEventListener('mouseup', up); };
    document.addEventListener('mousemove', move);
    document.addEventListener('mouseup', up);
  };
  // sendCustomMessage helper for AI explanations from annotation context menu
  if (!window.WA.sendCustomMessage) {
    window.WA.sendCustomMessage = (msg) => {
      const inp = document.getElementById('wa-ai-input');
      if (inp) { inp.value = msg; WA.sendMessage(); }
    };
  }

  // ── PDF Page Manager ─────────────────────────────────────────────────────
  window.WA.pdfPageMgrOpen = () => {
    const ed = state.activeEditor;
    if (!ed || !ed._pdf) { showToast('请先打开一个 PDF 文件', 'warning'); return; }
    const mgr = document.getElementById('wa-pdf-pagemgr');
    if (!mgr) return;
    mgr.style.display = 'flex';
    _pdfPageMgrBuild(ed);
  };
  window.WA.pdfPageMgrClose = () => {
    const mgr = document.getElementById('wa-pdf-pagemgr');
    if (mgr) mgr.style.display = 'none';
  };
  window.WA.pdfPageMgrApply = async () => {
    const ed = state.activeEditor;
    if (!ed || !state.fileId) return;
    const grid = document.getElementById('wa-pdf-pagemgr-grid');
    if (!grid) return;
    const cards = [...grid.querySelectorAll('.wa-pmgr-card:not(.deleted)')];
    const pages = cards.map(c => ({
      orig_page: parseInt(c.dataset.origPage),
      rotation: parseInt(c.dataset.rotation || '0'),
    }));
    showToast('正在应用页面更改…', 'info', 2000);
    try {
      const resp = await fetch('/api/v1/workspace/pdf/page_ops', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ file_id: state.fileId, pages }),
      });
      if (!resp.ok) { const e = await resp.json(); throw new Error(e.error || resp.statusText); }
      const blob = await resp.blob();
      _downloadBlob(blob, state.fileName || 'modified.pdf');
      WA.pdfPageMgrClose();
      showToast('页面更改已导出', 'success');
    } catch (err) {
      showToast('操作失败: ' + err.message, 'error');
    }
  };
  window.WA.pdfPageMgrExport = async () => {
    const ed = state.activeEditor;
    if (!ed || !state.fileId) return;
    const grid = document.getElementById('wa-pdf-pagemgr-grid');
    if (!grid) return;
    const selectedCards = [...grid.querySelectorAll('.wa-pmgr-card.selected:not(.deleted)')];
    if (!selectedCards.length) { showToast('请先勾选要导出的页面', 'warning'); return; }
    const pages = selectedCards.map(c => ({
      orig_page: parseInt(c.dataset.origPage),
      rotation: parseInt(c.dataset.rotation || '0'),
    }));
    showToast('正在导出选中页面…', 'info', 2000);
    try {
      const resp = await fetch('/api/v1/workspace/pdf/page_ops', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ file_id: state.fileId, pages }),
      });
      if (!resp.ok) { const e = await resp.json(); throw new Error(e.error || resp.statusText); }
      const blob = await resp.blob();
      const base = (state.fileName || 'export.pdf').replace(/\.pdf$/i, '');
      _downloadBlob(blob, base + '_选中页.pdf');
      showToast('导出完成', 'success');
    } catch (err) {
      showToast('导出失败: ' + err.message, 'error');
    }
  };

  function _pdfPageMgrBuild(ed) {
    const grid = document.getElementById('wa-pdf-pagemgr-grid');
    if (!grid) return;
    grid.innerHTML = '';
    const totalPages = ed._pdf ? ed._pdf.numPages : 0;
    for (let p = 1; p <= totalPages; p++) {
      const card = document.createElement('div');
      card.className = 'wa-pmgr-card';
      card.draggable = true;
      card.dataset.origPage = p;
      card.dataset.rotation = '0';
      card.innerHTML = `
        <input type="checkbox" class="wa-pmgr-check" title="选中此页">
        <div class="wa-pmgr-thumb"><canvas></canvas></div>
        <div class="wa-pmgr-rotation-badge"></div>
        <div class="wa-pmgr-label">第 ${p} 页</div>
        <div class="wa-pmgr-controls">
          <div class="wa-pmgr-ctrl-btn" title="顺时针旋转 90°" onclick="_pdfPageMgrRotate(this.closest('.wa-pmgr-card'), 90)">↻</div>
          <div class="wa-pmgr-ctrl-btn" title="逆时针旋转 90°" onclick="_pdfPageMgrRotate(this.closest('.wa-pmgr-card'), -90)">↺</div>
          <div class="wa-pmgr-ctrl-btn" title="删除此页" onclick="_pdfPageMgrDelete(this.closest('.wa-pmgr-card'))">✕</div>
        </div>`;
      const chk = card.querySelector('.wa-pmgr-check');
      chk.addEventListener('change', () => card.classList.toggle('selected', chk.checked));
      _setupPageMgrDrag(card);
      grid.appendChild(card);
      // Render thumbnail
      _pdfPageMgrRenderThumb(ed, p, card.querySelector('canvas'));
    }
  }

  async function _pdfPageMgrRenderThumb(ed, pageNum, canvas) {
    try {
      const page = await ed._pdf.getPage(pageNum);
      const vp = page.getViewport({ scale: 0.3 });
      canvas.width = vp.width;
      canvas.height = vp.height;
      await page.render({ canvasContext: canvas.getContext('2d'), viewport: vp }).promise;
    } catch (_e) {}
  }

  function _pdfPageMgrRotate(card, delta) {
    const cur = parseInt(card.dataset.rotation || '0');
    const next = ((cur + delta) % 360 + 360) % 360;
    card.dataset.rotation = next;
    const badge = card.querySelector('.wa-pmgr-rotation-badge');
    if (badge) {
      badge.style.display = next !== 0 ? 'block' : 'none';
      badge.textContent = next + '°';
    }
    const canvas = card.querySelector('canvas');
    if (canvas) canvas.style.transform = `rotate(${next}deg)`;
  }

  function _pdfPageMgrDelete(card) {
    card.classList.toggle('deleted');
    const lbl = card.querySelector('.wa-pmgr-label');
    if (lbl) lbl.textContent = card.classList.contains('deleted') ? '已删除' : `第 ${card.dataset.origPage} 页`;
  }

  function _setupPageMgrDrag(card) {
    card.addEventListener('dragstart', e => {
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', '');
      card.classList.add('dragging');
      window._pmgrDragSrc = card;
    });
    card.addEventListener('dragend', () => card.classList.remove('dragging'));
    card.addEventListener('dragover', e => { e.preventDefault(); e.dataTransfer.dropEffect = 'move'; card.classList.add('drag-over'); });
    card.addEventListener('dragleave', () => card.classList.remove('drag-over'));
    card.addEventListener('drop', e => {
      e.preventDefault();
      card.classList.remove('drag-over');
      const src = window._pmgrDragSrc;
      if (!src || src === card) return;
      const grid = card.parentNode;
      const cards = [...grid.children];
      const srcIdx = cards.indexOf(src);
      const dstIdx = cards.indexOf(card);
      if (srcIdx < dstIdx) grid.insertBefore(src, card.nextSibling);
      else grid.insertBefore(src, card);
    });
  }

  function _downloadBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  }

  // ── PDF Format Conversion ───────────────────────────────────────────────
  window.WA.pdfConvertMenu = (btn) => {
    const menu = document.getElementById('wa-pdf-convert-menu');
    if (!menu) return;
    const visible = menu.style.display !== 'none';
    menu.style.display = visible ? 'none' : 'block';
    if (!visible) {
      const close = (e) => {
        if (!menu.contains(e.target) && e.target !== btn) {
          menu.style.display = 'none';
          document.removeEventListener('mousedown', close);
        }
      };
      document.addEventListener('mousedown', close);
    }
  };
  window.WA.pdfConvert = async (targetFmt) => {
    const menu = document.getElementById('wa-pdf-convert-menu');
    if (menu) menu.style.display = 'none';
    if (!state.fileId) { showToast('请先打开一个 PDF 文件', 'warning'); return; }
    const fmtLabel = { docx: 'Word (.docx)', xlsx: 'Excel (.xlsx)', pptx: 'PowerPoint (.pptx)' }[targetFmt] || targetFmt;
    showToast(`正在转换为 ${fmtLabel}…`, 'info', 3000);
    try {
      const resp = await fetch('/api/v1/workspace/pdf/convert', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ file_id: state.fileId, target_format: targetFmt, filename: state.fileName }),
      });
      if (!resp.ok) { const e = await resp.json(); throw new Error(e.error || resp.statusText); }
      const warning = resp.headers.get('X-Koto-Warning');
      const blob = await resp.blob();
      const base = (state.fileName || 'converted').replace(/\.pdf$/i, '');
      _downloadBlob(blob, `${base}.${targetFmt}`);
      showToast(warning ? `转换完成 — ${warning}` : `已转换为 ${fmtLabel}`, warning ? 'warning' : 'success', 5000);
    } catch (err) {
      showToast('格式转换失败: ' + err.message, 'error');
    }
  };

  window.WA.docxZoom = (val) => {
     if (state.activeEditor && state.activeEditor.setZoom)
       state.activeEditor.setZoom(parseInt(val));
     // Update label from this scope where _updateDocxZoomUI is accessible.
     // (The TipTap IIFE bundle cannot reach this function directly.)
     _updateDocxZoomUI(parseInt(val));
  };

  /**
   * Switch DOCX between read (docx-preview) and edit (TipTap) modes.
   * Called from DocxReadView's "编辑" button and TipTap's "预览" button.
   */
  window.WA._switchDocxMode = async (targetMode) => {
    const tab = state.openTabs.find(t => t.path === state.activeTabPath);
    if (!tab || tab.fileType !== 'docx') return;

    // Serialize current editor before switching
    if (state.activeEditor) {
      if (state.activeEditor.serialize) {
        const serialized = _serializeEditorForTab(tab, state.activeEditor);
        if (tab.fileType !== 'docx' && serialized !== null) tab.cache = serialized;
      }
      try { state.activeEditor.destroy(); } catch(e) { console.error('[mode switch] destroy:', e); }
      state.activeEditor = null;
    }

    if (targetMode === 'edit') {
      const html = (tab.cache && typeof tab.cache === 'string' && tab.cache.trim()) ? tab.cache : tab.serverData.html;
      await _mountDocxEditor(tab, html, tab.serverData);
      tab._docxViewMode = 'edit';
      // Inject "预览" button into the editor toolbar
      setTimeout(() => {
        const toolbar = $('wa-editor-toolbar');
        if (toolbar && !toolbar.querySelector('.wa-drv-preview-btn')) {
          const btn = document.createElement('button');
          btn.className = 'wa-drv-preview-btn';
          btn.title = '切换到预览模式';
          btn.innerHTML = _SEARCH_SVG + ' 预览';
          btn.style.cssText = 'margin-left:auto;padding:3px 10px;font-size:12px;color:#d4d6e4;background:rgba(255,255,255,0.07);border:1px solid rgba(255,255,255,0.12);border-radius:4px;cursor:pointer;';
          btn.addEventListener('click', () => WA._switchDocxMode('read'));
          toolbar.appendChild(btn);
        }
      }, 200);
    } else {
      // Switch back to read mode
      const rawUrl = tab.serverData && tab.serverData.raw_url;
      if (rawUrl) {
        state.activeEditor = new DocxReadView();
        await state.activeEditor.render(rawUrl);
        tab._docxViewMode = 'read';
      } else {
        showToast('无法切换到预览模式（缺少原始文件）', 'error');
      }
    }
  };

  /**
   * Send image data to AI panel for describe/replace actions.
   * Called from DocxReadView image toolbar buttons.
   */
  window.WA._sendImageToAI = (action, imgSrc) => {
    const aiInput = document.getElementById('wa-ai-input');
    if (!aiInput) return;
    const label = action === 'describe' ? '请描述这张图片的内容' : '请为这张图片生成替换方案';
    aiInput.value = label;
    aiInput.focus();
    // Store image reference for AI context
    window.WA._pendingImageSrc = imgSrc;
    showToast('已将图片发送到 AI 输入，按回车发送', 'info', 3000);
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
     ed._pushUndo();
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
     ed._pushUndo();
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

  window.WA.pptxUndo = () => {
     if (state.activeEditor && state.activeEditor._undo) state.activeEditor._undo();
  };

  window.WA.pptxRedo = () => {
     if (state.activeEditor && state.activeEditor._redo) state.activeEditor._redo();
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
    if (!ta) return;
    ta.style.height = 'auto';
    const maxHeight = 360;
    ta.style.height = Math.min(ta.scrollHeight, maxHeight) + 'px';
    ta.style.overflowY = ta.scrollHeight > maxHeight ? 'auto' : 'hidden';
  }

  // ── Chart generation dialog ──
  let _chartLang = 'python';

  window.WA.openChartDialog = (lang) => {
     _chartLang = lang;
     $('wa-chart-dialog-title').innerHTML = lang === 'python' ? `${_CHART_SVG} Python 画图 (matplotlib)` : `${_CHART_SVG} R 画图 (ggplot2)`;
     // Show data hint
     const hasXlsx = state.fileType === 'xlsx';
     $('wa-chart-data-hint').textContent = hasXlsx
       ? `${_LIGHTBULB_SVG} 将自动附上当前表格的全量数据`
       : `${_LIGHTBULB_SVG} 请在描述中说明数据或粘贴 CSV`;
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
     uMsg.textContent = `${_chartLang.toUpperCase()} 画图：${desc}`;
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

  function _normalizeProposalText(text) {
    return String(text || '')
      .replace(/<[^>]+>/g, ' ')
      .replace(/^(?:以下|下面|这是|如下)(?:是|为)?.{0,20}(?:润色|翻译|改写|修改|修正|优化|版本|结果|文本|内容).{0,10}[：:]\s*/i, '')
      .replace(/\s+/g, '')
      .trim()
      .toLowerCase();
  }

  function _getProposalRationaleText(proposal) {
    const raw = (proposal?.rationale || '').replace(/<[^>]+>/g, '').trim();
    if (!raw) return '';
    const rationaleKey = _normalizeProposalText(raw);
    const originalKey = _normalizeProposalText(proposal?.original_text || '');
    const proposedKey = _normalizeProposalText(proposal?.proposed_text || '');
    if (!rationaleKey || rationaleKey === originalKey || rationaleKey === proposedKey) return '';
    return raw;
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
    const rText = _getProposalRationaleText(proposal);
    if (rText && rText.length > 5) {
      rationale.innerHTML = `${_LIGHTBULB_SVG} ` + _escHtml(rText.length > 150 ? rText.substring(0, 150) + '…' : rText);
    }

    const actions = document.createElement('div');
    actions.className = 'wa-proposal-actions';
    actions.innerHTML = canApply
      ? `<button class="wa-proposal-btn accept" onclick="WA.acceptProposal('${proposal.id}',this)">接受</button>` +
        `<button class="wa-proposal-btn reject" onclick="WA.rejectProposal('${proposal.id}',this)">拒绝</button>` +
        `<button class="wa-proposal-btn modify" onclick="WA.modifyProposal('${proposal.id}',this)">${_PENCIL_SVG} 再修改</button>`
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
      ? `<button class="wa-proposal-btn download small" onclick="WA.downloadPatchedFile()" title="将全部修改应用到目标文件并下载">应用并下载 ${_escHtml(targetFile.name)}</button>`
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
      showToast('请先设置目标文件（点击文件旁的 Pin 图标）', 'warn');
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
      // Save to workspace instead of browser downloads
      const arrayBuf = await blob.arrayBuffer();
      const uint8 = new Uint8Array(arrayBuf);
      let b64 = '';
      const chunkSize = 8192;
      for (let i = 0; i < uint8.length; i += chunkSize) {
        b64 += String.fromCharCode.apply(null, uint8.subarray(i, i + chunkSize));
      }
      b64 = btoa(b64);
      const saveRes = await fetch('/api/v1/workspace/save_to_workspace', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ type: 'file', data: b64, filename: dlName }),
      });
      if (!saveRes.ok) {
        const err = await saveRes.json().catch(() => ({}));
        throw new Error(err.error || `HTTP ${saveRes.status}`);
      }
      const saveData = await saveRes.json();
      _renderMyWorkspace();
      showToast(`已存入工作区: ${saveData.ws_path}`, 'success');
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

  // Parse AI response text and replace [来源: xxx] with clickable citation chips
  function _parseCitations(html) {
    return html.replace(
      /\[来源[:：]\s*([^\]]{1,60})\]/g,
      (_, srcName) =>
        `<span class="wa-citation-chip" onclick="WA._citationClick('${_escHtml(srcName.trim())}')" title="点击查看来源">${_PIN_SVG} ${_escHtml(srcName.trim())}</span>`
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
    label.textContent = file.name;
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
              body.innerHTML = `<div style="color:var(--error,red);padding:16px">${_escHtml(evt.data)}</div>`;
            }
          } catch(e) {}
        }
      }
      if (!script) body.innerHTML = '<div class="wa-audio-loading">未收到脚本</div>';
    } catch(e) {
      if (body) body.innerHTML = `<div style="color:var(--error,red);padding:16px">${_escHtml(e.message)}</div>`;
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
      : `<div class="wa-audio-no-tts">${_CHAT_SVG} 脚本已生成，音频合成需要 edge-tts 库（<code>pip install edge-tts</code>）</div>`;

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
        summary: '执行摘要', points: '关键要点',
        faq: '常见问答', glossary: '核心词汇',
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
              body.innerHTML += `<div style="color:var(--error,red);padding:10px">${_escHtml(evt.content)}</div>`;
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
              `<button class="wa-nb-copy-btn" onclick="event.stopPropagation();WA._copyNbSection(this)" title="复制">${_CLIPBOARD_SVG}</button>` +
              `<button class="wa-nb-send-btn" onclick="event.stopPropagation();WA._sendNbSection(this)" title="发送到AI">${_CHAT_SVG}</button>` +
              `<span class="wa-nb-chevron">▾</span></div></div>` +
              `<div class="wa-nb-card-body" data-raw="${_escHtml(evt.content)}">${renderMd(evt.content)}</div>`;
            body.appendChild(card);
          } catch(e) {}
        }
      }
      if (!body.children.length) {
        body.innerHTML = '<div class="wa-audio-loading">未收到内容</div>';
      }
    } catch(e) {
      if (body) body.innerHTML = `<div style="color:var(--error,red);padding:16px">${_escHtml(e.message)}</div>`;
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
      bar.appendChild(_btn('替换选区', 'primary', 'replace'));
      bar.appendChild(_btn('插入到后面', '', 'append'));
    } else if (snapshot.toolCall) {
      // No pinned selection but AI produced a structured tool call
      // (e.g. full-doc polish in 写入文档 mode) — allow applying it
      bar.appendChild(_btn('应用到文档', 'primary', 'replace'));
      bar.appendChild(_btn('插入到末尾', '', 'append'));
    } else if (snapshot.outputMode && snapshot.outputMode !== 'chat') {
      // In "写入文档" mode — offer direct write even without explicit selection/tool call
      bar.appendChild(_btn('写入文档', 'primary', 'replace'));
      bar.appendChild(_btn('插入到末尾', '', 'append'));
    } else {
      // Pure chat reply with no selection and no tool call
      bar.appendChild(_btn('插入到文档末尾', 'primary', 'append'));
    }
    bar.appendChild(_btn('仅查看', 'muted', 'view'));
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

  // ── Hide welcome card on first message ──
  function _hideWelcome() {
    const w = $('wa-ai-welcome');
    if (w && w.style.display !== 'none') w.style.display = 'none';
  }

  // ── Scenario card clicked — put text into input ──
  window.WA.useScenario = (text) => {
    _hideWelcome();
    const input = document.getElementById('wa-user-input');
    if (input) {
      input.value = text;
      input.focus();
      autoResize(input);
    }
  };

  window.WA.sendMessage = () => {
      const input = $('wa-user-input');
      const text = input.value.trim();
      if (state.isLoading) return;

      if (!text) return;

      // Guard: block send if any attached files are still loading
      if (state._aiFileContext && state._aiFileContext.some(f => f.loading)) {
        const loadingNames = state._aiFileContext.filter(f => f.loading).map(f => f.name).join(', ');
        showToast(`请等待文件读取完成：${loadingNames}`, 'warning');
        return;
      }

      // Capture and clear pinned selection before rendering
      const pinnedSel = state.pinnedSelection;
      state.lastPinnedSel = pinnedSel || null;
      state.pendingToolCall = null;
      if (pinnedSel) WA.clearSelection();

      const msgs = $('wa-ai-messages');
      _hideWelcome();  // hide welcome card on first send

      // Add user message bubble — with optional Copilot-style quote block
      const uMsg = document.createElement('div');
      uMsg.className = 'wa-msg user';
      // Show attached files indicator in the message
      if (state._aiFileContext && state._aiFileContext.length) {
        const filesNote = document.createElement('div');
        filesNote.className = 'wa-msg-files-note';
        filesNote.textContent = `${state._aiFileContext.map(f => f.name).join(', ')}`;
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
      autoResize(input);

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
      const _isOpenFileIntent = (t) => /^(?:打开|open|查看|show|打开文件)?\s*[\w\u4e00-\u9fff\u3400-\u4dbf\-. ()（）]+\.(?:docx?|xlsx?|pptx?|pdf|txt|md|csv|json)\s*$/i.test(t || '');
      // Detect intents that benefit from the agent ReAct loop (multi-step tasks)
      const _isAgentIntent = (t) => {
        if (!t) return false;
        return /对比|比较|diff|合并|汇总多|可视化|画.*图|趋势|图表|批量|格式化整理|报告|审查|条款|风险|检查|校验|审校|分析.*数据|数据.*分析|执行.*代码|运行|chart|plot|merge|compare|batch|report/.test(t);
      };
      let fullMessage = text;
      const _hasAttachedTaskFiles = !!(state._aiFileContext && state._aiFileContext.length);
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

      state.conversation.push({ role: 'user', content: text });
      state.isLoading = true;

      // Pass doc_edit context so backend can inject the right system prompt
      const _isDocEdit = !!(state.fileName && state.aiOutputMode !== 'chat' && !_isReadOnlyIntent(text));

      // ── Route: Agent mode (full ReAct loop) vs. simple chat stream ──
      // Use agent mode when explicitly enabled or when the intent looks like
      // a task that benefits from multi-step tool use (data analysis, file
      // operations, code execution, comparison, batch processing).
      // Also always use agent when 2+ files are attached — multi-file operations
      // (import, compare, sync) require structured tool use that the basic chat
      // stream cannot provide, and local models struggle with large combined prompts.
      const _hasCurrentTaskFile = !!(state.fileName && context);
      const _hasOpenFileIntent = _isOpenFileIntent(text);
      const _hasTaskIntent = _isAgentIntent(text);
      const _useOpenClawTaskForCurrentFile = _hasCurrentTaskFile && (pinnedSel || _isDocEdit || _hasTaskIntent);
      const _useOpenClawTask = _hasAttachedTaskFiles || _useOpenClawTaskForCurrentFile || _hasTaskIntent || _hasOpenFileIntent;
      const _useGenericAgent = !_useOpenClawTask && state.useAgentMode;
      if (_useOpenClawTask) {
        const tIdx = state._aiTargetFileIdx;
        const targetFile = (tIdx >= 0 && tIdx < state._aiFileContext.length) ? state._aiFileContext[tIdx] : null;
        const referenceFiles = targetFile
          ? state._aiFileContext.filter((_, idx) => idx !== tIdx)
          : (state._aiFileContext || []);
        const taskMessage = _waBuildOpenClawTaskMessage(text, {
          currentFileName: state.fileName || '',
          targetFileName: targetFile ? targetFile.name : '',
          referenceFileNames: referenceFiles.map((file) => file.name),
          attachedFileNames: (state._aiFileContext || []).map((file) => file.name),
          pinnedSelection: pinnedSel || '',
        });
        _waSendToOpenClawTask(taskMessage, loadingEl, {
          model: state.lockedModel || 'auto',
          currentContent: context,
          openIntentText: text,
        });
      } else if (_useGenericAgent) {
        _waSendToAgent(fullMessage, loadingEl, {
          model:       state.lockedModel || 'auto',
          file_type:   state.fileType || '',
          allow_apply: !_isReadOnlyIntent(text),
        });
      } else {
        _waSendToChat(fullMessage, loadingEl, {
          model:    state.lockedModel || 'auto',
          doc_edit: _isDocEdit,
          file_type: state.fileType || '',
          has_sel:  !!pinnedSel,
          allow_apply: !_isReadOnlyIntent(text),
        });
      }
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
    if (isOpen) {
      _checkOllamaStatus();
      _refreshModelCatalog(true);
    }
  };

  // ── Skill Library overlay ──────────────────────────────────
  let _waSkillCache = {};

  const _waFetchSkills = async (force = false) => {
    const fileType = String(state.fileType || '').trim().toLowerCase();
    const cacheKey = fileType || '_all';
    if (!force && _waSkillCache[cacheKey]) return _waSkillCache[cacheKey];
    try {
      const query = fileType ? `?file_type=${encodeURIComponent(fileType)}` : '';
      const r = await fetch(`/api/editor/ai/skill-list${query}`);
      const d = await r.json();
      const skills = d && Array.isArray(d.skills) ? d.skills : [];
      _waSkillCache[cacheKey] = skills;
      return skills;
    } catch(e) {
      console.error('[WA] skill fetch failed', e);
    }
    _waSkillCache[cacheKey] = [];
    return [];
  };

  const _waToggleSkill = async (skillId, enabled) => {
    try {
      const r = await fetch(`/api/skills/${encodeURIComponent(skillId)}/toggle`, {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ enabled }),
      });
      const d = await r.json();
      return d.success !== false;
    } catch(e) { return false; }
  };

  const _waRenderSkillLibrary = async () => {
    const container = $('wa-skill-library');
    if (!container) return;

    // If already open, close it
    if (container.classList.contains('open')) {
      container.classList.remove('open');
      container.innerHTML = '';
      return;
    }

    const skills = await _waFetchSkills();
    if (!skills || !skills.length) {
      container.innerHTML = '<div style="padding:20px;color:var(--text-muted);text-align:center">暂无可用技能</div>';
      container.classList.add('open');
      return;
    }

    let searchText = '';

    // Build inner HTML structure
    container.innerHTML = `
      <div class="wa-skill-lib-header">
        <input type="text" class="wa-skill-lib-search" placeholder="🔍 搜索技能…" autocomplete="off">
        <button class="wa-skill-lib-close" title="关闭">✕</button>
      </div>
      <div class="wa-skill-lib-grid"></div>
      <div class="wa-skill-lib-footer"></div>
    `;
    container.classList.add('open');

    const grid   = container.querySelector('.wa-skill-lib-grid');
    const footer = container.querySelector('.wa-skill-lib-footer');

    const renderGrid = (list) => {
      grid.innerHTML = '';
      if (!list.length) {
        grid.innerHTML = '<div class="wa-skill-lib-empty">暂无匹配的技能</div>';
        return;
      }
      list.forEach(skill => {
        const card = document.createElement('div');
        card.className = 'wa-skill-lib-card';
        card.style.cursor = 'pointer';

        const schema = skill.params_schema || {};
        const fileTypes = Object.values(schema)
          .filter(s => s.type === 'file' || s.type === 'file_list')
          .map(s => s.accept || s.label || '文件')
          .join('、') || '任意文件';

        card.innerHTML = `
          <div class="wa-skill-lib-card-top">
            <span class="wa-skill-lib-card-icon">${skill.icon||'🧠'}</span>
            <span class="wa-skill-lib-card-name">${_escHtml(skill.name||skill.id)}</span>
            <span class="wa-skill-lib-card-arrow">▸</span>
          </div>
          <div class="wa-skill-lib-card-desc">${_escHtml(skill.description||'')}</div>
          <div class="wa-skill-lib-card-detail" style="display:none">
            <div class="wa-skill-detail-body">
              <p class="wa-skill-detail-full">${_escHtml(skill.long_desc || skill.description || '暂无详细说明')}</p>
              <p class="wa-skill-detail-req">📎 适用：${_escHtml(fileTypes)}</p>
              <p class="wa-skill-detail-guide">点击按钮后将直接按文件任务模式执行</p>
            </div>
            <button class="wa-skill-start-btn">立即执行</button>
          </div>
        `;

        // Click card header to toggle detail
        card.querySelector('.wa-skill-lib-card-top').addEventListener('click', (e) => {
          e.stopPropagation();
          const detail = card.querySelector('.wa-skill-lib-card-detail');
          const arrow = card.querySelector('.wa-skill-lib-card-arrow');
          const isOpen = detail.style.display !== 'none';
          // Close all other details first
          grid.querySelectorAll('.wa-skill-lib-card-detail').forEach(d => { d.style.display = 'none'; });
          grid.querySelectorAll('.wa-skill-lib-card-arrow').forEach(a => { a.textContent = '▸'; });
          grid.querySelectorAll('.wa-skill-lib-card').forEach(c => c.classList.remove('expanded'));
          if (!isOpen) {
            detail.style.display = 'block';
            arrow.textContent = '▾';
            card.classList.add('expanded');
          }
        });

        card.querySelector('.wa-skill-start-btn').addEventListener('click', (e) => {
          e.stopPropagation();
          container.classList.remove('open');
          container.innerHTML = '';
          _hideWelcome();
          const input = $('wa-user-input');
          if (!input) return;
          input.value = `请使用「${skill.name || skill.id}」处理当前文件任务：${skill.description || ''}`;
          input.focus();
          autoResize(input);
          if ((state._aiFileContext && state._aiFileContext.length) || state.fileName) {
            WA.sendMessage();
          }
        });

        grid.appendChild(card);
      });
    };

    const renderAll = () => {
      const filtered = skills.filter(skill =>
        !searchText ||
        (skill.name||'').toLowerCase().includes(searchText) ||
        (skill.description||'').toLowerCase().includes(searchText)
      );
      renderGrid(filtered);
      footer.innerHTML = `共 ${skills.length} 个技能`;
    };

    container.querySelector('.wa-skill-lib-close').addEventListener('click', () => {
      container.classList.remove('open');
      container.innerHTML = '';
    });
    container.querySelector('.wa-skill-lib-search').addEventListener('input', e => {
      searchText = e.target.value.trim().toLowerCase();
      renderAll();
    });

    renderAll();
  };

  window.WA.toggleSkillLibrary = () => _waRenderSkillLibrary();

  window.WA.toggleWorkflowPanel = () => _waRenderSkillLibrary();

  function _refreshWorkflowChips() {}

  async function _appendWorkflowChips() {}

  async function _suggestWorkflows() {}

  // ── AI display mode: 'panel' (right side) or 'inline' (bottom of canvas) ──
  window.WA.setAIDisplayMode = (mode) => {
    if (mode !== 'panel' && mode !== 'inline') return;
    state.aiDisplayMode = mode;
    localStorage.setItem('wa_ai_display_mode', mode);

    const aiPanel = $('wa-ai');
    const inlineAi = $('wa-inline-ai');

    // Toggle buttons
    document.querySelectorAll('.wa-display-mode-toggle button[data-dm]').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.dm === mode);
    });

    if (mode === 'inline') {
      // Show inline dialog at bottom of canvas — AI panel stays visible
      if (inlineAi) inlineAi.style.display = 'flex';
    } else {
      // Hide inline dialog, AI panel stays as-is
      if (inlineAi) inlineAi.style.display = 'none';
    }
  };

  // ── Inline AI dialog messaging ──
  window.WA.sendInlineMessage = () => {
    const input = $('wa-iai-input');
    const text = input.value.trim();
    if (!text || state.isLoading) return;

    const pinnedSel = state.pinnedSelection;
    state.lastPinnedSel = pinnedSel || null;
    state.pendingToolCall = null;
    if (pinnedSel) WA.clearSelection();

    const msgArea = $('wa-iai-messages');
    _hideWelcome();

    // User message
    const uMsg = document.createElement('div');
    uMsg.className = 'wa-iai-msg user';
    if (pinnedSel) {
      const q = document.createElement('div');
      q.style.cssText = 'font-size:11px;font-style:italic;color:var(--text-muted);margin-bottom:2px;overflow:hidden;-webkit-line-clamp:2;-webkit-box-orient:vertical;display:-webkit-box;';
      q.textContent = pinnedSel.length > 120 ? pinnedSel.substring(0, 120) + '…' : pinnedSel;
      uMsg.appendChild(q);
    }
    const uContent = document.createElement('span');
    uContent.textContent = text;
    uMsg.appendChild(uContent);
    msgArea.appendChild(uMsg);

    // AI streaming bubble
    const aiMsg = document.createElement('div');
    aiMsg.className = 'wa-iai-msg ai streaming';
    msgArea.appendChild(aiMsg);
    msgArea.scrollTop = msgArea.scrollHeight;

    input.value = '';
    autoResize(input);

    // Build context (same logic as sendMessage)
    const MAX_CONTEXT = 6000;
    let contextRaw = state.activeEditor ? state.activeEditor.getContent() : '';
    const context = contextRaw.length > MAX_CONTEXT
        ? contextRaw.substring(0, MAX_CONTEXT) + '\n…[内容过长已截断]'
        : contextRaw;
    const fileType = state.fileType || 'general';

    let fullMessage = text;
    if (state.fileName && context) {
      const selHint = pinnedSel
        ? `\n\n[用户选中的文字]\n"${pinnedSel.length > 500 ? pinnedSel.substring(0, 500) + '…' : pinnedSel}"\n`
        : '';
      fullMessage = `[工作区文档助手模式]\n当前文件: ${state.fileName} (${fileType})\n\n文档内容:\n${context}${selHint}\n\n用户指令: ${text}`;
    }

    state.conversation.push({ role: 'user', content: text });
    state.isLoading = true;

    // Stream to the inline dialog's AI bubble
    _waSendToInline(fullMessage, aiMsg, {
      model: state.lockedModel || 'auto',
    });
  };

  window.WA.handleInlineInputKeydown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      WA.sendInlineMessage();
    }
  };

  window.WA.inlineQuickAction = (text) => {
    $('wa-iai-input').value = text;
    WA.sendInlineMessage();
  };

  // Lightweight streaming handler for inline dialog (reuses fetch logic from _waSendToChat)
  async function _waSendToInline(message, loadingEl, opts) {
    opts = opts || {};
    const msgArea = $('wa-iai-messages');
    let fullText = '';
    let streamBuffer = '';
    const renderMd = (text) => {
      if (window.marked) { try { return window.marked.parse(text || ''); } catch(e) {} }
      return (text || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\n/g,'<br>');
    };
    const payload = {
      session:      _waSession(),
      message:      message,
      locked_task:  opts.task || 'CHAT',
      locked_model: opts.model || state.lockedModel || 'auto',
      doc_edit:     false,
      doc_file_type: state.fileType || '',
      doc_has_sel:  false,
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
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
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
            if (evt.type === 'classification') {
              _applyRouteEvent(evt);
              continue;
            }
            if (evt.type === 'token') {
              fullText += evt.content || '';
              const visible = fullText.replace(/<TOOL>[\s\S]*?<\/TOOL>/g, '').trim();
              if (loadingEl) loadingEl.innerHTML = renderMd(visible);
              if (msgArea) msgArea.scrollTop = msgArea.scrollHeight;
            } else if (evt.type === 'done') {
              if (loadingEl) {
                loadingEl.classList.remove('streaming');
                const visible = fullText.replace(/<TOOL>[\s\S]*?<\/TOOL>/g, '').trim();
                const finalText = visible || evt.content || '';
                loadingEl.innerHTML = renderMd(finalText);
                if (finalText) state.conversation.push({ role: 'assistant', content: finalText });
              }
              state.isLoading = false;
              return;
            } else if (evt.type === 'error') {
              if (loadingEl) {
                loadingEl.classList.remove('streaming');
                loadingEl.innerHTML = `<span style="color:var(--error,#ef4444)">${_escHtml(evt.message || 'AI 处理失败')}</span>`;
              }
              state.isLoading = false;
              return;
            }
          } catch(e) { /* ignore malformed SSE */ }
        }
      }
      // Stream ended without done
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
        if (loadingEl) {
          loadingEl.classList.remove('streaming');
          if (!loadingEl.textContent.trim()) loadingEl.textContent = '[已取消]';
        }
      } else {
        if (loadingEl) {
          loadingEl.classList.remove('streaming');
          loadingEl.textContent = `网络错误：${err.message}`;
        }
      }
      state.isLoading = false;
    } finally {
      state._streamAbortCtrl = null;
      _setStreamBtn(false);
    }
  }

  window.WA.toggleTheme = () => {
    const html = document.documentElement;
    const isDark = html.getAttribute('data-wa-theme') === 'dark';
    if (isDark) {
      html.removeAttribute('data-wa-theme');
      localStorage.setItem('koto_theme', 'light');
    } else {
      html.setAttribute('data-wa-theme', 'dark');
      localStorage.setItem('koto_theme', 'dark');
    }
    const btn = document.getElementById('wa-theme-toggle-btn');
    if (btn) btn.innerHTML = isDark ? _SUN_SVG : _MOON_SVG;
  };

  // Restore theme toggle button label on load
  (function _initThemeBtn() {
    const btn = document.getElementById('wa-theme-toggle-btn');
    if (!btn) return;
    const isDark = document.documentElement.getAttribute('data-wa-theme') === 'dark';
    btn.innerHTML = isDark ? _MOON_SVG : _SUN_SVG;
  })();

  const _MODEL_LABELS = {
    auto: 'Koto AI',
    local: 'Ollama',
    'gemini-3-flash-preview': 'Gemini 3 Flash Preview',
    'gemini-3-pro-preview': 'Gemini 3 Pro Preview',
    'gemini-3.1-pro-preview': 'Gemini 3.1 Pro Preview',
    'gemini-2.5-flash': 'Gemini 2.5 Flash',
    'gemini-2.5-flash-lite': 'Gemini 2.5 Flash Lite',
    'gemini-2.5-pro': 'Gemini 2.5 Pro',
  };

  function _normalizeEditorLockedModel(modelId) {
    if (!modelId || ['auto', 'local'].includes(modelId)) return '';
    return modelId;
  }

  function _selectedCloudModelId() {
    return (state.lockedModel && !['auto', 'local'].includes(state.lockedModel))
      ? state.lockedModel
      : '';
  }

  function _clearActiveRoute() {
    state._activeRoute = null;
  }

  function _lookupModelMeta(modelId) {
    if (!modelId) return null;
    return (state._availableModels || []).find(model => model.id === modelId) || null;
  }

  function _modelDisplayName(modelId, fallback) {
    if (!modelId) return fallback || 'Koto AI';
    if (modelId === 'local') return 'Ollama';
    const meta = _lookupModelMeta(modelId);
    if (meta && meta.display) return meta.display;
    return _MODEL_LABELS[modelId] || fallback || modelId;
  }

  function _syncModelStatusUi() {
    const badge = $('wa-ai-model-badge');
    const footerName = $('wa-footer-model-name');
    const routeInfo = $('wa-ai-route-info');
    const explicitCloudModel = _selectedCloudModelId();
    const activeRoute = state._activeRoute || null;

    const modelLabel = activeRoute?.modelDisplay
      || (state.lockedModel === 'local'
        ? 'Ollama'
        : (explicitCloudModel ? _modelDisplayName(explicitCloudModel, explicitCloudModel) : 'Koto AI'));

    if (badge) {
      badge.textContent = modelLabel;
      badge.title = modelLabel;
    }
    if (footerName) {
      footerName.textContent = modelLabel;
      footerName.title = modelLabel;
    }

    if (!routeInfo) return;

    const routeBits = [];
    if (state.lockedModel === 'local') routeBits.push('本地优先');
    else if (explicitCloudModel) routeBits.push('已锁定模型');
    else if (activeRoute) routeBits.push('自动路由');

    if (activeRoute?.taskDisplay) routeBits.push(activeRoute.taskDisplay);
    if (activeRoute?.routeMethod) routeBits.push(activeRoute.routeMethod);
    if (!activeRoute?.taskDisplay && !activeRoute?.routeMethod && activeRoute?.message) {
      routeBits.push(activeRoute.message);
    }

    if (!routeBits.length) {
      routeInfo.style.display = 'none';
      routeInfo.textContent = '';
      routeInfo.removeAttribute('title');
      return;
    }

    const routeText = routeBits.join(' · ');
    routeInfo.style.display = '';
    routeInfo.textContent = routeText;
    routeInfo.title = routeText;
  }

  function _applyRouteEvent(evt) {
    if (!evt || typeof evt !== 'object') return;

    const routeModelId = evt.model || (state.lockedModel === 'local' ? 'local' : '');
    const taskDisplay = evt.task_display || evt.task_type || '';
    const routeMethod = evt.route_method || evt.workflow || evt.pattern || '';
    const routeMessage = evt.message || '';

    state._activeRoute = {
      modelId: routeModelId,
      modelDisplay: evt.model_display || _modelDisplayName(routeModelId, routeModelId || 'Koto AI'),
      taskDisplay,
      routeMethod,
      message: routeMessage,
    };

    _syncModelStatusUi();
  }

  function _refreshModelCatalog(force = false) {
    if (state._modelCatalogPromise && !force) return state._modelCatalogPromise;

    const request = fetch('/api/v1/models', { cache: 'no-store' })
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
      })
      .then((data) => {
        state._modelsReady = !!(data && data.ready);
        state._modelMap = (data && data.model_map) || {};
        state._availableModels = Array.isArray(data?.available) ? data.available : [];
        _syncModelStatusUi();
        return data;
      })
      .catch((error) => {
        console.warn('[WA] model catalog fetch failed:', error);
        state._modelsReady = false;
        state._modelMap = {};
        state._availableModels = state._availableModels || [];
        _syncModelStatusUi();
        return null;
      })
      .finally(() => {
        if (state._modelCatalogPromise === request) state._modelCatalogPromise = null;
      });

    state._modelCatalogPromise = request;
    return request;
  }

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
          txt.textContent = `Ollama 运行中 (${data.model || 'qwen3:8b'})`;
          if (onBtn) { onBtn.disabled = false; onBtn.title = '使用本地 Ollama 模型'; }
        } else {
          row.style.display = 'block';
          txt.textContent = 'Ollama 未运行，无法切换到本地模型';
          if (onBtn) { onBtn.disabled = true; onBtn.title = '请先启动 Ollama'; }
        }
      })
      .catch(() => {});
  }

  function _syncEditorModelPreference(mode, lockedModel) {
    const editorMode = mode === 'local' ? 'local' : 'auto';
    const editorLockedModel = editorMode === 'local'
      ? ''
      : _normalizeEditorLockedModel(lockedModel);

    localStorage.setItem('editor_model_mode', editorMode);
    if (editorLockedModel) {
      localStorage.setItem('editor_locked_model', editorLockedModel);
    } else {
      localStorage.removeItem('editor_locked_model');
    }

    try {
      window.__koto?.aiPanel?.notifyModelChange?.(editorMode === 'local' ? 'local' : (editorLockedModel || 'auto'));
    } catch (_) { /* best-effort UI sync only */ }
  }

  window.WA.setUseLocalModel = (useLocal) => {
    const newModel = useLocal ? 'local' : 'auto';
    state.lockedModel = newModel;
    localStorage.setItem('wa_locked_model', newModel);
    _clearActiveRoute();
    _syncEditorModelPreference(newModel, newModel);
    // Update local model toggle buttons
    document.querySelectorAll('[data-local-mode]').forEach(btn => {
      btn.classList.toggle('active', (btn.dataset.localMode === 'on') === useLocal);
    });
    _syncModelStatusUi();
    // Persist to server so file-editor AI (editor_ai_stream) also respects the choice
    fetch('/api/local-model/switch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode: newModel === 'local' ? 'local' : 'cloud' }),
    }).catch(() => {/* silent — localStorage state still works for chat/stream path */});
  };

  window.WA.setLockedModel = (val) => {
    window.WA.setUseLocalModel(val === 'local');
  };

  // Notify Python of dirty-state changes so _on_closing never needs evaluate_js
  // (avoids EdgeChromium COM deadlock that caused "未响应" on every close).
  function _notifyPyModified(tab, modified) {
    if (!tab) return;
    try {
      if (window.pywebview && window.pywebview.api && window.pywebview.api.mark_file_modified) {
        window.pywebview.api.mark_file_modified(tab.path || '', tab.name || '', modified);
      }
    } catch (_e) { /* non-fatal */ }
  }

  window.WA.scheduleAutoSave = () => {
    if (!state.fileId || !state.fileType || state.fileType === 'pdf' || state.fileType === 'image') return;
    // Mark active tab as modified (dirty indicator)
    const tab = state.openTabs.find(t => t.path === state.activeTabPath);
    if (tab && !tab.modified) { tab.modified = true; _notifyPyModified(tab, true); _renderTabs(); }
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
    if (!state.activeEditor || !state.fileId || !state.fileType || state.fileType === 'pdf' || state.fileType === 'image') return;
    const status = $('wa-autosave-status');
    try {
      const tab = state.openTabs.find(t => t.path === state.activeTabPath);
      if (!_ensureDocxCanSave(tab, false)) {
        if (status) { status.className = ''; status.textContent = ''; }
        return;
      }
      const data = _serializeEditorForTab(tab, state.activeEditor);
      // Always update in-memory cache
      if (tab && data && state.fileType !== 'docx') {
        tab.cache = data;
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
      const json = await _safeJson(res);
      if (!res.ok) throw new Error(json.error || '自动保存失败');
      if (tab) { tab.modified = false; _notifyPyModified(tab, false); _renderTabs(); }
      if (status) {
        status.className = 'saved';
        status.textContent = `已自动保存 ${json.saved_at}`;
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
          const data = _serializeEditorForTab(tab, state.activeEditor);
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

    if (!_ensureDocxCanSave(_saveTab, true)) return;

    const data = _serializeEditorForTab(_saveTab, state.activeEditor);
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
    const _saveJson = await _safeJson(res);
    if (!res.ok) throw new Error(_saveJson.error || '保存失败');
    if (_saveTab) {
      _saveTab.modified = false;
      _notifyPyModified(_saveTab, false);
      if (_saveFileType !== 'docx') _saveTab.cache = data;
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
    showToast('已保存', 'success');
  }

  // 保存 — save directly to the original local file (Ctrl+S)
  // If the file was opened from disk, writes back via its FileSystemFileHandle.
  // Otherwise saves to Koto workspace only.
  window.WA.saveFile = async () => {
    if (!state.activeEditor || !state.fileType || state.fileType === 'pdf' || state.fileType === 'image') return;
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
      const isPdf = (state.fileType === 'pdf' || state.fileType === 'image');
      btn.disabled    = isPdf;
      if (btnAs) btnAs.disabled = isPdf;
    }
  };

  // 另存为 — always shows the system file picker so the user can choose a new path
  window.WA.saveAs = async () => {
    if (!state.activeEditor || !state.fileType || state.fileType === 'pdf' || state.fileType === 'image') return;
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
      const isPdf = (state.fileType === 'pdf' || state.fileType === 'image');
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
        showToast(`已归档到「${category}」文件夹`, 'success');
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
      showToast('已恢复，正在重新加载…', 'success');
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
  async function _openFilePicker(opts) {
    opts = opts || {};
    const allowMultiple = !!opts.multiple;
    const fallbackInput = $(opts.fallbackInputId || 'wa-file-input');
    if (window.showOpenFilePicker) {
      try {
        const handles = await window.showOpenFilePicker({
          multiple: allowMultiple,
          types: [{ description: 'Documents', accept: {
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx'],
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
            'application/vnd.openxmlformats-officedocument.presentationml.presentation': ['.pptx'],
            'application/pdf': ['.pdf'],
          }}, { description: 'Images', accept: {
            'image/*': ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.svg'],
          }}],
        });
        if (!handles.length) return;
        const files = [];
        for (const handle of handles) {
          const file = await handle.getFile();
          file._fsHandle = handle;  // attach handle so Router.load can store it
          files.push(file);
        }
        if (allowMultiple) {
          loadFiles(files);
        } else {
          Router.load(files[0]);
        }
      } catch (e) {
        if (e.name !== 'AbortError') showToast('无法打开文件: ' + e.message, 'error');
      }
    } else {
      if (fallbackInput) fallbackInput.click();
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
  fileInput.addEventListener('change', (e) => {
    if (e.target.files.length) loadFiles(e.target.files);
    e.target.value = '';
  });

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
  fileInputLeft.addEventListener('change', (e) => {
    if (e.target.files.length) loadFiles(e.target.files);
    e.target.value = '';
  });

  window.WA.openSystemFileList = function () {
    _openFilePicker({ multiple: true, fallbackInputId: 'wa-file-input-left' });
  };

  // Whole-canvas drag-drop (works even when a file is already open)
  const canvas = $('wa-canvas');
  canvas.addEventListener('dragover', (e) => { e.preventDefault(); });
  canvas.addEventListener('drop', (e) => {
    e.preventDefault();
    if (e.dataTransfer.files.length) loadFiles(e.dataTransfer.files);
  });

  // ── OS image file drag → insert into open docx (window capture phase) ─────
  // WHY capture phase (not bubble on canvas):
  //   TipTap/ProseMirror delegates events at the document listener level.
  //   A bubble-phase handler on #wa-canvas cannot beat ProseMirror's
  //   delegation.  Registering at window capture phase (same
  //   technique as chart drag above) with stopImmediatePropagation() ensures
  //   ProseMirror never sees the event.
  const _IMG_DROP_EXTS = new Set(['png','jpg','jpeg','gif','bmp','webp','svg']);
  function _hasImageFiles(dt) {
    if (!dt || !dt.files || !dt.files.length) return false;
    for (let i = 0; i < dt.files.length; i++) {
      const f = dt.files[i];
      const ext = (f.name || '').split('.').pop().toLowerCase();
      if (_IMG_DROP_EXTS.has(ext) || (f.type && f.type.startsWith('image/'))) return true;
    }
    return false;
  }

  // dragover capture: preventDefault so the browser allows 'drop' to fire
  window.addEventListener('dragover', (e) => {
    if (state.fileType !== 'docx' || !state.activeEditor) return;
    const waCanvasEl = document.getElementById('wa-canvas');
    if (!waCanvasEl || !waCanvasEl.contains(e.target)) return;
    if (!e.dataTransfer.types.includes('Files')) return; // must be OS file drag
    e.preventDefault();
    e.dataTransfer.dropEffect = 'copy';
  }, true);

  // drop capture: intercept OS image files before Slate/React sees them
  window.addEventListener('drop', (e) => {
    if (state.fileType !== 'docx' || !state.activeEditor || !state.activeEditor.editor) return;
    const waCanvasEl = document.getElementById('wa-canvas');
    if (!waCanvasEl || !waCanvasEl.contains(e.target)) return;
    if (!_hasImageFiles(e.dataTransfer)) return;

    e.preventDefault();
    e.stopPropagation();
    e.stopImmediatePropagation(); // blocks Slate's document-level delegation

    const files = Array.from(e.dataTransfer.files);
    const imgFiles = files.filter(f => {
      const ext = (f.name || '').split('.').pop().toLowerCase();
      return _IMG_DROP_EXTS.has(ext) || (f.type && f.type.startsWith('image/'));
    });
    const otherFiles = files.filter(f => !imgFiles.includes(f));

    imgFiles.forEach(imgFile => {
      const reader = new FileReader();
      reader.onload = () => {
        const dataUri = reader.result;
        fetch('/api/v1/workspace/upload_image', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ data: dataUri }),
        })
          .then(r => r.ok ? r.json() : Promise.reject(r.status))
          .then(res => {
            const imgUrl = (res && res.url) ? res.url : dataUri;
            state.activeEditor.applyToolCall({ type: 'insert_image', src: imgUrl, alt: imgFile.name });
            showToast('图片已插入文档', 'success');
          })
          .catch(() => {
            state.activeEditor.applyToolCall({ type: 'insert_image', src: dataUri, alt: imgFile.name });
            showToast('图片已插入文档（本地模式）', 'success');
          });
      };
      reader.readAsDataURL(imgFile);
    });
    if (otherFiles.length) loadFiles(otherFiles);
  }, true);



  // Init
  initSocket();
  // Restore AI display mode preference
  if (state.aiDisplayMode === 'inline') {
    WA.setAIDisplayMode('inline');
  }
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
  // (prevents rich editors like TipTap/Univer from swallowing drag events)
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
    pick.innerHTML = `<div style="font-weight:700;margin-bottom:10px;font-size:13px">${_FOLDER_PICK_SVG} 选择要打开的文件</div>` +
      files.map((f, i) => {
        const icon = _EXT_ICON[f.name.split('.').pop().toLowerCase()] || _DEFAULT_FILE_SVG;
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
    if (!e.target.closest('#wa-save-split')) WA._closeSaveMenu();
  });

  // ── Save split-button dropdown ─────────────────────────────────────────────
  window.WA.toggleSaveMenu = function (e) {
    if (e) e.stopPropagation();
    const dd = $('wa-save-dropdown');
    if (!dd) return;
    dd.style.display = dd.style.display === 'none' ? 'block' : 'none';
  };
  window.WA._closeSaveMenu = function () {
    const dd = $('wa-save-dropdown');
    if (dd) dd.style.display = 'none';
  };

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

    // Initialise Split.js now that the container is visible (deferred in embedded mode).
    // Double-rAF ensures the browser has fully committed layout before Split.js
    // measures element sizes via getBoundingClientRect().
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        _initSplit();
        if (window._waSplit) {
          try { window._waSplit.setSizes(_savedSplitSizes || [15, 55, 30]); } catch {}
        }
      });
    });
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
            requestAnimationFrame(() => {
              const dz = parseFloat(sheetEl.dataset.dpiZoom);
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

  // Ctrl+K — Focus inline AI input (when in inline mode) or right panel input
  document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
      // Don't intercept in contentEditable or dedicated inputs
      const f = document.activeElement;
      if (f && f.isContentEditable) return;
      e.preventDefault();
      if (state.aiDisplayMode === 'inline') {
        const iaiInput = $('wa-iai-input');
        if (iaiInput) iaiInput.focus();
      } else {
        const waInput = $('wa-user-input');
        if (waInput) waInput.focus();
      }
    }
  });

  // Keep the save-caret button in sync with the save button's disabled state
  (function _syncSaveCaret() {
    const saveBtn = $('wa-save-btn');
    const caret   = $('wa-save-caret');
    if (!saveBtn || !caret) return;
    const sync = () => { caret.disabled = saveBtn.disabled; };
    sync();
    new MutationObserver(sync).observe(saveBtn, { attributes: true, attributeFilter: ['disabled'] });
  })();

  // ── Auto-restore embedded workspace view on page reload ──
  if (document.getElementById('workspaceView') && localStorage.getItem('koto.inWorkspace') === '1') {
    // Defer so the rest of the page finishes rendering first
    requestAnimationFrame(() => {
      if (typeof window.WA?.openInMainView === 'function') {
        window.WA.openInMainView();
      }
    });
  }

})();
