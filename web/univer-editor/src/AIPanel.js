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
  // ── Multi-step Skills ──
  { cmd: '/格式统一', action: 'format_normalize',  icon: '🎨', hint: '统一文档格式' },
  { cmd: '/审查',     action: 'review_checklist',  icon: '📋', hint: '文档审查清单' },
  { cmd: '/术语翻译', action: 'glossary_translate', icon: '📖', hint: '术语表+一致性翻译' },
  { cmd: '/会议纪要', action: 'meeting_notes',     icon: '📝', hint: '笔记→结构化纪要' },
  { cmd: '/清洗数据', action: 'data_clean',         icon: '🧹', hint: '表格数据清洗' },
  { cmd: '/填充幻灯片', action: 'slide_expand',    icon: '📑', hint: 'PPT大纲→内容填充' },
  // ── 文档专属（docx/pdf）──
  { cmd: '/格式修复',   action: 'doc_format_fix',   icon: '🔧', hint: '修复标题/列表/段落格式', fileTypes: ['docx', 'pdf'] },
  { cmd: '/事实核查',   action: 'doc_fact_check',   icon: '🔍', hint: '标记可疑数据和断言',     fileTypes: ['docx', 'pdf'] },
  { cmd: '/可读性',     action: 'doc_readability',  icon: '👓', hint: '简化长句、消除冗词',     fileTypes: ['docx', 'pdf'] },
  { cmd: '/法务审阅',   action: 'legal_review',     icon: '⚖️', hint: '检查合同条款完整性',     fileTypes: ['docx', 'pdf'] },
  { cmd: '/财务审阅',   action: 'financial_review', icon: '💰', hint: '核查财务数据一致性',     fileTypes: ['docx', 'pdf'] },
  { cmd: '/学术润色',   action: 'academic_polish',  icon: '🎓', hint: '期刊投稿风格精修',       fileTypes: ['docx', 'pdf'] },
  // ── Excel 专属（xlsx/csv）──
  { cmd: '/公式',       action: 'excel_formula',    icon: '🔢', hint: '诊断公式错误并推荐优化', fileTypes: ['xlsx', 'csv'] },
  { cmd: '/数据清洗',   action: 'excel_clean',      icon: '🧹', hint: '处理空值/重复行/异常值', fileTypes: ['xlsx', 'csv'] },
  { cmd: '/透视表',     action: 'pivot_table',      icon: '🔄', hint: '建议最优透视表结构',     fileTypes: ['xlsx', 'csv'] },
  // ── PPT 专属（pptx）──
  { cmd: '/演示叙事',   action: 'slide_storytell',  icon: '🎬', hint: '优化幻灯片故事线',       fileTypes: ['pptx'] },
  { cmd: '/图表建议',   action: 'slide_chart_type', icon: '📊', hint: '推荐最佳可视化图表类型', fileTypes: ['pptx'] },
  // ── AI 任务引擎 ──
  { cmd: '/任务',       action: 'ai_task',          icon: '🤖', hint: 'AI 自动规划并执行文件任务' },
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
    this._currentFileType = '';  // updated when a file is opened
    this._slashFiltered = [];
    this._history = [];   // [{role:'user'|'assistant', content:str}] multi-turn memory
    this._fileId  = null; // current doc ID (for server-side session persistence)
    this._docContext = ''; // brief document summary injected into all AI requests
    this._docMode = 'normal'; // Document mode: normal | formal | casual | academic | concise
    this._skillCache = null;   // cached skill list from /api/skills
    this._socketTaskProgress = null;
    this._emptyState = null;
    this._chatObserver = null;

    this._render();
    this._bind();
    this._bridge.setAIPanel(this);
    this._restoreCollapseState();
    this._loadActiveSkillBar();
  }

  // ══════════════════ Render ══════════════════

  _render() {
    this._container.innerHTML = `
      <div class="ai-panel-header">
        <button id="ai-panel-toggle" class="ai-panel-toggle-btn" title="展开/折叠 AI 面板">◀</button>
        <span class="ai-panel-title">AI 助手</span>
        <button id="ai-skill-lib-btn" class="ai-skill-lib-btn" title="技能库">📚</button>
        <span id="ai-model-badge" class="ai-model-badge"></span>
        <span id="conn-status" class="conn-status connected"><span class="conn-dot"></span>Koto AI</span>
      </div>
      <div id="ai-skill-bar" class="ai-skill-bar"></div>
      <div id="ai-chat-flow" class="ai-chat-flow">
        <section id="ai-empty-state" class="ai-empty-state">
          <div class="ai-empty-hero">
            <div class="ai-empty-hero-badge">✦</div>
            <h3 class="ai-empty-hero-title">欢迎使用 Koto AI</h3>
            <p class="ai-empty-hero-desc">围绕当前文件、选中文本或补充附件直接提问，AI 会按你的目标继续处理。</p>
          </div>
          <div class="ai-empty-context-grid">
            <button type="button" class="ai-empty-context" data-prefill="请先读一下当前文件，告诉我结构、重点和结论。">
              <span class="ai-empty-context-tag">当前文件</span>
              <span class="ai-empty-context-text">直接提问，让 AI 先快速读懂正在编辑的内容。</span>
            </button>
            <button type="button" class="ai-empty-context" data-prefill="我想基于当前选中的内容继续处理，请先判断最合适的下一步。">
              <span class="ai-empty-context-tag">选中文字</span>
              <span class="ai-empty-context-text">选中后可配合底部的润色、总结、检查、翻译、可视化。</span>
            </button>
            <button type="button" class="ai-empty-context" data-prefill="我会补充附件，请帮我一起分析、对比和提炼要点。">
              <span class="ai-empty-context-tag">补充附件</span>
              <span class="ai-empty-context-text">继续拖入文件后，可一起分析、对比和提炼重点。</span>
            </button>
          </div>
          <div class="ai-empty-card-grid">
            <button type="button" class="ai-empty-card" data-prefill="先给我结构、重点和结论。">
              <span class="ai-empty-card-icon">🗂</span>
              <span class="ai-empty-card-title">快速读懂当前文件</span>
              <span class="ai-empty-card-text">先给我结构、重点和结论。</span>
            </button>
            <button type="button" class="ai-empty-card" data-prefill="把信息整理成可执行结论和待办。">
              <span class="ai-empty-card-icon">☰</span>
              <span class="ai-empty-card-title">总结重点与待办</span>
              <span class="ai-empty-card-text">把信息整理成可执行结论。</span>
            </button>
            <button type="button" class="ai-empty-card" data-prefill="帮我检查这份内容里的语病、逻辑和表达风险。">
              <span class="ai-empty-card-icon">◌</span>
              <span class="ai-empty-card-title">检查问题并修订</span>
              <span class="ai-empty-card-text">找出语病、逻辑和表达风险。</span>
            </button>
            <button type="button" class="ai-empty-card" data-prefill="保留术语，同时优化语言表达，必要时也可以翻译。">
              <span class="ai-empty-card-icon">文</span>
              <span class="ai-empty-card-title">翻译或改写内容</span>
              <span class="ai-empty-card-text">保留术语，同时优化语言表达。</span>
            </button>
          </div>
          <div class="ai-empty-footer">也可以先在文档里选中文字，再使用底部快捷动作继续处理。</div>
        </section>
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
          <button id="btn-abort" class="ai-abort-btn hidden" title="取消生成">⬛</button>
        </div>
        <div class="ai-input-hint-bar">
          <span class="ai-hint-text">Enter 发送 · Shift+Enter 换行 · / 快捷命令 · Esc 取消</span>
        </div>
      </div>
    `;
    this._chatFlow = document.getElementById('ai-chat-flow');
    this._emptyState = document.getElementById('ai-empty-state');
    this._slashMenu = document.getElementById('ai-slash-menu');
    this._skillBar = document.getElementById('ai-skill-bar');
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

    // Skill library button
    const skillLibBtn = document.getElementById('ai-skill-lib-btn');
    if (skillLibBtn) skillLibBtn.addEventListener('click', () => this._toggleSkillLibrary());

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
    this._resizeInput(input);
    input.addEventListener('input', () => {
      this._resizeInput(input);
      this._handleSlashInput(input.value);
    });
    window.addEventListener('resize', () => this._resizeInput(input));
    this._bindEmptyState(input);
    this._setupChatFlowObserver();

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

    // Model badge — read editor_model_mode from localStorage, update on storage events
    this._syncModelBadge();
    window.addEventListener('storage', (e) => {
      if (e.key === 'editor_model_mode') this._syncModelBadge();
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

  _getInputBaseHeight() {
    const panelHeight = this._container?.clientHeight || window.innerHeight || 0;
    return Math.max(140, Math.min(280, Math.floor(panelHeight * 0.25)));
  }

  _getInputMaxHeight() {
    const panelHeight = this._container?.clientHeight || window.innerHeight || 0;
    return Math.max(this._getInputBaseHeight(), Math.min(360, Math.floor(panelHeight * 0.45)));
  }

  _resizeInput(input) {
    if (!input) return;
    input.style.height = 'auto';
    const baseHeight = this._getInputBaseHeight();
    const maxHeight = this._getInputMaxHeight();
    input.style.height = Math.max(baseHeight, Math.min(input.scrollHeight, maxHeight)) + 'px';
    input.style.overflowY = input.scrollHeight > maxHeight ? 'auto' : 'hidden';
  }

  _resetInput(input) {
    if (!input) return;
    input.value = '';
    input.style.overflowY = 'hidden';
    this._resizeInput(input);
  }

  _bindEmptyState(input) {
    if (!this._emptyState || !input) return;
    this._emptyState.querySelectorAll('[data-prefill]').forEach((el) => {
      el.addEventListener('click', () => {
        const text = el.dataset.prefill || '';
        input.value = text;
        this._resizeInput(input);
        input.focus();
        const cursor = input.value.length;
        if (typeof input.setSelectionRange === 'function') {
          input.setSelectionRange(cursor, cursor);
        }
      });
    });
  }

  _setupChatFlowObserver() {
    if (!this._chatFlow) return;
    if (this._chatObserver) this._chatObserver.disconnect();
    this._chatObserver = new MutationObserver(() => this._syncEmptyState());
    this._chatObserver.observe(this._chatFlow, { childList: true });
    this._syncEmptyState();
  }

  _syncEmptyState() {
    if (!this._chatFlow || !this._emptyState) return;
    const hasHistory = Array.from(this._chatFlow.children).some((child) => child !== this._emptyState && !child.classList.contains('hidden'));
    this._emptyState.classList.toggle('hidden', hasHistory);
    this._chatFlow.classList.toggle('has-history', hasHistory);
    this._container.classList.toggle('ai-has-history', hasHistory);
  }

  // ══════════════════ Slash Command Menu ══════════════════

  _handleSlashInput(value) {
    if (!value.startsWith('/')) { this._hideSlashMenu(); return; }
    const query = value.slice(1).toLowerCase();
    const ft = (this._currentFileType || this._doc?.getFileType?.() || '').toLowerCase();
    const fileFiltered = SLASH_COMMANDS.filter(c =>
      !c.fileTypes || c.fileTypes.includes(ft)
    );
    this._slashFiltered = fileFiltered.filter(c =>
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
    this._resetInput(input);
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
      if (input) this._resetInput(input);
      this.addMessage(`🧠 深度分析：${this._truncate(userQuery, 60)}`, 'user');
      this._sendViaAgent(userQuery, fullText);
      return;
    }

    // Data → Narrative: generate analysis paragraph AND chart
    if (actionType === 'narrative') {
      let text = '';
      let hasSelection = false;
      let selData = null;
      const _ev2 = window.__koto?.excelViewer;
      if (_ev2 && _ev2.isActive()) {
        const sheetsSelText = _ev2.getSelectionText();
        if (sheetsSelText && sheetsSelText.trim()) {
          text = sheetsSelText;
          hasSelection = true;
        } else {
          text = _ev2.getFullText();
        }
      } else {
        const selection = this._doc.getSelection();
        hasSelection = !!(selection && selection.text && selection.text.trim());
        text = hasSelection ? selection.text : this._getDocFullText();
        selData = hasSelection ? selection : null;
      }
      if (!text.trim()) { this.addMessage('请先选中数据或确保文档有内容。', 'error'); return; }
      this.addMessage(
        hasSelection ? `📝 数据叙述：「${this._truncate(text, 60)}」` : '📝 文档数据叙述',
        'user'
      );
      // Step 1: generate narrative paragraph
      this._sendViaMainAI('narrative', text, selData, '');
      // Step 2: also generate chart (independent, shown below)
      this._sendViaChart(text, '根据以上数据生成最合适的图表');
      return;
    }

    // Chart visualization — uses sandbox endpoint
    if (actionType === 'chart') {
      let text = '';
      let hasSelection = false;
      const _ev = window.__koto?.excelViewer;
      if (_ev && _ev.isActive()) {
        // Excel mode: try to get selected cell range from Univer Sheets canvas first
        const sheetsSelText = _ev.getSelectionText();
        if (sheetsSelText && sheetsSelText.trim()) {
          text = sheetsSelText;
          hasSelection = true;
        } else {
          text = _ev.getFullText();
        }
      } else {
        const selection = this._doc.getSelection();
        hasSelection = !!(selection && selection.text && selection.text.trim());
        text = hasSelection ? selection.text : this._getDocFullText();
      }
      if (!text.trim()) { this.addMessage('请先选中数据或确保文档有内容。', 'error'); return; }
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

    // ── Multi-step Skills (格式统一/审查/术语翻译/会议纪要/清洗数据/填充幻灯片) ──
    const MULTI_STEP_SKILLS = ['format_normalize', 'review_checklist', 'glossary_translate', 'meeting_notes', 'data_clean', 'slide_expand'];
    if (MULTI_STEP_SKILLS.includes(actionType)) {
      const fullText = this._getDocFullText();
      if (!fullText.trim()) { this.addMessage('文档为空，请先打开或输入内容。', 'error'); return; }
      const skillLabels = {
        format_normalize: '🎨 格式统一',
        review_checklist: '📋 文档审查',
        glossary_translate: '📖 术语翻译',
        meeting_notes: '📝 会议纪要',
        data_clean: '🧹 数据清洗',
        slide_expand: '📑 填充幻灯片',
      };
      this.addMessage(skillLabels[actionType] || actionType, 'user');
      this._sendViaMainAI(actionType, fullText, null, '');
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

    // AI Task Engine — dynamic LLM-driven file tasks
    if (actionType === 'ai_task') {
      const input = document.getElementById('ai-input');
      const userTask = (input && input.value.trim()) || '';
      if (input) this._resetInput(input);
      if (!userTask) {
        this.addMessage('请输入你要完成的任务描述，例如「将表格A的数据填入表格B」。', 'system');
        return;
      }
      this.addMessage(`🤖 AI 任务：${this._truncate(userTask, 80)}`, 'user');
      this._sendViaTask(userTask);
      return;
    }

    const selection = this._doc.getSelection();
    const hasSelection = !!(selection && selection.text && selection.text.trim());

    // check: selection or full doc
    if (actionType === 'check') {
      const text = hasSelection ? selection.text : this._getDocFullText();
      if (!text.trim()) { this.addMessage('文档为空，无内容可检查。', 'error'); return; }
      this.addMessage(hasSelection ? `🔍 检查选中：「${this._truncate(text, 60)}」` : '🔍 检查全文', 'user');
      this._sendViaMainAI('check', text, hasSelection ? selection : null, '');
      return;
    }

    // polish / translate / rewrite / annotate require a selection
    const labels = { polish: '✨ 润色', translate: '🌐 翻译', rewrite: '✏️ 改写', annotate: '🔖 标注', check: '🔍 检查' };

    // PPTX 幻灯片形状选中 → 通过 WebSocket 路由（输出 set_pptx_text 工具调用）
    const _pv = window.__koto?.pptxViewer;
    if (_pv && _pv.isActive()) {
      const shapeInfo = _pv.getSelectedShape?.();
      if (shapeInfo && shapeInfo.text.trim()) {
        this.addMessage(
          `${labels[actionType] || actionType}：幻灯片${shapeInfo.slideIndex + 1} 「${this._truncate(shapeInfo.text, 60)}」`,
          'user'
        );
        this._bridge.sendPptxShapeAction(actionType, shapeInfo, this._getDocFullText());
        return;
      }
    }

    if (!selection || !selection.text || !selection.text.trim()) {
      this.addMessage('请先在编辑器中选中要处理的文本。', 'error');
      return;
    }
    this.addMessage(`${labels[actionType] || actionType}：「${this._truncate(selection.text, 80)}」`, 'user');
    this._sendViaMainAI(actionType, selection.text, selection, '');
  }

  _onCustomInput(input) {
    const text = input.value.trim();
    if (!text) return;
    this._resetInput(input);
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

    // Route task-like instructions (file operations, data filling, etc.) to TaskAgent
    const isTask = /^(把|将|帮我把|帮我将|填入|填写|复制|转换|合并|提取|导出|导入|批量|清洗|整理|汇总|对比|生成报告)/.test(text)
      || /(填入|填到|写入|导出到|复制到|转换成|合并到|提取.*到)/.test(text);
    if (isTask) {
      this._sendViaTask(text);
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
        body: JSON.stringify({ data_context: dataContext, instruction, lang: 'python', model_mode: localStorage.getItem('editor_model_mode') || 'cloud' }),
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
      const chartProgressState = { stepElements: {} };

      const processEvent = (ev) => {
        if (!ev.startsWith('data: ')) return;
        let parsed;
        try { parsed = JSON.parse(ev.slice(6)); } catch { return; }

        if (this._consumeTaskProgressEvent(chartProgressState, chartWrap, parsed, { wrapperClass: 'task-progress' })) {
          statusEl.style.display = 'none';
          if (!chartWrap.isConnected) {
            this._chatFlow.appendChild(chartWrap);
          }
          return;
        }

        if (parsed.type === 'status') {
          statusEl.textContent = parsed.text;
        } else if (parsed.type === 'info') {
          this._showInfoBanner(parsed.text || '');
        } else if (parsed.type === 'code') {
          codeText = parsed.text;
          statusEl.style.display = 'none'; // hide status row

          // Build code block with collapsible toggle + edit/rerun
          chartWrap.querySelectorAll('.chart-code-block, .chart-img-wrap, .code-stdout, .code-stderr').forEach(el => el.remove());
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
          if (!chartWrap.isConnected) this._chatFlow.appendChild(chartWrap);
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
          model_mode: localStorage.getItem('editor_model_mode') || 'cloud',
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
      let hasStructuredOutput = false;
      let progressWrap = null;
      let progressSteps = null;
      const stepElements = {};

      const ensureProgressTracker = () => {
        if (progressSteps || !this._chatFlow) return progressSteps;
        progressWrap = document.createElement('div');
        progressWrap.className = 'chat-msg ai task-progress';
        progressSteps = document.createElement('div');
        progressSteps.className = 'task-steps';
        progressWrap.appendChild(progressSteps);
        this._chatFlow.appendChild(progressWrap);
        this._scrollBottom();
        return progressSteps;
      };

      const addProgressStep = (text, cls = '') => {
        const wrap = ensureProgressTracker();
        if (!wrap) return null;
        const el = document.createElement('div');
        el.className = 'task-step' + (cls ? ' ' + cls : '');
        el.textContent = text;
        wrap.appendChild(el);
        this._scrollBottom();
        return el;
      };

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

  _cleanAIText(text, { keepLists = false } = {}) {
    if (!text) return text;
    let cleaned = text
      .replace(/\*\*\*(.+?)\*\*\*/gs, '$1')   // ***bold italic***
      .replace(/\*\*(.+?)\*\*/gs, '$1')         // **bold**
      .replace(/\*([^*\n]+?)\*/g, '$1')          // *italic*
      .replace(/__(.+?)__/gs, '$1')              // __bold__
      .replace(/_([^_\n]+?)_/g, '$1')            // _italic_
      .replace(/^#{1,6}\s+/gm, '')               // ## Heading
      .replace(/^[\-\*=]{3,}\s*$/gm, '')         // --- / *** dividers
      .replace(/`{1,3}([^`]*)`{1,3}/g, '$1')     // `inline code` / ```code```
      .replace(/^\s*[\*_]+\s*$/gm, '')           // lone * or _ lines
      .replace(/\*{1,3}/g, '')                   // any remaining stray asterisks
      .replace(/\n{3,}/g, '\n\n');               // collapse excess blank lines
    if (!keepLists) {
      cleaned = cleaned
        .replace(/^\s*[\*\-\+]\s+/gm, '')          // * bullet / - bullet / + bullet list items
        .replace(/^\s*\d+\.\s+/gm, '');             // 1. numbered list items
    }
    return cleaned.trim();
  }

  /**
   * Strip common AI preamble/epilogue lines from polish/translate/rewrite results.
   * AI sometimes adds lines like "以下是润色后的文本：" or "---" before the actual output.
   */
  _stripAIPreamble(text) {
    if (!text) return text;
    return text
      .replace(/^(以下|下面|这是|如下)(是|为)?.{0,20}(润色|翻译|改写|修改|修正|优化|版本|结果|文本|内容).{0,10}[：:]\s*/i, '')
      .replace(/[\n\r]+[-—]{2,}\s*$/g, '')       // trailing --- dividers
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
      const progressState = { stepElements: {} };
      let hasStructuredProgress = false;

      const processLine = (line) => {
        if (!line.startsWith('data: ')) return;
        let parsed;
        try { parsed = JSON.parse(line.slice(6)); } catch { return; }
        if (this._consumeTaskProgressEvent(progressState, this._chatFlow, parsed)) {
          if (!hasStructuredProgress) {
            hasStructuredProgress = true;
            this.removeTyping();
          }
          this._chatFlow.querySelectorAll('.agent-status-msg').forEach(el => el.remove());
        } else if (parsed.type === 'status') {
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

  // ══════════════════ AI Task Engine (SSE) ══════════════════

  async _sendViaTask(taskDescription) {
    if (this._abortController) this._abortController.abort();
    this._abortController = new AbortController();
    this.expand();
    this._setAbortBtnVisible(true);

    // Build file context from current open file
    const files = [];
    const currentPath = this._fileId || '';
    if (currentPath) {
      const ext = this._currentFileType || currentPath.split('.').pop()?.toLowerCase() || '';
      const preview = this._getDocFullText()?.slice(0, 2000) || '';
      files.push({
        path: currentPath,
        name: currentPath.split(/[/\\]/).pop(),
        type: ext,
        content_preview: preview,
      });
    }

    const progressState = this._ensureTaskProgressState({ stepElements: {} }, this._chatFlow);
    this._updateTaskProgressSummary(progressState, '连接 AI 任务引擎', 5, 'step');
    this._appendTaskProgressStep(progressState, this._chatFlow, '🔗 连接 AI 任务引擎…');

    try {
      const _fileType = this._doc?.getFileType?.() || this._currentFileType || '';
      const _fileName = this._doc?.getFileName?.() || '';
      const _modelMode = localStorage.getItem('editor_model_mode') || 'cloud';
      const resp = await fetch('/api/editor/ai/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          action: 'ai_task',
          instruction: taskDescription,
          full_text: this._getDocFullText() || '',
          file_type: _fileType,
          file_name: _fileName,
          files,
          history: this._history.slice(-10),
          session_id: this._fileId ? 'editor_' + this._fileId : '',
          model_mode: _modelMode,
          model_id: _modelMode === 'local' ? '' : (localStorage.getItem('editor_locked_model') || ''),
        }),
        signal: this._abortController.signal,
      });

      if (!resp.ok) {
        this._finalizeTaskProgressState(progressState, `服务器错误 (${resp.status})`, 'error');
        this._appendTaskProgressStep(progressState, this._chatFlow, `❌ 服务器错误 (${resp.status})`, 'error');
        return;
      }

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';
      let resultText = '';

      const handleEvent = (raw) => {
        if (!raw.startsWith('data: ')) return;
        let ev;
        try { ev = JSON.parse(raw.slice(6)); } catch { return; }

        if (this._consumeTaskProgressEvent(progressState, this._chatFlow, ev)) {
          return;
        }

        switch (ev.type) {
          case 'status':
          case 'info':
            this._appendTaskProgressStep(progressState, this._chatFlow, `ℹ️ ${ev.text}`, 'dim');
            break;
          case 'file_change':
            this._applyTaskFilePreview(ev);
            break;
          case 'result':
            resultText = ev.data || '';
            if (ev.output_type === 'markdown' && resultText) {
              // Render final result as a new AI message
              this.removeTyping();
              const resultEl = document.createElement('div');
              resultEl.className = 'chat-msg ai';
              resultEl.innerHTML = this._renderMarkdown ? this._renderMarkdown(resultText) : resultText;
              this._chatFlow.appendChild(resultEl);
              this._scrollBottom();
            }
            break;
          case 'error':
            this._finalizeTaskProgressState(progressState, ev.text || '执行失败', 'error');
            this._appendTaskProgressStep(progressState, this._chatFlow, `❌ ${ev.text}`, 'error');
            break;
          case 'done':
            this._finalizeTaskProgressState(progressState, ev.summary || '完成');
            this._appendTaskProgressStep(progressState, this._chatFlow, `🎉 ${ev.summary || '完成'}`, 'done');
            break;
        }
      };

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const parts = buf.split('\n\n');
        buf = parts.pop();
        for (const p of parts) handleEvent(p);
      }
      if (buf) handleEvent(buf);

    } catch (err) {
      if (err.name === 'AbortError') return;
      this._finalizeTaskProgressState(progressState, err.message || '执行失败', 'error');
      this._appendTaskProgressStep(progressState, this._chatFlow, `❌ ${err.message}`, 'error');
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
    const _fileType = this._doc?.getFileType?.() || '';
    const _fileName = this._doc?.getFileName?.() || '';
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
          selection_offset: selectionCtx?.range?.startOffset ?? -1,
          doc_context: this._docContext || '',
          doc_mode: this._docMode || 'normal',
          model_mode: localStorage.getItem('editor_model_mode') || 'cloud',
          file_type: _fileType,
          file_name: _fileName,
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
      let hasStructuredOutput = false;
      let hasStructuredProgress = false;
      const progressState = { stepElements: {} };

      const processLine = (line) => {
        if (!line.startsWith('data: ')) return;
        let parsed;
        try { parsed = JSON.parse(line.slice(6)); } catch { return; }
        if (parsed.type === 'info') {
          this._showInfoBanner(parsed.text || '');
        } else if (this._consumeTaskProgressEvent(progressState, this._chatFlow, parsed)) {
          if (!hasStructuredProgress) {
            hasStructuredProgress = true;
            this.removeTyping();
          }
        } else if (parsed.type === 'token') {
          this.removeTyping();
          if (actionType !== 'glossary_translate') {
            this.appendStreamChunk(parsed.text || '');
          }
          fullText += parsed.text || '';
        } else if (parsed.type === 'proposals') {
          this.removeTyping();
          hasStructuredOutput = true;
          this.showProposals(parsed.proposals || [], parsed.summary || '', selectionCtx);
        } else if (parsed.type === 'doc_tool_call') {
          this.removeTyping();
          hasStructuredOutput = true;
          this.handleDocToolCall(parsed);
        } else if (parsed.type === 'skill_suggestions') {
          const suggs = parsed.suggestions || [];
          if (suggs.length) this.showSkillSuggestions(suggs);
        } else if (parsed.type === 'done') {
          if (hasStructuredProgress) {
            this._finalizeTaskProgressState(progressState, parsed.summary || '执行完成');
          }
          if (parsed.result) {
            fullText = parsed.result;
            if (this._streamingEl) this._streamingEl.textContent = parsed.result;
          }
          if (!fullText.trim() && !hasStructuredOutput) {
            this.removeTyping();
            if (this._streamingEl) {
              this._streamingEl.classList.remove('streaming');
              this._streamingEl.remove();
              this._streamingEl = null;
            }
            this.addMessage('⚠ AI 未返回有效内容，请重新选中文本后再试。', 'error');
            return;
          }
          if (actionType === 'glossary_translate') {
            const m = fullText.match(/TERM_TABLE_BEGIN\s*([\s\S]*?)\s*TERM_TABLE_END/);
            if (m) {
              try {
                const terms = JSON.parse(m[1].trim());
                if (this._streamingEl) {
                  this._streamingEl.classList.remove('streaming');
                  this._streamingEl.remove();
                  this._streamingEl = null;
                }
                this._showGlossaryApprovalCard(terms);
                return;
              } catch { /* malformed JSON — fall through to normal display */ }
            }
          }
          if (fullText) this._history.push({ role: 'assistant', content: fullText });
          if (this._streamingEl) this.finalizeStreamMessage(fullText, actionType, selectionCtx);
        } else if (parsed.type === 'error') {
          if (hasStructuredProgress) {
            this._finalizeTaskProgressState(progressState, parsed.text || '未知错误', 'error');
          }
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
        this.removeProgressMessages();
        if (this._streamingEl) {
          this._streamingEl.classList.remove('streaming');
          this._streamingEl.textContent += '\n[已取消]';
          this._streamingEl = null;
        }
        return;
      }
      this.removeTyping();
      this.removeProgressMessages();
      if (this._streamingEl) { this._streamingEl.classList.remove('streaming'); this._streamingEl = null; }
      this.addMessage(`❌ ${err.message}`, 'error');
    } finally {
      this._abortController = null;
      this._setAbortBtnVisible(false);
    }
  }

  // ══════════════════ Skill Suggestions ══════════════════

  /**
   * Render a row of skill-suggestion chips after the current AI response.
   * Clicking a chip sends a follow-up request that signals to the pipeline
   * to inject that skill's prompt.
   * @param {Array<{id:string, name:string, icon:string, description:string}>} suggestions
   */
  showSkillSuggestions(suggestions) {
    if (!suggestions || suggestions.length === 0) return;
    if (!this._chatFlow) return;

    // Separate executor skills (have their own panel) from prompt-only skills
    const execSkills = suggestions.filter(s => s.has_executor);
    const promptSkills = suggestions.filter(s => !s.has_executor);

    // Workflow/executor skills → rich recommend card via showSkillRecommend
    execSkills.forEach(s => this.showSkillRecommend(s));

    // Prompt-only skills → simple chip bar (existing behavior, kept for those)
    if (!promptSkills.length) return;

    const wrap = document.createElement('div');
    wrap.className = 'ai-skill-suggestions';

    const label = document.createElement('span');
    label.className = 'ai-skill-suggestions-label';
    label.textContent = '🔧 推荐技能';
    wrap.appendChild(label);

    promptSkills.forEach(s => {
      const chip = document.createElement('button');
      chip.className = 'ai-skill-chip';
      chip.title = s.description || '';
      chip.textContent = (s.icon ? s.icon + ' ' : '') + (s.name || s.id);
      chip.addEventListener('click', () => {
        wrap.remove();
        const msgText = `请使用「${s.name || s.id}」技能继续处理当前内容`;
        this.addMessage(msgText, 'user');
        this._history.push({ role: 'user', content: msgText });
        if (this._history.length > 20) this._history = this._history.slice(-20);
        this._sendViaMainAI('custom_instruction', this._getDocFullText() || '', null, msgText);
      });
      wrap.appendChild(chip);
    });

    const dismissBtn = document.createElement('button');
    dismissBtn.className = 'ai-skill-chip dismiss';
    dismissBtn.textContent = '✕';
    dismissBtn.title = '关闭建议';
    dismissBtn.addEventListener('click', () => wrap.remove());
    wrap.appendChild(dismissBtn);

    this._chatFlow.appendChild(wrap);
    this._scrollBottom();
  }

  // ══════════════════ Public API ══════════════════

  updateStatus(text, type) {
    const el = document.getElementById('conn-status');
    if (el) { el.textContent = text; el.className = 'conn-status ' + type; }
  }

  _syncModelBadge() {
    const badge = document.getElementById('ai-model-badge');
    if (!badge) return;
    const isLocal = (localStorage.getItem('editor_model_mode') || 'cloud') === 'local';
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

  _applyTaskFilePreview(ev) {
    const preview = this._cleanAIText(ev?.preview || '', { keepLists: true });
    if (!preview) return false;

    const docxViewer = window.__koto?.docxViewer;
    if (docxViewer?.isActive?.()) {
      return !!docxViewer.setLiveText(preview, {
        append: false,
        label: ev?.summary || 'AI 实时预览',
      });
    }

    if (this._doc?.loadContent) {
      this._doc.loadContent(preview);
      return true;
    }

    return false;
  }

  _buildApplyButtons(text, actionType, ctx, msgEl) {
    const btns = [];
    // Clean markdown artifacts before any injection into the document
    // For check action, keep numbered lists intact; for polish/translate/rewrite, strip AI preamble
    const PREAMBLE_ACTIONS = new Set(['polish', 'translate', 'rewrite']);
    const keepLists = (actionType === 'check');
    let clean = this._cleanAIText(text, { keepLists });
    if (PREAMBLE_ACTIONS.has(actionType)) clean = this._stripAIPreamble(clean);
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

      // Re-edit button — show inline input for additional instruction, then re-generate
      const reEditBtn = document.createElement('button');
      reEditBtn.className = 'msg-action-btn secondary diff-reedit-btn';
      reEditBtn.textContent = '✏️ 再修改';
      reEditBtn.addEventListener('click', () => {
        // Toggle inline edit input
        let editRow = msgEl?.querySelector('.ai-reedit-row');
        if (editRow) { editRow.remove(); return; }
        editRow = document.createElement('div');
        editRow.className = 'ai-reedit-row';
        const inp = document.createElement('input');
        inp.type = 'text';
        inp.className = 'ai-reedit-input';
        inp.placeholder = '输入修改要求，如"更正式"、"更简洁"…';
        const sendBtn = document.createElement('button');
        sendBtn.className = 'msg-action-btn ai-reedit-send';
        sendBtn.textContent = '发送';
        sendBtn.addEventListener('click', () => {
          const extra = inp.value.trim();
          if (msgEl) msgEl.remove();
          if (ctx?.text) {
            const labels = { polish: '✨ 润色', translate: '🌐 翻译', rewrite: '✏️ 改写', check: '🔍 检查' };
            this.addMessage(`${labels[actionType] || actionType}（再修改）：「${this._truncate(ctx.text, 60)}」`, 'user');
            this._sendViaMainAI(actionType, ctx.text, ctx, extra || '');
          }
        });
        inp.addEventListener('keydown', (e) => { if (e.key === 'Enter') sendBtn.click(); });
        editRow.appendChild(inp);
        editRow.appendChild(sendBtn);
        const bar = reEditBtn.closest('.msg-action-bar');
        if (bar && bar.parentElement) bar.parentElement.insertBefore(editRow, bar.nextSibling);
        else msgEl?.appendChild(editRow);
        inp.focus();
      });
      btns.push(reEditBtn);

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

  // ══════════════════ PhaseTracker (阶段进度条) ══════════════════

  /**
   * Update the PhaseTracker stepper UI.
   * Called by SocketBridge._handlePhase (WebSocket) or SSE processLine (HTTP).
   *
   * @param {{ phases: {id:string,label:string}[], current: string, status: 'running'|'done' }} data
   */
  updatePhase(data) {
    if (!this._chatFlow) return;
    this._socketTaskProgress = this._socketTaskProgress || { stepElements: {} };
    this._consumeTaskProgressEvent(this._socketTaskProgress, this._chatFlow, {
      type: 'phase',
      phases: data?.phases || [],
      current: data?.current || '',
      status: data?.status || 'running',
    });
  }

  /** Remove the PhaseTracker element. */
  removePhaseTracker() {
    if (!this._chatFlow) return;
    this._chatFlow.querySelectorAll('.phase-tracker').forEach(el => el.remove());
  }

  _ensureTaskProgressState(state, host, options = {}) {
    const current = state || {};
    if (current.wrap && current.steps && current.wrap.isConnected && current.labelEl && current.percentEl && current.barFill) {
      current.meta = this._ensureTaskProgressMeta(current);
      return current;
    }

    const wrap = document.createElement('div');
    wrap.className = options.wrapperClass || 'chat-msg ai task-progress';

    const header = document.createElement('div');
    header.className = options.headerClass || 'task-progress-header';

    const labelEl = document.createElement('div');
    labelEl.className = options.labelClass || 'task-progress-label';
    header.appendChild(labelEl);

    const percentEl = document.createElement('div');
    percentEl.className = options.percentClass || 'task-progress-percent';
    header.appendChild(percentEl);

    const bar = document.createElement('div');
    bar.className = options.barClass || 'task-progress-bar';

    const barFill = document.createElement('div');
    barFill.className = options.barFillClass || 'task-progress-bar-fill';
    bar.appendChild(barFill);

    const steps = document.createElement('div');
    steps.className = options.stepsClass || 'task-steps';
    wrap.appendChild(header);
    wrap.appendChild(bar);
    wrap.appendChild(steps);

    host.appendChild(wrap);

    current.wrap = wrap;
    current.header = header;
    current.labelEl = labelEl;
    current.percentEl = percentEl;
    current.bar = bar;
    current.barFill = barFill;
    current.steps = steps;
    current.stepElements = current.stepElements || {};
    current.meta = this._ensureTaskProgressMeta(current);
    this._updateTaskProgressSummary(current, options.initialLabel || '准备执行', 0, 'step', 0, 0, options);
    this._scrollBottom();
    return current;
  }

  _ensureTaskProgressMeta(state) {
    const current = state || {};
    current.meta = current.meta || {};
    current.meta.stepOrder = current.meta.stepOrder || new Map();
    current.meta.totalSteps = current.meta.totalSteps || 0;
    current.meta.currentStepIndex = current.meta.currentStepIndex || 0;
    current.meta.currentStepLabel = current.meta.currentStepLabel || '';
    current.meta.phaseIndex = current.meta.phaseIndex || new Map();
    current.meta.totalPhases = current.meta.totalPhases || 0;
    current.meta.currentPhaseIndex = current.meta.currentPhaseIndex || 0;
    current.meta.currentPhaseLabel = current.meta.currentPhaseLabel || '';
    current.meta.percent = current.meta.percent || 0;
    current.meta.source = current.meta.source || 'step';
    return current.meta;
  }

  _getTaskProgressKey(keyMap, rawKey, fallbackLabel = '') {
    return String(rawKey || '').trim() || fallbackLabel || `step_${keyMap.size + 1}`;
  }

  _ensureTaskProgressStepIndex(state, rawKey, fallbackLabel = '') {
    const meta = this._ensureTaskProgressMeta(state);
    const key = this._getTaskProgressKey(meta.stepOrder, rawKey, fallbackLabel);
    if (meta.stepOrder.has(key)) return { key, index: meta.stepOrder.get(key) };
    const nextIdx = meta.stepOrder.size + 1;
    meta.stepOrder.set(key, nextIdx);
    meta.totalSteps = Math.max(meta.totalSteps, nextIdx);
    return { key, index: nextIdx };
  }

  _getTaskProgressFraction(milestone = 'step_progress') {
    const fractions = {
      phase_running: 0.5,
      phase_done: 1,
      step_start: 0.35,
      tool_call: 0.5,
      step_progress: 0.7,
      tool_result: 0.85,
      step_done: 1,
      step_error: 1,
    };
    return fractions[milestone] ?? 0;
  }

  _computeTaskProgressPercent(index, total, milestone = 'step_progress') {
    const safeTotal = Math.max(Number(total) || 0, Number(index) || 0, 1);
    const safeIndex = Math.min(Math.max(Number(index) || 1, 1), safeTotal);
    const fraction = this._getTaskProgressFraction(milestone);
    const percent = Math.round((((safeIndex - 1) + fraction) / safeTotal) * 100);
    return Math.max(0, Math.min(100, percent));
  }

  _formatTaskProgressLabel(label, source = 'step', index = 0, total = 0) {
    const clean = String(label || '').trim();
    if (!clean) return source === 'phase' ? '执行中' : '处理中';
    if (index > 0 && total > 0) {
      const prefix = source === 'phase' ? '阶段' : '步骤';
      return `${prefix} ${index}/${total} · ${clean}`;
    }
    return clean;
  }

  _updateTaskProgressSummary(state, label, percent, source = 'step', index = 0, total = 0, options = {}) {
    if (!state || !state.wrap) return;
    const meta = this._ensureTaskProgressMeta(state);
    const safePercent = Math.max(0, Math.min(100, Math.round(percent || 0)));
    meta.percent = safePercent;
    meta.source = source;
    if (source === 'phase') {
      meta.currentPhaseIndex = index || meta.currentPhaseIndex || 0;
      meta.currentPhaseLabel = label || meta.currentPhaseLabel || '';
      meta.totalPhases = total || meta.totalPhases || 0;
    } else {
      meta.currentStepIndex = index || meta.currentStepIndex || 0;
      meta.currentStepLabel = label || meta.currentStepLabel || '';
      meta.totalSteps = total || meta.totalSteps || 0;
    }
    if (state.labelEl) state.labelEl.textContent = this._formatTaskProgressLabel(label, source, index, total);
    if (state.percentEl) state.percentEl.textContent = `${safePercent}%`;
    if (state.barFill) state.barFill.style.width = `${safePercent}%`;
    if (state.wrap) {
      state.wrap.dataset.progressSource = source;
      if (options.progressState) state.wrap.dataset.state = options.progressState;
    }
  }

  _finalizeTaskProgressState(state, summary = '', status = 'done') {
    if (!state || !state.wrap) return;
    const meta = this._ensureTaskProgressMeta(state);
    const source = meta.totalPhases > 0 ? 'phase' : 'step';
    const total = source === 'phase' ? meta.totalPhases : meta.totalSteps;
    const currentIndex = source === 'phase'
      ? (meta.currentPhaseIndex || total || 0)
      : (meta.currentStepIndex || total || 0);
    const fallbackLabel = source === 'phase' ? meta.currentPhaseLabel : meta.currentStepLabel;
    const label = summary || fallbackLabel || (status === 'error' ? '执行失败' : '执行完成');
    const percent = status === 'error' && total > 0 && currentIndex > 0
      ? this._computeTaskProgressPercent(currentIndex, total, 'step_error')
      : 100;
    this._updateTaskProgressSummary(state, label, percent, source, currentIndex, total, { progressState: status });
    state.wrap.dataset.state = status;
  }

  _appendTaskProgressStep(state, host, text, cls = '', options = {}) {
    const current = this._ensureTaskProgressState(state, host, options);
    const el = document.createElement('div');
    const baseClass = options.stepClass || 'task-step';
    el.className = baseClass + (cls ? ' ' + cls : '');
    el.textContent = text;
    current.steps.appendChild(el);
    this._scrollBottom();
    return el;
  }

  _consumeTaskProgressEvent(state, host, parsed, options = {}) {
    if (!parsed || !parsed.type) return false;
    let current = state || {};
    const ensureCurrent = () => {
      current = this._ensureTaskProgressState(current, host, options);
      current.stepElements = current.stepElements || {};
      return current;
    };

    switch (parsed.type) {
      case 'phase': {
        const currentState = ensureCurrent();
        const meta = this._ensureTaskProgressMeta(currentState);
        const phases = Array.isArray(parsed.phases) ? parsed.phases : [];
        meta.phaseIndex = new Map();
        phases.forEach((phase, idx) => {
          meta.phaseIndex.set(String(phase.id || phase.label || idx + 1), {
            index: idx + 1,
            label: phase.label || phase.id || `阶段 ${idx + 1}`,
          });
        });
        meta.totalPhases = phases.length;
        const currentKey = String(parsed.current || '').trim();
        const currentPhase = meta.phaseIndex.get(currentKey);
        const phaseIndex = currentPhase?.index || meta.currentPhaseIndex || (meta.totalPhases > 0 ? 1 : 0);
        const phaseLabel = currentPhase?.label || parsed.text || parsed.label || currentKey || '执行中';
        meta.currentPhaseIndex = phaseIndex;
        meta.currentPhaseLabel = phaseLabel;
        const percent = meta.totalPhases > 0 && phaseIndex > 0
          ? this._computeTaskProgressPercent(phaseIndex, meta.totalPhases, parsed.status === 'done' ? 'phase_done' : 'phase_running')
          : meta.percent || 0;
        this._updateTaskProgressSummary(currentState, phaseLabel, percent, 'phase', phaseIndex, meta.totalPhases, {
          ...options,
          progressState: parsed.status === 'done' && phaseIndex === meta.totalPhases ? 'done' : 'running',
        });
        return true;
      }
      case 'plan': {
        const currentState = ensureCurrent();
        const meta = this._ensureTaskProgressMeta(currentState);
        meta.stepOrder.clear();
        meta.currentStepIndex = 0;
        meta.currentStepLabel = '';
        meta.totalSteps = (parsed.steps || []).length;
        (parsed.steps || []).forEach((step, idx) => {
          const stepKey = this._getTaskProgressKey(
            meta.stepOrder,
            step.id || step.step_id || step.step,
            step.description || step.label || step.text || `步骤 ${idx + 1}`,
          );
          meta.stepOrder.set(stepKey, idx + 1);
        });
        if (!meta.totalPhases) {
          this._updateTaskProgressSummary(currentState, options.planLabel || '规划执行', 0, 'step', 0, meta.totalSteps, options);
        }
        this._appendTaskProgressStep(current, host, options.planTitle || '📋 执行计划：', 'dim', options);
        (parsed.steps || []).forEach((step, idx) => {
          const label = step.description || step.label || step.text || step.id || `步骤 ${idx + 1}`;
          this._appendTaskProgressStep(current, host, `${idx + 1}. ${label}`, 'dim', options);
        });
        return true;
      }
      case 'plan_summary': {
        ensureCurrent();
        const text = parsed.text || parsed.summary || '';
        if (text) this._appendTaskProgressStep(current, host, `📋 ${text}`, 'dim', options);
        return true;
      }
      case 'thought': {
        ensureCurrent();
        const text = parsed.text || '';
        if (text) this._appendTaskProgressStep(current, host, `💭 ${text}`, 'dim', options);
        return true;
      }
      case 'step_start': {
        const currentState = ensureCurrent();
        const stepElements = currentState.stepElements;
        const label = parsed.text || parsed.label || parsed.step_id || parsed.step || '执行中';
        const { key, index } = this._ensureTaskProgressStepIndex(currentState, parsed.step_id || parsed.step, label);
        const meta = this._ensureTaskProgressMeta(currentState);
        meta.currentStepIndex = index;
        meta.currentStepLabel = label;
        if (!meta.totalPhases) {
          this._updateTaskProgressSummary(currentState, label, this._computeTaskProgressPercent(index, meta.totalSteps || index, 'step_start'), 'step', index, meta.totalSteps || index, options);
        }
        stepElements[key] = this._appendTaskProgressStep(current, host, `⚙️ ${label}…`, '', options);
        return true;
      }
      case 'step_progress': {
        const currentState = ensureCurrent();
        const stepElements = currentState.stepElements;
        const detail = parsed.detail || parsed.text || '处理中';
        const { key, index } = this._ensureTaskProgressStepIndex(currentState, parsed.step_id || parsed.step, detail);
        const meta = this._ensureTaskProgressMeta(currentState);
        meta.currentStepIndex = index;
        meta.currentStepLabel = meta.currentStepLabel || detail;
        if (!meta.totalPhases) {
          this._updateTaskProgressSummary(currentState, meta.currentStepLabel || detail, this._computeTaskProgressPercent(index, meta.totalSteps || index, 'step_progress'), 'step', index, meta.totalSteps || index, options);
        }
        if (stepElements[key]) {
          stepElements[key].textContent = `⚙️ ${detail}`;
        } else {
          stepElements[key] = this._appendTaskProgressStep(current, host, `⚙️ ${detail}`, '', options);
        }
        return true;
      }
      case 'step_done': {
        const currentState = ensureCurrent();
        const stepElements = currentState.stepElements;
        const label = parsed.text || parsed.label || parsed.step_id || parsed.step || '步骤完成';
        const { key, index } = this._ensureTaskProgressStepIndex(currentState, parsed.step_id || parsed.step, label);
        const meta = this._ensureTaskProgressMeta(currentState);
        meta.currentStepIndex = index;
        meta.currentStepLabel = label;
        if (!meta.totalPhases) {
          const total = meta.totalSteps || index;
          const isFinal = index >= total;
          this._updateTaskProgressSummary(currentState, label, this._computeTaskProgressPercent(index, total, 'step_done'), 'step', index, total, {
            ...options,
            progressState: isFinal ? 'done' : 'running',
          });
        }
        if (stepElements[key]) {
          stepElements[key].textContent = `✅ ${label}`;
          stepElements[key].classList.remove('error');
          stepElements[key].classList.add('done');
        } else {
          this._appendTaskProgressStep(current, host, `✅ ${label}`, 'done', options);
        }
        return true;
      }
      case 'step_error': {
        const currentState = ensureCurrent();
        const stepElements = currentState.stepElements;
        const err = parsed.error || parsed.text || '步骤失败';
        const { key, index } = this._ensureTaskProgressStepIndex(currentState, parsed.step_id || parsed.step, err);
        const meta = this._ensureTaskProgressMeta(currentState);
        meta.currentStepIndex = index;
        if (!meta.totalPhases) {
          this._updateTaskProgressSummary(currentState, err, this._computeTaskProgressPercent(index, meta.totalSteps || index, 'step_error'), 'step', index, meta.totalSteps || index, {
            ...options,
            progressState: 'error',
          });
        }
        if (stepElements[key]) {
          stepElements[key].textContent = `❌ ${err}`;
          stepElements[key].classList.add('error');
        } else {
          this._appendTaskProgressStep(current, host, `❌ ${err}`, 'error', options);
        }
        return true;
      }
      case 'tool_call': {
        const currentState = ensureCurrent();
        const label = parsed.tool_name || '工具调用';
        const argNames = Object.keys(parsed.tool_args || {});
        const suffix = argNames.length ? ` (${argNames.join(', ')})` : '';
        const meta = this._ensureTaskProgressMeta(currentState);
        if (!meta.totalPhases && meta.currentStepIndex > 0) {
          const total = meta.totalSteps || meta.currentStepIndex;
          this._updateTaskProgressSummary(currentState, meta.currentStepLabel || label, this._computeTaskProgressPercent(meta.currentStepIndex, total, 'tool_call'), 'step', meta.currentStepIndex, total, options);
        }
        this._appendTaskProgressStep(current, host, `🔧 ${label}${suffix}`, 'dim', options);
        return true;
      }
      case 'tool_result': {
        const currentState = ensureCurrent();
        const preview = (parsed.result_preview || '').trim();
        const label = parsed.tool_name || '工具结果';
        const meta = this._ensureTaskProgressMeta(currentState);
        if (!meta.totalPhases && meta.currentStepIndex > 0) {
          const total = meta.totalSteps || meta.currentStepIndex;
          this._updateTaskProgressSummary(currentState, meta.currentStepLabel || label, this._computeTaskProgressPercent(meta.currentStepIndex, total, 'tool_result'), 'step', meta.currentStepIndex, total, options);
        }
        this._appendTaskProgressStep(current, host, preview ? `✅ ${label}: ${preview}` : `✅ ${label}`, 'dim', options);
        return true;
      }
      case 'progress': {
        const currentState = ensureCurrent();
        const meta = this._ensureTaskProgressMeta(currentState);
        const currentIndex = Number(parsed.current) || meta.currentStepIndex || 0;
        const total = Number(parsed.total) || meta.totalSteps || currentIndex;
        const detail = parsed.detail || parsed.text || '处理中';
        if (!meta.totalPhases && currentIndex > 0 && total > 0) {
          meta.currentStepIndex = currentIndex;
          meta.totalSteps = total;
          meta.currentStepLabel = detail;
          this._updateTaskProgressSummary(currentState, detail, Math.round((currentIndex / total) * 100), 'step', currentIndex, total, options);
        }
        this._appendTaskProgressStep(current, host, total ? `${detail} (${currentIndex}/${total})` : detail, 'dim', options);
        return true;
      }
      case 'rag_info': {
        ensureCurrent();
        const total = parsed.total_chunks || 0;
        const retrieved = parsed.retrieved_chunks || 0;
        if (total > 0 && retrieved > 0) {
          this._appendTaskProgressStep(current, host, `📚 已检索 ${retrieved}/${total} 个相关文档片段`, 'dim', options);
        }
        return true;
      }
      default:
        return false;
    }
  }

  handleAgentEvent(payload) {
    if (!payload || !this._chatFlow) return;
    this._socketTaskProgress = this._socketTaskProgress || { stepElements: {} };
    if (this._consumeTaskProgressEvent(this._socketTaskProgress, this._chatFlow, payload)) {
      return;
    }
    if (payload.type === 'status' && payload.text) {
      this.showProgressMessage(payload.text);
    }
  }

  finishAgentEventLog() {
    this._socketTaskProgress = null;
  }

  /**
   * Show an editable glossary approval card after phase-1 of glossary_translate.
   * terms: [{orig, trans, n}, ...]
   */
  _showGlossaryApprovalCard(terms) {
    if (!this._chatFlow) return;

    // Make a mutable copy so edits are tracked per-row
    const editableTerms = terms.map(t => ({ orig: t.orig || t.original || '', trans: t.trans || t.translation || '', n: t.n || t.count || 0 }));

    const card = document.createElement('div');
    card.className = 'chat-msg ai approval-card';

    const header = document.createElement('div');
    header.className = 'approval-header';
    header.innerHTML = '📖 <strong>已提取到术语表</strong>（共 ' + editableTerms.length + ' 条）— 请检查并编辑译文，然后点击「开始翻译全文」：';
    card.appendChild(header);

    // Editable table
    const table = document.createElement('table');
    table.className = 'glossary-table';
    const thead = document.createElement('thead');
    thead.innerHTML = '<tr><th>原文术语</th><th>建议译文（可编辑）</th><th>次数</th></tr>';
    table.appendChild(thead);
    const tbody = document.createElement('tbody');
    editableTerms.forEach((t, i) => {
      const tr = document.createElement('tr');
      const tdOrig = document.createElement('td');
      tdOrig.textContent = t.orig;
      const tdTrans = document.createElement('td');
      const inp = document.createElement('input');
      inp.type = 'text';
      inp.value = t.trans;
      inp.className = 'glossary-input';
      inp.addEventListener('input', () => { editableTerms[i].trans = inp.value; });
      tdTrans.appendChild(inp);
      const tdN = document.createElement('td');
      tdN.className = 'glossary-count';
      tdN.textContent = t.n > 0 ? t.n : '-';
      tr.appendChild(tdOrig); tr.appendChild(tdTrans); tr.appendChild(tdN);
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    card.appendChild(table);

    // Action buttons
    const bar = document.createElement('div');
    bar.className = 'approval-bar';

    const translateBtn = document.createElement('button');
    translateBtn.className = 'msg-action-btn';
    translateBtn.textContent = '🌐 开始翻译全文';
    translateBtn.addEventListener('click', () => {
      const confirmed = editableTerms.map(t => ({ orig: t.orig, trans: t.trans }));
      translateBtn.disabled = true;
      cancelBtn.disabled = true;
      translateBtn.textContent = '正在翻译…';
      this._sendViaMainAI('glossary_translate_exec', '', null, JSON.stringify(confirmed));
    });

    const cancelBtn = document.createElement('button');
    cancelBtn.className = 'msg-action-btn secondary';
    cancelBtn.textContent = '✕ 取消';
    cancelBtn.addEventListener('click', () => {
      card.remove();
      this.addMessage('已取消术语翻译。', 'system');
    });

    bar.appendChild(translateBtn);
    bar.appendChild(cancelBtn);
    card.appendChild(bar);

    this._chatFlow.appendChild(card);
    this._scrollBottom();
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
    const abortBtn = document.getElementById('btn-abort');
    const sendBtn  = document.getElementById('btn-send');
    if (abortBtn) abortBtn.classList.toggle('hidden', !visible);
    if (sendBtn)  sendBtn.classList.toggle('hidden', visible);
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
    // Refresh file type tracking when a new document is opened
    this._currentFileType = (this._doc?.getFileType?.() || '').toLowerCase();
    this._history = [];
    this._docContext = '';
    if (this._chatFlow) {
      this._chatFlow.querySelectorAll('.chat-hist-sep, .chat-hist-item, .doc-context-chip').forEach(el => el.remove());
    }
    // Reload skill bar for the new file type
    if (this._skillBar) {
      this._skillBar.innerHTML = '';
      this._skillBar.style.display = '';
    }
    this._loadSkillBar();
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

  // ══════════════════ Skill Library Panel ══════════════════

  // File-type → relevant skill id prefixes/tags (mirrors backend _FILE_TYPE_SKILL_AFFINITY)
  static _FILE_TYPE_AFFINITY = {
    docx: ['doc_', 'writing_assistant', 'annotate_', 'legal_doc_review', 'academic_paper_polish', 'marketing_copy', 'email_writer', 'meeting_notes', 'report_writer'],
    pdf:  ['doc_', 'doc_qa', 'doc_summarizer', 'annotate_', 'legal_doc_review', 'financial_doc_review'],
    xlsx: ['excel_', 'pivot_advisor', 'data_analysis', 'data_visualizer', 'spreadsheet_analyst'],
    csv:  ['excel_', 'data_analysis', 'data_visualizer', 'data_clean'],
    pptx: ['slide_', 'ppt_outline', 'ppt_generator_pro', 'presentation_outline'],
  };

  // Category display names
  static _CATEGORY_LABELS = {
    all: '全部',
    recommend: '📌 推荐',
    behavior: '⚙️ 行为',
    style: '🎨  风格',
    domain: '🔬 领域',
    workflow: '🔄 工作流',
    memory: '🧠 记忆',
    custom: '🛠 自定义',
  };

  /** Toggle the skill library overlay on/off. */
  _toggleSkillLibrary() {
    let lib = this._container.querySelector('.ai-skill-library');
    if (lib) {
      lib.remove();
      return;
    }
    this._renderSkillLibrary();
  }

  /** Build and display the skill library overlay. */
  async _renderSkillLibrary() {
    const skills = await this._fetchSkills();
    if (!skills) return;

    const lib = document.createElement('div');
    lib.className = 'ai-skill-library';

    // Header: search + view toggle + close
    const header = document.createElement('div');
    header.className = 'skill-lib-header';
    header.innerHTML = `
      <input type="text" class="skill-lib-search" placeholder="🔍 搜索技能…" autocomplete="off" />
      <div class="skill-lib-view-toggle">
        <button class="skill-lib-view-btn active" data-view="recommend">推荐</button>
        <button class="skill-lib-view-btn" data-view="all">全部</button>
      </div>
      <button class="skill-lib-close" title="关闭技能库">✕</button>
    `;
    lib.appendChild(header);

    // Category filter bar
    const catBar = document.createElement('div');
    catBar.className = 'skill-lib-cat-bar';
    lib.appendChild(catBar);

    // Card grid (scrollable)
    const grid = document.createElement('div');
    grid.className = 'skill-lib-grid';
    lib.appendChild(grid);

    // Active count footer
    const footer = document.createElement('div');
    footer.className = 'skill-lib-footer';
    lib.appendChild(footer);

    // Insert into container, covering chat-flow
    this._container.appendChild(lib);

    // State
    let currentView = 'recommend';
    let currentCat = 'all';
    let searchText = '';

    const render = () => {
      const filtered = this._filterSkillList(skills, currentView, currentCat, searchText);
      this._renderCategoryBar(catBar, skills, currentView, currentCat, (cat) => {
        currentCat = cat;
        render();
      });
      this._renderSkillGrid(grid, filtered);
      const activeCount = skills.filter(s => s.enabled).length;
      footer.textContent = `已激活 ${activeCount} 个技能`;
    };

    // Bind events
    header.querySelector('.skill-lib-close').addEventListener('click', () => lib.remove());
    header.querySelectorAll('.skill-lib-view-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        header.querySelectorAll('.skill-lib-view-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        currentView = btn.dataset.view;
        currentCat = 'all';
        render();
      });
    });
    header.querySelector('.skill-lib-search').addEventListener('input', (e) => {
      searchText = e.target.value.trim().toLowerCase();
      render();
    });

    render();
  }

  /** Fetch all skills from /api/skills and cache them. */
  async _fetchSkills(forceRefresh = false) {
    if (this._skillCache && !forceRefresh) return this._skillCache;
    try {
      const resp = await fetch('/api/skills');
      const data = await resp.json();
      if (data.success && data.skills) {
        this._skillCache = data.skills;
        return this._skillCache;
      }
    } catch (e) {
      console.error('[AIPanel] Failed to load skills:', e);
    }
    return null;
  }

  /** Filter skills list by view mode, category, and search text. */
  _filterSkillList(skills, view, category, search) {
    let list = skills;

    // "recommend" view: filter by file type affinity + already enabled
    if (view === 'recommend') {
      const ft = (this._currentFileType || '').toLowerCase();
      const affinity = AIPanel._FILE_TYPE_AFFINITY[ft] || [];
      list = skills.filter(s => {
        if (s.enabled) return true;
        if (affinity.length === 0) return true; // no file → show all
        return affinity.some(prefix => s.id.startsWith(prefix) || (s.tags || []).includes(prefix));
      });
    }

    // Category filter
    if (category && category !== 'all' && category !== 'recommend') {
      list = list.filter(s => s.category === category);
    }

    // Search filter
    if (search) {
      list = list.filter(s =>
        (s.name || '').toLowerCase().includes(search) ||
        (s.description || '').toLowerCase().includes(search) ||
        (s.id || '').toLowerCase().includes(search) ||
        (s.tags || []).some(t => t.toLowerCase().includes(search))
      );
    }

    return list;
  }

  /** Render category filter chips. */
  _renderCategoryBar(container, skills, view, activeCat, onSelect) {
    container.innerHTML = '';
    // Collect categories present in data
    const cats = new Map();
    cats.set('all', skills.length);
    skills.forEach(s => {
      const c = s.category || 'custom';
      cats.set(c, (cats.get(c) || 0) + 1);
    });

    for (const [cat, count] of cats) {
      const chip = document.createElement('button');
      chip.className = 'skill-lib-cat-chip' + (cat === activeCat ? ' active' : '');
      const label = AIPanel._CATEGORY_LABELS[cat] || cat;
      chip.textContent = `${label} (${count})`;
      chip.addEventListener('click', () => onSelect(cat));
      container.appendChild(chip);
    }
  }

  /** Render skill cards in the grid. */
  _renderSkillGrid(container, skills) {
    container.innerHTML = '';
    if (!skills.length) {
      container.innerHTML = '<div class="skill-lib-empty">暂无匹配的技能</div>';
      return;
    }

    // Group by category if in "all" view
    skills.forEach(s => {
      const card = document.createElement('div');
      card.className = 'skill-lib-card' + (s.enabled ? ' active' : '');
      card.innerHTML = `
        <div class="skill-lib-card-top">
          <span class="skill-lib-card-icon">${s.icon || '🔧'}</span>
          <span class="skill-lib-card-name">${s.name || s.id}</span>
        </div>
        <div class="skill-lib-card-desc">${s.description || ''}</div>
        <div class="skill-lib-card-bottom">
          <span class="skill-lib-card-cat">${AIPanel._CATEGORY_LABELS[s.category] || s.category || ''}</span>
          <label class="skill-lib-toggle">
            <input type="checkbox" ${s.enabled ? 'checked' : ''} />
            <span class="skill-lib-toggle-slider"></span>
          </label>
        </div>
      `;
      const checkbox = card.querySelector('input[type="checkbox"]');
      checkbox.addEventListener('change', async () => {
        const enabled = checkbox.checked;
        const ok = await this._toggleSkill(s.id, enabled);
        if (ok) {
          s.enabled = enabled;
          card.classList.toggle('active', enabled);
          this._refreshSkillBar();
          // Update footer
          const footer = this._container.querySelector('.skill-lib-footer');
          if (footer) {
            const cache = this._skillCache || [];
            footer.textContent = `已激活 ${cache.filter(x => x.enabled).length} 个技能`;
          }
        } else {
          checkbox.checked = !enabled; // revert
        }
      });
      container.appendChild(card);
    });
  }

  /** Toggle a skill on/off via the backend API. */
  async _toggleSkill(skillId, enabled) {
    try {
      const resp = await fetch(`/api/skills/${encodeURIComponent(skillId)}/toggle`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled }),
      });
      const data = await resp.json();
      return data.success !== false;
    } catch (e) {
      console.error('[AIPanel] Skill toggle failed:', e);
      return false;
    }
  }

  /** Refresh the top skill bar chips from the cached skill list. */
  _refreshSkillBar() {
    if (!this._skillBar) return;
    const active = (this._skillCache || []).filter(s => s.enabled);
    this._skillBar.innerHTML = '';
    if (!active.length) {
      this._skillBar.style.display = 'none';
      return;
    }
    this._skillBar.style.display = '';
    active.forEach(s => {
      const chip = document.createElement('span');
      chip.className = 'skill-chip';
      chip.innerHTML = `${s.icon || '🔧'}\u00a0${s.name || s.id}<button class="skill-chip-x" title="停用">✕</button>`;
      chip.querySelector('.skill-chip-x').addEventListener('click', async (e) => {
        e.stopPropagation();
        const ok = await this._toggleSkill(s.id, false);
        if (ok) {
          s.enabled = false;
          this._refreshSkillBar();
          // Also update the library panel if open
          const libCard = this._container.querySelector(`.skill-lib-card input[type="checkbox"]`);
          // Refresh the whole library if open
          const lib = this._container.querySelector('.ai-skill-library');
          if (lib) {
            this._skillCache = null;
            lib.remove();
            this._renderSkillLibrary();
          }
        }
      });
      this._skillBar.appendChild(chip);
    });
  }

  /** Load active skills into the skill bar on initialization. */
  async _loadActiveSkillBar() {
    const skills = await this._fetchSkills();
    if (skills) this._refreshSkillBar();
  }

  // ══════════════════ Skill Bar ══════════════════

  /**
   * Fetch executable skills from backend and populate the skill bar chips.
   * Called when a file is opened (via setFileContext) or on init.
   */
  async _loadSkillBar() {
    if (!this._skillBar) return;
    try {
      const ft = this._currentFileType || '';
      const resp = await fetch(`/api/editor/ai/skill-list?file_type=${encodeURIComponent(ft)}`);
      const data = await resp.json();
      const skills = (data.skills || []).filter(s => s.has_executor);
      this._skillBar.innerHTML = '';
      if (!skills.length) { this._skillBar.style.display = 'none'; return; }
      this._skillBar.style.display = '';
      skills.forEach(s => {
        const chip = document.createElement('button');
        chip.className = 'skill-chip';
        chip.dataset.skillId = s.id;
        chip.title = s.description || s.name;
        chip.textContent = (s.icon ? s.icon + '\u00a0' : '') + s.name;
        chip.addEventListener('click', () => this._activateSkill(s.id, s));
        this._skillBar.appendChild(chip);
      });
    } catch {
      this._skillBar.style.display = 'none';
    }
  }

  // ══════════════════ Skill Execution Panel ══════════════════

  /**
   * Open the bottom execution panel for a skill.
   * Builds a param form; auto-fills current file info; waits for user submit.
   * @param {string} skillId
   * @param {Object} skillMeta  - {id, name, icon, description, params_schema, ...}
   */
  _activateSkill(skillId, skillMeta) {
    const panel = this._getOrCreateExecPanel();
    panel.querySelector('.skill-exec-title').textContent =
      `${skillMeta.icon || '\u{1F527}'}\u00a0${skillMeta.name}`;
    const body = panel.querySelector('.skill-exec-body');
    body.innerHTML = '';
    panel.classList.remove('collapsed');

    if (skillMeta.description) {
      const desc = document.createElement('p');
      desc.className = 'skill-exec-desc';
      desc.textContent = skillMeta.description;
      body.appendChild(desc);
    }

    // Current-file chip
    const currentFile = (typeof this._doc?.getFileName === 'function'
      ? this._doc.getFileName() : null)
      || this._currentFileName || null;
    if (currentFile) {
      const chip = document.createElement('div');
      chip.className = 'skill-exec-current-file';
      chip.innerHTML =
        `<span>\uD83D\uDCC4</span><strong>${currentFile}</strong>` +
        `<span class="exec-file-hint">\uff08\u5f53\u524d\u6587\u4ef6\uff0c\u81ea\u52a8\u4f5c\u4e3a\u4e3b\u8f93\u5165\uff09</span>`;
      body.appendChild(chip);
    }

    // Param form
    const form = document.createElement('form');
    form.className = 'skill-exec-form';
    const schema = skillMeta.params_schema || {};

    Object.entries(schema).forEach(([key, field]) => {
      if (key === 'current_file') return; // auto-filled
      const lbl = document.createElement('label');
      lbl.className = 'skill-exec-field';
      const labelTxt = document.createElement('span');
      labelTxt.className = 'skill-exec-label';
      labelTxt.textContent = (field.label || key) + (field.required ? ' *' : '');
      lbl.appendChild(labelTxt);

      let input;
      if (field.type === 'file' || field.type === 'file_list') {
        input = document.createElement('input');
        input.type = 'file';
        if (field.type === 'file_list') input.multiple = true;
        if (field.accept) input.accept = field.accept;
        input.className = 'skill-exec-input-file';
      } else if (field.type === 'textarea') {
        input = document.createElement('textarea');
        input.rows = 3;
        input.placeholder = field.placeholder || '';
        input.className = 'skill-exec-input-text';
      } else if (field.type === 'select') {
        input = document.createElement('select');
        input.className = 'skill-exec-input-select';
        (field.options || []).forEach(opt => {
          const o = document.createElement('option');
          o.value = opt.value; o.textContent = opt.label;
          if (opt.value === field.default) o.selected = true;
          input.appendChild(o);
        });
      } else {
        input = document.createElement('input');
        input.type = 'text';
        input.placeholder = field.placeholder || '';
        input.className = 'skill-exec-input-text';
      }
      input.name = key;
      if (field.required) input.required = true;
      lbl.appendChild(input);
      form.appendChild(lbl);
    });

    const runBtn = document.createElement('button');
    runBtn.type = 'submit';
    runBtn.className = 'skill-exec-run-btn';
    runBtn.textContent = '\u25b6 \u5f00\u59cb\u6267\u884c';
    form.appendChild(runBtn);

    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      await this._executeSkill(skillId, skillMeta, form, currentFile, panel);
    });
    body.appendChild(form);
  }

  /**
   * Execute a skill via SSE + render multi-step progress and result.
   */
  async _executeSkill(skillId, skillMeta, form, currentFile, panel) {
    const body = panel.querySelector('.skill-exec-body');
    const runBtn = form.querySelector('.skill-exec-run-btn');
    runBtn.disabled = true;
    runBtn.textContent = '\u23f3 \u6267\u884c\u4e2d\u2026';

    const progressState = this._ensureTaskProgressState({ stepElements: {} }, body, {
      wrapperClass: 'skill-exec-progress task-progress',
      stepClass: 'skill-exec-step',
      initialLabel: '准备执行技能',
    });
    const progressWrap = progressState.wrap;

    const resultWrap = document.createElement('div');
    resultWrap.className = 'skill-exec-result hidden';
    body.appendChild(resultWrap);

    const addStep = (text, cls = '') => {
      const step = this._appendTaskProgressStep(progressState, body, text, cls, {
        wrapperClass: 'skill-exec-progress task-progress',
        stepClass: 'skill-exec-step',
        initialLabel: '准备执行技能',
      });
      progressWrap.scrollTop = progressWrap.scrollHeight;
      return step;
    };

    try {
      const params = {};
      const sessionId = Math.random().toString(36).slice(2, 10);

      // Collect form fields and upload any files
      for (const el of Array.from(form.elements)) {
        if (!el.name) continue;
        if (el.type === 'file') {
          if (el.files && el.files.length > 0) {
            const fd = new FormData();
            fd.append('session_id', sessionId);
            for (const f of el.files) fd.append('files[]', f);
            addStep('\uD83D\uDCE4 \u4e0a\u4f20\u6587\u4ef6\u2026');
            const upResp = await fetch('/api/editor/ai/skill-upload', { method: 'POST', body: fd });
            const upJson = await upResp.json();
            if (!upJson.success) throw new Error(`\u4e0a\u4f20\u5931\u8d25: ${upJson.error}`);
            params[el.name] = el.multiple ? upJson.paths : upJson.paths[0];
          }
        } else if (el.tagName === 'TEXTAREA' || el.tagName === 'SELECT' ||
                   (el.tagName === 'INPUT' && el.type !== 'submit')) {
          params[el.name] = el.value;
        }
      }

      if (currentFile) {
        params['current_file'] = currentFile;
        if (this._fileId) params['current_file_id'] = this._fileId;
      }

      addStep('\uD83D\uDCE1 \u8fde\u63a5\u6280\u80fd\u670d\u52a1\u2026');

      const resp = await fetch('/api/editor/ai/skill-execute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ skill_id: skillId, session_id: sessionId, params }),
      });
      if (!resp.ok) throw new Error(`\u670d\u52a1\u5668\u9519\u8bef (${resp.status})`);

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';

      const handleEvent = (raw) => {
        if (!raw.startsWith('data: ')) return;
        let ev;
        try { ev = JSON.parse(raw.slice(6)); } catch { return; }

        if (this._consumeTaskProgressEvent(progressState, body, ev, {
          wrapperClass: 'skill-exec-progress task-progress',
          stepClass: 'skill-exec-step',
          initialLabel: '准备执行技能',
        })) {
          return;
        }

        switch (ev.type) {
          case 'status':
            addStep(ev.text || '');
            break;
          case 'output':
            resultWrap.classList.remove('hidden');
            this._renderSkillOutput(ev, resultWrap);
            break;
          case 'error':
            this._finalizeTaskProgressState(progressState, ev.text || '执行失败', 'error');
            addStep(`❌ ${ev.text}`, 'error');
            break;
          case 'done':
            this._finalizeTaskProgressState(progressState, ev.summary || '执行完成');
            addStep(`🎉 完成${ev.summary ? '：' + ev.summary : ''}`, 'done');
            runBtn.disabled = false;
            runBtn.textContent = '▶ 重新执行';
            break;
        }
      };

            this._finalizeTaskProgressState(progressState, err.message || '执行失败', 'error');
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const parts = buf.split('\n\n');
        buf = parts.pop();
        for (const p of parts) handleEvent(p);
      }
      if (buf) handleEvent(buf);

    } catch (err) {
      addStep(`\u274c ${err.message}`, 'error');
      runBtn.disabled = false;
      runBtn.textContent = '\u25b6 \u91cd\u65b0\u6267\u884c';
    }
  }

  /**
   * Render an SSE output event inside the result area.
   */
  _renderSkillOutput(ev, resultWrap) {
    const { output_type, data, label } = ev;

    if (output_type === 'xlsx_data') {
      const rows = this._workbookToRows(data);
      resultWrap.appendChild(this._makeTablePreview(rows, label || '\u7ed3\u679c\u8868\u683c'));

      const btnRow = document.createElement('div');
      btnRow.className = 'skill-exec-btn-row';

      const openBtn = document.createElement('button');
      openBtn.className = 'skill-exec-action-btn primary';
      openBtn.textContent = '\uD83D\uDCCA \u5728\u7f16\u8f91\u5668\u4e2d\u6253\u5f00';
      openBtn.addEventListener('click', () => {
        if (window.__koto?.openWorkbookData) {
          window.__koto.openWorkbookData(data, label || 'skill_result.xlsx');
        } else {
          openBtn.textContent = '\u26a0\ufe0f \u5f53\u524d\u7248\u672c\u4e0d\u652f\u6301\u76f4\u63a5\u6253\u5f00';
          openBtn.disabled = true;
        }
      });
      btnRow.appendChild(openBtn);

      const insertBtn = document.createElement('button');
      insertBtn.className = 'skill-exec-action-btn';
      insertBtn.textContent = '\uD83D\uDCCB \u63d2\u5165\u5230\u6587\u6863';
      insertBtn.addEventListener('click', () => {
        if (rows.length > 0) {
          const tsv = rows.map(r => r.join('\t')).join('\n');
          this._doc?.insertText?.(tsv);
          insertBtn.textContent = '\u2705 \u5df2\u63d2\u5165';
          insertBtn.disabled = true;
        }
      });
      btnRow.appendChild(insertBtn);
      resultWrap.appendChild(btnRow);

    } else if (output_type === 'html') {
      const wrapper = document.createElement('div');
      wrapper.className = 'skill-exec-html-result';
      wrapper.innerHTML = typeof data === 'string' ? data : '';
      resultWrap.appendChild(wrapper);

      const btnRow = document.createElement('div');
      btnRow.className = 'skill-exec-btn-row';
      const insertBtn = document.createElement('button');
      insertBtn.className = 'skill-exec-action-btn primary';
      insertBtn.textContent = '\u270d\ufe0f \u63d2\u5165\u5230\u6587\u6863';
      insertBtn.addEventListener('click', () => {
        this._doc?.insertHTML?.(typeof data === 'string' ? data : '');
        insertBtn.textContent = '\u2705 \u5df2\u63d2\u5165';
        insertBtn.disabled = true;
      });
      btnRow.appendChild(insertBtn);
      resultWrap.appendChild(btnRow);

    } else if (output_type === 'markdown') {
      const wrapper = document.createElement('div');
      wrapper.className = 'skill-exec-md-result';
      wrapper.textContent = typeof data === 'string' ? data : JSON.stringify(data);
      resultWrap.appendChild(wrapper);

      const btnRow = document.createElement('div');
      btnRow.className = 'skill-exec-btn-row';
      const insertBtn = document.createElement('button');
      insertBtn.className = 'skill-exec-action-btn primary';
      insertBtn.textContent = '\u270d\ufe0f \u63d2\u5165\u5230\u6587\u6863';
      insertBtn.addEventListener('click', () => {
        this._doc?.insertText?.(typeof data === 'string' ? data : '');
        insertBtn.textContent = '\u2705 \u5df2\u63d2\u5165';
        insertBtn.disabled = true;
      });
      btnRow.appendChild(insertBtn);
      resultWrap.appendChild(btnRow);

    } else {
      const pre = document.createElement('pre');
      pre.className = 'skill-exec-raw-result';
      pre.textContent = typeof data === 'string' ? data : JSON.stringify(data, null, 2);
      resultWrap.appendChild(pre);
    }
  }

  // ══════════════════ Skill Auto-Recommend Card ══════════════════

  /**
   * Render a skill recommendation card in the chat flow.
   * Called when backend returns a skill_recommend SSE event.
   * @param {Object} skill - {id, name, icon, description, has_executor}
   */
  showSkillRecommend(skill) {
    if (!skill || !this._chatFlow) return;
    const card = document.createElement('div');
    card.className = 'skill-recommend-card';
    card.innerHTML = `
      <div class="skill-rec-header">
        <span class="skill-rec-icon">${skill.icon || '\uD83D\uDD27'}</span>
        <div class="skill-rec-meta">
          <div class="skill-rec-name">${skill.name}</div>
          <div class="skill-rec-desc">${skill.description || ''}</div>
        </div>
      </div>
      <div class="skill-rec-footer">
        <button class="skill-rec-start-btn">\u25b6 \u7acb\u5373\u4f7f\u7528</button>
        <button class="skill-rec-dismiss-btn">\u2715</button>
      </div>
    `;
    card.querySelector('.skill-rec-start-btn').addEventListener('click', () => {
      card.remove();
      this._activateSkill(skill.id, skill);
    });
    card.querySelector('.skill-rec-dismiss-btn').addEventListener('click', () => card.remove());
    this._chatFlow.appendChild(card);
    this._scrollBottom();
  }

  // ══════════════════ Panel + Table Helpers ══════════════════

  _getOrCreateExecPanel() {
    let panel = document.getElementById('skill-exec-panel');
    if (panel) return panel;
    panel = document.createElement('div');
    panel.id = 'skill-exec-panel';
    panel.className = 'skill-exec-panel collapsed';
    panel.innerHTML = `
      <div class="skill-exec-header">
        <span class="skill-exec-title"></span>
        <div class="skill-exec-header-btns">
          <button class="skill-exec-minimize" title="\u6700\u5c0f\u5316">\u25bc</button>
          <button class="skill-exec-close" title="\u5173\u95ed">\u2715</button>
        </div>
      </div>
      <div class="skill-exec-body"></div>
    `;
    const root = document.getElementById('file-assistant-root') || document.body;
    root.appendChild(panel);
    panel.querySelector('.skill-exec-minimize').addEventListener('click', () =>
      panel.classList.toggle('minimized'));
    panel.querySelector('.skill-exec-close').addEventListener('click', () =>
      panel.classList.add('collapsed'));
    return panel;
  }

  _workbookToRows(workbookData) {
    try {
      const sheets = workbookData.sheets || {};
      const firstSheet = Object.values(sheets)[0];
      if (!firstSheet) return [];
      const cellData = firstSheet.cellData || {};
      const rowCount = firstSheet.rowCount || Object.keys(cellData).length;
      const colCount = firstSheet.columnCount || 10;
      const rows = [];
      for (let r = 0; r < Math.min(rowCount, 200); r++) {
        const row = cellData[r] || {};
        const cells = [];
        for (let c = 0; c < colCount; c++) cells.push(row[c]?.v ?? '');
        rows.push(cells);
      }
      return rows;
    } catch { return []; }
  }

  _makeTablePreview(rows, label) {
    const wrap = document.createElement('div');
    wrap.className = 'skill-exec-table-wrap';
    if (label) {
      const h = document.createElement('div');
      h.className = 'skill-exec-table-label';
      h.textContent = label;
      wrap.appendChild(h);
    }
    if (!rows.length) {
      const p = document.createElement('p');
      p.textContent = '\uff08\u65e0\u6570\u636e\uff09';
      wrap.appendChild(p);
      return wrap;
    }
    const scroll = document.createElement('div');
    scroll.className = 'skill-exec-table-scroll';
    const table = document.createElement('table');
    table.className = 'skill-exec-table';
    const thead = document.createElement('thead');
    const hRow = document.createElement('tr');
    (rows[0] || []).forEach(cell => {
      const th = document.createElement('th');
      th.textContent = cell ?? '';
      hRow.appendChild(th);
    });
    thead.appendChild(hRow);
    table.appendChild(thead);
    const tbody = document.createElement('tbody');
    rows.slice(1, 51).forEach(row => {
      const tr = document.createElement('tr');
      row.forEach(cell => {
        const td = document.createElement('td');
        td.textContent = cell ?? '';
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    scroll.appendChild(table);
    wrap.appendChild(scroll);
    if (rows.length > 51) {
      const note = document.createElement('p');
      note.className = 'skill-exec-table-note';
      note.textContent = `\uff08\u663e\u793a\u524d 50 \u884c\uff0c\u5171 ${rows.length - 1} \u6761\u6570\u636e\uff09`;
      wrap.appendChild(note);
    }
    return wrap;
  }
}
