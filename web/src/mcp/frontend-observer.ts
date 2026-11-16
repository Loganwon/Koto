import { appendToUiPortal, setFixedVisualPosition } from '../shared/ui-scale';
import { getWorkspaceRuntime as _workspaceRuntime } from './workspace-runtime-inspector';
import { getFeatureRegistry, registerFeatures } from '../shared/feature-registry';
import {
  browserActionFingerprint as _actionFingerprint,
  browserActionMutation as _actionMutation,
  getBrowserActionJournal as _browserActionJournal,
  unknownActionOutcome as _unknownOutcome,
  type ActionOutcome, type BrowserActionRecord,
} from './frontend-action-journal';

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

export type FrontendAction = {
  id: string;
  request_fingerprint?: string;
  browser_id?: string;
  delivery_token?: string;
  request_id?: string;
  session_id?: string;
  mutation?: boolean;
  action:
    | 'click'
    | 'fill'
    | 'type'
    | 'press'
    | 'snapshot'
    | 'read_dom'
    | 'task_result_evidence'
    | 'surface_inventory'
    | 'wait_for'
    | 'open_panel'
    | 'search_workspace'
    | 'submit_prompt'
    | 'attach_task_file'
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
    | 'save_current_file'
    | 'ui_read_context'
    | 'ui_apply_edit'
    | 'ui_save';
  expires_at?: number;
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
export let _originalFetch: typeof window.fetch | null = null;

function _now(): number {
  return Date.now();
}

function _route(): string {
  return `${location.pathname}${location.search}${location.hash}`;
}

function _normalizeFrontendTaskPath(path: string): string {
  let value = String(path || '').trim().replace(/\\/g, '/');
  value = value.replace(/^\.\//, '');
  if (/^workspace\//i.test(value)) {
    value = value.slice('workspace/'.length);
  }
  return value;
}

function _elementViewportClip(el: Element, padding = 8): Record<string, number> {
  const rect = el.getBoundingClientRect();
  const x = Math.max(0, Math.floor(rect.x - padding));
  const y = Math.max(0, Math.floor(rect.y - padding));
  const maxWidth = Math.max(1, window.innerWidth - x);
  const maxHeight = Math.max(1, window.innerHeight - y);
  return {
    x,
    y,
    width: Math.max(1, Math.min(Math.ceil(rect.width + padding * 2), maxWidth)),
    height: Math.max(1, Math.min(Math.ceil(rect.height + padding * 2), maxHeight)),
  };
}

function _elementRect(el: Element): Record<string, number> {
  const rect = el.getBoundingClientRect();
  return {
    x: Math.round(rect.x),
    y: Math.round(rect.y),
    width: Math.round(rect.width),
    height: Math.round(rect.height),
  };
}

function _htmlEscape(value: unknown): string {
  return String(value || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function _removeTaskEvidenceOverlay(): void {
  document.getElementById('koto-task-evidence-capture')?.remove();
}

function _renderTaskEvidenceOverlay(evidence: Record<string, unknown>): HTMLElement {
  _removeTaskEvidenceOverlay();
  const overlay = document.createElement('div');
  overlay.id = 'koto-task-evidence-capture';
  overlay.style.cssText = [
    'position:fixed',
    'left:0',
    'top:0',
    'z-index:2147483647',
    'box-sizing:border-box',
    'width:min(720px, calc(var(--koto-layout-width, 100vw) - 24px))',
    'max-height:calc(var(--koto-layout-height, 100vh) - 24px)',
    'overflow:auto',
    'padding:16px',
    'border:1px solid #d0d7de',
    'border-radius:8px',
    'background:#ffffff',
    'color:#17202a',
    'box-shadow:0 16px 48px rgba(15, 23, 42, 0.22)',
    'font:13px/1.5 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
    'white-space:normal',
  ].join(';');
  const chips = Array.isArray(evidence.chips) ? evidence.chips : [];
  const chipText = chips
    .map((item: any) => String(item && (item.title || item.text) || '').trim())
    .filter(Boolean)
    .join(', ');
  const status = String(evidence.terminalStatus || '').trim() || 'unknown';
  const taskId = String(evidence.taskId || '').trim();
  const runId = String(evidence.runId || '').trim();
  const finalAnswer = String(evidence.finalAnswer || evidence.text || '').trim();
  overlay.innerHTML = [
    '<div style="font-weight:700;font-size:15px;margin-bottom:8px;">Koto Task Result Evidence</div>',
    `<div><strong>Status:</strong> ${_htmlEscape(status)}</div>`,
    taskId ? `<div><strong>Task ID:</strong> ${_htmlEscape(taskId)}</div>` : '',
    runId ? `<div><strong>Run ID:</strong> ${_htmlEscape(runId)}</div>` : '',
    chipText ? `<div><strong>Attached:</strong> ${_htmlEscape(chipText)}</div>` : '',
    '<div style="height:1px;background:#e5e7eb;margin:12px 0;"></div>',
    `<div style="white-space:pre-wrap;">${_htmlEscape(finalAnswer || 'No final answer text captured.')}</div>`,
  ].join('');
  appendToUiPortal(overlay);
  setFixedVisualPosition(overlay, 12, 12);
  return overlay;
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

export function _argToText(value: unknown): string {
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

export function _visibleText(el: Element | null | undefined, limit = 500): string {
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

export function _targetSummary(target: EventTarget | null): Record<string, unknown> {
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

export function _isVisible(el: Element): boolean {
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
  const wa = getFeatureRegistry() || {};
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
    'toggleCapabilityPanel',
    'openCapabilityPanel',
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
}import { _assistantComposerTargets, _bestSelector, _currentSelectionDetails, _findFirstVisible, _findTarget, _limitString, _panelSelector, _readEditorContent, _safeJsonClone, _selectedTexts, _workspaceStateDetails } from './frontend-observer-targeting';
export * from './frontend-observer-targeting';import { _documentContextDetails, _fetchWorkspaceFiles, _openWorkspaceFile, _replaceDocxAnchorText, _replaceTextSelection, _saveCurrentFile, _selectTextRange, _setEditorContent, _setPptxShapeText, _readScopedDocument, _applyScopedDocumentEdit, _saveScopedDocument } from './frontend-observer-document-actions';
export * from './frontend-observer-document-actions';


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

function _taskResultEvidence(action: FrontendAction): Record<string, unknown> {
  const opts = action.options || {};
  const limit = Math.max(200, Math.min(Number(opts.limit || 2400), 8000));
  const taskId = String(opts.taskId || opts.task_id || action.value || action.text || '').trim();
  const runId = String(opts.runId || opts.run_id || action.path || '').trim();
  const selectors: string[] = [];
  if (taskId) selectors.push(`.wa-task-run[data-task-id="${CSS.escape(taskId)}"]`);
  if (runId) selectors.push(`.wa-task-run[data-task-run-id="${CSS.escape(runId)}"]`);
  selectors.push('.wa-task-run:not([data-history-snapshot="true"])', '.wa-task-run');

  let card: HTMLElement | null = null;
  let selector = '';
  for (const candidateSelector of selectors) {
    const matches = Array.from(document.querySelectorAll(candidateSelector))
      .filter((item) => _isVisible(item)) as HTMLElement[];
    if (matches.length) {
      card = matches[matches.length - 1];
      selector = candidateSelector;
      break;
    }
  }
  if (!card) {
    return {
      found: false,
      reason: 'No visible task result card found',
      chips: Array.from(document.querySelectorAll('#wa-ai-file-chip-list .wa-ctx-file-row'))
        .map((item) => _visibleText(item, 180)),
    };
  }
  if (opts.scroll !== false) {
    card.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  }
  const finalReport = card.querySelector('.wa-task-final-report, .wa-task-final-answer');
  const chips = Array.from(document.querySelectorAll('#wa-ai-file-chip-list .wa-ctx-file-row')).map((item) => ({
    text: _visibleText(item, 180),
    title: item.getAttribute('title') || '',
  }));
  const dataset = (card as HTMLElement).dataset || {};
  const evidence: Record<string, unknown> = {
    found: true,
    selector,
    taskId: dataset.taskId || '',
    runId: dataset.taskRunId || '',
    terminalStatus: dataset.taskTerminalStatus || '',
    text: _visibleText(card, limit),
    finalAnswer: finalReport ? _visibleText(finalReport, limit) : '',
    chips,
    elementRect: _elementRect(card),
    screenshotClip: _elementViewportClip(card, Number(opts.padding || 8)),
    viewport: {
      width: window.innerWidth,
      height: window.innerHeight,
      devicePixelRatio: window.devicePixelRatio,
    },
  };
  if (opts.renderOverlay) {
    const overlay = _renderTaskEvidenceOverlay(evidence);
    evidence.overlaySelector = '#koto-task-evidence-capture';
    evidence.overlayClip = _elementViewportClip(overlay, 4);
  }
  return evidence;
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
  if (action.expires_at && Date.now() >= action.expires_at * 1000) throw Object.assign(new Error('Frontend action expired before execution'), { execution_started: false });
  if (action.action === 'ui_read_context') return _readScopedDocument(action);
  if (action.action === 'ui_apply_edit') return _applyScopedDocumentEdit(action);
  if (action.action === 'ui_save') return _saveScopedDocument(action);
  if (action.action === 'snapshot') return _snapshotDetails();
  if (action.action === 'surface_inventory') return _surfaceInventoryDetails(action);
  if (action.action === 'task_result_evidence') return _taskResultEvidence(action);
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
    const targets = _assistantComposerTargets();
    const input = targets.input;
    if (!input) throw new Error('Assistant prompt input not found');
    const prompt = action.value || action.text || '';
    _setElementValue(input, prompt, false);
    const send = targets.send;
    if (!send) throw new Error('Assistant send button not found');
    (send as HTMLElement).click();
    return {
      input: _targetSummary(input),
      send: _targetSummary(send),
      promptLength: prompt.length,
      submitted: true,
    };
  }
  if (action.action === 'attach_task_file') {
    const rawPath = String(action.path || action.value || action.text || '').trim();
    const rawPaths = Array.isArray(action.options?.paths) ? action.options.paths : [];
    const paths = rawPaths.length
      ? rawPaths.map((item: unknown) => _normalizeFrontendTaskPath(String(item || ''))).filter(Boolean)
      : [_normalizeFrontendTaskPath(rawPath)].filter(Boolean);
    if (!paths.length) throw new Error('Task file path is required');
    const attachFilesToTask = getFeatureRegistry()?.attachFilesToTask;
    if (typeof attachFilesToTask !== 'function') throw new Error('FeatureRegistry.attachFilesToTask is not available');
    const result = await attachFilesToTask(paths, {
      source: 'frontend_action',
      expandPanel: action.options?.expandPanel !== false,
      focusInput: action.options?.focusInput !== false,
      duplicateToast: false,
      replaceExisting: action.options?.replaceExisting !== false,
    });
    return { attached: true, paths, result: _safeJsonClone(result, {}) };
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

type FrontendActionOutcome = ActionOutcome;
const _actionExecutions = new Map<string, Promise<FrontendActionOutcome>>();
const _actionExecutionFingerprints = new Map<string, string>();
const _pendingActionReceipts = new Map<string, BrowserActionRecord>();
/** Record the execution boundary before touching an editor or firing a DOM action. */
export function _executeFrontendActionOnce(action: FrontendAction): Promise<FrontendActionOutcome> {
  const fingerprint = _actionFingerprint(action);
  const existing = _actionExecutions.get(action.id);
  if (existing) return _actionExecutionFingerprints.get(action.id) === fingerprint ? existing : Promise.resolve({ ok: false, result: {}, error: 'Operation ID was reused for a different browser action' });
  const execution = Promise.resolve().then(async () => {
    const mutation = _actionMutation(action);
    const journal = _browserActionJournal();
    try {
      const saved = journal.get(action.id);
      if (saved) {
        if (saved.fingerprint !== fingerprint) return { ok: false, result: {}, error: 'Operation ID was reused for a different browser action' };
        if (saved.outcome) return saved.outcome;
        if (mutation) {
          const unknown = _unknownOutcome();
          journal.finish(action.id, unknown);
          return unknown;
        }
        // A read can be repeated after a crash; it cannot repeat a mutation.
      } else {
        journal.reserve({ id: action.id, fingerprint, browser_id: action.browser_id || _getSessionId(), delivery_token: action.delivery_token || '', request_id: action.request_id, session_id: action.session_id, mutation });
      }
    } catch (error) {
      if (mutation) return { ok: false, result: {}, error: `Cannot persist browser execution boundary: ${_argToText(error)}` };
    }
    let outcome: FrontendActionOutcome;
    try { outcome = { ok: true, result: await _executeFrontendAction(action), error: '' }; }
    catch (error) {
      const unknown = mutation && (error as { execution_started?: boolean })?.execution_started !== false;
      outcome = { ok: false, result: unknown ? { execution_unknown: true } : {}, error: _argToText(error), unknown };
    }
    try { journal.finish(action.id, outcome); }
    catch (_) {
      // The started marker remains unknown on reload. The current page can
      // still submit its actual in-memory receipt without executing again.
    }
    return outcome;
  });
  _actionExecutions.set(action.id, execution);
  _actionExecutionFingerprints.set(action.id, fingerprint);
  if (_actionExecutions.size > 200) {
    const oldest = _actionExecutions.keys().next().value!;
    _actionExecutions.delete(oldest);
    _actionExecutionFingerprints.delete(oldest);
  }
  return execution;
}

async function _postActionResult(record: BrowserActionRecord): Promise<boolean> {
  const outcome = record.outcome || _unknownOutcome();
  const body = JSON.stringify({ id: record.id, browser_id: record.browser_id, delivery_token: record.delivery_token, request_id: record.request_id, session_id: record.session_id, ...outcome });
  const fetchImpl = _originalFetch || window.fetch.bind(window);
  const response = await fetchImpl(ACTION_RESULT_ENDPOINT, {
    method: 'POST', headers: _csrfHeaders(), body, keepalive: body.length < 60000,
  });
  if (!response.ok) {
    if ([400, 403, 404, 409, 410].includes(response.status)) {
      _enqueue({ type: 'frontend_action_receipt_rejected', level: 'error', message: `Receipt ${record.id} was rejected`, details: { actionId: record.id, status: response.status } });
      return false;
    }
    throw new Error(`Frontend receipt was not accepted: HTTP ${response.status}`);
  }
  const accepted = await response.json();
  if (accepted?.success !== true) throw new Error('Backend did not confirm receipt persistence');
  return true;
}

export async function _flushActionReceipts(): Promise<void> {
  await _browserActionJournal().flush(_pendingActionReceipts, _postActionResult);
}

async function _pollFrontendAction(): Promise<void> {
  if (_actionPollActive) return;
  _actionPollActive = true;
  let nextDelay = _actionIdleDelayMs;
  try {
    // A failed POST retries only receipt delivery, never the document edit.
    await _flushActionReceipts();
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
        const outcome = await _executeFrontendActionOnce(action);
        const persisted = _browserActionJournal().get(action.id);
        _pendingActionReceipts.set(action.id, {
          ...(persisted || { id: action.id, fingerprint: _actionFingerprint(action), mutation: _actionMutation(action), state: outcome.unknown ? 'unknown' : (outcome.ok ? 'completed' : 'failed'), acknowledged: false, updated_at: Date.now() }),
          browser_id: action.browser_id || _getSessionId(), delivery_token: action.delivery_token || '', request_id: action.request_id, session_id: action.session_id, outcome,
        });
        await _flushActionReceipts();
        _enqueue({
          type: 'frontend_action', level: outcome.ok ? 'info' : 'error',
          message: `${action.action} ${outcome.ok ? 'completed' : 'failed'}`,
          details: { actionId: action.id, action: action.action, ok: outcome.ok, execution_unknown: outcome.unknown === true },
        });
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

export async function getDocumentToolScope(): Promise<Record<string, string> | null> {
  const runtime = _workspaceRuntime();
  const path = String(runtime.state.activeTabPath || runtime.state.wsSourcePath || '');
  const fileId = String(runtime.state.fileId || '');
  if (!path || !fileId) return null;
  const fetchImpl = _originalFetch || window.fetch.bind(window);
  const response = await fetchImpl(ENDPOINT, {
    method: 'POST', headers: _csrfHeaders(),
    body: JSON.stringify({ type: 'snapshot', session_id: _getSessionId(), details: _snapshotDetails() }),
  });
  if (!response.ok) throw new Error('The open document could not be bound to its browser session');
  return {
    frontend_session_id: _getSessionId(), document_path: path, file_id: fileId,
    source_sha256: String(runtime.state.sourceSha256 || ''),
  };
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
  registerFeatures({ frontendObserver: {
    record: _enqueue,
    snapshot: () => _snapshotDetails(),
    flush: _flush,
  }, getDocumentToolScope });
}
