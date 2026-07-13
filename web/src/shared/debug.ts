// Lightweight debug logger — wraps console with a togglable flag.
// Set window.__KOTO_DEBUG__ = true in dev tools to enable verbose logging.

const KOTO_DEBUG = (window as any).__KOTO_DEBUG__ === true;

export function debugLog(tag: string, ...args: any[]): void {
  if (KOTO_DEBUG) {
    console.log(`[${tag}]`, ...args);
  }
}

export function debugWarn(tag: string, ...args: any[]): void {
  if (KOTO_DEBUG) {
    console.warn(`[${tag}]`, ...args);
  }
}
