import {
  isFileTaskConfirmationStatus,
  normalizeFileTaskTerminalStatus,
  normalizedResumeStatus,
} from './file-task-status';
import {
  TASK_REPORT_STAGE_DEFS,
  taskReportCompactText,
  taskReportStageFromStep,
  taskReportStageStatusText,
} from './task-report-layout';
import {
  taskStageProjectionFromEvent,
  type TaskStageProjection,
} from './task-stage-state';
import { escHtml as esc } from '../shared/sanitize';

const escAttr = esc;

export interface TaskStageCardElement extends HTMLElement {
  _fatalErrorText?: string;
}

export interface TaskStageUiState {
  uiProgress: number;
}

export interface TaskStagePresentationRuntime<
  TCard extends TaskStageCardElement,
  TState extends TaskStageUiState,
> {
  isTaskCardElement: (_value: unknown) => boolean;
  ensureTaskUiState: (_card: TCard) => TState;
  attachRunCardBehavior: (_card: TCard) => TCard;
  taskStageStep: (_card: TCard, _stageId: string) => HTMLElement;
  markStepDone: (_step: HTMLElement) => void;
  markStepRunning: (_step: HTMLElement) => void;
  markStepFailed: (_step: HTMLElement) => void;
  setStatus: (_card: TCard, _text: string) => void;
  syncTaskPrimaryAction?: (_card: TCard) => void;
}

export function ensureTaskReportAfterProcess<
  TCard extends TaskStageCardElement,
>(card: TCard | null): TCard | null {
  if (!card) return card;
  const process = card.querySelector(
    '[data-role="process"]',
  ) as HTMLElement | null;
  let summary = card.querySelector(
    '[data-role="summary"]',
  ) as HTMLElement | null;
  if (!summary) {
    summary = document.createElement('div');
    summary.className = 'wa-task-summary';
    summary.dataset.role = 'summary';
  }
  if (process && process.nextElementSibling !== summary) {
    process.insertAdjacentElement('afterend', summary);
  } else if (!process && summary.parentElement !== card) {
    card.appendChild(summary);
  }
  return card;
}

export function restoreTaskStageStatus<
  TCard extends TaskStageCardElement,
>(
  card: TCard,
  setStatus: (_card: TCard, _text: string) => void,
): void {
  const status = String(
    card.dataset.taskStageStatus || 'running',
  ).trim() || 'running';
  const statusElement = card.querySelector(
    '[data-role="status"]',
  ) as HTMLElement | null;
  if (statusElement) statusElement.dataset.status = status;
  setStatus(card, status === 'waiting' ? '待确认' : '处理中');
}

export interface TaskStagePresentation<
  TCard extends TaskStageCardElement,
> {
  resetCanonicalTaskStageState: (_card: TCard) => void;
  setTaskCurrentStage: (
    _card: TCard,
    _stageId: string,
    _detail?: string,
    _detailMode?: 'replace' | 'fallback',
  ) => void;
  syncTaskStageOverview: (_card: TCard) => void;
  syncTaskLiveProgress: (_card: TCard) => void;
  makeRunCard: (_loadingEl?: TCard | null) => TCard;
  claimLiveTaskPresentation: (_card: TCard) => void;
  applyCanonicalTaskStageState: (
    _card: TCard,
    _event: Record<string, any>,
  ) => void;
}

function normalizeQuickActionMode(value: string): string {
  const normalized = String(value || '').trim().toLowerCase();
  if (normalized === 'simple') return 'answer';
  if (normalized === 'proposal') return 'hybrid';
  return normalized;
}

function taskStageDetailDatasetKey(stageId: string): string {
  const normalized = String(stageId || 'execute')
    .replace(/[^a-z0-9]+/gi, ' ')
    .trim();
  const suffix = normalized
    .split(/\s+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join('');
  return `taskStageDetail${suffix || 'Execute'}`;
}

function taskStageOverviewMarkup(): string {
  const stages = TASK_REPORT_STAGE_DEFS.map((def, index) => (
    '<div class="wa-task-stage-item pending" data-stage-id="'
      + escAttr(def.id)
      + '">'
      + '<span class="wa-task-stage-marker" aria-hidden="true">'
      + (index + 1)
      + '</span>'
      + '<span class="wa-task-stage-name">'
      + esc(def.title)
      + '</span>'
    + '</div>'
  )).join('');
  return '<div class="wa-task-stage-overview" data-role="stage-overview"'
    + ' aria-label="任务阶段">'
    + '<div class="wa-task-stage-track">' + stages + '</div>'
    + '<div class="wa-task-stage-current" role="status" aria-live="polite" aria-atomic="true">'
      + '<span data-role="stage-current-label">分析需求</span>'
      + '<strong data-role="stage-current-detail">正在建立任务上下文…</strong>'
      + `<span data-role="stage-progress-count">0/${TASK_REPORT_STAGE_DEFS.length}</span>`
    + '</div>'
    + '<div class="wa-task-primary-action" data-role="task-primary-action" hidden></div>'
  + '</div>';
}

function taskStageFromElement(step: Element): string {
  const stepId = String((step as HTMLElement).dataset.stepId || '').trim();
  const title = String(
    step.querySelector('.wa-task-step-title')?.textContent || '',
  ).trim();
  return taskReportStageFromStep({ id: stepId, title });
}

function taskStageStatusLabel(status: string): string {
  if (status === 'done') return '已完成';
  if (status === 'error') return '异常';
  if (status === 'waiting') return '待确认';
  if (status === 'cancelled') return '已取消';
  if (status === 'running') return '进行中';
  return '待处理';
}

function taskStageStatusText(projection: TaskStageProjection): string {
  if (projection.status === 'succeeded') {
    return projection.terminal ? '已完成' : '进行中';
  }
  if (projection.status === 'failed') {
    return projection.terminal ? '未完成' : '执行失败';
  }
  if (projection.status === 'warning') return '需关注';
  if (projection.status === 'waiting') return '待确认';
  if (projection.status === 'cancelled') return '已取消';
  if (projection.stageId === 'route') return '分析中';
  if (projection.stageId === 'plan') return '规划中';
  if (projection.stageId === 'check') return '核验中';
  if (projection.stageId === 'deliver') return '整理结果';
  return '处理中';
}

export function createTaskStagePresentation<
  TCard extends TaskStageCardElement,
  TState extends TaskStageUiState,
>(
  runtime: TaskStagePresentationRuntime<TCard, TState>,
): TaskStagePresentation<TCard> {
  function isTaskCard(value: unknown): value is TCard {
    return runtime.isTaskCardElement(value);
  }

  function taskStageDetail(card: TCard, stageId: string): string {
    return String(
      (card.dataset as any)[taskStageDetailDatasetKey(stageId)] || '',
    ).trim();
  }

  function setTaskCurrentStage(
    card: TCard,
    stageId: string,
    detail = '',
    detailMode: 'replace' | 'fallback' = 'replace',
  ): void {
    if (!isTaskCard(card)) return;
    const normalized = taskReportStageFromStep({ id: stageId }, 'execute');
    const current = String(card.dataset.taskCurrentStage || '').trim();
    const currentIndex = TASK_REPORT_STAGE_DEFS.findIndex(
      (item) => item.id === current,
    );
    const nextIndex = TASK_REPORT_STAGE_DEFS.findIndex(
      (item) => item.id === normalized,
    );
    if (currentIndex < 0 || nextIndex >= currentIndex) {
      card.dataset.taskCurrentStage = normalized;
    }
    const compact = taskReportCompactText(detail, 120);
    if (compact) {
      const detailKey = taskStageDetailDatasetKey(normalized);
      const existing = String((card.dataset as any)[detailKey] || '').trim();
      if (detailMode === 'replace' || !existing) {
        (card.dataset as any)[detailKey] = compact;
      }
    }
  }

  function ensureTaskStageOverview(card: TCard): HTMLElement | null {
    if (!isTaskCard(card)) return null;
    let overview = card.querySelector(
      '[data-role="stage-overview"]',
    ) as HTMLElement | null;
    if (overview) return overview;
    const header = card.querySelector('.wa-task-header');
    const process = card.querySelector('[data-role="process"]');
    const wrapper = document.createElement('div');
    wrapper.innerHTML = taskStageOverviewMarkup();
    overview = wrapper.firstElementChild as HTMLElement | null;
    if (!overview) return null;
    if (header && header.parentElement === card) {
      header.insertAdjacentElement('afterend', overview);
    } else if (process && process.parentElement === card) {
      process.insertAdjacentElement('beforebegin', overview);
    } else {
      card.insertAdjacentElement('afterbegin', overview);
    }
    return overview;
  }

  function latestTaskStageRowText(card: TCard, stageId: string): string {
    const rows = Array.from(
      card.querySelectorAll('[data-role="steps"] .wa-task-step'),
    )
      .filter((step) => taskStageFromElement(step) === stageId)
      .flatMap((step) => Array.from(step.querySelectorAll('.wa-task-row')));
    for (let index = rows.length - 1; index >= 0; index -= 1) {
      const row = rows[index] as HTMLElement;
      const role = String(row.dataset.role || '').trim();
      if (
        role === 'task-heartbeat'
        || row.classList.contains('wa-task-performance')
      ) {
        continue;
      }
      const chip = String(
        row.querySelector('.wa-task-chip')?.textContent || '',
      ).replace(/\s+/g, ' ').trim();
      const raw = String(row.textContent || '').replace(/\s+/g, ' ').trim();
      if (!raw) continue;
      const rest = chip && raw.startsWith(chip)
        ? raw.slice(chip.length).trim()
        : raw;
      const text = chip && rest ? `${chip}：${rest}` : raw;
      return taskReportCompactText(text, 120);
    }
    return '';
  }

  function syncTaskStageOverview(card: TCard): void {
    const overview = ensureTaskStageOverview(card);
    if (!overview) return;
    const quickActionMode = normalizeQuickActionMode(
      String(card.dataset.taskQuickActionMode || '').trim(),
    );
    overview.hidden = !!quickActionMode;
    if (quickActionMode) return;

    const terminalStatus = normalizeFileTaskTerminalStatus(
      card.dataset.taskTerminalStatus || '',
    );
    const terminalUi = normalizedResumeStatus(terminalStatus);
    const confirmationPending = isFileTaskConfirmationStatus(terminalStatus);
    const currentStage = String(
      card.dataset.taskCurrentStage || 'route',
    ).trim();
    let currentIndex = TASK_REPORT_STAGE_DEFS.findIndex(
      (item) => item.id === currentStage,
    );
    if (currentIndex < 0) currentIndex = 0;
    if (
      terminalUi === 'completed'
      || terminalUi === 'failed'
      || confirmationPending
      || terminalUi === 'cancelled'
    ) {
      currentIndex = TASK_REPORT_STAGE_DEFS.length - 1;
    }

    const stageNodes = Array.from(
      card.querySelectorAll('[data-role="steps"] .wa-task-step'),
    );
    const statuses = TASK_REPORT_STAGE_DEFS.map((def, index) => {
      if (terminalUi === 'completed') return 'done';
      if (index < currentIndex) return 'done';
      if (index > currentIndex) return 'pending';
      if (terminalUi === 'failed') return 'error';
      if (terminalUi === 'cancelled') return 'cancelled';
      if (confirmationPending) return 'waiting';
      const matching = stageNodes.filter(
        (step) => taskStageFromElement(step) === def.id,
      );
      if (matching.some((step) => step.classList.contains('failed'))) {
        return 'error';
      }
      if (
        matching.length
        && matching.every((step) => step.classList.contains('done'))
      ) {
        return 'done';
      }
      return 'running';
    });

    const activeIndex = terminalUi === 'completed'
      ? TASK_REPORT_STAGE_DEFS.length - 1
      : Math.max(
        0,
        statuses.findIndex((status) => (
          ['running', 'error', 'waiting', 'cancelled'].includes(status)
        )),
      );
    const activeDef = TASK_REPORT_STAGE_DEFS[activeIndex]
      || TASK_REPORT_STAGE_DEFS[0];
    const activeStatus = statuses[activeIndex] || 'running';
    const detail = taskStageDetail(card, activeDef.id)
      || latestTaskStageRowText(card, activeDef.id)
      || taskReportStageStatusText(
        activeDef.id,
        taskStageStatusLabel(activeStatus),
      );
    const doneCount = statuses.filter((status) => status === 'done').length;

    overview.querySelectorAll<HTMLElement>('[data-stage-id]')
      .forEach((item, index) => {
        const status = statuses[index] || 'pending';
        const def = TASK_REPORT_STAGE_DEFS[index];
        item.className = `wa-task-stage-item ${status}`;
        item.setAttribute(
          'aria-label',
          `${def.title}：${taskStageStatusLabel(status)}`,
        );
        if (index === activeIndex && status !== 'done') {
          item.setAttribute('aria-current', 'step');
        } else {
          item.removeAttribute('aria-current');
        }
        const marker = item.querySelector('[aria-hidden="true"]');
        if (marker) {
          marker.textContent = status === 'done'
            ? '✓'
            : (status === 'error'
              ? '!'
              : (status === 'cancelled' ? '×' : String(index + 1)));
        }
      });

    const labelEl = overview.querySelector(
      '[data-role="stage-current-label"]',
    );
    const detailEl = overview.querySelector(
      '[data-role="stage-current-detail"]',
    );
    const countEl = overview.querySelector(
      '[data-role="stage-progress-count"]',
    );
    if (labelEl) {
      labelEl.textContent = activeStatus === 'done' && terminalUi === 'completed'
        ? '流程完成'
        : activeDef.title;
    }
    if (detailEl) detailEl.textContent = detail;
    if (countEl) {
      countEl.textContent = `${doneCount}/${TASK_REPORT_STAGE_DEFS.length}`;
    }
  }

  function ensureTaskLiveProgressHost(): HTMLElement | null {
    let host = document.getElementById('wa-task-live-progress');
    if (host) return host;
    const msgs = document.getElementById('wa-ai-messages');
    if (!msgs || !msgs.parentNode) return null;
    host = document.createElement('div');
    host.id = 'wa-task-live-progress';
    host.className = 'wa-task-live-progress';
    host.hidden = true;
    host.innerHTML = '<div class="wa-task-live-top">'
      + '<span class="wa-task-live-title">文件任务</span>'
      + '<span class="wa-task-live-status" data-role="live-status">处理中</span>'
      + '</div><div class="wa-task-live-meta">'
      + '<span data-role="live-phase">处理中</span>'
      + '<span data-role="live-plan" style="display:none"></span>'
      + '<span data-role="live-progress-value">初始化</span>'
      + '</div><div class="wa-task-live-track">'
      + '<i data-role="live-progress-fill"></i></div>';
    msgs.parentNode.insertBefore(host, msgs.nextSibling);
    return host;
  }

  function taskCardIsVisibleInViewport(card: TCard): boolean {
    if (
      !card
      || !card.isConnected
      || typeof card.getBoundingClientRect !== 'function'
    ) {
      return false;
    }
    const rect = card.getBoundingClientRect();
    return rect.width > 0
      && rect.height > 0
      && rect.bottom > 0
      && rect.right > 0
      && rect.top < window.innerHeight
      && rect.left < window.innerWidth;
  }

  function syncTaskLiveProgress(card: TCard): void {
    if (!isTaskCard(card)) return;
    syncTaskStageOverview(card);
    runtime.syncTaskPrimaryAction?.(card);
    const host = ensureTaskLiveProgressHost();
    if (!host) return;
    if (taskCardIsVisibleInViewport(card)) {
      host.hidden = true;
      host.dataset.inlineOwner = 'true';
      return;
    }
    const state = runtime.ensureTaskUiState(card);
    const statusEl = card.querySelector('[data-role="status"]');
    const overview = card.querySelector('[data-role="stage-overview"]');
    const phaseEl = overview?.querySelector(
      '[data-role="stage-current-label"]',
    );
    const detailEl = overview?.querySelector(
      '[data-role="stage-current-detail"]',
    );
    const countEl = overview?.querySelector(
      '[data-role="stage-progress-count"]',
    );
    const statusRaw = String(
      card.dataset.taskStageStatus
      || (
        statusEl
        && (statusEl as HTMLElement).dataset
          ? (statusEl as HTMLElement).dataset.status || ''
          : ''
      ),
    ).trim().toLowerCase() || 'running';
    const normalizedStatus = normalizeFileTaskTerminalStatus(statusRaw);
    const terminal = ['completed', 'failed', 'cancelled'].includes(
      normalizedResumeStatus(normalizedStatus),
    )
      || isFileTaskConfirmationStatus(normalizedStatus)
      || String(card.dataset.taskTerminalStatus || '').trim() !== '';
    let percent = Number(state.uiProgress || 0);
    const valueText = countEl
      ? String(countEl.textContent || '').trim()
      : '';
    if (!percent && valueText.includes('/')) {
      const [done, total] = valueText.split('/').map((part) => Number(part));
      if (Number.isFinite(done) && Number.isFinite(total) && total > 0) {
        percent = Math.round((done / total) * 100);
      }
    }
    if (terminal) {
      percent = Math.max(percent, statusRaw === 'failed' ? percent : 100);
    }
    percent = Math.max(0, Math.min(100, Math.round(percent)));
    host.hidden = false;
    delete host.dataset.inlineOwner;
    host.dataset.status = statusRaw || 'running';
    host.dataset.basis = 'stage';
    const liveStatus = host.querySelector('[data-role="live-status"]');
    const livePhase = host.querySelector('[data-role="live-phase"]');
    const livePlan = host.querySelector('[data-role="live-plan"]');
    const liveValue = host.querySelector('[data-role="live-progress-value"]');
    const liveFill = host.querySelector(
      '[data-role="live-progress-fill"]',
    ) as HTMLElement | null;
    if (liveStatus) {
      liveStatus.textContent = statusEl
        ? String(statusEl.textContent || '').trim() || '处理中'
        : '处理中';
    }
    if (livePhase) {
      livePhase.textContent = phaseEl
        ? String(phaseEl.textContent || '').trim() || '处理中'
        : '处理中';
    }
    if (livePlan) {
      livePlan.textContent = valueText ? `阶段 ${valueText}` : '';
      (livePlan as HTMLElement).style.display = valueText ? '' : 'none';
    }
    if (liveValue) {
      liveValue.textContent = detailEl
        ? String(detailEl.textContent || '').trim()
        : `${percent}%`;
    }
    if (liveFill) liveFill.style.width = percent + '%';
  }

  function makeRunCard(loadingEl?: TCard | null): TCard {
    const card = isTaskCard(loadingEl)
      ? loadingEl
      : document.createElement('div') as unknown as TCard;
    card.className = 'wa-msg ai wa-task-run is-compact';
    card._fatalErrorText = '';
    card.innerHTML = '<div class="wa-task-header">'
      + '<div class="wa-task-title-wrap">'
      + '<div class="wa-task-title">文件任务</div></div>'
      + '<div class="wa-task-status" data-role="status" data-status="running">处理中</div>'
      + '</div>'
      + '<details class="wa-task-process" data-role="process"><summary>'
      + '<span data-role="process-title">查看执行详情</span>'
      + '<span data-role="process-state">进行中</span></summary>'
      + '<div class="wa-task-plan" data-role="plan"></div>'
      + '<div class="wa-task-steps" data-role="steps"></div></details>'
      + '<div class="wa-task-summary" data-role="summary"></div>';
    ensureTaskStageOverview(card);
    ensureTaskReportAfterProcess(card);
    const attached = runtime.attachRunCardBehavior(card);
    syncTaskLiveProgress(attached);
    return attached;
  }

  function resetCanonicalTaskStageState(card: TCard): void {
    const state = runtime.ensureTaskUiState(card);
    state.uiProgress = 0;
    delete card.dataset.taskCurrentStage;
    delete card.dataset.taskStageProgress;
    delete card.dataset.taskStageStatus;
    TASK_REPORT_STAGE_DEFS.forEach((stage) => {
      delete (card.dataset as any)[taskStageDetailDatasetKey(stage.id)];
    });
  }

  function claimLiveTaskPresentation(card: TCard): void {
    if (!isTaskCard(card)) return;
    const workbench = document.getElementById(
      'wa-task-workbench',
    ) as HTMLElement | null;
    if (workbench) workbench.hidden = true;
  }

  function applyCanonicalTaskStageState(
    card: TCard,
    event: Record<string, any>,
  ): void {
    const projection = taskStageProjectionFromEvent(event);
    if (!isTaskCard(card)) return;
    if (!projection) {
      syncTaskLiveProgress(card);
      return;
    }
    const state = runtime.ensureTaskUiState(card);
    state.uiProgress = Math.max(
      state.uiProgress || 0,
      projection.progress || 0,
    );
    card.dataset.taskStageProgress = String(state.uiProgress);
    card.dataset.taskStageStatus = projection.status;
    setTaskCurrentStage(
      card,
      projection.stageId,
      projection.title,
      projection.detailMode || 'replace',
    );
    if (projection.stageId !== 'deliver') {
      const step = runtime.taskStageStep(card, projection.stageId);
      if (projection.status === 'succeeded') runtime.markStepDone(step);
      else if (projection.status === 'failed') runtime.markStepFailed(step);
      else runtime.markStepRunning(step);
    }
    const statusEl = card.querySelector(
      '[data-role="status"]',
    ) as HTMLElement | null;
    if (statusEl) statusEl.dataset.status = projection.status;
    runtime.setStatus(card, taskStageStatusText(projection));
    syncTaskLiveProgress(card);
  }

  return {
    resetCanonicalTaskStageState,
    setTaskCurrentStage,
    syncTaskStageOverview,
    syncTaskLiveProgress,
    makeRunCard,
    claimLiveTaskPresentation,
    applyCanonicalTaskStageState,
  };
}
