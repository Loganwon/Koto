type FrontendEvent = {
  id?: string;
  type: string;
  level?: string;
  message?: string;
  client_ts?: number;
  url?: string;
  route?: string;
  session_id?: string;
  source?: string;
  details?: Record<string, unknown>;
};

type FrontendAction = {
  id: string;
  action:
    | 'click'
    | 'fill'
    | 'type'
    | 'press'
    | 'snapshot'
    | 'read_dom'
    | 'surface_inventory'
    | 'wait_for'
    | 'open_panel'
    | 'search_workspace'
    | 'submit_prompt'
    | 'list_workspace_files'
    | 'open_workspace_file'
    | 'current_file_state'
    | 'read_editor_content'
    | 'current_selection'
    | 'document_context'
    | 'select_text_range'
    | 'replace_text_selection'
    | 'set_editor_content'
    | 'replace_docx_anchor_text'
    | 'set_pptx_shape_text'
    | 'save_current_file';
  selector?: string;
  panel?: string;
  path?: string;
  text?: string;
  value?: string;
  key?: string;
  options?: Record<string, unknown>;
};

const ENDPOINT = '/api/mcp/frontend-event';
const ACTION_ENDPOINT = '/api/mcp/frontend-action';
const ACTION_RESULT_ENDPOINT = '/api/mcp/frontend-action-result';
const MAX_QUEUE = 100;
const SNAPSHOT_INTERVAL_MS = 60000;
const ACTION_LONG_POLL_MS = 25000;
const ACTION_POLL_ACTIVE_DELAY_MS = 250;
const ACTION_POLL_IDLE_MIN_MS = 1000;
const ACTION_POLL_IDLE_MAX_MS = 10000;

let _installed = false;
let _queue: FrontendEvent[] = [];
let _flushTimer: number | null = null;
let _actionPollTimer: number | null = null;
let _actionPollActive = false;
let _actionIdleDelayMs = ACTION_POLL_IDLE_MIN_MS;
let _sessionId = '';
let _originalFetch: typeof window.fetch | null = null;

function _now(): number {
  return Date.now();
}

function _route(): string {
  return `${location.pathname}${location.search}${location.hash}`;
}

function _getSessionId(): string {
  if (_sessionId) return _sessionId;
  try {
    const key = 'koto_frontend_observer_session';
    _sessionId = sessionStorage.getItem(key) || '';
    if (!_sessionId) {
      _sessionId = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
      sessionStorage.setItem(key, _sessionId);
    }
  } catch (_) {
    _sessionId = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
  }
  return _sessionId;
}

function _argToText(value: unknown): string {
  if (value instanceof Error) return `${value.name}: ${value.message}`;
  if (typeof value === 'string') return value;
  try {
    return JSON.stringify(value);
  } catch (_) {
    return String(value);
  }
}

function _errorDetails(error: unknown): Record<string, unknown> {
  if (error instanceof Error) {
    return { name: error.name, message: error.message, stack: error.stack || '' };
  }
  return { value: _argToText(error) };
}

function _visibleText(el: Element | null | undefined, limit = 500): string {
  if (!el) return '';
  const clone = el.cloneNode(true) as HTMLElement;
  clone.querySelectorAll([
    'script',
    'style',
    'noscript',
    'template',
    'svg',
    'canvas',
    '[hidden]',
    '[aria-hidden="true"]',
    '.ProseMirror-separator',
    '.ProseMirror-trailingBreak',
  ].join(',')).forEach((node) => node.remove());
  const raw = clone.innerText || clone.textContent || '';
  return raw.replace(/\s+/g, ' ').trim().slice(0, Math.max(0, limit));
}

function _shouldSummarizeText(el: Element): boolean {
  if (el.matches('button,a,label,input,select,textarea,[role],[data-action],[contenteditable="true"],dialog,.modal,.dialog,.toast,.wa-toast,[data-toast]')) {
    return true;
  }
  return Boolean(el.id && /toast|dialog|modal|panel|status|tab|button/i.test(el.id));
}

function _isSensitiveControl(el: Element): boolean {
  if (el instanceof HTMLInputElement && ['password', 'hidden'].includes(el.type)) {
    return true;
  }
  const haystack = [
    el.id,
    el.getAttribute('name') || '',
    el.getAttribute('autocomplete') || '',
    el.getAttribute('aria-label') || '',
    el.getAttribute('placeholder') || '',
    el.getAttribute('title') || '',
    typeof el.className === 'string' ? el.className : '',
  ].join(' ');
  return /\b(password|passwd|pwd|token|secret|api[_-]?key|authorization|credential|cookie|session)\b/i.test(haystack);
}

function _summarizeControlValue(el: Element, value: string, limit = 500): Record<string, unknown> {
  if (_isSensitiveControl(el)) {
    return { value: value ? '[redacted]' : '', value_redacted: Boolean(value) };
  }
  return { value: value.slice(0, limit) };
}

function _targetSummary(target: EventTarget | null): Record<string, unknown> {
  const el = target instanceof Element ? target : null;
  if (!el) return {};
  const text = _shouldSummarizeText(el) ? _visibleText(el, 160) : '';
  const summary: Record<string, unknown> = {
    tag: el.tagName.toLowerCase(),
    id: el.id || '',
    className: typeof el.className === 'string' ? el.className.slice(0, 240) : '',
    role: el.getAttribute('role') || '',
    action: el.getAttribute('data-action') || '',
    ariaLabel: el.getAttribute('aria-label') || '',
    title: el.getAttribute('title') || '',
    text,
  };
  if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) {
    Object.assign(summary, _summarizeControlValue(el, el.value));
    summary.placeholder = el.getAttribute('placeholder') || '';
    summary.checked = el instanceof HTMLInputElement && ['checkbox', 'radio'].includes(el.type)
      ? el.checked
      : undefined;
  } else if (el instanceof HTMLSelectElement) {
    summary.value = el.value.slice(0, 500);
    summary.selectedText = el.selectedOptions[0]?.textContent?.trim().slice(0, 200) || '';
  } else if ((el as HTMLElement).isContentEditable) {
    Object.assign(summary, _summarizeControlValue(el, (el as HTMLElement).innerText || ''));
  }
  return summary;
}

function _isVisible(el: Element): boolean {
  const html = el as HTMLElement;
  const style = window.getComputedStyle(html);
  return style.display !== 'none'
    && style.visibility !== 'hidden'
    && style.opacity !== '0'
    && Boolean(html.offsetWidth || html.offsetHeight || html.getClientRects().length);
}

function _visibleControls(limit = 40): Record<string, unknown>[] {
  return Array.from(document.querySelectorAll('button,a,input,select,textarea,[role="button"],[data-action],[contenteditable="true"]'))
    .filter(_isVisible)
    .slice(0, limit)
    .map((item) => {
      const rect = item.getBoundingClientRect();
      return {
        ..._targetSummary(item),
        selector: _bestSelector(item),
        rect: {
          x: Math.round(rect.x),
          y: Math.round(rect.y),
          width: Math.round(rect.width),
          height: Math.round(rect.height),
        },
      };
    });
}

function _visiblePanelSummaries(limit = 30): Record<string, unknown>[] {
  const selectors = [
    '[id$="Panel"]',
    '#fileWorkspace',
    '#wa-left-panel',
    '#wa-editor-panel',
    '#wa-chat-panel',
    '#workspaceView',
    '.wa-panel',
    '.artifacts-panel',
  ].join(',');
  return Array.from(document.querySelectorAll(selectors))
    .filter(_isVisible)
    .slice(0, limit)
    .map((item) => {
      const rect = item.getBoundingClientRect();
      return {
        id: item.id || '',
        selector: _bestSelector(item),
        className: typeof item.className === 'string' ? item.className.slice(0, 240) : '',
        role: item.getAttribute('role') || '',
        text: _visibleText(item, 240),
        rect: {
          x: Math.round(rect.x),
          y: Math.round(rect.y),
          width: Math.round(rect.width),
          height: Math.round(rect.height),
        },
      };
    });
}

function _activeEditorControlSummaries(limit = 80): Record<string, unknown>[] {
  const roots = [
    '#wa-editor-header',
    '#wa-file-toolbar',
    '#wa-docx-editor.active',
    '#wa-pptx-editor.active',
    '#wa-xlsx-editor.active',
    '#wa-pdf-viewer.active',
    '#wa-text-editor.active',
    '#wa-image-viewer.active',
  ];
  const seen = new Set<Element>();
  const controls: Record<string, unknown>[] = [];
  for (const rootSelector of roots) {
    const root = document.querySelector(rootSelector);
    if (!root || !_isVisible(root)) continue;
    const rootControls = Array.from(root.querySelectorAll('button,a,input,select,textarea,[role="button"],[data-action],[contenteditable="true"]'));
    for (const item of rootControls) {
      if (seen.has(item) || !_isVisible(item)) continue;
      seen.add(item);
      controls.push({
        root: rootSelector,
        ..._targetSummary(item),
        selector: _bestSelector(item),
      });
      if (controls.length >= limit) return controls;
    }
  }
  return controls;
}

function _surfaceInventoryDetails(action?: FrontendAction): Record<string, unknown> {
  const limit = Number(action?.options?.limit || 80);
  const wa = (window as any).WA || {};
  const waMethods = Object.keys(wa)
    .filter((key) => typeof wa[key] === 'function')
    .sort()
    .slice(0, 240);
  const globalNames = [
    'KotoFrontendObserver',
    'KotoCsrf',
    'KotoDocxEditorLib',
    'KotoSheetsAPI',
    'pdfjsLib',
    'toggleSettings',
    'toggleSkillsPanel',
    'openSkillsPanel',
    'switchArtifactTab',
    'copyArtifactContent',
    'downloadArtifact',
  ];
  return {
    snapshot: _snapshotDetails(),
    visiblePanels: _visiblePanelSummaries(Math.min(limit, 80)),
    visibleControls: _visibleControls(Math.min(limit, 120)),
    activeEditorControls: _activeEditorControlSummaries(Math.min(limit, 160)),
    loadedScripts: Array.from(document.scripts)
      .map((script) => script.src || 'inline')
      .filter(Boolean)
      .slice(0, 120),
    loadedStylesheets: Array.from(document.styleSheets)
      .map((sheet) => sheet.href || 'inline')
      .filter(Boolean)
      .slice(0, 120),
    wa: {
      methodCount: Object.keys(wa).filter((key) => typeof wa[key] === 'function').length,
      methods: waMethods,
    },
    globals: globalNames.reduce((acc: Record<string, unknown>, name) => {
      acc[name] = typeof (window as any)[name];
      return acc;
    }, {}),
  };
}

function _bestSelector(el: Element): string {
  if (el.id) return `#${CSS.escape(el.id)}`;
  const testId = el.getAttribute('data-testid');
  if (testId) return `[data-testid="${CSS.escape(testId)}"]`;
  const action = el.getAttribute('data-action');
  if (action) return `[data-action="${CSS.escape(action)}"]`;
  const aria = el.getAttribute('aria-label');
  if (aria) return `${el.tagName.toLowerCase()}[aria-label="${CSS.escape(aria)}"]`;
  return el.tagName.toLowerCase();
}

function _textMatch(el: Element, text: string): boolean {
  const wanted = text.replace(/\s+/g, ' ').trim().toLowerCase();
  if (!wanted) return false;
  const candidates = [
    el.getAttribute('aria-label') || '',
    el.getAttribute('title') || '',
    el.getAttribute('placeholder') || '',
    _visibleText(el, 500),
  ].map((item) => item.toLowerCase());
  return candidates.some((item) => item === wanted || item.includes(wanted));
}

function _findTarget(action: FrontendAction): Element | null {
  const selector = (action.selector || '').trim();
  if (selector) {
    const selected = document.querySelector(selector);
    if (selected) return selected;
  }
  const text = (action.text || '').trim();
  if (!text) return null;
  return Array.from(document.querySelectorAll('button,a,input,select,textarea,[role="button"],[data-action],[contenteditable="true"]'))
    .find((item) => _isVisible(item) && _textMatch(item, text)) || null;
}

function _panelSelector(panel: string): string {
  const normalized = panel.trim().toLowerCase();
  if (normalized === 'settings') return '#navSettingsBtn';
  if (normalized === 'skills') return '#navSkillsBtn';
  if (normalized === 'artifact') return '#artifactsPanel, [data-action="open-artifact"], #navArtifactsBtn';
  if (normalized === 'workspace') return '[data-action="show-file-workspace"], #navWorkspaceBtn, #sidebarToggle';
  if (normalized === 'ai') return '[data-action="show-ai-workspace"], #wa-user-input';
  return '';
}

function _findFirstVisible(selectors: string[]): Element | null {
  for (const selector of selectors) {
    if (!selector) continue;
    const elements = Array.from(document.querySelectorAll(selector));
    const match = elements.find(_isVisible);
    if (match) return match;
  }
  return null;
}

function _selectedTexts(selector: string, limit = 10): string[] {
  return Array.from(document.querySelectorAll(selector))
    .slice(0, limit)
    .map((item) => _visibleText(item, 200))
    .filter(Boolean);
}

function _safeJsonClone(value: unknown, fallback: unknown = null): unknown {
  try {
    return JSON.parse(JSON.stringify(value));
  } catch (_) {
    return fallback;
  }
}

function _limitString(value: unknown, limit: number): { text: string; length: number; truncated: boolean } {
  const text = typeof value === 'string' ? value : value == null ? '' : String(value);
  const safeLimit = Math.max(100, Math.min(Number(limit || 8000), 50000));
  return {
    text: text.slice(0, safeLimit),
    length: text.length,
    truncated: text.length > safeLimit,
  };
}

function _jsonPreview(value: unknown, limit: number): { text: string; length: number; truncated: boolean } {
  let text = '';
  try {
    text = JSON.stringify(value, null, 2);
  } catch (_) {
    text = String(value);
  }
  return _limitString(text, limit);
}

function _workspaceStateDetails(): Record<string, unknown> {
  const state = (window as any).state || {};
  const openTabs = Array.isArray(state.openTabs) ? state.openTabs : [];
  const activePath = String(state.activeTabPath || state.wsSourcePath || '');
  const activeTab = openTabs.find((tab: any) => String(tab?.path || '') === activePath) || null;
  const activeEditorRuntime = state.activeEditor || null;
  const editorIds = [
    'wa-docx-editor',
    'wa-xlsx-editor',
    'wa-pptx-editor',
    'wa-pdf-viewer',
    'wa-image-viewer',
    'wa-text-editor',
  ];
  const editors = editorIds.map((id) => {
    const el = document.getElementById(id);
    const active = Boolean(el?.classList.contains('active'));
    let textPreview = '';
    if (active && activeEditorRuntime && typeof activeEditorRuntime.getContent === 'function') {
      textPreview = String(activeEditorRuntime.getContent() || '');
    } else if (active && activeEditorRuntime?.editor && typeof activeEditorRuntime.editor.getText === 'function') {
      textPreview = String(activeEditorRuntime.editor.getText() || '');
    } else if (id === 'wa-docx-editor') {
      textPreview = _visibleText(el?.querySelector('.ProseMirror, [contenteditable="true"]'), 300);
    } else {
      textPreview = _visibleText(el, 300);
    }
    return {
      id,
      active,
      visible: el ? _isVisible(el) : false,
      textPreview: textPreview.replace(/\s+/g, ' ').trim().slice(0, 300),
    };
  });
  const wa = (window as any).WA || {};
  return {
    fileId: state.fileId || '',
    fileType: state.fileType || '',
    fileName: state.fileName || document.getElementById('wa-file-name')?.textContent?.trim() || '',
    filePath: state.filePath || '',
    wsSourcePath: state.wsSourcePath || '',
    activeTabPath: state.activeTabPath || '',
    activeTab: activeTab
      ? {
          path: activeTab.path || '',
          name: activeTab.name || '',
          ext: activeTab.ext || '',
          fileType: activeTab.fileType || '',
          fileId: activeTab.fileId || '',
          filePath: activeTab.filePath || '',
          modified: Boolean(activeTab.modified),
          capabilityProfile: _safeJsonClone(activeTab.capabilityProfile || null),
        }
      : null,
    openTabs: openTabs.slice(0, 20).map((tab: any) => ({
      path: tab?.path || '',
      name: tab?.name || '',
      ext: tab?.ext || '',
      fileType: tab?.fileType || '',
      modified: Boolean(tab?.modified),
    })),
    activeEditors: editors.filter((item) => item.active || item.visible),
    tabLabels: _selectedTexts('#wa-tab-bar .wa-tab', 20),
    headerFileName: document.getElementById('wa-file-name')?.textContent?.trim() || '',
    waMethods: {
      openWorkspaceFile: typeof wa.openWorkspaceFile === 'function',
      openBrowserFile: typeof wa.openBrowserFile === 'function',
      applyFileJson: typeof wa._applyFileJson === 'function',
      refreshFiles: typeof wa.refreshFiles === 'function',
    },
  };
}

function _readEditorContent(action: FrontendAction): Record<string, unknown> {
  const limit = Number(action.options?.maxChars || action.options?.max_chars || action.options?.limit || 12000);
  const state = (window as any).state || {};
  const editor = state.activeEditor || null;
  const result: Record<string, unknown> = {
    state: _workspaceStateDetails(),
    content: _limitString('', limit),
    html: null,
    serialized: null,
    source: '',
  };
  try {
    if (editor && typeof editor.getContent === 'function') {
      result.content = _limitString(editor.getContent(), limit);
      result.source = 'activeEditor.getContent';
    } else if (editor?.editor && typeof editor.editor.getText === 'function') {
      result.content = _limitString(editor.editor.getText(), limit);
      result.source = 'activeEditor.editor.getText';
    } else {
      const textArea = document.getElementById('wa-text-content') as HTMLTextAreaElement | null;
      if (textArea && _isVisible(textArea)) {
        result.content = _limitString(textArea.value, limit);
        result.source = '#wa-text-content';
      } else {
        const activeEditor = document.querySelector(
          '#wa-docx-editor.active, #wa-xlsx-editor.active, #wa-pptx-editor.active, #wa-pdf-viewer.active, #wa-image-viewer.active, #wa-text-editor.active'
        );
        result.content = _limitString(_visibleText(activeEditor, limit), limit);
        result.source = 'active editor visible text';
      }
    }
    if (editor?.editor && typeof editor.editor.getHTML === 'function') {
      result.html = _limitString(editor.editor.getHTML(), Math.min(limit, 20000));
    }
    if (editor && typeof editor.serialize === 'function') {
      const serialized = editor.serialize();
      result.serialized = typeof serialized === 'string'
        ? _limitString(serialized, limit)
        : _jsonPreview(serialized, Math.min(limit, 20000));
    }
  } catch (error) {
    result.error = _argToText(error);
  }
  return result;
}

function _selectionRectSummary(selection: Selection | null): Record<string, unknown> | null {
  if (!selection || selection.rangeCount <= 0) return null;
  try {
    const rect = selection.getRangeAt(0).getBoundingClientRect();
    return {
      x: Math.round(rect.x),
      y: Math.round(rect.y),
      width: Math.round(rect.width),
      height: Math.round(rect.height),
    };
  } catch (_) {
    return null;
  }
}

function _currentSelectionDetails(action: FrontendAction): Record<string, unknown> {
  const limit = Number(action.options?.maxChars || action.options?.max_chars || action.options?.limit || 4000);
  const active = document.activeElement;
  const selection = window.getSelection ? window.getSelection() : null;
  const wa = (window as any).WA || {};
  let inputSelection: Record<string, unknown> | null = null;
  if (active instanceof HTMLInputElement || active instanceof HTMLTextAreaElement) {
    const start = Number(active.selectionStart || 0);
    const end = Number(active.selectionEnd || 0);
    inputSelection = {
      target: _targetSummary(active),
      selectionStart: start,
      selectionEnd: end,
      selectedText: _limitString(active.value.slice(start, end), limit),
    };
  }
  let docxSelection = '';
  try {
    if (typeof wa._getDocxSelectionTextForAI === 'function') {
      docxSelection = String(wa._getDocxSelectionTextForAI() || '');
    }
  } catch (_) {
    docxSelection = '';
  }
  const windowText = selection ? selection.toString() : '';
  const inputText = inputSelection && inputSelection.selectedText
    ? String((inputSelection.selectedText as Record<string, unknown>).text || '')
    : '';
  const text = docxSelection || inputText || windowText || '';
  return {
    state: _workspaceStateDetails(),
    activeElement: active instanceof Element ? _targetSummary(active) : {},
    hasSelection: Boolean(String(text || '').trim()),
    selectedText: _limitString(text, limit),
    inputSelection,
    windowSelection: {
      text: _limitString(windowText, limit),
      rangeCount: selection?.rangeCount || 0,
      isCollapsed: selection ? selection.isCollapsed : true,
      rect: _selectionRectSummary(selection),
    },
    docxSelection: _limitString(docxSelection, limit),
  };
}

function _editableTextTarget(action: FrontendAction): HTMLInputElement | HTMLTextAreaElement {
  const target = _findTarget(action) || document.getElementById('wa-text-content');
  if (!(target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement)) {
    throw new Error('Text editing requires an input or textarea target');
  }
  return target;
}

function _notifyTextEdited(target: HTMLInputElement | HTMLTextAreaElement): void {
  target.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: '' }));
  target.dispatchEvent(new Event('change', { bubbles: true }));
  const wa = (window as any).WA || {};
  if (typeof wa.scheduleAutoSave === 'function') {
    wa.scheduleAutoSave({ skipDiskWrite: true });
  }
}

function _selectTextRange(action: FrontendAction): Record<string, unknown> {
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

function _replaceTextSelection(action: FrontendAction): Record<string, unknown> {
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

function _setEditorContent(action: FrontendAction): Record<string, unknown> {
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

function _replaceDocxAnchorText(action: FrontendAction): Record<string, unknown> {
  const state = (window as any).state || {};
  const wa = (window as any).WA || {};
  const editor = state.activeEditor || null;
  const pm = editor?.editor || null;
  if (String(state.fileType || '').toLowerCase() !== 'docx' || !pm?.state || !pm?.view) {
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
  const state = (window as any).state || {};
  const wa = (window as any).WA || {};
  const editor = state.activeEditor || null;
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
  const state = (window as any).state || {};
  const editor = state.activeEditor || null;
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

async function _setPptxShapeText(action: FrontendAction): Promise<Record<string, unknown>> {
  const state = (window as any).state || {};
  const editor = state.activeEditor || null;
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

function _documentContextDetails(action: FrontendAction): Record<string, unknown> {
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
      canSave: typeof (window as any).WA?.saveFile === 'function',
      canOpenWorkspaceFile: typeof (window as any).WA?.openWorkspaceFile === 'function',
      richSelectionKinds: ['docx-text', 'docx-table', 'pptx-shape', 'pptx-table', 'xlsx-range', 'pdf-text'],
    },
  };
}

async function _saveCurrentFile(action: FrontendAction): Promise<Record<string, unknown>> {
  const wa = (window as any).WA || {};
  if (typeof wa.saveFile !== 'function') throw new Error('WA.saveFile is not available');
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

async function _fetchWorkspaceFiles(action: FrontendAction): Promise<Record<string, unknown>> {
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

async function _openWorkspaceFile(action: FrontendAction): Promise<Record<string, unknown>> {
  const path = String(action.path || action.value || action.text || action.selector || '').trim()
    .replace(/^workspace[\\/]/i, '');
  if (!path) throw new Error('Workspace file path is required');
  const wa = (window as any).WA || {};
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

function _snapshotDetails(): Record<string, unknown> {
  const active = document.activeElement instanceof Element
    ? _targetSummary(document.activeElement)
    : {};
  return {
    title: document.title,
    readyState: document.readyState,
    visibilityState: document.visibilityState,
    viewport: {
      width: window.innerWidth,
      height: window.innerHeight,
      devicePixelRatio: window.devicePixelRatio,
    },
    activeElement: active,
    visibleDialogs: Array.from(document.querySelectorAll('[role="dialog"], dialog, .modal, .dialog'))
      .filter((item) => {
        const el = item as HTMLElement;
        const style = window.getComputedStyle(el);
        return style.display !== 'none' && style.visibility !== 'hidden' && el.offsetParent !== null;
      })
      .slice(0, 8)
      .map((item) => _targetSummary(item)),
    toasts: _selectedTexts('.toast, .wa-toast, [data-toast]', 8),
    activeTabs: _selectedTexts('.active, [aria-selected="true"]', 12),
    bodyClasses: document.body?.className || '',
    workspace: _workspaceStateDetails(),
  };
}

function _enqueue(event: FrontendEvent): void {
  const enriched = {
    ...event,
    client_ts: event.client_ts || _now(),
    url: event.url || location.href,
    route: event.route || _route(),
    session_id: event.session_id || _getSessionId(),
    source: event.source || 'browser',
  };
  _queue.push(enriched);
  if (_queue.length > MAX_QUEUE) _queue = _queue.slice(-MAX_QUEUE);
  if (_flushTimer !== null) return;
  _flushTimer = window.setTimeout(_flush, 250);
}

function _csrfHeaders(): Record<string, string> {
  const token = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (token) headers['X-CSRFToken'] = token;
  return headers;
}

function _flush(): void {
  if (_flushTimer !== null) {
    window.clearTimeout(_flushTimer);
    _flushTimer = null;
  }
  const events = _queue.splice(0, _queue.length);
  if (!events.length) return;
  const fetchImpl = _originalFetch || window.fetch.bind(window);
  fetchImpl(ENDPOINT, {
    method: 'POST',
    headers: _csrfHeaders(),
    body: JSON.stringify({ events }),
    keepalive: JSON.stringify({ events }).length < 60000,
  }).catch(() => {});
}

function _recordSnapshot(reason: string): void {
  _enqueue({
    type: 'snapshot',
    level: 'info',
    message: reason,
    details: _snapshotDetails(),
  });
}

function _installConsole(): void {
  const originalError = console.error.bind(console);
  const originalWarn = console.warn.bind(console);
  console.error = (...args: unknown[]) => {
    _enqueue({
      type: 'console',
      level: 'error',
      message: args.map(_argToText).join(' '),
      details: { args: args.map(_argToText).slice(0, 8) },
    });
    originalError(...args);
  };
  console.warn = (...args: unknown[]) => {
    _enqueue({
      type: 'console',
      level: 'warn',
      message: args.map(_argToText).join(' '),
      details: { args: args.map(_argToText).slice(0, 8) },
    });
    originalWarn(...args);
  };
}

function _installRuntimeErrors(): void {
  window.addEventListener('error', (event) => {
    _enqueue({
      type: 'runtime_error',
      level: 'error',
      message: event.message || 'runtime error',
      details: {
        filename: event.filename,
        lineno: event.lineno,
        colno: event.colno,
        error: _errorDetails(event.error),
      },
    });
  });
  window.addEventListener('unhandledrejection', (event) => {
    _enqueue({
      type: 'unhandled_rejection',
      level: 'error',
      message: _argToText(event.reason),
      details: { reason: _errorDetails(event.reason) },
    });
  });
}

function _installFetch(): void {
  _originalFetch = window.fetch.bind(window);
  window.fetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const started = performance.now();
    const url = typeof input === 'string'
      ? input
      : input instanceof URL
        ? input.toString()
        : input.url;
    const method = init?.method || (input instanceof Request ? input.method : 'GET');
    const isObserverCall = url.includes(ENDPOINT);
    try {
      const response = await (_originalFetch as typeof window.fetch)(input, init);
      if (!isObserverCall && !response.ok) {
        _enqueue({
          type: 'network',
          level: response.status >= 500 ? 'error' : 'warn',
          message: `${method} ${url} -> ${response.status}`,
          details: {
            method,
            status: response.status,
            statusText: response.statusText,
            durationMs: Math.round(performance.now() - started),
          },
        });
      }
      return response;
    } catch (error) {
      if (!isObserverCall) {
        _enqueue({
          type: 'network',
          level: 'error',
          message: `${method} ${url} failed`,
          details: {
            method,
            durationMs: Math.round(performance.now() - started),
            error: _errorDetails(error),
          },
        });
      }
      throw error;
    }
  };
}

function _installInteractions(): void {
  document.addEventListener('click', (event) => {
    const target = event.target instanceof Element
      ? event.target.closest('button,a,input,select,textarea,[role="button"],[data-action],.wa-tab')
      : null;
    if (!target) return;
    _enqueue({
      type: 'click',
      level: 'info',
      message: 'user click',
      details: _targetSummary(target),
    });
  }, true);
}

function _installNavigationSnapshots(): void {
  const wrapHistory = (name: 'pushState' | 'replaceState') => {
    const original = history[name].bind(history);
    history[name] = ((...args: Parameters<History['pushState']>) => {
      const result = original(...args);
      window.setTimeout(() => _recordSnapshot(name), 0);
      return result;
    }) as History[typeof name];
  };
  wrapHistory('pushState');
  wrapHistory('replaceState');
  window.addEventListener('popstate', () => _recordSnapshot('popstate'));
  document.addEventListener('visibilitychange', () => _recordSnapshot('visibilitychange'));
  window.addEventListener('load', () => _recordSnapshot('load'));
  window.setInterval(() => _recordSnapshot('interval'), SNAPSHOT_INTERVAL_MS);
}

function _setElementValue(el: Element, value: string, append: boolean): void {
  const target = el as HTMLElement;
  target.focus();
  if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) {
    el.value = append ? `${el.value}${value}` : value;
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
    return;
  }
  if ((target as HTMLElement).isContentEditable) {
    target.textContent = append ? `${target.textContent || ''}${value}` : value;
    target.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: value }));
    return;
  }
  throw new Error('Target is not editable');
}

async function _waitForTarget(action: FrontendAction): Promise<Element> {
  const timeoutMs = Number(action.options?.timeoutMs || action.options?.timeout_ms || 5000);
  const deadline = Date.now() + Math.max(100, Math.min(timeoutMs, 30000));
  while (Date.now() <= deadline) {
    const target = _findTarget(action);
    if (target && _isVisible(target)) return target;
    await new Promise((resolve) => window.setTimeout(resolve, 100));
  }
  throw new Error(`Target not found: ${action.selector || action.text || action.action}`);
}

async function _executeFrontendAction(action: FrontendAction): Promise<Record<string, unknown>> {
  if (action.action === 'snapshot') return _snapshotDetails();
  if (action.action === 'read_dom') {
    return {
      snapshot: _snapshotDetails(),
      visibleControls: _visibleControls(Number(action.options?.limit || 40)),
    };
  }
  if (action.action === 'current_file_state') return _workspaceStateDetails();
  if (action.action === 'read_editor_content') return _readEditorContent(action);
  if (action.action === 'current_selection') return _currentSelectionDetails(action);
  if (action.action === 'document_context') return _documentContextDetails(action);
  if (action.action === 'select_text_range') return _selectTextRange(action);
  if (action.action === 'replace_text_selection') return _replaceTextSelection(action);
  if (action.action === 'set_editor_content') return _setEditorContent(action);
  if (action.action === 'replace_docx_anchor_text') return _replaceDocxAnchorText(action);
  if (action.action === 'set_pptx_shape_text') return _setPptxShapeText(action);
  if (action.action === 'save_current_file') return _saveCurrentFile(action);
  if (action.action === 'list_workspace_files') return _fetchWorkspaceFiles(action);
  if (action.action === 'open_workspace_file') return _openWorkspaceFile(action);
  if (action.action === 'wait_for') {
    const target = await _waitForTarget(action);
    return { target: _targetSummary(target), visible: _isVisible(target) };
  }
  if (action.action === 'open_panel') {
    const panel = action.panel || action.text || action.value || '';
    const selector = _panelSelector(panel);
    const target = selector ? _findFirstVisible(selector.split(',').map((item) => item.trim())) : null;
    if (!target) throw new Error(`Panel target not found: ${panel || '<empty>'}`);
    (target as HTMLElement).click();
    return { panel, target: _targetSummary(target), clicked: true };
  }
  if (action.action === 'search_workspace') {
    const target = _findFirstVisible(['#wa-search', '[data-testid="workspace-search"]', 'input[type="search"]']);
    if (!target) throw new Error('Workspace search input not found');
    const value = action.value || action.text || '';
    _setElementValue(target, value, false);
    return { target: _targetSummary(target), valueLength: value.length };
  }
  if (action.action === 'submit_prompt') {
    const input = _findFirstVisible(['#wa-user-input', 'textarea[name="message"]', 'textarea', '[contenteditable="true"]']);
    if (!input) throw new Error('Assistant prompt input not found');
    const prompt = action.value || action.text || '';
    _setElementValue(input, prompt, false);
    const send = _findFirstVisible(['#wa-send-btn', '[data-action="send"]', 'button[aria-label="发送"]', 'button[title="发送"]']);
    if (!send) throw new Error('Assistant send button not found');
    (send as HTMLElement).click();
    return {
      input: _targetSummary(input),
      send: _targetSummary(send),
      promptLength: prompt.length,
      submitted: true,
    };
  }
  const target = await _waitForTarget(action);
  if (action.action === 'click') {
    (target as HTMLElement).click();
    return { target: _targetSummary(target), clicked: true };
  }
  if (action.action === 'fill' || action.action === 'type') {
    _setElementValue(target, action.value || '', action.action === 'type');
    return { target: _targetSummary(target), valueLength: (action.value || '').length };
  }
  if (action.action === 'press') {
    (target as HTMLElement).focus();
    const key = action.key || action.value || 'Enter';
    target.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true }));
    target.dispatchEvent(new KeyboardEvent('keyup', { key, bubbles: true }));
    return { target: _targetSummary(target), key };
  }
  throw new Error(`Unsupported action: ${action.action}`);
}

async function _postActionResult(id: string, ok: boolean, result: Record<string, unknown>, error = ''): Promise<void> {
  const fetchImpl = _originalFetch || window.fetch.bind(window);
  await fetchImpl(ACTION_RESULT_ENDPOINT, {
    method: 'POST',
    headers: _csrfHeaders(),
    body: JSON.stringify({ id, ok, result, error }),
    keepalive: JSON.stringify({ id, ok, result, error }).length < 60000,
  });
}

async function _pollFrontendAction(): Promise<void> {
  if (_actionPollActive) return;
  _actionPollActive = true;
  let nextDelay = _actionIdleDelayMs;
  try {
    const fetchImpl = _originalFetch || window.fetch.bind(window);
    const response = await fetchImpl(
      `${ACTION_ENDPOINT}?session_id=${encodeURIComponent(_getSessionId())}&timeout_ms=${ACTION_LONG_POLL_MS}`,
    );
    if (response.ok) {
      const payload = await response.json();
      const action = payload?.action as FrontendAction | null;
      if (action?.id) {
        _actionIdleDelayMs = ACTION_POLL_IDLE_MIN_MS;
        nextDelay = ACTION_POLL_ACTIVE_DELAY_MS;
        try {
          const result = await _executeFrontendAction(action);
          await _postActionResult(action.id, true, result);
          _enqueue({
            type: 'frontend_action',
            level: 'info',
            message: `${action.action} completed`,
            details: { actionId: action.id, action: action.action, result },
          });
        } catch (error) {
          await _postActionResult(action.id, false, {}, _argToText(error));
          _enqueue({
            type: 'frontend_action',
            level: 'error',
            message: `${action.action} failed`,
            details: { actionId: action.id, action: action.action, error: _errorDetails(error) },
          });
        }
      } else {
        nextDelay = _actionIdleDelayMs;
        _actionIdleDelayMs = Math.min(_actionIdleDelayMs * 2, ACTION_POLL_IDLE_MAX_MS);
      }
    } else {
      nextDelay = _actionIdleDelayMs;
      _actionIdleDelayMs = Math.min(_actionIdleDelayMs * 2, ACTION_POLL_IDLE_MAX_MS);
    }
  } catch (_) {
    nextDelay = _actionIdleDelayMs;
    _actionIdleDelayMs = Math.min(_actionIdleDelayMs * 2, ACTION_POLL_IDLE_MAX_MS);
    // Keep polling lightweight; normal network instrumentation covers real failures.
  } finally {
    _actionPollActive = false;
    _actionPollTimer = window.setTimeout(_pollFrontendAction, nextDelay);
  }
}

function _installFrontendActions(): void {
  if (_actionPollTimer !== null) return;
  _actionPollTimer = window.setTimeout(_pollFrontendAction, ACTION_POLL_ACTIVE_DELAY_MS);
}

export function installFrontendObserver(): void {
  if (_installed || typeof window === 'undefined') return;
  _installed = true;
  _installConsole();
  _installRuntimeErrors();
  _installFetch();
  _installInteractions();
  _installNavigationSnapshots();
  _installFrontendActions();
  _recordSnapshot('install');
  (window as any).KotoFrontendObserver = {
    record: _enqueue,
    snapshot: () => _snapshotDetails(),
    flush: _flush,
  };
}
