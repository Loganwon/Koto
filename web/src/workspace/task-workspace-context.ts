import { previewText } from './task-final-report';
import {
  baseNameFromPath,
  type TaskFileInfo,
} from './task-file-contract';

export interface CurrentOpenTaskFileState {
  fileName?: string;
  wsSourcePath?: string;
  filePath?: string;
  fileType?: string;
  fileId?: string;
}

export interface WorkspaceChatFileContextParams {
  currentFile?: TaskFileInfo | null;
  readyFiles?: TaskFileInfo[];
  openTabs?: any[];
  selectionText?: string;
  selectionSource?: string;
  selectionContext?: Record<string, any> | null;
}

export function buildWorkspaceRouteFiles(
  files: any[],
  targetFileIndex: number,
  sampleTaskContext?: (content: string) => string,
): TaskFileInfo[] {
  return (Array.isArray(files) ? files : [])
    .map((file, originalIndex) => ({ file, originalIndex }))
    .filter(({ file }) => file && !file.loading && !file.error)
    .slice(0, 8)
    .map(({ file, originalIndex }) => ({
      path: previewText(file.path || '', 260),
      name: previewText(file.name || '', 180),
      type: previewText(file.type || file.file_type || '', 40),
      target: originalIndex === targetFileIndex || file.target === true,
      content: previewText(
        typeof sampleTaskContext === 'function'
          ? sampleTaskContext(file.content || '')
          : String(file.content || ''),
        700,
      ),
    }));
}

export function buildCurrentOpenTaskFile(
  state: CurrentOpenTaskFileState,
  activeEditorContent = '',
): TaskFileInfo | null {
  const name = String(state && state.fileName || '').trim();
  // Workspace-opened files also have an uploaded/session copy in filePath.
  // The original workspace path is the writable source of truth and must win.
  const path = String(state && (state.wsSourcePath || state.filePath) || '').trim();
  const type = String(state && state.fileType || '').trim();
  const id = String(state && state.fileId || '').trim();
  if (!name && !path && !type && !id) return null;
  return {
    path: path || id || name,
    name: name || baseNameFromPath(path || id),
    type,
    content: previewText(activeEditorContent, 6000),
    target: false,
  };
}

export function buildWorkspaceChatFileContextValue(
  params: WorkspaceChatFileContextParams,
): Record<string, any> | null {
  const currentFile = params.currentFile || null;
  const selectionText = String(params.selectionText || '').trim();
  const selectionContext = params.selectionContext && typeof params.selectionContext === 'object'
    ? params.selectionContext
    : null;
  const readyFiles = Array.isArray(params.readyFiles) ? params.readyFiles : [];
  if (!currentFile && !selectionText && !readyFiles.length) return null;

  const openTabs = (Array.isArray(params.openTabs) ? params.openTabs : [])
    .slice(0, 10)
    .map((tab) => tab && (tab.path || tab.name))
    .filter(Boolean);
  const selectionMeta: Record<string, any> = {};
  if (selectionContext) {
    ['kind', 'sourceType', 'sheetName', 'rangeA1', 'rows', 'cols', 'rawText'].forEach((key) => {
      const value = selectionContext[key];
      if (value !== undefined && value !== null && String(value).trim() !== '') selectionMeta[key] = value;
    });
  }

  return {
    file_path: currentFile ? currentFile.path || '' : '',
    file_name: currentFile ? currentFile.name || '' : '',
    file_type: currentFile ? currentFile.type || currentFile.file_type || '' : '',
    open_tabs: openTabs,
    attached_files: readyFiles.map((file) => ({
      path: file.path || '',
      name: file.name || '',
      type: file.type || file.file_type || '',
    })),
    selection: selectionText,
    selection_source: String(params.selectionSource || '').trim(),
    selection_preview: previewText(
      selectionContext && selectionContext.previewText ? selectionContext.previewText : selectionText,
      800,
    ),
    selection_kind: String(selectionMeta.kind || selectionMeta.sourceType || '').trim(),
    selection_meta: selectionMeta,
  };
}
