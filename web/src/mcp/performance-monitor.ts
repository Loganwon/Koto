import { getFeatureRegistry, registerFeatures } from '../shared/feature-registry';

type EventRecorder = (entry: Record<string, unknown>) => void;

export type FileOpenPerformanceMetric = {
  requestId: string;
  startedAt: number;
  outcome: 'success' | 'cancelled' | 'error';
  source: 'workspace' | 'external' | 'upload';
  extension?: string;
  sizeBytes?: number;
  finishedAt?: number;
};

type TimedSample = {
  name: string;
  durationMs: number;
  startTime: number;
  recordedAt: number;
};

const MAX_SAMPLES = 60;
const LONG_TASK_THRESHOLD_MS = 50;
const longTasks: TimedSample[] = [];
const slowEvents: TimedSample[] = [];
const fileOpens: Array<Record<string, unknown>> = [];
let installed = false;
let reportTimer: number | null = null;

function pushBounded<T>(target: T[], value: T): void {
  target.push(value);
  if (target.length > MAX_SAMPLES) target.splice(0, target.length - MAX_SAMPLES);
}

function rounded(value: number): number {
  return Math.round(value * 10) / 10;
}

function summarizeSamples(samples: TimedSample[]): Record<string, unknown> {
  const durations = samples.map((sample) => sample.durationMs);
  return {
    count: samples.length,
    total_ms: rounded(durations.reduce((sum, value) => sum + value, 0)),
    max_ms: rounded(durations.length ? Math.max(...durations) : 0),
    recent: samples.slice(-10),
  };
}

function canvasSnapshot(): Record<string, unknown> {
  const canvases = Array.from(document.querySelectorAll('canvas'));
  const pixels = canvases.reduce(
    (sum, canvas) => sum + Math.max(0, canvas.width) * Math.max(0, canvas.height),
    0,
  );
  return {
    count: canvases.length,
    backing_pixels: pixels,
    estimated_rgba_mb: rounded((pixels * 4) / 1048576),
    max_width: canvases.reduce((max, canvas) => Math.max(max, canvas.width), 0),
    max_height: canvases.reduce((max, canvas) => Math.max(max, canvas.height), 0),
  };
}

function resourceSnapshot(): Record<string, unknown> {
  const resources = performance.getEntriesByType?.('resource') as PerformanceResourceTiming[] || [];
  const bundles = resources.filter((entry) => /\/js\/build\/.+-bundle\.js(?:\?|$)/.test(entry.name));
  return {
    bundle_count: bundles.length,
    transfer_kb: rounded(bundles.reduce((sum, entry) => sum + (entry.transferSize || 0), 0) / 1024),
    decoded_kb: rounded(bundles.reduce((sum, entry) => sum + (entry.decodedBodySize || 0), 0) / 1024),
    max_duration_ms: rounded(bundles.reduce((max, entry) => Math.max(max, entry.duration || 0), 0)),
  };
}

function navigationSnapshot(): Record<string, unknown> {
  const navigation = performance.getEntriesByType?.('navigation')?.[0] as PerformanceNavigationTiming | undefined;
  if (!navigation) return {};
  return {
    dom_interactive_ms: rounded(navigation.domInteractive),
    dom_content_loaded_ms: rounded(navigation.domContentLoadedEventEnd),
    load_ms: rounded(navigation.loadEventEnd),
    response_ms: rounded(navigation.responseEnd),
  };
}

function memorySnapshot(): Record<string, unknown> {
  const memory = (performance as Performance & {
    memory?: { usedJSHeapSize: number; totalJSHeapSize: number; jsHeapSizeLimit: number };
  }).memory;
  if (!memory) return { supported: false };
  return {
    supported: true,
    used_heap_mb: rounded(memory.usedJSHeapSize / 1048576),
    total_heap_mb: rounded(memory.totalJSHeapSize / 1048576),
    heap_limit_mb: rounded(memory.jsHeapSizeLimit / 1048576),
  };
}

export function getFrontendPerformanceSnapshot(): Record<string, unknown> {
  return {
    captured_at: Date.now(),
    route: `${location.pathname}${location.search}${location.hash}`,
    long_tasks: summarizeSamples(longTasks),
    slow_events: summarizeSamples(slowEvents),
    file_opens: fileOpens.slice(-20),
    canvases: canvasSnapshot(),
    resources: resourceSnapshot(),
    navigation: navigationSnapshot(),
    memory: memorySnapshot(),
    ui_zoom: getComputedStyle(document.documentElement).getPropertyValue('--koto-ui-zoom').trim() || '1',
  };
}

export function recordFileOpenPerformance(metric: FileOpenPerformanceMetric): Record<string, unknown> {
  const finishedAt = metric.finishedAt ?? performance.now();
  const sample = {
    request_id: metric.requestId,
    source: metric.source,
    extension: String(metric.extension || '').toLowerCase().slice(0, 16),
    size_bytes: Math.max(0, Number(metric.sizeBytes || 0)),
    outcome: metric.outcome,
    duration_ms: rounded(Math.max(0, finishedAt - metric.startedAt)),
    recorded_at: Date.now(),
  };
  pushBounded(fileOpens, sample);
  const observer = getFeatureRegistry().frontendObserver;
  if (observer && typeof observer.record === 'function') {
    observer.record({
      type: 'file_open_performance',
      level: metric.outcome === 'error' ? 'warning' : 'info',
      message: `${metric.source} file open ${metric.outcome}`,
      details: sample,
    });
  }
  return sample;
}

function installEntryObserver(entryType: 'longtask' | 'event', target: TimedSample[]): void {
  if (typeof PerformanceObserver === 'undefined') return;
  try {
    const observer = new PerformanceObserver((list) => {
      list.getEntries().forEach((entry) => {
        if (entry.duration < LONG_TASK_THRESHOLD_MS) return;
        pushBounded(target, {
          name: String(entry.name || entryType).slice(0, 120),
          durationMs: rounded(entry.duration),
          startTime: rounded(entry.startTime),
          recordedAt: Date.now(),
        });
      });
    });
    observer.observe(entryType === 'event'
      ? { type: entryType, buffered: true, durationThreshold: LONG_TASK_THRESHOLD_MS } as PerformanceObserverInit
      : { type: entryType, buffered: true } as PerformanceObserverInit);
  } catch (_) {
    // Older WebViews do not expose these entry types; snapshots remain available.
  }
}

export function installFrontendPerformanceMonitor(record?: EventRecorder): void {
  if (installed || typeof window === 'undefined') return;
  installed = true;
  installEntryObserver('longtask', longTasks);
  installEntryObserver('event', slowEvents);
  document.documentElement.setAttribute('data-koto-performance-monitor', 'ready');
  registerFeatures({
    frontendPerformance: {
      snapshot: getFrontendPerformanceSnapshot,
      recordFileOpen: recordFileOpenPerformance,
    },
  });
  const emit = () => {
    record?.({
      type: 'frontend_performance',
      level: 'info',
      message: 'Periodic frontend performance snapshot',
      details: getFrontendPerformanceSnapshot(),
    });
  };
  reportTimer = window.setInterval(emit, 60000);
  void reportTimer;
}
