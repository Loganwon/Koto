import { describe, expect, it, vi } from 'vitest';

import { createReviewState } from './state';


describe('review state performance', () => {
  it('normalizes a large server review payload only once per array version', () => {
    const comments = Array.from({ length: 400 }, (_, index) => ({
      id: `c-${index}`,
      text: `comment ${index}`,
      anchor_text: `anchor ${index}`,
    }));
    const proposals = Array.from({ length: 300 }, (_, index) => ({
      id: `p-${index}`,
      original_text: `before ${index}`,
      proposed_text: `after ${index}`,
    }));
    const tab: any = {
      path: 'large-reviewed.docx',
      fileType: 'docx',
      serverData: { comments, proposals },
      reviewState: { comments: [], proposals: [], focusedId: '', expandedId: '' },
    };
    const state: any = {
      openTabs: [tab],
      activeTabPath: tab.path,
      fileType: 'docx',
    };
    const cloneSerializable = vi.fn((value: any, fallback: any) => {
      try { return JSON.parse(JSON.stringify(value)); } catch (_) { return fallback; }
    });
    const runtime = createReviewState({ state, cloneSerializable });

    const first = runtime.ensureTabReviewState(tab);
    const clonesAfterFirstPass = cloneSerializable.mock.calls.length;
    const second = runtime.ensureTabReviewState(tab);

    expect(first).toBe(second);
    expect(clonesAfterFirstPass).toBe(comments.length + proposals.length);
    expect(cloneSerializable).toHaveBeenCalledTimes(clonesAfterFirstPass);
  });

  it('renormalizes only the review array explicitly replaced by the caller', () => {
    const tab: any = {
      path: 'reviewed.docx',
      fileType: 'docx',
      serverData: {
        comments: [{ id: 'c-1', text: 'one' }],
        proposals: [{ id: 'p-1', original_text: 'a', proposed_text: 'b' }],
      },
      reviewState: { comments: [], proposals: [], focusedId: '', expandedId: '' },
    };
    const state: any = { openTabs: [tab], activeTabPath: tab.path, fileType: 'docx' };
    const cloneSerializable = vi.fn((value: any) => JSON.parse(JSON.stringify(value)));
    const runtime = createReviewState({ state, cloneSerializable });
    runtime.ensureTabReviewState(tab);
    const initialCalls = cloneSerializable.mock.calls.length;

    runtime.syncDocCommentStateForActiveFile([
      { id: 'c-2', text: 'two' },
      { id: 'c-3', text: 'three' },
    ]);
    const callsAfterReplace = cloneSerializable.mock.calls.length;
    runtime.ensureTabReviewState(tab);

    expect(callsAfterReplace - initialCalls).toBe(2);
    expect(cloneSerializable).toHaveBeenCalledTimes(callsAfterReplace);
  });
});
