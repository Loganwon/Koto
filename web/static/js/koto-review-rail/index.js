/**
 * koto-review-rail/index.js
 *
 * Public entry point for the WPS-style review rail.
 * Loads all sub-modules and exposes a unified API at window.KotoReviewRail.
 *
 * Sub-modules must be loaded before this file:
 *   1. geometry.js
 *   2. event-bus.js
 *   3. page-rail-mount.js
 *   4. card.js
 *   5. connector-layer.js
 *   6. rail-controller.js
 *   7. index.js  ← this file
 *
 * Usage from workspace-assistant.js:
 *   const rail = KotoReviewRail.createController({ editorRoot, getPreviewText, onAction });
 *   rail.mount();
 *   rail.updateItems(normalizedItems);
 *   rail.setFocused(id);
 *   rail.refresh();
 *   rail.destroy();
 */
(function (global) {
  'use strict';

  /**
   * Normalize raw comments + proposals + (optional) revisions from the
   * current tab.serverData into a unified ReviewItem array.
   *
   * ReviewItem:
   *   id, kind ('comment'|'proposal'|'revision'), author, created_at,
   *   body, anchor_text, anchor_occurrence, anchor_context_before,
   *   anchor_context_after, parent_id, status, original_text, proposed_text,
   *   review_id, _reviewStatus, done, resolved, initials, date
   */
  function normalizeReviewItems(rawComments, rawProposals, rawRevisions) {
    const items = [];

    // Comments
    (rawComments || []).forEach((c) => {
      const id = String(c.id || c.review_id || '').trim();
      if (!id) return;
      items.push({
        id,
        review_id: id,
        kind: 'comment',
        author:                  String(c.author || '').trim() || '文档批注',
        initials:                String(c.initials || '').trim(),
        created_at:              c.date || c.created_at || '',
        date:                    c.date || '',
        body:                    String(c.text || '').trim(),
        text:                    String(c.text || '').trim(),
        anchor_text:             String(c.anchor_text || '').trim(),
        anchor_occurrence:       c.anchor_occurrence ?? c.anchorOccurrence ?? 0,
        anchor_context_before:   String(c.anchor_context_before || c.anchorContextBefore || '').trim(),
        anchor_context_after:    String(c.anchor_context_after || c.anchorContextAfter || '').trim(),
        parent_id:               String(c.parent_id || '').trim(),
        status:                  c.done ? 'done' : c.resolved ? 'resolved' : '',
        done:                    !!c.done,
        resolved:                !!c.resolved,
        // pass-through fields for legacy rail compatibility
        _source:                 'comment',
      });
    });

    // Proposals
    (rawProposals || []).forEach((p) => {
      const rawId = String(p.id || p.review_id || '').trim();
      if (!rawId) return;
      const id = rawId.replace(/^proposal:/, '');
      const reviewId = rawId.startsWith('proposal:') ? rawId : `proposal:${id}`;
      items.push({
        id,
        review_id:               reviewId,
        kind:                    'proposal',
        author:                  String(p.author || 'Koto AI').trim(),
        initials:                'KA',
        created_at:              p.created_at || p.date || '',
        date:                    p.date || '',
        body:                    String(p.rationale || p.note || '').trim(),
        text:                    String(p.rationale || p.note || '').trim(),
        anchor_text:             String(p.original_text || p.anchor_text || '').trim(),
        anchor_occurrence:       p.anchor_occurrence ?? p.anchorOccurrence ?? 0,
        anchor_context_before:   String(p.anchor_context_before || '').trim(),
        anchor_context_after:    String(p.anchor_context_after || '').trim(),
        original_text:           String(p.original_text || '').trim(),
        proposed_text:           String(p.proposed_text || p.value || '').trim(),
        action:                  String(p.action || p.action_type || 'replace'),
        parent_id:               '',
        status:                  String(p._reviewStatus || '').trim(),
        _reviewStatus:           String(p._reviewStatus || '').trim(),
        // pass-through
        tool_call:               p.tool_call || null,
        _source:                 'proposal',
      });
    });

    // Native revisions (optional)
    (rawRevisions || []).forEach((r) => {
      const id = String(r.id || r.review_id || '').trim();
      if (!id) return;
      items.push({
        id,
        review_id:               id,
        kind:                    'revision',
        author:                  String(r.author || '').trim() || '修订',
        initials:                String(r.initials || '').trim(),
        created_at:              r.date || '',
        date:                    r.date || '',
        body:                    String(r.text || r.anchor_text || '').trim(),
        text:                    String(r.text || '').trim(),
        anchor_text:             String(r.anchor_text || '').trim(),
        anchor_occurrence:       0,
        anchor_context_before:   '',
        anchor_context_after:    '',
        original_text:           String(r.original_text || r.deleted_text || '').trim(),
        proposed_text:           String(r.proposed_text || r.inserted_text || '').trim(),
        action:                  String(r.action || 'replace'),
        parent_id:               '',
        status:                  String(r.status || '').trim(),
        _source:                 'revision',
      });
    });

    return items;
  }

  /**
   * Group items into thread trees: { root, children[] }[]
   */
  function groupReviewThreads(items) {
    const byId = new Map(items.map((item) => [String(item.id || ''), item]));
    const childrenOf = new Map();
    const roots = [];
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

  /**
   * Create a fully wired ReviewRailController instance.
   */
  function createController(opts) {
    return global.KotoReviewRailController
      ? global.KotoReviewRailController.create(opts)
      : null;
  }

  global.KotoReviewRail = {
    normalizeReviewItems,
    groupReviewThreads,
    createController,
    // re-export sub-module handles for convenience
    get Geometry()       { return global.KotoReviewRailGeometry; },
    get EventBus()       { return global.KotoReviewRailEventBus; },
    get PageRailMount()  { return global.KotoPageRailMount; },
    get Card()           { return global.KotoReviewRailCard; },
    get ConnectorLayer() { return global.KotoReviewRailConnectorLayer; },
    get Controller()     { return global.KotoReviewRailController; },
  };
})(window);
