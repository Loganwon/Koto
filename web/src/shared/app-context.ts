/**
 * AppContext ? Typed service locator replacing window-as-any antipattern.
 *
 * Instead of (window as any).showLoading(...), use:
 *   import { appCtx } from '../shared/app-context';
 *   appCtx.ui.showLoading('message', 'detail');
 *
 * Migration path:
 *   1. Register existing window globals here
 *   2. Refactor callers to import appCtx
 *   3. Remove window assignments once all callers migrated
 */

// ?? UI Helpers ??
export interface UiContext {
  showLoading: (message: string, detail?: string) => void;
  hideLoading: () => void;
  showMiniGame: () => void;
  hideMiniGame: () => void;
  showToast: (message: string, type?: string) => void;
  scrollToBottom: () => void;
  scrollToBottomForce: () => void;
  applyTheme: (theme: string) => void;
  updateThemeSelector: (theme: string) => void;
  setUIZoom: (zoom: string, immediate?: boolean) => void;
  hideStartupSplash: () => void;
  renderWelcomeScreen: () => void;
  initCapabilityButtons: () => void;
  initProactiveUI: () => void;
  initScrollBehavior: () => void;
}

// ?? Session Helpers ??
export interface SessionContext {
  currentSession: string;
  createNewSession: (name: string) => Promise<void>;
  generateSessionName: (hint: string) => string;
  autoTitleSession: (session: string, message: string, response: string) => void;
  confirmNewSession: () => void;
  loadSessions: () => Promise<void>;
  isSessionGenerating: (session: string) => boolean;
  setSessionGenerating: (session: string, value: boolean) => void;
  setSessionAbortController: (session: string, ctrl: AbortController | null) => void;
  getSessionAbortController: (session: string) => AbortController | null;
  getSessionTaskId: (session: string) => string | null;
  _newlyCreatedSessions: Set<string>;
}

// ?? Settings ??
export interface SettingsContext {
  currentSettings: Record<string, any>;
  loadSettings: () => Promise<void>;
  selectedModel: string;
}

// ?? File Helpers ??
export interface FileContext {
  selectedFiles: File[];
  removeFile: () => void;
  _kotoContextFiles: Array<{ path: string; name: string }>;
}

// ?? Chat Helpers ??
export interface ChatContext {
  renderMessage: (role: string, text: string, opts?: Record<string, any>) => string;
  parseMarkdown: (text: string) => string;
  escapeHtml: (value: string) => string;
  checkSetupStatus: () => Promise<void>;
  checkStatus: () => void;
  initProjectSelector: () => void;
}

// ?? Keyboard ??
export interface KeyboardContext {
  handleGlobalKeyDown: (e: KeyboardEvent) => void;
}

// ?? Sidebar ??
export interface SidebarContext {
  _syncSidebarState: (opts?: Record<string, any>) => void;
}

// ?? Aggregate Context ??
export interface AppContext {
  ui: UiContext;
  session: SessionContext;
  settings: SettingsContext;
  file: FileContext;
  chat: ChatContext;
  keyboard: KeyboardContext;
  sidebar: SidebarContext;
}

// ?? Implementation ??
// Lazy-initialized singleton that reads from window globals.
// After full migration, window assignments can be removed.

function noop(..._args: any[]): any {}
function noopAsync(..._args: any[]): Promise<void> { return Promise.resolve(); }
function noopStr(_hint?: string): string { return ''; }

const _win = (): any => (typeof window !== 'undefined' ? window : {});

function _get<T>(key: string, fallback: T): T {
  const val = _win()[key];
  return val !== undefined && val !== null ? val : fallback;
}

export function createAppContext(): AppContext {
  const w = _win();

  return {
    ui: {
      showLoading: w.showLoading || noop,
      hideLoading: w.hideLoading || noop,
      showMiniGame: w.showMiniGame || noop,
      hideMiniGame: w.hideMiniGame || noop,
      showToast: w.showToast || noop,
      scrollToBottom: w.scrollToBottom || noop,
      scrollToBottomForce: w.scrollToBottomForce || noop,
      applyTheme: w.applyTheme || noop,
      updateThemeSelector: w.updateThemeSelector || noop,
      setUIZoom: w.setUIZoom || noop,
      hideStartupSplash: w.hideStartupSplash || noop,
      renderWelcomeScreen: w.renderWelcomeScreen || noop,
      initCapabilityButtons: w.initCapabilityButtons || noop,
      initProactiveUI: w.initProactiveUI || noop,
      initScrollBehavior: w.initScrollBehavior || noop,
    },
    session: {
      get currentSession(): string { return w.currentSession || ''; },
      createNewSession: w.createNewSession || noopAsync,
      generateSessionName: w.generateSessionName || ((hint: string) => (hint || '???').slice(0, 24)),
      autoTitleSession: w.autoTitleSession || noop,
      confirmNewSession: w.confirmNewSession || noop,
      loadSessions: w.loadSessions || noopAsync,
      isSessionGenerating: w.isSessionGenerating || (() => false),
      setSessionGenerating: w.setSessionGenerating || noop,
      setSessionAbortController: w.setSessionAbortController || noop,
      getSessionAbortController: w.getSessionAbortController || (() => null),
      getSessionTaskId: w.getSessionTaskId || (() => null),
      _newlyCreatedSessions: w._newlyCreatedSessions || new Set(),
    },
    settings: {
      get currentSettings(): Record<string, any> { return w.currentSettings || {}; },
      loadSettings: w.loadSettings || noopAsync,
      get selectedModel(): string { return w.selectedModel || 'auto'; },
    },
    file: {
      get selectedFiles(): File[] { return Array.isArray(w.selectedFiles) ? w.selectedFiles : []; },
      removeFile: w.removeFile || noop,
      get _kotoContextFiles(): Array<{ path: string; name: string }> {
        return Array.isArray(w._kotoContextFiles) ? w._kotoContextFiles : [];
      },
    },
    chat: {
      renderMessage: w.renderMessage || (() => ''),
      parseMarkdown: w.parseMarkdown || ((text: string) => `<pre>${text}</pre>`),
      escapeHtml: w.escapeHtml || ((val: string) => String(val).replace(/[&<>"']/g, (c: string) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c] || c))),
      checkSetupStatus: w.checkSetupStatus || noopAsync,
      checkStatus: w.checkStatus || noop,
      initProjectSelector: w.initProjectSelector || noop,
    },
    keyboard: {
      handleGlobalKeyDown: w.handleGlobalKeyDown || noop,
    },
    sidebar: {
      _syncSidebarState: w._syncSidebarState || noop,
    },
  };
}

// Singleton instance
export const appCtx: AppContext = createAppContext();

// Re-export for convenience
export default appCtx;
