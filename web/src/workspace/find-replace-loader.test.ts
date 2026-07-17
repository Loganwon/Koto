import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  loadScript: vi.fn(),
}));

vi.mock('../editors/cdn-loaders', () => ({
  _loadScript: mocks.loadScript,
}));

describe('workspace find/replace loader', () => {
  beforeEach(() => {
    vi.resetModules();
    mocks.loadScript.mockReset();
    document.body.innerHTML = '';
    document.documentElement.removeAttribute('data-koto-find-replace');
    delete (window as any).__kotoWorkspaceEditorAssets;
    (window as any).WA = {};
  });

  it('loads the configured runtime once and catches up focused input state', async () => {
    const install = vi.fn();
    const syncInput = vi.fn();
    (window as any).__kotoWorkspaceEditorAssets = {
      'find-replace-bundle': '/assets/find-replace.v1.js',
    };
    mocks.loadScript.mockImplementation(async () => {
      (window as any).WA.installWorkspaceFindReplace = install;
      (window as any).WA.docxFindInput = syncInput;
    });

    const input = document.createElement('input');
    input.dataset.waFindInput = 'docx';
    input.value = '合同';
    document.body.appendChild(input);
    input.focus();

    const { loadWorkspaceFindReplace } = await import('./find-replace-loader');
    const deps = { getActiveEditor: vi.fn() };
    await loadWorkspaceFindReplace(deps);
    await loadWorkspaceFindReplace(deps);

    expect(mocks.loadScript).toHaveBeenCalledTimes(1);
    expect(mocks.loadScript).toHaveBeenCalledWith('/assets/find-replace.v1.js', 60000);
    expect(install).toHaveBeenCalledWith(deps);
    expect(syncInput).toHaveBeenCalledWith('合同');
    expect(document.documentElement.dataset.kotoFindReplace).toBe('ready');
  });
});
