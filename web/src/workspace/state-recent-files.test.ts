import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

describe('recent file availability filtering', () => {
  let storage: Map<string, string>;

  beforeEach(() => {
    storage = new Map();
    vi.stubGlobal('localStorage', {
      clear: () => storage.clear(),
      getItem: (key: string) => storage.get(key) ?? null,
      removeItem: (key: string) => storage.delete(key),
      setItem: (key: string, value: string) => storage.set(key, String(value)),
    });
    document.body.innerHTML = '<div id="wa-recent-list"></div>';
    localStorage.clear();
  });

  afterEach(() => {
    localStorage.clear();
    vi.unstubAllGlobals();
  });

  it('removes missing local entries before rendering the recent list', async () => {
    const { _WA_RECENT_KEY, loadRecentFiles } = await import('./state');
    localStorage.setItem(_WA_RECENT_KEY, JSON.stringify([
      { path: 'available.txt', name: 'available.txt', ts: 2 },
      { path: 'missing.txt', name: 'missing.txt', ts: 1 },
    ]));
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith('/api/files/recent')) {
        return { ok: true, status: 200, json: async () => ({ files: [] }) } as Response;
      }
      if (url === '/api/v1/workspace/recent_files/status') {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            files: [
              { path: 'available.txt', exists: true },
              { path: 'missing.txt', exists: false },
            ],
          }),
        } as Response;
      }
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);

    await loadRecentFiles();

    const list = document.getElementById('wa-recent-list');
    expect(list?.textContent).toContain('available.txt');
    expect(list?.textContent).not.toContain('missing.txt');
    expect(JSON.parse(localStorage.getItem(_WA_RECENT_KEY) || '[]')).toEqual([
      { path: 'available.txt', name: 'available.txt', ts: 2 },
    ]);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
