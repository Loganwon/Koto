/**
 * koto-review-rail/connector-layer.js
 *
 * Manages the per-page SVG connector layer (`.koto-rail-connectors`).
 * Draws WPS-style dashed leader lines from annotated text to review cards.
 *
 * Public API (window.KotoReviewRailConnectorLayer):
 *   updateConnectors(svgEl, layoutEntries, geo)  → void
 *   clearConnectors(svgEl)                       → void
 *
 * `layoutEntries` = LayoutEntry[] from geometry.relaxCardPositions(), each extended with:
 *   { itemId, top, height, connectorOriginY, clusterMidY, anchorX, cardLeft }
 *
 * `geo` = PageGeometry from geometry.computePageGeometry()
 */
(function (global) {
  'use strict';

  const SVG_NS = 'http://www.w3.org/2000/svg';

  // WPS connector style tokens
  const CONNECTOR_COLOR_DEFAULT  = 'var(--koto-review-connector, #c0392b)';
  const CONNECTOR_COLOR_FOCUSED  = 'var(--koto-review-connector-focus, #e74c3c)';
  const CONNECTOR_COLOR_HOVERED  = 'var(--koto-review-connector-hover, #e67e22)';
  const CONNECTOR_STROKE_DEFAULT = '1.2';
  const CONNECTOR_STROKE_FOCUSED = '1.8';
  const CONNECTOR_DASH_DEFAULT   = '2.5 3';
  const CONNECTOR_DASH_FOCUSED   = '2.5 3';

  function clearConnectors(svgEl) {
    if (!svgEl) return;
    svgEl.innerHTML = '';
  }

  /**
   * @param {SVGSVGElement} svgEl
   * @param {LayoutEntry[]} layoutEntries  – each: { itemId, top, height, connectorOriginY, anchorX, cardLeft, isFocused, isHovered, kind }
   * @param {PageGeometry}  geo
   */
  function updateConnectors(svgEl, layoutEntries, geo) {
    if (!svgEl || !layoutEntries || !geo) return;
    clearConnectors(svgEl);

    // Size the SVG to cover the full page height + right margin
    svgEl.setAttribute('width', String(geo.railLeft + geo.railWidth + 20));
    svgEl.setAttribute('height', String(geo.pageHeight));
    svgEl.style.position = 'absolute';
    svgEl.style.left = '0';
    svgEl.style.top = '0';
    svgEl.style.pointerEvents = 'none';
    svgEl.style.overflow = 'visible';

    const routeConnector = global.KotoReviewRailGeometry
      ? global.KotoReviewRailGeometry.routeConnector
      : _fallbackRoute;

    const usedBands = [];
    const addBand = (b) => usedBands.push(b);

    for (const entry of layoutEntries) {
      const cardMidY = entry.top + Math.round(entry.height / 2);

      const d = routeConnector(
        {
          anchorX:     entry.anchorX !== undefined ? entry.anchorX : geo.textColRight,
          anchorY:     entry.connectorOriginY,
          textColRight: geo.textColRight,
        },
        {
          left:  entry.cardLeft !== undefined ? entry.cardLeft : geo.railLeft,
          midY:  cardMidY,
        },
        { usedBands, addBand },
      );

      const isFocused = !!entry.isFocused;
      const isHovered = !!entry.isHovered;

      const path = document.createElementNS(SVG_NS, 'path');
      path.setAttribute('d', d);
      path.setAttribute('fill', 'none');
      path.setAttribute(
        'stroke',
        isHovered ? CONNECTOR_COLOR_HOVERED : isFocused ? CONNECTOR_COLOR_FOCUSED : CONNECTOR_COLOR_DEFAULT,
      );
      path.setAttribute(
        'stroke-width',
        (isFocused || isHovered) ? CONNECTOR_STROKE_FOCUSED : CONNECTOR_STROKE_DEFAULT,
      );
      path.setAttribute('stroke-dasharray', (isFocused || isHovered) ? CONNECTOR_DASH_FOCUSED : CONNECTOR_DASH_DEFAULT);
      path.setAttribute('stroke-linecap', 'round');
      path.setAttribute('stroke-linejoin', 'round');
      path.dataset.reviewId = String(entry.itemId || '');
      if (isFocused) path.classList.add('is-focused');
      if (isHovered) path.classList.add('is-hovered');
      svgEl.appendChild(path);
    }
  }

  function _fallbackRoute(anchor, card) {
    return `M ${anchor.anchorX} ${anchor.anchorY} L ${card.left} ${card.midY}`;
  }

  global.KotoReviewRailConnectorLayer = { updateConnectors, clearConnectors };
})(window);
