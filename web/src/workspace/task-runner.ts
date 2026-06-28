export interface SseParseResult {
  events: Record<string, any>[];
  remainder: string;
}

export interface TaskCardElement extends HTMLElement {
  _waRunCardBehaviorAttached?: boolean;
  _fatalErrorText?: string;
  _taskUiState?: FileTaskUiState;
  _abortFileTaskStream?: () => void;
  _cancelHandler?: () => void;
  _progressRow?: HTMLElement;
  _multiTargetTerminalRow?: HTMLElement;
  _stepResultRow?: HTMLElement;
  _completedChunkRows?: Map<string, HTMLElement>;
  _singletonRows?: Map<string, HTMLElement>;
  _fileRefreshHashes?: Map<string, string>;
}

export interface FileTaskUiState {
  readKeys: Set<string>;
  fileChangeKeys: Set<string>;
  fileRefreshEntries: Map<string, any>;
  streamIssueKeys: Set<string>;
  processedEventKeys: Set<string>;
  lastEventRunId: string;
  lastEventSeq: number;
  fileChanges: any[];
  readSummaries: Map<string, any>;
  modelSummaryRows: Map<string, HTMLElement>;
  modelSummary: ModelSummaryState;
  codeSummaryRows: Map<string, HTMLElement>;
  uiProgress: number;
  progressExplicit: boolean;
  plannedStepCount: number;
  lastActivityAt: number;
  heartbeatTimer: number | null;
  multiTargetActive: boolean;
  domHydrated: boolean;
  streamIssueRow?: HTMLElement;
}

export interface ModelSummaryState {
  rounds: Set<number>;
  startedRounds: Set<number>;
  toolCalls: number;
  contentChars: number;
  latestRound: number;
  mode: string;
  failed: boolean;
}

export interface TerminalResult {
  summary: string;
  status: string;
  task_id: string;
  run_id: string;
  loadingEl: TaskCardElement | null;
  terminal_status: string;
  completed_task: boolean;
}

export interface StreamFileTaskOptions {
  payload?: Record<string, any>;
  msgs?: HTMLElement | null;
  loadingEl?: HTMLElement | null;
  signal?: AbortSignal;
  abortController?: AbortController;
  onTaskCardSnapshot?: (card: TaskCardElement) => void;
}

export interface ResumeFileTaskOptions {
  taskId?: string;
  task_id?: string;
  runId?: string;
  run_id?: string;
  msgs?: HTMLElement | null;
  loadingEl?: HTMLElement | null;
  taskCardSnapshot?: Record<string, any>;
  initialStatus?: string;
  status?: string;
  onTaskCardSnapshot?: (card: TaskCardElement) => void;
  replay?: boolean;
  taskPayload?: Record<string, any>;
  actionLabel?: string;
}

export interface TaskContract {
  contract_id?: string;
  requested_operation?: string;
  target_path?: string;
  target_file_type?: string;
  write_required?: boolean;
  acceptance_criteria?: string[];
  reason_codes?: string[];
  required_capabilities?: string[];
  forbidden_capabilities?: string[];
}

export interface CompactTextOptions {
  text?: (value: string, limit: number) => string;
}

const FILE_TASK_LOG_PREFIX = '[WA fileTask]';
const FILE_TASK_IDLE_NOTICE_MS = 25000;
const FILE_TASK_IDLE_WARN_MS = 60000;
const TaskStatus: Record<string, any> = (window as any).WA?.fileTaskStatus || {};

const TOOL_LABELS: Record<string, string> = {
  selection_context: '读取选区',
  provided_file_context: '读取文件上下文',
  parse_file_to_text: '解析文件文本',
  read_sheet_data: '读取表格数据',
  read_docx_content: '读取 Word 内容',
  insert_excel_as_docx_table: '插入 Excel 表格',
  insert_image_into_docx: '插入 Word 图片',
  write_docx_content: '写入 Word 内容',
  write_sheet_data: '写入 Excel 单元格',
  design_pptx_theme_layout: '设计 PPT 主题版式',
  write_pptx_slides: '更新 PPT 页面',
  convert_pptx_picture_slides_to_textboxes: '图片页转可编辑文本',
  add_pptx_slides: '新增 PPT 页面',
  run_python_code: '运行 Python',
  read_file_range: '读取文本片段',
  replace_file_selection: '替换文本选区',
  create_file: '创建文件',
  copy_file: '复制文件',
  compare_files: '对比文件',
  extract_to_file: '提取到文件',
  annotate_file: '添加批注',
  list_conversions: '查询可转换格式',
  convert_file: '格式转换',
  list_workspace_files: '列出文件',
  open_file_in_editor: '打开文件',
  verify_task_completion: '核验结果',
  model_message: '模型说明',
  write_guard: '继续写入',
  supervisor_guard: '监管纠偏',
  plan_gate: '计划监管',
};

const INTERNAL_TOOL_NAMES = new Set([
  'selection_context', 'provided_file_context', 'parse_file_to_text',
  'model_message', 'answer_guard', 'readonly_answer_guard', 'repair_guard',
  'duplicate_guard', 'supervisor_guard', 'write_guard', 'plan_gate',
]);

const ALWAYS_SUPPRESS_TOOL_FINISHED_NAMES = new Set([
  'answer_guard', 'readonly_answer_guard', 'repair_guard', 'duplicate_guard',
  'supervisor_guard', 'write_guard', 'plan_gate',
]);

const READ_TOOL_NAMES = new Set([
  'read_sheet_data', 'read_docx_content', 'inspect_workbook_structure', 'audit_financial_workbook',
]);

const PRIMARY_STEP_TITLES: Record<string, string> = {
  route: '任务识别',
  plan: '执行方案',
  context: '读取文件',
  execute: '执行进度',
  check: '完成核验',
  run: '任务状态',
};

const PLAN_VIOLATION_LABELS: Record<string, string> = {
  'write_required_but_plan_not_write': '任务需要写回，但计划没有标记为写入',
  'write_required_but_output_not_write': '任务需要写回，但输出模式不是 write',
  'clear_review_misclassified_as_annotation': '清除批注被误判为新增批注',
  'clear_review_allows_annotate_file': '清除批注任务误选择了 annotate_file 能力',
  'annotation_request_not_classified_as_annotation': '批注任务未被识别为批注流程',
  'read_request_escalated_to_write': '只读任务被错误升级为写入',
};

function planViolationLabel(code: string): string {
  const value = String(code || '').trim();
  if (!value) return '';
  if (PLAN_VIOLATION_LABELS[value]) return PLAN_VIOLATION_LABELS[value];
  return value.replace(/_/g, ' ');
}

function planGateVisibleIssues(data: Record<string, any>): string[] {
  const violations = Array.isArray(data.violations) ? data.violations : [];
  const warnings = Array.isArray(data.warnings) ? data.warnings : [];
  const passed = data.passed !== false && String(data.status || '').trim().toLowerCase() !== 'failed';
  return uniqueTextParts([...violations, ...warnings])
    .filter((item) => !(passed && item === 'model_execution_plan_missing'));
}

function csrfToken(): string {
  const meta = document.querySelector('meta[name="csrf-token"]');
  return meta ? String(meta.getAttribute('content') || '') : '';
}

function headersWithCsrf(headers?: Headers | Record<string, string>): Headers | Record<string, string> {
  const csrf = csrfToken();
  if (!csrf) return headers || {};
  if (headers instanceof Headers) {
    if (!headers.has('X-CSRFToken')) headers.set('X-CSRFToken', csrf);
    return headers;
  }
  const next = Object.assign({}, headers || {});
  if (!next['X-CSRFToken'] && !next['X-CSRF-Token']) next['X-CSRFToken'] = csrf;
  return next;
}

function needsCsrf(method?: string): boolean {
  return !['GET', 'HEAD', 'OPTIONS', 'TRACE'].includes(String(method || 'GET').toUpperCase());
}

async function csrfFetch(url: string, options: RequestInit = {}): Promise<Response> {
  const fetchOptions = Object.assign({}, options);
  if (needsCsrf(fetchOptions.method as string)) {
    fetchOptions.headers = headersWithCsrf(fetchOptions.headers as any) as any;
  }
  return fetch(url, fetchOptions);
}

async function describeHttpError(resp: Response): Promise<string> {
  let detail = '';
  try {
    const data = await resp.clone().json();
    detail = data && (data.error || data.message || data.description || data.detail || '');
  } catch (_) {
    try { detail = await resp.clone().text(); } catch (__) { detail = ''; }
  }
  const suffix = detail ? `: ${String(detail).slice(0, 400)}` : '';
  return `HTTP ${resp.status}${suffix}`;
}

function esc(value: unknown): string {
  return String(value == null ? '' : value)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function escAttr(value: unknown): string {
  return String(value == null ? '' : value)
    .replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/'/g, '&#39;')
    .replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function scrollToBottom(container?: HTMLElement | null): void {
  if (container) container.scrollTop = container.scrollHeight;
}

function eventPayload(evt: Record<string, any>): Record<string, any> {
  return (evt && evt.payload && typeof evt.payload === 'object') ? evt.payload : {};
}

function normalizedTaskLifecyclePayload(payload: any): Record<string, any> {
  const data = payload && typeof payload === 'object' ? payload : {};
  const classification = data.classification && typeof data.classification === 'object' ? data.classification : null;
  if (!classification) return data;
  const normalized = Object.assign({}, classification);
  if (data.intent_plan && typeof data.intent_plan === 'object') normalized.intent_plan = data.intent_plan;
  if (data.runtime && typeof data.runtime === 'object') normalized.runtime = data.runtime;
  if (data.next_action_artifact && typeof data.next_action_artifact === 'object') normalized.next_action_artifact = data.next_action_artifact;
  if (data.artifact_result && typeof data.artifact_result === 'object') normalized.artifact_result = data.artifact_result;
  if (data.followup_record && typeof data.followup_record === 'object') normalized.followup_record = data.followup_record;
  if (data.requirements && typeof data.requirements === 'object') normalized.requirements = data.requirements;
  if (data.plan_check && typeof data.plan_check === 'object') normalized.plan_check = data.plan_check;
  if (data.constraint_audit && typeof data.constraint_audit === 'object') normalized.constraint_audit = data.constraint_audit;
  if (data.workflow_state && typeof data.workflow_state === 'object') normalized.workflow_state = data.workflow_state;
  if (data.supervisor_audit && typeof data.supervisor_audit === 'object') normalized.supervisor_audit = data.supervisor_audit;
  if (data.quick_action_mode) normalized.quick_action_mode = data.quick_action_mode;
  if (data.task_id) normalized.task_id = data.task_id;
  if (data.run_id) normalized.run_id = data.run_id;
  if (data.task) normalized.task = data.task;
  if (data.summary) normalized.summary = data.summary;
  if (data.text || data.error) normalized.text = data.text || data.error;
  if (Object.prototype.hasOwnProperty.call(data, 'completed_task')) normalized.completed_task = data.completed_task;
  return normalized;
}

function makeTaskError(message: string): Error & { waTaskError: boolean } {
  const error = new Error(String(message || '任务失败')) as Error & { waTaskError: boolean };
  error.waTaskError = true;
  return error;
}

function normalizeTaskContractText(value: unknown, limit: number): string {
  const text = String(value || '').trim();
  const max = Number(limit) > 0 ? Number(limit) : 0;
  if (!text) return '';
  if (!max || text.length <= max) return text;
  return text.slice(0, max) + '...';
}

function decodeTaskRequestPayload(encoded: string): Record<string, any> | null {
  const raw = String(encoded || '').trim();
  if (!raw) return null;
  try { return JSON.parse(decodeURIComponent(raw)); } catch { return null; }
}

function boolAttr(value: unknown): boolean {
  return String(value || '').trim().toLowerCase() === 'true';
}

function workflowCheckpointFromOptions(options?: Record<string, any>): Record<string, any> | null {
  const source = options && typeof options === 'object' ? options : {};
  if (source.workflow_checkpoint && typeof source.workflow_checkpoint === 'object') return source.workflow_checkpoint;
  return null;
}

function isTaskCardElement(value: unknown): value is TaskCardElement {
  return !!(value && (value as TaskCardElement).nodeType === 1 && (value as TaskCardElement).classList
    && typeof (value as TaskCardElement).querySelector === 'function'
    && typeof (value as TaskCardElement).querySelectorAll === 'function');
}

function toolLabel(name: string): string { return TOOL_LABELS[name] || name || '工具'; }
function isInternalTool(name: string): boolean { return INTERNAL_TOOL_NAMES.has(name || ''); }
function isReadTool(name: string): boolean { return READ_TOOL_NAMES.has(name || ''); }
function stepTitle(stepId: string, fallback?: string): string { return PRIMARY_STEP_TITLES[stepId] || fallback || '步骤'; }
function toolStepTitle(name: string): string { return '工具:' + toolLabel(name); }

function basename(path: string): string {
  const text = String(path || '').trim();
  if (!text) return '';
  const parts = text.split(/[\\/]+/).filter(Boolean);
  return parts.length ? parts[parts.length - 1] : text;
}

function rowsColsText(payload: Record<string, any>): string {
  const rows = Number(payload.rows_written || 0);
  const cols = Number(payload.columns_written || 0);
  if (rows && cols) return rows + ' 行 x ' + cols + ' 列';
  if (rows) return rows + ' 行';
  if (cols) return cols + ' 列';
  return '';
}

function isReviewChangePayload(payload: any): boolean {
  if (!payload || typeof payload !== 'object') return false;
  return payload.operation === 'annotate_file' || payload.operation === 'annotate' || Number(payload.annotations_added || 0) > 0;
}

function isConfirmEachStepResumePayload(payload: any): boolean {
  const options = payload && typeof payload === 'object' && payload.options && typeof payload.options === 'object' ? payload.options : {};
  const checkpoint = workflowCheckpointFromOptions(options);
  return String(checkpoint && checkpoint.policy || '').trim().toLowerCase() === 'confirm_each_step';
}

function previewText(value: string, limit: number): string {
  const text = String(value || '').trim();
  const max = Number(limit) > 0 ? Number(limit) : 0;
  if (!max || text.length <= max) return text;
  return text.slice(0, max) + '...';
}

function looksLikeFullAnswerText(value: string): boolean {
  const text = String(value || '').trim();
  if (!text) return false;
  if (text.length > 260) return true;
  return /(^|\n)\s*#{1,6}\s|\*\*|```|(^|\n)\s*[-*]\s+\S/u.test(text);
}

function compactFlowSummary(value: string, fallback = '完整结果见对话汇报。'): string {
  const text = String(value || '').trim();
  if (!text) return fallback;
  if (looksLikeFullAnswerText(text)) return fallback;
  return previewText(text.replace(/\s+/g, ' '), 160);
}

function renderTaskFinalReport(value: string): string {
  const text = String(value || '').trim();
  if (!text) return '';
  const renderer = (window as any)._waRenderMarkdown;
  if (typeof renderer === 'function') {
    try { return renderer(text); } catch { /* noop */ }
  }
  if ((window as any).marked) {
    try {
      const sanitizer = (window as any)._sanitizeRenderedHtml;
      const html = (window as any).marked.parse(text);
      return typeof sanitizer === 'function' ? sanitizer(html) : html;
    } catch { /* noop */ }
  }
  return esc(text).replace(/\n/g, '<br>');
}

function tryParseJson(value: string): any {
  const text = String(value || '').trim();
  if (!text || !'[{'.includes(text[0])) return null;
  try { return JSON.parse(text); } catch { return null; }
}

function readableResultItem(value: any): string {
  if (value == null) return '';
  if (typeof value === 'string') return basename(value) || value;
  if (typeof value !== 'object') return String(value);
  const raw = value.name || value.title || value.path || value.file || value.file_path || value.target_path || value.id || '';
  return basename(String(raw || '').trim()) || String(raw || '').trim();
}

function summarizeParsedResult(toolName: string, parsed: any): string {
  if (Array.isArray(parsed)) {
    const names = parsed.map(readableResultItem).filter(Boolean).slice(0, 3);
    const countText = toolName === 'list_workspace_files'
      ? '读取到 ' + parsed.length + ' 个工作区条目'
      : '返回 ' + parsed.length + ' 项结果';
    return names.length ? countText + '：' + names.join('、') : countText;
  }
  if (parsed && typeof parsed === 'object') {
    const summary = parsed.summary || parsed.message || parsed.result_summary || parsed.preview || parsed.text || '';
    if (summary) return previewText(String(summary), 160);
    const keys = Object.keys(parsed).slice(0, 4);
    if (keys.length) return '返回结果字段：' + keys.join('、');
  }
  return '';
}

function toolPreviewSummary(toolName: string, text: string): string {
  const source = String(text || '').trim();
  if (!source) return '';
  const parsed = tryParseJson(source);
  const parsedSummary = summarizeParsedResult(toolName, parsed);
  if (parsedSummary) return parsedSummary;
  const compact = source.replace(/\s+/g, ' ').trim();
  if (!compact) return '';
  return previewText(compact, 180);
}

function collapsibleBlock(label: string, content: string): string {
  const text = String(content || '').trim();
  if (!text) return '';
  return '<details class="wa-task-collapse" data-full-content="' + escAttr(text) + '"><summary>' + esc(label) + '</summary></details>';
}

function artifactSrc(artifact: Record<string, any>): string {
  if (!artifact || typeof artifact !== 'object') return '';
  const raw = String(artifact.data || artifact.src || artifact.url || '').trim();
  if (!raw) return '';
  if (raw.startsWith('data:') || raw.startsWith('http://') || raw.startsWith('https://') || raw.startsWith('/')) return raw;
  const mime = String(artifact.mime_type || 'image/png').trim() || 'image/png';
  return 'data:' + mime + ';base64,' + raw;
}

function appendToolArtifacts(row: HTMLElement, payload: Record<string, any>): void {
  const artifacts = Array.isArray(payload.artifacts) ? payload.artifacts : [];
  if (!row || !artifacts.length) return;
  const host = document.createElement('div');
  host.className = 'wa-task-artifacts';
  artifacts.forEach((artifact: Record<string, any>) => {
    if (artifact && artifact.kind && artifact.kind !== 'image') return;
    const src = artifactSrc(artifact);
    if (!src) return;
    const figure = document.createElement('figure');
    figure.className = 'wa-task-artifact';
    const img = document.createElement('img');
    img.className = 'wa-task-artifact-image';
    img.src = src;
    img.alt = String((artifact && artifact.name) || 'artifact');
    img.loading = 'lazy';
    figure.appendChild(img);
    const caption = document.createElement('figcaption');
    caption.className = 'wa-task-artifact-caption';
    const link = document.createElement('a');
    link.className = 'wa-task-artifact-open';
    link.href = src; link.target = '_blank'; link.rel = 'noopener';
    link.textContent = String((artifact && artifact.name) || '查看图像');
    caption.appendChild(link);
    figure.appendChild(caption);
    host.appendChild(figure);
  });
  if (host.childNodes.length) row.appendChild(host);
}

function resultPreviewHtml(payload: Record<string, any>): string {
  const preview = String(payload.result_preview || payload.result_text || payload.result || '').trim();
  if (!preview) return '';
  const toolName = payload.tool_name || '';
  if (toolName === 'run_python_code') return collapsibleBlock(payload.blocked ? '查看拦截原因' : '查看执行输出', preview);
  if (toolName === 'provided_file_context' || toolName === 'selection_context') return '';
  if (toolName === 'parse_file_to_text' && payload.success !== false) return '';
  if (looksLikeFullAnswerText(preview)) {
    return '<div class="wa-task-result-text">' + esc('结果已生成，完整内容见对话汇报。') + '</div>';
  }
  const summary = toolPreviewSummary(toolName, preview);
  if (!summary) return '';
  const full = preview.length > summary.length || tryParseJson(preview);
  return '<div class="wa-task-result-text">' + esc(summary) + '</div>' + (full ? collapsibleBlock('查看完整结果', preview) : '');
}

function shouldSuppressToolStart(payload: Record<string, any>): boolean {
  const name = payload.tool_name || '';
  return isInternalTool(name) || isReadTool(name);
}

function shouldSuppressToolFinished(payload: Record<string, any>): boolean {
  const name = payload.tool_name || '';
  if (ALWAYS_SUPPRESS_TOOL_FINISHED_NAMES.has(name)) return true;
  if (isInternalTool(name) && payload.success !== false && !payload.blocked) return true;
  if (payload.skipped) return true;
  return false;
}

function parseSseEvents(buffer: string, flush: boolean): SseParseResult {
  const source = String(buffer || '').replace(/\r\n/g, '\n');
  const frames = source.split('\n\n');
  const remainder = flush ? '' : (frames.pop() || '');
  const completeFrames = flush ? frames.filter((f) => f.trim()) : frames;
  const events: Record<string, any>[] = [];
  completeFrames.forEach((frame) => {
    const dataLines = String(frame || '').split('\n').filter((l) => l.startsWith('data:')).map((l) => l.replace(/^data:\s?/, ''));
    if (!dataLines.length) return;
    try { events.push(JSON.parse(dataLines.join('\n'))); } catch { /* noop */ }
  });
  return { events, remainder };
}

function ensureTaskUiState(card: TaskCardElement): FileTaskUiState {
  if (!isTaskCardElement(card)) {
    return {
      readKeys: new Set(), fileChangeKeys: new Set(), fileRefreshEntries: new Map(),
      streamIssueKeys: new Set(), processedEventKeys: new Set(), lastEventRunId: '',
      lastEventSeq: 0, fileChanges: [], readSummaries: new Map(),
      modelSummaryRows: new Map(),
      modelSummary: { rounds: new Set(), startedRounds: new Set(), toolCalls: 0, contentChars: 0, latestRound: 0, mode: '', failed: false },
      codeSummaryRows: new Map(), uiProgress: 0, progressExplicit: false,
      plannedStepCount: 0, lastActivityAt: 0, heartbeatTimer: null, multiTargetActive: false, domHydrated: true,
    };
  }
  if (!card._taskUiState) {
    card._taskUiState = {
      readKeys: new Set(), fileChangeKeys: new Set(), fileRefreshEntries: new Map(),
      streamIssueKeys: new Set(), processedEventKeys: new Set(), lastEventRunId: '',
      lastEventSeq: 0, fileChanges: [], readSummaries: new Map(),
      modelSummaryRows: new Map(),
      modelSummary: { rounds: new Set(), startedRounds: new Set(), toolCalls: 0, contentChars: 0, latestRound: 0, mode: '', failed: false },
      codeSummaryRows: new Map(), uiProgress: 0, progressExplicit: false,
      plannedStepCount: 0, lastActivityAt: 0, heartbeatTimer: null, multiTargetActive: false, domHydrated: false,
    };
  }
  hydrateTaskUiStateFromDom(card, card._taskUiState);
  return card._taskUiState;
}

function hydrateTaskUiStateFromDom(card: TaskCardElement, state: FileTaskUiState): void {
  if (!card || !state || state.domHydrated) return;
  state.domHydrated = true;
  if (!isTaskCardElement(card)) return;
  card.querySelectorAll('.wa-task-step').forEach((step) => {
    step.querySelectorAll('.wa-task-row[data-role]').forEach((row) => {
      const role = String((row as HTMLElement).dataset.role || '').trim();
      if (!role) return;
      if (!(step as any)._singletonRows) (step as any)._singletonRows = new Map();
      (step as any)._singletonRows.set(role, row);
      if (role.startsWith('model:')) state.modelSummaryRows.set(role.replace(/^model:/, ''), row as HTMLElement);
      if (role.startsWith('code:')) state.codeSummaryRows.set(role.replace(/^code:/, ''), row as HTMLElement);
      if (role.startsWith('read:')) state.readSummaries.set(role.replace(/^read:/, ''), { count: 0, signatures: new Set(), row: row as HTMLElement });
      if (role === 'stream-issue') state.streamIssueRow = row as HTMLElement;
    });
  });
}

function setStatus(card: TaskCardElement, text: string): void {
  const el = card.querySelector('[data-role="status"]');
  if (el) el.textContent = text || '';
}

function setStepTitle(step: HTMLElement, title: string): void {
  if (!step || !title) return;
  const titleEl = step.querySelector('.wa-task-step-title');
  if (titleEl) titleEl.textContent = title;
}

function ensureStep(card: TaskCardElement, stepId: string, title: string): HTMLElement {
  const steps = card.querySelector('[data-role="steps"]') as HTMLElement;
  const safeId = String(stepId || 'run');
  let step = Array.from(steps.children).find((n) => (n as HTMLElement).dataset.stepId === safeId) as HTMLElement;
  if (step) {
    setStepTitle(step, title || stepTitle(safeId));
    return step;
  }
  step = document.createElement('div');
  step.className = 'wa-task-step pending';
  step.dataset.stepId = safeId;
  step.innerHTML = '<details class="wa-task-step-detail" open><summary class="wa-task-step-head"><span class="wa-task-step-dot"></span><span class="wa-task-step-title">' + esc(title || safeId) + '</span></summary><div class="wa-task-step-body"></div></details>';
  steps.appendChild(step);
  return step;
}

function markStepRunning(step: HTMLElement): void {
  if (!step) return;
  step.classList.remove('pending', 'done', 'failed');
  step.classList.add('running');
}

function markStepDone(step: HTMLElement): void {
  if (!step) return;
  step.classList.remove('pending', 'running', 'failed');
  step.classList.add('done');
}

function markStepFailed(step: HTMLElement): void {
  if (!step) return;
  step.classList.remove('pending', 'running', 'done');
  step.classList.add('failed');
}

function taskStageStep(card: TaskCardElement, stepId: string): HTMLElement {
  return ensureStep(card, stepId, stepTitle(stepId));
}

function appendRow(step: HTMLElement, kind: string, html: string): HTMLElement {
  const body = step.querySelector('.wa-task-step-body') as HTMLElement;
  const row = document.createElement('div');
  row.className = ('wa-task-row ' + (kind || '')).trim();
  row.innerHTML = html;
  body.appendChild(row);
  return row;
}

function upsertStepSingletonRow(step: HTMLElement, role: string, kind: string, html: string): HTMLElement | null {
  if (!step) return null;
  const key = String(role || 'default').trim() || 'default';
  if (!(step as any)._singletonRows) (step as any)._singletonRows = new Map();
  let row = (step as any)._singletonRows.get(key) as HTMLElement;
  if (!row) { row = appendRow(step, kind, ''); row.dataset.role = key; (step as any)._singletonRows.set(key, row); }
  row.className = ('wa-task-row ' + (kind || '')).trim();
  row.innerHTML = html;
  return row;
}

function upsertMultiTargetTerminalRow(step: HTMLElement, kind: string, html: string): HTMLElement | null {
  if (!step) return null;
  let row = (step as any)._multiTargetTerminalRow as HTMLElement;
  if (!row) { row = appendRow(step, kind, html); row.dataset.role = 'multi-target-terminal'; (step as any)._multiTargetTerminalRow = row; return row; }
  row.className = ('wa-task-row ' + (kind || '')).trim();
  row.innerHTML = html;
  return row;
}

function noteStreamIssue(card: TaskCardElement, key: string, text: string): void {
  if (!card) return;
  const state = ensureTaskUiState(card);
  if (state.streamIssueKeys.has(key)) return;
  state.streamIssueKeys.add(key);
  const step = ensureStep(card, 'run', '任务状态');
  step.classList.remove('pending', 'failed');
  if (!step.classList.contains('running')) step.classList.add('done');
  const message = text || '检测到重复进度事件，已自动合并。';
  if (!state.streamIssueRow) {
    state.streamIssueRow = appendRow(step, 'warn', '');
    state.streamIssueRow.dataset.role = 'stream-issue';
  }
  state.streamIssueRow.innerHTML = '<span class="wa-task-chip warn">提示</span>' + esc(message);
}

function setTaskRunContext(card: TaskCardElement, evt: Record<string, any>, payload: Record<string, any>): void {
  if (!card || !card.dataset) return;
  const eventData = evt || {};
  const data = normalizedTaskLifecyclePayload(payload);
  const taskContract = data.task_contract && typeof data.task_contract === 'object' ? data.task_contract : null;
  const artifactResult = data.artifact_result && typeof data.artifact_result === 'object' ? data.artifact_result : null;
  const taskId = String(eventData.task_id || data.task_id || (artifactResult && artifactResult.task_id) || '').trim();
  const runId = String(eventData.run_id || data.run_id || '').trim();
  if (taskId) card.dataset.taskId = taskId;
  if (runId) card.dataset.taskRunId = runId;
  if (data.task) card.dataset.taskRequest = String(data.task || '').trim();
  if (data.mode) card.dataset.taskMode = String(data.mode || '').trim();
  if (data.summary) card.dataset.taskSummary = compactFlowSummary(String(data.summary || '').trim(), '任务已完成，完整结果见对话汇报。');
  if (data.text || data.error) card.dataset.taskSummary = compactFlowSummary(String(data.text || data.error || '').trim(), '任务已完成，完整结果见对话汇报。');
  if (data.quick_action_mode) card.dataset.taskQuickActionMode = String(data.quick_action_mode || '').trim();
  if (Object.prototype.hasOwnProperty.call(data, 'completed_task')) card.dataset.taskCompleted = data.completed_task ? 'true' : 'false';
  if (data.request_kind) card.dataset.taskRequestKind = String(data.request_kind || '').trim();
  if (data.task_family) card.dataset.taskFamily = String(data.task_family || '').trim();
  if (data.operation_kind) card.dataset.taskOperationKind = String(data.operation_kind || '').trim();
  if (data.execution_mode) card.dataset.taskExecutionMode = String(data.execution_mode || '').trim();
  if (data.selected_recipe) card.dataset.taskSelectedRecipe = String(data.selected_recipe || '').trim();
  if (data.output_mode) card.dataset.taskOutputMode = String(data.output_mode || '').trim();
  if (data.target_file_type) card.dataset.taskTargetFileType = String(data.target_file_type || '').trim();
  if (Object.prototype.hasOwnProperty.call(data, 'confidence')) {
    const c = Number(data.confidence);
    if (Number.isFinite(c) && c >= 0) card.dataset.taskClassificationConfidence = String(c);
  }
  if (Array.isArray(data.reason_codes)) {
    try { card.dataset.taskClassificationReasons = JSON.stringify(data.reason_codes); } catch { delete card.dataset.taskClassificationReasons; }
  }
  const encodedTaskContract = typeof (window as any).WA.encodeTaskContract === 'function' ? (window as any).WA.encodeTaskContract(taskContract) : '';
  if (encodedTaskContract) card.dataset.taskContract = encodedTaskContract; else delete card.dataset.taskContract;
  const intentPlan = data.intent_plan && typeof data.intent_plan === 'object' ? data.intent_plan : {};
  const intentStrategy = String(intentPlan.recommended_strategy || '').trim();
  if (intentStrategy) card.dataset.taskIntentStrategy = intentStrategy; else delete card.dataset.taskIntentStrategy;
  if (Object.prototype.hasOwnProperty.call(intentPlan, 'can_apply')) card.dataset.taskIntentCanApply = intentPlan.can_apply ? 'true' : 'false'; else delete card.dataset.taskIntentCanApply;
  if (Object.prototype.hasOwnProperty.call(intentPlan, 'requires_confirmation')) card.dataset.taskIntentRequiresConfirmation = intentPlan.requires_confirmation ? 'true' : 'false'; else delete card.dataset.taskIntentRequiresConfirmation;
  const runtime = data.runtime && typeof data.runtime === 'object' ? data.runtime : {};
  const terminalStatus = String(runtime.terminal_status || '').trim();
  if (terminalStatus) card.dataset.taskTerminalStatus = terminalStatus;
  const nextActionArtifact = data.next_action_artifact && typeof data.next_action_artifact === 'object' ? data.next_action_artifact : null;
  const resumeRequest = nextActionArtifact && nextActionArtifact.resume_request && typeof nextActionArtifact.resume_request === 'object' ? nextActionArtifact.resume_request : null;
  if (resumeRequest) {
    try {
      card.dataset.taskPendingResumePayload = encodeURIComponent(JSON.stringify(resumeRequest));
      card.dataset.taskPendingResumeLabel = String(nextActionArtifact.action_label || nextActionArtifact.title || '继续执行').trim() || '继续执行';
    } catch { delete card.dataset.taskPendingResumePayload; delete card.dataset.taskPendingResumeLabel; }
  } else {
    const existingResumePayload = decodeTaskRequestPayload(card.dataset.taskPendingResumePayload || '');
    if (!isConfirmEachStepResumePayload(existingResumePayload)) { delete card.dataset.taskPendingResumePayload; delete card.dataset.taskPendingResumeLabel; }
  }
}

function taskTerminalResult(card: TaskCardElement, fallbackSummary?: string): TerminalResult {
  const dataset = card && card.dataset ? card.dataset : {};
  const terminalStatus = String(dataset.taskTerminalStatus || '').trim().toLowerCase();
  const explicitSummary = String(dataset.taskSummary || fallbackSummary || '').trim();
  const fatalSummary = String(card && card._fatalErrorText || '').trim();
  const completedTask = Object.prototype.hasOwnProperty.call(dataset, 'taskCompleted') ? boolAttr(dataset.taskCompleted) : true;
  let status = 'done';
  if (fatalSummary) status = 'error';
  else if (terminalStatus === 'cancelled') status = 'cancelled';
  else if (terminalStatus === 'awaiting_confirmation' || terminalStatus === 'needs_attention' || terminalStatus === 'pending') status = 'pending';
  else if (
    terminalStatus === 'failed'
    || terminalStatus === 'blocked'
    || terminalStatus === 'write_blocked'
    || terminalStatus === 'tool_gap'
    || terminalStatus === 'no_file_change'
    || terminalStatus === 'model_unavailable'
    || terminalStatus === 'quality_gate_failed'
  ) status = 'error';
  else if (!completedTask) status = 'pending';
  return { summary: explicitSummary || fatalSummary || '文件任务流已完成。', status, task_id: String(dataset.taskId || '').trim(), run_id: String(dataset.taskRunId || '').trim(), loadingEl: card || null, terminal_status: terminalStatus, completed_task: completedTask };
}

function terminalStepSummary(result: TerminalResult): string {
  if (!result) return '最终汇报已生成。';
  if (result.status === 'error') return '执行失败，错误信息已写入最终汇报。';
  if (result.status === 'cancelled') return '任务已取消。';
  if (result.status === 'pending') return '任务等待确认。';
  return '最终汇报已生成。';
}

function taskResultActionsHtml(card: TaskCardElement): string {
  const dataset = card && card.dataset ? card.dataset : {};
  const terminal = String(dataset.taskTerminalStatus || '').trim().toLowerCase();
  const pendingResumePayload = String(dataset.taskPendingResumePayload || '').trim();
  const completed = String(dataset.taskCompleted || '').trim().toLowerCase() !== 'false'
    && !['failed', 'blocked', 'write_blocked', 'tool_gap', 'no_file_change', 'model_unavailable', 'quality_gate_failed', 'cancelled'].includes(terminal);
  const request = String(dataset.taskRequest || '').trim();
  const pendingLabel = String(dataset.taskPendingResumeLabel || '').trim();
  const quickActionMode = String(dataset.taskQuickActionMode || '').trim();
  const canApply = String(dataset.taskIntentCanApply || '').trim().toLowerCase() === 'true';
  const requiresConfirmation = String(dataset.taskIntentRequiresConfirmation || '').trim().toLowerCase() === 'true';
  const outputMode = String(dataset.taskOutputMode || '').trim().toLowerCase();
  const waitingForContinuation = terminal === 'awaiting_confirmation'
    || terminal === 'needs_attention'
    || terminal === 'pending'
    || !completed;
  if (pendingResumePayload && terminal === 'awaiting_confirmation' && waitingForContinuation) {
    const actionLabel = pendingLabel || '继续下一步';
    return [
      '<div class="wa-task-actions">',
      '  <span class="wa-task-action-hint">当前步骤已暂停，确认后继续。</span>',
      '  <div class="wa-task-action-buttons">',
      `    <button type="button" class="wa-task-followup-action primary" data-task-artifact-resume="${escAttr(pendingResumePayload)}" data-task-artifact-label="${escAttr(actionLabel)}">${esc(actionLabel)}</button>`,
      '    <button type="button" class="wa-task-followup-action" data-task-followup-action="question">追问计划</button>',
      '  </div>',
      '</div>',
    ].join('');
  }
  let improveText = completed ? '继续优化' : '继续修复';
  let applyActionHtml = '';

  if (quickActionMode === 'answer') {
    improveText = '继续分析';
  } else if (quickActionMode === 'hybrid') {
    if (canApply) {
      improveText = '继续细化方案';
      applyActionHtml = `    <button type="button" class="wa-task-followup-action primary" data-task-followup-action="apply">${esc(requiresConfirmation ? '应用建议' : '应用到文件')}</button>`;
    } else if (outputMode && outputMode !== 'write') {
      improveText = '继续细化';
    }
  } else if (pendingLabel) {
    improveText = pendingLabel;
  }

  return [
    '<div class="wa-task-actions">',
    '  <div class="wa-task-action-buttons">',
    applyActionHtml,
    '    <button type="button" class="wa-task-followup-action" data-task-followup-action="question">追问</button>',
    `    <button type="button" class="wa-task-followup-action" data-task-followup-action="improve" data-task-followup-request="${escAttr(request || '')}">${esc(improveText)}</button>`,
    '  </div>',
    '</div>',
  ].join('');
}

function scheduleTaskLiveProgressCollapse(card: TaskCardElement): void {
  const host = document.getElementById('wa-task-live-progress');
  if (!host) return;
  const terminalStatus = String(card && card.dataset && card.dataset.taskTerminalStatus || '').trim().toLowerCase();
  if (terminalStatus === 'awaiting_confirmation' || terminalStatus === 'needs_attention' || terminalStatus === 'pending') return;
  const currentTimer = (host as any)._waCollapseTimer;
  if (currentTimer) window.clearTimeout(currentTimer);
  (host as any)._waCollapseTimer = window.setTimeout(() => {
    const activeRun = document.querySelector('.wa-task-run.streaming:not([data-history-snapshot="true"])');
    if (!activeRun) host.hidden = true;
  }, 1600);
}

function initializeRecoveredRunCard(card: TaskCardElement, opts: Record<string, any>): TaskCardElement | null {
  const settings = opts && typeof opts === 'object' ? opts : {};
  if (!card) return null;
  card.classList.add('streaming');
  if (card.dataset) {
    if (settings.taskId) card.dataset.taskId = String(settings.taskId || '').trim();
    if (settings.runId) card.dataset.taskRunId = String(settings.runId || '').trim();
    if (settings.initialStatus === 'waiting') card.dataset.taskTerminalStatus = 'awaiting_confirmation';
  }
  const statusEl = card.querySelector('[data-role="status"]');
  if (statusEl) statusEl.textContent = settings.initialStatus === 'waiting' ? '待确认' : '恢复中';
  const summaryEl = card.querySelector('[data-role="summary"]');
  if (summaryEl && !String(summaryEl.textContent || '').trim()) {
    summaryEl.innerHTML = '<div class="wa-task-plan-summary wa-task-outcome">' + esc(settings.initialStatus === 'waiting' ? '已恢复等待确认的后台任务，正在同步最新进度…' : '已恢复后台任务，正在同步最新进度…') + '</div>';
  }
  return card;
}

function markTaskActivity(card: TaskCardElement): void {
  if (!card) return;
  ensureTaskUiState(card).lastActivityAt = Date.now();
}

function startTaskHeartbeat(card: TaskCardElement): void {
  if (!card) return;
  const state = ensureTaskUiState(card);
  if (state.heartbeatTimer) return;
  state.lastActivityAt = Date.now();
  state.heartbeatTimer = window.setInterval(() => {
    if (!card || !card.classList || !card.classList.contains('streaming')) return;
    const s = ensureTaskUiState(card);
    const idleMs = Date.now() - Number(s.lastActivityAt || 0);
    if (idleMs < FILE_TASK_IDLE_NOTICE_MS) return;
    const step = ensureStep(card, 'run', '任务状态');
    step.classList.remove('pending', 'failed');
    step.classList.add('running');
    const secs = Math.max(1, Math.round(idleMs / 1000));
    const warn = idleMs >= FILE_TASK_IDLE_WARN_MS;
    upsertStepSingletonRow(step, 'task-heartbeat', warn ? 'warn' : 'progress', '<span class="wa-task-chip ' + (warn ? 'warn' : '') + '">' + (warn ? '等待中' : '运行中') + '</span>' + esc(warn ? '已经 ' + secs + ' 秒没有收到新进度，任务仍在后台执行；本地模型或大文件处理可能需要更久。' : '任务仍在执行，已等待 ' + secs + ' 秒新进度。'));
    if (warn) setStatus(card, '仍在执行');
  }, 5000);
}

function removeTaskHeartbeatRows(card: TaskCardElement): void {
  if (!card) return;
  const runStep = card.querySelector('[data-role="steps"] .wa-task-step[data-step-id="run"]') as HTMLElement | null;
  if (!runStep) return;
  runStep.querySelectorAll('.wa-task-row[data-role="task-heartbeat"]').forEach((row) => row.remove());
  const rows = runStep.querySelectorAll('.wa-task-row');
  if (!rows.length) runStep.remove();
  const singletonRows = (runStep as any)._singletonRows;
  if (singletonRows && typeof singletonRows.delete === 'function') singletonRows.delete('task-heartbeat');
}

function stopTaskHeartbeat(card: TaskCardElement): void {
  if (!card) return;
  const state = ensureTaskUiState(card);
  if (state.heartbeatTimer) { window.clearInterval(state.heartbeatTimer); state.heartbeatTimer = null; }
  removeTaskHeartbeatRows(card);
}

function attachRunCardBehavior(card: TaskCardElement): TaskCardElement {
  if (!card._waRunCardBehaviorAttached) {
    card.classList.add('is-compact');
    card._waRunCardBehaviorAttached = true;
    card.addEventListener('click', async (event: MouseEvent) => {
      const target = event.target as HTMLElement | null;
      const lazyDetails = target && target.closest ? target.closest('.wa-task-collapse[data-full-content]') as HTMLDetailsElement | null : null;
      if (lazyDetails && !lazyDetails.querySelector('pre')) {
        const text = String(lazyDetails.dataset.fullContent || '').trim();
        if (text) {
          const pre = document.createElement('pre');
          pre.textContent = text;
          lazyDetails.appendChild(pre);
        }
      }

      const taskActionButton = target && target.closest ? target.closest('[data-task-followup-action]') : null;
      if (taskActionButton) {
        const action = taskActionButton.getAttribute('data-task-followup-action') || '';
        if (action && (window as any).WA && typeof (window as any).WA.beginTaskResultFollowup === 'function') {
          const taskState = ensureTaskUiState(card);
          const taskContract = typeof (window as any).WA.decodeTaskContract === 'function'
            ? (window as any).WA.decodeTaskContract(card.dataset.taskContract || '')
            : null;
          const taskPayload = decodeTaskRequestPayload(card.dataset.taskFollowupPayload || '');
          const pendingTaskPayload = decodeTaskRequestPayload(card.dataset.taskPendingResumePayload || '');
          (window as any).WA.beginTaskResultFollowup({
            action,
            task_id: card.dataset.taskId || '',
            run_id: card.dataset.taskRunId || '',
            task: card.dataset.taskRequest || '',
            mode: card.dataset.taskMode || '',
            summary: card.dataset.taskSummary || '',
            terminal_status: card.dataset.taskTerminalStatus || '',
            completed_task: boolAttr(card.dataset.taskCompleted),
            request_kind: card.dataset.taskRequestKind || '',
            task_family: card.dataset.taskFamily || '',
            operation_kind: card.dataset.taskOperationKind || '',
            execution_mode: card.dataset.taskExecutionMode || '',
            output_mode: card.dataset.taskOutputMode || '',
            intent_strategy: card.dataset.taskIntentStrategy || '',
            intent_can_apply: boolAttr(card.dataset.taskIntentCanApply),
            intent_requires_confirmation: boolAttr(card.dataset.taskIntentRequiresConfirmation),
            target_file_type: card.dataset.taskTargetFileType || '',
            task_contract: taskContract && typeof taskContract === 'object' ? taskContract : null,
            task_context: taskPayload && typeof taskPayload === 'object' ? taskPayload.task_context : null,
            taskPayload,
            pendingTaskPayload,
            file_changes: Array.isArray(taskState.fileChanges) ? taskState.fileChanges.slice(-8) : [],
          });
        }
        return;
      }

      const resumeButton = target && target.closest ? target.closest('[data-task-artifact-resume]') : null;
      if (resumeButton) {
        const encodedPayload = resumeButton.getAttribute('data-task-artifact-resume') || '';
        const actionLabel = resumeButton.getAttribute('data-task-artifact-label') || resumeButton.textContent || '';
        if (!encodedPayload || !(window as any).WA || typeof (window as any).WA.resumeTaskArtifact !== 'function') return;
        try {
          const taskPayload = JSON.parse(decodeURIComponent(encodedPayload));
          const taskId = String(taskPayload && taskPayload.task_id || card.dataset.taskId || '').trim();
          if (taskId && typeof (window as any).WA.resumePersistedTaskArtifact === 'function') {
            Promise.resolve((window as any).WA.resumePersistedTaskArtifact({
              taskId,
              taskPayload,
              actionLabel,
              loadingEl: card,
            })).catch((error: any) => console.warn(FILE_TASK_LOG_PREFIX + ' persisted task resume failed:', error));
          } else {
            (window as any).WA.resumeTaskArtifact({ taskPayload, actionLabel });
          }
        } catch (error) {
          console.warn(FILE_TASK_LOG_PREFIX + ' task artifact resume parse failed:', error);
        }
        return;
      }

      const cancelBtn = target && target.closest ? target.closest('[data-role="cancel"]') : null;
      if (cancelBtn) {
        if ((cancelBtn as HTMLElement).dataset.action === 'close') {
          const msg = card.closest('.wa-msg');
          if (msg) msg.remove();
          return;
        }
        cancelFileTaskRun(card);
      }
    });
  }
  return card;
}

function makeRunCard(loadingEl?: TaskCardElement | null): TaskCardElement {
  const card = isTaskCardElement(loadingEl) ? loadingEl : document.createElement('div') as TaskCardElement;
  card.className = 'wa-msg ai wa-task-run is-compact';
  card._fatalErrorText = '';
  card.innerHTML = '<div class="wa-task-header"><div class="wa-task-title-wrap"><div class="wa-task-title">文件任务</div><div class="wa-task-progress" data-role="ui-progress" data-status="running"><div class="wa-task-progress-meta"><span data-role="ui-phase">执行任务</span><span data-role="ui-progress-value">准备识别任务</span></div><div class="wa-task-progress-track"><i data-role="ui-progress-fill"></i></div></div></div><div class="wa-task-status" data-role="status">处理中</div><button type="button" class="wa-task-cancel-btn" data-role="cancel" title="取消任务">取消</button></div><details class="wa-task-process" data-role="process" open><summary><span data-role="process-title">执行过程</span><span data-role="process-state">进行中</span></summary><div class="wa-task-plan" data-role="plan"></div><div class="wa-task-steps" data-role="steps"></div></details><div class="wa-task-summary" data-role="summary"></div>';
  const attached = attachRunCardBehavior(card);
  syncTaskLiveProgress(attached);
  return attached;
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
  host.innerHTML = '<div class="wa-task-live-top"><span class="wa-task-live-title">文件任务</span><span class="wa-task-live-status" data-role="live-status">处理中</span></div><div class="wa-task-live-meta"><span data-role="live-phase">执行任务</span><span data-role="live-plan" style="display:none"></span><span data-role="live-progress-value">准备识别任务</span></div><div class="wa-task-live-track"><i data-role="live-progress-fill"></i></div>';
  msgs.parentNode.insertBefore(host, msgs.nextSibling);
  return host;
}

function taskPlanProgress(card: TaskCardElement): { total: number; completed: number; running: boolean } {
  const state = ensureTaskUiState(card);
  const planned = Number(state.plannedStepCount || 0);
  const runtimeSteps = isTaskCardElement(card) ? Array.from(card.querySelectorAll('.wa-task-step')).filter((s) => !String((s as HTMLElement).dataset.stepId || '').startsWith('task-heartbeat')) : [];
  const total = Math.max(planned, runtimeSteps.length);
  const completed = runtimeSteps.filter((s) => s.classList.contains('done')).length;
  const running = runtimeSteps.some((s) => s.classList.contains('running'));
  return { total, completed: total ? Math.min(completed, total) : 0, running };
}

function syncTaskLiveProgress(card: TaskCardElement): void {
  if (!isTaskCardElement(card)) return;
  const host = ensureTaskLiveProgressHost();
  if (!host) return;
  const state = ensureTaskUiState(card);
  const statusEl = card.querySelector('[data-role="status"]');
  const phaseEl = card.querySelector('[data-role="ui-phase"]');
  const progressEl = card.querySelector('[data-role="ui-progress"]');
  const valueEl = card.querySelector('[data-role="ui-progress-value"]');
  const fillEl = card.querySelector('[data-role="ui-progress-fill"]');
  const statusRaw = String(statusEl && (statusEl as HTMLElement).dataset ? (statusEl as HTMLElement).dataset.status || (progressEl && (progressEl as HTMLElement).dataset ? (progressEl as HTMLElement).dataset.status || '' : '') : '').trim().toLowerCase() || 'running';
  const explicit = state.progressExplicit === true || String(progressEl && (progressEl as HTMLElement).dataset ? (progressEl as HTMLElement).dataset.explicit || '' : '').trim().toLowerCase() === 'true';
  const plan = taskPlanProgress(card);
  const terminal = ['failed', 'succeeded', 'success', 'cancelled', 'waiting', 'awaiting_confirmation'].includes(statusRaw) || String(card.dataset.taskTerminalStatus || '').trim() !== '';
  const basis = explicit ? 'explicit' : (plan.total ? 'planned' : 'estimated');
  let percent = Number(state.uiProgress || 0);
  let valueText = valueEl ? String(valueEl.textContent || '').trim() : '';
  if (!explicit && plan.total) { percent = terminal && !plan.completed ? 100 : Math.round((plan.completed / plan.total) * 100); valueText = '步骤 ' + plan.completed + '/' + plan.total; }
  else if (!explicit) valueText = plan.running ? '执行中' : (valueText && valueText !== '准备中' ? valueText : '准备识别任务');
  if (terminal && explicit) percent = Math.max(percent, statusRaw === 'failed' ? percent : 100);
  percent = Math.max(0, Math.min(100, Math.round(percent)));
  if (progressEl) (progressEl as HTMLElement).dataset.basis = basis;
  if (!explicit && valueEl) valueEl.textContent = valueText;
  if (!explicit && fillEl) (fillEl as HTMLElement).style.width = percent + '%';
  host.hidden = false;
  host.dataset.status = statusRaw || 'running';
  host.dataset.basis = basis;
  const liveStatus = host.querySelector('[data-role="live-status"]');
  const livePhase = host.querySelector('[data-role="live-phase"]');
  const livePlan = host.querySelector('[data-role="live-plan"]');
  const liveValue = host.querySelector('[data-role="live-progress-value"]');
  const liveFill = host.querySelector('[data-role="live-progress-fill"]') as HTMLElement | null;
  if (liveStatus) liveStatus.textContent = statusEl ? String(statusEl.textContent || '').trim() || '处理中' : '处理中';
  if (livePhase) livePhase.textContent = phaseEl ? String(phaseEl.textContent || '').trim() || '执行任务' : '执行任务';
  if (livePlan) { livePlan.textContent = plan.total ? '规划 ' + plan.completed + '/' + plan.total : '等待规划'; (livePlan as HTMLElement).style.display = plan.total ? '' : 'none'; }
  if (liveValue) liveValue.textContent = explicit ? percent + '%' : valueText;
  if (liveFill) liveFill.style.width = percent + '%';
}

function notifyTaskWorkbenchForCard(card: TaskCardElement, options?: { delayed?: boolean }): void {
  if (!isTaskCardElement(card)) return;
  if ((window as any).WA && typeof (window as any).WA.notifyTaskFlowChanged === 'function') {
    const taskId = card.dataset.taskId || '';
    (window as any).WA.notifyTaskFlowChanged(taskId);
    if (options && options.delayed) {
      window.setTimeout(() => (window as any).WA.notifyTaskFlowChanged(taskId), 1200);
      window.setTimeout(() => (window as any).WA.notifyTaskFlowChanged(taskId), 3000);
    }
  }
}

function revealTaskWorkbenchForCard(card: TaskCardElement, options?: { scroll?: boolean }): void {
  if (!isTaskCardElement(card)) return;
  const WA = (window as any).WA;
  if (!WA) return;
  const taskId = String(card.dataset.taskId || '').trim();
  if (typeof WA.openTaskWorkbenchForCurrentRun === 'function') {
    WA.openTaskWorkbenchForCurrentRun({ taskId, scroll: options && options.scroll });
  }
}

function routeLabel(route: string): string {
  const value = String(route || '').trim();
  if (value === 'file_task') return '文件任务';
  if (value === 'web_search') return '联网搜索';
  if (value === 'light_chat') return '普通对话';
  if (value === 'open_file') return '打开文件';
  return value || '自动判断';
}

function classificationValueLabel(kind: string, value: unknown): string {
  const normalized = String(value || '').trim().toLowerCase();
  if (!normalized) return '';
  if (kind === 'family') {
    if (normalized === 'annotate') return '批注';
    if (normalized === 'transform') return '修改';
    if (normalized === 'analyze') return '分析';
    if (normalized === 'compare') return '对比';
    if (normalized === 'automation') return '自动处理';
    return normalized;
  }
  if (kind === 'operation') {
    if (normalized === 'annotate') return '批注';
    if (normalized === 'write') return '写入';
    if (normalized === 'read') return '读取';
    if (normalized === 'compare') return '对比';
    if (normalized === 'compute') return '计算';
    return normalized;
  }
  if (kind === 'output') {
    if (normalized === 'answer') return '只给答案';
    if (normalized === 'write') return '写入文件';
    if (normalized === 'hybrid') return '先分析后决定';
    return normalized;
  }
  return normalized;
}

function uniqueTextParts(items: unknown[]): string[] {
  const seen = new Set<string>();
  return (Array.isArray(items) ? items : [])
    .map((item) => String(item || '').replace(/\s+/g, ' ').trim())
    .filter((item) => {
      if (!item || seen.has(item)) return false;
      seen.add(item);
      return true;
    });
}

function taskRecognitionText(data: Record<string, any>): string {
  const family = classificationValueLabel('family', data.task_family || data.taskFamily || '');
  const operation = classificationValueLabel('operation', data.operation_kind || data.operationKind || '');
  const output = classificationValueLabel('output', data.output_mode || data.outputMode || '');
  const fileCount = Number(data.file_count || data.fileCount || 0);
  const writeIntent = data.write_intent === true || String(data.output_mode || data.outputMode || '').trim().toLowerCase() === 'write';
  const taskLabel = [family, operation].filter(Boolean).join(' · ');
  return uniqueTextParts([
    taskLabel,
    fileCount > 0 ? `${fileCount} 个文件` : '',
    output,
    writeIntent ? '允许写入' : '不写入文件',
  ]).join(' · ');
}

function planCheckSummaryText(data: Record<string, any>, passed: boolean): string {
  const requirements = data.requirements && typeof data.requirements === 'object' ? data.requirements : {};
  const audit = data.constraint_audit && typeof data.constraint_audit === 'object' ? data.constraint_audit : {};
  if (!passed) return String(data.summary || '计划与任务要求不匹配。').replace(/^规划检查(?:通过|未通过)?[：:]?\s*/u, '').trim() || '计划与任务要求不匹配。';
  if (Array.isArray(audit.conflicts) && audit.conflicts.length) return '发现任务边界冲突，已阻止继续执行。';
  if (requirements.write_required === true) return '计划检查通过：本轮允许写入，完成后必须核验文件变更。';
  return '计划检查通过：本轮只读，不会修改文件。';
}

function supervisorAuditFromPayload(data: Record<string, any>): Record<string, any> | null {
  if (data.supervisor_audit && typeof data.supervisor_audit === 'object') return data.supervisor_audit;
  const state = data.workflow_state && typeof data.workflow_state === 'object' ? data.workflow_state : {};
  return state.supervisor_audit && typeof state.supervisor_audit === 'object' ? state.supervisor_audit : null;
}

function supervisorAuditStatusLabel(status: unknown): string {
  const value = String(status || '').trim().toLowerCase();
  if (value === 'blocked') return '已阻止';
  if (value === 'warning') return '需关注';
  if (value === 'clear') return '通过';
  return value || '检查';
}

function supervisorAuditHtml(data: Record<string, any>): string {
  const audit = supervisorAuditFromPayload(data);
  if (!audit) return '';
  const status = String(audit.status || '').trim().toLowerCase();
  const chipClass = status === 'blocked' || status === 'warning' ? 'warn' : 'success';
  const summary = String(audit.summary || '').trim();
  const warnings = Array.isArray(audit.warnings) ? audit.warnings.map((item: any) => String(item || '').trim()).filter(Boolean).slice(0, 4) : [];
  const actions = Array.isArray(audit.required_actions) ? audit.required_actions.map((item: any) => String(item || '').trim()).filter(Boolean).slice(0, 3) : [];
  const confidence = Number(audit.confidence);
  const meta = [
    Number.isFinite(confidence) && confidence >= 0 && confidence <= 1 ? `置信度 ${Math.round(confidence * 100)}%` : '',
    audit.risk_level ? `风险 ${audit.risk_level}` : '',
  ].filter(Boolean);
  const details = uniqueTextParts([...warnings, ...actions.map((item) => `要求：${item}`)]);
  return '<div class="wa-task-result-text"><span class="wa-task-chip ' + chipClass + '">监管' + esc(supervisorAuditStatusLabel(status)) + '</span>'
    + esc(summary)
    + '</div>'
    + (meta.length ? '<div class="wa-task-meta">' + meta.map((item) => '<span class="wa-task-meta-item">' + esc(item) + '</span>').join('') + '</div>' : '')
    + (details.length ? '<ul class="wa-task-plan-violations">' + details.map((item) => '<li>' + esc(item) + '</li>').join('') + '</ul>' : '');
}

function modelLabel(mode: string, modelId?: string): string {
  const normalized = String(mode || '').trim().toLowerCase();
  const id = String(modelId || '').trim();
  if (normalized === 'local') return id ? `本地 ${id}` : '本地模型';
  if (normalized === 'deepseek') return id ? `DeepSeek ${id}` : 'DeepSeek';
  if (normalized === 'cloud') return 'DeepSeek';
  return id || normalized || '自动';
}

function seedRouteModelContext(card: TaskCardElement, payload: Record<string, any>): void {
  if (!isTaskCardElement(card) || !payload || typeof payload !== 'object') return;
  if (payload.task && !card.dataset.taskRequest) card.dataset.taskRequest = String(payload.task || '').trim();
  const options = payload.options && typeof payload.options === 'object' ? payload.options : {};
  const routeIntent = options.workspace_route_intent && typeof options.workspace_route_intent === 'object'
    ? options.workspace_route_intent
    : null;
  const route = String(routeIntent && routeIntent.route || '').trim();
  const mode = String(payload.model_mode || '').trim();
  const model = modelLabel(mode, payload.model_id);
  const step = taskStageStep(card, 'route');
  markStepRunning(step);
  const routeText = `路由：${routeLabel(route)} · 模型：${model}`;
  const reason = String(routeIntent && (routeIntent.reason || routeIntent.summary || '') || '').trim();
  const content = '<span class="wa-task-chip">模型调用</span>' + esc(reason ? `${routeText} · ${reason}` : routeText);
  const row = upsertStepSingletonRow(step, 'model:route', 'model-summary', content);
  if (row) ensureTaskUiState(card).modelSummaryRows.set('route', row);
  syncTaskLiveProgress(card);
  notifyTaskWorkbenchForCard(card);
}

function planStepsFromPayload(data: Record<string, any>): any[] {
  const candidates = [
    data.steps,
    data.dynamic_steps,
    data.plan,
    data.execution_plan && data.execution_plan.steps,
    data.intent_plan && data.intent_plan.dynamic_steps,
  ];
  for (const candidate of candidates) {
    if (Array.isArray(candidate) && candidate.length) return candidate;
  }
  return [];
}

function planSummaryFromPayload(data: Record<string, any>): string {
  return String(
    data.plan_summary
    || data.summary
    || data.goal
    || (data.execution_plan && (data.execution_plan.plan_summary || data.execution_plan.goal))
    || '已生成执行方案'
    || '',
  ).trim();
}

function renderPlanStepItem(item: any, index: number): string {
  if (item && typeof item === 'object') {
    const title = String(item.title || item.name || item.label || item.stage || `步骤 ${index + 1}`).trim();
    const tool = String(item.tool || item.tool_name || '').trim();
    const why = String(item.why || item.reason || item.description || item.detail || '').trim();
    const meta = [tool ? `工具：${tool}` : '', why].filter(Boolean).join(' · ');
    return `<li><strong>${esc(title)}</strong>${meta ? `<span>${esc(meta)}</span>` : ''}</li>`;
  }
  return `<li><strong>${esc(String(item || `步骤 ${index + 1}`))}</strong></li>`;
}

function renderPlanIntoCard(card: TaskCardElement, data: Record<string, any>): void {
  const steps = planStepsFromPayload(data);
  const summary = planSummaryFromPayload(data);
  const planEl = card.querySelector('[data-role="plan"]') as HTMLElement;
  if (planEl) {
    planEl.innerHTML = '<div class="wa-task-plan-summary">' + esc(summary) + '</div>';
    planEl.hidden = false;
  }
  if (steps.length) ensureTaskUiState(card).plannedStepCount = steps.length;
}

function terminalStepCompactText(card: TaskCardElement, stepId: string, title: string, result: TerminalResult): string {
  if (result && result.status === 'error') {
    if (stepId === 'check') return '已记录失败原因，详见底部答复。';
    if (stepId === 'execute') return '执行未完成，已停止继续处理。';
  }
  if (result && result.status === 'pending') {
    if (stepId === 'check') return '等待用户确认后继续。';
    return '已暂停，等待下一步确认。';
  }
  if (stepId === 'route') return '已识别任务目标和文件上下文。';
  if (stepId === 'plan') return '已确认执行方案和约束。';
  if (stepId === 'context') return '已读取并整理必要文件内容。';
  if (stepId === 'execute') {
    const changes = ensureTaskUiState(card).fileChanges || [];
    const names = changes
      .map((change) => basename(String(change && change.path || '').trim()))
      .filter(Boolean)
      .slice(0, 2);
    if (names.length) return `已完成处理：${names.join('、')}。`;
    return '已完成文件处理或分析。';
  }
  if (stepId === 'check') return '已完成核验，答复见底部。';
  return title ? `${title}已完成。` : '已完成。';
}

function compactTerminalProcess(card: TaskCardElement, result: TerminalResult): void {
  if (!isTaskCardElement(card)) return;
  const planEl = card.querySelector('[data-role="plan"]') as HTMLElement | null;
  if (planEl) {
    planEl.querySelectorAll('.wa-task-plan-steps').forEach((node) => node.remove());
  }
  card.querySelectorAll('[data-role="steps"] .wa-task-step[data-step-id="run"]').forEach((node) => node.remove());
  card.querySelectorAll('[data-role="steps"] .wa-task-step').forEach((node) => {
    const step = node as HTMLElement;
    const body = step.querySelector('.wa-task-step-body') as HTMLElement | null;
    if (!body) return;
    const stepId = String(step.dataset.stepId || '').trim();
    const title = String(step.querySelector('.wa-task-step-title')?.textContent || '').trim();
    const failed = step.classList.contains('failed');
    const pending = step.classList.contains('running') || result.status === 'pending';
    const chip = failed ? '异常' : (pending ? '待确认' : '完成');
    const kind = failed ? 'warn' : (pending ? 'progress' : 'success');
    body.innerHTML = '<div class="wa-task-row ' + kind + '" data-role="compact-terminal"><span class="wa-task-chip ' + (failed ? 'warn' : (!pending ? 'success' : '')) + '">' + esc(chip) + '</span>' + esc(terminalStepCompactText(card, stepId, title, result)) + '</div>';
    (step as any)._singletonRows = new Map([['compact-terminal', body.firstElementChild]]);
  });
}

function handleEvent_task_classified(card: TaskCardElement, evt: Record<string, any>, payload: Record<string, any>): void {
  const data = normalizedTaskLifecyclePayload(payload);
  setTaskRunContext(card, evt, payload);
  const step = taskStageStep(card, 'route');
  const recognition = taskRecognitionText(data);
  const confidence = Number(data.confidence);
  const confidenceText = Number.isFinite(confidence) && confidence > 0 ? ` · 置信度 ${Math.round(confidence * 100)}%` : '';
  upsertStepSingletonRow(step, 'task.classified', 'plan', '<span class="wa-task-chip success">识别</span>' + esc((recognition || '已完成任务识别') + confidenceText) + supervisorAuditHtml(data));
  markStepDone(step);
  setStatus(card, '已识别');
  syncTaskLiveProgress(card);
}

function handleEvent_plan(card: TaskCardElement, evt: Record<string, any>, payload: Record<string, any>): void {
  const data = normalizedTaskLifecyclePayload(payload);
  setTaskRunContext(card, evt, payload);
  const step = taskStageStep(card, 'plan');
  renderPlanIntoCard(card, data);
  upsertStepSingletonRow(step, 'plan.created', 'plan', '<span class="wa-task-chip">方案</span>' + esc(planSummaryFromPayload(data)));
  markStepRunning(step);
  syncTaskLiveProgress(card);
}

function handleEvent_plan_summary(card: TaskCardElement, evt: Record<string, any>, payload: Record<string, any>): void {
  card.dataset.taskSummary = String(payload.summary || evt.text || '').trim();
  const planEl = card.querySelector('[data-role="plan"]') as HTMLElement;
  if (planEl) {
    const summaryEl = planEl.querySelector('.wa-task-plan-summary');
    if (summaryEl) { summaryEl.textContent = (payload && payload.summary) || (evt && evt.text) || ''; }
  }
}

function handleEvent_plan_checked(card: TaskCardElement, evt: Record<string, any>, payload: Record<string, any>): void {
  const data = normalizedTaskLifecyclePayload(payload);
  setTaskRunContext(card, evt, payload);
  const step = taskStageStep(card, 'plan');
  const passed = data.passed !== false && String(data.status || '').trim().toLowerCase() !== 'replan';
  const violations = Array.isArray(data.violations) ? data.violations : [];
  const warnings = Array.isArray(data.warnings) ? data.warnings : [];
  const detail = [...violations, ...warnings].slice(0, 5).map((item: any) => planViolationLabel(String(item || '')) || String(item || '')).filter(Boolean).join('；');
  const summary = passed ? planCheckSummaryText(data, true) : (detail || planCheckSummaryText(data, false));
  upsertStepSingletonRow(step, 'plan.checked', passed ? 'success' : 'warn', '<span class="wa-task-chip ' + (passed ? 'success' : 'warn') + '">' + esc(passed ? '监管' : '需调整') + '</span>' + esc(summary) + supervisorAuditHtml(data));
  if (passed) markStepDone(step); else markStepRunning(step);
  syncTaskLiveProgress(card);
}

function planGateIssueHtml(data: Record<string, any>): string {
  const details = planGateVisibleIssues(data)
    .slice(0, 5)
    .map((item) => planViolationLabel(item));
  return details.length
    ? '<ul class="wa-task-plan-violations">' + details.map((item) => '<li>' + esc(item) + '</li>').join('') + '</ul>'
    : '';
}

function handleEvent_plan_gated(card: TaskCardElement, evt: Record<string, any>, payload: Record<string, any>): void {
  const data = normalizedTaskLifecyclePayload(payload);
  setTaskRunContext(card, evt, payload);
  const step = taskStageStep(card, 'plan');
  const passed = data.passed !== false && String(data.status || '').trim().toLowerCase() !== 'failed';
  const summary = String(data.summary || (passed ? '计划监管通过。' : '计划需要调整。')).trim();
  upsertStepSingletonRow(
    step,
    'plan.gated',
    passed ? 'success' : 'warn',
    '<span class="wa-task-chip ' + (passed ? 'success' : 'warn') + '">计划监管</span>' + esc(summary) + planGateIssueHtml(data),
  );
  if (passed) markStepDone(step);
  else markStepRunning(step);
  syncTaskLiveProgress(card);
}

function handleEvent_supervisor_status(card: TaskCardElement, evt: Record<string, any>, payload: Record<string, any>): void {
  const data = normalizedTaskLifecyclePayload(payload);
  setTaskRunContext(card, evt, payload);
  const step = taskStageStep(card, 'plan');
  const stage = String(data.stage || 'supervising').trim();
  const summary = String(data.summary || supervisorAuditFromPayload(data)?.summary || '监管检查已更新。').trim();
  const audit = supervisorAuditFromPayload(data);
  const auditStatus = audit ? ` · 监管${supervisorAuditStatusLabel(audit.status)}` : '';
  upsertStepSingletonRow(step, 'supervisor.status:' + stage, 'plan', '<span class="wa-task-chip success">监管</span>' + esc((stage || '检查') + auditStatus + ' · ' + summary) + supervisorAuditHtml(data));
  markStepRunning(step);
  syncTaskLiveProgress(card);
}

function handleEvent_supervisor_intervention(card: TaskCardElement, evt: Record<string, any>, payload: Record<string, any>): void {
  const data = normalizedTaskLifecyclePayload(payload);
  setTaskRunContext(card, evt, payload);
  const step = taskStageStep(card, 'plan');
  const reason = String(data.reason || '').trim();
  const summary = String(data.summary || data.message || data.text || '监管已纠偏执行方案。').trim();
  upsertStepSingletonRow(
    step,
    'supervisor.intervention:' + (reason || 'default'),
    'warn',
    '<span class="wa-task-chip warn">监管纠偏</span>' + esc(reason ? `${reason} · ${summary}` : summary) + supervisorAuditHtml(data),
  );
  markStepRunning(step);
  syncTaskLiveProgress(card);
}

function handleEvent_supervisor_step_verified(card: TaskCardElement, evt: Record<string, any>, payload: Record<string, any>): void {
  const data = normalizedTaskLifecyclePayload(payload);
  setTaskRunContext(card, evt, payload);
  const step = taskStageStep(card, stepIdFromEvent(evt, data));
  const passed = data.passed !== false && String(data.outcome || data.status || '').trim().toLowerCase() !== 'failed';
  const toolName = String(data.tool_name || '').trim();
  const outcome = String(data.outcome || (passed ? 'verified' : 'failed')).trim();
  const summary = String(data.summary || '').trim();
  const criteria = Array.isArray(data.criteria) ? data.criteria : [];
  const detail = criteria
    .map((item: any) => {
      if (!item || typeof item !== 'object') return '';
      const name = String(item.name || '').trim();
      const ok = item.passed !== false;
      const label = name === 'tool_allowlisted' ? '工具白名单'
        : name === 'tool_call_finished_or_guarded' ? '调用闭环'
          : name === 'write_has_result_evidence' ? '结果证据'
            : name;
      return label ? `${ok ? '通过' : '未通过'}：${label}` : '';
    })
    .filter(Boolean)
    .slice(0, 3)
    .join('；');
  const text = [toolName ? `${toolName} · ${outcome}` : outcome, summary, detail].filter(Boolean).join(' · ');
  upsertStepSingletonRow(
    step,
    'supervisor.step_verified:' + (toolName || String(data.tool_index || 'default')),
    passed ? 'success' : 'warn',
    '<span class="wa-task-chip ' + (passed ? 'success' : 'warn') + '">监管核验</span>' + esc(text || '步骤已完成监管核验。'),
  );
  if (passed && !step.classList.contains('failed')) markStepDone(step);
  else if (!passed) markStepFailed(step);
  markTaskActivity(card);
  syncTaskLiveProgress(card);
}

function handleEvent_decision_made(card: TaskCardElement, evt: Record<string, any>, payload: Record<string, any>): void {
  const data = normalizedTaskLifecyclePayload(payload);
  setTaskRunContext(card, evt, payload);
  const step = taskStageStep(card, 'execute');
  const decision = String(data.decision || data.action || data.status || '').trim();
  const summary = String(data.summary || data.reason || data.message || data.text || '已完成执行决策。').trim();
  upsertStepSingletonRow(
    step,
    'decision.made:' + (decision || 'default'),
    'plan',
    '<span class="wa-task-chip">决策</span>' + esc(decision ? `${decision} · ${summary}` : summary),
  );
  markStepRunning(step);
  syncTaskLiveProgress(card);
}

function handleEvent_workflow_state(card: TaskCardElement, evt: Record<string, any>, payload: Record<string, any>): void {
  const data = normalizedTaskLifecyclePayload(payload);
  setTaskRunContext(card, evt, payload);
  const step = taskStageStep(card, 'plan');
  const state = String(data.state || data.status || data.phase || '').trim();
  const summary = String(data.summary || data.message || data.text || '工作流状态已更新。').trim();
  const windows = Array.isArray(data.large_file_windows) ? data.large_file_windows.length : 0;
  const meta = windows ? ` · ${windows} 个大文件窗口` : '';
  upsertStepSingletonRow(
    step,
    'workflow.state:' + (state || 'default'),
    'plan',
    '<span class="wa-task-chip">工作流</span>' + esc((state ? `${state} · ` : '') + summary + meta),
  );
  markStepRunning(step);
  syncTaskLiveProgress(card);
}

function handleEvent_plan_step_started(card: TaskCardElement, evt: Record<string, any>, payload: Record<string, any>): void {
  const data = normalizedTaskLifecyclePayload(payload);
  const planEl = card.querySelector('[data-role="plan"]') as HTMLElement;
  if (planEl) {
    const listEl = planEl.querySelector('.wa-task-plan-steps');
    if (listEl) {
      const idx = Number(data.step_index || data.step || 0);
      const items = listEl.children;
      if (idx >= 0 && idx < items.length) { items[idx].classList.add('wa-task-plan-step-active'); }
    }
  }
  syncTaskLiveProgress(card);
}

function handleEvent_plan_step_finished(card: TaskCardElement, evt: Record<string, any>, payload: Record<string, any>): void {
  const planEl = card.querySelector('[data-role="plan"]') as HTMLElement;
  if (planEl) {
    const listEl = planEl.querySelector('.wa-task-plan-steps');
    if (listEl) {
      const idx = Number((payload && typeof payload === 'object' ? (payload.step_index || payload.step || 0) : 0));
      const items = listEl.children;
      if (idx >= 0 && idx < items.length) { items[idx].classList.remove('wa-task-plan-step-active'); items[idx].classList.add('wa-task-plan-step-done'); }
    }
  }
  syncTaskLiveProgress(card);
}

function handleEvent_run_started(card: TaskCardElement, evt: Record<string, any>, payload: Record<string, any>): void {
  const data = normalizedTaskLifecyclePayload(payload);
  setTaskRunContext(card, evt, payload);
  card.classList.remove('pending');
  card.classList.add('streaming');
  const step = taskStageStep(card, 'execute');
  markStepRunning(step);
  const summaryRow = upsertStepSingletonRow(step, 'run.started', 'plan', '<span class="wa-task-chip">' + esc(data.mode || '启动') + '</span>' + esc(data.summary || data.text || data.error || '开始执行任务'));
  if (summaryRow) {
    const state = ensureTaskUiState(card);
    state.modelSummaryRows.set('operation', summaryRow);
  }
  setStatus(card, '处理中');
  startTaskHeartbeat(card);
  if (data.tool_use_id) card.dataset.taskToolUseId = String(data.tool_use_id || '').trim();
  syncTaskLiveProgress(card);
}

function handleEvent_run_finished(card: TaskCardElement, evt: Record<string, any>, payload: Record<string, any>): void {
  const data = normalizedTaskLifecyclePayload(payload);
  setTaskRunContext(card, evt, payload);
  stopTaskHeartbeat(card);
  const executeStep = taskStageStep(card, 'execute');
  const planStep = card.querySelector('[data-role="steps"] .wa-task-step[data-step-id="plan"]') as HTMLElement | null;
  if (planStep && !planStep.classList.contains('failed')) markStepDone(planStep);
  const step = taskStageStep(card, 'check');
  const result = taskTerminalResult(card, data.summary || data.text || data.error || '文件任务已完成。');
  if (result.status === 'error') markStepFailed(executeStep);
  else if (result.status === 'pending') markStepRunning(executeStep);
  else markStepDone(executeStep);
  const runStep = card.querySelector('[data-role="steps"] .wa-task-step[data-step-id="run"]') as HTMLElement | null;
  if (runStep) {
    if (result.status === 'error') markStepFailed(runStep);
    else markStepDone(runStep);
  }
  if (result.status === 'cancelled') { markStepDone(step); setStatus(card, '已取消'); }
  else if (result.status === 'error') { markStepFailed(step); setStatus(card, '执行失败'); card.dataset.taskTerminalStatus = result.terminal_status; }
  else if (result.status === 'pending') { markStepRunning(step); setStatus(card, '待确认'); }
  else { markStepDone(step); setStatus(card, '已完成'); }
  const titleEl = card.querySelector('.wa-task-title');
  if (titleEl) {
    if (result.status === 'pending') titleEl.textContent = '等待确认';
    else if (result.status === 'error') titleEl.textContent = '任务未完成';
    else if (result.status === 'cancelled') titleEl.textContent = '任务已取消';
    else titleEl.textContent = '任务完成';
  }
  const summaryRow = upsertStepSingletonRow(step, 'model:operation', result.status === 'error' ? 'warn' : 'success', '<span class="wa-task-chip ' + (result.status === 'error' ? 'warn' : 'success') + '">' + esc(data.mode || '完成') + '</span>' + esc(terminalStepSummary(result)));
  if (summaryRow) {
    const state = ensureTaskUiState(card);
    state.modelSummaryRows.set('operation', summaryRow);
  }
  compactTerminalProcess(card, result);
  card.classList.remove('streaming');
  if (result.status === 'error') card.classList.add('failed');
  else if (result.status === 'cancelled') card.classList.add('cancelled');
  else card.classList.add('done');
  const summaryContainer = card.querySelector('[data-role="summary"]') as HTMLElement;
  if (summaryContainer) {
    const finalReport = String(data.summary || data.text || data.error || result.summary || '').trim();
    const visibleSummary = finalReport || terminalStepSummary(result);
    const auditHtml = supervisorAuditHtml(data);
    summaryContainer.innerHTML = taskResultActionsHtml(card) + auditHtml + '<div class="wa-task-final-report">' + renderTaskFinalReport(visibleSummary) + '</div>';
    summaryContainer.hidden = false;
  }
  const process = card.querySelector('[data-role="process"]') as HTMLDetailsElement | null;
  if (process) {
    process.open = true;
    const title = process.querySelector('[data-role="process-title"]');
    const state = process.querySelector('[data-role="process-state"]');
    if (title) title.textContent = '执行过程';
    if (state) state.textContent = result.status === 'error' ? '未完成' : (result.status === 'pending' ? '待确认' : '已完成');
  }
  const loadedSummary = data.summary || data.text || data.error || '';
  card.dataset.taskSummary = loadedSummary || result.summary || card.dataset.taskSummary || '';
  const cancelBtn = card.querySelector('[data-role="cancel"]');
  if (cancelBtn) { (cancelBtn as HTMLElement).textContent = '关闭'; (cancelBtn as HTMLElement).dataset.action = 'close'; }
  syncTaskLiveProgress(card);
  scheduleTaskLiveProgressCollapse(card);
  notifyTaskWorkbenchForCard(card, { delayed: true });
}

function handleEvent_run_cancelled(card: TaskCardElement, evt: Record<string, any>, payload: Record<string, any>): void {
  card.dataset.taskTerminalStatus = 'cancelled';
  card.dataset.taskCompleted = 'false';
  const cancelBtn = card.querySelector('[data-role="cancel"]');
  if (cancelBtn) { (cancelBtn as HTMLElement).textContent = '关闭'; (cancelBtn as HTMLElement).dataset.action = 'close'; }
  handleEvent_run_finished(card, evt, { ...(payload || {}), text: payload && payload.text ? payload.text : '任务已被取消。' });
}

function handleEvent_tool_started(card: TaskCardElement, evt: Record<string, any>, payload: Record<string, any>): void {
  const data = normalizedTaskLifecyclePayload(payload);
  if (shouldSuppressToolStart(data)) return;
  const step = taskStageStep(card, 'execute');
  markStepRunning(step);
  setStatus(card, '处理中');
  const toolName = data.tool_name || '';
  const toolTitle = data.tool_title || toolName;
  const args = data.tool_args || '';
  const argStr = args ? ' ' + esc(String(args).trim()) : '';
  const content = '<span class="wa-task-chip">' + esc(toolTitle) + '</span>' + esc('准备执行') + argStr;
  const tag = 'tool:' + toolName + ':' + String(data.tool_use_id || data.execution_id || '');
  const row = upsertStepSingletonRow(step, tag, 'tool-start', content);
  markTaskActivity(card);
}

function handleEvent_tool_finished(card: TaskCardElement, evt: Record<string, any>, payload: Record<string, any>): void {
  const data = normalizedTaskLifecyclePayload(payload);
  setTaskRunContext(card, evt, payload);
  if (shouldSuppressToolFinished(data)) return;
  const step = taskStageStep(card, 'execute');
  markStepRunning(step);
  const toolName = data.tool_name || '';
  const toolTitle = data.tool_title || toolName;
  const tag = 'tool:' + toolName + ':' + String(data.tool_use_id || data.execution_id || '');
  const finished = data.success !== false && !data.blocked && !data.skipped;
  const kind = data.blocked || data.tool_name === 'ask_user' ? 'warn' : (finished ? 'tool-finished' : 'tool-error');
  const icon = data.skipped ? '跳过' : (data.blocked ? '阻断' : (finished ? '完成' : '失败'));
  const preview = resultPreviewHtml(data);
  const fallbackText = String(data.error || '').trim();
  const content = '<span class="wa-task-chip ' + (data.blocked ? 'warn' : (finished ? 'success' : '')) + '">' + esc(icon) + ' ' + esc(toolTitle) + '</span>' + (preview || esc(fallbackText));
  if (data.blocked) {
    upsertStepSingletonRow(step, tag, 'warn', content);
    setStatus(card, '待确认');
  } else {
    const row = upsertStepSingletonRow(step, tag, kind, content);
  }
  appendToolArtifacts(step, data);
  markTaskActivity(card);
  syncTaskLiveProgress(card);
}

function handleEvent_file_changed(card: TaskCardElement, evt: Record<string, any>, payload: Record<string, any>): void {
  const data = normalizedTaskLifecyclePayload(payload);
  const step = taskStageStep(card, 'execute');
  markStepRunning(step);
  setStatus(card, '处理中');
  let path = String(data.path || data.file_path || '').trim();
  const changeType = String(data.change_type || 'modified').trim();
  if (!path) return;
  if (data.prefix && !path.includes('/')) { path = data.prefix.replace(/\/+$/, '') + '/' + path; }
  const state = ensureTaskUiState(card);
  const key = changeType + ':' + path;
  if (state.fileChangeKeys.has(key)) return;
  state.fileChangeKeys.add(key);
  state.fileChanges.push({ path, changeType });
  const shortPath = path.split('/').pop() || path;
  const content = '<span class="wa-task-chip success">' + esc(changeType === 'created' ? '创建' : (changeType === 'deleted' ? '删除' : '修改')) + '</span><a class="wa-task-file-link" href="javascript:void(0)" data-file-path="' + escAttr(path) + '">' + esc(shortPath) + '</a>';
  appendRow(step, 'tool-finished', content);
  if (data.supported !== false && data.refresh_supported !== false) {
    window.setTimeout(() => {
      const reload = (window as any).WA && (window as any).WA.reloadFileByPath;
      if (typeof reload !== 'function') return;
      Promise.resolve(reload(path, true)).catch((error) => {
        console.warn('[FileTask] refresh after file.changed failed:', error);
      });
    }, 200);
  }
  markTaskActivity(card);
  syncTaskLiveProgress(card);
}

function handleEvent_read_changed(card: TaskCardElement, evt: Record<string, any>, payload: Record<string, any>): void {
  const data = normalizedTaskLifecyclePayload(payload);
  const step = taskStageStep(card, 'context');
  markStepRunning(step);
  let path = String(data.path || data.file_path || '').trim();
  if (!path) {
    const entry = String(data.entry || '').trim();
    if (entry) { path = entry; }
  }
  if (!path) return;
  const state = ensureTaskUiState(card);
  const key = 'read:' + path;
  if (state.readKeys.has(key)) return;
  state.readKeys.add(key);
  let row = state.readSummaries.get(key);
  if (row) return;
  const shortPath = path.split('/').pop() || path;
  const content = '<span class="wa-task-chip">读取</span><a class="wa-task-file-link" href="javascript:void(0)" data-file-path="' + escAttr(path) + '">' + esc(shortPath) + '</a>';
  const r = appendRow(step, 'tool-start', content);
  r.dataset.role = key;
  state.readSummaries.set(key, { count: 1, signatures: new Set(), row: r });
  markTaskActivity(card);
}

function handleEvent_error(card: TaskCardElement, evt: Record<string, any>, payload: Record<string, any>): void {
  const data = normalizedTaskLifecyclePayload(payload);
  handleEvent_run_finished(card, evt, { ...(payload || {}), text: data.text || data.error || '任务执行出错。' });
  card.dataset.taskTerminalStatus = 'failed';
  card._fatalErrorText = String(data.error || data.text || data.message || payload).trim();
  syncTaskLiveProgress(card);
}

function handleEvent_model_summary(card: TaskCardElement, evt: Record<string, any>, payload: Record<string, any>): void {
  const data = normalizedTaskLifecyclePayload(payload);
  const step = taskStageStep(card, 'execute');
  markStepRunning(step);
  const state = ensureTaskUiState(card);
  const ms = state.modelSummary;
  ms.latestRound = Number(data.round || ms.latestRound || 0);
  ms.toolCalls = Number(data.tool_calls || ms.toolCalls || 0);
  ms.contentChars = Number(data.content_chars || ms.contentChars || 0);
  ms.mode = String(data.mode || ms.mode || '').trim();
  if (data.failed) ms.failed = true;
  if (data.round !== undefined && !ms.startedRounds.has(ms.latestRound)) ms.startedRounds.add(ms.latestRound);
  if (data.round_finished !== undefined && ms.latestRound) ms.rounds.add(ms.latestRound);
  const roundLabel = ms.latestRound ? '第' + ms.latestRound + '轮' : '';
  const callsLabel = ms.toolCalls ? ms.toolCalls + '次工具调用' : '';
  const summaryText = [roundLabel, callsLabel].filter(Boolean).join('，') || '思考中';
  const content = '<span class="wa-task-chip">' + esc(ms.mode || '思考') + '</span>' + esc(summaryText);
  const row = upsertStepSingletonRow(step, 'model:thinking', 'model-summary', content);
  if (row) state.modelSummaryRows.set('thinking', row);
  markTaskActivity(card);
  syncTaskLiveProgress(card);
}

function handleEvent_progress(card: TaskCardElement, evt: Record<string, any>, payload: Record<string, any>): void {
  const state = ensureTaskUiState(card);
  const value = payload && typeof payload === 'object' ? Number(payload.value ?? payload.progress ?? 0) : 0;
  const label = payload && typeof payload === 'object' ? String(payload.label || payload.phase || payload.stage || '').trim() : '';
  const text = payload && typeof payload === 'object' ? String(payload.text || payload.message || payload.detail || '').trim() : '';
  state.progressExplicit = true;
  state.uiProgress = value;
  const progressEl = card.querySelector('[data-role="ui-progress"]') as HTMLElement;
  const phaseEl = card.querySelector('[data-role="ui-phase"]');
  const valueEl = card.querySelector('[data-role="ui-progress-value"]');
  const fillEl = card.querySelector('[data-role="ui-progress-fill"]') as HTMLElement | null;
  if (progressEl) progressEl.dataset.explicit = 'true';
  if (phaseEl && label) phaseEl.textContent = label;
  if (valueEl) valueEl.textContent = text || (value ? value + '%' : '');
  if (fillEl) fillEl.style.width = Math.max(0, Math.min(100, Number(value))) + '%';
  const lowered = label.toLowerCase();
  const stepId = lowered.includes('class') || lowered.includes('识别') ? 'route'
    : (lowered.includes('plan') || lowered.includes('规划') || lowered.includes('方案') ? 'plan'
      : (lowered.includes('check') || lowered.includes('核验') || lowered.includes('完成') ? 'check' : 'execute'));
  const step = taskStageStep(card, stepId);
  if (stepId === 'check' && value >= 100) markStepDone(step); else markStepRunning(step);
  if (text || label) {
    upsertStepSingletonRow(step, `progress:${label || stepId}`, value >= 100 ? 'success' : 'progress', '<span class="wa-task-chip">' + esc(label || '进度') + '</span>' + esc(text || `${Math.round(value)}%`));
  }
  syncTaskLiveProgress(card);
}

function stepIdFromEvent(evt: Record<string, any>, data: Record<string, any>): string {
  const raw = String(evt.step_id || data.step_id || data.step || data.stage || '').trim().toLowerCase();
  if (raw.includes('context') || raw.includes('read')) return 'context';
  if (raw.includes('route') || raw.includes('class')) return 'route';
  if (raw.includes('plan')) return 'plan';
  if (raw.includes('check') || raw.includes('verify')) return 'check';
  if (raw.includes('execute') || raw.includes('tool') || raw.includes('run')) return 'execute';
  const title = String(data.title || data.summary || '').trim().toLowerCase();
  if (title.includes('读取') || title.includes('上下文') || title.includes('context')) return 'context';
  if (title.includes('识别') || title.includes('分类') || title.includes('route')) return 'route';
  if (title.includes('方案') || title.includes('规划') || title.includes('plan')) return 'plan';
  if (title.includes('核验') || title.includes('检查') || title.includes('verify') || title.includes('check')) return 'check';
  return 'execute';
}

function handleEvent_step_started(card: TaskCardElement, evt: Record<string, any>, payload: Record<string, any>): void {
  const data = normalizedTaskLifecyclePayload(payload);
  const stepId = stepIdFromEvent(evt, data);
  const step = taskStageStep(card, stepId);
  markStepRunning(step);
  const title = String(data.title || evt.step_id || stepId || '任务步骤').trim();
  upsertStepSingletonRow(step, `step.started:${stepId}`, 'progress', '<span class="wa-task-chip">进行中</span>' + esc(title));
  markTaskActivity(card);
  syncTaskLiveProgress(card);
}

function handleEvent_step_result(card: TaskCardElement, evt: Record<string, any>, payload: Record<string, any>): void {
  const data = normalizedTaskLifecyclePayload(payload);
  const stepId = stepIdFromEvent(evt, data);
  const step = taskStageStep(card, stepId);
  const status = String(data.status || '').trim().toLowerCase();
  const failed = status === 'failed' || status === 'error' || status === 'needs_attention';
  const pending = status === 'pending' || status === 'awaiting_confirmation';
  if (failed) markStepFailed(step);
  else if (pending) markStepRunning(step);
  else markStepDone(step);
  const title = String(data.title || evt.step_id || stepId || '任务步骤').trim();
  const summary = compactFlowSummary(String(data.summary || data.text || data.message || '').trim(), '步骤已完成，结果见对话汇报。');
  const chip = failed ? '需处理' : (pending ? '待处理' : '完成');
  const kind = failed ? 'warn' : (pending ? 'progress' : 'success');
  upsertStepSingletonRow(
    step,
    `step.result:${stepId}:${title}`,
    kind,
    '<span class="wa-task-chip ' + (failed ? 'warn' : (!pending ? 'success' : '')) + '">' + esc(chip) + '</span>' + esc(summary || title),
  );
  markTaskActivity(card);
  syncTaskLiveProgress(card);
}

function handleEvent_code_summary(card: TaskCardElement, evt: Record<string, any>, payload: Record<string, any>): void {
  const data = normalizedTaskLifecyclePayload(payload);
  const step = taskStageStep(card, 'execute');
  markStepRunning(step);
  const state = ensureTaskUiState(card);
  const file = String(data.file || data.path || '').trim();
  const action = String(data.action || data.change_type || 'write').trim();
  const summary = String(data.summary || data.text || '').trim();
  if (!file && !summary) return;
  const codeKey = 'code:' + (file || 'file:' + Date.now());
  if (file) {
    let row = state.codeSummaryRows.get(codeKey);
    if (row) return;
    const shortFile = file.split('/').pop() || file;
    const content = '<span class="wa-task-chip success">' + esc(action === 'delete' ? '删除' : '写入') + '</span><a class="wa-task-file-link" href="javascript:void(0)" data-file-path="' + escAttr(file) + '">' + esc(shortFile) + '</a>';
    const r = appendRow(step, 'tool-finished', content);
    r.dataset.role = codeKey;
    state.codeSummaryRows.set(codeKey, row || r);
    card.dataset.taskCompleted = 'true';
  }
  markTaskActivity(card);
  syncTaskLiveProgress(card);
}

let fileRefreshControllerInstance: any = null;

function fileRefreshController(): any {
  const WA = (window as any).WA || {};
  if (!fileRefreshControllerInstance && typeof WA.createFileTaskRefreshController === 'function') {
    fileRefreshControllerInstance = WA.createFileTaskRefreshController({
      ensureTaskUiState,
      basename,
      setStatus,
      normalizePath: (path: string) => (
        WA && typeof WA.normalizeWorkspaceFilePath === 'function'
          ? WA.normalizeWorkspaceFilePath(path)
          : path
      ),
      logPrefix: '[WA fileTask]',
    });
  }
  return fileRefreshControllerInstance;
}

function handleEvent_file_refresh(card: TaskCardElement, evt: Record<string, any>, payload: Record<string, any>): void {
  const data = normalizedTaskLifecyclePayload(payload);
  const path = String(data.path || data.file_path || '').trim();
  if (!path) return;
  const normalizedPath = String(path || '').replace(/\\/g, '/').toLowerCase();
  const fileRefreshHash = (data as any).file_refresh_hash || '';
  const hashStore = card._fileRefreshHashes || new Map<string, string>();
  card._fileRefreshHashes = hashStore;
  if (fileRefreshHash && hashStore.get(normalizedPath) === fileRefreshHash) return;
  if (fileRefreshHash) hashStore.set(normalizedPath, fileRefreshHash);
  const controller = fileRefreshController();
  if (controller && typeof controller.queue === 'function') {
    controller.queue(card, data, {
      stepId: String(evt.step_id || 'execute'),
      stepTitle: '刷新文件',
    });
  }
  if (controller && typeof controller.trigger === 'function') {
    controller.trigger(card, {
      errorLog: '[WA fileTask] refresh failed:',
    });
  }
}

const EVENT_HANDLERS: Record<string, (card: TaskCardElement, evt: Record<string, any>, payload: Record<string, any>) => void> = {
  'plan': handleEvent_plan,
  'task.classified': handleEvent_task_classified,
  'plan.created': handleEvent_plan,
  'plan.proposed': handleEvent_plan,
  'plan.checked': handleEvent_plan_checked,
  'plan.gated': handleEvent_plan_gated,
  'supervisor.status': handleEvent_supervisor_status,
  'supervisor.intervention': handleEvent_supervisor_intervention,
  'supervisor.step_verified': handleEvent_supervisor_step_verified,
  'decision.made': handleEvent_decision_made,
  'workflow.state': handleEvent_workflow_state,
  'plan_summary': handleEvent_plan_summary,
  'plan.step_started': handleEvent_plan_step_started,
  'plan.step_finished': handleEvent_plan_step_finished,
  'run.started': handleEvent_run_started,
  'run.finished': handleEvent_run_finished,
  'run.cancelled': handleEvent_run_cancelled,
  'step.started': handleEvent_step_started,
  'step.finished': handleEvent_step_result,
  'step.result': handleEvent_step_result,
  'tool.started': handleEvent_tool_started,
  'tool.finished': handleEvent_tool_finished,
  'file.changed': handleEvent_file_changed,
  'read.changed': handleEvent_read_changed,
  'error': handleEvent_error,
  'model_summary': handleEvent_model_summary,
  'progress': handleEvent_progress,
  'code_summary': handleEvent_code_summary,
  'file_refresh': handleEvent_file_refresh,
};

function getEventHandlers(): typeof EVENT_HANDLERS {
  return EVENT_HANDLERS;
}

function dispatchEventToCard(card: TaskCardElement, evt: Record<string, any>): void {
  if (!card || !evt || typeof evt !== 'object') return;
  const etype = String(evt.type || '').trim().toLowerCase();
  if (!etype) return;
  const handler = EVENT_HANDLERS[etype];
  if (!handler) return;
  const payload = evt.payload || evt;
  const state = ensureTaskUiState(card);
  const runId = String(evt.run_id || payload.run_id || '').trim();
  const seq = Number(evt.seq || payload.seq || 0);
  const eventKey = runId + ':' + etype + ':' + seq;
  if (runId && state.lastEventRunId && state.lastEventRunId !== runId) { state.processedEventKeys.clear(); state.lastEventSeq = 0; }
  state.lastEventRunId = runId;
  if (runId && seq > 0 && state.lastEventSeq >= seq) {
    if (state.processedEventKeys.has(eventKey)) return;
  }
  state.lastEventSeq = Math.max(state.lastEventSeq, seq);
  state.processedEventKeys.add(eventKey);
  handler(card, evt, payload);
  notifyTaskWorkbenchForCard(card);
}

function processFileTaskStreamEvent(card: TaskCardElement, evt: Record<string, any>): void {
  if (!card || !evt || typeof evt !== 'object') return;
  if (!card.classList.contains('streaming')) { card.classList.add('streaming'); startTaskHeartbeat(card); }
  dispatchEventToCard(card, evt);
}

function handleEvent(card: TaskCardElement, evt: Record<string, any>): void {
  processFileTaskStreamEvent(card, evt);
}

function scheduleTaskStream(run: () => void): void {
  const scheduler = typeof (globalThis as any).setImmediate === 'function'
    ? (globalThis as any).setImmediate
    : (callback: () => void) => window.setTimeout(callback, 0);
  scheduler(run);
}

function appendTaskRunCardIfDetached(card: TaskCardElement): void {
  if (!card || card.isConnected) return;
  const msgs = document.getElementById('wa-ai-messages');
  if (msgs) msgs.appendChild(card);
}

function streamTaskSse(cardOrLoadingEl: TaskCardElement | null, url: string, body: Record<string, any> | FormData, method?: string, opts?: Record<string, any>): Promise<TaskCardElement> {
  const streamingCard = makeRunCard(cardOrLoadingEl);
  streamingCard.dataset.taskUrl = url;
  appendTaskRunCardIfDetached(streamingCard);
  revealTaskWorkbenchForCard(streamingCard, { scroll: true });
  const options = opts && typeof opts === 'object' ? opts : {};
  const httpMethod = String(method || 'POST').toUpperCase() || 'POST';
  const fetchAbort = new AbortController();
  const signal: AbortSignal = fetchAbort.signal;
  const finishRunWithError = (errText: string) => {
    if (streamingCard.dataset.taskTerminalStatus === 'cancelled') return;
    streamingCard.dataset.taskTerminalStatus = 'error';
    streamingCard._fatalErrorText = errText;
    dispatchEventToCard(streamingCard, { type: 'error', payload: { text: errText } });
    streamingCard.classList.remove('streaming');
    streamingCard.classList.add('failed');
    const cancelBtn = streamingCard.querySelector('[data-role="cancel"]');
    if (cancelBtn) { (cancelBtn as HTMLElement).textContent = '关闭'; (cancelBtn as HTMLElement).dataset.action = 'close'; }
    syncTaskLiveProgress(streamingCard);
  };
  const cancellationHandler = () => {
    if (!fetchAbort) return;
    try { fetchAbort.abort(); } catch { /* noop */ }
    const cancelBtn = streamingCard.querySelector('[data-role="cancel"]');
    if (cancelBtn) { (cancelBtn as HTMLElement).textContent = '关闭'; (cancelBtn as HTMLElement).dataset.action = 'close'; }
    streamingCard.dataset.taskTerminalStatus = 'cancelled';
    stopTaskHeartbeat(streamingCard);
    streamingCard.classList.remove('streaming');
    streamingCard.classList.add('cancelled');
    syncTaskLiveProgress(streamingCard);
  };
  streamingCard._cancelHandler = cancellationHandler;
  scheduleTaskStream(async () => {
    try {
      const resp = await fetch(url, {
        method: httpMethod,
        headers: httpMethod !== 'GET' ? { 'Content-Type': 'application/json' } : undefined,
        body: httpMethod !== 'GET' ? JSON.stringify(body) : undefined,
        signal: signal || undefined,
      });
      if (!resp.ok) { finishRunWithError('请求失败: ' + resp.status + ' ' + resp.statusText); return; }
      if (!resp.body) { finishRunWithError('响应流不可用'); return; }
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      const readLoop = async (): Promise<void> => {
        while (true) {
          const { done, value } = await reader.read();
          if (done) { 
            const flushed = parseSseEvents(buffer, true);
            flushed.events.forEach((evt) => processFileTaskStreamEvent(streamingCard, evt));
            stopTaskHeartbeat(streamingCard);
            if (!streamingCard.dataset.taskTerminalStatus) { dispatchEventToCard(streamingCard, { type: 'run.finished', payload: { text: '流已结束。' } }); }
            break;
          }
          buffer += decoder.decode(value, { stream: true });
          const parsed = parseSseEvents(buffer, false);
          parsed.events.forEach((evt) => processFileTaskStreamEvent(streamingCard, evt));
          buffer = parsed.remainder;
        }
      };
      readLoop().catch((err) => finishRunWithError(String(err.message || err)));
    } catch (err: any) {
      if ((err as any)?.name === 'AbortError') return;
      finishRunWithError(String(err.message || err));
    }
  });
  return Promise.resolve(streamingCard);
}

function cancelFileTaskRun(card: TaskCardElement): boolean {
  if (!card || !isTaskCardElement(card)) return false;
  if (typeof card._cancelHandler === 'function') { card._cancelHandler(); return true; }
  if (card.dataset.taskTerminalStatus && !['cancelled', 'failed', 'error'].includes(card.dataset.taskTerminalStatus)) {
    card.dataset.taskTerminalStatus = 'cancelled';
    stopTaskHeartbeat(card);
    dispatchEventToCard(card, { type: 'run.cancelled', payload: { text: '任务已被取消。' } });
    card.classList.remove('streaming');
    card.classList.add('cancelled');
    const cancelBtn = card.querySelector('[data-role="cancel"]');
    if (cancelBtn) { (cancelBtn as HTMLElement).textContent = '关闭'; (cancelBtn as HTMLElement).dataset.action = 'close'; }
    syncTaskLiveProgress(card);
    return true;
  }
  return false;
}

function compactTaskContract(contract: Record<string, any> | null | undefined): Record<string, any> | null {
  if (!contract || typeof contract !== 'object') return null;
  const result: Record<string, any> = {};
  try {
    if (contract.file_path) result.fp = contract.file_path;
    if (contract.request_kind) result.rk = contract.request_kind;
    if (contract.task_family) result.tf = contract.task_family;
    if (contract.operation_kind) result.ok = contract.operation_kind;
    if (contract.execution_mode) result.em = contract.execution_mode;
    if (contract.output_mode) result.om = contract.output_mode;
    if (contract.target_mode) result.tm = contract.target_mode;
    if (contract.multi_target_instructions) result.mti = contract.multi_target_instructions;
    if (contract.expected_tool_name) result.etn = contract.expected_tool_name;
    if (contract.max_tool_calls) result.mtc = contract.max_tool_calls;
    if (contract.max_iterations) result.mi = contract.max_iterations;
    if (contract.background) result.bg = contract.background;
    if (contract.use_tool_fleet) result.utf = contract.use_tool_fleet;
    if (contract.draft_mode) result.dm = contract.draft_mode;
    if (contract.quick_action_mode) result.qam = contract.quick_action_mode;
    if (contract.allowed_tool_names && Array.isArray(contract.allowed_tool_names)) result.atn = contract.allowed_tool_names;
    if (contract.post_processing_script) result.pps = contract.post_processing_script;
    if (contract.initial_instructions) result.ii = contract.initial_instructions;
    if (contract.reasoning_effort) result.re = contract.reasoning_effort;
    result.v = 1;
    return result;
  } catch { return null; }
}

function encodeTaskContract(contract: Record<string, any> | null | undefined): string {
  if (!contract || typeof contract !== 'object') return '';
  const compacted = compactTaskContract(contract);
  if (!compacted) return '';
  try {
    const json = JSON.stringify(compacted);
    const compressed = (window as any).LZString?.compressToEncodedURIComponent(json);
    return compressed || encodeURIComponent(json);
  } catch { return ''; }
}

function decodeTaskContract(encoded: string): Record<string, any> | null {
  if (!encoded || typeof encoded !== 'string') return null;
  const EXPAND_MAP: Record<string, string> = {
    fp: 'file_path', rk: 'request_kind', tf: 'task_family', ok: 'operation_kind',
    em: 'execution_mode', om: 'output_mode', tm: 'target_mode', mti: 'multi_target_instructions',
    etn: 'expected_tool_name', mtc: 'max_tool_calls', mi: 'max_iterations', bg: 'background',
    utf: 'use_tool_fleet', dm: 'draft_mode', qam: 'quick_action_mode', atn: 'allowed_tool_names',
    pps: 'post_processing_script', ii: 'initial_instructions', re: 'reasoning_effort', v: 'v',
  };
  try {
    let json: string;
    if ((window as any).LZString && typeof (window as any).LZString.decompressFromEncodedURIComponent === 'function') {
      json = (window as any).LZString.decompressFromEncodedURIComponent(encoded) || '';
    } else { json = decodeURIComponent(encoded); }
    if (!json) return null;
    const parsed = JSON.parse(json);
    if (!parsed || typeof parsed !== 'object') return null;
    if (parsed.v === 1) {
      const expanded: Record<string, any> = {};
      for (const key of Object.keys(parsed)) {
        const expandedKey = EXPAND_MAP[key] || key;
        expanded[expandedKey] = parsed[key];
      }
      delete expanded.v;
      return expanded;
    }
    return parsed;
  } catch { return null; }
}

function markTaskRunCardAsHistory(card: TaskCardElement, options?: Record<string, any>): TaskCardElement {
  const settings = options && typeof options === 'object' ? options : {};
  const label = String(settings.history_label || '历史任务记录').trim() || '历史任务记录';
  const note = String(settings.history_note || '这是一条历史运行记录，不代表当前文件状态。').trim();
  card.classList.remove('streaming', 'pending');
  card.classList.add('is-history-snapshot');
  card.dataset.historySnapshot = 'true';
  card.dataset.taskCurrentRun = 'false';
  card.setAttribute('aria-label', label);
  card.querySelector('[data-role="cancel"]')?.remove();
  card.querySelectorAll('.wa-task-actions').forEach((node) => node.remove());
  const titleWrap = card.querySelector('.wa-task-title-wrap');
  if (titleWrap && !titleWrap.querySelector('[data-role="history-badge"]')) {
    const badge = document.createElement('span');
    badge.className = 'wa-task-history-badge';
    badge.dataset.role = 'history-badge';
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
}

function restoreTaskRunCard(cardOrSnapshot: TaskCardElement | Record<string, any>, initialSummary?: string | Record<string, any>, initialStatus?: string, recoveryPayload?: Record<string, any>): TaskCardElement | null {
  if (cardOrSnapshot && !isTaskCardElement(cardOrSnapshot as TaskCardElement) && typeof cardOrSnapshot === 'object' && (cardOrSnapshot as Record<string, any>).html) {
    const wrapper = document.createElement('div');
    wrapper.innerHTML = String((cardOrSnapshot as Record<string, any>).html || '').trim();
    const card = wrapper.firstElementChild as TaskCardElement | null;
    if (!card || !isTaskCardElement(card)) return null;
    card._fatalErrorText = String((cardOrSnapshot as Record<string, any>).fatal_error_text || '');
    const restored = attachRunCardBehavior(card);
    const options = initialSummary && typeof initialSummary === 'object' ? initialSummary as Record<string, any> : {};
    return options.history ? markTaskRunCardAsHistory(restored, options) : restored;
  }
  const cardEl = cardOrSnapshot as TaskCardElement;
  if (!cardEl || !isTaskCardElement(cardEl)) return null;
  const settings: Record<string, any> = {
    taskId: String(cardEl.dataset.taskId || '').trim(),
    runId: String(cardEl.dataset.taskRunId || '').trim(),
    initialStatus: String(initialStatus || cardEl.dataset.taskTerminalStatus || '').trim(),
  };
  if (settings.initialStatus === 'waiting' || settings.initialStatus === 'awaiting_confirmation') {
    initializeRecoveredRunCard(cardEl, settings);
  }
  const summaryText = typeof initialSummary === 'string' ? initialSummary : '';
  if (summaryText && !String(cardEl.dataset.taskSummary || '').trim()) { cardEl.dataset.taskSummary = summaryText; }
  const stepsHost = cardEl.querySelector('[data-role="steps"]');
  if (stepsHost && !stepsHost.children.length) { stepsHost.innerHTML = '<div class="wa-task-step pending" data-step-id="run"><details class="wa-task-step-detail" open><summary class="wa-task-step-head"><span class="wa-task-step-dot"></span><span class="wa-task-step-title">任务状态</span></summary><div class="wa-task-step-body"></div></details></div>'; }
  cardEl.classList.remove('streaming', 'pending');
  if (settings.initialStatus === 'waiting' || settings.initialStatus === 'awaiting_confirmation') { cardEl.classList.add('pending'); }
  else if (settings.initialStatus === 'running' || !settings.initialStatus) { cardEl.classList.add('streaming'); startTaskHeartbeat(cardEl); }
  else { cardEl.classList.add('done'); }
  syncTaskLiveProgress(cardEl);
  return cardEl;
}

function normalizedResumeStatus(status: string): string {
  const value = String(status || '').trim().toLowerCase();
  if (['completed', 'complete', 'success', 'succeeded', 'done', 'verified'].includes(value)) return 'completed';
  if (['failed', 'failure', 'error'].includes(value)) return 'failed';
  if (value === 'cancelled' || value === 'canceled') return 'cancelled';
  if (value === 'waiting' || value === 'awaiting_confirmation') return 'waiting';
  if (value === 'running' || value === 'streaming') return 'running';
  return value;
}

function isTerminalResumeStatus(status: string): boolean {
  return ['completed', 'failed', 'cancelled'].includes(normalizedResumeStatus(status));
}

function resumePersistedFileTask(optionsOrCard: ResumeFileTaskOptions | TaskCardElement, taskContract?: Record<string, any>): Promise<TaskCardElement> {
  const options: ResumeFileTaskOptions = isTaskCardElement(optionsOrCard)
    ? { loadingEl: optionsOrCard, taskPayload: taskContract || {} }
    : (optionsOrCard && typeof optionsOrCard === 'object' ? optionsOrCard as ResumeFileTaskOptions : {});
  const contract = (options.taskPayload && typeof options.taskPayload === 'object' ? options.taskPayload : taskContract) || {};
  const taskId = String(options.taskId || options.task_id || contract.task_id || contract.taskId || '').trim();
  if (!taskId) return Promise.reject(new Error('缺少 task_id，无法恢复任务流'));

  const card = makeRunCard(isTaskCardElement(options.loadingEl) ? options.loadingEl as TaskCardElement : null);
  card.dataset.taskId = taskId;
  const runId = String(options.runId || options.run_id || contract.run_id || contract.runId || '').trim();
  if (runId) card.dataset.taskRunId = runId;
  const initialStatus = options.initialStatus || options.status || contract.initialStatus || contract.status || 'running';
  restoreTaskRunCard(card, contract.summary || '', initialStatus, {});
  if (isTerminalResumeStatus(initialStatus)) {
    appendTaskRunCardIfDetached(card);
    revealTaskWorkbenchForCard(card, { scroll: true });
    const terminalStatus = normalizedResumeStatus(initialStatus);
    dispatchEventToCard(card, {
      type: terminalStatus === 'cancelled' ? 'run.cancelled' : 'run.finished',
      payload: {
        summary: contract.summary || '',
        terminal_status: terminalStatus === 'failed' ? 'error' : terminalStatus,
        completed_task: terminalStatus === 'completed',
      },
    });
    if (typeof options.onTaskCardSnapshot === 'function') {
      try { options.onTaskCardSnapshot(card); } catch (_) { /* noop */ }
    }
    return Promise.resolve(card);
  }

  const replay = options.replay === false ? 'false' : 'true';
  const finalUrl = `/api/tasks/${encodeURIComponent(taskId)}/stream?replay=${replay}`;
  return streamTaskSse(card, finalUrl, {}, 'GET').then((streamingCard) => {
    if (typeof options.onTaskCardSnapshot === 'function') {
      try { options.onTaskCardSnapshot(streamingCard); } catch (_) { /* noop */ }
    }
    return streamingCard;
  });
}

async function streamTaskFlow(optionsOrLoadingEl: StreamFileTaskOptions | TaskCardElement | null, url?: string, body?: Record<string, any> | FormData, method?: string, opts?: Record<string, any>): Promise<any> {
  if (url) {
    return streamTaskSse(optionsOrLoadingEl as TaskCardElement | null, url, body || {}, method, opts);
  }

  const options = (optionsOrLoadingEl && typeof optionsOrLoadingEl === 'object' && !('classList' in optionsOrLoadingEl))
    ? optionsOrLoadingEl as StreamFileTaskOptions
    : { loadingEl: optionsOrLoadingEl as TaskCardElement | null };
  const msgs = options.msgs || document.getElementById('wa-ai-messages');
  const card = makeRunCard(options.loadingEl as TaskCardElement | null);
  const payload = options.payload && typeof options.payload === 'object' ? options.payload : {};

  if (!String(payload.run_id || '').trim()) {
    const randomId = (window.crypto && typeof window.crypto.randomUUID === 'function')
      ? window.crypto.randomUUID().replace(/-/g, '').slice(0, 12)
      : `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;
    payload.run_id = randomId;
  }
  card.dataset.taskRunId = String(payload.run_id || '').trim();
  seedRouteModelContext(card, payload);
  const quickActionMode = payload.options && typeof payload.options === 'object'
    ? String(payload.options.quick_action_mode || '').trim()
    : '';
  if (quickActionMode) card.dataset.taskQuickActionMode = quickActionMode;
  if (!options.loadingEl && msgs) msgs.appendChild(card);
  card.classList.add('streaming');
  startTaskHeartbeat(card);
  revealTaskWorkbenchForCard(card, { scroll: true });
  if (typeof options.onTaskCardSnapshot === 'function') {
    try { options.onTaskCardSnapshot(card); } catch (_) { /* noop */ }
  }
  scrollToBottom(msgs);

  const resp = await csrfFetch('/api/editor/ai/task-stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Accept': 'text/event-stream' },
    body: JSON.stringify(payload),
    signal: options.signal,
  });
  if (!resp.ok) throw new Error(await describeHttpError(resp));
  if (!resp.body) throw new Error('响应流不可用');

  const reader = resp.body.getReader();
  card._abortFileTaskStream = () => {
    try {
      if (options.abortController && typeof options.abortController.abort === 'function' && !(options.abortController.signal && options.abortController.signal.aborted)) {
        options.abortController.abort();
      }
    } catch (_) { /* noop */ }
    try {
      if (reader && typeof reader.cancel === 'function') reader.cancel();
    } catch (_) { /* noop */ }
  };

  const decoder = new TextDecoder();
  let buffer = '';
  try {
    while (true) {
      const chunk = await reader.read();
      if (chunk.done) break;
      buffer += decoder.decode(chunk.value, { stream: true });
      const parsed = parseSseEvents(buffer, false);
      buffer = parsed.remainder;
      parsed.events.forEach((evt) => processFileTaskStreamEvent(card, evt));
      if (typeof options.onTaskCardSnapshot === 'function') {
        try { options.onTaskCardSnapshot(card); } catch (_) { /* noop */ }
      }
      scrollToBottom(msgs);
    }

    const trailing = parseSseEvents(buffer, true);
    trailing.events.forEach((evt) => processFileTaskStreamEvent(card, evt));
  } catch (error) {
    if (card._fatalErrorText) throw makeTaskError(card._fatalErrorText);
    throw error;
  } finally {
    card.classList.remove('streaming');
    stopTaskHeartbeat(card);
    if (typeof options.onTaskCardSnapshot === 'function') {
      try { options.onTaskCardSnapshot(card); } catch (_) { /* noop */ }
    }
    if (card._abortFileTaskStream) delete card._abortFileTaskStream;
  }

  const terminalResult = taskTerminalResult(card, '');
  if (card._fatalErrorText) throw makeTaskError(terminalResult.summary);
  return terminalResult;
}

const WA = (window as any).WA || {};
WA.streamTaskFlow = streamTaskFlow;
WA.cancelFileTaskRun = cancelFileTaskRun;
WA.makeRunCard = makeRunCard;
WA.compactTaskContract = compactTaskContract;
WA.encodeTaskContract = encodeTaskContract;
WA.decodeTaskContract = decodeTaskContract;
WA.restoreTaskRunCard = restoreTaskRunCard;
WA.resumePersistedFileTask = resumePersistedFileTask;
WA.ensureTaskUiState = ensureTaskUiState;
WA.syncTaskLiveProgress = syncTaskLiveProgress;
WA.processFileTaskStreamEvent = processFileTaskStreamEvent;
WA.getEventHandlers = getEventHandlers;
WA.parseSseEvents = parseSseEvents;
WA.setTaskRunContext = setTaskRunContext;
WA.taskTerminalResult = taskTerminalResult;
WA.handleEvent = handleEvent;
WA.handleEvent_run_started = handleEvent_run_started;
WA.handleEvent_run_finished = handleEvent_run_finished;
WA.handleEvent_tool_started = handleEvent_tool_started;
WA.handleEvent_tool_finished = handleEvent_tool_finished;
WA.handleEvent_file_changed = handleEvent_file_changed;
WA.handleEvent_error = handleEvent_error;
WA.TaskStatus = TaskStatus;
(window as any).WA = WA;
(window as any).WA.parseSseEvents = parseSseEvents;

export {
  streamTaskFlow,
  streamTaskSse,
  cancelFileTaskRun,
  makeRunCard,
  compactTaskContract,
  encodeTaskContract,
  decodeTaskContract,
  restoreTaskRunCard,
  resumePersistedFileTask,
  ensureTaskUiState,
  syncTaskLiveProgress,
  processFileTaskStreamEvent,
  getEventHandlers,
  parseSseEvents,
  setTaskRunContext,
  taskTerminalResult,
  handleEvent,
  handleEvent_run_started,
  handleEvent_run_finished,
  handleEvent_tool_started,
  handleEvent_tool_finished,
  handleEvent_file_changed,
  handleEvent_error,
  TaskStatus,
};
