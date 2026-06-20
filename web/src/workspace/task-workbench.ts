/**
 * Task Workbench UI — batch task management
 * Converted from workspace-task-workbench.js
 */

export interface WorkbenchFile {
  path: string;
  name: string;
  type: string;
  target: boolean;
}

export interface WorkbenchStep {
  tone: string;
  label: string;
  text: string;
}

export interface WorkbenchTask {
  task_id: string;
  session_id: string;
  user_input: string;
  status: string;
  task_type: string;
  source: string;
  created_at: string;
  started_at: string;
  completed_at: string;
  result_summary: string;
  error: string;
  step_count: number;
  tool_calls: number;
  elapsed_seconds: number;
  artifact_result: Record<string, any> | null;
  steps: any[];
  metadata: string;
}

export interface TaskWorkbenchConfig {
  host?: HTMLElement;
}

export interface WorkbenchAction {
  action: string;
  taskId?: string;
}

interface WorkbenchState {
  host: HTMLElement;
  tasks: WorkbenchTask[];
  activeTaskId: string;
  filter: string;
  focusedOnly: boolean;
  loading: boolean;
  refreshTimer: number | null;
}

const STATUS_LABELS: Record<string, string> = {
  pending: '排队',
  running: '进行中',
  waiting: '待确认',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
  retrying: '重试中',
};

const PRESET_LABELS: Record<string, string> = {
  proactive_agent_tick: '后台巡检',
  startup_runtime_health: '启动检查',
  startup_health: '启动检查',
};

const TASK_TYPE_LABELS: Record<string, string> = {
  file_task: '文件任务',
  proactive_tick: '后台巡检',
  background_agent: '后台任务',
  agent: 'Agent 任务',
  chat: '对话任务',
};

const STEP_TYPE_LABELS: Record<string, string> = {
  ACTION: '操作',
  OBSERVATION: '反馈',
  ANSWER: '完成',
  ERROR: '异常',
  THOUGHT: '分析',
  PLAN: '计划',
};

const TOOL_LABELS: Record<string, string> = {
  parse_file_to_text: '读取文件',
  read_file: '读取文件',
  open_file: '打开文件',
  write_file: '写入文件',
  write_docx_content: '写入文档',
  write_sheet_data: '写入表格',
  annotate_file: '添加批注',
  generate_preview: '生成预览',
  run_python_code: '执行代码',
};

const TITLE_KEYS = ['query', 'task', 'user_input', 'prompt', 'text', 'title', 'instruction'];
const SUMMARY_KEYS = ['summary', 'message', 'error', 'observation', 'result_summary', 'result', 'preview'];
const STARTUP_HEALTH_PROMPT = '请总结当前 Koto 的后台运行状态';
const INTERNAL_AGENT_SESSIONS = new Set(['s1', 'test-session']);

function esc(text: any): string {
  return String(text || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

function attr(text: any): string {
  return esc(text).replace(/"/g, '&quot;');
}

function compactText(value: any, limit: any): string {
  const text = String(value || '').replace(/\s+/g, ' ').trim();
  const max = Number(limit || 0);
  if (!text || !max || text.length <= max) return text;
  return `${text.slice(0, Math.max(0, max - 3)).trimEnd()}...`;
}

function safeJsonObject(value: any): Record<string, any> | null {
  const text = String(value || '').trim();
  if (!text || text[0] !== '{') return null;
  try {
    const parsed = JSON.parse(text);
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : null;
  } catch (_) {
    return null;
  }
}

function firstPayloadText(payload: any, keys?: string[]): string {
  if (!payload || typeof payload !== 'object') return '';
  const fields = Array.isArray(keys) && keys.length ? keys : TITLE_KEYS.concat(SUMMARY_KEYS);
  for (const key of fields) {
    const value = payload[key];
    if (typeof value === 'string' && value.trim()) return value.trim();
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      const nested = firstPayloadText(value, fields);
      if (nested) return nested;
    }
  }
  return '';
}

function payloadPresetKey(payload: any): string {
  return String(payload && (payload.preset_key || payload.presetKey || payload.preset) || '').trim();
}

function readableType(value: any): string {
  const type = String(value || '').trim();
  if (!type) return '';
  return TASK_TYPE_LABELS[type] || compactText(type.replace(/[_-]+/g, ' '), 24);
}

function readableJsonishText(value: any, limit: number, options?: { includePreset?: boolean }): string {
  const text = String(value || '').trim();
  if (!text) return '';
  const parsed = safeJsonObject(text);
  if (parsed) {
    const payloadText = firstPayloadText(parsed);
    if (payloadText) return compactText(payloadText, limit);
    const preset = payloadPresetKey(parsed);
    if (preset && options && options.includePreset) {
      return PRESET_LABELS[preset] || '后台任务';
    }
    return '';
  }
  if (text[0] === '[' || text[0] === '{') return '';
  return compactText(text, limit);
}

function normalizeTask(raw: any): WorkbenchTask {
  const task = raw && typeof raw === 'object' ? raw : ({} as any);
  return {
    task_id: String(task.task_id || '').trim(),
    session_id: String(task.session_id || '').trim(),
    user_input: String(task.user_input || '').trim(),
    status: String(task.status || '').trim().toLowerCase(),
    task_type: String(task.task_type || '').trim(),
    source: String(task.source || '').trim(),
    created_at: String(task.created_at || '').trim(),
    started_at: String(task.started_at || '').trim(),
    completed_at: String(task.completed_at || '').trim(),
    result_summary: String(task.result_summary || '').trim(),
    error: String(task.error || '').trim(),
    step_count: Number(task.step_count || 0),
    tool_calls: Number(task.tool_calls || 0),
    elapsed_seconds: Number(task.elapsed_seconds || 0),
    artifact_result: task.artifact_result && typeof task.artifact_result === 'object' ? task.artifact_result : null,
    steps: Array.isArray(task.steps) ? task.steps : [],
    metadata: typeof task.metadata === 'string'
      ? task.metadata.trim()
      : (task.metadata && typeof task.metadata === 'object' ? JSON.stringify(task.metadata) : ''),
  };
}

function shortId(taskId: any): string {
  return String(taskId || '').replace(/-/g, '').slice(0, 8) || 'task';
}

function statusLabel(status: any): string {
  return STATUS_LABELS[String(status || '').toLowerCase()] || '任务';
}

function timeLabel(value: any): string {
  if (!value) return '';
  const time = Date.parse(value);
  if (!Number.isFinite(time)) return value;
  const diff = Date.now() - time;
  const minute = 60 * 1000;
  const hour = 60 * minute;
  const day = 24 * hour;
  if (diff >= 0 && diff < minute) return '刚刚';
  if (diff >= 0 && diff < hour) return `${Math.max(1, Math.round(diff / minute))} 分钟前`;
  if (diff >= 0 && diff < day) return `${Math.round(diff / hour)} 小时前`;
  return new Date(time).toLocaleDateString();
}

function parseMetadata(task: any): Record<string, any> {
  try {
    const parsed = JSON.parse(String(task && task.metadata || '{}'));
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch (_) {
    return {};
  }
}

function taskPayload(task: any): Record<string, any> | null {
  return safeJsonObject(task && task.user_input) || parseMetadata(task);
}

function isHousekeepingTask(task: any): boolean {
  const payload = taskPayload(task);
  const preset = payloadPresetKey(payload);
  const hasUserText = !!firstPayloadText(payload, TITLE_KEYS);
  const type = String(task && task.task_type || '').trim();
  const source = String(task && task.source || '').trim();
  const sessionId = String(task && task.session_id || '').trim();
  const input = String(task && task.user_input || '').trim();
  const systemJob = source === 'job_runner' || sessionId === 'system';
  if (systemJob && (preset === 'proactive_agent_tick' || preset === 'startup_runtime_health')) return true;
  if (source === 'agent' && (type === 'SYSTEM' || type === 'PLAN')) return true;
  if (source === 'agent' && INTERNAL_AGENT_SESSIONS.has(sessionId)) return true;
  if (source === 'agent' && input.includes(STARTUP_HEALTH_PROMPT)) return true;
  if (preset === 'proactive_agent_tick' && !hasUserText) return true;
  return type === 'proactive_tick' && source === 'job_runner' && !hasUserText;
}

function displayTasksForFilter(state: WorkbenchState): WorkbenchTask[] {
  const visible = state.tasks.filter((task) => !isHousekeepingTask(task));
  return state.filter === 'all'
    ? visible
    : visible.filter((task) => task.status === state.filter);
}

function activeDisplayTask(state: WorkbenchState): WorkbenchTask | null {
  const visible = displayTasksForFilter(state);
  if (visible.some((task) => task.task_id === state.activeTaskId)) {
    return state.tasks.find((task) => task.task_id === state.activeTaskId) || null;
  }
  return visible[0] || null;
}

function runIdForTask(task: any): string {
  const metadata = parseMetadata(task);
  return String(metadata.run_id || '').trim();
}

function basename(path: any): string {
  const value = String(path || '').trim();
  if (!value) return '';
  return value.replace(/\\/g, '/').split('/').filter(Boolean).pop() || value;
}

function taskFiles(task: any): WorkbenchFile[] {
  const metadata = parseMetadata(task);
  const seen = new Set<string>();
  const files: WorkbenchFile[] = [];
  const pushFile = (item: any) => {
    const source = item && typeof item === 'object' ? item : { path: item };
    const path = String(source.path || source.file || source.target_path || '').trim();
    if (!path || seen.has(path)) return;
    seen.add(path);
    files.push({
      path,
      name: String(source.name || basename(path) || '文档').trim(),
      type: String(source.type || '').trim(),
      target: !!source.target,
    });
  };
  if (Array.isArray(metadata.files)) metadata.files.forEach(pushFile);
  if (metadata.target_path) pushFile({ path: metadata.target_path, target: true });
  return files;
}

function taskRouteLabel(task: any, metadata?: Record<string, any>): string {
  const data = metadata || parseMetadata(task);
  const routeIntent = data.route_intent && typeof data.route_intent === 'object' ? data.route_intent : null;
  const routeValue = String(
    (routeIntent && (routeIntent.task_type || routeIntent.route || routeIntent.intent || routeIntent.label))
    || task && task.task_type
    || ''
  ).trim();
  if (!routeValue) return '文件任务';
  if (TASK_TYPE_LABELS[routeValue]) return TASK_TYPE_LABELS[routeValue];
  return readableType(routeValue) || compactText(routeValue.replace(/[_-]+/g, ' '), 24);
}

function metadataModelLabel(task: any, metadata?: Record<string, any>): string {
  const data = metadata || parseMetadata(task);
  const payload = data.task_request_payload && typeof data.task_request_payload === 'object'
    ? data.task_request_payload
    : taskPayload(task);
  const mode = String(data.model_mode || payload && payload.model_mode || '').trim();
  const modelId = String(data.model_id || payload && payload.model_id || '').trim();
  const modeLabels: Record<string, string> = {
    auto: '自动',
    gemini: 'DeepSeek',
    cloud: 'DeepSeek',
    deepseek: 'DeepSeek',
    local: '本地模型',
  };
  const modeLabel = modeLabels[mode.toLowerCase()] || compactText(mode, 24);
  if (!modeLabel) return modelId;
  if (!modelId || modeLabel.toLowerCase().includes(modelId.toLowerCase())) return modeLabel;
  return `${modeLabel} · ${modelId}`;
}

function metadataStepsForTask(task: any): WorkbenchStep[] {
  const metadata = parseMetadata(task);
  const route = taskRouteLabel(task, metadata);
  const model = metadataModelLabel(task, metadata) || '自动';
  const status = terminalStatus(task);
  const steps: WorkbenchStep[] = [{
    tone: status === 'failed' ? 'error' : (status === 'completed' ? 'answer' : 'action'),
    label: `模型调用 · ${statusLabel(task && task.status)}`,
    text: `路由：${route} · 模型：${model}${runIdForTask(task) ? ` · 运行：${runIdForTask(task)}` : ''}`,
  }];
  const files = taskFiles(task);
  if (files.length) {
    const names = files.slice(0, 3).map((file) => file.name || basename(file.path)).filter(Boolean);
    const more = files.length > names.length ? `，另有 ${files.length - names.length} 个文件` : '';
    steps.push({
      tone: 'answer',
      label: '文件上下文 · 已载入',
      text: `已纳入 ${files.length} 个文件：${names.join('、')}${more}`,
    });
  }
  const summary = taskSummary(task);
  if (summary) {
    steps.push({
      tone: status === 'failed' ? 'error' : 'answer',
      label: status === 'failed' ? '结果 · 失败' : '结果 · 已完成',
      text: compactText(summary, 170),
    });
  }
  return steps;
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

function focusTaskCard(taskId: any, runId: any): boolean {
  const card = taskCardForTask(taskId, runId) as any;
  if (!card) return false;
  card.classList.add('is-workbench-focused');
  if (card._waWorkbenchFocusTimer) window.clearTimeout(card._waWorkbenchFocusTimer);
  card._waWorkbenchFocusTimer = window.setTimeout(() => {
    card.classList.remove('is-workbench-focused');
    card._waWorkbenchFocusTimer = null;
  }, 1600);
  if (typeof card.scrollIntoView === 'function') {
    card.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }
  return true;
}

function taskTitle(task: any): string {
  const input = String(task && task.user_input || '').trim();
  const inputPayload = safeJsonObject(input);
  if (input && !inputPayload) return compactText(input, 72);

  const payload = inputPayload || taskPayload(task);
  const payloadTitle = firstPayloadText(payload, TITLE_KEYS);
  if (payloadTitle) return compactText(payloadTitle, 72);

  const summaryTitle = readableJsonishText(task && (task.result_summary || task.error), 72, { includePreset: false });
  if (summaryTitle) return summaryTitle;

  const preset = payloadPresetKey(payload);
  if (preset) return PRESET_LABELS[preset] || '后台任务';
  return readableType(task && task.task_type) || 'Koto 任务';
}

function taskSummary(task: any): string {
  const summary = readableJsonishText(task && (task.result_summary || task.error), 180, { includePreset: false });
  if (summary) return summary;
  return compactText(firstPayloadText(taskPayload(task), SUMMARY_KEYS), 180);
}

function taskMetaLine(task: any): string {
  const parts = [
    timeLabel(task && task.created_at),
    readableType(task && task.task_type),
  ].filter(Boolean);
  if (task && task.elapsed_seconds > 0.05) {
    parts.push(`${Math.max(1, Math.round(task.elapsed_seconds))} 秒`);
  }
  return parts.join(' · ');
}

function openTaskFile(path: any): void {
  const value = String(path || '').trim();
  if (!value || !(window as any).WA) return;
  if (typeof (window as any).WA.openRecentFile === 'function') {
    void (window as any).WA.openRecentFile(value);
    return;
  }
  if (/^[a-z]:[\\/]/i.test(value) && typeof (window as any).WA.openBrowserFile === 'function') {
    void (window as any).WA.openBrowserFile(value, true);
    return;
  }
  if (typeof (window as any).WA.openWorkspaceFile === 'function') {
    void (window as any).WA.openWorkspaceFile(value.replace(/^workspace[\\/]/i, ''));
  }
}

function terminalStatus(task: any): string {
  const status = String(task.status || '').toLowerCase();
  if (status === 'waiting') return 'waiting';
  if (status === 'cancelled') return 'cancelled';
  if (status === 'failed') return 'failed';
  if (status === 'completed') return 'completed';
  return status || 'running';
}

function decodeTaskPayload(value: any): Record<string, any> {
  const raw = String(value || '').trim();
  if (!raw) return {};
  try {
    const parsed = JSON.parse(decodeURIComponent(raw));
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
  } catch (_) {
    return {};
  }
}

function latestLiveTaskCard(): HTMLElement | null {
  const cards = Array.from(document.querySelectorAll('.wa-task-run')) as HTMLElement[];
  for (let index = cards.length - 1; index >= 0; index--) {
    const card = cards[index];
    if (card.classList.contains('streaming')) return card;
  }
  for (let index = cards.length - 1; index >= 0; index--) {
    const card = cards[index];
    const dataset = card.dataset || {};
    if (String(dataset.taskRunId || '').trim() && !liveCardCompleted(card)) return card;
  }
  return null;
}

function statusFromLiveCard(card: HTMLElement): string {
  const dataset = card.dataset || {};
  const terminal = String(dataset.taskTerminalStatus || '').trim().toLowerCase();
  if (terminal === 'cancelled') return 'cancelled';
  if (terminal === 'failed' || terminal === 'error' || terminal === 'blocked') return 'failed';
  if (terminal === 'completed' || terminal === 'verified' || card.classList.contains('done')) return 'completed';
  if (card.classList.contains('cancelled')) return 'cancelled';
  if (card.classList.contains('failed')) return 'failed';
  return 'running';
}

function liveTaskFromCard(card: HTMLElement): WorkbenchTask {
  const dataset = card.dataset || {};
  const requestPayload = decodeTaskPayload(dataset.taskFollowupPayload || dataset.taskPendingResumePayload || '');
  const metadata: Record<string, any> = {
    run_id: String(dataset.taskRunId || '').trim(),
    files: Array.isArray(requestPayload.files) ? requestPayload.files : [],
    task_request_payload: requestPayload,
  };
  const routeIntent = requestPayload.options && typeof requestPayload.options === 'object'
    ? requestPayload.options.workspace_route_intent
    : null;
  if (routeIntent && typeof routeIntent === 'object') metadata.route_intent = routeIntent;
  if (requestPayload.model_mode) metadata.model_mode = requestPayload.model_mode;
  if (requestPayload.model_id) metadata.model_id = requestPayload.model_id;
  return normalizeTask({
    task_id: String(dataset.taskId || '').trim(),
    session_id: '',
    user_input: String(dataset.taskRequest || requestPayload.task || '').trim() || '文件任务',
    status: statusFromLiveCard(card),
    task_type: 'file_task',
    source: 'file_task',
    created_at: '',
    result_summary: String(dataset.taskSummary || card.querySelector('[data-role="summary"]')?.textContent || '').trim(),
    step_count: card.querySelectorAll('.wa-task-step').length,
    tool_calls: card.querySelectorAll('.wa-task-row').length,
    metadata: JSON.stringify(metadata),
  });
}

function renderFocusedLiveTask(state: WorkbenchState): boolean {
  const card = latestLiveTaskCard();
  if (!card) return false;
  renderTaskRows(state);
  renderDetail(state, liveTaskFromCard(card));
  return true;
}

function aiMessagesHost(): HTMLElement | null {
  return document.getElementById('wa-ai-messages') as HTMLElement | null;
}

function ensureWorkbenchChrome(host: HTMLElement | null): void {
  if (!host) return;
  const actions = host.querySelector('.wa-task-workbench-actions');
  const historyButton = actions ? actions.querySelector('[data-task-workbench-action="history"]') : null;
  if (historyButton) historyButton.remove();
  const filters = host.querySelector('.wa-task-workbench-filters') as HTMLElement | null;
  if (filters) filters.hidden = true;
  const kicker = host.querySelector('.wa-task-workbench-title-group .wa-task-workbench-kicker');
  if (kicker) kicker.textContent = '流程';
  const title = host.querySelector('.wa-task-workbench-title-group strong');
  if (title) title.textContent = '任务流程';
}

function setWorkbenchFocusedMode(state: WorkbenchState, _focused: boolean): void {
  if (!state || !state.host) return;
  const enabled = true;
  state.focusedOnly = enabled;
  state.host.classList.toggle('is-focused-task', enabled);
  const title = state.host.querySelector('.wa-task-workbench-title-group strong');
  if (title) title.textContent = '任务流程';
  const filters = state.host.querySelector('.wa-task-workbench-filters') as HTMLElement | null;
  if (filters) filters.hidden = true;
  const list = state.host.querySelector('#wa-task-workbench-list');
  if (list) list.innerHTML = '';
}

function ensureWorkbench(): HTMLElement | null {
  let host = document.getElementById('wa-task-workbench');
  if (host) {
    const messages = aiMessagesHost();
    if (messages && host.parentElement !== messages) {
      messages.appendChild(host);
    }
    host.classList.add('wa-inline-task-workbench');
    ensureWorkbenchChrome(host);
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
    '  <div id="wa-task-workbench-list" class="wa-task-workbench-list"></div>',
    '  <div id="wa-task-workbench-detail" class="wa-task-workbench-detail"></div>',
    '</div>',
  ].join('');
  fallbackAnchor.appendChild(host);
  ensureWorkbenchChrome(host);
  return host;
}

function emptyTaskFlowHtml(): string {
  return [
    '<div class="wa-task-workbench-empty wa-task-workbench-empty-flow">',
    '  <strong>等待文件任务</strong>',
    '  <span>当请求需要读取、修改或生成文件时，这里会直接展开任务识别、执行方案、进度和核验结果。</span>',
    '  <div class="wa-task-workbench-empty-steps">',
    '    <span>任务识别</span>',
    '    <span>模型调用</span>',
    '    <span>执行进度</span>',
    '    <span>完成核验</span>',
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

function renderTaskRows(state: WorkbenchState): void {
  const list = state.host.querySelector('#wa-task-workbench-list');
  if (!list) return;
  if (state.focusedOnly) {
    list.innerHTML = '';
    return;
  }
  const filtered = displayTasksForFilter(state);
  if (!filtered.length) {
    list.innerHTML = `<div class="wa-task-workbench-empty">${state.tasks.length ? '暂无可展示任务' : '暂无任务'}</div>`;
    return;
  }
  list.innerHTML = filtered.map((task) => {
    const active = task.task_id === state.activeTaskId ? ' is-active' : '';
    const artifactDot = task.artifact_result ? '<span class="wa-task-workbench-dot" title="有结果产物"></span>' : '';
    const title = taskTitle(task);
    const time = timeLabel(task.created_at);
    return [
      `<button type="button" class="wa-task-workbench-item${active}" data-task-id="${attr(task.task_id)}">`,
      `  <span class="wa-task-workbench-item-title">${esc(title)}</span>`,
      '  <span class="wa-task-workbench-item-meta">',
      `    <span data-status="${esc(task.status)}">${esc(statusLabel(task.status))}</span>`,
      time ? `    <span>${esc(time)}</span>` : '',
      `    ${artifactDot}`,
      '  </span>',
      '</button>',
    ].join('');
  }).join('');
}

function stepTone(stepType: any): string {
  const value = String(stepType || '').toUpperCase();
  if (value === 'ERROR') return 'error';
  if (value === 'ACTION') return 'action';
  if (value === 'ANSWER') return 'answer';
  return '';
}

function stepLabel(step: any): string {
  const type = String(step && step.step_type || '').trim().toUpperCase();
  const toolName = String(step && step.tool_name || '').trim();
  const typeLabel = STEP_TYPE_LABELS[type] || '过程';
  const toolLabel = TOOL_LABELS[toolName] || '';
  return [typeLabel, toolLabel].filter(Boolean).join(' · ');
}

function stepText(step: any): string {
  const text = readableJsonishText(step && (step.content || step.observation || step.message || step.error), 170, { includePreset: false });
  if (text) return text;
  const toolName = String(step && step.tool_name || '').trim();
  return toolName ? `${TOOL_LABELS[toolName] || '工具'}已执行` : '';
}

function liveCardCompleted(card: any): boolean {
  const dataset = card && card.dataset ? card.dataset : {};
  const terminal = String(dataset['taskTerminalStatus'] || '').trim().toLowerCase();
  return terminal === 'completed' || terminal === 'verified' || String(dataset['taskCompleted'] || '').trim().toLowerCase() === 'true';
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
  const raw = String(row.innerText || row.textContent || '').trim();
  const compact = raw.replace(/\s+/g, '');
  if (!compact) return '';
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
  return Array.from(card.querySelectorAll('.wa-task-step')).map((step) => {
    let title = String((step.querySelector('.wa-task-step-title') as HTMLElement | null)?.textContent || '').trim() || '步骤';
    const rows = Array.from(step.querySelectorAll('.wa-task-row'))
      .map((row) => liveStepText(liveRowText(row), 150))
      .filter(Boolean);
    if (title === '任务状态' && rows.length === 1 && rows[0].includes('：')) {
      title = rows[0].split('：')[0] || title;
    }
    const status = liveStepStatus(step, card);
    const text = rows.slice(-2).join('；') || status;
    return {
      tone: liveStepTone(step, card),
      label: `${title} · ${status}`,
      text,
    };
  }).filter((step) => step.text);
}

function renderSteps(steps: any[], task: any): string {
  const liveSteps = (!Array.isArray(steps) || !steps.length) ? liveStepsForTask(task) : [];
  if (liveSteps.length) {
    return liveSteps.slice(-5).map((step) => {
      return [
        `<div class="wa-task-workbench-step ${esc(step.tone)}">`,
        `  <div class="wa-task-workbench-step-meta">${esc(step.label || '过程')}</div>`,
        `  <div class="wa-task-workbench-step-text">${esc(step.text)}</div>`,
        '</div>',
      ].join('');
    }).join('');
  }
  if (!Array.isArray(steps) || !steps.length) {
    const metadataSteps = metadataStepsForTask(task);
    if (metadataSteps.length) {
      return metadataSteps.slice(-5).map((step) => {
        return [
          `<div class="wa-task-workbench-step ${esc(step.tone)}">`,
          `  <div class="wa-task-workbench-step-meta">${esc(step.label || '过程')}</div>`,
          `  <div class="wa-task-workbench-step-text">${esc(step.text)}</div>`,
          '</div>',
        ].join('');
      }).join('');
    }
    return [
      '<div class="wa-task-workbench-step answer">',
      `  <div class="wa-task-workbench-step-meta">${esc(statusLabel(task && task.status))}</div>`,
      '  <div class="wa-task-workbench-step-text">此任务未保存更细步骤，已显示摘要。</div>',
      '</div>',
    ].join('');
  }
  const visibleSteps: WorkbenchStep[] = steps.map((step) => ({
    tone: stepTone(step.step_type),
    label: stepLabel(step),
    text: stepText(step),
  })).filter((step) => step.text);
  if (!visibleSteps.length) {
    return '<div class="wa-task-workbench-empty">暂无步骤</div>';
  }
  return visibleSteps.slice(-5).map((step) => {
    return [
      `<div class="wa-task-workbench-step ${esc(step.tone)}">`,
      `  <div class="wa-task-workbench-step-meta">${esc(step.label || '过程')}</div>`,
      `  <div class="wa-task-workbench-step-text">${esc(step.text)}</div>`,
      '</div>',
    ].join('');
  }).join('');
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
    ['文件', Array.isArray(result.artifacts) ? result.artifacts.length : 0],
    ['变更', Array.isArray(result.changes) ? result.changes.length : 0],
    ['来源', Array.isArray(result.sources) ? result.sources.length : 0],
    ['日志', Array.isArray(result.logs) ? result.logs.length : 0],
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
  const summary = taskSummary(task);
  const files = taskFiles(task);
  const artifactButton = task.artifact_result
    ? '<button type="button" data-task-detail-action="artifact">结果</button>'
    : '';
  const canResume = typeof (window as any).WA.resumePersistedFileTask === 'function';
  const processButton = !state.focusedOnly && canResume
    ? '<button type="button" data-task-detail-action="process">定位对话</button>'
    : '';
  const metaLine = taskMetaLine(task);
  detail.innerHTML = [
    '<div class="wa-task-workbench-detail-head">',
    `  <span class="wa-task-workbench-status" data-status="${esc(task.status)}">${esc(statusLabel(task.status))}</span>`,
    `  <strong>${esc(taskTitle(task))}</strong>`,
    metaLine ? `  <span>${esc(metaLine)}</span>` : '',
    '</div>',
    summary ? `<div class="wa-task-workbench-summary">${esc(summary)}</div>` : '',
    renderTaskFiles(files),
    '<div class="wa-task-workbench-detail-actions">',
    processButton,
    artifactButton,
    '</div>',
    renderArtifactStats(task.artifact_result),
    '<div class="wa-task-workbench-steps">',
    renderSteps(task.steps, task),
    '</div>',
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

async function loadTasks(state: WorkbenchState): Promise<void> {
  state.loading = true;
  const list = state.host.querySelector('#wa-task-workbench-list');
  const preferredId = String(state.activeTaskId || '').trim();
  if (list && !state.focusedOnly) list.innerHTML = '<div class="wa-task-workbench-empty">正在读取任务...</div>';
  try {
    const data = await fetchJson('/api/tasks?limit=120&order_by=created_at');
    state.tasks = Array.isArray(data.data) ? data.data.map(normalizeTask) : [];
    const preferred = preferredId
      ? state.tasks.find((task) => task.task_id === preferredId && !isHousekeepingTask(task)) || null
      : null;
    const active = preferred || (!state.focusedOnly ? activeDisplayTask(state) : null);
    const selectedId = active ? active.task_id : (state.focusedOnly ? preferredId : '');
    state.activeTaskId = selectedId;
    renderTaskRows(state);
    if (selectedId) await selectTask(state, selectedId, { silentRows: true, skipFocus: true });
    else if (!(state.focusedOnly && renderFocusedLiveTask(state))) {
      renderEmptyDetail(state.host.querySelector('#wa-task-workbench-detail') as HTMLElement);
    }
  } catch (error: any) {
    if (list) list.innerHTML = `<div class="wa-task-workbench-empty">读取失败：${esc(error.message || error)}</div>`;
    renderEmptyDetail(state.host.querySelector('#wa-task-workbench-detail') as HTMLElement, '任务列表暂不可用');
  } finally {
    state.loading = false;
  }
}

async function selectTask(state: WorkbenchState, taskId: any, options?: { silentRows?: boolean; skipFocus?: boolean }): Promise<void> {
  const id = String(taskId || '').trim();
  if (!id) return;
  state.activeTaskId = id;
  let task = state.tasks.find((item) => item.task_id === id) || null;
  try {
    const data = await fetchJson(`/api/tasks/${encodeURIComponent(id)}`);
    task = normalizeTask(data.data || task);
    const taskIndex = state.tasks.findIndex((item) => item.task_id === id);
    if (taskIndex >= 0) state.tasks = state.tasks.map((item) => item.task_id === id ? task! : item);
    else if (task && task.task_id) state.tasks = [task].concat(state.tasks);
  } catch (_) {
    // Fall back to the list item; the detail route may be unavailable in test shells.
  }
  if (!(options && options.silentRows)) renderTaskRows(state);
  renderDetail(state, task);
  if (!(options && options.skipFocus)) focusTaskCard(id, runIdForTask(task));
}

function scheduleWorkbenchRefresh(state: WorkbenchState, taskId?: any): void {
  if (!state || !state.host || state.host.hidden) return;
  const id = String(taskId || '').trim();
  if (id) state.activeTaskId = id;
  if (!id && state.focusedOnly && !state.activeTaskId && renderFocusedLiveTask(state)) return;
  if (state.refreshTimer) window.clearTimeout(state.refreshTimer);
  state.refreshTimer = window.setTimeout(() => {
    state.refreshTimer = null;
    if (!state.loading) void loadTasks(state);
  }, 450);
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
    const taskId = target.getAttribute('data-task-id');
    if (taskId) {
      void selectTask(state, taskId);
      return;
    }
    const filter = target.getAttribute('data-task-workbench-filter');
    if (filter) {
      setWorkbenchFocusedMode(state, true);
      state.filter = filter;
      renderTaskRows(state);
      renderEmptyDetail(state.host.querySelector('#wa-task-workbench-detail') as HTMLElement);
      return;
    }
    const action = target.getAttribute('data-task-workbench-action');
    if (action === 'close') {
      state.host.hidden = true;
      return;
    }
    if (action === 'history') {
      setWorkbenchFocusedMode(state, true);
      renderTaskRows(state);
      renderEmptyDetail(state.host.querySelector('#wa-task-workbench-detail') as HTMLElement);
      return;
    }
    if (action === 'refresh') {
      if (state.activeTaskId) void loadTasks(state);
      else renderEmptyDetail(state.host.querySelector('#wa-task-workbench-detail') as HTMLElement);
      return;
    }
    const detailAction = target.getAttribute('data-task-detail-action');
    const task = state.tasks.find((item) => item.task_id === state.activeTaskId);
    if (!task) return;
    if (detailAction === 'artifact' && task.artifact_result && (window as any).WA && typeof (window as any).WA.renderArtifactResult === 'function') {
      (window as any).WA.renderArtifactResult(task.artifact_result);
    } else if (detailAction === 'focus') {
      focusTaskCard(task.task_id, runIdForTask(task));
    } else if (detailAction === 'process' && (window as any).WA && typeof (window as any).WA.resumePersistedFileTask === 'function') {
      if (focusTaskCard(task.task_id, runIdForTask(task))) return;
      const syncPromise = (window as any).WA.resumePersistedFileTask({
        taskId: task.task_id,
        runId: runIdForTask(task),
        initialStatus: terminalStatus(task),
        replay: true,
      });
      window.setTimeout(() => focusTaskCard(task.task_id, runIdForTask(task)), 0);
      syncPromise.catch((error: any) => console.warn('[WA taskWorkbench] process sync failed:', error));
    }
  });
}

export function initTaskWorkbench(): WorkbenchState | null {
  const host = ensureWorkbench();
  if (!host || (host as any)._waTaskWorkbenchState) return host ? (host as any)._waTaskWorkbenchState : null;
  const state: WorkbenchState = {
    host,
    tasks: [],
    activeTaskId: '',
    filter: 'all',
    focusedOnly: true,
    loading: false,
    refreshTimer: null,
  };
  (host as any)._waTaskWorkbenchState = state;
  bindWorkbench(state);
  setWorkbenchFocusedMode(state, true);
  renderEmptyDetail(host.querySelector('#wa-task-workbench-detail') as HTMLElement);
  return state;
}

export function openTaskWorkbenchForCurrentRun(options?: { taskId?: any; scroll?: boolean }): HTMLElement | null {
  const state = initTaskWorkbench();
  if (!state || !state.host) return null;
  const opts = options || {};
  const explicitTaskId = String(opts.taskId || '').trim();
  if (explicitTaskId) state.activeTaskId = explicitTaskId;
  setWorkbenchFocusedMode(state, true);
  state.host.hidden = false;
  if (state.activeTaskId && !state.loading) {
    void loadTasks(state);
  } else {
    if (!renderFocusedLiveTask(state)) {
      renderEmptyDetail(state.host.querySelector('#wa-task-workbench-detail') as HTMLElement);
    }
  }
  if (opts.scroll !== false && typeof state.host.scrollIntoView === 'function') {
    state.host.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }
  return state.host;
}

export function refreshCurrentTaskFlow(): Promise<any> {
  const state = initTaskWorkbench();
  if (!state) return Promise.resolve(null);
  if (state.focusedOnly && !state.activeTaskId) {
    if (!renderFocusedLiveTask(state)) {
      renderEmptyDetail(state.host.querySelector('#wa-task-workbench-detail') as HTMLElement);
    }
    return Promise.resolve([]);
  }
  return loadTasks(state);
}

export function notifyTaskFlowChanged(taskId?: any): void {
  const state = initTaskWorkbench();
  if (!state) return;
  scheduleWorkbenchRefresh(state, taskId);
}

function ready(): void {
  initTaskWorkbench();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', ready, { once: true });
} else {
  ready();
}

// Backward compat
const WA = (window as any).WA || {};
WA.initTaskWorkbench = initTaskWorkbench;
WA.refreshCurrentTaskFlow = refreshCurrentTaskFlow;
WA.notifyTaskFlowChanged = notifyTaskFlowChanged;
WA.openTaskWorkbenchForCurrentRun = openTaskWorkbenchForCurrentRun;
(window as any).WA = WA;
