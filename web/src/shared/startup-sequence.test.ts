import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { renderStartupShell, startPostPaintHydration } from './startup-sequence';

describe('startup sequence', () => {
  beforeEach(() => {
    const values = new Map<string, string>();
    vi.stubGlobal('localStorage', {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, String(value)),
      removeItem: (key: string) => values.delete(key),
      clear: () => values.clear(),
    });
    document.documentElement.removeAttribute('data-theme');
    delete document.documentElement.dataset.kotoTheme;
    delete document.documentElement.dataset.kotoUiZoom;
  });

  afterEach(() => {
    delete (window as any).pywebview;
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('renders cached appearance and welcome content without loading settings', () => {
    localStorage.setItem('koto.theme', 'ocean');
    localStorage.setItem('koto.uiZoom', '1.2');
    const host = {
      applyTheme: vi.fn(),
      updateThemeSelector: vi.fn(),
      setUIZoom: vi.fn(),
      renderWelcomeScreen: vi.fn(),
      loadSettings: vi.fn(),
    } as unknown as Window;

    renderStartupShell(host);

    expect((host as any).applyTheme).toHaveBeenCalledWith('ocean');
    expect((host as any).updateThemeSelector).toHaveBeenCalledWith('ocean');
    expect((host as any).setUIZoom).toHaveBeenCalledWith('1.2', true, false);
    expect((host as any).renderWelcomeScreen).toHaveBeenCalledOnce();
    expect((host as any).loadSettings).not.toHaveBeenCalled();
  });

  it('loads server settings only after two frames and an idle turn', async () => {
    const frames: FrameRequestCallback[] = [];
    let idleCallback: IdleRequestCallback | undefined;
    vi.spyOn(window, 'requestAnimationFrame').mockImplementation((callback) => {
      frames.push(callback);
      return frames.length;
    });
    vi.stubGlobal('requestIdleCallback', (callback: IdleRequestCallback) => {
      idleCallback = callback;
      return 1;
    });
    const report = vi.fn().mockResolvedValue({ success: true });
    const loadSettings = vi.fn().mockResolvedValue(undefined);
    (window as any).pywebview = { api: { report_frontend_ready: report } };
    const host = { loadSettings } as unknown as Window;

    startPostPaintHydration(host);
    expect(loadSettings).not.toHaveBeenCalled();

    while (frames.length) frames.shift()?.(16);
    expect(loadSettings).not.toHaveBeenCalled();
    expect(idleCallback).toBeTypeOf('function');

    idleCallback?.({ didTimeout: false, timeRemaining: () => 10 });
    await vi.waitFor(() => expect(report).toHaveBeenCalledOnce());
    expect(loadSettings).toHaveBeenCalledOnce();
  });
});
