import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  loadScript: vi.fn(),
}));

vi.mock('../editors/cdn-loaders', () => ({
  _loadScript: mocks.loadScript,
}));

describe('task workbench loader', () => {
  beforeEach(() => {
    vi.resetModules();
    mocks.loadScript.mockReset();
    document.documentElement.removeAttribute('data-koto-task-workbench');
    delete (window as any).__kotoWorkspaceEditorAssets;
    (window as any).WA = {};
  });

  it('replays the first open request after loading the configured runtime once', async () => {
    const init = vi.fn();
    const open = vi.fn();
    const refresh = vi.fn(async () => ({ status: 'completed' }));
    (window as any).__kotoWorkspaceEditorAssets = {
      'task-workbench-bundle': '/assets/task-workbench.v1.js',
    };
    mocks.loadScript.mockImplementation(async () => {
      Object.assign((window as any).WA, {
        initTaskWorkbench: init,
        openTaskWorkbenchForCurrentRun: open,
        refreshCurrentTaskFlow: refresh,
      });
    });

    const {
      installTaskWorkbenchLoader,
      loadTaskWorkbench,
    } = await import('./task-workbench-loader');
    installTaskWorkbenchLoader();
    const bridge = (window as any).WA.openTaskWorkbenchForCurrentRun;
    const request = { taskId: 'task-42', runId: 'run-7', scroll: false };
    expect(bridge(request)).toBeNull();
    await loadTaskWorkbench();
    await Promise.resolve();

    expect(mocks.loadScript).toHaveBeenCalledTimes(1);
    expect(mocks.loadScript).toHaveBeenCalledWith('/assets/task-workbench.v1.js', 60000);
    expect(open).toHaveBeenCalledWith(request);
    expect(document.documentElement.dataset.kotoTaskWorkbench).toBe('ready');
    await expect((window as any).WA.refreshCurrentTaskFlow()).resolves.toEqual({ status: 'completed' });
  });
});
