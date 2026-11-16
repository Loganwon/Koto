import { installFrontendObserver } from '../mcp/frontend-observer';
import { getFeatureRegistry } from '../shared/feature-registry';
import { drainStartupErrors } from '../shared/startup-monitor';
import { installFrontendPerformanceMonitor } from '../mcp/performance-monitor';

installFrontendObserver();

const observer = getFeatureRegistry().frontendObserver;
const startupErrors = drainStartupErrors();
if (observer && typeof observer.record === 'function') {
  installFrontendPerformanceMonitor(observer.record);
  startupErrors.forEach((entry: any) => {
    observer.record({
      type: 'startup_error',
      level: 'error',
      message: String(entry?.message || 'Unknown startup error'),
      details: entry && typeof entry === 'object' ? entry : { value: String(entry || '') },
    });
  });
} else {
  installFrontendPerformanceMonitor();
}
