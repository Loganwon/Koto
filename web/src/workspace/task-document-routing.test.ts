import { beforeEach, describe, expect, it, vi } from 'vitest';

const fetchMock = vi.hoisted(() => vi.fn());
vi.mock('./infrastructure', () => ({ _csrfFetch: fetchMock, showToast: vi.fn() }));
vi.mock('../shared/frontend-observer-loader', () => ({ loadFrontendObserver: async () => {} }));

import { createTaskDispatcher } from './task-dispatcher';
import { supportsLiveDocumentTools } from './task-workspace-context';

beforeEach(() => fetchMock.mockReset());

describe('current document capability routing', () => {
  it.each(['xlsx', 'pptx', 'pdf'])('keeps %s on the existing file tool runtime', async (type) => {
    const run = vi.fn(async () => ({ summary: '处理完成', status: 'done' }));
    const dispatcher = createTaskDispatcher({
      state: { fileName: `input.${type}`, fileType: type, wsSourcePath: `input.${type}`,
        fileId: 'f', _aiFileContext: [], conversation: [] },
      streamTaskFlow: run,
    });
    await dispatcher.dispatchMessage({ text: '处理当前内容' });
    expect(run).toHaveBeenCalledOnce();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(run.mock.calls[0][0].payload.options.workspace_route_intent.route_source).toBe('active_file_format');
  });

  it('only admits formats with implemented semantic UI editing', () => {
    expect(supportsLiveDocumentTools({ path: 'a', type: 'docx' })).toBe(true);
    expect(supportsLiveDocumentTools({ path: 'a', type: 'text' })).toBe(true);
    expect(supportsLiveDocumentTools({ path: 'a', type: 'xlsx' })).toBe(false);
    expect(supportsLiveDocumentTools({ path: 'a', type: 'pdf' })).toBe(false);
  });

  it('preserves a normal single-input PPT edit without inventing a write mode', async () => {
    const run = vi.fn(async () => ({ summary: '处理完成', status: 'done' }));
    const dispatcher = createTaskDispatcher({
      state: { fileName: 'deck.pptx', fileType: 'pptx', wsSourcePath: 'deck.pptx', fileId: 'deck-file', _aiFileContext: [], conversation: [] },
      streamTaskFlow: run,
    });
    const task = '把这个 PPT 编辑得好看一点，做成专业高级的汇报风格';
    await dispatcher.dispatchMessage({ text: task });
    const payload = run.mock.calls[0][0].payload;
    expect(payload.task).toBe(task);
    expect(payload.current_file).toMatchObject({ path: 'deck.pptx', type: 'pptx', target: false });
    expect(payload.files).toEqual([]);
    expect(payload.target_path).toBe('');
    expect(payload.options.output_mode).toBeUndefined();
    expect(payload.options.workspace_route_intent.route_source).toBe('active_file_format');
  });
});
