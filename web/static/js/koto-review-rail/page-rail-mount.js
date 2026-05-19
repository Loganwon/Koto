/**
 * koto-review-rail/page-rail-mount.js
 *
 * Creates and maintains one `.koto-page-rail` container per document page.
 * The rail container lives INSIDE the page element (position:absolute, right:0)
 * so card coordinates are always page-relative — no global scroll correction needed.
 *
 * Public API (window.KotoPageRailMount):
 *   mount(editorRoot, bus)   → void   — attach to all pages, observe mutations
 *   unmount()                → void   — tear down all mounts + observers
 *   getRailForPage(pageEl)   → HTMLElement | null
 *   getAllPageEls()           → HTMLElement[]
 *
 * Dependencies:
 *   Expects `.ProseMirror` or `.koto-doc-page` elements inside `editorRoot`.
 *   Fires `review:layout-needed` on the bus when pages change.
 */
(function (global) {
  'use strict';

  const RAIL_CLASS = 'koto-page-rail';
  const CONNECTOR_CLASS = 'koto-rail-connectors';
  const ATTR_PAGE_IDX = 'data-koto-rail-page';

  let _editorRoot = null;
  let _bus = null;
  let _mutationObserver = null;
  let _resizeObserver = null;
  let _mounted = false;

  /* ─── helpers ───────────────────────────────────────────────── */

  function _getPageEls(root) {
    if (!root) return [];
    // Support both .koto-doc-page wrappers (future) and direct ProseMirror
    const pages = Array.from(root.querySelectorAll('.koto-doc-page'));
    if (pages.length) return pages;
    // Fallback: the ProseMirror root itself is the single "page"
    const pm = root.querySelector('.ProseMirror');
    return pm ? [pm] : [];
  }

  /**
   * Create or update the .koto-page-rail inside a page element.
   * Idempotent: existing rail is preserved.
   */
  function _ensureRailForPage(pageEl, pageIdx) {
    if (!pageEl) return null;
    let rail = pageEl.querySelector(':scope > .' + RAIL_CLASS);
    if (!rail) {
      rail = document.createElement('div');
      rail.className = RAIL_CLASS;
      rail.setAttribute('aria-hidden', 'true');
      rail.setAttribute('data-koto-export-omit', 'true');

      // SVG connector layer (sibling of card list inside rail)
      const svgNS = 'http://www.w3.org/2000/svg';
      const svg = document.createElementNS(svgNS, 'svg');
      svg.classList.add(CONNECTOR_CLASS);
      svg.setAttribute('aria-hidden', 'true');
      svg.setAttribute('overflow', 'visible');
      rail.appendChild(svg);

      // Card list container
      const cardList = document.createElement('div');
      cardList.className = 'koto-page-rail-cards';
      rail.appendChild(cardList);

      pageEl.appendChild(rail);
    }
    rail.setAttribute(ATTR_PAGE_IDX, String(pageIdx));

    // Position: absolute, right:0, top:0, height:100%
    // Width is set dynamically via CSS var / style in rail-controller.js
    rail.style.position = 'absolute';
    rail.style.right = '0';
    rail.style.top = '0';
    rail.style.height = '100%';
    rail.style.pointerEvents = 'none';
    rail.style.overflow = 'visible';

    return rail;
  }

  /**
   * Ensure the page element has `position: relative` so that the rail
   * can be positioned absolutely inside it.
   */
  function _ensurePageRelative(pageEl) {
    const cs = window.getComputedStyle(pageEl);
    if (cs.position === 'static') {
      pageEl.style.position = 'relative';
    }
  }

  function _refreshAllMounts(root) {
    const pages = _getPageEls(root);
    pages.forEach((pageEl, idx) => {
      _ensurePageRelative(pageEl);
      _ensureRailForPage(pageEl, idx);
    });
    // Remove stale rails (pages that were deleted)
    const liveSet = new Set(pages);
    root.querySelectorAll('.' + RAIL_CLASS).forEach((rail) => {
      if (!liveSet.has(rail.parentElement)) rail.remove();
    });
    // NOTE: callers are responsible for emitting review:layout-needed.
    // Do NOT emit here — would create a loop when card innerHTML changes trigger this.
  }

  /* ─── IntersectionObserver for viewport virtualization ────── */

  let _intersectionObserver = null;

  function _setupIntersectionObserver(root) {
    if (typeof IntersectionObserver === 'undefined') return;
    if (_intersectionObserver) { _intersectionObserver.disconnect(); }
    _intersectionObserver = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          const rail = entry.target.querySelector(':scope > .' + RAIL_CLASS);
          if (rail) {
            rail.dataset.visible = entry.isIntersecting ? '1' : '0';
          }
        });
      },
      { root: null, rootMargin: '150% 0px', threshold: 0 },
    );
    _getPageEls(root).forEach((el) => _intersectionObserver.observe(el));
  }

  /* ─── Public API ─────────────────────────────────────────── */

  function mount(editorRoot, bus) {
    if (_mounted) unmount();
    _editorRoot = editorRoot;
    _bus = bus || null;
    _mounted = true;

    _refreshAllMounts(editorRoot);
    _setupIntersectionObserver(editorRoot);

    // MutationObserver: re-mount when pages are added/removed.
    // IMPORTANT: filter out mutations that originated inside our own .koto-page-rail
    // containers — otherwise every card innerHTML update creates an infinite layout loop.
    _mutationObserver = new MutationObserver((mutations) => {
      const hasExternalChange = mutations.some((m) => {
        const t = /** @type {Element} */ (m.target);
        return !(t.closest && t.closest('.' + RAIL_CLASS));
      });
      if (!hasExternalChange) return;
      _refreshAllMounts(editorRoot);
      _setupIntersectionObserver(editorRoot);
      if (_bus) _bus.emit('review:layout-needed', {});
    });
    _mutationObserver.observe(editorRoot, { childList: true, subtree: true });

    // ResizeObserver on root: fire layout-needed on resize
    if (typeof ResizeObserver !== 'undefined') {
      _resizeObserver = new ResizeObserver(() => {
        if (_bus) _bus.emit('review:layout-needed', {});
      });
      _resizeObserver.observe(editorRoot);
    }
  }

  function unmount() {
    if (_mutationObserver) { _mutationObserver.disconnect(); _mutationObserver = null; }
    if (_resizeObserver) { _resizeObserver.disconnect(); _resizeObserver = null; }
    if (_intersectionObserver) { _intersectionObserver.disconnect(); _intersectionObserver = null; }
    if (_editorRoot) {
      _editorRoot.querySelectorAll('.' + RAIL_CLASS).forEach((r) => r.remove());
    }
    _editorRoot = null;
    _bus = null;
    _mounted = false;
  }

  function getRailForPage(pageEl) {
    if (!pageEl) return null;
    return pageEl.querySelector(':scope > .' + RAIL_CLASS) || null;
  }

  function getAllPageEls() {
    return _editorRoot ? _getPageEls(_editorRoot) : [];
  }

  global.KotoPageRailMount = { mount, unmount, getRailForPage, getAllPageEls };
})(window);
