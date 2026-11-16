import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { getFeatureRegistry } from '../shared/feature-registry';
import { pollExternalOpenRequests } from './external-open-bridge';

describe('external open bridge', () => {
  beforeEach(() => {
    delete (window as any).pywebview;
    const registry = getFeatureRegistry();
    delete registry.openBrowserFile;
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('opens every handed-off path through the canonical absolute-path loader', async () => {
    const openBrowserFile = vi.fn().mockResolvedValue(null);
    getFeatureRegistry().openBrowserFile = openBrowserFile;
    (window as any).pywebview = {
      api: {
        consume_external_open_requests: vi.fn().mockResolvedValue({
          success: true,
          paths: ['C:\\Docs\\report.docx', 'C:\\Docs\\book.xlsx'],
        }),
      },
    };

    const paths = await pollExternalOpenRequests();

    expect(paths).toEqual(['C:\\Docs\\report.docx', 'C:\\Docs\\book.xlsx']);
    expect(openBrowserFile).toHaveBeenNthCalledWith(1, paths[0], true);
    expect(openBrowserFile).toHaveBeenNthCalledWith(2, paths[1], true);
  });

  it('does not consume requests before the workspace loader is ready', async () => {
    const consume = vi.fn();
    (window as any).pywebview = { api: { consume_external_open_requests: consume } };

    expect(await pollExternalOpenRequests()).toEqual([]);
    expect(consume).not.toHaveBeenCalled();
  });

  it('rejects malformed paths and de-duplicates Windows paths', async () => {
    const openBrowserFile = vi.fn().mockResolvedValue(null);
    getFeatureRegistry().openBrowserFile = openBrowserFile;
    (window as any).pywebview = {
      api: {
        consume_external_open_requests: vi.fn().mockResolvedValue({
          success: true,
          paths: [
            'C:\\Docs\\Report.docx',
            'c:/docs/report.DOCX',
            'relative.docx',
            'C:\\Docs\\notes.txt',
            { path: 'C:\\Docs\\fake.pdf' },
            '\\\\server\\share\\paper.pdf',
          ],
        }),
      },
    };

    const paths = await pollExternalOpenRequests();

    expect(paths).toEqual([
      'C:\\Docs\\Report.docx',
      '\\\\server\\share\\paper.pdf',
    ]);
    expect(openBrowserFile).toHaveBeenCalledTimes(2);
  });

  it('continues opening later files when one loader call rejects', async () => {
    vi.spyOn(console, 'warn').mockImplementation(() => {});
    const openBrowserFile = vi.fn()
      .mockRejectedValueOnce(new Error('broken document'))
      .mockResolvedValueOnce(null);
    getFeatureRegistry().openBrowserFile = openBrowserFile;
    (window as any).pywebview = {
      api: {
        consume_external_open_requests: vi.fn().mockResolvedValue({
          success: true,
          paths: ['C:\\Docs\\broken.docx', 'C:\\Docs\\book.xlsx'],
        }),
      },
    };

    const paths = await pollExternalOpenRequests();

    expect(paths).toHaveLength(2);
    expect(openBrowserFile).toHaveBeenCalledTimes(2);
    expect(openBrowserFile).toHaveBeenLastCalledWith('C:\\Docs\\book.xlsx', true);
  });

  it('coalesces overlapping polls into one desktop API call', async () => {
    let resolveConsume!: (value: { success: boolean; paths: string[] }) => void;
    const consume = vi.fn(() => new Promise<{ success: boolean; paths: string[] }>((resolve) => {
      resolveConsume = resolve;
    }));
    getFeatureRegistry().openBrowserFile = vi.fn().mockResolvedValue(null);
    (window as any).pywebview = { api: { consume_external_open_requests: consume } };

    const first = pollExternalOpenRequests();
    const second = pollExternalOpenRequests();
    resolveConsume({ success: true, paths: [] });

    expect(await second).toEqual([]);
    expect(await first).toEqual([]);
    expect(consume).toHaveBeenCalledOnce();
  });

  it('does not open paths returned with a failed desktop response', async () => {
    vi.spyOn(console, 'warn').mockImplementation(() => {});
    const openBrowserFile = vi.fn();
    getFeatureRegistry().openBrowserFile = openBrowserFile;
    (window as any).pywebview = {
      api: {
        consume_external_open_requests: vi.fn().mockResolvedValue({
          success: false,
          error: 'read failed',
          paths: ['C:\\Docs\\report.docx'],
        }),
      },
    };

    expect(await pollExternalOpenRequests()).toEqual([]);
    expect(openBrowserFile).not.toHaveBeenCalled();
  });
});
