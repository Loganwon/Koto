/**
 * Global error boundary — catches unhandled errors and rejections.
 * Prevents white-screen crashes in WebView2 by logging to console.
 */
export function installErrorBoundary(): void {
  window.addEventListener('error', (event) => {
    if (event.filename && event.filename.includes('/static/js/')) {
      console.error('[Koto] Unhandled error:', event.message, 'at', event.filename + ':' + event.lineno);
    }
  });

  window.addEventListener('unhandledrejection', (event) => {
    console.error('[Koto] Unhandled rejection:', event.reason);
    event.preventDefault(); // Prevent console pollution
  });

  // Track recurring errors to avoid spam
  let lastError = '';
  let lastErrorTime = 0;
  const ERROR_THROTTLE_MS = 5000;

  const originalError = console.error;
  console.error = function(...args: any[]) {
    const msg = String(args[0] || '');
    const now = Date.now();
    if (msg !== lastError || now - lastErrorTime > ERROR_THROTTLE_MS) {
      lastError = msg;
      lastErrorTime = now;
    }
    // Still call original for dev tools
    if (originalError !== console.error) {
      originalError.apply(console, args);
    }
  };
}
