/**
 * Deferred initializer ? batch non-critical startup work behind
 * requestIdleCallback so the critical render path is not blocked.
 *
 * Usage:
 *   import { deferInit, batchInit } from '../shared/init-deferred';
 *   deferInit(() => appCtx.chat.checkSetupStatus());
 *   batchInit([
 *     () => appCtx.chat.checkSetupStatus(),
 *     () => appCtx.session.loadSessions(),
 *   ]);
 */

type InitFn = () => void | Promise<void>;

const queue: InitFn[] = [];
let scheduled = false;

function flush(): void {
  scheduled = false;
  while (queue.length) {
    const fn = queue.shift()!;
    try {
      const result = fn();
      if (result && typeof result.then === 'function') {
        void result.catch((error) => console.warn('[Koto] deferred init failed:', error));
      }
    } catch (error) {
      console.warn('[Koto] deferred init failed:', error);
    }
  }
}

/** Schedule a single init function after critical render. */
export function deferInit(fn: InitFn): void {
  queue.push(fn);
  if (!scheduled) {
    scheduled = true;
    if (typeof requestIdleCallback !== 'undefined') {
      requestIdleCallback(flush, { timeout: 2000 });
    } else {
      setTimeout(flush, 0);
    }
  }
}

/** Batch multiple init functions; all run in the same deferred tick. */
export function batchInit(fns: InitFn[]): void {
  for (const fn of fns) queue.push(fn);
  if (!scheduled) {
    scheduled = true;
    if (typeof requestIdleCallback !== 'undefined') {
      requestIdleCallback(flush, { timeout: 2000 });
    } else {
      setTimeout(flush, 0);
    }
  }
}

/**
 * Schedule non-critical work only after the browser has painted the startup
 * shell. Two frames keep the setTimeout fallback from competing with first
 * paint on runtimes that do not implement requestIdleCallback (pywebview).
 */
export function deferAfterPaint(fn: InitFn): void {
  requestAnimationFrame(() => requestAnimationFrame(() => deferInit(fn)));
}
