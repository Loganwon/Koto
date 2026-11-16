import { beforeEach, describe, expect, it, vi } from 'vitest';

const testState = vi.hoisted(() => ({ fileId: null as string | null, fileName: null as string | null, activeEditor: null }));
vi.mock('../workspace/state', () => ({ state: testState }));
import { _expandWAPanel, showConversationLayout, showDocumentLayout, toggleAiPanel } from './workspace-layout';
import { mountWorkspaceAiComposer } from '../workspace/ai-composer';

beforeEach(() => {
  testState.fileId = 'doc-1';
  testState.fileName = '报告.docx';
  document.body.className = '';
  document.body.innerHTML = `<aside id="sideNav"></aside><div id="workspaceView"><div id="wa-ai"></div><div id="wa-canvas"><textarea id="editor">未保存的修改</textarea></div></div><button id="koto-document-toggle"></button>`;
  showConversationLayout();
  toggleAiPanel();
});

describe('document AI dock', () => {
  it('opens an actionable conversation without creating another composer', () => {
    testState.fileId = null;
    document.body.insertAdjacentHTML('beforeend', '<div id="wa-chat-composer-host"><div id="wa-ai-input-area"><textarea id="wa-user-input"></textarea><button id="wa-send-btn"></button></div></div>');
    const original = document.getElementById('wa-user-input');
    showConversationLayout();
    mountWorkspaceAiComposer('chat');
    mountWorkspaceAiComposer('chat');
    expect(document.getElementById('workspaceView')?.dataset.layout).toBe('conversation');
    expect(document.getElementById('wa-ai')?.inert).toBe(false);
    expect(document.querySelectorAll('#wa-user-input')).toHaveLength(1);
    expect(document.getElementById('wa-user-input')).toBe(original);
  });

  it('keeps the native layout usable when persisted browser storage is unavailable', () => {
    const read = vi.fn(() => { throw new Error('storage denied'); });
    vi.stubGlobal('localStorage', { getItem: read, setItem: read });
    try {
      showDocumentLayout();
      _expandWAPanel();
      expect(document.getElementById('wa-canvas')?.inert).toBe(false);
      expect(document.getElementById('wa-ai')?.inert).toBe(false);
      expect(read).not.toHaveBeenCalled();
    } finally { vi.unstubAllGlobals(); }
  });
  it('opens and closes AI without hiding or remounting the unsaved editor', () => {
    const editor = document.getElementById('editor');
    showDocumentLayout();
    toggleAiPanel();
    expect(document.getElementById('wa-canvas')?.inert).toBe(false);
    expect(document.getElementById('wa-ai')?.inert).toBe(false);
    toggleAiPanel();
    expect(document.getElementById('wa-ai')?.inert).toBe(true);
    expect(document.getElementById('editor')).toBe(editor);
    expect((editor as HTMLTextAreaElement).value).toBe('未保存的修改');
  });

  it('keeps both document and AI accessible on a narrow screen', () => {
    document.body.classList.add('koto-layout-compact');
    showDocumentLayout();
    expect(document.getElementById('wa-ai')?.inert).toBe(true);
    expect(document.getElementById('wa-canvas')?.inert).toBe(false);
    toggleAiPanel();
    expect(document.getElementById('workspaceView')?.dataset.layout).toBe('document');
    expect(document.getElementById('wa-ai')?.inert).toBe(false);
    expect(document.getElementById('wa-canvas')?.inert).toBe(false);
  });

  it('keeps the unique conversation entry accessible when no file is open', () => {
    testState.fileId = null;
    showDocumentLayout();
    expect(document.getElementById('workspaceView')?.dataset.layout).toBe('conversation');
    expect(document.getElementById('koto-document-toggle')?.hidden).toBe(true);
    expect(document.getElementById('wa-canvas')?.inert).toBe(true);
    expect(document.getElementById('wa-ai')?.inert).toBe(false);
  });

  it('reveals the AI process and restores tasks alongside an open document', () => {
    showDocumentLayout();
    _expandWAPanel();
    expect(document.getElementById('workspaceView')?.hasAttribute('data-ai-open')).toBe(true);
    showConversationLayout();
    expect(document.getElementById('workspaceView')?.dataset.layout).toBe('document');
    expect(document.getElementById('wa-canvas')?.inert).toBe(false);
  });
});
