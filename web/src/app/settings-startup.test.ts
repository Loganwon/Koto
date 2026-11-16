import { getFeatureRegistry } from '../shared/feature-registry';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { loadSettings, openDefaultAppsSettings } from './settings';

describe('settings startup hydration', () => {
  afterEach(() => {
    delete (window as any).pywebview;
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('coalesces concurrent settings requests and applies the response once', async () => {
    const values = new Map<string, string>();
    vi.stubGlobal('localStorage', {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, String(value)),
      removeItem: (key: string) => values.delete(key),
    });
    let resolveFetch!: (response: Response) => void;
    const fetchMock = vi.fn(() => new Promise<Response>((resolve) => {
      resolveFetch = resolve;
    }));
    vi.stubGlobal('fetch', fetchMock);
    getFeatureRegistry().applyTheme = vi.fn();
    getFeatureRegistry().updateThemeSelector = vi.fn();
    getFeatureRegistry().setUIZoom = vi.fn();

    const first = loadSettings();
    const second = loadSettings();

    expect(first).toBe(second);
    expect(fetchMock).toHaveBeenCalledOnce();
    resolveFetch({
      ok: true,
      json: async () => ({ appearance: { theme: 'forest', ui_zoom: '1.1' } }),
    } as Response);
    await Promise.all([first, second]);

    expect(getFeatureRegistry().applyTheme).toHaveBeenCalledOnce();
    expect(getFeatureRegistry().setUIZoom).toHaveBeenCalledWith('1.1', true);
    expect(localStorage.getItem('koto.theme')).toBe('forest');
  });

  it('opens the registered Koto page in Windows default-app settings', async () => {
    const openDefaultApps = vi.fn().mockResolvedValue({ success: true });
    const notify = vi.fn();
    (window as any).pywebview = {
      api: { open_default_apps_settings: openDefaultApps },
    };
    getFeatureRegistry().showNotification = notify;

    await openDefaultAppsSettings();

    expect(openDefaultApps).toHaveBeenCalledOnce();
    expect(notify).toHaveBeenCalledWith(
      '请在 Windows 中为需要的文件类型选择 Koto',
      'info',
      5000,
    );
  });

  it('explains that default-app settings require the desktop build', async () => {
    const notify = vi.fn();
    getFeatureRegistry().showNotification = notify;

    await openDefaultAppsSettings();

    expect(notify).toHaveBeenCalledWith(
      '此功能仅在 Koto Windows 桌面版中可用',
      'info',
      3000,
    );
  });
});
