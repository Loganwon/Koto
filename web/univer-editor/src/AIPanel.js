// ══════════════════════════════════════════════════════════════
// AIPanel.js — v2: Preview-First + Streaming Typewriter Output
//
// RULE: AI output is NEVER applied to the document automatically.
// All results stream into the right panel first. Only after the
// user clicks a confirm button does the text enter the document.
// ══════════════════════════════════════════════════════════════

export class AIPanel {
  constructor(containerId, docController, socketBridge) {
    this._container = document.getElementById(containerId);
    this._doc = docController;
    this._bridge = socketBridge;
    this._chatFlow = null;
    /** Current streaming message <div> element */
    this._streamingEl = null;

    this._render();
    this._bind();
    this._bridge.setAIPanel(this);
  }

  // ══════════════════ Render ══════════════════

  _render() {
    this._container.classList.add('collapsed');
    this._container.innerHTML = `
      <div class="ai-panel-header">
        <button id="ai-panel-toggle" class="ai-panel-toggle-btn" title="展开/折叠">◀</button>
        <span class="ai-panel-title">AI 文件助手</span>
        <span id="conn-status" class="conn-status disconnected">离线</span>
      </div>
      <div class="ai-actions">
        <button class="action-btn" data-action="polish"          title="润色选中文本">✨ 润色</button>
        <button class="action-btn" data-action="translate"       title="翻译选中文本">🌐 翻译</button>
        <button class="action-btn" data-action="summarize"       title="生成全文摘要">📝 摘要</button>
        <button class="action-btn" data-action="continue_writing" title="AI 续写">🖊️ 续写</button>
      </div>
      <div id="ai-chat-flow" class="ai-chat-flow">
        <div class="chat-msg system">AI 结果会在此预览，确认后再应用到文档。选中文本后点击按钮或使用浮动工具栏。</div>
      </div>
      <div class="ai-input-bar">
        <textarea id="ai-input" rows="1" placeholder="输入指令…（Enter 发送，Shift+Enter 换行）" autocomplete="off"></textarea>
        <button id="btn-send" title="发送">▶</button>
      </div>
    `;
    this._chatFlow = document.getElementById('ai-chat-flow');
  }

  // ══════════════════ Bind ══════════════════

  _bind() {
    // Collapse toggle
    const toggleBtn = document.getElementById('ai-panel-toggle');
    toggleBtn.addEventListener('click', () => {
      const collapsed = this._container.classList.toggle('collapsed');
      toggleBtn.textContent = collapsed ? '◀' : '▶';
    });

    // Action buttons
    this._container.querySelectorAll('.action-btn[data-action]').forEach(btn => {
      btn.addEventListener('click', () => this._onAction(btn.dataset.action));
    });

    // Custom input textarea - auto-resize
    const input = document.getElementById('ai-input');
    input.addEventListener('input', () => {
      input.style.height = 'auto';
      input.style.height = Math.min(input.scrollHeight, 120) + 'px';
    });

    document.getElementById('btn-send').addEventListener('click', () => this._onCustomInput(input));
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        this._onCustomInput(input);
      }
    });
  }

  // ══════════════════ Action Dispatch ══════════════════

  _onAction(actionType) {
    if (actionType === 'summarize' || actionType === 'continue_writing') {
      const fullText = this._doc.getFullText();
      if (!fullText.trim()) {
        this.addMessage('文档为空，请先输入内容。', 'error');
        return;
      }
      const label = actionType === 'summarize' ? '📝 全文摘要' : '🖊️ AI 续写';
      this.addMessage(label, 'user');
      this._bridge.sendAction(actionType, { text: fullText, range: null });
      this.expand();
      return;
    }

    // polish / translate require a selection
    const selection = this._doc.getSelection();
    if (!selection || !selection.text || !selection.text.trim()) {
      this.addMessage('请先在编辑器中选中要处理的文本。', 'error');
      return;
    }

    const labels = { polish: '✨ 润色', translate: '🌐 翻译' };
    this.addMessage(`${labels[actionType]}：「${this._truncate(selection.text, 80)}」`, 'user');
    this._bridge.sendAction(actionType, selection);
    this.expand();
  }

  _onCustomInput(input) {
    const text = input.value.trim();
    if (!text) return;
    input.value = '';
    input.style.height = 'auto';
    const selection = this._doc.getSelection();
    this.addMessage(text, 'user');
    this._bridge.sendAction('custom_instruction', { instruction: text, context: selection });
    this.expand();
  }

  // ══════════════════ Public API (used by SocketBridge) ══════════════════

  updateStatus(text, type) {
    const el = document.getElementById('conn-status');
    if (el) { el.textContent = text; el.className = 'conn-status ' + type; }
  }

  addMessage(text, role = 'system') {
    if (!this._chatFlow) return;
    const div = document.createElement('div');
    div.className = 'chat-msg ' + role;
    div.textContent = text;
    this._chatFlow.appendChild(div);
    this._chatFlow.scrollTop = this._chatFlow.scrollHeight;
    return div;
  }

  /** Begin a new streaming AI bubble. Returns the element. */
  startStreamMessage() {
    this.removeTyping();
    if (this._streamingEl) return this._streamingEl; // already open
    const div = document.createElement('div');
    div.className = 'chat-msg ai streaming';
    this._chatFlow.appendChild(div);
    this._streamingEl = div;
    this._chatFlow.scrollTop = this._chatFlow.scrollHeight;
    return div;
  }

  /** Append a text chunk to the current streaming bubble (typewriter). */
  appendStreamChunk(chunk) {
    if (!this._streamingEl) this.startStreamMessage();
    this._streamingEl.textContent += chunk;
    this._chatFlow.scrollTop = this._chatFlow.scrollHeight;
  }

  /**
   * Stream complete: lock the bubble and attach Preview action buttons.
   * NOTHING is written to the document until the user clicks a button.
   */
  finalizeStreamMessage(fullText, actionType, selectionContext) {
    const el = this._streamingEl;
    this._streamingEl = null;
    if (!el) return;
    el.classList.remove('streaming');

    const bar = document.createElement('div');
    bar.className = 'msg-action-bar';

    // Domain-specific apply buttons
    this._buildApplyButtons(fullText, actionType, selectionContext)
        .forEach(b => bar.appendChild(b));

    // Copy button — always present
    const copyBtn = document.createElement('button');
    copyBtn.className = 'msg-action-btn secondary';
    copyBtn.textContent = '📋 复制';
    copyBtn.addEventListener('click', () => {
      navigator.clipboard.writeText(fullText).then(() => {
        copyBtn.textContent = '✅ 已复制';
        setTimeout(() => { copyBtn.textContent = '📋 复制'; }, 2000);
      });
    });
    bar.appendChild(copyBtn);

    el.appendChild(bar);
    this._chatFlow.scrollTop = this._chatFlow.scrollHeight;
  }

  _buildApplyButtons(text, actionType, ctx) {
    const btns = [];
    const make = (label, cb) => {
      const btn = document.createElement('button');
      btn.className = 'msg-action-btn';
      btn.textContent = label;
      btn.addEventListener('click', () => { cb(); btn.disabled = true; btn.textContent = '✅ 已应用'; });
      return btn;
    };

    if (actionType === 'polish' || actionType === 'translate') {
      if (ctx?.range) btns.push(make('✏️ 替换选中内容', () => this._doc.replaceRange(ctx.range, text)));
      btns.push(make('📝 插入到末尾', () => this._doc.insertTextAtCursor('\n' + text)));
    } else if (actionType === 'continue_writing') {
      btns.push(make('📝 追加到文档', () => this._doc.insertTextAtCursor('\n' + text)));
    } else if (actionType === 'summarize') {
      btns.push(make('📝 插入摘要', () => this._doc.insertTextAtCursor('\n\n【摘要】\n' + text)));
    } else {
      // custom_instruction
      if (ctx?.range) btns.push(make('✏️ 替换选中内容', () => this._doc.replaceRange(ctx.range, text)));
      btns.push(make('📝 插入到末尾', () => this._doc.insertTextAtCursor('\n' + text)));
    }
    return btns;
  }

  /** Display code execution result (stdout + images) */
  showCodeResult(payload) {
    if (!this._chatFlow) return;
    this.removeTyping();

    if (payload.error) {
      this.addMessage('❌ 执行错误：' + payload.error, 'error');
      return;
    }

    const wrap = document.createElement('div');
    wrap.className = 'chat-msg code-result';

    if (payload.stdout) {
      const pre = document.createElement('pre');
      pre.className = 'code-stdout';
      pre.textContent = payload.stdout.trim();
      wrap.appendChild(pre);
    }
    if (payload.stderr) {
      const pre = document.createElement('pre');
      pre.className = 'code-stderr';
      pre.textContent = payload.stderr.trim();
      wrap.appendChild(pre);
    }
    if (payload.files) {
      Object.entries(payload.files).forEach(([name, b64]) => {
        const ext = name.split('.').pop().toLowerCase();
        if (['png', 'jpg', 'jpeg', 'svg', 'gif'].includes(ext)) {
          const img = document.createElement('img');
          img.className = 'code-result-img';
          img.src = `data:image/${ext === 'svg' ? 'svg+xml' : ext};base64,${b64}`;
          img.alt = name;
          wrap.appendChild(img);

          const bar = document.createElement('div');
          bar.className = 'msg-action-bar';
          const dl = document.createElement('button');
          dl.className = 'msg-action-btn';
          dl.textContent = '💾 下载图片';
          dl.addEventListener('click', () => {
            const a = document.createElement('a');
            a.href = img.src; a.download = name; a.click();
            dl.textContent = '✅ 下载中'; dl.disabled = true;
          });
          bar.appendChild(dl);
          wrap.appendChild(bar);
        }
      });
    }

    this._chatFlow.appendChild(wrap);
    this._chatFlow.scrollTop = this._chatFlow.scrollHeight;
  }

  showTyping() {
    this.removeTyping();
    const div = document.createElement('div');
    div.className = 'chat-msg ai';
    div.id = 'typing-indicator';
    div.innerHTML = '<div class="typing-indicator"><span></span><span></span><span></span></div>';
    this._chatFlow.appendChild(div);
    this._chatFlow.scrollTop = this._chatFlow.scrollHeight;
  }

  removeTyping() {
    const el = document.getElementById('typing-indicator');
    if (el) el.remove();
  }

  expand() {
    if (this._container.classList.contains('collapsed')) {
      this._container.classList.remove('collapsed');
      const btn = document.getElementById('ai-panel-toggle');
      if (btn) btn.textContent = '▶';
    }
  }

  _truncate(str, max) {
    return str.length > max ? str.substring(0, max) + '…' : str;
  }
}
