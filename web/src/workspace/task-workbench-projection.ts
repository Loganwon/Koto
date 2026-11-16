import {
  TASK_REPORT_STAGE_DONE_TEXT,
  taskReportCompactText as compactText,
  taskReportStageFromStep as stageFromStep,
  taskReportUniqueTexts as uniqueTexts,
} from './task-report-layout';
import {
  fileTaskStatusLabel,
  isFileTaskFailureStatus,
  normalizeFileTaskTerminalStatus,
} from './file-task-status';

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

const PRESET_LABELS: Record<string, string> = {
  proactive_agent_tick: '后台巡检',
  startup_runtime_health: '启动检查',
  startup_health: '启动检查',
};

const TASK_TYPE_LABELS: Record<string, string> = {
  file_task: '文件任务',
  proactive_tick: '后台巡检',
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

export const TOOL_LABELS: Record<string, string> = {
  parse_file_to_text: '读取文件',
  read_file: '读取文件',
  open_file: '打开文件',
  read_file_range: '读取文本',
  write_file: '写入文件',
  create_file: '创建文件',
  write_docx_content: '写入文档',
  write_sheet_data: '写入表格',
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
  /后端关键词路由兜底/,
  /planner_policy/i,
  /planner_backend/i,
];

const TITLE_KEYS = ['query', 'task', 'user_input', 'prompt', 'text', 'title', 'instruction'];
const SUMMARY_KEYS = ['summary', 'message', 'error', 'observation', 'result_summary', 'result', 'preview'];
const WORKBENCH_STAGE_BY_STEP_ID: Record<string, string> = {
  'task.classified': 'route',
};

export function esc(text: any): string {
  return String(text || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

export function attr(text: any): string {
  return esc(text).replace(/"/g, '&quot;');
}

function isInternalProgressText(text: any): boolean {
  const value = String(text || '').trim();
  return !!value && INTERNAL_PROGRESS_PATTERNS.some((pattern) => pattern.test(value));
}

function friendlyFileName(value: any): string {
  return basename(String(value || '').trim().replace(/[。；;，,]+$/g, ''));
}

export function userFacingTaskText(value: any, stageId?: string): string {
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
  if (/^识别[:：]|置信度|write_required|write_authorized|summary_request/.test(text)) {
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
  if (stageId === 'check' && text.length > 80) return TASK_REPORT_STAGE_DONE_TEXT.check;
  if (stageId === 'execute' && text.length > 90) return TASK_REPORT_STAGE_DONE_TEXT.execute;
  return compactText(text, stageId === 'execute' ? 120 : 110);
}

export function workbenchStageFromStep(step: any, fallbackStage = ''): string {
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

export function readableJsonishText(value: any, limit: number, options?: { includePreset?: boolean }): string {
  const text = String(value || '').trim();
  if (!text) return '';
  const parsed = safeJsonObject(text);
  if (parsed) {
    const payloadText = firstPayloadText(parsed);
    if (payloadText) return compactText(payloadText, limit);
    const preset = payloadPresetKey(parsed);
    if (preset && options && options.includePreset) return PRESET_LABELS[preset] || '后台任务';
    return '';
  }
  if (text[0] === '[' || text[0] === '{') return '';
  return compactText(text, limit);
}

export function normalizeTask(raw: any): WorkbenchTask {
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

export function statusLabel(status: any): string {
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

export function runIdForTask(task: any): string {
  const metadata = parseMetadata(task);
  return String(metadata.run_id || '').trim();
}

export function basename(path: any): string {
  const value = String(path || '').trim();
  if (!value) return '';
  return value.replace(/\\/g, '/').split('/').filter(Boolean).pop() || value;
}

export function taskFiles(task: any): WorkbenchFile[] {
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

export function taskModelLabel(task: any, metadata?: Record<string, any>): string {
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

export function terminalStatus(task: any): string {
  const metadata = parseMetadata(task);
  return normalizeFileTaskTerminalStatus(
    metadata.task_terminal_status || metadata.terminal_status || metadata.status || (task && task.status),
  ) || 'running';
}

export function metadataStepsForTask(task: any): WorkbenchStep[] {
  const metadata = parseMetadata(task);
  const route = taskRouteLabel(task, metadata);
  const model = taskModelLabel(task, metadata) || '自动';
  const status = terminalStatus(task);
  const terminalComplete = status === 'completed';
  const terminalFailed = isFileTaskFailureStatus(status);
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

export function taskTitle(task: any): string {
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

export function taskSummary(task: any): string {
  const summary = readableJsonishText(task && (task.result_summary || task.error), 180, { includePreset: false });
  if (summary) return summary;
  return compactText(firstPayloadText(taskPayload(task), SUMMARY_KEYS), 180);
}

export function taskCompletionSummary(task: any): string {
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

export function taskMetaLine(task: any): string {
  const parts = [timeLabel(task && task.created_at)].filter(Boolean);
  if (task && task.elapsed_seconds > 0.05) parts.push(`${Math.max(1, Math.round(task.elapsed_seconds))} 秒`);
  return parts.join(' · ');
}

export function taskTypeMetaHtml(task: any): string {
  const taskType = readableType(task && task.task_type);
  return taskType ? `<span class="koto-task-type-meta">${esc(taskType)}</span>` : '';
}

export function stepTone(stepType: any): string {
  const value = String(stepType || '').toUpperCase();
  if (value === 'ERROR') return 'error';
  if (value === 'ACTION') return 'action';
  if (value === 'ANSWER') return 'answer';
  return '';
}

export function stepLabel(step: any): string {
  const type = String(step && step.step_type || '').trim().toUpperCase();
  const toolName = String(step && step.tool_name || '').trim();
  const typeLabel = STEP_TYPE_LABELS[type] || '过程';
  const toolLabel = TOOL_LABELS[toolName] || '';
  return [typeLabel, toolLabel].filter(Boolean).join(' · ');
}

export function stepText(step: any): string {
  const text = readableJsonishText(step && (step.content || step.observation || step.message || step.error), 170, { includePreset: false });
  if (text) return text;
  const toolName = String(step && step.tool_name || '').trim();
  return toolName ? `${TOOL_LABELS[toolName] || '工具'}已执行` : '';
}
