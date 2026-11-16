import { beforeEach, describe, expect, it, vi } from 'vitest';
import { registerFeatures } from '../shared/feature-registry';
const context = vi.hoisted(() => ({ fileId: null as string | null, fileName: '报告.docx', fileType: 'text',
  activeEditor: null, _aiFileContext: [], pinnedSelection: { text: '选区' } }));
vi.mock('../workspace/state', () => ({ state: context }));
vi.mock('../workspace/infrastructure', () => ({ showToast: vi.fn() }));

beforeEach(() => {
  vi.resetModules();
  context.fileId = null;
  document.body.innerHTML = `<aside id="sideNav"></aside><div id="workspaceView"><div id="wa-canvas"><textarea id="editor">未保存修改</textarea></div>
    <div id="wa-ai"><div id="wa-ai-chat-view"><div id="wa-ai-messages"><article class="wa-task-run">原任务</article></div></div>
    <textarea id="wa-user-input">未发送输入</textarea></div></div><button id="koto-document-toggle"></button>`;
});

describe('workspace startup entry', () => {
  it('returns keyboard focus to the context trigger when the materials drawer closes', async () => {
    document.body.insertAdjacentHTML('beforeend', '<button id="scope" data-koto-shell-action="materials">材料范围</button>'
      + '<div id="wa-left"><button role="tab" aria-selected="true">本任务材料</button></div>');
    registerFeatures({
      toggleMobileFiles: (force?: boolean) => document.body.classList.toggle('wa-mobile-files-open', force),
      closeMobileFiles: () => document.body.classList.remove('wa-mobile-files-open'),
    });
    const { initWorkspaceLayout } = await import('./workspace-layout');
    initWorkspaceLayout();
    const trigger = document.getElementById('scope')!;
    trigger.click();
    expect(document.body.classList.contains('wa-mobile-files-open')).toBe(true);
    expect(document.activeElement?.getAttribute('role')).toBe('tab');
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    expect(document.body.classList.contains('wa-mobile-files-open')).toBe(false);
    expect(document.activeElement).toBe(trigger);
  });

  it.each([false, true])('keeps one composer and existing work accessible with document=%s', async (hasDocument) => {
    context.fileId = hasDocument ? 'doc-1' : null;
    const input = document.getElementById('wa-user-input');
    const editor = document.getElementById('editor');
    const { initWorkspaceLayout } = await import('./workspace-layout');
    initWorkspaceLayout();
    expect(document.getElementById('workspaceView')?.dataset.layout).toBe(hasDocument ? 'document' : 'conversation');
    expect(document.getElementById('wa-ai')?.inert).toBe(false);
    expect(document.getElementById('wa-canvas')?.inert).toBe(!hasDocument);
    expect(document.querySelectorAll('#wa-user-input')).toHaveLength(1);
    expect(document.getElementById('wa-user-input')).toBe(input);
    expect((input as HTMLTextAreaElement).value).toBe('未发送输入');
    expect(document.getElementById('editor')).toBe(editor);
    expect((editor as HTMLTextAreaElement).value).toBe('未保存修改');
    expect(context.pinnedSelection.text).toBe('选区');
    expect(document.getElementById('wa-ai-messages')?.textContent).toBe('原任务');
  });
});
