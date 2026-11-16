/**
 * docx-extensions.js
 * Custom TipTap / ProseMirror extensions that preserve
 * DOCX-specific formatting attributes during round-trip HTML editing.
 */

import { Extension, Mark, Node, mergeAttributes } from '@tiptap/core';
import { NodeSelection, Plugin, PluginKey } from '@tiptap/pm/state';
import { Decoration, DecorationSet } from '@tiptap/pm/view';
import {
  ResizeState,
  TableMap,
  cellAround,
  columnResizingPluginKey,
  pointsAtCell,
  tableEditing,
  tableNodeTypes,
  updateColumnsOnResize,
} from '@tiptap/pm/tables';
import { Table, TableView } from '@tiptap/extension-table';
import { TableRow } from '@tiptap/extension-table-row';
import { TableCell } from '@tiptap/extension-table-cell';
import { TableHeader } from '@tiptap/extension-table-header';
import { TextStyle } from '@tiptap/extension-text-style';
import Image from '@tiptap/extension-image';
import Heading from '@tiptap/extension-heading';
import { resolveDocxBreakChrome } from './docx-pagination-runtime.js';
import { createDocxPaginationScheduler } from './docx-pagination-scheduler.js';

// ─────────────────────────────────────────────────────────────────────────────
// DocxImage
// ─────────────────────────────────────────────────────────────────────────────
function _docxNormalizeImageLayout(layoutValue) {
  const value = String(layoutValue || '').trim().toLowerCase();

  if (!value) return '';
  if (value === 'top-bottom') return 'top-bottom-center';
  if (
    value === 'inline'
    || value === 'square-left'
    || value === 'square-center'
    || value === 'square-right'
    || value === 'tight-left'
    || value === 'tight-center'
    || value === 'tight-right'
    || value === 'top-bottom-left'
    || value === 'top-bottom-center'
    || value === 'top-bottom-right'
  ) {
    return value;
  }

  return '';
}

function _docxImageLayoutContainer(el) {
  const parent = el?.parentElement || null;
  if (!parent) return null;

  if (
    parent.hasAttribute('data-koto-layout')
    || parent.hasAttribute('data-koto-wrap')
    || parent.hasAttribute('data-koto-side')
  ) {
    return parent;
  }

  if (parent.childElementCount !== 1 || parent.firstElementChild !== el) {
    return null;
  }

  if (
    parent.style.float
    || parent.style.display
    || parent.style.textAlign
    || parent.style.position
    || parent.style.left
    || parent.style.top
    || parent.style.margin
  ) {
    return parent;
  }

  return null;
}

function _docxImageStyleValue(el, prop) {
  return String(el?.style?.[prop] || '').trim().toLowerCase();
}

function _docxImageStyleRaw(el, prop) {
  return String(el?.style?.[prop] || '').trim();
}

function _docxImageStyleAttr(el, prop, { preferContainer = false } = {}) {
  const container = _docxImageLayoutContainer(el);
  const sources = preferContainer
    ? [container, el]
    : [el, container];

  for (const source of sources) {
    const value = _docxImageStyleRaw(source, prop);
    if (value) return value;
  }

  return null;
}

function _docxComposeImageLayout(wrapMode, align = '') {
  const wrap = String(wrapMode || '').trim().toLowerCase();
  const side = String(align || '').trim().toLowerCase();

  if (wrap === 'inline') return 'inline';
  if (wrap === 'square') {
    if (side === 'left' || side === 'center' || side === 'right') return `square-${side}`;
    return 'square-right';
  }
  if (wrap === 'tight') {
    if (side === 'left' || side === 'center' || side === 'right') return `tight-${side}`;
    return 'tight-right';
  }
  if (wrap === 'top-bottom') {
    if (side === 'left' || side === 'right') return `top-bottom-${side}`;
    return 'top-bottom-center';
  }

  return '';
}

function _docxImageLayoutStateFromLayout(layoutValue) {
  const layout = _docxNormalizeImageLayout(layoutValue);

  switch (layout) {
    case 'inline':
      return { wrapMode: 'inline', align: 'center' };
    case 'square-left':
      return { wrapMode: 'square', align: 'left' };
    case 'square-center':
      return { wrapMode: 'square', align: 'center' };
    case 'square-right':
      return { wrapMode: 'square', align: 'right' };
    case 'tight-left':
      return { wrapMode: 'tight', align: 'left' };
    case 'tight-center':
      return { wrapMode: 'tight', align: 'center' };
    case 'tight-right':
      return { wrapMode: 'tight', align: 'right' };
    case 'top-bottom-left':
      return { wrapMode: 'top-bottom', align: 'left' };
    case 'top-bottom-right':
      return { wrapMode: 'top-bottom', align: 'right' };
    case 'top-bottom-center':
      return { wrapMode: 'top-bottom', align: 'center' };
    default:
      return null;
  }
}

function _docxImageLayoutSupportsAlign(wrapMode, align) {
  if (wrapMode === 'inline') return false;
  if (wrapMode === 'square' || wrapMode === 'tight') {
    return align === 'left' || align === 'center' || align === 'right';
  }
  if (wrapMode === 'top-bottom') {
    return align === 'left' || align === 'center' || align === 'right';
  }
  return false;
}

function _docxDefaultImageMargin(wrapMode, align) {
  if (wrapMode === 'square') {
    if (align === 'center') return '4px auto 12px';
    return align === 'left' ? '0 16px 12px 0' : '0 0 12px 16px';
  }
  if (wrapMode === 'tight') {
    if (align === 'center') return '4px auto 8px';
    return align === 'left' ? '0 10px 8px 0' : '0 0 8px 10px';
  }
  if (wrapMode === 'top-bottom') {
    if (align === 'left') return '10px auto 10px 0';
    if (align === 'right') return '10px 0 10px auto';
    return '10px auto';
  }
  return '0 6px';
}

function _docxImageLayoutStateFromAttrs(attrs = {}) {
  const explicit = _docxImageLayoutStateFromLayout(attrs.layout);
  if (explicit) return explicit;

  const float = String(attrs.float || '').trim().toLowerCase();
  if (float === 'left') return { wrapMode: 'square', align: 'left' };
  if (float === 'right') return { wrapMode: 'square', align: 'right' };

  if (String(attrs.display || '').trim().toLowerCase() === 'block') {
    return { wrapMode: 'top-bottom', align: 'center' };
  }

  return { wrapMode: 'inline', align: 'center' };
}

function _docxImageLayoutFromElement(el) {
  const container = _docxImageLayoutContainer(el);
  const explicit = _docxNormalizeImageLayout(
    container?.getAttribute('data-koto-layout') || el.getAttribute('data-koto-layout')
  );
  if (explicit) return explicit;

  const wrapMode = String(
    container?.getAttribute('data-koto-wrap') || el.getAttribute('data-koto-wrap') || ''
  ).trim().toLowerCase();
  const align = String(
    container?.getAttribute('data-koto-side') || el.getAttribute('data-koto-side') || ''
  ).trim().toLowerCase();
  const composed = _docxComposeImageLayout(wrapMode, align);
  if (composed) return composed;

  const float = _docxImageStyleValue(container, 'float') || _docxImageStyleValue(el, 'float');
  if (float === 'left') return 'square-left';
  if (float === 'right') return 'square-right';

  const display = _docxImageStyleValue(container, 'display') || _docxImageStyleValue(el, 'display');
  const position = _docxImageStyleValue(container, 'position');
  const width = _docxImageStyleValue(container, 'width');
  const height = _docxImageStyleValue(container, 'height');
  const left = _docxImageStyleRaw(container, 'left');
  const top = _docxImageStyleRaw(container, 'top');

  // Imported DOCX encodes wrapNone/anchored drawings as a zero-sized relative
  // wrapper with left/top offsets. Treat those as unsupported floating imports
  // instead of misclassifying them as top/bottom-wrapped images.
  const looksAnchored = !!container
    && display === 'block'
    && position === 'relative'
    && (width === '0px' || width === '0')
    && (height === '0px' || height === '0')
    && (left || top);
  if (looksAnchored) return 'inline';

  if (display === 'block') {
    const textAlign = _docxImageStyleValue(container, 'textAlign');
    if (textAlign === 'left') return 'top-bottom-left';
    if (textAlign === 'right') return 'top-bottom-right';
    return 'top-bottom-center';
  }

  return 'inline';
}

function _docxBuildImageLayoutAttrs(attrs, nextState) {
  const wrapMode = String(nextState?.wrapMode || '').trim().toLowerCase() || 'inline';
  let align = String(nextState?.align || '').trim().toLowerCase() || 'center';
  const centeredWrappedImage = (wrapMode === 'square' || wrapMode === 'tight') && align === 'center';

  if (!_docxImageLayoutSupportsAlign(wrapMode, align)) {
    align = wrapMode === 'top-bottom' ? 'center' : 'right';
  }

  return {
    ...attrs,
    layout: _docxComposeImageLayout(wrapMode, align),
    float: wrapMode === 'square' || wrapMode === 'tight'
      ? (align === 'left' || align === 'right' ? align : null)
      : null,
    display: wrapMode === 'top-bottom' || centeredWrappedImage ? 'block' : null,
    margin: _docxDefaultImageMargin(wrapMode, align),
    verticalAlign: wrapMode === 'inline' ? 'baseline' : null,
  };
}

function _docxImageWrapperStyle(attrs) {
  const { wrapMode, align } = _docxImageLayoutStateFromAttrs(attrs);
  const margin = attrs.margin || _docxDefaultImageMargin(wrapMode, align);

  if (wrapMode === 'square' || wrapMode === 'tight') {
    if (align === 'center') {
      return [
        'display:block',
        'width:fit-content',
        'max-width:100%',
        'clear:both',
        `margin:${margin}`,
        'position:relative',
      ].join(';');
    }

    return [
      `float:${align === 'left' ? 'left' : 'right'}`,
      'display:inline-block',
      `margin:${margin}`,
      'position:relative',
    ].join(';');
  }

  if (wrapMode === 'top-bottom' || attrs.display === 'block') {
    return [
      'display:block',
      'width:fit-content',
      'max-width:100%',
      'clear:both',
      `margin:${margin}`,
      'position:relative',
    ].join(';');
  }

  return [
    'display:inline-block',
    'max-width:100%',
    `margin:${margin}`,
    `vertical-align:${attrs.verticalAlign || 'baseline'}`,
    'position:relative',
  ].join(';');
}

function _docxImageWrapLabel(wrapMode) {
  if (wrapMode === 'square') return '四周环绕';
  if (wrapMode === 'tight') return '紧密环绕';
  if (wrapMode === 'top-bottom') return '上下环绕';
  return '与文字同行';
}

function _docxImageAlignLabel(align) {
  if (align === 'left') return '靠左';
  if (align === 'right') return '靠右';
  return '居中';
}

function _docxImageLayoutStatusText(attrs) {
  const state = _docxImageLayoutStateFromAttrs(attrs);
  if (state.wrapMode === 'inline') return '当前: 与文字同行';
  return `当前: ${_docxImageWrapLabel(state.wrapMode)} · ${_docxImageAlignLabel(state.align)}`;
}

export const DocxImage = Image.extend({
  inline() {
    return true;
  },

  group() {
    return 'inline';
  },

  addAttributes() {
    return {
      ...this.parent?.(),
      layout:       {
        default: null,
        parseHTML: el => _docxImageLayoutFromElement(el),
      },
      width:        { default: null, parseHTML: el => el.style.width        || el.getAttribute('width') || null },
      height:       { default: null, parseHTML: el => el.style.height       || el.getAttribute('height') || null },
      float:        { default: null, parseHTML: el => _docxImageStyleAttr(el, 'float', { preferContainer: true }) },
      display:      { default: null, parseHTML: el => _docxImageStyleAttr(el, 'display', { preferContainer: true }) },
      verticalAlign:{ default: null, parseHTML: el => el.style.verticalAlign || null },
      objectFit:    { default: null, parseHTML: el => el.style.objectFit    || null },
      margin:       { default: null, parseHTML: el => _docxImageStyleAttr(el, 'margin', { preferContainer: true }) },
      maxWidth:     { default: null, parseHTML: el => el.style.maxWidth     || null },
      maxHeight:    { default: null, parseHTML: el => el.style.maxHeight    || null },
      borderRadius: { default: null, parseHTML: el => el.style.borderRadius || null },
    };
  },
  renderHTML({ HTMLAttributes, node }) {
    const styles = [];
    const a = node.attrs;
    const layoutState = _docxImageLayoutStateFromAttrs(a);
    const canonicalLayout = _docxComposeImageLayout(layoutState.wrapMode, layoutState.align);
    if (a.width)        styles.push(`width:${a.width}`);
    if (a.height)       styles.push(`height:${a.height}`);
    if (a.float)        styles.push(`float:${a.float}`);
    if (a.display)      styles.push(`display:${a.display}`);
    if (a.verticalAlign) styles.push(`vertical-align:${a.verticalAlign}`);
    if (a.objectFit)    styles.push(`object-fit:${a.objectFit}`);
    if (a.margin)       styles.push(`margin:${a.margin}`);
    if (a.maxWidth)     styles.push(`max-width:${a.maxWidth}`);
    if (a.maxHeight)    styles.push(`max-height:${a.maxHeight}`);
    if (a.borderRadius) styles.push(`border-radius:${a.borderRadius}`);

    const merged = mergeAttributes(this.options.HTMLAttributes, HTMLAttributes);
    if (canonicalLayout) merged['data-koto-layout'] = canonicalLayout;
    merged['data-koto-wrap'] = layoutState.wrapMode;
    if (layoutState.wrapMode !== 'inline') merged['data-koto-side'] = layoutState.align;
    if (styles.length) merged.style = styles.join(';');

    return ['img', merged];
  },

  // ── Interactive NodeView: resize handles + Word-like layout toolbar ──────
  addNodeView() {
    return ({ node, editor, getPos }) => {
      const UI_HIDE_DELAY_MS = 1200;
      const dom = document.createElement('span');
      dom.className = 'koto-img-wrapper';
      let uiHideTimer = null;
      let isHoverUiVisible = false;
      let isNodeSelected = false;
      let isToolbarOpen = false;
      let toolbarTrigger = null;

      const _clearUiHideTimer = () => {
        if (uiHideTimer != null) {
          window.clearTimeout(uiHideTimer);
          uiHideTimer = null;
        }
      };

      const _syncUiState = () => {
        const shouldShowUi = isHoverUiVisible || isNodeSelected || isToolbarOpen;
        dom.classList.toggle('is-ui-visible', shouldShowUi);
        dom.classList.toggle('selected', isNodeSelected);
        dom.classList.toggle('is-toolbar-open', isToolbarOpen);
        if (toolbarTrigger) {
          toolbarTrigger.setAttribute('aria-expanded', isToolbarOpen ? 'true' : 'false');
        }
      };

      const _setHoverUiVisible = (visible) => {
        isHoverUiVisible = !!visible;
        _syncUiState();
      };

      const _setNodeSelected = (selected) => {
        isNodeSelected = !!selected;
        if (!isNodeSelected && isToolbarOpen) _setToolbarOpen(false);
        _syncUiState();
      };

      const _setToolbarOpen = (open) => {
        isToolbarOpen = !!open;
        if (isToolbarOpen) {
          isHoverUiVisible = true;
          _clearUiHideTimer();
          // Portal: mount toolbar on body so it is completely outside the
          // transform:scale() zoom wrapper (fixed positioning only works
          // relative to the viewport when no transform ancestor is present).
          const bodyEl = (dom.ownerDocument || document).body;
          if (!toolbar.parentNode) bodyEl.appendChild(toolbar);
          toolbar.style.display = 'block';
          requestAnimationFrame(_updateFixedToolbarPos);
          window.addEventListener('scroll', _updateFixedToolbarPos, { passive: true, capture: true });
          window.addEventListener('resize', _updateFixedToolbarPos, { passive: true });
        } else {
          toolbar.style.display = 'none';
          window.removeEventListener('scroll', _updateFixedToolbarPos, { capture: true });
          window.removeEventListener('resize', _updateFixedToolbarPos);
          if (!isNodeSelected) {
            isHoverUiVisible = false;
          }
        }
        _syncUiState();
      };

      const _showUi = () => {
        _clearUiHideTimer();
        _setHoverUiVisible(true);
      };

      const _scheduleUiHide = () => {
        if (isNodeSelected || isToolbarOpen) return;
        _clearUiHideTimer();
        uiHideTimer = window.setTimeout(() => {
          _setHoverUiVisible(false);
          uiHideTimer = null;
        }, UI_HIDE_DELAY_MS);
      };

      // Position through Koto's shared painted/logical coordinate contract.
      const _updateFixedToolbarPos = () => {
        if (!isToolbarOpen || !toolbarTrigger) return;
        const triggerRect = toolbarTrigger.getBoundingClientRect();
        const panelRect = toolbar.getBoundingClientRect();
        const panelW = panelRect.width || 284;
        const panelH = panelRect.height || 340;
        const viewport = window.KotoUiScale.getVisualViewportBounds();
        // Prefer opening below the trigger; flip above when space is tight.
        const spaceBelow = viewport.bottom - triggerRect.bottom - 12;
        let topPx = spaceBelow >= Math.min(panelH, 240)
          ? triggerRect.bottom + 8
          : Math.max(viewport.top + 8, triggerRect.top - panelH - 8);
        // Align right edge with trigger right edge, clamped to viewport.
        const leftPx = triggerRect.right - panelW;
        toolbar.style.position = 'fixed';
        window.KotoUiScale.placeFixedInViewport(toolbar, leftPx, topPx, 8);
        toolbar.style.right = 'auto';
        toolbar.style.bottom = 'auto';
      };

      const _isInsideTableCell = () => !!dom.closest('td,th');

      const _applyWrapperStyle = (attrs) => {
        const state = _docxImageLayoutStateFromAttrs(attrs);
        dom.dataset.layout = _docxComposeImageLayout(state.wrapMode, state.align);
        dom.dataset.scope = _isInsideTableCell() ? 'table' : 'body';
        dom.style.cssText = _docxImageWrapperStyle(attrs);
      };
      _applyWrapperStyle(node.attrs);

      const img = document.createElement('img');
      img.className = 'koto-docx-img';
      img.style.display = 'block';
      img.draggable = false;
      const _syncImg = (attrs) => {
        img.src = attrs.src || '';
        img.alt = attrs.alt || '';
        img.style.width = attrs.width || 'auto';
        img.style.height = attrs.height || 'auto';
        img.style.maxWidth = attrs.maxWidth || '100%';
        img.style.maxHeight = attrs.maxHeight || '';
        img.style.objectFit = attrs.objectFit || 'contain';
        img.style.borderRadius = attrs.borderRadius || '';
        img.style.verticalAlign = attrs.verticalAlign || '';
      };
      _syncImg(node.attrs);
      dom.appendChild(img);

      const _focusImageNodeSelection = () => {
        const pos = typeof getPos === 'function' ? getPos() : null;
        if (pos == null) return;

        editor.view.focus();

        let tr = editor.view.state.tr;
        try {
          tr = tr.setSelection(NodeSelection.create(tr.doc, pos));
        } catch (_) {}

        editor.view.dispatch(tr);
        _setNodeSelected(true);
      };

      toolbarTrigger = document.createElement('button');
      toolbarTrigger.type = 'button';
      toolbarTrigger.className = 'koto-img-toolbar-trigger';
      toolbarTrigger.setAttribute('contenteditable', 'false');
      toolbarTrigger.setAttribute('aria-label', '打开图片布局选项');
      toolbarTrigger.setAttribute('title', '图片布局选项');
      toolbarTrigger.innerHTML = `
        <span class="koto-img-toolbar-trigger-icon" aria-hidden="true"></span>
        <span class="koto-img-toolbar-trigger-label">布局选项</span>
      `;
      toolbarTrigger.addEventListener('mouseenter', _showUi);
      toolbarTrigger.addEventListener('mouseleave', _scheduleUiHide);
      toolbarTrigger.addEventListener('mousedown', (e) => e.preventDefault());
      toolbarTrigger.addEventListener('pointerdown', (e) => {
        e.preventDefault();
        e.stopPropagation();
        _focusImageNodeSelection();
        _setToolbarOpen(!isToolbarOpen);
      });
      dom.appendChild(toolbarTrigger);

      const toolbar = document.createElement('div');
      toolbar.className = 'koto-img-toolbar';
      toolbar.setAttribute('contenteditable', 'false');
      toolbar.innerHTML = `
        <div class="koto-img-toolbar-header">
          <div class="koto-img-toolbar-title">图片布局</div>
          <div class="koto-img-toolbar-status" data-role="status"></div>
        </div>
        <div class="koto-img-toolbar-section">
          <div class="koto-img-toolbar-label">文字环绕</div>
          <div class="koto-img-toolbar-grid" role="group" aria-label="文字环绕">
            <button type="button" class="koto-img-layout-card" data-wrap="inline" aria-label="与文字同行">
              <span class="koto-img-layout-preview" aria-hidden="true"></span>
              <span class="koto-img-layout-title">同行</span>
              <span class="koto-img-layout-copy">嵌入段落</span>
            </button>
            <button type="button" class="koto-img-layout-card" data-wrap="square" aria-label="四周环绕">
              <span class="koto-img-layout-preview" aria-hidden="true"></span>
              <span class="koto-img-layout-title">四周</span>
              <span class="koto-img-layout-copy">矩形绕排</span>
            </button>
            <button type="button" class="koto-img-layout-card" data-wrap="tight" aria-label="紧密环绕">
              <span class="koto-img-layout-preview" aria-hidden="true"></span>
              <span class="koto-img-layout-title">紧密</span>
              <span class="koto-img-layout-copy">更贴近文字</span>
            </button>
            <button type="button" class="koto-img-layout-card" data-wrap="top-bottom" aria-label="上下环绕">
              <span class="koto-img-layout-preview" aria-hidden="true"></span>
              <span class="koto-img-layout-title">上下</span>
              <span class="koto-img-layout-copy">段前段后绕排</span>
            </button>
          </div>
        </div>
        <div class="koto-img-toolbar-section">
          <div class="koto-img-toolbar-label">图片位置</div>
          <div class="koto-img-position-group" role="group" aria-label="图片位置">
            <button type="button" class="koto-img-pos-btn" data-align="left" aria-label="靠左">靠左</button>
            <button type="button" class="koto-img-pos-btn" data-align="center" aria-label="居中">居中</button>
            <button type="button" class="koto-img-pos-btn" data-align="right" aria-label="靠右">靠右</button>
          </div>
          <div class="koto-img-toolbar-note" data-role="scope"></div>
        </div>
      `;

      const statusEl = toolbar.querySelector('[data-role="status"]');
      const scopeEl = toolbar.querySelector('[data-role="scope"]');

      const _syncToolbarState = (attrs) => {
        const state = _docxImageLayoutStateFromAttrs(attrs);
        const insideTable = _isInsideTableCell();

        toolbar.dataset.scope = insideTable ? 'table' : 'body';
        toolbar.dataset.wrap = state.wrapMode;
        toolbar.dataset.align = state.align;

        toolbar.querySelectorAll('[data-wrap]').forEach((button) => {
          const isActive = button.dataset.wrap === state.wrapMode;
          button.classList.toggle('active', isActive);
          button.setAttribute('aria-pressed', isActive ? 'true' : 'false');
        });

        toolbar.querySelectorAll('[data-align]').forEach((button) => {
          const supported = _docxImageLayoutSupportsAlign(state.wrapMode, button.dataset.align);
          const isActive = supported && button.dataset.align === state.align;
          button.disabled = !supported;
          button.classList.toggle('is-disabled', !supported);
          button.classList.toggle('active', isActive);
          button.setAttribute('aria-pressed', isActive ? 'true' : 'false');
        });

        if (statusEl) statusEl.textContent = _docxImageLayoutStatusText(attrs);
        if (scopeEl) {
          let noteText = insideTable
            ? '表格内仅影响当前单元格中的文本环绕'
            : '正文图片会按所选环绕方式影响后续段落';
          if ((state.wrapMode === 'square' || state.wrapMode === 'tight') && state.align === 'center') {
            noteText += '；居中为网页近似效果';
          }
          scopeEl.textContent = noteText;
        }
      };

      const _applyLayoutUpdate = (nextState) => {
        const pos = typeof getPos === 'function' ? getPos() : null;
        if (pos == null) return;

        const nextAttrs = _docxBuildImageLayoutAttrs(node.attrs, nextState);
        editor.view.focus();

        let tr = editor.view.state.tr.setNodeMarkup(pos, null, nextAttrs);
        try {
          tr = tr.setSelection(NodeSelection.create(tr.doc, pos));
        } catch (_) {}

        editor.view.dispatch(tr.scrollIntoView());
        _applyWrapperStyle(nextAttrs);
        _syncToolbarState(nextAttrs);
        _showUi();
        requestAnimationFrame(_updateFixedToolbarPos);
      };

      toolbar.addEventListener('mousedown', (e) => e.preventDefault());
      toolbar.addEventListener('pointerdown', (e) => {
        const wrapBtn = e.target.closest('[data-wrap]');
        const alignBtn = e.target.closest('[data-align]');

        if (!wrapBtn && !alignBtn) return;

        e.preventDefault();
        e.stopPropagation();

        const currentState = _docxImageLayoutStateFromAttrs(node.attrs);

        if (wrapBtn) {
          const nextWrapMode = wrapBtn.dataset.wrap || 'inline';
          let nextAlign = currentState.align;
          if (!_docxImageLayoutSupportsAlign(nextWrapMode, nextAlign)) {
            nextAlign = nextWrapMode === 'top-bottom' ? 'center' : 'right';
          }
          // For float modes (square/tight), 'center' produces a display:block element (no float).
          // When inheriting 'center' from inline/top-bottom mode, default to 'left' so the image
          // actually floats and text wraps around it across multiple lines.
          if ((nextWrapMode === 'square' || nextWrapMode === 'tight') && nextAlign === 'center') {
            nextAlign = 'left';
          }
          _applyLayoutUpdate({ wrapMode: nextWrapMode, align: nextAlign });
          return;
        }

        const nextAlign = alignBtn?.dataset.align || '';
        if (!_docxImageLayoutSupportsAlign(currentState.wrapMode, nextAlign)) return;
        _applyLayoutUpdate({ wrapMode: currentState.wrapMode, align: nextAlign });
      });

      const ownerDoc = dom.ownerDocument || document;
      const _handleOutsidePointerDown = (event) => {
        if (!isToolbarOpen) return;
        // Toolbar is mounted on body (portal) so check it separately.
        if (event.target && (dom.contains(event.target) || toolbar.contains(event.target))) return;
        _setToolbarOpen(false);
      };

      const _handleEscapeKey = (event) => {
        if (event.key !== 'Escape' || !isToolbarOpen) return;
        event.preventDefault();
        _setToolbarOpen(false);
        editor.view.focus();
      };

      ownerDoc.addEventListener('pointerdown', _handleOutsidePointerDown, true);
      ownerDoc.addEventListener('keydown', _handleEscapeKey, true);

      // NOTE: toolbar is NOT appended to dom here — it is portal-mounted on
      // document.body when first opened, to escape the zoom transform context.
      _syncToolbarState(node.attrs);
      _syncUiState();

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
          const isTop = cls.includes('n');
          const startX = e.clientX;
          const startY = e.clientY;
          const startW = img.offsetWidth || parseInt(node.attrs.width) || img.naturalWidth || 200;
          const startH = img.offsetHeight || parseInt(node.attrs.height) || img.naturalHeight || 150;

          const onMove = (me) => {
            const delta = window.KotoUiScale.viewportDeltaToElement(img, me.clientX - startX, me.clientY - startY);
            const dx = delta.x;
            const dy = delta.y;
            const newW = Math.max(40, startW + (isLeft ? -dx : dx));
            const newH = Math.max(30, startH + (isTop ? -dy : dy));
            img.style.width = newW + 'px';
            img.style.height = newH + 'px';
          };

          const onUp = () => {
            document.removeEventListener('mousemove', onMove);
            document.removeEventListener('mouseup', onUp);
            const newW = img.offsetWidth || startW;
            const newH = img.offsetHeight || startH;
            const pos = typeof getPos === 'function' ? getPos() : null;
            if (pos == null) return;
            editor.view.dispatch(
              editor.view.state.tr.setNodeMarkup(pos, null, {
                ...node.attrs,
                width: newW + 'px',
                height: newH + 'px',
              })
            );
          };

          document.addEventListener('mousemove', onMove);
          document.addEventListener('mouseup', onUp);
        });
        dom.appendChild(handle);
      }

      dom.addEventListener('mouseenter', _showUi);
      dom.addEventListener('mouseleave', _scheduleUiHide);
      dom.addEventListener('mousedown', _showUi);

      return {
        dom,
        selectNode() {
          _clearUiHideTimer();
          _setNodeSelected(true);
        },
        deselectNode() {
          _clearUiHideTimer();
          _setHoverUiVisible(false);
          _setNodeSelected(false);
        },
        update(updatedNode) {
          if (updatedNode.type.name !== node.type.name) return false;
          node = updatedNode;
          _syncImg(node.attrs);
          _applyWrapperStyle(node.attrs);
          _syncToolbarState(node.attrs);
          _syncUiState();
          return true;
        },
        stopEvent(event) {
          // Toolbar is on document.body (not inside dom), so ProseMirror
          // never sees its events. Only guard handles and the trigger button.
          return !!(event.target && event.target.closest &&
            event.target.closest('.koto-img-handle, .koto-img-toolbar-trigger'));
        },
        destroy() {
          _clearUiHideTimer();
          window.removeEventListener('scroll', _updateFixedToolbarPos, { capture: true });
          window.removeEventListener('resize', _updateFixedToolbarPos);
          ownerDoc.removeEventListener('pointerdown', _handleOutsidePointerDown, true);
          ownerDoc.removeEventListener('keydown', _handleEscapeKey, true);
          // Remove body-portalled toolbar to avoid orphaned DOM nodes.
          if (toolbar.parentNode) toolbar.parentNode.removeChild(toolbar);
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
      kotoRole:       { default: null, parseHTML: el => el.getAttribute('data-koto-role') || null, renderHTML: attrs => attrs.kotoRole ? { 'data-koto-role': attrs.kotoRole } : {} },
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
