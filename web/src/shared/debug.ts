// Lightweight debug logger — wraps console with a togglable flag.
// Toggle the __KOTO_DEBUG__ browser flag in dev tools to enable verbose logging.

const KOTO_DEBUG =
  typeof window !== 'undefined' && (window as any).__KOTO_DEBUG__ === true;

export function debugLog(tag: string, ...args: any[]): void {
  if (KOTO_DEBUG) {
    // eslint-disable-next-line no-console -- this module is the debug logging boundary
    console.log(`[${tag}]`, ...args);
  }
}

export function debugWarn(tag: string, ...args: any[]): void {
  if (KOTO_DEBUG) {
    console.warn(`[${tag}]`, ...args);
  }
}
