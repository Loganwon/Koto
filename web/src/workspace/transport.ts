/**
 * SSE transport abstraction for workspace AI communication.
 * Includes CSRF token auto-refresh pattern for safe POST requests.
 */

interface SseEvent {
  type?: string;
  [key: string]: any;
}

interface TransportDeps {
  state?: {
    _streamAbortCtrl?: AbortController | null;
    isLoading?: boolean;
    [key: string]: any;
  };
  setStreamButton?: (loading: boolean) => void;
}

interface StreamOptions {
  url: string;
  method?: string;
  body?: string | Record<string, any>;
  headers?: Record<string, string>;
  signal?: AbortSignal;
  onEvent?: (event: SseEvent) => void | Promise<void>;
  delimiter?: string;
}

// ── CSRF helpers ──

function _csrfToken(): string | null {
  const meta = document.querySelector('meta[name="csrf-token"]') as HTMLMetaElement | null;
  return (meta && meta.content) || null;
}

function _needsCsrf(method: string): boolean {
  const m = (method || 'GET').toUpperCase();
  return !['GET', 'HEAD', 'OPTIONS', 'TRACE'].includes(m);
}

function _headersWithCsrf(headers: Record<string, string> | undefined, csrf: string | null): Record<string, string> {
  const next: Record<string, string> = Object.assign({}, headers || {});
  if (csrf && !next['X-CSRFToken'] && !next['X-CSRF-Token']) {
    next['X-CSRFToken'] = csrf;
  }
  return next;
}

let _csrfRefreshPromise: Promise<string | null> | null = null;

async function _refreshCsrfToken(): Promise<string | null> {
  if (_csrfRefreshPromise) return _csrfRefreshPromise;
  _csrfRefreshPromise = fetch('/api/csrf-token', {
    method: 'GET',
    cache: 'no-store',
    credentials: 'same-origin',
  })
    .then((resp) => (resp.ok ? resp.json() : null))
    .then((data: any) => {
      const token = data && data.csrf_token;
      if (token) {
        let meta = document.querySelector('meta[name="csrf-token"]') as HTMLMetaElement | null;
        if (!meta) {
          meta = document.createElement('meta');
          meta.name = 'csrf-token';
          document.head.appendChild(meta);
        }
        meta.setAttribute('content', token);
      }
      return token || null;
    })
    .catch(() => null)
    .finally(() => { _csrfRefreshPromise = null; });
  return _csrfRefreshPromise;
}

async function _csrfFetch(url: string, options: RequestInit & { headers?: Record<string, string> } = {}): Promise<Response> {
  const fetchOptions: RequestInit = Object.assign({}, options);
  if (!fetchOptions.credentials) fetchOptions.credentials = 'same-origin';
  if (_needsCsrf(fetchOptions.method as string)) {
    const csrf = _csrfToken();
    fetchOptions.headers = _headersWithCsrf(options.headers || {}, csrf);
  }
  let response = await fetch(url, fetchOptions);
  if (response.status === 400 && _needsCsrf(fetchOptions.method as string)) {
    const token = await _refreshCsrfToken();
    if (token) {
      fetchOptions.headers = _headersWithCsrf(options.headers || {}, token);
      response = await fetch(url, fetchOptions);
    }
  }
  return response;
}

// ── SSE helpers ──

async function emitSseEvent(raw: string, onEvent?: (event: SseEvent) => void | Promise<void>): Promise<void> {
  if (!raw || !raw.startsWith('data: ')) return;
  let evt: SseEvent;
  try {
    evt = JSON.parse(raw.slice(6));
  } catch {
    return;
  }
  if (typeof onEvent === 'function') {
    await onEvent(evt);
  }
}

export function createWorkspaceAiTransport(deps: TransportDeps = {}) {
  const options = deps || {};
  const state = options.state || {};
  const setStreamButton = typeof options.setStreamButton === 'function'
    ? options.setStreamButton
    : (_loading: boolean) => {};

  function beginRequest(): AbortController {
    const ctrl = new AbortController();
    state._streamAbortCtrl = ctrl;
    state.isLoading = true;
    setStreamButton(true);
    return ctrl;
  }

  function endRequest(ctrl: AbortController): void {
    if (state._streamAbortCtrl === ctrl) state._streamAbortCtrl = null;
    state.isLoading = false;
    setStreamButton(false);
  }

  async function streamSse(opts: StreamOptions): Promise<void> {
    const requestBody = typeof opts.body === 'string'
      ? opts.body
      : JSON.stringify(opts.body || {});
    const method = opts.method || 'POST';
    const baseHeaders = Object.assign({ 'Content-Type': 'application/json' }, opts.headers || {});
    const response = await _csrfFetch(opts.url, {
      method,
      headers: baseHeaders,
      body: requestBody,
      signal: opts.signal,
    });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }

    const reader = response.body!.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    const delimiter = opts.delimiter || '\n\n';

    while (true) {
      const chunk = await reader.read();
      if (chunk.done) break;
      buffer += decoder.decode(chunk.value, { stream: true });
      const parts = buffer.split(delimiter);
      buffer = parts.pop() || '';
      for (const part of parts) {
        await emitSseEvent(part, opts.onEvent);
      }
    }

    const trailing = buffer.trim();
    if (trailing) {
      await emitSseEvent(trailing, opts.onEvent);
    }
  }

  async function streamEventBlocks(opts: StreamOptions): Promise<void> {
    return streamSse(Object.assign({}, opts, { delimiter: '\n\n' }));
  }

  async function streamEventLines(opts: StreamOptions): Promise<void> {
    return streamSse(Object.assign({}, opts, { delimiter: '\n' }));
  }

  return {
    beginRequest,
    endRequest,
    streamEventBlocks,
    streamEventLines,
  };
}

const WA = (window as any).WA || {};
WA.createWorkspaceAiTransport = createWorkspaceAiTransport;
(window as any).WA = WA;
