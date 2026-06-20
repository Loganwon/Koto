/**
 * Core Infrastructure — CSRF helpers, toast, SVG icon factories, file icons.
 * Extracted from workspace-assistant.js lines 1-324.
 */

export interface CsrfOptions {
  url?: string;
  method?: string;
  headers?: Record<string, string> | Headers;
  credentials?: RequestCredentials;
  body?: any;
  [key: string]: any;
}

export interface ToastOptions {
  message: string;
  kind?: 'success' | 'error' | 'info' | 'warning';
  duration?: number;
}

export interface SvgIconConfig {
  width?: number;
  height?: number;
  viewBox?: string;
  strokeWidth?: number;
  pageFill?: string;
  pageStroke?: string;
  foldFill?: string;
  badgeFill?: string;
  lineColor?: string;
  labelColor?: string;
  fontSize?: number;
  fontWeight?: number;
}

export function $(id: string): HTMLElement | null {
  return document.getElementById(id);
}

function _csrfToken(): string {
  const meta = document.querySelector('meta[name="csrf-token"]');
  return meta ? String(meta.getAttribute('content') || '') : '';
}

function _setCsrfToken(token: string): string {
  const value = String(token || '').trim();
  if (!value) return '';
  let meta = document.querySelector('meta[name="csrf-token"]');
  if (!meta) {
    meta = document.createElement('meta');
    meta.setAttribute('name', 'csrf-token');
    document.head.appendChild(meta);
  }
  meta.setAttribute('content', value);
  return value;
}

let _csrfRefreshPromise: Promise<string> | null = null;

async function _refreshCsrfToken(): Promise<string> {
  if (_csrfRefreshPromise) return _csrfRefreshPromise;
  _csrfRefreshPromise = fetch('/api/csrf-token', {
    method: 'GET',
    cache: 'no-store',
    credentials: 'same-origin',
  })
    .then((resp) => (resp.ok ? resp.json() : null))
    .then((data: any) => _setCsrfToken(data && data.csrf_token))
    .catch(() => '')
    .finally(() => {
      _csrfRefreshPromise = null;
    });
  return _csrfRefreshPromise;
}

function _headersWithCsrf(headers?: Record<string, string> | Headers): Record<string, string> | Headers {
  const csrf = _csrfToken();
  if (!csrf) return headers || {};
  if (headers instanceof Headers) {
    if (!headers.has('X-CSRFToken')) headers.set('X-CSRFToken', csrf);
    return headers;
  }
  const next: Record<string, string> = Object.assign({}, headers || {});
  if (!next['X-CSRFToken'] && !next['X-CSRF-Token']) next['X-CSRFToken'] = csrf;
  return next;
}

function _needsCsrf(method?: string): boolean {
  return !['GET', 'HEAD', 'OPTIONS', 'TRACE'].includes(String(method || 'GET').toUpperCase());
}

export async function _csrfFetch(url: string, options: CsrfOptions = {}): Promise<Response> {
  const fetchOptions: CsrfOptions = Object.assign({}, options);
  if (!fetchOptions.credentials) fetchOptions.credentials = 'same-origin';
  if (_needsCsrf(fetchOptions.method)) {
    fetchOptions.headers = _headersWithCsrf(fetchOptions.headers);
  }
  let response = await fetch(url, fetchOptions as RequestInit);
  if (response.status === 400 && _needsCsrf(fetchOptions.method)) {
    const token = await _refreshCsrfToken();
    if (token) {
      fetchOptions.headers = _headersWithCsrf(options.headers);
      response = await fetch(url, fetchOptions as RequestInit);
    }
  }
  return response;
}

// Document listener cleanup registry
const _docListeners: Array<{ type: string; listener: EventListenerOrEventListenerObject; options?: any }> = [];
const _origDocAddEventListener = document.addEventListener.bind(document);
const _origDocRemoveEventListener = document.removeEventListener.bind(document);

document.addEventListener = function (type: string, listener: EventListenerOrEventListenerObject, options?: any) {
  _docListeners.push({ type, listener, options });
  return _origDocAddEventListener(type, listener, options);
};
document.removeEventListener = function (type: string, listener: EventListenerOrEventListenerObject, options?: any) {
  _docListeners.filter((entry) => {
    return !(entry.type === type && entry.listener === listener);
  });
  return _origDocRemoveEventListener(type, listener, options);
};

function _cleanupDocumentListeners(): void {
  let removed = 0;
  while (_docListeners.length > 0) {
    const entry = _docListeners.pop()!;
    try {
      _origDocRemoveEventListener(entry.type, entry.listener, entry.options);
      removed++;
    } catch (_) {
      /* ignore */
    }
  }
  document.addEventListener = function (type: string, listener: EventListenerOrEventListenerObject, options?: any) {
    _docListeners.push({ type, listener, options });
    return _origDocAddEventListener(type, listener, options);
  };
  if (removed > 0) console.log('[WA] Cleaned up ' + removed + ' document event listeners');
}

// Toast
let _waToastTimer: ReturnType<typeof setTimeout> | null = null;

export function showToast(message: string, kind: 'success' | 'error' | 'info' | 'warning' = 'info', duration: number = 2600): void {
  const toast = $('wa-toast');
  if (!toast) return;
  const tone = kind === 'success' || kind === 'error' || kind === 'info' ? kind : 'info';
  toast.textContent = String(message || '');
  toast.className = '';
  toast.classList.add(tone, 'show');
  if (_waToastTimer !== null) clearTimeout(_waToastTimer);
  _waToastTimer = setTimeout(() => {
    toast.classList.remove('show');
  }, Math.max(800, Number(duration) || 2600));
}

// SVG icon factories
function _waIcon(paths: string, opts: SvgIconConfig = {}): string {
  const width = opts.width || 14;
  const height = opts.height || 14;
  const viewBox = opts.viewBox || '0 0 24 24';
  const strokeWidth = opts.strokeWidth || 1.8;
  return `<svg width="${width}" height="${height}" viewBox="${viewBox}" fill="none" stroke="currentColor" stroke-width="${strokeWidth}" stroke-linecap="round" stroke-linejoin="round">${paths}</svg>`;
}

function _waBrandFileSvg(label: string, opts: SvgIconConfig = {}): string {
  const width = opts.width || 14;
  const height = opts.height || 14;
  const pageFill = opts.pageFill || '#ffffff';
  const pageStroke = opts.pageStroke || '#cbd5e1';
  const foldFill = opts.foldFill || '#e2e8f0';
  const badgeFill = opts.badgeFill || '#2563eb';
  const lineColor = opts.lineColor || '#dbe3ee';
  const labelColor = opts.labelColor || '#ffffff';
  const fontSize = opts.fontSize || (String(label || '').length > 1 ? 4.2 : 7.2);
  const fontWeight = opts.fontWeight || 700;
  const safeLabel = String(label || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
  return `
    <svg width="${width}" height="${height}" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <path d="M7 2.75h7L18.25 7v12A2.25 2.25 0 0 1 16 21.25H7A2.25 2.25 0 0 1 4.75 19V5A2.25 2.25 0 0 1 7 2.75Z" fill="${pageFill}" stroke="${pageStroke}" stroke-width="1.2"/>
      <path d="M14 2.75V7h4.25" fill="${foldFill}" stroke="${pageStroke}" stroke-width="1.2" stroke-linejoin="round"/>
      <path d="M15.2 11.5h2.2" stroke="${lineColor}" stroke-width="1.2" stroke-linecap="round"/>
      <path d="M15.2 14.2h2.2" stroke="${lineColor}" stroke-width="1.2" stroke-linecap="round"/>
      <path d="M15.2 16.9h1.5" stroke="${lineColor}" stroke-width="1.2" stroke-linecap="round"/>
      <rect x="3" y="9.25" width="10.5" height="10.5" rx="1.9" fill="${badgeFill}"/>
      <text x="8.25" y="16.15" text-anchor="middle" font-size="${fontSize}" font-weight="${fontWeight}" fill="${labelColor}" font-family="Segoe UI, Arial, sans-serif">${safeLabel}</text>
    </svg>`;
}

function _waImageFileSvg(opts: SvgIconConfig = {}): string {
  const width = opts.width || 14;
  const height = opts.height || 14;
  return `
    <svg width="${width}" height="${height}" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <rect x="3.5" y="4" width="17" height="15.5" rx="2.5" fill="#ffffff" stroke="#cbd5e1" stroke-width="1.2"/>
      <rect x="6" y="7" width="12" height="9.5" rx="1.4" fill="#dbeafe"/>
      <circle cx="9.2" cy="10" r="1.4" fill="#f59e0b"/>
      <path d="M7.2 15.2 10.3 12l2.6 2.6 1.8-1.8 2.1 2.4Z" fill="#22c55e"/>
    </svg>`;
}

// SVG icon constants
export const _DEFAULT_FILE_SVG = _waIcon(
  '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" />' +
    '<path d="M14 3v5h5" />'
);
export const _DOC_SVG = _waIcon(
  '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" />' +
    '<path d="M14 3v5h5" />' +
    '<path d="M8.5 13h7" />' +
    '<path d="M8.5 16h7" />'
);
export const _FOLDER_SVG = _waIcon('<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />');
export const _FOLDER_OPEN_SVG = _waIcon(
  '<path d="M3 9a2 2 0 0 1 2-2h4l2 2h9l-2 8a2 2 0 0 1-2 1.5H6a2 2 0 0 1-2-1.5z" />' +
    '<path d="M3 9V7a2 2 0 0 1 2-2h4l2 2h4" />'
);
export const _FOLDER_PICK_SVG = _waIcon(
  '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v2" />' +
    '<path d="M3 9v8a2 2 0 0 0 2 2h8" />' +
    '<path d="M17 14v6" /><path d="M14 17h6" />'
);
export const _PIN_SVG = _waIcon(
  '<path d="M9 4h6l-1 4 2 2H8l2-2z" />' +
    '<path d="M12 10v10" />'
);
export const _PENCIL_SVG = _waIcon(
  '<path d="m4 20 4.5-1 8.8-8.8a2.1 2.1 0 0 0-3-3L5.5 16 4 20z" />' +
    '<path d="m13.5 6.5 4 4" />'
);
export const _SEARCH_SVG = _waIcon('<circle cx="11" cy="11" r="6" /><path d="m20 20-3.5-3.5" />');
export const _CLIPBOARD_SVG = _waIcon(
  '<rect x="7" y="5" width="10" height="14" rx="2" />' +
    '<path d="M9 5.5h6" />' +
    '<path d="M10 3h4a1 1 0 0 1 1 1v1.5H9V4a1 1 0 0 1 1-1z" />'
);
export const _CHART_SVG = _waIcon('<path d="M4 19h16" /><path d="M7 16v-5" /><path d="M12 16V7" /><path d="M17 16v-8" />');
export const _LIGHTBULB_SVG = _waIcon(
  '<path d="M9 18h6" />' +
    '<path d="M10 21h4" />' +
    '<path d="M8.7 14.3A6 6 0 1 1 15.3 14.3C14.5 15 14 16 14 17h-4c0-1-.5-2-1.3-2.7" />'
);
export const _TRASH_SVG = _waIcon(
  '<path d="M4 6h16" />' +
    '<path d="M9 6V4h6v2" />' +
    '<path d="M7 6l1 14h8l1-14" />' +
    '<path d="M10 10v6" /><path d="M14 10v6" />'
);
export const _PAUSE_SVG = _waIcon('<path d="M9 5v14" /><path d="M15 5v14" />');
export const _SEND_SVG = _waIcon('<path d="M3 11.5 21 3l-4 18-5-6-6-3.5Z" /><path d="m12 15 5-12" />');
export const _DOWNLOAD_SVG = _waIcon('<path d="M12 3v12" /><path d="m7 10 5 5 5-5" /><path d="M4 21h16" />');
export const _CHAT_SVG = _waIcon('<path d="M21 15a2 2 0 0 1-2 2H8l-5 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />');
export const _SLIDES_SVG = _waIcon('<rect x="4" y="5" width="16" height="12" rx="2" /><path d="M8 19h8" /><path d="M12 17v2" />');
export const _SUN_SVG = _waIcon(
  '<circle cx="12" cy="12" r="4" />' +
    '<path d="M12 2v2" /><path d="M12 20v2" />' +
    '<path d="m4.93 4.93 1.41 1.41" /><path d="m17.66 17.66 1.41 1.41" />' +
    '<path d="M2 12h2" /><path d="M20 12h2" />' +
    '<path d="m4.93 19.07 1.41-1.41" /><path d="m17.66 6.34 1.41-1.41" />'
);
export const _MOON_SVG = _waIcon('<path d="M20 14.5A8.5 8.5 0 1 1 9.5 4 6.5 6.5 0 0 0 20 14.5z" />');

export const _WORD_FILE_SVG = _waBrandFileSvg('W', {
  badgeFill: '#185ABD',
  foldFill: '#DBEAFE',
  lineColor: '#BFDBFE',
});
export const _EXCEL_FILE_SVG = _waBrandFileSvg('X', {
  badgeFill: '#107C41',
  foldFill: '#DCFCE7',
  lineColor: '#BBF7D0',
});
export const _POWERPOINT_FILE_SVG = _waBrandFileSvg('P', {
  badgeFill: '#D24726',
  foldFill: '#FEE2E2',
  lineColor: '#FECACA',
});
export const _PDF_SVG = _waBrandFileSvg('PDF', {
  badgeFill: '#E53935',
  foldFill: '#FEE2E2',
  lineColor: '#FECACA',
  fontSize: 3.9,
  fontWeight: 800,
});
export const _TEXT_SVG = _waBrandFileSvg('T', {
  badgeFill: '#64748B',
  foldFill: '#E2E8F0',
  lineColor: '#CBD5E1',
});
export const _CODE_SVG = _waBrandFileSvg('</>', {
  badgeFill: '#7C3AED',
  foldFill: '#F3E8FF',
  lineColor: '#E9D5FF',
  fontSize: 3.5,
  fontWeight: 800,
});
export const _IMAGE_SVG = _waImageFileSvg();

const _EXT_ICON: Record<string, string> = {
  doc: _WORD_FILE_SVG,
  docx: _WORD_FILE_SVG,
  pdf: _PDF_SVG,
  ppt: _POWERPOINT_FILE_SVG,
  pptx: _POWERPOINT_FILE_SVG,
  xls: _EXCEL_FILE_SVG,
  xlsx: _EXCEL_FILE_SVG,
  csv: _EXCEL_FILE_SVG,
  txt: _TEXT_SVG,
  md: _TEXT_SVG,
  markdown: _TEXT_SVG,
  py: _CODE_SVG,
  js: _CODE_SVG,
  ts: _CODE_SVG,
  json: _CODE_SVG,
  html: _CODE_SVG,
  css: _CODE_SVG,
  xml: _CODE_SVG,
  yaml: _CODE_SVG,
  yml: _CODE_SVG,
  png: _IMAGE_SVG,
  jpg: _IMAGE_SVG,
  jpeg: _IMAGE_SVG,
  gif: _IMAGE_SVG,
  bmp: _IMAGE_SVG,
  webp: _IMAGE_SVG,
  svg: _IMAGE_SVG,
};

export function _fileIcon(ext: string, category: string = ''): string {
  const normalizedExt = String(ext || '').toLowerCase().replace(/^\./, '');
  const normalizedCategory = String(category || '').toLowerCase();
  const classSuffix = (normalizedExt || normalizedCategory || 'default').replace(/[^a-z0-9_-]/g, '');
  const icon =
    _EXT_ICON[normalizedExt] ||
    (normalizedCategory === 'docx' || normalizedCategory === 'word'
      ? _WORD_FILE_SVG
      : normalizedCategory === 'pdf'
        ? _PDF_SVG
        : normalizedCategory === 'xlsx' || normalizedCategory === 'spreadsheet' || normalizedCategory === 'csv'
          ? _EXCEL_FILE_SVG
          : normalizedCategory === 'pptx' || normalizedCategory === 'presentation'
            ? _POWERPOINT_FILE_SVG
            : normalizedCategory === 'image'
              ? _IMAGE_SVG
              : normalizedCategory === 'code'
                ? _CODE_SVG
                : normalizedCategory === 'text'
                  ? _TEXT_SVG
                  : normalizedCategory === 'folder'
                    ? _FOLDER_SVG
                    : _DEFAULT_FILE_SVG);
  return `<span class="wa-file-icon ext-${classSuffix}">${icon}</span>`;
}

export function _escHtml(s: any): string {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// Backward compatibility
(window as any).$ = $;
(window as any)._csrfFetch = _csrfFetch;
(window as any)._escHtml = _escHtml;
(window as any)._fileIcon = _fileIcon;
(window as any)._DEFAULT_FILE_SVG = _DEFAULT_FILE_SVG;
(window as any)._DOC_SVG = _DOC_SVG;
(window as any)._FOLDER_SVG = _FOLDER_SVG;
(window as any)._FOLDER_OPEN_SVG = _FOLDER_OPEN_SVG;
(window as any)._FOLDER_PICK_SVG = _FOLDER_PICK_SVG;
(window as any)._PIN_SVG = _PIN_SVG;
(window as any)._PENCIL_SVG = _PENCIL_SVG;
(window as any)._SEARCH_SVG = _SEARCH_SVG;
(window as any)._CLIPBOARD_SVG = _CLIPBOARD_SVG;
(window as any)._CHART_SVG = _CHART_SVG;
(window as any)._LIGHTBULB_SVG = _LIGHTBULB_SVG;
(window as any)._TRASH_SVG = _TRASH_SVG;
(window as any)._PAUSE_SVG = _PAUSE_SVG;
(window as any)._SEND_SVG = _SEND_SVG;
(window as any)._DOWNLOAD_SVG = _DOWNLOAD_SVG;
(window as any)._CHAT_SVG = _CHAT_SVG;
(window as any)._SLIDES_SVG = _SLIDES_SVG;
(window as any)._SUN_SVG = _SUN_SVG;
(window as any)._MOON_SVG = _MOON_SVG;
(window as any)._WORD_FILE_SVG = _WORD_FILE_SVG;
(window as any)._EXCEL_FILE_SVG = _EXCEL_FILE_SVG;
(window as any)._POWERPOINT_FILE_SVG = _POWERPOINT_FILE_SVG;
(window as any)._PDF_SVG = _PDF_SVG;
(window as any)._TEXT_SVG = _TEXT_SVG;
(window as any)._CODE_SVG = _CODE_SVG;
(window as any)._IMAGE_SVG = _IMAGE_SVG;
(window as any)._EXT_ICON = _EXT_ICON;
(window as any).showToast = showToast;
(window as any).WA = (window as any).WA || {};
const wa = (window as any).WA;
wa._csrfToken = _csrfToken;
wa._setCsrfToken = _setCsrfToken;
wa._refreshCsrfToken = _refreshCsrfToken;
wa._headersWithCsrf = _headersWithCsrf;
wa._needsCsrf = _needsCsrf;
wa._csrfFetch = _csrfFetch;
wa._cleanupDocumentListeners = _cleanupDocumentListeners;
wa.showToast = showToast;
