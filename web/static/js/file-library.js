/**
 * Koto 智能文件库 — file-library.js
 *
 * 所有功能通过全局 FL 对象暴露，无框架依赖。
 * 数据流：
 *   mounts (localStorage + API) → fileTree (API) → viewer (Monaco / HTML embed)
 *   notebooks (API) → file cards → AI chat (SSE)
 *   Socket.IO /files namespace → real-time tree updates
 */

'use strict';

/* ═══════════════════════════════════════════════════════
   STATE
═══════════════════════════════════════════════════════ */
const _state = {
  // UI
  viewMode: localStorage.getItem('fl_view_mode') || 'tree',
  rightPanelOpen: localStorage.getItem('fl_right_panel') !== 'false',
  openFolders: new Set(JSON.parse(localStorage.getItem('fl_open_folders') || '[]')),
  sectionOpen: JSON.parse(localStorage.getItem('fl_sections') || '{"mounts":true,"notebooks":true,"tags":false}'),

  // Data
  mounts: [],
  notebooks: [],
  activeMount: null,    // {path, name}
  activeNotebook: null, // {id, name, color}
  treeCache: {},        // path → tree array
  allTags: [],
  activeTag: null,

  // Tabs
  tabs: [],             // [{id, path, name, category, content, renderedHtml}]
  activeTab: null,

  // Notebooks
  nbFiles: [],          // files in current notebook

  // Chat
  chatHistory: [],
  chatStreaming: false,

  // Context menu target
  ctxTarget: null,      // {path, name, category}

  // Mount dialog
  mountBrowsePath: null,
  mountSelectedPath: null,

  // Add-to-notebook dialog
  addNbTargetPaths: [],

  // Monaco
  monacoInstances: {},  // tabId → monaco editor instance

  // Socket
  socket: null,

  // Search
  searchQuery: '',

  // Debounce timers
  _debounceTimers: {},
};

/* ═══════════════════════════════════════════════════════
   UTILS
═══════════════════════════════════════════════════════ */
function _debounce(key, fn, ms = 120) {
  clearTimeout(_state._debounceTimers[key]);
  _state._debounceTimers[key] = setTimeout(fn, ms);
}

function _el(id) { return document.getElementById(id); }

function _categoryIcon(cat, ext) {
  const icons = {
    pdf: '📕', word: '📘', spreadsheet: '📗', presentation: '📙',
    csv: '📊', markdown: '📝', code: '📄', text: '📄', image: '🖼️',
  };
  return icons[cat] || '📄';
}

function _extIcon(ext) {
  const m = {
    py: '🐍', js: '📜', ts: '📜', json: '📋', html: '🌐', css: '🎨',
    sql: '🗄️', sh: '💻', bat: '💻', r: '📊', ipynb: '📓',
    md: '📝', pdf: '📕', docx: '📘', doc: '📘', xlsx: '📗', xls: '📗',
    pptx: '📙', ppt: '📙', csv: '📊', txt: '📄',
    png: '🖼️', jpg: '🖼️', jpeg: '🖼️', gif: '🖼️', svg: '🖼️', webp: '🖼️',
  };
  return m[ext] || '📄';
}

function _timeAgo(ms) {
  const diff = Date.now() - ms;
  if (diff < 60000) return '刚刚';
  if (diff < 3600000) return `${Math.floor(diff / 60000)} 分钟前`;
  if (diff < 86400000) return `${Math.floor(diff / 3600000)} 小时前`;
  return `${Math.floor(diff / 86400000)} 天前`;
}

function _escapeHtml(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function _status(msg, right = '') {
  const t = _el('flStatusText');
  const r = _el('flStatusRight');
  if (t) t.textContent = msg;
  if (r) r.textContent = right;
}

/* ═══════════════════════════════════════════════════════
   THEME
═══════════════════════════════════════════════════════ */
function _applyTheme(theme) {
  document.body.setAttribute('data-theme', theme);
  localStorage.setItem('fl_theme', theme);
}

/* ═══════════════════════════════════════════════════════
   SOCKET.IO — /files namespace (real-time watch)
═══════════════════════════════════════════════════════ */
function _initSocket() {
  if (typeof io === 'undefined') return;
  try {
    _state.socket = io('/files', { transports: ['websocket', 'polling'] });

    _state.socket.on('connect', () => {
      const ws = _el('flStatusWs');
      if (ws) { ws.textContent = '●'; ws.className = 'fl-status-ws online'; }
    });

    _state.socket.on('disconnect', () => {
      const ws = _el('flStatusWs');
      if (ws) { ws.textContent = '●'; ws.className = 'fl-status-ws offline'; }
    });

    _state.socket.on('file_change', (data) => {
      _debounce('fs_change_' + (data.path || ''), () => {
        _handleFileChange(data);
      }, 200);
    });
  } catch (e) {
    console.warn('[FL] Socket init failed:', e);
  }
}

function _handleFileChange(data) {
  const { event, path } = data;
  // Invalidate tree cache for affected mount
  for (const mount of _state.mounts) {
    if (path && path.startsWith(mount.path)) {
      delete _state.treeCache[mount.path];
      // If this mount is currently shown, refresh
      if (_state.activeMount && _state.activeMount.path === mount.path) {
        _loadTree(mount.path, true).then(() => {
          _flashTreeNode(path);
        });
      }
      break;
    }
  }
  _status(`文件变动: ${event} — ${path.split(/[\\/]/).pop()}`);
}

function _flashTreeNode(path) {
  const el = document.querySelector(`.fl-tree-item[data-path="${CSS.escape(path)}"]`);
  if (el) {
    el.classList.remove('fl-changed');
    void el.offsetWidth; // reflow
    el.classList.add('fl-changed');
    setTimeout(() => el.classList.remove('fl-changed'), 800);
  }
}

/* ═══════════════════════════════════════════════════════
   MOUNTS
═══════════════════════════════════════════════════════ */
async function _loadMounts() {
  try {
    const r = await fetch('/api/file-library/mounts');
    const d = await r.json();
    _state.mounts = d.mounts || [];
    _renderMountsList();
    // Auto-show first mount if nothing active
    if (_state.mounts.length > 0 && !_state.activeMount && !_state.activeNotebook) {
      _selectMount(_state.mounts[0]);
    }
    if (_state.mounts.length === 0) {
      _showWelcome();
    }
  } catch (e) {
    console.warn('[FL] loadMounts error:', e);
  }
}

function _renderMountsList() {
  const el = _el('fl-mounts-list');
  if (!el) return;
  if (_state.mounts.length === 0) {
    el.innerHTML = '<div style="padding:6px 14px;font-size:12px;color:var(--fl-text3)">暂无挂载文件夹</div>';
    return;
  }
  el.innerHTML = _state.mounts.map(m => {
    const isActive = _state.activeMount && _state.activeMount.path === m.path;
    return `<div class="fl-mount-item ${isActive ? 'active' : ''}" 
                 onclick="FL._selectMount(${JSON.stringify(m).replace(/"/g, '&quot;')})"
                 title="${_escapeHtml(m.path)}">
      <svg class="fl-mount-item-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
      </svg>
      <span class="fl-mount-item-name">${_escapeHtml(m.name || m.path.split(/[\\/]/).pop())}</span>
      <div class="fl-mount-item-actions">
        <button class="fl-icon-btn" onclick="FL._unmount('${m.path.replace(/'/g, "\\'")}');event.stopPropagation()" title="卸载">
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
        </button>
      </div>
    </div>`;
  }).join('');
}

function _selectMount(mount) {
  _state.activeMount = mount;
  _state.activeNotebook = null;
  _renderMountsList();
  _renderNotebooksList();
  _el('flNpFiles').style.display = 'none';
  _el('flNpTitle').textContent = mount.name || mount.path.split(/[\\/]/).pop();
  _loadTree(mount.path);
}

async function _unmount(path) {
  if (!confirm(`卸载 "${path.split(/[\\/]/).pop()}"？`)) return;
  await fetch('/api/file-library/mounts', {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path }),
  });
  _state.treeCache[path] = undefined;
  await _loadMounts();
}

/* ═══════════════════════════════════════════════════════
   TREE LOADING & RENDERING
═══════════════════════════════════════════════════════ */
async function _loadTree(rootPath, forceRefresh = false) {
  _showTreeContainer(rootPath);
  if (!forceRefresh && _state.treeCache[rootPath]) {
    _renderTree(_state.treeCache[rootPath], rootPath);
    return;
  }
  _status('加载文件树…');
  try {
    const r = await fetch(`/api/file-library/tree?root=${encodeURIComponent(rootPath)}`);
    const d = await r.json();
    if (d.tree) {
      _state.treeCache[rootPath] = d.tree;
      _renderTree(d.tree, rootPath);
    }
    _status('就绪', `${_countFiles(d.tree || [])} 个文件`);
  } catch (e) {
    _status('加载失败: ' + e.message);
  }
}

function _countFiles(items) {
  let n = 0;
  for (const it of items) {
    if (it.type === 'file') n++;
    else if (it.children) n += _countFiles(it.children);
  }
  return n;
}

function _showTreeContainer(rootPath) {
  _el('flWelcome').style.display = 'none';
  _el('flNotebookGrid').style.display = 'none';
  _el('flTreeContainer').style.display = '';
  const lbl = _el('flTreeRootLabel');
  if (lbl) lbl.textContent = rootPath;
  // Update breadcrumb
  _updateBreadcrumb([{ label: rootPath.split(/[\\/]/).pop(), path: rootPath }]);
}

function _renderTree(items, rootPath) {
  const body = _el('flTreeBody');
  if (!body) return;
  const q = _state.searchQuery.toLowerCase();
  body.innerHTML = _buildTreeHTML(items, 0, q);
  _restoreFolderState();
}

function _buildTreeHTML(items, depth, searchQ) {
  let html = '';
  for (const item of items) {
    if (searchQ && item.type === 'file' && !item.name.toLowerCase().includes(searchQ)) continue;
    const indent = depth * 14;
    if (item.type === 'folder') {
      const isOpen = _state.openFolders.has(item.path);
      const hasMatch = searchQ ? _treeHasMatch(item.children || [], searchQ) : true;
      if (searchQ && !hasMatch) continue;
      html += `<div class="fl-folder-group" data-folder="${_escapeHtml(item.path)}">
        <div class="fl-tree-item" data-path="${_escapeHtml(item.path)}" data-type="folder"
             onclick="FL._toggleFolder(this)"
             oncontextmenu="FL._showCtxMenu(event,${JSON.stringify({path:item.path,name:item.name,type:'folder'}).replace(/"/g,'&quot;')})">
          <span class="fl-tree-indent" style="width:${indent}px"></span>
          <span class="fl-tree-arrow ${isOpen ? 'open' : ''}">
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="9 18 15 12 9 6"/></svg>
          </span>
          <svg class="fl-tree-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
          </svg>
          <span class="fl-tree-name">${_escapeHtml(item.name)}</span>
          ${item.childCount ? `<span class="fl-tree-meta">${item.childCount}</span>` : ''}
        </div>
        <div class="fl-tree-children" style="display:${isOpen ? 'block' : 'none'}">
          ${isOpen ? _buildTreeHTML(item.children || [], depth + 1, searchQ) : ''}
        </div>
      </div>`;
    } else {
      const active = _state.activeTab && _state.activeTab.path === item.path;
      html += `<div class="fl-tree-item ${active ? 'active' : ''}" data-path="${_escapeHtml(item.path)}" data-type="file"
           draggable="true"
           onclick="FL._openFile(${JSON.stringify(item).replace(/"/g,'&quot;')})"
           ondragstart="FL._onDragStart(event,'${item.path.replace(/'/g, "\\'")}','${item.name.replace(/'/g, "\\'")}')"
           oncontextmenu="FL._showCtxMenu(event,${JSON.stringify({path:item.path,name:item.name,category:item.category,type:'file'}).replace(/"/g,'&quot;')})">
        <span class="fl-tree-indent" style="width:${indent}px"></span>
        <span class="fl-tree-arrow-placeholder"></span>
        <span class="fl-tree-icon">${_extIcon(item.ext || '')}</span>
        <span class="fl-tree-name">${_escapeHtml(item.name)}</span>
        <span class="fl-tree-meta">${item.size || ''}</span>
      </div>`;
    }
  }
  return html;
}

function _treeHasMatch(items, q) {
  for (const it of items) {
    if (it.name.toLowerCase().includes(q)) return true;
    if (it.type === 'folder' && _treeHasMatch(it.children || [], q)) return true;
  }
  return false;
}

function _toggleFolder(el) {
  const arrow = el.querySelector('.fl-tree-arrow');
  const path = el.dataset.path;
  const group = el.parentElement;
  const childEl = group.querySelector('.fl-tree-children');
  const isOpen = arrow.classList.contains('open');

  if (!isOpen) {
    // Open — may need to lazy-render children
    if (!childEl.innerHTML.trim() || childEl.innerHTML.trim() === '') {
      // Find node in tree
      const root = _state.activeMount ? _state.activeMount.path : '';
      const cached = _state.treeCache[root] || [];
      const node = _findTreeNode(cached, path);
      if (node && node.children) {
        childEl.innerHTML = _buildTreeHTML(node.children, _getDepth(el) + 1, _state.searchQuery.toLowerCase());
      }
    }
    childEl.style.display = 'block';
    arrow.classList.add('open');
    _state.openFolders.add(path);
  } else {
    childEl.style.display = 'none';
    arrow.classList.remove('open');
    _state.openFolders.delete(path);
  }
  localStorage.setItem('fl_open_folders', JSON.stringify([..._state.openFolders]));
}

function _getDepth(el) {
  const indent = el.querySelector('.fl-tree-indent');
  return indent ? Math.round(parseFloat(indent.style.width || 0) / 14) : 0;
}

function _findTreeNode(items, path) {
  for (const it of items) {
    if (it.path === path) return it;
    if (it.children) {
      const found = _findTreeNode(it.children, path);
      if (found) return found;
    }
  }
  return null;
}

function _restoreFolderState() {
  for (const path of _state.openFolders) {
    const el = document.querySelector(`.fl-tree-item[data-path="${CSS.escape(path)}"]`);
    if (el) {
      const arrow = el.querySelector('.fl-tree-arrow');
      const group = el.parentElement;
      const childEl = group && group.querySelector('.fl-tree-children');
      if (arrow && childEl && childEl.style.display === 'none') {
        arrow.classList.add('open');
        childEl.style.display = 'block';
      }
    }
  }
}

/* ═══════════════════════════════════════════════════════
   FILE OPENING & TABS
═══════════════════════════════════════════════════════ */
async function _openFile(item) {
  // Check if already open
  const existing = _state.tabs.find(t => t.path === item.path);
  if (existing) { _activateTab(existing.id); return; }

  _status(`加载 ${item.name}…`);

  // Image — just show inline
  if (item.category === 'image') {
    _addTab({ ...item, content: null, renderedHtml: `<img src="/api/file-library/serve?path=${encodeURIComponent(item.path)}" style="max-width:100%;display:block;margin:0 auto"/>` });
    return;
  }

  // Parse via backend
  try {
    const r = await fetch('/api/file-library/parse', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: item.path }),
    });
    const d = await r.json();
    if (!d.success) { _status('打开失败: ' + (d.error || '未知错误')); return; }
    _addTab({
      id: item.path,
      path: item.path,
      name: item.name,
      category: d.category || item.category,
      content: d.content || '',
      renderedHtml: d.rendered_html || null,
    });
    _status(`已打开 ${item.name}`);
    // Load metadata async
    _loadFileMetadata(item.path);
  } catch (e) {
    _status('打开失败: ' + e.message);
  }
}

function _addTab(tab) {
  const id = tab.id || tab.path;
  tab.id = id;
  _state.tabs.push(tab);
  _renderTabs();
  _activateTab(id);
}

function _activateTab(tabId) {
  _state.activeTab = _state.tabs.find(t => t.id === tabId) || null;
  _renderTabs();
  _renderViewer();
  _el('flExplorerView').style.display = 'none';
  _el('flViewerBody').style.display = '';
  // Highlight in tree
  document.querySelectorAll('.fl-tree-item.active').forEach(e => e.classList.remove('active'));
  if (_state.activeTab) {
    const el = document.querySelector(`.fl-tree-item[data-path="${CSS.escape(_state.activeTab.path)}"]`);
    if (el) el.classList.add('active');
  }
  // Update breadcrumb
  if (_state.activeTab) {
    const parts = _state.activeTab.path.replace(/\\/g, '/').split('/');
    _updateBreadcrumb(parts.map((p, i) => ({ label: p, path: parts.slice(0, i + 1).join('/') })));
  }
  // Load related files
  if (_state.activeNotebook && _state.activeTab) {
    _loadRelated(_state.activeTab.path, _state.activeNotebook.id);
  }
}

function _closeTab(tabId, e) {
  if (e) e.stopPropagation();
  const idx = _state.tabs.findIndex(t => t.id === tabId);
  if (idx === -1) return;
  // Dispose monaco if any
  const mi = _state.monacoInstances[tabId];
  if (mi) { try { mi.dispose(); } catch (_) {} delete _state.monacoInstances[tabId]; }
  _state.tabs.splice(idx, 1);
  if (_state.activeTab && _state.activeTab.id === tabId) {
    _state.activeTab = _state.tabs[Math.min(idx, _state.tabs.length - 1)] || null;
  }
  _renderTabs();
  if (_state.activeTab) {
    _renderViewer();
  } else {
    _el('flViewerBody').style.display = 'none';
    _el('flExplorerView').style.display = '';
    _restoreExplorerView();
  }
}

function _renderTabs() {
  const el = _el('flTabs');
  if (!el) return;
  el.innerHTML = _state.tabs.map(t => {
    const active = _state.activeTab && _state.activeTab.id === t.id;
    return `<div class="fl-tab ${active ? 'active' : ''}" onclick="FL._activateTab('${t.id.replace(/'/g,"\\'")}')">
      <span class="fl-tab-name" title="${_escapeHtml(t.path)}">${_extIcon(t.name.split('.').pop())} ${_escapeHtml(t.name)}</span>
      <button class="fl-tab-close" onclick="FL._closeTab('${t.id.replace(/'/g,"\\'")}',event)">×</button>
    </div>`;
  }).join('');
}

function _renderViewer() {
  const tab = _state.activeTab;
  if (!tab) return;

  const reader = _el('flReaderContent');
  const monacoWrap = _el('flMonacoWrap');

  const useMonaco = ['code', 'text', 'markdown', 'csv'].includes(tab.category);

  if (useMonaco) {
    reader.style.display = 'none';
    monacoWrap.style.display = '';
    _renderMonaco(tab);
  } else if (tab.category === 'pdf') {
    monacoWrap.style.display = 'none';
    reader.style.display = '';
    const blob = new Blob([new TextEncoder().encode('')], { type: 'application/pdf' });
    // Use a backend serve route for PDF
    reader.innerHTML = `<iframe class="fl-pdf-embed" src="/api/file-library/serve?path=${encodeURIComponent(tab.path)}"></iframe>`;
  } else {
    monacoWrap.style.display = 'none';
    reader.style.display = '';
    if (tab.renderedHtml) {
      reader.innerHTML = tab.renderedHtml;
    } else {
      reader.innerHTML = `<pre style="white-space:pre-wrap;font-family:var(--fl-font)">${_escapeHtml(tab.content || '')}</pre>`;
    }
  }
}

function _renderMonaco(tab) {
  const editorEl = _el('flMonacoEditor');
  if (!editorEl) return;

  const langMap = {
    py: 'python', js: 'javascript', ts: 'typescript', json: 'json',
    html: 'html', css: 'css', sql: 'sql', sh: 'shell', md: 'markdown',
    yaml: 'yaml', yml: 'yaml', xml: 'xml', r: 'r', csv: 'plaintext',
    txt: 'plaintext',
  };
  const ext = tab.name.split('.').pop().toLowerCase();
  const lang = langMap[ext] || 'plaintext';
  const isDark = document.body.getAttribute('data-theme') !== 'light';

  // Dispose any existing instance
  if (_state.monacoInstances[tab.id]) {
    _state.monacoInstances[tab.id].dispose();
    delete _state.monacoInstances[tab.id];
  }
  editorEl.innerHTML = '';

  const _create = () => {
    const inst = window.monaco.editor.create(editorEl, {
      value: tab.content || '',
      language: lang,
      theme: isDark ? 'vs-dark' : 'vs',
      readOnly: true,
      automaticLayout: true,
      minimap: { enabled: true },
      fontSize: 13,
      wordWrap: 'on',
      scrollBeyondLastLine: false,
      lineNumbers: 'on',
      folding: true,
      bracketPairColorization: { enabled: true },
    });
    _state.monacoInstances[tab.id] = inst;
  };

  if (window.monaco) {
    _create();
    return;
  }
  // Lazy-load Monaco from CDN
  if (!document.getElementById('fl-monaco-loader')) {
    const s = document.createElement('script');
    s.id = 'fl-monaco-loader';
    s.src = 'https://cdn.jsdelivr.net/npm/monaco-editor@0.44.0/min/vs/loader.js';
    s.onload = () => {
      require.config({ paths: { vs: 'https://cdn.jsdelivr.net/npm/monaco-editor@0.44.0/min/vs' } });
      window.require(['vs/editor/editor.main'], _create);
    };
    document.head.appendChild(s);
  } else {
    const poll = setInterval(() => {
      if (window.monaco) { clearInterval(poll); _create(); }
    }, 100);
  }
}

/* ═══════════════════════════════════════════════════════
   NOTEBOOKS
═══════════════════════════════════════════════════════ */
async function _loadNotebooks() {
  try {
    const r = await fetch('/api/file-library/notebooks');
    const d = await r.json();
    _state.notebooks = d.notebooks || [];
    _renderNotebooksList();
    _el('fl-nb-badge').textContent = _state.notebooks.length || '';
    // Rebuild tags from all notebook files
    _rebuildTags();
  } catch (e) {
    console.warn('[FL] loadNotebooks error:', e);
  }
}

function _renderNotebooksList() {
  const el = _el('fl-notebooks-list');
  if (!el) return;
  if (_state.notebooks.length === 0) {
    el.innerHTML = '<div style="padding:6px 14px;font-size:12px;color:var(--fl-text3)">暂无笔记本</div>';
    return;
  }
  el.innerHTML = _state.notebooks.map(nb => {
    const active = _state.activeNotebook && _state.activeNotebook.id === nb.id;
    return `<div class="fl-nb-item ${active ? 'active' : ''}"
                 onclick="FL._selectNotebook(${nb.id})">
      <span class="fl-nb-dot" style="background:${nb.color}"></span>
      <span class="fl-nb-name">${_escapeHtml(nb.name)}</span>
      <span class="fl-nb-count">${nb.file_count || ''}</span>
      <div class="fl-nb-actions">
        <button class="fl-icon-btn" onclick="FL._renameNotebook(${nb.id},'${nb.name.replace(/'/g,"\\'")}');event.stopPropagation()" title="重命名">
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
        </button>
        <button class="fl-icon-btn" onclick="FL._deleteNotebook(${nb.id});event.stopPropagation()" title="删除" style="color:var(--fl-red)">
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4h6v2"/></svg>
        </button>
      </div>
    </div>`;
  }).join('');
}

async function _selectNotebook(nbId) {
  const nb = _state.notebooks.find(n => n.id === nbId);
  if (!nb) return;
  _state.activeNotebook = nb;
  _state.activeMount = null;
  _renderMountsList();
  _renderNotebooksList();
  _el('flNpTitle').textContent = nb.name;
  _el('flNpFiles').style.display = '';
  // Load notebook files
  await _loadNotebookFiles(nbId);
  _showNotebookGrid(nb);
}

async function _loadNotebookFiles(nbId) {
  try {
    const r = await fetch(`/api/file-library/notebooks/${nbId}/files`);
    const d = await r.json();
    _state.nbFiles = d.files || [];
    _renderNpFileList();
    _renderNotebookGrid();
  } catch (e) {
    console.warn('[FL] loadNotebookFiles error:', e);
  }
}

function _renderNpFileList() {
  const el = _el('flNpFileList');
  if (!el) return;
  el.innerHTML = _state.nbFiles.map(f =>
    `<div class="fl-np-file-row" onclick="FL._openFile({path:'${f.file_path.replace(/'/g,"\\'")}',name:'${f.name.replace(/'/g,"\\'")}',category:'${f.category}'})">
      <span class="fl-np-file-icon">${_extIcon(f.ext)}</span>
      <span class="fl-np-file-name">${_escapeHtml(f.name)}</span>
      <button class="fl-np-file-rm fl-icon-btn" onclick="FL._removeNbFile(${f.id});event.stopPropagation()" title="移除">
        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
      </button>
    </div>`
  ).join('');
}

function _showNotebookGrid(nb) {
  _el('flWelcome').style.display = 'none';
  _el('flTreeContainer').style.display = 'none';
  _el('flNotebookGrid').style.display = '';
  _el('flViewerBody').style.display = 'none';
  _el('flExplorerView').style.display = '';
  _updateBreadcrumb([{ label: nb.name, path: null }]);
}

function _renderNotebookGrid() {
  const grid = _el('flCardsGrid');
  const header = _el('flNotebookGridHeader');
  if (!grid) return;
  const nb = _state.activeNotebook;
  if (header && nb) {
    header.innerHTML = `
      <span class="fl-nb-dot" style="background:${nb.color}"></span>
      <span class="fl-nb-grid-title">${_escapeHtml(nb.name)}</span>
      <span class="fl-nb-grid-count">${_state.nbFiles.length} 个文件</span>
      <button class="fl-btn fl-btn-sm" onclick="FL.openAddFilesDialog()">+ 添加文件</button>
    `;
  }
  if (_state.nbFiles.length === 0) {
    grid.innerHTML = `<div style="grid-column:1/-1;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:60px 20px;gap:12px;color:var(--fl-text3)">
      <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.2"><path d="M12 5v14M5 12h14"/></svg>
      <span>从左侧文件树拖入文件，或点击"添加文件"</span>
    </div>`;
    return;
  }
  grid.innerHTML = _state.nbFiles.map(f => {
    const summary = f.summary || '';
    const tags = (f.tags || []).slice(0, 3);
    return `<div class="fl-file-card" draggable="true"
                 ondragstart="FL._onDragStart(event,'${f.file_path.replace(/'/g,"\\'")}','${f.name.replace(/'/g,"\\'")}','${f.id}')"
                 onclick="FL._openFile({path:'${f.file_path.replace(/'/g,"\\'")}',name:'${f.name.replace(/'/g,"\\'")}',category:'${f.category}'})">
      <div class="fl-file-card-icon">${_extIcon(f.ext)}</div>
      <div class="fl-file-card-name" title="${_escapeHtml(f.file_path)}">${_escapeHtml(f.name)}</div>
      <div class="fl-file-card-summary">${summary ? _escapeHtml(summary) : '<span style="color:var(--fl-text3);font-style:italic">点击右键生成摘要</span>'}</div>
      ${tags.length ? `<div class="fl-file-card-tags">${tags.map(t => `<span class="fl-card-tag">${_escapeHtml(t)}</span>`).join('')}</div>` : ''}
      <div class="fl-file-card-footer">
        <span class="fl-file-card-date">${f.mtime ? _timeAgo(f.mtime) : ''}</span>
        <button class="fl-file-card-remove fl-icon-btn" onclick="FL._removeNbFile(${f.id});event.stopPropagation()" title="从笔记本移除">
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
        </button>
      </div>
    </div>`;
  }).join('');
}

async function _createNotebook() {
  const name = prompt('笔记本名称：');
  if (!name || !name.trim()) return;
  const colors = ['#6366f1', '#06b6d4', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6'];
  const color = colors[Math.floor(Math.random() * colors.length)];
  await fetch('/api/file-library/notebooks', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: name.trim(), color }),
  });
  await _loadNotebooks();
}

async function _renameNotebook(id, oldName) {
  const name = prompt('新名称：', oldName);
  if (!name || !name.trim() || name.trim() === oldName) return;
  await fetch(`/api/file-library/notebooks/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: name.trim() }),
  });
  await _loadNotebooks();
}

async function _deleteNotebook(id) {
  const nb = _state.notebooks.find(n => n.id === id);
  if (!confirm(`删除笔记本"${nb ? nb.name : id}"？（文件不会被删除）`)) return;
  await fetch(`/api/file-library/notebooks/${id}`, { method: 'DELETE' });
  if (_state.activeNotebook && _state.activeNotebook.id === id) {
    _state.activeNotebook = null;
    _showWelcome();
  }
  await _loadNotebooks();
}

async function _removeNbFile(entryId) {
  const f = _state.nbFiles.find(x => x.id === entryId);
  if (!f) return;
  await fetch(`/api/file-library/notebooks/${_state.activeNotebook.id}/files`, {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path: f.file_path }),
  });
  await _loadNotebookFiles(_state.activeNotebook.id);
}

/* ═══════════════════════════════════════════════════════
   DRAG & DROP (tree → notebook)
═══════════════════════════════════════════════════════ */
function _onDragStart(event, path, name) {
  event.dataTransfer.setData('text/fl-path', path);
  event.dataTransfer.setData('text/fl-name', name);
  event.dataTransfer.effectAllowed = 'copy';
}

function _initNotebookDrop() {
  const cardsEl = _el('flCardsGrid');
  const nbGrid = _el('flNotebookGrid');
  if (!cardsEl || !nbGrid) return;

  [cardsEl, nbGrid].forEach(el => {
    el.addEventListener('dragover', e => { e.preventDefault(); el.classList.add('fl-drag-over'); });
    el.addEventListener('dragleave', () => el.classList.remove('fl-drag-over'));
    el.addEventListener('drop', async e => {
      e.preventDefault();
      el.classList.remove('fl-drag-over');
      const path = e.dataTransfer.getData('text/fl-path');
      if (!path || !_state.activeNotebook) return;
      await fetch(`/api/file-library/notebooks/${_state.activeNotebook.id}/files`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ paths: [path] }),
      });
      await _loadNotebookFiles(_state.activeNotebook.id);
      // Auto-trigger summarize in background
      fetch('/api/file-library/summarize', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path }),
      });
    });
  });

  // Drop onto nb items in left panel
  document.querySelectorAll('.fl-nb-item').forEach(item => {
    item.addEventListener('dragover', e => { e.preventDefault(); item.classList.add('fl-drag-over'); });
    item.addEventListener('dragleave', () => item.classList.remove('fl-drag-over'));
    item.addEventListener('drop', async e => {
      e.preventDefault();
      item.classList.remove('fl-drag-over');
      const path = e.dataTransfer.getData('text/fl-path');
      const nbIndex = Array.from(_el('fl-notebooks-list').children).indexOf(item);
      if (nbIndex < 0 || !path) return;
      const nb = _state.notebooks[nbIndex];
      if (!nb) return;
      await fetch(`/api/file-library/notebooks/${nb.id}/files`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ paths: [path] }),
      });
      _status(`已添加到笔记本 "${nb.name}"`);
    });
  });
}

/* ═══════════════════════════════════════════════════════
   AI METADATA & RELATED
═══════════════════════════════════════════════════════ */
async function _loadFileMetadata(filePath) {
  try {
    const r = await fetch(`/api/file-library/metadata?path=${encodeURIComponent(filePath)}`);
    const d = await r.json();
    if (d.tags && d.tags.length > 0) {
      // Update notebook card if visible
      _updateCardMetadata(filePath, d.summary, d.tags);
    }
  } catch (_) {}
}

function _updateCardMetadata(filePath, summary, tags) {
  // Find card in grid
  const cards = document.querySelectorAll('.fl-file-card');
  cards.forEach(card => {
    const nameEl = card.querySelector('.fl-file-card-name');
    // Match by title attribute (full path)
    if (nameEl && nameEl.title === filePath) {
      const summEl = card.querySelector('.fl-file-card-summary');
      if (summEl && summary) summEl.textContent = summary;
      const tagsEl = card.querySelector('.fl-file-card-tags');
      if (tagsEl && tags.length) {
        tagsEl.innerHTML = tags.slice(0, 3).map(t => `<span class="fl-card-tag">${_escapeHtml(t)}</span>`).join('');
      }
    }
  });
}

async function _loadRelated(filePath, nbId) {
  try {
    const r = await fetch(`/api/file-library/related?path=${encodeURIComponent(filePath)}&notebook_id=${nbId}`);
    const d = await r.json();
    const rel = d.related || [];
    const bar = _el('flRelatedBar');
    const items = _el('flRelatedItems');
    if (!bar || !items) return;
    if (rel.length === 0) { bar.style.display = 'none'; return; }
    bar.style.display = '';
    items.innerHTML = rel.map(rf =>
      `<div class="fl-related-item" onclick="FL._openFile({path:'${rf.path.replace(/'/g,"\\'")}',name:'${rf.name.replace(/'/g,"\\'")}',category:'${rf.category}'})">
        ${_extIcon(rf.name.split('.').pop())} ${_escapeHtml(rf.name)}
      </div>`
    ).join('');
  } catch (_) {}
}

function _rebuildTags() {
  // Tags are loaded per-file; collect from nbFiles
  const tagSet = new Set();
  for (const f of _state.nbFiles) {
    if (f.tags) f.tags.forEach(t => tagSet.add(t));
  }
  _state.allTags = [...tagSet];
  _renderTagsCloud();
}

function _renderTagsCloud() {
  const el = _el('fl-tags-cloud');
  if (!el) return;
  if (_state.allTags.length === 0) {
    el.innerHTML = '<span style="padding:0 14px;color:var(--fl-text3);font-size:12px">（生成摘要后自动出现标签）</span>';
    return;
  }
  el.className = 'fl-section-body fl-tags-cloud';
  el.innerHTML = _state.allTags.map(t =>
    `<span class="fl-tag-chip ${_state.activeTag === t ? 'active' : ''}"
          onclick="FL._filterTag('${t.replace(/'/g,"\\'")}')">
      ${_escapeHtml(t)}
    </span>`
  ).join('');
}

function _filterTag(tag) {
  _state.activeTag = _state.activeTag === tag ? null : tag;
  _renderTagsCloud();
  if (_state.searchQuery === '') {
    _state.searchQuery = '';
  }
  // Filter grip cards
  _renderNotebookGrid();
}

/* ═══════════════════════════════════════════════════════
   CHAT
═══════════════════════════════════════════════════════ */
async function sendChat() {
  const input = _el('flChatInput');
  if (!input) return;
  const msg = input.value.trim();
  if (!msg || _state.chatStreaming) return;
  input.value = '';
  input.style.height = '';

  _appendChatMsg('user', msg);
  _state.chatHistory.push({ role: 'user', content: msg });
  _state.chatStreaming = true;
  _el('flChatSend').disabled = true;

  // Show typing indicator
  const typingEl = document.createElement('div');
  typingEl.className = 'fl-typing';
  typingEl.innerHTML = '<span></span><span></span><span></span>';
  const messagesEl = _el('flChatMessages');
  messagesEl.appendChild(typingEl);
  messagesEl.scrollTop = messagesEl.scrollHeight;

  let fullText = '';
  let assistantBubbleEl = null;

  try {
    const resp = await fetch('/api/file-library/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        notebook_id: _state.activeNotebook ? _state.activeNotebook.id : null,
        message: msg,
        history: _state.chatHistory.slice(-6),
      }),
    });

    typingEl.remove();

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const lines = buf.split('\n');
      buf = lines.pop() || '';
      for (const line of lines) {
        if (!line.startsWith('data:')) continue;
        const data = line.slice(5).trim();
        if (!data) continue;
        try {
          const ev = JSON.parse(data);
          if (ev.type === 'meta') {
            if (!assistantBubbleEl) {
              assistantBubbleEl = _createAssistantBubble(
                ev.file_count > 0 ? `基于 ${ev.file_count} 个文件` : ''
              );
            }
          } else if (ev.type === 'chunk') {
            fullText += ev.text;
            if (!assistantBubbleEl) assistantBubbleEl = _createAssistantBubble('');
            assistantBubbleEl.textContent = fullText;
            messagesEl.scrollTop = messagesEl.scrollHeight;
          } else if (ev.type === 'error') {
            if (!assistantBubbleEl) assistantBubbleEl = _createAssistantBubble('');
            assistantBubbleEl.textContent = ev.text;
          }
        } catch (_) {}
      }
    }
  } catch (e) {
    typingEl.remove();
    _appendChatMsg('assistant', '请求失败：' + e.message);
    fullText = '错误';
  }

  _state.chatHistory.push({ role: 'assistant', content: fullText });
  _state.chatStreaming = false;
  _el('flChatSend').disabled = false;
}

function _appendChatMsg(role, text) {
  const el = _el('flChatMessages');
  if (!el) return;
  const hint = el.querySelector('.fl-chat-hint');
  if (hint) hint.remove();
  const msgEl = document.createElement('div');
  msgEl.className = `fl-chat-msg ${role}`;
  const bubble = document.createElement('div');
  bubble.className = 'fl-chat-bubble';
  bubble.textContent = text;
  msgEl.appendChild(bubble);
  el.appendChild(msgEl);
  el.scrollTop = el.scrollHeight;
  return bubble;
}

function _createAssistantBubble(badgeText) {
  const el = _el('flChatMessages');
  if (!el) return null;
  const msgEl = document.createElement('div');
  msgEl.className = 'fl-chat-msg assistant';
  if (badgeText) {
    const badge = document.createElement('div');
    badge.className = 'fl-chat-file-badge';
    badge.textContent = badgeText;
    msgEl.appendChild(badge);
  }
  const bubble = document.createElement('div');
  bubble.className = 'fl-chat-bubble';
  msgEl.appendChild(bubble);
  el.appendChild(msgEl);
  el.scrollTop = el.scrollHeight;
  return bubble;
}

function onChatKeydown(e) {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChat(); }
}

function autoResizeInput(el) {
  el.style.height = '';
  el.style.height = Math.min(el.scrollHeight, 120) + 'px';
}

/* ═══════════════════════════════════════════════════════
   AI QUICK ACTIONS
═══════════════════════════════════════════════════════ */
async function aiQuickAction(type) {
  const tab = _state.activeTab;
  const labels = { summary: '帮我总结这个文件的主要内容', keypoints: '提取文件的关键要点，用列表呈现', tags: '给这个文件自动打标签，并生成简短摘要' };
  const msg = labels[type] || type;
  const chatInput = _el('flChatInput');
  if (chatInput) { chatInput.value = msg; await sendChat(); }
}

/* ═══════════════════════════════════════════════════════
   MOUNT DIALOG
═══════════════════════════════════════════════════════ */
async function showMountDialog() {
  _el('flMountOverlay').style.display = '';
  _el('flMountSelectedPath').textContent = '未选择';
  _state.mountSelectedPath = null;
  // Load drives + quick access
  try {
    const r = await fetch('/api/browse/drives');
    const d = await r.json();
    // Quick access
    const qa = _el('flMountQuickAccess');
    qa.innerHTML = (d.quick_access || []).map(loc =>
      `<button class="fl-qas-btn" onclick="FL.browsePath('${loc.path.replace(/'/g,"\\'")}')">
        ${_escapeHtml(loc.name)}
      </button>`
    ).join('');
    // Drives
    const drivesEl = _el('flMountDrives');
    drivesEl.innerHTML = (d.drives || []).map(drv =>
      `<button class="fl-drive-btn" onclick="FL.browsePath('${drv.path.replace(/'/g,"\\'")}')">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.07 4.93a10 10 0 0 1 1.41 11.4M3.52 15.33a10 10 0 0 1 1.41-11.4M9 12a3 3 0 1 0 6 0 3 3 0 0 0-6 0"/></svg>
        ${_escapeHtml(drv.name)}
      </button>`
    ).join('');
  } catch (_) {}
}

function closeMountDialog() {
  _el('flMountOverlay').style.display = 'none';
}

async function browsePath(path) {
  path = path || _el('flMountPathInput').value.trim();
  if (!path) return;
  _el('flMountPathInput').value = path;
  _state.mountSelectedPath = path;
  _el('flMountSelectedPath').textContent = path;

  try {
    const r = await fetch(`/api/browse?path=${encodeURIComponent(path)}`);
    const d = await r.json();
    const browser = _el('flMountBrowser');
    const folders = d.folders || [];
    if (folders.length === 0) {
      browser.innerHTML = '<div class="fl-browser-empty">（空文件夹）</div>';
      return;
    }
    browser.innerHTML = folders.map(f =>
      `<div class="fl-browser-item" onclick="FL.browsePath('${f.path.replace(/'/g,"\\'")}')">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="var(--fl-accent)" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
        ${_escapeHtml(f.name)}
      </div>`
    ).join('');
  } catch (e) {
    _el('flMountBrowser').innerHTML = `<div class="fl-browser-empty">无法访问: ${_escapeHtml(e.message)}</div>`;
  }
}

async function confirmMount() {
  const path = _state.mountSelectedPath || _el('flMountPathInput').value.trim();
  if (!path) { alert('请选择一个文件夹'); return; }
  const r = await fetch('/api/file-library/mounts', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path }),
  });
  const d = await r.json();
  if (!d.success) { alert('挂载失败: ' + (d.error || '未知')); return; }
  closeMountDialog();
  await _loadMounts();
}

/* ═══════════════════════════════════════════════════════
   ADD TO NOTEBOOK DIALOG
═══════════════════════════════════════════════════════ */
function _showAddToNotebookDialog(paths) {
  _state.addNbTargetPaths = Array.isArray(paths) ? paths : [paths];
  const listEl = _el('flAddNbList');
  listEl.innerHTML = _state.notebooks.map(nb =>
    `<div class="fl-addnb-item" onclick="FL._addToNotebook(${nb.id})">
      <span class="fl-addnb-dot" style="background:${nb.color}"></span>
      <span class="fl-addnb-name">${_escapeHtml(nb.name)}</span>
    </div>`
  ).join('') || '<div style="color:var(--fl-text3);padding:10px;font-size:12px">暂无笔记本，请先新建</div>';
  _el('flAddNbOverlay').style.display = '';
}

function closeAddNbDialog() {
  _el('flAddNbOverlay').style.display = 'none';
}

async function _addToNotebook(nbId) {
  closeAddNbDialog();
  await fetch(`/api/file-library/notebooks/${nbId}/files`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ paths: _state.addNbTargetPaths }),
  });
  _status('已加入笔记本');
  // Auto-trigger summarize for each
  for (const p of _state.addNbTargetPaths) {
    fetch('/api/file-library/summarize', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: p }),
    });
  }
  if (_state.activeNotebook && _state.activeNotebook.id === nbId) {
    await _loadNotebookFiles(nbId);
  }
  await _loadNotebooks();
}

function openAddFilesDialog() {
  // Open a file picker by browsing current mount
  if (_state.activeMount) {
    // Show tree briefly to pick files — simplified: just alert instruction
    alert('从左侧文件树中拖拽文件到笔记本网格区域，即可添加');
  } else {
    alert('请先挂载一个文件夹，然后从文件树拖入文件');
  }
}

async function createNotebookAndAdd() {
  const name = prompt('新笔记本名称：');
  if (!name || !name.trim()) return;
  const colors = ['#6366f1', '#06b6d4', '#10b981', '#f59e0b', '#ef4444'];
  const color = colors[Math.floor(Math.random() * colors.length)];
  const r = await fetch('/api/file-library/notebooks', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: name.trim(), color }),
  });
  const d = await r.json();
  if (d.notebook) {
    await _addToNotebook(d.notebook.id);
    await _loadNotebooks();
    closeAddNbDialog();
  }
}

/* ═══════════════════════════════════════════════════════
   CONTEXT MENU
═══════════════════════════════════════════════════════ */
function _showCtxMenu(event, item) {
  event.preventDefault();
  _state.ctxTarget = item;
  const menu = _el('flCtxMenu');
  menu.style.display = '';
  menu.style.left = Math.min(event.clientX, window.innerWidth - 170) + 'px';
  menu.style.top = Math.min(event.clientY, window.innerHeight - 200) + 'px';

  const isFile = item.type === 'file';
  _el('flCtxOpen').style.display = isFile ? '' : 'none';
  _el('flCtxAddToNb').style.display = isFile ? '' : 'none';
  _el('flCtxSummarize').style.display = isFile ? '' : 'none';
  _el('flCtxCopyPath').style.display = '';
  _el('flCtxOpenNative').style.display = '';
  _el('flCtxReveal').style.display = '';
}

function _hideCtxMenu() {
  _el('flCtxMenu').style.display = 'none';
}

function _initCtxMenuListeners() {
  document.addEventListener('click', _hideCtxMenu);
  document.addEventListener('keydown', e => { if (e.key === 'Escape') _hideCtxMenu(); });

  _el('flCtxOpen').addEventListener('click', () => {
    if (_state.ctxTarget) _openFile(_state.ctxTarget);
  });
  _el('flCtxAddToNb').addEventListener('click', () => {
    if (_state.ctxTarget) _showAddToNotebookDialog([_state.ctxTarget.path]);
  });
  _el('flCtxSummarize').addEventListener('click', async () => {
    if (!_state.ctxTarget) return;
    _status('摘要生成中…');
    await fetch('/api/file-library/summarize', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: _state.ctxTarget.path }),
    });
    // Poll after 3s
    setTimeout(async () => {
      await _loadFileMetadata(_state.ctxTarget.path);
      _status('摘要已更新');
    }, 3000);
  });
  _el('flCtxCopyPath').addEventListener('click', () => {
    if (_state.ctxTarget) navigator.clipboard.writeText(_state.ctxTarget.path).then(() => _status('路径已复制'));
  });
  _el('flCtxOpenNative').addEventListener('click', async () => {
    if (!_state.ctxTarget) return;
    await fetch('/api/file-library/open-native', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: _state.ctxTarget.path }),
    });
  });
  _el('flCtxReveal').addEventListener('click', async () => {
    if (!_state.ctxTarget) return;
    // Open the parent folder
    const parent = _state.ctxTarget.path.replace(/[/\\][^/\\]+$/, '');
    await fetch('/api/open-workspace', { method: 'POST' });
  });
}

/* ═══════════════════════════════════════════════════════
   SECTION COLLAPSE
═══════════════════════════════════════════════════════ */
function toggleSection(name) {
  _state.sectionOpen[name] = !_state.sectionOpen[name];
  localStorage.setItem('fl_sections', JSON.stringify(_state.sectionOpen));
  const bodyEl = _el(`fl-${name === 'mounts' ? 'mounts-list' : name === 'notebooks' ? 'notebooks-list' : 'tags-cloud'}`);
  const arrowEl = _el(`fl-arrow-${name}`);
  if (bodyEl) bodyEl.classList.toggle('collapsed', !_state.sectionOpen[name]);
  if (arrowEl) arrowEl.classList.toggle('collapsed', !_state.sectionOpen[name]);
}

/* ═══════════════════════════════════════════════════════
   PANEL RESIZE
═══════════════════════════════════════════════════════ */
function _initResize() {
  _makeResizable(_el('flResizeLeft'), _el('flExplorer'), 'left');
  _makeResizable(_el('flResizeRight'), _el('flNotebookPanel'), 'right');
}

function _makeResizable(handle, panel, side) {
  if (!handle || !panel) return;
  let startX, startW;
  handle.addEventListener('mousedown', e => {
    startX = e.clientX;
    startW = panel.offsetWidth;
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
    const onMove = ev => {
      const delta = ev.clientX - startX;
      const newW = side === 'left' ? startW + delta : startW - delta;
      const clamped = Math.max(160, Math.min(520, newW));
      panel.style.width = clamped + 'px';
      if (side === 'left') document.documentElement.style.setProperty('--fl-left-w', clamped + 'px');
      else document.documentElement.style.setProperty('--fl-right-w', clamped + 'px');
    };
    const onUp = () => {
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
  });
}

/* ═══════════════════════════════════════════════════════
   SEARCH
═══════════════════════════════════════════════════════ */
function onSearch(val) {
  _state.searchQuery = val;
  const clearBtn = _el('flSearchClear');
  if (clearBtn) clearBtn.style.display = val ? '' : 'none';
  _debounce('search', () => {
    if (_state.activeMount) {
      const cached = _state.treeCache[_state.activeMount.path];
      if (cached) _renderTree(cached, _state.activeMount.path);
    }
  }, 200);
}

function clearSearch() {
  const input = _el('flSearchInput');
  if (input) input.value = '';
  onSearch('');
}

/* ═══════════════════════════════════════════════════════
   BREADCRUMB
═══════════════════════════════════════════════════════ */
function _updateBreadcrumb(parts) {
  const el = _el('flBreadcrumb');
  if (!el) return;
  el.innerHTML = parts.map((p, i) => {
    const isLast = i === parts.length - 1;
    return `${i > 0 ? '<span class="fl-breadcrumb-sep">/</span>' : ''}` +
      `<span class="fl-breadcrumb-item ${isLast ? 'active' : ''}">${_escapeHtml(p.label)}</span>`;
  }).join('');
}

/* ═══════════════════════════════════════════════════════
   MISC UI
═══════════════════════════════════════════════════════ */
function _showWelcome() {
  _el('flWelcome').style.display = '';
  _el('flTreeContainer').style.display = 'none';
  _el('flNotebookGrid').style.display = 'none';
  _el('flExplorerView').style.display = '';
  _el('flViewerBody').style.display = 'none';
}

function _restoreExplorerView() {
  if (_state.activeNotebook) {
    _showNotebookGrid(_state.activeNotebook);
    _renderNotebookGrid();
  } else if (_state.activeMount) {
    _showTreeContainer(_state.activeMount.path);
    const cached = _state.treeCache[_state.activeMount.path];
    if (cached) _renderTree(cached, _state.activeMount.path);
  } else {
    _showWelcome();
  }
}

function closeAllTabs() {
  for (const tab of [..._state.tabs]) {
    const mi = _state.monacoInstances[tab.id];
    if (mi) { try { mi.dispose(); } catch (_) {} }
  }
  _state.tabs = [];
  _state.activeTab = null;
  _state.monacoInstances = {};
  _renderTabs();
  _el('flViewerBody').style.display = 'none';
  _el('flExplorerView').style.display = '';
  _restoreExplorerView();
}

function toggleRightPanel() {
  const panel = _el('flNotebookPanel');
  const isHidden = panel.classList.toggle('fl-hidden');
  _state.rightPanelOpen = !isHidden;
  localStorage.setItem('fl_right_panel', String(_state.rightPanelOpen));
}

function setViewMode(mode) {
  _state.viewMode = mode;
  localStorage.setItem('fl_view_mode', mode);
  document.querySelectorAll('.fl-vt-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.view === mode);
  });
}

function refreshCurrentTree() {
  if (_state.activeMount) {
    delete _state.treeCache[_state.activeMount.path];
    _loadTree(_state.activeMount.path, true);
  }
}

function toggleTheme() {
  const current = document.body.getAttribute('data-theme');
  const next = current === 'light' ? 'dark' : 'light';
  _applyTheme(next);
  // Update Monaco themes
  if (window.monaco) {
    Object.values(_state.monacoInstances).forEach(inst => {
      window.monaco.editor.setTheme(next === 'light' ? 'vs' : 'vs-dark');
    });
  }
}

/* ═══════════════════════════════════════════════════════
   PUBLIC FL OBJECT
═══════════════════════════════════════════════════════ */
window.FL = {
  // Mount
  showMountDialog,
  closeMountDialog,
  browsePath,
  confirmMount,
  _selectMount,
  _unmount,

  // Tree
  _toggleFolder,
  _openFile,
  refreshCurrentTree,

  // Tabs
  _activateTab,
  _closeTab,
  closeAllTabs,

  // Notebooks
  createNotebook: _createNotebook,
  _selectNotebook,
  _renameNotebook,
  _deleteNotebook,
  _removeNbFile,
  openAddFilesDialog,
  createNotebookAndAdd,
  _addToNotebook,
  closeAddNbDialog,

  // Drag
  _onDragStart,

  // Chat
  sendChat,
  onChatKeydown,
  autoResizeInput,
  aiQuickAction,

  // Context menu
  _showCtxMenu,

  // Search
  onSearch,
  clearSearch,

  // UI toggles
  toggleSection,
  toggleRightPanel,
  toggleTheme,
  setViewMode,
};

/* ═══════════════════════════════════════════════════════
   INIT
═══════════════════════════════════════════════════════ */
document.addEventListener('DOMContentLoaded', () => {
  // Theme
  const savedTheme = localStorage.getItem('fl_theme') || 'dark';
  _applyTheme(savedTheme);

  // Initial section state
  ['mounts', 'notebooks', 'tags'].forEach(name => {
    if (!_state.sectionOpen[name]) toggleSection(name);
  });

  // Right panel state
  if (!_state.rightPanelOpen) {
    _el('flNotebookPanel').classList.add('fl-hidden');
  }

  // Resize handles
  _initResize();

  // Context menu
  _initCtxMenuListeners();

  // Socket
  _initSocket();

  // Load data
  Promise.all([_loadMounts(), _loadNotebooks()]).then(() => {
    _initNotebookDrop();
    // Re-bind notebook drop after render
    setTimeout(_initNotebookDrop, 500);
  });
});
