import { beforeEach, describe, expect, it } from 'vitest';

import {
  getFrontendPerformanceSnapshot,
  recordFileOpenPerformance,
} from './performance-monitor';

describe('frontend performance monitor', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
    document.documentElement.style.setProperty('--koto-ui-zoom', '1.2');
  });

  it('reports canvas backing-store pressure in the unified snapshot', () => {
    const canvas = document.createElement('canvas');
    canvas.width = 2400;
    canvas.height = 1200;
    document.body.appendChild(canvas);

    const snapshot = getFrontendPerformanceSnapshot() as any;

    expect(snapshot.canvases).toMatchObject({
      count: 1,
      backing_pixels: 2_880_000,
      max_width: 2400,
      max_height: 1200,
    });
    expect(snapshot.ui_zoom).toBe('1.2');
  });

  it('records a bounded, path-free file-open timing sample', () => {
    const sample = recordFileOpenPerformance({
      requestId: 'request_12345678',
      startedAt: performance.now() - 25,
      source: 'workspace',
      extension: 'XLSX',
      sizeBytes: 4096,
      outcome: 'success',
    });

    expect(sample).toMatchObject({
      request_id: 'request_12345678',
      source: 'workspace',
      extension: 'xlsx',
      size_bytes: 4096,
      outcome: 'success',
    });
    expect(sample).not.toHaveProperty('path');
    expect(Number(sample.duration_ms)).toBeGreaterThanOrEqual(0);
  });
});
