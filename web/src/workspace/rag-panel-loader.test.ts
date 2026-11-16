import { beforeEach, describe, expect, it, vi } from 'vitest';
const load = vi.hoisted(() => vi.fn());
vi.mock('../editors/cdn-loaders', () => ({ _loadScript: load }));
vi.mock('../shared/feature-registry', () => ({ registerFeatures: vi.fn() }));
vi.mock('../shared/workspace-assets', () => ({ getWorkspaceAssetUrl: () => '/assets/rag-panel-bundle.js' }));
beforeEach(() => { vi.resetModules(); load.mockReset(); document.body.innerHTML = '<div id="koto-knowledge-status"></div>'; });
describe('optional knowledge tools', () => {
  it('keeps a failed load visible and allows the explicit retry action to finish loading', async () => {
    let ready = false;
    const lookup = vi.spyOn(customElements, 'get').mockImplementation((name) => name === 'koto-rag-panel' && ready ? HTMLElement : undefined);
    load.mockRejectedValueOnce(new Error('offline')).mockImplementationOnce(async () => { ready = true; });
    try {
      const { loadKnowledgePanel } = await import('./rag-panel-loader');
      expect(load).not.toHaveBeenCalled();
      await expect(loadKnowledgePanel()).rejects.toThrow('offline');
      expect(document.getElementById('koto-knowledge-status')?.textContent).toContain('重试');
      expect(await loadKnowledgePanel()).toBeUndefined();
      expect(document.getElementById('koto-knowledge-status')?.hidden).toBe(true);
      expect(load).toHaveBeenCalledTimes(2);
    } finally { lookup.mockRestore(); }
  });
});
