import {
  isFileTaskConfirmationStatus,
  isFileTaskWaitingStatus,
  normalizeFileTaskTerminalStatus,
  normalizedResumeStatus,
} from './file-task-status';
import { escHtml as esc } from '../shared/sanitize';

export interface TaskRunRecoveryCard extends HTMLElement {
  _fatalErrorText?: string;
  _terminalSnapshotHandler?: (_card: TaskRunRecoveryCard) => void;
}

export interface ResumePersistedTaskOptions<TCard extends TaskRunRecoveryCard> {
  taskId?: string;
  task_id?: string;
  runId?: string;
  run_id?: string;
  msgs?: HTMLElement | null;
  loadingEl?: HTMLElement | null;
  taskCardSnapshot?: Record<string, any>;
  initialStatus?: string;
  status?: string;
  onTaskCardSnapshot?: (_card: TCard) => void;
  replay?: boolean;
  taskPayload?: Record<string, any>;
  actionLabel?: string;
}

export interface TaskRunRecoveryRuntime<TCard extends TaskRunRecoveryCard> {
  isCard: (_value: unknown) => _value is TCard;
  makeRunCard: (_loadingEl: TCard | null) => TCard;
  ensureReport: (_card: TCard) => void;
  attachBehavior: (_card: TCard) => TCard;
  startHeartbeat: (_card: TCard) => void;
  syncLiveProgress: (_card: TCard) => void;
  appendIfDetached: (_card: TCard) => void;
  claimLivePresentation: (_card: TCard) => void;
  dispatchEvent: (_card: TCard, _event: Record<string, any>) => void;
  streamTaskSse: (
    _card: TCard,
    _url: string,
    _body: Record<string, any>,
    _method: string,
  ) => Promise<TCard>;
}

export interface TaskRunRecoveryController<TCard extends TaskRunRecoveryCard> {
  initializeRecoveredRunCard: (
    _card: TCard,
    _options: Record<string, any>,
  ) => TCard | null;
  markTaskRunCardAsHistory: (
    _card: TCard,
    _options?: Record<string, any>,
  ) => TCard;
  restoreTaskRunCard: (
    _cardOrSnapshot: TCard | Record<string, any>,
    _initialSummary?: string | Record<string, any>,
    _initialStatus?: string,
    _recoveryPayload?: Record<string, any>,
  ) => TCard | null;
  resumePersistedFileTask: (
    _optionsOrCard: ResumePersistedTaskOptions<TCard> | TCard,
    _taskContract?: Record<string, any>,
  ) => Promise<TCard>;
}

export function notifyTaskCardSnapshot<TCard extends TaskRunRecoveryCard>(
  card: TCard,
  handler?: ((_card: TCard) => void) | null,
): boolean {
  if (typeof handler !== 'function') return false;
  try { handler(card); } catch { /* snapshot persistence is best effort */ }
  return true;
}

export function installTerminalSnapshotHandler<TCard extends TaskRunRecoveryCard>(
  card: TCard,
  handler?: ((_card: TCard) => void) | null,
): () => void {
  const installed = typeof handler === 'function'
    ? handler as unknown as (_card: TaskRunRecoveryCard) => void
    : undefined;
  card._terminalSnapshotHandler = installed;
  return () => {
    if (card._terminalSnapshotHandler === installed) {
      delete card._terminalSnapshotHandler;
    }
  };
}

export function createTaskRunRecovery<TCard extends TaskRunRecoveryCard>(
  runtime: TaskRunRecoveryRuntime<TCard>,
): TaskRunRecoveryController<TCard> {
  const initializeRecoveredRunCard = (
    card: TCard,
    options: Record<string, any>,
  ): TCard | null => {
    const settings = options && typeof options === 'object' ? options : {};
    if (!card) return null;
    card.classList.add('streaming');
    const waiting = isFileTaskWaitingStatus(settings.initialStatus);
    const confirmation = isFileTaskConfirmationStatus(settings.initialStatus);
    if (settings.taskId) card.dataset.taskId = String(settings.taskId || '').trim();
    if (settings.runId) card.dataset.taskRunId = String(settings.runId || '').trim();
    if (confirmation) card.dataset.taskTerminalStatus = 'awaiting_confirmation';
    else if (waiting) {
      card.dataset.taskTerminalStatus = normalizeFileTaskTerminalStatus(
        settings.initialStatus,
      );
    }
    const statusEl = card.querySelector('[data-role="status"]');
    if (statusEl) {
      statusEl.textContent = confirmation ? '待确认' : (waiting ? '待处理' : '恢复中');
    }
    const summaryEl = card.querySelector('[data-role="summary"]');
    if (summaryEl && !String(summaryEl.textContent || '').trim()) {
      const copy = confirmation
        ? '已恢复等待确认的后台任务，正在同步最新进度…'
        : (waiting
          ? '已恢复待处理的后台任务，正在同步最新进度…'
          : '已恢复后台任务，正在同步最新进度…');
      summaryEl.innerHTML = '<div class="wa-task-plan-summary wa-task-outcome">'
        + esc(copy) + '</div>';
    }
    return card;
  };

  const markTaskRunCardAsHistory = (
    card: TCard,
    options?: Record<string, any>,
  ): TCard => {
    const settings = options && typeof options === 'object' ? options : {};
    runtime.ensureReport(card);
    const label = String(settings.history_label || '历史任务记录').trim()
      || '历史任务记录';
    const note = Object.prototype.hasOwnProperty.call(settings, 'history_note')
      ? String(settings.history_note || '').trim()
      : '';
    const historyStatus = normalizedResumeStatus(
      settings.initialStatus || card.dataset.taskTerminalStatus || '',
    );
    const statusText = historyStatus === 'failed'
      ? '执行失败'
      : historyStatus === 'cancelled'
        ? '已取消'
        : historyStatus === 'completed'
          ? '已完成'
          : '历史记录';
    card.classList.remove('streaming', 'pending');
    card.classList.add('is-history-snapshot');
    card.dataset.historySnapshot = 'true';
    card.dataset.taskCurrentRun = 'false';
    card.dataset.historyStatus = historyStatus || 'history';
    card.setAttribute('aria-label', label);
    card.querySelector('[data-role="cancel"]')?.remove();
    card.querySelectorAll('.wa-task-actions').forEach((node) => node.remove());
    const statusEl = card.querySelector('[data-role="status"]') as HTMLElement | null;
    if (statusEl) {
      statusEl.textContent = statusText;
      statusEl.dataset.status = historyStatus || 'history';
    }
    const process = card.querySelector('[data-role="process"]') as HTMLDetailsElement | null;
    if (process) {
      process.removeAttribute('open');
      process.dataset.historyCollapsed = 'true';
      const state = process.querySelector('[data-role="process-state"]');
      if (state) state.textContent = '可展开';
    }
    const titleWrap = card.querySelector('.wa-task-title-wrap');
    if (titleWrap && !titleWrap.querySelector('[data-role="history-badge"]')) {
      const badge = document.createElement('span');
      badge.className = 'wa-task-history-badge';
      badge.dataset.role = 'history-badge';
      badge.dataset.status = historyStatus || 'history';
      badge.textContent = label;
      titleWrap.appendChild(badge);
    }
    if (note) {
      const summary = card.querySelector('[data-role="summary"]');
      if (summary && !summary.querySelector('[data-role="history-note"]')) {
        const noteEl = document.createElement('div');
        noteEl.className = 'wa-task-history-note';
        noteEl.dataset.role = 'history-note';
        noteEl.textContent = note;
        summary.insertBefore(noteEl, summary.firstChild);
        (summary as HTMLElement).hidden = false;
      }
    }
    return card;
  };

  const restoreTaskRunCard = (
    cardOrSnapshot: TCard | Record<string, any>,
    initialSummary?: string | Record<string, any>,
    initialStatus?: string,
    _recoveryPayload?: Record<string, any>,
  ): TCard | null => {
    if (
      cardOrSnapshot
      && !runtime.isCard(cardOrSnapshot)
      && typeof cardOrSnapshot === 'object'
      && cardOrSnapshot.html
    ) {
      const wrapper = document.createElement('div');
      wrapper.innerHTML = String(cardOrSnapshot.html || '').trim();
      const card = wrapper.firstElementChild as TCard | null;
      if (!card || !runtime.isCard(card)) return null;
      card._fatalErrorText = String(cardOrSnapshot.fatal_error_text || '');
      runtime.ensureReport(card);
      const restored = runtime.attachBehavior(card);
      const options = initialSummary && typeof initialSummary === 'object'
        ? initialSummary as Record<string, any>
        : {};
      return options.history ? markTaskRunCardAsHistory(restored, options) : restored;
    }
    const card = cardOrSnapshot as TCard;
    if (!card || !runtime.isCard(card)) return null;
    runtime.ensureReport(card);
    const settings = {
      taskId: String(card.dataset.taskId || '').trim(),
      runId: String(card.dataset.taskRunId || '').trim(),
      initialStatus: normalizeFileTaskTerminalStatus(
        initialStatus || card.dataset.taskTerminalStatus || '',
      ),
    };
    if (isFileTaskWaitingStatus(settings.initialStatus)) {
      initializeRecoveredRunCard(card, settings);
    }
    const summaryText = typeof initialSummary === 'string' ? initialSummary : '';
    if (summaryText && !String(card.dataset.taskSummary || '').trim()) {
      card.dataset.taskSummary = summaryText;
    }
    const stepsHost = card.querySelector('[data-role="steps"]');
    if (stepsHost && !stepsHost.children.length) {
      stepsHost.innerHTML = '<div class="wa-task-step pending" data-step-id="run">'
        + '<details class="wa-task-step-detail" open><summary class="wa-task-step-head">'
        + '<span class="wa-task-step-dot"></span><span class="wa-task-step-title">'
        + '任务状态</span></summary><div class="wa-task-step-body"></div></details></div>';
    }
    card.classList.remove('streaming', 'pending');
    if (isFileTaskWaitingStatus(settings.initialStatus)) card.classList.add('pending');
    else if (settings.initialStatus === 'running' || !settings.initialStatus) {
      card.classList.add('streaming');
      runtime.startHeartbeat(card);
    } else card.classList.add('done');
    runtime.syncLiveProgress(card);
    return card;
  };

  const resumePersistedFileTask = (
    optionsOrCard: ResumePersistedTaskOptions<TCard> | TCard,
    taskContract?: Record<string, any>,
  ): Promise<TCard> => {
    const options: ResumePersistedTaskOptions<TCard> = runtime.isCard(optionsOrCard)
      ? { loadingEl: optionsOrCard, taskPayload: taskContract || {} }
      : (optionsOrCard && typeof optionsOrCard === 'object'
        ? optionsOrCard as ResumePersistedTaskOptions<TCard>
        : {});
    const contract = (
      options.taskPayload && typeof options.taskPayload === 'object'
        ? options.taskPayload
        : taskContract
    ) || {};
    const taskId = String(
      options.taskId || options.task_id || contract.task_id || contract.taskId || '',
    ).trim();
    if (!taskId) return Promise.reject(new Error('缺少 task_id，无法恢复任务流'));

    const card = runtime.makeRunCard(
      runtime.isCard(options.loadingEl) ? options.loadingEl : null,
    );
    card.dataset.taskId = taskId;
    const runId = String(
      options.runId || options.run_id || contract.run_id || contract.runId || '',
    ).trim();
    if (runId) card.dataset.taskRunId = runId;
    const initialStatus = options.initialStatus || options.status
      || contract.initialStatus || contract.status || 'running';
    restoreTaskRunCard(card, contract.summary || '', initialStatus, {});
    const terminalStatus = normalizedResumeStatus(initialStatus);
    if (['completed', 'failed', 'cancelled'].includes(terminalStatus)) {
      runtime.appendIfDetached(card);
      runtime.claimLivePresentation(card);
      runtime.dispatchEvent(card, {
        type: terminalStatus === 'cancelled' ? 'run.cancelled' : 'run.finished',
        payload: {
          summary: contract.summary || '',
          terminal_status: terminalStatus === 'failed' ? 'error' : terminalStatus,
          completed_task: terminalStatus === 'completed',
        },
      });
      notifyTaskCardSnapshot(card, options.onTaskCardSnapshot);
      return Promise.resolve(card);
    }

    const replay = options.replay === false ? 'false' : 'true';
    const finalUrl = `/api/tasks/${encodeURIComponent(taskId)}/stream?replay=${replay}`;
    return runtime.streamTaskSse(card, finalUrl, {}, 'GET').then((streamingCard) => {
      notifyTaskCardSnapshot(streamingCard, options.onTaskCardSnapshot);
      return streamingCard;
    });
  };

  return {
    initializeRecoveredRunCard,
    markTaskRunCardAsHistory,
    restoreTaskRunCard,
    resumePersistedFileTask,
  };
}
