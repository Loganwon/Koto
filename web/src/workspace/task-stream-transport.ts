import { persistedTaskStreamEvent } from './file-task-sse';
import {
  consumeTaskEventStream,
  installTaskCancelHandler,
} from './task-stream-lifecycle';
import {
  installTerminalSnapshotHandler,
  notifyTaskCardSnapshot,
  type ResumePersistedTaskOptions,
} from './task-run-recovery';
import { normalizeQuickActionMode } from './task-result-presentation';

export interface TaskStreamTransportCard extends HTMLElement {
  _fatalErrorText?: string;
  _abortFileTaskStream?: () => void;
  _cancelHandler?: () => void;
}

export interface StreamFileTaskOptions<TCard extends TaskStreamTransportCard> {
  payload?: Record<string, any>;
  msgs?: HTMLElement | null;
  loadingEl?: TCard | null;
  signal?: AbortSignal;
  abortController?: AbortController;
  onTaskCardSnapshot?: (_card: TCard) => void;
}

interface TaskStreamRequestOptions {
  method?: string;
  headers?: Record<string, string>;
  body?: BodyInit | null;
  signal?: AbortSignal;
}

type FetchLike = (
  _input: string,
  _init?: TaskStreamRequestOptions,
) => Promise<Response>;

export interface TaskStreamTransportRuntime<
  TCard extends TaskStreamTransportCard,
  TTerminalResult extends { summary?: string },
> {
  makeRunCard: (_loadingEl: TCard | null) => TCard;
  claimLivePresentation: (_card: TCard) => void;
  finalizeCancellation: (_card: TCard) => void;
  processEvent: (_card: TCard, _event: Record<string, any>) => void;
  stopHeartbeat: (_card: TCard) => void;
  startHeartbeat: (_card: TCard) => void;
  seedRouteModelContext: (_card: TCard, _payload: Record<string, any>) => void;
  prepareActive: (_card: TCard) => void;
  showReconnectNotice: (
    _card: TCard,
    _state: 'recovering' | 'failed',
  ) => void;
  terminalResult: (_card: TCard, _fallback?: string) => TTerminalResult;
  csrfFetch: FetchLike;
  fetchImpl?: FetchLike;
}

function randomToken(length: number): string {
  const uuid = globalThis.crypto
    && typeof globalThis.crypto.randomUUID === 'function'
    ? globalThis.crypto.randomUUID().replace(/-/g, '')
    : `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 14)}`;
  return uuid.slice(0, length);
}

export function createFileTaskId(): string {
  return `task_${randomToken(32)}`;
}

export function createFileTaskRunId(): string {
  return randomToken(12);
}

async function describeHttpError(response: Response): Promise<string> {
  let detail = '';
  try {
    const data = await response.clone().json();
    detail = data && (
      data.error || data.message || data.description || data.detail || ''
    );
  } catch (_) {
    try { detail = await response.clone().text(); } catch (__) { detail = ''; }
  }
  const suffix = detail ? `: ${String(detail).slice(0, 400)}` : '';
  return `HTTP ${response.status}${suffix}`;
}

function makeTaskError(message: string): Error & { waTaskError: boolean } {
  const error = new Error(
    String(message || '任务失败'),
  ) as Error & { waTaskError: boolean };
  error.waTaskError = true;
  return error;
}

function scrollToBottom(container?: HTMLElement | null): void {
  if (container) container.scrollTop = container.scrollHeight;
}

function scheduleTaskStream(run: () => void): void {
  const scheduler = typeof (globalThis as any).setImmediate === 'function'
    ? (globalThis as any).setImmediate
    : (callback: () => void) => window.setTimeout(callback, 0);
  scheduler(run);
}

export function createTaskStreamTransport<
  TCard extends TaskStreamTransportCard,
  TTerminalResult extends { summary?: string },
>(runtime: TaskStreamTransportRuntime<TCard, TTerminalResult>) {
  const fetchImpl: FetchLike = runtime.fetchImpl
    || ((input, init) => globalThis.fetch(input, init));
  let resumePersistedTask = async (
    _options: ResumePersistedTaskOptions<TCard>,
  ): Promise<TCard> => {
    throw new Error('任务恢复尚未初始化。');
  };

  function setResumePersistedTask(
    handler: (
      _options: ResumePersistedTaskOptions<TCard>,
      _taskContract?: Record<string, any>,
    ) => Promise<TCard>,
  ): void {
    resumePersistedTask = handler;
  }

  function appendTaskRunCardIfDetached(card: TCard): void {
    if (!card || card.isConnected) return;
    const messages = document.getElementById('wa-ai-messages');
    if (messages) messages.appendChild(card);
  }

  function streamTaskSse(
    cardOrLoadingEl: TCard | null,
    url: string,
    body: Record<string, any> | FormData,
    method?: string,
    _options?: Record<string, any>,
  ): Promise<TCard> {
    const streamingCard = runtime.makeRunCard(cardOrLoadingEl);
    streamingCard.dataset.taskUrl = url;
    appendTaskRunCardIfDetached(streamingCard);
    runtime.claimLivePresentation(streamingCard);
    const httpMethod = String(method || 'POST').toUpperCase() || 'POST';
    const fetchAbort = new AbortController();
    const cleanupCancellation = installTaskCancelHandler(
      streamingCard,
      () => { try { fetchAbort.abort(); } catch { /* noop */ } },
      runtime.finalizeCancellation,
    );
    return new Promise<TCard>((resolve, reject) => scheduleTaskStream(async () => {
      try {
        const response = await fetchImpl(url, {
          method: httpMethod,
          headers: httpMethod !== 'GET'
            ? { 'Content-Type': 'application/json' }
            : undefined,
          body: httpMethod !== 'GET' ? JSON.stringify(body) : undefined,
          signal: fetchAbort.signal,
        });
        if (!response.ok) {
          throw new Error(
            '请求失败: ' + response.status + ' ' + response.statusText,
          );
        }
        if (!response.body) throw new Error('响应流不可用');
        const reader = response.body.getReader();
        const { terminalSeen } = await consumeTaskEventStream(reader, {
          transformEvent: persistedTaskStreamEvent,
          onEvent: (event) => runtime.processEvent(streamingCard, event),
        });
        if (!terminalSeen) {
          throw new Error('任务状态流已断开，正在保留后台任务状态。');
        }
        runtime.stopHeartbeat(streamingCard);
        resolve(streamingCard);
      } catch (error: any) {
        if (error?.name !== 'AbortError') {
          runtime.showReconnectNotice(streamingCard, 'failed');
          runtime.stopHeartbeat(streamingCard);
        }
        reject(error);
      } finally {
        cleanupCancellation();
      }
    }));
  }

  async function streamTaskFlow(
    optionsOrLoadingEl: StreamFileTaskOptions<TCard> | TCard | null,
    url?: string,
    body?: Record<string, any> | FormData,
    method?: string,
    options?: Record<string, any>,
  ): Promise<TTerminalResult | TCard> {
    if (url) {
      return streamTaskSse(
        optionsOrLoadingEl as TCard | null,
        url,
        body || {},
        method,
        options,
      );
    }

    const streamOptions = (
      optionsOrLoadingEl
      && typeof optionsOrLoadingEl === 'object'
      && !('classList' in optionsOrLoadingEl)
    )
      ? optionsOrLoadingEl as StreamFileTaskOptions<TCard>
      : { loadingEl: optionsOrLoadingEl as TCard | null };
    const messages = streamOptions.msgs
      || document.getElementById('wa-ai-messages');
    const card = runtime.makeRunCard(streamOptions.loadingEl || null);
    const payload = streamOptions.payload
      && typeof streamOptions.payload === 'object'
      ? streamOptions.payload
      : {};

    if (!String(payload.run_id || '').trim()) {
      payload.run_id = createFileTaskRunId();
    }
    if (!String(payload.task_id || payload.taskId || '').trim()) {
      payload.task_id = createFileTaskId();
    }
    card.dataset.taskId = String(
      payload.task_id || payload.taskId || '',
    ).trim();
    card.dataset.taskRunId = String(payload.run_id || '').trim();
    runtime.seedRouteModelContext(card, payload);
    const quickActionMode = normalizeQuickActionMode(
      payload.options && typeof payload.options === 'object'
        ? String(payload.options.quick_action_mode || '').trim()
        : '',
    );
    if (quickActionMode) card.dataset.taskQuickActionMode = quickActionMode;
    if (!streamOptions.loadingEl && messages) messages.appendChild(card);
    runtime.prepareActive(card);
    runtime.startHeartbeat(card);
    runtime.claimLivePresentation(card);
    const clearTerminalSnapshotHandler = installTerminalSnapshotHandler(
      card,
      streamOptions.onTaskCardSnapshot,
    );
    notifyTaskCardSnapshot(card, streamOptions.onTaskCardSnapshot);
    scrollToBottom(messages);

    let reader: ReadableStreamDefaultReader<Uint8Array> | null = null;
    let recoveryAttempted = false;
    try {
      const response = await runtime.csrfFetch('/api/editor/ai/task-stream', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'text/event-stream',
        },
        body: JSON.stringify(payload),
        signal: streamOptions.signal,
      });
      if (!response.ok) throw new Error(await describeHttpError(response));
      if (!response.body) throw new Error('响应流不可用');

      reader = response.body.getReader();
      card._abortFileTaskStream = () => {
        try {
          if (
            streamOptions.abortController
            && typeof streamOptions.abortController.abort === 'function'
            && !streamOptions.abortController.signal?.aborted
          ) {
            streamOptions.abortController.abort();
          }
        } catch (_) { /* noop */ }
        try {
          if (reader && typeof reader.cancel === 'function') void reader.cancel();
        } catch (_) { /* noop */ }
      };

      const { terminalSeen } = await consumeTaskEventStream(reader, {
        onEvent: (event) => runtime.processEvent(card, event),
        onBatch: () => {
          notifyTaskCardSnapshot(card, streamOptions.onTaskCardSnapshot);
          scrollToBottom(messages);
        },
        stopOnTerminal: true,
      });
      if (!terminalSeen) throw new Error('任务状态流已断开。');
    } catch (error: any) {
      if (card._fatalErrorText) throw makeTaskError(card._fatalErrorText);
      const aborted = error?.name === 'AbortError';
      const taskId = String(card.dataset.taskId || '').trim();
      if (!aborted && !recoveryAttempted && taskId) {
        recoveryAttempted = true;
        runtime.showReconnectNotice(card, 'recovering');
        const recovered = await resumePersistedTask({
          taskId,
          runId: String(card.dataset.taskRunId || '').trim(),
          loadingEl: card,
          initialStatus: 'running',
          replay: true,
        });
        return runtime.terminalResult(recovered);
      }
      if (!aborted) runtime.showReconnectNotice(card, 'failed');
      throw error;
    } finally {
      card.classList.remove('streaming');
      runtime.stopHeartbeat(card);
      notifyTaskCardSnapshot(card, streamOptions.onTaskCardSnapshot);
      if (card._abortFileTaskStream) delete card._abortFileTaskStream;
      clearTerminalSnapshotHandler();
    }

    const terminalResult = runtime.terminalResult(card, '');
    if (card._fatalErrorText) {
      throw makeTaskError(terminalResult.summary || card._fatalErrorText);
    }
    return terminalResult;
  }

  return {
    appendTaskRunCardIfDetached,
    setResumePersistedTask,
    streamTaskFlow,
    streamTaskSse,
  };
}
