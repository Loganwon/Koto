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

    this._createDOM();
    this._bindEvents();
  }

  // ══════════════════ DOM 创建 ══════════════════

  _createDOM() {
    this._toolbar = document.createElement('div');
    this._toolbar.id = 'floating-ai-toolbar';
    this._toolbar.className = 'floating-toolbar hidden';
    this._toolbar.style.flexWrap = 'wrap';
    this._toolbar.style.maxWidth = '270px';
    this._toolbar.innerHTML = `
      <button class="ft-btn" data-action="translate"        title="翻译">🌐 翻译</button>
      <button class="ft-btn" data-action="rewrite"          title="改写">✏️ 改写</button>
      <button class="ft-btn" data-action="continue_writing" title="续写">📝 续写</button>
      <button class="ft-btn" data-action="polish"           title="润色">✨ 润色</button>
      <button class="ft-btn" data-action="summarize"        title="摘要">📋 摘要</button>
      <button class="ft-btn" data-action="annotate"         title="标注">🔖 标注</button>
      <button class="ft-btn" data-action="quote"            title="引用">❝ 引用</button>
      <button class="ft-btn" data-action="custom"           title="AI 指令">💬 AI</button>
    `;
    document.body.appendChild(this._toolbar);

    // 防止点击工具栏时丢失选区
    this._toolbar.addEventListener('mousedown', (e) => {
      e.preventDefault();
      e.stopPropagation();
    });

    // 按钮点击
    this._toolbar.querySelectorAll('.ft-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        const action = btn.dataset.action;
        this._onAction(action);
      });
    });
  }

  // ══════════════════ 事件绑定 ══════════════════

  _bindEvents() {
    const editorArea = document.getElementById('center-doc');
    if (!editorArea) return;

    // mouseup 检测选区
    editorArea.addEventListener('mouseup', () => {
      // 短暂延迟让浏览器完成选区更新
      setTimeout(() => this._checkSelection(), 50);
    });

    // 键盘选择（Shift+方向键等）
    editorArea.addEventListener('keyup', (e) => {
      if (e.shiftKey || e.key === 'Shift') {
        setTimeout(() => this._checkSelection(), 50);
      }
    });

    // 点击其他地方隐藏
    document.addEventListener('mousedown', (e) => {
      if (this._toolbar && !this._toolbar.contains(e.target)) {
        // 延迟隐藏，让按钮点击有机会执行
        this._hideTimer = setTimeout(() => this.hide(), 200);
      }
    });

    // 滚动时隐藏
    editorArea.addEventListener('scroll', () => this.hide(), true);
  }

  // ══════════════════ 选区检测 ══════════════════

  _checkSelection() {
    const sel = window.getSelection();
    if (!sel || sel.isCollapsed || !sel.rangeCount) {
      this.hide();
      return;
    }

    const text = sel.toString().trim();
    if (!text || text.length < 1) {
      this.hide();
      return;
    }

    // 确保选区在编辑器区域内
    const editorArea = document.getElementById('center-doc');
    const range = sel.getRangeAt(0);
    if (!editorArea || !editorArea.contains(range.commonAncestorContainer)) {
      this.hide();
      return;
    }

    this._selectedText = text;

    // 计算选中文本在文档 dataStream 中的 offset
    const fullText = this._doc.getFullText();
    const idx = fullText.indexOf(text);
    if (idx >= 0) {
      this._selectionRange = { startOffset: idx, endOffset: idx + text.length };
    } else {
      this._selectionRange = { startOffset: 0, endOffset: fullText.length };
    }

    // 定位并显示浮动工具栏
    this._positionToolbar(range);
  }

  _positionToolbar(range) {
    const rect = range.getBoundingClientRect();
    if (!rect || (rect.width === 0 && rect.height === 0)) {
      this.hide();
      return;
    }

    const tb = this._toolbar;
    tb.classList.remove('hidden');

    // 先设为可见以获取尺寸
    const tbRect = tb.getBoundingClientRect();
    const tbWidth = tbRect.width || 200;
    const tbHeight = tbRect.height || 36;

    // 定位在选区上方居中
    let left = rect.left + (rect.width / 2) - (tbWidth / 2);
    let top = rect.top - tbHeight - 8;

    // 如果上方空间不够，放到下方
    if (top < 4) {
      top = rect.bottom + 8;
    }

    // 防止超出左右边界
    left = Math.max(4, Math.min(left, window.innerWidth - tbWidth - 4));

    tb.style.left = left + 'px';
    tb.style.top = top + 'px';

    if (this._hideTimer) {
      clearTimeout(this._hideTimer);
      this._hideTimer = null;
    }
  }

  // ══════════════════ 操作处理 ══════════════════

  _onAction(action) {
    if (!this._selectedText) return;

    const selData = {
      text: this._selectedText,
      range: this._selectionRange,
      fullText: this._doc.getFullText(),
    };
    const preview = this._truncate(this._selectedText, 40);
    const labelMap = {
      translate: '翻译', rewrite: '改写', continue_writing: '续写',
      polish: '润色', summarize: '摘要', annotate: '标注',
      quote: '引用', custom: 'AI',
    };

    if (action === 'quote') {
      // 引用：纯客户端格式化
      const quoted = '\n「' + this._selectedText + '」\n';
      this._panel.addMessage('引用格式化', 'user');
      this._panel.startStreamMessage();
      this._panel.appendStreamChunk(quoted);
      this._panel.finalizeStreamMessage(quoted, 'quote', selData);
    } else if (action === 'custom') {
      const instruction = prompt('输入 AI 指令：');
      if (!instruction) return;
      this._panel.addMessage(instruction, 'user');
      this._bridge.sendAction('custom_instruction', { instruction, context: selData });
    } else {
      this._panel.addMessage(`${labelMap[action] || action}：「${preview}」`, 'user');
      this._bridge.sendAction(action, selData);
    }

    this._panel.expand();
    this.hide();
  }

  _showAIPanel() {
    const panel = document.getElementById('right-ai-panel');
    if (panel && panel.classList.contains('collapsed')) {
      panel.classList.remove('collapsed');
      const toggle = document.getElementById('ai-panel-toggle');
      if (toggle) toggle.textContent = '▶';
    }
  }

  // ══════════════════ 显隐控制 ══════════════════

  hide() {
    if (this._toolbar) {
      this._toolbar.classList.add('hidden');
    }
  }

  _truncate(str, max) {
    return str.length > max ? str.substring(0, max) + '…' : str;
  }
}
