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
}

export interface ParsedWorkspaceSseEvents {
  events: any[];
  remainder: string;
}

export function parseWorkspaceSseEvents(
  buffer: string,
  flush: boolean,
): ParsedWorkspaceSseEvents {
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
    try {
      events.push(JSON.parse(dataLines.join('\n')));
    } catch {
      // Ignore malformed frames and keep consuming later valid events.
    }
  });
  return { events, remainder };
}

export function appendWorkspaceChatEvents(
  currentText: string,
  events: any[],
): string {
  let text = String(currentText || '');
  (Array.isArray(events) ? events : []).forEach((event) => {
    const type = String(event && event.type || '').trim();
    if (type === 'token') {
      text += String(event.content || event.text || '');
      return;
    }
    if (type === 'error') {
      throw new Error(String(event.message || event.text || '对话失败'));
    }
  });
  return text;
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
  return { route: route || 'light_chat', lockedTask: 'CHAT', taskKind: 'message', loadingText: '正在思考…' };
}

function renderAssistantText(loadingEl: HTMLElement | undefined, text: string): void {
  if (!loadingEl) return;
  const value = String(text || '');
  loadingEl.dataset.rawText = value;
  loadingEl.innerHTML = renderWorkspaceMarkdown(value);
}

export function createWorkspaceChatStreamer(deps: WorkspaceDirectChatDeps) {
  return async function streamWorkspaceChatRoute(
    context: WorkspaceDirectChatContext,
    routeDecision: Record<string, any>,
  ): Promise<any> {
    const loadingEl = context.loadingEl;
    const routeContract = directChatRouteContract(routeDecision);
    const ctrl = new AbortController();
    let assistantText = '';
    deps.state._streamAbortCtrl = ctrl;
    deps.state.isLoading = true;
    if (typeof deps.setStreamButton === 'function') deps.setStreamButton(true);
    if (loadingEl) {
      loadingEl.classList.add('streaming');
      loadingEl.textContent = routeContract.loadingText;
      loadingEl.dataset.workspaceRoute = routeContract.route;
      loadingEl.dataset.workspaceRouteSource = String(routeDecision.route_source || '');
    }
    try {
      const sessionId = typeof deps.ensureSessionId === 'function'
        ? await deps.ensureSessionId()
        : (typeof deps.getSessionId === 'function' ? deps.getSessionId() : 'workspace_default');
      const response = await deps.csrfFetch('/api/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session: sessionId || 'workspace_default',
          message: context.text,
          locked_task: routeContract.lockedTask,
          locked_model: chatStreamLockedModel(
            typeof deps.getModelMode === 'function' ? deps.getModelMode() : '',
            typeof deps.getSelectedCloudModelId === 'function'
              ? deps.getSelectedCloudModelId()
              : '',
          ),
          skills_enabled: false,
          workspace_route_intent: routeDecision,
          file_context: deps.buildFileContext(context),
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
        const nextText = appendWorkspaceChatEvents(assistantText, parsed.events);
        if (nextText !== assistantText) {
          assistantText = nextText;
          renderAssistantText(loadingEl, assistantText);
        }
        if (context.msgs) context.msgs.scrollTop = context.msgs.scrollHeight;
      }
      buffer += decoder.decode();
      const trailing = parseWorkspaceSseEvents(buffer, true);
      assistantText = appendWorkspaceChatEvents(assistantText, trailing.events);
      assistantText = assistantText.trim() || '已完成。';
      if (loadingEl) {
        loadingEl.classList.remove('streaming');
        renderAssistantText(loadingEl, assistantText);
      }
      deps.appendAssistantTurn(assistantText, {
        loadingEl,
        task_kind: routeContract.taskKind,
        status: 'done',
        route_intent: routeDecision,
        skip_model_context: false,
      });
      return { routeId: routeContract.route, assistantText, routeDecision };
    } catch (error: any) {
      const aborted = error && error.name === 'AbortError';
      assistantText = aborted
        ? '已停止。'
        : `对话失败：${error && error.message ? error.message : error}`;
      if (loadingEl) {
        loadingEl.classList.remove('streaming');
        renderAssistantText(loadingEl, assistantText);
      }
      deps.appendAssistantTurn(assistantText, {
        loadingEl,
        task_kind: routeContract.taskKind,
        status: aborted ? 'cancelled' : 'error',
        route_intent: routeDecision,
      });
      return { routeId: routeContract.route, assistantText, routeDecision, error };
    } finally {
      if (deps.state._streamAbortCtrl === ctrl) deps.state._streamAbortCtrl = null;
      deps.state.isLoading = false;
      if (typeof deps.setStreamButton === 'function') deps.setStreamButton(false);
    }
  };
}
import { renderWorkspaceMarkdown } from './markdown-rendering';
