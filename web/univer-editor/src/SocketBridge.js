// ══════════════════════════════════════════════════════════════
// SocketBridge.js — 模块 C：实时通信网关
//
// 维护客户端与 Flask 后端之间的 WebSocket 全双工长连接。
// 将 AIPanel 产生的动作封装为 JSON 发送给后端，
// 接收后端推送的指令并派发给 DocController 执行物理修改。
// ══════════════════════════════════════════════════════════════

// socket.io 客户端：使用 CDN 全局变量 window.io
const _io = typeof window !== 'undefined' && window.io ? window.io : null;

export class SocketBridge {
  /**
   * @param {string} serverUrl         后端地址 (e.g. "http://127.0.0.1:5000")
   * @param {import('./DocController').DocController} docController
   */
  constructor(serverUrl, docController) {
    this._url = serverUrl;
    this._doc = docController;
    this._socket = null;
    /** @type {import('./AIPanel').AIPanel | null} */
    this._panel = null;
    /** 当前待处理的 AI 请求上下文 */
    this._pendingAction = null;
    /** 最后一条 AI 结果文本（用于 task_complete 时提供"应用到文档"按钮） */
    this._lastAiResult = null;
  }

  setAIPanel(panel) {
    this._panel = panel;
  }

  // ══════════════════ 初始化连接 ══════════════════

  init() {
    if (!_io) {
      console.error('[SocketBridge] socket.io 客户端不可用');
      if (this._panel) this._panel.updateStatus('无 socket.io', 'disconnected');
      return;
    }

    if (this._panel) this._panel.updateStatus('连接中…', 'connecting');

    this._socket = _io(this._url + '/doc', {
      path: '/socket.io',
      transports: ['websocket', 'polling'],
      reconnection: true,
      reconnectionAttempts: 10,
      reconnectionDelay: 2000,
    });

    // ── 连接生命周期 ──
    this._socket.on('connect', () => {
      console.log('[SocketBridge] 已连接:', this._url);
      if (this._panel) this._panel.updateStatus('已连接', 'connected');
    });

    this._socket.on('disconnect', (reason) => {
      console.warn('[SocketBridge] 断开:', reason);
      if (this._panel) this._panel.updateStatus('已断开', 'disconnected');
    });

    this._socket.on('connect_error', (err) => {
      console.error('[SocketBridge] 连接失败:', err.message);
      if (this._panel) this._panel.updateStatus('连接失败', 'disconnected');
    });

    // ── 监听后端指令 ──
    this._socket.on('agent_execute_command', (payload) => {
      this._handleCommand(payload);
    });

    // ── 监听流式输出 ──
    this._socket.on('agent_stream_chunk', (payload) => {
      this._handleStreamChunk(payload);
    });

    // ── 监听处理完成 ──
    this._socket.on('agent_task_complete', (payload) => {
      this._handleTaskComplete(payload);
    });
  }

  // ══════════════════ 发送动作到后端 ══════════════════

  sendAction(actionType, data) {
    if (!this._socket || !this._socket.connected) {
      console.warn('[SocketBridge] 未连接，无法发送');
      if (this._panel) this._panel.addMessage('未连接到服务器，请稍后重试', 'error');
      return;
    }

    // 记录当前请求上下文，用于任务完成时添加"应用"按钮
    this._pendingAction = { type: actionType, data };
    this._lastAiResult = null;

    if (this._panel) this._panel.showTyping();

    this._socket.emit('client_request', {
      type: actionType,
      payload: data,
      timestamp: Date.now(),
    });
  }

  // ══════════════════ 后端指令处理 ══════════════════

  _handleCommand(payload) {
    console.log('[SocketBridge] 收到指令:', payload?.action);

    switch (payload.action) {
      case 'replace': {
        const ok = this._doc.replaceRange(payload.range, payload.text);
        this._lastAiResult = payload.text;
        if (this._panel) {
          this._panel.removeTyping();
          // 显示截断预览
          const preview = payload.text.length > 120
            ? payload.text.substring(0, 120) + '…'
            : payload.text;
          this._panel.addMessage(preview, 'ai');
          this._panel.addMessage(
            ok ? '✅ 已更新到文档' : '❌ 文档更新失败',
            ok ? 'system' : 'error'
          );
        }
        break;
      }

      case 'insert': {
        const ok = this._doc.insertTextAtCursor(payload.text);
        this._lastAiResult = payload.text;
        if (this._panel) {
          this._panel.removeTyping();
          const preview = payload.text.length > 120
            ? payload.text.substring(0, 120) + '…'
            : payload.text;
          this._panel.addMessage(preview, 'ai');
          this._panel.addMessage(
            ok ? '✅ 已插入到文档' : '❌ 插入失败',
            ok ? 'system' : 'error'
          );
        }
        break;
      }

      case 'show_message': {
        this._lastAiResult = payload.text;
        if (this._panel) {
          this._panel.removeTyping();
          this._panel.addMessage(payload.text, 'ai');
        }
        break;
      }

      default:
        console.warn('[SocketBridge] 未知指令:', payload.action);
    }
  }

  _handleStreamChunk(payload) {
    this._lastAiResult = (this._lastAiResult || '') + (payload.chunk || '');
    if (this._panel) {
      this._panel.removeTyping();
      this._panel.addMessage(payload.chunk, 'ai');
    }
  }

  _handleTaskComplete(payload) {
    const ctx = this._pendingAction;
    this._pendingAction = null;

    if (!this._panel) return;

    this._panel.removeTyping();
    if (payload?.message) {
      this._panel.addMessage(payload.message, 'system');
    }

    // 对于"仅展示"型结果（摘要/自定义/翻译），提供手动应用按钮
    if (this._lastAiResult && ctx) {
      const result = this._lastAiResult;
      const type = ctx.type;

      if (type === 'summarize' || type === 'custom_instruction') {
        this._panel.addMessageWithAction('', 'system', [
          { label: '📝 插入到文档末尾', callback: () => this._doc.insertTextAtCursor('\n' + result) },
          { label: '📋 替换全文', callback: () => this._doc.loadContent(result) },
        ]);
      }
    }
    this._lastAiResult = null;
  }

  // ══════════════════ 工具方法 ══════════════════

  get connected() {
    return this._socket?.connected ?? false;
  }

  disconnect() {
    if (this._socket) {
      this._socket.disconnect();
      this._socket = null;
    }
  }
}
