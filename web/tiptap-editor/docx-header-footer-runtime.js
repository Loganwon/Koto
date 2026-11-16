/** Shared header/footer DOM helpers used by explicit and automatic pagination. */

export function normalizeHdrFtrHtml(html) {
  return String(html || '')
    .replace(/<p(?:\s[^>]*)?>\s*(?:<br\s*\/?>|&nbsp;|\s)*<\/p>/gi, '')
    .replace(/&nbsp;/gi, ' ')
    .trim();
}

export function hdrFtrSlotLabel(slotType) {
  return slotType === 'footer' ? '页脚' : '页眉';
}

export function markHdrFtrOverlayActive(overlay) {
  const root = document.getElementById('wa-docx-editor') || document;
  root.querySelectorAll('.koto-hdrftr-overlay.is-active').forEach((element) => {
    if (element !== overlay) element.classList.remove('is-active');
  });
  if (overlay) overlay.classList.add('is-active');
}

export function clearHdrFtrOverlayActive(overlay) {
  if (overlay) overlay.classList.remove('is-active');
}

export function isHdrFtrToolbarInteractionLocked() {
  return Number(window.__kotoHdrFtrToolbarUntil || 0) > Date.now();
}

export function notifyHdrFtrSelectionChanged() {
  if (typeof window._kotoDocxSelectionChanged === 'function') {
    window._kotoDocxSelectionChanged();
  }
  try { window.dispatchEvent(new CustomEvent('koto-hdrftr-changed')); } catch (_) {}
}

export function initialHdrFtrOverlayHtml(html) {
  return normalizeHdrFtrHtml(html) ? html : '<p><br></p>';
}

export function focusHdrFtrOverlay(overlay) {
  if (!overlay || !window.getSelection || !document.createRange) return;
  const target = overlay.querySelector('p,div,li,blockquote,h1,h2,h3,h4,h5,h6') || overlay;
  if (!target) return;
  if (!target.childNodes.length) target.appendChild(document.createElement('br'));
  const range = document.createRange();
  range.selectNodeContents(target);
  range.collapse(false);
  const selection = window.getSelection();
  try {
    selection.removeAllRanges();
    selection.addRange(range);
  } catch (_) {}
}

export function setHdrFtrSlotState(slotElement, html, slotType) {
  if (!slotElement) return;
  const hasContent = !!normalizeHdrFtrHtml(html);
  const slotLabel = hdrFtrSlotLabel(slotType);
  slotElement.dataset.slotType = slotType;
  slotElement.dataset.slotLabel = slotLabel;
  slotElement.title = `双击编辑${slotLabel}`;
  slotElement.classList.toggle('is-empty', !hasContent);
  slotElement.innerHTML = hasContent ? html : '';
}
