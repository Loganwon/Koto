(function () {
  'use strict';

  function create(deps) {
    const state = deps.state;
    const cloneSerializable = typeof deps.cloneSerializable === 'function'
      ? deps.cloneSerializable
      : ((value, fallback) => {
          try { return JSON.parse(JSON.stringify(value)); } catch (_) { return fallback; }
        });

    function cleanString(value) {
      return String(value == null ? '' : value).trim();
    }

    function makeId(prefix, index) {
      return `${prefix}-${Date.now().toString(36)}-${index}-${Math.random().toString(36).slice(2, 8)}`;
    }

    function proposalKey(proposal) {
      const raw = cleanString(proposal && (proposal.id || proposal.review_id || proposal.proposal_id));
      return raw.replace(/^proposal:/, '');
    }

    function commentKey(comment) {
      const raw = cleanString(comment && (comment.id || comment.review_id || comment.comment_id));
      return raw.replace(/^comment:/, '');
    }

    function normalizeReviewComment(comment, index) {
      const raw = cloneSerializable(comment, {}) || {};
      const id = commentKey(raw) || makeId('comment', index);
      const normalized = Object.assign({}, raw, {
        id,
        review_id: cleanString(raw.review_id) || `comment:${id}`,
        author: cleanString(raw.author || raw.user || raw.initials) || '批注',
        initials: cleanString(raw.initials || raw.author).slice(0, 2),
        text: cleanString(raw.text || raw.content || raw.body || raw.comment),
        anchor_text: cleanString(raw.anchor_text || raw.anchorText || raw.quote || raw.selection_text || raw.original_text),
        date: cleanString(raw.date || raw.created_at || raw.createdAt || raw.time),
      });
      if (!normalized.date) normalized.date = new Date().toISOString();
      return normalized;
    }

    function normalizeReviewProposal(proposal, index) {
      const raw = cloneSerializable(proposal, {}) || {};
      const id = proposalKey(raw) || makeId('proposal', index);
      const action = cleanString(raw.action || raw.action_type || raw.type) || 'replace';
      const originalText = cleanString(raw.original_text || raw.anchor_text || raw.old_text || raw.from || raw.text);
      const proposedText = cleanString(raw.proposed_text || raw.replacement_text || raw.new_text || raw.value || raw.to);
      const normalized = Object.assign({}, raw, {
        id,
        review_id: cleanString(raw.review_id) || `proposal:${id}`,
        source: cleanString(raw.source) || 'ai_proposal',
        action,
        action_type: cleanString(raw.action_type || action) || 'replace',
        original_text: originalText,
        anchor_text: cleanString(raw.anchor_text || originalText),
        proposed_text: proposedText,
        rationale: cleanString(raw.rationale || raw.reason || raw.comment || raw.explanation),
        _reviewStatus: cleanString(raw._reviewStatus || raw.review_status || raw.status),
      });
      return normalized;
    }

    function ensureTabReviewState(tab) {
      if (!tab) return null;
      const existing = tab.reviewState && typeof tab.reviewState === 'object'
        ? tab.reviewState
        : {};
      const serverData = tab.serverData && typeof tab.serverData === 'object'
        ? tab.serverData
        : {};
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
      return tabs.find((tab) => tab && tab.path === activePath)
        || tabs.find((tab) => tab && tab.fileType === 'docx' && (tab.path === state.wsSourcePath || tab.name === state.fileName))
        || (state.fileType === 'docx' ? tabs.find((tab) => tab && tab.fileType === 'docx') : null)
        || null;
    }

    function setStoredReviewMode(mode) {
      const next = ['all', 'comments', 'proposals'].includes(mode) ? mode : 'all';
      state._reviewMode = next;
      try { localStorage.setItem('wa_review_mode', next); } catch (_) {}
      return next;
    }

    function isReviewRailVisible() {
      return state.fileType === 'docx' && state._reviewCenterOpen !== false;
    }

    function isReviewCommentModeEnabled() {
      return state.fileType === 'docx' && state._reviewCenterOpen !== false && state._reviewMode === 'comments';
    }

    function isResolvedReviewProposal(proposal) {
      const status = cleanString(proposal && (proposal._reviewStatus || proposal.status)).toLowerCase();
      return status === 'accepted' || status === 'rejected' || status === 'resolved';
    }

    function visibleReviewProposals(reviewState) {
      return (reviewState && Array.isArray(reviewState.proposals) ? reviewState.proposals : [])
        .filter((proposal) => proposal && (cleanString(proposal.id || proposal.review_id) || cleanString(proposal.original_text || proposal.anchor_text || proposal.proposed_text)));
    }

    function shouldShowDocxReviewMarkers(reviewState) {
      if (state.fileType !== 'docx') return false;
      if (state._reviewCenterOpen !== false) return true;
      return !!(
        reviewState
        && ((Array.isArray(reviewState.comments) && reviewState.comments.length)
          || visibleReviewProposals(reviewState).length)
      );
    }

    function focusFirstReviewEntry(reviewState, preferredKind = '') {
      if (!reviewState) return '';
      const wantsComments = preferredKind === 'comment' || preferredKind === 'comments';
      const wantsProposals = preferredKind === 'proposal' || preferredKind === 'proposals';
      let item = null;
      if (wantsComments) item = (reviewState.comments || [])[0] || null;
      if (!item && wantsProposals) item = visibleReviewProposals(reviewState)[0] || null;
      if (!item) item = (reviewState.comments || [])[0] || visibleReviewProposals(reviewState)[0] || null;
      const id = item ? cleanString(item.review_id || item.id) : '';
      reviewState.focusedId = id;
      if (id && id.indexOf('proposal:') === 0) reviewState.expandedId = id;
      return id;
    }

    function reviewModeHasVisibleEntries(reviewState, mode = state._reviewMode) {
      if (!reviewState) return false;
      const hasComments = Array.isArray(reviewState.comments) && reviewState.comments.length > 0;
      const hasProposals = visibleReviewProposals(reviewState).length > 0;
      if (mode === 'comments') return hasComments;
      if (mode === 'proposals') return hasProposals;
      return hasComments || hasProposals;
    }

    function coerceReviewModeForVisibleContent(reviewState, preferredKind = '') {
      if (!reviewState) return state._reviewMode;
      const hasComments = reviewModeHasVisibleEntries(reviewState, 'comments');
      const hasProposals = reviewModeHasVisibleEntries(reviewState, 'proposals');
      if ((preferredKind === 'comment' || preferredKind === 'comments') && hasComments) return setStoredReviewMode('comments');
      if ((preferredKind === 'proposal' || preferredKind === 'proposals') && hasProposals) return setStoredReviewMode('proposals');
      if (state._reviewMode === 'comments' && !hasComments && hasProposals) return setStoredReviewMode('proposals');
      if (state._reviewMode === 'proposals' && !hasProposals && hasComments) return setStoredReviewMode('comments');
      if (!reviewModeHasVisibleEntries(reviewState, state._reviewMode)) return setStoredReviewMode('all');
      return state._reviewMode;
    }

    function serializeReviewComment(comment) {
      const normalized = normalizeReviewComment(comment, 0);
      const out = cloneSerializable(normalized, {}) || {};
      delete out.review_id;
      return out;
    }

    function syncDocCommentStateForActiveFile(nextComments) {
      const tab = activeReviewTab();
      const reviewState = ensureTabReviewState(tab);
      if (!reviewState) return [];
      if (Array.isArray(nextComments)) {
        reviewState.comments = nextComments.map(normalizeReviewComment);
      } else if (tab.serverData && Array.isArray(tab.serverData.comments)) {
        reviewState.comments = tab.serverData.comments.map(normalizeReviewComment);
      }
      return reviewState.comments;
    }

    function mergeReviewProposals(existing, incoming) {
      const merged = [];
      const seen = new Map();
      function add(item, index) {
        const normalized = normalizeReviewProposal(item, index);
        const key = proposalKey(normalized) || `${normalized.original_text}\n${normalized.proposed_text}\n${normalized.rationale}`;
        if (!key) return;
        if (seen.has(key)) {
          const existingIndex = seen.get(key);
          merged[existingIndex] = Object.assign({}, merged[existingIndex], normalized, {
            _reviewStatus: normalized._reviewStatus || merged[existingIndex]._reviewStatus,
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
      reviewState.proposals = options.replace
        ? mergeReviewProposals([], incoming)
        : mergeReviewProposals(reviewState.proposals, incoming);
      if (tab.serverData && typeof tab.serverData === 'object') {
        tab.serverData.proposals = reviewState.proposals.map((proposal) => cloneSerializable(proposal, {}) || {});
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
      visibleReviewProposals,
    };
  }

  window.KotoDocxReviewState = { create };
})();
