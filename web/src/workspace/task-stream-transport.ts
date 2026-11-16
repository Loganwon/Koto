import { persistedTaskStreamEvent, isTaskStreamTerminalEvent } from './file-task-sse';
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
import { installTaskReconnectAction, taskStreamResumeUrl } from './task-stream-reconnect';
import { createTaskScrollFollower } from './task-follow-scroll';

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

  function markCancelRequested(card: TCard): void {
    card.dataset.taskCancelRequested = 'true';
    const status = card.querySelector('[data-role="status"]');
    if (status) status.textContent = '正在停止…';
    const button = card.querySelector<HTMLButtonElement>('[data-role="cancel"]');
    if (button) { button.disabled = true; button.textContent = '正在停止'; }
  }

  async function requestTaskCancellation(card: TCard): Promise<void> {
    const taskId = String(card.dataset.taskId || '').trim();
    if (!taskId) throw new Error('任务尚未登记，暂时不能确认停止');
    try {
      const response = await runtime.csrfFetch(`/api/tasks/${encodeURIComponent(taskId)}/cancel`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ run_id: card.dataset.taskRunId || '' }),
      });
      if (!response.ok) throw new Error(await describeHttpError(response));
      // The durable cancel request is accepted. Only the server terminal event
      // confirms that in-flight work has finished or rolled back.
    } catch (error) {
      card.dataset.taskCancelRequested = 'false';
      const status = card.querySelector('[data-role="status"]');
      if (status) status.textContent = '停止请求未确认，可重试';
      const button = card.querySelector<HTMLButtonElement>('[data-role="cancel"]');
      if (button) { button.disabled = false; button.textContent = '停止'; }
      throw error;
    }
  }

  const processEvent = (card: TCard, event: Record<string, any>): void => {
    const payload = event.payload || event;
    if (event.task_id || payload.task_id) card.dataset.taskId = String(event.task_id || payload.task_id);
    if (event.run_id || payload.run_id) card.dataset.taskRunId = String(event.run_id || payload.run_id);
    const seq = Number(event.seq || payload.seq || 0);
    card.dataset.taskLastSeq = String(Math.max(Number(card.dataset.taskLastSeq || 0), seq));
    runtime.processEvent(card, event);
    if (card.dataset.taskCancelRequested === 'true' && !isTaskStreamTerminalEvent(event)) markCancelRequested(card);
  };

  function streamTaskSse(
    cardOrLoadingEl: TCard | null,
    url: string,
    body: Record<string, any> | FormData,
    method?: string,
    _options?: Record<string, any>,
  ): Promise<TCard> {
    const streamingCard = runtime.makeRunCard(cardOrLoadingEl);
    streamingCard.querySelector('[data-role="reconnect-actions"]')?.remove();
    const follower = createTaskScrollFollower(document.getElementById('wa-ai-messages'), streamingCard);
    streamingCard.dataset.taskUrl = url;
    appendTaskRunCardIfDetached(streamingCard);
    runtime.claimLivePresentation(streamingCard);
    const httpMethod = String(method || 'POST').toUpperCase() || 'POST';
    const fetchAbort = new AbortController();
    const cleanupCancellation = installTaskCancelHandler(
      streamingCard,
      () => requestTaskCancellation(streamingCard),
      markCancelRequested,
    );
    return new Promise<TCard>((resolve, reject) => scheduleTaskStream(async () => {
      try {
        let terminalSeen = false;
        let lastError: unknown;
        for (let attempt = 0; attempt < 4 && !terminalSeen; attempt += 1) {
          if (attempt) {
            runtime.showReconnectNotice(streamingCard, 'recovering');
            await new Promise((next) => setTimeout(next, Math.min(250 * (2 ** attempt), 2000)));
          }
          const requestUrl = httpMethod === 'GET' && attempt
            ? streamingCard.dataset.taskId && streamingCard.dataset.taskRunId
              ? taskStreamResumeUrl({ taskId: streamingCard.dataset.taskId, runId: streamingCard.dataset.taskRunId, afterSeq: Number(streamingCard.dataset.taskLastSeq || 0) })
              : url.replace(/([?&])after_seq=\d+/, '$1after_seq=' + (streamingCard.dataset.taskLastSeq || '0'))
            : url;
          try {
        const response = await fetchImpl(requestUrl, {
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
        const consumed = await consumeTaskEventStream(reader, {
          transformEvent: persistedTaskStreamEvent,
          onEvent: (event) => processEvent(streamingCard, event),
          onBatch: () => follower.notify(),
          stopOnTerminal: true,
        });
        terminalSeen = consumed.terminalSeen;
        if (!terminalSeen) throw new Error('任务状态流已断开，正在保留后台任务状态。');
          } catch (error) {
            lastError = error;
            if (httpMethod !== 'GET' || fetchAbort.signal.aborted) throw error;
          }
        }
        if (!terminalSeen) throw lastError;
        runtime.stopHeartbeat(streamingCard);
            if (streamingCard.dataset.taskId && streamingCard.dataset.taskRunId) {
              installTaskReconnectAction(streamingCard, () => resumePersistedTask({
                taskId: streamingCard.dataset.taskId!, runId: streamingCard.dataset.taskRunId!,
                loadingEl: streamingCard, initialStatus: 'running', replay: true,
              }), () => requestTaskCancellation(streamingCard));
            }
        resolve(streamingCard);
      } catch (error: any) {
        if (error?.name !== 'AbortError') {
          runtime.showReconnectNotice(streamingCard, 'failed');
          runtime.stopHeartbeat(streamingCard);
        }
        reject(error);
      } finally {
        cleanupCancellation();
        follower.dispose();
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
    const follower = createTaskScrollFollower(messages, card);
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
    follower.notify();

    let reader: ReadableStreamDefaultReader<Uint8Array> | null = null;
    let recoveryAttempted = false;
    const clearCancellation = installTaskCancelHandler(
      card, () => requestTaskCancellation(card), markCancelRequested,
    );
    card._abortFileTaskStream = () => card._cancelHandler?.();
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
      const { terminalSeen } = await consumeTaskEventStream(reader, {
        onEvent: (event) => processEvent(card, event),
        onBatch: () => {
          notifyTaskCardSnapshot(card, streamOptions.onTaskCardSnapshot);
          follower.notify();
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
        try { const recovered = await resumePersistedTask({
          taskId,
          runId: String(card.dataset.taskRunId || '').trim(),
          loadingEl: card,
          initialStatus: 'running',
          replay: true,
        });
        return runtime.terminalResult(recovered);
        } catch (recoveryError) {
          installTaskReconnectAction(card, () => resumePersistedTask({
            taskId, runId: String(card.dataset.taskRunId || ''), loadingEl: card,
            initialStatus: 'running', replay: true,
          }), () => requestTaskCancellation(card));
          throw recoveryError;
        }
      }
      if (!aborted) runtime.showReconnectNotice(card, 'failed');
      throw error;
    } finally {
      card.classList.remove('streaming');
      runtime.stopHeartbeat(card);
      notifyTaskCardSnapshot(card, streamOptions.onTaskCardSnapshot);
      if (card._abortFileTaskStream) delete card._abortFileTaskStream;
      clearCancellation();
      clearTerminalSnapshotHandler();
      follower.dispose();
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
