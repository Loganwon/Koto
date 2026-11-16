/**
 * The single coordinate contract for Koto UI scaling.
 *
 * CSS `zoom` keeps layout measurements (`offsetWidth`, authored `left/top`) in
 * logical CSS pixels while pointer events and DOMRect values use painted
 * viewport pixels.  Code that crosses that boundary must go through this
 * module instead of reading `body.style.zoom` or dividing coordinates ad hoc.
 */

export const UI_ZOOM_EVENT = 'koto-ui-zoom-change';
export const UI_SCALE_BOUNDARY_CLASS = 'koto-ui-scale-boundary';
export const UI_PORTAL_ROOT_ID = 'koto-ui-portal-root';

export interface PaintScale {
  x: number;
  y: number;
}

export interface UiPoint {
  x: number;
  y: number;
}

export interface UiSize {
  width: number;
  height: number;
}

export interface UiZoomChangeDetail {
  zoom: number;
  layoutWidth: number;
  layoutHeight: number;
  devicePixelRatio: number;
}

export const LOGICAL_VIEWPORT_BREAKPOINTS = Object.freeze([
  1200,
  900,
  860,
  768,
  640,
  520,
  480,
] as const);

export interface VisualViewportBounds {
  left: number;
  top: number;
  right: number;
  bottom: number;
  width: number;
  height: number;
}

function positiveNumber(value: unknown, fallback: number = 1): number {
  const parsed = typeof value === 'number' ? value : parseFloat(String(value || ''));
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

export function normalizeUiZoom(value: unknown): number {
  return Math.max(0.7, Math.min(1.5, positiveNumber(value)));
}

export function readUiZoom(): number {
  const datasetZoom = document.documentElement?.dataset?.kotoUiZoom;
  if (datasetZoom) return normalizeUiZoom(datasetZoom);
  const bodyZoom = document.body ? window.getComputedStyle(document.body).zoom : '';
  return normalizeUiZoom(bodyZoom);
}

/**
 * Dynamic overlays live beside the application shell, never directly under a
 * zoomed body. This keeps downloads, startup chrome and browser integrations
 * in native viewport coordinates while visual UI portals share app scaling.
 */
export function ensureUiPortalRoot(): HTMLElement {
  let root = document.getElementById(UI_PORTAL_ROOT_ID) as HTMLElement | null;
  if (root) return root;
  root = document.createElement('div');
  root.id = UI_PORTAL_ROOT_ID;
  root.className = UI_SCALE_BOUNDARY_CLASS;
  root.setAttribute('aria-live', 'polite');
  document.body.appendChild(root);
  return root;
}

export function getUiScaleBoundaries(): HTMLElement[] {
  const shell = document.querySelector('.app-shell.koto-unified-workspace') as HTMLElement | null;
  const portal = ensureUiPortalRoot();
  if (shell) shell.classList.add(UI_SCALE_BOUNDARY_CLASS);
  return shell ? [shell, portal] : [portal];
}

export function syncUiScaleBoundaries(zoom: number = readUiZoom()): HTMLElement[] {
  const normalizedZoom = normalizeUiZoom(zoom);
  const boundaries = getUiScaleBoundaries();
  boundaries.forEach((boundary) => {
    boundary.style.setProperty('zoom', String(normalizedZoom), 'important');
  });
  return boundaries;
}

export function appendToUiPortal<T extends HTMLElement>(element: T): T {
  ensureUiPortalRoot().appendChild(element);
  return element;
}

export function getLogicalViewportSize(zoom: number = readUiZoom()): UiSize {
  const normalizedZoom = normalizeUiZoom(zoom);
  return {
    width: window.innerWidth / normalizedZoom,
    height: window.innerHeight / normalizedZoom,
  };
}

/** Keep every responsive breakpoint derived from the same logical width. */
export function syncLogicalViewportClasses(target: HTMLElement, layoutWidth: number): void {
  for (const breakpoint of LOGICAL_VIEWPORT_BREAKPOINTS) {
    target.classList.toggle(`koto-layout-max-${breakpoint}`, layoutWidth <= breakpoint);
  }
  target.classList.toggle('koto-layout-compact', layoutWidth < 1100);
  target.classList.toggle('koto-layout-phone', layoutWidth < 760);
}

/** Return the total painted scale affecting an element, including nested zoom. */
export function getElementPaintScale(element: Element | null): PaintScale {
  if (!(element instanceof HTMLElement) && !(element instanceof SVGElement)) {
    const zoom = readUiZoom();
    return { x: zoom, y: zoom };
  }

  const rect = element.getBoundingClientRect();
  const htmlElement = element as HTMLElement;
  const layoutWidth = Number(htmlElement.offsetWidth) || Number(htmlElement.clientWidth) || 0;
  const layoutHeight = Number(htmlElement.offsetHeight) || Number(htmlElement.clientHeight) || 0;
  const fallback = readUiZoom();
  return {
    x: layoutWidth > 0 ? positiveNumber(rect.width / layoutWidth, fallback) : fallback,
    y: layoutHeight > 0 ? positiveNumber(rect.height / layoutHeight, fallback) : fallback,
  };
}

export function getElementLogicalSize(element: Element): UiSize {
  const htmlElement = element as HTMLElement;
  const rect = element.getBoundingClientRect();
  const scale = getElementPaintScale(element);
  return {
    width: Number(htmlElement.offsetWidth) || Number(htmlElement.clientWidth) || rect.width / scale.x,
    height: Number(htmlElement.offsetHeight) || Number(htmlElement.clientHeight) || rect.height / scale.y,
  };
}

/** Convert a viewport pointer coordinate into an element's logical space. */
export function viewportPointToElement(
  element: Element,
  clientX: number,
  clientY: number,
): UiPoint {
  const rect = element.getBoundingClientRect();
  const scale = getElementPaintScale(element);
  return {
    x: (clientX - rect.left) / scale.x,
    y: (clientY - rect.top) / scale.y,
  };
}

/** Convert a painted pointer delta into an element's logical delta. */
export function viewportDeltaToElement(
  element: Element,
  deltaX: number,
  deltaY: number,
): UiPoint {
  const scale = getElementPaintScale(element);
  return { x: deltaX / scale.x, y: deltaY / scale.y };
}

/** Convert a painted DOMRect into coordinates relative to an element. */
export function viewportRectToElement(element: Element, rect: DOMRect): DOMRect {
  const origin = viewportPointToElement(element, rect.left, rect.top);
  const scale = getElementPaintScale(element);
  return new DOMRect(
    origin.x,
    origin.y,
    rect.width / scale.x,
    rect.height / scale.y,
  );
}

export function getVisualViewportBounds(): VisualViewportBounds {
  const visualViewport = window.visualViewport;
  const left = visualViewport?.offsetLeft || 0;
  const top = visualViewport?.offsetTop || 0;
  const width = visualViewport?.width || window.innerWidth;
  const height = visualViewport?.height || window.innerHeight;
  return { left, top, width, height, right: left + width, bottom: top + height };
}

/**
 * Write a desired painted viewport position to a fixed element living inside
 * the zoomed application coordinate space.
 */
export function setFixedVisualPosition(element: HTMLElement, left: number, top: number): void {
  const scale = getElementPaintScale(element);
  element.style.left = `${left / scale.x}px`;
  element.style.top = `${top / scale.y}px`;
}

/** Clamp and place a fixed element using painted viewport pixels. */
export function placeFixedInViewport(
  element: HTMLElement,
  left: number,
  top: number,
  padding: number = 8,
): UiPoint {
  const viewport = getVisualViewportBounds();
  const rect = element.getBoundingClientRect();
  const visualLeft = Math.min(
    Math.max(viewport.left + padding, left),
    Math.max(viewport.left + padding, viewport.right - rect.width - padding),
  );
  const visualTop = Math.min(
    Math.max(viewport.top + padding, top),
    Math.max(viewport.top + padding, viewport.bottom - rect.height - padding),
  );
  setFixedVisualPosition(element, visualLeft, visualTop);
  return { x: visualLeft, y: visualTop };
}

export function createUiZoomChangeEvent(detail: UiZoomChangeDetail): CustomEvent<UiZoomChangeDetail> {
  return new CustomEvent<UiZoomChangeDetail>(UI_ZOOM_EVENT, { detail });
}

/** Plain-JS editor runtimes consume the same contract through this bridge. */
export const uiScaleApi = Object.freeze({
  readUiZoom,
  ensureUiPortalRoot,
  getUiScaleBoundaries,
  syncUiScaleBoundaries,
  appendToUiPortal,
  getLogicalViewportSize,
  getElementPaintScale,
  getElementLogicalSize,
  viewportPointToElement,
  viewportDeltaToElement,
  viewportRectToElement,
  getVisualViewportBounds,
  setFixedVisualPosition,
  placeFixedInViewport,
});

if (typeof window !== 'undefined') {
  (window as any).KotoUiScale = uiScaleApi;
}
