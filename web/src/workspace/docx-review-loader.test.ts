import { afterEach, describe, expect, it, vi } from 'vitest';

afterEach(() => {
  delete (window as any).KotoDocxReviewEngineModule;
});

describe('DOCX review engine loader', () => {
  it('installs an already loaded engine without adding another script', async () => {
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      value: {
        getItem: vi.fn(() => null),
        setItem: vi.fn(),
        removeItem: vi.fn(),
      },
    });
    const { loadDocxReviewEngine } = await import('./docx-review-loader');
    const engine = {
      createReviewState: vi.fn(() => ({
        activeReviewTab: () => null,
      })),
      createDocxReviewLayout: vi.fn(() => ({})),
    };
    (window as any).KotoDocxReviewEngineModule = engine;

    await expect(loadDocxReviewEngine()).resolves.toBe(engine);
    expect(engine.createReviewState).toHaveBeenCalledTimes(1);
    expect(document.querySelector('script[src*="docx-review-engine-bundle"]')).toBeNull();
  });
});
