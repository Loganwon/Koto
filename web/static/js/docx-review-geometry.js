/**
 * docx-review-geometry.js
 *
 * Pure geometry / measurement for the DOCX review annotation rail.
 * No DOM mutations, no side-effects, no CSS writes.
 *
 * Exposed as window.KotoDocxReviewGeometry.
 */
(function () {
  'use strict';

  /* ─────────────────────────────────────────────────────────────────
     Low-level helpers
  ───────────────────────────────────────────────────────────────── */

  /**
   * Parse the CSS transform matrix on a zoom wrapper element to get the
   * X/Y scale factors applied to the document page.
   * Returns { x, y } (defaults to { x:1, y:1 } when not found).
   */
  function _readZoomScale(zoomWrapper) {
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

  /**
   * Convert a screen-space X coordinate to a content-space X coordinate.
   * Content X = viewportScrollLeft + (screenX − viewportRect.left)
   */
  function _screenToContentX(screenX, viewportRect, scrollLeft, scaleX) {
    const scale = Number.isFinite(scaleX) && scaleX > 0.01 ? scaleX : 1;
    return Math.round(scrollLeft + ((screenX - viewportRect.left) / scale));
  }

  /**
   * Convert a screen-space Y coordinate to a content-space Y coordinate.
   * Content Y = viewportScrollTop + (screenY − viewportRect.top)
   */
  function _screenToContentY(screenY, viewportRect, scrollTop, scaleY) {
    const scale = Number.isFinite(scaleY) && scaleY > 0.01 ? scaleY : 1;
    return Math.round(scrollTop + ((screenY - viewportRect.top) / scale));
  }

  function _layoutScale(element, rect) {
    if (!element || !rect) return { x: 1, y: 1 };
    const width = Number(element.offsetWidth) || Number(element.clientWidth) || 0;
    const height = Number(element.offsetHeight) || Number(element.clientHeight) || 0;
    return {
      x: width > 0 ? Math.max(0.01, rect.width / width) : 1,
      y: height > 0 ? Math.max(0.01, rect.height / height) : 1,
    };
  }

  /* ─────────────────────────────────────────────────────────────────
     Main geometry computation
  ───────────────────────────────────────────────────────────────── */

  /**
   * Compute the full geometry state for one layout pass of the review rail.
   *
   * @param {HTMLElement} host     – #wa-docx-editor (position:relative container)
   * @param {HTMLElement} viewport – #wa-editor-content (scrollable container)
   * @returns {ReviewGeometry|null}
   *
   * ReviewGeometry fields:
   *   hostRect, viewportRect
   *   scrollLeft, scrollTop
   *   pageEl, pageRect, pagePaddingRight
   *   zoom: { x, y }
   *   textColRight   — content-coord X where text ends (right of text, before margin)
   *   railGap        — fixed gap from textColRight to card left edge (16px)
   *   railWidth      — computed card column width (140–180px)
   *   cardColLeft    — content-coord X for card left edge (= textColRight + railGap)
   *   contentWidth   — total content width needed for the SVG overlay
   *   shellLeft      — host-coord left offset for #wa-review-shell
   *   shellTop       — host-coord top offset for #wa-review-shell
   *   toContentX(sx) — helper: screen X → content X
   *   toContentY(sy) — helper: screen Y → content Y
   */
  function computeReviewGeometry(host, viewport) {
    if (!host || !viewport) return null;

    const hostRect = host.getBoundingClientRect();
    const viewportRect = viewport.getBoundingClientRect();
    const layoutScale = _layoutScale(viewport, viewportRect);
    const scrollLeft = Math.max(0, Math.round(viewport.scrollLeft || 0));
    const scrollTop  = Math.max(0, Math.round(viewport.scrollTop  || 0));

    const toContentX = (sx) => _screenToContentX(sx, viewportRect, scrollLeft, layoutScale.x);
    const toContentY = (sy) => _screenToContentY(sy, viewportRect, scrollTop, layoutScale.y);

    // Page element (ProseMirror) and its zoom wrapper
    const pageEl = host.querySelector('.ProseMirror') || null;
    const pageRect = pageEl ? pageEl.getBoundingClientRect() : null;
    const zoomWrapper = pageEl ? pageEl.closest('.koto-zoom-wrapper') : null;
    const zoom = _readZoomScale(zoomWrapper);

    // Right padding of the page (the natural document margin)
    const pagePaddingRight = pageEl
      ? Math.max(0, parseFloat(window.getComputedStyle(pageEl).paddingRight) || 0)
      : 0;
    const hostStyles = window.getComputedStyle(host);
    const viewportWidth = Math.max(1, Math.round(viewportRect.width / layoutScale.x));

    // Text-column right edge in content coordinates:
    // = right edge of ProseMirror box − its right padding, converted to content space.
    let textColRight;
    if (pageRect) {
      textColRight = toContentX(pageRect.right) - Math.round(pagePaddingRight * (zoom.x || 1));
    } else {
      // Fallback when page element is not available
      textColRight = Math.round(scrollLeft + viewportWidth * 0.68);
    }

    // Rail sizing: viewport-aware, no persistence
    const minRailWidth  = 132;
    const cssRailWidth = parseFloat(hostStyles.getPropertyValue('--wa-review-rail-width'));
    const railWidth = Math.max(
      minRailWidth,
      Math.round(
        cssRailWidth ||
        Math.max(140, Math.min(180, viewportWidth * 0.19))
      )
    );

    // Fixed gap between text column right edge and card left edge
    const railGap = Math.max(6, Math.round(parseFloat(hostStyles.getPropertyValue('--wa-review-rail-gap')) || 16));
    const cardColLeft = textColRight + railGap;

    // Total content width for the SVG layer (must cover cards fully)
    const contentWidth = Math.max(
      Math.round(viewport.scrollWidth  || 0),
      viewportWidth,
      cardColLeft + railWidth + 12,
    );

    // Shell position in host-relative coordinates.
    // Because shell is position:absolute inside host, a card at content-coord X
    // will appear at screen X = hostRect.left + shellLeft + X.
    // We want the shell itself to cover the viewport; listEl's transform handles scroll.
    // ⟹ shellLeft = viewportRect.left − hostRect.left, converted back through UI zoom.
    const shellLeft = Math.round((viewportRect.left - hostRect.left) / layoutScale.x);
    const shellTop  = Math.round((viewportRect.top  - hostRect.top)  / layoutScale.y);

    return {
      cardColLeft,
      contentWidth,
      hostRect,
      layoutScale,
      pageEl,
      pageRect,
      pagePaddingRight,
      pageContentHeight: pageRect ? Math.round(pageRect.height / layoutScale.y) : (pageEl ? pageEl.offsetHeight : 0),
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

  /* ─────────────────────────────────────────────────────────────────
     Anchor geometry resolution
  ───────────────────────────────────────────────────────────────── */

  /**
   * Get content-space geometry for a review anchor.
   *
   * Priority order:
   *   1. [data-koto-review-id="reviewId"] span in the ProseMirror DOM — exact, O(1)
   *   2. Element supplied directly by caller (anchorEl)
   *   3. null (caller handles missing anchor gracefully)
   *
   * Returns: { top, bottom, midY } in content coordinates, or null.
   */
  function getAnchorGeometry(reviewId, anchorEl, geometry) {
    if (!geometry) return null;
    const { viewportRect, scrollLeft, scrollTop, pageEl } = geometry;
    const toY = (sy) => _screenToContentY(sy, viewportRect, scrollTop);

    // Strategy 1: find [data-koto-review-id] span in content DOM
    const cleanId = reviewId
      ? String(reviewId).replace(/^proposal:/, '').replace(/^comment:/, '').trim()
      : '';
    const root = pageEl || document.querySelector('#wa-docx-editor .ProseMirror');
    if (cleanId && root) {
      const candidates = Array.from(root.querySelectorAll('[data-koto-review-id]'));
      const el = candidates.find(
        (n) => String(n.getAttribute('data-koto-review-id') || '').trim() === cleanId
      );
      if (el) {
        const r = el.getBoundingClientRect();
        if (r && (r.width > 0 || r.height > 0)) {
          return {
            top:  toY(r.top),
            bottom: toY(r.bottom),
            midY: toY(r.top + r.height / 2),
          };
        }
      }
    }

    // Strategy 2: directly supplied element
    if (anchorEl && typeof anchorEl.getBoundingClientRect === 'function') {
      const r = anchorEl.getBoundingClientRect();
      if (r && (r.width > 0 || r.height > 0)) {
        return {
          top:    toY(r.top),
          bottom: toY(r.bottom),
          midY:   toY(r.top + r.height / 2),
        };
      }
    }

    return null;
  }

  /* ─────────────────────────────────────────────────────────────────
     Connector path builder
  ───────────────────────────────────────────────────────────────── */

  /**
   * Build the SVG "d" attribute for a review connector line.
   *
   * The connector goes from (textColRight, anchorMidY) to (cardLeft-4, cardMidY).
   * When the card is displaced vertically by more than 40px from the anchor,
   * an elbow jog is added so lines do not appear to float mid-air.
   *
   * @param {{ startX, startY, endX, endY }} opts
   * @returns {string} SVG path d-attribute value
   */
  function buildConnectorPath({ startX, startY, endX, endY }) {
    const sx = Math.round(startX);
    const sy = Math.round(startY);
    const ex = Math.round(endX);
    const ey = Math.round(endY);
    const vDelta = Math.abs(ey - sy);

    if (vDelta <= 40) {
      // Short straight line
      return `M ${sx} ${sy} L ${ex} ${ey}`;
    }

    // Elbow: horizontal stub at anchor Y, then diagonal to card
    const elbowX = sx + Math.min(20, Math.round((ex - sx) * 0.35));
    return `M ${sx} ${sy} L ${elbowX} ${sy} L ${ex} ${ey}`;
  }

  /* ─────────────────────────────────────────────────────────────────
     Module export
  ───────────────────────────────────────────────────────────────── */

  window.KotoDocxReviewGeometry = {
    computeReviewGeometry,
    getAnchorGeometry,
    buildConnectorPath,
  };
})();
