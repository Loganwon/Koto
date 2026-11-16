import { _csrfFetch, showToast } from './infrastructure';
import { isFileTaskTerminalStatus, normalizeFileTaskTerminalStatus } from './file-task-status';
import { previewText, terminalAnswerText } from './task-final-report';
import {
  attachTaskContextPackage,
  cloneTaskPayload,
  compactFollowupTaskFile,
  compactFollowupTaskPayload,
  compactJsonValue,
  compactPendingResumePayload,
  compactTaskContext,
} from './task-dispatcher-payload';
import {
  baseNameFromPath,
  fileTypeFromPath,
  normalizeTaskPath,
  type TaskFileInfo,
} from './task-file-contract';
import {
  canonicalTaskFileType,
  explicitWriteTargetPathFromText,
  inferAttachedWriteTargetFile,
} from './task-target-inference';
import { localModelWritePreflight } from './task-model-preflight';
import {
  buildCurrentOpenTaskFile,
  buildWorkspaceChatFileContextValue,
  buildWorkspaceRouteFiles,
  supportsLiveDocumentTools,
} from './task-workspace-context';
import {
  deterministicWorkspaceRouteDecision,
  fileTaskRouteDecision,
  isDirectWorkspaceResponse,
  isWorkspaceOpenFileResponse,
  normalizeFileTaskRoutingDecision,
  normalizeWorkspaceRouteDecision,
  shouldBypassWorkspaceRoute,
  shouldForceFileTaskForWorkspaceContext,
  workspaceRouteErrorFallbackDecision,
} from './task-routing-decision';
import { createWorkspaceChatStreamer } from './task-direct-chat';
import { runWorkspaceOpenFileRoute } from './task-open-file-route';
import { decodeTaskContract } from './task-contract-codec';
import { taskCardPersistenceStructure } from './task-card-persistence';
import {
  buildTaskFollowupContext,
  looksLikeTaskCritique,
} from './task-followup-context';
export interface TaskDispatcherDeps {
  state?: Record<string, any>;
  getSessionId?: () => string;
  ensureSessionId?: () => Promise<string>;
  getConversationHistory?: () => any[];
  getModelMode?: () => string;
  getSelectedCloudModelId?: () => string;
  setStreamButton?: (_loading: boolean) => void;
  openWorkspaceFile?: (_path: string) => Promise<any> | any;
  streamTaskFlow?: (_opts: any) => Promise<any>;
  beginAssistantTaskTurn?: (_metadata?: any) => any;
  syncAssistantTaskTurn?: (_turnId: string, _metadata?: any) => any;
  appendAssistantTurn?: (_content: string, _metadata?: any) => any;
  persistTaskTurn?: (_record?: any) => Promise<any>;
  getActiveEditorContent?: () => string;
  sampleTaskContext?: (_content: string) => string;
}

export interface MessageRoute {
  id?: string;
  priority?: number;
  match: (_context: any) => boolean;
  run: (_context: any) => any;
}

export interface TaskContext {
  text: string;
  pinnedSelText?: string;
  pinnedSelSource?: string;
  selectionContext?: Record<string, any> | null;
  model_mode?: string;
  model_id?: string;
  msgs?: HTMLElement;
  loadingEl?: HTMLElement;
  taskPayload?: Record<string, any> | null;
  options?: Record<string, any>;
}

export function createTaskDispatcher(deps: TaskDispatcherDeps = {}) {
  const options = deps || {};
  const state = options.state || {};
  const messageRoutes: MessageRoute[] = [];
  const quickActionHandlers = new Map<string, Function>();
  let defaultQuickActionHandler: Function | null = null;

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

  function workspaceRouteFiles(): any[] {
    return buildWorkspaceRouteFiles(
      state._aiFileContext,
      state._aiTargetFileIdx,
      options.sampleTaskContext,
    ).map((file) => ({
      path: file.path,
      name: file.name,
      type: file.type,
      target: file.target,
      content_preview: file.content,
    }));
  }

  function currentOpenTaskFile(): TaskFileInfo | null {
    const content = typeof options.getActiveEditorContent === 'function'
      ? options.getActiveEditorContent() || ''
      : '';
    return buildCurrentOpenTaskFile(state, content);
  }

  function buildWorkspaceChatFileContext(context: TaskContext): Record<string, any> | null {
    return buildWorkspaceChatFileContextValue({
      currentFile: currentOpenTaskFile(),
      readyFiles: workspaceRouteFiles(),
      openTabs: state.openTabs,
      selectionText: context && context.pinnedSelText,
      selectionSource: context && context.pinnedSelSource,
      selectionContext: context && context.selectionContext,
    });
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

  const streamWorkspaceChatRoute = createWorkspaceChatStreamer({
    state,
    csrfFetch: _csrfFetch,
    ensureSessionId: options.ensureSessionId,
    getSessionId: options.getSessionId,
    getModelMode: options.getModelMode,
    getSelectedCloudModelId: options.getSelectedCloudModelId,
    setStreamButton: options.setStreamButton,
    buildFileContext: buildWorkspaceChatFileContext,
    appendAssistantTurn: appendAssistantConversationTurn,
    syncAssistantTurn: options.syncAssistantTaskTurn,
  });

  function openWorkspaceFileRoute(context: TaskContext, routeDecision: Record<string, any>): Promise<any> {
    return runWorkspaceOpenFileRoute({
      state,
      openWorkspaceFile: options.openWorkspaceFile,
      appendAssistantTurn: appendAssistantConversationTurn,
      setStreamButton: options.setStreamButton,
    }, context, routeDecision);
  }

  async function runTaskFlowRoute(context: TaskContext, routeDecision?: Record<string, any>): Promise<any> {
    const loadingEl = context.loadingEl;
    const modelPreflightBlock = localModelWritePreflight({
      text: context.text,
      files: workspaceRouteFiles(),
      modelMode: context.model_mode
        || (typeof options.getModelMode === 'function' ? options.getModelMode() : ''),
      lockedModel: state.lockedModel,
      supportsTools: state._localModelSupportsTools,
      modelLabel: state._localRuntimeModel,
    });
    if (modelPreflightBlock) {
      const assistantText = modelPreflightBlock.message;
      if (loadingEl) {
        loadingEl.classList.remove('streaming');
        loadingEl.textContent = assistantText;
        loadingEl.dataset.rawText = assistantText;
        loadingEl.dataset.taskTerminalStatus = 'blocked';
        loadingEl.dataset.taskCompleted = 'false';
      }
      state.isLoading = false;
      if (typeof options.setStreamButton === 'function') options.setStreamButton(false);
      showToast(assistantText, 'warning', 6000);
      const modelMenuTrigger = document.querySelector<HTMLButtonElement>('#wa-model-menu-trigger');
      if (modelMenuTrigger && modelMenuTrigger.getAttribute('aria-expanded') !== 'true') modelMenuTrigger.click();
      appendAssistantConversationTurn(assistantText, {
        task_kind: 'file_task',
        status: 'blocked',
        block_code: modelPreflightBlock.code,
        skip_model_context: true,
      });
      return Promise.resolve({
        routeId: 'task-flow',
        assistantText,
        blocked: true,
        blockCode: modelPreflightBlock.code,
        routeDecision,
      });
    }
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
    const taskTurnId = taskTurn && taskTurn.id
      ? taskTurn.id
      : `task_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 10)}`;
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
    if (typeof options.ensureSessionId === 'function') {
      try {
        await options.ensureSessionId();
      } catch (error) {
        console.warn('[WA] unable to establish the task persistence session:', error);
      }
    }
    const payload = buildWhiteboxTaskPayload(context.text, context.pinnedSelText, context.pinnedSelSource, routedContext);
    if (loadingEl) {
      setTaskFollowupPayload(loadingEl, payload);
      setPendingTaskResumePayload(loadingEl, payload);
    }
    let terminalTaskPersisted = false;
    let activeTaskCard: HTMLElement | undefined = loadingEl || undefined;
    const requestCancellation = (): void => {
      const handler = (activeTaskCard as any)?._cancelHandler;
      if (typeof handler === 'function') handler();
      else showToast('正在登记任务，请稍后再次停止。', 'info');
    };
    state._cancelCurrentTask = requestCancellation;
    let terminalPersistTimer: number | null = null;
    let terminalPersistDelayTimer: number | null = null;
    const basePersistMetadata = (card?: HTMLElement, extra?: Record<string, any>) => Object.assign({
      turn_id: taskTurnId,
      task_kind: 'file_task',
      status: 'streaming',
      task_terminal_status: 'running',
      partial: true,
      skip_model_context: true,
    }, extra || {}, taskTurnMetadataFromLoadingEl(card));
    const taskCardHasTerminalResult = (card?: HTMLElement): boolean => {
      if (!card || !card.dataset) return false;
      const dataset = card.dataset;
      const status = normalizeFileTaskTerminalStatus(dataset.taskTerminalStatus || '');
      const hasFinalText = !!String(dataset.taskFinalAnswer || dataset.taskSummary || '').trim();
      if (card.classList.contains('done') || card.classList.contains('failed') || card.classList.contains('cancelled')) return hasFinalText || status !== '';
      if (isFileTaskTerminalStatus(status)) return true;
      return String(dataset.taskCompleted || '').trim().toLowerCase() === 'true' && hasFinalText;
    };
    const persistTerminalTaskCard = (card?: HTMLElement, streamResult?: any, fallbackStatus = 'done'): string => {
      const targetCard = card || loadingEl;
      const assistantText = finalizeWhiteboxTaskTurn(taskTurnId, targetCard, streamResult || {
        summary: String(targetCard && targetCard.dataset && (targetCard.dataset.taskFinalAnswer || targetCard.dataset.taskSummary) || '').trim(),
        status: fallbackStatus,
      }, fallbackStatus, false);
      if (!terminalTaskPersisted) {
        terminalTaskPersisted = true;
        persistTaskTurn(context.text, assistantText, Object.assign({
          turn_id: taskTurnId,
          task_kind: 'file_task',
          task_title: '文件任务结果',
          partial: false,
          skip_model_context: false,
        }, taskTurnMetadataFromLoadingEl(targetCard)), payload.files || [], targetCard);
      }
      return assistantText;
    };
    const stopTerminalPersistWatch = () => {
      if (terminalPersistTimer !== null) {
        window.clearInterval(terminalPersistTimer);
        terminalPersistTimer = null;
      }
      if (terminalPersistDelayTimer !== null) {
        window.clearTimeout(terminalPersistDelayTimer);
        terminalPersistDelayTimer = null;
      }
    };
    const startTerminalPersistWatch = () => {
      stopTerminalPersistWatch();
      terminalPersistTimer = window.setInterval(() => {
        if (terminalTaskPersisted) {
          stopTerminalPersistWatch();
          return;
        }
        if (activeTaskCard && taskCardHasTerminalResult(activeTaskCard)) {
          persistTerminalTaskCard(activeTaskCard);
          stopTerminalPersistWatch();
        }
      }, 150);
      window.setTimeout(stopTerminalPersistWatch, 30000);
    };
    persistTaskTurn(context.text, '文件任务已启动，正在执行…', basePersistMetadata(loadingEl), payload.files || [], loadingEl);
    startTerminalPersistWatch();
    return Promise.resolve(streamTaskFlow!({
      payload, msgs: context.msgs, loadingEl, signal: ctrl.signal, abortController: ctrl,
      onTaskCardSnapshot: (card: HTMLElement) => {
        activeTaskCard = card;
        setTaskFollowupPayload(card, payload);
        setPendingTaskResumePayload(card, payload);
        if (!terminalTaskPersisted && taskCardHasTerminalResult(card) && terminalPersistDelayTimer === null) {
          terminalPersistDelayTimer = window.setTimeout(() => {
            terminalPersistDelayTimer = null;
            if (!terminalTaskPersisted) persistTerminalTaskCard(activeTaskCard || card);
          }, 600);
        }
        if (!taskTurnId || typeof options.syncAssistantTaskTurn !== 'function') return;
        options.syncAssistantTaskTurn(taskTurnId, Object.assign({ loadingEl: card, task_kind: 'file_task', status: 'streaming', skip_model_context: true }, taskTurnMetadataFromLoadingEl(card)));
      },
    })).then((streamResult: any) => {
      const assistantText = persistTerminalTaskCard(activeTaskCard || loadingEl, streamResult, 'done');
      return { routeId: 'task-flow', assistantText, payload, result: streamResult, routeDecision };
    }).catch((error: any) => {
      const aborted = error && error.name === 'AbortError';
      const assistantText = aborted ? '任务已停止。' : (error && error.waTaskError ? error.message : `任务流失败：${error && error.message ? error.message : error}`);
      if (loadingEl) { loadingEl.classList.remove('streaming'); loadingEl.textContent = assistantText; loadingEl.dataset!.rawText = assistantText; }
      finalizeWhiteboxTaskTurn(taskTurnId, loadingEl, { summary: assistantText, status: aborted ? 'cancelled' : 'error' }, aborted ? 'cancelled' : 'error', true);
      persistTaskTurn(context.text, assistantText, Object.assign({
        turn_id: taskTurnId,
        task_kind: 'file_task',
        partial: false,
        status: aborted ? 'cancelled' : 'error',
        skip_model_context: aborted,
      }, taskTurnMetadataFromLoadingEl(loadingEl)), [], loadingEl);
      return { routeId: 'task-flow', assistantText, error, routeDecision };
    }).finally(() => {
      if (state._cancelCurrentTask === requestCancellation) state._cancelCurrentTask = null;
      stopTerminalPersistWatch();
      if (state._streamAbortCtrl === ctrl) state._streamAbortCtrl = null;
      state.isLoading = false;
      if (typeof options.setStreamButton === 'function') options.setStreamButton(false);
    });
  }

  async function runWorkspaceModelRoutedTask(context: TaskContext): Promise<any> {
    const pendingModelChoice = state._modelChoicePromise;
    if (pendingModelChoice && typeof pendingModelChoice.then === 'function') {
      await pendingModelChoice;
    }
    if (shouldBypassWorkspaceRoute(context)) {
      return runTaskFlowRoute(context, fileTaskRouteDecision('explicit_task_payload'));
    }
    const readyRouteFiles = workspaceRouteFiles();
    // An explicitly open document is the current environment. Let the Kernel
    // read its live selection and execute semantic edits, rather than copying
    // its contents into a separate disk-only file workflow.
    const activeFile = currentOpenTaskFile();
    if (activeFile && readyRouteFiles.length === 0 && !supportsLiveDocumentTools(activeFile)) {
      return runTaskFlowRoute(context, fileTaskRouteDecision('active_file_format'));
    }
    if (supportsLiveDocumentTools(activeFile) && readyRouteFiles.length === 0) {
      return streamWorkspaceChatRoute(context, {
        route: 'light_chat', route_kind: 'direct_response', task_type: 'AGENT',
        route_source: 'active_document_context',
      });
    }
    const deterministicRoute = deterministicWorkspaceRouteDecision({
      text: context.text,
      hasFileContext: readyRouteFiles.length > 0
        || !!currentOpenTaskFile()
        || !!String(context.pinnedSelText || '').trim(),
    });
    if (deterministicRoute) {
      if (isWorkspaceOpenFileResponse(deterministicRoute)) {
        return openWorkspaceFileRoute(context, deterministicRoute);
      }
      if (isDirectWorkspaceResponse(deterministicRoute)) {
        return streamWorkspaceChatRoute(context, deterministicRoute);
      }
      return runTaskFlowRoute(context, deterministicRoute);
    }
    if (context.loadingEl) context.loadingEl.textContent = '正在判断…';
    let routeDecision: Record<string, any> | null = null;
    try {
      routeDecision = await resolveWorkspaceRouteIntent(context);
    } catch (error) {
      console.warn('[WA] workspace route intent failed, applying contextual fallback:', error);
      routeDecision = workspaceRouteErrorFallbackDecision({
        text: context.text,
        hasFileContext: readyRouteFiles.length > 0
          || !!currentOpenTaskFile()
          || !!String(context.pinnedSelText || '').trim(),
      });
    }
    if (shouldForceFileTaskForWorkspaceContext({
      text: context.text,
      hasFileContext: readyRouteFiles.length > 0
        || !!String(context.pinnedSelText || '').trim(),
    }, routeDecision)) {
      routeDecision = fileTaskRouteDecision('frontend_file_context_guard', routeDecision);
    }
    if (isWorkspaceOpenFileResponse(routeDecision)) {
      return openWorkspaceFileRoute(context, routeDecision!);
    }
    if (isDirectWorkspaceResponse(routeDecision)) {
      return streamWorkspaceChatRoute(context, routeDecision!);
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
    if (dataset.taskTitle) metadata.task_title = String(dataset.taskTitle || '').trim();
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
    if (dataset.taskRoute) metadata.task_route = String(dataset.taskRoute || '').trim();
    if (dataset.taskRouteSource) metadata.task_route_source = String(dataset.taskRouteSource || '').trim();
    if (dataset.taskRoutingDecision) {
      try { metadata.route_intent = JSON.parse(decodeURIComponent(String(dataset.taskRoutingDecision || '').trim())); } catch { /* noop */ }
    }
    if (dataset.taskIntentStrategy) metadata.task_intent_strategy = String(dataset.taskIntentStrategy || '').trim();
    if (Object.prototype.hasOwnProperty.call(dataset, 'taskIntentCanApply')) {
      metadata.task_intent_can_apply = String(dataset.taskIntentCanApply || '').trim().toLowerCase() === 'true';
    }
    if (Object.prototype.hasOwnProperty.call(dataset, 'taskIntentRequiresConfirmation')) {
      metadata.task_intent_requires_confirmation = String(dataset.taskIntentRequiresConfirmation || '').trim().toLowerCase() === 'true';
    }
    if (dataset.taskTargetFileType) metadata.task_target_file_type = String(dataset.taskTargetFileType || '').trim();
    const taskContract = decodeTaskContract(dataset.taskContract || '');
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
    const persistenceStructure = taskCardPersistenceStructure(loadingEl);
    if (persistenceStructure) metadata.test_structure = persistenceStructure;
    if (Object.prototype.hasOwnProperty.call(dataset, 'taskCompleted')) {
      metadata.completed_task = String(dataset.taskCompleted || '').trim().toLowerCase() === 'true';
    }
    return metadata;
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
    const dataset = loadingEl && loadingEl.dataset ? loadingEl.dataset : {};
    const assistantText = terminalAnswerText(
      payload,
      String(dataset.taskFinalAnswer || dataset.taskSummary || '').trim(),
    ) || '文件任务流已结束。';
    if (loadingEl && loadingEl.dataset) loadingEl.dataset.rawText = assistantText;
    const turnMetadata = Object.assign({
      content: assistantText, loadingEl, task_kind: 'file_task',
      status: String(payload.status || fallbackStatus || 'done').trim() || 'done',
    }, taskTurnMetadataFromLoadingEl(loadingEl), {
      // Streaming snapshots stay out of model context, but a terminal task
      // result must be available to an immediate follow-up after a file switch.
      skip_model_context: !!skipModelContext,
    });
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
    const routingDecision = normalizeFileTaskRoutingDecision(
      requestOverrides.routing_decision || requestOverrides.workspace_route_intent || overrideOptions.workspace_route_intent,
    );
    if (routingDecision && routingDecision.skip_ai_intent_adjudicator === true) {
      overrideOptions.disable_ai_intent_adjudicator = true;
      delete overrideOptions.enable_ai_intent_adjudicator;
    }
    overrideOptions.router_policy = overrideOptions.router_policy || 'model_primary_intent';
    if (!overrideOptions.selection_context && requestOverrides.selectionContext && typeof requestOverrides.selectionContext === 'object') {
      overrideOptions.selection_context = compactJsonValue(requestOverrides.selectionContext, 0, 1200);
    }
    if (routingDecision && !routingDecision.router_policy) {
      routingDecision.router_policy = String(overrideOptions.router_policy || '').trim();
    }

    if (explicitTaskPayload) {
      return finalizeExplicitTaskPayload(explicitTaskPayload, text, pinnedSelText, pinnedSelSource, overrideOptions, requestOverrides, routingDecision)!;
    }

    const resumedTaskPayload = implicitResumeTaskPayload(text);
    if (resumedTaskPayload) {
      return finalizeExplicitTaskPayload(resumedTaskPayload, text, pinnedSelText, pinnedSelSource, overrideOptions, requestOverrides, routingDecision)!;
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
    const followupContext = buildTaskFollowupContext(text, state.conversation);
    if (followupContext && !overrideOptions.followup_context) overrideOptions.followup_context = followupContext;
    if (targetFile && !overrideOptions.inferred_target_file_type) overrideOptions.inferred_target_file_type = canonicalTaskFileType(targetFile);
    const payload: Record<string, any> = {
      task: text, session_id: typeof options.getSessionId === 'function' ? options.getSessionId() : '',
      selection: pinnedSelText || '', selection_source: pinnedSelSource || '', files: rawFiles,
      target_path: inferredTargetPath, file_name: inferredFileName, file_type: inferredFileType,
      current_file: currentFile,
      routing_decision: routingDecision,
      model_mode: typeof options.getModelMode === 'function' ? options.getModelMode() : 'auto',
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
    return attachTaskContextPackage(payload);
  }

  function finalizeExplicitTaskPayload(taskPayload: any, text: string, pinnedSelText?: string, pinnedSelSource?: string, overrideOptions?: Record<string, any>, requestOverrides?: any, routingDecision?: Record<string, any> | null): Record<string, any> | null {
    const explicitTaskPayload = cloneTaskPayload(taskPayload);
    if (!explicitTaskPayload) return null;
    const explicitOptions = explicitTaskPayload.options && typeof explicitTaskPayload.options === 'object' ? Object.assign({}, explicitTaskPayload.options) : {};
    explicitTaskPayload.file_name = explicitTaskPayload.file_name || state.fileName || '';
    explicitTaskPayload.file_type = explicitTaskPayload.file_type || state.fileType || '';
    explicitTaskPayload.session_id = explicitTaskPayload.session_id || (typeof options.getSessionId === 'function' ? options.getSessionId() : '');
    explicitTaskPayload.options = Object.assign({}, explicitOptions, overrideOptions);
    const explicitRoutingDecision = normalizeFileTaskRoutingDecision(
      explicitTaskPayload.routing_decision
        || routingDecision
        || explicitTaskPayload.options.workspace_route_intent,
    );
    if (explicitRoutingDecision) explicitTaskPayload.routing_decision = explicitRoutingDecision;
    if (!Array.isArray(explicitTaskPayload.history)) {
      explicitTaskPayload.history = typeof options.getConversationHistory === 'function' ? options.getConversationHistory() : (Array.isArray(state.conversation) ? state.conversation.slice(-12) : []);
    }
    attachTaskContextPackage(explicitTaskPayload, {
      defaultTask: text,
      defaultSelection: pinnedSelText || '',
      defaultSelectionSource: pinnedSelSource || '',
      dropCurrentFileWithoutSelection: true,
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
    return attachTaskContextPackage(cloned, {
      followupContext,
      workflowCheckpoint: options.workflow_checkpoint,
    });
  }

  function normalizeStepwiseTaskText(text: string): string {
    const source = String(text || '').trim();
    if (!source) return '继续当前分步文件任务的下一步';
    if (/^继续当前分步文件任务/u.test(source)) return source;
    return `继续当前分步文件任务的下一步。原始任务：${previewText(source, 1200)}`;
  }

  return {
    registerMessageRoute,
    registerQuickActionHandler,
    setDefaultQuickActionHandler,
    dispatchMessage,
    dispatchQuickAction,
    matchQuickAction,
    taskCardPersistenceStructure,
    buildWhiteboxTaskPayload,
    buildFileTaskPayload: buildWhiteboxTaskPayload,
  };
}
