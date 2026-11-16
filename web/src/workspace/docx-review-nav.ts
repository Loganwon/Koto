import { _escHtml } from './infrastructure';
import {
  DOCX_REVIEW_NAV_RENDER_BUDGET,
  reviewNavWindow,
} from './docx-review-window';

type ReviewNavEntry = {
  id: string;
  item: Record<string, any>;
};

function clean(value: any): string {
  return String(value == null ? '' : value).trim();
}

export function renderReviewNavMenu(
  allEntries: ReviewNavEntry[],
  query: string,
  previewText: (value: any, limit?: number) => string,
): void {
  const nav = document.querySelector('#wa-docx-editor .wa-docx-review-nav') as HTMLElement | null;
  const menu = nav?.querySelector('.wa-docx-review-nav-menu') as HTMLElement | null;
  const summary = nav?.querySelector('.wa-docx-review-summary') as HTMLButtonElement | null;
  if (!nav || !menu || !summary) return;
  const open = summary.getAttribute('aria-expanded') === 'true';
  if (!open) {
    menu.replaceChildren();
    nav.classList.remove('is-open');
    return;
  }
  const windowed = reviewNavWindow(
    allEntries,
    query,
    (entry) => clean(entry.item.anchor_text || entry.item.text || entry.id),
  );
  const countText = windowed.matched > DOCX_REVIEW_NAV_RENDER_BUDGET
    ? `显示前 ${windowed.entries.length} 条，共匹配 ${windowed.matched} / ${windowed.total} 条`
    : `显示 ${windowed.entries.length} / ${windowed.total} 条`;
  const items = windowed.entries.map((entry) => (
    `<button type="button" class="wa-docx-review-nav-item" data-review-nav-id="${_escHtml(entry.id)}">${_escHtml(previewText(entry.item.anchor_text || entry.item.text || entry.id, 40))}</button>`
  )).join('');
  menu.innerHTML = `
    <div class="wa-docx-review-nav-search">
      <input class="wa-docx-review-nav-search-input" type="search" value="${_escHtml(query)}" placeholder="搜索批注原文" aria-label="搜索批注和修订">
      <button type="button" class="wa-docx-review-nav-clear" aria-label="清除搜索" ${query ? '' : 'disabled'}>×</button>
    </div>
    <div class="wa-docx-review-nav-count">${_escHtml(countText)}</div>
    ${items || '<div class="wa-docx-review-nav-empty">没有匹配的批注或修订</div>'}`;
  menu.dataset.reviewNavTotal = String(windowed.total);
  menu.dataset.reviewNavMatched = String(windowed.matched);
  menu.dataset.reviewNavRendered = String(windowed.entries.length);
  nav.classList.add('is-open');
}
