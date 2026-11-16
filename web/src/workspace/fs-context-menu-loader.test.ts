import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getFeatureRegistry, registerFeatures } from '../shared/feature-registry';

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
    Object.keys(getFeatureRegistry()).forEach((key) => delete getFeatureRegistry()[key]);
    document.body.innerHTML = '<script id="koto-workspace-bundle"></script><div id="wa-ctx-menu"></div>';
    document.documentElement.removeAttribute('data-koto-fs-context-menu');
  });

  it('keeps close lightweight and replays the first context-menu request once', async () => {
    const show = vi.fn();
    const close = vi.fn();
    (document.getElementById('koto-workspace-bundle') as HTMLScriptElement).dataset.fsContextMenuBundleUrl = '/assets/fs-context-menu.v1.js';
    mocks.loadScript.mockImplementation(async () => {
      registerFeatures({
        _showBrowserCtx: show,
        _closeCtxMenu: close,
      });
    });

    const {
      installFsContextMenuLoader,
      loadFsContextMenu,
    } = await import('./fs-context-menu-loader');
    installFsContextMenuLoader();
    getFeatureRegistry()._closeCtxMenu();
    expect(mocks.loadScript).not.toHaveBeenCalled();

    const event = new MouseEvent('contextmenu', { clientX: 12, clientY: 24 });
    const row = document.createElement('div');
    row.dataset.path = 'C:/docs/report.docx';
    expect(getFeatureRegistry()._showBrowserCtx(event, row)).toBeNull();
    await loadFsContextMenu();
    await Promise.resolve();

    expect(mocks.loadScript).toHaveBeenCalledTimes(1);
    expect(mocks.loadScript).toHaveBeenCalledWith('/assets/fs-context-menu.v1.js', 60000);
    expect(show).toHaveBeenCalledWith(event, row);
    expect(document.documentElement.dataset.kotoFsContextMenu).toBe('ready');
  });
});
