// ══════════════════════════════════════════════════════════════
// SocketBridge.js — v2: Streaming-aware + Preview-First
//
// KEY CHANGES from v1:
// - agent_stream_chunk  → appends to a single growing bubble (typewriter)
// - agent_task_complete → calls panel.finalizeStreamMessage() attaching
//     apply buttons instead of auto-writing to the document
// - code_result         → renders stdout + images via panel.showCodeResult()
// ══════════════════════════════════════════════════════════════

const _io = typeof window !== 'undefined' && window.io ? window.io : null;

export class SocketBridge {
  constructor(serverUrl, docController) {
    this._url = serverUrl;
    this._doc = docController;
    this._socket = null;
    /** @type {import('./AIPanel').AIPanel|null} */
    this._panel = null;
    /** Track current request context for task_complete finalisation */
    this._pendingAction = null;
  }

  setAIPanel(panel) { this._panel = panel; }

  // ══════════════════ Init ══════════════════

  init() {
    if (!_io) {
      console.error('[SocketBridge] socket.io CDN global not available');
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

    this._socket.on('connect', () => {
      if (this._panel) this._panel.updateStatus('已连接', 'connected');
    });
    this._socket.on('disconnect', () => {
      if (this._panel) this._panel.updateStatus('已断开', 'disconnected');
    });
    this._socket.on('connect_error', () => {
      if (this._panel) this._panel.updateStatus('连接失败', 'disconnected');
    });

    // ── Backend event handlers ──
    this._socket.on('agent_execute_command', (p) => this._handleCommand(p));
    this._socket.on('agent_stream_chunk',    (p) => this._handleStreamChunk(p));
    this._socket.on('agent_task_complete',   (p) => this._handleTaskComplete(p));
    this._socket.on('code_result',           (p) => this._handleCodeResult(p));
  }

  // ══════════════════ Send ══════════════════

  sendAction(actionType, data) {
    if (!this._socket?.connected) {
      if (this._panel) this._panel.addMessage('未连接到服务器，请稍后重试。', 'error');
      return;
    }
    this._pendingAction = { type: actionType, data };
    if (this._panel) this._panel.showTyping();
    this._socket.emit('client_request', { type: actionType, payload: data, timestamp: Date.now() });
  }

  // ══════════════════ Handlers ══════════════════

  _handleCommand(payload) {
    if (!this._panel) return;
    this._panel.removeTyping();

    switch (payload.action) {
      case 'show_message':
        // Status / error messages only — shown in panel, never touch the doc
        this._panel.addMessage(payload.text, payload.is_error ? 'error' : 'system');
        break;

      default:
        console.warn('[SocketBridge] Unexpected command action:', payload.action);
    }
  }

  /**
   * Streaming chunk: append to the current bubble (typewriter effect).
   * The first chunk auto-creates the bubble.
   */
  _handleStreamChunk(payload) {
    if (!this._panel) return;
    this._panel.removeTyping();
    this._panel.appendStreamChunk(payload.chunk || '');
  }

  /**
   * Task complete: seal the streaming bubble and attach action buttons.
   * Crucially stores the FULL text so user can choose what to do with it.
   */
  _handleTaskComplete(payload) {
    const ctx = this._pendingAction;
    this._pendingAction = null;
    if (!this._panel) return;

    this._panel.removeTyping();

    const fullText = payload.full_text || '';
    const actionType = ctx?.type || 'custom_instruction';
    const selectionContext = ctx?.data || null;

    if (payload.error) {
      this._panel.addMessage('❌ ' + payload.error, 'error');
      return;
    }

    // Finalise (attach apply buttons) only if there's text to show
    if (fullText) {
      this._panel.finalizeStreamMessage(fullText, actionType, selectionContext);
    } else if (payload.message) {
      this._panel.addMessage(payload.message, 'system');
    }
  }

  _handleCodeResult(payload) {
    if (this._panel) this._panel.showCodeResult(payload);
  }

  // ══════════════════ Utils ══════════════════

  get connected() { return this._socket?.connected ?? false; }

  disconnect() {
    this._socket?.disconnect();
    this._socket = null;
  }
}
