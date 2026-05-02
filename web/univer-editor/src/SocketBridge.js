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
    /** @type {import('./DocLiveRenderer').DocLiveRenderer|null} */
    this._liveRenderer = null;
  }

  setAIPanel(panel) { this._panel = panel; }

  /** Wire up the DocLiveRenderer for live document streaming. */
  setLiveRenderer(renderer) { this._liveRenderer = renderer; }

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
    this._socket.on('agent_event',           (p) => this._handleAgentEvent(p));
    this._socket.on('agent_progress',        (p) => this._handleProgress(p));
    this._socket.on('agent_phase',           (p) => this._handlePhase(p));
    this._socket.on('agent_proposals',       (p) => this._handleProposals(p));
    this._socket.on('doc_tool_call',         (p) => this._handleDocToolCall(p));
    this._socket.on('skill_suggestions',      (p) => this._handleSkillSuggestions(p));
    // Live document streaming events
    this._socket.on('doc_live_chunk',        (p) => this._handleLiveChunk(p));
    this._socket.on('doc_live_commit',       (p) => this._handleLiveCommit(p));
  }

  // ══════════════════ Send ══════════════════

  sendAction(actionType, data) {
    if (!this._socket?.connected) {
      if (this._panel) this._panel.addMessage('未连接到服务器，请稍后重试。', 'error');
      return;
    }
    this._pendingAction = { type: actionType, data };
    if (this._panel) this._panel.showTyping();

    // Map simple FloatingToolbar actions to the full doc_ai_request format so
    // they go through the modern handler (streaming history, proposals, model
    // fallback) instead of the legacy on_client_request handler.
    const ACTION_PROMPT_MAP = {
      polish:           '你是一名专业编辑。请对以下文本进行润色，使其更加流畅、优雅，保持原意不变。只输出润色后的文本，不要添加任何解释：',
      translate:        '请将以下文本翻译（中文→英文，英文→中文）。只输出翻译结果，不要添加原文或任何解释：',
      summarize:        '请对以下内容生成一份简洁的中文摘要，包含关键论点和要点，摘要控制在200字以内：',
      continue_writing: '你是一名优秀的写作助手。请根据以下已有文本，自然地继续写下去（100-200字），保持语气和风格一致，衔接流畅。直接输出续写内容，不要重复原文：',
      rewrite:          '请对以下文本进行改写，保留核心意思，但用不同的措辞和句式重新表达，使语言更加多样化。只输出改写后的文本，不要添加任何说明：',
      annotate:         '请为以下文本添加简洁的注释，解释关键概念、术语或难点，注释用【】标注，插入相应位置。只输出带注释的文本：',
    };

    const promptPrefix = ACTION_PROMPT_MAP[actionType];
    if (promptPrefix) {
      // Known text-transform action: use doc_ai_request for full streaming pipeline
      const selText = (data && data.text) || '';
      const fullText = (data && data.fullText) || '';
      const docFileType = this._doc?.getFileType?.() || 'unknown';
      const docFileName = this._doc?.getFileName?.() || '';
      // 传递选区起始偏移量（让后端 _build_editor_prompt 能精确手和 周围文本）
      const selectionOffset = (data && data.range && typeof data.range.startOffset === 'number')
        ? data.range.startOffset : -1;
      this._socket.emit('doc_ai_request', {
        prompt: selText,
        context: fullText ? `[文档上下文（仅供参考，不要重复输出）]\n${fullText.slice(0, 4000)}` : '',
        selection: selText,
        selection_offset: selectionOffset,
        file_type: docFileType,
        file_name: docFileName,
        has_selection: !!selText,
        history: (this._panel?._history || []).slice(-10),
        language: '',
        csv_data: '',
        output_mode: 'inline',
        model_mode: localStorage.getItem('wa_locked_model') === 'local' ? 'local' : 'cloud',
        _action_system_prompt: promptPrefix,
        _action_type: actionType,
        live_doc: !!(window.__koto?.docxViewer?.isActive()),
        live_mode: selText ? 'replace' : 'append',
      });
    } else {
      // Fallback: legacy path for custom_instruction / code_exec
      this._socket.emit('client_request', { type: actionType, payload: data, timestamp: Date.now() });
    }
  }

  // ══════════════════ Handlers ══════════════════

  _handleCommand(payload) {
    if (!this._panel) return;
    this._panel.removeTyping();

    switch (payload.action) {
      case 'editor_apply':
        this._applyEditorPayload(payload.payload || {});
        break;

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
   * Falls back to text already rendered in the streaming bubble if the
   * backend event omits full_text (P5 fix).
   */
  _handleTaskComplete(payload) {
    const ctx = this._pendingAction;
    this._pendingAction = null;
    if (!this._panel) return;

    this._panel.removeTyping();
    this._panel.finishAgentEventLog?.();

    // Prefer payload.full_text; fall back to streamed text or payload.result
    const fullText = payload.full_text
      || this._panel.getStreamingText?.()
      || (typeof payload.result === 'string' && !payload.result.startsWith('❌') ? payload.result : '')
      || '';
    const actionType = ctx?.type || 'custom_instruction';
    const selectionContext = ctx?.data || null;

    if (payload.error) {
      this._panel.addMessage('❌ ' + payload.error, 'error');
      return;
    }

    // payload.result starts with ❌ → treat as error (legacy on_doc_ai_request error path)
    if (typeof payload.result === 'string' && payload.result.startsWith('❌')) {
      this._panel.addMessage(payload.result, 'error');
      return;
    }

    // Always finalise so apply buttons appear (even if fullText is empty)
    this._panel.finalizeStreamMessage(fullText, actionType, selectionContext);
    if (!fullText && payload.message) {
      this._panel.addMessage(payload.message, 'system');
    }
  }

  _handleCodeResult(payload) {
    if (this._panel) this._panel.finishAgentEventLog?.();
    if (this._panel) this._panel.showCodeResult(payload);
  }

  _handleAgentEvent(payload) {
    if (!this._panel || !payload) return;
    this._panel.removeTyping?.();
    this._panel.handleAgentEvent?.(payload);
  }

  _handleSkillSuggestions(payload) {
    const suggestions = payload.suggestions || [];
    if (suggestions.length && this._panel) {
      this._panel.showSkillSuggestions(suggestions);
    }
  }

  // ── Live document streaming handlers ──────────────────────────

  _handleLiveChunk(payload) {
    const dv = window.__koto?.docxViewer;
    if (!dv?.isActive() || !this._liveRenderer) return;
    // Start a new live session when the request_id changes
    if (payload.request_id && payload.request_id !== this._liveRenderer._requestId) {
      this._liveRenderer.start(payload.mode || 'replace', null, payload.request_id);
    }
    this._liveRenderer.push(payload.chunk || '');
  }

  _handleLiveCommit(payload) {
    const dv = window.__koto?.docxViewer;
    if (!dv?.isActive() || !this._liveRenderer) return;
    this._liveRenderer.showCommitBar(
      payload.full_text || '',
      payload.mode || 'replace',
      payload.original_selection || '',
    );
  }

  /**
   * Progress step from server during long-running tasks.
   * Shown as a transient system message (auto-dismissed on task_complete).
   */
  _handleProgress(payload) {
    if (!this._panel) return;
    const step = payload.step || '';
    const detail = payload.detail || '';
    if (step === 'complete') {
      // Remove all pending progress indicators + phase tracker
      this._panel.removeProgressMessages?.();
      this._panel.removePhaseTracker?.();
      return;
    }
    if (detail) this._panel.showProgressMessage?.(detail);
  }

  /**
   * Phase update from server — drives the PhaseTracker stepper UI.
   * payload: { phases: [{id,label}], current: string, status: 'running'|'done' }
   */
  _handlePhase(payload) {
    if (!this._panel) return;
    if (this._panel.updatePhase) {
      this._panel.updatePhase(payload);
    }
  }

  /**
   * Structured proposals emitted when user had a pinned selection.
   * Each proposal has: id, original_text, proposed_text, rationale, tool_call.
   */
  _handleProposals(payload) {
    if (!this._panel) return;
    const proposals = payload.proposals || [];
    const summary = payload.summary || '';
    if (proposals.length > 0 && this._panel.showProposals) {
      this._panel.showProposals(proposals, summary, this._pendingAction?.data || null);
    }
  }

  /**
   * Direct tool call emitted (non-proposal mode: no pinned selection).
   * Passes tool call to the panel which shows apply buttons.
   */
  _handleDocToolCall(payload) {
    if (!this._panel) return;
    if (this._panel.handleDocToolCall) {
      this._panel.handleDocToolCall(payload);
    }
  }

  _applyEditorPayload(payload) {
    const kind = payload?.type;
    if (!kind) return;

    switch (kind) {
      case 'set_html':
        this._applyHtmlUpdate(payload);
        return;

      case 'insert_text':
        this._applyInsertText(payload);
        return;

      case 'set_cell':
        this._applySheetCell(payload);
        return;

      case 'set_cells':
        this._applySheetCells(payload.cells || []);
        return;

      case 'set_pptx_text':
        this._applyPptxText(payload);
        return;

      default:
        console.warn('[SocketBridge] Unsupported editor_apply payload:', payload);
    }
  }

  _applyHtmlUpdate(payload) {
    const content = payload.content ?? payload.value ?? payload.html ?? payload.text ?? '';
    const plainText = this._htmlToText(content);
    const docxViewer = window.__koto?.docxViewer;

    if (docxViewer?.isActive?.()) {
      docxViewer.setLiveText(plainText, { append: false });
      return;
    }

    this._doc?.loadContent?.(plainText);
  }

  _applyInsertText(payload) {
    const content = payload.content ?? payload.value ?? payload.text ?? '';
    const plainText = this._htmlToText(content);
    const docxViewer = window.__koto?.docxViewer;

    if (docxViewer?.isActive?.()) {
      docxViewer.setLiveText(plainText, { append: true });
      return;
    }

    if ((payload.position || 'end') === 'start') {
      const current = this._doc?.getFullText?.() || '';
      this._doc?.loadContent?.(plainText + current);
      return;
    }

    this._doc?.insertTextAtCursor?.(plainText);
  }

  _applySheetCell(payload) {
    const excelViewer = window.__koto?.excelViewer;
    const coords = this._resolveCellCoords(payload);
    if (!excelViewer?.isActive?.() || !coords) return;
    excelViewer.setCellValue(coords.r, coords.c, payload.value ?? payload.content ?? '');
  }

  _applySheetCells(cells) {
    const excelViewer = window.__koto?.excelViewer;
    if (!excelViewer?.isActive?.()) return;

    const normalized = cells
      .map((cell) => {
        const coords = this._resolveCellCoords(cell || {});
        if (!coords) return null;
        return { ...coords, value: cell.value ?? cell.content ?? '' };
      })
      .filter(Boolean);

    if (!normalized.length) return;
    excelViewer.setCells(normalized);
  }

  _applyPptxText(payload) {
    const pptxViewer = window.__koto?.pptxViewer;
    if (!pptxViewer?.isActive?.()) return;

    const slideIndex = Number(payload.slide_index ?? payload.slideIndex ?? -1);
    const shapeId = Number(payload.shape_id ?? payload.shapeId ?? -1);
    const text = payload.text ?? payload.value ?? payload.content ?? '';

    if (slideIndex < 0 || shapeId < 0) return;
    pptxViewer.setShapeText(slideIndex, shapeId, text);
  }

  _resolveCellCoords(payload) {
    if (!payload || typeof payload !== 'object') return null;

    if (typeof payload.r === 'number' || typeof payload.c === 'number') {
      return {
        r: Number(payload.r) || 0,
        c: Number(payload.c) || 0,
      };
    }

    if (typeof payload.row === 'number' || typeof payload.col === 'number') {
      return {
        r: Math.max((Number(payload.row) || 1) - 1, 0),
        c: Math.max((Number(payload.col) || 1) - 1, 0),
      };
    }

    const cellRef = String(payload.cell || '').trim();
    if (!cellRef) return null;

    const match = /^([A-Za-z]+)(\d+)$/.exec(cellRef);
    if (!match) return null;

    const [, letters, rowText] = match;
    let col = 0;
    for (const ch of letters.toUpperCase()) {
      col = col * 26 + (ch.charCodeAt(0) - 64);
    }

    return {
      r: Math.max(Number(rowText) - 1, 0),
      c: Math.max(col - 1, 0),
    };
  }

  _htmlToText(html) {
    if (typeof html !== 'string') return String(html || '');
    if (!/[<>]/.test(html)) return html;

    const doc = new DOMParser().parseFromString(html, 'text/html');
    doc.querySelectorAll('script,style').forEach((el) => el.remove());
    doc.querySelectorAll('br').forEach((el) => el.replaceWith(doc.createTextNode('\n')));
    doc.querySelectorAll('p,div,li,tr,h1,h2,h3,h4,h5,h6').forEach((el) => {
      if (!el.textContent?.endsWith('\n')) {
        el.appendChild(doc.createTextNode('\n'));
      }
    });

    return (doc.body.textContent || '')
      .replace(/\u00a0/g, ' ')
      .replace(/\n{3,}/g, '\n\n')
      .trim();
  }

  // ══════════════════ Utils ══════════════════

  get connected() { return this._socket?.connected ?? false; }

  disconnect() {
    this._socket?.disconnect();
    this._socket = null;
  }

  /**
   * 通过 WebSocket 向特定 PPTX 形状发送 AI 编辑指令。
   * 不使用 _action_system_prompt 覆盖，确保后端使用 pptx 工具调用系统指令。
   * @param {string} actionType - 'polish' | 'translate' | 'rewrite' | 'check' | 'annotate'
   * @param {{ slideIndex:number, shapeId:number, shapeName:string, text:string }} shapeInfo
   * @param {string} fullText - 全局 PPT 文本（供后端分析上下文）
   */
  sendPptxShapeAction(actionType, shapeInfo, fullText) {
    if (!this._socket?.connected) {
      if (this._panel) this._panel.addMessage('未连接到服务器，请稍后重试。', 'error');
      return;
    }
    const ACTION_VERBS = {
      polish:    '对以下文字进行润色，使其更加流畅优雅，保持原意：',
      translate: '将以下文字翻译（中文→英文，英文→中文）：',
      rewrite:   '将以下文字用不同错误词改写，保留核心意思：',
      annotate:  '为以下文字添加简洁注释：',
      check:     '检查以下文字的语法和表达，直接输出修改后的版本：',
    };
    const verb = ACTION_VERBS[actionType] || '处理以下文字：';
    const shapeCtxBlock =
      `[幻灯片 ${shapeInfo.slideIndex + 1}，shape_id=${shapeInfo.shapeId}，名称="${shapeInfo.shapeName}"]
原文：${shapeInfo.text}`;

    this._pendingAction = { type: actionType, data: { text: shapeInfo.text } };
    if (this._panel) this._panel.showTyping();

    this._socket.emit('doc_ai_request', {
      prompt: `${verb}\n"${shapeInfo.text}"`,
      context: `[PPT幻灯片内容]\n${shapeCtxBlock}${fullText ? `\n\n[全文]\n${fullText.slice(0, 3000)}` : ''}`,
      selection: shapeInfo.text,
      file_type: 'pptx',
      file_name: this._doc?.getFileName?.() || '',
      has_selection: true,
      history: (this._panel?._history || []).slice(-10),
      language: '',
      csv_data: '',
      output_mode: 'inline',
      model_mode: localStorage.getItem('wa_locked_model') === 'local' ? 'local' : 'cloud',
    });
  }
}
