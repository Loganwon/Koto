/**
 * Review state management — comments, proposals, normalization.
 * Pure data manipulation; no DOM.
 */

interface ReviewTab {
  path?: string;
  fileType?: string;
  name?: string;
  reviewState?: ReviewState;
  serverData?: {
    comments?: ReviewComment[];
    proposals?: ReviewProposal[];
  };
}

interface AppState {
  openTabs?: ReviewTab[];
  activeTabPath?: string;
  wsSourcePath?: string;
  fileType?: string;
  fileName?: string;
  _reviewMode?: string;
  _reviewCenterOpen?: boolean;
}

interface ReviewComment {
  id?: string;
  review_id?: string;
  comment_id?: string;
  author?: string;
  initials?: string;
  text?: string;
  anchor_text?: string;
  date?: string;
  content?: string;
  body?: string;
  comment?: string;
  user?: string;
  raw?: any;
  anchorText?: string;
  quote?: string;
  selection_text?: string;
  original_text?: string;
  created_at?: string;
  createdAt?: string;
  time?: string;
}

interface ReviewProposal {
  id?: string;
  review_id?: string;
  proposal_id?: string;
  action?: string;
  action_type?: string;
  type?: string;
  source?: string;
  original_text?: string;
  anchor_text?: string;
  old_text?: string;
  from?: string;
  text?: string;
  proposed_text?: string;
  replacement_text?: string;
  new_text?: string;
  value?: string;
  to?: string;
  rationale?: string;
  reason?: string;
  comment?: string;
  explanation?: string;
  _reviewStatus?: string;
  review_status?: string;
  status?: string;
}

interface ReviewState {
  comments: ReviewComment[];
  proposals: ReviewProposal[];
  focusedId: string;
  expandedId: string;
}

type ReviewMode = 'all' | 'comments' | 'proposals';

function cleanString(value: any): string {
  return String(value == null ? '' : value).trim();
}

function cloneSerializable(value: any, fallback: any): any {
  try { return JSON.parse(JSON.stringify(value)); } catch (_) { return fallback; }
}

function makeId(prefix: string, index: number): string {
  return `${prefix}-${Date.now().toString(36)}-${index}-${Math.random().toString(36).slice(2, 8)}`;
}

export function createReviewState(deps: { state: AppState; cloneSerializable?: (v: any, fb: any) => any }) {
  const state = deps.state;
  const clone = typeof deps.cloneSerializable === 'function'
    ? deps.cloneSerializable
    : cloneSerializable;

  function proposalKey(proposal: ReviewProposal): string {
    const raw = cleanString(proposal && (proposal.id || proposal.review_id || proposal.proposal_id));
    return raw.replace(/^proposal:/, '');
  }

  function commentKey(comment: ReviewComment): string {
    const raw = cleanString(comment && (comment.id || comment.review_id || comment.comment_id));
    return raw.replace(/^comment:/, '');
  }

  function normalizeReviewComment(comment: ReviewComment, index?: number): ReviewComment {
    const raw = clone(comment, {}) || {};
    const id = commentKey(raw) || makeId('comment', index ?? 0);
    const normalized: ReviewComment = Object.assign({}, raw, {
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

  function normalizeReviewProposal(proposal: ReviewProposal, index?: number): ReviewProposal {
    const raw = clone(proposal, {}) || {};
    const id = proposalKey(raw) || makeId('proposal', index ?? 0);
    const action = cleanString(raw.action || raw.action_type || raw.type) || 'replace';
    const originalText = cleanString(raw.original_text || raw.anchor_text || raw.old_text || raw.from || raw.text);
    const proposedText = cleanString(raw.proposed_text || raw.replacement_text || raw.new_text || raw.value || raw.to);
    const normalized: ReviewProposal = Object.assign({}, raw, {
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

  function ensureTabReviewState(tab: ReviewTab | null): ReviewState | null {
    if (!tab) return null;
    const existing = (tab.reviewState && typeof tab.reviewState === 'object'
      ? tab.reviewState
      : {}) as any;
    const serverData = (tab.serverData && typeof tab.serverData === 'object'
      ? tab.serverData
      : {});
    const existingComments = Array.isArray(existing.comments) ? existing.comments : [];
    const serverComments = Array.isArray(serverData.comments) ? serverData.comments : [];
    const existingProposals = Array.isArray(existing.proposals) ? existing.proposals : [];
    const serverProposals = Array.isArray(serverData.proposals) ? serverData.proposals : [];
    // Preserve object identity once review state is live. Callers commonly
    // resolve an entry and then call ensureTabReviewState() again before
    // mutating it; replacing the arrays with cloned normalized objects here
    // made saves, edits and deletes silently target stale entries.
    existing.comments = existingComments.length
      ? existingComments.map((comment: ReviewComment, index: number) => Object.assign(comment, normalizeReviewComment(comment, index)))
      : serverComments.map(normalizeReviewComment);
    existing.proposals = existingProposals.length
      ? existingProposals.map((proposal: ReviewProposal, index: number) => Object.assign(proposal, normalizeReviewProposal(proposal, index)))
      : mergeReviewProposals([], serverProposals);
    existing.focusedId = cleanString(existing.focusedId);
    existing.expandedId = cleanString(existing.expandedId);
    tab.reviewState = existing;
    return existing;
  }

  function activeReviewTab(): ReviewTab | null {
    const tabs: ReviewTab[] = Array.isArray(state.openTabs) ? state.openTabs : [];
    const activePath = cleanString(state.activeTabPath || state.wsSourcePath);
    return tabs.find((tab) => tab && tab.path === activePath)
      || tabs.find((tab) => tab && tab.fileType === 'docx' && (tab.path === state.wsSourcePath || tab.name === state.fileName))
      || (state.fileType === 'docx' ? tabs.find((tab) => tab && tab.fileType === 'docx') ?? null : null)
      || null;
  }

  function setStoredReviewMode(mode: string): ReviewMode {
    const next: ReviewMode = (['all', 'comments', 'proposals'] as ReviewMode[]).includes(mode as ReviewMode) ? mode as ReviewMode : 'all';
    (state as any)._reviewMode = next;
    try { localStorage.setItem('wa_review_mode', next); } catch (_) {}
    return next;
  }

  function isReviewRailVisible(): boolean {
    return state.fileType === 'docx' && (state as any)._reviewCenterOpen !== false;
  }

  function isReviewCommentModeEnabled(): boolean {
    return state.fileType === 'docx' && (state as any)._reviewCenterOpen !== false && (state as any)._reviewMode === 'comments';
  }

  function isResolvedReviewProposal(proposal: ReviewProposal): boolean {
    const status = cleanString(proposal && (proposal._reviewStatus || proposal.status)).toLowerCase();
    return status === 'accepted' || status === 'rejected' || status === 'resolved';
  }

  function visibleReviewProposals(reviewState: ReviewState | null): ReviewProposal[] {
    return (reviewState && Array.isArray(reviewState.proposals) ? reviewState.proposals : [])
      .filter((proposal) => proposal && (cleanString(proposal.id || proposal.review_id) || cleanString(proposal.original_text || proposal.anchor_text || proposal.proposed_text)));
  }

  function shouldShowDocxReviewMarkers(reviewState: ReviewState | null): boolean {
    if (state.fileType !== 'docx') return false;
    if ((state as any)._reviewCenterOpen !== false) return true;
    return !!(
      reviewState
      && ((Array.isArray(reviewState.comments) && reviewState.comments.length)
        || visibleReviewProposals(reviewState).length)
    );
  }

  function focusFirstReviewEntry(reviewState: ReviewState | null, preferredKind: string = ''): string {
    if (!reviewState) return '';
    const wantsComments = preferredKind === 'comment' || preferredKind === 'comments';
    const wantsProposals = preferredKind === 'proposal' || preferredKind === 'proposals';
    let item: ReviewComment | ReviewProposal | null = null;
    if (wantsComments) item = (reviewState.comments || [])[0] || null;
    if (!item && wantsProposals) item = visibleReviewProposals(reviewState)[0] || null;
    if (!item) item = (reviewState.comments || [])[0] || visibleReviewProposals(reviewState)[0] || null;
    const id = item ? cleanString(item.review_id || item.id) : '';
    reviewState.focusedId = id;
    if (id && id.indexOf('proposal:') === 0) reviewState.expandedId = id;
    return id;
  }

  function reviewModeHasVisibleEntries(reviewState: ReviewState | null, mode: string = (state as any)._reviewMode): boolean {
    if (!reviewState) return false;
    const hasComments = Array.isArray(reviewState.comments) && reviewState.comments.length > 0;
    const hasProposals = visibleReviewProposals(reviewState).length > 0;
    if (mode === 'comments') return hasComments;
    if (mode === 'proposals') return hasProposals;
    return hasComments || hasProposals;
  }

  function coerceReviewModeForVisibleContent(reviewState: ReviewState | null, preferredKind: string = ''): ReviewMode {
    if (!reviewState) return (state as any)._reviewMode;
    const hasComments = reviewModeHasVisibleEntries(reviewState, 'comments');
    const hasProposals = reviewModeHasVisibleEntries(reviewState, 'proposals');
    if ((preferredKind === 'comment' || preferredKind === 'comments') && hasComments) return setStoredReviewMode('comments');
    if ((preferredKind === 'proposal' || preferredKind === 'proposals') && hasProposals) return setStoredReviewMode('proposals');
    if ((state as any)._reviewMode === 'comments' && !hasComments && hasProposals) return setStoredReviewMode('proposals');
    if ((state as any)._reviewMode === 'proposals' && !hasProposals && hasComments) return setStoredReviewMode('comments');
    if (!reviewModeHasVisibleEntries(reviewState, (state as any)._reviewMode)) return setStoredReviewMode('all');
    return (state as any)._reviewMode;
  }

  function serializeReviewComment(comment: ReviewComment): ReviewComment {
    const normalized = normalizeReviewComment(comment, 0);
    const out = clone(normalized, {}) || {};
    delete out.review_id;
    return out;
  }

  function syncDocCommentStateForActiveFile(nextComments?: ReviewComment[]): ReviewComment[] {
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

  function mergeReviewProposals(existing: ReviewProposal[], incoming: ReviewProposal[]): ReviewProposal[] {
    const merged: ReviewProposal[] = [];
    const seen = new Map<string, number>();
    function add(item: ReviewProposal, index: number): void {
      const normalized = normalizeReviewProposal(item, index);
      const key = proposalKey(normalized) || `${normalized.original_text}\n${normalized.proposed_text}\n${normalized.rationale}`;
      if (!key) return;
      if (seen.has(key)) {
        const existingIndex = seen.get(key)!;
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

  function syncProposalStateForActiveFile(proposals: ReviewProposal[], options: { replace?: boolean } = {}): ReviewProposal[] {
    const tab = activeReviewTab();
    const reviewState = ensureTabReviewState(tab);
    if (!reviewState) return [];
    const incoming = Array.isArray(proposals) ? proposals : [];
    reviewState.proposals = options.replace
      ? mergeReviewProposals([], incoming)
      : mergeReviewProposals(reviewState.proposals, incoming);
    if (tab?.serverData && typeof tab.serverData === 'object') {
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
    visibleReviewProposals,
  };
}
