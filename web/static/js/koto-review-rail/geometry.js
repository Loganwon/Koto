/**
 * koto-review-rail/geometry.js
 *
 * Pure geometry engine for the WPS-style per-page review rail.
 * No DOM mutations. No global state. No side-effects.
 *
 * All coordinates returned are PAGE-RELATIVE (origin = pageEl.getBoundingClientRect()
 * top-left BEFORE zoom transform), so the caller never needs to account for
 * global scroll or viewport offsets. The rail mount lives inside the page element
 * itself, so page-relative coords map directly to CSS `top`/`left` on children.
 *
 * Public API (exposed as window.KotoReviewRailGeometry):
 *   computePageGeometry(pageEl)          → PageGeometry | null
 *   resolveAnchors(items, pageEl)        → AnchorRef[]
 *   mergeNeighborAnchors(refs, tol)      → AnchorCluster[]
 *   relaxCardPositions(clusters, cfg)    → LayoutEntry[]
 *   routeConnector(anchor, card, opts)   → string   (SVG path d)
 */
(function (global) {
  'use strict';

  /* ─────────────────────────────────────────────────────────────────
     Zoom helpers
  ───────────────────────────────────────────────────────────────── */

  function _readZoomScale(el) {
    if (!el) return { x: 1, y: 1 };
    const t = window.getComputedStyle(el).transform;
    if (!t || t === 'none') return { x: 1, y: 1 };
    const m = t.match(/^matrix\(([^)]+)\)/);
    if (m) {
      const p = m[1].split(',').map(Number);
      if (p.length >= 4 && p.every(Number.isFinite))
        return { x: Math.hypot(p[0], p[1]) || 1, y: Math.hypot(p[2], p[3]) || 1 };
    }
    const m3 = t.match(/^matrix3d\(([^)]+)\)/);
    if (m3) {
      const p = m3[1].split(',').map(Number);
      if (p.length >= 16 && p.every(Number.isFinite))
        return { x: Math.hypot(p[0], p[1], p[2]) || 1, y: Math.hypot(p[4], p[5], p[6]) || 1 };
    }
    return { x: 1, y: 1 };
  }

  /* ─────────────────────────────────────────────────────────────────
     computePageGeometry
  ───────────────────────────────────────────────────────────────── */

  /**
   * @param {HTMLElement} pageEl  – the ProseMirror / .koto-doc-page element
   * @returns {PageGeometry | null}
   *
   * PageGeometry:
   *   zoom       {x, y}           CSS transform scale
   *   pageRect   DOMRect          screen rect of pageEl
   *   textColRight  number        page-relative X where prose ends (before margin)
   *   railLeft      number        page-relative X where rail cards begin
   *   railWidth     number        pixel width of the card column
   *   pageHeight    number        full unscaled content height of page
   *   marginRight   number        computed right padding of pageEl
   *   screenToPageY(sy)           screen Y → page-relative Y
   *   screenToPageX(sx)           screen X → page-relative X
   */
  function computePageGeometry(pageEl) {
    if (!pageEl) return null;

    const zoomWrapper = pageEl.closest('.koto-zoom-wrapper') || pageEl.parentElement;
    const zoom = _readZoomScale(zoomWrapper);

    const pageRect = pageEl.getBoundingClientRect();
    if (!pageRect || (pageRect.width === 0 && pageRect.height === 0)) return null;

    const cs = window.getComputedStyle(pageEl);
    const marginRight = Math.max(0, parseFloat(cs.paddingRight) || 0);

    // text-column right edge: page screen right minus right padding, in PAGE-relative coords
    const textColRight = Math.round((pageRect.width - marginRight) / zoom.x);

    // Rail sizing: inside the right margin, with a small safe reserve
    const safeReserve = 6;
    const availRail = Math.max(0, Math.round(marginRight / zoom.x) - safeReserve);
    const railWidth = Math.max(120, Math.min(200, availRail > 0 ? availRail : 160));
    const railGap = 10;
    const railLeft = textColRight + railGap;

    // Page height: use scrollHeight for full content height, unscaled
    const pageHeight = Math.round(pageEl.scrollHeight || pageRect.height / zoom.y);

    const screenToPageX = (sx) => Math.round((sx - pageRect.left) / zoom.x);
    const screenToPageY = (sy) => Math.round((sy - pageRect.top) / zoom.y);

    return {
      zoom,
      pageRect,
      textColRight,
      railLeft,
      railWidth,
      railGap,
      pageHeight,
      marginRight,
      screenToPageX,
      screenToPageY,
    };
  }

  /* ─────────────────────────────────────────────────────────────────
     Anchor resolution helpers
  ───────────────────────────────────────────────────────────────── */

  function _normalizeSearchText(v) {
    return String(v || '').replace(/\s+/g, ' ').trim().toLowerCase();
  }

  function _buildTextIndex(root) {
    if (!root || typeof document.createTreeWalker !== 'function') return null;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode(n) {
        return String(n.textContent || '').trim() ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
      },
    });
    let normalizedText = '';
    const normalizedMap = [];
    const rawPositions = [];
    let rawIndex = 0;
    let prevWS = false;
    let node;
    while ((node = walker.nextNode())) {
      const raw = String(node.nodeValue || '');
      for (let i = 0; i < raw.length; i++) {
        rawPositions[rawIndex] = { node, offset: i };
        const ch = raw[i];
        const nc = /\s/.test(ch) ? ' ' : ch.toLowerCase();
        if (nc === ' ') {
          if (!prevWS) { normalizedText += ' '; normalizedMap.push(rawIndex); prevWS = true; }
        } else {
          normalizedText += nc; normalizedMap.push(rawIndex); prevWS = false;
        }
        rawIndex++;
      }
    }
    return { normalizedText, normalizedMap, rawPositions };
  }

  function _findAnchorRange(root, item, textIndex) {
    const key = String(item.id || item.review_id || '').replace(/^proposal:|^comment:/, '').trim();
    if (key) {
      const el = Array.from(root.querySelectorAll('[data-koto-review-id]')).find(
        (e) => e.getAttribute('data-koto-review-id').trim() === key,
      );
      if (el && el.ownerDocument.createRange) {
        const r = el.ownerDocument.createRange();
        r.selectNodeContents(el);
        return r;
      }
    }
    if (!textIndex) return null;
    const needle = _normalizeSearchText(
      item.anchor_text || item.original_text || item.body || '',
    );
    if (!needle) return null;
    const hay = textIndex.normalizedText;
    const matches = [];
    let cursor = 0;
    while (cursor < hay.length) {
      const pos = hay.indexOf(needle, cursor);
      if (pos === -1) break;
      matches.push([pos, pos + needle.length]);
      cursor = pos + Math.max(1, needle.length);
    }
    if (!matches.length) return null;

    // Pick by occurrence or context
    const occ = Number(item.anchor_occurrence ?? item.anchorOccurrence ?? -1);
    let chosen = matches[0];
    if (Number.isFinite(occ) && occ >= 0 && occ < matches.length) {
      chosen = matches[Math.floor(occ)];
    } else {
      const ctxBefore = _normalizeSearchText(item.anchor_context_before || '');
      const ctxAfter = _normalizeSearchText(item.anchor_context_after || '');
      let best = -1;
      matches.forEach((m) => {
        let score = 0;
        if (ctxBefore && hay.slice(Math.max(0, m[0] - ctxBefore.length - 8), m[0]).includes(ctxBefore)) score += 2;
        if (ctxAfter && hay.slice(m[1], m[1] + ctxAfter.length + 8).includes(ctxAfter)) score += 2;
        if (score > best) { best = score; chosen = m; }
      });
    }

    const si = textIndex.normalizedMap[chosen[0]];
    const ei = textIndex.normalizedMap[chosen[1] - 1];
    const sp = textIndex.rawPositions[si];
    const ep = textIndex.rawPositions[ei];
    if (!sp || !ep) return null;
    const range = sp.node.ownerDocument.createRange();
    range.setStart(sp.node, sp.offset);
    range.setEnd(ep.node, ep.offset + 1);
    return range;
  }

  /* ─────────────────────────────────────────────────────────────────
     resolveAnchors
  ───────────────────────────────────────────────────────────────── */

  /**
   * For each item in `items`, find its anchor element in `pageEl` and
   * return a page-relative AnchorRef.  Items whose anchor is not found
   * in this page are omitted.
   *
   * @param {ReviewItem[]} items
   * @param {HTMLElement}  pageEl
   * @returns {AnchorRef[]}
   *   { itemId, midY, lineTopY, lineBottomY, lineRight }
   *   All coordinates are PAGE-RELATIVE (unscaled).
   */
  function resolveAnchors(items, pageEl) {
    if (!pageEl || !items || !items.length) return [];
    const geo = computePageGeometry(pageEl);
    if (!geo) return [];

    const textIndex = _buildTextIndex(pageEl);
    const refs = [];

    for (const item of items) {
      // Skip reply items (parent_id set) — they share the parent's anchor
      if (item.parent_id) continue;

      const range = _findAnchorRange(pageEl, item, textIndex);
      if (!range) continue;

      const rects = Array.from(range.getClientRects()).filter(
        (r) => r && (r.width > 0.5 || r.height > 0.5),
      );
      if (!rects.length) continue;

      // Use the LAST rect's right edge as connector origin (end of annotated text)
      const lastRect = rects[rects.length - 1];
      const firstRect = rects[0];

      const midY = geo.screenToPageY(lastRect.top + lastRect.height / 2);
      const lineTopY = geo.screenToPageY(firstRect.top);
      const lineBottomY = geo.screenToPageY(lastRect.bottom);
      const lineRight = geo.screenToPageX(lastRect.right);

      // Only include anchors that are actually within this page's content area
      if (midY < 0 || midY > geo.pageHeight + 20) continue;

      refs.push({
        itemId: item.id,
        midY,
        lineTopY,
        lineBottomY,
        lineRight: Math.min(lineRight, geo.textColRight),
      });
    }

    // Sort by midY top-down
    refs.sort((a, b) => a.midY - b.midY);
    return refs;
  }

  /* ─────────────────────────────────────────────────────────────────
     mergeNeighborAnchors
  ───────────────────────────────────────────────────────────────── */

  /**
   * Merge anchors from the same text line (within `tolerancePx`) into one cluster.
   * The cluster's midY = average of merged anchor midYs.
   * Multiple items in a cluster share a single connector origin point (WPS behavior).
   *
   * @param {AnchorRef[]} refs         – sorted by midY
   * @param {number}      tolerancePx  – merge window in page-relative pixels (default 6)
   * @returns {AnchorCluster[]}
   *   { itemIds[], midY, lineRight }
   */
  function mergeNeighborAnchors(refs, tolerancePx = 6) {
    if (!refs || !refs.length) return [];
    const clusters = [];
    let current = null;
    for (const ref of refs) {
      if (!current || ref.midY - current.midY > tolerancePx) {
        current = {
          itemIds: [ref.itemId],
          midY: ref.midY,
          lineTopY: ref.lineTopY,
          lineRight: ref.lineRight,
        };
        clusters.push(current);
      } else {
        current.itemIds.push(ref.itemId);
        // Take rightmost lineRight and average midY
        current.lineTopY = Math.min(current.lineTopY, ref.lineTopY);
        current.lineRight = Math.max(current.lineRight, ref.lineRight);
        current.midY = Math.round((current.midY + ref.midY) / 2);
      }
    }
    return clusters;
  }

  /* ─────────────────────────────────────────────────────────────────
     relaxCardPositions  (linked-list O(n) slack relaxation)
  ───────────────────────────────────────────────────────────────── */

  const CARD_GAP = 8;        // minimum vertical gap between cards (px)
  const MAX_RELAX_PASSES = 8; // guard against degenerate cases

  /**
   * Given clusters and their desired card heights, compute final top positions
   * that:
   *  - prefer anchor.midY − cardHeight/2 (center card on anchor)
   *  - push cards apart to avoid overlap
   *  - clamp to [0, pageHeight − totalCardsHeight]
   *
   * @param {AnchorCluster[]} clusters
   * @param {Map<string,number>} cardHeights   itemId → pixel height
   * @param {object} cfg   { railHeight, cardWidth, defaultCardHeight }
   * @returns {LayoutEntry[]}
   *   { itemId, top, height, clusterMidY, connectorOriginY }
   */
  function relaxCardPositions(clusters, cardHeights, cfg = {}) {
    const { railHeight = 2000, defaultCardHeight = 60 } = cfg;

    if (!clusters || !clusters.length) return [];

    // Build initial entries: one entry per cluster (will split multi-item clusters later)
    const entries = [];
    for (const cluster of clusters) {
      for (const itemId of cluster.itemIds) {
        const h = cardHeights.get(itemId) || defaultCardHeight;
        const anchorTop = Number.isFinite(cluster.lineTopY) ? cluster.lineTopY : cluster.midY;
        const desiredTop = Math.max(0, Math.round(anchorTop - 2));
        entries.push({
          itemId,
          top: desiredTop,
          height: h,
          clusterMidY: cluster.midY,
          connectorOriginY: cluster.midY,
          _desired: desiredTop,
        });
      }
    }

    // Relaxation passes: push overlapping cards downward
    for (let pass = 0; pass < MAX_RELAX_PASSES; pass++) {
      let changed = false;
      for (let i = 1; i < entries.length; i++) {
        const prev = entries[i - 1];
        const curr = entries[i];
        const minTop = prev.top + prev.height + CARD_GAP;
        if (curr.top < minTop) {
          curr.top = minTop;
          changed = true;
        }
      }
      if (!changed) break;
    }

    // Clamp from bottom: pull cards up if they overflow the page
    let totalH = entries.reduce((s, e) => s + e.height + CARD_GAP, -CARD_GAP);
    if (entries.length && totalH > railHeight) {
      // Compress top-to-bottom keeping min gap
      let y = 0;
      for (const e of entries) {
        e.top = y;
        y += e.height + CARD_GAP;
      }
    } else if (entries.length) {
      const last = entries[entries.length - 1];
      const overflow = (last.top + last.height) - railHeight;
      if (overflow > 0) {
        entries.forEach((e) => { e.top -= overflow; });
        const underflow = Math.min(0, entries[0].top);
        if (underflow < 0) {
          entries.forEach((e) => { e.top -= underflow; });
        }
      }
    }

    return entries;
  }

  /* ─────────────────────────────────────────────────────────────────
     routeConnector  (L-shape / elbow polyline avoiding neighbor bands)
  ───────────────────────────────────────────────────────────────── */

  /**
   * Build an SVG path string for a WPS-style dashed connector.
   *
   * The connector has an L-shaped route:
   *   anchorPoint (right edge of annotated text)
   *     → short horizontal stub to textColRight
   *     → vertical segment to card midY level
   *     → horizontal segment to card left edge
   *
   * `usedBands` is an array of {y1, y2} ranges already occupied by other
   * connectors' vertical segments.  When this connector's vertical track
   * would overlap, the connector shifts its horizontal stub slightly to
   * find a clear lane (max 3 attempts, step 8px).
   *
   * @param {{ anchorX, anchorY, textColRight }} anchor
   * @param {{ left, midY }} card
   * @param {{ usedBands?, addBand? }} opts
   * @returns {string}
   */
  function routeConnector(anchor, card, opts = {}) {
    const { anchorX, anchorY, textColRight } = anchor;
    const { left: cardLeft, midY: cardMidY } = card;
    const usedBands = opts.usedBands || [];
    const addBand = opts.addBand || null;

    const ax = Math.round(anchorX);
    const ay = Math.round(anchorY);
    const cx = Math.round(cardLeft - 2);
    const cy = Math.round(cardMidY);
    const tcr = Math.round(textColRight);

    // If anchor is at/beyond textColRight just draw a direct line to card
    if (ax >= tcr) {
      return `M ${ax} ${ay} L ${cx} ${cy}`;
    }

    const vDelta = Math.abs(cy - ay);

    if (vDelta <= 4) {
      // Nearly flat — single horizontal line
      return `M ${ax} ${ay} L ${cx} ${cy}`;
    }

    // Standard L-shape: horizontal → vertical → horizontal
    // Vertical track runs at tcr (text column right edge)
    const trackX = tcr + 1;

    // Find a clear vertical lane (shift by ±4px to avoid congestion)
    let finalTrackX = trackX;
    for (let attempt = 0; attempt < 3; attempt++) {
      const candidate = trackX + attempt * 4;
      const busy = usedBands.some((b) => {
        const minY = Math.min(ay, cy);
        const maxY = Math.max(ay, cy);
        return candidate >= b.x - 2 && candidate <= b.x + 2
          && maxY > b.y1 - 2 && minY < b.y2 + 2;
      });
      if (!busy) { finalTrackX = candidate; break; }
    }

    if (addBand) {
      addBand({ x: finalTrackX, y1: Math.min(ay, cy), y2: Math.max(ay, cy) });
    }

    return `M ${ax} ${ay} L ${finalTrackX} ${ay} L ${finalTrackX} ${cy} L ${cx} ${cy}`;
  }

  /* ─────────────────────────────────────────────────────────────────
     Module export
  ───────────────────────────────────────────────────────────────── */

  global.KotoReviewRailGeometry = {
    computePageGeometry,
    resolveAnchors,
    mergeNeighborAnchors,
    relaxCardPositions,
    routeConnector,
  };
})(window);
