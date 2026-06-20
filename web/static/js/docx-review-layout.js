(function () {
  'use strict';

  function create(deps) {
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
      _previewReviewText,
    } = deps;

    const SVG_NS = 'http://www.w3.org/2000/svg';
    const DEFAULT_REVIEW_RAIL_LEFT_SHIFT = 0;
    const DEFAULT_REVIEW_RAIL_RIGHT_SHIFT = 0;

    function _reviewLayoutScale(element, rect) {
      if (!element || !rect) return { x: 1, y: 1 };
      const width = Number(element.offsetWidth) || Number(element.clientWidth) || 0;
      const height = Number(element.offsetHeight) || Number(element.clientHeight) || 0;
      return {
        x: width > 0 ? Math.max(0.01, rect.width / width) : 1,
        y: height > 0 ? Math.max(0.01, rect.height / height) : 1,
      };
    }

    function _screenDeltaToLayout(delta, scale) {
      const safeScale = Number.isFinite(scale) && scale > 0.01 ? scale : 1;
      return Math.round((Number(delta) || 0) / safeScale);
    }

    function _reviewRailLeftShift(host) {
      if (!host || typeof window === 'undefined' || typeof window.getComputedStyle !== 'function') {
        return DEFAULT_REVIEW_RAIL_LEFT_SHIFT;
      }
      const raw = window.getComputedStyle(host).getPropertyValue('--wa-review-rail-left-shift');
      const parsed = parseFloat(raw);
      return Number.isFinite(parsed) ? Math.round(parsed) : DEFAULT_REVIEW_RAIL_LEFT_SHIFT;
    }

    function _shiftReviewRailLeft(value, host) {
      const left = Math.round(Number(value) || 0) - _reviewRailLeftShift(host);
      return Math.max(0, left);
    }

    function _reviewRailRightShift(host) {
      if (!host || typeof window === 'undefined' || typeof window.getComputedStyle !== 'function') {
        return DEFAULT_REVIEW_RAIL_RIGHT_SHIFT;
      }
      const raw = window.getComputedStyle(host).getPropertyValue('--wa-review-rail-right-shift');
      const parsed = parseFloat(raw);
      return Number.isFinite(parsed) ? Math.round(parsed) : DEFAULT_REVIEW_RAIL_RIGHT_SHIFT;
    }

    function _positionReviewRail(value, host) {
      const offset = _reviewRailRightShift(host) - _reviewRailLeftShift(host);
      return Math.max(0, Math.round(Number(value) || 0) + offset);
    }

    function _normalizeReviewSearchText(value) {
      return String(value || '').replace(/\s+/g, ' ').trim().toLowerCase();
    }

    function _buildReviewMarkerIndex(root) {
      const index = new Map();
      if (!root || !root.querySelectorAll) return index;
      root.querySelectorAll('[data-koto-review-id]').forEach((element) => {
        const key = String(element.getAttribute('data-koto-review-id') || '').trim();
        if (!key) return;
        if (!index.has(key)) index.set(key, []);
        index.get(key).push(element);
      });
      return index;
    }

    function _parseReviewScaleFromTransform(transformValue) {
      const value = String(transformValue || '').trim();
      if (!value || value === 'none') return null;
      const matrixMatch = value.match(/^matrix\(([^)]+)\)$/i);
      if (matrixMatch) {
        const parts = matrixMatch[1].split(',').map((part) => parseFloat(part.trim()));
        if (parts.length >= 4 && parts.every((part) => Number.isFinite(part))) {
          return {
            x: Math.hypot(parts[0], parts[1]) || 1,
            y: Math.hypot(parts[2], parts[3]) || 1,
          };
        }
      }
      const matrix3dMatch = value.match(/^matrix3d\(([^)]+)\)$/i);
      if (matrix3dMatch) {
        const parts = matrix3dMatch[1].split(',').map((part) => parseFloat(part.trim()));
        if (parts.length >= 16 && parts.every((part) => Number.isFinite(part))) {
          return {
            x: Math.hypot(parts[0], parts[1], parts[2]) || 1,
            y: Math.hypot(parts[4], parts[5], parts[6]) || 1,
          };
        }
      }
      const scaleMatch = value.match(/^scale(?:3d)?\(([^)]+)\)$/i);
      if (scaleMatch) {
        const parts = scaleMatch[1]
          .split(',')
          .map((part) => parseFloat(part.trim()))
          .filter((part) => Number.isFinite(part));
        if (parts.length) {
          return {
            x: parts[0] || 1,
            y: (parts[1] || parts[0]) || 1,
          };
        }
      }
      return null;
    }

    function _resolveReviewAxisScale(rectSpan, offsetSpan, fallbackScale) {
      const rectScale = Number(offsetSpan) > 0 ? (Number(rectSpan) / Number(offsetSpan)) : 0;
      if (Number.isFinite(rectScale) && rectScale > 0.01) return rectScale;
      if (Number.isFinite(fallbackScale) && fallbackScale > 0.01) return fallbackScale;
      return 1;
    }

    function _buildReviewTextIndex(root) {
      if (!root || !root.ownerDocument || !root.ownerDocument.createRange || typeof document.createTreeWalker !== 'function') {
        return null;
      }
      const walker = document.createTreeWalker(
        root,
        NodeFilter.SHOW_TEXT,
        {
          acceptNode(node) {
            return String(node && node.textContent || '').trim()
              ? NodeFilter.FILTER_ACCEPT
              : NodeFilter.FILTER_REJECT;
          },
        },
      );
      const normalizedMap = [];
      const rawPositions = [];
      let normalizedText = '';
      let rawIndex = 0;
      let previousWhitespace = false;
      let node = null;
      while ((node = walker.nextNode())) {
        const rawText = String(node.nodeValue || '');
        for (let index = 0; index < rawText.length; index += 1) {
          rawPositions[rawIndex] = { node, offset: index };
          const char = rawText[index];
          const normalizedChar = /\s/.test(char) ? ' ' : char.toLowerCase();
          if (normalizedChar === ' ') {
            if (!previousWhitespace) {
              normalizedText += ' ';
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
        const beforeText = beforeNeedle
          ? index.normalizedText.slice(Math.max(0, match[0] - beforeNeedle.length - 8), match[0])
          : '';
        const afterText = afterNeedle
          ? index.normalizedText.slice(match[1], match[1] + afterNeedle.length + 8)
          : '';
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
      const reviewKey = String(item && (item.id || item.review_id || '') || '')
        .replace(/^proposal:/, '')
        .replace(/^comment:/, '')
        .trim();
      if (reviewKey) {
        const exact = layoutCache && layoutCache.markerIndex instanceof Map
          ? ((layoutCache.markerIndex.get(reviewKey) || [])[0] || null)
          : (Array.from(root.querySelectorAll('[data-koto-review-id]')).find((element) => {
              return String(element.getAttribute('data-koto-review-id') || '').trim() === reviewKey;
            }) || null);
        if (exact && exact.ownerDocument && exact.ownerDocument.createRange) {
          const range = exact.ownerDocument.createRange();
          range.selectNodeContents(exact);
          return range;
        }
      }
      const anchorText = _normalizeReviewSearchText(
        item && (item.anchor_text || item.original_text || item.text || '')
      );
      if (!anchorText) return null;
      const textIndex = layoutCache && typeof layoutCache.getTextIndex === 'function'
        ? layoutCache.getTextIndex()
        : layoutCache;
      if (!textIndex || !textIndex.normalizedText) return null;
      const matches = _collectReviewTextMatches(textIndex.normalizedText, anchorText);
      if (!matches.length) return null;
      const selectedMatch = _selectReviewTextMatch(textIndex, matches, item);
      if (!selectedMatch) return null;
      return _rangeFromReviewTextIndex(textIndex, selectedMatch[0], selectedMatch[1]);
    }

    function _collectRangeClientRects(range) {
      if (!range || typeof range.getClientRects !== 'function') return [];
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
          height: Math.max(2, bottom - top),
        };
      }).filter((rect) => rect.width > 0 && rect.height > 0);
    }

    function _screenXToReviewContentX(screenX, layoutState) {
      if (!layoutState || !layoutState.viewportRect) return Math.round(screenX || 0);
      const scale = layoutState.layoutScale && Number.isFinite(layoutState.layoutScale.x)
        ? layoutState.layoutScale.x
        : 1;
      return Math.round(layoutState.viewportScrollLeft + ((screenX - layoutState.viewportRect.left) / scale));
    }

    function _screenYToReviewContentY(screenY, layoutState) {
      if (!layoutState || !layoutState.viewportRect) return Math.round(screenY || 0);
      const scale = layoutState.layoutScale && Number.isFinite(layoutState.layoutScale.y)
        ? layoutState.layoutScale.y
        : 1;
      return Math.round(layoutState.viewportScrollTop + ((screenY - layoutState.viewportRect.top) / scale));
    }

    function _collectReviewVisualPageBounds(layoutState, root) {
      if (!layoutState || !layoutState.viewportRect) return [];
      const pageRoot = root && root.querySelectorAll
        ? root
        : (layoutState.pageEl || $('wa-docx-editor')?.querySelector('.ProseMirror'));
      if (!pageRoot || typeof pageRoot.getBoundingClientRect !== 'function') return [];
      if (layoutState._reviewVisualPageRoot === pageRoot && Array.isArray(layoutState._reviewVisualPageBounds)) {
        return layoutState._reviewVisualPageBounds;
      }
      const rootRect = pageRoot.getBoundingClientRect();
      if (!rootRect || rootRect.height <= 0) return [];

      const bounds = [];
      let currentTop = _screenYToReviewContentY(rootRect.top, layoutState);
      const breaks = Array.from(pageRoot.querySelectorAll('.koto-page-break'))
        .map((breakEl) => {
          const rect = breakEl.getBoundingClientRect();
          if (!rect || rect.height <= 0) return null;
          const endEl = breakEl.querySelector('.koto-pb-end');
          const startEl = breakEl.querySelector('.koto-pb-start');
          const endRect = endEl ? endEl.getBoundingClientRect() : rect;
          const startRect = startEl ? startEl.getBoundingClientRect() : rect;
          return {
            top: rect.top,
            upperBottom: _screenYToReviewContentY(endRect.bottom, layoutState),
            nextTop: _screenYToReviewContentY(startRect.top, layoutState),
          };
        })
        .filter(Boolean)
        .sort((a, b) => a.top - b.top);

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
          const distance = contentY < page.top
            ? page.top - contentY
            : (contentY > page.bottom ? contentY - page.bottom : 0);
          if (distance < nearestDistance) {
            nearestDistance = distance;
            nearest = page;
          }
        });
        if (nearest) return nearest;
      }
      const host = $('wa-docx-editor');
      const scopedRoot = root && root.querySelectorAll ? root : host;
      const pageCandidates = [];
      if (scopedRoot && scopedRoot.matches && scopedRoot.matches('.koto-doc-page, .ProseMirror')) {
        pageCandidates.push(scopedRoot);
      }
      if (scopedRoot && scopedRoot.querySelectorAll) {
        pageCandidates.push(...Array.from(scopedRoot.querySelectorAll('.koto-doc-page')));
      }
      if (!pageCandidates.length && layoutState.pageEl) {
        pageCandidates.push(layoutState.pageEl);
      }
      let bestPage = null;
      let bestDistance = Infinity;
      pageCandidates.forEach((pageEl) => {
        if (!pageEl || typeof pageEl.getBoundingClientRect !== 'function') return;
        const rect = pageEl.getBoundingClientRect();
        if (!rect || rect.height <= 0) return;
        const distance = screenY < rect.top
          ? rect.top - screenY
          : (screenY > rect.bottom ? screenY - rect.bottom : 0);
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
        const pageBounds = _resolveReviewPageBoundsForScreenY(
          lastRect.top + (lastRect.height / 2),
          layoutState,
          root,
        );
        return {
          pointX: _screenXToReviewContentX(lastRect.right, layoutState),
          pointY: _screenYToReviewContentY(lastRect.top + (lastRect.height / 2), layoutState),
          top: _screenYToReviewContentY(firstRect.top, layoutState),
          bottom: _screenYToReviewContentY(lastRect.bottom, layoutState),
          pageTop: pageBounds ? pageBounds.top : null,
          pageBottom: pageBounds ? pageBounds.bottom : null,
          highlightRects: _reviewHighlightRectsFromClientRects(rangeRects, layoutState),
        };
      }
      const anchorEl = _findDocxReviewAnchorElement(item);
      const anchorRect = anchorEl ? anchorEl.getBoundingClientRect() : null;
      if (!anchorRect) return null;
      const pageBounds = _resolveReviewPageBoundsForScreenY(
        anchorRect.top + (anchorRect.height / 2),
        layoutState,
        root,
      );
      return {
        pointX: _screenXToReviewContentX(anchorRect.right, layoutState),
        pointY: _screenYToReviewContentY(anchorRect.top + (anchorRect.height / 2), layoutState),
        top: _screenYToReviewContentY(anchorRect.top, layoutState),
        bottom: _screenYToReviewContentY(anchorRect.bottom, layoutState),
        pageTop: pageBounds ? pageBounds.top : null,
        pageBottom: pageBounds ? pageBounds.bottom : null,
        highlightRects: _reviewHighlightRectsFromClientRects([anchorRect], layoutState),
      };
    }

    function _getReviewContentRoot() {
      return document.querySelector('#wa-docx-editor .ProseMirror')
        || $('wa-editor-content')
        || null;
    }

    function _getRangeBoundingRect(range, rangeRects) {
      if (Array.isArray(rangeRects) && rangeRects.length) {
        const left = Math.min(...rangeRects.map((rect) => rect.left));
        const top = Math.min(...rangeRects.map((rect) => rect.top));
        const right = Math.max(...rangeRects.map((rect) => rect.right));
        const bottom = Math.max(...rangeRects.map((rect) => rect.bottom));
        return {
          left,
          top,
          right,
          bottom,
          width: Math.max(0, right - left),
          height: Math.max(0, bottom - top),
        };
      }
      if (!range || typeof range.getBoundingClientRect !== 'function') return null;
      const rect = range.getBoundingClientRect();
      if (!rect || (!rect.width && !rect.height)) return null;
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
        },
      };
      const range = _findDocxReviewAnchorRange(root, item, layoutCache);
      const rangeRects = _collectRangeClientRects(range);
      const rangeRect = _getRangeBoundingRect(range, rangeRects);
      if (rangeRect) {
        const container = range && range.commonAncestorContainer
          ? (range.commonAncestorContainer.nodeType === 1
              ? range.commonAncestorContainer
              : range.commonAncestorContainer.parentElement)
          : null;
        return {
          element: container && container.nodeType === 1 ? container : null,
          rect: rangeRect,
          root,
        };
      }
      const element = _findDocxReviewAnchorElement(item);
      if (!element || typeof element.getBoundingClientRect !== 'function') return null;
      const rect = element.getBoundingClientRect();
      if (!rect || (!rect.width && !rect.height)) return null;
      return { element, rect, root };
    }

    function scrollReviewAnchorIntoView(item) {
      const viewport = $('wa-editor-content');
      const target = _resolveReviewAnchorTarget(item);
      if (!viewport || !target || !target.rect) return { found: false, element: null };
      const viewportRect = viewport.getBoundingClientRect();
      const rect = target.rect;
      const verticalMargin = Math.max(28, Math.round((viewport.clientHeight - Math.min(rect.height || 0, viewport.clientHeight)) * 0.4));
      const horizontalMargin = Math.max(36, Math.round(Math.min(120, viewport.clientWidth * 0.18)));
      const nextTop = Math.max(
        0,
        Math.round((viewport.scrollTop || 0) + (rect.top - viewportRect.top) - verticalMargin),
      );
      const nextLeft = Math.max(
        0,
        Math.round((viewport.scrollLeft || 0) + (rect.left - viewportRect.left) - horizontalMargin),
      );
      viewport.scrollTo({
        behavior: 'smooth',
        left: nextLeft,
        top: nextTop,
      });
      return {
        found: true,
        element: target.element || null,
        rect,
      };
    }

    function _ensureReviewConnectorLayer(listEl) {
      if (!listEl) return null;
      let layer = listEl.querySelector('.wa-review-connector-layer');
      if (!layer) {
        layer = document.createElementNS(SVG_NS, 'svg');
        layer.classList.add('wa-review-connector-layer');
        layer.setAttribute('aria-hidden', 'true');
        listEl.insertBefore(layer, listEl.firstChild);
      }
      return layer;
    }

    function _drawReviewConnector(layer, connector) {
      if (!layer || !connector) return;
      const path = document.createElementNS(SVG_NS, 'path');
      const startX = Math.round(connector.startX);
      const startY = Math.round(connector.startY);
      const endX = Math.round(connector.endX);
      const endY = Math.round(connector.endY);
      path.setAttribute('d', `M ${startX} ${startY} L ${endX} ${endY}`);
      path.setAttribute('class', `wa-review-connector-path${connector.isProposal ? ' is-proposal' : ' is-comment'}${connector.isFocused ? ' is-focused' : ''}`);
      layer.appendChild(path);
    }

    function _ensureReviewAnchorHighlightLayer(listEl) {
      if (!listEl) return null;
      let layer = listEl.querySelector('.wa-review-anchor-highlight-layer');
      if (!layer) {
        layer = document.createElementNS(SVG_NS, 'svg');
        layer.classList.add('wa-review-anchor-highlight-layer');
        layer.setAttribute('aria-hidden', 'true');
        listEl.insertBefore(layer, listEl.firstChild);
      }
      return layer;
    }

    function _drawReviewAnchorHighlight(layer, highlight) {
      if (!layer || !highlight || !Array.isArray(highlight.rects)) return;
      highlight.rects.forEach((rect) => {
        if (!rect || rect.width <= 0 || rect.height <= 0) return;
        const node = document.createElementNS(SVG_NS, 'rect');
        node.setAttribute('x', String(Math.round(rect.left)));
        node.setAttribute('y', String(Math.round(rect.top)));
        node.setAttribute('width', String(Math.max(1, Math.round(rect.width))));
        node.setAttribute('height', String(Math.max(2, Math.round(rect.height))));
        node.setAttribute('rx', '3');
        node.setAttribute('class', `wa-review-anchor-highlight-rect${highlight.isProposal ? ' is-proposal' : ' is-comment'}${highlight.isFocused ? ' is-focused' : ''}`);
        layer.appendChild(node);
      });
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
      const minTop = bounds && Number.isFinite(bounds.minTop)
        ? Math.max(0, Math.round(bounds.minTop))
        : 0;
      const effectiveCardHeight = Math.max(
        0,
        Math.round(cardCollisionHeight || cardHeight || 0),
      );
      const maxTop = bounds && Number.isFinite(bounds.maxTop)
        ? Math.max(minTop, Math.round(bounds.maxTop) - effectiveCardHeight)
        : Infinity;
      const maxAnchorDrift = bounds && Number.isFinite(bounds.maxAnchorDrift)
        ? Math.max(0, Math.round(bounds.maxAnchorDrift))
        : Infinity;
      let nextTop = Math.max(minTop, Math.round(desiredTop));
      let collided = true;
      let resolvedByCollision = false;
      while (collided) {
        collided = false;
        for (let index = 0; index < layoutEntries.length; index += 1) {
          const entry = layoutEntries[index];
          const horizontalOverlap = desiredLeft < entry.left + entry.width + 22
            && desiredLeft + cardWidth + 22 > entry.left;
          const entryBottom = _reviewLayoutEntryBottom(entry);
          const verticalOverlap = nextTop < entryBottom + 10
            && nextTop + effectiveCardHeight + 10 > entry.top;
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
      const driftMaxTop = Number.isFinite(maxAnchorDrift) && Number.isFinite(desiredTop)
        ? Math.max(minTop, Math.round(desiredTop) + maxAnchorDrift)
        : Infinity;
      return Math.max(minTop, Math.min(nextTop, maxTop, driftMaxTop));
    }

    function ensureReviewShellHost() {
      const shell = $('wa-review-shell');
      const docxEditor = $('wa-docx-editor');
      if (!shell || !docxEditor) return shell;
      if (shell.parentElement !== docxEditor) {
        docxEditor.appendChild(shell);
      }
      shell.classList.add('wa-review-shell-docx');
      return shell;
    }

    function getDocxReviewRailMetrics(host, viewport) {
      if (!host || !viewport) return null;
      // Use the geometry module when available (clean, no persistence).
      if (window.KotoDocxReviewGeometry) {
        const geo = window.KotoDocxReviewGeometry.computeReviewGeometry(host, viewport);
        if (geo) {
          // Expose legacy field names that workspace-assistant.js may read.
          return Object.assign(geo, {
            edgeInset:          8,
            laneLeft:           geo.cardColLeft,
            pageContentLeft:    geo.scrollLeft,
            pageContentTop:     geo.scrollTop,
            pageEdgeRight:      geo.textColRight,
            pageOffsetHeight:   geo.pageContentHeight,
            pageOffsetWidth:    geo.pageRect ? Math.round(geo.pageRect.width) : 0,
            scaleX:             geo.zoom ? geo.zoom.x : 1,
            scaleY:             geo.zoom ? geo.zoom.y : 1,
            viewportScrollLeft: geo.scrollLeft,
            viewportScrollTop:  geo.scrollTop,
            viewportRight:      Number.isFinite(geo.viewportRight)
              ? geo.viewportRight
              : Math.round(geo.scrollLeft + (geo.viewportWidth || 0)),
          });
        }
      }

      // Fallback: inline geometry (geometry module not yet loaded).
      const hostRect = host.getBoundingClientRect();
      const viewportRect = viewport.getBoundingClientRect();
      const layoutScale = _reviewLayoutScale(viewport, viewportRect);
      const viewportScrollLeft = Math.max(0, Math.round(viewport.scrollLeft || 0));
      const viewportScrollTop  = Math.max(0, Math.round(viewport.scrollTop  || 0));
      const pageEl   = host.querySelector('.ProseMirror');
      const pageRect = pageEl ? pageEl.getBoundingClientRect() : null;
      const hostStyles    = window.getComputedStyle(host);
      const minRailWidth  = 220;
      const railGap       = Math.max(6, Math.round(parseFloat(hostStyles.getPropertyValue('--wa-review-rail-gap')) || 6));
      const safeInset     = 8;
      // Rail width: read from CSS variable only (no stale dataset.noteWidth persistence).
      const railWidth = Math.max(
        minRailWidth,
        Math.round(
          parseFloat(hostStyles.getPropertyValue('--wa-review-rail-width')) ||
          Math.max(220, Math.min(300, viewportRect.width * 0.24))
        )
      );
      if (!pageRect) {
        const contentWidth = Math.max(
          Math.round(viewport.scrollWidth || 0),
          Math.round((viewportRect.width || 0) / layoutScale.x),
          Math.round(railWidth + railGap + 24),
        );
        const textColRight = Math.max(0, Math.round(contentWidth - railWidth - safeInset));
        _setDocxReviewRailWidth(host, railWidth);
        return {
          cardColLeft:        textColRight + railGap + 10,
          contentWidth,
          edgeInset:          safeInset,
          hostRect,
          laneLeft:           textColRight,
          pageContentLeft:    viewportScrollLeft,
          pageContentTop:     viewportScrollTop,
          pageEdgeRight:      textColRight,
          pageEl:             null,
          pageOffsetHeight:   0,
          pageOffsetWidth:    0,
          pageRect:           null,
          railGap,
          railWidth,
          scaleX:             1,
          scaleY:             1,
          layoutScale,
          shellLeft:          _screenDeltaToLayout(viewportRect.left - hostRect.left, layoutScale.x),
          shellTop:           _screenDeltaToLayout(viewportRect.top - hostRect.top, layoutScale.y),
          textColRight,
          viewportRect,
          viewportRight:      Math.round(viewportScrollLeft + ((viewportRect.width || 0) / layoutScale.x)),
          viewportWidth:      Math.round((viewportRect.width || 0) / layoutScale.x),
          viewportScrollLeft,
          viewportScrollTop,
        };
      }
      const transformScale = _parseReviewScaleFromTransform(
        window.getComputedStyle(pageEl.closest('.koto-zoom-wrapper') || pageEl).transform
      ) || { x: 1, y: 1 };
      const pagePaddingRight = Math.max(0, parseFloat(window.getComputedStyle(pageEl).paddingRight) || 0);
      const pageContentLeft  = Math.max(0, Math.round(viewportScrollLeft + ((pageRect.left - viewportRect.left) / layoutScale.x)));
      const pageContentTop   = Math.max(0, Math.round(viewportScrollTop  + ((pageRect.top  - viewportRect.top) / layoutScale.y)));
      const pageContentRight = Math.round(viewportScrollLeft + ((pageRect.right - viewportRect.left) / layoutScale.x));
      const textColRight     = Math.round(pageContentRight - (pagePaddingRight * (transformScale.x || 1)));
      const viewportRight    = Math.round(viewportScrollLeft + ((viewportRect.width || 0) / layoutScale.x));
      const anchorGap        = Math.max(6, railGap) + 10;
      const laneLeft         = Math.round(textColRight + anchorGap);
      const contentWidth = Math.max(
        Math.round(viewport.scrollWidth || 0),
        Math.round((viewportRect.width || 0) / layoutScale.x),
        Math.round(laneLeft + railWidth + safeInset),
      );
      _setDocxReviewRailWidth(host, railWidth);
      return {
        cardColLeft:      laneLeft,
        contentWidth,
        edgeInset:        safeInset,
        hostRect,
        laneLeft,
        pageContentLeft,
        pageContentTop,
        pageEdgeRight:    pageContentRight,
        pageEl,
        pageOffsetHeight: Math.round((pageRect.height || 0) / layoutScale.y),
        pageOffsetWidth:  Math.round((pageRect.width  || 0) / layoutScale.x),
        pagePaddingRight: Math.round(pagePaddingRight || 0),
        pageRect,
        railGap,
        railWidth,
        scaleX:           transformScale.x || 1,
        scaleY:           transformScale.y || 1,
        layoutScale,
        shellLeft:        _screenDeltaToLayout(viewportRect.left - hostRect.left, layoutScale.x),
        shellTop:         _screenDeltaToLayout(viewportRect.top - hostRect.top, layoutScale.y),
        textColRight,
        viewportRect,
        viewportRight,
        viewportWidth:    Math.round((viewportRect.width || 0) / layoutScale.x),
        viewportScrollLeft,
        viewportScrollTop,
      };
    }

    function layoutReviewShellInDocx() {
      const shell = $('wa-review-shell');
      const host = $('wa-docx-editor');
      const viewport = $('wa-editor-content');
      const listEl = $('wa-review-list');
      if (!shell || !host || !viewport || !listEl || shell.style.display === 'none') {
        if (host) host.classList.remove('has-review-shell');
        return;
      }
      const cards = Array.from(listEl.querySelectorAll('.koto-docx-comment-card, .wa-proposal-card'));
      if (!cards.length) {
        host.classList.remove('has-review-shell');
        return;
      }
      host.classList.add('has-review-shell');
      const railMetrics = getDocxReviewRailMetrics(host, viewport);
      const hostRect = railMetrics ? railMetrics.hostRect : host.getBoundingClientRect();
      const viewportRect = railMetrics ? railMetrics.viewportRect : viewport.getBoundingClientRect();
      const layoutScale = railMetrics && railMetrics.layoutScale
        ? railMetrics.layoutScale
        : _reviewLayoutScale(viewport, viewportRect);
      const viewportWidth = Math.round(
        (railMetrics && Number.isFinite(railMetrics.viewportWidth))
          ? railMetrics.viewportWidth
          : ((viewportRect.width || viewport.clientWidth || 0) / layoutScale.x)
      );
      const viewportScrollTop = Math.max(0, Math.round(viewport.scrollTop || 0));
      const viewportScrollLeft = Math.max(0, Math.round(viewport.scrollLeft || 0));
      const shellTop = railMetrics && Number.isFinite(railMetrics.shellTop)
        ? Math.round(railMetrics.shellTop)
        : _screenDeltaToLayout(viewportRect.top - hostRect.top, layoutScale.y);
      const viewportHeight = Math.round(
        viewport.clientHeight ||
        ((viewportRect.height || 0) / layoutScale.y)
      );
      if (railMetrics) {
        const shellLeft = Number.isFinite(railMetrics.shellLeft)
          ? Math.round(railMetrics.shellLeft)
          : _screenDeltaToLayout(viewportRect.left - hostRect.left, layoutScale.x);
        shell.style.left = shellLeft + 'px';
        shell.style.right = 'auto';
        shell.style.width = Math.max(0, viewportWidth) + 'px';
      }
      shell.style.top = shellTop + 'px';
      shell.style.bottom = 'auto';
      shell.style.height = viewportHeight + 'px';
      listEl.style.transform = `translate(${-viewportScrollLeft}px, ${-viewportScrollTop}px)`;
      listEl.style.width = Math.max(160, Math.round(railMetrics && railMetrics.contentWidth || viewport.scrollWidth || viewportRect.width || 0)) + 'px';
      const contentRoot = railMetrics && railMetrics.pageEl
        ? railMetrics.pageEl
        : (host.querySelector('.ProseMirror') || host);
      let textIndex = null;
      const layoutCache = {
        markerIndex: _buildReviewMarkerIndex(contentRoot),
        getTextIndex() {
          if (!textIndex) textIndex = _buildReviewTextIndex(contentRoot);
          return textIndex;
        },
      };
      const highlightLayer = _ensureReviewAnchorHighlightLayer(listEl);
      if (highlightLayer) {
        highlightLayer.innerHTML = '';
        highlightLayer.setAttribute('width', String(Math.max(160, Math.round(railMetrics && railMetrics.contentWidth || viewport.scrollWidth || viewportRect.width || 0))));
      }
      const connectorLayer = _ensureReviewConnectorLayer(listEl);
      if (connectorLayer) {
        connectorLayer.innerHTML = '';
        connectorLayer.setAttribute('width', String(Math.max(160, Math.round(railMetrics && railMetrics.contentWidth || viewport.scrollWidth || viewportRect.width || 0))));
      }
      // All cards share the same column: left edge = text-column right edge + gap.
      // This produces a clean WPS-style annotation rail where cards line up in a
      // column and each connector is a short line from the text-column edge to the card.
      // Use railGap + 10 to match the extra padding the CSS adds to #wa-editor-content.
      const rawCardColLeft = railMetrics
        ? Math.max(12, Math.round(railMetrics.cardColLeft || (railMetrics.textColRight || 0) + Math.max(6, railMetrics.railGap) + 10))
        : 12;
      const cardColWidth = Math.max(
        railMetrics ? railMetrics.railWidth : 148,
        ...cards.map((card) => Math.round(card.offsetWidth || 0)),
      );
      const desiredCardColLeft = Math.max(12, _positionReviewRail(rawCardColLeft, host));
      const viewportRight = railMetrics && Number.isFinite(railMetrics.viewportRight)
        ? Math.round(railMetrics.viewportRight)
        : Math.round(viewportScrollLeft + viewportWidth);
      // Anchor rail to the text-column right edge so cards never drift
      // leftward into the document when the viewport is narrow (e.g. wide AI panel).
      const minCardColFromText = railMetrics && Number.isFinite(railMetrics.textColRight)
        ? Math.round(railMetrics.textColRight + Math.max(6, railMetrics.railGap || 12) + 4)
        : 12;
      const maxVisibleCardColLeft = Math.round(viewportRight - cardColWidth - 12);
      const cardColLeft = Math.max(
        12,
        minCardColFromText,
        Math.min(desiredCardColLeft, maxVisibleCardColLeft),
      );
      const connectorOriginX = railMetrics
        ? Math.round(railMetrics.textColRight || 0)
        : Math.max(0, cardColLeft - 20);

      // Expand shell to cover the card column horizontally while still clipping
      // vertically to the editor viewport.
      const shellCoverWidth = Math.max(
        viewportWidth,
        railMetrics ? railMetrics.contentWidth || 0 : 0,
        cardColLeft + cardColWidth + 14
      );
      shell.style.width = Math.max(0, viewportWidth) + 'px';
      shell.style.overflow = 'hidden';
      listEl.style.width = Math.max(160, Math.round(shellCoverWidth)) + 'px';
      if (connectorLayer) {
        connectorLayer.setAttribute('width', String(Math.max(160, Math.round(shellCoverWidth))));
      }

      const layoutEntries = [];
      const measuredCards = cards.map((card, index) => {
        const reviewId = String(card.dataset.reviewId || '').trim();
        const entry = _findReviewEntry(reviewId);
        const anchorGeometry = entry && entry.item
          ? _resolveReviewAnchorGeometry(contentRoot, entry.item, railMetrics, layoutCache)
          : null;
        // All cards in the same column — never vary left by anchor X.
        card.style.left = cardColLeft + 'px';
        card.style.right = 'auto';
        card.classList.remove('is-page-bounded', 'is-page-clamped');
        card.style.removeProperty('--wa-review-card-page-max-height');
        card.style.removeProperty('--wa-review-card-anchor-min-height');
        const pageBounds = anchorGeometry
          && Number.isFinite(anchorGeometry.pageTop)
          && Number.isFinite(anchorGeometry.pageBottom)
          && anchorGeometry.pageBottom > anchorGeometry.pageTop
          ? {
              minTop: Math.max(0, Math.round(anchorGeometry.pageTop + 6)),
              maxTop: Math.max(0, Math.round(anchorGeometry.pageBottom - 6)),
              maxAnchorDrift: 48,
            }
          : null;
        const anchorHeight = _reviewAnchorHeight(anchorGeometry);
        const pageAvailableHeight = pageBounds
          ? Math.max(28, Math.round(pageBounds.maxTop - pageBounds.minTop))
          : Infinity;
        if (anchorHeight > 0) {
          const isCommentCard = card.classList.contains('koto-docx-comment-card');
          const baseMinHeight = isCommentCard ? 72 : 54;
          const cs = window.getComputedStyle(card);
          const padV = Math.round((parseFloat(cs.paddingTop) || 0) + (parseFloat(cs.paddingBottom) || 0));
          const anchorMinHeight = Number.isFinite(pageAvailableHeight)
            ? Math.min(Math.max(0, anchorHeight - padV), pageAvailableHeight)
            : Math.max(0, anchorHeight - padV);
          const anchorHeightCap = isCommentCard ? 104 : 78;
          card.style.setProperty('--wa-review-card-anchor-min-height', `${Math.max(baseMinHeight, Math.min(anchorMinHeight, anchorHeightCap))}px`);
        }
        let cardHeight = card.offsetHeight || 32;
        if (pageBounds && Number.isFinite(pageAvailableHeight)) {
          card.classList.add('is-page-bounded');
          card.style.setProperty('--wa-review-card-page-max-height', `${Math.max(32, pageAvailableHeight)}px`);
          if (cardHeight > pageAvailableHeight) {
            card.classList.add('is-page-clamped');
            cardHeight = Math.max(32, pageAvailableHeight);
          }
        }
        const cardWidth = Math.max(cardColWidth, card.offsetWidth || 148);
        const cardCollisionHeight = Math.max(cardHeight, anchorHeight);
        const connectorOffsetY = _clampReviewConnectorOffsetY(anchorGeometry, cardHeight);
        const desiredTop = anchorGeometry
          ? Math.max(
              pageBounds ? pageBounds.minTop : 0,
              Math.round(anchorGeometry.top - 2),
            )
          : Infinity;
        return {
          anchorGeometry,
          card,
          cardCollisionHeight,
          cardHeight,
          cardWidth,
          connectorOffsetY,
          desiredTop,
          index,
          pageBounds,
        };
      }).sort((a, b) => {
        const pageA = a.pageBounds ? a.pageBounds.minTop : Number.MAX_SAFE_INTEGER;
        const pageB = b.pageBounds ? b.pageBounds.minTop : Number.MAX_SAFE_INTEGER;
        if (pageA !== pageB) return pageA - pageB;
        if (a.desiredTop !== b.desiredTop) return a.desiredTop - b.desiredTop;
        return a.index - b.index;
      });

      measuredCards.forEach((item) => {
        const fallbackTop = layoutEntries.length
          ? _reviewLayoutEntryBottom(layoutEntries[layoutEntries.length - 1]) + 10
          : 0;
        const desiredTop = Number.isFinite(item.desiredTop) ? item.desiredTop : fallbackTop;
        const peerEntries = item.pageBounds
          ? layoutEntries.filter((entry) => (
              entry.pageTop === item.pageBounds.minTop
              && entry.pageBottom === item.pageBounds.maxTop
            ))
          : layoutEntries;
        const top = _resolveNonOverlappingCardTop(
          peerEntries,
          desiredTop,
          cardColLeft,
          item.cardWidth,
          item.cardHeight,
          item.pageBounds,
          item.cardCollisionHeight,
        );
        item.card.style.top = top + 'px';
        layoutEntries.push({
          collisionHeight: item.cardCollisionHeight,
          height: item.cardHeight,
          left: cardColLeft,
          pageBottom: item.pageBounds ? item.pageBounds.maxTop : null,
          pageTop: item.pageBounds ? item.pageBounds.minTop : null,
          top,
          width: item.cardWidth,
        });
        if (highlightLayer && item.anchorGeometry) {
          _drawReviewAnchorHighlight(highlightLayer, {
            rects: item.anchorGeometry.highlightRects || [],
            isFocused: item.card.classList.contains('focused') || item.card.classList.contains('is-focused'),
            isProposal: item.card.classList.contains('wa-proposal-card'),
          });
        }
        if (connectorLayer && item.anchorGeometry) {
          // Connector always starts from the fixed text-column right edge (connectorOriginX),
          // never from the annotated word's X. This prevents the line from spanning across
          // the page interior.
          _drawReviewConnector(connectorLayer, {
            startX: connectorOriginX,
            startY: item.anchorGeometry.pointY,
            endX: cardColLeft - 4,
            endY: top + item.connectorOffsetY,
            isFocused: item.card.classList.contains('focused') || item.card.classList.contains('is-focused'),
            isProposal: item.card.classList.contains('wa-proposal-card'),
          });
        }
      });
      const contentHeight = Math.max(
        Math.round(viewport.scrollHeight || 0),
        Math.round((railMetrics && railMetrics.pageContentTop || 0) + (railMetrics && railMetrics.pageOffsetHeight || 0)),
        layoutEntries.length
          ? (Math.max(...layoutEntries.map((entry) => _reviewLayoutEntryBottom(entry))) + 24)
          : 0,
        160,
      );
      listEl.style.minHeight = contentHeight + 'px';
      if (highlightLayer) {
        highlightLayer.setAttribute('height', String(contentHeight));
        highlightLayer.setAttribute('viewBox', `0 0 ${Math.max(160, Math.round(shellCoverWidth))} ${contentHeight}`);
      }
      if (connectorLayer) {
        connectorLayer.setAttribute('height', String(contentHeight));
        connectorLayer.setAttribute('viewBox', `0 0 ${Math.max(160, Math.round(shellCoverWidth))} ${contentHeight}`);
      }
    }

    function scheduleReviewShellLayout() {
      requestAnimationFrame(() => {
        layoutReviewShellInDocx();
      });
    }

    function renderReviewSelectionLauncher() {
      const host = $('wa-docx-editor');
      const viewport = $('wa-editor-content');
      const launcher = ensureReviewSelectionLauncher();
      if (
        state.fileType !== 'docx'
        || !host
        || !viewport
        || !launcher
        || !_isReviewCommentModeEnabled()
        || state._editingReviewCommentId
        || _isReviewEditorFocused()
      ) {
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
      const layoutScale = railMetrics && railMetrics.layoutScale
        ? railMetrics.layoutScale
        : _reviewLayoutScale(viewport, viewportRect);
      const viewportHostLeft = _screenDeltaToLayout(viewportRect.left - hostRect.left, layoutScale.x);
      const viewportHostTop = _screenDeltaToLayout(viewportRect.top - hostRect.top, layoutScale.y);
      const viewportHostRight = viewportHostLeft + Math.round(
        (railMetrics && Number.isFinite(railMetrics.viewportWidth))
          ? railMetrics.viewportWidth
          : ((viewportRect.width || viewport.clientWidth || 0) / layoutScale.x)
      );
      const viewportHostBottom = viewportHostTop + Math.round(
        viewport.clientHeight ||
        ((viewportRect.height || 0) / layoutScale.y)
      );
      const shellTop = Math.max(0, viewportHostTop + 18);
      const maxTop = Math.max(shellTop, viewportHostBottom - 54);
      const top = Math.max(
        shellTop,
        Math.min(_screenDeltaToLayout(bounds.top - hostRect.top, layoutScale.y) - 8, maxTop),
      );
      if (railMetrics) {
        // Use the selection end rect (cursor position) instead of the rightmost
        // bounding edge across all line fragments — this places the launcher
        // where the mouse was released, not at the widest line.
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
        const selectionRight = Number.isFinite(cursorRight)
          ? _screenDeltaToLayout(cursorRight - hostRect.left, layoutScale.x) + Math.max(6, railMetrics.railGap || 12)
          : viewportHostRight - railMetrics.railWidth - 12;
        const maxLauncherLeft = Math.max(0, viewportHostRight - railMetrics.railWidth - 14);
        const launcherLeft = Math.min(selectionRight, maxLauncherLeft);
        launcher.style.left = launcherLeft + 'px';
        launcher.style.right = 'auto';
      }
      launcher.style.top = top + 'px';
      launcher.style.display = 'flex';
      const subtitle = launcher.querySelector('.wa-review-selection-subtitle');
      if (subtitle) {
        const label = String(selection.countLabel || '').trim() || `${String(selection.rawText || '').trim().length}字`;
        const preview = _previewReviewText(selection.previewText || selection.rawText || '', 28);
        subtitle.textContent = preview ? `${label} · ${preview}` : label;
        subtitle.title = subtitle.textContent;
      }
      syncDocxReviewRailHostClass();
    }

    function ensureReviewShellViewportSync() {
      const viewport = $('wa-editor-content');
      if (viewport && !viewport._waReviewShellSyncBound) {
        viewport._waReviewShellSyncBound = true;
        viewport.addEventListener('scroll', () => {
          const shell = $('wa-review-shell');
          if (shell && shell.style.display !== 'none') scheduleReviewShellLayout();
          renderReviewSelectionLauncher();
        }, { passive: true });
      }
      if (!window.__waReviewShellResizeBound) {
        window.__waReviewShellResizeBound = true;
        window.addEventListener('resize', () => {
          const shell = $('wa-review-shell');
          if (shell && shell.style.display !== 'none') scheduleReviewShellLayout();
          renderReviewSelectionLauncher();
        });
      }
      const host = $('wa-docx-editor');
      if (host && !host._waReviewShellResizeObserved) {
        host._waReviewShellResizeObserved = true;
        var ro = new ResizeObserver(function () {
          var shell = $('wa-review-shell');
          if (shell && shell.style.display !== 'none') scheduleReviewShellLayout();
          renderReviewSelectionLauncher();
        });
        ro.observe(host);
      }
    }

    function syncDocxReviewRailHostClass() {
      const host = $('wa-docx-editor');
      const shell = $('wa-review-shell');
      const listEl = $('wa-review-list');
      if (!host) return;
      const hasShellCards = !!(
        shell &&
        shell.style.display !== 'none' &&
        listEl &&
        listEl.children &&
        listEl.children.length
      );
      host.classList.toggle('has-review-shell', hasShellCards || !!state._reviewLauncherVisible);
    }

    function ensureReviewSelectionLauncher() {
      const host = $('wa-docx-editor');
      if (!host) return null;
      let launcher = $('wa-review-selection-launcher');
      if (!launcher) {
        launcher = document.createElement('div');
        launcher.id = 'wa-review-selection-launcher';
        launcher.setAttribute('aria-label', '为当前选区新建批注或修订');
        launcher.innerHTML = ''
          + '<div class="wa-review-selection-box">'
          + '  <span class="wa-review-selection-kicker" aria-hidden="true">'
          + '    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 11h6"/><path d="M9 15h4"/><path d="M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4z"/></svg>'
          + '  </span>'
          + '  <span class="wa-review-selection-copy">'
          + '    <span class="wa-review-selection-title">添加批注或修订</span>'
          + '    <span class="wa-review-selection-subtitle"></span>'
          + '  </span>'
          + '  <span class="wa-review-selection-actions">'
          + '    <button type="button" class="wa-review-selection-add" data-review-create="comment" title="像 Word 一样在当前选区添加批注">'
          + '      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4z"/><path d="M8 10h8M8 14h5"/></svg><span>批注</span>'
          + '    </button>'
          + '    <button type="button" class="wa-review-selection-add wa-review-selection-revise" data-review-create="revision" title="把当前选区添加为修订建议">'
          + '      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L8 18l-4 1 1-4Z"/></svg><span>修订</span>'
          + '    </button>'
          + '  </span>'
          + '</div>';
        launcher.addEventListener('mousedown', (event) => {
          if (event && typeof event.preventDefault === 'function') event.preventDefault();
          if (event && typeof event.stopPropagation === 'function') event.stopPropagation();
          window.WA.captureReviewSelection(event);
        });
        launcher.querySelectorAll('.wa-review-selection-add').forEach((button) => {
          button.addEventListener('mousedown', (event) => {
            if (event && typeof event.preventDefault === 'function') event.preventDefault();
            if (event && typeof event.stopPropagation === 'function') event.stopPropagation();
            window.WA.captureReviewSelection(event);
          });
          button.addEventListener('click', (event) => {
            if (event && typeof event.preventDefault === 'function') event.preventDefault();
            if (event && typeof event.stopPropagation === 'function') event.stopPropagation();
            const createMode = String(button.dataset.reviewCreate || '').trim();
            if (createMode === 'revision' && window.WA && typeof window.WA.createReviewRevision === 'function') {
              window.WA.createReviewRevision();
            } else if (window.WA && typeof window.WA.createReviewComment === 'function') {
              window.WA.createReviewComment();
            }
          });
        });
        host.appendChild(launcher);
      }
      return launcher;
    }

    function hideReviewSelectionLauncher() {
      const launcher = $('wa-review-selection-launcher');
      state._reviewLauncherVisible = false;
      if (launcher) launcher.style.display = 'none';
      syncDocxReviewRailHostClass();
    }

    return {
      ensureReviewShellHost,
      getDocxReviewRailMetrics,
      layoutReviewShellInDocx,
      scrollReviewAnchorIntoView,
      scheduleReviewShellLayout,
      ensureReviewShellViewportSync,
      syncDocxReviewRailHostClass,
      ensureReviewSelectionLauncher,
      hideReviewSelectionLauncher,
      renderReviewSelectionLauncher,
    };
  }

  window.KotoDocxReviewLayout = { create };
})();
