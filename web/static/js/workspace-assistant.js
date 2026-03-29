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
    activeEditor: null,
    socket: null,
    isLoading: false,
    conversation: [],   // [{role:'user'|'assistant', content:string}] — multi-turn history
    recentFiles: JSON.parse(localStorage.getItem('wa_recent_files') || '[]'),  // [{name, ext, path, time}]
    sortBy: localStorage.getItem('wa_sort_by') || 'name',   // 'name' | 'date' | 'type'
    sectionOpen: JSON.parse(localStorage.getItem('wa_sections') || '{"recent":true,"workspace":true}'),
    searchQuery: '',
    _allFiles: [],  // full file tree cached for client-side filter
    pinnedSelection: '',  // text pinned as Copilot-style context chip
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

  // ── Recent files helpers ──
  // path: workspace-relative path used to re-open the file (e.g. "uploads/foo.docx")
  function _saveRecentFile(name, ext, path) {
    const MAX_RECENT = 8;
    const wsPath = path || ('uploads/' + name);
    state.recentFiles = state.recentFiles.filter(f => f.name !== name);
    state.recentFiles.unshift({ name, ext, path: wsPath, time: Date.now() });
    if (state.recentFiles.length > MAX_RECENT) state.recentFiles.length = MAX_RECENT;
    localStorage.setItem('wa_recent_files', JSON.stringify(state.recentFiles));
    renderRecentFiles();
  }

  function renderRecentFiles() {
    const el = $('wa-recent-list');
    if (!el) return;

    // Update section visibility
    el.style.display = state.sectionOpen.recent ? '' : 'none';
    const arrow = $('wa-recent-arrow');
    if (arrow) arrow.className = 'wa-section-arrow' + (state.sectionOpen.recent ? ' open' : '');

    // Update count badge
    const badge = $('wa-recent-badge');
    if (badge) badge.textContent = state.recentFiles.length || '';

    if (!state.recentFiles.length) {
      el.innerHTML = '<div style="padding:4px 14px;color:var(--text-muted);font-size:11px;">暂无最近文件</div>';
      return;
    }
    el.innerHTML = state.recentFiles.map(f => {
      const icon = _EXT_ICON[f.ext] || '📄';
      const wsPath = f.path || ('uploads/' + f.name);
      const esc = wsPath.replace(/'/g, "\\'");
      const nameEsc = f.name.replace(/'/g, "\\'");
      return `<div class="wa-file-item file" data-depth="0" onclick="WA.openWorkspaceFile('${esc}')" title="${f.name}">
        <span class="wa-file-icon">${icon}</span>
        <span style="overflow:hidden;text-overflow:ellipsis;flex:1;font-size:12px">${f.name}</span>
        <button class="wa-file-del" onclick="event.stopPropagation();WA.removeRecentFile('${nameEsc}')" title="从列表移除">×</button>
      </div>`;
    }).join('');
  }

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
    if (sortBtn) sortBtn.textContent = '↕ ' + _SORT_LABELS[state.sortBy];

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
          return `<div class="wa-folder-group" data-folder="${item.path}">
            <div class="wa-file-item folder" data-depth="${depth}" onclick="WA.toggleFolder(this)">
              <span class="wa-folder-arrow${isOpen ? ' open' : ''}">▶</span>
              <span class="wa-file-icon">📁</span>
              <span style="overflow:hidden;text-overflow:ellipsis;flex:1">${item.name}</span>
            </div>
            <div class="wa-folder-children" style="display:${isOpen ? 'block' : 'none'};">${childrenHtml}</div>
          </div>`;
        } else {
          const icon = _EXT_ICON[item.ext] || '📄';
          const esc = item.path.replace(/'/g, "\\'");
          const nameEsc = item.name.replace(/'/g, "\\'");
          const isActive = (state.fileName && item.name === state.fileName) ? ' active' : '';
          const meta = [item.size, _formatDate(item.mtime)].filter(Boolean).join(' · ');
          return `<div class="wa-file-item file${isActive}" data-depth="${depth}" data-path="${esc}"
              onclick="WA.openWorkspaceFile('${esc}')" title="${item.path}&#10;${item.size || ''} · ${_formatDate(item.mtime)}">
            <span class="wa-file-icon">${icon}</span>
            <span style="overflow:hidden;text-overflow:ellipsis;flex:1;min-width:0">
              <span class="wa-file-label">${item.name}</span>
              ${meta ? `<span class="wa-file-meta">${meta}</span>` : ''}
            </span>
            <button class="wa-file-rename" onclick="event.stopPropagation();WA.renameWorkspaceFile('${esc}','${nameEsc}')" title="重命名">✎</button>
            <button class="wa-file-del" onclick="event.stopPropagation();WA.deleteWorkspaceFile('${esc}')" title="删除">×</button>
          </div>`;
        }
      }).join('');
    }

    list.innerHTML = renderTree(items);
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
    if (id === 'recent') renderRecentFiles();
    else _renderWorkspaceTree();
  };

  window.WA.cycleSortOrder = () => {
    const order = ['name', 'date', 'type'];
    const idx = order.indexOf(state.sortBy);
    state.sortBy = order[(idx + 1) % order.length];
    localStorage.setItem('wa_sort_by', state.sortBy);
    _renderWorkspaceTree();
  };

  window.WA.removeRecentFile = (name) => {
    state.recentFiles = state.recentFiles.filter(f => f.name !== name);
    localStorage.setItem('wa_recent_files', JSON.stringify(state.recentFiles));
    renderRecentFiles();
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
        // Update recent files if the old name was there
        state.recentFiles = state.recentFiles.map(f =>
          f.name === currentName ? { ...f, name: json.name, path: json.path } : f
        );
        localStorage.setItem('wa_recent_files', JSON.stringify(state.recentFiles));
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
      if (!res.ok) throw new Error(json.error || '删除失败');
      showToast('已删除 ' + filepath.split('/').pop(), 'success');
      loadWorkspaceFiles();
    } catch (e) {
      showToast(e.message, 'error');
    }
  };

  window.WA.toggleFolder = (el) => {
    const arrow = el.querySelector('.wa-folder-arrow');
    const children = el.nextElementSibling;
    const folderPath = el.closest('.wa-folder-group') && el.closest('.wa-folder-group').dataset.folder;
    const isOpen = children.style.display !== 'none';
    if (!isOpen) {
      children.style.display = 'block';
      arrow.classList.add('open');
      if (folderPath) {
        const openFolders = JSON.parse(localStorage.getItem('wa_open_folders') || '{}');
        openFolders[folderPath] = true;
        localStorage.setItem('wa_open_folders', JSON.stringify(openFolders));
      }
    } else {
      children.style.display = 'none';
      arrow.classList.remove('open');
      if (folderPath) {
        const openFolders = JSON.parse(localStorage.getItem('wa_open_folders') || '{}');
        delete openFolders[folderPath];
        localStorage.setItem('wa_open_folders', JSON.stringify(openFolders));
      }
    }
  };

  window.WA.openWorkspaceFile = async (filename) => {
    const baseName = filename.split('/').pop();
    showToast('正在加载 ' + baseName, 'success');
    try {
      const encodedPath = filename.split('/').map(p => encodeURIComponent(p)).join('/');
      const res = await fetch('/api/v1/workspace/file/' + encodedPath);
      if (!res.ok) throw new Error('File not found');
      const blob = await res.blob();
      // Use basename only so the title bar doesn't show "uploads/foo.docx".
      // Tag the file object with _wsPath so Router.load knows the workspace path.
      const file = new File([blob], baseName);
      file._wsPath = filename;   // full workspace-relative path
      await Router.load(file);
    } catch (e) {
      console.error('[WA openWorkspaceFile]', e);
      showToast('无法打开文件: ' + e.message, 'error');
    }
  };

  // ── Global Selection Tooltip ──
  let lastSelectionText = "";

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
    // Save WangEditor Slate selection before we move focus to chat input
    if (state.activeEditor && state.activeEditor.editor && state.fileType === 'docx') {
      const slateSelection = state.activeEditor.editor.selection;
      if (slateSelection) {
        state.activeEditor._savedRange = JSON.parse(JSON.stringify(slateSelection));
      }
    }
    // Pin as Copilot-style chip — user types their question separately
    state.pinnedSelection = sel;
    const preview = sel.length > 200 ? sel.substring(0, 200) + '…' : sel;
    $('wa-selection-preview').textContent = preview;
    $('wa-selection-chip').style.display = 'flex';
    $('wa-pdf-tooltip').style.display = 'none';
    $('wa-user-input').focus();
  };

  window.WA.clearSelection = () => {
    state.pinnedSelection = '';
    lastSelectionText = '';
    $('wa-selection-chip').style.display = 'none';
  };

  // Auto-pin selection when user clicks/focuses the chat input.
  // The browser clears document selection on click, so we capture it here
  // before it disappears — same effect as clicking "💬 转交 AI" manually.
  const _waInput = $('wa-user-input');
  if (_waInput) {
    _waInput.addEventListener('mousedown', () => {
      if (lastSelectionText) {
        // Always update chip — reselecting new text replaces the old context
        state.pinnedSelection = lastSelectionText;
        const preview = lastSelectionText.length > 200
          ? lastSelectionText.substring(0, 200) + '…'
          : lastSelectionText;
        $('wa-selection-preview').textContent = preview;
        $('wa-selection-chip').style.display = 'flex';
        $('wa-pdf-tooltip').style.display = 'none';

        // Save the WangEditor internal Slate selection so applyToolCall can restore it.
        // Must be done here — BEFORE the editor loses focus and browser clears the range.
        if (state.activeEditor && state.activeEditor.editor && state.fileType === 'docx') {
          const slateSelection = state.activeEditor.editor.selection;
          if (slateSelection) {
            state.activeEditor._savedRange = JSON.parse(JSON.stringify(slateSelection));
          }
        }
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
      if (this.editor) { try { this.editor.destroy(); } catch(e) { console.warn('[WangEditor destroy]', e); } }
      if (this.toolbar) { try { this.toolbar.destroy(); } catch(e) {} }
      this.editor = null;
      this.toolbar = null;

      // CRITICAL: Always recreate inner containers.
      // WangEditor modifies/replaces the selector's children on destroy().
      this._lastHtml = html;  // Fallback if getHtml() returns empty

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
            // Allow base64 images up to 5 MB — no upload server needed
            uploadImage: {
              base64LimitSize: 5 * 1024 * 1024,
            },
            insertImage: {
              // Accept all common image types
              checkImage(src) { return true; },
            },
          },
        }
      });
      this.toolbar = createToolbar({
        editor: this.editor,
        selector: '#wa-editor-toolbar',
        config: { excludeKeys: ['fullScreen'] }
      });
    }

    getContent() {
      if (!this.editor) return "";
      const selected = this.editor.getSelectionText();
      if (selected) return `[当前选中文本]:\n${selected}\n`;
      return `[文档全文]:\n${this.editor.getText()}\n`;
    }

    serialize() {
      if (!this.editor) return this._lastHtml || "";
      const html = this.editor.getHtml();
      // WangEditor empty-doc pattern: only <p><br></p> — fall back to original HTML
      const stripped = html.replace(/<p><br\s*\/?><\/p>/gi, '').replace(/<p>\s*<\/p>/gi, '').trim();
      if (!stripped) {
        console.warn('[KotoDocxEditor] getHtml() returned empty content, using stored HTML');
        return this._lastHtml || html;
      }
      return html;
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
      }
    }

    destroy() {
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
      } else if (cmd.type === 'set_cells' && window.luckysheet && Array.isArray(cmd.cells)) {
        cmd.cells.forEach(cell => {
          window.luckysheet.setCellValue(cell.r, cell.c, cell.value);
        });
        showToast(`AI 已批量更新 ${cmd.cells.length} 个单元格`, 'success');
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
      this.containerId = 'wa-pptx-editor';
      this.data = null;
      $(this.containerId).classList.add('active');
    }

    render(slidesJson) {
      this.data = slidesJson;
      const c = $(this.containerId);
      c.innerHTML = '';

      slidesJson.forEach(slide => {
        // Canvas Card
        const card = document.createElement('div');
        card.className = 'wa-slide-card';
        card.id = `slide-card-${slide.slide_id}`;
        
        let html = `<div class="wa-slide-card-header">
                      <span class="wa-slide-badge">${slide.slide_id}</span>
                      <span>幻灯片内容区</span>
                    </div>`;
        
        slide.texts.forEach(shape => {
            const badge = shape.is_title ? `<span class="wa-shape-title-badge">Title</span>` : '';
            html += `
              <div class="wa-shape-row">
                <div class="wa-shape-label">
                   <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18"/></svg>
                   ${shape.shape_name} ${badge}
                </div>
                <textarea class="wa-shape-textarea" data-slide-idx="${slide.slide_index}" data-shape-id="${shape.shape_id}" onchange="WA.pptxSync(this)">${shape.text}</textarea>
              </div>`;
        });
        
        if(slide.texts.length === 0) {
           html += `<div class="wa-shape-row" style="color:var(--text-muted);font-size:12px;text-align:center;">此幻灯片没有可编辑的文本框。</div>`;
        }

        card.innerHTML = html;
        c.appendChild(card);
      });
    }

    sync(textarea) {
      const sIdx = parseInt(textarea.getAttribute('data-slide-idx'));
      const shId = parseInt(textarea.getAttribute('data-shape-id'));
      const val = textarea.value;
      const slide = this.data.find(s => s.slide_index === sIdx);
      if (slide) {
         const shape = slide.texts.find(t => t.shape_id === shId);
         if (shape) shape.text = val;
      }
    }

    getContent() {
      // Return focused textarea or all text
      const active = document.activeElement;
      if (active && active.classList.contains('wa-shape-textarea')) {
         const sel = active.value.substring(active.selectionStart, active.selectionEnd);
         return sel ? `[当前选中 PPT 文本]:\n${sel}\n` : `[当前光标所在 PPT 文本框]:\n${active.value}\n`;
      }
      return `[PPT 大纲信息已省略，请提示用户选中特定的文本框发问]`;
    }

    serialize() {
      return this.data; // Already synced via WA.pptxSync
    }

    applyToolCall(cmd) {
      if (cmd.type === 'set_pptx_text') {
         const ta = document.querySelector(`textarea[data-slide-idx="${cmd.slide_index}"][data-shape-id="${cmd.shape_id}"]`);
         if (ta) {
             ta.value = cmd.value;
             this.sync(ta);
             showToast('AI 已更新 PPT 文本', 'success');
         }
      }
    }

    destroy() {
      $(this.containerId).classList.remove('active');
      $(this.containerId).innerHTML = '';
      this.data = null;
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
         // Save to recent files with workspace path so re-opening works
         const ext = json.file_name.split('.').pop().toLowerCase();
         // file._wsPath is set by openWorkspaceFile; for local uploads use uploads/<name>
         const wsPath = file._wsPath || ('uploads/' + json.file_name);
         _saveRecentFile(json.file_name, ext, wsPath);
         $('wa-file-name').textContent = state.fileName;
         $('wa-save-btn').disabled = (state.fileType === 'pdf');

         if (state.activeEditor) {
           try { state.activeEditor.destroy(); } catch(e) { console.warn('[destroy old editor]', e); }
         }
         state.activeEditor = null;

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
       reconnectionAttempts: 10,
       reconnectionDelay: 1000,
       reconnectionDelayMax: 5000,
     });
     
     state.socket.on('connect', () => {
       console.log('WA AI Socket connected, id:', state.socket.id);
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
        if (last && last.classList.contains('streaming')) {
           last.classList.remove('streaming');
           const finalText = data.result || '';
           last.innerHTML = renderMd(finalText);
           delete last.dataset.raw;
        } else if (data.result) {
           const msg = document.createElement('div');
           msg.className = 'wa-msg ai';
           msg.innerHTML = renderMd(data.result);
           msgs.appendChild(msg);
        }
        // Push AI response to conversation history
        if (data.result) {
           state.conversation.push({ role: 'assistant', content: data.result });
        }
        state.isLoading = false;
        msgs.scrollTop = msgs.scrollHeight;
     });

     state.socket.on('doc_tool_call', (cmd) => {
         const msgs = $('wa-ai-messages');
         const note = document.createElement('div');
         note.className = 'wa-tool-notification';
         note.innerHTML = `✨ <b>AI 执行了操作</b>: ${cmd.type}`;
         msgs.appendChild(note);
         msgs.scrollTop = msgs.scrollHeight;

         if (state.activeEditor) state.activeEditor.applyToolCall(cmd);
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

  window.WA.sendMessage = () => {
      const input = $('wa-user-input');
      const text = input.value.trim();
      if (!text) return;

      // Capture and clear pinned selection before rendering
      const pinnedSel = state.pinnedSelection;
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
      // Detect active selection
      const hasSelection = !!(state.activeEditor && state.activeEditor.editor &&
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

  window.WA.saveFile = async () => {
     if (!state.activeEditor || !state.fileType || state.fileType === 'pdf') return;
     const btn = $('wa-save-btn');
     btn.disabled = true;
     btn.innerHTML = '保存中...';

     try {
         const data = state.activeEditor.serialize();
         const payload = {
            file_type: state.fileType,
            file_id: state.fileId,
            file_name: state.fileName,
            data: data
         };

         const res = await fetch('/api/v1/workspace/save_file', {
             method: 'POST',
             headers: { 'Content-Type': 'application/json' },
             body: JSON.stringify(payload)
         });

         if (!res.ok) {
             const json = await res.json();
             throw new Error(json.error || '导出失败');
         }

         // Trigger download
         const blob = await res.blob();
         const url = window.URL.createObjectURL(blob);
         const a = document.createElement('a');
         a.href = url;
         a.download = state.fileName.includes('.') ? 
             state.fileName.substring(0, state.fileName.lastIndexOf('.')) + '_modified.' + state.fileType : 
             `koto_export.${state.fileType}`;
         document.body.appendChild(a);
         a.click();
         a.remove();
         window.URL.revokeObjectURL(url);
         
         showToast('导出成功', 'success');
     } catch(e) {
         showToast(e.message, 'error');
     } finally {
         btn.disabled = false;
         btn.innerHTML = `<svg width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg> 保存 / 导出`;
     }
  };

  // ── Drag & Drop Events ──
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
  dropZone.addEventListener('click', () => fileInput.click());
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
  leftDrop.addEventListener('click', () => fileInputLeft.click());
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
  renderRecentFiles();

  // ── Local file / folder pickers ──
  const localFileInput = $('wa-local-file-input');
  const localFolderInput = $('wa-local-folder-input');

  $('wa-pick-local-file-btn').addEventListener('click', () => localFileInput.click());
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

})();
