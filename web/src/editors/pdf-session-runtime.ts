import type { EditorSession, EditorSessionSnapshot } from './editor-session';
import type { WorkspaceEditor } from './types';

let activeSession: EditorSession | null = null;

export function bindPdfSession(session: EditorSession): void {
  activeSession = session;
}

export function releasePdfSession(session: EditorSession): void {
  if (activeSession === session) activeSession = null;
}

export function getActivePdfEditor(): WorkspaceEditor | null {
  return activeSession?.getActiveEditor() || null;
}

export function getPdfDocument(editor: any): any {
  return editor && (editor._pdfDoc || editor._pdf || null);
}

export function getPdfSessionSnapshot(): EditorSessionSnapshot {
  return activeSession?.snapshot() || {
    fileId: null,
    fileType: null,
    fileName: null,
    filePath: null,
    wsSourcePath: null,
    activeTabPath: null,
    isLoading: false,
    pinnedSelection: null,
    openTabs: [],
  };
}
