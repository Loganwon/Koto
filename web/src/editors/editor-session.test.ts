import { describe, expect, it } from 'vitest';
import { createEditorSession } from './editor-session';
import type { WorkspaceEditor } from './types';

function editorStub(): WorkspaceEditor {
  return {
    render: () => undefined,
    getContent: () => '',
    applyToolCall: () => undefined,
    serialize: () => null,
    destroy: () => undefined,
  };
}

describe('EditorSession', () => {
  it('reads the live workspace store without publishing it on window', () => {
    const store = {
      fileId: 'file-1',
      fileType: 'pdf',
      fileName: 'draft.pdf',
      filePath: 'C:/draft.pdf',
      wsSourcePath: 'workspace/draft.pdf',
      activeTabPath: 'workspace/draft.pdf',
      activeEditor: null as WorkspaceEditor | null,
      isLoading: false,
      pinnedSelection: { sourceType: 'pdf' },
      openTabs: [{ path: 'workspace/draft.pdf', name: 'draft.pdf', fileType: 'pdf', modified: false }],
    };
    const session = createEditorSession(store);

    expect(session.snapshot().fileName).toBe('draft.pdf');
    store.fileName = 'renamed.pdf';
    expect(session.snapshot().fileName).toBe('renamed.pdf');
    expect((window as any).state).toBeUndefined();
  });

  it('owns editor mounting and loading updates through the explicit store dependency', () => {
    const store = { activeEditor: null as WorkspaceEditor | null, isLoading: false };
    const session = createEditorSession(store);
    const editor = editorStub();

    expect(session.mount(editor)).toBe(editor);
    expect(store.activeEditor).toBe(editor);
    expect(session.getActiveEditor()).toBe(editor);
    expect((editor as any).editorSession).toBe(session);

    session.setLoading(true);
    expect(store.isLoading).toBe(true);
    expect(session.snapshot().isLoading).toBe(true);
  });

  it('returns diagnostic tab projections instead of mutable tab objects', () => {
    const tab = { path: 'a.xlsx', name: 'a.xlsx', fileType: 'xlsx', modified: true, cache: { secret: true } };
    const session = createEditorSession({ openTabs: [tab] });
    const snapshot = session.snapshot();

    expect(snapshot.openTabs[0]).toMatchObject({ path: 'a.xlsx', fileType: 'xlsx', modified: true });
    expect(snapshot.openTabs[0]).not.toHaveProperty('cache');
    expect(snapshot.openTabs[0]).not.toBe(tab);
  });
});
