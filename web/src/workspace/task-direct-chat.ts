import { parseSseEvents, persistedTaskStreamEvent } from './file-task-sse';
import { applyTaskMessageStreamEvent, createTaskMessageStreamState } from './task-message-stream';
import { consumeTaskEventStream } from './task-stream-lifecycle';
import { createTaskChatPresentation } from './task-chat-presentation';
import { reconnectTaskStream, installTaskReconnectAction } from './task-stream-reconnect';
import { getFeatureRegistry } from '../shared/feature-registry';
import { loadFrontendObserver } from '../shared/frontend-observer-loader';
import { createFileTaskId, createFileTaskRunId } from './task-stream-transport';

export interface WorkspaceDirectChatContext {
  text: string;
  pinnedSelText?: string;
  pinnedSelSource?: string;
  selectionContext?: Record<string, any> | null;
  msgs?: HTMLElement;
  loadingEl?: HTMLElement;
}

export interface WorkspaceDirectChatDeps {
  state: Record<string, any>;
  csrfFetch: (url: string, init?: any) => Promise<Response>;
  ensureSessionId?: () => Promise<string>;
  getSessionId?: () => string;
  getModelMode?: () => string;
  getSelectedCloudModelId?: () => string;
  setStreamButton?: (loading: boolean) => void;
  buildFileContext: (context: WorkspaceDirectChatContext) => Record<string, any> | null;
  appendAssistantTurn: (text: string, metadata: Record<string, any>) => void;
  syncAssistantTurn?: (turnId: string, metadata: Record<string, any>) => void;
}

export interface ParsedWorkspaceSseEvents {
  events: any[];
  remainder: string;
}

export function parseWorkspaceSseEvents(
  buffer: string,
  flush: boolean,
): ParsedWorkspaceSseEvents {
  return parseSseEvents(buffer, flush);
}

export function appendWorkspaceChatEvents(
  currentText: string,
  events: any[],
): string {
  const state = createTaskMessageStreamState(String(currentText || ''));
  (Array.isArray(events) ? events : []).forEach((event) => applyTaskMessageStreamEvent(state, event));
  return state.text;
}

export function chatStreamLockedModel(
  modelMode: string,
  selectedCloudModelId: string,
): string {
  const mode = String(modelMode || '').trim().toLowerCase();
  if (mode === 'local') return 'local';
  const selected = String(selectedCloudModelId || '').trim();
  return selected || 'cloud';
}

export function directChatRouteContract(routeDecision: Record<string, any>): {
  route: string;
  lockedTask: string;
  taskKind: string;
  loadingText: string;
} {
  const route = String(routeDecision && routeDecision.route || '').trim();
  if (route === 'web_search') {
    return { route, lockedTask: 'WEB_SEARCH', taskKind: 'web_search', loadingText: '正在检索…' };
  }
  if (route === 'system_action') {
    return { route, lockedTask: 'SYSTEM', taskKind: 'system_action', loadingText: '正在执行…' };
  }
  return { route: route || 'light_chat', lockedTask: '', taskKind: 'message', loadingText: '正在处理…' };
}

export function createWorkspaceChatStreamer(deps: WorkspaceDirectChatDeps) {
  return async function streamWorkspaceChatRoute(context: WorkspaceDirectChatContext, routeDecision: Record<string, any>): Promise<any> {
    const host = context.loadingEl;
    const route = directChatRouteContract(routeDecision);
    const ctrl = new AbortController();
    const state = createTaskMessageStreamState();
    const taskId = createFileTaskId();
    const runId = createFileTaskRunId();
    const view = createTaskChatPresentation(host, context.msgs || document.getElementById('wa-ai-messages') || undefined);
    let sessionId = '';
    let lastSeq = 0;
    let cancelRequested = false;
    let published = false;
    let recoveryAttempted = false;
    let rejected = false;
    let removeReconnect: (() => void) | undefined;
    if (host) {
      host.classList.add('streaming');
      Object.assign(host.dataset, { taskId, taskRunId: runId, workspaceRoute: route.route,
        workspaceRouteSource: String(routeDecision.route_source || '') });
    }
    view.progress(route.loadingText);
    deps.state._streamAbortCtrl = ctrl;
    deps.state.isLoading = true;
    deps.setStreamButton?.(true);
    const identity = () => ({ taskId, runId, afterSeq: lastSeq });
    const requestCancel = async (): Promise<void> => {
      if (cancelRequested || state.terminal) return;
      cancelRequested = true;
      view.progress('正在停止，等待当前操作结束…');
      try {
        const response = await deps.csrfFetch(`/api/tasks/${encodeURIComponent(taskId)}/cancel`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ run_id: runId }),
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
      } catch (error) {
        cancelRequested = false;
        view.progress(`停止请求未确认，可重试：${error instanceof Error ? error.message : error}`);
        throw error;
      }
    };
    const safeCancel = () => requestCancel().catch(() => {});
    deps.state._cancelCurrentTask = safeCancel;
    const consume = async (response: Response): Promise<boolean> => {
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      if (!response.body) throw new Error('响应流不可用');
      await consumeTaskEventStream(response.body.getReader(), {
        stopOnTerminal: true, transformEvent: persistedTaskStreamEvent,
        isTerminalEvent: () => state.terminal,
        onEvent: (event) => {
          const changed = applyTaskMessageStreamEvent(state, event, () => {
            const payload = event.payload || event;
            lastSeq = Math.max(lastSeq, Number(event.seq || payload.seq || 0));
            if (host) host.dataset.taskLastSeq = String(lastSeq);
            view.event(event);
          });
          if (changed) view.text(state.text, event.type === 'message.finished');
          if (cancelRequested && !state.terminal) view.progress('正在停止，等待当前操作结束…');
        },
      });
      return state.terminal;
    };
    const publish = (status: string): string => {
      const text = state.text.trim() || (status === 'cancelled' ? '任务已停止。'
        : ['failed', 'error', 'blocked'].includes(status) ? state.errorMessage || '任务未完成。'
          : status === 'interrupted' ? '进度同步中断，原任务记录已保留。'
            : status === 'waiting' ? '任务等待处理。' : '已完成。');
      const metadata = { id: runId, loadingEl: host, content: text, task_kind: route.taskKind,
        status: ['success', 'succeeded', 'completed'].includes(status) ? 'done' : status,
        route_intent: routeDecision, skip_model_context: !['success', 'succeeded', 'completed'].includes(status),
        preserve_scroll_position: true, document_receipts: view.receipts, task_id: taskId, run_id: runId };
      view.preserve(() => {
        if (!published) { deps.appendAssistantTurn(text, metadata); published = true; }
        else if (deps.syncAssistantTurn) deps.syncAssistantTurn(runId, metadata);
        else {
          const turn = deps.state.conversation?.find((entry: any) => entry.id === runId || entry.run_id === runId);
          if (turn) Object.assign(turn, metadata);
        }
      });
      return text;
    };
    const recover = async (signal?: AbortSignal): Promise<void> => {
      if (deps.getSessionId && deps.getSessionId() !== sessionId) throw new Error('请回到原会话继续查看该任务');
      recoveryAttempted = true;
      view.begin();
      await reconnectTaskStream({ identity, fetch: deps.csrfFetch, consume, signal,
        onAttempt: () => view.progress('连接中断，正在同步原任务…') });
    };
    const finish = () => {
      const status = state.terminalStatus || 'failed';
      view.settle(status, publish(status), cancelRequested);
      removeReconnect?.();
    };
    const interrupted = (error: unknown) => {
      view.settle('interrupted', publish('interrupted'), cancelRequested);
      if (host) removeReconnect = installTaskReconnectAction(host, async () => {
        try { await recover(); finish(); }
        catch (caught) { view.settle('interrupted', state.text, cancelRequested); throw caught; }
      }, requestCancel);
      return { routeId: route.route, assistantText: state.text, routeDecision, error };
    };
    try {
      sessionId = deps.ensureSessionId ? await deps.ensureSessionId() : deps.getSessionId?.() || 'workspace_default';
      const fileContext = deps.buildFileContext(context);
      let frontendScope = null;
      if (fileContext?.file_path && (deps.state.activeEditor || deps.state.activeTabPath)) {
        try { await loadFrontendObserver(); frontendScope = await getFeatureRegistry().getDocumentToolScope?.() || null; }
        catch { /* Disk tools remain usable without a live editor. */ }
      }
      const response = await deps.csrfFetch('/api/chat/stream', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: ctrl.signal,
        body: JSON.stringify({ session: sessionId, message: context.text, task_id: taskId, run_id: runId,
          ...(route.lockedTask ? { locked_task: route.lockedTask } : {}),
          locked_model: chatStreamLockedModel(deps.getModelMode?.() || '', deps.getSelectedCloudModelId?.() || ''),
          workspace_route_intent: routeDecision, file_context: fileContext,
          ...(frontendScope ? { frontend_scope: frontendScope } : {}) }),
      });
      if (!response.ok) {
        rejected = true; state.errorMessage = `任务请求未被接受：HTTP ${response.status}`;
        throw new Error(state.errorMessage);
      }
      try {
        if (!await consume(response)) throw new Error('连接中断');
      } catch (error) {
        if (state.terminal || ctrl.signal.aborted) throw error;
        await recover(ctrl.signal);
      }
      finish();
      return { routeId: route.route, assistantText: state.text, routeDecision };
    } catch (error) {
      if (state.terminal) { finish(); return { routeId: route.route, assistantText: state.text, routeDecision, error }; }
      if (rejected) {
        view.settle('failed', publish('failed'));
        return { routeId: route.route, assistantText: state.errorMessage, routeDecision, error };
      }
      if (!recoveryAttempted && !ctrl.signal.aborted) {
        try { await recover(ctrl.signal); finish(); return { routeId: route.route, assistantText: state.text, routeDecision }; }
        catch (caught) { return interrupted(caught); }
      }
      return interrupted(error);
    } finally {
      if (deps.state._cancelCurrentTask === safeCancel) deps.state._cancelCurrentTask = null;
      if (deps.state._streamAbortCtrl === ctrl) deps.state._streamAbortCtrl = null;
      deps.state.isLoading = false;
      deps.setStreamButton?.(false);
    }
  };
}
