const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS', 'TRACE']);

let refreshPromise: Promise<string> | null = null;

function _csrfMeta(): HTMLMetaElement | null {
  return document.querySelector('meta[name="csrf-token"]');
}

export function getCsrfToken(): string {
  return _csrfMeta()?.getAttribute('content') || '';
}

function _setCsrfToken(token: string): string {
  let meta = _csrfMeta();
  if (!meta) {
    meta = document.createElement('meta');
    meta.setAttribute('name', 'csrf-token');
    document.head.appendChild(meta);
  }
  meta.setAttribute('content', token || '');
  return token || '';
}

export async function refreshCsrfToken(): Promise<string> {
  if (refreshPromise) return refreshPromise;
  refreshPromise = fetch('/api/csrf-token', {
    method: 'GET',
    credentials: 'same-origin',
    cache: 'no-store',
  })
    .then(async (response) => {
      if (!response.ok) return getCsrfToken();
      const data = await response.json().catch(() => ({}));
      const token = String(data?.csrf_token || data?.token || '');
      return token ? _setCsrfToken(token) : getCsrfToken();
    })
    .catch(() => getCsrfToken())
    .finally(() => {
      refreshPromise = null;
    });
  return refreshPromise;
}

function _methodNeedsCsrf(method?: string): boolean {
  return !SAFE_METHODS.has(String(method || 'GET').toUpperCase());
}

function _withCsrfHeaders(headersInit?: HeadersInit, token?: string): Headers {
  const headers = new Headers(headersInit || {});
  const nextToken = token || getCsrfToken();
  if (nextToken && !headers.has('X-CSRFToken') && !headers.has('X-CSRF-Token')) {
    headers.set('X-CSRFToken', nextToken);
  }
  return headers;
}

export async function csrfFetch(url: string, options: RequestInit = {}): Promise<Response> {
  const shared = (window as any).WA?._csrfFetch || (window as any)._csrfFetch;
  if (typeof shared === 'function') return shared(url, options);

  const method = String(options.method || 'GET').toUpperCase();
  const needsCsrf = _methodNeedsCsrf(method);
  const makeInit = (token?: string): RequestInit => {
    const init: RequestInit = { ...options, credentials: options.credentials || 'same-origin' };
    if (needsCsrf) init.headers = _withCsrfHeaders(options.headers, token);
    return init;
  };

  let response = await fetch(url, makeInit());
  if (response.status === 400 && needsCsrf) {
    const token = await refreshCsrfToken();
    if (token) response = await fetch(url, makeInit(token));
  }
  return response;
}
