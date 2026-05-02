/**
 * docx-extensions.js
 * Custom TipTap / ProseMirror extensions that preserve
 * DOCX-specific formatting attributes during round-trip HTML editing.
 */

import { Extension, Node, mergeAttributes } from '@tiptap/core';
import { Plugin, PluginKey } from 'prosemirror-state';
import { Decoration, DecorationSet } from 'prosemirror-view';
import { TableMap } from '@tiptap/pm/tables';
import { TableCell } from '@tiptap/extension-table-cell';
import { TableHeader } from '@tiptap/extension-table-header';
import { TextStyle } from '@tiptap/extension-text-style';
import Image from '@tiptap/extension-image';
import Heading from '@tiptap/extension-heading';

// ─────────────────────────────────────────────────────────────────────────────
// DocxImage
// ─────────────────────────────────────────────────────────────────────────────
export const DocxImage = Image.extend({
  addAttributes() {
    return {
      ...this.parent?.(),
      width:        { default: null, parseHTML: el => el.style.width        || el.getAttribute('width') || null },
      height:       { default: null, parseHTML: el => el.style.height       || el.getAttribute('height') || null },
      float:        { default: null, parseHTML: el => el.style.float        || null },
      objectFit:    { default: null, parseHTML: el => el.style.objectFit    || null },
      margin:       { default: null, parseHTML: el => el.style.margin       || null },
      maxWidth:     { default: null, parseHTML: el => el.style.maxWidth     || null },
      maxHeight:    { default: null, parseHTML: el => el.style.maxHeight    || null },
      borderRadius: { default: null, parseHTML: el => el.style.borderRadius || null },
    };
  },
  renderHTML({ HTMLAttributes, node }) {
    const styles = [];
    const a = node.attrs;
    if (a.width)        styles.push(`width:${a.width}`);
    if (a.height)       styles.push(`height:${a.height}`);
    if (a.float)        styles.push(`float:${a.float}`);
    if (a.objectFit)    styles.push(`object-fit:${a.objectFit}`);
    if (a.margin)       styles.push(`margin:${a.margin}`);
    if (a.maxWidth)     styles.push(`max-width:${a.maxWidth}`);
    if (a.maxHeight)    styles.push(`max-height:${a.maxHeight}`);
    if (a.borderRadius) styles.push(`border-radius:${a.borderRadius}`);
    
    const merged = mergeAttributes(this.options.HTMLAttributes, HTMLAttributes);
    if (styles.length) merged.style = styles.join(';');
    
    return ['img', merged];
  },

  // ── Interactive NodeView: resize handles + float toolbar ──────────────────
  addNodeView() {
    return ({ node, editor, getPos }) => {
      // ── Wrapper div ──────────────────────────────────────────────────
      const dom = document.createElement('div');
      dom.className = 'koto-img-wrapper';

      // Sync wrapper floating/block style from attributes
      const _applyWrapperStyle = (attrs) => {
        const f = attrs.float;
        if (f === 'left') {
          dom.style.cssText = 'float:left;display:inline-block;margin:' + (attrs.margin || '0 14px 10px 0') + ';position:relative;';
        } else if (f === 'right') {
          dom.style.cssText = 'float:right;display:inline-block;margin:' + (attrs.margin || '0 0 10px 14px') + ';position:relative;';
        } else {
          // display:block + width:fit-content ensures the wrapper hugs the image
          // instead of spanning the full editor width.  margin:auto centres it.
          dom.style.cssText = 'display:block;width:fit-content;max-width:100%;margin:' + (attrs.margin || '10px auto') + ';position:relative;';
        }
      };
      _applyWrapperStyle(node.attrs);

      // ── Image element ────────────────────────────────────────────────
      const img = document.createElement('img');
      img.style.display = 'block';
      img.draggable = false;  // prevent browser drag; we do it via ProseMirror
      const _syncImg = (attrs) => {
        img.src = attrs.src || '';
        img.alt = attrs.alt || '';
        img.style.width    = attrs.width  || 'auto';
        // Always keep height auto so the browser preserves the image's
        // natural aspect ratio.  Explicit height from DOCX extent metrics
        // is often incorrect (describes the frame, not the pixel ratio)
        // and causes stretching / letterboxing with object-fit:contain.
        img.style.height   = 'auto';
        img.style.maxWidth = '100%';
        // No object-fit override needed when height is auto.
      };
      _syncImg(node.attrs);
      dom.appendChild(img);

      // ── Float toolbar (appears on hover / selection) ──────────────────
      const toolbar = document.createElement('div');
      toolbar.className = 'koto-img-toolbar';
      toolbar.setAttribute('contenteditable', 'false');
      toolbar.innerHTML =
        '<button class="koto-img-tb-btn" data-float="left"  title="靠左浮动" aria-label="靠左">◧</button>' +
        '<button class="koto-img-tb-btn" data-float=""       title="居中显示" aria-label="居中">⊟</button>' +
        '<button class="koto-img-tb-btn" data-float="right" title="靠右浮动" aria-label="靠右">◨</button>';
      toolbar.addEventListener('mousedown', (e) => e.preventDefault());
      toolbar.addEventListener('click', (e) => {
        const btn = e.target.closest('[data-float]');
        if (!btn) return;
        e.stopPropagation();
        const newFloat = btn.dataset.float || null;
        const pos = typeof getPos === 'function' ? getPos() : null;
        if (pos == null) return;
        const newMargin = newFloat === 'left'  ? '0 14px 10px 0'
                        : newFloat === 'right' ? '0 0 10px 14px' : null;
        editor.view.dispatch(
          editor.view.state.tr.setNodeMarkup(pos, null, {
            ...node.attrs,
            float:  newFloat  || null,
            margin: newMargin || null,
          })
        );
      });
      dom.appendChild(toolbar);

      // ── Resize handles (4 corners) ────────────────────────────────────
      const CORNERS = [
        { cls: 'nw', cursor: 'nw-resize' },
        { cls: 'ne', cursor: 'ne-resize' },
        { cls: 'sw', cursor: 'sw-resize' },
        { cls: 'se', cursor: 'se-resize' },
      ];
      for (const { cls } of CORNERS) {
        const handle = document.createElement('span');
        handle.className = `koto-img-handle koto-img-handle-${cls}`;
        handle.setAttribute('contenteditable', 'false');

        handle.addEventListener('mousedown', (e) => {
          e.preventDefault();
          e.stopPropagation();

          const isLeft = cls.includes('w');
          const isTop  = cls.includes('n');
          const startX = e.clientX;
          const startY = e.clientY;
          const startW = img.offsetWidth  || parseInt(node.attrs.width)  || img.naturalWidth  || 200;
          const startH = img.offsetHeight || parseInt(node.attrs.height) || img.naturalHeight || 150;

          const onMove = (me) => {
            const dx = me.clientX - startX;
            const dy = me.clientY - startY;
            const newW = Math.max(40, startW + (isLeft ? -dx : dx));
            const newH = Math.max(30, startH + (isTop  ? -dy : dy));
            img.style.width  = newW + 'px';
            img.style.height = newH + 'px';
          };

          const onUp = () => {
            document.removeEventListener('mousemove', onMove);
            document.removeEventListener('mouseup',  onUp);
            const newW = img.offsetWidth  || startW;
            const newH = img.offsetHeight || startH;
            const pos = typeof getPos === 'function' ? getPos() : null;
            if (pos == null) return;
            editor.view.dispatch(
              editor.view.state.tr.setNodeMarkup(pos, null, {
                ...node.attrs,
                width:  newW + 'px',
                height: newH + 'px',
              })
            );
          };

          document.addEventListener('mousemove', onMove);
          document.addEventListener('mouseup',  onUp);
        });
        dom.appendChild(handle);
      }

      return {
        dom,
        // update() is called by ProseMirror when node attrs change without
        // removing/re-creating the NodeView.  Return true to accept the update.
        update(updatedNode) {
          if (updatedNode.type.name !== 'image') return false;
          node = updatedNode;
          _syncImg(node.attrs);
          _applyWrapperStyle(node.attrs);
          return true;
        },
        // stopEvent() controls which events ProseMirror should NOT handle.
        // We claim handle & toolbar events; everything else uses ProseMirror default.
        stopEvent(event) {
          return !!(event.target && event.target.closest &&
            event.target.closest('.koto-img-handle, .koto-img-toolbar'));
        },
      };
    };
  },
});


// ─────────────────────────────────────────────────────────────────────────────
// DocxParagraph
// Extends the built-in Paragraph to carry indent, line-height, and
// spacing-before/after attributes that python-docx emits.
// ─────────────────────────────────────────────────────────────────────────────
export const DocxParagraph = Node.create({
  name: 'paragraph',
  priority: 1000,
  group: 'block',
  content: 'inline*',
  addAttributes() {
    return {
      textAlign:      { default: null, parseHTML: el => el.style.textAlign      || null, renderHTML: attrs => attrs.textAlign      ? { style: `text-align:${attrs.textAlign}` }      : {} },
      marginLeft:     { default: null, parseHTML: el => el.style.marginLeft      || null, renderHTML: attrs => attrs.marginLeft      ? { style: `margin-left:${attrs.marginLeft}` }      : {} },
      marginRight:    { default: null, parseHTML: el => el.style.marginRight     || null, renderHTML: attrs => attrs.marginRight     ? { style: `margin-right:${attrs.marginRight}` }     : {} },
      marginTop:      { default: null, parseHTML: el => el.style.marginTop       || null, renderHTML: attrs => attrs.marginTop       ? { style: `margin-top:${attrs.marginTop}` }         : {} },
      marginBottom:   { default: null, parseHTML: el => el.style.marginBottom    || null, renderHTML: attrs => attrs.marginBottom    ? { style: `margin-bottom:${attrs.marginBottom}` }   : {} },
      lineHeight:     { default: null, parseHTML: el => el.style.lineHeight      || null, renderHTML: attrs => attrs.lineHeight      ? { style: `line-height:${attrs.lineHeight}` }       : {} },
      textIndent:     { default: null, parseHTML: el => el.style.textIndent      || null, renderHTML: attrs => attrs.textIndent      ? { style: `text-indent:${attrs.textIndent}` }       : {} },
      listStyleType:  { default: null, parseHTML: el => el.style.listStyleType   || el.getAttribute('data-list-style') || null, renderHTML: attrs => {} },
      paddingLeft:    { default: null, parseHTML: el => el.style.paddingLeft     || null, renderHTML: attrs => attrs.paddingLeft     ? { style: `padding-left:${attrs.paddingLeft}` }     : {} },
      fontSize:       { default: null, parseHTML: el => el.style.fontSize        || null, renderHTML: attrs => attrs.fontSize        ? { style: `font-size:${attrs.fontSize}` }           : {} },
      fontFamily:     { default: null, parseHTML: el => el.style.fontFamily      || null, renderHTML: attrs => attrs.fontFamily      ? { style: `font-family:${attrs.fontFamily}` }       : {} },
      fontWeight:     { default: null, parseHTML: el => el.style.fontWeight      || null, renderHTML: attrs => attrs.fontWeight      ? { style: `font-weight:${attrs.fontWeight}` }       : {} },
      fontStyle:      { default: null, parseHTML: el => el.style.fontStyle       || null, renderHTML: attrs => attrs.fontStyle       ? { style: `font-style:${attrs.fontStyle}` }         : {} },
      className:      { default: null, parseHTML: el => el.getAttribute('class') || null, renderHTML: attrs => attrs.className ? { class: attrs.className } : {} },
      id:             { default: null, parseHTML: el => el.getAttribute('id') || null, renderHTML: attrs => attrs.id ? { id: attrs.id } : {} },
    };
  },
  parseHTML() {
    return [{ tag: 'p' }];
  },
  renderHTML({ HTMLAttributes, node }) {
    // Merge all style attributes into one style string
    const styles = [];
    const a = node.attrs;
    if (a.textAlign)     styles.push(`text-align:${a.textAlign}`);
    if (a.marginLeft)    styles.push(`margin-left:${a.marginLeft}`);
    if (a.marginRight)   styles.push(`margin-right:${a.marginRight}`);
    if (a.marginTop)     styles.push(`margin-top:${a.marginTop}`);
    if (a.marginBottom)  styles.push(`margin-bottom:${a.marginBottom}`);
    if (a.lineHeight)    styles.push(`line-height:${a.lineHeight}`);
    if (a.textIndent)    styles.push(`text-indent:${a.textIndent}`);
    if (a.paddingLeft)   styles.push(`padding-left:${a.paddingLeft}`);
    if (a.fontSize)      styles.push(`font-size:${a.fontSize}`);
    if (a.fontFamily)    styles.push(`font-family:${a.fontFamily}`);
    if (a.fontWeight)    styles.push(`font-weight:${a.fontWeight}`);
    if (a.fontStyle)     styles.push(`font-style:${a.fontStyle}`);
    const merged = { ...HTMLAttributes };
    if (styles.length) merged.style = styles.join(';');
    return ['p', merged, 0];
  },
});

// ─────────────────────────────────────────────────────────────────────────────
// DocxTableCell
// Extends TipTap's TableCell to preserve all DOCX cell styling:
// border colours, background fill, vertical alignment, padding, colspan/rowspan.
// ─────────────────────────────────────────────────────────────────────────────
function _cellStyle(attrs) {
  const styles = [];
  if (attrs.backgroundColor) styles.push(`background-color:${attrs.backgroundColor}`);
  if (attrs.verticalAlign)   styles.push(`vertical-align:${attrs.verticalAlign}`);
  if (attrs.paddingTop)      styles.push(`padding-top:${attrs.paddingTop}`);
  if (attrs.paddingBottom)   styles.push(`padding-bottom:${attrs.paddingBottom}`);
  if (attrs.paddingLeft)     styles.push(`padding-left:${attrs.paddingLeft}`);
  if (attrs.paddingRight)    styles.push(`padding-right:${attrs.paddingRight}`);
  if (attrs.borderTop)       styles.push(`border-top:${attrs.borderTop}`);
  if (attrs.borderBottom)    styles.push(`border-bottom:${attrs.borderBottom}`);
  if (attrs.borderLeft)      styles.push(`border-left:${attrs.borderLeft}`);
  if (attrs.borderRight)     styles.push(`border-right:${attrs.borderRight}`);
  if (attrs.width)           styles.push(`width:${attrs.width}`);
  return styles.join(';');
}

const _docxCellAttrs = {
  colspan:         { default: 1 },
  rowspan:         { default: 1 },
  colwidth: {
    default: null,
    parseHTML: el => {
      const raw = el.getAttribute('data-colwidth') || el.getAttribute('colwidth');
      if (!raw) return null;
      const arr = raw.split(',').map(v => parseInt(v, 10)).filter(v => v > 0);
      return arr.length ? arr : null;
    },
    renderHTML: attrs => {
      if (!attrs.colwidth) return {};
      return { 'data-colwidth': attrs.colwidth.join(',') };
    },
  },
  backgroundColor: {
    default: null,
    parseHTML: el => el.style.backgroundColor || el.getAttribute('data-bg-color') || null,
  },
  verticalAlign: {
    default: null,
    parseHTML: el => el.style.verticalAlign || el.getAttribute('data-valign') || null,
  },
  paddingTop:    { default: null, parseHTML: el => el.style.paddingTop     || null },
  paddingBottom: { default: null, parseHTML: el => el.style.paddingBottom  || null },
  paddingLeft:   { default: null, parseHTML: el => el.style.paddingLeft    || null },
  paddingRight:  { default: null, parseHTML: el => el.style.paddingRight   || null },
  borderTop:     { default: null, parseHTML: el => el.style.borderTop      || null },
  borderBottom:  { default: null, parseHTML: el => el.style.borderBottom   || null },
  borderLeft:    { default: null, parseHTML: el => el.style.borderLeft     || null },
  borderRight:   { default: null, parseHTML: el => el.style.borderRight    || null },
  width:         { default: null, parseHTML: el => el.style.width          || null },
};

export const DocxTableCell = TableCell.extend({
  addAttributes() {
    return _docxCellAttrs;
  },
  renderHTML({ HTMLAttributes, node }) {
    const style = _cellStyle(node.attrs);
    const merged = { ...HTMLAttributes };
    if (node.attrs.colspan && node.attrs.colspan > 1) merged.colspan = node.attrs.colspan;
    if (node.attrs.rowspan && node.attrs.rowspan > 1) merged.rowspan = node.attrs.rowspan;
    if (node.attrs.colwidth) merged['data-colwidth'] = node.attrs.colwidth.join(',');
    if (style) merged.style = style;
    return ['td', merged, 0];
  },
});

export const DocxTableHeader = TableHeader.extend({
  addAttributes() {
    return _docxCellAttrs;
  },
  renderHTML({ HTMLAttributes, node }) {
    const style = _cellStyle(node.attrs);
    const merged = { ...HTMLAttributes };
    if (node.attrs.colspan && node.attrs.colspan > 1) merged.colspan = node.attrs.colspan;
    if (node.attrs.rowspan && node.attrs.rowspan > 1) merged.rowspan = node.attrs.rowspan;
    if (node.attrs.colwidth) merged['data-colwidth'] = node.attrs.colwidth.join(',');
    if (style) merged.style = style;
    return ['th', merged, 0];
  },
});

function _normalizeHdrFtrHtml(html) {
  return String(html || '')
    .replace(/<p(?:\s[^>]*)?>\s*(?:<br\s*\/?>|&nbsp;|\s)*<\/p>/gi, '')
    .replace(/&nbsp;/gi, ' ')
    .trim();
}

function _hdrFtrSlotLabel(slotType) {
  return slotType === 'footer' ? '页脚' : '页眉';
}

function _markHdrFtrOverlayActive(overlay) {
  const root = document.getElementById('wa-docx-editor') || document;
  root.querySelectorAll('.koto-hdrftr-overlay.is-active').forEach((el) => {
    if (el !== overlay) el.classList.remove('is-active');
  });
  if (overlay) overlay.classList.add('is-active');
}

function _clearHdrFtrOverlayActive(overlay) {
  if (overlay) overlay.classList.remove('is-active');
}

function _isHdrFtrToolbarInteractionLocked() {
  return Number(window.__kotoHdrFtrToolbarUntil || 0) > Date.now();
}

function _notifyHdrFtrSelectionChanged() {
  if (typeof window._kotoDocxSelectionChanged === 'function') {
    window._kotoDocxSelectionChanged();
  }
}

function _initialHdrFtrOverlayHtml(html) {
  return _normalizeHdrFtrHtml(html) ? html : '<p><br></p>';
}

function _focusHdrFtrOverlay(overlay) {
  if (!overlay || !window.getSelection || !document.createRange) return;
  const target = overlay.querySelector('p,div,li,blockquote,h1,h2,h3,h4,h5,h6') || overlay;
  if (!target) return;
  if (!target.childNodes.length) target.appendChild(document.createElement('br'));
  const range = document.createRange();
  range.selectNodeContents(target);
  range.collapse(false);
  const sel = window.getSelection();
  try {
    sel.removeAllRanges();
    sel.addRange(range);
  } catch (_) {}
}

function _setHdrFtrSlotState(slotEl, html, slotType) {
  if (!slotEl) return;
  const hasContent = !!_normalizeHdrFtrHtml(html);
  const slotLabel = _hdrFtrSlotLabel(slotType);
  slotEl.dataset.slotType = slotType;
  slotEl.dataset.slotLabel = slotLabel;
  slotEl.title = `双击编辑${slotLabel}`;
  slotEl.classList.toggle('is-empty', !hasContent);
  slotEl.innerHTML = hasContent ? html : '';
}

// ─────────────────────────────────────────────────────────────────────────────
// DocxPageBreak
// An in-flow block node that creates REAL vertical space between pages.
// Instead of a z-index overlay, the NodeView renders a full structural
// gap: bottom-margin zone → gray gap → top-margin zone, each occupying
// actual height in the document so content is never hidden behind them.
//
// Header / footer HTML is supplied via extension storage after the editor
// is created:
//   editor.storage.docxPageBreak.headerHtml = '<p>…</p>';
//   editor.storage.docxPageBreak.footerHtml = '<p>…</p>';
// ─────────────────────────────────────────────────────────────────────────────
export const DocxPageBreak = Node.create({
  name: 'docxPageBreak',
  group: 'block',
  atom: true,
  selectable: false,

  addStorage() {
    return { headerHtml: '', footerHtml: '' };
  },

  addAttributes() {
    return {
      page: { default: 1 },
    };
  },

  parseHTML() {
    return [{ tag: 'div[data-page-break]' }];
  },

  // renderHTML is used ONLY when serializing back to HTML for saving.
  // The NodeView below handles all visual rendering in the editor.
  renderHTML({ HTMLAttributes }) {
    return ['div', mergeAttributes(HTMLAttributes, {
      'data-page-break': '',
      class: 'koto-page-break',
      contenteditable: 'false',
    })];
  },

  addNodeView() {
    return ({ node, editor }) => {
      // ── Root wrapper ─────────────────────────────────────────────────
      const dom = document.createElement('div');
      dom.setAttribute('data-page-break', '');
      dom.className = 'koto-page-break';
      dom.setAttribute('contenteditable', 'false');

      const pageNum = node.attrs.page || 1;

      // ── Bottom zone of the upper page (white, with footer) ───────────
      const endZone = document.createElement('div');
      endZone.className = 'koto-pb-end';

      // Footer content
      const footerEl = document.createElement('div');
      footerEl.className = 'koto-pb-footer';
      _setHdrFtrSlotState(footerEl, '', 'footer');
      endZone.appendChild(footerEl);

      dom.appendChild(endZone);

      // ── Gap between pages (canvas-colored separator) ─────────────────
      const gapZone = document.createElement('div');
      gapZone.className = 'koto-pb-gap';
      dom.appendChild(gapZone);

      // ── Top zone of the next page (white, with header) ───────────────
      const startZone = document.createElement('div');
      startZone.className = 'koto-pb-start';

      // Header content
      const headerEl = document.createElement('div');
      headerEl.className = 'koto-pb-header';
      _setHdrFtrSlotState(headerEl, '', 'header');
      startZone.appendChild(headerEl);

      dom.appendChild(startZone);

      // ── Click-to-edit overlay for header/footer ───────────────────────
      const _openOverlay = (targetEl, type) => {
        if (targetEl.querySelector('.koto-hdrftr-overlay')) return;
        targetEl.classList.add('is-editing');
        const overlay = document.createElement('div');
        overlay.className = 'koto-hdrftr-overlay';
        overlay.setAttribute('contenteditable', 'true');
        overlay.dataset.slotType = type;
        overlay.innerHTML = _normalizeHdrFtrHtml(targetEl.innerHTML) ? targetEl.innerHTML : '<p></p>';
        const overlayOutline = type === 'header'
          ? 'outline:none;outline-offset:0;'
          : 'outline:1px dashed rgba(79,126,255,.5);outline-offset:-1px;';
        overlay.style.cssText = `position:absolute;top:0;left:0;right:0;bottom:0;z-index:10;background:#fff;padding:inherit;box-sizing:border-box;${overlayOutline}`;

        const _finish = () => {
          const newHtml = _normalizeHdrFtrHtml(overlay.innerHTML) ? overlay.innerHTML : '';
          overlay.remove();
          targetEl.classList.remove('is-editing');
          _setHdrFtrSlotState(targetEl, newHtml, type);
          if (editor.storage?.docxPageBreak) editor.storage.docxPageBreak[type === 'header' ? 'headerHtml' : 'footerHtml'] = newHtml;
          if (editor.storage?.autoPageBreak) {
            const storageKey = type === 'header' ? 'headerHtml' : 'footerHtml';
            editor.storage.autoPageBreak[storageKey] = newHtml;
            if (Array.isArray(editor.storage.autoPageBreak.sections)) {
              editor.storage.autoPageBreak.sections.forEach((section) => {
                if (section && typeof section === 'object') {
                  section[type === 'header' ? 'header_html' : 'footer_html'] = newHtml;
                }
              });
            }
          }
          const root = dom.closest('#wa-docx-editor');
          if (!root) return;
          root.querySelectorAll(type === 'header' ? '.koto-pb-header' : '.koto-pb-footer').forEach((sib) => {
            if (sib !== targetEl) _setHdrFtrSlotState(sib, newHtml, type);
          });
          const flEl = root.querySelector(type === 'header' ? '.koto-page-header-first' : '.koto-page-footer-last');
          if (flEl && flEl.dataset.variant !== 'first') {
            _setHdrFtrSlotState(flEl, newHtml, type);
          }
        };

        overlay.addEventListener('blur', _finish);
        overlay.addEventListener('keydown', (e) => {
          if (e.key === 'Escape') { overlay.blur(); }
          if (e.key === 'Enter') { e.preventDefault(); document.execCommand('insertLineBreak'); }
        });
        targetEl.appendChild(overlay);
        overlay.focus();
      };

      headerEl.addEventListener('dblclick', (e) => { e.stopPropagation(); _openOverlay(headerEl, 'header'); });
      footerEl.addEventListener('dblclick', (e) => { e.stopPropagation(); _openOverlay(footerEl, 'footer'); });

      // ── Deferred header/footer injection ─────────────────────────────
      // storage.docxPageBreak is set by render() AFTER new Editor() returns,
      // so NodeViews created during parsing read empty defaults.  Retry on
      // rAF and again at 200ms to guarantee content is filled.
      const _injectHdrFtr = () => {
        const hdr = editor.storage?.docxPageBreak?.headerHtml || '';
        const ftr = editor.storage?.docxPageBreak?.footerHtml || '';
        if (!footerEl.querySelector('.koto-hdrftr-overlay')) {
          _setHdrFtrSlotState(footerEl, ftr, 'footer');
        }
        if (!headerEl.querySelector('.koto-hdrftr-overlay')) {
          _setHdrFtrSlotState(headerEl, hdr, 'header');
        }
      };
      _injectHdrFtr();
      requestAnimationFrame(_injectHdrFtr);
      setTimeout(_injectHdrFtr, 200);

      return {
        dom,
        update(updatedNode) {
          if (updatedNode.type.name !== 'docxPageBreak') return false;
          if (updatedNode.type.name !== 'docxPageBreak') return false;
          _injectHdrFtr();
          return true;
        },
        stopEvent() { return true; },
      };
    };
  },
});

// ─────────────────────────────────────────────────────────────────────────────
// DocxHeading
// Extends the built-in Heading to preserve `id` and `class` attributes
// from DOCX bookmarks, enabling TOC anchor navigation (#_Toc... links).
// ─────────────────────────────────────────────────────────────────────────────
export const DocxHeading = Heading.extend({
  addAttributes() {
    return {
      ...this.parent?.(),
      id:        { default: null, parseHTML: el => el.getAttribute('id') || null, renderHTML: attrs => attrs.id ? { id: attrs.id } : {} },
      className: { default: null, parseHTML: el => el.getAttribute('class') || null, renderHTML: attrs => attrs.className ? { class: attrs.className } : {} },
      style:     { default: null, parseHTML: el => el.getAttribute('style') || null, renderHTML: attrs => attrs.style ? { style: attrs.style } : {} },
    };
  },
});

// ─────────────────────────────────────────────────────────────────────────────
// TocTab
// Inline atom node that preserves <span class="koto-toc-tab"></span> in TOC
// paragraphs.  The backend emits this empty span for tab characters inside TOC
// entries; CSS renders it as a flex-grow spacer with dot-leader ::after content.
// Without this extension ProseMirror would strip the unrecognised span entirely,
// causing dot leaders and right-aligned page numbers to vanish.
// ─────────────────────────────────────────────────────────────────────────────
export const TocTab = Node.create({
  name: 'tocTab',
  group: 'inline',
  inline: true,
  atom: true,          // non-editable, no text content
  selectable: false,
  parseHTML() {
    return [{ tag: 'span.koto-toc-tab' }];
  },
  renderHTML() {
    return ['span', { class: 'koto-toc-tab' }];
  },
});

// ─────────────────────────────────────────────────────────────────────────────
// FontSize extension
// Adds `fontSize` mark via TextStyle so any span with font-size CSS is preserved.
// ─────────────────────────────────────────────────────────────────────────────
function _normalizeFontSize(value) {
  const raw = String(value || '').trim();
  if (!raw) return null;
  const match = raw.match(/^(-?\d+(?:\.\d+)?)([a-z%]*)$/i);
  if (!match) return null;
  const numeric = parseFloat(match[1]);
  if (!Number.isFinite(numeric) || numeric <= 0) return null;
  const rounded = Math.round(numeric * 10) / 10;
  const formatted = Number.isInteger(rounded)
    ? String(rounded)
    : String(rounded).replace(/\.0$/, '');
  return `${formatted}pt`;
}

export const FontSize = Extension.create({
  name: 'fontSize',

  addCommands() {
    return {
      setFontSize: fontSize => ({ chain }) => {
        const normalized = _normalizeFontSize(fontSize);
        if (!normalized) return false;
        return chain().setMark('textStyle', { fontSize: normalized }).run();
      },

      unsetFontSize: () => ({ chain }) => {
        return chain().setMark('textStyle', { fontSize: null }).removeEmptyTextStyle().run();
      },
    };
  },

  addGlobalAttributes() {
    return [
      {
        types: ['textStyle'],
        attributes: {
          fontSize: {
            default: null,
            parseHTML: el => el.style.fontSize || null,
            renderHTML: attrs => {
              if (!attrs.fontSize) return {};
              return { style: `font-size:${attrs.fontSize}` };
            },
          },
        },
      },
    ];
  },
});

// ─────────────────────────────────────────────────────────────────────────────
// LineHeight extension
// Adds `lineHeight` mark via TextStyle
// ─────────────────────────────────────────────────────────────────────────────
export const LineHeight = Extension.create({
  name: 'lineHeight',
  addGlobalAttributes() {
    return [
      {
        types: ['textStyle'],
        attributes: {
          lineHeight: {
            default: null,
            parseHTML: el => el.style.lineHeight || null,
            renderHTML: attrs => {
              if (!attrs.lineHeight) return {};
              return { style: `line-height:${attrs.lineHeight}` };
            },
          },
        },
      },
    ];
  },
});

// ─────────────────────────────────────────────────────────────────────────────
// AutoPageBreakPlugin
//
// A ProseMirror-based TipTap Extension that measures each top-level block's
// rendered height and inserts WORD-LIKE soft page breaks as widget decorations
// (not real nodes) whenever cumulative content height exceeds one page's
// content area.
//
// Key design decisions:
//   - Widget decorations (not real nodes): soft breaks never appear in the
//     serialized HTML or DOCX export. Only explicit <w:br type="page"/> breaks
//     become real DocxPageBreak nodes.
//   - Block-level only: breaks at block (paragraph / table / image) boundaries,
//     not mid-line. This avoids font-metric calculations while still producing
//     a layout close to Word's Print Layout view.
//   - No overlay: all break visuals are in-flow (display:block inside
//     .ProseMirror), so content is never hidden behind a z-index overlay.
//   - Explicit DocxPageBreak nodes coexist: when encountered, they reset the
//     height accumulator (page counter advances via the NodeView itself).
//
// Configuration (set on editor.storage.autoPageBreak after render()):
//   pageHeightPx     — full page height in CSS pixels (default: 1056 US-Letter)
//   marginTopPx      — top margin in px (default: 96)
//   marginBottomPx   — bottom margin in px (default: 80)
//   headerHtml       — HTML string for page header (shown in each break zone)
//   footerHtml       — HTML string for page footer (shown in each break zone)
//   onPageCountChange — optional callback(totalPages) called after each recalc
// ─────────────────────────────────────────────────────────────────────────────

const _AUTO_PB_KEY = new PluginKey('autoPageBreak');

/** Build the DOM element rendered for each soft page break widget. */
function _buildSoftBreakWidget(pageNum, headerHtml, footerHtml, marginTopPx, marginBottomPx, marginLeftPx, marginRightPx, pageWidthPx, extStorage) {
  const dom = document.createElement('div');
  dom.setAttribute('data-soft-page-break', String(pageNum));
  dom.className = 'koto-page-break';
  dom.setAttribute('contenteditable', 'false');
  // Cancel ProseMirror's horizontal padding so the page break spans the full page width
  const mL = marginLeftPx || 96;
  const mR = marginRightPx || 96;
  dom.style.marginLeft = `-${mL}px`;
  dom.style.marginRight = `-${mR}px`;

  // ── Bottom zone of ending page (white footer area) ──────────────────────
  const endZone = document.createElement('div');
  endZone.className = 'koto-pb-end';
  if (marginBottomPx) endZone.style.height = marginBottomPx + 'px';
  endZone.style.setProperty('--koto-docx-marker-left', `${Math.max(24, mL - 12)}px`);
  endZone.style.setProperty('--koto-docx-marker-right', `${Math.max(24, mR - 12)}px`);

  const footerEl = document.createElement('div');
  footerEl.className = 'koto-pb-footer';
  footerEl.style.padding = `0 ${mL}px 0 ${mR}px`;
  _setHdrFtrSlotState(footerEl, footerHtml, 'footer');
  endZone.appendChild(footerEl);

  dom.appendChild(endZone);

  // ── Gray gap between pages ───────────────────────────────────────────────
  const gapZone = document.createElement('div');
  gapZone.className = 'koto-pb-gap';
  dom.appendChild(gapZone);

  // ── Top zone of starting page (white header area) ────────────────────────
  const startZone = document.createElement('div');
  startZone.className = 'koto-pb-start';
  if (marginTopPx) startZone.style.height = marginTopPx + 'px';
  startZone.style.setProperty('--koto-docx-marker-left', `${Math.max(24, mL - 12)}px`);
  startZone.style.setProperty('--koto-docx-marker-right', `${Math.max(24, mR - 12)}px`);

  const headerEl = document.createElement('div');
  headerEl.className = 'koto-pb-header';
  headerEl.style.padding = `0 ${mL}px 0 ${mR}px`;
  _setHdrFtrSlotState(headerEl, headerHtml, 'header');
  startZone.appendChild(headerEl);

  dom.appendChild(startZone);

  // ── Click-to-edit: double-click opens an overlay editor ──────────────────
  const _openOverlay = (targetEl, type) => {
    // Prevent duplicate overlays
    if (targetEl.querySelector('.koto-hdrftr-overlay')) return;
    targetEl.classList.add('is-editing');
    const overlay = document.createElement('div');
    overlay.className = 'koto-hdrftr-overlay';
    overlay.setAttribute('contenteditable', 'true');
    overlay.dataset.slotType = type;
    overlay.innerHTML = _initialHdrFtrOverlayHtml(targetEl.innerHTML);
    const overlayOutline = type === 'header'
      ? 'outline:none;outline-offset:0;'
      : 'outline:1px dashed rgba(79,126,255,.5);outline-offset:-1px;';
    overlay.style.cssText = `position:absolute;top:0;left:0;right:0;bottom:0;z-index:10;background:#fff;padding:inherit;box-sizing:border-box;${overlayOutline}`;

    const _finish = () => {
      const newHtml = _normalizeHdrFtrHtml(overlay.innerHTML) ? overlay.innerHTML : '';
      _clearHdrFtrOverlayActive(overlay);
      overlay.remove();
      targetEl.classList.remove('is-editing');
      _setHdrFtrSlotState(targetEl, newHtml, type);
      const storageKey = type === 'header' ? 'headerHtml' : 'footerHtml';
      if (extStorage) extStorage[storageKey] = newHtml;
      if (extStorage && Array.isArray(extStorage.sections)) {
        extStorage.sections.forEach((section) => {
          if (section && typeof section === 'object') {
            section[type === 'header' ? 'header_html' : 'footer_html'] = newHtml;
          }
        });
      }
      // Sync to all header/footer instances
      const root = dom.closest('#wa-docx-editor');
      if (!root) return;
      const cls = type === 'header' ? '.koto-pb-header' : '.koto-pb-footer';
      root.querySelectorAll(cls).forEach((sib) => {
        if (sib !== targetEl) _setHdrFtrSlotState(sib, newHtml, type);
      });
      const flCls = type === 'header' ? '.koto-page-header-first' : '.koto-page-footer-last';
      const flEl = root.querySelector(flCls);
      if (flEl && flEl.dataset.variant !== 'first') {
        _setHdrFtrSlotState(flEl, newHtml, type);
      }
      _notifyHdrFtrSelectionChanged();
    };

    const _syncSelection = () => {
      _markHdrFtrOverlayActive(overlay);
      _notifyHdrFtrSelectionChanged();
    };

    overlay.addEventListener('focus', _syncSelection);
    overlay.addEventListener('mouseup', () => requestAnimationFrame(_syncSelection));
    overlay.addEventListener('keyup', _syncSelection);
    overlay.addEventListener('input', _syncSelection);
    overlay.addEventListener('blur', () => {
      requestAnimationFrame(() => {
        if (!overlay.isConnected || _isHdrFtrToolbarInteractionLocked()) return;
        _finish();
      });
    });
    overlay.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') { overlay.blur(); }
      if (e.key === 'Enter') { e.preventDefault(); document.execCommand('insertLineBreak'); }
    });
    targetEl.appendChild(overlay);
    _markHdrFtrOverlayActive(overlay);
    overlay.focus();
    requestAnimationFrame(() => _focusHdrFtrOverlay(overlay));
  };

  headerEl.addEventListener('dblclick', (e) => { e.stopPropagation(); _openOverlay(headerEl, 'header'); });
  footerEl.addEventListener('dblclick', (e) => { e.stopPropagation(); _openOverlay(footerEl, 'footer'); });

  return dom;
}

function _measureRelativeLeftPx(element, ancestor) {
  if (!element || !ancestor || !element.getBoundingClientRect || !ancestor.getBoundingClientRect) {
    return 0;
  }
  const ancestorRect = ancestor.getBoundingClientRect();
  const elementRect = element.getBoundingClientRect();
  const scaleX = ancestor.offsetWidth ? ancestorRect.width / ancestor.offsetWidth : 1;
  if (!Number.isFinite(scaleX) || scaleX <= 0) {
    return 0;
  }
  return Math.max(0, (elementRect.left - ancestorRect.left) / scaleX);
}

function _buildSoftBreakTableRow(pageNum, columnCount, headerHtml, footerHtml, marginTopPx, marginBottomPx, marginLeftPx, marginRightPx, pageWidthPx, extStorage, tableLeftOffsetPx) {
  const row = document.createElement('tr');
  row.className = 'koto-table-page-break-row';
  row.setAttribute('data-soft-page-break', String(pageNum));
  row.setAttribute('contenteditable', 'false');

  const cell = document.createElement('td');
  cell.className = 'koto-table-page-break-cell';
  cell.colSpan = Math.max(1, columnCount || 1);
  cell.setAttribute('contenteditable', 'false');

  const widget = _buildSoftBreakWidget(
    pageNum,
    headerHtml,
    footerHtml,
    marginTopPx,
    marginBottomPx,
    marginLeftPx,
    marginRightPx,
    pageWidthPx,
    extStorage,
  );
  widget.style.marginLeft = `${-Math.round(tableLeftOffsetPx || 0)}px`;
  widget.style.marginRight = '0';
  widget.style.position = 'relative';
  widget.style.left = '0';
  widget.style.transform = 'none';
  if (pageWidthPx) {
    widget.style.width = pageWidthPx + 'px';
    widget.style.maxWidth = pageWidthPx + 'px';
  }

  cell.appendChild(widget);
  row.appendChild(cell);
  return row;
}

export const AutoPageBreakPlugin = Extension.create({
  name: 'autoPageBreak',

  addStorage() {
    return {
      pageWidthPx:       null,
      pageHeightPx:      null,
      marginTopPx:       null,
      marginBottomPx:    null,
      marginLeftPx:      null,
      marginRightPx:     null,
      headerHtml:        '',
      footerHtml:        '',
      sections:          [],      // per-section header/footer data from backend
      totalPages:        1,
      onPageCountChange: null,
    };
  },

  addProseMirrorPlugins() {
    const extStorage = this.storage;  // mutable reference, updated by KotoTipTapEditor

    return [new Plugin({
      key: _AUTO_PB_KEY,

      // ── Plugin state: holds the current DecorationSet ──────────────────
      state: {
        init() {
          return DecorationSet.empty;
        },
        apply(tr, decoSet) {
          // When measurement result arrives (via setMeta), replace the set
          const newSet = tr.getMeta(_AUTO_PB_KEY);
          if (newSet !== undefined) return newSet;
          // Otherwise map existing decorations through any content changes
          if (!tr.docChanged) return decoSet;
          return decoSet.map(tr.mapping, tr.doc);
        },
      },

      // ── Provide decorations to ProseMirror ─────────────────────────────
      props: {
        decorations(state) {
          return _AUTO_PB_KEY.getState(state);
        },
      },

      // ── View plugin: triggers measurement after DOM settles ────────────
      view(editorView) {
        let _timer = null;
        let _measuring = false;  // guard against re-entrant measurement

        const _schedule = () => {
          clearTimeout(_timer);
          _timer = setTimeout(() => {
            requestAnimationFrame(() => _measure(editorView));
          }, 320);
        };

        const _measure = (view) => {
          if (_measuring) return;
          _measuring = true;
          try {
            _measureInner(view);
          } finally {
            _measuring = false;
          }
        };

        const _measureInner = (view) => {
          const doc    = view.state.doc;
          const pmDom  = view.dom;  // the .ProseMirror editable div

          // ── Read config from extension storage ──────────────────────────
          const pageW      = extStorage.pageWidthPx    || 816;
          const pageH      = extStorage.pageHeightPx   || 1056;
          const mTop       = extStorage.marginTopPx    || 96;
          const mBot       = extStorage.marginBottomPx || 80;
          const mLeft      = extStorage.marginLeftPx   || 96;
          const mRight     = extStorage.marginRightPx  || 96;
          const hdrHtml    = extStorage.headerHtml     || '';
          const ftrHtml    = extStorage.footerHtml     || '';
          const sectionsAr = extStorage.sections       || [];

          // ── Content height per page ────────────────────────────────────
          // In Word, headers/footers are positioned within the margin areas
          // (between page edge and margin boundary).  They do NOT reduce the
          // usable content area unless they overflow the margin, which is
          // rare.  Content area = page_height - top_margin - bottom_margin.
          const contentH   = pageH - mTop - mBot;

          // ── First pass: clear existing widget decorations ──────────────
          // This is crucial! Without clearing, the measurement includes the
          // height of old page break widgets, causing incorrect results.
          // We dispatch an empty decoration set first, then measure after
          // the DOM has updated.
          const currentDecos = _AUTO_PB_KEY.getState(view.state);
          if (currentDecos && currentDecos !== DecorationSet.empty) {
            view.dispatch(view.state.tr.setMeta(_AUTO_PB_KEY, DecorationSet.empty));
            // After clearing decorations, wait for DOM to update before measuring
            requestAnimationFrame(() => {
              requestAnimationFrame(() => {
                _measureClean(view);
              });
            });
            return;
          }

          _measureClean(view);
        };

        const _measureClean = (view) => {
          const doc    = view.state.doc;
          const pmDom  = view.dom;

          const pageW      = extStorage.pageWidthPx    || 816;
          const pageH      = extStorage.pageHeightPx   || 1056;
          const mTop       = extStorage.marginTopPx    || 96;
          const mBot       = extStorage.marginBottomPx || 80;
          const mLeft      = extStorage.marginLeftPx   || 96;
          const mRight     = extStorage.marginRightPx  || 96;
          const hdrHtml    = extStorage.headerHtml     || '';
          const ftrHtml    = extStorage.footerHtml     || '';
          const sectionsAr = extStorage.sections       || [];
          const contentH   = pageH - mTop - mBot;

          const docNodes = [];
          doc.content.forEach((node, start) => {
            docNodes.push({ node, start });
          });

          const pmChildren = Array.from(pmDom.children);
          let pmIdx = 0;

          const breaks = [];   // { pos, pageNum, sectionIdx, tableCols?, tableLeftOffsetPx? }
          let pageNum = 1;
          let usedH = 0;
          let curSection = 0;

          for (const { node, start } of docNodes) {
            while (
              pmIdx < pmChildren.length &&
              (pmChildren[pmIdx].hasAttribute('data-soft-page-break') ||
               pmChildren[pmIdx].hasAttribute('data-page-break'))
            ) {
              pmIdx++;
            }
            const domEl = pmChildren[pmIdx];
            pmIdx++;

            if (!domEl) break;

            if (node.type.name === 'docxPageBreak') {
              const si = node.attrs.sectionIdx;
              if (si != null && si >= 0) curSection = si;
              pageNum++;
              usedH = 0;
              continue;
            }

            if (node.type.name === 'table') {
              const tableEl = domEl?.tagName === 'TABLE'
                ? domEl
                : domEl?.querySelector?.('table');
              const domRows = tableEl ? Array.from(tableEl.rows || []) : [];
              const pmRows = [];

              node.forEach((rowNode, rowOffset) => {
                if (rowNode.type?.name === 'tableRow') {
                  pmRows.push({ pos: start + 1 + rowOffset });
                }
              });

              if (domRows.length && domRows.length === pmRows.length) {
                const tableCols = Math.max(1, TableMap.get(node).width || 1);

                for (let rowIdx = 0; rowIdx < domRows.length; rowIdx++) {
                  const rowEl = domRows[rowIdx];
                  const rowPos = pmRows[rowIdx]?.pos;
                  if (rowPos == null) continue;

                  // When previous rows span into this row, the synthetic break
                  // cell is laid out after those carried columns. Anchor to the
                  // row's first rendered cell instead of the table edge so the
                  // full-width widget still snaps back to the page left edge.
                  const rowAnchorEl = rowEl.cells && rowEl.cells.length
                    ? rowEl.cells[0]
                    : tableEl;
                  const tableLeftOffsetPx = _measureRelativeLeftPx(rowAnchorEl, pmDom);

                  const rowH = rowEl.offsetHeight || 0;
                  if (rowH <= 0) continue;

                  const remaining = contentH - usedH;
                  if (usedH > 0 && rowH > remaining) {
                    breaks.push({
                      pos: rowPos,
                      pageNum,
                      sectionIdx: curSection,
                      tableCols,
                      tableLeftOffsetPx,
                    });
                    pageNum++;
                    usedH = rowH;
                  } else {
                    usedH += rowH;
                    if (usedH >= contentH) {
                      const overflow = usedH - contentH;
                      if (overflow > 0) {
                        const extra = Math.floor(overflow / contentH);
                        pageNum += 1 + extra;
                        usedH = overflow % contentH;
                      } else {
                        pageNum++;
                        usedH = 0;
                      }
                    }
                  }
                }
                continue;
              }
            }

            let blockH = domEl.offsetHeight;
            try {
              const cs = window.getComputedStyle(domEl);
              blockH += parseFloat(cs.marginTop || 0) + parseFloat(cs.marginBottom || 0);
            } catch (_) {}

            if (blockH <= 0) continue;

            const remaining = contentH - usedH;
            if (usedH > 0 && blockH > remaining) {
              breaks.push({ pos: start, pageNum, sectionIdx: curSection });
              pageNum++;

              if (blockH > contentH) {
                const extra = Math.floor(blockH / contentH);
                pageNum += extra;
                usedH = blockH % contentH;
                if (usedH === 0) usedH = contentH;
              } else {
                usedH = blockH;
              }
            } else {
              usedH += blockH;
              if (usedH >= contentH) {
                const overflow = usedH - contentH;
                if (overflow > 0) {
                  const extra = Math.floor(overflow / contentH);
                  pageNum += 1 + extra;
                  usedH = overflow % contentH;
                } else {
                  pageNum++;
                  usedH = 0;
                }
              }
            }
          }

          const total = pageNum;
          extStorage.totalPages = total;
          if (typeof extStorage.onPageCountChange === 'function') {
            extStorage.onPageCountChange(total);
          }

          let decoSet;
          if (breaks.length === 0) {
            decoSet = DecorationSet.empty;
          } else {
            const decos = breaks.map(({ pos, pageNum: pn, sectionIdx: si, tableCols, tableLeftOffsetPx }) => {
              const sec = sectionsAr[si] || sectionsAr[0] || {};
              const _hdr = sec.header_html || hdrHtml;
              const _ftr = sec.footer_html || ftrHtml;
              return Decoration.widget(
                pos,
                () => {
                  const breakDom = tableCols
                    ? _buildSoftBreakTableRow(pn, tableCols, _hdr, _ftr, mTop, mBot, mLeft, mRight, pageW, extStorage, tableLeftOffsetPx)
                    : _buildSoftBreakWidget(pn, _hdr, _ftr, mTop, mBot, mLeft, mRight, pageW, extStorage);
                  breakDom.querySelectorAll('.koto-hdr-page-num').forEach(el => {
                    el.textContent = String(pn);
                    el.setAttribute('contenteditable', 'false');
                  });
                  return breakDom;
                },
                {
                  side:             -1,
                  key:              `spb-${pos}-${pn}`,
                  stopEvent:        () => true,
                  ignoreSelection:  true,
                  destroy:          (dom) => { dom.remove(); },
                },
              );
            });
            decoSet = DecorationSet.create(doc, decos);
          }

          view.dispatch(view.state.tr.setMeta(_AUTO_PB_KEY, decoSet));
        };

        _schedule();
        extStorage._forceRecalc = () => _schedule();

        return {
          update(view, prevState) {
            // Only re-measure when doc content changed (not on meta dispatches)
            if (view.state.doc !== prevState.doc) {
              _schedule();
            }
          },
          destroy() {
            clearTimeout(_timer);
            extStorage._forceRecalc = null;
          },
        };
      },
    })];
  },
});
