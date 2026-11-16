/**
 * Unified high-density rendering contract.
 *
 * Application layout is authored in logical CSS pixels. CSS zoom and the
 * operating-system DPR determine how many painted device pixels a raster
 * surface needs. Editors must use this module instead of reading
 * `devicePixelRatio`, creating their own zoom listeners, or stretching a
 * low-resolution canvas.
 */

import {
  getElementLogicalSize,
  getElementPaintScale,
  readUiZoom,
  UI_ZOOM_EVENT,
  type PaintScale,
  type UiSize,
} from './ui-scale';

export type RenderSurfaceReason = 'initial' | 'layout' | 'ui-scale' | 'manual';

export interface RenderScaleSnapshot {
  uiZoom: number;
  devicePixelRatio: number;
  logicalSize: UiSize;
  paintScale: PaintScale;
  backingScale: PaintScale;
}

export interface CanvasBackingStore {
  width: number;
  height: number;
  scaleX: number;
  scaleY: number;
  changed: boolean;
  snapshot: RenderScaleSnapshot;
}

export type RenderSurfaceCallback = (
  snapshot: RenderScaleSnapshot,
  reasons: ReadonlySet<RenderSurfaceReason>,
) => void;

function positiveNumber(value: unknown, fallback: number = 1): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

export function getRenderScaleSnapshot(element: Element): RenderScaleSnapshot {
  const paintScale = getElementPaintScale(element);
  const devicePixelRatio = positiveNumber(window.devicePixelRatio);
  return {
    uiZoom: readUiZoom(),
    devicePixelRatio,
    logicalSize: getElementLogicalSize(element),
    paintScale,
    backingScale: {
      x: paintScale.x * devicePixelRatio,
      y: paintScale.y * devicePixelRatio,
    },
  };
}

/**
 * Size a canvas for its painted device-pixel footprint while preserving a
 * logical CSS coordinate system. The reference element may be a stable parent
 * when the canvas has not been attached or sized yet.
 */
export function syncCanvasBackingStore(
  canvas: HTMLCanvasElement,
  logicalWidth: number,
  logicalHeight: number,
  referenceElement: Element = canvas,
): CanvasBackingStore {
  const width = Math.max(1, positiveNumber(logicalWidth));
  const height = Math.max(1, positiveNumber(logicalHeight));
  const snapshot = getRenderScaleSnapshot(referenceElement);
  const backingWidth = Math.max(1, Math.round(width * snapshot.backingScale.x));
  const backingHeight = Math.max(1, Math.round(height * snapshot.backingScale.y));
  const changed = canvas.width !== backingWidth || canvas.height !== backingHeight;

  if (canvas.width !== backingWidth) canvas.width = backingWidth;
  if (canvas.height !== backingHeight) canvas.height = backingHeight;
  canvas.style.width = `${width}px`;
  canvas.style.height = `${height}px`;

  return {
    width: backingWidth,
    height: backingHeight,
    scaleX: backingWidth / width,
    scaleY: backingHeight / height,
    changed,
    snapshot,
  };
}

/** Prepare a 2D canvas whose drawing API remains in logical CSS pixels. */
export function prepareCanvas2d(
  canvas: HTMLCanvasElement,
  logicalWidth: number,
  logicalHeight: number,
  referenceElement: Element = canvas,
): { context: CanvasRenderingContext2D; backingStore: CanvasBackingStore } | null {
  const backingStore = syncCanvasBackingStore(canvas, logicalWidth, logicalHeight, referenceElement);
  const context = canvas.getContext('2d');
  if (!context) return null;
  context.setTransform(backingStore.scaleX, 0, 0, backingStore.scaleY, 0, 0);
  return { context, backingStore };
}

/** Keep a third-party renderer outside application CSS zoom stretching. */
export function syncNativeRenderSurface(element: HTMLElement): RenderScaleSnapshot {
  const snapshot = getRenderScaleSnapshot(element.parentElement || element);
  element.style.setProperty('zoom', String(1 / snapshot.uiZoom), 'important');
  element.style.setProperty('width', '100%', 'important');
  element.style.setProperty('height', '100%', 'important');
  return snapshot;
}

/**
 * One lifecycle owner for layout, UI zoom and DPR changes. UI zoom and DPR are
 * already normalized into UI_ZOOM_EVENT by theme.ts; ResizeObserver supplies
 * element-level layout changes. All notifications are coalesced to one frame.
 */
export class RenderSurfaceController {
  private readonly target: Element;
  private readonly callback: RenderSurfaceCallback;
  private resizeObserver: ResizeObserver | null = null;
  private frame = 0;
  private started = false;
  private reasons = new Set<RenderSurfaceReason>();

  constructor(target: Element, callback: RenderSurfaceCallback) {
    this.target = target;
    this.callback = callback;
  }

  start(): this {
    if (this.started) return this;
    this.started = true;
    window.addEventListener(UI_ZOOM_EVENT, this.onUiScale);
    if (typeof ResizeObserver !== 'undefined') {
      this.resizeObserver = new ResizeObserver(this.onLayout);
      this.resizeObserver.observe(this.target);
    }
    this.request('initial');
    return this;
  }

  request(reason: RenderSurfaceReason = 'manual'): void {
    if (!this.started) return;
    this.reasons.add(reason);
    if (this.frame) return;
    this.frame = window.requestAnimationFrame(this.flush);
  }

  dispose(): void {
    if (!this.started) return;
    this.started = false;
    window.removeEventListener(UI_ZOOM_EVENT, this.onUiScale);
    this.resizeObserver?.disconnect();
    this.resizeObserver = null;
    if (this.frame) window.cancelAnimationFrame(this.frame);
    this.frame = 0;
    this.reasons.clear();
  }

  private readonly onUiScale = (): void => this.request('ui-scale');
  private readonly onLayout = (): void => this.request('layout');
  private readonly flush = (): void => {
    this.frame = 0;
    if (!this.started || !this.target.isConnected) return;
    const reasons = new Set(this.reasons);
    this.reasons.clear();
    this.callback(getRenderScaleSnapshot(this.target), reasons);
  };
}

export function createRenderSurfaceController(
  target: Element,
  callback: RenderSurfaceCallback,
): RenderSurfaceController {
  return new RenderSurfaceController(target, callback).start();
}

export const renderSurfaceApi = Object.freeze({
  getSnapshot: getRenderScaleSnapshot,
  syncCanvasBackingStore,
  prepareCanvas2d,
  syncNativeRenderSurface,
  createController: createRenderSurfaceController,
});

if (typeof window !== 'undefined') {
  (window as any).KotoRenderSurface = renderSurfaceApi;
}
