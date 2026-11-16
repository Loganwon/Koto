import {
  TASK_REPORT_LABELS,
  TASK_REPORT_STAGE_DEFS,
  taskReportCompactText as compactText,
  taskReportStageActionText as stageActionText,
  taskReportStageDef as stageDef,
  taskReportStageStatusText,
  taskReportStatusClass as statusClass,
  taskReportUniqueTexts as uniqueTexts,
} from './task-report-layout';
import {
  isFileTaskFailureStatus,
  normalizeFileTaskTerminalStatus,
} from './file-task-status';
import { getFeatureRegistry, registerFeatures } from '../shared/feature-registry';
import {
  TOOL_LABELS,
  attr,
  basename,
  esc,
  metadataStepsForTask,
  normalizeTask,
  runIdForTask,
  statusLabel,
  stepLabel,
  stepText,
  stepTone,
  taskCompletionSummary,
  taskFiles,
  taskMetaLine,
  taskModelLabel,
  taskSummary,
  taskTitle,
  taskTypeMetaHtml,
  terminalStatus,
  userFacingTaskText,
  workbenchStageFromStep,
  type WorkbenchFile,
  type WorkbenchStep,
  type WorkbenchTask,
} from './task-workbench-projection';

const workspaceApi = getFeatureRegistry();

interface WorkbenchState {
  host: HTMLElement;
  activeTaskId: string;
  activeTask: WorkbenchTask | null;
  loading: boolean;
  requestVersion: number;
}

function taskCardForTask(taskId: any, runId: any): HTMLElement | null {
  const id = String(taskId || '').trim();
  const run = String(runId || '').trim();
  if (!id && !run) return null;
  const cards = Array.from(document.querySelectorAll('.wa-task-run')) as HTMLElement[];
  return cards.find((card) => {
    const dataset = card && card.dataset ? card.dataset : {};
    return (id && String(dataset['taskId'] || '').trim() === id)
      || (run && String(dataset['taskRunId'] || '').trim() === run);
  }) || null;
}

function openTaskFile(path: any): void {
  const value = String(path || '').trim();
  if (!value) return;
  if (typeof workspaceApi.openRecentFile === 'function') {
    void workspaceApi.openRecentFile(value);
    return;
  }
  if (/^[a-z]:[\\/]/i.test(value) && typeof workspaceApi.openBrowserFile === 'function') {
    void workspaceApi.openBrowserFile(value, true);
    return;
  }
  if (typeof workspaceApi.openWorkspaceFile === 'function') {
    void workspaceApi.openWorkspaceFile(value.replace(/^workspace[\\/]/i, ''));
  }
}

function aiMessagesHost(): HTMLElement | null {
  return document.getElementById('wa-ai-messages') as HTMLElement | null;
}

function ensureWorkbench(): HTMLElement | null {
  let host = document.getElementById('wa-task-workbench');
  if (host) {
    const messages = aiMessagesHost();
    if (messages && host.parentElement !== messages) {
      messages.appendChild(host);
    }
    host.classList.add('wa-inline-task-workbench');
    return host;
  }
  const fallbackAnchor = aiMessagesHost();
  if (!fallbackAnchor) return null;
  host = document.createElement('section');
  host.id = 'wa-task-workbench';
  host.className = 'wa-task-workbench wa-inline-task-workbench';
  host.hidden = true;
  host.innerHTML = [
    '<div class="wa-task-workbench-header">',
    '  <div class="wa-task-workbench-title-group">',
    '    <span class="wa-task-workbench-kicker">流程</span>',
    '    <strong>任务流程</strong>',
    '  </div>',
    '  <div class="wa-task-workbench-actions">',
    '    <button type="button" data-task-workbench-action="refresh" title="刷新任务">刷新</button>',
    '    <button type="button" data-task-workbench-action="close" title="关闭任务流程">关闭</button>',
    '  </div>',
    '</div>',
    '<div class="wa-task-workbench-body">',
    '  <div id="wa-task-workbench-detail" class="wa-task-workbench-detail"></div>',
    '</div>',
  ].join('');
  fallbackAnchor.appendChild(host);
  return host;
}

function emptyTaskFlowHtml(): string {
  const stageLabels = TASK_REPORT_STAGE_DEFS
    .map((def) => '    <span>' + esc(def.title) + '</span>')
    .join('');
  return [
    '<div class="wa-task-workbench-empty wa-task-workbench-empty-flow">',
    '  <strong>等待文件任务</strong>',
    '  <span>当请求需要读取、修改或生成文件时，这里会直接展开需求分析、执行计划、进度和结果检查。</span>',
    '  <div class="wa-task-workbench-empty-steps">',
    stageLabels,
    '  </div>',
    '</div>',
  ].join('');
}

function renderEmptyDetail(detail: HTMLElement | null, message?: string): void {
  if (!detail) return;
  if (message) {
    detail.innerHTML = `<div class="wa-task-workbench-empty">${esc(message)}</div>`;
    return;
  }
  detail.innerHTML = emptyTaskFlowHtml();
}

function liveCardCompleted(card: any): boolean {
  const dataset = card && card.dataset ? card.dataset : {};
  const terminal = normalizeFileTaskTerminalStatus(dataset['taskTerminalStatus'] || '');
  if (isFileTaskFailureStatus(terminal)) return false;
  return terminal === 'completed' || String(dataset['taskCompleted'] || '').trim().toLowerCase() === 'true';
}

function liveStepTone(step: any, card: any): string {
  if (!step || !step.classList) return '';
  if (step.classList.contains('failed')) return 'error';
  if (liveCardCompleted(card)) return 'answer';
  if (step.classList.contains('running')) return 'action';
  if (step.classList.contains('done')) return 'answer';
  return '';
}

function liveStepStatus(step: any, card: any): string {
  if (!step || !step.classList) return '待处理';
  if (step.classList.contains('failed')) return '异常';
  if (liveCardCompleted(card)) return '已完成';
  if (step.classList.contains('running')) return '进行中';
  if (step.classList.contains('done')) return '已完成';
  return '待处理';
}

function liveStepText(value: any, limit?: number): string {
  const text = String(value || '')
    .replace(/完成已\s*完成/g, '已完成')
    .replace(/结果以下/g, '结果：以下')
    .replace(/(监管|主线锁定|完成|结果|通过|待处理|流程|任务：|操作：|输出：)/g, ' $1')
    .replace(/已\s+完成/g, '已完成')
    .replace(/\s+/g, ' ')
    .trim();
  return compactText(text, limit || 170);
}

function liveRowText(row: any): string {
  if (!row) return '';
  if (row.dataset && row.dataset.role === 'task-heartbeat') return '';
  const raw = String(row.innerText || row.textContent || '').trim();
  const compact = raw.replace(/\s+/g, '');
  if (!compact) return '';
  if (/^(运行中|等待中).*(任务仍在执行|没有收到新进度|已等待)/.test(compact)) return '';
  if (compact.includes('主线锁定') || compact.includes('任务主线已锁定') || /^监管/.test(compact)) {
    return '';
  }
  const chip = String(row.querySelector('.wa-task-chip')?.textContent || '').trim();
  const detail = String(
    row.querySelector('.wa-task-result-text')?.textContent
    || row.querySelector('.wa-task-detail')?.textContent
    || ''
  ).trim();
  const chipLower = chip.toLowerCase();
  if (!detail && chipLower.includes('whitebox')) return '';
  const doneTool = chip.match(/^完成\s+(.+)$/);
  if (doneTool) {
    const toolName = doneTool[1].trim();
    const label = TOOL_LABELS[toolName] || toolName.replace(/[_-]+/g, ' ');
    return detail ? `${label}：${detail}` : `${label}已完成`;
  }
  if (detail) return chip ? `${chip}：${detail}` : detail;
  if (chip) return `${chip}：${raw.replace(chip, '').trim() || '已完成'}`;
  return raw;
}

function liveStepsForTask(task: any): WorkbenchStep[] {
  const card = taskCardForTask(task && task.task_id, runIdForTask(task));
  if (!card) return [];
  const completed = liveCardCompleted(card);
  return Array.from(card.querySelectorAll('.wa-task-step')).map((step) => {
    const stepId = String((step as HTMLElement).dataset && (step as HTMLElement).dataset.stepId || '').trim();
    let title = String((step.querySelector('.wa-task-step-title') as HTMLElement | null)?.textContent || '').trim() || '步骤';
    if (completed && (stepId === 'run' || title === '任务状态')) return null;
    const stage = workbenchStageFromStep({ id: stepId, title }, stepId === 'run' ? 'execute' : '');
    const rows = Array.from(step.querySelectorAll('.wa-task-row'))
      .map((row) => userFacingTaskText(liveStepText(liveRowText(row), 220), stage))
      .filter(Boolean);
    if (title === '任务状态' && rows.length === 1 && rows[0].includes('：')) {
      title = rows[0].split('：')[0] || title;
    }
    const status = liveStepStatus(step, card);
    const text = uniqueTexts(rows, 2).join('；') || '';
    return {
      id: stepId,
      stage,
      title,
      status,
      rows,
      tone: liveStepTone(step, card),
      label: `${title} · ${status}`,
      text,
    };
  }).filter((step) => !!step && !!step.text) as WorkbenchStep[];
}

function flowStageIndex(stageId: string): number {
  return Math.max(0, TASK_REPORT_STAGE_DEFS.findIndex((item) => item.id === stageId));
}

function stageFallbackText(stageId: string, status: string): string {
  return taskReportStageStatusText(stageId, status);
}

function inferredStageStatus(def: { id: string }, existing: any, task: any, maxSeenIndex: number): string {
  const terminal = terminalStatus(task);
  if (existing && existing.status) return existing.status;
  if (terminal === 'completed') return '已完成';
  if (terminal === 'failed') return def.id === 'deliver' || flowStageIndex(def.id) <= maxSeenIndex ? '异常' : '待处理';
  if (flowStageIndex(def.id) < maxSeenIndex) return '已完成';
  return '待处理';
}

function normalizedFlowStages(rawSteps: any[], task: any): WorkbenchStep[] {
  const byStage = new Map<string, any>();
  let maxSeenIndex = -1;
  (rawSteps || []).forEach((rawStep) => {
    const stage = workbenchStageFromStep(rawStep);
    const stageIndex = flowStageIndex(stage);
    maxSeenIndex = Math.max(maxSeenIndex, stageIndex);
    const cleanText = userFacingTaskText(rawStep && rawStep.text, stage);
    const rows = uniqueTexts([].concat(rawStep && rawStep.rows || []).map((row) => userFacingTaskText(row, stage)).filter(Boolean), 3);
    const mergedRows = uniqueTexts([cleanText].concat(rows).filter(Boolean), 3);
    const existing = byStage.get(stage);
    const status = String(rawStep && rawStep.status || '').trim();
    const tone = rawStep && rawStep.tone;
    byStage.set(stage, {
      id: stage,
      stage,
      title: rawStep && (rawStep.title || rawStep.label) || stageDef(stage).title,
      status: status || (existing && existing.status) || '',
      tone: tone || (existing && existing.tone) || '',
      label: rawStep && rawStep.label || stageDef(stage).title,
      text: mergedRows[0] || (existing && existing.text) || '',
      rows: uniqueTexts((existing && existing.rows || []).concat(mergedRows), 3),
    });
  });

  return TASK_REPORT_STAGE_DEFS.map((def) => {
    const existing = byStage.get(def.id);
    const status = inferredStageStatus(def, existing, task, maxSeenIndex);
    const text = existing && existing.text ? existing.text : stageFallbackText(def.id, status);
    const rows = existing && existing.rows && existing.rows.length
      ? uniqueTexts(existing.rows.filter((row: string) => row !== text), 2)
      : [];
    return {
      id: def.id,
      stage: def.id,
      title: def.title,
      status,
      tone: existing && existing.tone ? existing.tone : (status === '已完成' ? 'answer' : (status === '进行中' ? 'action' : '')),
      label: `${def.title} · ${status}`,
      text,
      rows,
    };
  });
}

function normalizedWorkbenchSteps(steps: any[], task: any): WorkbenchStep[] {
  const liveSteps = liveStepsForTask(task);
  if (liveSteps.length) return normalizedFlowStages(liveSteps, task);
  if (!Array.isArray(steps) || !steps.length) {
    const metadataSteps = metadataStepsForTask(task);
    if (metadataSteps.length) return normalizedFlowStages(metadataSteps, task);
    return normalizedFlowStages([{
      id: 'check',
      stage: 'check',
      tone: 'answer',
      status: statusLabel(task && task.status),
      label: statusLabel(task && task.status),
      text: '此任务未保存更细步骤，已显示摘要。',
    }], task);
  }
  const finalSummary = taskSummary(task);
  const persistedSteps = steps.map((step) => {
    const label = stepLabel(step);
    const tone = stepTone(step.step_type);
    const stage = workbenchStageFromStep({ id: step && (step.step_id || step.id), title: label });
    const text = userFacingTaskText(stepText(step), stage);
    if (finalSummary && text && finalSummary.includes(text.slice(0, 80))) return null;
    if (text.length > 260 && stage === 'check') return null;
    return {
      id: String(step && (step.step_id || step.id || '') || '').trim(),
      stage,
      tone,
      status: tone === 'error' ? '异常' : (tone === 'action' ? '进行中' : '已完成'),
      label,
      title: label || '过程',
      text,
    };
  }).filter((step) => !!step && !!step.text) as WorkbenchStep[];
  return normalizedFlowStages(persistedSteps, task);
}

function renderStageOverview(steps: WorkbenchStep[]): string {
  const byStage = new Map<string, WorkbenchStep>();
  (steps || []).forEach((step) => {
    const stage = workbenchStageFromStep(step);
    byStage.set(stage, step);
  });
  return [
    '<div class="wa-task-workbench-stage-grid" aria-label="任务阶段总览">',
    TASK_REPORT_STAGE_DEFS.map((def, index) => {
      const step = byStage.get(def.id);
      const status = step ? String(step.status || (step.tone === 'action' ? '进行中' : '已完成')) : '待处理';
      const tone = statusClass(status, step && step.tone);
      const summary = stageActionText(def.id, step);
      return [
        `<div class="wa-task-workbench-stage ${tone}" data-stage="${attr(def.id)}">`,
        '  <div class="wa-task-workbench-stage-top">',
        `    <span class="wa-task-workbench-stage-index">${index + 1}</span>`,
        `    <strong>${esc(def.title)}</strong>`,
        `    <em>${esc(status)}</em>`,
        '  </div>',
        `  <div class="wa-task-workbench-stage-text">${esc(summary)}</div>`,
        '</div>',
      ].join('');
    }).join(''),
    '</div>',
  ].join('');
}

function renderSteps(steps: any[], task: any): string {
  const visibleSteps = normalizedWorkbenchSteps(steps, task);
  if (!visibleSteps.length) {
    return '<div class="wa-task-workbench-empty">暂无步骤</div>';
  }
  return [
    `<div class="wa-task-workbench-section-title">${esc(TASK_REPORT_LABELS.processTitle)}</div>`,
    renderStageOverview(visibleSteps),
  ].join('');
}

function renderCompletionReport(task: WorkbenchTask, summary: string, artifactButton: string): string {
  const stats = renderArtifactStats(task.artifact_result);
  const body = summary
    ? `<div class="wa-task-workbench-summary">${esc(summary)}</div>`
    : '<div class="wa-task-workbench-summary is-empty">暂无任务结果。</div>';
  const actions = artifactButton
    ? `<div class="wa-task-workbench-detail-actions">${artifactButton}</div>`
    : '';
  return [
    `<div class="wa-task-workbench-section-title">${esc(TASK_REPORT_LABELS.finalTitle)}</div>`,
    '<div class="wa-task-workbench-completion">',
    stats,
    actions,
    body,
    '</div>',
  ].join('');
}
function renderTaskFiles(files: WorkbenchFile[]): string {
  if (!Array.isArray(files) || !files.length) return '';
  const visible = files.slice(0, 3);
  const more = files.length > visible.length ? `<span class="wa-task-workbench-file-more">+${files.length - visible.length}</span>` : '';
  return [
    '<div class="wa-task-workbench-files">',
    visible.map((file) => [
      `<button type="button" class="wa-task-workbench-file" data-task-file-path="${attr(file.path)}" title="${attr(file.path)}">`,
      `  <span>${esc(file.name || basename(file.path) || '文档')}</span>`,
      file.target ? '  <em>目标</em>' : '',
      '</button>',
    ].join('')).join(''),
    more,
    '</div>',
  ].join('');
}

function renderArtifactStats(result: any): string {
  if (!result || typeof result !== 'object') return '';
  const stats = [
    ['产物', Array.isArray(result.artifacts) ? result.artifacts.length : 0],
    ['变更', Array.isArray(result.changes) ? result.changes.length : 0],
    ['引用', Array.isArray(result.sources) ? result.sources.length : 0],
    ['过程记录', Array.isArray(result.logs) ? result.logs.length : 0],
  ].filter((entry) => entry[1] > 0);
  if (!stats.length) return '';
  return [
    '<div class="wa-task-workbench-artifacts">',
    stats.map(([label, count]) => `<span>${esc(label)} ${esc(count)}</span>`).join(''),
    '</div>',
  ].join('');
}

function renderDetail(state: WorkbenchState, task: WorkbenchTask | null): void {
  const detail = state.host.querySelector('#wa-task-workbench-detail');
  if (!detail) return;
  if (!task) {
    renderEmptyDetail(detail as HTMLElement);
    return;
  }
  const summary = taskCompletionSummary(task);
  const files = taskFiles(task);
  const artifactButton = task.artifact_result
    ? '<button type="button" data-task-detail-action="artifact">查看产物</button>'
    : '';
  const metaLine = taskMetaLine(task);
  const modelLabel = taskModelLabel(task);
  detail.innerHTML = [
    '<div class="wa-task-workbench-detail-head">',
    `  <span class="wa-task-workbench-status" data-status="${esc(task.status)}">${esc(statusLabel(task.status))}</span>`,
    `  <strong>${esc(taskTitle(task))}</strong>`,
    metaLine ? `  <span>${esc(metaLine)}</span>` : '',
    taskTypeMetaHtml(task),
    modelLabel ? `  <span class="koto-task-model-meta">${esc(modelLabel)}</span>` : '',
    '</div>',
    renderTaskFiles(files),
    '<div class="wa-task-workbench-steps">',
    renderSteps(task.steps, task),
    '</div>',
    renderCompletionReport(task, summary, artifactButton),
  ].join('');
}

async function fetchJson(url: string): Promise<any> {
  const response = await fetch(url, { cache: 'no-store' });
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data.ok === false) {
    throw new Error(data.error || `HTTP ${response.status}`);
  }
  return data;
}

async function loadActiveTask(state: WorkbenchState): Promise<WorkbenchTask | null> {
  const id = String(state.activeTaskId || '').trim();
  if (!id) return null;
  const requestVersion = ++state.requestVersion;
  state.loading = true;
  renderEmptyDetail(state.host.querySelector('#wa-task-workbench-detail') as HTMLElement, '正在读取任务详情...');
  try {
    const data = await fetchJson(`/api/tasks/${encodeURIComponent(id)}`);
    if (requestVersion !== state.requestVersion || id !== state.activeTaskId) return null;
    const task = normalizeTask(data.data);
    state.activeTask = task && task.task_id ? task : null;
    renderDetail(state, state.activeTask);
    return state.activeTask;
  } catch (error: any) {
    if (requestVersion !== state.requestVersion || id !== state.activeTaskId) return null;
    state.activeTask = null;
    renderEmptyDetail(
      state.host.querySelector('#wa-task-workbench-detail') as HTMLElement,
      `任务详情暂不可用：${String(error && error.message || error || '读取失败')}`,
    );
    return null;
  } finally {
    if (requestVersion === state.requestVersion) state.loading = false;
  }
}

function bindWorkbench(state: WorkbenchState): void {
  state.host.addEventListener('click', (event: Event) => {
    const target = (event.target as HTMLElement) && (event.target as HTMLElement).closest ? (event.target as HTMLElement).closest('button') : null;
    if (!target) return;
    const filePath = target.getAttribute('data-task-file-path');
    if (filePath) {
      openTaskFile(filePath);
      return;
    }
    const action = target.getAttribute('data-task-workbench-action');
    if (action === 'close') {
      state.host.hidden = true;
      return;
    }
    if (action === 'refresh') {
      if (state.activeTaskId) void loadActiveTask(state);
      else renderEmptyDetail(state.host.querySelector('#wa-task-workbench-detail') as HTMLElement);
      return;
    }
    const detailAction = target.getAttribute('data-task-detail-action');
    const task = state.activeTask;
    if (!task) return;
    if (detailAction === 'artifact' && task.artifact_result && typeof workspaceApi.renderArtifactResult === 'function') {
      workspaceApi.renderArtifactResult(task.artifact_result);
    }
  });
}

export function initTaskWorkbench(): WorkbenchState | null {
  const host = ensureWorkbench();
  if (!host || (host as any)._waTaskWorkbenchState) return host ? (host as any)._waTaskWorkbenchState : null;
  const state: WorkbenchState = {
    host,
    activeTaskId: '',
    activeTask: null,
    loading: false,
    requestVersion: 0,
  };
  (host as any)._waTaskWorkbenchState = state;
  bindWorkbench(state);
  renderEmptyDetail(host.querySelector('#wa-task-workbench-detail') as HTMLElement);
  return state;
}

export function openTaskWorkbenchForCurrentRun(options?: { taskId?: any; scroll?: boolean }): HTMLElement | null {
  const state = initTaskWorkbench();
  if (!state || !state.host) return null;
  const opts = options || {};
  const explicitTaskId = String(opts.taskId || '').trim();
  if (!explicitTaskId) return null;
  state.activeTaskId = explicitTaskId;
  state.activeTask = null;
  state.host.hidden = false;
  void loadActiveTask(state);
  if (opts.scroll !== false && typeof state.host.scrollIntoView === 'function') {
    state.host.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }
  return state.host;
}

export function refreshCurrentTaskFlow(): Promise<any> {
  const state = initTaskWorkbench();
  if (!state) return Promise.resolve(null);
  if (!state.activeTaskId) {
    renderEmptyDetail(state.host.querySelector('#wa-task-workbench-detail') as HTMLElement);
    return Promise.resolve([]);
  }
  return loadActiveTask(state);
}

function ready(): void {
  initTaskWorkbench();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', ready, { once: true });
} else {
  ready();
}

registerFeatures({
  initTaskWorkbench,
  refreshCurrentTaskFlow,
  openTaskWorkbenchForCurrentRun,
});
