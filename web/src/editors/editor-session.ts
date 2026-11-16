import type { WorkspaceEditor } from './types';

export interface EditorSessionTabSnapshot {
  path: string;
  name: string;
  ext: string;
  fileType: string;
  fileId: string;
  filePath: string;
  modified: boolean;
  capabilityProfile: unknown;
}

export interface EditorSessionSnapshot {
  fileId: string | null;
  fileType: string | null;
  fileName: string | null;
  filePath: string | null;
  wsSourcePath: string | null;
  activeTabPath: string | null;
  isLoading: boolean;
  pinnedSelection: Record<string, unknown> | null;
  openTabs: EditorSessionTabSnapshot[];
}

interface EditorSessionStore {
  fileId?: string | null;
  fileType?: string | null;
  fileName?: string | null;
  filePath?: string | null;
  wsSourcePath?: string | null;
  activeTabPath?: string | null;
  activeEditor?: object | null;
  isLoading?: boolean;
  pinnedSelection?: Record<string, unknown> | null;
  openTabs?: Array<Record<string, any>>;
}

export interface EditorSession {
  snapshot(): EditorSessionSnapshot;
  getActiveEditor(): WorkspaceEditor | null;
  getPinnedSelection(): Record<string, unknown> | null;
  setLoading(loading: boolean): void;
  mount<T extends WorkspaceEditor>(editor: T): T;
}

function _stringOrNull(value: unknown): string | null {
  return value === null || value === undefined || value === '' ? null : String(value);
}

/** The sole editor-facing boundary for mutable workspace state. */
export function createEditorSession(store: EditorSessionStore): EditorSession {
  return {
    snapshot(): EditorSessionSnapshot {
      const openTabs = Array.isArray(store.openTabs) ? store.openTabs : [];
      return {
        fileId: _stringOrNull(store.fileId),
        fileType: _stringOrNull(store.fileType),
        fileName: _stringOrNull(store.fileName),
        filePath: _stringOrNull(store.filePath),
        wsSourcePath: _stringOrNull(store.wsSourcePath),
        activeTabPath: _stringOrNull(store.activeTabPath),
        isLoading: store.isLoading === true,
        pinnedSelection: store.pinnedSelection || null,
        openTabs: openTabs.map((tab) => ({
          path: String(tab?.path || ''),
          name: String(tab?.name || ''),
          ext: String(tab?.ext || ''),
          fileType: String(tab?.fileType || ''),
          fileId: String(tab?.fileId || ''),
          filePath: String(tab?.filePath || ''),
          modified: tab?.modified === true,
          capabilityProfile: tab?.capabilityProfile || null,
        })),
      };
    },
    getActiveEditor(): WorkspaceEditor | null {
      return (store.activeEditor as WorkspaceEditor | null | undefined) || null;
    },
    getPinnedSelection(): Record<string, unknown> | null {
      return store.pinnedSelection || null;
    },
    setLoading(loading: boolean): void {
      store.isLoading = loading;
    },
    mount<T extends WorkspaceEditor>(editor: T): T {
      Object.defineProperty(editor, 'editorSession', {
        configurable: true,
        enumerable: false,
        value: this,
        writable: false,
      });
      store.activeEditor = editor;
      return editor;
    },
  };
}
