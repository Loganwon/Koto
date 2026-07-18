import {
  isFileTaskWaitingStatus,
  normalizeFileTaskTerminalStatus,
} from './file-task-status';
import {
  isTaskStreamTerminalEvent,
  parseSseEvents,
} from './file-task-sse';
import {
  TaskStreamConnectionState,
  TaskWaitNoticeLevel,
  taskReconnectFeedback,
  taskWaitFeedback,
} from './task-stream-feedback';
import { escHtml as esc } from '../shared/sanitize';

export interface TaskStreamLifecycleState {
  lastActivityAt: number;
  heartbeatTimer: number | null;
  waitNoticeLevel: TaskWaitNoticeLevel;
  streamConnectionState: TaskStreamConnectionState;
}

export interface TaskStreamLifecycleCard extends HTMLElement {
  _abortFileTaskStream?: () => void;
  _cancelHandler?: () => void;
}

export interface TaskStreamLifecycleRuntime<
  TCard extends TaskStreamLifecycleCard,
  TState extends TaskStreamLifecycleState,
> {
  getState: (_card: TCard) => TState;
  isCard: (_card: unknown) => _card is TCard;
  removeStatusRow: (_card: TCard, _role: string) => void;
  restoreStageStatus: (_card: TCard) => void;
  ensureRunStep: (_card: TCard) => HTMLElement;
  currentRunStep: (_card: TCard) => HTMLElement;
  markStepRunning: (_step: HTMLElement) => void;
  upsertStatusRow: (
    _step: HTMLElement,
    _role: string,
    _kind: string,
    _html: string,
  ) => HTMLElement | null;
  setStatus: (_card: TCard, _text: string) => void;
  syncLiveProgress: (_card: TCard) => void;
  dispatchEvent: (_card: TCard, _event: Record<string, any>) => void;
}

export interface TaskStreamLifecycleController<TCard extends TaskStreamLifecycleCard> {
  clearTransientFeedback: (_card: TCard) => void;
  markActivity: (_card: TCard) => void;
  startHeartbeat: (_card: TCard) => void;
  stopHeartbeat: (_card: TCard) => void;
  showReconnectNotice: (
    _card: TCard,
    _state?: Exclude<TaskStreamConnectionState, 'connected'>,
  ) => void;
  cancelRun: (_card: TCard) => boolean;
  finalizeCancellation: (_card: TCard) => void;
}

export function createTaskStreamLifecycle<
  TCard extends TaskStreamLifecycleCard,
  TState extends TaskStreamLifecycleState,
>(runtime: TaskStreamLifecycleRuntime<TCard, TState>): TaskStreamLifecycleController<TCard> {
  const removeHeartbeatRows = (card: TCard): void => {
    runtime.removeStatusRow(card, 'task-heartbeat');
    runtime.getState(card).waitNoticeLevel = 'none';
  };

  const clearTransientFeedback = (card: TCard): void => {
    if (!card) return;
    const state = runtime.getState(card);
    const hadVisibleFeedback = state.waitNoticeLevel !== 'none'
      || state.streamConnectionState !== 'connected';
    if (state.waitNoticeLevel !== 'none') {
      runtime.removeStatusRow(card, 'task-heartbeat');
    }
    if (state.streamConnectionState !== 'connected') {
      runtime.removeStatusRow(card, 'stream-reconnect');
    }
    state.waitNoticeLevel = 'none';
    state.streamConnectionState = 'connected';
    if (hadVisibleFeedback) runtime.restoreStageStatus(card);
  };

  const markActivity = (card: TCard): void => {
    if (!card) return;
    runtime.getState(card).lastActivityAt = Date.now();
    clearTransientFeedback(card);
  };

  const startHeartbeat = (card: TCard): void => {
    if (!card) return;
    const state = runtime.getState(card);
    if (state.heartbeatTimer) return;
    state.lastActivityAt = Date.now();
    state.waitNoticeLevel = 'none';
    runtime.removeStatusRow(card, 'task-heartbeat');
    state.heartbeatTimer = window.setInterval(() => {
      if (!card.classList || !card.classList.contains('streaming')) return;
      const current = runtime.getState(card);
      const idleMs = Date.now() - Number(current.lastActivityAt || 0);
      const feedback = taskWaitFeedback(idleMs);
      if (!feedback || feedback.level === current.waitNoticeLevel) return;
      const step = runtime.ensureRunStep(card);
      step.classList.remove('pending', 'failed');
      step.classList.add('running');
      const warnClass = feedback.tone === 'warn' ? ' warn' : '';
      runtime.upsertStatusRow(
        step,
        'task-heartbeat',
        feedback.tone,
        '<span class="wa-task-chip' + warnClass + '">' + esc(feedback.chip)
          + '</span>' + esc(feedback.detail),
      );
      current.waitNoticeLevel = feedback.level;
      const statusEl = card.querySelector('[data-role="status"]') as HTMLElement | null;
      if (statusEl) statusEl.dataset.status = 'warning';
      runtime.setStatus(card, feedback.statusText);
      runtime.syncLiveProgress(card);
    }, 5000);
  };

  const stopHeartbeat = (card: TCard): void => {
    if (!card) return;
    const state = runtime.getState(card);
    if (state.heartbeatTimer) {
      window.clearInterval(state.heartbeatTimer);
      state.heartbeatTimer = null;
    }
    removeHeartbeatRows(card);
  };

  const showReconnectNotice = (
    card: TCard,
    connectionState: Exclude<TaskStreamConnectionState, 'connected'> = 'recovering',
  ): void => {
    const feedback = taskReconnectFeedback(connectionState);
    const state = runtime.getState(card);
    removeHeartbeatRows(card);
    state.streamConnectionState = feedback.state;
    const step = runtime.currentRunStep(card);
    runtime.markStepRunning(step);
    runtime.upsertStatusRow(
      step,
      'stream-reconnect',
      'warn',
      '<span class="wa-task-chip warn">' + esc(feedback.chip) + '</span>'
        + esc(feedback.detail),
    );
    const statusEl = card.querySelector('[data-role="status"]') as HTMLElement | null;
    if (statusEl) statusEl.dataset.status = 'warning';
    runtime.setStatus(card, feedback.statusText);
    runtime.syncLiveProgress(card);
  };

  const finalizeCancellation = (card: TCard): void => {
    if (!card || card.dataset.taskTerminalStatus === 'cancelled') return;
    stopHeartbeat(card);
    runtime.dispatchEvent(card, {
      type: 'run.cancelled',
      payload: { text: '任务已被取消。', completed_task: false },
    });
    card.classList.remove('streaming', 'pending');
    card.classList.add('cancelled');
    runtime.syncLiveProgress(card);
  };

  const cancelRun = (card: TCard): boolean => {
    if (!card || !runtime.isCard(card)) return false;
    if (typeof card._cancelHandler === 'function') {
      card._cancelHandler();
      return true;
    }
    if (typeof card._abortFileTaskStream === 'function') {
      card._abortFileTaskStream();
      finalizeCancellation(card);
      return true;
    }
    const terminalStatus = normalizeFileTaskTerminalStatus(
      card.dataset.taskTerminalStatus || '',
    );
    if (card.classList.contains('streaming') || isFileTaskWaitingStatus(terminalStatus)) {
      finalizeCancellation(card);
      return true;
    }
    return false;
  };

  return {
    clearTransientFeedback,
    markActivity,
    startHeartbeat,
    stopHeartbeat,
    showReconnectNotice,
    cancelRun,
    finalizeCancellation,
  };
}

export interface TaskEventStreamOptions {
  transformEvent?: (_event: Record<string, any>) => Record<string, any>;
  onEvent: (_event: Record<string, any>) => void;
  onBatch?: (_events: Record<string, any>[]) => void;
  stopOnTerminal?: boolean;
}

export async function consumeTaskEventStream(
  reader: ReadableStreamDefaultReader<Uint8Array>,
  options: TaskEventStreamOptions,
): Promise<{ terminalSeen: boolean }> {
  const decoder = new TextDecoder();
  let buffer = '';
  let terminalSeen = false;
  const applyEvents = (rawEvents: Record<string, any>[]): boolean => {
    const events = rawEvents.map((event) => (
      options.transformEvent ? options.transformEvent(event) : event
    ));
    events.forEach((event) => options.onEvent(event));
    if (events.length && options.onBatch) options.onBatch(events);
    const batchTerminal = events.some(isTaskStreamTerminalEvent);
    if (batchTerminal) terminalSeen = true;
    return batchTerminal;
  };

  while (true) {
    const chunk = await reader.read();
    if (chunk.done) break;
    buffer += decoder.decode(chunk.value, { stream: true });
    const parsed = parseSseEvents(buffer, false);
    buffer = parsed.remainder;
    if (applyEvents(parsed.events) && options.stopOnTerminal) {
      try { Promise.resolve(reader.cancel()).catch(() => {}); } catch { /* noop */ }
      break;
    }
  }
  const trailing = parseSseEvents(buffer, true);
  applyEvents(trailing.events);
  return { terminalSeen };
}

export function installTaskCancelHandler<TCard extends TaskStreamLifecycleCard>(
  card: TCard,
  abort: () => void,
  finalize: (_card: TCard) => void,
): () => void {
  let cancelled = false;
  const handler = (): void => {
    if (cancelled) return;
    cancelled = true;
    try { abort(); } finally { finalize(card); }
  };
  card._cancelHandler = handler;
  return () => {
    if (card._cancelHandler === handler) delete card._cancelHandler;
  };
}
