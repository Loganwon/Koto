/**
 * AI Runtime Init & Registration — lazy initialization of AI runtimes,
 * conversation hydration, task registration.
 * Workspace AI runtime initialization.
 */

import { $, _LIGHTBULB_SVG, _PENCIL_SVG, _SLIDES_SVG, showToast, _csrfFetch } from './infrastructure';
import { state, _WA_RUNTIME_SESSION_ID } from './state';
import {
  _computeInlineDiff,
  _createPinnedSelectionContext,
  _getProposalRationaleText,
  _hideWelcome,
  _makeAIActionBar,
  _proposalCanApply,
  _selectionContextText,
  _setStreamBtn,
} from './ai-review';
import { _applyRouteEvent, _selectedCloudModelId } from './model-settings';

let _waAiResultsRuntime: any = (window as any)._waAiResultsRuntime || null;
let _waQuickActionRuntime: any = (window as any)._waQuickActionRuntime || null;
let _waConversationRuntime: any = (window as any)._waConversationRuntime || null;
let _waTaskDispatcher: any = (window as any)._waTaskDispatcher || null;
let _waQuickActionDispatcherAttached: boolean = Boolean((window as any)._waQuickActionDispatcherAttached);
let _hostSessionId: string = String((window as any)._hostSessionId || '').trim();

function _syncRuntimeGlobals(): void {
  (window as any)._waAiResultsRuntime = _waAiResultsRuntime;
  (window as any)._waQuickActionRuntime = _waQuickActionRuntime;
  (window as any)._waConversationRuntime = _waConversationRuntime;
  (window as any)._waTaskDispatcher = _waTaskDispatcher;
  (window as any)._waQuickActionDispatcherAttached = _waQuickActionDispatcherAttached;
  (window as any)._hostSessionId = _hostSessionId;
  (window as any)._WA_RUNTIME_SESSION_ID = _WA_RUNTIME_SESSION_ID;
}

function _sanitizeRenderedHtml(html: string): string {
  const sanitizer = (window as any)._sanitizeRenderedHtml;
  if (typeof sanitizer === 'function') return sanitizer(html);
  return String(html || '')
    .replace(/<script[\s\S]*?>[\s\S]*?<\/script>/gi, '')
    .replace(/\son[a-z]+\s*=\s*(['"]).*?\1/gi, '');
}

export function _waRenderMarkdown(text: string): string {
  if ((window as any).marked) {
    try { return _sanitizeRenderedHtml((window as any).marked.parse(text || '')); } catch (_) { /* noop */ }
  }
  return String(text || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/\n/g, '<br>');
}

function _hostChatSession(): string {
  const bridge = (window as any).KotoSessionBridge;
  if (bridge && typeof bridge.getSession === 'function') {
    const bridged = String(bridge.getSession() || '').trim();
    if (bridged) {
      _hostSessionId = bridged;
      _syncRuntimeGlobals();
      return bridged;
    }
  }
  return String(_hostSessionId || '').trim();
}

export function _waSession(): string {
  return _hostChatSession() || _WA_RUNTIME_SESSION_ID;
}

export function _waQuickActionModelMode(): string {
  const value = String(state.lockedModel || '').trim().toLowerCase();
  return ['cloud', 'deepseek', 'local'].includes(value) ? value : 'cloud';
}

export function _waSampleTaskContext(text: string, limit: number = 12000): string {
  const content = String(text || '');
  if (content.length <= limit) return content;
  const head = Math.max(Math.floor(limit * 0.7), 1);
  const tail = Math.max(limit - head - 48, 0);
  const marker = '\n\n...[中间内容已省略]...\n\n';
  if (tail <= 0) return content.slice(0, limit);
  return content.slice(0, head) + marker + content.slice(-tail);
}

function _handleProposals(data: any): void {
  const runtime = (window as any)._waAiResultsRuntime;
  if (runtime && typeof runtime.handleProposals === 'function') {
    runtime.handleProposals(data);
  }
}

export function _hydrateAiConversation(force: boolean = false): Promise<any[]> {
  if (!_waConversationRuntime || typeof _waConversationRuntime.hydrate !== 'function') return Promise.resolve([]);
  return _waConversationRuntime.hydrate({
    force,
    sessionId: _waSession(),
  }).then((turns: any[]) => {
    if (!force || state.isLoading) return turns;
    const restore = (window as any).WA && (window as any).WA._restoreActiveFileTasks;
    if (typeof restore !== 'function') return turns;
    return Promise.resolve(restore(force)).then(() => turns);
  });
}

export async function _persistWorkspaceConversationTurn(record: any): Promise<any> {
  const sessionId = _hostChatSession();
  if (!sessionId || /^workspace_runtime_/i.test(sessionId)) return null;
  const payload = record && typeof record === 'object' ? record : {};
  const userText = String(payload.user || payload.user_text || '').trim();
  const assistantText = String(payload.assistant || payload.assistant_text || '').trim();
  if (!userText || !assistantText) return null;
  try {
    const response = await _csrfFetch(`/api/sessions/${encodeURIComponent(sessionId)}/workspace-turn`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        user: userText,
        assistant: assistantText,
        attachments: Array.isArray(payload.attachments) ? payload.attachments : [],
        task_card_snapshot: payload.task_card_snapshot && typeof payload.task_card_snapshot === 'object'
          ? payload.task_card_snapshot
          : null,
        metadata: Object.assign({ source: 'workspace' }, payload.metadata || {}),
      }),
    });
    if (!response.ok) return null;
    const data = await response.json().catch(() => null);
    const bridge = (window as any).KotoSessionBridge;
    if (bridge && typeof bridge.refreshSessions === 'function') {
      Promise.resolve(bridge.refreshSessions()).catch(() => {});
    }
    const refreshAiSessions = (window as any).WA && (window as any).WA.refreshAiSessions;
    if (typeof refreshAiSessions === 'function') {
      Promise.resolve(refreshAiSessions({ silent: true })).catch(() => {});
    }
    return data;
  } catch (error) {
    console.warn('[WA] workspace turn persistence failed:', error);
    return null;
  }
}

export interface RuntimeConfig {
  state: any;
  getMessagesElement: () => HTMLElement | null;
  getSessionId?: () => string;
  hideWelcome?: () => void;
  renderMarkdown?: (text: string) => string;
  loadSessionHistory?: (sessionId: string) => Promise<any[]>;
  selectionContextText?: (ctx: any) => string;
  createPinnedSelectionContext?: (text: any, sourceMeta?: any) => any;
  showToast?: (message: string, kind?: string, duration?: number) => void;
  scheduleAutoSave?: () => void;
  getUserInputElement?: () => HTMLElement | null;
  sendMessage?: () => void;
  getActiveEditorContent?: () => string;
  sampleTaskContext?: (text: string, limit?: number) => string;
  getModelMode?: () => string;
  getSelectedCloudModelId?: () => string;
  getConversationHistory?: () => any[];
  beginAssistantTaskTurn?: (metadata: any) => any;
  syncAssistantTaskTurn?: (turnId: string, metadata: any) => any;
  appendAssistantTurn?: (text: string, metadata?: any) => any;
  persistTaskTurn?: (record: any) => Promise<any>;
  streamTaskFlow?: (options: any) => any;
  setStreamButton?: (streaming: boolean) => void;
}

export interface TaskEntryRoute {
  match?: (text: string) => boolean;
  handler?: (options: any) => any;
  modelId?: string;
  [key: string]: any;
}

export interface TaskQuickAction {
  action: string;
  handler?: (options: any) => any;
  [key: string]: any;
}

// ── Lazy initialization of all AI runtimes ───────────────────────
export function _initWorkspaceAiRuntimes(): void {
  if (!_waAiResultsRuntime && (window as any).WA && typeof (window as any).WA.createWorkspaceAiResultsRuntime === 'function') {
    _waAiResultsRuntime = (window as any).WA.createWorkspaceAiResultsRuntime({
      state,
      getMessagesElement: () => $('wa-ai-messages'),
      selectionContextText: _selectionContextText,
      createPinnedSelectionContext: _createPinnedSelectionContext,
      showToast,
      scheduleAutoSave: () => (window as any).WA.scheduleAutoSave && (window as any).WA.scheduleAutoSave(),
      getUserInputElement: () => $('wa-user-input'),
      sendMessage: () => (window as any).WA.sendMessage && (window as any).WA.sendMessage(),
      lightbulbIcon: _LIGHTBULB_SVG,
      pencilIcon: _PENCIL_SVG,
      getProposalRationaleText: _getProposalRationaleText,
      proposalCanApply: _proposalCanApply,
      getActiveProposalBatch: () => state._activeProposalBatch,
      acceptProposal: (...args: any[]) => (window as any).WA.acceptProposal(...args),
      rejectProposal: (...args: any[]) => (window as any).WA.rejectProposal(...args),
      modifyProposal: (...args: any[]) => (window as any).WA.modifyProposal(...args),
      submitModify: (...args: any[]) => (window as any).WA._submitModify(...args),
      batchAcceptAll: () => (window as any).WA.batchAcceptAll(),
      batchRejectAll: () => (window as any).WA.batchRejectAll(),
      computeInlineDiff: _computeInlineDiff,
    });
  }

  if (!_waConversationRuntime && (window as any).WA && typeof (window as any).WA.createWorkspaceAiConversation === 'function') {
    _waConversationRuntime = (window as any).WA.createWorkspaceAiConversation({
      state,
      getMessagesElement: () => $('wa-ai-messages'),
      getSessionId: _waSession,
      hideWelcome: _hideWelcome,
      renderMarkdown: _waRenderMarkdown,
      loadSessionHistory: async (sessionId: string) => {
        const normalized = String(sessionId || '').trim();
        if (!normalized || /^workspace_runtime_/i.test(normalized)) return [];
        const response = await fetch(`/api/sessions/${encodeURIComponent(normalized)}`);
        if (!response.ok) return [];
        const data = await response.json().catch(() => null);
        return data && Array.isArray(data.history) ? data.history : [];
      },
    });
  }

  if (!_waTaskDispatcher && (window as any).WA && typeof (window as any).WA.createTaskDispatcher === 'function') {
    _waTaskDispatcher = (window as any).WA.createTaskDispatcher({
      state,
      getActiveEditorContent: () => (state.activeEditor && typeof state.activeEditor.getContent === 'function')
        ? (state.activeEditor.getContent() || '')
        : '',
      sampleTaskContext: _waSampleTaskContext,
      getSessionId: _waSession,
      getModelMode: _waQuickActionModelMode,
      getSelectedCloudModelId: _selectedCloudModelId,
      getConversationHistory: () => _waConversationRuntime && typeof _waConversationRuntime.getHistoryForModel === 'function'
        ? _waConversationRuntime.getHistoryForModel(12)
        : (Array.isArray(state.conversation) ? state.conversation.slice(-12) : []),
      beginAssistantTaskTurn: (metadata: any) => _waConversationRuntime && typeof _waConversationRuntime.beginAssistantTaskTurn === 'function'
        ? _waConversationRuntime.beginAssistantTaskTurn(metadata || {})
        : null,
      syncAssistantTaskTurn: (turnId: string, metadata: any) => _waConversationRuntime && typeof _waConversationRuntime.syncAssistantTaskTurn === 'function'
        ? _waConversationRuntime.syncAssistantTaskTurn(turnId, metadata || {})
        : null,
      appendAssistantTurn: (text: string, metadata: any) => _waConversationRuntime && typeof _waConversationRuntime.appendAssistantTurn === 'function'
        ? _waConversationRuntime.appendAssistantTurn(text, Object.assign({ render: false }, metadata || {}))
        : null,
      persistTaskTurn: _persistWorkspaceConversationTurn,
      streamTaskFlow: (options: any) => (window as any).WA.streamTaskFlow(options),
      setStreamButton: _setStreamBtn,
    });
  }

  if (!_waQuickActionRuntime && (window as any).WA && typeof (window as any).WA.createWorkspaceQuickActionRuntime === 'function') {
    _waQuickActionRuntime = (window as any).WA.createWorkspaceQuickActionRuntime({
      state,
      getMessagesElement: () => $('wa-ai-messages'),
      getModelMode: _waQuickActionModelMode,
      getSelectedCloudModelId: _selectedCloudModelId,
      handleProposals: _handleProposals,
      makeAIActionBar: _makeAIActionBar,
      applyRouteEvent: _applyRouteEvent,
      setPendingToolCall: (parsed: any) => { (state as any).pendingToolCall = parsed; },
      appendAssistantTurn: (text: string, metadata: any) => _waConversationRuntime && typeof _waConversationRuntime.appendAssistantTurn === 'function'
        ? _waConversationRuntime.appendAssistantTurn(text, Object.assign({ render: false }, metadata || {}))
        : null,
      getSessionId: _waSession,
      getConversationHistory: () => _waConversationRuntime && typeof _waConversationRuntime.getHistoryForModel === 'function'
        ? _waConversationRuntime.getHistoryForModel(12)
        : (Array.isArray(state.conversation) ? state.conversation.slice(-12) : []),
      slidesIcon: _SLIDES_SVG,
    });
    _waQuickActionDispatcherAttached = false;
  }

  if (!_waQuickActionDispatcherAttached && _waQuickActionRuntime && _waTaskDispatcher && typeof _waQuickActionRuntime.attachDispatcher === 'function') {
    _waQuickActionRuntime.attachDispatcher(_waTaskDispatcher);
    _waQuickActionDispatcherAttached = true;
  }
  _syncRuntimeGlobals();
}

_initWorkspaceAiRuntimes();
_hydrateAiConversation(true).catch((error: any) => console.warn('[WA] AI history hydrate failed:', error));

// ── Public API ─────────────────────────────────────────────────────

export function hydrateAiHistory(force: boolean = true): Promise<any[]> {
  return _hydrateAiConversation(force);
}

export function useHostSession(sessionId: string, options?: { force?: boolean }): Promise<any[]> {
  _hostSessionId = String(sessionId || '').trim();
  _syncRuntimeGlobals();
  _initWorkspaceAiRuntimes();
  const syncSelection = (window as any).WA && (window as any).WA._syncAiSessionSelection;
  if (_hostSessionId && typeof syncSelection === 'function') {
    syncSelection(_hostSessionId);
  }
  return _hydrateAiConversation(options ? options.force !== false : true);
}

export function registerTaskQuickAction(definition: TaskQuickAction): any {
  _initWorkspaceAiRuntimes();
  if (!_waQuickActionRuntime || typeof _waQuickActionRuntime.registerAction !== 'function') return null;
  return _waQuickActionRuntime.registerAction(definition);
}

export function registerTaskEntryRoute(route: TaskEntryRoute): any {
  _initWorkspaceAiRuntimes();
  if (!_waTaskDispatcher || typeof _waTaskDispatcher.registerMessageRoute !== 'function') return null;
  return _waTaskDispatcher.registerMessageRoute(route);
}

export function registerTaskActionHandler(action: string, handler: (options: any) => any): any {
  _initWorkspaceAiRuntimes();
  if (!_waTaskDispatcher || typeof _waTaskDispatcher.registerQuickActionHandler !== 'function') return null;
  return _waTaskDispatcher.registerQuickActionHandler(action, handler);
}

// ── Backward compat ──
if (typeof window !== 'undefined') {
  (window as any).WA = (window as any).WA || {};
  (window as any).WA.hydrateAiHistory = hydrateAiHistory;
  (window as any).WA.useHostSession = useHostSession;
  (window as any).WA.registerTaskQuickAction = registerTaskQuickAction;
  (window as any).WA.registerTaskEntryRoute = registerTaskEntryRoute;
  (window as any).WA.registerTaskActionHandler = registerTaskActionHandler;
  (window as any).WA._initWorkspaceAiRuntimes = _initWorkspaceAiRuntimes;
  (window as any)._initWorkspaceAiRuntimes = _initWorkspaceAiRuntimes;
  (window as any)._hydrateAiConversation = _hydrateAiConversation;
  (window as any)._waSession = _waSession;
  (window as any)._waRenderMarkdown = _waRenderMarkdown;
  (window as any)._waQuickActionModelMode = _waQuickActionModelMode;
  (window as any)._waSampleTaskContext = _waSampleTaskContext;
  (window as any)._persistWorkspaceConversationTurn = _persistWorkspaceConversationTurn;
  _syncRuntimeGlobals();
}
// ── MCP Panel injection ──
setTimeout(() => {
  try {
    if ((window as any).WA && (window as any).WA.initMCPPanel) {
      const statusBar = document.querySelector(".activity-bar-bottom");
      if (statusBar) {
        const mcpEl = (window as any).WA.initMCPPanel();
        if (mcpEl) {
          mcpEl.style.position = "relative";
          statusBar.appendChild(mcpEl);
          console.log("[MCP] Panel mounted in activity bar");
        }
      }
    }
  } catch (_) { /* non-critical */ }
}, 2000);
