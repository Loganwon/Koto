/**
 * Memory cleanup utilities.
 * Call disposeAll() before page unload to clear timers, abort streams, and release references.
 */
export interface Disposable {
  dispose(): void;
}

const _disposables: Disposable[] = [];

export function registerDisposable(d: Disposable): void {
  _disposables.push(d);
}

export function createIntervalDisposable(timer: ReturnType<typeof setInterval> | null): Disposable {
  return {
    dispose() {
      if (timer !== null) {
        clearInterval(timer);
      }
    },
  };
}

export function createAbortDisposable(ctrl: AbortController | null): Disposable {
  return {
    dispose() {
      if (ctrl !== null) {
        ctrl.abort();
      }
    },
  };
}


/**
 * Create a Disposable that removes an event listener.
 *
 * Usage:
 *   const d = createEventListenerDisposable(window, 'resize', handler);
 *   registerDisposable(d);
 *   // Later: d.dispose(); // removes the listener
 */
export function createEventListenerDisposable(
  target: EventTarget,
  type: string,
  listener: EventListenerOrEventListenerObject,
  options?: AddEventListenerOptions | boolean,
): Disposable {
  let disposed = false;
  return {
    dispose() {
      if (!disposed) {
        disposed = true;
        target.removeEventListener(type, listener, options);
      }
    },
  };
}

/**
 * Create a Disposable that disconnects a MutationObserver or ResizeObserver.
 */
export function createObserverDisposable(
  observer: MutationObserver | ResizeObserver | IntersectionObserver | null,
): Disposable {
  return {
    dispose() {
      if (observer !== null) {
        observer.disconnect();
      }
    },
  };
}

/**
 * Create a Disposable that clears a timeout.
 */
export function createTimeoutDisposable(timer: ReturnType<typeof setTimeout> | null): Disposable {
  return {
    dispose() {
      if (timer !== null) {
        clearTimeout(timer);
      }
    },
  };
}

export function disposeAll(): void {
  while (_disposables.length > 0) {
    try {
      _disposables.pop()!.dispose();
    } catch (_e) { /* cleanup must not throw */ }
  }
}

// Auto-cleanup on page unload
if (typeof window !== 'undefined') {
  window.addEventListener('beforeunload', disposeAll);
}