import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
  createRenderSurfaceController,
  getRenderScaleSnapshot,
  prepareCanvas2d,
  syncCanvasBackingStore,
} from './render-surface';

function mockPaintedElement(element: HTMLElement, logicalWidth = 200, logicalHeight = 100): void {
  Object.defineProperties(element, {
    offsetWidth: { configurable: true, value: logicalWidth },
    offsetHeight: { configurable: true, value: logicalHeight },
  });
  vi.spyOn(element, 'getBoundingClientRect').mockReturnValue({
    left: 0,
    top: 0,
    right: logicalWidth * 1.25,
    bottom: logicalHeight * 1.25,
    width: logicalWidth * 1.25,
    height: logicalHeight * 1.25,
    x: 0,
    y: 0,
    toJSON: () => ({}),
  });
}

describe('render surface contract', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
    document.documentElement.dataset.kotoUiZoom = '1.25';
    Object.defineProperty(window, 'devicePixelRatio', { configurable: true, value: 2 });
    vi.restoreAllMocks();
  });

  it('combines CSS paint scale and DPR into a backing-store scale', () => {
    const element = document.createElement('div');
    document.body.appendChild(element);
    mockPaintedElement(element);

    expect(getRenderScaleSnapshot(element)).toEqual({
      uiZoom: 1.25,
      devicePixelRatio: 2,
      logicalSize: { width: 200, height: 100 },
      paintScale: { x: 1.25, y: 1.25 },
      backingScale: { x: 2.5, y: 2.5 },
    });
  });

  it('allocates enough canvas pixels without changing logical CSS dimensions', () => {
    const host = document.createElement('div');
    const canvas = document.createElement('canvas');
    host.appendChild(canvas);
    document.body.appendChild(host);
    mockPaintedElement(host);

    const result = syncCanvasBackingStore(canvas, 148, 84, host);
    expect(result.width).toBe(370);
    expect(result.height).toBe(210);
    expect(canvas.style.width).toBe('148px');
    expect(canvas.style.height).toBe('84px');
  });

  it('keeps 2D drawing coordinates logical', () => {
    const host = document.createElement('div');
    const canvas = document.createElement('canvas');
    host.appendChild(canvas);
    document.body.appendChild(host);
    mockPaintedElement(host);
    const setTransform = vi.fn();
    vi.spyOn(canvas, 'getContext').mockReturnValue({ setTransform } as unknown as CanvasRenderingContext2D);

    const prepared = prepareCanvas2d(canvas, 100, 50, host);
    expect(prepared).not.toBeNull();
    expect(setTransform).toHaveBeenCalledWith(2.5, 0, 0, 2.5, 0, 0);
  });

  it('coalesces layout and UI-scale notifications into one frame', () => {
    const callbacks: FrameRequestCallback[] = [];
    vi.spyOn(window, 'requestAnimationFrame').mockImplementation((callback) => {
      callbacks.push(callback);
      return callbacks.length;
    });
    vi.spyOn(window, 'cancelAnimationFrame').mockImplementation(() => undefined);
    const host = document.createElement('div');
    document.body.appendChild(host);
    mockPaintedElement(host);
    const listener = vi.fn();
    const controller = createRenderSurfaceController(host, listener);
    controller.request('layout');
    controller.request('ui-scale');

    expect(callbacks).toHaveLength(1);
    callbacks[0](0);
    expect(listener).toHaveBeenCalledTimes(1);
    expect([...listener.mock.calls[0][1]]).toEqual(['initial', 'layout', 'ui-scale']);
    controller.dispose();
  });
});
