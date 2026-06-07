/**
 * koto-review-rail/rail-controller.js
 *
 * The main orchestrator for the WPS-style per-page review rail.
 * Integrates: page-rail-mount + geometry + card renderer + connector layer.
 *
 * Usage:
 *   const ctrl = KotoReviewRailController.create({ editorRoot, getPreviewText });
 *   ctrl.mount();
 *   ctrl.updateItems(normalizedItems);
 *   ctrl.setFocused('c_1');
 *   ctrl.refresh();
 *   ctrl.destroy();
 *
 * The controller owns a single RAF scheduler — all signals (scroll, resize,
 * zoom, data change, focus change) coalesce into one animation-frame layout pass.
 *
 * Exposed as window.KotoReviewRailController.
 */
(function (global) {
  'use strict';

  function create(opts) {
    opts = opts || {};
    const editorRoot = opts.editorRoot || document.getElementById('wa-docx-editor') || document.body;
    const getPreviewText = opts.getPreviewText || ((s, n) => String(s || '').slice(0, n || 64));
    const onAction = opts.onAction || null;   // callback(action, itemId, extra)

    /* ── state ────────────────────────────────────────────────── */
    let _items = [];          // ReviewItem[] (normalized)
    let _focusedId = '';
    let _hoveredId = '';
    let _editingId = '';
    let _mounted = false;
    let _rafPending = false;
    let _destroyed = false;

    /* ── event bus ─────────────────────────────────────────────── */
    const bus = global.KotoReviewRailEventBus
      ? global.KotoReviewRailEventBus.create()
      : _fallbackBus();

    /* ── module references ─────────────────────────────────────── */
    const Geo       = () => global.KotoReviewRailGeometry;
    const Mount     = () => global.KotoPageRailMount;
    const Card      = () => global.KotoReviewRailCard;
    const Connector = () => global.KotoReviewRailConnectorLayer;

    /* ── thread grouping ───────────────────────────────────────── */

    function _groupThreads(items) {
      const roots = [];
      const byId = new Map();
      items.forEach((item) => byId.set(String(item.id || ''), item));
      const childrenOf = new Map();
      items.forEach((item) => {
        const pid = String(item.parent_id || '').trim();
        if (pid && byId.has(pid)) {
          if (!childrenOf.has(pid)) childrenOf.set(pid, []);
          childrenOf.get(pid).push(item);
        } else {
          roots.push(item);
        }
      });
      return roots.map((root) => ({
        root,
        children: childrenOf.get(String(root.id || '')) || [],
      }));
    }

    /* ── layout pass ───────────────────────────────────────────── */

    function _layoutPage(pageEl, threads, cardHeightCache) {
      const geo = Geo() && Geo().computePageGeometry(pageEl);
      if (!geo) return;

      const railMount = Mount() && Mount().getRailForPage(pageEl);
      if (!railMount) return;

      // Skip invisible pages (IntersectionObserver flag)
      if (railMount.dataset.visible === '0') {
        const cardList = railMount.querySelector('.koto-page-rail-cards');
        const svgEl    = railMount.querySelector('.koto-rail-connectors');
        if (cardList) cardList.innerHTML = '';
        if (svgEl && Connector()) Connector().clearConnectors(svgEl);
        return;
      }

      // Collect all root items (and their children) for this page
      const allItems = threads.flatMap((t) => [t.root, ...t.children]);

      // Resolve anchors for root items only
      const rootItems = threads.map((t) => t.root);
      const anchorRefs = Geo().resolveAnchors(rootItems, pageEl);
      if (!anchorRefs.length && !allItems.some((item) => item._forceShowOnPage === pageEl)) {
        // No anchors found on this page — clear rail and return
        const cardList = railMount.querySelector('.koto-page-rail-cards');
        const svgEl    = railMount.querySelector('.koto-rail-connectors');
        if (cardList) cardList.innerHTML = '';
        if (svgEl && Connector()) Connector().clearConnectors(svgEl);
        return;
      }

      // Build clusters from anchor refs
      const clusters = Geo().mergeNeighborAnchors(anchorRefs, 6);

      // Set rail width via CSS custom property
      railMount.style.setProperty('--koto-rail-width', geo.railWidth + 'px');
      railMount.style.width = geo.railWidth + 'px';
      railMount.style.right = '0px';

      // Measure card heights using cached or rendered values
      const cardList = railMount.querySelector('.koto-page-rail-cards');
      if (!cardList) return;

      const cardHtml = threads.map((t) => {
        if (!anchorRefs.some((r) => r.itemId === t.root.id)) return '';
        const ctx = {
          focusedId:   _focusedId,
          hoveredId:   _hoveredId,
          editingId:   _editingId,
          previewText: getPreviewText,
        };
        return Card() ? Card().renderThread(t.root, t.children, ctx) : '';
      }).filter(Boolean).join('\n');

      cardList.innerHTML = cardHtml;

      // Measure heights after render
      const cardEls = Array.from(cardList.querySelectorAll('.koto-review-card, .koto-review-thread'));
      const heightMap = new Map();
      threads.forEach((t, i) => {
        const el = cardEls[i];
        if (el) {
          const h = el.offsetHeight || 60;
          cardHeightCache.set(t.root.id, h);
          heightMap.set(t.root.id, h);
          t.children.forEach((c) => heightMap.set(c.id, 0)); // children nested inside root height
        }
      });

      // Relax positions
      const layoutEntries = Geo().relaxCardPositions(clusters, heightMap, {
        railHeight: geo.pageHeight,
        defaultCardHeight: 60,
      });

      // Position cards
      layoutEntries.forEach((entry) => {
        const selector = `[data-review-id="${CSS.escape(entry.itemId)}"]`;
        const cardEl = cardList.querySelector(selector)
          || cardList.querySelector(`.koto-review-thread[data-thread-root="${CSS.escape(entry.itemId)}"]`);
        if (cardEl) {
          cardEl.style.position = 'absolute';
          cardEl.style.top  = entry.top + 'px';
          cardEl.style.left = '0';
          cardEl.style.width = geo.railWidth + 'px';
          cardEl.style.pointerEvents = 'auto';
        }
      });

      cardList.style.position = 'relative';
      cardList.style.height   = geo.pageHeight + 'px';

      // Lookup anchor X for each entry
      const anchorMap = new Map(anchorRefs.map((r) => [r.itemId, r]));

      // Draw connectors
      const svgEl = railMount.querySelector('.koto-rail-connectors');
      if (svgEl && Connector()) {
        const connEntries = layoutEntries.map((entry) => {
          const ref = anchorMap.get(entry.itemId);
          return {
            ...entry,
            anchorX:     ref ? ref.lineRight : geo.textColRight,
            connectorOriginY: entry.connectorOriginY,
            cardLeft:    geo.railLeft,
            isFocused:   _focusedId === entry.itemId || _focusedId === `proposal:${entry.itemId}` || _focusedId === `comment:${entry.itemId}`,
            isHovered:   _hoveredId === entry.itemId,
          };
        });
        Connector().updateConnectors(svgEl, connEntries, geo);
      }

      // Bind per-page interaction events
      _bindPageCardInteractions(cardList);
    }

    function _runLayout() {
      _rafPending = false;
      if (_destroyed) return;
      if (!Mount()) return;

      const pageEls = Mount().getAllPageEls();
      if (!pageEls.length) return;

      const threads = _groupThreads(_items);
      const cardHeightCache = new Map();

      pageEls.forEach((pageEl) => _layoutPage(pageEl, threads, cardHeightCache));
    }

    /* ── RAF scheduler ─────────────────────────────────────────── */

    function scheduleLayout() {
      if (_rafPending || _destroyed) return;
      _rafPending = true;
      requestAnimationFrame(_runLayout);
    }

    /* ── interaction delegation ────────────────────────────────── */

    function _bindPageCardInteractions(cardList) {
      if (!cardList || cardList._kotoRailBound) return;
      cardList._kotoRailBound = true;

      cardList.addEventListener('click', (e) => {
        const btn = e.target.closest('[data-review-action]');
        if (!btn) return;
        e.stopPropagation();
        const action = btn.dataset.reviewAction;
        const itemId = btn.dataset.reviewId || btn.closest('[data-review-id]')?.dataset.reviewId || '';
        _handleAction(action, itemId, btn);
      });

      cardList.addEventListener('mouseenter', (e) => {
        const card = e.target.closest('[data-review-id]');
        if (!card) return;
        const id = card.dataset.reviewId || '';
        if (_hoveredId !== id) { _hoveredId = id; bus.emit('review:hover', { itemId: id }); scheduleLayout(); }
      }, true);

      cardList.addEventListener('mouseleave', (e) => {
        const card = e.target.closest('[data-review-id]');
        if (!card) return;
        if (_hoveredId) { _hoveredId = ''; bus.emit('review:hover', { itemId: null }); scheduleLayout(); }
      }, true);

      cardList.addEventListener('keydown', (e) => {
        if (e.key === 'Tab') {
          const allCards = Array.from(cardList.querySelectorAll('[data-review-id][tabindex="0"]'));
          const cur = document.activeElement;
          const idx = allCards.indexOf(cur);
          if (idx >= 0) {
            e.preventDefault();
            const next = e.shiftKey ? allCards[idx - 1] : allCards[idx + 1];
            if (next) next.focus();
          }
        } else if (e.key === 'Enter' || e.key === ' ') {
          const card = e.target.closest('[data-review-id]');
          if (card) _handleAction('activate', card.dataset.reviewId, card);
        }
      });
    }

    function _handleAction(action, itemId, el) {
      switch (action) {
        case 'activate':
        case 'focus':
          setFocused(itemId);
          bus.emit('review:focus', { itemId });
          bus.emit('review:scroll-into-view', { itemId });
          break;
        case 'hover':
          break;
        case 'accept':
          bus.emit('review:accept', { itemId });
          break;
        case 'reject':
          bus.emit('review:reject', { itemId });
          break;
        case 'delete':
          bus.emit('review:delete', { itemId });
          break;
        case 'reply':
          bus.emit('review:reply', { parentId: itemId, text: '' });
          break;
        case 'edit':
          _editingId = itemId;
          scheduleLayout();
          break;
        case 'cancel':
          _editingId = '';
          scheduleLayout();
          break;
        case 'save': {
          const textarea = el && el.closest('[data-review-id]')
            ? el.closest('[data-review-id]').querySelector('textarea')
            : null;
          const text = textarea ? textarea.value : '';
          bus.emit('review:save-comment', { itemId, text });
          _editingId = '';
          scheduleLayout();
          break;
        }
      }
      if (onAction) onAction(action, itemId, el);
    }

    /* ── public API ─────────────────────────────────────────────── */

    function mount() {
      if (_mounted) return;
      _mounted = true;
      if (Mount()) Mount().mount(editorRoot, bus);
      bus.on('review:layout-needed', scheduleLayout);
      scheduleLayout();
    }

    function updateItems(items) {
      _items = Array.isArray(items) ? items : [];
      scheduleLayout();
    }

    function setFocused(id) {
      _focusedId = String(id || '');
      scheduleLayout();
    }

    function refresh() {
      scheduleLayout();
    }

    function destroy() {
      _destroyed = true;
      if (Mount()) Mount().unmount();
      bus.off('review:layout-needed', scheduleLayout);
    }

    function getBus() { return bus; }

    return { mount, updateItems, setFocused, refresh, destroy, getBus };
  }

  /* ── fallback no-op bus (when event-bus.js not loaded) ───── */

  function _fallbackBus() {
    const handlers = {};
    return {
      emit(type) {},
      on(type, fn) { (handlers[type] || (handlers[type] = [])).push(fn); },
      off(type, fn) { handlers[type] = (handlers[type] || []).filter((h) => h !== fn); },
      once(type, fn) {},
    };
  }

  global.KotoReviewRailController = { create };
})(window);
