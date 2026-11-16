export const DOCX_REVIEW_CARD_RENDER_BUDGET = 120;
export const DOCX_REVIEW_NAV_RENDER_BUDGET = 80;

export function reviewRenderWindow<T extends { id: string }>(
  entries: T[],
  focusedId: string,
): { entries: T[]; start: number } {
  if (entries.length <= DOCX_REVIEW_CARD_RENDER_BUDGET) {
    return { entries, start: 0 };
  }
  const normalizedFocus = String(focusedId || '').trim().replace(/^(comment|proposal):/, '');
  const focusedIndex = entries.findIndex((entry) => (
    entry.id === focusedId
    || entry.id.replace(/^(comment|proposal):/, '') === normalizedFocus
  ));
  const centerIndex = focusedIndex >= 0 ? focusedIndex : 0;
  const maxStart = entries.length - DOCX_REVIEW_CARD_RENDER_BUDGET;
  const start = Math.max(
    0,
    Math.min(maxStart, centerIndex - Math.floor(DOCX_REVIEW_CARD_RENDER_BUDGET / 2)),
  );
  return {
    entries: entries.slice(start, start + DOCX_REVIEW_CARD_RENDER_BUDGET),
    start,
  };
}

export function reviewNavWindow<T>(
  entries: T[],
  query: string,
  searchableText: (entry: T) => string,
): { entries: T[]; matched: number; total: number } {
  const normalizedQuery = String(query || '').trim().toLocaleLowerCase();
  const matches = normalizedQuery
    ? entries.filter((entry) => searchableText(entry).toLocaleLowerCase().includes(normalizedQuery))
    : entries;
  return {
    entries: matches.slice(0, DOCX_REVIEW_NAV_RENDER_BUDGET),
    matched: matches.length,
    total: entries.length,
  };
}
