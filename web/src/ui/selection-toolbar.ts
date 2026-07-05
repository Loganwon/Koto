/**
 * Selection Toolbar — AI context bar, selection tooltip, PPTX table extract,
 * HTML table extract, toolbar positioning engine.
 * Workspace selection toolbar.
 */

// ── External dependencies (provided by workspace-assistant IIFE scope) ──
declare function $(id: string): HTMLElement | null;
declare let state: any;
declare let WA: any;
declare let lastSelectionText: string;
declare let _docxMouseIsDown: boolean;
declare let _docxMouseUpY: number;
declare let _docxHbEl: HTMLElement | null;
declare let _docxCpEl: HTMLElement | null;
declare let _docxSelTimer: any;
declare function _cloneSerializable(val: any, fallback: any): any;
declare function _escHtml(s: any): string;
declare function _getPinnedSelectionSourceMeta(): { sourcePath: string; sourceName: string; sourceType: string };
declare function _getDocxHdrFtrSelectionInfo(): any;
declare function _saveEditorRange(): void;
declare function _showDocxHoverBar(): void;
declare function _syncDocxHoverBar(): void;
declare function _syncDocxReviewToolbar(): void;
declare function _renderReviewShell(): void;
declare function _renderReviewSelectionLauncher(): void;
declare function _hideReviewSelectionLauncher(): void;
declare function _isReviewEditorFocused(): boolean;
declare function _isReviewShellFocused(): boolean;
declare function _syncReviewSelectionSnapshot(): void;
declare function _updateSubjectBar(fileName: string, fileType: string): void;
declare function _expandWAPanel(): void;

const _WA_EXPLICIT_CONTEXT_RULE = '只处理用户明确提供的选中文本和分析文档';

function _safeGetDocxHdrFtrSelectionInfo(): any {
  const getter = (window as any)._getDocxHdrFtrSelectionInfo;
  return typeof getter === 'function' ? getter() : null;
}

export interface ToolbarConfig {
  centerX: number;
  top: number;
  bottom: number;
  left?: number;
  right?: number;
}

export interface PositionResult {
  left: number;
  top: number;
  centerX: number;
}

export interface SelectionBounds {
  top: number;
  bottom: number;
  left: number;
  right: number;
  centerX: number;
}

export interface PinnedSelectionContext {
  text: string;
  previewText: string;
  sourcePath: string;
  sourceName: string;
  sourceType: string;
  kind?: string;
  rawText?: string;
  sheetName?: string;
  rangeA1?: string;
  rows?: number;
  cols?: number;
}

export interface DocxSelectionPayload {
  kind: string;
  rawText: string;
  aiText: string;
  previewText: string;
  countLabel: string;
  tableElement: HTMLElement | null;
  anchor_text?: string;
  anchor_start_offset?: number;
  anchor_end_offset?: number;
  anchor_occurrence?: number;
  anchor_context_before?: string;
  anchor_context_after?: string;
}

export interface DocxAnchorMeta {
  anchor_text: string;
  anchor_start_offset: number;
  anchor_end_offset: number;
  anchor_occurrence: number;
  anchor_context_before: string;
  anchor_context_after: string;
}

export interface PptxTableSelection {
  anchorRow: number;
  anchorCol: number;
  headRow: number;
  headCol: number;
  startRow: number;
  endRow: number;
  startCol: number;
  endCol: number;
  rows: number;
  cols: number;
}

// ── CSS Custom Highlights ──
export function _applyPinnedHighlight(): void {
  if (!(window as any).CSS || !(window as any).CSS.highlights) return;
  const sel = window.getSelection();
  if (!sel || sel.rangeCount === 0) return;
  try {
    const range = sel.getRangeAt(0).cloneRange();
    (window as any).CSS.highlights.set('wa-pinned', new (window as any).Highlight(range));
  } catch (e) { /* ignore if API unavailable */ }
}

export function _clearPinnedHighlight(): void {
  if ((window as any).CSS && (window as any).CSS.highlights) (window as any).CSS.highlights.delete('wa-pinned');
}

export function _applyTemporaryHighlight(textToFind: string): void {
  if (!textToFind || !(window as any).CSS || !(window as any).CSS.highlights) return;
  try {
    const container = document.getElementById('wa-docx-editor') ||
                      document.getElementById('wa-workspace') || document.body;
    const ranges: Range[] = [];
    const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT, null);
    let node: Node | null;
    while ((node = walker.nextNode())) {
      const text = node.nodeValue || '';
      let idx = 0;
      while ((idx = text.indexOf(textToFind, idx)) !== -1) {
        const r = document.createRange();
        r.setStart(node, idx);
        r.setEnd(node, idx + textToFind.length);
        ranges.push(r);
        idx += textToFind.length;
      }
    }
    if (ranges.length) {
      const HighlightCtor = (window as any).Highlight;
      const hl = new HighlightCtor(ranges[0]);
      for (let i = 1; i < ranges.length; i++) {
        hl.add(ranges[i]);
      }
      (window as any).CSS.highlights.set('wa-accepted-highlight', hl);
      setTimeout(() => { try { (window as any).CSS.highlights.delete('wa-accepted-highlight'); } catch(e) {} }, 3000);
    }
  } catch(e) { console.warn('[WA highlight]', e); }
}

// ── Selection context helpers ──
export function _selectionContextText(selectionContext: any): string {
  if (!selectionContext) return '';
  if (typeof selectionContext === 'string') return selectionContext.trim();
  return String(selectionContext.text || '').trim();
}

export function _selectionContextSourceLabel(selectionContext: any): string {
  if (!selectionContext || typeof selectionContext === 'string') return '';
  const sourceName = String(selectionContext.sourceName || '').trim();
  if (sourceName) return sourceName;
  const sourcePath = String(selectionContext.sourcePath || '').trim();
  return sourcePath ? sourcePath.split(/[\\/]/).pop() || sourcePath : '';
}

export function _selectionContextPreview(selectionContext: any, limit: number = 60): string {
  if (selectionContext && typeof selectionContext === 'object') {
    const previewText = String(selectionContext.previewText || selectionContext.preview_text || '').trim();
    if (previewText) {
      return previewText.length > limit ? previewText.substring(0, limit) + '\u2026' : previewText;
    }
  }
  const text = _selectionContextText(selectionContext);
  if (!text) return '';
  return text.length > limit ? text.substring(0, limit) + '\u2026' : text;
}

export function _createPinnedSelectionContext(text: any, sourceMeta?: any): PinnedSelectionContext | null {
  if (text && typeof text === 'object') {
    const normalizedText = _selectionContextText(text);
    if (!normalizedText) return null;
    const previewText = String(text.previewText || text.preview_text || '').trim();
    const sourcePath = String(text.sourcePath || text.source_path || '').trim();
    const sourceName = String(text.sourceName || text.source_name || '').trim();
    const sourceType = String(text.sourceType || text.source_type || '').trim();
    return {
      text: normalizedText,
      previewText,
      sourcePath,
      sourceName: sourceName || (sourcePath ? sourcePath.split(/[\\/]/).pop() || sourcePath : ''),
      sourceType,
      kind: String(text.kind || text.selectionKind || '').trim(),
      rawText: String(text.rawText || text.raw_text || '').trim(),
      sheetName: String(text.sheetName || text.sheet_name || '').trim(),
      rangeA1: String(text.rangeA1 || text.range_a1 || '').trim(),
      rows: Number(text.rows || 0) || 0,
      cols: Number(text.cols || 0) || 0,
    };
  }

  const normalizedText = String(text || '').trim();
  if (!normalizedText) return null;
  const meta = sourceMeta || _getPinnedSelectionSourceMeta();
  const previewText = String(meta.previewText || meta.preview_text || '').trim();
  const sourcePath = String(meta.sourcePath || meta.source_path || '').trim();
  const sourceName = String(meta.sourceName || meta.source_name || '').trim();
  return {
    text: normalizedText,
    previewText,
    sourcePath,
    sourceName: sourceName || (sourcePath ? sourcePath.split(/[\\/]/).pop() || sourcePath : ''),
    sourceType: String(meta.sourceType || meta.source_type || '').trim(),
  };
}

// ── Unified context bar ──
export function _updateContextBar(opts?: { selection?: string; files?: number; table?: string }): void {
  const bar = $('wa-context-bar');
  if (!bar) return;
  bar.dataset.rule = _WA_EXPLICIT_CONTEXT_RULE;
  const nFiles = (opts && opts.files != null) ? opts.files : (state._aiFileContext ? state._aiFileContext.length : 0);
  const selText = (opts && opts.selection) || '';
  const tableInfo = (opts && opts.table) || '';
  const pinnedSelectionText = _selectionContextText(state.pinnedSelection);
  const pinnedSelectionSource = _selectionContextSourceLabel(state.pinnedSelection);
  const clearSelectionButton = '<button type="button" class="ctx-bar-clear ctx-bar-clear-selection" onclick="WA.clearSelection()" title="\u53d6\u6d88\u9009\u4e2d\u6587\u672c\u4e0a\u4e0b\u6587" aria-label="\u53d6\u6d88\u9009\u62e9">\u53d6\u6d88\u9009\u62e9</button>';

  const parts: string[] = [];

  if (selText) {
    const preview = selText.length > 60 ? selText.substring(0, 60) + '\u2026' : selText;
    parts.push(`<span class="ctx-bar-sel" data-selection-injected="true">\u5df2\u6ce8\u5165\u9009\u4e2d\u6587\u672c\uff1a<b>${_escHtml(preview)}</b>${clearSelectionButton}</span>`);
  } else if (tableInfo) {
    parts.push(`<span class="ctx-bar-sel" data-selection-injected="true">\u5df2\u6ce8\u5165\u9009\u4e2d\u5185\u5bb9\uff1a<b>${_escHtml(tableInfo)}</b>${clearSelectionButton}</span>`);
  } else if (pinnedSelectionText) {
    const preview = _selectionContextPreview(state.pinnedSelection, 60);
    const sourceHint = pinnedSelectionSource
      ? `<span class="ctx-bar-source">\u6765\u81ea <b>${_escHtml(pinnedSelectionSource)}</b></span>`
      : '';
    parts.push(`<span class="ctx-bar-sel" data-selection-injected="true"><span class="ctx-bar-quote"></span>\u5df2\u6ce8\u5165\u9009\u4e2d\u6587\u672c\uff1a<b>${_escHtml(preview)}</b>${sourceHint}${clearSelectionButton}</span>`);
  }

  if (nFiles > 0) {
    parts.push(`<span class="ctx-bar-files">\u5df2\u9644\u52a0 <b>${nFiles} \u4efd\u6587\u4ef6</b><button type="button" class="ctx-bar-clear ctx-bar-clear-files" onclick="WA.clearAIFileContext()" title="\u6e05\u9664\u5168\u90e8\u9644\u52a0\u6587\u4ef6" aria-label="\u6e05\u9664\u9644\u52a0\u6587\u4ef6">\u6e05\u9664\u6587\u4ef6</button></span>`);
  }

  if (parts.length) {
    bar.innerHTML = parts.join('<span class="ctx-bar-sep">\u00b7</span>');
    bar.style.display = 'flex';
  } else {
    bar.innerHTML = '';
    bar.style.display = 'none';
  }

  if (state.fileType === 'docx') {
    const syncReviewSelectionSnapshot = (window as any)._syncReviewSelectionSnapshot;
    const syncDocxReviewToolbar = (window as any)._syncDocxReviewToolbar;
    const renderReviewShell = (window as any)._renderReviewShell;
    const renderReviewSelectionLauncher = (window as any)._renderReviewSelectionLauncher;
    if (typeof syncReviewSelectionSnapshot === 'function') syncReviewSelectionSnapshot();
    if (typeof syncDocxReviewToolbar === 'function') syncDocxReviewToolbar();
    const reviewEditorFocused = typeof (window as any)._isReviewEditorFocused === 'function'
      ? (window as any)._isReviewEditorFocused()
      : false;
    const reviewShellFocused = typeof (window as any)._isReviewShellFocused === 'function'
      ? (window as any)._isReviewShellFocused()
      : false;
    if (state._reviewCenterOpen && !state._editingReviewCommentId && !reviewEditorFocused && !reviewShellFocused && typeof renderReviewShell === 'function') {
      renderReviewShell();
    }
    if (typeof renderReviewSelectionLauncher === 'function') renderReviewSelectionLauncher();
  } else {
    const hideReviewSelectionLauncher = (window as any)._hideReviewSelectionLauncher;
    if (typeof hideReviewSelectionLauncher === 'function') hideReviewSelectionLauncher();
  }
}

export function _pinSelectionChip(text: any, sourceMeta?: any): void {
  const selectionContext = _createPinnedSelectionContext(text, sourceMeta);
  if (!selectionContext) {
    (window as any).WA.clearSelection();
    return;
  }
  state._selectionDismissed = false;
  state.pinnedSelection = selectionContext;
  _updateContextBar();
}

// ── DOCX selection utilities ──
export function _hasUsableDocxSelectionTarget(): boolean {
  if (state.fileType !== 'docx' || !state.activeEditor || !state.activeEditor.editor) {
    return false;
  }
  if (state._selectionDismissed) {
    return false;
  }
  const editorHost = state.activeEditor;
  const selection = editorHost.editor.state && editorHost.editor.state.selection;
  if (selection && selection.from < selection.to) {
    return true;
  }
  const savedSel = editorHost._savedSel;
  if (savedSel && typeof savedSel.from === 'number' && typeof savedSel.to === 'number' && savedSel.from !== savedSel.to) {
    return true;
  }
  return !!editorHost._toolbarSelection;
}

export interface TrimmedDocxSlice {
  text: string;
  leadingLength: number;
}

export function _trimDocxAnchorSlice(rawText: string): TrimmedDocxSlice | null {
  const sourceText = String(rawText || '');
  if (!sourceText) return null;
  const trimmedText = sourceText.trim();
  if (!trimmedText) return null;
  const leadingMatch = sourceText.match(/^\s*/);
  return {
    text: trimmedText,
    leadingLength: leadingMatch ? leadingMatch[0].length : 0,
  };
}

export function _countTextOccurrencesBefore(sourceText: string, targetText: string, endOffset: number): number {
  const haystack = String(sourceText || '');
  const needle = String(targetText || '');
  const limit = Math.max(0, Number(endOffset) || 0);
  if (!haystack || !needle || limit <= 0) return 0;
  let count = 0;
  let cursor = 0;
  while (cursor < limit) {
    const hitIndex = haystack.indexOf(needle, cursor);
    if (hitIndex === -1 || hitIndex >= limit) break;
    count += 1;
    cursor = hitIndex + Math.max(needle.length, 1);
  }
  return count;
}

export function _buildDocxTextAnchorMeta(editorHost: any, from: number, to: number): DocxAnchorMeta | null {
  const liveEditor = editorHost && editorHost.editor;
  const liveDoc = liveEditor && liveEditor.state && liveEditor.state.doc;
  if (!liveDoc) return null;
  const selectionFrom = Math.max(0, Number(from) || 0);
  const selectionTo = Math.max(selectionFrom, Number(to) || 0);
  if (selectionTo <= selectionFrom) return null;

  const fullText = String(liveDoc.textBetween(0, liveDoc.content.size, '\n', '\n') || '');
  const rawSelectionText = String(liveDoc.textBetween(selectionFrom, selectionTo, '\n', '\n') || '');
  const trimmedSelection = _trimDocxAnchorSlice(rawSelectionText);
  if (!trimmedSelection || !trimmedSelection.text) return null;

  const leadingText = String(liveDoc.textBetween(0, selectionFrom, '\n', '\n') || '');
  const anchorStartOffset = Math.max(0, leadingText.length + trimmedSelection.leadingLength);
  const anchorEndOffset = Math.max(anchorStartOffset, anchorStartOffset + trimmedSelection.text.length);

  return {
    anchor_text: trimmedSelection.text,
    anchor_start_offset: anchorStartOffset,
    anchor_end_offset: anchorEndOffset,
    anchor_occurrence: _countTextOccurrencesBefore(fullText, trimmedSelection.text, anchorStartOffset),
    anchor_context_before: fullText.slice(Math.max(0, anchorStartOffset - 48), anchorStartOffset),
    anchor_context_after: fullText.slice(anchorEndOffset, anchorEndOffset + 48),
  };
}

export function _getDocxSelectionPayload(options?: { includeOverlay?: boolean; allowStaleFallback?: boolean; includeAnchorMeta?: boolean }): DocxSelectionPayload | null {
  const opts = options || {};
  const includeOverlay = opts.includeOverlay !== false;
  const allowStaleFallback = opts.allowStaleFallback !== false;
  const includeAnchorMeta = !!opts.includeAnchorMeta;

  if (state.fileType !== 'docx') return null;
  if (state._selectionDismissed) return null;

  const _makePayload = (kind: string, rawText: string, extras: any = {}): DocxSelectionPayload | null => {
    const normalizedText = String(rawText || '').trim();
    if (!normalizedText) return null;
    const normalizedPreview = String(extras.previewText || '').trim() || normalizedText;
    const payload: DocxSelectionPayload = {
      kind,
      rawText: normalizedText,
      aiText: String(extras.aiText || normalizedText).trim(),
      previewText: normalizedPreview,
      countLabel: String(extras.countLabel || '').trim(),
      tableElement: extras.tableElement || null,
    };
    const normalizedAnchorMeta = (extras.anchorMeta && typeof extras.anchorMeta === 'object')
      ? (_cloneSerializable(extras.anchorMeta, {}) || {})
      : null;
    if (normalizedAnchorMeta) {
      Object.assign(payload, normalizedAnchorMeta);
    }
    return payload;
  };

  if (includeOverlay) {
    const overlaySelection = _safeGetDocxHdrFtrSelectionInfo();
    if (overlaySelection && overlaySelection.text) {
      const overlayText = String(overlaySelection.text || '').trim();
      return _makePayload('text', overlayText, {
        countLabel: `${overlayText.replace(/\s/g, '').length}\u5b57`,
      });
    }
  }

  const editorHost = state.activeEditor;
  if (!editorHost) return null;
  const _ed = editorHost.editor;
  const _s = _ed && _ed.state && _ed.state.selection;
  const liveTextAnchorMeta = (includeAnchorMeta && _ed && _s && _s.from < _s.to)
    ? _buildDocxTextAnchorMeta(editorHost, _s.from, _s.to)
    : null;

  if (typeof editorHost.getWholeTableSelectionInfo === 'function') {
    const wholeTableInfo = editorHost.getWholeTableSelectionInfo();
    const wholeTableText = String(wholeTableInfo && wholeTableInfo.text || '').trim();
    if (wholeTableText) {
      const rows = Math.max(0, Number(wholeTableInfo.rows) || 0);
      const cols = Math.max(0, Number(wholeTableInfo.cols) || 0);
      const tableLabel = rows > 0 && cols > 0
        ? `${rows}\u00d7${cols} \u8868\u683c`
        : (rows > 0 ? `${rows} \u884c\u8868\u683c` : '\u8868\u683c');
      return _makePayload('table', wholeTableText, {
        previewText: tableLabel,
        countLabel: tableLabel,
        aiText: `[\u5f53\u524d\u9009\u4e2d\u8868\u683c\u6570\u636e]:\n${wholeTableText}\n`,
        tableElement: wholeTableInfo.tableElement || null,
      });
    }
  }

  if (typeof editorHost.getCellSelectionInfo === 'function') {
    const cellSelectionInfo = editorHost.getCellSelectionInfo();
    const cellSelectionText = String(cellSelectionInfo && cellSelectionInfo.text || '').trim();
    if (cellSelectionText) {
      const rows = Math.max(0, Number(cellSelectionInfo.rows) || 0);
      const cols = Math.max(0, Number(cellSelectionInfo.cols) || 0);
      const selectedCells = Math.max(0, Number(cellSelectionInfo.selectedCells) || 0);
      const cellLabel = rows > 0 && cols > 0
        ? `${rows}\u00d7${cols} \u5355\u5143\u683c\u533a\u57df`
        : (selectedCells > 0 ? `${selectedCells} \u4e2a\u5355\u5143\u683c` : '\u5355\u5143\u683c');
      return _makePayload('cell', cellSelectionText, {
        previewText: cellLabel,
        countLabel: cellLabel,
        aiText: `[\u5f53\u524d\u9009\u4e2d\u8868\u683c\u6570\u636e]:\n${cellSelectionText}\n`,
        tableElement: cellSelectionInfo.tableElement || null,
      });
    }
  }

  if (typeof editorHost.getSelectionTextForAI === 'function') {
    const selectionTextForAI = String(editorHost.getSelectionTextForAI() || '').trim();
    if (selectionTextForAI) {
      return _makePayload('text', (liveTextAnchorMeta && liveTextAnchorMeta.anchor_text) || selectionTextForAI, {
        countLabel: `${selectionTextForAI.replace(/\s/g, '').length}\u5b57`,
        anchorMeta: liveTextAnchorMeta,
      });
    }
  }

  if (_hasUsableDocxSelectionTarget()) {
    if (_ed && _s && _s.from < _s.to) {
      const liveText = (_ed.state.doc.textBetween(_s.from, _s.to, ' ') || '').trim();
      if (liveText) {
        return _makePayload('text', (liveTextAnchorMeta && liveTextAnchorMeta.anchor_text) || liveText, {
          countLabel: `${liveText.replace(/\s/g, '').length}\u5b57`,
          anchorMeta: liveTextAnchorMeta,
        });
      }
    }
  }

  if (allowStaleFallback) {
    const fallbackText = String(lastSelectionText || '').trim();
    if (fallbackText) {
      return _makePayload('text', fallbackText, {
        countLabel: `${fallbackText.replace(/\s/g, '').length}\u5b57`,
      });
    }
  }

  return null;
}

export function _getDocxSelectionTextForAI(): string {
  const docxSelection = _getDocxSelectionPayload();
  return docxSelection ? docxSelection.aiText : '';
}

export function _getActiveTextEditorSelectionForAI(): string {
  const editor = state.activeEditor;
  const textarea = editor && editor._ta ? editor._ta : $('wa-text-content');
  if (!textarea || typeof textarea.value !== 'string') return '';
  if (typeof textarea.selectionStart !== 'number' || typeof textarea.selectionEnd !== 'number') return '';
  const start = Math.max(0, Number(textarea.selectionStart) || 0);
  const end = Math.max(start, Number(textarea.selectionEnd) || 0);
  if (end <= start) return '';
  const liveText = String(textarea.value || '').slice(start, end).trim();
  if (liveText) lastSelectionText = liveText;
  return liveText;
}

export function _getLiveEditorSelectionForAI(options?: { allowStaleFallback?: boolean }): any {
  const allowStaleFallback = !options || options.allowStaleFallback !== false;
  if (state.fileType === 'docx') {
    const docxSelection = _getDocxSelectionPayload({ allowStaleFallback });
    return docxSelection
      ? Object.assign({}, docxSelection, {
          text: docxSelection.aiText,
          sourceType: 'docx',
          selectionKind: docxSelection.kind,
        })
      : null;
  }
  if (state.fileType === 'xlsx' && state.activeEditor && typeof state.activeEditor.getSelectionPayload === 'function') {
    const payload = state.activeEditor.getSelectionPayload();
    if (payload && String(payload.aiText || payload.text || '').trim()) {
      return Object.assign({}, payload, {
        text: String(payload.aiText || payload.text || '').trim(),
        sourceType: 'xlsx',
        selectionKind: payload.kind || 'xlsx-range',
      });
    }
  }
  let sel: string = _getActiveTextEditorSelectionForAI();
  if (!sel && allowStaleFallback) sel = lastSelectionText;
  if (!sel && state.fileType === 'xlsx' && state.activeEditor) {
    const rangeText = state.activeEditor.getContent();
    if (rangeText && !rangeText.includes('\u672a\u9009\u4e2d\u533a\u57df')) sel = rangeText;
  }
  return (sel || '').trim();
}

// ── PPTX Table Text Extract ──
export function _normalizePptxTableSelection(selection: any, maxRows: number, maxCols: number): PptxTableSelection | null {
  if (!selection || maxRows <= 0 || maxCols <= 0) return null;

  const anchorRow = Math.max(0, Math.min(maxRows - 1, Number(selection.anchorRow)));
  const anchorCol = Math.max(0, Math.min(maxCols - 1, Number(selection.anchorCol)));
  const headRow = Math.max(0, Math.min(maxRows - 1, Number(selection.headRow)));
  const headCol = Math.max(0, Math.min(maxCols - 1, Number(selection.headCol)));
  if (![anchorRow, anchorCol, headRow, headCol].every(Number.isFinite)) return null;

  const startRow = Math.min(anchorRow, headRow);
  const endRow = Math.max(anchorRow, headRow);
  const startCol = Math.min(anchorCol, headCol);
  const endCol = Math.max(anchorCol, headCol);

  return { anchorRow, anchorCol, headRow, headCol, startRow, endRow, startCol, endCol, rows: endRow - startRow + 1, cols: endCol - startCol + 1 };
}

export function _extractPptxTableText(shape: any, selection?: any): string {
  const rows = shape.table_rows || 0;
  const cols = shape.table_cols || 0;
  const range = _normalizePptxTableSelection(selection, rows, cols);
  const cellDataMap: Record<string, any> = {};
  (shape.cells || []).forEach((c: any) => { cellDataMap[c.row + '_' + c.col] = c; });
  const lines: string[] = [];
  const startRow = range ? range.startRow : 0;
  const endRow = range ? range.endRow : rows - 1;
  const startCol = range ? range.startCol : 0;
  const endCol = range ? range.endCol : cols - 1;
  for (let r = startRow; r <= endRow; r++) {
    const rowData: string[] = [];
    for (let c = startCol; c <= endCol; c++) {
      const cell = cellDataMap[r + '_' + c];
      rowData.push((cell && cell.text) ? cell.text.replace(/[\t\n]/g, ' ').trim() : '');
    }
    lines.push(rowData.join('\t'));
  }
  return lines.join('\n');
}

// ── HTML Table Text Extract ──
export function _extractHtmlTableText(tblEl: HTMLTableElement): string {
  const lines: string[] = [];
  for (let r = 0; r < tblEl.rows.length; r++) {
    const row = tblEl.rows[r];
    const cells: string[] = [];
    for (let c = 0; c < row.cells.length; c++) {
      cells.push(row.cells[c].textContent!.trim().replace(/[\t\n]/g, ' '));
    }
    lines.push(cells.join('\t'));
  }
  return lines.join('\n');
}

// ── Show tooltip near a DOM element ──
export function _showTableTooltipNear(el: HTMLElement): void {
  const tt = $('wa-pdf-tooltip');
  if (!tt || !el) return;
  const rect = el.getBoundingClientRect();
  const GAP = 10;
  const vw = window.innerWidth;
  tt.style.visibility = 'hidden';
  tt.style.display = 'flex';
  const ttW = tt.offsetWidth || 260;
  tt.style.display = 'none';
  tt.style.visibility = '';
  const cx = rect.left + rect.width / 2;
  let left = cx - ttW / 2;
  left = Math.max(8, Math.min(left, vw - ttW - 8));
  let top = rect.top - 42 - GAP;
  if (top < 8) top = rect.bottom + GAP;
  tt.style.left = left + 'px';
  tt.style.top = top + 'px';
  tt.style.display = 'flex';
}

// ── Selection geometry helper ──
export function _getSelectionViewportBounds(): SelectionBounds | null {
  const ws = window.getSelection();
  if (!ws || ws.isCollapsed || !ws.rangeCount) return null;
  const range = ws.getRangeAt(0);

  let top = Infinity, bottom = -Infinity;
  let minLeft = Infinity, maxRight = -Infinity;
  const rects = range.getClientRects();
  for (let i = 0; i < rects.length; i++) {
    const r = rects[i];
    if (r.height <= 0 || r.width <= 0) continue;
    if (r.top < top) top = r.top;
    if (r.bottom > bottom) bottom = r.bottom;
    if (r.left < minLeft) minLeft = r.left;
    if (r.right > maxRight) maxRight = r.right;
  }

  if (top === Infinity) {
    const br = range.getBoundingClientRect();
    if (!br || br.height <= 0) return null;
    top = br.top;
    bottom = br.bottom;
    minLeft = br.left;
    maxRight = br.right;
  }

  let centerX = window.innerWidth / 2;
  const refEl = document.querySelector('#wa-docx-editor .koto-zoom-wrapper') as HTMLElement
             || document.querySelector('#wa-docx-editor .ProseMirror') as HTMLElement
             || document.querySelector('#wa-pptx-stage') as HTMLElement
             || document.querySelector('#wa-pdf-viewer') as HTMLElement;
  if (refEl) {
    const rr = refEl.getBoundingClientRect();
    centerX = rr.left + rr.width / 2;
  } else {
    if (minLeft !== Infinity && maxRight !== -Infinity) centerX = (minLeft + maxRight) / 2;
  }

  return { top, bottom, left: minLeft !== Infinity ? minLeft : centerX, right: maxRight !== -Infinity ? maxRight : centerX, centerX };
}

// ── Position the AI quick-action toolbar ──
export function _positionSelectionToolbar(overrideRect?: ToolbarConfig | null): void {
  const tt = $('wa-pdf-tooltip');
  if (!tt) return;

  if (tt.parentElement !== document.body) {
    document.body.appendChild(tt);
  }

  let selTop: number, selBottom: number, selCenterX: number;
  if (overrideRect) {
    selCenterX = overrideRect.centerX;
    selTop = overrideRect.top;
    selBottom = overrideRect.bottom;
  } else {
    const bounds = _getSelectionViewportBounds();
    if (!bounds) return;
    selTop = bounds.top;
    selBottom = bounds.bottom;
    selCenterX = bounds.centerX;
  }

  tt.style.visibility = 'hidden';
  tt.style.display = 'flex';
  const ttW = tt.offsetWidth || 220;
  const ttH = tt.offsetHeight || 36;
  tt.style.display = 'none';
  tt.style.visibility = '';

  const GAP = 12;
  const vw = window.innerWidth;
  const vh = window.innerHeight;

  let left = selCenterX - ttW / 2;
  left = Math.max(8, Math.min(left, vw - ttW - 8));

  let top = selBottom + GAP;
  if (top + ttH > vh - 8) top = selTop - ttH - GAP;
  if (top < 8) top = selBottom + GAP;

  top = Math.max(8, Math.min(top, vh - ttH - 8));

  tt.style.left = left + 'px';
  tt.style.top = top + 'px';
  tt.style.display = 'flex';
}

// ── Mouse event helper ──
export function _evtEl(target: EventTarget | null): Element | null {
  if (!target) return null;
  if ((target as Node).nodeType === Node.TEXT_NODE) return (target as Node).parentElement;
  return target as Element;
}

function _selectionPayloadForToolbar(options?: { allowStaleFallback?: boolean }): { text: string; previewText: string; countLabel: string; raw: any } | null {
  const liveSelection = _getLiveEditorSelectionForAI(options);
  const docxSelection = liveSelection && typeof liveSelection === 'object' ? liveSelection : null;
  const text = typeof liveSelection === 'string'
    ? liveSelection
    : (docxSelection ? String(docxSelection.text || '') : '');
  const normalized = String(text || '').trim();
  if (!normalized) return null;
  const previewText = docxSelection && docxSelection.previewText
    ? String(docxSelection.previewText || '').trim()
    : normalized;
  const countLabel = docxSelection && docxSelection.countLabel
    ? String(docxSelection.countLabel || '').trim()
    : `${normalized.replace(/\s/g, '').length}字`;
  return { text: normalized, previewText, countLabel, raw: docxSelection || normalized };
}

function _setSelectionToolbarCount(label: string): void {
  const countEl = $('wa-tooltip-count');
  if (countEl) countEl.textContent = label;
}

function _isSelectionToolbarTarget(el: Element | null): boolean {
  return !!(el && (el.id === 'wa-pdf-tooltip' || (el.closest && el.closest('#wa-pdf-tooltip'))));
}

function _isAIInputTarget(el: Element | null): boolean {
  return !!(el && el.closest && (
    el.closest('#wa-ai-input-area') ||
    el.closest('#wa-user-input') ||
    el.closest('#wa-context-bar')
  ));
}

function _isInsideWorkspaceEditor(el: Element | null): boolean {
  return !!(el && el.closest && (
    el.closest('#wa-editor-content') ||
    el.closest('#wa-text-editor') ||
    el.closest('#wa-text-content') ||
    el.closest('#wa-docx-editor') ||
    el.closest('#wa-pptx-editor') ||
    el.closest('#wa-pptx-stage') ||
    el.closest('#wa-pdf-viewer') ||
    el.closest('#wa-review-shell') ||
    el.closest('#wa-review-selection-launcher') ||
    el.closest('.wa-sel-toolbar')
  ));
}

function _clearSelectionInjectionIfIdle(): void {
  const activeEl = document.activeElement as Element | null;
  if (_isSelectionToolbarTarget(activeEl) || _isAIInputTarget(activeEl)) return;
  if (!state.pinnedSelection && !lastSelectionText) return;
  clearSelection();
}

function _showSelectionToolbarForPayload(payload: { text: string; previewText: string; countLabel: string; raw: any }): void {
  state._selectionDismissed = false;
  lastSelectionText = payload.text;
  _setSelectionToolbarCount(payload.countLabel);
  const activeEl = document.activeElement as HTMLElement | null;
  const textEditor = $('wa-text-content') as HTMLTextAreaElement | null;
  const textEditorHasSelection = textEditor
    && typeof textEditor.selectionStart === 'number'
    && typeof textEditor.selectionEnd === 'number'
    && textEditor.selectionEnd > textEditor.selectionStart;
  const activeRect = textEditorHasSelection
    ? textEditor.getBoundingClientRect()
    : activeEl && (activeEl.tagName === 'TEXTAREA' || activeEl.tagName === 'INPUT')
    ? activeEl.getBoundingClientRect()
    : null;
  if (activeRect && activeRect.width > 0 && activeRect.height > 0) {
    _positionSelectionToolbar({
      centerX: activeRect.left + activeRect.width / 2,
      top: activeRect.top,
      bottom: activeRect.bottom,
    });
  } else {
    _positionSelectionToolbar();
  }
  if (payload.previewText && payload.previewText !== payload.text) {
    _updateContextBar({ table: payload.previewText });
  } else {
    _updateContextBar({ selection: payload.text });
  }
}

export function _showSelectionToolbarForCurrentSelection(): boolean {
  const payload = _selectionPayloadForToolbar({ allowStaleFallback: false });
  if (!payload) {
    const tt = $('wa-pdf-tooltip');
    if (tt) tt.style.display = 'none';
    _clearSelectionInjectionIfIdle();
    return false;
  }
  _showSelectionToolbarForPayload(payload);
  return true;
}

export function sendSelectionToAI(): void {
  const payload = _selectionPayloadForToolbar();
  if (!payload) return;
  _saveEditorRange();
  _applyPinnedHighlight();
  _pinSelectionChip(payload.raw);
  const tt = $('wa-pdf-tooltip');
  if (tt) tt.style.display = 'none';
  _expandWAPanel();
  const input = $('wa-user-input') as HTMLTextAreaElement | null;
  if (input) input.focus();
}

export function closeSelectionToolbar(): void {
  state._selectionDismissed = true;
  const tt = $('wa-pdf-tooltip');
  if (tt) tt.style.display = 'none';
  try { window.getSelection()?.removeAllRanges(); } catch (_) { /* allowed to fail */ }
}

export function clearSelection(): void {
  state.pinnedSelection = null;
  state.lastPinnedSel = null;
  state._selectionDismissed = true;
  lastSelectionText = '';
  try { window.getSelection()?.removeAllRanges(); } catch (_) { /* allowed to fail */ }
  try {
    if (state.activeEditor) {
      state.activeEditor._savedSel = null;
      state.activeEditor._toolbarSelection = null;
      state.activeEditor._lastTableText = null;
      state.activeEditor._lastTableRows = 0;
      state.activeEditor._lastTableCols = 0;
    }
  } catch (e) { console.warn("[Koto]", e) }
  const tt = $('wa-pdf-tooltip');
  if (tt) tt.style.display = 'none';
  _updateContextBar();
  _clearPinnedHighlight();
}

export function _hideDocxHoverBar(): void {
  const legacy = (window as any)._hideDocxHoverBar;
  if (typeof legacy === 'function' && legacy !== _hideDocxHoverBar) {
    try {
      legacy();
      return;
    } catch (_) { /* fall through to local reset */ }
  }
  const hoverbar = $('wa-docx-hoverbar') || (window as any)._docxHbEl;
  const colorPicker = $('wa-docx-cp') || (window as any)._docxCpEl;
  if (hoverbar) hoverbar.style.display = 'none';
  if (colorPicker) colorPicker.style.display = 'none';
}

export function _resetDocxSelection(): void {
  (window as any)._docxNativeSelBottom = 0;
  _hideDocxHoverBar();
  const hideLauncher = (window as any)._hideReviewSelectionLauncher;
  if (typeof hideLauncher === 'function') {
    try { hideLauncher(); } catch (_) { /* noop */ }
  }
  const tooltip = $('wa-pdf-tooltip');
  if (tooltip) tooltip.style.display = 'none';
  lastSelectionText = '';
  _updateContextBar();
  if (!state._aiFileContext || !state._aiFileContext.length) {
    const updateSubject = (window as any)._updateSubjectBar;
    if (typeof updateSubject === 'function') {
      try { updateSubject(state.fileName, state.fileType); } catch (_) { /* noop */ }
    }
  }
}

function _installSelectionToolbarEvents(): void {
  if ((window as any).__waSelectionToolbarEventsInstalled) return;
  (window as any).__waSelectionToolbarEventsInstalled = true;

  document.addEventListener('mouseup', (event: MouseEvent) => {
    const el = _evtEl(event.target);
    if (event.button === 2 || _isSelectionToolbarTarget(el)) return;
    if (!_isInsideWorkspaceEditor(el)) {
      const tt = $('wa-pdf-tooltip');
      if (tt) tt.style.display = 'none';
      if (!_isAIInputTarget(el)) {
        _clearSelectionInjectionIfIdle();
      } else if (!state.pinnedSelection) {
        _updateContextBar();
      }
      return;
    }

    window.setTimeout(() => {
      if (_showSelectionToolbarForCurrentSelection()) return;
    }, 0);
  });

  document.addEventListener('mousedown', (event: MouseEvent) => {
    const el = _evtEl(event.target);
    if (!_isSelectionToolbarTarget(el)) {
      const tt = $('wa-pdf-tooltip');
      if (tt) tt.style.display = 'none';
    }
  });

  document.addEventListener('selectionchange', () => {
    window.setTimeout(() => {
      if (state._selectionDismissed) return;
      if (_showSelectionToolbarForCurrentSelection()) return;
    }, 100);
  });

  document.addEventListener('keyup', (event: KeyboardEvent) => {
    const el = _evtEl(event.target);
    if (!_isInsideWorkspaceEditor(el)) return;
    window.setTimeout(() => {
      _showSelectionToolbarForCurrentSelection();
    }, 0);
  });

  const input = $('wa-user-input');
  if (input) {
    input.addEventListener('mousedown', () => {
      if (state._selectionDismissed) return;
      const payload = _selectionPayloadForToolbar();
      if (!payload) return;
      _saveEditorRange();
      _applyPinnedHighlight();
      _pinSelectionChip(payload.raw);
      const tt = $('wa-pdf-tooltip');
      if (tt) tt.style.display = 'none';
    });
  }
}

// ── Backward compat ──
if (typeof window !== 'undefined') {
  (window as any).WA = (window as any).WA || {};
  (window as any).WA._updateContextBar = _updateContextBar;
  (window as any).WA._getDocxSelectionPayload = _getDocxSelectionPayload;
  (window as any).WA._getDocxSelectionTextForAI = _getDocxSelectionTextForAI;
  (window as any).WA._extractPptxTableText = _extractPptxTableText;
  (window as any).WA._extractHtmlTableText = _extractHtmlTableText;
  (window as any).WA._positionSelectionToolbar = _positionSelectionToolbar;
  (window as any).WA._getSelectionViewportBounds = _getSelectionViewportBounds;
  (window as any).WA._getLiveEditorSelectionForAI = _getLiveEditorSelectionForAI;
  (window as any).WA._showSelectionToolbarForCurrentSelection = _showSelectionToolbarForCurrentSelection;
  (window as any).WA._applyPinnedHighlight = _applyPinnedHighlight;
  (window as any).WA._clearPinnedHighlight = _clearPinnedHighlight;
  (window as any).WA._applyTemporaryHighlight = _applyTemporaryHighlight;
  (window as any).WA.sendSelectionToAI = sendSelectionToAI;
  (window as any).WA.closeSelectionToolbar = closeSelectionToolbar;
  (window as any).WA.clearSelection = clearSelection;
  (window as any)._hideDocxHoverBar = _hideDocxHoverBar;
  (window as any)._resetDocxSelection = _resetDocxSelection;
  (window as any)._pinSelectionChip = _pinSelectionChip;
  _installSelectionToolbarEvents();
}
