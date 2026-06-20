/**
 * Pure geometry / measurement for the DOCX review annotation rail.
 * No DOM mutations, no side-effects, no CSS writes.
 */

export interface ZoomScale {
  x: number;
  y: number;
}

export interface LayoutScale {
  x: number;
  y: number;
}

export interface AnchorGeometry {
  top: number;
  bottom: number;
  midY: number;
}

export interface ReviewGeometry {
  cardColLeft: number;
  contentWidth: number;
  hostRect: DOMRect;
  layoutScale: LayoutScale;
  pageEl: HTMLElement | null;
  pageRect: DOMRect | null;
  pagePaddingRight: number;
  pageContentHeight: number;
  railGap: number;
  railWidth: number;
  scrollLeft: number;
  scrollTop: number;
  shellLeft: number;
  shellTop: number;
  textColRight: number;
  viewportRect: DOMRect;
  viewportRight: number;
  viewportWidth: number;
  zoom: ZoomScale;
  toContentX(sx: number): number;
  toContentY(sy: number): number;
}

function readZoomScale(zoomWrapper: HTMLElement | null): ZoomScale {
  if (!zoomWrapper) return { x: 1, y: 1 };
  const t = window.getComputedStyle(zoomWrapper).transform;
  if (!t || t === 'none') return { x: 1, y: 1 };
  const m = t.match(/^matrix\(([^)]+)\)/);
  if (m) {
    const p = m[1].split(',').map(Number);
    if (p.length >= 4 && p.every(Number.isFinite)) {
      return {
        x: Math.hypot(p[0], p[1]) || 1,
        y: Math.hypot(p[2], p[3]) || 1,
      };
    }
  }
  const m3 = t.match(/^matrix3d\(([^)]+)\)/);
  if (m3) {
    const p = m3[1].split(',').map(Number);
    if (p.length >= 16 && p.every(Number.isFinite)) {
      return {
        x: Math.hypot(p[0], p[1], p[2]) || 1,
        y: Math.hypot(p[4], p[5], p[6]) || 1,
      };
    }
  }
  return { x: 1, y: 1 };
}

function screenToContentX(screenX: number, viewportRect: DOMRect, scrollLeft: number, scaleX: number): number {
  const scale = Number.isFinite(scaleX) && scaleX > 0.01 ? scaleX : 1;
  return Math.round(scrollLeft + ((screenX - viewportRect.left) / scale));
}

function screenToContentY(screenY: number, viewportRect: DOMRect, scrollTop: number, scaleY: number): number {
  const scale = Number.isFinite(scaleY) && scaleY > 0.01 ? scaleY : 1;
  return Math.round(scrollTop + ((screenY - viewportRect.top) / scale));
}

function layoutScale(element: HTMLElement | null, rect: DOMRect | null): LayoutScale {
  if (!element || !rect) return { x: 1, y: 1 };
  const width = Number(element.offsetWidth) || Number(element.clientWidth) || 0;
  const height = Number(element.offsetHeight) || Number(element.clientHeight) || 0;
  return {
    x: width > 0 ? Math.max(0.01, rect.width / width) : 1,
    y: height > 0 ? Math.max(0.01, rect.height / height) : 1,
  };
}

export function computeReviewGeometry(host: HTMLElement, viewport: HTMLElement): ReviewGeometry | null {
  if (!host || !viewport) return null;

  const hostRect = host.getBoundingClientRect();
  const viewportRect = viewport.getBoundingClientRect();
  const ls = layoutScale(viewport, viewportRect);
  const scrollLeft = Math.max(0, Math.round(viewport.scrollLeft || 0));
  const scrollTop = Math.max(0, Math.round(viewport.scrollTop || 0));

  const toContentX = (sx: number) => screenToContentX(sx, viewportRect, scrollLeft, ls.x);
  const toContentY = (sy: number) => screenToContentY(sy, viewportRect, scrollTop, ls.y);

  const pageEl = host.querySelector('.ProseMirror') as HTMLElement | null;
  const pageRect = pageEl ? pageEl.getBoundingClientRect() : null;
  const zoomWrapper = pageEl ? pageEl.closest('.koto-zoom-wrapper') as HTMLElement | null : null;
  const zoom = readZoomScale(zoomWrapper);

  const pagePaddingRight = pageEl
    ? Math.max(0, parseFloat(window.getComputedStyle(pageEl).paddingRight) || 0)
    : 0;
  const hostStyles = window.getComputedStyle(host);
  const viewportWidth = Math.max(1, Math.round(viewportRect.width / ls.x));

  let textColRight: number;
  if (pageRect) {
    textColRight = toContentX(pageRect.right) - Math.round(pagePaddingRight * (zoom.x || 1));
  } else {
    textColRight = Math.round(scrollLeft + viewportWidth * 0.68);
  }

  const minRailWidth = 132;
  const cssRailWidth = parseFloat(hostStyles.getPropertyValue('--wa-review-rail-width'));
  const railWidth = Math.max(
    minRailWidth,
    Math.round(
      cssRailWidth ||
      Math.max(140, Math.min(180, viewportWidth * 0.19))
    )
  );

  const railGap = Math.max(6, Math.round(parseFloat(hostStyles.getPropertyValue('--wa-review-rail-gap')) || 16));
  const cardColLeft = textColRight + railGap;

  const contentWidth = Math.max(
    Math.round(viewport.scrollWidth || 0),
    viewportWidth,
    cardColLeft + railWidth + 12,
  );

  const shellLeft = Math.round((viewportRect.left - hostRect.left) / ls.x);
  const shellTop = Math.round((viewportRect.top - hostRect.top) / ls.y);

  return {
    cardColLeft,
    contentWidth,
    hostRect,
    layoutScale: ls,
    pageEl,
    pageRect,
    pagePaddingRight,
    pageContentHeight: pageRect ? Math.round(pageRect.height / ls.y) : (pageEl ? pageEl.offsetHeight : 0),
    railGap,
    railWidth,
    scrollLeft,
    scrollTop,
    shellLeft,
    shellTop,
    textColRight,
    viewportRect,
    viewportRight: Math.round(scrollLeft + viewportWidth),
    viewportWidth,
    zoom,
    toContentX,
    toContentY,
  };
}

export function getAnchorGeometry(
  reviewId: string,
  anchorEl: HTMLElement | null,
  geometry: ReviewGeometry | null,
): AnchorGeometry | null {
  if (!geometry) return null;
  const { viewportRect, scrollTop, pageEl } = geometry;
  const toY = (sy: number) => screenToContentY(sy, viewportRect, scrollTop, 1);

  const cleanId = reviewId
    ? String(reviewId).replace(/^proposal:/, '').replace(/^comment:/, '').trim()
    : '';
  const root = pageEl || document.querySelector('#wa-docx-editor .ProseMirror') as HTMLElement | null;
  if (cleanId && root) {
    const candidates = Array.from(root.querySelectorAll('[data-koto-review-id]'));
    const el = candidates.find(
      (n) => String((n as HTMLElement).getAttribute('data-koto-review-id') || '').trim() === cleanId
    );
    if (el) {
      const r = el.getBoundingClientRect();
      if (r && (r.width > 0 || r.height > 0)) {
        return {
          top: toY(r.top),
          bottom: toY(r.bottom),
          midY: toY(r.top + r.height / 2),
        };
      }
    }
  }

  if (anchorEl && typeof anchorEl.getBoundingClientRect === 'function') {
    const r = anchorEl.getBoundingClientRect();
    if (r && (r.width > 0 || r.height > 0)) {
      return {
        top: toY(r.top),
        bottom: toY(r.bottom),
        midY: toY(r.top + r.height / 2),
      };
    }
  }

  return null;
}

interface ConnectorOpts {
  startX: number;
  startY: number;
  endX: number;
  endY: number;
}

export function buildConnectorPath({ startX, startY, endX, endY }: ConnectorOpts): string {
  const sx = Math.round(startX);
  const sy = Math.round(startY);
  const ex = Math.round(endX);
  const ey = Math.round(endY);
  const vDelta = Math.abs(ey - sy);

  if (vDelta <= 40) {
    return `M ${sx} ${sy} L ${ex} ${ey}`;
  }

  const elbowX = sx + Math.min(20, Math.round((ex - sx) * 0.35));
  return `M ${sx} ${sy} L ${elbowX} ${sy} L ${ex} ${ey}`;
}

(window as any).KotoDocxReviewGeometry = {
  computeReviewGeometry,
  getAnchorGeometry,
  buildConnectorPath,
};
