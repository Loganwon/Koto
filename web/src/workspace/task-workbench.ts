import {
  TASK_REPORT_LABELS,
  TASK_REPORT_STAGE_DEFS,
  TASK_REPORT_STAGE_DONE_TEXT,
  taskReportCompactText as compactText,
  taskReportStageActionText as stageActionText,
  taskReportStageDef as stageDef,
  taskReportStageFromStep as stageFromStep,
  taskReportStageStatusText,
  taskReportStatusClass as statusClass,
  taskReportUniqueTexts as uniqueTexts,
} from './task-report-layout';
import { fileTaskStatusLabel, isFileTaskAttentionStatus, normalizeFileTaskTerminalStatus } from './file-task-status';
import { getWorkspaceApi, publishWorkspaceApi } from '../shared/workspace-api';

const workspaceApi = getWorkspaceApi();
/**
 * Task Workbench UI — batch task management
 * Workspace task workbench.
 */

export interface WorkbenchFile {
  path: string;
  name: string;
  type: string;
  target: boolean;
}

export interface WorkbenchStep {
  id?: string;
  stage?: string;
  title?: string;
  status?: string;
  tone: string;
  label: string;
  text: string;
  rows?: string[];
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
  read_file_range: '读取文本',
  write_file: '写入文件',
  create_file: '创建文件',
  write_docx_content: '写入文档',
  write_sheet_data: '写入表格',
  annotate_file: '添加批注',
  generate_preview: '生成预览',
  run_python_code: '执行代码',
};

const INTERNAL_PROGRESS_PATTERNS = [
  /你还没有/,
  /下一轮必须/,
  /不要只总结/,
  /完成真实文件写入/,
  /original_selection/i,
  /replace_file_selection/i,
  /run_python_code/i,
  /read_\.\.\./i,
  /模型路由不可用/,
  /后端 SmartDispatcher 兜底/,
  /planner_policy/i,
  /planner_backend/i,
];

const TITLE_KEYS = ['query', 'task', 'user_input', 'prompt', 'text', 'title', 'instruction'];
const SUMMARY_KEYS = ['summary', 'message', 'error', 'observation', 'result_summary', 'result', 'preview'];
const STARTUP_HEALTH_PROMPT = '请总结当前 Koto 的后台运行状态';
const INTERNAL_AGENT_SESSIONS = new Set(['s1', 'test-session']);
const WORKBENCH_STAGE_BY_STEP_ID: Record<string, string> = {
  'task.classified': 'route',
};

function esc(text: any): string {
  return String(text || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

function attr(text: any): string {
  return esc(text).replace(/"/g, '&quot;');
}

function isInternalProgressText(text: any): boolean {
  const value = String(text || '').trim();
  return !!value && INTERNAL_PROGRESS_PATTERNS.some((pattern) => pattern.test(value));
}

function friendlyFileName(value: any): string {
  return basename(String(value || '').trim().replace(/[。；;，,]+$/g, ''));
}

function userFacingTaskText(value: any, stageId?: string): string {
  const raw = String(value || '').replace(/\s+/g, ' ').trim();
  if (!raw || isInternalProgressText(raw)) return '';
  const chunks = uniqueTexts(raw.split(/[；;\n]+/)
    .map((chunk) => String(chunk || '').replace(/^(进行中|完成|通过|提示)[:：]\s*/, '').trim())
    .filter((chunk) => (
      chunk
      && !isInternalProgressText(chunk)
      && !/^(读取显式上下文|模型规划并调用工具|准备处理\s*\d+\s*个文件)$/.test(chunk)
    )), 4);
  const text = chunks.join('；');
  if (!text) return '';

  const successFile = text.match(/文件已成功(?:修改|写入)[:：]\s*([^；]+)/);
  if (successFile) return `已生成并核验 ${friendlyFileName(successFile[1])}。`;

  const createdFile = text.match(/已创建文件\s*([^；]+)/);
  const changedFile = text.match(/修改[:：]\s*([^；]+)/);
  if (createdFile || changedFile) {
    const name = friendlyFileName((changedFile && changedFile[1]) || (createdFile && createdFile[1]));
    return name ? `已创建并写入 ${name}。` : '已完成文件写入。';
  }

  const preparedFile = text.match(/准备生成\s*([^。；]+)/);
  if (preparedFile) return `已确定生成 ${friendlyFileName(preparedFile[1])}。`;

  const contextCount = text.match(/已整理\s*(\d+)\s*份上下文片段/);
  if (contextCount) return `已读取并整理 ${contextCount[1]} 份文件上下文。`;

  if (/^模型调用[:：]/.test(text) || /路由[:：]/.test(text)) {
    return '已进入文件任务流程，处理方式已确认。';
  }
  if (/^识别[:：]|置信度|write_intent|summary_request/.test(text)) {
    return '已识别为文件处理任务。';
  }
  if (/方案已完成约束检查|通过[:：]/.test(text)) {
    return '方案已通过约束检查。';
  }
  if (/^方案[:：]/.test(text)) {
    return text.replace(/^方案[:：]\s*/, '') || TASK_REPORT_STAGE_DONE_TEXT.plan;
  }
  if (/^完成[:：]/.test(text)) {
    return text.replace(/^完成[:：]\s*/, '') || TASK_REPORT_STAGE_DONE_TEXT.check;
  }
  if (stageId === 'check' && text.length > 80) {
    return TASK_REPORT_STAGE_DONE_TEXT.check;
  }
  if (stageId === 'execute' && text.length > 90) {
    return TASK_REPORT_STAGE_DONE_TEXT.execute;
  }

  return compactText(text, stageId === 'execute' ? 120 : 110);
}

function workbenchStageFromStep(step: any, fallbackStage = ''): string {
  const id = String(step && (step.id || step.step_id || step.stage || '') || '').trim().toLowerCase();
  return WORKBENCH_STAGE_BY_STEP_ID[id] || stageFromStep(step, fallbackStage);
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
  const normalized = String(status || '').trim().toLowerCase();
  if (normalized === 'retrying') return '重试中';
  return fileTaskStatusLabel(normalized, '任务');
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
  const terminalComplete = status === 'completed';
  const terminalFailed = status === 'failed';
  const steps: WorkbenchStep[] = [{
    tone: terminalFailed ? 'error' : (terminalComplete ? 'answer' : 'action'),
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
      tone: terminalFailed ? 'error' : (terminalComplete ? 'answer' : 'action'),
      label: terminalFailed ? '结果 · 失败' : (terminalComplete ? '结果 · 已完成' : `结果 · ${statusLabel(task && task.status)}`),
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

function taskCompletionSummary(task: any): string {
  const text = String(task && (task.result_summary || task.error) || '').trim();
  if (text) {
    const parsed = safeJsonObject(text);
    if (parsed) {
      const payloadText = firstPayloadText(parsed, SUMMARY_KEYS);
      if (payloadText) return compactText(payloadText, 8000);
    } else if (text[0] !== '[' && text[0] !== '{') {
      return compactText(text, 8000);
    }
  }
  return compactText(firstPayloadText(taskPayload(task), SUMMARY_KEYS), 8000);
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

function terminalStatus(task: any): string {
  const metadata = parseMetadata(task);
  return normalizeFileTaskTerminalStatus(
    metadata.task_terminal_status || metadata.terminal_status || metadata.status || (task && task.status),
  ) || 'running';
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
  const terminal = normalizeFileTaskTerminalStatus(dataset.taskTerminalStatus || '');
  if (terminal === 'cancelled') return 'cancelled';
  if (terminal === 'failed' || terminal === 'error' || terminal === 'blocked') return 'failed';
  if (isFileTaskAttentionStatus(terminal)) return 'waiting';
  if (terminal === 'completed' || card.classList.contains('done')) return 'completed';
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
  const routeIntent = requestPayload.routing_decision && typeof requestPayload.routing_decision === 'object'
    ? requestPayload.routing_decision
    : (requestPayload.options && typeof requestPayload.options === 'object'
      ? requestPayload.options.workspace_route_intent
      : null);
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
  const terminal = normalizeFileTaskTerminalStatus(dataset['taskTerminalStatus'] || '');
  if (isFileTaskAttentionStatus(terminal)) return false;
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
  if (terminal === 'failed') return flowStageIndex(def.id) <= maxSeenIndex ? '异常' : '待处理';
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
  const canResume = typeof workspaceApi.resumePersistedFileTask === 'function';
  const processButton = !state.focusedOnly && canResume
    ? '<button type="button" data-task-detail-action="process">定位对话</button>'
    : '';
  const inlineTaskCardOwnsResult = taskHasProjectedInlineCard(task);
  const metaLine = taskMetaLine(task);
  detail.innerHTML = [
    '<div class="wa-task-workbench-detail-head">',
    `  <span class="wa-task-workbench-status" data-status="${esc(task.status)}">${esc(statusLabel(task.status))}</span>`,
    `  <strong>${esc(taskTitle(task))}</strong>`,
    metaLine ? `  <span>${esc(metaLine)}</span>` : '',
    '</div>',
    renderTaskFiles(files),
    '<div class="wa-task-workbench-steps">',
    renderSteps(task.steps, task),
    '</div>',
    '<div class="wa-task-workbench-detail-actions">',
    processButton,
    '</div>',
    inlineTaskCardOwnsResult ? '' : renderCompletionReport(task, summary, artifactButton),
  ].join('');
}

function taskHasProjectedInlineCard(task: WorkbenchTask): boolean {
  const taskId = String(task && task.task_id || '').trim();
  if (!taskId) return false;
  return Array.from(document.querySelectorAll('#wa-ai-messages .wa-task-run.is-workbench-projected'))
    .some((node) => (node as HTMLElement).dataset.taskId === taskId);
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
    if (detailAction === 'artifact' && task.artifact_result && typeof workspaceApi.renderArtifactResult === 'function') {
      workspaceApi.renderArtifactResult(task.artifact_result);
    } else if (detailAction === 'focus') {
      focusTaskCard(task.task_id, runIdForTask(task));
    } else if (detailAction === 'process' && typeof workspaceApi.resumePersistedFileTask === 'function') {
      if (focusTaskCard(task.task_id, runIdForTask(task))) return;
      const syncPromise = workspaceApi.resumePersistedFileTask({
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
  projectWorkbenchBeforeInlineTaskCard(state, taskId);
  scheduleWorkbenchRefresh(state, taskId);
}

function projectWorkbenchBeforeInlineTaskCard(state: WorkbenchState, taskId?: any): void {
  const id = String(taskId || state.activeTaskId || '').trim();
  if (!id || !state.host) return;
  const card = Array.from(document.querySelectorAll('#wa-ai-messages .wa-task-run'))
    .find((node) => (node as HTMLElement).dataset.taskId === id) as HTMLElement | undefined;
  if (!card || card.classList.contains('is-history-snapshot')) return;
  card.classList.add('is-workbench-projected');
  if (state.host.parentElement === card.parentElement && state.host.nextElementSibling !== card) {
    card.parentElement?.insertBefore(state.host, card);
  }
}

function ready(): void {
  initTaskWorkbench();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', ready, { once: true });
} else {
  ready();
}

publishWorkspaceApi({
  initTaskWorkbench,
  refreshCurrentTaskFlow,
  notifyTaskFlowChanged,
  openTaskWorkbenchForCurrentRun,
});
