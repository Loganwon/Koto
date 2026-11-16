import { describe, expect, it, vi } from 'vitest';
import {
  createFileTaskUiState,
  ensureTaskUiState,
  hydrateTaskUiStateFromDom,
  noteTaskStreamIssue,
} from './task-ui-state';

describe('task UI state', () => {
  it('creates isolated default state for every task card', () => {
    const first = createFileTaskUiState();
    const second = createFileTaskUiState();

    first.readKeys.add('workspace/source.docx');
    expect(second.readKeys.size).toBe(0);
    expect(first.streamConnectionState).toBe('connected');
    expect(first.waitNoticeLevel).toBe('none');
    expect(first.domHydrated).toBe(false);
  });

  it('hydrates singleton rows, code summaries and read paths once', () => {
    const card = document.createElement('article');
    card.innerHTML = `
      <section class="wa-task-step">
        <div class="wa-task-row" data-role="code:python">代码完成</div>
        <div class="wa-task-row" data-role="read-files">
          <button data-file-path="workspace/source.docx">source.docx</button>
        </div>
        <div class="wa-task-row" data-role="stream-issue">同步提示</div>
      </section>
    `;
    const state = createFileTaskUiState();

    hydrateTaskUiStateFromDom(card, state);
    const step = card.querySelector('.wa-task-step') as HTMLElement & {
      _singletonRows?: Map<string, HTMLElement>;
    };

    expect(state.domHydrated).toBe(true);
    expect(state.codeSummaryRows.has('code:python')).toBe(true);
    expect(state.readKeys).toEqual(new Set(['workspace/source.docx']));
    expect(state.streamIssueRow?.dataset.role).toBe('stream-issue');
    expect((step as any)._singletonRows.size).toBe(3);

    card.querySelector('[data-role="read-files"]')?.remove();
    hydrateTaskUiStateFromDom(card, state);
    expect(state.readKeys).toEqual(new Set(['workspace/source.docx']));
  });

  it('caches card state and deduplicates stream issue counters', () => {
    const card = document.createElement('article');
    const debug = vi.spyOn(console, 'debug').mockImplementation(() => {});

    const first = ensureTaskUiState(card);
    const second = ensureTaskUiState(card);
    noteTaskStreamIssue(card, 'duplicate-run-1', 'duplicate');
    noteTaskStreamIssue(card, 'duplicate-run-1', 'duplicate');

    expect(second).toBe(first);
    expect(card.dataset.taskStreamIssueCount).toBe('1');
    expect(first.streamIssueKeys).toEqual(new Set(['duplicate-run-1']));
    expect(debug).toHaveBeenCalledTimes(1);
    debug.mockRestore();
  });

  it('returns a detached hydrated state for invalid cards', () => {
    const state = ensureTaskUiState(null as any);
    expect(state.domHydrated).toBe(true);
    expect(state.processedEventKeys.size).toBe(0);
  });
});
