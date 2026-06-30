(function() {
  "use strict";
  function readZoomScale(zoomWrapper) {
    if (!zoomWrapper) return { x: 1, y: 1 };
    const t = window.getComputedStyle(zoomWrapper).transform;
    if (!t || t === "none") return { x: 1, y: 1 };
    const m = t.match(/^matrix\(([^)]+)\)/);
    if (m) {
      const p = m[1].split(",").map(Number);
      if (p.length >= 4 && p.every(Number.isFinite)) {
        return {
          x: Math.hypot(p[0], p[1]) || 1,
          y: Math.hypot(p[2], p[3]) || 1
        };
      }
    }
    const m3 = t.match(/^matrix3d\(([^)]+)\)/);
    if (m3) {
      const p = m3[1].split(",").map(Number);
      if (p.length >= 16 && p.every(Number.isFinite)) {
        return {
          x: Math.hypot(p[0], p[1], p[2]) || 1,
          y: Math.hypot(p[4], p[5], p[6]) || 1
        };
      }
    }
    return { x: 1, y: 1 };
  }
  function screenToContentX(screenX, viewportRect, scrollLeft, scaleX) {
    const scale = Number.isFinite(scaleX) && scaleX > 0.01 ? scaleX : 1;
    return Math.round(scrollLeft + (screenX - viewportRect.left) / scale);
  }
  function screenToContentY(screenY, viewportRect, scrollTop, scaleY) {
    const scale = Number.isFinite(scaleY) && scaleY > 0.01 ? scaleY : 1;
    return Math.round(scrollTop + (screenY - viewportRect.top) / scale);
  }
  function layoutScale(element, rect) {
    if (!element || !rect) return { x: 1, y: 1 };
    const width = Number(element.offsetWidth) || Number(element.clientWidth) || 0;
    const height = Number(element.offsetHeight) || Number(element.clientHeight) || 0;
    return {
      x: width > 0 ? Math.max(0.01, rect.width / width) : 1,
      y: height > 0 ? Math.max(0.01, rect.height / height) : 1
    };
  }
  function computeReviewGeometry(host, viewport) {
    if (!host || !viewport) return null;
    const hostRect = host.getBoundingClientRect();
    const viewportRect = viewport.getBoundingClientRect();
    const ls = layoutScale(viewport, viewportRect);
    const scrollLeft = Math.max(0, Math.round(viewport.scrollLeft || 0));
    const scrollTop = Math.max(0, Math.round(viewport.scrollTop || 0));
    const toContentX = (sx) => screenToContentX(sx, viewportRect, scrollLeft, ls.x);
    const toContentY = (sy) => screenToContentY(sy, viewportRect, scrollTop, ls.y);
    const pageEl = host.querySelector(".ProseMirror");
    const pageRect = pageEl ? pageEl.getBoundingClientRect() : null;
    const zoomWrapper = pageEl ? pageEl.closest(".koto-zoom-wrapper") : null;
    const zoom = readZoomScale(zoomWrapper);
    const pagePaddingRight = pageEl ? Math.max(0, parseFloat(window.getComputedStyle(pageEl).paddingRight) || 0) : 0;
    const hostStyles = window.getComputedStyle(host);
    const viewportWidth = Math.max(1, Math.round(viewportRect.width / ls.x));
    let textColRight;
    if (pageRect) {
      textColRight = toContentX(pageRect.right) - Math.round(pagePaddingRight * (zoom.x || 1));
    } else {
      textColRight = Math.round(scrollLeft + viewportWidth * 0.68);
    }
    const minRailWidth = 220;
    const cssRailWidth = parseFloat(hostStyles.getPropertyValue("--wa-review-rail-width"));
    const railWidth = Math.max(
      minRailWidth,
      Math.round(
        cssRailWidth || Math.max(220, Math.min(300, viewportWidth * 0.24))
      )
    );
    const railGap = Math.max(6, Math.round(parseFloat(hostStyles.getPropertyValue("--wa-review-rail-gap")) || 16));
    const cardColLeft = textColRight + railGap;
    const contentWidth = Math.max(
      Math.round(viewport.scrollWidth || 0),
      viewportWidth,
      cardColLeft + railWidth + 12
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
      pageContentHeight: pageRect ? Math.round(pageRect.height / ls.y) : pageEl ? pageEl.offsetHeight : 0,
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
      toContentY
    };
  }
  function getAnchorGeometry(reviewId, anchorEl, geometry) {
    if (!geometry) return null;
    const { viewportRect, scrollTop, pageEl } = geometry;
    const toY = (sy) => screenToContentY(sy, viewportRect, scrollTop, 1);
    const cleanId = reviewId ? String(reviewId).replace(/^proposal:/, "").replace(/^comment:/, "").trim() : "";
    const root = pageEl || document.querySelector("#wa-docx-editor .ProseMirror");
    if (cleanId && root) {
      const candidates = Array.from(root.querySelectorAll("[data-koto-review-id]"));
      const el = candidates.find(
        (n) => String(n.getAttribute("data-koto-review-id") || "").trim() === cleanId
      );
      if (el) {
        const r = el.getBoundingClientRect();
        if (r && (r.width > 0 || r.height > 0)) {
          return {
            top: toY(r.top),
            bottom: toY(r.bottom),
            midY: toY(r.top + r.height / 2)
          };
        }
      }
    }
    if (anchorEl && typeof anchorEl.getBoundingClientRect === "function") {
      const r = anchorEl.getBoundingClientRect();
      if (r && (r.width > 0 || r.height > 0)) {
        return {
          top: toY(r.top),
          bottom: toY(r.bottom),
          midY: toY(r.top + r.height / 2)
        };
      }
    }
    return null;
  }
  function buildConnectorPath({ startX, startY, endX, endY }) {
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
  window.KotoDocxReviewGeometry = {
    computeReviewGeometry,
    getAnchorGeometry,
    buildConnectorPath
  };
  const SVG_NS = "http://www.w3.org/2000/svg";
  function createDocxReviewLayoutSvg(deps) {
    const {
      state,
      $,
      _findReviewEntry,
      _findDocxReviewAnchorElement,
      _getReviewCommentSelectionState
    } = deps;
    function _normalizeReviewSearchText(value) {
      return String(value || "").replace(/\s+/g, " ").trim().toLowerCase();
    }
    function _buildReviewMarkerIndex(root) {
      const index = /* @__PURE__ */ new Map();
      if (!root || !root.querySelectorAll) return index;
      root.querySelectorAll("[data-koto-review-id]").forEach((element) => {
        const key = String(element.getAttribute("data-koto-review-id") || "").trim();
        if (!key) return;
        if (!index.has(key)) index.set(key, []);
        index.get(key).push(element);
      });
      return index;
    }
    function _buildReviewTextIndex(root) {
      if (!root || !root.ownerDocument || !root.ownerDocument.createRange || typeof document.createTreeWalker !== "function") {
        return null;
      }
      const walker = document.createTreeWalker(
        root,
        NodeFilter.SHOW_TEXT,
        {
          acceptNode(node2) {
            return String(node2.textContent || "").trim() ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
          }
        }
      );
      const normalizedMap = [];
      const rawPositions = [];
      let normalizedText = "";
      let rawIndex = 0;
      let previousWhitespace = false;
      let node;
      while (node = walker.nextNode()) {
        const rawText = String(node.nodeValue || "");
        for (let index = 0; index < rawText.length; index += 1) {
          rawPositions[rawIndex] = { node, offset: index };
          const char = rawText[index];
          const normalizedChar = /\s/.test(char) ? " " : char.toLowerCase();
          if (normalizedChar === " ") {
            if (!previousWhitespace) {
              normalizedText += " ";
              normalizedMap.push(rawIndex);
              previousWhitespace = true;
            }
          } else {
            normalizedText += normalizedChar;
            normalizedMap.push(rawIndex);
            previousWhitespace = false;
          }
          rawIndex += 1;
        }
      }
      return { normalizedMap, normalizedText, rawPositions };
    }
    function _rangeFromReviewTextIndex(index, normalizedStart, normalizedEnd) {
      if (!index || normalizedEnd <= normalizedStart) return null;
      const startRawIndex = index.normalizedMap[normalizedStart];
      const endRawIndex = index.normalizedMap[normalizedEnd - 1];
      const startPos = index.rawPositions[startRawIndex];
      const endPos = index.rawPositions[endRawIndex];
      if (!startPos || !endPos || !startPos.node || !endPos.node) return null;
      const range = startPos.node.ownerDocument.createRange();
      range.setStart(startPos.node, startPos.offset);
      range.setEnd(endPos.node, endPos.offset + 1);
      return range;
    }
    function _collectReviewTextMatches(haystack, needle) {
      const matches = [];
      if (!haystack || !needle) return matches;
      let cursor = 0;
      while (cursor < haystack.length) {
        const foundAt = haystack.indexOf(needle, cursor);
        if (foundAt === -1) break;
        matches.push([foundAt, foundAt + needle.length]);
        cursor = foundAt + Math.max(1, needle.length);
      }
      return matches;
    }
    function _selectReviewTextMatch(index, matches, item) {
      if (!index || !Array.isArray(matches) || !matches.length) return null;
      const occurrence = Number(item && (item.anchor_occurrence ?? item.anchorOccurrence));
      if (Number.isFinite(occurrence) && occurrence >= 0 && occurrence < matches.length) {
        return matches[Math.floor(occurrence)];
      }
      const beforeNeedle = _normalizeReviewSearchText(
        item && (item.anchor_context_before ?? item.anchorContextBefore)
      );
      const afterNeedle = _normalizeReviewSearchText(
        item && (item.anchor_context_after ?? item.anchorContextAfter)
      );
      let bestMatch = matches[0];
      let bestScore = -1;
      matches.forEach((match) => {
        const beforeText = beforeNeedle ? index.normalizedText.slice(Math.max(0, match[0] - beforeNeedle.length - 8), match[0]) : "";
        const afterText = afterNeedle ? index.normalizedText.slice(match[1], match[1] + afterNeedle.length + 8) : "";
        let score = 0;
        if (beforeNeedle && beforeText.includes(beforeNeedle)) score += 2;
        if (afterNeedle && afterText.includes(afterNeedle)) score += 2;
        if (score > bestScore) {
          bestScore = score;
          bestMatch = match;
        }
      });
      return bestMatch;
    }
    function _findDocxReviewAnchorRange(root, item, layoutCache) {
      if (!root) return null;
      const reviewKey = String(item && (item.id || item.review_id || "") || "").replace(/^proposal:/, "").replace(/^comment:/, "").trim();
      if (reviewKey) {
        const exact = layoutCache && layoutCache.markerIndex instanceof Map ? (layoutCache.markerIndex.get(reviewKey) || [])[0] || null : Array.from(root.querySelectorAll("[data-koto-review-id]")).find((element) => {
          return String(element.getAttribute("data-koto-review-id") || "").trim() === reviewKey;
        }) || null;
        if (exact && exact.ownerDocument && exact.ownerDocument.createRange) {
          const range = exact.ownerDocument.createRange();
          range.selectNodeContents(exact);
          return range;
        }
      }
      const anchorText = _normalizeReviewSearchText(
        item && (item.anchor_text || item.original_text || item.text || "")
      );
      if (!anchorText) return null;
      const textIndex = layoutCache && typeof layoutCache.getTextIndex === "function" ? layoutCache.getTextIndex() : null;
      if (!textIndex || !textIndex.normalizedText) return null;
      const matches = _collectReviewTextMatches(textIndex.normalizedText, anchorText);
      if (!matches.length) return null;
      const selectedMatch = _selectReviewTextMatch(textIndex, matches, item);
      if (!selectedMatch) return null;
      return _rangeFromReviewTextIndex(textIndex, selectedMatch[0], selectedMatch[1]);
    }
    function _collectRangeClientRects(range) {
      if (!range || typeof range.getClientRects !== "function") return [];
      return Array.from(range.getClientRects()).filter((rect) => rect && (rect.width > 0.5 || rect.height > 0.5));
    }
    function _reviewHighlightRectsFromClientRects(rangeRects, layoutState) {
      if (!layoutState || !Array.isArray(rangeRects)) return [];
      return rangeRects.map((rect) => {
        const left = _screenXToReviewContentX(rect.left, layoutState);
        const right = _screenXToReviewContentX(rect.right, layoutState);
        const top = _screenYToReviewContentY(rect.top, layoutState);
        const bottom = _screenYToReviewContentY(rect.bottom, layoutState);
        return {
          left,
          top,
          width: Math.max(1, right - left),
          height: Math.max(2, bottom - top)
        };
      }).filter((rect) => rect.width > 0 && rect.height > 0);
    }
    function _screenXToReviewContentX(screenX, layoutState) {
      if (!layoutState || !layoutState.viewportRect) return Math.round(screenX || 0);
      const scale = layoutState.layoutScale && Number.isFinite(layoutState.layoutScale.x) ? layoutState.layoutScale.x : 1;
      return Math.round(layoutState.viewportScrollLeft + (screenX - layoutState.viewportRect.left) / scale);
    }
    function _screenYToReviewContentY(screenY, layoutState) {
      if (!layoutState || !layoutState.viewportRect) return Math.round(screenY || 0);
      const scale = layoutState.layoutScale && Number.isFinite(layoutState.layoutScale.y) ? layoutState.layoutScale.y : 1;
      return Math.round(layoutState.viewportScrollTop + (screenY - layoutState.viewportRect.top) / scale);
    }
    function _collectReviewVisualPageBounds(layoutState, root) {
      if (!layoutState || !layoutState.viewportRect) return [];
      const pageRoot = root && root.querySelectorAll ? root : layoutState.pageEl || $("wa-docx-editor")?.querySelector(".ProseMirror") || null;
      if (!pageRoot || typeof pageRoot.getBoundingClientRect !== "function") return [];
      if (layoutState._reviewVisualPageRoot === pageRoot && Array.isArray(layoutState._reviewVisualPageBounds)) {
        return layoutState._reviewVisualPageBounds;
      }
      const rootRect = pageRoot.getBoundingClientRect();
      if (!rootRect || rootRect.height <= 0) return [];
      const bounds = [];
      let currentTop = _screenYToReviewContentY(rootRect.top, layoutState);
      const breaks = Array.from(pageRoot.querySelectorAll(".koto-page-break")).map((breakEl) => {
        const rect = breakEl.getBoundingClientRect();
        if (!rect || rect.height <= 0) return null;
        const endEl = breakEl.querySelector(".koto-pb-end");
        const startEl = breakEl.querySelector(".koto-pb-start");
        const endRect = endEl ? endEl.getBoundingClientRect() : rect;
        const startRect = startEl ? startEl.getBoundingClientRect() : rect;
        return {
          top: rect.top,
          upperBottom: _screenYToReviewContentY(endRect.bottom, layoutState),
          nextTop: _screenYToReviewContentY(startRect.top, layoutState)
        };
      }).filter((b) => b !== null && b !== void 0).sort((a, b) => a.top - b.top);
      breaks.forEach((pageBreak) => {
        const upperBottom = Math.max(currentTop, pageBreak.upperBottom);
        if (upperBottom > currentTop + 8) {
          bounds.push({ top: currentTop, bottom: upperBottom });
        }
        currentTop = Math.max(upperBottom, pageBreak.nextTop);
      });
      const rootBottom = _screenYToReviewContentY(rootRect.bottom, layoutState);
      if (rootBottom > currentTop + 8) {
        bounds.push({ top: currentTop, bottom: rootBottom });
      }
      layoutState._reviewVisualPageRoot = pageRoot;
      layoutState._reviewVisualPageBounds = bounds;
      return bounds;
    }
    function _resolveReviewPageBoundsForScreenY(screenY, layoutState, root) {
      if (!layoutState || !layoutState.viewportRect) return null;
      const contentY = _screenYToReviewContentY(screenY, layoutState);
      const visualPages = _collectReviewVisualPageBounds(layoutState, root);
      if (visualPages.length) {
        const containingPage = visualPages.find((page) => contentY >= page.top && contentY <= page.bottom);
        if (containingPage) return containingPage;
        let nearest = null;
        let nearestDistance = Infinity;
        visualPages.forEach((page) => {
          const distance = contentY < page.top ? page.top - contentY : contentY > page.bottom ? contentY - page.bottom : 0;
          if (distance < nearestDistance) {
            nearestDistance = distance;
            nearest = page;
          }
        });
        if (nearest) return nearest;
      }
      const host = $("wa-docx-editor");
      const scopedRoot = root && root.querySelectorAll ? root : host;
      const pageCandidates = [];
      if (scopedRoot && scopedRoot.matches && scopedRoot.matches(".koto-doc-page, .ProseMirror")) {
        pageCandidates.push(scopedRoot);
      }
      if (scopedRoot && scopedRoot.querySelectorAll) {
        pageCandidates.push(...Array.from(scopedRoot.querySelectorAll(".koto-doc-page")));
      }
      if (!pageCandidates.length && layoutState.pageEl) {
        pageCandidates.push(layoutState.pageEl);
      }
      let bestPage = null;
      let bestDistance = Infinity;
      pageCandidates.forEach((pageEl) => {
        if (!pageEl || typeof pageEl.getBoundingClientRect !== "function") return;
        const rect = pageEl.getBoundingClientRect();
        if (!rect || rect.height <= 0) return;
        const distance = screenY < rect.top ? rect.top - screenY : screenY > rect.bottom ? screenY - rect.bottom : 0;
        if (distance < bestDistance) {
          bestDistance = distance;
          bestPage = { rect, pageEl };
        }
      });
      if (!bestPage || !bestPage.rect) return null;
      const top = _screenYToReviewContentY(bestPage.rect.top, layoutState);
      const bottom = _screenYToReviewContentY(bestPage.rect.bottom, layoutState);
      if (!Number.isFinite(top) || !Number.isFinite(bottom) || bottom <= top) return null;
      return { top, bottom, pageEl: bestPage.pageEl };
    }
    function _resolveReviewAnchorGeometry(root, item, layoutState, layoutCache) {
      if (!root || !layoutState || !layoutState.viewportRect) return null;
      const range = _findDocxReviewAnchorRange(root, item, layoutCache);
      const rangeRects = _collectRangeClientRects(range);
      if (rangeRects.length) {
        const lastRect = rangeRects[rangeRects.length - 1];
        const firstRect = rangeRects[0];
        const pageBounds2 = _resolveReviewPageBoundsForScreenY(
          lastRect.top + lastRect.height / 2,
          layoutState,
          root
        );
        return {
          pointX: _screenXToReviewContentX(lastRect.right, layoutState),
          pointY: _screenYToReviewContentY(lastRect.top + lastRect.height / 2, layoutState),
          top: _screenYToReviewContentY(firstRect.top, layoutState),
          bottom: _screenYToReviewContentY(lastRect.bottom, layoutState),
          pageTop: pageBounds2 ? pageBounds2.top : null,
          pageBottom: pageBounds2 ? pageBounds2.bottom : null,
          highlightRects: _reviewHighlightRectsFromClientRects(rangeRects, layoutState)
        };
      }
      const anchorEl = _findDocxReviewAnchorElement(item);
      const anchorRect = anchorEl ? anchorEl.getBoundingClientRect() : null;
      if (!anchorRect) return null;
      const pageBounds = _resolveReviewPageBoundsForScreenY(
        anchorRect.top + anchorRect.height / 2,
        layoutState,
        root
      );
      return {
        pointX: _screenXToReviewContentX(anchorRect.right, layoutState),
        pointY: _screenYToReviewContentY(anchorRect.top + anchorRect.height / 2, layoutState),
        top: _screenYToReviewContentY(anchorRect.top, layoutState),
        bottom: _screenYToReviewContentY(anchorRect.bottom, layoutState),
        pageTop: pageBounds ? pageBounds.top : null,
        pageBottom: pageBounds ? pageBounds.bottom : null,
        highlightRects: _reviewHighlightRectsFromClientRects([anchorRect], layoutState)
      };
    }
    function _getReviewContentRoot() {
      return document.querySelector("#wa-docx-editor .ProseMirror") || $("wa-editor-content") || null;
    }
    function _getRangeBoundingRect(range, rangeRects) {
      if (Array.isArray(rangeRects) && rangeRects.length) {
        const left = Math.min(...rangeRects.map((rect2) => rect2.left));
        const top = Math.min(...rangeRects.map((rect2) => rect2.top));
        const right = Math.max(...rangeRects.map((rect2) => rect2.right));
        const bottom = Math.max(...rangeRects.map((rect2) => rect2.bottom));
        return {
          left,
          top,
          right,
          bottom,
          width: Math.max(0, right - left),
          height: Math.max(0, bottom - top)
        };
      }
      if (!range || typeof range.getBoundingClientRect !== "function") return null;
      const rect = range.getBoundingClientRect();
      if (!rect || !rect.width && !rect.height) return null;
      return rect;
    }
    function _resolveReviewAnchorTarget(item) {
      const root = _getReviewContentRoot();
      if (!root) return null;
      let textIndex = null;
      const layoutCache = {
        markerIndex: _buildReviewMarkerIndex(root),
        getTextIndex() {
          if (!textIndex) textIndex = _buildReviewTextIndex(root);
          return textIndex;
        }
      };
      const range = _findDocxReviewAnchorRange(root, item, layoutCache);
      const rangeRects = _collectRangeClientRects(range);
      const rangeRect = _getRangeBoundingRect(range, rangeRects);
      if (rangeRect) {
        const container = range && range.commonAncestorContainer ? range.commonAncestorContainer.nodeType === 1 ? range.commonAncestorContainer : range.commonAncestorContainer.parentElement : null;
        return {
          element: container && container.nodeType === 1 ? container : null,
          rect: rangeRect,
          root
        };
      }
      const element = _findDocxReviewAnchorElement(item);
      if (!element || typeof element.getBoundingClientRect !== "function") return null;
      const rect = element.getBoundingClientRect();
      if (!rect || !rect.width && !rect.height) return null;
      return { element, rect, root };
    }
    function scrollReviewAnchorIntoView(item) {
      const viewport = $("wa-editor-content");
      const target = _resolveReviewAnchorTarget(item);
      if (!viewport || !target || !target.rect) return { found: false, element: null };
      const viewportRect = viewport.getBoundingClientRect();
      const rect = target.rect;
      const verticalMargin = Math.max(28, Math.round((viewport.clientHeight - Math.min(rect.height || 0, viewport.clientHeight)) * 0.4));
      const horizontalMargin = Math.max(36, Math.round(Math.min(120, viewport.clientWidth * 0.18)));
      const nextTop = Math.max(
        0,
        Math.round((viewport.scrollTop || 0) + (rect.top - viewportRect.top) - verticalMargin)
      );
      const nextLeft = Math.max(
        0,
        Math.round((viewport.scrollLeft || 0) + (rect.left - viewportRect.left) - horizontalMargin)
      );
      viewport.scrollTo({
        behavior: "smooth",
        left: nextLeft,
        top: nextTop
      });
      return {
        found: true,
        element: target.element || null,
        rect
      };
    }
    function _ensureReviewConnectorLayer(listEl) {
      if (!listEl) return null;
      let layer = listEl.querySelector(".wa-review-connector-layer");
      if (!layer) {
        layer = document.createElementNS(SVG_NS, "svg");
        layer.classList.add("wa-review-connector-layer");
        layer.setAttribute("aria-hidden", "true");
        listEl.insertBefore(layer, listEl.firstChild);
      }
      return layer;
    }
    function _ensureReviewAnchorHighlightLayer(listEl) {
      if (!listEl) return null;
      let layer = listEl.querySelector(".wa-review-anchor-highlight-layer");
      if (!layer) {
        layer = document.createElementNS(SVG_NS, "svg");
        layer.classList.add("wa-review-anchor-highlight-layer");
        layer.setAttribute("aria-hidden", "true");
        listEl.insertBefore(layer, listEl.firstChild);
      }
      return layer;
    }
    function _drawReviewConnector(layer, connector) {
      if (!layer || !connector) return;
      const path = document.createElementNS(SVG_NS, "path");
      const startX = Math.round(connector.startX);
      const startY = Math.round(connector.startY);
      const endX = Math.round(connector.endX);
      const endY = Math.round(connector.endY);
      path.setAttribute("d", `M ${startX} ${startY} L ${endX} ${endY}`);
      path.setAttribute("class", `wa-review-connector-path${connector.isProposal ? " is-proposal" : " is-comment"}${connector.isFocused ? " is-focused" : ""}`);
      layer.appendChild(path);
    }
    function _drawReviewAnchorHighlight(layer, highlight) {
      if (!layer || !highlight || !Array.isArray(highlight.rects)) return;
      highlight.rects.forEach((rect) => {
        if (!rect || rect.width <= 0 || rect.height <= 0) return;
        const node = document.createElementNS(SVG_NS, "rect");
        node.setAttribute("x", String(Math.round(rect.left)));
        node.setAttribute("y", String(Math.round(rect.top)));
        node.setAttribute("width", String(Math.max(1, Math.round(rect.width))));
        node.setAttribute("height", String(Math.max(2, Math.round(rect.height))));
        node.setAttribute("rx", "3");
        node.setAttribute("class", `wa-review-anchor-highlight-rect${highlight.isProposal ? " is-proposal" : " is-comment"}${highlight.isFocused ? " is-focused" : ""}`);
        layer.appendChild(node);
      });
    }
    return {
      scrollReviewAnchorIntoView,
      _ensureReviewConnectorLayer,
      _ensureReviewAnchorHighlightLayer,
      _drawReviewConnector,
      _drawReviewAnchorHighlight,
      _resolveReviewAnchorTarget,
      _resolveReviewAnchorGeometry,
      _buildReviewMarkerIndex,
      _buildReviewTextIndex,
      _getReviewContentRoot
    };
  }
  const DEFAULT_REVIEW_RAIL_LEFT_SHIFT = 0;
  const DEFAULT_REVIEW_RAIL_RIGHT_SHIFT = 0;
  function createDocxReviewLayout(deps) {
    const svg = createDocxReviewLayoutSvg(deps);
    const {
      state,
      $,
      _findReviewEntry,
      _findDocxReviewAnchorElement,
      _setDocxReviewRailWidth,
      _getReviewCommentSelectionState,
      _isReviewCommentModeEnabled,
      _isReviewEditorFocused,
      _getSelectionViewportBounds,
      _previewReviewText
    } = deps;
    function _reviewRailLeftShift(host) {
      if (!host || typeof window === "undefined" || typeof window.getComputedStyle !== "function") {
        return DEFAULT_REVIEW_RAIL_LEFT_SHIFT;
      }
      const raw = window.getComputedStyle(host).getPropertyValue("--wa-review-rail-left-shift");
      const parsed = parseFloat(raw);
      return Number.isFinite(parsed) ? Math.round(parsed) : DEFAULT_REVIEW_RAIL_LEFT_SHIFT;
    }
    function _reviewRailRightShift(host) {
      if (!host || typeof window === "undefined" || typeof window.getComputedStyle !== "function") {
        return DEFAULT_REVIEW_RAIL_RIGHT_SHIFT;
      }
      const raw = window.getComputedStyle(host).getPropertyValue("--wa-review-rail-right-shift");
      const parsed = parseFloat(raw);
      return Number.isFinite(parsed) ? Math.round(parsed) : DEFAULT_REVIEW_RAIL_RIGHT_SHIFT;
    }
    function _positionReviewRail(value, host) {
      const offset = _reviewRailRightShift(host) - _reviewRailLeftShift(host);
      return Math.max(0, Math.round(Number(value) || 0) + offset);
    }
    function _reviewAnchorHeight(anchorGeometry) {
      if (!anchorGeometry) return 0;
      const top = Number(anchorGeometry.top);
      const bottom = Number(anchorGeometry.bottom);
      if (!Number.isFinite(top) || !Number.isFinite(bottom) || bottom <= top) return 0;
      return Math.max(0, Math.round(bottom - top));
    }
    function _clampReviewConnectorOffsetY(anchorGeometry, cardHeight) {
      const measuredHeight = Math.max(0, Math.round(Number(cardHeight) || 0));
      const fallback = Math.min(16, Math.max(11, Math.round(measuredHeight * 0.3)));
      if (!anchorGeometry) return fallback;
      const anchorOffset = Math.round((Number(anchorGeometry.pointY) || 0) - (Number(anchorGeometry.top) || 0));
      if (!Number.isFinite(anchorOffset)) return fallback;
      const maxOffset = Math.max(11, measuredHeight - 10);
      return Math.max(11, Math.min(maxOffset, anchorOffset));
    }
    function _reviewLayoutEntryBottom(entry) {
      if (!entry) return 0;
      return entry.top + Math.max(entry.height || 0, entry.collisionHeight || 0);
    }
    function _resolveNonOverlappingCardTop(layoutEntries, desiredTop, desiredLeft, cardWidth, cardHeight, bounds, cardCollisionHeight) {
      const minTop = bounds && Number.isFinite(bounds.minTop) ? Math.max(0, Math.round(bounds.minTop)) : 0;
      const effectiveCardHeight = Math.max(
        0,
        Math.round(cardCollisionHeight || cardHeight || 0)
      );
      const maxTop = bounds && Number.isFinite(bounds.maxTop) ? Math.max(minTop, Math.round(bounds.maxTop) - effectiveCardHeight) : Infinity;
      const maxAnchorDrift = bounds && Number.isFinite(bounds.maxAnchorDrift) ? Math.max(0, Math.round(bounds.maxAnchorDrift)) : Infinity;
      let nextTop = Math.max(minTop, Math.round(desiredTop));
      let collided = true;
      let resolvedByCollision = false;
      while (collided) {
        collided = false;
        for (let index = 0; index < layoutEntries.length; index += 1) {
          const entry = layoutEntries[index];
          const horizontalOverlap = desiredLeft < entry.left + entry.width + 22 && desiredLeft + cardWidth + 22 > entry.left;
          const entryBottom = _reviewLayoutEntryBottom(entry);
          const verticalOverlap = nextTop < entryBottom + 10 && nextTop + effectiveCardHeight + 10 > entry.top;
          if (horizontalOverlap && verticalOverlap) {
            resolvedByCollision = true;
            nextTop = entryBottom + 10;
            if (nextTop > maxTop) {
              nextTop = maxTop;
              collided = false;
              break;
            }
            collided = true;
          }
        }
      }
      if (resolvedByCollision) {
        return Math.max(minTop, Math.min(nextTop, maxTop));
      }
      const driftMaxTop = Number.isFinite(maxAnchorDrift) && Number.isFinite(desiredTop) ? Math.max(minTop, Math.round(desiredTop) + maxAnchorDrift) : Infinity;
      return Math.max(minTop, Math.min(nextTop, maxTop, driftMaxTop));
    }
    function ensureReviewShellHost() {
      const shell = $("wa-review-shell");
      const docxEditor = $("wa-docx-editor");
      if (!shell || !docxEditor) return shell;
      if (shell.parentElement !== docxEditor) {
        docxEditor.appendChild(shell);
      }
      shell.classList.add("wa-review-shell-docx");
      return shell;
    }
    function getDocxReviewRailMetrics(host, viewport) {
      if (!host || !viewport) return null;
      if (window.KotoDocxReviewGeometry) {
        const geo = window.KotoDocxReviewGeometry.computeReviewGeometry(host, viewport);
        if (geo) {
          return Object.assign(geo, {
            edgeInset: 8,
            laneLeft: geo.cardColLeft,
            pageContentLeft: geo.scrollLeft,
            pageContentTop: geo.scrollTop,
            pageEdgeRight: geo.textColRight,
            pageOffsetHeight: geo.pageContentHeight,
            pageOffsetWidth: geo.pageRect ? Math.round(geo.pageRect.width) : 0,
            scaleX: geo.zoom ? geo.zoom.x : 1,
            scaleY: geo.zoom ? geo.zoom.y : 1,
            viewportScrollLeft: geo.scrollLeft,
            viewportScrollTop: geo.scrollTop,
            viewportRight: Number.isFinite(geo.viewportRight) ? geo.viewportRight : Math.round(geo.scrollLeft + (geo.viewportWidth || 0))
          });
        }
      }
      const hostRect = host.getBoundingClientRect();
      const viewportRect = viewport.getBoundingClientRect();
      const layoutScale2 = deps._reviewLayoutScale ? deps._reviewLayoutScale(viewport, viewportRect) : { x: 1, y: 1 };
      const viewportScrollLeft = Math.max(0, Math.round(viewport.scrollLeft || 0));
      const viewportScrollTop = Math.max(0, Math.round(viewport.scrollTop || 0));
      const pageEl = host.querySelector(".ProseMirror");
      const pageRect = pageEl ? pageEl.getBoundingClientRect() : null;
      const hostStyles = window.getComputedStyle(host);
      const minRailWidth = 220;
      const railGap = Math.max(6, Math.round(parseFloat(hostStyles.getPropertyValue("--wa-review-rail-gap")) || 6));
      const safeInset = 8;
      const railWidth = Math.max(
        minRailWidth,
        Math.round(
          parseFloat(hostStyles.getPropertyValue("--wa-review-rail-width")) || Math.max(220, Math.min(300, viewportRect.width * 0.24))
        )
      );
      if (!pageRect) {
        const contentWidth2 = Math.max(
          Math.round(viewport.scrollWidth || 0),
          Math.round((viewportRect.width || 0) / layoutScale2.x),
          Math.round(railWidth + railGap + 24)
        );
        const textColRight2 = Math.max(0, Math.round(contentWidth2 - railWidth - safeInset));
        _setDocxReviewRailWidth(host, railWidth);
        return {
          cardColLeft: textColRight2 + railGap + 10,
          contentWidth: contentWidth2,
          edgeInset: safeInset,
          hostRect,
          laneLeft: textColRight2,
          pageContentLeft: viewportScrollLeft,
          pageContentTop: viewportScrollTop,
          pageEdgeRight: textColRight2,
          pageEl: null,
          pageOffsetHeight: 0,
          pageOffsetWidth: 0,
          pageRect: null,
          railGap,
          railWidth,
          scaleX: 1,
          scaleY: 1,
          layoutScale: layoutScale2,
          shellLeft: Math.round((viewportRect.left - hostRect.left) / layoutScale2.x),
          shellTop: Math.round((viewportRect.top - hostRect.top) / layoutScale2.y),
          textColRight: textColRight2,
          viewportRect,
          viewportRight: Math.round(viewportScrollLeft + (viewportRect.width || 0) / layoutScale2.x),
          viewportWidth: Math.round((viewportRect.width || 0) / layoutScale2.x),
          viewportScrollLeft,
          viewportScrollTop,
          pageContentRight: 0,
          pagePaddingRight: 0
        };
      }
      const zoomWrapper = pageEl.closest(".koto-zoom-wrapper") || pageEl;
      const transformScale = _parseScaleFromTransform(
        zoomWrapper ? window.getComputedStyle(zoomWrapper).transform : ""
      ) || { x: 1, y: 1 };
      const pagePaddingRight = Math.max(0, parseFloat(window.getComputedStyle(pageEl).paddingRight) || 0);
      const pageContentLeft = Math.max(0, Math.round(viewportScrollLeft + (pageRect.left - viewportRect.left) / layoutScale2.x));
      const pageContentTop = Math.max(0, Math.round(viewportScrollTop + (pageRect.top - viewportRect.top) / layoutScale2.y));
      const pageContentRight = Math.round(viewportScrollLeft + (pageRect.right - viewportRect.left) / layoutScale2.x);
      const textColRight = Math.round(pageContentRight - pagePaddingRight * (transformScale.x || 1));
      const viewportRight = Math.round(viewportScrollLeft + (viewportRect.width || 0) / layoutScale2.x);
      const anchorGap = Math.max(6, railGap) + 10;
      const laneLeft = Math.round(textColRight + anchorGap);
      const contentWidth = Math.max(
        Math.round(viewport.scrollWidth || 0),
        Math.round((viewportRect.width || 0) / layoutScale2.x),
        Math.round(laneLeft + railWidth + safeInset)
      );
      _setDocxReviewRailWidth(host, railWidth);
      return {
        cardColLeft: laneLeft,
        contentWidth,
        edgeInset: safeInset,
        hostRect,
        laneLeft,
        pageContentLeft,
        pageContentTop,
        pageEdgeRight: pageContentRight,
        pageEl,
        pageOffsetHeight: Math.round((pageRect.height || 0) / layoutScale2.y),
        pageOffsetWidth: Math.round((pageRect.width || 0) / layoutScale2.x),
        pagePaddingRight: Math.round(pagePaddingRight || 0),
        pageRect,
        railGap,
        railWidth,
        scaleX: transformScale.x || 1,
        scaleY: transformScale.y || 1,
        layoutScale: layoutScale2,
        shellLeft: Math.round((viewportRect.left - hostRect.left) / layoutScale2.x),
        shellTop: Math.round((viewportRect.top - hostRect.top) / layoutScale2.y),
        textColRight,
        viewportRect,
        viewportRight,
        viewportWidth: Math.round((viewportRect.width || 0) / layoutScale2.x),
        viewportScrollLeft,
        viewportScrollTop,
        pageContentRight: 0
      };
    }
    function _parseScaleFromTransform(transformValue) {
      const value = String(transformValue || "").trim();
      if (!value || value === "none") return null;
      const m = value.match(/^matrix\(([^)]+)\)/);
      if (m) {
        const p = m[1].split(",").map(Number);
        if (p.length >= 4 && p.every(Number.isFinite)) {
          return { x: Math.hypot(p[0], p[1]) || 1, y: Math.hypot(p[2], p[3]) || 1 };
        }
      }
      return null;
    }
    function layoutReviewShellInDocx() {
      const shell = $("wa-review-shell");
      const host = $("wa-docx-editor");
      const viewport = $("wa-editor-content");
      const listEl = $("wa-review-list");
      if (!shell || !host || !viewport || !listEl || shell.style.display === "none") {
        if (host) host.classList.remove("has-review-shell");
        return;
      }
      const cards = Array.from(listEl.querySelectorAll(".koto-docx-comment-card, .wa-proposal-card"));
      if (!cards.length) {
        host.classList.remove("has-review-shell");
        return;
      }
      host.classList.add("has-review-shell");
      const railMetrics = getDocxReviewRailMetrics(host, viewport);
      const hostRect = railMetrics ? railMetrics.hostRect : host.getBoundingClientRect();
      const viewportRect = railMetrics ? railMetrics.viewportRect : viewport.getBoundingClientRect();
      const layoutScale2 = railMetrics && railMetrics.layoutScale ? railMetrics.layoutScale : { x: 1, y: 1 };
      const viewportWidth = Math.round(
        railMetrics && Number.isFinite(railMetrics.viewportWidth) ? railMetrics.viewportWidth : (viewportRect.width || viewport.clientWidth || 0) / layoutScale2.x
      );
      const viewportScrollTop = Math.max(0, Math.round(viewport.scrollTop || 0));
      const viewportScrollLeft = Math.max(0, Math.round(viewport.scrollLeft || 0));
      const shellTop = railMetrics && Number.isFinite(railMetrics.shellTop) ? Math.round(railMetrics.shellTop) : Math.round((viewportRect.top - hostRect.top) / layoutScale2.y);
      const viewportHeight = Math.round(
        viewport.clientHeight || (viewportRect.height || 0) / layoutScale2.y
      );
      if (railMetrics) {
        const shellLeft = Number.isFinite(railMetrics.shellLeft) ? Math.round(railMetrics.shellLeft) : Math.round((viewportRect.left - hostRect.left) / layoutScale2.x);
        shell.style.left = shellLeft + "px";
        shell.style.right = "auto";
        shell.style.width = Math.max(0, viewportWidth) + "px";
      }
      shell.style.top = shellTop + "px";
      shell.style.bottom = "auto";
      shell.style.height = viewportHeight + "px";
      listEl.style.transform = `translate(${-viewportScrollLeft}px, ${-viewportScrollTop}px)`;
      listEl.style.width = Math.max(160, Math.round(railMetrics && railMetrics.contentWidth || viewport.scrollWidth || viewportRect.width || 0)) + "px";
      const contentRoot = railMetrics && railMetrics.pageEl ? railMetrics.pageEl : host.querySelector(".ProseMirror") || host;
      let textIndex = null;
      const layoutCache = {
        markerIndex: svg._buildReviewMarkerIndex(contentRoot),
        getTextIndex() {
          if (!textIndex) textIndex = svg._buildReviewTextIndex(contentRoot);
          return textIndex;
        }
      };
      const highlightLayer = svg._ensureReviewAnchorHighlightLayer(listEl);
      if (highlightLayer) {
        highlightLayer.innerHTML = "";
        highlightLayer.setAttribute("width", String(Math.max(160, Math.round(railMetrics && railMetrics.contentWidth || viewport.scrollWidth || viewportRect.width || 0))));
      }
      const connectorLayer = svg._ensureReviewConnectorLayer(listEl);
      if (connectorLayer) {
        connectorLayer.innerHTML = "";
        connectorLayer.setAttribute("width", String(Math.max(160, Math.round(railMetrics && railMetrics.contentWidth || viewport.scrollWidth || viewportRect.width || 0))));
      }
      const rawCardColLeft = railMetrics ? Math.max(12, Math.round(railMetrics.cardColLeft || (railMetrics.textColRight || 0) + Math.max(6, railMetrics.railGap) + 10)) : 12;
      const cardColWidth = Math.max(
        railMetrics ? railMetrics.railWidth : 148,
        ...cards.map((card) => Math.round(card.offsetWidth || 0))
      );
      const desiredCardColLeft = Math.max(12, _positionReviewRail(rawCardColLeft, host));
      const viewportRight2 = railMetrics && Number.isFinite(railMetrics.viewportRight) ? Math.round(railMetrics.viewportRight) : Math.round(viewportScrollLeft + viewportWidth);
      const minCardColFromText = railMetrics && Number.isFinite(railMetrics.textColRight) ? Math.round(railMetrics.textColRight + Math.max(6, railMetrics.railGap || 12) + 4) : 12;
      const maxVisibleCardColLeft = Math.round(viewportRight2 - cardColWidth - 12);
      const cardColLeft = Math.max(
        12,
        minCardColFromText,
        Math.min(desiredCardColLeft, maxVisibleCardColLeft)
      );
      const connectorOriginX = railMetrics ? Math.round(railMetrics.textColRight || 0) : Math.max(0, cardColLeft - 20);
      const shellCoverWidth = Math.max(
        viewportWidth,
        railMetrics ? railMetrics.contentWidth || 0 : 0,
        cardColLeft + cardColWidth + 14
      );
      shell.style.width = Math.max(0, viewportWidth) + "px";
      shell.style.overflow = "hidden";
      listEl.style.width = Math.max(160, Math.round(shellCoverWidth)) + "px";
      if (connectorLayer) {
        connectorLayer.setAttribute("width", String(Math.max(160, Math.round(shellCoverWidth))));
      }
      const layoutEntries = [];
      const measuredCards = cards.map((card, index) => {
        const reviewId = String(card.dataset.reviewId || "").trim();
        const entry = _findReviewEntry(reviewId);
        const anchorGeometry = entry && entry.item ? svg._resolveReviewAnchorGeometry(contentRoot, entry.item, railMetrics, layoutCache) : null;
        card.style.left = cardColLeft + "px";
        card.style.right = "auto";
        card.classList.remove("is-page-bounded", "is-page-clamped");
        card.style.removeProperty("--wa-review-card-page-max-height");
        card.style.removeProperty("--wa-review-card-anchor-min-height");
        const pageBounds = anchorGeometry && Number.isFinite(anchorGeometry.pageTop) && Number.isFinite(anchorGeometry.pageBottom) && anchorGeometry.pageBottom > anchorGeometry.pageTop ? {
          minTop: Math.max(0, Math.round(anchorGeometry.pageTop + 6)),
          maxTop: Math.max(0, Math.round(anchorGeometry.pageBottom - 6)),
          maxAnchorDrift: 48
        } : null;
        const anchorHeight = _reviewAnchorHeight(anchorGeometry);
        const pageAvailableHeight = pageBounds ? Math.max(28, Math.round(pageBounds.maxTop - pageBounds.minTop)) : Infinity;
        if (anchorHeight > 0) {
          const isCommentCard = card.classList.contains("koto-docx-comment-card");
          const baseMinHeight = isCommentCard ? 72 : 54;
          const cs = window.getComputedStyle(card);
          const padV = Math.round((parseFloat(cs.paddingTop) || 0) + (parseFloat(cs.paddingBottom) || 0));
          const anchorMinHeight = Number.isFinite(pageAvailableHeight) ? Math.min(Math.max(0, anchorHeight - padV), pageAvailableHeight) : Math.max(0, anchorHeight - padV);
          const anchorHeightCap = isCommentCard ? 104 : 78;
          card.style.setProperty("--wa-review-card-anchor-min-height", `${Math.max(baseMinHeight, Math.min(anchorMinHeight, anchorHeightCap))}px`);
        }
        let cardHeight = card.offsetHeight || 32;
        if (pageBounds && Number.isFinite(pageAvailableHeight)) {
          card.classList.add("is-page-bounded");
          card.style.setProperty("--wa-review-card-page-max-height", `${Math.max(32, pageAvailableHeight)}px`);
          if (cardHeight > pageAvailableHeight) {
            card.classList.add("is-page-clamped");
            cardHeight = Math.max(32, pageAvailableHeight);
          }
        }
        const measuredCardWidth = Math.max(cardColWidth, card.offsetWidth || 148);
        const cardCollisionHeight = Math.max(cardHeight, anchorHeight);
        const connectorOffsetY = _clampReviewConnectorOffsetY(anchorGeometry, cardHeight);
        const desiredTop = anchorGeometry ? Math.max(
          pageBounds ? pageBounds.minTop : 0,
          Math.round(anchorGeometry.top - 2)
        ) : Infinity;
        return {
          anchorGeometry,
          card,
          cardCollisionHeight,
          cardHeight,
          cardWidth: measuredCardWidth,
          connectorOffsetY,
          desiredTop,
          index,
          pageBounds
        };
      }).sort((a, b) => {
        const pageA = a.pageBounds ? a.pageBounds.minTop : Number.MAX_SAFE_INTEGER;
        const pageB = b.pageBounds ? b.pageBounds.minTop : Number.MAX_SAFE_INTEGER;
        if (pageA !== pageB) return pageA - pageB;
        if (a.desiredTop !== b.desiredTop) return a.desiredTop - b.desiredTop;
        return a.index - b.index;
      });
      measuredCards.forEach((item) => {
        const fallbackTop = layoutEntries.length ? _reviewLayoutEntryBottom(layoutEntries[layoutEntries.length - 1]) + 10 : 0;
        const desiredTop = Number.isFinite(item.desiredTop) ? item.desiredTop : fallbackTop;
        const peerEntries = item.pageBounds ? layoutEntries.filter((entry) => entry.pageTop === item.pageBounds.minTop && entry.pageBottom === item.pageBounds.maxTop) : layoutEntries;
        const top = _resolveNonOverlappingCardTop(
          peerEntries,
          desiredTop,
          cardColLeft,
          item.cardWidth,
          item.cardHeight,
          item.pageBounds,
          item.cardCollisionHeight
        );
        item.card.style.top = top + "px";
        layoutEntries.push({
          collisionHeight: item.cardCollisionHeight,
          height: item.cardHeight,
          left: cardColLeft,
          pageBottom: item.pageBounds ? item.pageBounds.maxTop : null,
          pageTop: item.pageBounds ? item.pageBounds.minTop : null,
          top,
          width: item.cardWidth
        });
        if (highlightLayer && item.anchorGeometry) {
          svg._drawReviewAnchorHighlight(highlightLayer, {
            rects: item.anchorGeometry.highlightRects || [],
            isFocused: item.card.classList.contains("focused") || item.card.classList.contains("is-focused"),
            isProposal: item.card.classList.contains("wa-proposal-card")
          });
        }
        if (connectorLayer && item.anchorGeometry) {
          svg._drawReviewConnector(connectorLayer, {
            startX: connectorOriginX,
            startY: item.anchorGeometry.pointY,
            endX: cardColLeft - 4,
            endY: top + item.connectorOffsetY,
            isFocused: item.card.classList.contains("focused") || item.card.classList.contains("is-focused"),
            isProposal: item.card.classList.contains("wa-proposal-card")
          });
        }
      });
      const contentHeight = Math.max(
        Math.round(viewport.scrollHeight || 0),
        Math.round((railMetrics && railMetrics.pageContentTop || 0) + (railMetrics && railMetrics.pageOffsetHeight || 0)),
        layoutEntries.length ? Math.max(...layoutEntries.map((entry) => _reviewLayoutEntryBottom(entry))) + 24 : 0,
        160
      );
      listEl.style.minHeight = contentHeight + "px";
      if (highlightLayer) {
        highlightLayer.setAttribute("height", String(contentHeight));
        highlightLayer.setAttribute("viewBox", `0 0 ${Math.max(160, Math.round(shellCoverWidth))} ${contentHeight}`);
      }
      if (connectorLayer) {
        connectorLayer.setAttribute("height", String(contentHeight));
        connectorLayer.setAttribute("viewBox", `0 0 ${Math.max(160, Math.round(shellCoverWidth))} ${contentHeight}`);
      }
    }
    function scheduleReviewShellLayout() {
      requestAnimationFrame(() => {
        layoutReviewShellInDocx();
      });
    }
    function renderReviewSelectionLauncher() {
      const host = $("wa-docx-editor");
      const viewport = $("wa-editor-content");
      const launcher = ensureReviewSelectionLauncher();
      if (state.fileType !== "docx" || !host || !viewport || !launcher || !_isReviewCommentModeEnabled() || state._editingReviewCommentId || _isReviewEditorFocused()) {
        hideReviewSelectionLauncher();
        return;
      }
      const selectionState = _getReviewCommentSelectionState();
      const selection = selectionState && selectionState.selection;
      const bounds = _getSelectionViewportBounds();
      if (!selectionState.supported || !selection || !bounds) {
        hideReviewSelectionLauncher();
        return;
      }
      state._reviewLauncherVisible = true;
      syncDocxReviewRailHostClass();
      const railMetrics = getDocxReviewRailMetrics(host, viewport);
      const hostRect = railMetrics ? railMetrics.hostRect : host.getBoundingClientRect();
      const viewportRect = railMetrics ? railMetrics.viewportRect : viewport.getBoundingClientRect();
      const layoutScale2 = railMetrics && railMetrics.layoutScale ? railMetrics.layoutScale : { x: 1, y: 1 };
      const viewportHostLeft = Math.round((viewportRect.left - hostRect.left) / layoutScale2.x);
      const viewportHostTop = Math.round((viewportRect.top - hostRect.top) / layoutScale2.y);
      const viewportHostRight = viewportHostLeft + Math.round(
        railMetrics && Number.isFinite(railMetrics.viewportWidth) ? railMetrics.viewportWidth : (viewportRect.width || viewport.clientWidth || 0) / layoutScale2.x
      );
      const viewportHostBottom = viewportHostTop + Math.round(
        viewport.clientHeight || (viewportRect.height || 0) / layoutScale2.y
      );
      const shellTop = Math.max(0, viewportHostTop + 18);
      const maxTop = Math.max(shellTop, viewportHostBottom - 54);
      const top = Math.max(
        shellTop,
        Math.min(Math.round((bounds.top - hostRect.top) / layoutScale2.y) - 8, maxTop)
      );
      if (railMetrics) {
        let cursorRight = bounds.right;
        const _ws = window.getSelection();
        if (_ws && !_ws.isCollapsed && _ws.rangeCount > 0) {
          const _rects = _ws.getRangeAt(0).getClientRects();
          for (let _i = _rects.length - 1; _i >= 0; _i--) {
            const _r = _rects[_i];
            if (_r && _r.width > 0 && _r.height > 0) {
              cursorRight = _r.right;
              break;
            }
          }
        }
        const selectionRight = Number.isFinite(cursorRight) ? Math.round((cursorRight - hostRect.left) / layoutScale2.x) + Math.max(6, railMetrics.railGap || 12) : viewportHostRight - railMetrics.railWidth - 12;
        const maxLauncherLeft = Math.max(0, viewportHostRight - railMetrics.railWidth - 14);
        const launcherLeft = Math.min(selectionRight, maxLauncherLeft);
        launcher.style.left = launcherLeft + "px";
        launcher.style.right = "auto";
      }
      launcher.style.top = top + "px";
      launcher.style.display = "flex";
      const subtitle = launcher.querySelector(".wa-review-selection-subtitle");
      if (subtitle) {
        const label = String(selection.countLabel || "").trim() || `${String((selection.rawText || "").trim()).length}字`;
        const preview = _previewReviewText(selection.previewText || selection.rawText || "", 28);
        subtitle.textContent = preview ? `${label} · ${preview}` : label;
        subtitle.title = subtitle.textContent || "";
      }
      syncDocxReviewRailHostClass();
    }
    function ensureReviewShellViewportSync() {
      const viewport = $("wa-editor-content");
      if (viewport && !viewport._waReviewShellSyncBound) {
        viewport._waReviewShellSyncBound = true;
        viewport.addEventListener("scroll", () => {
          const shell = $("wa-review-shell");
          if (shell && shell.style.display !== "none") scheduleReviewShellLayout();
          renderReviewSelectionLauncher();
        }, { passive: true });
      }
      if (!window.__waReviewShellResizeBound) {
        window.__waReviewShellResizeBound = true;
        window.addEventListener("resize", () => {
          const shell = $("wa-review-shell");
          if (shell && shell.style.display !== "none") scheduleReviewShellLayout();
          renderReviewSelectionLauncher();
        });
      }
      const host = $("wa-docx-editor");
      if (host && !host._waReviewShellResizeObserved) {
        host._waReviewShellResizeObserved = true;
        const ro = new ResizeObserver(() => {
          const shell = $("wa-review-shell");
          if (shell && shell.style.display !== "none") scheduleReviewShellLayout();
          renderReviewSelectionLauncher();
        });
        ro.observe(host);
      }
    }
    function syncDocxReviewRailHostClass() {
      const host = $("wa-docx-editor");
      const shell = $("wa-review-shell");
      const listEl = $("wa-review-list");
      if (!host) return;
      const hasShellCards = !!(shell && shell.style.display !== "none" && listEl && listEl.children && listEl.children.length);
      host.classList.toggle("has-review-shell", hasShellCards || !!state._reviewLauncherVisible);
    }
    function ensureReviewSelectionLauncher() {
      const host = $("wa-docx-editor");
      if (!host) return null;
      let launcher = $("wa-review-selection-launcher");
      if (!launcher) {
        launcher = document.createElement("div");
        launcher.id = "wa-review-selection-launcher";
        launcher.setAttribute("aria-label", "为当前选区新建批注或修订");
        launcher.innerHTML = '<div class="wa-review-selection-box">  <span class="wa-review-selection-kicker" aria-hidden="true">    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 11h6"/><path d="M9 15h4"/><path d="M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4z"/></svg>  </span>  <span class="wa-review-selection-copy">    <span class="wa-review-selection-title">添加批注或修订</span>    <span class="wa-review-selection-subtitle"></span>  </span>  <span class="wa-review-selection-actions">    <button type="button" class="wa-review-selection-add" data-review-create="comment" title="像 Word 一样在当前选区添加批注">      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4z"/><path d="M8 10h8M8 14h5"/></svg><span>批注</span>    </button>    <button type="button" class="wa-review-selection-add wa-review-selection-revise" data-review-create="revision" title="把当前选区添加为修订建议">      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L8 18l-4 1 1-4Z"/></svg><span>修订</span>    </button>  </span></div>';
        launcher.addEventListener("mousedown", (event) => {
          if (event && typeof event.preventDefault === "function") event.preventDefault();
          if (event && typeof event.stopPropagation === "function") event.stopPropagation();
          window.WA.captureReviewSelection(event);
        });
        launcher.querySelectorAll(".wa-review-selection-add").forEach((button) => {
          button.addEventListener("mousedown", (event) => {
            if (event && typeof event.preventDefault === "function") event.preventDefault();
            if (event && typeof event.stopPropagation === "function") event.stopPropagation();
            window.WA.captureReviewSelection(event);
          });
          button.addEventListener("click", (event) => {
            if (event && typeof event.preventDefault === "function") event.preventDefault();
            if (event && typeof event.stopPropagation === "function") event.stopPropagation();
            const createMode = String(button.dataset.reviewCreate || "").trim();
            if (createMode === "revision" && window.WA && typeof window.WA.createReviewRevision === "function") {
              window.WA.createReviewRevision();
            } else if (window.WA && typeof window.WA.createReviewComment === "function") {
              window.WA.createReviewComment();
            }
          });
        });
        host.appendChild(launcher);
      }
      return launcher;
    }
    function hideReviewSelectionLauncher() {
      const launcher = $("wa-review-selection-launcher");
      state._reviewLauncherVisible = false;
      if (launcher) launcher.style.display = "none";
      syncDocxReviewRailHostClass();
    }
    return {
      ensureReviewShellHost,
      getDocxReviewRailMetrics,
      layoutReviewShellInDocx,
      scrollReviewAnchorIntoView: svg.scrollReviewAnchorIntoView,
      scheduleReviewShellLayout,
      ensureReviewShellViewportSync,
      syncDocxReviewRailHostClass,
      ensureReviewSelectionLauncher,
      hideReviewSelectionLauncher,
      renderReviewSelectionLauncher
    };
  }
  if (typeof window !== "undefined") {
    window.KotoDocxReviewLayout = { create: createDocxReviewLayout };
  }
  function cleanString(value) {
    return String(value == null ? "" : value).trim();
  }
  function cloneSerializable(value, fallback) {
    try {
      return JSON.parse(JSON.stringify(value));
    } catch (_) {
      return fallback;
    }
  }
  function makeId(prefix, index) {
    return `${prefix}-${Date.now().toString(36)}-${index}-${Math.random().toString(36).slice(2, 8)}`;
  }
  function createReviewState(deps) {
    const state = deps.state;
    const clone = typeof deps.cloneSerializable === "function" ? deps.cloneSerializable : cloneSerializable;
    function proposalKey(proposal) {
      const raw = cleanString(proposal && (proposal.id || proposal.review_id || proposal.proposal_id));
      return raw.replace(/^proposal:/, "");
    }
    function commentKey(comment) {
      const raw = cleanString(comment && (comment.id || comment.review_id || comment.comment_id));
      return raw.replace(/^comment:/, "");
    }
    function normalizeReviewComment(comment, index) {
      const raw = clone(comment, {}) || {};
      const id = commentKey(raw) || makeId("comment", index ?? 0);
      const normalized = Object.assign({}, raw, {
        id,
        review_id: cleanString(raw.review_id) || `comment:${id}`,
        author: cleanString(raw.author || raw.user || raw.initials) || "批注",
        initials: cleanString(raw.initials || raw.author).slice(0, 2),
        text: cleanString(raw.text || raw.content || raw.body || raw.comment),
        anchor_text: cleanString(raw.anchor_text || raw.anchorText || raw.quote || raw.selection_text || raw.original_text),
        date: cleanString(raw.date || raw.created_at || raw.createdAt || raw.time)
      });
      if (!normalized.date) normalized.date = (/* @__PURE__ */ new Date()).toISOString();
      return normalized;
    }
    function normalizeReviewProposal(proposal, index) {
      const raw = clone(proposal, {}) || {};
      const id = proposalKey(raw) || makeId("proposal", index ?? 0);
      const action = cleanString(raw.action || raw.action_type || raw.type) || "replace";
      const originalText = cleanString(raw.original_text || raw.anchor_text || raw.old_text || raw.from || raw.text);
      const proposedText = cleanString(raw.proposed_text || raw.replacement_text || raw.new_text || raw.value || raw.to);
      const normalized = Object.assign({}, raw, {
        id,
        review_id: cleanString(raw.review_id) || `proposal:${id}`,
        source: cleanString(raw.source) || "ai_proposal",
        action,
        action_type: cleanString(raw.action_type || action) || "replace",
        original_text: originalText,
        anchor_text: cleanString(raw.anchor_text || originalText),
        proposed_text: proposedText,
        rationale: cleanString(raw.rationale || raw.reason || raw.comment || raw.explanation),
        _reviewStatus: cleanString(raw._reviewStatus || raw.review_status || raw.status)
      });
      return normalized;
    }
    function ensureTabReviewState(tab) {
      if (!tab) return null;
      const existing = tab.reviewState && typeof tab.reviewState === "object" ? tab.reviewState : {};
      const serverData = tab.serverData && typeof tab.serverData === "object" ? tab.serverData : {};
      const existingComments = Array.isArray(existing.comments) ? existing.comments : [];
      const serverComments = Array.isArray(serverData.comments) ? serverData.comments : [];
      const existingProposals = Array.isArray(existing.proposals) ? existing.proposals : [];
      const serverProposals = Array.isArray(serverData.proposals) ? serverData.proposals : [];
      const rawComments = existingComments.length ? existingComments : serverComments;
      const rawProposals = existingProposals.length ? existingProposals : serverProposals;
      existing.comments = rawComments.map(normalizeReviewComment);
      existing.proposals = mergeReviewProposals([], rawProposals);
      existing.focusedId = cleanString(existing.focusedId);
      existing.expandedId = cleanString(existing.expandedId);
      tab.reviewState = existing;
      return existing;
    }
    function activeReviewTab() {
      const tabs = Array.isArray(state.openTabs) ? state.openTabs : [];
      const activePath = cleanString(state.activeTabPath || state.wsSourcePath);
      return tabs.find((tab) => tab && tab.path === activePath) || tabs.find((tab) => tab && tab.fileType === "docx" && (tab.path === state.wsSourcePath || tab.name === state.fileName)) || (state.fileType === "docx" ? tabs.find((tab) => tab && tab.fileType === "docx") ?? null : null) || null;
    }
    function setStoredReviewMode(mode) {
      const next = ["all", "comments", "proposals"].includes(mode) ? mode : "all";
      state._reviewMode = next;
      try {
        localStorage.setItem("wa_review_mode", next);
      } catch (_) {
      }
      return next;
    }
    function isReviewRailVisible() {
      return state.fileType === "docx" && state._reviewCenterOpen !== false;
    }
    function isReviewCommentModeEnabled() {
      return state.fileType === "docx" && state._reviewCenterOpen !== false && state._reviewMode === "comments";
    }
    function isResolvedReviewProposal(proposal) {
      const status = cleanString(proposal && (proposal._reviewStatus || proposal.status)).toLowerCase();
      return status === "accepted" || status === "rejected" || status === "resolved";
    }
    function visibleReviewProposals(reviewState) {
      return (reviewState && Array.isArray(reviewState.proposals) ? reviewState.proposals : []).filter((proposal) => proposal && (cleanString(proposal.id || proposal.review_id) || cleanString(proposal.original_text || proposal.anchor_text || proposal.proposed_text)));
    }
    function shouldShowDocxReviewMarkers(reviewState) {
      if (state.fileType !== "docx") return false;
      if (state._reviewCenterOpen !== false) return true;
      return !!(reviewState && (Array.isArray(reviewState.comments) && reviewState.comments.length || visibleReviewProposals(reviewState).length));
    }
    function focusFirstReviewEntry(reviewState, preferredKind = "") {
      if (!reviewState) return "";
      const wantsComments = preferredKind === "comment" || preferredKind === "comments";
      const wantsProposals = preferredKind === "proposal" || preferredKind === "proposals";
      let item = null;
      if (wantsComments) item = (reviewState.comments || [])[0] || null;
      if (!item && wantsProposals) item = visibleReviewProposals(reviewState)[0] || null;
      if (!item) item = (reviewState.comments || [])[0] || visibleReviewProposals(reviewState)[0] || null;
      const id = item ? cleanString(item.review_id || item.id) : "";
      reviewState.focusedId = id;
      if (id && id.indexOf("proposal:") === 0) reviewState.expandedId = id;
      return id;
    }
    function reviewModeHasVisibleEntries(reviewState, mode = state._reviewMode) {
      if (!reviewState) return false;
      const hasComments = Array.isArray(reviewState.comments) && reviewState.comments.length > 0;
      const hasProposals = visibleReviewProposals(reviewState).length > 0;
      if (mode === "comments") return hasComments;
      if (mode === "proposals") return hasProposals;
      return hasComments || hasProposals;
    }
    function coerceReviewModeForVisibleContent(reviewState, preferredKind = "") {
      if (!reviewState) return state._reviewMode;
      const hasComments = reviewModeHasVisibleEntries(reviewState, "comments");
      const hasProposals = reviewModeHasVisibleEntries(reviewState, "proposals");
      if ((preferredKind === "comment" || preferredKind === "comments") && hasComments) return setStoredReviewMode("comments");
      if ((preferredKind === "proposal" || preferredKind === "proposals") && hasProposals) return setStoredReviewMode("proposals");
      if (state._reviewMode === "comments" && !hasComments && hasProposals) return setStoredReviewMode("proposals");
      if (state._reviewMode === "proposals" && !hasProposals && hasComments) return setStoredReviewMode("comments");
      if (!reviewModeHasVisibleEntries(reviewState, state._reviewMode)) return setStoredReviewMode("all");
      return state._reviewMode;
    }
    function serializeReviewComment(comment) {
      const normalized = normalizeReviewComment(comment, 0);
      const out = clone(normalized, {}) || {};
      delete out.review_id;
      return out;
    }
    function syncDocCommentStateForActiveFile(nextComments) {
      const tab = activeReviewTab();
      const reviewState = ensureTabReviewState(tab);
      if (!reviewState) return [];
      if (Array.isArray(nextComments)) {
        reviewState.comments = nextComments.map(normalizeReviewComment);
      } else if (tab?.serverData && Array.isArray(tab.serverData.comments)) {
        reviewState.comments = tab.serverData.comments.map(normalizeReviewComment);
      }
      return reviewState.comments;
    }
    function mergeReviewProposals(existing, incoming) {
      const merged = [];
      const seen = /* @__PURE__ */ new Map();
      function add(item, index) {
        const normalized = normalizeReviewProposal(item, index);
        const key = proposalKey(normalized) || `${normalized.original_text}
${normalized.proposed_text}
${normalized.rationale}`;
        if (!key) return;
        if (seen.has(key)) {
          const existingIndex = seen.get(key);
          merged[existingIndex] = Object.assign({}, merged[existingIndex], normalized, {
            _reviewStatus: normalized._reviewStatus || merged[existingIndex]._reviewStatus
          });
          return;
        }
        seen.set(key, merged.length);
        merged.push(normalized);
      }
      (Array.isArray(existing) ? existing : []).forEach(add);
      (Array.isArray(incoming) ? incoming : []).forEach(add);
      return merged;
    }
    function syncProposalStateForActiveFile(proposals, options = {}) {
      const tab = activeReviewTab();
      const reviewState = ensureTabReviewState(tab);
      if (!reviewState) return [];
      const incoming = Array.isArray(proposals) ? proposals : [];
      reviewState.proposals = options.replace ? mergeReviewProposals([], incoming) : mergeReviewProposals(reviewState.proposals, incoming);
      if (tab?.serverData && typeof tab.serverData === "object") {
        tab.serverData.proposals = reviewState.proposals.map((proposal) => clone(proposal, {}) || {});
      }
      return reviewState.proposals;
    }
    return {
      activeReviewTab,
      coerceReviewModeForVisibleContent,
      ensureTabReviewState,
      focusFirstReviewEntry,
      isResolvedReviewProposal,
      isReviewCommentModeEnabled,
      isReviewRailVisible,
      mergeReviewProposals,
      normalizeReviewComment,
      normalizeReviewProposal,
      reviewModeHasVisibleEntries,
      serializeReviewComment,
      setStoredReviewMode,
      shouldShowDocxReviewMarkers,
      syncDocCommentStateForActiveFile,
      syncProposalStateForActiveFile,
      visibleReviewProposals
    };
  }
  window.KotoDocxReviewState = { create: createReviewState };
})();
//# sourceMappingURL=review-bundle.js.map
