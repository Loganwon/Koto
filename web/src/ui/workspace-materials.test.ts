import { beforeEach, describe, expect, it, vi } from 'vitest';
const context = vi.hoisted(() => ({ fileId: 'doc-1', fileName: '报告.docx', activeTabPath: 'workspace/report.docx',
  pinnedSelection: { text: '已选文本' }, _aiTargetFileIdx: 0,
  _aiFileContext: [{ name: '<script>.txt', path: 'workspace/reference.txt', error: '', loading: false }] }));
const api = vi.hoisted(() => ({ removeAIFileContext: vi.fn(), openRecentFile: vi.fn(async () => {}), pickAIContextFiles: vi.fn(),
  showDocumentLayout: vi.fn(), closeMobileFiles: vi.fn() }));
vi.mock('../workspace/state', () => ({ state: context }));
vi.mock('../shared/feature-registry', () => ({ getFeatureRegistry: () => api }));
vi.mock('../workspace/infrastructure', () => ({ showToast: vi.fn() }));
import { initWorkspaceMaterials, syncWorkspaceMaterials } from './workspace-materials';

beforeEach(() => {
  vi.clearAllMocks();
  document.body.innerHTML = `<button id="koto-context-scope"></button><div role="tablist">
    <button role="tab" data-materials-tab="task" aria-selected="true">本任务材料</button>
    <button role="tab" data-materials-tab="all" aria-selected="false">全部文件</button></div>
    <section data-materials-panel="task"><div id="koto-task-material-list"></div><button id="koto-add-material"></button></section>
    <section data-materials-panel="all" hidden><input id="wa-search"></section>`;
});

describe('task materials projection', () => {
  it('shows the current document and explicit attachments without interpreting names as HTML', async () => {
    initWorkspaceMaterials();
    expect(document.getElementById('koto-context-scope')?.textContent).toContain('引用选区 4 字');
    expect(document.querySelectorAll('.koto-material-row')).toHaveLength(2);
    expect(document.querySelector('#koto-task-material-list script')).toBeNull();
    expect(document.getElementById('koto-task-material-list')?.textContent).toContain('修改目标');
    const open = document.querySelector<HTMLButtonElement>('.koto-material-name')!;
    open.click(); await Promise.resolve();
    expect(api.showDocumentLayout).toHaveBeenCalledTimes(1);
    expect(api.openRecentFile).not.toHaveBeenCalled();
    document.querySelectorAll<HTMLButtonElement>('.koto-material-name')[1].click();
    await Promise.resolve();
    expect(api.openRecentFile).toHaveBeenCalledWith('workspace/reference.txt');
    syncWorkspaceMaterials();
    expect(document.querySelector('.koto-material-name')).toBe(open);
    open.focus();
    context._aiFileContext[0].loading = true;
    syncWorkspaceMaterials();
    expect(document.activeElement?.getAttribute('aria-label')).toBe('返回当前文档 报告.docx');
    context._aiFileContext[0].loading = false;
    syncWorkspaceMaterials();
    document.querySelector<HTMLButtonElement>('[aria-label="移除材料 <script>.txt"]')?.click();
    expect(api.removeAIFileContext).toHaveBeenCalledWith(0);
  });

  it('switches tabs with the keyboard without losing composer or editor content', () => {
    document.body.insertAdjacentHTML('beforeend', '<textarea id="draft">未发出的任务</textarea>');
    const draft = document.getElementById('draft');
    initWorkspaceMaterials();
    const tabs = document.querySelectorAll<HTMLButtonElement>('[role="tab"]');
    tabs[0].dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
    expect(tabs[1].getAttribute('aria-selected')).toBe('true');
    expect(document.activeElement).toBe(tabs[1]);
    expect(document.querySelector<HTMLElement>('[data-materials-panel="all"]')?.hidden).toBe(false);
    expect(document.getElementById('draft')).toBe(draft);
    expect((draft as HTMLTextAreaElement).value).toBe('未发出的任务');
  });
});
