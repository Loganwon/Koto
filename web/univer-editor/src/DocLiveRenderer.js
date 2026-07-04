// ═══════════════════════════════════════════════════════════════
// DocLiveRenderer — Live AI document preview + commit bar
//
// Receives streaming token chunks from the AI and renders them
// into the DocxViewer's ghost preview layer with 200ms debouncing.
// On stream completion, shows a commit bar with Tab/Esc shortcuts.
// ═══════════════════════════════════════════════════════════════

export class DocLiveRenderer {
  constructor(docxViewer) {
    this._viewer = docxViewer;
    this._buffer = '';
    this._mode = 'replace';           // 'replace' | 'append'
    this._requestId = '';
    this._originalSelection = '';
    this._active = false;
    this._flushTimer = null;
    this._FLUSH_MS = 200;
    this._commitBarEl = null;
    this._keyHandler = null;
    this._originalDocBuffer = null;
  }

  /**
   * Called when the first doc_live_chunk arrives for a new request.
   * @param {string} mode - 'replace' or 'append'
   * @param {string|null} originalSelection - text that was selected before the request
   * @param {string} requestId - correlates all chunks to this run
   */
  start(mode, originalSelection, requestId) {
    this._mode = mode || 'replace';
    this._originalSelection = originalSelection || '';
    this._requestId = requestId || '';
    this._buffer = '';
    this._active = true;
    // Save current DOCX ArrayBuffer for dismiss path
    this._originalDocBuffer = window.__koto?.lastDocxBuffer || null;
    // Immediately show an empty preview with a loading label
    this._viewer.setLiveText('', {
      append: false,
      label: this._mode === 'append' ? 'AI 正在插入内容…' : 'AI 实时预览中…',
    });
  }

  /**
   * Push a new token chunk into the buffer; schedule a debounced flush.
   * @param {string} chunk
   */
  push(chunk) {
    if (!this._active) return;
    this._buffer += chunk;
    if (!this._flushTimer) {
      this._flushTimer = setTimeout(() => {
        this._flushTimer = null;
        this._flush();
      }, this._FLUSH_MS);
    }
  }

  _flush() {
    if (!this._buffer || !this._viewer.isActive()) return;
    this._viewer.setLiveText(this._buffer, {
      append: false,
      label: this._mode === 'append' ? 'AI 正在插入内容…' : 'AI 实时预览',
    });
  }

  /**
   * Called when doc_live_commit arrives. Renders final text and shows
   * the commit bar.
   * @param {string} fullText - complete generated text
   * @param {string} mode
   * @param {string} originalSelection
   */
  showCommitBar(fullText, mode, originalSelection) {
    this._active = false;
    if (this._flushTimer) {
      clearTimeout(this._flushTimer);
      this._flushTimer = null;
    }
    // Final render
    this._viewer.setLiveText(fullText, {
      append: false,
      label: '✨ AI 已完成 — Tab 应用 / Esc 放弃',
    });
    this._buildCommitUI(fullText, mode || this._mode, originalSelection || this._originalSelection);
  }

  _buildCommitUI(fullText, mode, originalSelection) {
    // Remove any previous bar
    this._commitBarEl?.remove();

    const bar = document.createElement('div');
    bar.className = 'doc-live-commit-bar';

    const label = document.createElement('span');
    label.className = 'doc-live-commit-label';
    label.textContent = 'AI 修改已就绪';
    bar.appendChild(label);

    const acceptBtn = document.createElement('button');
    acceptBtn.textContent = '✅ 应用修改 (Tab)';
    acceptBtn.className = 'doc-live-btn doc-live-btn--accept';
    acceptBtn.addEventListener('click', () => this._commit(fullText, mode, originalSelection));
    bar.appendChild(acceptBtn);

    const dismissBtn = document.createElement('button');
    dismissBtn.textContent = '❌ 放弃 (Esc)';
    dismissBtn.className = 'doc-live-btn doc-live-btn--dismiss';
    dismissBtn.addEventListener('click', () => this._dismiss());
    bar.appendChild(dismissBtn);

    // Keyboard shortcuts
    document.addEventListener('keydown', this._keyHandler = (e) => {
      if (e.key === 'Tab' && !e.shiftKey) {
        e.preventDefault();
        this._commit(fullText, mode, originalSelection);
      }
      if (e.key === 'Escape') {
        this._dismiss();
      }
    }, { capture: true });

    document.body.appendChild(bar);
    this._commitBarEl = bar;
  }

  _commit(fullText, mode, originalSelection) {
    this._clearUI();
    if (mode === 'replace' && originalSelection) {
      // Replace the original selection text in the rendered DOCX DOM
      const ok = this._viewer.replaceText(originalSelection, fullText);
      if (!ok) {
        // Fallback: ghost preview stays visible — user can manually copy if needed
        console.warn('[DocLiveRenderer] replaceText: original text not found in rendered doc');
      }
    }
    // append mode: the ghost preview already shows the correct content; no further action needed
  }

  _dismiss() {
    this._clearUI();
    if (this._originalDocBuffer) {
      const filename = window.__koto?.currentFilename || '文档';
      this._viewer.render(this._originalDocBuffer, filename);
    } else {
      this._viewer.hide();
    }
  }

  _clearUI() {
    this._commitBarEl?.remove();
    this._commitBarEl = null;
    if (this._keyHandler) {
      document.removeEventListener('keydown', this._keyHandler, { capture: true });
      this._keyHandler = null;
    }
  }

  /** Reset all state (e.g. when a new file is opened). */
  reset() {
    this._active = false;
    this._buffer = '';
    if (this._flushTimer) {
      clearTimeout(this._flushTimer);
      this._flushTimer = null;
    }
    this._clearUI();
  }
}
