/**
 * DocAgent UI — Frontend controller for the new document processing system
 *
 * Provides:
 * - PhaseTracker: Step-by-step execution timeline (like coding agents)
 * - ChangeVisualizer: Real-time document change highlighting
 * - ConfirmDialog: User confirmation for pending changes
 *
 * Usage:
 *   const docAgent = new DocAgentUI(socket, { container: '#wa-ai-panel' });
 */

// ============================================================================
// PhaseTracker — Step Timeline Component
// ============================================================================

class PhaseTracker {
  constructor(container) {
    this.container = typeof container === 'string'
      ? document.querySelector(container)
      : container;
    this.steps = new Map();
    this.currentTaskId = null;

    if (this.container) {
      this.container.classList.add('phase-tracker');
    }
  }

  /**
   * Render the execution plan as a timeline
   * @param {Array} steps - Array of step objects from doc_plan_created
   */
  renderPlan(steps) {
    if (!this.container) return;

    this.steps.clear();
    this.container.innerHTML = '';

    // Add plan header
    const header = document.createElement('div');
    header.className = 'phase-tracker-header';
    header.innerHTML = `
      <span class="header-icon">📋</span>
      <span class="header-text">执行计划 (${steps.length} 步)</span>
    `;
    this.container.appendChild(header);

    // Add steps
    const stepsContainer = document.createElement('div');
    stepsContainer.className = 'phase-steps';

    steps.forEach((step, index) => {
      const el = this.createStepElement(step, index);
      stepsContainer.appendChild(el);
      this.steps.set(step.step_id || step.name, el);
    });

    this.container.appendChild(stepsContainer);
  }

  createStepElement(step, index) {
    const div = document.createElement('div');
    div.className = 'phase-step pending';
    div.dataset.stepId = step.step_id || step.name;

    const stepType = step.step_type || 'generic';
    const typeIcon = {
      'llm': '🤖',
      'code': '💻',
      'file': '📁',
      'search': '🔍',
      'tool': '🔧',
      'generic': '▶️',
    }[stepType] || '▶️';

    div.innerHTML = `
      <div class="step-connector">
        <div class="connector-line"></div>
      </div>
      <div class="step-indicator">
        <span class="step-number">${index + 1}</span>
        <span class="step-icon">${typeIcon}</span>
        <span class="step-status-icon"></span>
      </div>
      <div class="step-content">
        <div class="step-header">
          <span class="step-name">${this.escapeHtml(step.name || `步骤 ${index + 1}`)}</span>
          <span class="step-type-badge">${stepType}</span>
        </div>
        <div class="step-description">${this.escapeHtml(step.description || '')}</div>
        <div class="step-progress-container">
          <div class="step-progress-bar">
            <div class="progress-fill" style="width: 0%"></div>
          </div>
          <span class="progress-text">0%</span>
        </div>
        <div class="step-detail"></div>
        <div class="step-tools"></div>
      </div>
    `;

    return div;
  }

  activateStep(stepId) {
    const el = this.steps.get(stepId);
    if (!el) return;

    // Deactivate other running steps
    this.container.querySelectorAll('.phase-step.running').forEach(s => {
      if (s !== el) {
        s.classList.remove('running');
      }
    });

    el.classList.remove('pending', 'completed', 'error');
    el.classList.add('running');

    // Update status icon
    const statusIcon = el.querySelector('.step-status-icon');
    if (statusIcon) {
      statusIcon.innerHTML = '<span class="spinner">⏳</span>';
    }

    // Scroll into view
    el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  updateProgress(stepId, progress, message = '') {
    const el = this.steps.get(stepId);
    if (!el) return;

    const progressFill = el.querySelector('.progress-fill');
    const progressText = el.querySelector('.progress-text');

    if (progressFill) {
      progressFill.style.width = `${Math.min(100, Math.max(0, progress))}%`;
    }
    if (progressText) {
      progressText.textContent = `${progress}%`;
    }

    if (message) {
      const detail = el.querySelector('.step-detail');
      if (detail) {
        detail.textContent = message;
      }
    }
  }

  addToolCall(stepId, toolName, toolArgs) {
    const el = this.steps.get(stepId);
    if (!el) return;

    const toolsContainer = el.querySelector('.step-tools');
    if (!toolsContainer) return;

    const toolEl = document.createElement('div');
    toolEl.className = 'tool-call';
    toolEl.innerHTML = `
      <span class="tool-icon">🔧</span>
      <span class="tool-name">${this.escapeHtml(toolName)}</span>
      <span class="tool-status pending">...</span>
    `;
    toolEl.dataset.toolName = toolName;
    toolsContainer.appendChild(toolEl);
  }

  updateToolResult(stepId, toolName, resultPreview) {
    const el = this.steps.get(stepId);
    if (!el) return;

    const toolEl = el.querySelector(`.tool-call[data-tool-name="${toolName}"]`);
    if (!toolEl) return;

    const status = toolEl.querySelector('.tool-status');
    if (status) {
      status.classList.remove('pending');
      status.classList.add('completed');
      status.textContent = '✓';
      status.title = resultPreview;
    }
  }

  completeStep(stepId, summary = '') {
    const el = this.steps.get(stepId);
    if (!el) return;

    el.classList.remove('running', 'pending');
    el.classList.add('completed');

    // Update status icon
    const statusIcon = el.querySelector('.step-status-icon');
    if (statusIcon) {
      statusIcon.innerHTML = '✅';
    }

    // Update progress to 100%
    this.updateProgress(stepId, 100);

    // Show summary
    if (summary) {
      const detail = el.querySelector('.step-detail');
      if (detail) {
        detail.textContent = summary;
      }
    }
  }

  errorStep(stepId, error) {
    const el = this.steps.get(stepId);
    if (!el) return;

    el.classList.remove('running', 'pending');
    el.classList.add('error');

    // Update status icon
    const statusIcon = el.querySelector('.step-status-icon');
    if (statusIcon) {
      statusIcon.innerHTML = '❌';
    }

    // Show error
    const detail = el.querySelector('.step-detail');
    if (detail) {
      detail.classList.add('error-text');
      detail.textContent = error;
    }
  }

  reset() {
    if (this.container) {
      this.container.innerHTML = '';
    }
    this.steps.clear();
  }

  escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }
}


// ============================================================================
// ChangeVisualizer — Document Change Highlighting
// ============================================================================

class ChangeVisualizer {
  constructor(editorGetter) {
    // editorGetter is a function that returns the current editor instance
    this.getEditor = typeof editorGetter === 'function'
      ? editorGetter
      : () => editorGetter;
    this.highlights = new Map();
    this.bubbles = [];
  }

  /**
   * Highlight a file change in the editor
   * @param {Object} changeEvent - doc_file_change event data
   */
  highlight(changeEvent) {
    const {
      file_path,
      range,
      highlight_color,
      change_type,
      modified,
      original
    } = changeEvent;

    const editor = this.getEditor();
    if (!editor) return;

    // Detect editor type and apply appropriate highlighting
    const editorType = this.detectEditorType(editor);

    try {
      switch (editorType) {
        case 'tiptap':
          this.highlightTipTap(editor, range, highlight_color, change_type);
          break;
        case 'univer':
          this.highlightUniver(editor, range, highlight_color);
          break;
        case 'canvas':
          this.highlightCanvas(editor, range, highlight_color);
          break;
        default:
          console.warn('[ChangeVisualizer] Unknown editor type');
      }
    } catch (e) {
      console.error('[ChangeVisualizer] Highlight failed:', e);
    }

    // Show change bubble
    this.showChangeBubble(change_type, modified, original);
  }

  detectEditorType(editor) {
    if (!editor) return 'unknown';

    // TipTap editor
    if (editor.chain && typeof editor.chain === 'function') {
      return 'tiptap';
    }

    // Univer sheets
    if (editor.getActiveSheet || editor.univerAPI) {
      return 'univer';
    }

    // Canvas-based (PPTX)
    if (editor.canvas || editor.renderSlide) {
      return 'canvas';
    }

    return 'unknown';
  }

  highlightTipTap(editor, range, color, changeType) {
    if (!range || range.length < 2) return;

    const [start, end] = range;
    if (start < 0 || end <= start) return;

    // Map color to CSS class
    const colorClass = {
      'green': 'doc-highlight-add',
      'red': 'doc-highlight-delete',
      'yellow': 'doc-highlight-modify',
      'blue': 'doc-highlight-info',
    }[color] || 'doc-highlight-default';

    try {
      // TipTap highlight using Mark
      editor.chain()
        .focus()
        .setTextSelection({ from: start, to: end })
        .setMark('highlight', { class: colorClass })
        .run();

      // Store for later removal
      this.highlights.set(`${start}-${end}`, { start, end, color });

      // Auto-remove after 5 seconds
      setTimeout(() => {
        this.removeHighlight(editor, start, end);
      }, 5000);
    } catch (e) {
      console.warn('[ChangeVisualizer] TipTap highlight failed:', e);
    }
  }

  highlightUniver(editor, range, color) {
    if (!range) return;

    try {
      // Univer range format could be cell references or indices
      const sheet = editor.getActiveSheet?.() || editor;
      if (!sheet) return;

      const colorHex = {
        'green': '#D4EDDA',
        'red': '#F8D7DA',
        'yellow': '#FFF3CD',
        'blue': '#CCE5FF',
      }[color] || '#E9ECEF';

      // Attempt to set background - API varies by Univer version
      if (sheet.getRange && typeof range === 'string') {
        sheet.getRange(range).setBackground(colorHex);
      } else if (Array.isArray(range) && range.length >= 2) {
        // Assume [row, col] or [row, col, endRow, endCol]
        const rangeRef = sheet.getRange(
          range[0], range[1],
          range[2] || range[0], range[3] || range[1]
        );
        rangeRef?.setBackground?.(colorHex);
      }
    } catch (e) {
      console.warn('[ChangeVisualizer] Univer highlight failed:', e);
    }
  }

  highlightCanvas(editor, range, color) {
    // Canvas highlighting for PPTX - emit event for custom handling
    if (window.dispatchEvent) {
      window.dispatchEvent(new CustomEvent('doc-agent-highlight', {
        detail: { range, color, editor }
      }));
    }
  }

  removeHighlight(editor, start, end) {
    const key = `${start}-${end}`;
    if (!this.highlights.has(key)) return;

    try {
      if (editor.chain) {
        editor.chain()
          .setTextSelection({ from: start, to: end })
          .unsetMark('highlight')
          .run();
      }
    } catch (e) {
      // Ignore removal errors
    }

    this.highlights.delete(key);
  }

  showChangeBubble(changeType, modified, original) {
    // Create floating bubble showing the change
    const bubble = document.createElement('div');
    bubble.className = 'change-bubble';

    const typeLabels = {
      'add': '➕ 新增',
      'modify': '✏️ 修改',
      'delete': '🗑️ 删除',
      'annotate': '📝 批注',
    };

    const typeColors = {
      'add': 'green',
      'modify': 'yellow',
      'delete': 'red',
      'annotate': 'blue',
    };

    bubble.innerHTML = `
      <div class="bubble-header ${typeColors[changeType] || 'blue'}">
        ${typeLabels[changeType] || changeType}
      </div>
      <div class="bubble-content">
        ${this.escapeHtml(this.truncate(modified || original || '', 100))}
      </div>
    `;

    // Position near the editor panel
    const editorPanel = document.querySelector('#wa-editor-container');
    if (editorPanel) {
      const rect = editorPanel.getBoundingClientRect();
      bubble.style.position = 'fixed';
      bubble.style.top = `${rect.top + 20}px`;
      bubble.style.right = `${window.innerWidth - rect.right + 10}px`;
    }

    document.body.appendChild(bubble);
    this.bubbles.push(bubble);

    // Animate in
    requestAnimationFrame(() => {
      bubble.classList.add('visible');
    });

    // Auto-remove after 3 seconds
    setTimeout(() => {
      bubble.classList.remove('visible');
      setTimeout(() => {
        bubble.remove();
        const idx = this.bubbles.indexOf(bubble);
        if (idx > -1) this.bubbles.splice(idx, 1);
      }, 300);
    }, 3000);
  }

  clearAll() {
    this.highlights.clear();
    this.bubbles.forEach(b => b.remove());
    this.bubbles = [];
  }

  truncate(text, maxLen) {
    if (!text) return '';
    return text.length > maxLen ? text.substring(0, maxLen) + '...' : text;
  }

  escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }
}


// ============================================================================
// ConfirmDialog — User Confirmation Component
// ============================================================================

class ConfirmDialog {
  constructor() {
    this.overlay = null;
    this.dialog = null;
    this.callback = null;
  }

  show(data, callback) {
    this.callback = callback;

    // Create overlay
    this.overlay = document.createElement('div');
    this.overlay.className = 'confirm-dialog-overlay';

    // Create dialog
    this.dialog = document.createElement('div');
    this.dialog.className = 'confirm-dialog';

    const changesHtml = (data.pending_changes || [])
      .slice(0, 5)
      .map(c => `
        <div class="change-item ${c.change_type || 'modify'}">
          <span class="change-icon">${this.getChangeIcon(c.change_type)}</span>
          <span class="change-path">${this.escapeHtml(c.file_path || '')}</span>
          <span class="change-preview">${this.escapeHtml(this.truncate(c.modified || '', 50))}</span>
        </div>
      `)
      .join('');

    this.dialog.innerHTML = `
      <div class="dialog-header">
        <span class="dialog-icon">⚠️</span>
        <span class="dialog-title">确认操作</span>
      </div>
      <div class="dialog-body">
        <p class="dialog-description">${this.escapeHtml(data.description || '是否执行以下操作？')}</p>
        <div class="pending-changes">
          ${changesHtml || '<p class="no-changes">无待确认的变更</p>'}
        </div>
      </div>
      <div class="dialog-actions">
        <button class="btn-cancel">取消</button>
        <button class="btn-confirm">确认执行</button>
      </div>
    `;

    // Add event listeners
    this.dialog.querySelector('.btn-cancel').onclick = () => this.respond(false);
    this.dialog.querySelector('.btn-confirm').onclick = () => this.respond(true);

    this.overlay.appendChild(this.dialog);
    document.body.appendChild(this.overlay);

    // Animate in
    requestAnimationFrame(() => {
      this.overlay.classList.add('visible');
    });
  }

  respond(approved) {
    if (this.callback) {
      this.callback(approved);
    }
    this.hide();
  }

  hide() {
    if (this.overlay) {
      this.overlay.classList.remove('visible');
      setTimeout(() => {
        this.overlay.remove();
        this.overlay = null;
        this.dialog = null;
      }, 300);
    }
  }

  getChangeIcon(type) {
    return {
      'add': '➕',
      'modify': '✏️',
      'delete': '🗑️',
    }[type] || '📄';
  }

  truncate(text, maxLen) {
    return text.length > maxLen ? text.substring(0, maxLen) + '...' : text;
  }

  escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text || '';
    return div.innerHTML;
  }
}


// ============================================================================
// DocAgentUI — Main Controller
// ============================================================================

class DocAgentUI {
  constructor(socket, options = {}) {
    this.socket = socket;
    this.options = options;

    // Container for the phase tracker
    this.container = typeof options.container === 'string'
      ? document.querySelector(options.container)
      : options.container;

    // Initialize sub-components
    this.phaseTracker = new PhaseTracker(
      this.container?.querySelector('.phases') || this.createPhasesContainer()
    );

    this.changeVisualizer = new ChangeVisualizer(
      options.editorGetter || (() => window.currentEditor)
    );

    this.confirmDialog = new ConfirmDialog();

    // Current task state
    this.currentTaskId = null;
    this.isProcessing = false;

    // Bind socket events
    if (socket) {
      this.bindEvents();
    }
  }

  createPhasesContainer() {
    if (!this.container) return null;

    let phasesContainer = this.container.querySelector('.doc-agent-phases');
    if (!phasesContainer) {
      phasesContainer = document.createElement('div');
      phasesContainer.className = 'doc-agent-phases phases';
      this.container.insertBefore(phasesContainer, this.container.firstChild);
    }
    return phasesContainer;
  }

  bindEvents() {
    const socket = this.socket;

    // Plan events
    socket.on('doc_plan_start', (data) => {
      this.currentTaskId = data.task_id;
      this.isProcessing = true;
      this.phaseTracker.reset();
      this.changeVisualizer.clearAll();
    });

    socket.on('doc_plan_created', (data) => {
      if (data.steps && data.steps.length > 0) {
        this.phaseTracker.renderPlan(data.steps);
      }
    });

    // Step events
    socket.on('doc_step_start', (data) => {
      this.phaseTracker.activateStep(data.step_id);
    });

    socket.on('doc_step_progress', (data) => {
      this.phaseTracker.updateProgress(
        data.step_id,
        data.progress,
        data.message
      );
    });

    socket.on('doc_step_done', (data) => {
      this.phaseTracker.completeStep(data.step_id, data.summary);
    });

    socket.on('doc_step_error', (data) => {
      this.phaseTracker.errorStep(data.step_id, data.error);
    });

    // Tool events
    socket.on('doc_tool_call', (data) => {
      this.phaseTracker.addToolCall(
        data.step_id,
        data.tool_name,
        data.tool_args
      );
    });

    socket.on('doc_tool_result', (data) => {
      this.phaseTracker.updateToolResult(
        data.step_id,
        data.tool_name,
        data.result_preview
      );
    });

    // File change events
    socket.on('doc_file_change', (data) => {
      this.changeVisualizer.highlight(data);
    });

    socket.on('doc_highlight', (data) => {
      if (data.ranges) {
        data.ranges.forEach(range => {
          this.changeVisualizer.highlight({
            range: [range.start, range.end],
            highlight_color: range.color,
            change_type: 'annotate',
          });
        });
      }
    });

    // User confirmation
    socket.on('doc_user_confirm', (data) => {
      this.confirmDialog.show(data, (approved) => {
        socket.emit('doc_user_confirm_response', {
          step_id: data.step_id,
          task_id: data.task_id,
          approved: approved,
        });
      });
    });

    // Replan notification
    socket.on('doc_replan', (data) => {
      console.log('[DocAgentUI] Replan:', data.reason);
      if (data.new_steps && data.new_steps.length > 0) {
        // Re-render the plan with updated steps
        this.phaseTracker.renderPlan(data.new_steps);
      }
    });

    // Verification result
    socket.on('doc_verification', (data) => {
      console.log('[DocAgentUI] Verification:', data.status, data.summary);
    });

    // Task completion
    socket.on('agent_task_complete', (data) => {
      if (data.task_id === this.currentTaskId || !data.task_id) {
        this.isProcessing = false;
      }
    });

    // Error
    socket.on('doc_error', (data) => {
      console.error('[DocAgentUI] Error:', data.message);
      this.isProcessing = false;
    });
  }

  /**
   * Send a document processing request
   * @param {string} prompt - User prompt
   * @param {Object} context - File context
   */
  sendRequest(prompt, context = {}) {
    if (!this.socket) {
      console.error('[DocAgentUI] No socket connection');
      return;
    }

    const data = {
      prompt: prompt,
      _use_doc_agent: true,  // Force use of DocAgent
      ...context,
    };

    this.socket.emit('doc_ai_request', data);
  }

  reset() {
    this.phaseTracker.reset();
    this.changeVisualizer.clearAll();
    this.currentTaskId = null;
    this.isProcessing = false;
  }
}


// ============================================================================
// Export
// ============================================================================

// Make available globally
window.DocAgentUI = DocAgentUI;
window.PhaseTracker = PhaseTracker;
window.ChangeVisualizer = ChangeVisualizer;
window.ConfirmDialog = ConfirmDialog;

// Auto-initialize if socket is available
if (typeof window !== 'undefined') {
  window.addEventListener('DOMContentLoaded', () => {
    // Check if we should auto-init
    const socket = window.waSocket || window.socket;
    const container = document.querySelector('#wa-ai-panel');

    if (socket && container) {
      window.docAgentUI = new DocAgentUI(socket, {
        container: container,
        editorGetter: () => window.currentEditor || window.waEditor,
      });
      console.log('[DocAgentUI] Auto-initialized');
    }
  });
}
