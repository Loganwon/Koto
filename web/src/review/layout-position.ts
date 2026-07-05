/**
 * Review rail positioning, card layout, and selection launcher for DOCX review.
 * Uses the SVG module for anchor resolution and connector drawing.
 *
 * Exports `createDocxReviewLayout()` as the main entry point — looks for
 * `window.KotoDocxReviewGeometry` for geometry computation, falls back to inline.
 */
import {
  createDocxReviewLayoutSvg,
  AnchorGeometry,
  LayoutCache,
  RailMetrics,
  LayoutState,
  ReviewLayoutDeps,
  ReviewSvgApi,
} from './layout-svg';

const DEFAULT_REVIEW_RAIL_LEFT_SHIFT = 0;
const DEFAULT_REVIEW_RAIL_RIGHT_SHIFT = 0;

interface LayoutEntry {
  collisionHeight: number;
  height: number;
  left: number;
  pageBottom: number | null;
  pageTop: number | null;
  top: number;
  width: number;
}

interface MeasuredCard {
  anchorGeometry: AnchorGeometry | null;
  card: HTMLElement;
  cardCollisionHeight: number;
  cardHeight: number;
  cardWidth: number;
  connectorOffsetY: number;
  desiredTop: number;
  index: number;
  pageBounds: { minTop: number; maxTop: number; maxAnchorDrift: number } | null;
}

interface ReviewLayoutApi {
  ensureReviewShellHost: () => HTMLElement | null;
  getDocxReviewRailMetrics: (host: HTMLElement, viewport: HTMLElement) => RailMetrics | null;
  layoutReviewShellInDocx: () => void;
  scrollReviewAnchorIntoView: (item: any) => { found: boolean; element: HTMLElement | null; rect?: DOMRect };
  scheduleReviewShellLayout: () => void;
  ensureReviewShellViewportSync: () => void;
  syncDocxReviewRailHostClass: () => void;
  ensureReviewSelectionLauncher: () => HTMLElement | null;
  hideReviewSelectionLauncher: () => void;
  renderReviewSelectionLauncher: () => void;
}

export function createDocxReviewLayout(deps: ReviewLayoutDeps): ReviewLayoutApi {
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
    _previewReviewText,
  } = deps;

  function _reviewRailLeftShift(host: HTMLElement | null): number {
    if (!host || typeof window === 'undefined' || typeof window.getComputedStyle !== 'function') {
      return DEFAULT_REVIEW_RAIL_LEFT_SHIFT;
    }
    const raw = window.getComputedStyle(host).getPropertyValue('--wa-review-rail-left-shift');
    const parsed = parseFloat(raw);
    return Number.isFinite(parsed) ? Math.round(parsed) : DEFAULT_REVIEW_RAIL_LEFT_SHIFT;
  }

  function _shiftReviewRailLeft(value: number, host: HTMLElement | null): number {
    const left = Math.round(Number(value) || 0) - _reviewRailLeftShift(host);
    return Math.max(0, left);
  }

  function _reviewRailRightShift(host: HTMLElement | null): number {
    if (!host || typeof window === 'undefined' || typeof window.getComputedStyle !== 'function') {
      return DEFAULT_REVIEW_RAIL_RIGHT_SHIFT;
    }
    const raw = window.getComputedStyle(host).getPropertyValue('--wa-review-rail-right-shift');
    const parsed = parseFloat(raw);
    return Number.isFinite(parsed) ? Math.round(parsed) : DEFAULT_REVIEW_RAIL_RIGHT_SHIFT;
  }

  function _positionReviewRail(value: number, host: HTMLElement | null): number {
    const offset = _reviewRailRightShift(host) - _reviewRailLeftShift(host);
    return Math.max(0, Math.round(Number(value) || 0) + offset);
  }

  function _reviewAnchorHeight(anchorGeometry: AnchorGeometry | null): number {
    if (!anchorGeometry) return 0;
    const top = Number(anchorGeometry.top);
    const bottom = Number(anchorGeometry.bottom);
    if (!Number.isFinite(top) || !Number.isFinite(bottom) || bottom <= top) return 0;
    return Math.max(0, Math.round(bottom - top));
  }

  function _clampReviewConnectorOffsetY(anchorGeometry: AnchorGeometry | null, cardHeight: number): number {
    const measuredHeight = Math.max(0, Math.round(Number(cardHeight) || 0));
    const fallback = Math.min(16, Math.max(11, Math.round(measuredHeight * 0.3)));
    if (!anchorGeometry) return fallback;
    const anchorOffset = Math.round((Number(anchorGeometry.pointY) || 0) - (Number(anchorGeometry.top) || 0));
    if (!Number.isFinite(anchorOffset)) return fallback;
    const maxOffset = Math.max(11, measuredHeight - 10);
    return Math.max(11, Math.min(maxOffset, anchorOffset));
  }

  function _reviewLayoutEntryBottom(entry: LayoutEntry | null): number {
    if (!entry) return 0;
    return entry.top + Math.max(entry.height || 0, entry.collisionHeight || 0);
  }

  function _resolveNonOverlappingCardTop(
    layoutEntries: LayoutEntry[],
    desiredTop: number,
    desiredLeft: number,
    cardWidth: number,
    cardHeight: number,
    bounds: { minTop: number; maxTop: number; maxAnchorDrift: number } | null,
    cardCollisionHeight: number,
  ): number {
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

  function ensureReviewShellHost(): HTMLElement | null {
    const shell = $('wa-review-shell');
    const docxEditor = $('wa-docx-editor');
    if (!shell || !docxEditor) return shell;
    if (shell.parentElement !== docxEditor) {
      docxEditor.appendChild(shell);
    }
    shell.classList.add('wa-review-shell-docx');
    return shell;
  }

  function getDocxReviewRailMetrics(host: HTMLElement, viewport: HTMLElement): RailMetrics | null {
    if (!host || !viewport) return null;
    if ((window as any).KotoDocxReviewGeometry) {
      const geo = (window as any).KotoDocxReviewGeometry.computeReviewGeometry(host, viewport);
      if (geo) {
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

    const hostRect = host.getBoundingClientRect();
    const viewportRect = viewport.getBoundingClientRect();
    const layoutScale = (deps as any)._reviewLayoutScale
      ? (deps as any)._reviewLayoutScale(viewport, viewportRect)
      : { x: 1, y: 1 };
    const viewportScrollLeft = Math.max(0, Math.round(viewport.scrollLeft || 0));
    const viewportScrollTop  = Math.max(0, Math.round(viewport.scrollTop  || 0));
    const pageEl   = host.querySelector('.ProseMirror') as HTMLElement | null;
    const pageRect = pageEl ? pageEl.getBoundingClientRect() : null;
    const hostStyles    = window.getComputedStyle(host);
    const minRailWidth  = 220;
    const railGap       = Math.max(6, Math.round(parseFloat(hostStyles.getPropertyValue('--wa-review-rail-gap')) || 6));
    const safeInset     = 8;
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
        shellLeft:          Math.round(((viewportRect.left - hostRect.left) / layoutScale.x)),
        shellTop:           Math.round(((viewportRect.top - hostRect.top) / layoutScale.y)),
        textColRight,
        viewportRect,
        viewportRight:      Math.round(viewportScrollLeft + ((viewportRect.width || 0) / layoutScale.x)),
        viewportWidth:      Math.round((viewportRect.width || 0) / layoutScale.x),
        viewportScrollLeft,
        viewportScrollTop,
        pageContentRight:   0,
        pagePaddingRight:   0,
      };
    }
    const zoomWrapper = pageEl!.closest('.koto-zoom-wrapper') || pageEl;
    const transformScale = _parseScaleFromTransform(
      zoomWrapper ? window.getComputedStyle(zoomWrapper as HTMLElement).transform : ''
    ) || { x: 1, y: 1 };
    const pagePaddingRight = Math.max(0, parseFloat(window.getComputedStyle(pageEl!).paddingRight) || 0);
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
      shellLeft:        Math.round(((viewportRect.left - hostRect.left) / layoutScale.x)),
      shellTop:         Math.round(((viewportRect.top - hostRect.top) / layoutScale.y)),
      textColRight,
      viewportRect,
      viewportRight,
      viewportWidth:    Math.round((viewportRect.width || 0) / layoutScale.x),
      viewportScrollLeft,
      viewportScrollTop,
      pageContentRight: 0,
    };
  }

  function _parseScaleFromTransform(transformValue: string): { x: number; y: number } | null {
    const value = String(transformValue || '').trim();
    if (!value || value === 'none') return null;
    const m = value.match(/^matrix\(([^)]+)\)/);
    if (m) {
      const p = m[1].split(',').map(Number);
      if (p.length >= 4 && p.every(Number.isFinite)) {
        return { x: Math.hypot(p[0], p[1]) || 1, y: Math.hypot(p[2], p[3]) || 1 };
      }
    }
    return null;
  }

  function layoutReviewShellInDocx(): void {
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
      : { x: 1, y: 1 };
    const viewportWidth = Math.round(
      (railMetrics && Number.isFinite(railMetrics.viewportWidth))
        ? railMetrics.viewportWidth
        : ((viewportRect.width || viewport.clientWidth || 0) / layoutScale.x)
    );
    const viewportScrollTop = Math.max(0, Math.round(viewport.scrollTop || 0));
    const viewportScrollLeft = Math.max(0, Math.round(viewport.scrollLeft || 0));
    const shellTop = railMetrics && Number.isFinite(railMetrics.shellTop)
      ? Math.round(railMetrics.shellTop)
      : Math.round(((viewportRect.top - hostRect.top) / layoutScale.y));
    const viewportHeight = Math.round(
      viewport.clientHeight ||
      ((viewportRect.height || 0) / layoutScale.y)
    );
    if (railMetrics) {
      const shellLeft = Number.isFinite(railMetrics.shellLeft)
        ? Math.round(railMetrics.shellLeft)
        : Math.round(((viewportRect.left - hostRect.left) / layoutScale.x));
      shell.style.left = shellLeft + 'px';
      shell.style.right = 'auto';
      shell.style.width = Math.max(0, viewportWidth) + 'px';
    }
    shell.style.top = shellTop + 'px';
    shell.style.bottom = 'auto';
    shell.style.height = viewportHeight + 'px';
    listEl.style.transform = `translate(${-viewportScrollLeft}px, ${-viewportScrollTop}px)`;
    listEl.style.width = Math.max(160, Math.round(railMetrics && (railMetrics as any).contentWidth || viewport.scrollWidth || viewportRect.width || 0)) + 'px';
    const contentRoot = railMetrics && railMetrics.pageEl
      ? railMetrics.pageEl
      : (host.querySelector('.ProseMirror') || host);
    let textIndex: any = null;
    const layoutCache: LayoutCache = {
      markerIndex: svg._buildReviewMarkerIndex(contentRoot as HTMLElement),
      getTextIndex() {
        if (!textIndex) textIndex = svg._buildReviewTextIndex(contentRoot as HTMLElement);
        return textIndex;
      },
    };
    const highlightLayer = svg._ensureReviewAnchorHighlightLayer(listEl);
    if (highlightLayer) {
      highlightLayer.innerHTML = '';
      highlightLayer.setAttribute('width', String(Math.max(160, Math.round(railMetrics && (railMetrics as any).contentWidth || viewport.scrollWidth || viewportRect.width || 0))));
    }
    const connectorLayer = svg._ensureReviewConnectorLayer(listEl);
    if (connectorLayer) {
      connectorLayer.innerHTML = '';
      connectorLayer.setAttribute('width', String(Math.max(160, Math.round(railMetrics && (railMetrics as any).contentWidth || viewport.scrollWidth || viewportRect.width || 0))));
    }
    const rawCardColLeft = railMetrics
      ? Math.max(12, Math.round(railMetrics.cardColLeft || (railMetrics.textColRight || 0) + Math.max(6, railMetrics.railGap) + 10))
      : 12;
    const cardColWidth = Math.max(
      railMetrics ? railMetrics.railWidth : 148,
      ...cards.map((card) => Math.round((card as HTMLElement).offsetWidth || 0)),
    );
    const desiredCardColLeft = Math.max(12, _positionReviewRail(rawCardColLeft, host));
    const viewportRight2 = railMetrics && Number.isFinite(railMetrics.viewportRight)
      ? Math.round(railMetrics.viewportRight)
      : Math.round(viewportScrollLeft + viewportWidth);
    const minCardColFromText = railMetrics && Number.isFinite(railMetrics.textColRight)
      ? Math.round(railMetrics.textColRight + Math.max(6, railMetrics.railGap || 12) + 4)
      : 12;
    const maxVisibleCardColLeft = Math.round(viewportRight2 - cardColWidth - 12);
    const cardColLeft = Math.max(
      12,
      minCardColFromText,
      Math.min(desiredCardColLeft, maxVisibleCardColLeft),
    );
    const connectorOriginX = railMetrics
      ? Math.round(railMetrics.textColRight || 0)
      : Math.max(0, cardColLeft - 20);

    const shellCoverWidth = Math.max(
      viewportWidth,
      railMetrics ? (railMetrics as any).contentWidth || 0 : 0,
      cardColLeft + cardColWidth + 14
    );
    shell.style.width = Math.max(0, viewportWidth) + 'px';
    shell.style.overflow = 'hidden';
    listEl.style.width = Math.max(160, Math.round(shellCoverWidth)) + 'px';
    if (connectorLayer) {
      connectorLayer.setAttribute('width', String(Math.max(160, Math.round(shellCoverWidth))));
    }

    const layoutEntries: LayoutEntry[] = [];
    const measuredCards: MeasuredCard[] = cards.map((card, index) => {
      const reviewId = String((card as HTMLElement).dataset.reviewId || '').trim();
      const entry = _findReviewEntry(reviewId);
      const anchorGeometry = entry && entry.item
        ? svg._resolveReviewAnchorGeometry(contentRoot as HTMLElement, entry.item, railMetrics as LayoutState, layoutCache)
        : null;
      (card as HTMLElement).style.left = cardColLeft + 'px';
      (card as HTMLElement).style.right = 'auto';
      card.classList.remove('is-page-bounded', 'is-page-clamped');
      (card as HTMLElement).style.removeProperty('--wa-review-card-page-max-height');
      (card as HTMLElement).style.removeProperty('--wa-review-card-anchor-min-height');
      const pageBounds = anchorGeometry
        && Number.isFinite(anchorGeometry.pageTop)
        && Number.isFinite(anchorGeometry.pageBottom)
        && anchorGeometry.pageBottom! > anchorGeometry.pageTop!
        ? {
            minTop: Math.max(0, Math.round(anchorGeometry.pageTop! + 6)),
            maxTop: Math.max(0, Math.round(anchorGeometry.pageBottom! - 6)),
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
        const cs = window.getComputedStyle(card as HTMLElement);
        const padV = Math.round((parseFloat(cs.paddingTop) || 0) + (parseFloat(cs.paddingBottom) || 0));
        const anchorMinHeight = Number.isFinite(pageAvailableHeight)
          ? Math.min(Math.max(0, anchorHeight - padV), pageAvailableHeight)
          : Math.max(0, anchorHeight - padV);
        const anchorHeightCap = isCommentCard ? 104 : 78;
        (card as HTMLElement).style.setProperty('--wa-review-card-anchor-min-height', `${Math.max(baseMinHeight, Math.min(anchorMinHeight, anchorHeightCap))}px`);
      }
      let cardHeight = (card as HTMLElement).offsetHeight || 32;
      if (pageBounds && Number.isFinite(pageAvailableHeight)) {
        card.classList.add('is-page-bounded');
        (card as HTMLElement).style.setProperty('--wa-review-card-page-max-height', `${Math.max(32, pageAvailableHeight)}px`);
        if (cardHeight > pageAvailableHeight) {
          card.classList.add('is-page-clamped');
          cardHeight = Math.max(32, pageAvailableHeight);
        }
      }
      const measuredCardWidth = Math.max(cardColWidth, (card as HTMLElement).offsetWidth || 148);
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
        card: card as HTMLElement,
        cardCollisionHeight,
        cardHeight,
        cardWidth: measuredCardWidth,
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
            entry.pageTop === item.pageBounds!.minTop
            && entry.pageBottom === item.pageBounds!.maxTop
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
        svg._drawReviewAnchorHighlight(highlightLayer, {
          rects: item.anchorGeometry.highlightRects || [],
          isFocused: item.card.classList.contains('focused') || item.card.classList.contains('is-focused'),
          isProposal: item.card.classList.contains('wa-proposal-card'),
        });
      }
      if (connectorLayer && item.anchorGeometry) {
        svg._drawReviewConnector(connectorLayer, {
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
      Math.round((railMetrics && (railMetrics as any).pageContentTop || 0) + (railMetrics && railMetrics.pageOffsetHeight || 0)),
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

  function scheduleReviewShellLayout(): void {
    requestAnimationFrame(() => {
      layoutReviewShellInDocx();
    });
  }

  function renderReviewSelectionLauncher(): void {
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
      : { x: 1, y: 1 };
    const viewportHostLeft = Math.round(((viewportRect.left - hostRect.left) / layoutScale.x));
    const viewportHostTop = Math.round(((viewportRect.top - hostRect.top) / layoutScale.y));
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
      Math.min(Math.round(((bounds.top - hostRect.top) / layoutScale.y)) - 8, maxTop),
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
      const selectionRight = Number.isFinite(cursorRight)
        ? Math.round(((cursorRight - hostRect.left) / layoutScale.x)) + Math.max(6, railMetrics.railGap || 12)
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
      const label = String(selection.countLabel || '').trim() || `${String((selection.rawText || '').trim()).length}字`;
      const preview = _previewReviewText(selection.previewText || selection.rawText || '', 28);
      (subtitle as HTMLElement).textContent = preview ? `${label} · ${preview}` : label;
      (subtitle as HTMLElement).title = (subtitle as HTMLElement).textContent || '';
    }
    syncDocxReviewRailHostClass();
  }

  function ensureReviewShellViewportSync(): void {
    const viewport = $('wa-editor-content');
    if (viewport && !(viewport as any)._waReviewShellSyncBound) {
      (viewport as any)._waReviewShellSyncBound = true;
      viewport.addEventListener('scroll', () => {
        const shell = $('wa-review-shell');
        if (shell && shell.style.display !== 'none') scheduleReviewShellLayout();
        renderReviewSelectionLauncher();
      }, { passive: true } as any);
    }
    if (!(window as any).__waReviewShellResizeBound) {
      (window as any).__waReviewShellResizeBound = true;
      window.addEventListener('resize', () => {
        const shell = $('wa-review-shell');
        if (shell && shell.style.display !== 'none') scheduleReviewShellLayout();
        renderReviewSelectionLauncher();
      });
    }
    const host = $('wa-docx-editor');
    if (host && !(host as any)._waReviewShellResizeObserved) {
      (host as any)._waReviewShellResizeObserved = true;
      const ro = new ResizeObserver(() => {
        const shell = $('wa-review-shell');
        if (shell && shell.style.display !== 'none') scheduleReviewShellLayout();
        renderReviewSelectionLauncher();
      });
      ro.observe(host);
    }
  }

  function syncDocxReviewRailHostClass(): void {
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

  function ensureReviewSelectionLauncher(): HTMLElement | null {
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
        (window as any).WA.captureReviewSelection(event);
      });
      launcher.querySelectorAll('.wa-review-selection-add').forEach((button) => {
        button.addEventListener('mousedown', (event) => {
          if (event && typeof event.preventDefault === 'function') event.preventDefault();
          if (event && typeof event.stopPropagation === 'function') event.stopPropagation();
          (window as any).WA.captureReviewSelection(event);
        });
        button.addEventListener('click', (event) => {
          if (event && typeof event.preventDefault === 'function') event.preventDefault();
          if (event && typeof event.stopPropagation === 'function') event.stopPropagation();
          const createMode = String((button as HTMLElement).dataset.reviewCreate || '').trim();
          if (createMode === 'revision' && (window as any).WA && typeof (window as any).WA.createReviewRevision === 'function') {
            (window as any).WA.createReviewRevision();
          } else if ((window as any).WA && typeof (window as any).WA.createReviewComment === 'function') {
            (window as any).WA.createReviewComment();
          }
        });
      });
      host.appendChild(launcher);
    }
    return launcher;
  }

  function hideReviewSelectionLauncher(): void {
    const launcher = $('wa-review-selection-launcher');
    state._reviewLauncherVisible = false;
    if (launcher) launcher.style.display = 'none';
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
    renderReviewSelectionLauncher,
  };
}

// Backward compat
if (typeof window !== 'undefined') {
  (window as any).KotoDocxReviewLayout = { create: createDocxReviewLayout };
}
