import { afterEach, describe, expect, it, vi } from 'vitest';

import { reportFrontendReadyAfterPaint, reportWorkspaceReady } from './startup-monitor';

describe('startup monitor frontend readiness', () => {
  afterEach(() => {
    delete (window as any).pywebview;
    delete document.documentElement.dataset.kotoFrontendReady;
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('reports readiness only after two animation frames', async () => {
    const callbacks: FrameRequestCallback[] = [];
    vi.spyOn(window, 'requestAnimationFrame').mockImplementation((callback) => {
      callbacks.push(callback);
      return callbacks.length;
    });
    const report = vi.fn().mockResolvedValue({ success: true });
    (window as any).pywebview = { api: { report_frontend_ready: report } };

    const ready = reportFrontendReadyAfterPaint();
    expect(report).not.toHaveBeenCalled();
    callbacks.shift()?.(16);
    expect(report).not.toHaveBeenCalled();
    callbacks.shift()?.(32);

    await expect(ready).resolves.toBe(true);
    expect(report).toHaveBeenCalledWith(expect.objectContaining({
      document_ready_state: document.readyState,
    }));
    expect(document.documentElement.dataset.kotoFrontendReady).toBe('true');
  });

  it('reports deferred workspace readiness with bundle duration', async () => {
    const reportFrontend = vi.fn().mockResolvedValue({ success: true });
    const reportWorkspace = vi.fn().mockResolvedValue({ success: true });
    (window as any).pywebview = { api: {
      report_frontend_ready: reportFrontend,
      report_workspace_ready: reportWorkspace,
    } };

    await expect(reportWorkspaceReady(123.7)).resolves.toBe(true);
    expect(reportWorkspace).toHaveBeenCalledWith({ bundle_load_ms: 124 });
  });

  it('keeps waiting when the desktop bridge arrives after 1.5 seconds', async () => {
    vi.useFakeTimers();
    vi.spyOn(window, 'requestAnimationFrame').mockImplementation((callback) => {
      callback(0);
      return 1;
    });
    const report = vi.fn().mockResolvedValue({ success: true });

    const ready = reportFrontendReadyAfterPaint();
    await vi.advanceTimersByTimeAsync(2000);
    (window as any).pywebview = { api: { report_frontend_ready: report } };
    window.dispatchEvent(new Event('pywebviewready'));

    await expect(ready).resolves.toBe(true);
    expect(report).toHaveBeenCalledOnce();
  });
});
