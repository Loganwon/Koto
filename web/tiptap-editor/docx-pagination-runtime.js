const _DEFAULT_PAGE_LAYOUT = {
  pageWidthPx: 816,
  pageHeightPx: 1056,
  marginTopPx: 96,
  marginBottomPx: 80,
  marginLeftPx: 96,
  marginRightPx: 96,
};

function _toFiniteNumber(value, fallback) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : fallback;
}

function _hasRenderableChromeHtml(html) {
  if (html == null) return false;
  const raw = String(html).trim();
  if (!raw) return false;
  const withoutTags = raw
    .replace(/<br\s*\/?>/gi, '')
    .replace(/&nbsp;/gi, ' ')
    .replace(/<[^>]+>/g, '')
    .trim();
  return withoutTags.length > 0;
}

function _pickSection(source, sectionIdx = 0) {
  const sections = Array.isArray(source?.sections) ? source.sections : [];
  const numericIdx = Math.max(0, Number.parseInt(sectionIdx, 10) || 0);
  return {
    section: sections[numericIdx] || sections[0] || {},
    sectionIdx: sections[numericIdx] ? numericIdx : 0,
  };
}

function _resolveSlotHtml(source, section, pageNum, slotType) {
  const defaultKey = slotType === 'header' ? 'header_html' : 'footer_html';
  const firstKey = slotType === 'header' ? 'first_header_html' : 'first_footer_html';
  const evenKey = slotType === 'header' ? 'even_header_html' : 'even_footer_html';
  const globalKey = slotType === 'header' ? 'headerHtml' : 'footerHtml';

  const firstHtml = section?.[firstKey] || '';
  if (pageNum === 1 && _hasRenderableChromeHtml(firstHtml)) {
    return { html: firstHtml, variant: 'first' };
  }

  const evenHtml = section?.[evenKey] || '';
  if ((pageNum % 2) === 0 && _hasRenderableChromeHtml(evenHtml)) {
    return { html: evenHtml, variant: 'even' };
  }

  const defaultHtml = section?.[defaultKey] || source?.[globalKey] || '';
  return { html: defaultHtml, variant: 'default' };
}

export function resolveDocxPageChrome(source, pageNum = 1, sectionIdx = 0) {
  const safePageNum = Math.max(1, Number.parseInt(pageNum, 10) || 1);
  const { section, sectionIdx: resolvedSectionIdx } = _pickSection(source, sectionIdx);

  return {
    pageNum: safePageNum,
    sectionIdx: resolvedSectionIdx,
    pageWidthPx: _toFiniteNumber(section?.page_width_px, _toFiniteNumber(source?.pageWidthPx, _DEFAULT_PAGE_LAYOUT.pageWidthPx)),
    pageHeightPx: _toFiniteNumber(section?.page_height_px, _toFiniteNumber(source?.pageHeightPx, _DEFAULT_PAGE_LAYOUT.pageHeightPx)),
    marginTopPx: _toFiniteNumber(section?.margin_top_px, _toFiniteNumber(source?.marginTopPx, _DEFAULT_PAGE_LAYOUT.marginTopPx)),
    marginBottomPx: _toFiniteNumber(section?.margin_bottom_px, _toFiniteNumber(source?.marginBottomPx, _DEFAULT_PAGE_LAYOUT.marginBottomPx)),
    marginLeftPx: _toFiniteNumber(section?.margin_left_px, _toFiniteNumber(source?.marginLeftPx, _DEFAULT_PAGE_LAYOUT.marginLeftPx)),
    marginRightPx: _toFiniteNumber(section?.margin_right_px, _toFiniteNumber(source?.marginRightPx, _DEFAULT_PAGE_LAYOUT.marginRightPx)),
    ...(() => {
      const header = _resolveSlotHtml(source, section, safePageNum, 'header');
      const footer = _resolveSlotHtml(source, section, safePageNum, 'footer');
      return {
        headerHtml: header.html,
        headerVariant: header.variant,
        footerHtml: footer.html,
        footerVariant: footer.variant,
      };
    })(),
  };
}

export function resolveDocxBreakChrome(source, pageNum = 1, currentSectionIdx = 0, nextSectionIdx = currentSectionIdx) {
  const currentPage = resolveDocxPageChrome(source, pageNum, currentSectionIdx);
  const nextPage = resolveDocxPageChrome(source, currentPage.pageNum + 1, nextSectionIdx);

  return {
    pageNum: currentPage.pageNum,
    currentSectionIdx: currentPage.sectionIdx,
    nextSectionIdx: nextPage.sectionIdx,
    pageWidthPx: currentPage.pageWidthPx,
    pageHeightPx: currentPage.pageHeightPx,
    marginTopPx: currentPage.marginTopPx,
    marginBottomPx: currentPage.marginBottomPx,
    marginLeftPx: currentPage.marginLeftPx,
    marginRightPx: currentPage.marginRightPx,
    currentPage,
    nextPage,
  };
}