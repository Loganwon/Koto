// ══════════════════════════════════════════════════════════════
// AIPanel.js — v4: Sandbox Charts + Slash Commands + Diff View
//
// RULE: AI output is NEVER applied to the document automatically.
// All results stream into the right panel first. Only after the
// user clicks a confirm button does the text enter the document.
// ══════════════════════════════════════════════════════════════

const SLASH_COMMANDS = [
  { cmd: '/润色',   action: 'polish',           icon: '✨', hint: '润色选中文本' },
  { cmd: '/翻译',   action: 'translate',         icon: '🌐', hint: '翻译为英文' },
  { cmd: '/总结',   action: 'summarize',         icon: '📋', hint: '总结全文要点' },
  { cmd: '/检查',   action: 'check',             icon: '🔍', hint: '检查语法错别字' },
  { cmd: '/续写',   action: 'continue_writing',  icon: '✍️', hint: '继续写作' },
  { cmd: '/改写',   action: 'rewrite',           icon: '✏️', hint: '改写表达方式' },
  { cmd: '/叙述',   action: 'narrative',         icon: '📝', hint: '数据转文字+图表' },
  { cmd: '/可视化', action: 'chart',             icon: '📊', hint: '用Python画图' },
  { cmd: '/解析',   action: 'analyze_doc',       icon: '🧠', hint: '深度分析文档（AI工具调用）' },
  { cmd: '/替换',   action: 'find_replace',      icon: '🔄', hint: '智能查找替换' },
  { cmd: '/引用',   action: 'find_reference',    icon: '📚', hint: '查找参考引用' },
];

// ── 图表图片全局缓存（避免拖拽时序列化巨大 base64 卡死 UI 线程）
// key: 短 ID  value: { src: dataUrl, name: fileName }
const _CHART_IMG_STORE = new Map();
let _chartImgCounter = 0;

export function getChartImgSrc(id) {
  return _CHART_IMG_STORE.get(id);
}

// ── 下一步建议映射（按动作类型） ──────────────────────────────────
const NEXT_STEPS = {
  polish:           [{ action: 'check',    label: '🔍 检查语法' }, { action: 'translate', label: '🌐 翻译' }, { action: 'rewrite', label: '✏️ 改写风格' }],
  translate:        [{ action: 'polish',   label: '✨ 润色译文' }, { action: 'summarize', label: '📋 总结' }],
  rewrite:          [{ action: 'check',    label: '🔍 检查语法' }, { action: 'translate', label: '🌐 翻译' }],
  check:            [{ action: 'polish',   label: '✨ 润色建议' }, { action: 'rewrite',   label: '✏️ 改写' }],
  summarize:        [{ action: 'polish',   label: '✨ 润色总结' }, { action: 'continue_writing', label: '✍️ 继续扩写' }],
  continue_writing: [{ action: 'check',    label: '🔍 检查全文' }, { action: 'summarize', label: '📋 重新总结' }],
  narrative:        [{ action: 'chart',    label: '📊 同时可视化' }, { action: 'polish',   label: '✨ 润色段落' }],
  analyze_doc:      [{ action: 'chart',    label: '📊 数据可视化' }, { action: 'narrative', label: '📝 叙述分析' }],
  explain:          [{ action: 'find_reference', label: '📚 查找引用' }, { action: 'summarize', label: '📋 全文总结' }],
};

export class AIPanel {
  constructor(containerId, docController, socketBridge) {
    this._container = document.getElementById(containerId);
    this._doc = docController;
    this._bridge = socketBridge;
    this._chatFlow = null;
    this._streamingEl = null;
    this._abortController = null;
    this._slashMenu = null;
    this._slashIdx = 0;
    this._slashFiltered = [];
    this._history = [];   // [{role:'user'|'assistant', content:str}] multi-turn memory
    this._fileId  = null; // current doc ID (for server-side session persistence)
    this._docContext = ''; // brief document summary injected into all AI requests
    this._docMode = 'normal'; // Document mode: normal | formal | casual | academic | concise

    this._render();
    this._bind();
    this._bridge.setAIPanel(this);
    this._restoreCollapseState();
  }

  // ══════════════════ Render ══════════════════

  _render() {
    this._container.innerHTML = `
      <div class="ai-panel-header">
        <button id="ai-panel-toggle" class="ai-panel-toggle-btn" title="展开/折叠 AI 面板">◀</button>
        <span class="ai-panel-title">AI 助手</span>
        <span id="ai-model-badge" class="ai-model-badge"></span>
        <span id="conn-status" class="conn-status connected"><span class="conn-dot"></span>Koto AI</span>
      </div>
      <div id="ai-chat-flow" class="ai-chat-flow">
        <div class="chat-msg system">你好！请从左侧打开一个文件，我可以帮你<strong>分析内容、润色文字、总结要点、翻译段落或可视化数据</strong>。<br><br>选中文档中的文字后，可快速将选区发送给我处理。输入 <code>/</code> 可以快速选择 AI 操作。</div>
      </div>
      <div class="ai-quick-bar">
        <button class="quick-btn" data-action="polish"         title="润色选中文本">✨ 润色</button>
        <button class="quick-btn" data-action="summarize"      title="生成全文摘要">📋 总结</button>
        <button class="quick-btn" data-action="check"          title="检查语法与错别字">🔍 检查</button>
        <button class="quick-btn" data-action="translate"      title="翻译选中文本为英文">🌐 翻译</button>
        <button class="quick-btn" data-action="narrative"      title="将选中数据生成分析段落+图表">📝 叙述</button>
        <button class="quick-btn" data-action="analyze_doc"    title="深度分析文档（AI工具调用）">🧠 分析</button>
        <button class="quick-btn chart-quick-btn" data-action="chart" title="用 Python 将数据可视化为图表">📊 可视化</button>
      </div>
      <div class="ai-mode-bar" title="选择写作基调，影响润色/改写/续写风格">
        <span class="ai-mode-label">基调</span>
        <button class="ai-mode-btn active" data-mode="normal"   title="默认基调">📝 默认</button>
        <button class="ai-mode-btn"        data-mode="formal"   title="正式、专业">🎩 正式</button>
        <button class="ai-mode-btn"        data-mode="casual"   title="轻松、口语化">😊 轻松</button>
        <button class="ai-mode-btn"        data-mode="academic" title="学术严谨">🎓 学术</button>
        <button class="ai-mode-btn"        data-mode="concise"  title="简洁有力">⚡ 简洁</button>
      </div>
      <div class="ai-input-wrap">
        <div id="ai-slash-menu" class="ai-slash-menu hidden"></div>
        <div class="ai-input-bar">
          <textarea id="ai-input" rows="1" placeholder="有什么需要帮忙的？输入 / 快速操作" autocomplete="off"></textarea>
          <button id="btn-send" title="发送 (Ctrl+Enter)">▶</button>
        </div>
        <div class="ai-input-hint-bar">
          <span class="ai-hint-text">Enter 发送 · Shift+Enter 换行 · / 快捷命令 · Esc 取消</span>
          <button id="btn-abort" class="ai-abort-btn hidden" title="取消生成">⬛ 停止</button>
        </div>
      </div>
    `;
    this._chatFlow = document.getElementById('ai-chat-flow');
    this._slashMenu = document.getElementById('ai-slash-menu');
    // Flag: stop auto-scroll-to-bottom when user has manually scrolled up
    this._autoScroll = true;
  }

  // ══════════════════ Bind ══════════════════

  _bind() {
    // Collapse toggle — persist state
    const toggleBtn = document.getElementById('ai-panel-toggle');
    toggleBtn.addEventListener('click', () => {
      const collapsed = this._container.classList.toggle('collapsed');
      toggleBtn.textContent = collapsed ? '◀' : '▶';
      this._saveCollapseState(collapsed);
    });

    // Wheel scroll: stop propagation in capture phase so Univer canvas never
    // steals the event. Do NOT preventDefault — let the browser natively scroll
    // _chatFlow (which works now that min-height:0 is set in CSS).
    this._container.addEventListener('wheel', (e) => {
      e.stopPropagation();
    }, { capture: true, passive: true });

    // Track whether user has scrolled up (disable auto-scroll-to-bottom).
    this._chatFlow.addEventListener('scroll', () => {
      const atBottom = this._chatFlow.scrollHeight - this._chatFlow.scrollTop
                       <= this._chatFlow.clientHeight + 40;
      this._autoScroll = atBottom;
    });

    // Ctrl+Z inside the AI panel → undo last AI injection via custom undo stack
    this._container.addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'z' && !e.shiftKey) {
        if (this._doc && this._doc.canUndo()) {
          e.preventDefault();
          e.stopPropagation();
          if (this._doc.undo()) {
            this.addMessage('↩ 已撤销上一次 AI 修改', 'system');
          }
        }
      }
    });

    // Quick-bar action buttons
    this._container.querySelectorAll('.quick-btn[data-action]').forEach(btn => {
      btn.addEventListener('click', () => this._onAction(btn.dataset.action));
    });

    // Document mode buttons
    this._container.querySelectorAll('.ai-mode-btn[data-mode]').forEach(btn => {
      btn.addEventListener('click', () => {
        this._docMode = btn.dataset.mode;
        this._container.querySelectorAll('.ai-mode-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
      });
    });

    // Input textarea — auto-resize + slash command detection
    const input = document.getElementById('ai-input');
    input.addEventListener('input', () => {
      input.style.height = 'auto';
      input.style.height = Math.min(input.scrollHeight, 120) + 'px';
      this._handleSlashInput(input.value);
    });

    // Keyboard handling
    input.addEventListener('keydown', (e) => {
      // Navigate slash menu
      if (!this._slashMenu.classList.contains('hidden')) {
        if (e.key === 'ArrowDown') { e.preventDefault(); this._navigateSlash(1); return; }
        if (e.key === 'ArrowUp')   { e.preventDefault(); this._navigateSlash(-1); return; }
        if (e.key === 'Enter' && !e.shiftKey) {
          e.preventDefault();
          this._confirmSlash(input);
          return;
        }
        if (e.key === 'Escape') { e.preventDefault(); this._hideSlashMenu(); return; }
      }

      // Send: Ctrl+Enter (always) or Enter (without Shift, when no slash menu)
      if (e.key === 'Enter' && (e.ctrlKey || !e.shiftKey)) {
        if (e.ctrlKey || !e.shiftKey) {
          e.preventDefault();
          this._onCustomInput(input);
        }
      }

      // Escape — cancel streaming
      if (e.key === 'Escape' && this._abortController) {
        this._abortController.abort();
      }
    });

    // Send button
    document.getElementById('btn-send').addEventListener('click', () => this._onCustomInput(input));

    // Abort button
    document.getElementById('btn-abort').addEventListener('click', () => {
      if (this._abortController) this._abortController.abort();
    });

    // Model badge — read wa_locked_model from localStorage, update on storage events
    this._syncModelBadge();
    window.addEventListener('storage', (e) => {
      if (e.key === 'wa_locked_model') this._syncModelBadge();
    });

    // Close slash menu when clicking outside
    document.addEventListener('mousedown', (e) => {
      if (!this._slashMenu.contains(e.target) && e.target !== input) {
        this._hideSlashMenu();
      }
    });

    // Global Ctrl+Z: intercept at document level for AI undo — but only
    // when focus is NOT inside the Univer document canvas (#center-doc),
    // so manual edits in the canvas can still be undone by Univer natively.
    document.addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'z' && !e.shiftKey) {
        const centerDoc = document.getElementById('center-doc');
        if (centerDoc && centerDoc.contains(e.target)) return; // let Univer handle
        if (this._doc && this._doc.canUndo()) {
          e.preventDefault();
          e.stopPropagation();
          if (this._doc.undo()) {
            this.addMessage('↩ 已撤销上一次 AI 修改', 'system');
          }
        }
      }
    }, true);  // capture phase
  }

  // ══════════════════ Slash Command Menu ══════════════════

  _handleSlashInput(value) {
    if (!value.startsWith('/')) { this._hideSlashMenu(); return; }
    const query = value.slice(1).toLowerCase();
    this._slashFiltered = SLASH_COMMANDS.filter(c =>
      c.cmd.slice(1).includes(query) || c.hint.includes(query)
    );
    if (!this._slashFiltered.length) { this._hideSlashMenu(); return; }
    this._slashIdx = 0;
    this._renderSlashMenu();
    this._slashMenu.classList.remove('hidden');
  }

  _renderSlashMenu() {
    this._slashMenu.innerHTML = this._slashFiltered.map((c, i) =>
      `<div class="slash-item${i === this._slashIdx ? ' active' : ''}" data-idx="${i}">
        <span class="slash-icon">${c.icon}</span>
        <span class="slash-cmd">${c.cmd}</span>
        <span class="slash-hint">${c.hint}</span>
      </div>`
    ).join('');
    this._slashMenu.querySelectorAll('.slash-item').forEach(el => {
      el.addEventListener('mousedown', (e) => {
        e.preventDefault();
        this._slashIdx = parseInt(el.dataset.idx);
        const input = document.getElementById('ai-input');
        this._confirmSlash(input);
      });
    });
  }

  _navigateSlash(dir) {
    this._slashIdx = (this._slashIdx + dir + this._slashFiltered.length) % this._slashFiltered.length;
    this._renderSlashMenu();
  }

  _confirmSlash(input) {
    const item = this._slashFiltered[this._slashIdx];
    if (!item) return;
    this._hideSlashMenu();
    input.value = '';
    input.style.height = 'auto';
    this._onAction(item.action);
  }

  _hideSlashMenu() {
    this._slashMenu.classList.add('hidden');
    this._slashFiltered = [];
    this._slashIdx = 0;
  }

  /** Returns full document text from whichever viewer is currently active, falling back to Univer canvas. */
  _getDocFullText() {
    const dv = window.__koto?.docxViewer;
    if (dv && dv.isActive()) return dv.getFullText();
    const pv = window.__koto?.pptxViewer;
    if (pv && pv.isActive()) return pv.getFullText();
    const ev = window.__koto?.excelViewer;
    if (ev && ev.isActive()) return ev.getFullText();
    return this._doc.getFullText();
  }

  // ══════════════════ Action Dispatch ══════════════════

  _onAction(actionType) {
    // Deep document analysis — routes to UnifiedAgent with tool access
    if (actionType === 'analyze_doc') {
      const fullText = this._getDocFullText();
      if (!fullText.trim()) { this.addMessage('文档为空，无内容可分析。', 'error'); return; }
      const input = document.getElementById('ai-input');
      const userQuery = (input && input.value.trim()) || '请对这篇文档进行全面分析，包括主要论点、逻辑结构、数据质量和改进建议。';
      if (input) { input.value = ''; input.style.height = 'auto'; }
      this.addMessage(`🧠 深度分析：${this._truncate(userQuery, 60)}`, 'user');
      this._sendViaAgent(userQuery, fullText);
      return;
    }

    // Data → Narrative: generate analysis paragraph AND chart
    if (actionType === 'narrative') {
      const selection = this._doc.getSelection();
      const hasSelection = selection && selection.text && selection.text.trim();
      const text = hasSelection ? selection.text : this._getDocFullText();
      if (!text.trim()) { this.addMessage('请先选中数据或确保文档有内容。', 'error'); return; }
      this.addMessage(
        hasSelection ? `📝 数据叙述：「${this._truncate(text, 60)}」` : '📝 文档数据叙述',
        'user'
      );
      // Step 1: generate narrative paragraph
      this._sendViaMainAI('narrative', text, hasSelection ? selection : null, '');
      // Step 2: also generate chart (independent, shown below)
      this._sendViaChart(text, '根据以上数据生成最合适的图表');
      return;
    }

    // Chart visualization — uses sandbox endpoint
    if (actionType === 'chart') {
      const selection = this._doc.getSelection();
      const hasSelection = selection && selection.text && selection.text.trim();
      const text = hasSelection ? selection.text : this._getDocFullText();
      const instruction = '';
      this.addMessage(hasSelection
        ? `📊 可视化选中数据：「${this._truncate(text, 60)}」`
        : '📊 可视化当前文档数据', 'user');
      this._sendViaChart(text, instruction);
      return;
    }

    // Find & Replace — works on full document
    if (actionType === 'find_replace') {
      const fullText = this._getDocFullText();
      if (!fullText.trim()) { this.addMessage('文档为空。', 'error'); return; }
      this.addMessage('🔄 智能查找替换', 'user');
      this._sendViaFindReplace(fullText);
      return;
    }

    // Reference search — uses selection or prompts
    if (actionType === 'find_reference') {
      const selection = this._doc.getSelection();
      const hasSelection = selection && selection.text && selection.text.trim();
      const text = hasSelection ? selection.text : '';
      if (!text) { this.addMessage('请先选中需要查找引用的内容。', 'error'); return; }
      this.addMessage(`📚 查找引用：「${this._truncate(text, 60)}」`, 'user');
      this._sendViaMainAI('find_reference', text, selection, '');
      return;
    }

    // Actions that work on full document (no selection needed)
    if (actionType === 'summarize' || actionType === 'continue_writing') {
      const fullText = this._getDocFullText();
      if (!fullText.trim()) { this.addMessage('文档为空，请先输入内容。', 'error'); return; }
      const label = actionType === 'summarize' ? '📋 全文总结' : '✍️ AI 续写';
      this.addMessage(label, 'user');
      this._sendViaMainAI(actionType, fullText, null, '');
      return;
    }

    // check: selection or full doc
    if (actionType === 'check') {
      const selection = this._doc.getSelection();
      const hasSelection = selection && selection.text && selection.text.trim();
      const text = hasSelection ? selection.text : this._getDocFullText();
      if (!text.trim()) { this.addMessage('文档为空，无内容可检查。', 'error'); return; }
      this.addMessage(hasSelection ? `🔍 检查选中：「${this._truncate(text, 60)}」` : '🔍 检查全文', 'user');
      this._sendViaMainAI('check', text, hasSelection ? selection : null, '');
      return;
    }

    // polish / translate / rewrite / annotate require a selection
    const selection = this._doc.getSelection();
    if (!selection || !selection.text || !selection.text.trim()) {
      this.addMessage('请先在编辑器中选中要处理的文本。', 'error');
      return;
    }
    const labels = { polish: '✨ 润色', translate: '🌐 翻译', rewrite: '✏️ 改写', annotate: '🔖 标注' };
    this.addMessage(`${labels[actionType] || actionType}：「${this._truncate(selection.text, 80)}」`, 'user');
    this._sendViaMainAI(actionType, selection.text, selection, '');
  }

  _onCustomInput(input) {
    const text = input.value.trim();
    if (!text) return;
    input.value = '';
    input.style.height = 'auto';
    this._hideSlashMenu();

    // Check if it's a plain /command with no additional text
    if (text.startsWith('/')) {
      const match = SLASH_COMMANDS.find(c => c.cmd === text.trim());
      if (match) { this._onAction(match.action); return; }
    }

    const selection = this._doc.getSelection();
    this.addMessage(text, 'user');

    // Route complex analytical queries (questions with no selection) to UnifiedAgent
    const hasSelection = selection && selection.text && selection.text.trim();
    const isQuestion = /[？?]$/.test(text) || /^(分析|帮我分析|评估|判断|是否|有没有|这份|这个文档|准不准|正确吗|合理吗|检验|验证)/.test(text);
    if (!hasSelection && isQuestion) {
      this._sendViaAgent(text, this._getDocFullText());
      return;
    }

    this._sendViaMainAI('custom_instruction', selection?.text || '', selection, text);
  }

  // ══════════════════ Chart (Sandbox) SSE ══════════════════

  async _sendViaChart(dataContext, instruction) {
    if (this._abortController) this._abortController.abort();
    this._abortController = new AbortController();
    this.expand();
    this._setAbortBtnVisible(true);

    // Running status message
    const statusEl = this.addMessage('', 'ai');

    try {
      const resp = await fetch('/api/editor/ai/chart', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ data_context: dataContext, instruction, lang: 'python', model_mode: localStorage.getItem('wa_locked_model') || 'auto' }),
        signal: this._abortController.signal,
      });

      if (!resp.ok) {
        statusEl.textContent = `❌ 请求失败 (${resp.status})`;
        statusEl.className = 'chat-msg error';
        return;
      }

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let codeText = '';
      let hasImages = false;
      const chartWrap = document.createElement('div');
      chartWrap.className = 'chat-msg chart-result';
      let codeEl = null;

      const processEvent = (ev) => {
        if (!ev.startsWith('data: ')) return;
        let parsed;
        try { parsed = JSON.parse(ev.slice(6)); } catch { return; }

        if (parsed.type === 'status') {
          statusEl.textContent = parsed.text;
        } else if (parsed.type === 'info') {
          this._showInfoBanner(parsed.text || '');
        } else if (parsed.type === 'code') {
          codeText = parsed.text;
          statusEl.style.display = 'none'; // hide status row

          // Build code block with collapsible toggle + edit/rerun
          chartWrap.innerHTML = '';
          const codeWrap = document.createElement('div');
          codeWrap.className = 'chart-code-block';
          const codeHeader = document.createElement('div');
          codeHeader.className = 'chart-code-header';
          codeHeader.innerHTML = '<span>🐍 生成的代码</span>'
            + '<button class="chart-code-toggle">展开</button>'
            + '<button class="chart-code-edit">✏️ 编辑</button>'
            + '<button class="chart-code-rerun hidden">▶ 重新运行</button>';
          const pre = document.createElement('pre');
          pre.className = 'chart-code-pre collapsed';
          pre.textContent = codeText;

          // Editable textarea (hidden by default)
          const textarea = document.createElement('textarea');
          textarea.className = 'chart-code-editor hidden';
          textarea.value = codeText;
          textarea.rows = 12;

          const toggleBtn = codeHeader.querySelector('.chart-code-toggle');
          toggleBtn.addEventListener('click', () => {
            const collapsed = pre.classList.toggle('collapsed');
            toggleBtn.textContent = collapsed ? '展开' : '收起';
          });

          const editBtn = codeHeader.querySelector('.chart-code-edit');
          const rerunBtn = codeHeader.querySelector('.chart-code-rerun');
          editBtn.addEventListener('click', () => {
            pre.classList.add('hidden');
            textarea.classList.remove('hidden');
            textarea.value = codeText;
            rerunBtn.classList.remove('hidden');
            editBtn.classList.add('hidden');
            toggleBtn.classList.add('hidden');
          });
          rerunBtn.addEventListener('click', () => {
            codeText = textarea.value;
            pre.textContent = codeText;
            textarea.classList.add('hidden');
            pre.classList.remove('hidden', 'collapsed');
            rerunBtn.classList.add('hidden');
            editBtn.classList.remove('hidden');
            toggleBtn.classList.remove('hidden');
            toggleBtn.textContent = '收起';
            // Re-run the code via chart-rerun endpoint
            this._rerunChartCode(codeText, chartWrap);
          });

          codeWrap.appendChild(codeHeader);
          codeWrap.appendChild(pre);
          codeWrap.appendChild(textarea);
          codeEl = codeWrap;
          chartWrap.appendChild(codeWrap);
          this._chatFlow.appendChild(chartWrap);
          this._scrollBottom();

        } else if (parsed.type === 'image') {
          hasImages = true;
          const ext = (parsed.name || 'chart.png').split('.').pop().toLowerCase();
          const mime = ext === 'svg' ? 'image/svg+xml' : `image/${ext}`;
          const imgSrc = `data:${mime};base64,${parsed.data}`;
          chartWrap.appendChild(this._makeChartImageWrap(imgSrc, parsed.name || 'chart.png'));
          this._scrollBottom();

        } else if (parsed.type === 'stdout' && parsed.text.trim()) {
          const pre = document.createElement('pre');
          pre.className = 'code-stdout';
          pre.textContent = parsed.text.trim();
          chartWrap.appendChild(pre);

        } else if (parsed.type === 'stderr' && parsed.text.trim()) {
          const pre = document.createElement('pre');
          pre.className = 'code-stderr';
          pre.textContent = parsed.text.trim();
          chartWrap.appendChild(pre);

        } else if (parsed.type === 'error') {
          statusEl.style.display = '';
          statusEl.textContent = `❌ ${parsed.text || '执行失败'}`;
          statusEl.className = 'chat-msg error';
          // Show code if available for debugging
          if (codeText && !chartWrap.isConnected) {
            this._chatFlow.appendChild(chartWrap);
          }
        } else if (parsed.type === 'done') {
          if (!hasImages && !chartWrap.isConnected) {
            this._chatFlow.appendChild(chartWrap);
          }
        }
      };

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split('\n\n');
        buffer = parts.pop();
        for (const part of parts) processEvent(part);
      }
      if (buffer) processEvent(buffer);

    } catch (err) {
      if (err.name === 'AbortError') {
        statusEl.textContent = '⬛ 已取消';
        return;
      }
      statusEl.textContent = `❌ ${err.message}`;
      statusEl.className = 'chat-msg error';
    } finally {
      this._abortController = null;
      this._setAbortBtnVisible(false);
    }
  }

  // ══════════════════ Chart Code Rerun ══════════════════

  async _rerunChartCode(code, chartWrap) {
    // Remove previous images/results from this chart wrap (keep code block)
    chartWrap.querySelectorAll('.chart-img-wrap, .code-stdout, .code-stderr').forEach(el => el.remove());

    const statusEl = this.addMessage('▶ 正在重新运行代码…', 'ai');

    try {
      const resp = await fetch('/api/editor/ai/chart-rerun', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code, lang: 'python' }),
      });

      if (!resp.ok) {
        statusEl.textContent = `❌ 请求失败 (${resp.status})`;
        statusEl.className = 'chat-msg error';
        return;
      }

      const result = await resp.json();
      statusEl.remove();

      if (result.error) {
        const errEl = this.addMessage(`❌ ${result.error}`, 'error');
        if (result.stderr) {
          const pre = document.createElement('pre');
          pre.className = 'code-stderr';
          pre.textContent = result.stderr;
          errEl.after(pre);
        }
        return;
      }

      if (result.stdout) {
        const pre = document.createElement('pre');
        pre.className = 'code-stdout';
        pre.textContent = result.stdout;
        chartWrap.appendChild(pre);
      }

      const images = result.files || {};
      for (const [name, b64] of Object.entries(images)) {
        const ext = name.split('.').pop().toLowerCase();
        const mime = ext === 'svg' ? 'image/svg+xml' : `image/${ext}`;
        chartWrap.appendChild(this._makeChartImageWrap(`data:${mime};base64,${b64}`, name));
      }

      if (!Object.keys(images).length) {
        this.addMessage('代码执行成功但未生成图片。', 'system');
      }

      this._scrollBottom();

    } catch (err) {
      statusEl.textContent = `❌ ${err.message}`;
      statusEl.className = 'chat-msg error';
    }
  }

  // ══════════════════ Find & Replace (HTTP SSE) ══════════════════

  async _sendViaFindReplace(fullText) {
    const instruction = prompt('请描述替换需求（如："把所有的你好替换成您好"，或 "将表格中的2024改成2025"）：');
    if (!instruction) return;

    if (this._abortController) this._abortController.abort();
    this._abortController = new AbortController();
    this.showTyping();
    this.expand();
    this._setAbortBtnVisible(true);

    let resultText = '';
    try {
      const resp = await fetch('/api/editor/ai/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          action: 'find_replace',
          selection: '',
          instruction: instruction,
          full_text: fullText,
          model_mode: localStorage.getItem('wa_locked_model') || 'auto',
        }),
        signal: this._abortController.signal,
      });

      if (!resp.ok) {
        this.removeTyping();
        this.addMessage(`❌ 请求失败 (${resp.status})`, 'error');
        return;
      }

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      const processLine = (line) => {
        if (!line.startsWith('data: ')) return;
        let parsed;
        try { parsed = JSON.parse(line.slice(6)); } catch { return; }
        if (parsed.type === 'token') {
          this.removeTyping();
          this.appendStreamChunk(parsed.text || '');
          resultText += parsed.text || '';
        } else if (parsed.type === 'find_replace_result') {
          this.removeTyping();
          if (this._streamingEl) { this._streamingEl.classList.remove('streaming'); this._streamingEl = null; }
          this._showFindReplacePreview(parsed.replacements, parsed.summary, fullText);
        } else if (parsed.type === 'done') {
          // Try to parse resultText as JSON replacements
          if (resultText.trim()) {
            try {
              const data = JSON.parse(resultText.trim());
              if (data.replacements) {
                if (this._streamingEl) { this._streamingEl.classList.remove('streaming'); this._streamingEl = null; }
                this._showFindReplacePreview(data.replacements, data.summary || '', fullText);
                return;
              }
            } catch { /* not JSON, show as normal message */ }
          }
          if (this._streamingEl) this.finalizeStreamMessage(resultText, 'find_replace', null);
        } else if (parsed.type === 'error') {
          this.removeTyping();
          if (this._streamingEl) { this._streamingEl.classList.remove('streaming'); this._streamingEl = null; }
          this.addMessage(`❌ ${parsed.text || '未知错误'}`, 'error');
        }
      };

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split('\n\n');
        buffer = parts.pop();
        for (const part of parts) processLine(part);
      }
      if (buffer) processLine(buffer);

    } catch (err) {
      if (err.name === 'AbortError') {
        this.removeTyping();
        if (this._streamingEl) { this._streamingEl.classList.remove('streaming'); this._streamingEl = null; }
        return;
      }
      this.removeTyping();
      this.addMessage(`❌ ${err.message}`, 'error');
    } finally {
      this._abortController = null;
      this._setAbortBtnVisible(false);
    }
  }

  _showFindReplacePreview(replacements, summary, fullText) {
    if (!replacements || !replacements.length) {
      this.addMessage('未找到需要替换的内容。', 'system');
      return;
    }

    const wrap = document.createElement('div');
    wrap.className = 'chat-msg ai find-replace-preview';

    // Summary header
    const header = document.createElement('div');
    header.className = 'fr-header';
    header.textContent = summary || `找到 ${replacements.length} 处替换`;
    wrap.appendChild(header);

    // Replacement list with checkboxes
    const list = document.createElement('div');
    list.className = 'fr-list';
    replacements.forEach((r, i) => {
      const item = document.createElement('label');
      item.className = 'fr-item';
      const cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.checked = true;
      cb.dataset.idx = i;
      item.appendChild(cb);
      const text = document.createElement('span');
      text.innerHTML = `<del class="fr-del">${this._escapeHtml(r.from)}</del> → <ins class="fr-ins">${this._escapeHtml(r.to)}</ins>`;
      item.appendChild(text);
      list.appendChild(item);
    });
    wrap.appendChild(list);

    // Action buttons
    const bar = document.createElement('div');
    bar.className = 'msg-action-bar';

    const applyBtn = document.createElement('button');
    applyBtn.className = 'msg-action-btn';
    applyBtn.textContent = '✅ 应用选中的替换';
    applyBtn.addEventListener('click', () => {
      const checked = list.querySelectorAll('input[type="checkbox"]:checked');
      let text = fullText;
      checked.forEach(cb => {
        const r = replacements[parseInt(cb.dataset.idx)];
        if (r) text = text.split(r.from).join(r.to);
      });
      // Route to the appropriate viewer rather than unconditionally writing to Univer canvas
      const _dv = window.__koto?.docxViewer;
      if (_dv && _dv.isActive()) {
        // DOCX mode: apply each replacement to the live DOM via DocxViewer
        checked.forEach(cb => {
          const r = replacements[parseInt(cb.dataset.idx)];
          if (r) _dv.replaceText(r.from, r.to);
        });
      } else {
        this._doc.loadContent(this._cleanAIText(text));
      }
      applyBtn.disabled = true;
      applyBtn.textContent = '✅ 已应用';
    });
    bar.appendChild(applyBtn);

    const selectAllBtn = document.createElement('button');
    selectAllBtn.className = 'msg-action-btn secondary';
    selectAllBtn.textContent = '全选';
    selectAllBtn.addEventListener('click', () => {
      list.querySelectorAll('input[type="checkbox"]').forEach(cb => cb.checked = true);
    });
    bar.appendChild(selectAllBtn);

    const deselectBtn = document.createElement('button');
    deselectBtn.className = 'msg-action-btn secondary';
    deselectBtn.textContent = '全不选';
    deselectBtn.addEventListener('click', () => {
      list.querySelectorAll('input[type="checkbox"]').forEach(cb => cb.checked = false);
    });
    bar.appendChild(deselectBtn);

    wrap.appendChild(bar);
    this._chatFlow.appendChild(wrap);
    this._scrollBottom();
  }

  _escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  /** Scroll chat to bottom only if user hasn't scrolled up manually */
  _scrollBottom() {
    if (this._autoScroll) {
      this._chatFlow.scrollTop = this._chatFlow.scrollHeight;
    }
  }

  _showInfoBanner(text) {
    // Remove any previous info banner to avoid stacking
    this._chatFlow.querySelectorAll('.ai-info-banner').forEach(el => el.remove());
    const banner = document.createElement('div');
    banner.className = 'chat-msg system ai-info-banner';
    banner.style.cssText = 'background:rgba(255,171,0,0.12);border-left:3px solid #ffab00;padding:6px 10px;font-size:11px;color:#b88000;border-radius:4px;margin:4px 0;';
    banner.textContent = text;
    this._chatFlow.appendChild(banner);
    this._scrollBottom();
    setTimeout(() => { if (banner.isConnected) banner.remove(); }, 8000);
  }

  /**
   * Strip markdown-style format artifacts left by LLM or file conversion.
   * Removes **bold**, *italic*, __underline__, heading # markers, and
   * lone divider lines (---/***) while preserving actual content.
   */
  // ══════════════════ Chart image helper ══════════════════

  /**
   * Build a chart-image wrapper with drag-to-doc, open, and download actions.
   * Dragging the image onto #center-doc triggers the global drop handler
   * (registered in main.js) which calls docxViewer.appendImage() or
   * shows a floating image overlay on the Univer canvas.
   */
  _makeChartImageWrap(imgSrc, fileName) {
    const imgWrap = document.createElement('div');
    imgWrap.className = 'chart-img-wrap';

    // Register in the global store so drag only transfers a short ID (not the full base64)
    const imgId = 'ci_' + (++_chartImgCounter);
    _CHART_IMG_STORE.set(imgId, { src: imgSrc, name: fileName });
    // Expose on window so main.js drop handler can resolve without a module import
    if (!window._kotoChartStore) window._kotoChartStore = {};
    window._kotoChartStore[imgId] = { src: imgSrc, name: fileName };

    const img = document.createElement('img');
    img.className = 'chart-img chart-img-draggable';
    img.src = imgSrc;
    img.alt = fileName;
    img.draggable = true;
    img.title = '拖动到左侧文档即可插入图片';
    img.addEventListener('dragstart', (e) => {
      e.dataTransfer.effectAllowed = 'copy';
      // Only transfer the short ID — drop handler resolves full data URL from window._kotoChartStore
      e.dataTransfer.setData('application/koto-chart-id', imgId);
      e.dataTransfer.setData('application/koto-chart-name', fileName);
    });
    imgWrap.appendChild(img);

    const hint = document.createElement('div');
    hint.className = 'chart-drag-hint';
    hint.textContent = '· 拖入文档 ·';
    imgWrap.appendChild(hint);

    const bar = document.createElement('div');
    bar.className = 'msg-action-bar';

    const openBtn = document.createElement('button');
    openBtn.className = 'msg-action-btn secondary';
    openBtn.textContent = '🖼 查看';
    openBtn.title = '在新标签页打开图片';
    openBtn.addEventListener('click', () => {
      // Convert data URL → Blob → Object URL to reliably open in new tab
      // (modern browsers block window.open with data: URLs)
      try {
        const [header, b64] = imgSrc.split(',');
        const mime = header.match(/:(.*?);/)?.[1] || 'image/png';
        const bytes = atob(b64);
        const arr = new Uint8Array(bytes.length);
        for (let i = 0; i < bytes.length; i++) arr[i] = bytes.charCodeAt(i);
        const blob = new Blob([arr], { type: mime });
        const blobUrl = URL.createObjectURL(blob);
        const win = window.open(blobUrl, '_blank');
        // Revoke after a short delay so the tab has time to load it
        setTimeout(() => URL.revokeObjectURL(blobUrl), 30000);
        if (!win) {
          // Popup blocked — fall back to direct download
          const a = document.createElement('a');
          a.href = blobUrl;
          a.target = '_blank';
          a.click();
        }
      } catch (_) {
        // Last resort: try original data URL
        window.open(imgSrc, '_blank');
      }
    });

    const dlBtn = document.createElement('button');
    dlBtn.className = 'msg-action-btn secondary';
    dlBtn.textContent = '💾 下载';
    dlBtn.addEventListener('click', () => {
      const a = document.createElement('a');
      a.href = imgSrc;
      a.download = fileName;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      dlBtn.textContent = '✅ 下载中';
      setTimeout(() => { dlBtn.textContent = '💾 下载'; }, 2000);
    });

    bar.appendChild(openBtn);
    bar.appendChild(dlBtn);
    imgWrap.appendChild(bar);
    return imgWrap;
  }

  _cleanAIText(text) {
    if (!text) return text;
    return text
      .replace(/\*\*\*(.+?)\*\*\*/gs, '$1')   // ***bold italic***
      .replace(/\*\*(.+?)\*\*/gs, '$1')         // **bold**
      .replace(/\*([^*\n]+?)\*/g, '$1')          // *italic*
      .replace(/__(.+?)__/gs, '$1')              // __bold__
      .replace(/_([^_\n]+?)_/g, '$1')            // _italic_
      .replace(/^#{1,6}\s+/gm, '')               // ## Heading
      .replace(/^[\-\*=]{3,}\s*$/gm, '')         // --- / *** dividers
      .replace(/^\s*[\*\-\+]\s+/gm, '')          // * bullet / - bullet / + bullet list items
      .replace(/^\s*\d+\.\s+/gm, '')             // 1. numbered list items
      .replace(/`{1,3}([^`]*)`{1,3}/g, '$1')     // `inline code` / ```code```
      .replace(/^\s*[\*_]+\s*$/gm, '')           // lone * or _ lines
      .replace(/\*{1,3}/g, '')                   // any remaining stray asterisks
      .replace(/\n{3,}/g, '\n\n')               // collapse excess blank lines
      .trim();
  }

  // ══════════════════ Document Auto-Analyze ══════════════════

  /**
   * Called when a file is opened. Silently fetches a structural summary
   * and stores it as _docContext for injection into all subsequent AI calls.
   */
  async analyzeDoc(fullText) {
    this._docContext = '';
    if (!fullText || fullText.trim().length < 30) return;
    try {
      const resp = await fetch('/api/editor/ai/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ full_text: fullText }),
      });
      if (!resp.ok) return;
      const data = await resp.json();
      if (!data.summary) return;
      this._docContext = `文档类型：${data.doc_type || ''}；主题：${data.summary}；` +
        (data.structure && data.structure.length
          ? `结构：${data.structure.slice(0, 4).join(' / ')}`
          : '');
      // Show a subtle doc-awareness chip
      const chip = document.createElement('div');
      chip.className = 'chat-msg system doc-context-chip';
      chip.innerHTML = `📄 <strong>${data.doc_type || '文档'}</strong>：${data.summary}` +
        (data.word_count ? ` <span class="chip-wc">（约${data.word_count}字）</span>` : '');
      // Insert right after initial greeting
      const anchor = this._chatFlow.children[1] || null;
      this._chatFlow.insertBefore(chip, anchor);
      this._scrollBottom();
    } catch {}
  }

  // ══════════════════ Agent (UnifiedAgent) SSE ══════════════════

  /**
   * Routes analytical questions to the full Koto UnifiedAgent with tool access.
   * The current document is injected as context automatically.
   */
  async _sendViaAgent(query, fullText) {
    if (this._abortController) this._abortController.abort();
    this._abortController = new AbortController();

    // Record user turn (mirrors the pattern in _sendViaMainAI)
    this._history.push({ role: 'user', content: query || '' });
    if (this._history.length > 20) this._history = this._history.slice(-20);

    this.showTyping();
    this.expand();
    this._setAbortBtnVisible(true);

    let resultText = '';
    try {
      const resp = await fetch('/api/editor/ai/agent', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query,
          doc_context: this._docContext || '',
          full_text: fullText || this._getDocFullText() || '',
          session_id: this._fileId ? 'editor_' + this._fileId : '',
        }),
        signal: this._abortController.signal,
      });

      if (!resp.ok) {
        this.removeTyping();
        this.addMessage(`❌ 请求失败 (${resp.status})`, 'error');
        return;
      }

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      const processLine = (line) => {
        if (!line.startsWith('data: ')) return;
        let parsed;
        try { parsed = JSON.parse(line.slice(6)); } catch { return; }
        if (parsed.type === 'status') {
          // Show thinking/tool-call status inline as a dimmed system message
          const existing = this._chatFlow.querySelector('.agent-status-msg');
          if (existing) { existing.textContent = parsed.text; }
          else {
            const el = document.createElement('div');
            el.className = 'chat-msg system agent-status-msg';
            el.textContent = parsed.text;
            this._chatFlow.appendChild(el);
            this._scrollBottom();
          }
        } else if (parsed.type === 'token') {
          this.removeTyping();
          // Remove status chip once answer starts
          this._chatFlow.querySelectorAll('.agent-status-msg').forEach(el => el.remove());
          this.appendStreamChunk(parsed.text || '');
          resultText += parsed.text || '';
        } else if (parsed.type === 'done') {
          if (resultText) this._history.push({ role: 'assistant', content: resultText });
          if (this._streamingEl) this.finalizeStreamMessage(resultText, 'analyze_doc', null);
        } else if (parsed.type === 'error') {
          this.removeTyping();
          this._chatFlow.querySelectorAll('.agent-status-msg').forEach(el => el.remove());
          if (this._streamingEl) { this._streamingEl.classList.remove('streaming'); this._streamingEl = null; }
          this.addMessage(`❌ ${parsed.text || '未知错误'}`, 'error');
        }
      };

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split('\n\n');
        buffer = parts.pop();
        for (const part of parts) processLine(part);
      }
      if (buffer) processLine(buffer);
      if (this._streamingEl) {
        if (resultText) this._history.push({ role: 'assistant', content: resultText });
        this.finalizeStreamMessage(resultText, 'analyze_doc', null);
      }

    } catch (err) {
      if (err.name === 'AbortError') {
        this.removeTyping();
        if (this._streamingEl) { this._streamingEl.classList.remove('streaming'); this._streamingEl = null; }
        return;
      }
      this.removeTyping();
      if (this._streamingEl) { this._streamingEl.classList.remove('streaming'); this._streamingEl = null; }
      this.addMessage(`❌ ${err.message}`, 'error');
    } finally {
      this._abortController = null;
      this._setAbortBtnVisible(false);
    }
  }

  // ══════════════════ Main AI (HTTP SSE) ══════════════════

  async _sendViaMainAI(actionType, selectionText, selectionCtx, instruction) {
    // Record this user turn before sending (popped on abort)
    const _userMsg = instruction
      || (actionType !== 'custom_instruction'
          ? actionType + '：' + this._truncate(selectionText || '', 100)
          : selectionText || actionType);
    this._history.push({ role: 'user', content: _userMsg });
    if (this._history.length > 20) this._history = this._history.slice(-20);

    if (this._abortController) this._abortController.abort();
    this._abortController = new AbortController();

    this.showTyping();
    this.expand();
    this._setAbortBtnVisible(true);

    const _histCtx = this._history.slice(0, -1); // previous turns (exclude current)
    let fullText = '';
    try {
      const resp = await fetch('/api/editor/ai/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          action: actionType,
          selection: selectionText || '',
          instruction: instruction || '',
          full_text: this._getDocFullText() || '',
          doc_context: this._docContext || '',
          doc_mode: this._docMode || 'normal',
          model_mode: localStorage.getItem('wa_locked_model') || 'auto',
          history: _histCtx,
          session_id: this._fileId ? 'editor_' + this._fileId : '',
        }),
        signal: this._abortController.signal,
      });

      if (!resp.ok) {
        this.removeTyping();
        this.addMessage(`❌ 请求失败 (${resp.status})`, 'error');
        return;
      }

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      const processLine = (line) => {
        if (!line.startsWith('data: ')) return;
        let parsed;
        try { parsed = JSON.parse(line.slice(6)); } catch { return; }
        if (parsed.type === 'token') {
          this.removeTyping();
          this.appendStreamChunk(parsed.text || '');
          fullText += parsed.text || '';
        } else if (parsed.type === 'info') {
          // Non-streaming notification: fallback to local model, etc.
          this._showInfoBanner(parsed.text || '');
        } else if (parsed.type === 'done') {
          if (fullText) this._history.push({ role: 'assistant', content: fullText });
          if (this._streamingEl) this.finalizeStreamMessage(fullText, actionType, selectionCtx);
        } else if (parsed.type === 'error') {
          this.removeTyping();
          if (this._streamingEl) {
            this._streamingEl.classList.remove('streaming');
            this._streamingEl = null;
          }
          this.addMessage(`❌ ${parsed.text || '未知错误'}`, 'error');
        }
      };

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split('\n\n');
        buffer = parts.pop();
        for (const part of parts) processLine(part);
      }
      if (buffer) processLine(buffer);
      if (this._streamingEl) {
        // Stream ended without a 'done' event — still record what we got
        if (fullText) this._history.push({ role: 'assistant', content: fullText });
        this.finalizeStreamMessage(fullText, actionType, selectionCtx);
      }

    } catch (err) {
      if (err.name === 'AbortError') {
        this._history.pop(); // discard the unfulfilled user turn
        this.removeTyping();
        if (this._streamingEl) {
          this._streamingEl.classList.remove('streaming');
          this._streamingEl.textContent += '\n[已取消]';
          this._streamingEl = null;
        }
        return;
      }
      this.removeTyping();
      if (this._streamingEl) { this._streamingEl.classList.remove('streaming'); this._streamingEl = null; }
      this.addMessage(`❌ ${err.message}`, 'error');
    } finally {
      this._abortController = null;
      this._setAbortBtnVisible(false);
    }
  }

  // ══════════════════ Public API ══════════════════

  updateStatus(text, type) {
    const el = document.getElementById('conn-status');
    if (el) { el.textContent = text; el.className = 'conn-status ' + type; }
  }

  _syncModelBadge() {
    const badge = document.getElementById('ai-model-badge');
    if (!badge) return;
    const isLocal = (localStorage.getItem('wa_locked_model') || 'auto') === 'local';
    badge.textContent = isLocal ? 'Ollama ●' : '';
    badge.className = isLocal ? 'ai-model-badge local' : 'ai-model-badge';
  }

  /** Called by workspace-assistant when the user switches models globally. */
  notifyModelChange(newModel) {
    this._syncModelBadge();
  }

  addMessage(text, role = 'system') {
    if (!this._chatFlow) return null;
    const div = document.createElement('div');
    div.className = 'chat-msg ' + role;
    div.textContent = text;
    this._chatFlow.appendChild(div);
    this._scrollBottom();
    return div;
  }

  /** Returns accumulated text from the active streaming bubble (fallback for SocketBridge). */
  getStreamingText() {
    return this._streamingEl?.textContent || '';
  }

  startStreamMessage() {
    this.removeTyping();
    if (this._streamingEl) return this._streamingEl;
    const div = document.createElement('div');
    div.className = 'chat-msg ai streaming';
    this._chatFlow.appendChild(div);
    this._streamingEl = div;
    this._scrollBottom();
    return div;
  }

  appendStreamChunk(chunk) {
    if (!this._streamingEl) this.startStreamMessage();
    this._streamingEl.textContent += chunk;
    this._scrollBottom();
  }

  finalizeStreamMessage(fullText, actionType, selectionContext) {
    const el = this._streamingEl;
    this._streamingEl = null;
    if (!el) return;
    el.classList.remove('streaming');

    // Clean markdown symbols from the displayed bubble text
    if (el.childNodes.length === 1 && el.firstChild.nodeType === Node.TEXT_NODE) {
      el.textContent = this._cleanAIText(el.textContent);
    }

    const bar = document.createElement('div');
    bar.className = 'msg-action-bar';
    this._buildApplyButtons(fullText, actionType, selectionContext, el).forEach(b => bar.appendChild(b));

    // Copy button
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

    // Next-steps hint row
    const steps = NEXT_STEPS[actionType];
    if (steps && steps.length) {
      const nextRow = document.createElement('div');
      nextRow.className = 'ai-next-steps';
      const label = document.createElement('span');
      label.className = 'ai-next-label';
      label.textContent = '继续 →';
      nextRow.appendChild(label);
      steps.forEach(step => {
        const btn = document.createElement('button');
        btn.className = 'ai-next-btn';
        btn.textContent = step.label;
        btn.addEventListener('click', () => {
          nextRow.remove();
          this._onAction(step.action);
        });
        nextRow.appendChild(btn);
      });
      el.appendChild(nextRow);
    }

    this._scrollBottom();
  }

  _buildApplyButtons(text, actionType, ctx, msgEl) {
    const btns = [];
    // Clean markdown artifacts before any injection into the document
    const clean = this._cleanAIText(text);
    const make = (label, cb) => {
      const btn = document.createElement('button');
      btn.className = 'msg-action-btn';
      btn.textContent = label;
      btn.addEventListener('click', () => {
        const ok = cb();
        if (ok === false) {
          // Modification failed — likely DOCX read-only mode or no active Univer doc
          this.addMessage('⚠ 当前文档为只读模式（如 DOCX）或编辑器未加载，无法直接修改。AI 内容已显示在上方，请复制后手动粘贴。', 'system');
        } else {
          btn.disabled = true;
          btn.textContent = '✅ 已应用';
        }
      });
      return btn;
    };

    // Helper: apply a text replacement, DOCX-aware
    const applyReplace = (range) => {
      if (ctx?._docxMode) {
        const dv = window.__koto?.docxViewer;
        return (dv && dv.isActive()) ? dv.replaceText(ctx.text, clean) : false;
      }
      return this._doc.replaceRange(range, clean);
    };
    const canReplace = !!(ctx?.range || ctx?._docxMode);

    const DIFF_ACTIONS = new Set(['polish', 'translate', 'rewrite', 'check']);
    if (DIFF_ACTIONS.has(actionType) && ctx?.text) {
      // Show inline diff view (word-level)
      const diffEl = this._buildDiffView(ctx.text, clean);
      if (diffEl && msgEl) {
        msgEl.textContent = '';
        msgEl.appendChild(diffEl);
      }

      // Helper: disable all buttons in the bar after an action is taken
      const lockBar = (activeBtn, label) => {
        const bar = activeBtn.closest('.msg-action-bar');
        if (bar) bar.querySelectorAll('button').forEach(b => { b.disabled = true; });
        activeBtn.textContent = label;
      };

      if (canReplace) {
        const acceptBtn = document.createElement('button');
        acceptBtn.className = 'msg-action-btn';
        acceptBtn.textContent = '✅ 接受修改';
        acceptBtn.addEventListener('click', () => {
          const ok = applyReplace(ctx?.range);
          if (ok === false) {
            this.addMessage('⚠ 当前文档为只读模式（如 DOCX）或编辑器未加载，无法直接修改。AI 内容已显示在上方，请复制后手动粘贴。', 'system');
          } else {
            lockBar(acceptBtn, '✅ 已接受');
          }
        });
        btns.push(acceptBtn);
      }

      // Reject button — removes the AI bubble entirely
      const rejectBtn = document.createElement('button');
      rejectBtn.className = 'msg-action-btn secondary diff-reject-btn';
      rejectBtn.textContent = '❌ 拒绝';
      rejectBtn.addEventListener('click', () => {
        if (msgEl) msgEl.remove();
      });
      btns.push(rejectBtn);

      // Regenerate button — removes bubble and re-sends the same action
      const regenBtn = document.createElement('button');
      regenBtn.className = 'msg-action-btn secondary';
      regenBtn.textContent = '🔄 重新生成';
      regenBtn.addEventListener('click', () => {
        if (msgEl) msgEl.remove();
        if (ctx?.text) {
          const labels = { polish: '✨ 润色', translate: '🌐 翻译', rewrite: '✏️ 改写', check: '🔍 检查' };
          this.addMessage(`${labels[actionType] || actionType}：「${this._truncate(ctx.text, 80)}」`, 'user');
          this._sendViaMainAI(actionType, ctx.text, ctx, '');
        }
      });
      btns.push(regenBtn);

      btns.push(make('📝 插入到末尾', () => this._doc.insertTextAtCursor('\n' + clean)));
    } else if (actionType === 'narrative') {
      // Narrative paragraph: offer to insert after the data or at cursor
      btns.push(make('📝 插入分析段落', () => this._doc.insertTextAtCursor('\n\n' + clean)));
      if (canReplace) btns.push(make('✅ 替换选中内容', () => applyReplace(ctx?.range)));
    } else if (actionType === 'analyze_doc') {
      // Analysis result: informational, offer insert or just copy
      btns.push(make('📝 插入分析报告', () => this._doc.insertTextAtCursor('\n\n【AI 分析报告】\n' + clean)));
    } else if (actionType === 'annotate') {
      if (canReplace) btns.push(make('✏️ 替换选中内容', () => applyReplace(ctx?.range)));
      btns.push(make('📝 插入到末尾', () => this._doc.insertTextAtCursor('\n' + clean)));
    } else if (actionType === 'continue_writing') {
      btns.push(make('📝 追加到文档', () => this._doc.insertTextAtCursor('\n' + clean)));
    } else if (actionType === 'summarize') {
      btns.push(make('📝 插入总结', () => this._doc.insertTextAtCursor('\n\n【总结】\n' + clean)));
    } else if (actionType === 'check') {
      btns.push(make('📝 插入修改建议', () => this._doc.insertTextAtCursor('\n\n【检查建议】\n' + clean)));
    } else if (actionType === 'find_reference') {
      btns.push(make('📝 插入引用', () => this._doc.insertTextAtCursor('\n\n【参考引用】\n' + clean)));
    } else if (actionType === 'explain') {
      // Explanation is informational — insert only, no "replace selected" option
      btns.push(make('📝 插入解释', () => this._doc.insertTextAtCursor('\n\n【解释】\n' + clean)));
    } else {
      if (canReplace) btns.push(make('✏️ 替换选中内容', () => applyReplace(ctx?.range)));
      btns.push(make('📝 插入到末尾', () => this._doc.insertTextAtCursor('\n' + clean)));
    }
    return btns;
  }

  // ══════════════════ Diff View ══════════════════

  _buildDiffView(original, revised) {
    // Limit diff computation to reasonable size
    const MAX_WORDS = 400;
    const tokOld = original.split(/(\s+)/);
    const tokNew = revised.split(/(\s+)/);
    if (tokOld.length > MAX_WORDS || tokNew.length > MAX_WORDS) {
      // Just show both texts side by side without word diff
      const wrap = document.createElement('div');
      wrap.className = 'diff-simple';
      const del = document.createElement('div');
      del.className = 'diff-old';
      del.textContent = original;
      const add = document.createElement('div');
      add.className = 'diff-new';
      add.textContent = revised;
      wrap.appendChild(del);
      wrap.appendChild(add);
      return wrap;
    }

    const diff = this._computeWordDiff(tokOld, tokNew);
    const frag = document.createElement('div');
    frag.className = 'diff-view';
    diff.forEach(d => {
      const span = document.createElement('span');
      span.textContent = d.text;
      if (d.type === 'del') span.className = 'diff-del';
      else if (d.type === 'add') span.className = 'diff-add';
      frag.appendChild(span);
    });
    return frag;
  }

  _computeWordDiff(oldToks, newToks) {
    const m = oldToks.length, n = newToks.length;
    // dp[i][j] = LCS length of oldToks[i:] and newToks[j:]
    const dp = Array.from({ length: m + 1 }, () => new Int16Array(n + 1));
    for (let i = m - 1; i >= 0; i--) {
      for (let j = n - 1; j >= 0; j--) {
        dp[i][j] = oldToks[i] === newToks[j]
          ? dp[i + 1][j + 1] + 1
          : Math.max(dp[i + 1][j], dp[i][j + 1]);
      }
    }
    const result = [];
    let i = 0, j = 0;
    while (i < m || j < n) {
      if (i < m && j < n && oldToks[i] === newToks[j]) {
        result.push({ type: 'same', text: oldToks[i] });
        i++; j++;
      } else if (j < n && (i >= m || dp[i][j + 1] >= dp[i + 1][j])) {
        result.push({ type: 'add', text: newToks[j] });
        j++;
      } else {
        result.push({ type: 'del', text: oldToks[i] });
        i++;
      }
    }
    return result;
  }

  // ══════════════════ Legacy code-result (SocketBridge) ══════════════════

  showCodeResult(payload) {
    if (!this._chatFlow) return;
    this.removeTyping();
    if (payload.error) { this.addMessage('❌ 执行错误：' + payload.error, 'error'); return; }
    const wrap = document.createElement('div');
    wrap.className = 'chat-msg code-result';
    if (payload.stdout) {
      const pre = document.createElement('pre');
      pre.className = 'code-stdout';
      pre.textContent = payload.stdout.trim();
      wrap.appendChild(pre);
    }
    if (payload.files) {
      Object.entries(payload.files).forEach(([name, b64]) => {
        const ext = name.split('.').pop().toLowerCase();
        if (['png', 'jpg', 'jpeg', 'svg', 'gif'].includes(ext)) {
          const mime = `image/${ext === 'svg' ? 'svg+xml' : ext}`;
          wrap.appendChild(this._makeChartImageWrap(`data:${mime};base64,${b64}`, name));
        }
      });
    }
    this._chatFlow.appendChild(wrap);
    this._scrollBottom();
  }

  /**
   * Show a transient progress message (e.g. "正在分析上下文…").
   * Previous progress message is replaced in-place.
   */
  showProgressMessage(text) {
    if (!this._chatFlow) return;
    let el = this._chatFlow.querySelector('.ai-progress-msg');
    if (!el) {
      el = document.createElement('div');
      el.className = 'chat-msg system ai-progress-msg';
      el.style.cssText = 'opacity:0.7;font-size:11px;padding:3px 8px;';
      this._chatFlow.appendChild(el);
    }
    el.textContent = text;
    this._scrollBottom();
  }

  /** Remove all progress indicator messages. */
  removeProgressMessages() {
    if (!this._chatFlow) return;
    this._chatFlow.querySelectorAll('.ai-progress-msg').forEach(el => el.remove());
  }

  /**
   * Show structured proposals from socket_handler agent_proposals event.
   * Each proposal: { id, original_text, proposed_text, rationale, tool_call }
   */
  showProposals(proposals, summary, selectionCtx) {
    if (!this._chatFlow) return;
    this.removeProgressMessages();

    const wrap = document.createElement('div');
    wrap.className = 'chat-msg ai proposals-wrap';

    if (summary) {
      const sumEl = document.createElement('div');
      sumEl.className = 'proposals-summary';
      sumEl.textContent = summary;
      wrap.appendChild(sumEl);
    }

    proposals.forEach((p) => {
      const card = document.createElement('div');
      card.className = 'proposal-card';

      // Clean markdown symbols from proposed text before display and application
      const cleanProposed = this._cleanAIText(p.proposed_text);

      const diffEl = this._buildDiffView(p.original_text, cleanProposed);
      if (diffEl) card.appendChild(diffEl);

      const bar = document.createElement('div');
      bar.className = 'msg-action-bar';

      const applyBtn = document.createElement('button');
      applyBtn.className = 'msg-action-btn';
      applyBtn.textContent = '✅ 应用';
      applyBtn.addEventListener('click', () => {
        // Prefer DOCX viewer replace if in docx mode
        if (selectionCtx?._docxMode) {
          const dv = window.__koto?.docxViewer;
          if (dv && dv.isActive()) {
            dv.replaceText(p.original_text, cleanProposed);
          }
        } else if (selectionCtx?.range) {
          this._doc.replaceRange(selectionCtx.range, cleanProposed);
        } else {
          // No range — insert at cursor
          this._doc.insertTextAtCursor('\n' + cleanProposed);
        }
        applyBtn.disabled = true;
        applyBtn.textContent = '✅ 已应用';
      });
      bar.appendChild(applyBtn);

      const copyBtn = document.createElement('button');
      copyBtn.className = 'msg-action-btn secondary';
      copyBtn.textContent = '📋 复制';
      copyBtn.addEventListener('click', () => {
        navigator.clipboard.writeText(cleanProposed).then(() => {
          copyBtn.textContent = '✅ 已复制';
          setTimeout(() => { copyBtn.textContent = '📋 复制'; }, 2000);
        });
      });
      bar.appendChild(copyBtn);

      card.appendChild(bar);
      wrap.appendChild(card);
    });

    this._chatFlow.appendChild(wrap);
    this._scrollBottom();
  }

  /**
   * Handle direct doc_tool_call events (non-proposal mode).
   * Shows a confirmation message with apply button.
   */
  handleDocToolCall(toolCall) {
    if (!this._chatFlow) return;
    const type = toolCall.type || 'unknown';
    const value = toolCall.value || '';
    const preview = value.length > 60 ? value.substring(0, 60) + '…' : value;

    const el = this.addMessage(`🔧 文档操作 (${type})：${preview}`, 'ai');
    const bar = document.createElement('div');
    bar.className = 'msg-action-bar';

    const applyBtn = document.createElement('button');
    applyBtn.className = 'msg-action-btn';
    applyBtn.textContent = '✅ 应用到文档';
    applyBtn.addEventListener('click', () => {
      // Strip HTML tags for plain text insertion
      const clean = value.replace(/<[^>]+>/g, '').trim() || value;
      this._doc.insertTextAtCursor('\n' + clean);
      applyBtn.disabled = true;
      applyBtn.textContent = '✅ 已应用';
    });
    bar.appendChild(applyBtn);
    el.appendChild(bar);
  }

  // ══════════════════ State helpers ══════════════════

  showTyping() {
    this.removeTyping();
    const div = document.createElement('div');
    div.className = 'chat-msg ai';
    div.id = 'typing-indicator';
    div.innerHTML = '<div class="typing-indicator"><span></span><span></span><span></span></div>';
    this._chatFlow.appendChild(div);
    this._scrollBottom();
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
      this._saveCollapseState(false);
    }
  }

  _setAbortBtnVisible(visible) {
    const btn = document.getElementById('btn-abort');
    if (btn) btn.classList.toggle('hidden', !visible);
  }

  _saveCollapseState(collapsed) {
    try { localStorage.setItem('ai-panel-collapsed', collapsed ? '1' : '0'); } catch {}
  }

  _restoreCollapseState() {
    try {
      const saved = localStorage.getItem('ai-panel-collapsed');
      const toggleBtn = document.getElementById('ai-panel-toggle');
      if (saved === '0') {
        this._container.classList.remove('collapsed');
        if (toggleBtn) toggleBtn.textContent = '▶';
      } else {
        // Default collapsed
        this._container.classList.add('collapsed');
        if (toggleBtn) toggleBtn.textContent = '◀';
      }
    } catch {}
  }

  /** Reset conversation history and load any saved history from server. */
  resetHistory(fileId = null) {
    this._fileId = fileId;
    this._history = [];
    this._docContext = '';
    if (this._chatFlow) {
      this._chatFlow.querySelectorAll('.chat-hist-sep, .chat-hist-item, .doc-context-chip').forEach(el => el.remove());
    }
    if (fileId) {
      this._loadServerHistory(fileId);
      // Silently analyze document structure for contextual awareness
      setTimeout(() => {
        const fullText = this._getDocFullText();
        if (fullText && fullText.trim().length >= 30) this.analyzeDoc(fullText);
      }, 800);  // slight delay to let the document finish loading
    }
  }

  /** Fetch saved conversation from server and display it as dimmed history above new messages. */
  async _loadServerHistory(docId) {
    try {
      const resp = await fetch(`/api/editor/ai/history?doc_id=${encodeURIComponent(docId)}`);
      if (!resp.ok) return;
      const data = await resp.json();
      const history = data.history || [];
      if (history.length === 0) return;
      // Inject separator
      const sep = document.createElement('div');
      sep.className = 'chat-hist-sep';
      sep.textContent = '── 历史记录 ──';
      // Insert after the initial greeting message
      const anchor = this._chatFlow.children[1] || null;
      this._chatFlow.insertBefore(sep, anchor);
      let insertAfter = sep;
      history.forEach(turn => {
        const el = document.createElement('div');
        el.className = `chat-msg chat-hist-item ${turn.role === 'user' ? 'user' : 'ai'}`;
        const ts = turn.timestamp
          ? `<small class="chat-hist-ts">${new Date(turn.timestamp).toLocaleString()}</small>`
          : '';
        el.innerHTML = ts + (turn.content || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        insertAfter.insertAdjacentElement('afterend', el);
        insertAfter = el;
      });
      // Restore in-memory history for multi-turn continuity
      this._history = history.map(t => ({
        role: t.role === 'user' ? 'user' : 'assistant',
        content: t.content || '',
      }));
      this._scrollBottom();
    } catch {}
  }

  _truncate(str, max) {
    return str.length > max ? str.substring(0, max) + '…' : str;
  }
}


