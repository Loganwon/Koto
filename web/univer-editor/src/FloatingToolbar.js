// ══════════════════════════════════════════════════════════════
// FloatingToolbar.js — 模块 E：文本选区浮动 AI 工具栏
//
// 监听编辑器区域的文本选择事件，当用户高亮选中文本时，
// 在选区附近弹出浮动工具栏，提供快捷 AI 操作按钮。
// ══════════════════════════════════════════════════════════════

export class FloatingToolbar {
  /**
   * @param {import('./DocController').DocController} docController
   * @param {import('./SocketBridge').SocketBridge} socketBridge
   * @param {import('./AIPanel').AIPanel} aiPanel
   */
  constructor(docController, socketBridge, aiPanel) {
    this._doc = docController;
    this._bridge = socketBridge;
    this._panel = aiPanel;
    this._toolbar = null;
    this._selectedText = '';
    this._selectionRange = null;
    this._hideTimer = null;
    this._autoHideTimer = null;
    this._pinned = false;
    this._docxMode = false;

    this._createDOM();
    this._bindEvents();
  }

  // ══════════════════ DOM 创建 ══════════════════

  // Three quick-access actions always visible in toolbar
  static PRIMARY_ACTIONS = [
    { action: 'polish',    label: '润色' },
    { action: 'explain',  label: '解释' },
    { action: 'translate', label: '翻译' },
  ];

  // All additional actions accessible via command palette (···)
  static ALL_ACTIONS = [
    { action: 'rewrite',          label: '改写' },
    { action: 'continue_writing', label: '续写' },
    { action: 'summarize',        label: '摘要' },
    { action: 'chart',            label: '可视化' },
    { action: 'annotate',         label: '標注' },
    { action: 'find_replace',     label: '批量替换' },
    { action: 'find_reference',   label: '查找引用' },
    { action: 'quote',            label: '引用格式' },
    { action: 'custom',           label: '自定义指令' },
  ];

  _createDOM() {
    this._toolbar = document.createElement('div');
    this._toolbar.id = 'floating-ai-toolbar';
    this._toolbar.className = 'floating-toolbar hidden';

    const row = document.createElement('div');
    row.className = 'ft-row';

    // Three primary action buttons
    FloatingToolbar.PRIMARY_ACTIONS.forEach(a => {
      const btn = document.createElement('button');
      btn.className = 'ft-btn';
      btn.dataset.action = a.action;
      btn.title = a.label;
      btn.textContent = a.label;
      btn.addEventListener('click', (e) => { e.preventDefault(); e.stopPropagation(); this._onAction(a.action); });
      row.appendChild(btn);
    });

    // Thin vertical separator
    const sep = document.createElement('span');
    sep.className = 'ft-sep';
    row.appendChild(sep);

    // ··· command palette toggle
    const moreBtn = document.createElement('button');
    moreBtn.className = 'ft-btn ft-more-btn';
    moreBtn.title = '更多操作';
    moreBtn.textContent = '···';
    moreBtn.addEventListener('click', (e) => {
      e.preventDefault(); e.stopPropagation();
      this._togglePalette();
      this._resetAutoHide();
    });
    row.appendChild(moreBtn);

    // Pin button — keep toolbar visible until unpinned
    const pinBtn = document.createElement('button');
    pinBtn.className = 'ft-btn ft-pin-btn';
    pinBtn.title = '固定工具栏';
    pinBtn.textContent = '📌';
    pinBtn.addEventListener('click', (e) => {
      e.preventDefault(); e.stopPropagation();
      this._pinned = !this._pinned;
      pinBtn.classList.toggle('active', this._pinned);
      pinBtn.title = this._pinned ? '取消固定' : '固定工具栏';
      if (this._pinned) {
        this._clearAutoHide();
      } else {
        this._resetAutoHide();
      }
    });
    row.appendChild(pinBtn);
    this._pinBtn = pinBtn;

    this._toolbar.appendChild(row);

    // Command palette — remaining actions in a compact grid
    this._palette = document.createElement('div');
    this._palette.className = 'ft-palette hidden';

    FloatingToolbar.ALL_ACTIONS.forEach(a => {
      const item = document.createElement('button');
      item.className = 'ft-palette-item';
      item.dataset.action = a.action;
      item.textContent = a.label;
      item.addEventListener('click', (e) => { e.preventDefault(); e.stopPropagation(); this._onAction(a.action); });
      this._palette.appendChild(item);
    });

    this._toolbar.appendChild(this._palette);

    // Prevent toolbar clicks from losing selection
    this._toolbar.addEventListener('mousedown', (e) => {
      e.preventDefault();
      e.stopPropagation();
    });

    // Reset auto-hide on hover
    this._toolbar.addEventListener('mouseenter', () => this._resetAutoHide());
    this._toolbar.addEventListener('mouseleave', () => this._startAutoHide());

    document.body.appendChild(this._toolbar);
  }

  // ══════════════════ 事件绑定 ══════════════════

  _bindEvents() {
    const editorArea = document.getElementById('center-doc');
    if (!editorArea) return;

    // Track whether the mouse button is currently held down (drag-select in progress).
    // While dragging, we suppress selectionchange callbacks so the toolbar only
    // appears/repositions once the user releases the mouse — not mid-drag.
    this._mouseIsDown = false;
    editorArea.addEventListener('mousedown', () => { this._mouseIsDown = true; });
    document.addEventListener('mouseup', () => { this._mouseIsDown = false; }, true);

    editorArea.addEventListener('mouseup', () => {
      setTimeout(() => this._checkSelection(), 50);
    });

    // Touch support: fire on touchend inside the editor (mobile text selection)
    editorArea.addEventListener('touchend', () => {
      setTimeout(() => this._checkSelection(), 150);
    });

    // selectionchange fires on all browsers (desktop + mobile) when selection changes.
    // Skip while mouse is held — the drag is still changing the selection and the
    // final result will be picked up on mouseup.
    document.addEventListener('selectionchange', () => {
      if (this._mouseIsDown) return;
      if (this._selChangeTimer) clearTimeout(this._selChangeTimer);
      this._selChangeTimer = setTimeout(() => {
        const sel = window.getSelection();
        if (!sel || sel.isCollapsed) return;
        this._checkSelection();
      }, 200);
    });

    editorArea.addEventListener('keyup', (e) => {
      if (e.shiftKey || e.key === 'Shift') {
        setTimeout(() => this._checkSelection(), 50);
      }
    });

    document.addEventListener('mousedown', (e) => {
      const insideEditor = editorArea.contains(e.target);
      if (insideEditor) {
        // Click inside the editor starts a new selection — cancel any pending hide
        // so the toolbar isn't removed mid-drag. Visibility is managed by _checkSelection
        // which fires on mouseup.
        if (this._hideTimer) { clearTimeout(this._hideTimer); this._hideTimer = null; }
      } else if (this._toolbar && !this._toolbar.contains(e.target)) {
        this._hideTimer = setTimeout(() => this.hide(), 200);
      }
      if (this._cmdInput && !this._cmdInput.contains(e.target)) {
        this._hideCmdInput();
      }
    });

    editorArea.addEventListener('scroll', () => { this.hide(); this._hideCmdInput(); }, true);

    // Ctrl+K — show inline AI command input near current selection
    document.addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        // Only activate when cursor is inside the editor area
        const active = document.activeElement;
        const inEditor = editorArea.contains(active) || editorArea.contains(document.getSelection()?.anchorNode);
        if (!inEditor && !this._selectedText) return;
        e.preventDefault();
        e.stopPropagation();
        this._showCmdInput();
      }
    });
  }

  // ══════════════════ Ctrl+K 命令面板 ══════════════════

  _createCmdInput() {
    this._cmdInput = document.createElement('div');
    this._cmdInput.id = 'ft-cmd-input';
    this._cmdInput.className = 'ft-cmd-input hidden';
    this._cmdInput.innerHTML = `
      <div class="ft-cmd-row">
        <span class="ft-cmd-icon">⌘K</span>
        <input id="ft-cmd-text" class="ft-cmd-text" type="text" placeholder="输入 AI 指令…" autocomplete="off" spellcheck="false">
        <button class="ft-cmd-close" title="取消 (Esc)">✕</button>
      </div>
      <div class="ft-cmd-chips">
        <button class="ft-chip" data-action="polish">✨ 润色</button>
        <button class="ft-chip" data-action="translate">🌐 翻译</button>
        <button class="ft-chip" data-action="rewrite">✏️ 改写</button>
        <button class="ft-chip" data-action="check">🔍 检查</button>
        <button class="ft-chip" data-action="summarize">📋 总结</button>
      </div>
    `;
    document.body.appendChild(this._cmdInput);

    const input = this._cmdInput.querySelector('#ft-cmd-text');

    // Quick-chip buttons
    this._cmdInput.querySelectorAll('.ft-chip[data-action]').forEach(btn => {
      btn.addEventListener('mousedown', (e) => {
        e.preventDefault();
        this._onAction(btn.dataset.action);
        this._hideCmdInput();
      });
    });

    // Close button
    this._cmdInput.querySelector('.ft-cmd-close').addEventListener('mousedown', (e) => {
      e.preventDefault();
      this._hideCmdInput();
    });

    // Enter to send
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        const cmd = input.value.trim();
        if (!cmd) return;
        this._dispatchCmdInstruction(cmd);
        this._hideCmdInput();
      } else if (e.key === 'Escape') {
        e.preventDefault();
        this._hideCmdInput();
      }
    });

    // Prevent losing selection
    this._cmdInput.addEventListener('mousedown', (e) => e.preventDefault());
  }

  _showCmdInput() {
    if (!this._cmdInput) this._createCmdInput();
    // Re-capture current selection
    this._checkSelection();

    const sel = window.getSelection();
    let rect = null;
    if (sel && sel.rangeCount > 0) {
      try { rect = sel.getRangeAt(0).getBoundingClientRect(); } catch (_) {}
    }

    const w = 340;
    let left = 0, top = 0;
    if (rect && rect.width > 0) {
      left = rect.left + (rect.width / 2) - (w / 2);
      top = rect.bottom + 10;
    } else {
      left = window.innerWidth / 2 - w / 2;
      top = 160;
    }
    left = Math.max(8, Math.min(left, window.innerWidth - w - 8));
    top = Math.min(top, window.innerHeight - 120);

    this._cmdInput.style.left = left + 'px';
    this._cmdInput.style.top = top + 'px';
    this._cmdInput.style.width = w + 'px';
    this._cmdInput.classList.remove('hidden');

    const textInput = this._cmdInput.querySelector('#ft-cmd-text');
    textInput.value = '';
    setTimeout(() => textInput.focus(), 30);

    this.hide(); // hide the regular floating toolbar
  }

  _hideCmdInput() {
    if (this._cmdInput) this._cmdInput.classList.add('hidden');
  }

  /** Returns full text from whichever viewer is active (DOCX / PPTX / Excel), else Univer canvas. */
  _getViewerFullText() {
    const dv = window.__koto?.docxViewer;
    if (dv && dv.isActive()) return dv.getFullText();
    const pv = window.__koto?.pptxViewer;
    if (pv && pv.isActive()) return pv.getFullText();
    const ev = window.__koto?.excelViewer;
    if (ev && ev.isActive()) return ev.getFullText();
    return this._doc.getFullText();
  }

  _dispatchCmdInstruction(instruction) {
    if (!this._selectedText && !instruction) return;
    const selData = this._selectedText ? {
      text: this._selectedText,
      range: this._selectionRange,
      fullText: this._getViewerFullText(),
      _docxMode: this._docxMode,
    } : null;
    const displayText = this._selectedText
      ? `⌘K：「${this._truncate(this._selectedText, 40)}」→ ${instruction}`
      : `⌘K：${instruction}`;
    this._panel.addMessage(displayText, 'user');
    this._panel._sendViaMainAI('custom_instruction', this._selectedText || '', selData, instruction);
    this._showAIPanel();
  }

  // ══════════════════ 选区检测 ══════════════════

  _checkSelection() {
    const sel = window.getSelection();
    if (!sel || sel.isCollapsed || !sel.rangeCount) { this.hide(); return; }
    const text = sel.toString().trim();
    if (!text || text.length < 1) { this.hide(); return; }

    const editorArea = document.getElementById('center-doc');
    const range = sel.getRangeAt(0);
    if (!editorArea || !editorArea.contains(range.commonAncestorContainer)) { this.hide(); return; }

    this._selectedText = text;

    // Update word count badge
    const wordCount = text.replace(/\s+/g, ' ').trim().split(' ').length;
    const charCount = text.replace(/\s/g, '').length;
    const badge = document.getElementById('ft-word-count');
    if (badge) badge.textContent = `${charCount}字`;

    const _dv = window.__koto?.docxViewer;
    this._docxMode = !!(_dv && _dv.isActive());
    const fullText = this._getViewerFullText();
    const idx = fullText.indexOf(text);
    this._selectionRange = idx >= 0
      ? { startOffset: idx, endOffset: idx + text.length }
      : { startOffset: 0, endOffset: fullText.length };

    this._positionToolbar(range);
    this._resetAutoHide();
  }

  _positionToolbar(range) {
    const rect = range.getBoundingClientRect();
    if (!rect || (rect.width === 0 && rect.height === 0)) { this.hide(); return; }

    const tb = this._toolbar;
    tb.classList.remove('hidden');

    const tbRect = tb.getBoundingClientRect();
    const tbWidth = tbRect.width || 260;
    const tbHeight = tbRect.height || 36;

    let left = rect.left + (rect.width / 2) - (tbWidth / 2);
    // Always prefer below the selection so Univer's format toolbar stays above unobstructed
    let top = rect.bottom + 8;
    if (top + tbHeight + 4 > window.innerHeight) top = rect.top - tbHeight - 8;
    if (top < 4) top = rect.bottom + 8; // last resort: below even if tight at bottom
    left = Math.max(4, Math.min(left, window.innerWidth - tbWidth - 4));

    tb.style.left = left + 'px';
    tb.style.top = top + 'px';

    if (this._hideTimer) { clearTimeout(this._hideTimer); this._hideTimer = null; }
  }

  // ══════════════════ 自动隐藏 ══════════════════

  _startAutoHide() {
    if (this._pinned) return;
    this._clearAutoHide();
    this._autoHideTimer = setTimeout(() => this.hide(), 8000);
  }

  _resetAutoHide() {
    if (this._pinned) return;
    this._clearAutoHide();
    this._autoHideTimer = setTimeout(() => this.hide(), 8000);
  }

  _clearAutoHide() {
    if (this._autoHideTimer) { clearTimeout(this._autoHideTimer); this._autoHideTimer = null; }
  }

  // ══════════════════ 操作处理 ══════════════════

  _onAction(action) {
    if (!this._selectedText && action !== 'find_replace') return;

    const selData = {
      text: this._selectedText,
      range: this._selectionRange,
      fullText: this._getViewerFullText(),
      _docxMode: this._docxMode,
    };

    const allActions = [...FloatingToolbar.PRIMARY_ACTIONS, ...FloatingToolbar.ALL_ACTIONS];
    const labelMap = {};
    allActions.forEach(a => { labelMap[a.action] = a.label; });
    const label = labelMap[action] || action;
    const preview = this._truncate(this._selectedText, 40);

    if (action === 'find_replace') {
      // Find & replace operates on full document
      this._panel._onAction('find_replace');
    } else if (action === 'find_reference') {
      this._panel.addMessage(`📚 查找引用：「${preview}」`, 'user');
      this._panel._sendViaMainAI('find_reference', this._selectedText, selData, '');
    } else if (action === 'quote') {
      const quoted = `\n「${this._selectedText}」\n`;
      this._panel.addMessage('引用格式化', 'user');
      this._panel.startStreamMessage?.();
      this._panel.appendStreamChunk?.(quoted);
      this._panel.finalizeStreamMessage?.(quoted, 'quote', selData);
    } else if (action === 'custom') {
      const instruction = prompt('输入 AI 指令（将应用于选中文本）：');
      if (!instruction) return;
      this._panel.addMessage(instruction, 'user');
      this._bridge.sendAction('custom_instruction', { instruction, context: selData });
    } else if (action === 'chart') {
      // Chart: use selection as data context
      this._panel.addMessage(`📊 可视化：「${preview}」`, 'user');
      this._panel._sendViaChart(this._selectedText, '');
    } else if (action === 'explain') {
      // Route through SSE (_sendViaMainAI) so it gets explain-specific
      // apply buttons ("插入解释") instead of generic "替换选中内容".
      this._panel.addMessage(`💡 解释：「${preview}」`, 'user');
      this._panel._sendViaMainAI('explain', this._selectedText, selData, '请解释以下内容的含义、背景或重要性，语言简洁易懂：');
    } else {
      this._panel.addMessage(`${label}：「${preview}」`, 'user');
      this._bridge.sendAction(action, selData);
    }

    this._showAIPanel();
    this.hide();
    this._clearAutoHide();
  }

  _showAIPanel() {
    const panel = document.getElementById('right-ai-panel');
    if (panel && panel.classList.contains('collapsed')) {
      panel.classList.remove('collapsed');
      const toggle = document.getElementById('ai-panel-toggle');
      if (toggle) toggle.textContent = '▶';
    }
    if (this._panel && typeof this._panel.expand === 'function') {
      this._panel.expand();
    }
  }

  // ══════════════════ 显隐控制 ══════════════════

  _togglePalette() {
    if (this._palette) {
      const willShow = this._palette.classList.contains('hidden');
      this._palette.classList.toggle('hidden');
      // Close palette if clicking ··· again when open
      const moreBtn = this._toolbar.querySelector('.ft-more-btn');
      if (moreBtn) moreBtn.classList.toggle('active', willShow);
    }
  }

  hide() {
    if (this._toolbar) {
      this._toolbar.classList.add('hidden');
      if (this._palette) this._palette.classList.add('hidden');
    }
    this._clearAutoHide();
  }

  _truncate(str, max) {
    return str.length > max ? str.substring(0, max) + '…' : str;
  }
}


