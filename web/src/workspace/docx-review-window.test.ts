import { describe, expect, it } from 'vitest';

import {
  DOCX_REVIEW_NAV_RENDER_BUDGET,
  reviewNavWindow,
  reviewRenderWindow,
} from './docx-review-window';

describe('DOCX review windows', () => {
  const entries = Array.from({ length: 500 }, (_, index) => ({
    id: `comment:${index}`,
    text: `Review anchor ${String(index).padStart(4, '0')}`,
  }));

  it('bounds the review rail around a far focused item', () => {
    const result = reviewRenderWindow(entries, 'comment:499');
    expect(result.entries).toHaveLength(120);
    expect(result.start).toBe(380);
    expect(result.entries.at(-1)?.id).toBe('comment:499');
  });

  it('bounds navigation DOM and still finds a far item through search', () => {
    const initial = reviewNavWindow(entries, '', (entry) => entry.text);
    expect(initial.entries).toHaveLength(DOCX_REVIEW_NAV_RENDER_BUDGET);
    expect(initial.total).toBe(500);
    expect(initial.matched).toBe(500);

    const searched = reviewNavWindow(entries, 'anchor 0499', (entry) => entry.text);
    expect(searched.entries.map((entry) => entry.id)).toEqual(['comment:499']);
    expect(searched.matched).toBe(1);
  });
});
