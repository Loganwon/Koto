import { installFrontendObserver } from '../mcp/frontend-observer';

installFrontendObserver();

const observer = (window as any).KotoFrontendObserver;
const startupErrors = Array.isArray((window as any).__kotoStartupErrors)
  ? (window as any).__kotoStartupErrors.splice(0)
  : [];
if (observer && typeof observer.record === 'function') {
  startupErrors.forEach((entry: any) => {
    observer.record({
      type: 'startup_error',
      level: 'error',
      message: String(entry?.message || 'Unknown startup error'),
      details: entry && typeof entry === 'object' ? entry : { value: String(entry || '') },
    });
  });
}
