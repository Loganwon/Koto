import { afterEach, describe, expect, it, vi } from 'vitest';
import { _loadScript } from './cdn-loaders';

afterEach(() => {
  vi.useRealTimers();
  document.head.innerHTML = '';
});

describe('_loadScript', () => {
  it('removes a failed script so the same dependency can be retried', async () => {
    const first = _loadScript('/static/vendor/example.js');
    const failedScript = document.head.querySelector('script[data-koto-loader-src]') as HTMLScriptElement;
    expect(failedScript).toBeTruthy();

    failedScript.dispatchEvent(new Event('error'));
    await expect(first).rejects.toThrow('CDN 加载失败');
    expect(document.head.querySelector('script[data-koto-loader-src]')).toBeNull();

    const retry = _loadScript('/static/vendor/example.js');
    const retryScript = document.head.querySelector('script[data-koto-loader-src]') as HTMLScriptElement;
    expect(retryScript).toBeTruthy();
    expect(retryScript).not.toBe(failedScript);

    retryScript.dispatchEvent(new Event('load'));
    await expect(retry).resolves.toBeUndefined();
    expect(retryScript.dataset.kotoLoaderState).toBe('loaded');
  });

  it('removes a timed-out script before releasing the retry lock', async () => {
    vi.useFakeTimers();
    const loading = _loadScript('/static/vendor/slow-example.js', 50);
    const rejection = expect(loading).rejects.toThrow('CDN 加载超时');

    await vi.advanceTimersByTimeAsync(50);
    await rejection;
    expect(document.head.querySelector('script[data-koto-loader-src]')).toBeNull();
  });
});
