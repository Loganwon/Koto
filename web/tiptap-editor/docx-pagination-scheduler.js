/**
 * DOCX pagination scheduling boundary.
 *
 * This module is the only owner of browser-side pagination triggers. The
 * pagination plugin supplies the measurement callback; it must not create
 * timers or observers itself. Page-break decorations and the editor's final
 * bottom padding intentionally change editor height, so height-only observer
 * notifications are never a reason to paginate again.
 */

const DEFAULT_UPDATE_DELAY_MS = 120;

function _roundLayoutWidth(value) {
  return Math.round((Number(value) || 0) * 100) / 100;
}

function _readLogicalWidth(element) {
  const snapshot = window.KotoRenderSurface?.getSnapshot?.(element);
  if (snapshot?.logicalSize) return _roundLayoutWidth(snapshot.logicalSize.width);
  const rectWidth = Number(element?.getBoundingClientRect?.().width) || 0;
  const paintScale = window.KotoUiScale?.getElementPaintScale?.(element)?.x || 1;
  return _roundLayoutWidth(rectWidth / paintScale);
}

export function createDocxPaginationScheduler({
  view,
  measure,
  initialDelayMs,
  updateDelayMs = DEFAULT_UPDATE_DELAY_MS,
}) {
  let destroyed = false;
  let measuring = false;
  let timer = null;
  let frame = null;
  let mediaResizeObserver = null;
  let renderSurfaceController = null;
  let observedLayoutRoot = null;
  let lastObservedLayoutWidth = null;
  const watchedMedia = new Map();

  const schedule = (_reason = 'layout', delayMs = updateDelayMs) => {
    if (destroyed) return;
    if (timer) window.clearTimeout(timer);
    timer = window.setTimeout(() => {
      timer = null;
      if (frame) window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(() => {
        frame = null;
        if (destroyed || measuring) return;
        measuring = true;
        try { measure(); } finally { measuring = false; }
      });
    }, Math.max(0, delayMs));
  };

  const scheduleAfterMediaSettles = () => schedule('media', 40);

  const unwatchMedia = (node, onSettled) => {
    try { mediaResizeObserver?.unobserve(node); } catch (_) {}
    try {
      node.removeEventListener('load', onSettled);
      node.removeEventListener('error', onSettled);
    } catch (_) {}
  };

  const watchMedia = (currentView = view) => {
    const pmDom = currentView?.dom;
    if (!pmDom?.querySelectorAll) return;
    if (typeof ResizeObserver !== 'undefined' && !mediaResizeObserver) {
      mediaResizeObserver = new ResizeObserver(scheduleAfterMediaSettles);
    }

    const mediaNodes = new Set(pmDom.querySelectorAll(
      'img,svg,canvas,video,.koto-img-wrapper',
    ));
    watchedMedia.forEach((onSettled, node) => {
      if (mediaNodes.has(node)) return;
      unwatchMedia(node, onSettled);
      watchedMedia.delete(node);
    });

    mediaNodes.forEach((node) => {
      if (watchedMedia.has(node)) return;
      const onSettled = () => scheduleAfterMediaSettles();
      watchedMedia.set(node, onSettled);
      try { mediaResizeObserver?.observe(node); } catch (_) {}
      if (node.tagName === 'IMG' || node.tagName === 'VIDEO') {
        node.addEventListener('load', onSettled, { passive: true });
        node.addEventListener('error', onSettled, { passive: true });
        if (node.tagName === 'IMG' && node.complete) scheduleAfterMediaSettles();
      }
    });
  };

  const watchLayoutSurface = (currentView = view) => {
    const pmDom = currentView?.dom;
    if (!pmDom || !window.KotoRenderSurface?.createController) return;
    if (observedLayoutRoot === pmDom && renderSurfaceController) return;
    try { renderSurfaceController?.dispose(); } catch (_) {}
    observedLayoutRoot = pmDom;
    lastObservedLayoutWidth = _readLogicalWidth(pmDom);
    renderSurfaceController = window.KotoRenderSurface.createController(pmDom, (_snapshot, reasons) => {
      const observedWidth = _readLogicalWidth(pmDom);
      const widthChanged = Number.isFinite(observedWidth) && observedWidth !== lastObservedLayoutWidth;
      const uiScaleChanged = reasons?.has?.('ui-scale');
      if (!widthChanged && !uiScaleChanged) return;
      lastObservedLayoutWidth = observedWidth;
      schedule(widthChanged ? 'editor-width' : 'ui-scale', 40);
    });
  };

  const onHeaderFooterChanged = () => schedule('header-footer', 40);

  return {
    start() {
      watchMedia(view);
      watchLayoutSurface(view);
      window.addEventListener('koto-hdrftr-changed', onHeaderFooterChanged);
      try { document.fonts?.ready?.then(() => schedule('fonts', 40)); } catch (_) {}
      schedule('initial', initialDelayMs);
    },

    onDocumentChanged(currentView = view) {
      watchMedia(currentView);
      watchLayoutSurface(currentView);
      schedule('document');
    },

    destroy() {
      destroyed = true;
      if (timer) window.clearTimeout(timer);
      if (frame) window.cancelAnimationFrame(frame);
      window.removeEventListener('koto-hdrftr-changed', onHeaderFooterChanged);
      try { mediaResizeObserver?.disconnect(); } catch (_) {}
      try { renderSurfaceController?.dispose(); } catch (_) {}
      mediaResizeObserver = null;
      renderSurfaceController = null;
      observedLayoutRoot = null;
      watchedMedia.forEach((onSettled, node) => unwatchMedia(node, onSettled));
      watchedMedia.clear();
    },
  };
}
