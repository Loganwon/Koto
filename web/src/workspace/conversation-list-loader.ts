import { _loadScript } from '../editors/cdn-loaders';
import { getWorkspaceApi, publishWorkspaceApi } from '../shared/workspace-api';
import {
  mountWorkspaceAiComposer,
  resizeWorkspaceAiComposer,
  syncWorkspaceAiComposerSendState,
  workspaceAiComposerMode,
} from './ai-composer';

type SessionRefreshOptions = { silent?: boolean };
type OpenSessionOptions = SessionRefreshOptions & { force?: boolean };
type NewSessionOptions = { focus?: boolean; toast?: boolean };

let conversationListLoadPromise: Promise<void> | null = null;
let loaderInstalled = false;
const composerStateBoundInputs = new WeakSet<HTMLTextAreaElement>();

function installComposerStateSync(): void {
  const input = document.getElementById('wa-user-input') as HTMLTextAreaElement | null;
  if (!input || composerStateBoundInputs.has(input)) return;

  composerStateBoundInputs.add(input);
  input.addEventListener('input', () => {
    resizeWorkspaceAiComposer(input);
    syncWorkspaceAiComposerSendState(workspaceAiComposerMode());
  });
}

function conversationListAssetUrl(): string {
  const assets = (window as any).__kotoWorkspaceEditorAssets || {};
  return String(
    assets['conversation-list-bundle']
    || '/static/js/build/conversation-list-bundle.js',
  );
}

function hasLoadedConversationList(): boolean {
  const api = getWorkspaceApi();
  return typeof api.showAiSessionList === 'function'
    && api.showAiSessionList !== showAiSessionListBridge
    && typeof api.openAiSession === 'function'
    && api.openAiSession !== openAiSessionBridge
    && typeof api.submitUnifiedAiComposer === 'function'
    && api.submitUnifiedAiComposer !== submitUnifiedAiComposerBridge;
}

export function loadConversationList(): Promise<void> {
  if (conversationListLoadPromise) return conversationListLoadPromise;
  if (hasLoadedConversationList()) {
    document.documentElement.setAttribute('data-koto-conversation-list', 'ready');
    return Promise.resolve();
  }

  document.documentElement.setAttribute('data-koto-conversation-list', 'loading');
  conversationListLoadPromise = _loadScript(conversationListAssetUrl(), 60000)
    .then(() => {
      if (!hasLoadedConversationList()) {
        throw new Error('会话历史运行时加载后未注册完整接口');
      }
      document.documentElement.setAttribute('data-koto-conversation-list', 'ready');
    })
    .catch((error) => {
      conversationListLoadPromise = null;
      document.documentElement.setAttribute('data-koto-conversation-list', 'error');
      throw error;
    });
  return conversationListLoadPromise;
}

function reportLoadFailure(error: unknown): void {
  console.warn('[Koto] Conversation history runtime unavailable:', error);
}

function replayAfterLoad(name: string, args: any[] = []): Promise<any> {
  return loadConversationList().then(() => {
    const method = getWorkspaceApi()[name];
    if (typeof method === 'function' && method !== BRIDGE_METHODS[name]) {
      return method(...args);
    }
    return null;
  });
}

function showAiSessionListBridge(): null {
  void replayAfterLoad('showAiSessionList').catch(reportLoadFailure);
  return null;
}

function showAiChatBridge(): void {
  const listView = document.getElementById('wa-ai-session-list-view');
  const chatView = document.getElementById('wa-ai-chat-view');
  if (listView) listView.hidden = true;
  if (chatView) chatView.hidden = false;
  mountWorkspaceAiComposer('chat');
}

function refreshAiSessionsBridge(options: SessionRefreshOptions = {}): Promise<any[]> {
  // Background persistence refreshes should not pull the history UI into the
  // first chat interaction. The real runtime fetches fresh data when opened.
  if (options.silent) return Promise.resolve([]);
  return replayAfterLoad('refreshAiSessions', [{ ...options }]);
}

function openAiSessionBridge(sessionId: string, options: OpenSessionOptions = {}): Promise<any> {
  return replayAfterLoad('openAiSession', [sessionId, { ...options }]);
}

function deleteAiSessionBridge(sessionId: string): Promise<any> {
  return replayAfterLoad('deleteAiSession', [sessionId]);
}

function clearAiSessionsBridge(): Promise<any> {
  return replayAfterLoad('clearAiSessions');
}

function newAiSessionBridge(options: NewSessionOptions = {}): Promise<any> {
  return replayAfterLoad('newAiSession', [{ ...options }]);
}

function submitUnifiedAiComposerBridge(): any {
  if (workspaceAiComposerMode() === 'sessionList') {
    return replayAfterLoad('submitUnifiedAiComposer');
  }
  const send = getWorkspaceApi().sendMessage;
  return typeof send === 'function' ? send() : null;
}

function handleUnifiedComposerKeydownBridge(event: KeyboardEvent): void {
  if (workspaceAiComposerMode() === 'sessionList') {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      void replayAfterLoad('submitUnifiedAiComposer').catch(reportLoadFailure);
      return;
    }
    void replayAfterLoad('handleUnifiedComposerKeydown', [event]).catch(reportLoadFailure);
    return;
  }

  const fallback = getWorkspaceApi().handleInputKeydown;
  if (typeof fallback === 'function' && fallback !== handleUnifiedComposerKeydownBridge) {
    fallback(event);
    return;
  }
  const target = event.target as HTMLTextAreaElement | null;
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    const send = getWorkspaceApi().sendMessage;
    if (typeof send === 'function') send();
  } else if (target && target.tagName === 'TEXTAREA') {
    window.setTimeout(() => resizeWorkspaceAiComposer(target), 0);
  }
}

function sendSessionListComposerBridge(): Promise<any> {
  return replayAfterLoad('submitUnifiedAiComposer');
}

function handleSessionListComposerKeydownBridge(event: KeyboardEvent): void {
  handleUnifiedComposerKeydownBridge(event);
}

function syncAiSessionSelectionBridge(sessionId: string): void {
  (window as any)._hostSessionId = String(sessionId || '').trim();
}

function activeAiSessionMetaBridge(): { id: string } | null {
  const id = String((window as any)._hostSessionId || '').trim();
  return id ? { id } : null;
}

const BRIDGE_METHODS: Record<string, Function> = {
  showAiSessionList: showAiSessionListBridge,
  showAiChat: showAiChatBridge,
  refreshAiSessions: refreshAiSessionsBridge,
  openAiSession: openAiSessionBridge,
  deleteAiSession: deleteAiSessionBridge,
  clearAiSessions: clearAiSessionsBridge,
  newAiSession: newAiSessionBridge,
  submitUnifiedAiComposer: submitUnifiedAiComposerBridge,
  handleUnifiedComposerKeydown: handleUnifiedComposerKeydownBridge,
  sendSessionListComposer: sendSessionListComposerBridge,
  handleSessionListComposerKeydown: handleSessionListComposerKeydownBridge,
  _syncAiSessionSelection: syncAiSessionSelectionBridge,
  _activeAiSessionMeta: activeAiSessionMetaBridge,
};

export function installConversationListLoader(): void {
  if (loaderInstalled) return;
  loaderInstalled = true;
  publishWorkspaceApi({
    ...BRIDGE_METHODS,
    loadConversationList,
  });
  installComposerStateSync();
  syncWorkspaceAiComposerSendState(workspaceAiComposerMode());
}
