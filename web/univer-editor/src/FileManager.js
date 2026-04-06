// ══════════════════════════════════════════════════════════════
// FileManager.js — 模块 D：文件导入与管理面板
//
// 渲染左侧文件导航树，支持：
//   - 新建空白文档
//   - 导入文件（.txt / .md / .docx / .pdf 等）
//   - 文档列表切换（自动保存/加载 Univer 快照）
//   - 重命名 / 删除文档
//   - 导出为 .txt
//
// 约束：只通过 DocController 操控 Univer，不直接访问底层 API。
// ══════════════════════════════════════════════════════════════

const API_BASE = '/api/editor/docs';

export class FileManager {
  /**
   * @param {string} sidebarId        左侧 sidebar 的 DOM id
   * @param {import('./DocController').DocController} docController
   * @param {function} onDocSwitch    文档切换时的回调（新 snapshot）
   * @param {import('./DocxViewer').DocxViewer|null} docxViewer  可选 DOCX 查看器
   */
  constructor(sidebarId, docController, onDocSwitch, docxViewer = null) {
    this._sidebar = document.getElementById(sidebarId);
    this._doc = docController;
    this._onDocSwitch = onDocSwitch;
    this._docxViewer = docxViewer;

    /** @type {Array<{id:string, name:string, updatedAt:string}>} */
    this._files = [];
    /** @type {string|null} */
    this._activeId = null;
    /** @type {boolean} */
    this._loading = false;

    this._render();
    this._bindGlobal();
    this.refresh();
  }

  // ══════════════════ 初始 UI 渲染 ══════════════════

  _render() {
    this._sidebar.innerHTML = `
      <div class="sidebar-header">
        <span class="sidebar-title">文件管理</span>
      </div>
      <div class="fm-toolbar">
        <button id="fm-btn-new" class="fm-tool-btn" title="新建空白文档">
          <span class="fm-icon">＋</span>
        </button>
        <button id="fm-btn-import" class="fm-tool-btn" title="导入文件">
          <span class="fm-icon">📂</span>
        </button>
        <button id="fm-btn-refresh" class="fm-tool-btn" title="刷新列表">
          <span class="fm-icon">↻</span>
        </button>
      </div>
      <div id="fm-file-list" class="file-tree">
        <div class="file-tree-empty">加载中…</div>
      </div>
      <div class="save-bar">
        <button id="fm-btn-save" class="save-btn" title="保存 (Ctrl+S)">💾 保存</button>
        <span id="fm-save-status" class="save-status"></span>
      </div>
      <input type="file" id="fm-file-input" style="display:none"
             accept=".txt,.md,.docx,.pdf,.html,.csv,.json,.rtf" multiple />
    `;
  }

  // ══════════════════ 事件绑定 ══════════════════

  _bindGlobal() {
    this._sidebar.querySelector('#fm-btn-new').addEventListener('click', () => this._createDoc());
    this._sidebar.querySelector('#fm-btn-import').addEventListener('click', () => {
      this._sidebar.querySelector('#fm-file-input').click();
    });
    this._sidebar.querySelector('#fm-btn-refresh').addEventListener('click', () => this.refresh());
    this._sidebar.querySelector('#fm-file-input').addEventListener('change', (e) => {
      this._importFiles(e.target.files);
      e.target.value = '';
    });
    this._sidebar.querySelector('#fm-btn-save').addEventListener('click', () => this.saveWithFeedback());

    // Ctrl+S → 保存
    document.addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 's') {
        e.preventDefault();
        this.saveWithFeedback();
      }
    });

    // Drag & drop
    const listEl = this._sidebar.querySelector('#fm-file-list');
    listEl.addEventListener('dragover', (e) => { e.preventDefault(); listEl.classList.add('fm-dragover'); });
    listEl.addEventListener('dragleave', () => listEl.classList.remove('fm-dragover'));
    listEl.addEventListener('drop', (e) => {
      e.preventDefault();
      listEl.classList.remove('fm-dragover');
      if (e.dataTransfer.files.length) this._importFiles(e.dataTransfer.files);
    });
  }

  // ══════════════════ API 调用 ══════════════════

  async _api(path, method = 'GET', body = null) {
    const opts = { method, headers: {} };
    if (body instanceof FormData) {
      opts.body = body;
    } else if (body) {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body);
    }
    const resp = await fetch(`${API_BASE}${path}`, opts);
    if (!resp.ok) throw new Error(`API ${method} ${path} → ${resp.status}`);
    return resp.json();
  }

  // ══════════════════ 文件列表 ══════════════════

  async refresh() {
    try {
      const data = await this._api('');
      this._files = data.docs || [];
      this._renderList();
    } catch (e) {
      console.error('[FileManager] refresh failed:', e);
      this._renderList();
    }
  }

  _renderList() {
    const listEl = this._sidebar.querySelector('#fm-file-list');
    if (this._files.length === 0) {
      listEl.innerHTML = `
        <div class="file-tree-empty">
          <div style="margin-bottom:8px">暂无文档</div>
          <div style="font-size:11px;color:#555">点击上方 ＋ 新建，或拖拽文件到此处导入</div>
        </div>`;
      return;
    }

    listEl.innerHTML = this._files.map(f => `
      <div class="file-tree-item${f.id === this._activeId ? ' active' : ''}" data-id="${f.id}">
        <span class="icon">${this._fileIcon(f.name)}</span>
        <span class="fm-name" title="${this._escHtml(f.name)}">${this._escHtml(f.name)}</span>
        <span class="fm-actions">
          <button class="fm-act-btn fm-act-rename" data-id="${f.id}" title="重命名">✏️</button>
          <button class="fm-act-btn fm-act-delete" data-id="${f.id}" title="删除">🗑️</button>
        </span>
      </div>`).join('');

    // Bind click events
    listEl.querySelectorAll('.file-tree-item').forEach(el => {
      el.addEventListener('click', (e) => {
        if (e.target.closest('.fm-act-btn')) return;
        this._switchDoc(el.dataset.id);
      });
    });
    listEl.querySelectorAll('.fm-act-rename').forEach(btn => {
      btn.addEventListener('click', (e) => { e.stopPropagation(); this._renameDoc(btn.dataset.id); });
    });
    listEl.querySelectorAll('.fm-act-delete').forEach(btn => {
      btn.addEventListener('click', (e) => { e.stopPropagation(); this._deleteDoc(btn.dataset.id); });
    });
  }

  // ══════════════════ 新建文档 ══════════════════

  async _createDoc() {
    const name = prompt('文档名称：', `未命名文档 ${this._files.length + 1}`);
    if (!name || !name.trim()) return;

    try {
      // Save current doc first
      await this._saveCurrentDoc();

      const data = await this._api('', 'POST', { name: name.trim() });
      this._activeId = data.id;
      await this.refresh();

      // Load the new blank document into Univer
      if (this._onDocSwitch) this._onDocSwitch(null, data.id);
      console.log('[FileManager] Created doc:', data.id);
    } catch (e) {
      console.error('[FileManager] Create failed:', e);
      alert('创建文档失败: ' + e.message);
    }
  }

  // ══════════════════ 导入文件 ══════════════════

  async _importFiles(fileList) {
    let lastImportedDoc = null;
    for (const file of fileList) {
      try {
        const fd = new FormData();
        fd.append('file', file);
        const data = await this._api('/import', 'POST', fd);
        this._activeId = data.id;
        lastImportedDoc = data;
        console.log('[FileManager] Imported:', file.name, '→', data.id);
      } catch (e) {
        console.error('[FileManager] Import failed:', file.name, e);
        alert(`导入 "${file.name}" 失败: ${e.message}`);
      }
    }
    await this.refresh();
    // Switch to the last imported doc
    if (lastImportedDoc && this._activeId) {
      if (lastImportedDoc.sourceExt === '.docx' && this._docxViewer) {
        await this._renderDocx(lastImportedDoc.id, lastImportedDoc.name || lastImportedDoc.id);
      } else {
        const doc = await this._api(`/${this._activeId}`);
        if (this._docxViewer) this._docxViewer.hide();
        if (this._onDocSwitch) this._onDocSwitch(doc.content || null, this._activeId);
      }
    }
  }

  // ══════════════════ 切换文档 ══════════════════

  async _switchDoc(docId) {
    if (docId === this._activeId || this._loading) return;
    this._loading = true;

    try {
      // Save current doc
      await this._saveCurrentDoc();

      // Load new doc
      const data = await this._api(`/${docId}`);
      this._activeId = docId;
      this._renderList();

      if (data.sourceExt === '.docx' && this._docxViewer) {
        // ── DOCX: render in Word-sim viewer ──
        await this._renderDocx(docId, data.name || docId);
      } else {
        // ── Plain text / blank doc ──
        if (this._docxViewer) this._docxViewer.hide();
        if (this._onDocSwitch) this._onDocSwitch(data.content || null, docId);
      }
      console.log('[FileManager] Switched to:', docId);
    } catch (e) {
      console.error('[FileManager] Switch failed:', e);
    } finally {
      this._loading = false;
    }
  }

  // ── 从后端取原始 DOCX 二进制并交给 DocxViewer 渲染 ──
  async _renderDocx(docId, name) {
    try {
      // Fetch source binary and page metadata in parallel
      const [sourceResp, metaResp] = await Promise.all([
        fetch(`/api/editor/docs/${encodeURIComponent(docId)}/source`),
        fetch(`/api/editor/docs/${encodeURIComponent(docId)}/meta`),
      ]);

      if (!sourceResp.ok) throw new Error(`HTTP ${sourceResp.status}`);
      const buffer = await sourceResp.arrayBuffer();

      // Apply meta (page size, margins, default font) before render
      if (metaResp.ok) {
        const meta = await metaResp.json();
        this._docxViewer.setMeta(meta);
      }

      await this._docxViewer.render(buffer, name);
    } catch (e) {
      console.error('[FileManager] DOCX fetch failed:', e);
      if (this._docxViewer) {
        this._docxViewer.show();
        const el = document.getElementById('docx-render-area');
        if (el) el.innerHTML = `<div class="docx-error">⚠ 无法加载原始文件：${e.message}</div>`;
      }
    }
  }

  // ══════════════════ 保存当前文档 ══════════════════

  async _saveCurrentDoc() {
    if (!this._activeId) return;
    try {
      const text = this._doc.getFullText();
      const snapshot = this._doc.getSnapshot?.() || null;
      await this._api(`/${this._activeId}`, 'PUT', {
        content: text,
        snapshot: snapshot,
      });
    } catch (e) {
      console.warn('[FileManager] Auto-save failed:', e);
    }
  }

  /** 公开方法：供外部调用（如定时自动保存） */
  save() {
    return this._saveCurrentDoc();
  }

  /** 带 UI 反馈的保存 */
  async saveWithFeedback() {
    const statusEl = document.getElementById('fm-save-status');
    if (!this._activeId) {
      if (statusEl) { statusEl.textContent = '无活动文档'; statusEl.className = 'save-status'; }
      return;
    }
    try {
      if (statusEl) { statusEl.textContent = '保存中…'; statusEl.className = 'save-status saving'; }
      await this._saveCurrentDoc();
      if (statusEl) { statusEl.textContent = '✓ 已保存'; statusEl.className = 'save-status saved'; }
      setTimeout(() => { if (statusEl) statusEl.textContent = ''; }, 2000);
    } catch (e) {
      if (statusEl) { statusEl.textContent = '保存失败'; statusEl.className = 'save-status'; }
    }
  }

  /** 设置当前激活文档 ID（首次加载时用） */
  setActiveId(id) {
    this._activeId = id;
    this._renderList();
  }

  // ══════════════════ 重命名 ══════════════════

  async _renameDoc(docId) {
    const file = this._files.find(f => f.id === docId);
    if (!file) return;
    const newName = prompt('新名称：', file.name);
    if (!newName || !newName.trim() || newName.trim() === file.name) return;

    try {
      await this._api(`/${docId}`, 'PATCH', { name: newName.trim() });
      await this.refresh();
    } catch (e) {
      console.error('[FileManager] Rename failed:', e);
      alert('重命名失败: ' + e.message);
    }
  }

  // ══════════════════ 删除 ══════════════════

  async _deleteDoc(docId) {
    const file = this._files.find(f => f.id === docId);
    if (!file) return;
    if (!confirm(`确定删除 "${file.name}" 吗？此操作不可撤销。`)) return;

    try {
      await this._api(`/${docId}`, 'DELETE');
      if (this._activeId === docId) {
        this._activeId = null;
        // Load next available doc or show empty
        if (this._onDocSwitch) this._onDocSwitch(null, null);
      }
      await this.refresh();
    } catch (e) {
      console.error('[FileManager] Delete failed:', e);
      alert('删除失败: ' + e.message);
    }
  }

  // ══════════════════ 工具方法 ══════════════════

  _fileIcon(name) {
    const ext = (name || '').split('.').pop().toLowerCase();
    const map = {
      pdf: '📕', docx: '📘', doc: '📘', txt: '📄', md: '📝',
      html: '🌐', csv: '📊', json: '📋', rtf: '📃',
    };
    return map[ext] || '📄';
  }

  _escHtml(str) {
    const d = document.createElement('div');
    d.textContent = str;
    return d.innerHTML;
  }
}
