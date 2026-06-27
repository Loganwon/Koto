import { _csrfFetch } from './infrastructure';

export interface TaskDispatcherDeps {
  state?: Record<string, any>;
  getSessionId?: () => string;
  getConversationHistory?: () => any[];
  getModelMode?: () => string;
  getSelectedCloudModelId?: () => string;
  setStreamButton?: (loading: boolean) => void;
  streamTaskFlow?: (opts: any) => Promise<any>;
  beginAssistantTaskTurn?: (metadata?: any) => any;
  syncAssistantTaskTurn?: (turnId: string, metadata?: any) => any;
  appendAssistantTurn?: (content: string, metadata?: any) => any;
  persistTaskTurn?: (record?: any) => Promise<any>;
  getActiveEditorContent?: () => string;
  sampleTaskContext?: (content: string) => string;
}

export interface MessageRoute {
  id?: string;
  priority?: number;
  match: (context: any) => boolean;
  run: (context: any) => any;
}

export interface TaskContext {
  text: string;
  pinnedSelText?: string;
  pinnedSelSource?: string;
  model_mode?: string;
  model_id?: string;
  msgs?: HTMLElement;
  loadingEl?: HTMLElement;
  taskPayload?: Record<string, any> | null;
  options?: Record<string, any>;
}

export interface TaskFileInfo {
  path?: string;
  name?: string;
  type?: string;
  file_type?: string;
  content?: string;
  target?: boolean;
  loading?: boolean;
}

export function createTaskDispatcher(deps: TaskDispatcherDeps = {}) {
  const options = deps || {};
  const state = options.state || {};
  const messageRoutes: MessageRoute[] = [];
  const quickActionHandlers = new Map<string, Function>();
  let defaultQuickActionHandler: Function | null = null;
  const WORKSPACE_ROUTE_NAMES = new Set(['light_chat', 'web_search', 'file_task', 'open_file']);
  const WORKSPACE_DIRECT_ROUTES = new Set(['light_chat', 'web_search']);
  const WORKSPACE_FILE_TASK_ROUTE = 'file_task';
  const WORKSPACE_FILE_TASK_KIND = 'complex_task';
  const WORKSPACE_DIRECT_KIND = 'direct_response';

  function registerMessageRoute(route: MessageRoute): MessageRoute {
    if (!route || typeof route.match !== 'function' || typeof route.run !== 'function') {
      throw new Error('Invalid task message route');
    }
    messageRoutes.push(route);
    messageRoutes.sort((left, right) => (Number(right.priority) || 0) - (Number(left.priority) || 0));
    return route;
  }

  function registerQuickActionHandler(action: string, handler: Function): Function {
    const key = String(action || '').trim();
    if (!key || typeof handler !== 'function') throw new Error('Invalid task action handler');
    quickActionHandlers.set(key, handler);
    return handler;
  }

  function setDefaultQuickActionHandler(handler: Function): Function {
    if (typeof handler !== 'function') throw new Error('Invalid default task action handler');
    defaultQuickActionHandler = handler;
    return handler;
  }

  function matchQuickAction(text: string): string {
    const source = String(text || '').trim();
    return quickActionHandlers.has(source) ? source : '';
  }

  function dispatchMessage(context: TaskContext): Promise<any> {
    const route = messageRoutes.find((candidate) => candidate.match(context));
    if (!route) return Promise.reject(new Error('没有可用的任务路由'));
    return Promise.resolve(route.run(context));
  }

  function dispatchQuickAction(action: string, context: any): Promise<any> {
    const handler = quickActionHandlers.get(action) || defaultQuickActionHandler;
    if (!handler) return Promise.reject(new Error(`未注册任务动作处理器：${action}`));
    return Promise.resolve(handler(Object.assign({ action }, context)));
  }

  function previewText(value: string, limit: number): string {
    const text = String(value || '').trim();
    const max = Number(limit) > 0 ? Number(limit) : 0;
    if (!max || text.length <= max) return text;
    return text.slice(0, max) + '...';
  }

  function cloneTaskPayload(payload: any): any {
    if (!payload || typeof payload !== 'object') return null;
    try { return JSON.parse(JSON.stringify(payload)); }
    catch { return Object.assign({}, payload); }
  }

  function compactJsonValue(value: any, depth: number, textLimit: number): any {
    const level = Number(depth) || 0;
    const limit = Number(textLimit) > 0 ? Number(textLimit) : 2000;
    if (level > 5) return null;
    if (value == null) return null;
    if (typeof value === 'string') return previewText(value, limit);
    if (typeof value === 'number' || typeof value === 'boolean') return value;
    if (Array.isArray(value)) {
      return value.slice(0, 20).map((item: any) => compactJsonValue(item, level + 1, limit)).filter((item: any) => item != null);
    }
    if (typeof value === 'object') {
      const compact: Record<string, any> = {};
      Object.entries(value).slice(0, 60).forEach(([key, item]) => {
        const cleanKey = previewText(key, 120);
        if (!cleanKey) return;
        const cleanValue = compactJsonValue(item, level + 1, limit);
        if (cleanValue != null) compact[cleanKey] = cleanValue;
      });
      return Object.keys(compact).length ? compact : null;
    }
    return previewText(value, limit);
  }

  function compactFollowupTaskFile(file: any): Record<string, any> | null {
    if (!file || typeof file !== 'object') return null;
    const compact: Record<string, any> = {};
    const path = String(file.path || '').trim();
    const name = String(file.name || '').trim();
    const type = String(file.type || file.file_type || '').trim();
    if (path) compact.path = path;
    if (name) compact.name = name;
    if (type) compact.type = type;
    if (file.target) compact.target = true;
    return Object.keys(compact).length ? compact : null;
  }

  function compactTaskFileList(files: any[], limit: number): any[] {
    const max = Number(limit) > 0 ? Number(limit) : 8;
    return (Array.isArray(files) ? files : []).map((file) => compactFollowupTaskFile(file)).filter(Boolean).slice(0, max);
  }

  function compactTaskContext(value: any): Record<string, any> | null {
    if (!value || typeof value !== 'object') return null;
    try {
      const cloned = compactJsonValue(value, 0, 2000);
      if (!cloned || typeof cloned !== 'object') return null;
      const c = cloned as Record<string, any>;
      if (c.files && typeof c.files === 'object') {
        if (Array.isArray(c.files.sources)) c.files.sources = compactTaskFileList(c.files.sources, 8);
        if (c.files.current) c.files.current = compactFollowupTaskFile(c.files.current);
        if (c.files.target) c.files.target = compactFollowupTaskFile(c.files.target);
      }
      if (c.continuity && typeof c.continuity === 'object') {
        if (Array.isArray(c.continuity.previous_file_changes)) {
          c.continuity.previous_file_changes = c.continuity.previous_file_changes.slice(-8);
        }
        if (c.continuity.followup_context && typeof c.continuity.followup_context === 'object') {
          const followup = c.continuity.followup_context;
          if (followup.previous_task_summary) followup.previous_task_summary = previewText(followup.previous_task_summary, 2000);
          if (followup.user_feedback) followup.user_feedback = previewText(followup.user_feedback, 1000);
        }
      }
      return Object.keys(c).length ? c : null;
    } catch { return null; }
  }

  function compactFollowupTaskPayload(payload: any): Record<string, any> | null {
    if (!payload || typeof payload !== 'object') return null;
    const compact: Record<string, any> = {};
    const task = String(payload.task || '').trim();
    const files = Array.isArray(payload.files) ? payload.files.map((f: any) => compactFollowupTaskFile(f)).filter(Boolean) : [];
    const currentFile = compactFollowupTaskFile(payload.current_file);
    const selection = String(payload.selection || '').trim();
    const selectionSource = String(payload.selection_source || '').trim();
    const targetPath = String(payload.target_path || '').trim();
    const fileName = String(payload.file_name || '').trim();
    const fileType = String(payload.file_type || '').trim();
    const taskContext = compactTaskContext(payload.task_context);
    if (task) compact.task = task;
    if (files.length) compact.files = files;
    if (selection) compact.selection = selection;
    if (selectionSource) compact.selection_source = selectionSource;
    if (targetPath) compact.target_path = targetPath;
    if (fileName) compact.file_name = fileName;
    if (fileType) compact.file_type = fileType;
    if (currentFile) compact.current_file = currentFile;
    if (taskContext) compact.task_context = taskContext;
    return Object.keys(compact).length ? compact : null;
  }

  function compactPendingResumePayload(payload: any): Record<string, any> | null {
    if (!payload || typeof payload !== 'object') return null;
    const compact = compactFollowupTaskPayload(payload) || {};
    const task = String(payload.task || '').trim();
    const taskId = String(payload.task_id || '').trim();
    const sessionId = String(payload.session_id || '').trim();
    const modelMode = String(payload.model_mode || '').trim();
    const modelId = String(payload.model_id || '').trim();
    const workflowCheckpoint = payload.options && typeof payload.options === 'object'
      && payload.options.workflow_checkpoint && typeof payload.options.workflow_checkpoint === 'object'
      ? Object.assign({}, payload.options.workflow_checkpoint) : null;
    if (task) compact.task = task;
    if (taskId) compact.task_id = taskId;
    if (sessionId) compact.session_id = sessionId;
    if (modelMode) compact.model_mode = modelMode;
    if (modelId) compact.model_id = modelId;
    if (workflowCheckpoint) compact.options = { workflow_checkpoint: workflowCheckpoint };
    return Object.keys(compact).length ? compact : null;
  }

  function setTaskFollowupPayload(loadingEl: HTMLElement, payload: any): void {
    if (!loadingEl || !loadingEl.dataset) return;
    const compactPayload = compactFollowupTaskPayload(payload);
    if (!compactPayload) { delete loadingEl.dataset.taskFollowupPayload; return; }
    try { loadingEl.dataset.taskFollowupPayload = encodeURIComponent(JSON.stringify(compactPayload)); }
    catch { delete loadingEl.dataset.taskFollowupPayload; }
  }

  function setPendingTaskResumePayload(loadingEl: HTMLElement, payload: any): void {
    if (!loadingEl || !loadingEl.dataset) return;
    const compactPayload = compactPendingResumePayload(payload);
    const checkpoint = compactPayload && compactPayload.options && typeof compactPayload.options === 'object'
      ? compactPayload.options.workflow_checkpoint : null;
    const policy = String(checkpoint && checkpoint.policy || '').trim().toLowerCase();
    if (!checkpoint || policy !== 'confirm_each_step') {
      delete loadingEl.dataset.taskPendingResumePayload;
      return;
    }
    try { loadingEl.dataset.taskPendingResumePayload = encodeURIComponent(JSON.stringify(compactPayload)); }
    catch { delete loadingEl.dataset.taskPendingResumePayload; }
  }

  function buildTaskContextPackage(params: {
    task?: string; files?: any[]; currentFile?: any; targetFile?: any;
    selection?: string; selectionSource?: string; followupContext?: any; workflowCheckpoint?: any;
  }): Record<string, any> | null {
    const payload = params && typeof params === 'object' ? params : {};
    const files = Array.isArray(payload.files) ? payload.files : [];
    const targetFile = payload.targetFile || files.find((f: any) => f && f.target) || null;
    const currentFile = payload.currentFile || null;
    const followupContext = payload.followupContext && typeof payload.followupContext === 'object' ? payload.followupContext : null;
    const selectionText = String(payload.selection || '').trim();
    const context: Record<string, any> = {
      context_version: 'koto_task_context_v1',
      intent: {
        request: previewText(payload.task || '', 2000),
        followup_action: followupContext ? String(followupContext.followup_action || 'question').trim() || 'question' : '',
        source: followupContext ? String(followupContext.source || '').trim() : 'user_input',
      },
      files: {
        current: compactFollowupTaskFile(currentFile),
        target: compactFollowupTaskFile(targetFile),
        sources: compactTaskFileList(files.filter((f: any) => f && f !== targetFile), 8),
      },
      selection: { has_selection: !!selectionText, source: previewText(payload.selectionSource || '', 240), preview: previewText(selectionText, 600) },
      continuity: { followup_context: followupContext },
    };
    const workflowCheckpoint = payload.workflowCheckpoint && typeof payload.workflowCheckpoint === 'object' ? payload.workflowCheckpoint : null;
    if (workflowCheckpoint && String(workflowCheckpoint.policy || '').trim().toLowerCase() === 'confirm_each_step') {
      context.continuity.stepwise = {
        policy: 'confirm_each_step', step_index: Number(workflowCheckpoint.step_index || 0) || 0,
        original_task: previewText(workflowCheckpoint.original_task || payload.task || '', 2000), resume_label: '继续下一步',
      };
    }
    if (followupContext) {
      context.continuity.previous_run_id = previewText(followupContext.previous_run_id || '', 128);
      context.continuity.previous_task_status = previewText(followupContext.previous_task_status || '', 80);
      context.continuity.previous_task_summary = previewText(followupContext.previous_task_summary || '', 2000);
      if (followupContext.stepwise && typeof followupContext.stepwise === 'object') {
        context.continuity.stepwise = Object.assign({}, context.continuity.stepwise || {}, compactJsonValue(followupContext.stepwise, 0, 2000) || {});
      }
      if (Array.isArray(followupContext.previous_task_file_changes)) {
        context.continuity.previous_file_changes = followupContext.previous_task_file_changes.slice(-8);
      }
    }
    return compactTaskContext(context);
  }

  const WRITE_TARGET_HINTS = ['加入', '写入', '插入', '放到', '放入', '放进', '写回', '更新', '同步到', '汇总到', '整理到', '保存到', '输出到', '追加到', 'append', 'insert', 'write', 'save'];
  const READ_ONLY_HINTS = ['不要修改', '不要改', '别修改', '别改', '不用修改', '无需修改', '不要写入', '不要写回', '不要更新', '不写入', '不写回', '只分析', '仅分析', '只总结', '仅总结', '只检查', '仅检查', '只列出', '仅列出', '只解释', '仅解释', '只给建议', '仅给建议', 'do not modify', 'do not edit', 'do not write', 'do not update', 'read only', 'readonly', 'only analyze', 'only summar'];
  const TARGET_TYPE_CUES = [
    { canonical: 'docx', cues: ['docx', 'word'] }, { canonical: 'xlsx', cues: ['xlsx', 'excel'] },
    { canonical: 'pptx', cues: ['pptx', 'powerpoint', 'slides', 'ppt'] }, { canonical: 'csv', cues: ['csv'] },
    { canonical: 'md', cues: ['markdown', 'md'] }, { canonical: 'txt', cues: ['txt'] },
  ];
  const TARGET_TYPE_FAMILIES: Record<string, string[]> = {
    docx: ['docx', 'doc'], xlsx: ['xlsx', 'xlsm', 'xls'], pptx: ['pptx', 'ppt'],
    csv: ['csv'], md: ['md'], txt: ['txt'],
  };
  const COMPARE_TASK_HINTS = ['对比', '比较', '对照', '差异', '区别', '不同', 'compare', 'diff', 'difference'];
  const ANNOTATION_TASK_HINTS = ['标注', '批注', '修订', '审校', '标出来', '注释', 'comment', 'annotate', 'review'];
  const REVISED_TARGET_NAME_HINTS = ['_revised', '-revised', ' revised', 'revised_', '修订', '修改', '批注', 'annotated', 'reviewed', 'commented', 'markup'];

  function workspaceRouteFiles(): any[] {
    const files = Array.isArray(state._aiFileContext) ? state._aiFileContext : [];
    return files.filter((file: any) => file && !file.loading && !file.error).slice(0, 8).map((file: any, idx: number) => ({
      path: previewText(file.path || '', 260),
      name: previewText(file.name || '', 180),
      type: previewText(file.type || file.file_type || '', 40),
      target: idx === state._aiTargetFileIdx || file.target === true,
      content_preview: previewText(typeof options.sampleTaskContext === 'function' ? options.sampleTaskContext(file.content || '') : String(file.content || ''), 700),
    }));
  }

  function currentOpenTaskFile(): TaskFileInfo | null {
    const name = String(state.fileName || '').trim();
    const path = String(state.filePath || state.wsSourcePath || '').trim();
    const type = String(state.fileType || '').trim();
    const id = String(state.fileId || '').trim();
    if (!name && !path && !type && !id) return null;
    const content = typeof options.getActiveEditorContent === 'function'
      ? previewText(options.getActiveEditorContent() || '', 6000)
      : '';
    return {
      path: path || id || name,
      name: name || baseNameFromPath(path || id),
      type,
      content,
      target: false,
    };
  }

  function mentionsAttachedFileContext(text: string): boolean {
    const source = String(text || '').trim();
    if (!source) return false;
    return /(?:附件|附加|已添加|添加的|分析文档|拖入|上传|attached|uploaded)/i.test(source);
  }

  function sameTaskFile(left: TaskFileInfo | null | undefined, right: TaskFileInfo | null | undefined): boolean {
    if (!left || !right) return false;
    const leftKey = normalizeTaskPath(left.path || left.name || '');
    const rightKey = normalizeTaskPath(right.path || right.name || '');
    return !!leftKey && !!rightKey && leftKey === rightKey;
  }

  function shouldForceFileTaskForWorkspaceContext(context: TaskContext, routeDecision: Record<string, any> | null): boolean {
    const route = String(routeDecision && routeDecision.route || '').trim().toLowerCase();
    if (route && !WORKSPACE_DIRECT_ROUTES.has(route)) return false;
    const text = String(context && context.text || '').trim();
    if (!text) return false;
    const hasFileContext = workspaceRouteFiles().length > 0 || !!String(context.pinnedSelText || '').trim();
    if (!hasFileContext) return false;
    return /(?:当前(?:打开的?)?(?:文件|文档|表格|演示稿)?|这个(?:文件|文档|表格|演示稿)|已打开|附件|选区|读取|阅读|查看|总结|概括|归纳|分析|检查|提取|改写|润色|翻译|批注|修订|写入|写回|修改|更新|处理|基于|文件|文档|表格|演示稿|pdf|docx?|xlsx?|pptx?|txt|md|csv)/i.test(text);
  }

  function fileTaskRouteDecision(routeSource: string, base?: Record<string, any> | null): Record<string, any> {
    return Object.assign({}, base || {}, {
      route_kind: WORKSPACE_FILE_TASK_KIND,
      base_task_type: 'COMPLEX_TASK',
      route: WORKSPACE_FILE_TASK_ROUTE,
      task_type: 'FILE_TASK',
      route_source: routeSource,
      keyword_policy: 'hint_only',
    });
  }

  function isDirectWorkspaceResponse(routeDecision: Record<string, any> | null): boolean {
    if (!routeDecision) return false;
    const routeKind = String(routeDecision.route_kind || '').trim().toLowerCase();
    const route = String(routeDecision.route || '').trim().toLowerCase();
    return routeKind === WORKSPACE_DIRECT_KIND && WORKSPACE_DIRECT_ROUTES.has(route);
  }

  function normalizeWorkspaceRouteDecision(data: any): Record<string, any> {
    const payload = data && typeof data === 'object' ? data : {};
    const route = String(payload.route || '').trim().toLowerCase();
    const legacyRoute = WORKSPACE_ROUTE_NAMES.has(route) ? route : WORKSPACE_FILE_TASK_ROUTE;
    const normalizedRoute = legacyRoute === 'open_file' ? WORKSPACE_FILE_TASK_ROUTE : legacyRoute;
    const routeKind = canonicalWorkspaceRouteKind(normalizedRoute, payload.route_kind);
    const rawTaskType = String(payload.task_type || '').trim().toUpperCase();
    const canonicalTaskType = canonicalWorkspaceTaskType(normalizedRoute, rawTaskType);
    const explicitSourceTaskType = String(payload.source_task_type || '').trim().toUpperCase();
    const sourceTaskType = explicitSourceTaskType || (rawTaskType && rawTaskType !== canonicalTaskType ? rawTaskType : '');
    return {
      ok: payload.ok !== false,
      route_kind: routeKind,
      base_task_type: routeKind === 'direct_response' ? 'DIRECT_RESPONSE' : 'COMPLEX_TASK',
      route: normalizedRoute,
      task_type: canonicalTaskType,
      source_task_type: sourceTaskType,
      confidence: Math.max(0, Math.min(1, Number(payload.confidence || 0) || 0)),
      reason: previewText(payload.reason || '', 280),
      target_path: previewText(payload.target_path || '', 260),
      hint: previewText(payload.hint || '', 180),
      route_source: previewText(payload.route_source || '', 160),
      keyword_policy: String(payload.keyword_policy || '').trim() || 'hint_only',
    };
  }

  function canonicalWorkspaceRouteKind(route: string, routeKind?: string): string {
    const normalizedRoute = String(route || '').trim().toLowerCase();
    const normalizedKind = String(routeKind || '').trim().toLowerCase();
    if (normalizedKind === WORKSPACE_DIRECT_KIND || normalizedKind === WORKSPACE_FILE_TASK_KIND) {
      if (normalizedKind === WORKSPACE_DIRECT_KIND && normalizedRoute === WORKSPACE_FILE_TASK_ROUTE) return WORKSPACE_FILE_TASK_KIND;
      if (normalizedKind === WORKSPACE_FILE_TASK_KIND && WORKSPACE_DIRECT_ROUTES.has(normalizedRoute)) return WORKSPACE_DIRECT_KIND;
      return normalizedKind;
    }
    return WORKSPACE_DIRECT_ROUTES.has(normalizedRoute) ? WORKSPACE_DIRECT_KIND : WORKSPACE_FILE_TASK_KIND;
  }

  function canonicalWorkspaceTaskType(route: string, taskType?: string): string {
    const normalizedRoute = String(route || '').trim().toLowerCase();
    const normalizedTask = String(taskType || '').trim().toUpperCase();
    if (normalizedRoute === 'web_search') return 'WEB_SEARCH';
    if (normalizedRoute === 'light_chat') return 'CHAT';
    if (normalizedRoute === WORKSPACE_FILE_TASK_ROUTE) return 'FILE_TASK';
    if (normalizedTask === 'CHAT' || normalizedTask === 'WEB_SEARCH') return normalizedTask;
    return 'FILE_TASK';
  }

  function shouldBypassWorkspaceRoute(context: TaskContext): boolean {
    const opts = context && context.options && typeof context.options === 'object' ? context.options : {};
    return !!(context && context.taskPayload) || !!opts.followup_context || !!opts.workflow_checkpoint;
  }

  async function resolveWorkspaceRouteIntent(context: TaskContext): Promise<Record<string, any>> {
    const body = {
      text: context.text,
      session_id: typeof options.getSessionId === 'function' ? options.getSessionId() : '',
      history: typeof options.getConversationHistory === 'function' ? options.getConversationHistory() : [],
      files: workspaceRouteFiles(),
      current_file: compactFollowupTaskFile(currentOpenTaskFile()),
      has_selection: !!String(context.pinnedSelText || '').trim(),
      selection_preview: previewText(context.pinnedSelText || '', 800),
      model_mode: typeof options.getModelMode === 'function' ? options.getModelMode() : '',
      model_id: typeof options.getSelectedCloudModelId === 'function' ? options.getSelectedCloudModelId() : '',
    };
    const response = await _csrfFetch('/api/workspace/ai/route-intent', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!response.ok) {
      throw new Error(await response.text().catch(() => `HTTP ${response.status}`));
    }
    return normalizeWorkspaceRouteDecision(await response.json().catch(() => null));
  }

  function renderAssistantText(loadingEl: HTMLElement | undefined, text: string): void {
    if (!loadingEl) return;
    const value = String(text || '');
    loadingEl.dataset!.rawText = value;
    const renderer = (window as any)._waRenderMarkdown;
    if (typeof renderer === 'function') {
      loadingEl.innerHTML = renderer(value);
      return;
    }
    if ((window as any).marked) {
      try {
        const sanitizer = (window as any)._sanitizeRenderedHtml;
        const html = (window as any).marked.parse(value);
        loadingEl.innerHTML = typeof sanitizer === 'function' ? sanitizer(html) : html;
        return;
      } catch { /* noop */ }
    }
    loadingEl.textContent = value;
  }

  function parseWorkspaceSseEvents(buffer: string, flush: boolean): { events: any[]; remainder: string } {
    const source = String(buffer || '').replace(/\r\n/g, '\n');
    const frames = source.split('\n\n');
    const remainder = flush ? '' : (frames.pop() || '');
    const completeFrames = flush ? frames.filter((frame) => frame.trim()) : frames;
    const events: any[] = [];
    completeFrames.forEach((frame) => {
      const dataLines = String(frame || '').split('\n')
        .filter((line) => line.startsWith('data:'))
        .map((line) => line.replace(/^data:\s?/, ''));
      if (!dataLines.length) return;
      try { events.push(JSON.parse(dataLines.join('\n'))); } catch { /* noop */ }
    });
    return { events, remainder };
  }

  function chatStreamLockedModel(): string {
    const mode = typeof options.getModelMode === 'function' ? String(options.getModelMode() || '').trim().toLowerCase() : '';
    if (mode === 'local') return 'local';
    const selected = typeof options.getSelectedCloudModelId === 'function' ? String(options.getSelectedCloudModelId() || '').trim() : '';
    return selected || 'cloud';
  }

  async function streamWorkspaceChatRoute(context: TaskContext, routeDecision: Record<string, any>): Promise<any> {
    const loadingEl = context.loadingEl;
    const route = String(routeDecision.route || '').trim();
    const lockedTask = route === 'web_search' ? 'WEB_SEARCH' : 'CHAT';
    const ctrl = new AbortController();
    let assistantText = '';
    state._streamAbortCtrl = ctrl;
    state.isLoading = true;
    if (typeof options.setStreamButton === 'function') options.setStreamButton(true);
    if (loadingEl) {
      loadingEl.classList.add('streaming');
      loadingEl.textContent = route === 'web_search' ? '正在检索…' : '正在思考…';
      loadingEl.dataset!.workspaceRoute = route;
      loadingEl.dataset!.workspaceRouteSource = String(routeDecision.route_source || '');
    }
    try {
      const response = await _csrfFetch('/api/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session: typeof options.getSessionId === 'function' ? options.getSessionId() : 'workspace_default',
          message: context.text,
          locked_task: lockedTask,
          locked_model: chatStreamLockedModel(),
          skills_enabled: false,
          workspace_route_intent: routeDecision,
        }),
        signal: ctrl.signal,
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      if (!response.body) throw new Error('响应流不可用');
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      while (true) {
        const chunk = await reader.read();
        if (chunk.done) break;
        buffer += decoder.decode(chunk.value, { stream: true });
        const parsed = parseWorkspaceSseEvents(buffer, false);
        buffer = parsed.remainder;
        parsed.events.forEach((evt) => {
          const type = String(evt && evt.type || '').trim();
          if (type === 'token') {
            assistantText += String(evt.content || evt.text || '');
            renderAssistantText(loadingEl, assistantText);
          } else if (type === 'error') {
            throw new Error(String(evt.message || evt.text || '对话失败'));
          }
        });
        if (context.msgs) context.msgs.scrollTop = context.msgs.scrollHeight;
      }
      const trailing = parseWorkspaceSseEvents(buffer, true);
      trailing.events.forEach((evt) => {
        const type = String(evt && evt.type || '').trim();
        if (type === 'token') {
          assistantText += String(evt.content || evt.text || '');
          renderAssistantText(loadingEl, assistantText);
        }
      });
      assistantText = assistantText.trim() || '已完成。';
      if (loadingEl) {
        loadingEl.classList.remove('streaming');
        renderAssistantText(loadingEl, assistantText);
      }
      appendAssistantConversationTurn(assistantText, {
        loadingEl,
        task_kind: route === 'web_search' ? 'web_search' : 'message',
        status: 'done',
        route_intent: routeDecision,
        skip_model_context: false,
      });
      return { routeId: route, assistantText, routeDecision };
    } catch (error: any) {
      const aborted = error && error.name === 'AbortError';
      assistantText = aborted ? '已停止。' : `对话失败：${error && error.message ? error.message : error}`;
      if (loadingEl) {
        loadingEl.classList.remove('streaming');
        renderAssistantText(loadingEl, assistantText);
      }
      appendAssistantConversationTurn(assistantText, {
        loadingEl,
        task_kind: route === 'web_search' ? 'web_search' : 'message',
        status: aborted ? 'cancelled' : 'error',
        route_intent: routeDecision,
      });
      return { routeId: route, assistantText, routeDecision, error };
    } finally {
      if (state._streamAbortCtrl === ctrl) state._streamAbortCtrl = null;
      state.isLoading = false;
      if (typeof options.setStreamButton === 'function') options.setStreamButton(false);
    }
  }

  function runTaskFlowRoute(context: TaskContext, routeDecision?: Record<string, any>): Promise<any> {
    const loadingEl = context.loadingEl;
    const streamTaskFlow = typeof options.streamTaskFlow === 'function' ? options.streamTaskFlow : null;
    if (typeof streamTaskFlow !== 'function') {
      const assistantText = '任务流程运行时未加载，请刷新后重试。';
      if (loadingEl) { loadingEl.classList.remove('streaming'); loadingEl.textContent = assistantText; loadingEl.dataset!.rawText = assistantText; }
      state.isLoading = false;
      if (typeof options.setStreamButton === 'function') options.setStreamButton(false);
      return Promise.resolve({ routeId: 'task-flow', assistantText });
    }
    const ctrl = new AbortController();
    const taskTurn = typeof options.beginAssistantTaskTurn === 'function'
      ? options.beginAssistantTaskTurn({ content: '文件任务已启动，正在建立执行流…', task_kind: 'file_task', status: 'streaming', skip_model_context: true, render: false })
      : null;
    const taskTurnId = taskTurn && taskTurn.id ? taskTurn.id : '';
    state._streamAbortCtrl = ctrl;
    state.isLoading = true;
    if (typeof options.setStreamButton === 'function') options.setStreamButton(true);
    const routedContext = routeDecision
      ? Object.assign({}, context, {
          options: Object.assign({}, context.options || {}, {
            workspace_route_intent: routeDecision,
            router_policy: 'model_primary_intent',
          }),
        })
      : context;
    const payload = buildWhiteboxTaskPayload(context.text, context.pinnedSelText, context.pinnedSelSource, routedContext);
    if (loadingEl) {
      setTaskFollowupPayload(loadingEl, payload);
      setPendingTaskResumePayload(loadingEl, payload);
    }
    return Promise.resolve(streamTaskFlow!({
      payload, msgs: context.msgs, loadingEl, signal: ctrl.signal, abortController: ctrl,
      onTaskCardSnapshot: (card: HTMLElement) => {
        setTaskFollowupPayload(card, payload);
        setPendingTaskResumePayload(card, payload);
        if (!taskTurnId || typeof options.syncAssistantTaskTurn !== 'function') return;
        options.syncAssistantTaskTurn(taskTurnId, Object.assign({ loadingEl: card, task_kind: 'file_task', status: 'streaming', skip_model_context: true }, taskTurnMetadataFromLoadingEl(card)));
      },
    })).then((streamResult: any) => {
      const assistantText = finalizeWhiteboxTaskTurn(taskTurnId, loadingEl, streamResult, 'done', false);
      persistTaskTurn(context.text, assistantText, taskTurnMetadataFromLoadingEl(loadingEl), payload.files || [], loadingEl);
      return { routeId: 'task-flow', assistantText, payload, result: streamResult, routeDecision };
    }).catch((error: any) => {
      const aborted = error && error.name === 'AbortError';
      const assistantText = aborted ? '任务已停止。' : (error && error.waTaskError ? error.message : `任务流失败：${error && error.message ? error.message : error}`);
      if (loadingEl) { loadingEl.classList.remove('streaming'); loadingEl.textContent = assistantText; loadingEl.dataset!.rawText = assistantText; }
      finalizeWhiteboxTaskTurn(taskTurnId, loadingEl, { summary: assistantText, status: aborted ? 'cancelled' : 'error' }, aborted ? 'cancelled' : 'error', true);
      persistTaskTurn(context.text, assistantText, Object.assign({
        status: aborted ? 'cancelled' : 'error',
      }, taskTurnMetadataFromLoadingEl(loadingEl)), [], loadingEl);
      return { routeId: 'task-flow', assistantText, error, routeDecision };
    }).finally(() => {
      if (state._streamAbortCtrl === ctrl) state._streamAbortCtrl = null;
      state.isLoading = false;
      if (typeof options.setStreamButton === 'function') options.setStreamButton(false);
    });
  }

  async function runWorkspaceModelRoutedTask(context: TaskContext): Promise<any> {
    if (shouldBypassWorkspaceRoute(context)) {
      return runTaskFlowRoute(context, fileTaskRouteDecision('explicit_task_payload'));
    }
    if (context.loadingEl) context.loadingEl.textContent = '正在判断…';
    let routeDecision: Record<string, any> | null = null;
    try {
      routeDecision = await resolveWorkspaceRouteIntent(context);
    } catch (error) {
      console.warn('[WA] workspace route intent failed, falling back to file task:', error);
    }
    if (shouldForceFileTaskForWorkspaceContext(context, routeDecision)) {
      routeDecision = fileTaskRouteDecision('frontend_file_context_guard', routeDecision);
    }
    if (isDirectWorkspaceResponse(routeDecision)) {
      return streamWorkspaceChatRoute(context, routeDecision);
    }
    return runTaskFlowRoute(context, routeDecision || undefined);
  }

  registerMessageRoute({
    id: 'task-flow',
    priority: -100,
    match() { return true; },
    run(context: TaskContext) {
      return runWorkspaceModelRoutedTask(context);
    },
  });

  function appendAssistantConversationTurn(text: string, metadata: Record<string, any>): void {
    const content = String(text || '').trim();
    if (!content) return;
    const payload = metadata || {};
    if (typeof options.appendAssistantTurn === 'function') {
      options.appendAssistantTurn(content, Object.assign({ task_kind: payload.task_kind || 'file_task', status: payload.status || 'done' }, payload));
      return;
    }
    if (!Array.isArray(state.conversation)) state.conversation = [];
    const last = state.conversation[state.conversation.length - 1];
    if (last && last.role === 'assistant' && String(last.content || '').trim() === content) return;
    state.conversation.push(Object.assign({ role: 'assistant', content }, payload));
  }

  function taskCardSnapshotFromElement(element?: HTMLElement): Record<string, string> | null {
    if (!element || !element.classList || !element.classList.contains('wa-task-run')) return null;
    return {
      html: element.outerHTML,
      fatal_error_text: String((element as any)._fatalErrorText || ''),
    };
  }

  function persistTaskTurn(userText: string, assistantText: string, metadata?: Record<string, any>, attachments?: any[], taskCard?: HTMLElement): void {
    if (typeof options.persistTaskTurn !== 'function') return;
    const request = String(userText || '').trim();
    const content = String(assistantText || '').trim();
    if (!request || !content) return;
    const snapshot = taskCardSnapshotFromElement(taskCard);
    const record: Record<string, any> = {
      user: request,
      assistant: content,
      attachments: Array.isArray(attachments) ? attachments : [],
      metadata: metadata || {},
    };
    if (snapshot) record.task_card_snapshot = snapshot;
    Promise.resolve(options.persistTaskTurn(record)).catch(() => { /* best effort */ });
  }

  function taskTurnMetadataFromLoadingEl(loadingEl?: HTMLElement): Record<string, any> {
    const dataset = loadingEl && loadingEl.dataset ? loadingEl.dataset : null;
    if (!dataset) return {};
    const metadata: Record<string, any> = {};
    const taskUiState = loadingEl && (loadingEl as any)._taskUiState && typeof (loadingEl as any)._taskUiState === 'object' ? (loadingEl as any)._taskUiState : null;
    if (dataset.taskId) metadata.task_id = String(dataset.taskId || '').trim();
    if (dataset.taskRunId) metadata.run_id = String(dataset.taskRunId || '').trim();
    if (dataset.taskRequest) metadata.task_request = String(dataset.taskRequest || '').trim();
    if (dataset.taskMode) metadata.task_mode = String(dataset.taskMode || '').trim();
    if (dataset.taskRequestKind) metadata.task_request_kind = String(dataset.taskRequestKind || '').trim();
    if (dataset.taskFamily) metadata.task_family = String(dataset.taskFamily || '').trim();
    if (dataset.taskOperationKind) metadata.task_operation_kind = String(dataset.taskOperationKind || '').trim();
    if (dataset.taskExecutionMode) metadata.task_execution_mode = String(dataset.taskExecutionMode || '').trim();
    if (dataset.taskSelectedRecipe) metadata.task_selected_recipe = String(dataset.taskSelectedRecipe || '').trim();
    if (dataset.taskOutputMode) metadata.task_output_mode = String(dataset.taskOutputMode || '').trim();
    if (dataset.taskIntentStrategy) metadata.task_intent_strategy = String(dataset.taskIntentStrategy || '').trim();
    if (Object.prototype.hasOwnProperty.call(dataset, 'taskIntentCanApply')) {
      metadata.task_intent_can_apply = String(dataset.taskIntentCanApply || '').trim().toLowerCase() === 'true';
    }
    if (Object.prototype.hasOwnProperty.call(dataset, 'taskIntentRequiresConfirmation')) {
      metadata.task_intent_requires_confirmation = String(dataset.taskIntentRequiresConfirmation || '').trim().toLowerCase() === 'true';
    }
    if (dataset.taskTargetFileType) metadata.task_target_file_type = String(dataset.taskTargetFileType || '').trim();
    const taskContract = (window as any).WA && typeof (window as any).WA.decodeTaskContract === 'function'
      ? (window as any).WA.decodeTaskContract(dataset.taskContract || '') : null;
    if (taskContract) metadata.task_contract = taskContract;
    if (Object.prototype.hasOwnProperty.call(dataset, 'taskClassificationConfidence')) {
      const confidence = Number(dataset.taskClassificationConfidence || '');
      if (Number.isFinite(confidence) && confidence >= 0) metadata.task_classification_confidence = confidence;
    }
    if (dataset.taskClassificationReasons) {
      try { metadata.task_classification_reasons = JSON.parse(String(dataset.taskClassificationReasons || '').trim()); } catch { /* noop */ }
    }
    if (dataset.taskTerminalStatus) metadata.task_terminal_status = String(dataset.taskTerminalStatus || '').trim();
    if (dataset.taskPendingResumeLabel) metadata.pending_task_label = String(dataset.taskPendingResumeLabel || '').trim();
    if (dataset.taskPendingResumePayload) {
      try { metadata.pending_task_payload = JSON.parse(decodeURIComponent(String(dataset.taskPendingResumePayload || '').trim())); } catch { /* noop */ }
    }
    if (dataset.taskFollowupPayload) {
      try {
        metadata.task_request_payload = JSON.parse(decodeURIComponent(String(dataset.taskFollowupPayload || '').trim()));
        if (metadata.task_request_payload && metadata.task_request_payload.task_context) {
          metadata.task_context = compactTaskContext(metadata.task_request_payload.task_context);
        }
      } catch { /* noop */ }
    }
    if (taskUiState && Array.isArray(taskUiState.fileChanges) && taskUiState.fileChanges.length) {
      try { metadata.task_file_changes = JSON.parse(JSON.stringify(taskUiState.fileChanges.slice(-8))); } catch { /* noop */ }
    }
    const taskVisibleTrace = taskCardVisibleTrace(loadingEl);
    if (taskVisibleTrace) metadata.task_visible_trace = taskVisibleTrace;
    const testStructure = taskCardTestStructure(loadingEl);
    if (testStructure) metadata.test_structure = testStructure;
    if (Object.prototype.hasOwnProperty.call(dataset, 'taskCompleted')) {
      metadata.completed_task = String(dataset.taskCompleted || '').trim().toLowerCase() === 'true';
    }
    return metadata;
  }

  function taskCardCheckLine(value: unknown): string {
    let text = String(value || '').replace(/\s+/g, ' ').trim();
    if (!text) return '';
    if (/完整结果见对话汇报|结果见对话汇报|任务已完成，?完整结果/u.test(text)) return '';
    text = text.replace(/^(进行中|完成|待处理|失败|警告)\s*/u, '').trim();
    if (/whitebox_v1.*开始执行任务/u.test(text)) return '任务流已启动';
    if (/决策已完成执行决策/u.test(text)) return '模型决策已完成';
    if (/Model planning and tool use/i.test(text)) return '模型正在规划并选择工具';
    if (/Round \d+ complete/i.test(text)) return '本轮执行已完成';
    if (/Loaded \d+ context snippet/i.test(text)) return '已读取必要上下文';
    if (/模型调用路由.*文件任务/u.test(text)) return 'AI 已判断为文件任务';
    return previewText(text, 180);
  }

  function taskCardTestStructure(loadingEl?: HTMLElement): Record<string, any> | null {
    if (!loadingEl || !loadingEl.querySelectorAll || !loadingEl.classList || !loadingEl.classList.contains('wa-task-run')) return null;
    const dataset = loadingEl.dataset || {};
    const steps = Array.from(loadingEl.querySelectorAll('.wa-task-step')).map((step: Element) => {
      const el = step as HTMLElement;
      const title = String(el.querySelector('.wa-task-step-title')?.textContent || '').trim() || String(el.dataset.stepId || '').trim() || '步骤';
      const status = el.classList.contains('failed') ? 'failed'
        : el.classList.contains('done') ? 'done'
          : el.classList.contains('running') ? 'running'
            : 'pending';
      const checks = Array.from(el.querySelectorAll('.wa-task-row'))
        .map((row: Element) => taskCardCheckLine((row as HTMLElement).innerText || row.textContent || ''))
        .filter(Boolean)
        .slice(-4);
      return {
        id: String(el.dataset.stepId || '').trim(),
        title,
        status,
        checks,
      };
    }).filter((step: any) => step.id || step.title || step.checks.length);
    const terminal = String(dataset.taskTerminalStatus || '').trim();
    const completed = Object.prototype.hasOwnProperty.call(dataset, 'taskCompleted')
      ? String(dataset.taskCompleted || '').trim().toLowerCase() === 'true'
      : terminal === 'completed' || terminal === 'verified';
    const summaryEl = loadingEl.querySelector('[data-role="summary"]') as HTMLElement | null;
    const finalSummary = previewText(
      String(dataset.taskSummary || (summaryEl && (summaryEl.innerText || summaryEl.textContent)) || '').replace(/\s+/g, ' ').trim(),
      900,
    );
    return {
      schema: 'koto_ai_task_chain_test_v1',
      entrypoint: '工作区输入框 -> AI 意图判断 -> 文件任务流 -> 监管执行',
      route_policy: 'AI 先判断任务类型',
      supervisor_policy: '每一步执行后验证',
      technical_entrypoint: 'workspace.sendMessage -> taskDispatcher.dispatchMessage -> route-intent -> task-stream -> FileTaskRuntime',
      technical_route_policy: 'model_primary_intent',
      technical_supervisor_policy: 'plan_step_verification_required',
      task_id: String(dataset.taskId || '').trim(),
      run_id: String(dataset.taskRunId || '').trim(),
      request: String(dataset.taskRequest || '').trim(),
      final_summary: finalSummary,
      mode: String(dataset.taskMode || '').trim(),
      request_kind: String(dataset.taskRequestKind || '').trim(),
      task_family: String(dataset.taskFamily || '').trim(),
      operation_kind: String(dataset.taskOperationKind || '').trim(),
      execution_mode: String(dataset.taskExecutionMode || '').trim(),
      output_mode: String(dataset.taskOutputMode || '').trim(),
      terminal_status: terminal,
      completed_task: completed,
      step_count: steps.length,
      steps,
    };
  }

  function taskCardVisibleTrace(loadingEl?: HTMLElement): string {
    if (!loadingEl || !loadingEl.querySelector) return '';
    const parts: string[] = [];
    const summaryEl = loadingEl.querySelector('[data-role="summary"]');
    const summaryText = previewText(summaryEl && (summaryEl as HTMLElement).innerText ? (summaryEl as HTMLElement).innerText : '', 900);
    const contextText = taskCardStepTrace(loadingEl, 'context', 420);
    const executeText = taskCardStepTrace(loadingEl, 'execute', 560);
    const checkText = taskCardStepTrace(loadingEl, 'check', 420);
    if (summaryText) parts.push(`结果：${summaryText}`);
    if (contextText) parts.push(`上下文：${contextText}`);
    if (executeText) parts.push(`执行：${executeText}`);
    if (checkText) parts.push(`检查：${checkText}`);
    return parts.join('\n');
  }

  function taskCardStepTrace(loadingEl: HTMLElement, stepId: string, limit: number): string {
    if (!loadingEl || !loadingEl.querySelector) return '';
    const body = loadingEl.querySelector(`.wa-task-step[data-step-id="${stepId}"] .wa-task-step-body`);
    return previewText(body && (body as HTMLElement).innerText ? (body as HTMLElement).innerText : '', limit);
  }

  function finalizeWhiteboxTaskTurn(taskTurnId: string, loadingEl: HTMLElement | undefined, result: any, fallbackStatus: string, skipModelContext: boolean): string {
    const payload = result && typeof result === 'object' ? result : { summary: result };
    const assistantText = String(payload.summary || '').trim() || '文件任务流已完成。';
    if (loadingEl && loadingEl.dataset) loadingEl.dataset.rawText = assistantText;
    const turnMetadata = Object.assign({
      content: assistantText, loadingEl, task_kind: 'file_task',
      status: String(payload.status || fallbackStatus || 'done').trim() || 'done',
      skip_model_context: !!skipModelContext,
    }, taskTurnMetadataFromLoadingEl(loadingEl));
    if (taskTurnId && typeof options.syncAssistantTaskTurn === 'function') {
      options.syncAssistantTaskTurn(taskTurnId, turnMetadata);
    } else {
      appendAssistantConversationTurn(assistantText, turnMetadata);
    }
    return assistantText;
  }

  function buildWhiteboxTaskPayload(text: string, pinnedSelText?: string, pinnedSelSource?: string, overrides?: any): Record<string, any> {
    const requestOverrides = overrides || {};
    const explicitTaskPayload = cloneTaskPayload(requestOverrides.taskPayload);
    const overrideOptions: Record<string, any> = requestOverrides.options && typeof requestOverrides.options === 'object'
      ? Object.assign({}, requestOverrides.options) : {};
    if (!Object.prototype.hasOwnProperty.call(overrideOptions, 'enable_ai_intent_adjudicator')) {
      overrideOptions.enable_ai_intent_adjudicator = true;
    }
    overrideOptions.router_policy = overrideOptions.router_policy || 'model_primary_intent';

    if (explicitTaskPayload) {
      return finalizeExplicitTaskPayload(explicitTaskPayload, text, pinnedSelText, pinnedSelSource, overrideOptions, requestOverrides);
    }

    const resumedTaskPayload = implicitResumeTaskPayload(text);
    if (resumedTaskPayload) {
      return finalizeExplicitTaskPayload(resumedTaskPayload, text, pinnedSelText, pinnedSelSource, overrideOptions, requestOverrides);
    }

    const rawFiles: TaskFileInfo[] = Array.isArray(state._aiFileContext)
      ? state._aiFileContext.filter((f: any) => f && !f.loading).map((file: any, idx: number) => ({
          path: file.path || '', name: file.name || '', type: file.type || file.file_type || '',
          content: typeof options.sampleTaskContext === 'function' ? options.sampleTaskContext(file.content || '') : String(file.content || ''),
          target: idx === state._aiTargetFileIdx,
        }))
      : [];
    const currentFile = currentOpenTaskFile();

    let targetFile = rawFiles.find((f) => f.target) || null;
    const explicitTextTargetPath = explicitWriteTargetPathFromText(text);
    if (explicitTextTargetPath) {
      const explicitTargetKey = normalizeTaskPath(explicitTextTargetPath);
      rawFiles.forEach((f) => { f.target = !!normalizeTaskPath(f.path || f.name || '') && normalizeTaskPath(f.path || f.name || '') === explicitTargetKey; });
      targetFile = rawFiles.find((f) => f.target) || null;
      if (!targetFile) {
        targetFile = {
          path: explicitTextTargetPath,
          name: baseNameFromPath(explicitTextTargetPath),
          type: fileTypeFromPath(explicitTextTargetPath),
          content: '',
          target: true,
        };
        rawFiles.push(targetFile);
      }
    }
    const inferredAttachedTargetFile = !targetFile ? inferAttachedWriteTargetFile(text, rawFiles) : null;
    if (!targetFile && inferredAttachedTargetFile) {
      const inferredTargetKey = normalizeTaskPath(inferredAttachedTargetFile.path || inferredAttachedTargetFile.name || '');
      rawFiles.forEach((f) => { f.target = !!normalizeTaskPath(f.path || f.name || '') && normalizeTaskPath(f.path || f.name || '') === inferredTargetKey; });
      targetFile = rawFiles.find((f) => f.target) || null;
    }
    const inferredTargetPath = targetFile ? (targetFile.path || targetFile.name || '') : explicitTextTargetPath;
    const inferredFileName = targetFile ? (targetFile.name || '') : baseNameFromPath(explicitTextTargetPath);
    const inferredFileType = targetFile ? (targetFile.type || targetFile.file_type || '') : fileTypeFromPath(explicitTextTargetPath);
    const followupContext = buildTaskFollowupContext(text);
    if (followupContext && !overrideOptions.followup_context) overrideOptions.followup_context = followupContext;
    if (targetFile && !overrideOptions.inferred_target_file_type) overrideOptions.inferred_target_file_type = canonicalTaskFileType(targetFile);
    const taskContext = buildTaskContextPackage({
      task: text, files: rawFiles, currentFile, targetFile, selection: pinnedSelText || '',
      selectionSource: pinnedSelSource || '', followupContext: overrideOptions.followup_context || null,
      workflowCheckpoint: overrideOptions.workflow_checkpoint || null,
    });
    const payload: Record<string, any> = {
      task: text, session_id: typeof options.getSessionId === 'function' ? options.getSessionId() : '',
      selection: pinnedSelText || '', selection_source: pinnedSelSource || '', files: rawFiles,
      target_path: inferredTargetPath, file_name: inferredFileName, file_type: inferredFileType,
      current_file: currentFile,
      task_context: taskContext, model_mode: typeof options.getModelMode === 'function' ? options.getModelMode() : 'auto',
      model_id: typeof options.getSelectedCloudModelId === 'function' ? options.getSelectedCloudModelId() : '',
      options: overrideOptions,
      history: typeof options.getConversationHistory === 'function' ? options.getConversationHistory() : (Array.isArray(state.conversation) ? state.conversation.slice(-12) : []),
    };
    if (requestOverrides.model_mode) payload.model_mode = requestOverrides.model_mode;
    if (requestOverrides.model_id) payload.model_id = requestOverrides.model_id;
    if (taskRequestsStepwiseConfirmation(text) && !payload.options.workflow_checkpoint) {
      const stepwisePayload = ensureStepwiseResumePayload(payload, text);
      if (stepwisePayload) return stepwisePayload;
    }
    return payload;
  }

  function finalizeExplicitTaskPayload(taskPayload: any, text: string, pinnedSelText?: string, pinnedSelSource?: string, overrideOptions?: Record<string, any>, requestOverrides?: any): Record<string, any> | null {
    const explicitTaskPayload = cloneTaskPayload(taskPayload);
    if (!explicitTaskPayload) return null;
    const explicitOptions = explicitTaskPayload.options && typeof explicitTaskPayload.options === 'object' ? Object.assign({}, explicitTaskPayload.options) : {};
    explicitTaskPayload.task = String(explicitTaskPayload.task || text || '').trim();
    explicitTaskPayload.selection = Object.prototype.hasOwnProperty.call(explicitTaskPayload, 'selection') ? explicitTaskPayload.selection : (pinnedSelText || '');
    explicitTaskPayload.selection_source = Object.prototype.hasOwnProperty.call(explicitTaskPayload, 'selection_source') ? explicitTaskPayload.selection_source : (pinnedSelSource || '');
    explicitTaskPayload.file_name = explicitTaskPayload.file_name || state.fileName || '';
    explicitTaskPayload.file_type = explicitTaskPayload.file_type || state.fileType || '';
    explicitTaskPayload.session_id = explicitTaskPayload.session_id || (typeof options.getSessionId === 'function' ? options.getSessionId() : '');
    explicitTaskPayload.options = Object.assign({}, explicitOptions, overrideOptions);
    if (!Array.isArray(explicitTaskPayload.history)) {
      explicitTaskPayload.history = typeof options.getConversationHistory === 'function' ? options.getConversationHistory() : (Array.isArray(state.conversation) ? state.conversation.slice(-12) : []);
    }
    const explicitFiles = Array.isArray(explicitTaskPayload.files) ? explicitTaskPayload.files.filter((f: any) => f && typeof f === 'object') : [];
    const explicitSelectionText = String(explicitTaskPayload.selection || '').trim();
    if (!explicitSelectionText && Object.prototype.hasOwnProperty.call(explicitTaskPayload, 'current_file')) delete explicitTaskPayload.current_file;
    const explicitFollowupContext = explicitTaskPayload.options && typeof explicitTaskPayload.options === 'object' ? explicitTaskPayload.options.followup_context : null;
    const existingTaskContext = explicitTaskPayload.task_context && typeof explicitTaskPayload.task_context === 'object' ? explicitTaskPayload.task_context : {};
    const existingTaskContextFiles = existingTaskContext.files && typeof existingTaskContext.files === 'object' ? existingTaskContext.files : {};
    explicitTaskPayload.task_context = buildTaskContextPackage({
      task: explicitTaskPayload.task, files: explicitFiles, currentFile: explicitTaskPayload.current_file || null,
      targetFile: explicitFiles.find((f: any) => f && f.target) || existingTaskContextFiles.target || null,
      selection: explicitTaskPayload.selection || '', selectionSource: explicitTaskPayload.selection_source || '',
      followupContext: explicitFollowupContext, workflowCheckpoint: explicitTaskPayload.options && explicitTaskPayload.options.workflow_checkpoint,
    });
    if (requestOverrides.model_mode) explicitTaskPayload.model_mode = requestOverrides.model_mode;
    if (requestOverrides.model_id) explicitTaskPayload.model_id = requestOverrides.model_id;
    return explicitTaskPayload;
  }

  function implicitResumeTaskPayload(text: string): any {
    if (!looksLikePendingTaskResume(text)) return null;
    const pendingTurn = latestPendingTaskResumeTurn();
    if (!pendingTurn) return null;
    return cloneTaskPayload(pendingTurn.pending_task_payload);
  }

  function latestPendingTaskResumeTurn(): any {
    const turns = Array.isArray(state.conversation) ? state.conversation : [];
    for (let index = turns.length - 1; index >= 0; index -= 1) {
      const turn = turns[index];
      if (!turn || String(turn.role || '').trim() !== 'assistant') continue;
      if (String(turn.task_kind || '').trim() !== 'file_task') continue;
      const pendingPayload = turn.pending_task_payload;
      if (!pendingPayload || typeof pendingPayload !== 'object') continue;
      const terminalStatus = String(turn.task_terminal_status || '').trim().toLowerCase();
      if (terminalStatus && terminalStatus !== 'awaiting_confirmation') continue;
      return turn;
    }
    return null;
  }

  function looksLikePendingTaskResume(text: string): boolean {
    const source = String(text || '').trim();
    if (!source) return false;
    if (source.length > 80) return false;
    if (looksLikeTaskCritique(source)) return false;
    if (/^(继续|继续吧|开始|开始吧|确认|确认执行|下一步|下一批|执行|执行吧|可以|好|好的|行|ok|okay|yes|go|run|continue)$/i.test(source)) return true;
    return /(继续|开始|执行|确认).{0,10}(下一步|下一批|第\s*\d+\s*(?:\/\s*\d+\s*批?|批))/i.test(source)
      || /(下一步|下一批|第\s*\d+\s*(?:\/\s*\d+\s*批?|批)).{0,10}(继续|开始|执行|确认)/i.test(source);
  }

  function looksLikeTaskCritique(text: string): boolean {
    const source = String(text || '').trim();
    if (!source) return false;
    if (looksLikeDiagnosticLead(source)) return true;
    if (looksLikeTaskFollowupContinuation(source)) return true;
    if (source.length > 240) return false;
    if (looksLikeStandaloneTaskInstruction(source)) return false;
    return /(为什么|为啥|为何|怎么会|怎么没有|为什么没有|为什么没|不对|不太对|有问题|结果不好|结果很差|不行|不满意|错了|哪里不对|解释一下|说明一下|给我解释|依据是什么|原因是什么|你这是|你为什么|为什么这么|为什么这样|质疑|反馈|review this result|why did you|this is wrong|not good|bad result|explain this)/i.test(source);
  }

  function looksLikeDiagnosticLead(text: string): boolean {
    const source = String(text || '').trim();
    if (!source) return false;
    if (source.length > 240) return false;
    return /^(?:为什么|为啥|为何|怎么会|怎么没有|为什么没有|为什么没|失败原因|原因是什么|怎么回事|哪里出了问题|请解释|解释一下|说明一下|帮我解释|帮我说明)/i.test(source)
      || /^(?:这个任务|这次任务|这个结果|这次结果|上一轮|上次|这轮|这个流程|这次审校).{0,18}(?:为什么|为啥|为何|失败|出错|不对|有问题)/i.test(source)
      || ((/(?:上一轮|上次|这次|这个任务|这个结果|这次任务|这次结果)/i.test(source) || /(?:任务|结果|审校|修订|写回|批注|修改|删除|失败|报错|权限|permission denied)/i.test(source))
        && /(?:为什么|为啥|为何|解释|说明|失败|问题|不对|怎么会|怎么没有)/i.test(source));
  }

  function looksLikePreviousTaskReference(text: string): boolean {
    const source = String(text || '').trim();
    if (!source) return false;
    return /(?:上一轮|上一版|上一次|上次|前一轮|刚才|这次|这个任务|这次任务|这个结果|这次结果|上一轮结果|上一轮建议|上一轮审校|上一轮处理|当前结果|当前方案)/i.test(source);
  }

  function looksLikeTaskFollowupContinuation(text: string): boolean {
    const source = String(text || '').trim();
    if (!source) return false;
    if (source.length > 240) return false;
    if (!looksLikePreviousTaskReference(source)) return false;
    return /(?:继续|再|重新|重做|重写|补充|优化|改进|修复|调整|完善|细化|补强|按上一轮|按建议|按方案|应用建议|直接应用|继续处理|继续执行|重新分析|重新总结|再分析|再总结|continue|improve|refine|fix|apply)/i.test(source);
  }

  function looksLikeStandaloneTaskInstruction(text: string): boolean {
    const source = String(text || '').trim();
    if (!source) return false;
    if (looksLikePreviousTaskReference(source)) return false;
    return /^(?:帮我|请|麻烦|需要|把|将|给我|新建|打开|创建|生成|导出|翻译|润色|审校|批注|写入|保存|插入|删除|替换|修改|重写|create|write|edit|revise|translate|export|save|insert|replace|open)/i.test(source)
      || /(?:新建|打开|创建|生成|导出|翻译|润色|审校|批注|写入|保存|插入|删除|替换|修改|重写).{0,20}(?:文件|文档|表格|工作表|演示稿|ppt|docx|xlsx|pdf|slide|sheet)/i.test(source);
  }

  function buildTaskFollowupContext(text: string): Record<string, any> | null {
    if (!looksLikeTaskCritique(text)) return null;
    const previousTaskTurn = latestCompletedFileTaskTurn();
    if (!previousTaskTurn) return null;
    const previousUserTurn = latestUserTurnBefore(previousTaskTurn);
    const previousTaskVisibleTrace = previewText(previousTaskTurn.task_visible_trace || '', 1600);
    const previousTaskSummary = previousTaskVisibleTrace
      ? previewText(`${previousTaskTurn.content || ''}\n\n任务轨迹：\n${previousTaskVisibleTrace}`, 2000)
      : previewText(previousTaskTurn.content || '', 2000);
    const context: Record<string, any> = {
      kind: 'review_last_task', followup_action: inferTaskFollowupAction(text), source: 'workspace_task_dispatcher',
      user_feedback: previewText(text, 1000), previous_task_summary: previousTaskSummary,
      previous_task_status: String(previousTaskTurn.status || 'done').trim() || 'done',
      previous_task_timestamp: String(previousTaskTurn.timestamp || '').trim(),
      previous_user_request: previousUserTurn ? previewText(previousUserTurn.content || '', 1500) : '',
    };
    const previousRunId = previewText(previousTaskTurn.run_id || previousTaskTurn.task_run_id || '', 128);
    const previousTaskRequest = previewText(previousTaskTurn.task_request || (previousUserTurn ? previousUserTurn.content || '' : ''), 1500);
    const previousTaskMode = previewText(previousTaskTurn.task_mode || '', 120);
    const previousTaskRequestKind = previewText(previousTaskTurn.task_request_kind || '', 120);
    const previousTaskFamily = previewText(previousTaskTurn.task_family || '', 120);
    const previousTaskOperationKind = previewText(previousTaskTurn.task_operation_kind || '', 120);
    const previousTaskExecutionMode = previewText(previousTaskTurn.task_execution_mode || '', 120);
    const previousTaskSelectedRecipe = previewText(previousTaskTurn.task_selected_recipe || '', 160);
    const previousTaskOutputMode = previewText(previousTaskTurn.task_output_mode || '', 120);
    const previousTaskFileChanges = Array.isArray(previousTaskTurn.task_file_changes) ? previousTaskTurn.task_file_changes.filter((i: any) => i && typeof i === 'object').slice(-8) : [];
    const previousTaskContext = compactTaskContext(previousTaskTurn.task_context);
    if (previousRunId) context.previous_run_id = previousRunId;
    if (previousTaskRequest) context.previous_task_request = previousTaskRequest;
    if (previousTaskMode) context.previous_task_mode = previousTaskMode;
    if (previousTaskRequestKind) context.previous_task_request_kind = previousTaskRequestKind;
    if (previousTaskFamily) context.previous_task_family = previousTaskFamily;
    if (previousTaskOperationKind) context.previous_task_operation_kind = previousTaskOperationKind;
    if (previousTaskExecutionMode) context.previous_task_execution_mode = previousTaskExecutionMode;
    if (previousTaskSelectedRecipe) context.previous_task_selected_recipe = previousTaskSelectedRecipe;
    if (previousTaskOutputMode) context.previous_task_output_mode = previousTaskOutputMode;
    if (previousTaskContext) context.previous_task_context = previousTaskContext;
    if (previousTaskFileChanges.length) context.previous_task_file_changes = previousTaskFileChanges;
    return context;
  }

  function inferTaskFollowupAction(text: string): string {
    const source = String(text || '').trim();
    if (!source) return 'question';
    if (looksLikePreviousTaskReference(source) && /(?:直接应用|应用建议|按上一轮|按建议|按方案|apply)/i.test(source)) return 'apply';
    if (looksLikeTaskFollowupContinuation(source)) return 'improve';
    return 'question';
  }

  function latestCompletedFileTaskTurn(): any {
    const turns = Array.isArray(state.conversation) ? state.conversation : [];
    for (let index = turns.length - 1; index >= 0; index -= 1) {
      const turn = turns[index];
      if (!turn || String(turn.role || '').trim() !== 'assistant') continue;
      if (String(turn.task_kind || '').trim() !== 'file_task') continue;
      if (String(turn.status || '').trim() && String(turn.status || '').trim() !== 'done') continue;
      return turn;
    }
    return null;
  }

  function latestUserTurnBefore(turn: any): any {
    const turns = Array.isArray(state.conversation) ? state.conversation : [];
    const targetIndex = turns.indexOf(turn);
    if (targetIndex <= 0) return null;
    for (let index = targetIndex - 1; index >= 0; index -= 1) {
      const candidate = turns[index];
      if (candidate && String(candidate.role || '').trim() === 'user' && String(candidate.content || '').trim()) return candidate;
    }
    return null;
  }

  function taskRequestsStepwiseConfirmation(text: string): boolean {
    const source = String(text || '').trim();
    if (!source) return false;
    return /(?:每完成一步|每一步(?:完成)?后|分步|一步一步|拆分成很多个小任务).{0,40}(?:汇报|告诉|通知|停|暂停|等我|确认|继续)/i.test(source)
      || /(?:等我(?:来说)?继续|我来说继续|等我确认|确认后继续|等待(?:我|用户)?确认|回复继续|说继续|我说继续)/i.test(source)
      || /(?:完成一步|每步|当前步骤).{0,30}(?:等待|待确认|确认|继续下一步)/i.test(source);
  }

  function ensureStepwiseResumePayload(payload: any, text: string): any {
    if (!payload || typeof payload !== 'object') return null;
    const cloned = cloneTaskPayload(payload);
    if (!cloned) return null;
    const options = cloned.options && typeof cloned.options === 'object' ? Object.assign({}, cloned.options) : {};
    const existingWorkflowCheckpoint = options.workflow_checkpoint && typeof options.workflow_checkpoint === 'object' ? Object.assign({}, options.workflow_checkpoint) : {};
    const checkpointSeed = existingWorkflowCheckpoint;
    const hasExplicitStepIndex = Object.prototype.hasOwnProperty.call(checkpointSeed, 'step_index') && checkpointSeed.step_index !== '' && checkpointSeed.step_index != null;
    const currentStep = Math.max(0, Number(checkpointSeed.step_index || 0) || 0);
    const resumeStepIndex = hasExplicitStepIndex ? currentStep : currentStep + 1;
    delete options.batch_control;
    options.workflow_checkpoint = Object.assign({}, existingWorkflowCheckpoint, {
      adapter: String(checkpointSeed.adapter || 'generic_tool_loop').trim() || 'generic_tool_loop',
      policy: 'confirm_each_step', step_index: resumeStepIndex,
      original_task: String(checkpointSeed.original_task || text || cloned.task || '').trim(),
    });
    const followupContext = options.followup_context && typeof options.followup_context === 'object' ? Object.assign({}, options.followup_context) : {};
    followupContext.kind = followupContext.kind || 'stepwise_task_resume';
    followupContext.source = followupContext.source || 'workspace_task_dispatcher';
    followupContext.followup_action = 'resume';
    followupContext.stepwise = Object.assign({}, followupContext.stepwise || {}, {
      policy: 'confirm_each_step', next_step_index: resumeStepIndex, original_task: String(options.workflow_checkpoint.original_task || '').trim(),
    });
    options.followup_context = followupContext;
    cloned.options = options;
    cloned.task = String(cloned.task || text || options.workflow_checkpoint.original_task || '').trim()
      || normalizeStepwiseTaskText(options.workflow_checkpoint.original_task || text || '');
    const files = Array.isArray(cloned.files) ? cloned.files : [];
    const existingContext = cloned.task_context && typeof cloned.task_context === 'object' ? cloned.task_context : {};
    const existingContextFiles = existingContext.files && typeof existingContext.files === 'object' ? existingContext.files : {};
    cloned.task_context = buildTaskContextPackage({
      task: cloned.task, files, currentFile: cloned.current_file || null,
      targetFile: files.find((f: any) => f && f.target) || existingContextFiles.target || null,
      selection: cloned.selection || '', selectionSource: cloned.selection_source || '', followupContext, workflowCheckpoint: options.workflow_checkpoint,
    });
    return cloned;
  }

  function normalizeStepwiseTaskText(text: string): string {
    const source = String(text || '').trim();
    if (!source) return '继续当前分步文件任务的下一步';
    if (/^继续当前分步文件任务/u.test(source)) return source;
    return `继续当前分步文件任务的下一步。原始任务：${previewText(source, 1200)}`;
  }

  function inferAttachedWriteTargetFile(text: string, files: TaskFileInfo[]): TaskFileInfo | null {
    if (!Array.isArray(files) || !files.length) return null;
    const lowered = String(text || '').toLowerCase();
    const targetMentionMatches = files.map((f) => ({ file: f, score: targetMentionScore(lowered, f) }))
      .filter((e) => e.score > 0).sort((a, b) => b.score - a.score);
    if (targetMentionMatches.length && targetMentionMatches[0].score !== (targetMentionMatches[1] && targetMentionMatches[1].score || 0)) {
      return targetMentionMatches[0].file;
    }
    const roleHintTarget = inferCompareTargetFromRoleHint(text, files);
    if (roleHintTarget) return roleHintTarget;
    const compareTarget = inferCompareAnnotatedTargetFile(text, files);
    if (compareTarget) return compareTarget;
    if (!hasWriteTargetHint(text)) return null;
    const writableFamilies = new Set(files.map((f) => canonicalTaskFileType(f)).filter((t) => Object.prototype.hasOwnProperty.call(TARGET_TYPE_FAMILIES, t)));
    if (writableFamilies.size < 2) return null;
    let preferredType = '';
    let bestIndex = -1;
    for (const entry of TARGET_TYPE_CUES) {
      if (!writableFamilies.has(entry.canonical)) continue;
      for (const cue of entry.cues) {
        const index = lowered.lastIndexOf(cue);
        if (index > bestIndex) { bestIndex = index; preferredType = entry.canonical; }
      }
    }
    if (!preferredType) return null;
    const matches = files.filter((f) => canonicalTaskFileType(f) === preferredType);
    return matches.length === 1 ? matches[0] : null;
  }

  function targetMentionScore(text: string, file: TaskFileInfo): number {
    const lowered = String(text || '').trim().toLowerCase();
    if (!lowered || !file) return 0;
    let score = 0;
    taskFileNameAliases(file).forEach((alias) => {
      let index = lowered.indexOf(alias);
      while (index >= 0) {
        const before = lowered.slice(Math.max(0, index - 18), index);
        const after = lowered.slice(index + alias.length, index + alias.length + 24);
        if (/(?:在|到|给|向|于|目标|target|into|in|on)\s*$/i.test(before)) score += 4;
        if (/^\s*(?:上|里|中|内|旁|文件|文档)?\s*(?:标注|批注|写入|写回|添加|加上|comment|annotate|mark|write)/i.test(after)) score += 5;
        if (/^\s*(?:作为|为)?\s*(?:目标|被标注|被批注|被修改|target)/i.test(after)) score += 3;
        index = lowered.indexOf(alias, index + alias.length);
      }
    });
    return score;
  }

  function taskFileNameAliases(file: TaskFileInfo): string[] {
    const values = [file && file.name, file && file.path, String(file && file.path || '').split(/[\\/]/).pop()];
    return Array.from(new Set(values.map((v) => String(v || '').trim().toLowerCase()).filter(Boolean)));
  }

  function canonicalTaskFileType(file: TaskFileInfo): string {
    const rawType = String(file && (file.type || file.file_type) || '').trim().toLowerCase().replace(/^\./, '');
    const rawName = String(file && (file.name || file.path) || '').trim();
    const ext = rawType || (rawName.includes('.') ? rawName.split('.').pop()!.toLowerCase() : '');
    for (const [canonical, family] of Object.entries(TARGET_TYPE_FAMILIES)) {
      if (family.includes(ext)) return canonical;
    }
    return ext;
  }

  function inferCompareTargetFromRoleHint(text: string, files: TaskFileInfo[]): TaskFileInfo | null {
    if (!Array.isArray(files) || files.length !== 2 || !looksLikeCompareAnnotationTask(text)) return null;
    const docxFiles = files.filter((f) => ['docx', 'doc'].includes(canonicalTaskFileType(f)));
    if (docxFiles.length !== 2) return null;
    const lowered = String(text || '').trim().toLowerCase();
    if (!lowered) return null;
    const firstDocx = docxFiles[0];
    const secondDocx = docxFiles[1];
    if (/(?:原文|原文件|原稿|旧版|第一份|第一版|source|original)/i.test(lowered)) {
      const originalScored = docxFiles.map((f, idx) => ({ file: f, score: (idx === 0 ? 1 : 0) + (/(?:original|source|原文|原稿|旧|old)/i.test(taskFileNameAliases(f).join(' ')) ? 2 : 0) - compareTargetNameScore(f) })).sort((a, b) => b.score - a.score);
      return originalScored[0] && originalScored[0].score !== originalScored[1].score ? originalScored[0].file : firstDocx;
    }
    if (/(?:修订稿|修改稿|新版|第二份|第二版|revised|reviewed|commented)/i.test(lowered)) {
      const revisedScored = docxFiles.map((f, idx) => ({ file: f, score: compareTargetNameScore(f) + (idx === 1 ? 1 : 0) })).sort((a, b) => b.score - a.score);
      return revisedScored[0] && revisedScored[0].score !== revisedScored[1].score ? revisedScored[0].file : secondDocx;
    }
    return null;
  }

  function inferCompareAnnotatedTargetFile(text: string, files: TaskFileInfo[]): TaskFileInfo | null {
    if (!Array.isArray(files) || files.length !== 2 || !looksLikeCompareAnnotationTask(text)) return null;
    const docxFiles = files.filter((f) => ['docx', 'doc'].includes(canonicalTaskFileType(f)));
    if (docxFiles.length !== 2) return null;
    const scored = docxFiles.map((f) => ({ file: f, score: compareTargetNameScore(f) })).filter((e) => e.score > 0);
    return scored.length === 1 ? scored[0].file : null;
  }

  function compareTargetNameScore(file: TaskFileInfo): number {
    const baseName = String(file && (file.name || file.path) || '').trim().toLowerCase();
    if (!baseName) return 0;
    return REVISED_TARGET_NAME_HINTS.reduce((score, marker) => score + (baseName.includes(marker) ? 1 : 0), 0);
  }

  function looksLikeCompareAnnotationTask(text: string): boolean {
    const lowered = String(text || '').trim().toLowerCase();
    if (!lowered) return false;
    return COMPARE_TASK_HINTS.some((w) => lowered.includes(w)) && ANNOTATION_TASK_HINTS.some((w) => lowered.includes(w));
  }

  function hasWriteTargetHint(text: string): boolean {
    const lowered = String(text || '').trim().toLowerCase();
    return !!lowered && WRITE_TARGET_HINTS.some((w) => lowered.includes(w));
  }

  function hasReadOnlyHint(text: string): boolean {
    const lowered = String(text || '').trim().toLowerCase();
    if (!lowered) return false;
    if (READ_ONLY_HINTS.some((w) => lowered.includes(w))) return true;
    return /(?:不要|不用|无需|不需要|别).{0,8}(?:修改|改动|编辑|写入|写回|更新|保存|插入|删除|替换|应用)/i.test(lowered)
      || /(?:只|仅).{0,6}(?:分析|总结|解释|检查|列出|指出|给建议|输出建议)/i.test(lowered);
  }

  function explicitWriteTargetPathFromText(text: string): string {
    const source = String(text || '').trim();
    if (!source) return '';
    const filePattern = /((?:[A-Za-z]:[\\/])?[^\s"'<>|:：,，。；;、!?！？()[\]【】]+?\.(?:csv|docx?|html|json|md|pdf|pptx?|txt|xlsx?))/ig;
    const writePattern = /(继续优化|优化|修改|更新|保存|写入|写回|追加|添加|插入|落盘|continue|improve|modify|edit|update|save|write|append|insert)/i;
    const protectPattern = /(不要|不用|无需|不需要|不必|别|不|do not|don't|dont|without).{0,24}(修改|改动|编辑|覆盖|替换|删除|写入|写回|更新|modify|edit|overwrite|replace|delete|write|update)/i;
    const readSourcePattern = /(读取|阅读|查看|分析|基于|来自|原文|原文件|源文件|输入文件|已添加|source|input|read)/i;
    const explicitOutputBeforePattern = /(保存为|另存为|输出到|写入到|导出到|save as|export to|write to).{0,80}$/i;
    const sourceBeforePattern = /(读取|阅读|查看|分析|基于|来自|当前打开|当前文件|原文|原文件|源文件|输入文件|已添加|source|input|read).{0,36}$/i;
    const candidates: Array<{ path: string; score: number; index: number }> = [];
    let match: RegExpExecArray | null;
    while ((match = filePattern.exec(source)) !== null) {
      const rawPath = String(match[1] || '').replace(/[ \t\r\n,，。；;、!?！？()[\]【】"']+$/g, '');
      const start = match.index;
      const end = start + rawPath.length;
      const before = source.slice(Math.max(0, start - 80), start);
      const near = source.slice(Math.max(0, start - 80), Math.min(source.length, end + 80));
      if (
        hasReadOnlyHint(source)
        && mentionsAttachedFileContext(near)
        && !explicitOutputBeforePattern.test(before)
      ) {
        continue;
      }
      let score = 0;
      if (writePattern.test(near) && !protectPattern.test(near)) score += 5;
      if (explicitOutputBeforePattern.test(before)) score += 8;
      if (sourceBeforePattern.test(before)) score -= 8;
      if (/(同一个|当前|目标|target|same)/i.test(near)) score += 2;
      if (/(同一个|当前|目标).{0,16}(docx|word|xlsx|excel|pptx|ppt|pdf|文档|表格|幻灯片|文件)/i.test(near)) score += 5;
      if (readSourcePattern.test(near)) score -= 2;
      if (protectPattern.test(before)) score -= 8;
      if (score > 0) candidates.push({ path: rawPath, score, index: start });
    }
    candidates.sort((a, b) => (b.score - a.score) || (a.index - b.index));
    return candidates.length ? candidates[0].path : '';
  }

  function normalizeTaskPath(value: string): string {
    return String(value || '').trim().replace(/\\/g, '/').toLowerCase();
  }

  function fileTypeFromPath(value: string): string {
    const text = String(value || '').trim();
    const match = /\.([A-Za-z0-9]+)(?:$|[?#])/i.exec(text);
    return match ? match[1].toLowerCase() : '';
  }

  function baseNameFromPath(value: string): string {
    const text = String(value || '').trim().replace(/\\/g, '/');
    return text ? text.split('/').pop() || '' : '';
  }

  return {
    registerMessageRoute,
    registerQuickActionHandler,
    setDefaultQuickActionHandler,
    dispatchMessage,
    dispatchQuickAction,
    matchQuickAction,
    buildWhiteboxTaskPayload,
    buildFileTaskPayload: buildWhiteboxTaskPayload,
  };
}

const WA = (window as any).WA || {};
WA.createTaskDispatcher = createTaskDispatcher;
(window as any).WA = WA;
