import { beforeEach, describe, expect, it, vi } from 'vitest';
const api = vi.hoisted(() => ({ documentReviewRuntime: null as any }));
const load = vi.hoisted(() => vi.fn());
vi.mock('../editors/cdn-loaders', () => ({ _loadScript: load }));
vi.mock('../shared/feature-registry', () => ({ getFeatureRegistry: () => api, registerFeatures: vi.fn() }));
vi.mock('../shared/workspace-assets', () => ({ getWorkspaceAssetUrl: () => '/assets/document-review-bundle.js' }));

beforeEach(() => { vi.resetModules(); load.mockReset(); api.documentReviewRuntime = null; });
describe('optional document review loader', () => {
  it('loads once on demand and returns the published runtime for concurrent review actions', async () => {
    const runtime = { renderDocumentDiff: vi.fn() };
    load.mockImplementation(async () => { await Promise.resolve(); api.documentReviewRuntime = runtime; });
    const { loadDocumentReviewRuntime } = await import('./document-review-loader');
    expect(load).not.toHaveBeenCalled();
    const first = loadDocumentReviewRuntime();
    expect(loadDocumentReviewRuntime()).toBe(first);
    expect(await first).toBe(runtime);
    expect(await loadDocumentReviewRuntime()).toBe(runtime);
    expect(load).toHaveBeenCalledExactlyOnceWith('/assets/document-review-bundle.js', 60000);
  });
  it('allows retry after loading fails instead of caching a rejected promise', async () => {
    load.mockRejectedValueOnce(new Error('offline'));
    const { loadDocumentReviewRuntime } = await import('./document-review-loader');
    await expect(loadDocumentReviewRuntime()).rejects.toThrow('offline');
    load.mockImplementationOnce(async () => { api.documentReviewRuntime = { ready: true }; });
    expect(await loadDocumentReviewRuntime()).toEqual({ ready: true });
    expect(load).toHaveBeenCalledTimes(2);
  });
});
