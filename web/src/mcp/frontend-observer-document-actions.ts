// @ts-nocheck
import { getWorkspaceRuntime as _workspaceRuntime } from './workspace-runtime-inspector';
import { getFeatureRegistry, registerFeatures } from '../shared/feature-registry';
import { applyDocxTextPatch, assertDocumentPatchText, readDocxBlockContext, resolveDocxTextAnchor, undoDocxTextPatch } from './document-semantic-patch';
import { FrontendAction, _argToText, _isVisible, _originalFetch, _targetSummary } from './frontend-observer';
import { _findTarget, _limitString, _safeJsonClone, _workspaceStateDetails, _currentSelectionDetails } from './frontend-observer-targeting';

function _editableTextTarget(action: FrontendAction): HTMLInputElement | HTMLTextAreaElement {
  const target = _findTarget(action) || document.getElementById('wa-text-content');
  if (!(target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement)) {
    throw new Error('Text editing requires an input or textarea target');
  }
  return target;
}

function _notifyTextEdited(target: HTMLInputElement | HTMLTextAreaElement): void {
  const event = new InputEvent('input', { bubbles: true, inputType: 'insertText', data: '' });
  Object.defineProperty(event, 'kotoSkipDiskWrite', { value: true });
  target.dispatchEvent(event);
  target.dispatchEvent(new Event('change', { bubbles: true }));
  const wa = getFeatureRegistry() || {};
  if (typeof wa.scheduleAutoSave === 'function') {
    wa.scheduleAutoSave({ skipDiskWrite: true });
  }
}

export function _selectTextRange(action: FrontendAction): Record<string, unknown> {
  const target = _editableTextTarget(action);
  const length = target.value.length;
  const selectAll = action.options?.all === true || String(action.value || '').toLowerCase() === 'all';
  const rawStart = selectAll ? 0 : Number(action.options?.start ?? action.options?.selectionStart ?? 0);
  const rawEnd = selectAll ? length : Number(action.options?.end ?? action.options?.selectionEnd ?? rawStart);
  const start = Math.max(0, Math.min(length, Number.isFinite(rawStart) ? rawStart : 0));
  const end = Math.max(start, Math.min(length, Number.isFinite(rawEnd) ? rawEnd : start));
  target.focus();
  target.setSelectionRange(start, end);
  target.dispatchEvent(new Event('select', { bubbles: true }));
  return {
    target: _targetSummary(target),
    selectionStart: start,
    selectionEnd: end,
    selectedText: _limitString(target.value.slice(start, end), Number(action.options?.maxChars || 4000)),
  };
}

export function _replaceTextSelection(action: FrontendAction): Record<string, unknown> {
  const target = _editableTextTarget(action);
  const replacement = String(action.value ?? action.text ?? '');
  const length = target.value.length;
  const start = Math.max(0, Math.min(length, Number(target.selectionStart || 0)));
  const end = Math.max(start, Math.min(length, Number(target.selectionEnd || start)));
  const before = target.value.slice(0, start);
  const removed = target.value.slice(start, end);
  const after = target.value.slice(end);
  target.focus();
  target.value = `${before}${replacement}${after}`;
  const caret = before.length + replacement.length;
  target.setSelectionRange(caret, caret);
  _notifyTextEdited(target);
  return {
    target: _targetSummary(target),
    selectionStart: start,
    selectionEnd: end,
    insertedLength: replacement.length,
    removedText: _limitString(removed, Number(action.options?.maxChars || 4000)),
    state: _workspaceStateDetails(),
    content: _limitString(target.value, Number(action.options?.maxChars || 4000)),
  };
}

export function _setEditorContent(action: FrontendAction): Record<string, unknown> {
  const target = _editableTextTarget(action);
  const content = String(action.value ?? action.text ?? '');
  target.focus();
  target.value = content;
  const caret = Math.max(0, Math.min(content.length, Number(action.options?.caret ?? content.length)));
  target.setSelectionRange(caret, caret);
  _notifyTextEdited(target);
  return {
    target: _targetSummary(target),
    length: content.length,
    caret,
    state: _workspaceStateDetails(),
    content: _limitString(content, Number(action.options?.maxChars || 4000)),
  };
}

function _normalizeDocxText(value: unknown): string {
  return String(value ?? '').replace(/\s+/g, ' ').trim();
}

function _numberOption(action: FrontendAction, names: string[]): number | null {
  for (const name of names) {
    const value = (action.options || {})[name];
    if (value === undefined || value === null || value === '') continue;
    const numeric = Number(value);
    if (Number.isFinite(numeric)) return numeric;
  }
  return null;
}

function _stringOption(action: FrontendAction, names: string[]): string {
  for (const name of names) {
    const value = (action.options || {})[name];
    if (value !== undefined && value !== null && String(value) !== '') return String(value);
  }
  return '';
}

function _docxContextMatches(actual: string, expected: string, side: 'before' | 'after'): boolean {
  const actualNorm = _normalizeDocxText(actual);
  const expectedNorm = _normalizeDocxText(expected);
  if (!expectedNorm) return true;
  if (!actualNorm) return false;
  const needle = side === 'before' ? expectedNorm.slice(-80) : expectedNorm.slice(0, 80);
  return side === 'before'
    ? actualNorm.endsWith(needle) || actualNorm.includes(needle)
    : actualNorm.startsWith(needle) || actualNorm.includes(needle);
}

type DocxLinearChar = {
  ch: string;
  pos: number | null;
};

function _buildDocxLinearTextMap(doc: any): { text: string; chars: DocxLinearChar[] } {
  const chars: DocxLinearChar[] = [];
  let sawTextBlock = false;
  doc.descendants((node: any, pos: number) => {
    if (node?.isTextblock) {
      if (sawTextBlock) chars.push({ ch: '\n', pos: null });
      sawTextBlock = true;
      return true;
    }
    if (!node?.isText || typeof node.text !== 'string') return true;
    for (let index = 0; index < node.text.length; index += 1) {
      chars.push({ ch: node.text[index], pos: pos + index });
    }
    return true;
  });
  return { text: chars.map((item) => item.ch).join(''), chars };
}

function _docxRangeFromLinearMatch(
  doc: any,
  chars: DocxLinearChar[],
  start: number,
  length: number,
): Record<string, unknown> | null {
  const end = start + length;
  const matchedChars = chars.slice(start, end);
  if (!matchedChars.length) return null;
  const firstMapped = matchedChars.find((item) => Number.isFinite(item.pos));
  const lastMapped = [...matchedChars].reverse().find((item) => Number.isFinite(item.pos));
  if (!firstMapped || !lastMapped) return null;
  if (matchedChars.some((item) => item.pos === null)) {
    return {
      unsupported: true,
      reason: 'DOCX anchor spans a block separator; cross-paragraph replacement is not supported yet',
    };
  }
  const from = Number(firstMapped.pos);
  const to = Number(lastMapped.pos) + 1;
  return {
    from,
    to,
    text: String(doc.textBetween(from, to, '\n', '\n') || ''),
  };
}

function _resolveDocxAnchorRange(pm: any, action: FrontendAction): Record<string, unknown> {
  const doc = pm?.state?.doc;
  if (!doc || typeof doc.descendants !== 'function') throw new Error('DOCX ProseMirror document is not available');
  const options = action.options || {};
  const anchorText = String(
    options.anchorText
    ?? options.anchor_text
    ?? options.original
    ?? options.originalText
    ?? options.original_text
    ?? action.selector
    ?? action.text
    ?? ''
  );
  if (!anchorText) throw new Error('replace_docx_anchor_text requires options.anchorText or action.text');
  const wantedOccurrence = _numberOption(action, ['anchorOccurrence', 'anchor_occurrence', 'occurrence']);
  const wantedStart = _numberOption(action, ['anchorStartOffset', 'anchor_start_offset', 'startOffset', 'start']);
  const contextBefore = _stringOption(action, ['contextBefore', 'anchor_context_before']);
  const contextAfter = _stringOption(action, ['contextAfter', 'anchor_context_after']);
  const linear = _buildDocxLinearTextMap(doc);
  const fullText = linear.text || String(doc.textBetween(0, doc.content?.size || doc.nodeSize || 0, '\n', '\n') || '');
  const candidates: Record<string, unknown>[] = [];
  let occurrence = 0;
  let cursor = 0;
  while (cursor <= fullText.length) {
    const start = fullText.indexOf(anchorText, cursor);
    if (start < 0) break;
    const mappedRange = _docxRangeFromLinearMatch(doc, linear.chars, start, anchorText.length);
    if (mappedRange?.unsupported) {
      candidates.push({
        ...mappedRange,
        occurrence,
        linearStart: start,
        linearEnd: start + anchorText.length,
        text: anchorText,
        leadingLength: start,
        contextBefore: fullText.slice(Math.max(0, start - 160), start),
        contextAfter: fullText.slice(start + anchorText.length, start + anchorText.length + 160),
      });
    } else if (mappedRange) {
      const from = Number(mappedRange.from);
      const to = Number(mappedRange.to);
      candidates.push({
        from,
        to,
        occurrence,
        linearStart: start,
        linearEnd: start + anchorText.length,
        text: mappedRange.text,
        leadingLength: start,
        contextBefore: fullText.slice(Math.max(0, start - 160), start),
        contextAfter: fullText.slice(start + anchorText.length, start + anchorText.length + 160),
      });
    }
    occurrence += 1;
    cursor = start + Math.max(anchorText.length, 1);
  }
  if (!candidates.length) {
    throw new Error('DOCX anchor text not found in document text');
  }
  const scored = candidates
    .map((candidate) => {
      let score = 0;
      if (candidate.unsupported) score -= 1000;
      if (wantedOccurrence !== null && Number(candidate.occurrence) === wantedOccurrence) score += 100;
      if (wantedStart !== null) score += Math.max(0, 30 - Math.abs(Number(candidate.leadingLength) - wantedStart));
      if (_docxContextMatches(String(candidate.contextBefore || ''), contextBefore, 'before')) score += contextBefore ? 20 : 0;
      else if (contextBefore) score -= 50;
      if (_docxContextMatches(String(candidate.contextAfter || ''), contextAfter, 'after')) score += contextAfter ? 20 : 0;
      else if (contextAfter) score -= 50;
      if (String(candidate.text) === anchorText) score += 10;
      return { candidate, score };
    })
    .filter((item) => {
      if (wantedOccurrence !== null && Number(item.candidate.occurrence) !== wantedOccurrence) return false;
      if (contextBefore && !_docxContextMatches(String(item.candidate.contextBefore || ''), contextBefore, 'before')) return false;
      if (contextAfter && !_docxContextMatches(String(item.candidate.contextAfter || ''), contextAfter, 'after')) return false;
      return true;
    })
    .sort((a, b) => b.score - a.score);
  if (!scored.length) throw new Error('DOCX anchor candidates were found, but none matched the supplied occurrence/context');
  if (scored[0].candidate.unsupported) throw new Error(String(scored[0].candidate.reason || 'DOCX anchor range is not editable'));
  if (scored.length > 1 && scored[0].score === scored[1].score && wantedOccurrence === null && wantedStart === null) {
    throw new Error('DOCX anchor is ambiguous; provide anchorOccurrence or anchorStartOffset');
  }
  return {
    ...scored[0].candidate,
    anchorText,
    fullTextLength: fullText.length,
    candidateCount: candidates.length,
  };
}

export function _replaceDocxAnchorText(action: FrontendAction): Record<string, unknown> {
  const runtime = _workspaceRuntime();
  const wa = getFeatureRegistry() || {};
  const editor = runtime.activeEditor;
  const pm = editor?.editor || null;
  if (String(runtime.state.fileType || '').toLowerCase() !== 'docx' || !pm?.state || !pm?.view) {
    throw new Error('replace_docx_anchor_text requires an active DOCX editor');
  }
  const replacement = String(action.value ?? action.options?.replacement ?? action.options?.replacementText ?? '');
  const range = _resolveDocxAnchorRange(pm, action);
  const from = Number(range.from);
  const to = Number(range.to);
  const beforeText = String(pm.state.doc.textBetween(from, to, '\n', '\n') || '');
  pm.view.focus();
  pm.view.dispatch(pm.state.tr.insertText(replacement, from, to).scrollIntoView());
  if (typeof wa.scheduleAutoSave === 'function') {
    wa.scheduleAutoSave({ skipDiskWrite: true });
  }
  const afterEnd = from + replacement.length;
  const afterText = String(pm.state.doc.textBetween(from, afterEnd, '\n', '\n') || '');
  return {
    updated: true,
    range,
    replacementLength: replacement.length,
    beforeText: _limitString(beforeText, Number(action.options?.maxChars || 4000)),
    afterText: _limitString(afterText, Number(action.options?.maxChars || 4000)),
    state: _workspaceStateDetails(),
    document: _docxContext(action),
  };
}

function _shapeText(shape: any): string {
  if (!shape) return '';
  if (typeof shape.text === 'string') return shape.text;
  if (!Array.isArray(shape.paragraphs)) return '';
  return shape.paragraphs
    .map((para: any) => Array.isArray(para?.runs)
      ? para.runs.map((run: any) => String(run?.text || '')).join('')
      : '')
    .join('\n')
    .trim();
}

function _shapeSummary(shape: any): Record<string, unknown> {
  const rows = Math.max(0, Number(shape?.table_rows) || 0);
  const cols = Math.max(0, Number(shape?.table_cols) || 0);
  const text = _shapeText(shape);
  return {
    id: shape?.id ?? '',
    name: shape?.name || '',
    type: shape?.type || shape?._type || '',
    hasText: Boolean(shape?.has_text || text),
    text: _limitString(text, 1200),
    table: rows || cols ? { rows, cols } : null,
    geometry: {
      left: shape?.left ?? null,
      top: shape?.top ?? null,
      width: shape?.width ?? null,
      height: shape?.height ?? null,
      rotation: shape?.rotation ?? shape?.rot ?? null,
      zOrder: shape?.z_order ?? null,
    },
  };
}

function _docxContext(action: FrontendAction): Record<string, unknown> {
  const runtime = _workspaceRuntime();
  const wa = getFeatureRegistry() || {};
  const editor = runtime.activeEditor;
  const pm = editor?.editor || null;
  const limit = Number(action.options?.maxChars || action.options?.max_chars || action.options?.limit || 12000);
  let documentText = '';
  let selection: Record<string, unknown> | null = null;
  try {
    const doc = pm?.state?.doc;
    if (doc && typeof doc.textBetween === 'function') {
      documentText = String(doc.textBetween(0, doc.content?.size || doc.nodeSize || 0, '\n', '\n') || '');
    } else if (typeof pm?.getText === 'function') {
      documentText = String(pm.getText() || '');
    } else if (typeof editor?.getContent === 'function') {
      documentText = String(editor.getContent() || '');
    }
    if (typeof wa._getDocxSelectionPayload === 'function') {
      selection = _safeJsonClone(wa._getDocxSelectionPayload({
        allowStaleFallback: false,
        includeAnchorMeta: true,
      }), null) as Record<string, unknown> | null;
    }
  } catch (error) {
    return { error: _argToText(error) };
  }
  const headings = Array.from(document.querySelectorAll('#wa-docx-editor h1, #wa-docx-editor h2, #wa-docx-editor h3, #wa-docx-editor h4'))
    .filter(_isVisible)
    .slice(0, 30)
    .map((item) => ({
      level: item.tagName.toLowerCase(),
      text: (item.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 240),
    }))
    .filter((item) => item.text);
  const liveSelection = pm?.state?.selection
    ? {
        from: pm.state.selection.from,
        to: pm.state.selection.to,
        empty: Boolean(pm.state.selection.empty),
      }
    : null;
  return {
    kind: 'docx',
    documentText: _limitString(documentText, limit),
    selection,
    liveSelection,
    headings,
    canUseAnchorMeta: Boolean(selection && (selection as any).anchor_text),
  };
}

function _pptxContext(action: FrontendAction): Record<string, unknown> {
  const runtime = _workspaceRuntime();
  const editor = runtime.activeEditor;
  const data = editor?.data || null;
  const slides = Array.isArray(data?.slides) ? data.slides : [];
  const curIdx = Math.max(0, Math.min(slides.length - 1, Number(editor?._curIdx) || 0));
  const slide = slides[curIdx] || null;
  const shapes = Array.isArray(slide?.shapes) ? slide.shapes : [];
  const selectedShapeId = Number(editor?._selShape?.dataset?.shapeId || editor?._pinnedShapeId || 0) || null;
  const selectedShape = selectedShapeId != null
    ? shapes.find((shape: any) => Number(shape?.id) === selectedShapeId) || null
    : null;
  const tableSelection = editor?._tableSelection || null;
  const selectedText = editor?._activeSpan?.textContent || '';
  let slideContent = '';
  try {
    slideContent = typeof editor?.getContent === 'function' ? String(editor.getContent() || '') : '';
  } catch (_) {
    slideContent = '';
  }
  return {
    kind: 'pptx',
    slideCount: slides.length,
    currentSlideIndex: curIdx,
    slideIndex: slide?.index ?? slide?.slide_index ?? curIdx,
    slideSize: {
      widthEmu: data?.slideWidthEmu || data?.slide_width_emu || null,
      heightEmu: data?.slideHeightEmu || data?.slide_height_emu || null,
    },
    selectedShapeId,
    selectedShape: selectedShape ? _shapeSummary(selectedShape) : null,
    selectedText: _limitString(selectedText, Number(action.options?.maxChars || 4000)),
    tableSelection: _safeJsonClone(tableSelection, null),
    slideContent: _limitString(slideContent, Number(action.options?.maxChars || 12000)),
    shapes: shapes.slice(0, Number(action.options?.shapeLimit || action.options?.shape_limit || 80)).map(_shapeSummary),
  };
}

export async function _setPptxShapeText(action: FrontendAction): Promise<Record<string, unknown>> {
  const runtime = _workspaceRuntime();
  const state = runtime.state;
  const editor = runtime.activeEditor;
  if (String(state.fileType || '').toLowerCase() !== 'pptx' || !editor?.data) {
    throw new Error('set_pptx_shape_text requires an active PPTX editor');
  }
  if (typeof editor.applyToolCall !== 'function') {
    throw new Error('Active PPTX editor cannot apply tool calls');
  }
  const slides = Array.isArray(editor.data?.slides) ? editor.data.slides : [];
  const rawSlideIndex = action.options?.slideIndex ?? action.options?.slide_index ?? action.options?.slide ?? editor._curIdx ?? 0;
  const slideIndex = Number(rawSlideIndex);
  if (!Number.isFinite(slideIndex)) throw new Error('A numeric slide_index is required');
  const rawShapeId = action.options?.shapeId ?? action.options?.shape_id ?? action.options?.id ?? action.selector;
  const shapeId = Number(rawShapeId);
  if (!Number.isFinite(shapeId) || shapeId <= 0) throw new Error('A numeric shape_id is required');
  const value = String(action.value ?? action.text ?? action.options?.value ?? '');
  const slide = slides.find((item: any) => Number(item?.index ?? item?.slide_index) === slideIndex);
  if (!slide) throw new Error(`PPTX slide not found: ${slideIndex}`);
  const shape = Array.isArray(slide.shapes)
    ? slide.shapes.find((item: any) => Number(item?.id) === shapeId)
    : null;
  if (!shape) throw new Error(`PPTX shape not found: slide=${slideIndex} shape=${shapeId}`);
  if (!Array.isArray(shape.paragraphs)) throw new Error(`PPTX shape has no editable text: ${shapeId}`);
  const beforeShape = _shapeSummary(shape);
  editor.applyToolCall({ type: 'set_pptx_text', slide_index: slideIndex, shape_id: shapeId, value });
  await new Promise((resolve) => window.requestAnimationFrame(resolve));
  const updatedSlide = slides.find((item: any) => Number(item?.index ?? item?.slide_index) === slideIndex);
  const updatedShape = Array.isArray(updatedSlide?.shapes)
    ? updatedSlide.shapes.find((item: any) => Number(item?.id) === shapeId)
    : null;
  return {
    updated: true,
    slideIndex,
    shapeId,
    beforeShape,
    afterShape: updatedShape ? _shapeSummary(updatedShape) : null,
    state: _workspaceStateDetails(),
    document: _pptxContext(action),
  };
}

function _xlsxContext(action: FrontendAction): Record<string, unknown> {
  const api = (window as any).KotoSheetsAPI;
  const ready = Boolean(api && typeof api.isReady === 'function' && api.isReady());
  const limit = Number(action.options?.maxChars || action.options?.max_chars || action.options?.limit || 12000);
  let selectionText = '';
  let activeSheetCsv = '';
  let snapshotSummary: Record<string, unknown> | null = null;
  try {
    if (ready && typeof api.getSelectionText === 'function') {
      selectionText = String(api.getSelectionText() || '');
    }
    if (ready && typeof api.getActiveSheetCSV === 'function') {
      activeSheetCsv = String(api.getActiveSheetCSV() || '');
    }
    if (ready && action.options?.includeSnapshot === true && typeof api.getSnapshot === 'function') {
      const snapshot = api.getSnapshot();
      const sheets = snapshot?.sheets && typeof snapshot.sheets === 'object'
        ? Object.values(snapshot.sheets)
        : [];
      snapshotSummary = {
        sheetCount: Array.isArray(sheets) ? sheets.length : 0,
        names: Array.isArray(sheets)
          ? sheets.slice(0, 20).map((sheet: any) => String(sheet?.name || '')).filter(Boolean)
          : [],
      };
    }
  } catch (error) {
    return { kind: 'xlsx', ready, error: _argToText(error) };
  }
  return {
    kind: 'xlsx',
    ready,
    selectionText: _limitString(selectionText, limit),
    activeSheetCsv: _limitString(activeSheetCsv, limit),
    snapshotSummary,
  };
}

function _pdfContext(action: FrontendAction): Record<string, unknown> {
  const limit = Number(action.options?.maxChars || action.options?.max_chars || action.options?.limit || 12000);
  const viewer = document.getElementById('wa-pdf-viewer');
  const selection = window.getSelection ? window.getSelection()?.toString() || '' : '';
  const pageSelectors = '#wa-pdf-viewer .page, #wa-pdf-viewer .pdf-page, #wa-pdf-viewer [data-page-number]';
  const pages = Array.from(document.querySelectorAll(pageSelectors)).filter(_isVisible);
  return {
    kind: 'pdf',
    selectedText: _limitString(selection, limit),
    visibleText: _limitString(viewer?.textContent || '', limit),
    visiblePages: pages.slice(0, 20).map((page) => ({
      selector: _bestSelector(page),
      pageNumber: page.getAttribute('data-page-number') || page.getAttribute('data-page') || '',
      textPreview: (page.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 400),
    })),
  };
}

function _textContext(action: FrontendAction): Record<string, unknown> {
  const target = document.getElementById('wa-text-content') as HTMLTextAreaElement | null;
  const limit = Number(action.options?.maxChars || action.options?.max_chars || action.options?.limit || 12000);
  if (!target) return { kind: 'text', available: false };
  const start = Math.max(0, Number(target.selectionStart || 0));
  const end = Math.max(start, Number(target.selectionEnd || start));
  return {
    kind: 'text',
    available: true,
    content: _limitString(target.value, limit),
    selection: {
      start,
      end,
      selectedText: _limitString(target.value.slice(start, end), limit),
    },
  };
}

export function _documentContextDetails(action: FrontendAction): Record<string, unknown> {
  const state = _workspaceStateDetails();
  const fileType = String((state.fileType || (state.activeTab as any)?.fileType || '') as string).toLowerCase();
  const activeKind = fileType || String((state.activeTab as any)?.ext || '').replace(/^\./, '').toLowerCase();
  let docContext: Record<string, unknown>;
  if (activeKind === 'docx') docContext = _docxContext(action);
  else if (activeKind === 'pptx' || activeKind === 'ppt') docContext = _pptxContext(action);
  else if (activeKind === 'xlsx' || activeKind === 'xls' || activeKind === 'csv') docContext = _xlsxContext(action);
  else if (activeKind === 'pdf') docContext = _pdfContext(action);
  else docContext = _textContext(action);
  return {
    state,
    document: docContext,
    selection: _currentSelectionDetails(action),
    capabilities: {
      canReadDocumentContext: true,
      canEditPlainText: Boolean(document.getElementById('wa-text-content')),
      canSave: typeof getFeatureRegistry()?.saveFile === 'function',
      canOpenWorkspaceFile: typeof getFeatureRegistry()?.openWorkspaceFile === 'function',
      richSelectionKinds: ['docx-text', 'docx-table', 'pptx-shape', 'pptx-table', 'xlsx-range', 'pdf-text'],
    },
  };
}

export async function _saveCurrentFile(action: FrontendAction): Promise<Record<string, unknown>> {
  const wa = getFeatureRegistry() || {};
  if (typeof wa.saveFile !== 'function') throw new Error('FeatureRegistry.saveFile is not available');
  const before = _workspaceStateDetails();
  const result = await wa.saveFile();
  const timeoutMs = Number(action.options?.timeoutMs || action.options?.timeout_ms || 8000);
  const deadline = Date.now() + Math.max(500, Math.min(timeoutMs, 30000));
  while (Date.now() <= deadline) {
    const state = _workspaceStateDetails();
    const activeTab = state.activeTab as Record<string, unknown> | null;
    if (activeTab && activeTab.modified === false) {
      return { saved: true, before, state, saveResult: _safeJsonClone(result, {}) };
    }
    await new Promise((resolve) => window.setTimeout(resolve, 100));
  }
  return { saved: false, timedOut: true, before, state: _workspaceStateDetails(), saveResult: _safeJsonClone(result, {}) };
}

function _semanticPath(value: unknown): string {
  return String(value || '').trim().replace(/\\/g, '/').replace(/^\.\//, '').toLowerCase();
}

/** A synchronous version of the complete editor snapshot, including formatting. */
function _editorRevision(snapshot: string): string {
  let first = 2166136261;
  let second = 2246822507;
  for (let index = 0; index < snapshot.length; index += 1) {
    const code = snapshot.charCodeAt(index);
    first = Math.imul(first ^ code, 16777619);
    second = Math.imul(second ^ code, 3266489909);
  }
  return `editor-${snapshot.length}-${(first >>> 0).toString(16)}-${(second >>> 0).toString(16)}`;
}

function _semanticDocument(action: FrontendAction): Record<string, any> {
  const runtime = _workspaceRuntime();
  const state = runtime.state;
  const path = String(state.activeTabPath || state.wsSourcePath || '');
  const fileId = String(state.fileId || '');
  const expectedPath = String(action.options?.document_path || '');
  const expectedId = String(action.options?.file_id || '');
  if (!expectedPath || !expectedId || _semanticPath(path) !== _semanticPath(expectedPath) || fileId !== expectedId) {
    throw new Error('Document identity conflict: the scoped document is no longer active');
  }
  const tab = (state.openTabs || []).find((item: any) => _semanticPath(item.path) === _semanticPath(path));
  const kind = String(state.fileType || '').toLowerCase();
  let content = '';
  let serialized: any;
  if (kind === 'docx') {
    const pm = runtime.activeEditor?.editor;
    if (!pm?.state?.doc) throw new Error('DOCX editor is not ready');
    const doc = pm.state.doc;
    content = String(doc.textBetween(0, doc.content?.size || doc.nodeSize || 0, '\n', '\n') || '');
    serialized = typeof doc.toJSON === 'function' ? doc.toJSON() : content;
  } else if (['text', 'code', 'txt', 'md'].includes(kind)) {
    const input = document.getElementById('wa-text-content');
    if (!(input instanceof HTMLTextAreaElement || input instanceof HTMLInputElement)) throw new Error('Text editor is not ready');
    content = input.value;
    serialized = content;
  } else {
    const editor = runtime.activeEditor;
    if (!editor) throw new Error('Editor is not ready');
    serialized = typeof editor.serialize === 'function' ? editor.serialize() : typeof editor.getContent === 'function' ? editor.getContent() : null;
    if (serialized == null) throw new Error('This editor cannot expose a reliable document snapshot');
    content = typeof serialized === 'string' ? serialized : JSON.stringify(serialized);
  }
  return {
    document_path: path, file_id: fileId, file_type: kind,
    revision: _editorRevision(JSON.stringify({ path, fileId, kind, serialized })),
    source_sha256: tab?.sourceSha256 || state.sourceSha256 || '',
    content, modified: tab?.modified === true,
  };
}

export function _readScopedDocument(action: FrontendAction): Record<string, unknown> {
  const snapshot = _semanticDocument(action);
  const blockContext = snapshot.file_type === 'docx'
    ? readDocxBlockContext(_workspaceRuntime().activeEditor?.editor?.state?.doc, action.options || {}) : {};
  const textOffset = snapshot.file_type === 'docx' ? 0 : Number(action.options?.start_offset || 0);
  if (!Number.isInteger(textOffset) || textOffset < 0 || textOffset > snapshot.content.length) throw new Error('start_offset is outside the current document');
  if (textOffset > 0 && /[\uD800-\uDBFF]/.test(snapshot.content[textOffset - 1]) && /[\uDC00-\uDFFF]/.test(snapshot.content[textOffset])) throw new Error('start_offset splits a Unicode surrogate pair');
  const textLimit = Math.max(200, Math.min(Number(action.options?.max_chars || 4000), 16000));
  let textEnd = Math.min(snapshot.content.length, textOffset + textLimit);
  if (textEnd < snapshot.content.length && /[\uD800-\uDBFF]/.test(snapshot.content[textEnd - 1]) && /[\uDC00-\uDFFF]/.test(snapshot.content[textEnd])) textEnd -= 1;
  return {
    ...snapshot, content: { text: snapshot.content.slice(textOffset, textEnd), length: snapshot.content.length, text_offset: textOffset, truncated: textEnd < snapshot.content.length },
    next_offset: textEnd < snapshot.content.length ? textEnd : 0,
    ...blockContext,
    capabilities: { exact_text_patch: ['docx', 'text', 'code', 'txt', 'md'].includes(snapshot.file_type),
      multi_paragraph: snapshot.file_type === 'docx', preserve_block_structure: true,
      table_cell_scope: snapshot.file_type === 'docx', list_item_scope: snapshot.file_type === 'docx',
      structural_insert_delete: false, undo_requires_current_revision: true },
    selection: _currentSelectionDetails({ ...action, options: { ...action.options, maxChars: 2000 } }),
    persisted: false,
  };
}

const _documentUndoRecords = new Map<string, Record<string, any>>();
function _documentActionError(error: any, started: boolean): never {
  const failure = error instanceof Error ? error : new Error(String(error));
  failure.execution_started = failure.execution_started === true || started;
  throw failure;
}

export function _applyScopedDocumentEdit(action: FrontendAction): Record<string, unknown> {
  let started = false;
  try {
  const before = _semanticDocument(action);
  if (getFeatureRegistry().isDocumentSaveInProgress?.()) throw new Error('Document is currently saving; wait before applying an edit');
  if (!action.options?.expected_revision || action.options.expected_revision !== before.revision) {
    throw new Error('Document revision conflict: read the current document again before editing');
  }
  const anchor = String(action.options?.anchor_text || '');
  const replacement = String(action.options?.replacement ?? '');
  assertDocumentPatchText(anchor); assertDocumentPatchText(replacement);
  if (!anchor) throw new Error('An exact nonempty anchor_text is required');
  let edit: Record<string, unknown>;
  let plainBefore = '';
  if (before.file_type === 'docx') {
    const pm = _workspaceRuntime().activeEditor?.editor;
    edit = applyDocxTextPatch(pm, { anchor_text: anchor, replacement, anchor_occurrence: action.options?.anchor_occurrence, scope: action.options?.scope });
    started = edit.applied === true;
    if (edit.applied && !edit.verified) throw new Error('Editor mutation could not be verified; do not replay this operation');
    if (edit.applied) { getFeatureRegistry().scheduleAutoSave?.({ skipDiskWrite: true }); }
  } else if (['text', 'code', 'txt', 'md'].includes(before.file_type)) {
    if (Object.keys(action.options?.scope || {}).length) throw new Error('Plain-text edits do not support DOCX block or structural scopes');
    const matches: number[] = [];
    for (let offset = before.content.indexOf(anchor); offset >= 0; offset = before.content.indexOf(anchor, offset + 1)) matches.push(offset);
    const occurrence = action.options?.anchor_occurrence;
    if (!matches.length || (occurrence == null && matches.length !== 1)) throw new Error('Document anchor is absent or ambiguous; read context and specify anchor_occurrence');
    const wanted = occurrence == null ? 1 : Number(occurrence);
    if (!Number.isInteger(wanted) || wanted < 1 || wanted > matches.length) throw new Error('anchor_occurrence is outside the exact match range');
    const input = document.getElementById('wa-text-content') as HTMLTextAreaElement;
    plainBefore = input.value;
    if (anchor === replacement) edit = { applied: false, reason: 'no_change' };
    else {
    input.setSelectionRange(matches[wanted - 1], matches[wanted - 1] + anchor.length);
    started = true;
    edit = _replaceTextSelection({ ...action, selector: '#wa-text-content', value: replacement });
    edit.applied = true;
    if (input.value !== plainBefore.slice(0, matches[wanted - 1]) + replacement + plainBefore.slice(matches[wanted - 1] + anchor.length)) throw new Error('Text editor mutation could not be verified');
    }
  } else {
    throw new Error('Semantic text editing currently supports plain text and DOCX documents');
  }
  const after = _semanticDocument(action);
  const undoToken = edit.applied ? `undo-${globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`}` : '';
  if (undoToken) {
    _documentUndoRecords.set(undoToken, { document_path: before.document_path, file_id: before.file_id, revision_after: after.revision,
      native: edit.undo, plainBefore, plainAfter: after.content, before_text: anchor, after_text: replacement });
    if (_documentUndoRecords.size > 100) _documentUndoRecords.delete(_documentUndoRecords.keys().next().value);
  }
  return {
    document_path: after.document_path, file_id: after.file_id,
    revision_before: before.revision, revision_after: after.revision,
    source_sha256: before.source_sha256, before_text: anchor, after_text: replacement,
    applied: edit.applied === true, persisted: false, editor_modified: after.modified === true || edit.applied === true,
    verified: true, reason: edit.reason || '', block_ids: edit.block_ids || [], undo_token: undoToken,
  };
  } catch (error) { return _documentActionError(error, started); }
}

function _reviewAction(options: Record<string, any> = {}): FrontendAction {
  const state = _workspaceRuntime().state;
  return { id: options.operation_id || '', action: 'ui_read_context', options: {
    document_path: state.activeTabPath || state.wsSourcePath || '', file_id: state.fileId || '', ...options,
  } };
}

const _reviewOperations = new Map<string, { fingerprint: string; result?: Record<string, any>; error?: Error }>();
function _reviewMutation(kind: string, options: Record<string, any>, mutate: () => Record<string, any>): Record<string, any> {
  if (!options.operation_id || !options.document_path || !options.file_id) throw Object.assign(new Error('A document identity and stable operation_id are required'), { execution_started: false });
  const key = JSON.stringify([options.document_path, options.file_id, options.operation_id]);
  const fingerprint = JSON.stringify([kind, options.expected_revision, options.anchor_text, options.replacement, options.anchor_occurrence, options.scope || {}, options.undo_token]);
  const existing = _reviewOperations.get(key);
  if (existing) {
    if (existing.fingerprint !== fingerprint) throw Object.assign(new Error('Operation ID was reused for a different document edit'), { execution_started: false });
    if (existing.error && existing.error.execution_started !== false) throw existing.error;
    if (existing.result) return existing.result;
  }
  try { const result = mutate(); _reviewOperations.set(key, { fingerprint, result }); return result; }
  catch (error) { _reviewOperations.set(key, { fingerprint, error }); throw error; }
  finally { if (_reviewOperations.size > 200) _reviewOperations.delete(_reviewOperations.keys().next().value); }
}

export function _undoScopedDocumentEdit(options: Record<string, any>): Record<string, any> {
  let started = false;
  try {
    const action = _reviewAction(options);
    const before = _semanticDocument(action);
    if (getFeatureRegistry().isDocumentSaveInProgress?.()) throw new Error('Document is currently saving; wait before undoing an edit');
    const record = _documentUndoRecords.get(String(options.undo_token || ''));
    if (!record) throw new Error('Undo is unavailable after editor reload or receipt expiry; no document change was attempted');
    if (options.expected_revision !== before.revision || before.revision !== record.revision_after || before.file_id !== record.file_id || _semanticPath(before.document_path) !== _semanticPath(record.document_path)) throw new Error('Undo revision conflict: the document changed after this edit');
    if (record.native) { undoDocxTextPatch(_workspaceRuntime().activeEditor?.editor, record.native); started = true; getFeatureRegistry().scheduleAutoSave?.({ skipDiskWrite: true }); }
    else {
      const input = document.getElementById('wa-text-content') as HTMLTextAreaElement;
      if (input.value !== record.plainAfter) throw new Error('Undo text no longer matches the edited revision');
      started = true; input.value = record.plainBefore; _notifyTextEdited(input);
    }
    const after = _semanticDocument(action);
    _documentUndoRecords.delete(String(options.undo_token));
    return { document_path: before.document_path, file_id: before.file_id, applied: true, persisted: false, verified: true,
      revision_before: before.revision, revision_after: after.revision, before_text: record.after_text, after_text: record.before_text, reason: '' };
  } catch (error) { return _documentActionError(error, started); }
}

registerFeatures({
  getDocumentReviewContext: (options: Record<string, any> = {}) => _readScopedDocument(_reviewAction(options)),
  applyDocumentReviewEdit: (options: Record<string, any>) => _reviewMutation('apply', options, () => _applyScopedDocumentEdit(_reviewAction(options))),
  undoDocumentReviewEdit: (options: Record<string, any>) => _reviewMutation('undo', options, () => _undoScopedDocumentEdit(options)),
  locateDocumentReviewEdit: (options: Record<string, any>) => {
    const action = _reviewAction(options); const snapshot = _semanticDocument(action);
    if (snapshot.revision !== options.expected_revision) throw new Error('Document revision conflict before locating');
    if (snapshot.file_type === 'docx') {
      const pm = _workspaceRuntime().activeEditor?.editor;
      const found = resolveDocxTextAnchor(pm.state.doc, options);
      const segments = found.segments;
      if (typeof pm.commands?.setTextSelection !== 'function') throw new Error('Document editor cannot locate an exact selection');
      const from = segments[0].block.from + segments[0].start;
      const to = segments.at(-1).block.from + segments.at(-1).end;
      const selected = pm.commands.setTextSelection({ from, to });
      if (selected === false || pm.state.selection?.from !== from || pm.state.selection?.to !== to) throw new Error('Document editor rejected the exact selection');
      pm.commands?.focus?.();
      return { located: true, block_ids: found.block_ids, revision: snapshot.revision };
    }
    const input = document.getElementById('wa-text-content') as HTMLTextAreaElement;
    const anchor = String(options.anchor_text || ''); const offset = input.value.indexOf(anchor);
    if (!anchor || offset < 0 || input.value.indexOf(anchor, offset + anchor.length) >= 0) throw new Error('Text anchor is absent or ambiguous');
    input.setSelectionRange(offset, offset + anchor.length); input.focus(); return { located: true, revision: snapshot.revision };
  },
});

async function _sha256(bytes: ArrayBuffer): Promise<string> {
  if (!globalThis.crypto?.subtle) throw new Error('Secure byte readback is unavailable in this browser');
  const digest = await crypto.subtle.digest('SHA-256', bytes);
  return Array.from(new Uint8Array(digest), (value) => value.toString(16).padStart(2, '0')).join('');
}

export async function _saveScopedDocument(action: FrontendAction): Promise<Record<string, unknown>> {
  let started = false;
  try {
  const before = _semanticDocument(action);
  if (!action.options?.expected_revision || action.options.expected_revision !== before.revision) throw new Error('Document revision conflict before save');
  const sourceHash = String(action.options?.expected_source_sha256 || '');
  if (!/^[a-f0-9]{64}$/.test(sourceHash) || sourceHash !== before.source_sha256) throw new Error('Original source revision is missing or does not match the opened document');
  const initialRuntime = _workspaceRuntime();
  const initialTab = (initialRuntime.state.openTabs || []).find((item: any) => _semanticPath(item.path) === _semanticPath(before.document_path));
  if (initialTab?.fsHandle && typeof initialTab.fsHandle.getFile === 'function') {
    const currentSourceHash = await _sha256(await (await initialTab.fsHandle.getFile()).arrayBuffer());
    if (currentSourceHash !== sourceHash) throw new Error('Original browser file changed externally; save was not attempted');
    if (_semanticDocument(action).revision !== before.revision) throw new Error('Document changed during source version check');
  }
  const save = getFeatureRegistry().saveFileWithReceipt;
  if (typeof save !== 'function') throw new Error('Strict document save receipts are unavailable');
  started = true;
  const receipt = await save({ expected_source_sha256: sourceHash });
  const after = _semanticDocument(action);
  if (!receipt?.persisted || receipt.unsaved_changes || after.revision !== before.revision) throw new Error('The document changed during save or the source was not persisted');
  if (String(receipt.file_id || '') !== before.file_id) throw new Error('Save receipt belongs to another document');
  const fetchImpl = _originalFetch || window.fetch.bind(window);
  const raw = await fetchImpl(`/api/v1/workspace/raw/${encodeURIComponent(before.file_id)}?_=${Date.now()}`, { cache: 'no-store' });
  if (!raw.ok) throw new Error(`Saved bytes could not be read back: HTTP ${raw.status}`);
  const rawSha256 = await _sha256(await raw.arrayBuffer());
  let handleVerified = false;
  if (receipt.file_handle_written) {
    const runtime = _workspaceRuntime();
    const tab = (runtime.state.openTabs || []).find((item: any) => _semanticPath(item.path) === _semanticPath(before.document_path));
    const handle = tab?.fsHandle;
    if (!handle || typeof handle.getFile !== 'function') throw new Error('Original browser file cannot be read back');
    handleVerified = await _sha256(await (await handle.getFile()).arrayBuffer()) === rawSha256;
    if (!handleVerified) throw new Error('Original browser file bytes differ from saved content');
  }
  if (_semanticDocument(action).revision !== before.revision) throw new Error('Document changed during save readback');
  return {
    ...receipt, document_path: before.document_path, file_id: before.file_id,
    revision: before.revision, raw_sha256: rawSha256,
    file_handle_readback_verified: handleVerified, unsaved_changes: false,
  };
  } catch (error) { return _documentActionError(error, started); }
}

function _flattenWorkspaceTree(value: unknown, limit = 500): Record<string, unknown>[] {
  const out: Record<string, unknown>[] = [];
  const visit = (node: unknown): void => {
    if (out.length >= limit || !node) return;
    if (Array.isArray(node)) {
      node.forEach(visit);
      return;
    }
    if (typeof node !== 'object') return;
    const item = node as Record<string, unknown>;
    if (item.type === 'file') {
      out.push({
        path: item.path || '',
        name: item.name || '',
        ext: item.ext || '',
        supported: Boolean(item.supported),
        category: item.category || '',
        size: item.size || '',
        mtime: item.mtime || 0,
      });
    }
    if (Array.isArray(item.children)) visit(item.children);
    if (Array.isArray(item.files)) visit(item.files);
  };
  visit(value);
  return out;
}

export async function _fetchWorkspaceFiles(action: FrontendAction): Promise<Record<string, unknown>> {
  const fetchImpl = _originalFetch || window.fetch.bind(window);
  const response = await fetchImpl('/api/v1/workspace/list_files');
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `list_files failed: ${response.status}`);
  const resultLimit = Number(action.options?.limit || 80);
  const scanLimit = Number(action.options?.scanLimit || action.options?.scan_limit || Math.max(1000, resultLimit * 10));
  const files = _flattenWorkspaceTree(data, scanLimit);
  const query = String(action.value || action.text || action.path || '').trim().toLowerCase();
  const matches = query
    ? files.filter((file) => {
        const haystack = `${file.path || ''} ${file.name || ''} ${file.category || ''}`.toLowerCase();
        return haystack.includes(query);
      })
    : files;
  return {
    workspaceName: data.workspace_name || '',
    workspacePath: data.workspace_path || '',
    totalFiles: files.length,
    query,
    files: matches.slice(0, resultLimit),
  };
}

export async function _openWorkspaceFile(action: FrontendAction): Promise<Record<string, unknown>> {
  const path = String(action.path || action.value || action.text || action.selector || '').trim()
    .replace(/^workspace[\\/]/i, '');
  if (!path) throw new Error('Workspace file path is required');
  const wa = getFeatureRegistry() || {};
  if (typeof wa.openWorkspaceFile === 'function') {
    await wa.openWorkspaceFile(path);
  } else {
    const fetchImpl = _originalFetch || window.fetch.bind(window);
    const response = await fetchImpl('/api/v1/workspace/open_file_by_path', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || `open_file_by_path failed: ${response.status}`);
    if (typeof wa._applyFileJson === 'function') {
      await wa._applyFileJson(data, path, null);
    }
  }
  const timeoutMs = Number(action.options?.timeoutMs || action.options?.timeout_ms || 8000);
  const deadline = Date.now() + Math.max(500, Math.min(timeoutMs, 30000));
  while (Date.now() <= deadline) {
    const state = _workspaceStateDetails();
    const activePath = String(state.activeTabPath || state.wsSourcePath || '');
    if (activePath.replace(/\\/g, '/').toLowerCase().endsWith(path.replace(/\\/g, '/').toLowerCase())) {
      return { requestedPath: path, opened: true, state };
    }
    await new Promise((resolve) => window.setTimeout(resolve, 100));
  }
  return { requestedPath: path, opened: false, state: _workspaceStateDetails() };
}
