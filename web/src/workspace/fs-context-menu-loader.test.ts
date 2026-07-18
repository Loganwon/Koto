import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  loadScript: vi.fn(),
}));

vi.mock('../editors/cdn-loaders', () => ({
  _loadScript: mocks.loadScript,
}));

describe('file context menu loader', () => {
  beforeEach(() => {
    vi.resetModules();
    mocks.loadScript.mockReset();
    document.body.innerHTML = '<div id="wa-ctx-menu"></div>';
    document.documentElement.removeAttribute('data-koto-fs-context-menu');
    delete (window as any).__kotoWorkspaceEditorAssets;
    (window as any).WA = {};
  });

  it('keeps close lightweight and replays the first context-menu request once', async () => {
    const show = vi.fn();
    const close = vi.fn();
    (window as any).__kotoWorkspaceEditorAssets = {
      'fs-context-menu-bundle': '/assets/fs-context-menu.v1.js',
    };
    mocks.loadScript.mockImplementation(async () => {
      Object.assign((window as any).WA, {
        _showBrowserCtx: show,
        _closeCtxMenu: close,
      });
    });

    const {
      installFsContextMenuLoader,
      loadFsContextMenu,
    } = await import('./fs-context-menu-loader');
    installFsContextMenuLoader();
    (window as any).WA._closeCtxMenu();
    expect(mocks.loadScript).not.toHaveBeenCalled();

    const event = new MouseEvent('contextmenu', { clientX: 12, clientY: 24 });
    const row = document.createElement('div');
    row.dataset.path = 'C:/docs/report.docx';
    expect((window as any).WA._showBrowserCtx(event, row)).toBeNull();
    await loadFsContextMenu();
    await Promise.resolve();

    expect(mocks.loadScript).toHaveBeenCalledTimes(1);
    expect(mocks.loadScript).toHaveBeenCalledWith('/assets/fs-context-menu.v1.js', 60000);
    expect(show).toHaveBeenCalledWith(event, row);
    expect(document.documentElement.dataset.kotoFsContextMenu).toBe('ready');
  });
});
