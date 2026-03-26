// ══════════════════════════════════════════════════════════════
// AIPanel.js — 模块 B：AI 交互面板层
//
// 渲染右侧控制台 UI，绑定按钮点击事件，渲染 AI 返回的对话气泡。
// 约束：不得直接调用 Univer 底层方法，只能调用 DocController 的接口。
// ══════════════════════════════════════════════════════════════

export class AIPanel {
  /**
   * @param {string}          containerId    右侧面板挂载 DOM id
   * @param {import('./DocController').DocController} docController
   * @param {import('./SocketBridge').SocketBridge}   socketBridge
   */
  constructor(containerId, docController, socketBridge) {
    this._container = document.getElementById(containerId);
    this._doc = docController;
    this._bridge = socketBridge;
    this._chatFlow = null;

    this._render();
    this._bind();
    this._bridge.setAIPanel(this);
  }

  // ══════════════════ UI 渲染 ══════════════════

  _render() {
    // 默认折叠右侧面板，给编辑区更多空间
    this._container.classList.add('collapsed');

    this._container.innerHTML = `
      <div class="ai-panel-header">
        <button id="ai-panel-toggle" class="ai-panel-toggle-btn" title="展开/折叠 AI 面板">◀</button>
        <span class="ai-panel-title">AI 文件助手</span>
        <span id="conn-status" class="conn-status disconnected">离线</span>
      </div>

      <div class="ai-actions">
        <button id="btn-polish"    class="action-btn" title="将选中文本发送给 AI 进行润色">✨ AI 润色</button>
        <button id="btn-summarize" class="action-btn" title="让 AI 总结全文要点">📝 全文摘要</button>
        <button id="btn-continue"  class="action-btn" title="AI 根据上下文继续写作">🖊️ 续写</button>
        <button id="btn-translate" class="action-btn" title="翻译选中文本">🌐 翻译</button>
      </div>

      <div id="ai-chat-flow" class="ai-chat-flow">
        <div class="chat-msg system">欢迎使用 Koto 文件助手！选中文本后可使用浮动工具栏快速调用 AI。</div>
      </div>

      <div class="ai-input-bar">
        <input id="ai-input" type="text" placeholder="输入自定义指令…" autocomplete="off" />
        <button id="btn-send">发送</button>
      </div>
    `;
    this._chatFlow = document.getElementById('ai-chat-flow');
  }

  // ══════════════════ 事件绑定 ══════════════════

  _bind() {
    // 折叠/展开切换
    const toggleBtn = document.getElementById('ai-panel-toggle');
    toggleBtn.addEventListener('click', () => {
      const collapsed = this._container.classList.toggle('collapsed');
      toggleBtn.textContent = collapsed ? '◀' : '▶';
    });

    // 快捷操作按钮
    document.getElementById('btn-polish').addEventListener('click', () => this._onAction('polish'));
    document.getElementById('btn-summarize').addEventListener('click', () => this._onAction('summarize'));
    document.getElementById('btn-continue').addEventListener('click', () => this._onAction('continue_writing'));
    document.getElementById('btn-translate').addEventListener('click', () => this._onAction('translate'));

    // 自定义指令输入
    const input = document.getElementById('ai-input');
    const sendBtn = document.getElementById('btn-send');
    sendBtn.addEventListener('click', () => this._onCustomInput(input));
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        this._onCustomInput(input);
      }
    });
  }

  // ══════════════════ 操作处理 ══════════════════

  _onAction(actionType) {
    const selection = this._doc.getSelection();

    if (actionType === 'summarize' || actionType === 'continue_writing') {
      // 摘要和续写使用全文
      const fullText = this._doc.getFullText();
      if (!fullText) {
        this.addMessage('文档为空，请先输入内容', 'error');
        return;
      }
      this.addMessage(actionType === 'summarize' ? '请求全文摘要…' : '请求 AI 续写…', 'user');
      this._bridge.sendAction(actionType, { text: fullText, range: null });
      return;
    }

    // 润色和翻译需要选区
    if (!selection || !selection.text || selection.text.length === 0) {
      this.addMessage('请先在编辑器中选中文本', 'error');
      return;
    }
    const label = actionType === 'polish' ? 'AI 润色' : '翻译';
    this.addMessage(`${label}: "${this._truncate(selection.text, 60)}"`, 'user');
    this._bridge.sendAction(actionType, selection);
  }

  _onCustomInput(input) {
    const text = input.value.trim();
    if (!text) return;
    input.value = '';

    const selection = this._doc.getSelection();
    this.addMessage(text, 'user');
    this._bridge.sendAction('custom_instruction', {
      instruction: text,
      context: selection,
    });
  }

  // ══════════════════ 公开方法（供 SocketBridge 调用） ══════════════════

  updateStatus(text, type) {
    const el = document.getElementById('conn-status');
    if (!el) return;
    el.textContent = text;
    el.className = 'conn-status ' + type;
  }

  addMessage(text, role = 'system') {
    if (!this._chatFlow) return;
    const div = document.createElement('div');
    div.className = 'chat-msg ' + role;
    div.textContent = text;
    this._chatFlow.appendChild(div);
    this._chatFlow.scrollTop = this._chatFlow.scrollHeight;
  }

  /** 带操作按钮的消息（用于"应用到文档"等场景） */
  addMessageWithAction(text, role, actions) {
    if (!this._chatFlow) return;
    const div = document.createElement('div');
    div.className = 'chat-msg ' + role;

    if (text) {
      const span = document.createElement('span');
      span.textContent = text;
      div.appendChild(span);
    }

    if (actions && actions.length) {
      const bar = document.createElement('div');
      bar.className = 'msg-action-bar';
      actions.forEach(a => {
        const btn = document.createElement('button');
        btn.className = 'msg-action-btn';
        btn.textContent = a.label;
        btn.addEventListener('click', () => {
          a.callback();
          btn.disabled = true;
          btn.textContent = '✅ 已应用';
        });
        bar.appendChild(btn);
      });
      div.appendChild(bar);
    }

    this._chatFlow.appendChild(div);
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
    const existing = document.getElementById('typing-indicator');
    if (existing) existing.remove();
  }

  // ══════════════════ 工具方法 ══════════════════

  _truncate(str, max) {
    return str.length > max ? str.substring(0, max) + '…' : str;
  }
}
