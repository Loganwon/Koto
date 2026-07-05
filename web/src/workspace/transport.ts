/**
 * SSE transport abstraction for workspace AI communication.
 * Delegates CSRF handling to the shared csrf module.
 */

import { csrfFetch as _sharedCsrfFetch } from '../shared/csrf';

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
  /** Per-chunk read timeout in ms (default: 120000 = 2 min) */
  timeoutMs?: number;
}

// ?? CSRF delegated to shared/csrf.ts ??

async function _csrfFetch(url: string, options: RequestInit = {}): Promise<Response> {
  return _sharedCsrfFetch(url, options);
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

    const chunkTimeout = opts.timeoutMs || 120000;
    let lastChunkTime = Date.now();
    while (true) {
      const readPromise = reader.read();
      const timeoutPromise = new Promise<ReadableStreamReadResult<Uint8Array>>((_, reject) => {
        setTimeout(() => reject(new Error(`SSE stream timed out after ${chunkTimeout}ms of inactivity`)), chunkTimeout);
      });
      let chunk: ReadableStreamReadResult<Uint8Array>;
      try {
        chunk = await Promise.race([readPromise, timeoutPromise]);
        lastChunkTime = Date.now();
      } catch (e) {
        reader.cancel();
        throw e;
      }
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
