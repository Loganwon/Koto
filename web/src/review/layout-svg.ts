/**
 * Review SVG connectors, anchor resolution, and text indexing for DOCX review.
 * Pure geometry helper functions; no card-positioning logic.
 */
const SVG_NS = 'http://www.w3.org/2000/svg';

export interface ZoomScale {
  x: number;
  y: number;
}

export interface LayoutScale {
  x: number;
  y: number;
}

export interface PageBounds {
  top: number;
  bottom: number;
  pageEl?: HTMLElement;
}

export interface AnchorGeometry {
  pointX: number;
  pointY: number;
  top: number;
  bottom: number;
  pageTop: number | null;
  pageBottom: number | null;
  highlightRects: AnchorHighlightRect[];
}

export interface AnchorHighlightRect {
  left: number;
  top: number;
  width: number;
  height: number;
}

export interface AnchorTarget {
  element: HTMLElement | null;
  rect: DOMRect;
  root: HTMLElement;
}

export interface ConnectorSpec {
  startX: number;
  startY: number;
  endX: number;
  endY: number;
  isFocused: boolean;
  isProposal: boolean;
}

export interface AnchorHighlightSpec {
  rects: AnchorHighlightRect[];
  isFocused: boolean;
  isProposal: boolean;
}

export interface TextIndex {
  normalizedMap: number[];
  normalizedText: string;
  rawPositions: Array<{ node: Node; offset: number }>;
}

export interface ReviewEntry {
  item: any;
  id: string;
}

export interface LayoutCache {
  markerIndex: Map<string, HTMLElement[]>;
  getTextIndex(): TextIndex | null;
}

export interface RailMetrics {
  hostRect: DOMRect;
  viewportRect: DOMRect;
  layoutScale: LayoutScale;
  viewportWidth: number;
  viewportRight: number;
  cardColLeft: number;
  textColRight: number;
  railGap: number;
  railWidth: number;
  contentWidth: number;
  pageContentLeft: number;
  pageContentTop: number;
  pageRect: DOMRect | null;
  pageEl: HTMLElement | null;
  pageOffsetHeight: number;
  pageOffsetWidth: number;
  pagePaddingRight: number;
  shellLeft: number;
  shellTop: number;
  viewportScrollLeft: number;
  viewportScrollTop: number;
  scaleX: number;
  scaleY: number;
  edgeInset: number;
  laneLeft: number;
  pageContentRight: number;
  pageEdgeRight: number;
  [key: string]: any;
}

export interface LayoutState extends RailMetrics {
  [key: string]: any;
}

export interface ReviewLayoutDeps {
  state: {
    fileType?: string;
    _editingReviewCommentId?: string;
    _reviewLauncherVisible?: boolean;
    [key: string]: any;
  };
  $: (id: string) => HTMLElement | null;
  _findReviewEntry: (reviewId: string) => ReviewEntry | null | undefined;
  _findDocxReviewAnchorElement: (item: any) => HTMLElement | null;
  _setDocxReviewRailWidth: (host: HTMLElement, width: number) => void;
  _getReviewCommentSelectionState: () => any;
  _isReviewCommentModeEnabled: () => boolean;
  _isReviewEditorFocused: () => boolean;
  _getSelectionViewportBounds: () => any;
  _previewReviewText: (text: string, maxLength: number) => string;
  captureReviewSelection: (event?: Event) => any;
  createReviewComment: () => void;
  createReviewRevision: () => void;
}

export interface ReviewSvgApi {
  scrollReviewAnchorIntoView: (item: any) => { found: boolean; element: HTMLElement | null; rect?: DOMRect };
  _ensureReviewConnectorLayer: (listEl: HTMLElement) => SVGElement | null;
  _ensureReviewAnchorHighlightLayer: (listEl: HTMLElement) => SVGElement | null;
  _drawReviewConnector: (layer: SVGElement, connector: ConnectorSpec) => void;
  _drawReviewAnchorHighlight: (layer: SVGElement, highlight: AnchorHighlightSpec) => void;
  _resolveReviewAnchorTarget: (item: any) => AnchorTarget | null;
  _resolveReviewAnchorGeometry: (root: HTMLElement, item: any, layoutState: LayoutState, layoutCache: LayoutCache) => AnchorGeometry | null;
  _buildReviewMarkerIndex: (root: HTMLElement) => Map<string, HTMLElement[]>;
  _buildReviewTextIndex: (root: HTMLElement) => TextIndex | null;
  _getReviewContentRoot: () => HTMLElement | null;
}

export function createDocxReviewLayoutSvg(deps: ReviewLayoutDeps): ReviewSvgApi {
  const {
    state,
    $,
    _findReviewEntry,
    _findDocxReviewAnchorElement,
    _getReviewCommentSelectionState,
  } = deps;

  function _reviewLayoutScale(element: HTMLElement | null, rect: DOMRect | null): LayoutScale {
    if (!element || !rect) return { x: 1, y: 1 };
    const width = Number(element.offsetWidth) || Number(element.clientWidth) || 0;
    const height = Number(element.offsetHeight) || Number(element.clientHeight) || 0;
    return {
      x: width > 0 ? Math.max(0.01, rect.width / width) : 1,
      y: height > 0 ? Math.max(0.01, rect.height / height) : 1,
    };
  }

  function _screenDeltaToLayout(delta: number, scale: number): number {
    const safeScale = Number.isFinite(scale) && scale > 0.01 ? scale : 1;
    return Math.round((Number(delta) || 0) / safeScale);
  }

  function _normalizeReviewSearchText(value: unknown): string {
    return String(value || '').replace(/\s+/g, ' ').trim().toLowerCase();
  }

  function _buildReviewMarkerIndex(root: HTMLElement): Map<string, HTMLElement[]> {
    const index = new Map<string, HTMLElement[]>();
    if (!root || !root.querySelectorAll) return index;
    root.querySelectorAll('[data-koto-review-id]').forEach((element) => {
      const key = String(element.getAttribute('data-koto-review-id') || '').trim();
      if (!key) return;
      if (!index.has(key)) index.set(key, []);
      index.get(key)!.push(element as HTMLElement);
    });
    return index;
  }

  function _parseReviewScaleFromTransform(transformValue: string): ZoomScale | null {
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

  function _buildReviewTextIndex(root: HTMLElement): TextIndex | null {
    if (!root || !root.ownerDocument || !root.ownerDocument.createRange || typeof document.createTreeWalker !== 'function') {
      return null;
    }
    const walker = document.createTreeWalker(
      root,
      NodeFilter.SHOW_TEXT,
      {
        acceptNode(node) {
          return String((node as Text).textContent || '').trim()
            ? NodeFilter.FILTER_ACCEPT
            : NodeFilter.FILTER_REJECT;
        },
      },
    );
    const normalizedMap: number[] = [];
    const rawPositions: Array<{ node: Node; offset: number }> = [];
    let normalizedText = '';
    let rawIndex = 0;
    let previousWhitespace = false;
    let node: Node | null;
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

  function _rangeFromReviewTextIndex(index: TextIndex, normalizedStart: number, normalizedEnd: number): Range | null {
    if (!index || normalizedEnd <= normalizedStart) return null;
    const startRawIndex = index.normalizedMap[normalizedStart];
    const endRawIndex = index.normalizedMap[normalizedEnd - 1];
    const startPos = index.rawPositions[startRawIndex];
    const endPos = index.rawPositions[endRawIndex];
    if (!startPos || !endPos || !startPos.node || !endPos.node) return null;
    const range = (startPos.node as Text).ownerDocument!.createRange();
    range.setStart(startPos.node, startPos.offset);
    range.setEnd(endPos.node, endPos.offset + 1);
    return range;
  }

  function _collectReviewTextMatches(haystack: string, needle: string): Array<[number, number]> {
    const matches: Array<[number, number]> = [];
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

  function _selectReviewTextMatch(index: TextIndex, matches: Array<[number, number]>, item: any): [number, number] | null {
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

  function _findDocxReviewAnchorRange(root: HTMLElement, item: any, layoutCache: LayoutCache): Range | null {
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
      : null;
    if (!textIndex || !textIndex.normalizedText) return null;
    const matches = _collectReviewTextMatches(textIndex.normalizedText, anchorText);
    if (!matches.length) return null;
    const selectedMatch = _selectReviewTextMatch(textIndex, matches, item);
    if (!selectedMatch) return null;
    return _rangeFromReviewTextIndex(textIndex, selectedMatch[0], selectedMatch[1]);
  }

  function _collectRangeClientRects(range: Range | null): DOMRect[] {
    if (!range || typeof range.getClientRects !== 'function') return [];
    return Array.from(range.getClientRects()).filter((rect) => rect && (rect.width > 0.5 || rect.height > 0.5));
  }

  function _reviewHighlightRectsFromClientRects(rangeRects: DOMRect[], layoutState: LayoutState | null): AnchorHighlightRect[] {
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

  function _screenXToReviewContentX(screenX: number, layoutState: LayoutState | null): number {
    if (!layoutState || !layoutState.viewportRect) return Math.round(screenX || 0);
    const scale = layoutState.layoutScale && Number.isFinite(layoutState.layoutScale.x)
      ? layoutState.layoutScale.x
      : 1;
    return Math.round(layoutState.viewportScrollLeft + ((screenX - layoutState.viewportRect.left) / scale));
  }

  function _screenYToReviewContentY(screenY: number, layoutState: LayoutState | null): number {
    if (!layoutState || !layoutState.viewportRect) return Math.round(screenY || 0);
    const scale = layoutState.layoutScale && Number.isFinite(layoutState.layoutScale.y)
      ? layoutState.layoutScale.y
      : 1;
    return Math.round(layoutState.viewportScrollTop + ((screenY - layoutState.viewportRect.top) / scale));
  }

  function _collectReviewVisualPageBounds(layoutState: LayoutState, root: HTMLElement | null): PageBounds[] {
    if (!layoutState || !layoutState.viewportRect) return [];
    const pageRoot: HTMLElement | null = root || (layoutState.pageEl || $( 'wa-docx-editor' )?.querySelector('.ProseMirror') as HTMLElement || null);
    if (!pageRoot || typeof pageRoot.getBoundingClientRect !== 'function') return [];
    if (layoutState._reviewVisualPageRoot === pageRoot && Array.isArray(layoutState._reviewVisualPageBounds)) {
      return layoutState._reviewVisualPageBounds;
    }
    const rootRect = pageRoot.getBoundingClientRect();
    if (!rootRect || rootRect.height <= 0) return [];

    const bounds: PageBounds[] = [];
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
      .filter((b): b is { top: number; upperBottom: number; nextTop: number } => b !== null && b !== undefined)
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

  function _resolveReviewPageBoundsForScreenY(screenY: number, layoutState: LayoutState, root: HTMLElement | null): PageBounds | null {
    if (!layoutState || !layoutState.viewportRect) return null;
    const contentY = _screenYToReviewContentY(screenY, layoutState);
    const visualPages = _collectReviewVisualPageBounds(layoutState, root);
    if (visualPages.length) {
      const containingPage = visualPages.find((page) => contentY >= page.top && contentY <= page.bottom);
      if (containingPage) return containingPage;
      let nearest: PageBounds | null = null;
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
    const scopedRoot: HTMLElement | null = root || host;
    const pageCandidates: HTMLElement[] = [];
    if (scopedRoot && scopedRoot.matches && scopedRoot.matches('.koto-doc-page, .ProseMirror')) {
      pageCandidates.push(scopedRoot);
    }
    if (scopedRoot && scopedRoot.querySelectorAll) {
      pageCandidates.push(...Array.from(scopedRoot.querySelectorAll('.koto-doc-page')) as HTMLElement[]);
    }
    if (!pageCandidates.length && layoutState.pageEl) {
      pageCandidates.push(layoutState.pageEl);
    }
    let bestPage: { rect: DOMRect; pageEl: HTMLElement } | null = null;
    let bestDistance = Infinity;
    for (const pageEl of pageCandidates) {
      if (!pageEl || typeof pageEl.getBoundingClientRect !== 'function') continue;
      const rect = pageEl.getBoundingClientRect();
      if (!rect || rect.height <= 0) continue;
      const distance = screenY < rect.top
        ? rect.top - screenY
        : (screenY > rect.bottom ? screenY - rect.bottom : 0);
      if (distance < bestDistance) {
        bestDistance = distance;
        bestPage = { rect, pageEl };
      }
    }
    if (!bestPage) return null;
    const top = _screenYToReviewContentY(bestPage.rect.top, layoutState);
    const bottom = _screenYToReviewContentY(bestPage.rect.bottom, layoutState);
    if (!Number.isFinite(top) || !Number.isFinite(bottom) || bottom <= top) return null;
    return { top, bottom, pageEl: bestPage.pageEl };
  }

  function _resolveReviewAnchorGeometry(root: HTMLElement, item: any, layoutState: LayoutState, layoutCache: LayoutCache): AnchorGeometry | null {
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

  function _getReviewContentRoot(): HTMLElement | null {
    return document.querySelector('#wa-docx-editor .ProseMirror')
      || $('wa-editor-content')
      || null;
  }

  function _getRangeBoundingRect(range: Range | null, rangeRects?: DOMRect[]): DOMRect | null {
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
      } as DOMRect;
    }
    if (!range || typeof range.getBoundingClientRect !== 'function') return null;
    const rect = range.getBoundingClientRect();
    if (!rect || (!rect.width && !rect.height)) return null;
    return rect;
  }

  function _resolveReviewAnchorTarget(item: any): AnchorTarget | null {
    const root = _getReviewContentRoot();
    if (!root) return null;
    let textIndex: TextIndex | null = null;
    const layoutCache: LayoutCache = {
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
            ? range.commonAncestorContainer as HTMLElement
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

  function scrollReviewAnchorIntoView(item: any): { found: boolean; element: HTMLElement | null; rect?: DOMRect } {
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

  function _ensureReviewConnectorLayer(listEl: HTMLElement): SVGElement | null {
    if (!listEl) return null;
    let layer = listEl.querySelector('.wa-review-connector-layer');
    if (!layer) {
      layer = document.createElementNS(SVG_NS, 'svg');
      layer.classList.add('wa-review-connector-layer');
      layer.setAttribute('aria-hidden', 'true');
      listEl.insertBefore(layer, listEl.firstChild);
    }
    return layer as SVGElement;
  }

  function _ensureReviewAnchorHighlightLayer(listEl: HTMLElement): SVGElement | null {
    if (!listEl) return null;
    let layer = listEl.querySelector('.wa-review-anchor-highlight-layer');
    if (!layer) {
      layer = document.createElementNS(SVG_NS, 'svg');
      layer.classList.add('wa-review-anchor-highlight-layer');
      layer.setAttribute('aria-hidden', 'true');
      listEl.insertBefore(layer, listEl.firstChild);
    }
    return layer as SVGElement;
  }

  function _drawReviewConnector(layer: SVGElement, connector: ConnectorSpec): void {
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

  function _drawReviewAnchorHighlight(layer: SVGElement, highlight: AnchorHighlightSpec): void {
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
    _getReviewContentRoot,
  };
}
