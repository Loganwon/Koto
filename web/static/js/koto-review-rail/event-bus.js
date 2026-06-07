/**
 * koto-review-rail/event-bus.js
 *
 * Minimal event bus for the WPS-style review rail.
 * Wraps a standard EventTarget so all rail components communicate through
 * typed custom events rather than direct imperative mutation.
 *
 * Usage:
 *   const bus = KotoReviewRailEventBus.create();
 *   bus.on('review:focus', ({ detail }) => …);
 *   bus.emit('review:focus', { itemId: 'c_1' });
 *
 * Supported events:
 *   review:items-changed        { items: ReviewItem[] }
 *   review:focus                { itemId: string }
 *   review:hover                { itemId: string | null }
 *   review:scroll-into-view     { itemId: string }
 *   review:anchor-highlight     { itemId: string, active: boolean }
 *   review:create-from-selection { text: string, anchorText: string }
 *   review:accept               { itemId: string }
 *   review:reject               { itemId: string }
 *   review:delete               { itemId: string }
 *   review:reply                { parentId: string, text: string }
 *   review:layout-needed        {}
 *
 * Exposed as window.KotoReviewRailEventBus.
 */
(function (global) {
  'use strict';

  function create() {
    const target = new EventTarget();

    function emit(type, detail) {
      target.dispatchEvent(new CustomEvent(type, { detail: detail || {} }));
    }

    function on(type, handler) {
      target.addEventListener(type, handler);
    }

    function off(type, handler) {
      target.removeEventListener(type, handler);
    }

    function once(type, handler) {
      const wrapper = (e) => { handler(e); target.removeEventListener(type, wrapper); };
      target.addEventListener(type, wrapper);
    }

    return { emit, on, off, once };
  }

  global.KotoReviewRailEventBus = { create };
})(window);
