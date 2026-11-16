import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getFeatureRegistry, registerFeatures } from '../shared/feature-registry';

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
    Object.keys(getFeatureRegistry()).forEach((key) => delete getFeatureRegistry()[key]);
    document.body.innerHTML = '<script id="koto-workspace-bundle"></script>';
    document.documentElement.removeAttribute('data-koto-find-replace');
  });

  it('loads the configured runtime once and catches up focused input state', async () => {
    const install = vi.fn();
    const syncInput = vi.fn();
    (document.getElementById('koto-workspace-bundle') as HTMLScriptElement).dataset.findReplaceBundleUrl = '/assets/find-replace.v1.js';
    mocks.loadScript.mockImplementation(async () => {
      registerFeatures({ installWorkspaceFindReplace: install, docxFindInput: syncInput });
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
