/**
 * koto-docx-editor.js
 * KotoTipTapEditor — drop-in replacement for KotoDocxEditor (WangEditor/Slate).
 *
 * Public API (identical to KotoDocxEditor):
 *   render(html)
 *   getContent()        → selected text or full plain-text
 *   serialize()         → current full HTML string
 *   applyToolCall(cmd)  → handles insert_image, replace_text, replace_all, set_html, insert_text
 *   replaceSelectionWith(mode, pinnedText, newText)
 *   setZoom(pct)
 *   destroy()
 *
 * Differences from WangEditor edition:
 *   - Uses TipTap v2 / ProseMirror instead of Slate.js
 *   - Native table support: colspan / rowspan / colwidth / resizable
 *   - No "Slate JSON corruption" workarounds needed
 *   - editor.state.selection (ProseMirror) replaces editor.selection (Slate)
 */

import { Editor } from '@tiptap/core';
import StarterKit from '@tiptap/starter-kit';
import { TextAlign } from '@tiptap/extension-text-align';
import { Selection } from '@tiptap/pm/state';
import { CellSelection, TableMap, selectionCell, findTable } from '@tiptap/pm/tables';
import Underline from '@tiptap/extension-underline';
import { Color } from '@tiptap/extension-color';
import { TextStyle } from '@tiptap/extension-text-style';
import { FontFamily } from '@tiptap/extension-font-family';
import Placeholder from '@tiptap/extension-placeholder';
import Link from '@tiptap/extension-link';
import Highlight from '@tiptap/extension-highlight';
import Subscript from '@tiptap/extension-subscript';
import Superscript from '@tiptap/extension-superscript';
import { resolveDocxPageChrome, resolveDocxBreakChrome } from './docx-pagination-runtime.js';

import {
  DOCX_TABLE_RESIZE_TRANSACTION_META,
  DOCX_ROW_RESIZE_SKIP_AUTOSAVE_META,
  DocxParagraph,
  DocxTable,
  DocxTableRow,
  DocxTableCell,
  DocxTableHeader,
  DocxPageBreak,
  DocxImage,
  DocxHeading,
  DocxTrackChange,
  DocxTrackChangePart,
  TocTab,
  FontSize,
  LineHeight,
  AutoPageBreakPlugin,
} from './docx-extensions.js';

// ─── Constants ───────────────────────────────────────────────────────────────
// Default page dimensions (US Letter 96dpi). Overridden per-doc via render(html, opts).
const _DEFAULT_PAGE_H = 1056;
// ProseMirror CSS: padding-top:96px + padding-bottom:80px = 176px of vertical padding.
// Effective content height per page (what Word shows between margins):
const _PAD_V          = 176;  // top(96) + bottom(80) padding from .ProseMirror CSS
const _AI_REVIEW_PENDING_HIGHLIGHT = 'wa-ai-review-pending';
const _AI_REVIEW_FOCUS_HIGHLIGHT = 'wa-ai-review-focus';

function _cloneJson(value, fallback) {
  try {
    return JSON.parse(JSON.stringify(value));
  } catch (_) {
    return fallback;
  }
}

function _stripAiPreviewHtml(value) {
  return String(value || '').replace(/<[^>]+>/g, ' ');
}

function _normalizeAiPreviewText(value) {
  return _stripAiPreviewHtml(value)
    .replace(/\s+/g, ' ')
    .trim()
    .toLowerCase();
}

function _previewAnchorText(value, limit = 48) {
  const text = _stripAiPreviewHtml(value).replace(/\s+/g, ' ').trim();
  if (!text) return '';
  return text.length > limit ? text.slice(0, limit) + '…' : text;
}

function _buildAiPreviewTextIndex(root) {
  if (!root) return null;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null, false);
  const rawPositions = [];
  const normalizedMap = [];
  let normalizedText = '';
  let rawIndex = 0;
  let lastWasSpace = false;
  let node;

  while ((node = walker.nextNode())) {
    const value = node.nodeValue || '';
    for (let offset = 0; offset < value.length; offset += 1) {
      rawPositions[rawIndex] = { node, offset };
      const rawChar = value[offset];
      const normalizedChar = /\s/.test(rawChar) ? ' ' : rawChar.toLowerCase();
      if (normalizedChar === ' ') {
        if (!lastWasSpace) {
          normalizedText += ' ';
          normalizedMap.push(rawIndex);
        }
        lastWasSpace = true;
      } else {
        normalizedText += normalizedChar;
        normalizedMap.push(rawIndex);
        lastWasSpace = false;
      }
      rawIndex += 1;
    }
  }

  return { normalizedText, normalizedMap, rawPositions };
}

function _createAiPreviewRange(index, start, end) {
  if (!index || end <= start) return null;
  const rawStartIndex = index.normalizedMap[start];
  const rawEndIndex = index.normalizedMap[end - 1];
  const startPos = index.rawPositions[rawStartIndex];
  const endPos = index.rawPositions[rawEndIndex];
  if (!startPos || !endPos) return null;
  const range = document.createRange();
  range.setStart(startPos.node, startPos.offset);
  range.setEnd(endPos.node, endPos.offset + 1);
  return range;
}

function _getFontSizeNumericValue(value, { pxToPt = false } = {}) {
  const raw = String(value || '').trim();
  if (!raw) return null;
  const match = raw.match(/^(-?\d+(?:\.\d+)?)([a-z%]*)$/i);
  if (!match) return null;
  let numeric = parseFloat(match[1]);
  if (!Number.isFinite(numeric) || numeric <= 0) return null;
  const unit = (match[2] || '').toLowerCase();
  if (unit === 'px' && pxToPt) {
    numeric = numeric * 72 / 96;
  }
  return numeric;
}

function _getFontSizeOptionValue(rawValue, options, { pxToPt = false } = {}) {
  const target = _getFontSizeNumericValue(rawValue, { pxToPt });
  if (!Number.isFinite(target)) return '';
  const candidates = [...options]
    .map(option => ({
      value: option.value,
      numeric: _getFontSizeNumericValue(option.value),
    }))
    .filter(option => Number.isFinite(option.numeric));
  if (!candidates.length) return '';
  const exact = candidates.find(option => Math.abs(option.numeric - target) < 0.05);
  if (exact) return exact.value;
  let closest = candidates[0];
  for (const option of candidates.slice(1)) {
    if (Math.abs(option.numeric - target) < Math.abs(closest.numeric - target)) {
      closest = option;
    }
  }
  return closest.value;
}

function _normalizeFontFamilyToken(value) {
  return String(value || '')
    .trim()
    .replace(/^['"]+|['"]+$/g, '')
    .replace(/\s+/g, ' ')
    .toLowerCase();
}

const _DOCX_FONT_FAMILIES = [
  { value: 'SimSun', label: '宋体', eastAsian: true, aliases: ['宋体', 'Songti', 'STSong'] },
  { value: 'SimHei', label: '黑体', eastAsian: true, aliases: ['黑体', 'Heiti'] },
  { value: 'Microsoft YaHei', label: '微软雅黑', eastAsian: true, aliases: ['微软雅黑', 'YaHei'] },
  { value: 'KaiTi', label: '楷体', eastAsian: true, aliases: ['楷体', 'KaiTi_GB2312', '楷体_GB2312'] },
  { value: 'FangSong', label: '仿宋', eastAsian: true, aliases: ['仿宋', 'FangSong_GB2312', '仿宋_GB2312'] },
  { value: 'DengXian', label: '等线', eastAsian: true, aliases: ['等线'] },
  { value: 'STZhongsong', label: '华文中宋', eastAsian: true, aliases: ['华文中宋'] },
  { value: 'STKaiti', label: '华文楷体', eastAsian: true, aliases: ['华文楷体'] },
  { value: 'Arial', label: 'Arial', aliases: ['Arial'] },
  { value: 'Calibri', label: 'Calibri', aliases: ['Calibri'] },
  { value: 'Times New Roman', label: 'Times New Roman', aliases: ['Times New Roman'] },
  { value: 'Georgia', label: 'Georgia', aliases: ['Georgia'] },
  { value: 'Verdana', label: 'Verdana', aliases: ['Verdana'] },
];

const _DOCX_FONT_FAMILY_LOOKUP = new Map();
for (const font of _DOCX_FONT_FAMILIES) {
  for (const alias of [font.value, font.label, ...(font.aliases || [])]) {
    const token = _normalizeFontFamilyToken(alias);
    if (token) _DOCX_FONT_FAMILY_LOOKUP.set(token, font);
  }
}

function _splitFontFamilyCandidates(value) {
  return String(value || '')
    .split(',')
    .map(part => part.trim())
    .filter(Boolean);
}

function _resolveDocxFontFamily(value, { preferEastAsian = true } = {}) {
  const raw = String(value || '').trim();
  if (!raw) return '';

  const candidates = _splitFontFamilyCandidates(raw);
  const matches = candidates
    .map(candidate => _DOCX_FONT_FAMILY_LOOKUP.get(_normalizeFontFamilyToken(candidate)))
    .filter(Boolean);

  if (matches.length) {
    const preferred = preferEastAsian ? matches.find(font => font.eastAsian) : null;
    return (preferred || matches[0]).value;
  }

  const normalizedRaw = _normalizeFontFamilyToken(raw);
  const exact = _DOCX_FONT_FAMILY_LOOKUP.get(normalizedRaw);
  if (exact) return exact.value;

  const partial = _DOCX_FONT_FAMILIES.find(font => {
    return [font.value, font.label, ...(font.aliases || [])].some(alias => {
      const token = _normalizeFontFamilyToken(alias);
      return token && normalizedRaw.includes(token);
    });
  });
  if (partial) return partial.value;

  return candidates[0].replace(/^['"]+|['"]+$/g, '');
}

function _getDocxFontFamilyOptionValue(rawValue, options) {
  const resolved = _resolveDocxFontFamily(rawValue);
  if (!resolved) return '';

  const normalizedResolved = _normalizeFontFamilyToken(resolved);
  const exact = [...options].find(option => {
    return [_normalizeFontFamilyToken(option.value), _normalizeFontFamilyToken(option.textContent)]
      .includes(normalizedResolved);
  });
  if (exact) return exact.value;

  const aliasMatch = [...options].find(option => {
    const optionValue = option.value || option.textContent || '';
    return _normalizeFontFamilyToken(_resolveDocxFontFamily(optionValue)) === normalizedResolved;
  });
  return aliasMatch ? aliasMatch.value : '';
}

function _extractCssStyleValue(styleText, propertyName) {
  const raw = String(styleText || '');
  if (!raw) return '';
  const match = raw.match(new RegExp(`${propertyName}\\s*:\\s*([^;]+)`, 'i'));
  return match ? match[1].trim() : '';
}

function _setCssStyleValue(styleText, propertyName, value) {
  const target = String(propertyName || '').trim().toLowerCase();
  const nextValue = value == null ? '' : String(value).trim();
  const parts = String(styleText || '')
    .split(';')
    .map(part => part.trim())
    .filter(Boolean);
  const kept = [];
  parts.forEach(part => {
    const idx = part.indexOf(':');
    if (idx === -1) return;
    const name = part.slice(0, idx).trim();
    const rawValue = part.slice(idx + 1).trim();
    if (!name || !rawValue) return;
    if (name.toLowerCase() === target) return;
    kept.push(`${name}:${rawValue}`);
  });
  if (target && nextValue) kept.push(`${propertyName}:${nextValue}`);
  return kept.join(';');
}

function _getDocxStylePropertyName(attrName) {
  switch (attrName) {
    case 'fontFamily': return 'font-family';
    case 'fontSize':   return 'font-size';
    case 'fontWeight': return 'font-weight';
    case 'fontStyle':  return 'font-style';
    default:           return '';
  }
}

function _isDocxBoldValue(value) {
  const raw = String(value || '').trim().toLowerCase();
  if (!raw) return false;
  if (raw === 'bold' || raw === 'bolder') return true;
  const numeric = parseInt(raw, 10);
  return Number.isFinite(numeric) && numeric >= 600;
}

function _isDocxItalicValue(value) {
  const raw = String(value || '').trim().toLowerCase();
  return raw === 'italic' || raw === 'oblique';
}

function _getDocxBlockTextStyleValue(ed, attrName) {
  const paragraphAttrs = ed.getAttributes('paragraph') || {};
  if (paragraphAttrs[attrName]) return paragraphAttrs[attrName];

  const headingAttrs = ed.getAttributes('heading') || {};
  if (headingAttrs[attrName]) return headingAttrs[attrName];

  const cssProperty = _getDocxStylePropertyName(attrName);
  if (cssProperty && headingAttrs.style) {
    return _extractCssStyleValue(headingAttrs.style, cssProperty);
  }
  return '';
}

function _normalizeHdrFtrHtml(html) {
  return String(html || '')
    .replace(/<p(?:\s[^>]*)?>\s*(?:<br\s*\/?>|&nbsp;|\s)*<\/p>/gi, '')
    .replace(/&nbsp;/gi, ' ')
    .trim();
}

function _hasHdrFtrContent(html) {
  return !!_normalizeHdrFtrHtml(html);
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

function _lockHdrFtrToolbarInteraction(ms = 400) {
  window.__kotoHdrFtrToolbarUntil = Date.now() + ms;
}

function _isHdrFtrToolbarInteractionLocked() {
  return Number(window.__kotoHdrFtrToolbarUntil || 0) > Date.now();
}

function _initialHdrFtrOverlayHtml(html) {
  return _hasHdrFtrContent(html) ? html : '<p><br></p>';
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

// ─── Toolbar template (plain HTML, inserted above the editor) ──────────────
const _TOOLBAR_HTML = `
<div class="koto-tt-toolbar" id="koto-tt-toolbar">
  <select class="tt-select" data-cmd="setHeading" title="标题">
    <option value="">正文</option>
    <option value="1">标题 1</option>
    <option value="2">标题 2</option>
    <option value="3">标题 3</option>
    <option value="4">标题 4</option>
    <option value="5">标题 5</option>
    <option value="6">标题 6</option>
  </select>
  <span class="tt-sep"></span>
  <select class="tt-select tt-select-font" data-cmd="setFontFamily" title="字体" style="width:90px;">
    <option value="">默认字体</option>
    <option value="SimSun">宋体</option>
    <option value="SimHei">黑体</option>
    <option value="Microsoft YaHei">微软雅黑</option>
    <option value="KaiTi">楷体</option>
    <option value="FangSong">仿宋</option>
    <option value="DengXian">等线</option>
    <option value="STZhongsong">华文中宋</option>
    <option value="STKaiti">华文楷体</option>
    <option value="Arial">Arial</option>
    <option value="Calibri">Calibri</option>
    <option value="Times New Roman">Times New Roman</option>
    <option value="Georgia">Georgia</option>
    <option value="Verdana">Verdana</option>
  </select>
  <select class="tt-select tt-select-size" data-cmd="setFontSize" title="字号" style="width:54px;">
    <option value="">字号</option>
    <option value="10pt">10</option>
    <option value="11pt">11</option>
    <option value="12pt">12</option>
    <option value="14pt">14</option>
    <option value="16pt">16</option>
    <option value="18pt">18</option>
    <option value="20pt">20</option>
    <option value="24pt">24</option>
    <option value="28pt">28</option>
    <option value="32pt">32</option>
    <option value="36pt">36</option>
    <option value="48pt">48</option>
    <option value="72pt">72</option>
  </select>
  <span class="tt-sep"></span>
  <button class="tt-btn" data-cmd="toggleBold" title="粗体 (Ctrl+B)"><b>B</b></button>
  <button class="tt-btn" data-cmd="toggleUnderline" title="下划线 (Ctrl+U)"><u>U</u></button>
  <button class="tt-btn" data-cmd="toggleItalic" title="斜体 (Ctrl+I)"><i>I</i></button>
  <button class="tt-btn" data-cmd="toggleStrike" title="删除线"><s>S</s></button>
  <button class="tt-btn tt-color-btn" data-cmd="setColor" title="字体颜色" style="gap:2px;flex-direction:column;padding:2px 5px;">
    <span style="font-size:13px;font-weight:700;line-height:1.1;">A</span>
    <span class="tt-color-swatch" id="tt-color-swatch" style="width:18px;height:3px;border-radius:1px;background:#000;display:block;"></span>
  </button>
  <button class="tt-btn tt-color-btn" data-cmd="setHighlight" title="文字背景色" style="gap:2px;flex-direction:column;padding:2px 5px;">
    <span style="font-size:11px;line-height:1.1;">A̲</span>
    <span class="tt-color-swatch" id="tt-bg-swatch" style="width:18px;height:3px;border-radius:1px;background:transparent;border:1px solid #555;display:block;"></span>
  </button>
  <button class="tt-btn" data-cmd="unsetAllMarks" title="清除格式" style="font-size:11px;">✕A</button>
  <span class="tt-sep"></span>
  <button class="tt-btn" data-cmd="setTextAlignLeft" title="左对齐">
    <svg width="14" height="12" viewBox="0 0 14 12" fill="currentColor"><rect x="0" y="0" width="14" height="2" rx="1"/><rect x="0" y="5" width="10" height="2" rx="1"/><rect x="0" y="10" width="14" height="2" rx="1"/></svg>
  </button>
  <button class="tt-btn" data-cmd="setTextAlignCenter" title="居中">
    <svg width="14" height="12" viewBox="0 0 14 12" fill="currentColor"><rect x="0" y="0" width="14" height="2" rx="1"/><rect x="2" y="5" width="10" height="2" rx="1"/><rect x="0" y="10" width="14" height="2" rx="1"/></svg>
  </button>
  <button class="tt-btn" data-cmd="setTextAlignRight" title="右对齐">
    <svg width="14" height="12" viewBox="0 0 14 12" fill="currentColor"><rect x="0" y="0" width="14" height="2" rx="1"/><rect x="4" y="5" width="10" height="2" rx="1"/><rect x="0" y="10" width="14" height="2" rx="1"/></svg>
  </button>
  <button class="tt-btn" data-cmd="setTextAlignJustify" title="两端对齐">
    <svg width="14" height="12" viewBox="0 0 14 12" fill="currentColor"><rect x="0" y="0" width="14" height="2" rx="1"/><rect x="0" y="5" width="14" height="2" rx="1"/><rect x="0" y="10" width="14" height="2" rx="1"/></svg>
  </button>
  <span class="tt-sep"></span>
  <button class="tt-btn" data-cmd="toggleBulletList" title="无序列表">
    <svg width="14" height="12" viewBox="0 0 14 12" fill="currentColor"><circle cx="1.5" cy="1.5" r="1.5"/><rect x="4" y="0" width="10" height="2" rx="1"/><circle cx="1.5" cy="6" r="1.5"/><rect x="4" y="5" width="10" height="2" rx="1"/><circle cx="1.5" cy="10.5" r="1.5"/><rect x="4" y="10" width="10" height="2" rx="1"/></svg>
  </button>
  <button class="tt-btn" data-cmd="toggleOrderedList" title="有序列表">
    <svg width="14" height="12" viewBox="0 0 14 12" fill="currentColor"><text x="0" y="10" font-size="9" font-family="Arial">1.</text><rect x="7" y="0" width="7" height="2" rx="1"/><rect x="7" y="5" width="7" height="2" rx="1"/><rect x="7" y="10" width="7" height="2" rx="1"/></svg>
  </button>
  <span class="tt-sep"></span>
  <button class="tt-btn" data-cmd="indent" title="增加缩进">
    <svg width="14" height="12" viewBox="0 0 14 12" fill="currentColor"><rect x="0" y="0" width="14" height="2" rx="1"/><polygon points="0,4 4,6 0,8"/><rect x="6" y="5" width="8" height="2" rx="1"/><rect x="0" y="10" width="14" height="2" rx="1"/></svg>
  </button>
  <button class="tt-btn" data-cmd="outdent" title="减少缩进">
    <svg width="14" height="12" viewBox="0 0 14 12" fill="currentColor"><rect x="0" y="0" width="14" height="2" rx="1"/><polygon points="4,4 0,6 4,8"/><rect x="6" y="5" width="8" height="2" rx="1"/><rect x="0" y="10" width="14" height="2" rx="1"/></svg>
  </button>
  <span class="tt-sep"></span>
  <button class="tt-btn" data-cmd="toggleBlockquote" title="引用">❝</button>
  <button class="tt-btn" data-cmd="toggleCodeBlock" title="代码块">&lt;/&gt;</button>
  <button class="tt-btn" data-cmd="setLink" title="插入链接">
    <svg width="14" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>
  </button>
  <button class="tt-btn" data-cmd="insertImage" title="插入图片">
    <svg width="14" height="12" viewBox="0 0 24 20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="1" width="20" height="18" rx="2"/><circle cx="8.5" cy="7.5" r="2.5"/><polyline points="21 15 16 10 5 19"/></svg>
  </button>
  <input type="file" id="tt-image-input" accept="image/*" style="display:none;">
  <span class="tt-sep"></span>
  <div class="tt-table-insert-wrap" style="position:relative;display:inline-block;">
    <button class="tt-btn" data-cmd="insertTable" title="插入表格">⊞</button>
    <div class="tt-table-picker" id="tt-table-picker" style="display:none;position:absolute;top:100%;left:0;z-index:10002;background:#2b2b2b;border:1px solid #555;border-radius:6px;padding:8px;box-shadow:0 6px 24px rgba(0,0,0,.65);user-select:none;" onmousedown="event.preventDefault()">
      <div style="color:#aaa;font-size:11px;margin-bottom:4px;text-align:center;" id="tt-table-picker-label">选择表格大小</div>
      <div id="tt-table-grid" style="display:grid;grid-template-columns:repeat(8,18px);gap:2px;"></div>
    </div>
  </div>
  <span class="tt-sep"></span>
  <button class="tt-btn" data-cmd="undo" title="撤销 (Ctrl+Z)">↺</button>
  <button class="tt-btn" data-cmd="redo" title="重做 (Ctrl+Y)">↻</button>
  <!-- Inline colour picker popup (no OS dialog, preserves editor selection) -->
  <div class="tt-cp-popup" id="tt-cp-popup" style="display:none;position:fixed;background:#2b2b2b;border:1px solid #555;border-radius:6px;padding:8px;z-index:10001;box-shadow:0 6px 24px rgba(0,0,0,.65);user-select:none;" onmousedown="event.preventDefault()">
    <div id="tt-cp-grid" style="display:grid;grid-template-columns:repeat(8,18px);gap:3px;"></div>
    <div style="margin-top:6px;padding-top:6px;border-top:1px solid #444;display:flex;align-items:center;gap:6px;">
      <span style="color:#aaa;font-size:11px;white-space:nowrap;">自定义:</span>
      <input type="color" id="tt-cp-custom" value="#000000" style="width:32px;height:20px;padding:1px;border:1px solid #666;border-radius:3px;cursor:pointer;background:transparent" onmousedown="event.stopPropagation()">
      <span id="tt-cp-hex" style="color:#ccc;font-size:11px;font-family:monospace;min-width:54px;">#000000</span>
    </div>
  </div>
</div>
`;

// ─── Table toolbar (appears when cursor is inside a table) ─────────────────
// Keep common actions in a bottom dock row. Richer table actions live in the
// right-click context menu so the document viewport stays unobstructed.
const _TABLE_TOOLBAR_HTML = `
<div class="koto-table-float-toolbar" id="koto-table-float-toolbar" style="display:none;">
  <div class="ttf-bar-actions">
    <button class="ttf-btn ttf-btn-labeled" data-table-cmd="selectRow" title="选择当前行">
      <span class="ttf-btn-text">选行</span>
    </button>
    <button class="ttf-btn ttf-btn-labeled" data-table-cmd="selectColumn" title="选择当前列">
      <span class="ttf-btn-text">选列</span>
    </button>
    <button class="ttf-btn ttf-btn-labeled" data-table-cmd="selectTable" title="选择整个表格">
      <span class="ttf-btn-text">选表</span>
    </button>
    <span class="ttf-bar-sep"></span>
    <button class="ttf-btn ttf-btn-labeled" data-table-cmd="addRowBefore" title="在上方插入行">
      <span class="ttf-btn-text">上插行</span>
    </button>
    <button class="ttf-btn ttf-btn-labeled" data-table-cmd="addRowAfter" title="在下方插入行">
      <span class="ttf-btn-text">下插行</span>
    </button>
    <button class="ttf-btn ttf-btn-labeled" data-table-cmd="addColumnBefore" title="在左侧插入列">
      <span class="ttf-btn-text">左插列</span>
    </button>
    <button class="ttf-btn ttf-btn-labeled" data-table-cmd="addColumnAfter" title="在右侧插入列">
      <span class="ttf-btn-text">右插列</span>
    </button>
    <span class="ttf-bar-sep"></span>
    <button class="ttf-btn ttf-btn-labeled" data-table-cmd="mergeCells" title="合并单元格（选中多个单元格后可用)">
      <span class="ttf-btn-text">合并</span>
    </button>
    <button class="ttf-btn ttf-btn-labeled" data-table-cmd="splitCell" title="拆分单元格（光标在合并单元格中时可用)">
      <span class="ttf-btn-text">拆分</span>
    </button>
    <button class="ttf-btn ttf-btn-labeled" data-table-cmd="distributeColumnsEvenly" title="平均分布各列">
      <span class="ttf-btn-text">均分列</span>
    </button>
    <span class="ttf-bar-sep"></span>
    <button class="ttf-btn ttf-btn-labeled" data-table-cmd="setTextAlignLeft" title="左对齐">
      <span class="ttf-btn-text">左对齐</span>
    </button>
    <button class="ttf-btn ttf-btn-labeled" data-table-cmd="setTextAlignCenter" title="水平居中">
      <span class="ttf-btn-text">居中</span>
    </button>
    <button class="ttf-btn ttf-btn-labeled" data-table-cmd="setTextAlignRight" title="右对齐">
      <span class="ttf-btn-text">右对齐</span>
    </button>
    <button class="ttf-btn ttf-btn-labeled" data-table-cmd="setTextAlignJustify" title="两端对齐">
      <span class="ttf-btn-text">两端</span>
    </button>
    <button class="ttf-btn ttf-btn-labeled" data-table-cmd="setCellAlignTop" title="顶端对齐">
      <span class="ttf-btn-text">顶对齐</span>
    </button>
    <button class="ttf-btn ttf-btn-labeled" data-table-cmd="setCellAlignMiddle" title="垂直居中">
      <span class="ttf-btn-text">中对齐</span>
    </button>
    <button class="ttf-btn ttf-btn-labeled" data-table-cmd="setCellAlignBottom" title="底端对齐">
      <span class="ttf-btn-text">底对齐</span>
    </button>
    <span class="ttf-bar-sep"></span>
    <button class="ttf-btn ttf-btn-labeled ttf-btn-toggle" data-table-cmd="toggleHeaderColumn" title="切换首列表头（加粗底纹）">
      <span class="ttf-btn-text">首列表头</span>
    </button>
    <button class="ttf-btn ttf-btn-labeled" data-table-cmd="deleteRow" title="删除行">
      <span class="ttf-btn-text">删行</span>
    </button>
    <button class="ttf-btn ttf-btn-labeled" data-table-cmd="deleteColumn" title="删除列">
      <span class="ttf-btn-text">删列</span>
    </button>
    <button class="ttf-btn ttf-btn-labeled ttf-btn-toggle" data-table-cmd="toggleHeaderRow" title="切换首行为表头行（加粗底纹）">
      <span class="ttf-btn-text">表头行</span>
    </button>
    <button class="ttf-btn ttf-btn-labeled ttf-btn-color" data-table-cmd="setCellBgColor" title="单元格背景色">
      <span class="ttf-btn-text">底纹</span>
      <span class="ttf-color-indicator" id="ttf-cell-bg-swatch"></span>
    </button>
    <button class="ttf-btn ttf-btn-labeled ttf-btn-danger" data-table-cmd="deleteTable" title="删除表格">
      <span class="ttf-btn-text">删表</span>
    </button>
  </div>

  <!-- Cell BG color picker popup -->
  <div class="ttf-cp-popup" id="ttf-cp-popup" style="display:none;" onmousedown="event.preventDefault()">
    <div id="ttf-cp-grid" style="display:grid;grid-template-columns:repeat(8,18px);gap:3px;"></div>
    <div style="margin-top:6px;padding-top:6px;border-top:1px solid #444;display:flex;align-items:center;gap:6px;">
      <span style="color:#aaa;font-size:11px;white-space:nowrap;">自定义:</span>
      <input type="color" id="ttf-cp-custom" value="#ffffff" style="width:32px;height:20px;padding:1px;border:1px solid #666;border-radius:3px;cursor:pointer;background:transparent" onmousedown="event.stopPropagation()">
      <button class="ttf-cp-clear" id="ttf-cp-clear" style="font-size:11px;color:#aaa;background:none;border:1px solid #555;border-radius:3px;padding:2px 6px;cursor:pointer;">清除</button>
    </div>
  </div>
</div>
`;

// ─── Build extension list ─────────────────────────────────────────────────
function _buildExtensions(onUpdate) {
  return [
    // StarterKit already includes: Bold, Italic, Strike, Code, Blockquote,
    // BulletList, OrderedList, Heading, HardBreak, HorizontalRule, History.
    // We exclude Paragraph (replaced by DocxParagraph) and History is kept.
    StarterKit.configure({
      paragraph: false,            // replaced below
      heading: false,              // replaced by DocxHeading
      codeBlock: { HTMLAttributes: { class: 'wa-code-block koto-code' } },
    }),
    DocxParagraph,
    DocxHeading.configure({ levels: [1, 2, 3, 4, 5, 6] }),
    DocxTable.configure({
      HTMLAttributes: { class: 'koto-docx-table' },
    }),
    DocxTableRow,
    DocxTableCell,
    DocxTableHeader,
    TextAlign.configure({
      types: ['heading', 'paragraph'],
    }),
    DocxImage.configure({
      HTMLAttributes: { class: 'koto-docx-img' },
      allowBase64: true,
    }),
    Underline,
    DocxTrackChange,
    DocxTrackChangePart,
    TextStyle,
    Color,
    FontFamily,
    FontSize,
    LineHeight,
    Highlight.configure({ multicolor: true }),
    Link.configure({ openOnClick: false }),
    Subscript,
    Superscript,
    Placeholder.configure({ placeholder: '开始编辑文档…' }),
    DocxPageBreak,
    TocTab,
    AutoPageBreakPlugin,
  ];
}

// ─── Main class ────────────────────────────────────────────────────────────
export class KotoTipTapEditor {
  constructor() {
    this.containerId    = 'wa-docx-editor';
    this.editor         = null;
    this._zoom          = 100;
    this._savedSel      = null;  // saved ProseMirror TextSelection for AI replace
    this._toolbarSelection = null; // last non-empty selection preserved for toolbar dropdowns
    this._lastHtml      = '';
    this._pageIndicator = null;
    this._wheelHandler  = null;
    this._scrollHandler = null;  // scroll → _updatePI
    this._updateHandler = null;  // TipTap update → debounced recalc
    this._totalPages    = 1;
    this._scrollEl      = null;  // <div id="wa-editor-content"> (the scrollable canvas)
    this._zoomWrapper   = null;  // <div class="koto-zoom-wrapper"> — zoom applied here
    this._ctxMenuHandler = null; // bound contextmenu event handler for cleanup
    this._ctxSelectionPreserveHandler = null;
    this._ctxMenuSelection = null;
    this._ctxCloseOnClick = null;
    this._ctxCloseOnKey   = null;
    // RAF handle for throttled zoom — prevents multiple CSS reflows per frame
    this._pendingZoomRaf  = null;
    this._hdrFtrSelectionHandler = null;
    // Table border click handler for whole-table selection
    this._tableBorderHandler = null;
    // Page dimensions (populated from render() opts, forwarded to AutoPageBreakPlugin)
    this._pageWidthPx    = null;
    this._pageHeightPx   = null;
    this._marginTopPx    = null;
    this._marginBottomPx = null;
    this._marginLeftPx   = null;
    this._marginRightPx  = null;
    this._headerHtml     = null;
    this._footerHtml     = null;
    this._sections       = [];
    this._topHeaderVariant = 'default';
    this._bottomFooterVariant = 'default';
    this._reviewPreviewProposals = [];
    this._reviewPreviewMatches = [];
    this._reviewPreviewFocusedId = '';
    this._reviewPreviewAnchorLayer = null;

    const wrap = document.getElementById(this.containerId);
    if (wrap) wrap.classList.add('active');
  }

  // ── render(html, opts) ──────────────────────────────────────────────────
  render(html, opts) {
    // opts may contain page dimensions from backend
    if (opts) {
      const _hasOpt = (key) => Object.prototype.hasOwnProperty.call(opts, key);
      if (_hasOpt('pageWidthPx'))     this._pageWidthPx    = opts.pageWidthPx;
      if (_hasOpt('pageHeightPx'))    this._pageHeightPx   = opts.pageHeightPx;
      if (_hasOpt('marginTopPx'))     this._marginTopPx    = opts.marginTopPx;
      if (_hasOpt('marginBottomPx'))  this._marginBottomPx = opts.marginBottomPx;
      if (_hasOpt('marginLeftPx'))    this._marginLeftPx   = opts.marginLeftPx;
      if (_hasOpt('marginRightPx'))   this._marginRightPx  = opts.marginRightPx;
      if (_hasOpt('headerHtml'))      this._headerHtml     = opts.headerHtml || '';
      if (_hasOpt('footerHtml'))      this._footerHtml     = opts.footerHtml || '';
      if (_hasOpt('sections'))        this._sections       = Array.isArray(opts.sections) ? opts.sections : [];
    }
    const sec0 = (Array.isArray(this._sections) && this._sections[0]) || null;
    if (this._headerHtml == null && sec0?.header_html) this._headerHtml = sec0.header_html;
    if (this._footerHtml == null && sec0?.footer_html) this._footerHtml = sec0.footer_html;
    // Tear down previous instance
    this._cleanup();

    const wrap = document.getElementById(this.containerId);
    if (!wrap) return;
    // Preserve host-managed overlays before clearing so re-renders do not
    // delete the review rail/launcher that the workspace shell mounts here.
    const _findBar = wrap.querySelector('#wa-docx-find-bar');
    const _reviewShell = wrap.querySelector('#wa-review-shell');
    const _reviewLauncher = wrap.querySelector('#wa-review-selection-launcher');
    wrap.innerHTML = '';
    if (_findBar) wrap.insertBefore(_findBar, wrap.firstChild);

    // Toolbar div
    const tbWrap = document.createElement('div');
    tbWrap.innerHTML = _TOOLBAR_HTML;
    wrap.appendChild(tbWrap.firstElementChild);

    // Editor mount target (outer scroll canvas)
    const edEl = document.createElement('div');
    edEl.id = 'wa-editor-content';
    wrap.appendChild(edEl);

    // Zoom wrapper — CSS zoom is applied to this element so .ProseMirror
    // and the page-break overlay share the same intrinsic coordinate space.
    // The wrapper is centered inside the gray canvas via margin:0 auto.
    const zoomEl = document.createElement('div');
    zoomEl.className = 'koto-zoom-wrapper';
    // Keep the wrapper in the same intrinsic coordinate space as the page.
    // If the wrapper shrinks to the viewport while .ProseMirror stays at the
    // full page width, the browser resolves a large negative auto margin on
    // the page and the soft page-break blocks visibly protrude to the right.
    const zoomPageW = this._pageWidthPx || 816;
    zoomEl.style.width = zoomPageW + 'px';
    zoomEl.style.maxWidth = zoomPageW + 'px';
    zoomEl.style.minWidth = zoomPageW + 'px';
    zoomEl.style.boxSizing = 'border-box';
    edEl.appendChild(zoomEl);

    // Page indicator
    const pi = document.createElement('div');
    pi.id = 'wa-docx-page-indicator';
    pi.innerHTML = '<span id="wa-pi-text">第 1 页 / 共 1 页</span>';
    wrap.appendChild(pi);
    this._pageIndicator = pi.querySelector('#wa-pi-text');
    if (_reviewShell) wrap.appendChild(_reviewShell);
    if (_reviewLauncher) wrap.appendChild(_reviewLauncher);

    // Sanitize: TipTap (ProseMirror) handles nested tables correctly, but
    // we still sanitize to avoid XSS on loaded document HTML.
    const safeHtml = _sanitizeDocxHtml(html);
    this._lastHtml = safeHtml;

    // Create TipTap editor
    this.editor = new Editor({
      element: zoomEl,
      extensions: _buildExtensions(),
      content: safeHtml,
      onUpdate: ({ editor, transaction }) => {
        const isResizeTransaction = !!transaction?.getMeta?.(DOCX_TABLE_RESIZE_TRANSACTION_META)
          || !!transaction?.getMeta?.(DOCX_ROW_RESIZE_SKIP_AUTOSAVE_META);
        try {
          const h = editor.getHTML();
          const stripped = h.replace(/<p><\/p>/gi, '').trim();
          if (stripped) this._lastHtml = h;
        } catch (_) {}
        if (!isResizeTransaction) {
          this._markImportedDocxTables(editor.view?.dom);
        }
        // Notify workspace auto-save (global WA.scheduleAutoSave)
        if (typeof window.WA !== 'undefined' && typeof window.WA.scheduleAutoSave === 'function') {
          window.WA.scheduleAutoSave(isResizeTransaction ? { skipDiskWrite: true } : undefined);
        }
        requestAnimationFrame(() => {
          this._renderReviewProposalAnchors();
          if (window.WA && typeof window.WA.relayoutDocxReviewRail === 'function') {
            window.WA.relayoutDocxReviewRail();
          }
        });
      },
    });

    this._markImportedDocxTables();

    // ── Apply DOCX page dimensions to .ProseMirror element ────────────
    // This ensures the rendered page matches the actual Word page size
    // instead of using the hardcoded 816px US-Letter fallback.
    {
      const pmEl = this.editor.view.dom;  // .ProseMirror element
      const pageW  = this._pageWidthPx  || 816;
      const mLeft  = this._marginLeftPx  || 96;
      const mRight = this._marginRightPx || 96;
      const mTop   = this._marginTopPx   || 96;
      const mBot   = this._marginBottomPx || 80;
      pmEl.style.width    = pageW + 'px';
      pmEl.style.maxWidth = pageW + 'px';
      pmEl.style.minWidth = pageW + 'px';
      pmEl.style.paddingLeft   = mLeft + 'px';
      pmEl.style.paddingRight  = mRight + 'px';
      pmEl.style.paddingTop    = mTop + 'px';
      pmEl.style.paddingBottom = mBot + 'px';
    }

    // ── Pass header/footer HTML to DocxPageBreak extension storage ───────
    // The NodeView reads from storage so each break renders the same
    // header/footer. Must be set before the NodeViews are created (they
    // read storage on first render, triggered by requestAnimationFrame).
    if (this.editor.storage?.docxPageBreak) {
      this.editor.storage.docxPageBreak.headerHtml = this._headerHtml || '';
      this.editor.storage.docxPageBreak.footerHtml = this._footerHtml || '';
    }

    // ── Pass page dimensions + header/footer to AutoPageBreakPlugin ──────
    // These values are used by the plugin to measure content heights and
    // insert soft-break widget decorations at page boundaries.
    if (this.editor.storage?.autoPageBreak) {
      const s = this.editor.storage.autoPageBreak;
      s.pageWidthPx    = this._pageWidthPx    || null;
      s.pageHeightPx   = this._pageHeightPx   || null;
      s.marginTopPx    = this._marginTopPx    || null;
      s.marginBottomPx = this._marginBottomPx || null;
      s.marginLeftPx   = this._marginLeftPx  || null;
      s.marginRightPx  = this._marginRightPx || null;
      s.headerHtml     = this._headerHtml     || '';
      s.footerHtml     = this._footerHtml     || '';
      s.sections       = this._sections       || [];
      // Page count callback: updates the page indicator whenever the plugin
      // finishes a measurement pass (triggered by content changes).
      s.onPageCountChange = (total) => {
        this._totalPages = Math.max(1, total || 1);
        this._refreshPageChromeShells(this._totalPages);
        this._refreshHeaderFooterPageNumbers(this._totalPages);
        this._updatePageIndicator(this._totalPages);
      };
    }

    // ── Inject page-1 header inside ProseMirror's top margin area ───────
    // Absolutely positioned within the zoom-wrapper so it overlays
    // ProseMirror's top padding (the margin area).  IMPORTANT: NO
    // contenteditable="true" on the container — that would trigger the
    // generic [contenteditable="true"] CSS rule which adds min-height:1056px,
    // background:#fff, and padding, covering all page content.
    // Instead, dblclick opens an overlay editor (same pattern as page breaks).
    {
      const firstPageChrome = resolveDocxPageChrome(this._getPaginationRuntimeSource(), 1, 0);
      this._topHeaderVariant = firstPageChrome.headerVariant;
      const firstHdr = firstPageChrome.headerHtml || '';
      const hdrFirst = document.createElement('div');
      hdrFirst.className = 'koto-page-header-first';
      hdrFirst.dataset.variant = this._topHeaderVariant;
      // NO contenteditable on the wrapper — avoid polluting CSS selector
      const _pw = firstPageChrome.pageWidthPx || 816;
      const _ml = firstPageChrome.marginLeftPx || 96;
      const _mr = firstPageChrome.marginRightPx || 96;
      const _mt = firstPageChrome.marginTopPx || 96;
      hdrFirst.style.cssText = `
        position:absolute; top:0; left:50%; transform:translateX(-50%);
        z-index:5; pointer-events:auto; cursor:text;
        width:${_pw}px; max-width:${_pw}px; box-sizing:border-box;
        --koto-docx-marker-left:${Math.max(24, _ml - 12)}px;
        --koto-docx-marker-right:${Math.max(24, _mr - 12)}px;
        padding:12px ${_mr}px 4px ${_ml}px;
        height:${_mt}px;
        font-size:9pt; color:#333;
        font-family:'Calibri','Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;
      `.replace(/\s+/g, ' ').trim();
      this._setHeaderFooterSlotState(hdrFirst, firstHdr, 'header');

      const _openOverlay = () => {
        if (hdrFirst.querySelector('.koto-hdrftr-overlay')) return;
        hdrFirst.classList.add('is-editing');
        const overlay = document.createElement('div');
        overlay.className = 'koto-hdrftr-overlay';
        overlay.setAttribute('contenteditable', 'true');
        overlay.dataset.slotType = 'header';
        overlay.innerHTML = _initialHdrFtrOverlayHtml(hdrFirst.innerHTML);
        overlay.style.cssText = 'position:absolute;top:0;left:0;right:0;bottom:0;z-index:10;background:#fff;box-sizing:border-box;outline:none;outline-offset:0;padding:inherit;cursor:text;';
        const _finish = () => {
          const newHtml = overlay.innerHTML;
          _clearHdrFtrOverlayActive(overlay);
          overlay.remove();
          hdrFirst.classList.remove('is-editing');
          this._applyHeaderEdit(newHtml, this._topHeaderVariant, hdrFirst);
        };
        overlay.addEventListener('focus', () => _markHdrFtrOverlayActive(overlay));
        overlay.addEventListener('blur', () => {
          requestAnimationFrame(() => {
            if (!overlay.isConnected || _isHdrFtrToolbarInteractionLocked()) return;
            _finish();
          });
        });
        overlay.addEventListener('keydown', (e) => {
          if (e.key === 'Escape') overlay.blur();
          if (e.key === 'Enter') { e.preventDefault(); document.execCommand('insertLineBreak'); }
        });
        hdrFirst.style.position = 'absolute'; // ensure relative context
        hdrFirst.appendChild(overlay);
        _markHdrFtrOverlayActive(overlay);
        overlay.focus();
        requestAnimationFrame(() => _focusHdrFtrOverlay(overlay));
      };
      hdrFirst.addEventListener('dblclick', (e) => { e.stopPropagation(); _openOverlay(); });

      zoomEl.appendChild(hdrFirst);
    }
    // ── Inject last-page footer inside ProseMirror's bottom margin area ──
    // Same pattern: NO contenteditable on wrapper, dblclick opens overlay.
    {
      const sections = this._ensureDocxSections();
      const lastSectionIdx = Math.max(0, sections.length - 1);
      const lastPageChrome = resolveDocxPageChrome(
        this._getPaginationRuntimeSource(),
        Math.max(1, this._totalPages || 1),
        lastSectionIdx,
      );
      this._bottomFooterVariant = lastPageChrome.footerVariant;
      const lastFtr = lastPageChrome.footerHtml || '';
      const ftrLast = document.createElement('div');
      ftrLast.className = 'koto-page-footer-last';
      ftrLast.dataset.variant = this._bottomFooterVariant;
      const _pw = lastPageChrome.pageWidthPx || 816;
      const _ml = lastPageChrome.marginLeftPx || 96;
      const _mr = lastPageChrome.marginRightPx || 96;
      const _mb = lastPageChrome.marginBottomPx || 80;
      ftrLast.style.cssText = `
        position:absolute; bottom:0; left:50%; transform:translateX(-50%);
        z-index:5; pointer-events:auto; cursor:text;
        width:${_pw}px; max-width:${_pw}px; box-sizing:border-box;
        padding:4px ${_mr}px 12px ${_ml}px;
        height:${_mb}px;
        font-size:9pt; color:#333;
        font-family:'Calibri','Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;
      `.replace(/\s+/g, ' ').trim();
      this._setHeaderFooterSlotState(ftrLast, lastFtr, 'footer');

      const _openOverlay = () => {
        if (ftrLast.querySelector('.koto-hdrftr-overlay')) return;
        ftrLast.classList.add('is-editing');
        const overlay = document.createElement('div');
        overlay.className = 'koto-hdrftr-overlay';
        overlay.setAttribute('contenteditable', 'true');
        overlay.dataset.slotType = 'footer';
        overlay.innerHTML = _initialHdrFtrOverlayHtml(ftrLast.innerHTML);
        overlay.style.cssText = 'position:absolute;top:0;left:0;right:0;bottom:0;z-index:10;background:#fff;box-sizing:border-box;outline:1px dashed rgba(79,126,255,.5);outline-offset:-1px;padding:inherit;cursor:text;';
        const _finish = () => {
          const newHtml = overlay.innerHTML;
          _clearHdrFtrOverlayActive(overlay);
          overlay.remove();
          ftrLast.classList.remove('is-editing');
          this._applyFooterEdit(newHtml, this._bottomFooterVariant, ftrLast);
        };
        overlay.addEventListener('focus', () => _markHdrFtrOverlayActive(overlay));
        overlay.addEventListener('blur', () => {
          requestAnimationFrame(() => {
            if (!overlay.isConnected || _isHdrFtrToolbarInteractionLocked()) return;
            _finish();
          });
        });
        overlay.addEventListener('keydown', (e) => {
          if (e.key === 'Escape') overlay.blur();
          if (e.key === 'Enter') { e.preventDefault(); document.execCommand('insertLineBreak'); }
        });
        ftrLast.appendChild(overlay);
        _markHdrFtrOverlayActive(overlay);
        overlay.focus();
        requestAnimationFrame(() => _focusHdrFtrOverlay(overlay));
      };
      ftrLast.addEventListener('dblclick', (e) => { e.stopPropagation(); _openOverlay(); });

      zoomEl.appendChild(ftrLast);
    }

    this._refreshPageChromeShells(this._totalPages || 1);
    this._refreshHeaderFooterPageNumbers(this._totalPages || 1);

    // Wire toolbar buttons
    this._wireToolbar(document.getElementById('koto-tt-toolbar'));

    // Wire Ctrl+Wheel zoom
    this._wheelHandler = (e) => {
      if (!e.ctrlKey && !e.metaKey) return;
      e.preventDefault();
      this.setZoom(this._zoom + (e.deltaY > 0 ? -10 : 10));
    };
    wrap.addEventListener('wheel', this._wheelHandler, { passive: false });

    // Wire right-click context menu
    this._ctxSelectionPreserveHandler = (e) => {
      if (!this.editor || e.button !== 2) return;
      this._captureContextMenuSelection();
      const selection = this.editor.state && this.editor.state.selection;
      if (selection && (!selection.empty || selection instanceof CellSelection)) {
        // Keep the active table/text selection intact while the custom menu opens.
        e.preventDefault();
      }
    };
    zoomEl.addEventListener('mousedown', this._ctxSelectionPreserveHandler, true);
    this._ctxMenuHandler = (e) => this._showDocxContextMenu(e);
    zoomEl.addEventListener('contextmenu', this._ctxMenuHandler);

    // Wire table border click → select entire table (Word-like behavior)
    this._wireTableBorderSelect(zoomEl);

    // Inject the table toolbar as a bottom dock above the page indicator.
    // It stays out of normal table layout so selection drags do not resize the
    // editor canvas, but it still reads as the bottom row of table controls.
    this._injectTableToolbar(wrap);

    // Apply current zoom
    if (this._zoom !== 100) this._applyZoom();

    // Page indicator wiring only needs the mounted DOM, not a fixed post-render delay.
    requestAnimationFrame(() => this._setupPageFeatures());

    // ── TOC link handler: click internal #anchor links to scroll ───────
    const _edContent = document.getElementById('wa-editor-content');
    if (_edContent) {
      _edContent.addEventListener('click', (e) => {
        const a = e.target.closest('a[href^="#"]');
        if (!a || !this.editor) return;
        e.preventDefault();
        const targetId = a.getAttribute('href').slice(1);
        if (!targetId) return;
        const target = this.editor.view.dom.querySelector(`[id="${CSS.escape(targetId)}"]`);
        if (target) {
          this._scrollDocxTargetIntoView(target);
          // Brief highlight to indicate the target
          target.style.transition = 'background .3s';
          target.style.background = 'rgba(79,126,255,.15)';
          setTimeout(() => { target.style.background = ''; }, 1500);
        }
      });
    }
  }

  _markImportedDocxTables(root = null) {
    const scope = root || this.editor?.view?.dom;
    if (!scope || typeof scope.querySelectorAll !== 'function') return;

    const importedCellSelector = [
      'td[data-koto-borderless-cell="true"]',
      'td[paddingtop]',
      'td[paddingright]',
      'td[paddingbottom]',
      'td[paddingleft]',
      'td[bordertop]',
      'td[borderright]',
      'td[borderbottom]',
      'td[borderleft]',
      'th[data-koto-borderless-cell="true"]',
      'th[paddingtop]',
      'th[paddingright]',
      'th[paddingbottom]',
      'th[paddingleft]',
      'th[bordertop]',
      'th[borderright]',
      'th[borderbottom]',
      'th[borderleft]',
    ].join(',');

    scope.querySelectorAll('.tableWrapper table:not(.koto-docx-table)').forEach((tableEl) => {
      if (!tableEl.querySelector(importedCellSelector)) return;
      tableEl.classList.add('koto-docx-table');
    });
  }

  // ── _wireToolbar ─────────────────────────────────────────────────────────
  _wireToolbar(tbEl) {
    if (!tbEl || !this.editor) return;
    const ed = this.editor;

    // Preset colours for the inline picker
    const _TB_COLORS = [
      '#000000','#1f1f1f','#595959','#808080','#a6a6a6','#d9d9d9','#f2f2f2','#ffffff',
      '#c00000','#ff0000','#ff4b4b','#ff6d00','#ff9900','#ffc000','#ffff00','#fff2cc',
      '#375623','#548235','#70ad47','#92d050','#00b050','#008080','#0070c0','#bdd7ee',
      '#1f3864','#2e75b6','#4472c4','#9dc3e6','#7030a0','#984ea3','#c9a0dc','#d9e1f2',
    ];

    // ── Colour picker popup ────────────────────────────────────────────────
    const cpPopup = tbEl.querySelector('#tt-cp-popup');
    const cpGrid  = tbEl.querySelector('#tt-cp-grid');
    const cpHex   = tbEl.querySelector('#tt-cp-hex');
    const cpCustom = tbEl.querySelector('#tt-cp-custom');
    let _cpMode = 'font';  // 'font' | 'bg'

      const _getActiveHdrFtrOverlay = () => {
      const marked = document.querySelector('#wa-docx-editor .koto-hdrftr-overlay.is-active');
      if (marked) return marked;
      const active = document.activeElement;
      if (active && typeof active.closest === 'function') {
        const overlay = active.closest('.koto-hdrftr-overlay');
        if (overlay) return overlay;
      }
      const sel = window.getSelection ? window.getSelection() : null;
      let node = sel ? (sel.focusNode || sel.anchorNode) : null;
      if (node && node.nodeType === 3) node = node.parentElement;
      return node && typeof node.closest === 'function'
        ? node.closest('.koto-hdrftr-overlay')
        : null;
    };

    const _restoreBodyToolbarSelection = () => {
      if (_getActiveHdrFtrOverlay()) return false;
      return this._restoreToolbarSelection();
    };

    tbEl.addEventListener('mousedown', (evt) => {
      const target = evt.target.closest('[data-cmd], #tt-cp-popup, #tt-cp-custom, #tt-cp-grid');
      if (!target) return;

      if (!_getActiveHdrFtrOverlay()) {
        if (!this._captureToolbarSelection()) {
          this._toolbarSelection = null;
        }
        return;
      }

      _lockHdrFtrToolbarInteraction();
      const tag = target.tagName;
      if (tag !== 'SELECT' && tag !== 'INPUT') {
        evt.preventDefault();
      }
    }, true);

    const _getHdrFtrBlockEl = (overlay) => {
      if (!overlay) return null;
      const sel = window.getSelection ? window.getSelection() : null;
      let node = sel ? (sel.focusNode || sel.anchorNode) : null;
      if (node && node.nodeType === 3) node = node.parentElement;
      const block = node && typeof node.closest === 'function'
        ? node.closest('p,div,li,blockquote,h1,h2,h3,h4,h5,h6')
        : null;
      if (block && block !== overlay && overlay.contains(block)) return block;
      return overlay.querySelector('p,div,li,blockquote,h1,h2,h3,h4,h5,h6') || overlay;
    };

    const _applyHdrFtrBlockStyle = (styleName, value) => {
      const overlay = _getActiveHdrFtrOverlay();
      if (!overlay) return false;
      const block = _getHdrFtrBlockEl(overlay);
      if (!block) return false;
      block.style[styleName] = value || '';
      if (document.activeElement !== overlay) overlay.focus();
      return true;
    };

    const _getHdrFtrComputedStyle = () => {
      const overlay = _getActiveHdrFtrOverlay();
      if (!overlay) return null;
      const block = _getHdrFtrBlockEl(overlay);
      return block ? window.getComputedStyle(block) : window.getComputedStyle(overlay);
    };

    const _openColorPicker = (mode, triggerEl) => {
      if (!cpPopup || !cpGrid) return;
      if (cpPopup.style.display !== 'none' && _cpMode === mode) {
        cpPopup.style.display = 'none'; return;
      }
      _cpMode = mode;
      cpGrid.innerHTML = _TB_COLORS.map(c =>
        `<div title="${c}" style="width:18px;height:18px;border-radius:3px;background:${c};cursor:pointer;border:1px solid rgba(255,255,255,.12);box-sizing:border-box;" onmousedown="event.preventDefault()" onclick="_ttPickColor('${c}')"></div>`
      ).join('');
      if (triggerEl) {
        const r = triggerEl.getBoundingClientRect();
        cpPopup.style.left = Math.max(4, Math.min(r.left, window.innerWidth - 180)) + 'px';
        cpPopup.style.top  = (r.bottom + 4) + 'px';
      }
      cpPopup.style.display = 'block';
    };

    // Expose to inline onclick= in the swatch grid
    window._ttPickColor = (color, keepOpen) => {
      const overlay = _getActiveHdrFtrOverlay();
      if (overlay) {
        try { document.execCommand('styleWithCSS', false, true); } catch (_) {}
        document.execCommand(_cpMode === 'font' ? 'foreColor' : 'hiliteColor', false, color);
      } else if (this._applyCellSelectionCommand(_cpMode === 'font' ? 'setColor' : 'setHighlight', color)) {
      } else if (_cpMode === 'font') {
        ed.chain().focus().setColor(color).run();
      } else {
        ed.chain().focus().toggleHighlight({ color }).run();
      }
      const sw = document.getElementById(_cpMode === 'font' ? 'tt-color-swatch' : 'tt-bg-swatch');
      if (sw) sw.style.background = color;
      if (cpHex) cpHex.textContent = color;
      if (cpCustom && /^#[0-9a-f]{6}$/i.test(color)) cpCustom.value = color;
      if (!keepOpen && cpPopup) cpPopup.style.display = 'none';
      _updateActiveStates();
    };

    // Custom colour input change
    if (cpCustom) {
      cpCustom.addEventListener('input', () => window._ttPickColor(cpCustom.value, true));
    }

    // Close picker when clicking outside
    document.addEventListener('mousedown', (evt) => {
      if (!cpPopup || cpPopup.style.display === 'none') return;
      if (cpPopup.contains(evt.target)) return;
      const inTrigger = evt.target.closest &&
        (evt.target.closest('[data-cmd="setColor"]') || evt.target.closest('[data-cmd="setHighlight"]'));
      if (inTrigger) return;
      cpPopup.style.display = 'none';
    }, true);

    // ── Click handler for buttons ──────────────────────────────────────────
    tbEl.addEventListener('click', (e) => {
      const btn = e.target.closest('[data-cmd]');
      if (!btn) return;
      // Don't intercept select changes here (handled separately)
      if (btn.tagName === 'SELECT') return;
      e.preventDefault();
      const cmd = btn.dataset.cmd;

      if (_getActiveHdrFtrOverlay()) {
        switch (cmd) {
          case 'setTextAlignLeft':
            _applyHdrFtrBlockStyle('textAlign', 'left');
            _updateActiveStates();
            return;
          case 'setTextAlignCenter':
            _applyHdrFtrBlockStyle('textAlign', 'center');
            _updateActiveStates();
            return;
          case 'setTextAlignRight':
            _applyHdrFtrBlockStyle('textAlign', 'right');
            _updateActiveStates();
            return;
          case 'setTextAlignJustify':
            _applyHdrFtrBlockStyle('textAlign', 'justify');
            _updateActiveStates();
            return;
          case 'toggleBold':
            document.execCommand('bold', false);
            _updateActiveStates();
            return;
          case 'toggleUnderline':
            document.execCommand('underline', false);
            _updateActiveStates();
            return;
          case 'toggleItalic':
            document.execCommand('italic', false);
            _updateActiveStates();
            return;
          case 'toggleStrike':
            document.execCommand('strikeThrough', false);
            _updateActiveStates();
            return;
          case 'unsetAllMarks':
            document.execCommand('removeFormat', false);
            _updateActiveStates();
            return;
          default:
            break;
        }
      }

      if (this._applyCellSelectionCommand(cmd)) {
        _updateActiveStates();
        return;
      }

      switch (cmd) {
        case 'toggleBold': {
          const hasBlockBold = this._selectionHasBlockTextStyle('fontWeight', _isDocxBoldValue);
          const hadMarkBold = ed.isActive('bold');
          if (hadMarkBold) ed.chain().focus().unsetBold().run();
          if (hasBlockBold) this._setSelectionBlockTextStyle('fontWeight', null);
          if (!hadMarkBold && !hasBlockBold) ed.chain().focus().toggleBold().run();
          break;
        }
        case 'toggleUnderline':    ed.chain().focus().toggleUnderline().run(); break;
        case 'toggleItalic': {
          const hasBlockItalic = this._selectionHasBlockTextStyle('fontStyle', _isDocxItalicValue);
          const hadMarkItalic = ed.isActive('italic');
          if (hadMarkItalic) ed.chain().focus().unsetItalic().run();
          if (hasBlockItalic) this._setSelectionBlockTextStyle('fontStyle', null);
          if (!hadMarkItalic && !hasBlockItalic) ed.chain().focus().toggleItalic().run();
          break;
        }
        case 'toggleStrike':       ed.chain().focus().toggleStrike().run(); break;
        case 'setTextAlignLeft':   ed.chain().focus().setTextAlign('left').run(); break;
        case 'setTextAlignCenter': ed.chain().focus().setTextAlign('center').run(); break;
        case 'setTextAlignRight':  ed.chain().focus().setTextAlign('right').run(); break;
        case 'setTextAlignJustify':ed.chain().focus().setTextAlign('justify').run(); break;
        case 'toggleBulletList':   ed.chain().focus().toggleBulletList().run(); break;
        case 'toggleOrderedList':  ed.chain().focus().toggleOrderedList().run(); break;
        case 'toggleBlockquote':   ed.chain().focus().toggleBlockquote().run(); break;
        case 'toggleCodeBlock':    ed.chain().focus().toggleCodeBlock().run(); break;
        case 'insertTable':
          // Handled by table size picker (mousedown handler on the button)
          return;
        case 'undo':  ed.chain().focus().undo().run(); break;
        case 'redo':  ed.chain().focus().redo().run(); break;
        case 'unsetAllMarks': ed.chain().focus().unsetAllMarks().run(); break;
        case 'indent': {
          // TipTap StarterKit: indent inside lists, otherwise increase indent level
          if (ed.isActive('listItem')) {
            ed.chain().focus().sinkListItem('listItem').run();
          } else {
            // Increase paragraph indent via DocxParagraph margin-left
            const cur = parseInt((ed.getAttributes('paragraph') || {}).marginLeft || '0', 10);
            ed.chain().focus().updateAttributes('paragraph', { marginLeft: (cur + 36) + 'px' }).run();
          }
          break;
        }
        case 'outdent': {
          if (ed.isActive('listItem')) {
            ed.chain().focus().liftListItem('listItem').run();
          } else {
            const cur = parseInt((ed.getAttributes('paragraph') || {}).marginLeft || '0', 10);
            const next = Math.max(0, cur - 36);
            ed.chain().focus().updateAttributes('paragraph', { marginLeft: next > 0 ? next + 'px' : null }).run();
          }
          break;
        }
        case 'setColor':
          _openColorPicker('font', btn);
          return;  // Don't trigger _updateActiveStates
        case 'setHighlight':
          _openColorPicker('bg', btn);
          return;
        case 'setLink': {
          const prev = ed.getAttributes('link').href || '';
          const href = window.prompt('输入链接地址 (留空可清除链接):', prev);
          if (href === null) return;  // cancelled
          if (href.trim() === '') {
            ed.chain().focus().unsetLink().run();
          } else {
            const safeHref = href.trim().startsWith('http') ? href.trim() : 'https://' + href.trim();
            ed.chain().focus().setLink({ href: safeHref, target: '_blank' }).run();
          }
          break;
        }
        case 'insertImage': {
          const inp = document.getElementById('tt-image-input');
          if (inp) inp.click();
          return;
        }
      }
      _updateActiveStates();
    });

    // ── Font family select ─────────────────────────────────────────────────
    const fontFamilySel = tbEl.querySelector('[data-cmd="setFontFamily"]');
    if (fontFamilySel) {
      fontFamilySel.addEventListener('change', (e) => {
        const v = _resolveDocxFontFamily(e.target.value);
        if (_getActiveHdrFtrOverlay()) {
          _applyHdrFtrBlockStyle('fontFamily', v || '');
        } else {
          _restoreBodyToolbarSelection();
          if (this._applyCellSelectionCommand(v ? 'setFontFamily' : 'unsetFontFamily', v || null)) {
          } else if (v) {
            ed.chain().focus().setFontFamily(v).run();
          } else {
            ed.chain().focus().unsetFontFamily().run();
          }
        }
        _updateActiveStates();
      });
    }

    // ── Font size select ───────────────────────────────────────────────────
    const fontSizeSel = tbEl.querySelector('[data-cmd="setFontSize"]');
    if (fontSizeSel) {
      fontSizeSel.addEventListener('change', (e) => {
        const v = e.target.value;
        if (_getActiveHdrFtrOverlay()) {
          _applyHdrFtrBlockStyle('fontSize', v || '');
        } else {
          _restoreBodyToolbarSelection();
          if (v && this._applyCellSelectionCommand('setFontSize', v)) {
          } else if (v) {
            ed.chain().focus().setFontSize(v).run();
          } else if (this._applyCellSelectionCommand('unsetFontSize')) {
          } else {
            ed.chain().focus().unsetFontSize().run();
          }
        }
        _updateActiveStates();
      });
    }

    // ── Heading select ─────────────────────────────────────────────────────
    const headingSel = tbEl.querySelector('[data-cmd="setHeading"]');
    if (headingSel) {
      headingSel.addEventListener('change', (e) => {
        const lvl = parseInt(e.target.value, 10);
        if (lvl) {
          ed.chain().focus().setHeading({ level: lvl }).run();
        } else {
          ed.chain().focus().setParagraph().run();
        }
        _updateActiveStates();
      });
    }

    // ── Image file input ───────────────────────────────────────────────────
    const imgInput = document.getElementById('tt-image-input');
    if (imgInput) {
      imgInput.addEventListener('change', (e) => {
        const file = e.target.files && e.target.files[0];
        if (!file) return;
        const reader = new FileReader();
        reader.onload = (ev) => {
          ed.chain().focus().setImage({ src: ev.target.result, alt: file.name }).run();
        };
        reader.readAsDataURL(file);
        imgInput.value = '';
      });
    }

    // ── Active state tracking ──────────────────────────────────────────────
    const _updateActiveStates = () => {
      const hdrFtrStyle = _getHdrFtrComputedStyle();
      const hdrFtrAlign = hdrFtrStyle ? (hdrFtrStyle.textAlign || 'left') : null;
      const cellSelection = this._getActiveCellSelection();
      const cellTextAlign = cellSelection
        ? this._getCellSelectionBlockAttrValue('textAlign', { defaultValue: 'left' }, cellSelection)
        : null;
      const marks = {
        'toggleBold':      hdrFtrStyle ? document.queryCommandState('bold') : (cellSelection ? (this._cellSelectionHasMark('bold', cellSelection) || _isDocxBoldValue(this._getCellSelectionBlockAttrValue('fontWeight', { defaultValue: null }, cellSelection))) : (ed.isActive('bold') || this._selectionHasBlockTextStyle('fontWeight', _isDocxBoldValue))),
        'toggleUnderline': hdrFtrStyle ? document.queryCommandState('underline') : (cellSelection ? this._cellSelectionHasMark('underline', cellSelection) : ed.isActive('underline')),
        'toggleItalic':    hdrFtrStyle ? document.queryCommandState('italic') : (cellSelection ? (this._cellSelectionHasMark('italic', cellSelection) || _isDocxItalicValue(this._getCellSelectionBlockAttrValue('fontStyle', { defaultValue: null }, cellSelection))) : (ed.isActive('italic') || this._selectionHasBlockTextStyle('fontStyle', _isDocxItalicValue))),
        'toggleStrike':    hdrFtrStyle ? document.queryCommandState('strikeThrough') : (cellSelection ? this._cellSelectionHasMark('strike', cellSelection) : ed.isActive('strike')),
        'toggleBulletList':  ed.isActive('bulletList'),
        'toggleOrderedList': ed.isActive('orderedList'),
        'toggleBlockquote':  ed.isActive('blockquote'),
        'toggleCodeBlock':   ed.isActive('codeBlock'),
        'setTextAlignLeft':    hdrFtrStyle ? !hdrFtrAlign || hdrFtrAlign === 'left' || hdrFtrAlign === 'start' : (cellSelection ? cellTextAlign === 'left' : ed.isActive({ textAlign: 'left' })),
        'setTextAlignCenter':  hdrFtrStyle ? hdrFtrAlign === 'center' : (cellSelection ? cellTextAlign === 'center' : ed.isActive({ textAlign: 'center' })),
        'setTextAlignRight':   hdrFtrStyle ? hdrFtrAlign === 'right' || hdrFtrAlign === 'end' : (cellSelection ? cellTextAlign === 'right' : ed.isActive({ textAlign: 'right' })),
        'setTextAlignJustify': hdrFtrStyle ? hdrFtrAlign === 'justify' : (cellSelection ? cellTextAlign === 'justify' : ed.isActive({ textAlign: 'justify' })),
      };
      for (const [cmd, active] of Object.entries(marks)) {
        const btn = tbEl.querySelector(`[data-cmd="${cmd}"]`);
        if (btn) btn.classList.toggle('is-active', active);
      }
      // Sync heading SELECT
      if (headingSel) {
        for (let lvl = 1; lvl <= 6; lvl++) {
          if (ed.isActive('heading', { level: lvl })) {
            headingSel.value = String(lvl);
            break;
          }
          if (lvl === 6) headingSel.value = '';
        }
      }
      // Sync font family SELECT
      if (fontFamilySel) {
        const ff = hdrFtrStyle
          ? (hdrFtrStyle.fontFamily || '')
          : (cellSelection
            ? this._getCellSelectionTextStyleValue('fontFamily', cellSelection)
            : ((ed.getAttributes('textStyle') || {}).fontFamily || _getDocxBlockTextStyleValue(ed, 'fontFamily') || ''));
        fontFamilySel.value = _getDocxFontFamilyOptionValue(ff, fontFamilySel.options);
      }
      // Sync font size SELECT
      if (fontSizeSel) {
        const fs = hdrFtrStyle
          ? (hdrFtrStyle.fontSize || '')
          : (cellSelection
            ? this._getCellSelectionTextStyleValue('fontSize', cellSelection)
            : ((ed.getAttributes('textStyle') || {}).fontSize || _getDocxBlockTextStyleValue(ed, 'fontSize') || ''));
        fontSizeSel.value = _getFontSizeOptionValue(fs, fontSizeSel.options, { pxToPt: !!hdrFtrStyle });
      }
      // Sync colour swatch
      const colorAttr = hdrFtrStyle ? hdrFtrStyle.color : (ed.getAttributes('textStyle') || {}).color;
      const colorSw = document.getElementById('tt-color-swatch');
      if (colorSw && colorAttr) colorSw.style.background = colorAttr;
    };

    this._hdrFtrSelectionHandler = () => {
      if (!_getActiveHdrFtrOverlay()) return;
      _updateActiveStates();
      if (typeof window._kotoDocxSelectionChanged === 'function') {
        window._kotoDocxSelectionChanged();
      }
    };
    document.addEventListener('selectionchange', this._hdrFtrSelectionHandler);

    // Listen to TipTap selection/update events for active state sync
    ed.on('selectionUpdate', () => {
      this._captureToolbarSelection();
      _updateActiveStates();
      // Notify the outer shell that selection changed (triggers DOCX hoverbar)
      if (typeof window._kotoDocxSelectionChanged === 'function') {
        window._kotoDocxSelectionChanged();
      }
    });
    this._updateHandler = ({ transaction } = {}) => {
      if (transaction?.getMeta?.(DOCX_TABLE_RESIZE_TRANSACTION_META)) return;
      _updateActiveStates();
    };
    ed.on('update', this._updateHandler);
    // Run once after editor ready
    setTimeout(_updateActiveStates, 100);
  }

  _getActiveCellSelection() {
    if (!this.editor || this.editor.isDestroyed) return null;
    const selection = this.editor.state && this.editor.state.selection;
    return selection instanceof CellSelection ? selection : null;
  }

  _getCellNodeTextForAI(cellNode) {
    return String((cellNode && cellNode.textContent) || '')
      .replace(/[\t\r\n]+/g, ' ')
      .replace(/\s+/g, ' ')
      .trim();
  }

  _getTableNodeTextForAI(tableNode) {
    if (!tableNode) return '';
    const lines = [];
    tableNode.forEach((rowNode) => {
      if (!rowNode || rowNode.type.name !== 'tableRow') return;
      const cells = [];
      rowNode.forEach((cellNode) => {
        cells.push(this._getCellNodeTextForAI(cellNode));
      });
      lines.push(cells.join('\t'));
    });
    return lines.join('\n').trim();
  }

  _getCellSelectionInfo(selection = this._getActiveCellSelection()) {
    if (!this.editor || !selection) return null;
    const tableInfo = findTable(selection.$anchorCell);
    if (!tableInfo || !tableInfo.node) return null;

    const selectedCells = new Map();
    selection.forEachCell((cell, cellPos) => {
      selectedCells.set(cellPos, cell);
    });
    if (!selectedCells.size) return null;

    const tableStart = typeof tableInfo.start === 'number'
      ? tableInfo.start
      : (typeof tableInfo.pos === 'number' ? tableInfo.pos + 1 : null);
    if (tableStart == null) return null;

    const lines = [];
    let rowCount = 0;
    let colCount = 0;
    tableInfo.node.forEach((rowNode, rowOffset) => {
      if (!rowNode || rowNode.type.name !== 'tableRow') return;
      const rowStart = tableStart + rowOffset;
      const cells = [];
      rowNode.forEach((cellNode, cellOffset) => {
        const cellPos = rowStart + 1 + cellOffset;
        if (!selectedCells.has(cellPos)) return;
        cells.push(this._getCellNodeTextForAI(cellNode));
      });
      if (!cells.length) return;
      rowCount += 1;
      colCount = Math.max(colCount, cells.length);
      lines.push(cells.join('\t'));
    });

    const text = lines.join('\n').trim();
    if (!text) return null;

    const tableDomPos = typeof tableInfo.pos === 'number'
      ? tableInfo.pos
      : (typeof tableInfo.start === 'number' ? tableInfo.start - 1 : null);
    let tableElement = null;
    if (tableDomPos != null) {
      const domNode = this.editor.view.nodeDOM(tableDomPos);
      if (domNode && domNode.nodeType === Node.ELEMENT_NODE) {
        tableElement = domNode.tagName === 'TABLE' ? domNode : domNode.querySelector('table');
      }
    }

    return {
      text,
      rows: rowCount,
      cols: colCount,
      selectedCells: selectedCells.size,
      tableElement,
    };
  }

  getCellSelectionInfo() {
    const selection = this._getPreservedSelection();
    return selection instanceof CellSelection ? this._getCellSelectionInfo(selection) : null;
  }

  _getDomWholeTableSelectionInfo() {
    const root = document.getElementById(this.containerId);
    if (!root) return null;
    const table = root.querySelector('.tableWrapper.koto-table-selected table');
    if (!table) return null;

    const lines = [];
    Array.from(table.rows || []).forEach((row) => {
      const cells = Array.from(row.cells || []).map((cell) => String(cell.textContent || '')
        .replace(/[\t\r\n]+/g, ' ')
        .replace(/\s+/g, ' ')
        .trim());
      lines.push(cells.join('\t'));
    });

    const text = lines.join('\n').trim();
    if (!text) return null;

    const rows = table.rows ? table.rows.length : 0;
    const cols = Math.max(0, ...Array.from(table.rows || []).map((row) => row.cells.length || 0));
    return { text, rows, cols, tableElement: table };
  }

  _getWholeTableSelectionInfo(selection = this._getActiveCellSelection()) {
    if (!this.editor || !selection) return null;
    const tableInfo = findTable(selection.$anchorCell);
    if (!tableInfo || !tableInfo.node) return null;

    const selectedCells = new Set();
    selection.forEachCell((_cell, cellPos) => {
      selectedCells.add(cellPos);
    });
    if (!selectedCells.size) return null;

    let totalCells = 0;
    tableInfo.node.descendants((node) => {
      if (node.type.name === 'tableCell' || node.type.name === 'tableHeader') {
        totalCells += 1;
      }
    });
    if (!totalCells || selectedCells.size !== totalCells) return null;

    let cols = 0;
    try {
      cols = TableMap.get(tableInfo.node).width || 0;
    } catch (_) {}

    const rows = tableInfo.node.childCount || 0;
    const text = this._getTableNodeTextForAI(tableInfo.node);
    const tableDomPos = typeof tableInfo.pos === 'number'
      ? tableInfo.pos
      : (typeof tableInfo.start === 'number' ? tableInfo.start - 1 : null);
    let tableElement = null;
    if (tableDomPos != null) {
      const domNode = this.editor.view.nodeDOM(tableDomPos);
      if (domNode && domNode.nodeType === Node.ELEMENT_NODE) {
        tableElement = domNode.tagName === 'TABLE' ? domNode : domNode.querySelector('table');
      }
    }

    return { text, rows, cols, tableElement };
  }

  isWholeTableSelection() {
    return !!this.getWholeTableSelectionInfo();
  }

  _getPreservedSelection() {
    if (!this.editor || this.editor.isDestroyed) return null;
    const state = this.editor.state;
    const liveSelection = state && state.selection;
    if (liveSelection && (!liveSelection.empty || liveSelection instanceof CellSelection)) {
      return liveSelection;
    }
    if (this._toolbarSelection) {
      try {
        const restoredSelection = Selection.fromJSON(state.doc, this._toolbarSelection);
        if (restoredSelection && (!restoredSelection.empty || restoredSelection instanceof CellSelection)) {
          return restoredSelection;
        }
      } catch (_) {}
    }
    if (this._savedSel && this._savedSel.from !== this._savedSel.to) {
      try {
        const restoredTextSelection = Selection.fromJSON(state.doc, {
          type: 'text',
          anchor: this._savedSel.from,
          head: this._savedSel.to,
        });
        if (restoredTextSelection && !restoredTextSelection.empty) {
          return restoredTextSelection;
        }
      } catch (_) {}
    }
    return null;
  }

  getWholeTableSelectionInfo() {
    const selection = this._getPreservedSelection();
    const pmWholeTableInfo = selection instanceof CellSelection
      ? this._getWholeTableSelectionInfo(selection)
      : null;
    if (pmWholeTableInfo && pmWholeTableInfo.text) return pmWholeTableInfo;
    return this._getDomWholeTableSelectionInfo();
  }

  getSelectionTextForAI() {
    if (!this.editor) return '';
    const selection = this._getPreservedSelection();
    if (!selection) return '';
    if (selection instanceof CellSelection) {
      const cellSelectionInfo = this._getCellSelectionInfo(selection) || this._getDomWholeTableSelectionInfo();
      if (cellSelectionInfo && cellSelectionInfo.text) return cellSelectionInfo.text;
    }
    const { doc } = this.editor.state;
    if (selection.from !== selection.to) {
      return (doc.textBetween(selection.from, selection.to, ' ') || '').trim();
    }
    return '';
  }

  _getCellSelectionTextNodes(selection = this._getActiveCellSelection()) {
    if (!selection) return [];
    const textNodes = [];
    selection.forEachCell((cell, cellPos) => {
      cell.descendants((node, offset) => {
        if (!node.isText || !node.text || !node.text.length) return;
        const from = cellPos + 1 + offset;
        textNodes.push({ node, from, to: from + node.nodeSize });
      });
    });
    return textNodes;
  }

  _getBlockNodeTextStyleValue(node, attrName) {
    if (!node) return '';
    const attrs = node.attrs || {};
    if (attrs[attrName] != null && attrs[attrName] !== '') return attrs[attrName];
    const cssProperty = _getDocxStylePropertyName(attrName);
    if (cssProperty && attrs.style) return _extractCssStyleValue(attrs.style, cssProperty);
    return '';
  }

  _setBlockNodeTextStyle(tr, node, pos, attrName, value) {
    if (!tr || !node) return tr;
    const attrs = node.attrs || {};
    const nextValue = value == null ? null : value;
    if (Object.prototype.hasOwnProperty.call(attrs, attrName)) {
      if ((attrs[attrName] ?? null) === nextValue) return tr;
      return tr.setNodeMarkup(pos, undefined, { ...attrs, [attrName]: nextValue });
    }
    const cssProperty = _getDocxStylePropertyName(attrName);
    if (!cssProperty || !Object.prototype.hasOwnProperty.call(attrs, 'style')) return tr;
    const nextStyle = _setCssStyleValue(attrs.style, cssProperty, nextValue);
    if ((attrs.style || '') === nextStyle) return tr;
    return tr.setNodeMarkup(pos, undefined, { ...attrs, style: nextStyle || null });
  }

  _getSelectionBlockNodes() {
    if (!this.editor) return [];
    const { state } = this.editor;
    const blockNodes = [];
    const seen = new Set();
    const pushNode = (node, pos) => {
      if (!node || !node.isTextblock || seen.has(pos)) return;
      seen.add(pos);
      blockNodes.push({ node, pos });
    };
    state.doc.nodesBetween(state.selection.from, state.selection.to, (node, pos) => {
      if (!node.isTextblock) return;
      pushNode(node, pos);
      return false;
    });
    if (!blockNodes.length) {
      const { $from } = state.selection;
      for (let depth = $from.depth; depth > 0; depth -= 1) {
        const node = $from.node(depth);
        if (!node || !node.isTextblock) continue;
        pushNode(node, $from.before(depth));
        break;
      }
    }
    return blockNodes;
  }

  _selectionHasBlockTextStyle(attrName, matcher) {
    if (!this.editor) return false;
    const blockNodes = this._getSelectionBlockNodes();
    if (!blockNodes.length || typeof matcher !== 'function') return false;
    return blockNodes.every(({ node }) => matcher(this._getBlockNodeTextStyleValue(node, attrName)));
  }

  _setSelectionBlockTextStyle(attrName, value) {
    if (!this.editor) return false;
    const { state, view } = this.editor;
    const blockNodes = this._getSelectionBlockNodes();
    if (!blockNodes.length) return false;
    let tr = state.tr;
    blockNodes.forEach(({ node, pos }) => {
      tr = this._setBlockNodeTextStyle(tr, node, pos, attrName, value);
    });
    view.focus();
    if (tr.docChanged) view.dispatch(tr);
    return tr.docChanged;
  }

  _getCellSelectionBlockNodes(selection = this._getActiveCellSelection()) {
    if (!selection) return [];
    const blockNodes = [];
    selection.forEachCell((cell, cellPos) => {
      cell.descendants((node, offset) => {
        if (!node.isTextblock) return;
        if (!Object.prototype.hasOwnProperty.call(node.attrs || {}, 'textAlign')) return;
        blockNodes.push({ node, pos: cellPos + 1 + offset });
      });
    });
    return blockNodes;
  }

  _cellSelectionHasMark(markName, selection = this._getActiveCellSelection()) {
    if (!this.editor || !selection) return false;
    const markType = this.editor.state.schema.marks[markName];
    if (!markType) return false;
    const textNodes = this._getCellSelectionTextNodes(selection);
    if (!textNodes.length) return false;
    return textNodes.every(({ node }) => node.marks.some(mark => mark.type === markType));
  }

  _getCellSelectionTextStyleValue(attrName, selection = this._getActiveCellSelection()) {
    if (!this.editor || !selection) return '';
    const textStyleType = this.editor.state.schema.marks.textStyle;
    if (!textStyleType) return '';
    const textNodes = this._getCellSelectionTextNodes(selection);
    if (!textNodes.length) return '';
    let value;
    for (const { node } of textNodes) {
      const mark = node.marks.find(item => item.type === textStyleType);
      const next = (mark && mark.attrs && mark.attrs[attrName]) || '';
      if (value === undefined) {
        value = next;
      } else if (value !== next) {
        return '';
      }
    }
    return value || '';
  }

  _getCellSelectionBlockAttrValue(attrName, { defaultValue = '' } = {}, selection = this._getActiveCellSelection()) {
    if (!selection) return '';
    const blockNodes = this._getCellSelectionBlockNodes(selection);
    if (!blockNodes.length) return defaultValue;
    let value;
    for (const { node } of blockNodes) {
      const next = node.attrs && node.attrs[attrName] != null ? node.attrs[attrName] : defaultValue;
      if (value === undefined) {
        value = next;
      } else if (value !== next) {
        return '';
      }
    }
    return value == null ? defaultValue : value;
  }

  _toggleCellSelectionMark(markName) {
    if (!this.editor) return false;
    const selection = this._getActiveCellSelection();
    if (!selection) return false;
    const { state, view } = this.editor;
    const markType = state.schema.marks[markName];
    if (!markType) return false;
    const textNodes = this._getCellSelectionTextNodes(selection);
    if (!textNodes.length) return true;
    const shouldRemove = this._cellSelectionHasMark(markName, selection);
    const tr = state.tr;
    textNodes.forEach(({ from, to }) => {
      if (shouldRemove) {
        tr.removeMark(from, to, markType);
      } else {
        tr.addMark(from, to, markType.create());
      }
    });
    view.focus();
    if (tr.docChanged) view.dispatch(tr);
    return true;
  }

  _removeCellSelectionMark(markName) {
    if (!this.editor) return false;
    const selection = this._getActiveCellSelection();
    if (!selection) return false;
    const { state, view } = this.editor;
    const markType = state.schema.marks[markName];
    if (!markType) return false;
    const textNodes = this._getCellSelectionTextNodes(selection);
    if (!textNodes.length) return false;
    const tr = state.tr;
    textNodes.forEach(({ from, to }) => {
      tr.removeMark(from, to, markType);
    });
    view.focus();
    if (tr.docChanged) view.dispatch(tr);
    return tr.docChanged;
  }

  _setCellSelectionTextStyle(stylePatch) {
    if (!this.editor) return false;
    const selection = this._getActiveCellSelection();
    if (!selection) return false;
    const { state, view } = this.editor;
    const textStyleType = state.schema.marks.textStyle;
    if (!textStyleType) return false;
    const textNodes = this._getCellSelectionTextNodes(selection);
    if (!textNodes.length) return true;
    const tr = state.tr;
    textNodes.forEach(({ node, from, to }) => {
      const current = node.marks.find(mark => mark.type === textStyleType);
      const nextAttrs = { ...(current ? current.attrs : {}), ...stylePatch };
      Object.keys(nextAttrs).forEach((key) => {
        if (nextAttrs[key] == null || nextAttrs[key] === '') delete nextAttrs[key];
      });
      tr.removeMark(from, to, textStyleType);
      if (Object.keys(nextAttrs).length) {
        tr.addMark(from, to, textStyleType.create(nextAttrs));
      }
    });
    view.focus();
    if (tr.docChanged) view.dispatch(tr);
    return true;
  }

  _setCellSelectionMark(markName, attrs = {}) {
    if (!this.editor) return false;
    const selection = this._getActiveCellSelection();
    if (!selection) return false;
    const { state, view } = this.editor;
    const markType = state.schema.marks[markName];
    if (!markType) return false;
    const textNodes = this._getCellSelectionTextNodes(selection);
    if (!textNodes.length) return true;
    const tr = state.tr;
    textNodes.forEach(({ from, to }) => {
      tr.removeMark(from, to, markType);
      tr.addMark(from, to, markType.create(attrs));
    });
    view.focus();
    if (tr.docChanged) view.dispatch(tr);
    return true;
  }

  _setCellSelectionBlockAttr(attrName, value, { defaultValue = null } = {}) {
    if (!this.editor) return false;
    const selection = this._getActiveCellSelection();
    if (!selection) return false;
    const { state, view } = this.editor;
    const blockNodes = this._getCellSelectionBlockNodes(selection);
    if (!blockNodes.length) return true;
    const tr = state.tr;
    blockNodes.forEach(({ node, pos }) => {
      const nextValue = value == null ? defaultValue : value;
      if ((node.attrs && node.attrs[attrName]) === nextValue) return;
      tr.setNodeMarkup(pos, undefined, { ...node.attrs, [attrName]: nextValue });
    });
    view.focus();
    if (tr.docChanged) view.dispatch(tr);
    return true;
  }

  _clearCellSelectionMarks() {
    if (!this.editor) return false;
    const selection = this._getActiveCellSelection();
    if (!selection) return false;
    const { state, view } = this.editor;
    const textNodes = this._getCellSelectionTextNodes(selection);
    if (!textNodes.length) return true;
    const tr = state.tr;
    textNodes.forEach(({ node, from, to }) => {
      node.marks.forEach(mark => tr.removeMark(from, to, mark.type));
    });
    view.focus();
    if (tr.docChanged) view.dispatch(tr);
    return true;
  }

  _applyCellSelectionCommand(command, value = null) {
    if (!this._getActiveCellSelection()) return false;
    switch (command) {
      case 'toggleBold': {
        const selection = this._getActiveCellSelection();
        const hadMarkBold = this._cellSelectionHasMark('bold', selection);
        const hasBlockBold = _isDocxBoldValue(this._getCellSelectionBlockAttrValue('fontWeight', { defaultValue: null }, selection));
        let changed = false;
        if (hadMarkBold) changed = this._removeCellSelectionMark('bold') || changed;
        if (hasBlockBold) changed = this._setCellSelectionBlockAttr('fontWeight', null, { defaultValue: null }) || changed;
        return changed || this._toggleCellSelectionMark('bold');
      }
      case 'toggleUnderline':
        return this._toggleCellSelectionMark('underline');
      case 'toggleItalic': {
        const selection = this._getActiveCellSelection();
        const hadMarkItalic = this._cellSelectionHasMark('italic', selection);
        const hasBlockItalic = _isDocxItalicValue(this._getCellSelectionBlockAttrValue('fontStyle', { defaultValue: null }, selection));
        let changed = false;
        if (hadMarkItalic) changed = this._removeCellSelectionMark('italic') || changed;
        if (hasBlockItalic) changed = this._setCellSelectionBlockAttr('fontStyle', null, { defaultValue: null }) || changed;
        return changed || this._toggleCellSelectionMark('italic');
      }
      case 'toggleStrike':
        return this._toggleCellSelectionMark('strike');
      case 'setTextAlignLeft':
        return this._setCellSelectionBlockAttr('textAlign', 'left', { defaultValue: null });
      case 'setTextAlignCenter':
        return this._setCellSelectionBlockAttr('textAlign', 'center', { defaultValue: null });
      case 'setTextAlignRight':
        return this._setCellSelectionBlockAttr('textAlign', 'right', { defaultValue: null });
      case 'setTextAlignJustify':
        return this._setCellSelectionBlockAttr('textAlign', 'justify', { defaultValue: null });
      case 'setFontFamily':
        return this._setCellSelectionTextStyle({ fontFamily: value });
      case 'unsetFontFamily':
        return this._setCellSelectionTextStyle({ fontFamily: null });
      case 'setFontSize':
        return this._setCellSelectionTextStyle({ fontSize: value });
      case 'unsetFontSize':
        return this._setCellSelectionTextStyle({ fontSize: null });
      case 'setColor':
        return this._setCellSelectionTextStyle({ color: value });
      case 'setHighlight':
        return this._setCellSelectionMark('highlight', { color: value });
      case 'unsetAllMarks':
        return this._clearCellSelectionMarks();
      default:
        return false;
    }
  }

  // ── _setupPageFeatures ────────────────────────────────────────
  // Sets up the scroll-based page indicator.
  // Actual page-break visuals and counting are handled entirely by
  // AutoPageBreakPlugin (widget decorations). When the plugin finishes each
  // measurement it calls storage.autoPageBreak.onPageCountChange(n), which
  // was wired in render() to update _totalPages and refresh the indicator.
  // This method only registers the scroll listener for current-page tracking.
  _getDocxPageBreakBoundaries() {
    const scrollEl = this._scrollEl || document.getElementById('wa-editor-content');
    const boundaryRoot = this._zoomWrapper || this.editor?.view?.dom?.parentElement || this.editor?.view?.dom;
    if (!scrollEl || !boundaryRoot) return [];

    const scrollRect = scrollEl.getBoundingClientRect();
    return Array.from(boundaryRoot.querySelectorAll('[data-page-break],[data-soft-page-break]'))
      .map((el) => el.getBoundingClientRect().top - scrollRect.top + scrollEl.scrollTop)
      .filter((top) => Number.isFinite(top))
      .sort((left, right) => left - right)
      .filter((top, idx, arr) => idx === 0 || Math.abs(top - arr[idx - 1]) > 1);
  }

  getDocxNavigationAnchorOffset() {
    const configuredMarginTop = Number(this._marginTopPx);
    if (Number.isFinite(configuredMarginTop) && configuredMarginTop > 0) {
      return Math.min(120, configuredMarginTop);
    }

    const pm = this.editor?.view?.dom;
    if (pm && typeof window.getComputedStyle === 'function') {
      const pmStyle = window.getComputedStyle(pm);
      const paddingTop = parseFloat(pmStyle.paddingTop || '0');
      if (Number.isFinite(paddingTop) && paddingTop > 0) {
        return Math.min(120, paddingTop);
      }
    }

    return 96;
  }

  getDocxTargetScrollTop(target) {
    if (!target) return null;
    const scrollEl = this._scrollEl || document.getElementById('wa-editor-content');
    if (!scrollEl) return null;

    const scrollRect = scrollEl.getBoundingClientRect();
    const targetRect = target.getBoundingClientRect();
    const relativeTop = targetRect.top - scrollRect.top + scrollEl.scrollTop;
    return Number.isFinite(relativeTop) ? relativeTop : null;
  }

  _getCurrentDocxPage(totalPages = this._totalPages) {
    const normalizedTotal = Math.max(1, totalPages || 1);
    if (!this._scrollEl) return 1;

    const threshold = this._scrollEl.scrollTop + this.getDocxNavigationAnchorOffset();
    const boundaries = this._getDocxPageBreakBoundaries();
    if (!boundaries.length) return 1;

    let currentPage = 1;
    for (const boundaryTop of boundaries) {
      if (threshold >= boundaryTop) currentPage += 1;
      else break;
    }

    return Math.max(1, Math.min(normalizedTotal, currentPage));
  }

  _updatePageIndicator(totalPages = this._totalPages) {
    if (!this._pageIndicator) return;
    const normalizedTotal = Math.max(1, totalPages || 1);
    const curPage = this._getCurrentDocxPage(normalizedTotal);
    this._pageIndicator.textContent = `第 ${curPage} 页 / 共 ${normalizedTotal} 页`;
  }

  _setupPageFeatures() {
    if (!this.editor) return;
    const editable    = this.editor.view.dom;      // .ProseMirror
    const zoomWrapper = editable.parentElement;    // .koto-zoom-wrapper
    const scrollEl    = zoomWrapper?.parentElement
                     || document.getElementById('wa-editor-content');
    if (!scrollEl) return;
    this._scrollEl    = scrollEl;
    this._zoomWrapper = zoomWrapper;

    // ── Update page indicator label (scroll-driven) ────────────────────────
    const _updatePI = () => {
      this._updatePageIndicator();
    };

    this._scrollHandler = _updatePI;
    scrollEl.addEventListener('scroll', this._scrollHandler, { passive: true });

    // Bootstrap indicator (plugin will update totalPages asynchronously)
    requestAnimationFrame(_updatePI);
  }

  syncReviewProposals(proposals, options = {}) {
    this._reviewPreviewProposals = Array.isArray(proposals) ? proposals.slice() : [];
    this._reviewPreviewFocusedId = String(options.focusedId || '').trim();
    this._reviewPreviewMatches = [];
    this._clearReviewProposalHighlights();
    this._clearReviewProposalAnchors();

    if (!this.editor || !this._scrollEl || !this._reviewPreviewProposals.length) return [];

    const index = _buildAiPreviewTextIndex(this.editor.view?.dom);
    if (!index || !index.normalizedText) return [];

    const occupied = [];
    this._reviewPreviewProposals.forEach((proposal) => {
      const reviewId = String((proposal && (proposal.review_id || proposal.id)) || '').trim();
      const originalText = _normalizeAiPreviewText(proposal && proposal.original_text);
      if (!reviewId || !originalText) return;

      let searchFrom = 0;
      while (searchFrom < index.normalizedText.length) {
        const matchStart = index.normalizedText.indexOf(originalText, searchFrom);
        if (matchStart === -1) return;
        const matchEnd = matchStart + originalText.length;
        const overlaps = occupied.some(([start, end]) => matchStart < end && matchEnd > start);
        if (!overlaps) {
          const range = _createAiPreviewRange(index, matchStart, matchEnd);
          if (!range) return;
          occupied.push([matchStart, matchEnd]);
          this._reviewPreviewMatches.push({ proposal, range, reviewId });
          return;
        }
        searchFrom = matchStart + Math.max(1, originalText.length);
      }
    });

    this._applyReviewProposalHighlights();
    this._renderReviewProposalAnchors();
    if (this._reviewPreviewFocusedId) {
      requestAnimationFrame(() => this._scrollFocusedReviewProposalIntoView());
    }
    return this._reviewPreviewMatches.slice();
  }

  clearReviewProposals() {
    this._reviewPreviewProposals = [];
    this._reviewPreviewMatches = [];
    this._reviewPreviewFocusedId = '';
    this._clearReviewProposalHighlights();
    this._clearReviewProposalAnchors();
  }

  _clearReviewProposalHighlights() {
    if (!window.CSS || !CSS.highlights) return;
    try { CSS.highlights.delete(_AI_REVIEW_PENDING_HIGHLIGHT); } catch (_) {}
    try { CSS.highlights.delete(_AI_REVIEW_FOCUS_HIGHLIGHT); } catch (_) {}
  }

  _applyReviewProposalHighlights() {
    if (!window.CSS || !CSS.highlights) return;
    const ranges = this._reviewPreviewMatches.map((entry) => entry.range).filter(Boolean);
    if (!ranges.length) return;
    CSS.highlights.set(_AI_REVIEW_PENDING_HIGHLIGHT, new Highlight(...ranges));

    const focused = this._reviewPreviewMatches.find((entry) => entry.reviewId === this._reviewPreviewFocusedId || String(entry.proposal?.id || '') === this._reviewPreviewFocusedId);
    if (focused && focused.range) {
      CSS.highlights.set(_AI_REVIEW_FOCUS_HIGHLIGHT, new Highlight(focused.range));
    }
  }

  _clearReviewProposalAnchors() {
    if (!this._reviewPreviewAnchorLayer) return;
    this._reviewPreviewAnchorLayer.innerHTML = '';
  }

  _ensureReviewProposalAnchorLayer() {
    if (!this._scrollEl) return null;
    if (this._reviewPreviewAnchorLayer && this._reviewPreviewAnchorLayer.isConnected) {
      return this._reviewPreviewAnchorLayer;
    }
    if (window.getComputedStyle(this._scrollEl).position === 'static') {
      this._scrollEl.style.position = 'relative';
    }
    const layer = document.createElement('div');
    layer.className = 'koto-ai-review-anchor-layer';
    this._scrollEl.appendChild(layer);
    this._reviewPreviewAnchorLayer = layer;
    return layer;
  }

  _renderReviewProposalAnchors() {
    const layer = this._ensureReviewProposalAnchorLayer();
    if (!layer || !this._scrollEl) return;
    layer.innerHTML = '';
    if (!this._reviewPreviewMatches.length) return;

    layer.style.width = Math.max(this._scrollEl.scrollWidth, this._scrollEl.clientWidth) + 'px';
    layer.style.height = Math.max(this._scrollEl.scrollHeight, this._scrollEl.clientHeight) + 'px';

    const scrollRect = this._scrollEl.getBoundingClientRect();
    const scrollTop = this._scrollEl.scrollTop;
    const scrollLeft = this._scrollEl.scrollLeft;
    const pageRect = this._zoomWrapper ? this._zoomWrapper.getBoundingClientRect() : null;
    const pageRight = pageRect
      ? (pageRect.right - scrollRect.left + scrollLeft + 18)
      : null;

    const placed = [];
    this._reviewPreviewMatches.forEach((entry) => {
      const rect = entry.range.getBoundingClientRect();
      if (!rect || (!rect.width && !rect.height)) return;

      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'koto-ai-review-anchor';
      if (entry.reviewId === this._reviewPreviewFocusedId || String(entry.proposal?.id || '') === this._reviewPreviewFocusedId) {
        button.classList.add('focused');
      }

      const badge = document.createElement('span');
      badge.className = 'koto-ai-review-anchor-badge';
      badge.textContent = 'AI 建议';
      button.appendChild(badge);

      const text = document.createElement('span');
      text.className = 'koto-ai-review-anchor-text';
      text.textContent = _previewAnchorText(entry.proposal?.proposed_text || entry.proposal?.value || '') || '查看修改建议';
      button.appendChild(text);

      const originalPreview = _previewAnchorText(entry.proposal?.original_text || '', 64);
      const proposedPreview = _previewAnchorText(entry.proposal?.proposed_text || entry.proposal?.value || '', 64);
      button.title = originalPreview && proposedPreview
        ? `原文：${originalPreview}\n建议：${proposedPreview}`
        : (proposedPreview || originalPreview || '查看 AI 修改建议');
      button.addEventListener('click', () => {
        if (window.WA && typeof window.WA.focusReviewThread === 'function') {
          window.WA.focusReviewThread(entry.reviewId);
        }
      });

      let top = rect.top - scrollRect.top + scrollTop - 4;
      let left = pageRight != null
        ? pageRight
        : (rect.right - scrollRect.left + scrollLeft + 12);

      const width = 198;
      left = Math.max(12, Math.min(left, Math.max(12, layer.clientWidth - width - 12)));
      placed.forEach((item) => {
        const overlapsVertically = Math.abs(top - item.top) < 30;
        const overlapsHorizontally = Math.abs(left - item.left) < 210;
        if (overlapsVertically && overlapsHorizontally) {
          top = item.top + 34;
        }
      });
      placed.push({ top, left });

      button.style.top = `${Math.max(0, top)}px`;
      button.style.left = `${left}px`;
      layer.appendChild(button);
    });
  }

  _scrollFocusedReviewProposalIntoView() {
    if (!this._scrollEl || !this._reviewPreviewFocusedId) return;
    const focused = this._reviewPreviewMatches.find((entry) => entry.reviewId === this._reviewPreviewFocusedId || String(entry.proposal?.id || '') === this._reviewPreviewFocusedId);
    if (!focused || !focused.range) return;
    const rect = focused.range.getBoundingClientRect();
    const scrollRect = this._scrollEl.getBoundingClientRect();
    const top = this._scrollEl.scrollTop + (rect.top - scrollRect.top) - 96;
    this._scrollEl.scrollTo({ top: Math.max(0, top), behavior: 'smooth' });
  }

  _scrollDocxTargetIntoView(target, { behavior = 'smooth', offset = null } = {}) {
    if (!target) return;
    const scrollEl = this._scrollEl || document.getElementById('wa-editor-content');
    if (!scrollEl) {
      target.scrollIntoView({ behavior, block: 'center' });
      return;
    }

    const targetTop = this.getDocxTargetScrollTop(target);
    if (targetTop === null) return;

    const resolvedOffset = Number.isFinite(offset) ? offset : this.getDocxNavigationAnchorOffset();
    scrollEl.scrollTo({ top: Math.max(0, targetTop - resolvedOffset), behavior });
  }

  _distributeTableColumnsEvenly() {
    if (!this.editor) return;
    try {
      const { state, view } = this.editor;
      const tableInfo = findTable(state.selection.$anchor);
      if (!tableInfo) return;
      const { node: tableNode, start: tableStart } = tableInfo;
      const map = TableMap.get(tableNode);
      const numCols = map.width;
      if (numCols < 2) return;

      let totalWidth = 0;
      for (let col = 0; col < numCols; ) {
        const cellOffset = map.map[col];
        const cell = tableNode.nodeAt(cellOffset);
        if (!cell) { col++; continue; }
        const colwidth = cell.attrs.colwidth;
        if (colwidth && colwidth.length > 0) {
          totalWidth += colwidth.reduce((sum, value) => sum + (value || 0), 0);
        } else {
          totalWidth += 100 * (cell.attrs.colspan || 1);
        }
        col += cell.attrs.colspan || 1;
      }
      if (totalWidth <= 0) totalWidth = numCols * 100;
      const equalWidth = Math.round(totalWidth / numCols);

      let tr = state.tr;
      for (let row = 0; row < map.height; row++) {
        const seen = new Set();
        for (let col = 0; col < numCols; col++) {
          const cellOffset = map.map[row * numCols + col];
          if (seen.has(cellOffset)) continue;
          seen.add(cellOffset);
          const cell = tableNode.nodeAt(cellOffset);
          if (!cell) continue;
          const colspan = cell.attrs.colspan || 1;
          const newColwidth = Array.from({ length: colspan }, () => equalWidth);
          tr = tr.setNodeMarkup(tableStart + cellOffset, undefined, {
            ...cell.attrs,
            colwidth: newColwidth,
          });
        }
      }
      view.dispatch(tr);
    } catch (error) {
      console.error('[koto] distributeColumnsEvenly', error);
    }
  }

  // ── _injectTableToolbar ─────────────────────────────────────────────────
  // Injects the bottom-docked table toolbar and wires its buttons + visibility.
  _injectTableToolbar(wrap) {
    if (!this.editor) return;
    const ed = this.editor;

    // Inject toolbar HTML
    const tbDiv = document.createElement('div');
    tbDiv.innerHTML = _TABLE_TOOLBAR_HTML;
    const toolbar = tbDiv.firstElementChild;
    const pageIndicator = wrap.querySelector('#wa-docx-page-indicator');
    if (pageIndicator) wrap.insertBefore(toolbar, pageIndicator);
    else wrap.appendChild(toolbar);

    // Colours for cell background picker
    const _CELL_COLORS = [
      '#ffffff','#f2f2f2','#d9d9d9','#bfbfbf','#808080','#404040','#1f1f1f','#000000',
      '#c00000','#ff0000','#ff6d00','#ff9900','#ffc000','#ffff00','#92d050','#00b050',
      '#00b0f0','#0070c0','#4472c4','#2e75b6','#1f3864','#7030a0','#984ea3','#c9a0dc',
      '#fbe4d5','#daeef3','#e2efda','#d6dce4','#fff2cc','#f8d7da','#d4edda','#cce5ff',
    ];

    const cpPopup = toolbar.querySelector('#ttf-cp-popup');
    const cpGrid  = toolbar.querySelector('#ttf-cp-grid');
    const cpCustom = toolbar.querySelector('#ttf-cp-custom');
    const cpClear = toolbar.querySelector('#ttf-cp-clear');

    const _applyCellBg = (color) => {
      if (!ed.isActive('tableCell') && !ed.isActive('tableHeader')) return;
      ed.chain().focus().setCellAttribute('backgroundColor', color || null).run();
      const sw = toolbar.querySelector('#ttf-cell-bg-swatch');
      if (sw) sw.style.background = color || 'transparent';
    };

    const _openCellColorPicker = (triggerBtn) => {
      if (!cpPopup) return;
      if (cpPopup.style.display !== 'none') { cpPopup.style.display = 'none'; return; }
      cpGrid.innerHTML = _CELL_COLORS.map(c =>
        `<div data-cell-color="${c}" title="${c}" style="width:18px;height:18px;border-radius:3px;background:${c};cursor:pointer;border:1px solid rgba(255,255,255,.12);box-sizing:border-box;" onmousedown="event.preventDefault()"></div>`
      ).join('');
      if (triggerBtn) {
        const r = triggerBtn.getBoundingClientRect();
        cpPopup.style.left = Math.max(4, Math.min(r.left, window.innerWidth - 180)) + 'px';
        cpPopup.style.top  = (r.bottom + 4) + 'px';
        cpPopup.style.position = 'fixed';
      }
      cpPopup.style.display = 'block';
    };

    if (cpGrid) {
      cpGrid.addEventListener('click', (e) => {
        const el = e.target.closest('[data-cell-color]');
        if (!el) return;
        _applyCellBg(el.dataset.cellColor);
        if (cpPopup) cpPopup.style.display = 'none';
      });
    }

    if (cpCustom) {
      cpCustom.addEventListener('input', () => _applyCellBg(cpCustom.value));
    }
    if (cpClear) {
      cpClear.addEventListener('click', () => { _applyCellBg(null); if (cpPopup) cpPopup.style.display = 'none'; });
    }

    // Close cell color picker on outside click
    document.addEventListener('mousedown', (evt) => {
      if (!cpPopup || cpPopup.style.display === 'none') return;
      if (cpPopup.contains(evt.target)) return;
      if (evt.target.closest('[data-table-cmd="setCellBgColor"]')) return;
      cpPopup.style.display = 'none';
    }, true);

    // Wire button clicks
    toolbar.addEventListener('click', (e) => {
      const btn = e.target.closest('[data-table-cmd]');
      if (!btn) return;
      e.preventDefault();
      const cmd = btn.dataset.tableCmd;

      switch (cmd) {
        case 'addRowBefore':    ed.chain().focus().addRowBefore().run(); break;
        case 'addRowAfter':     ed.chain().focus().addRowAfter().run(); break;
        case 'addColumnBefore': ed.chain().focus().addColumnBefore().run(); break;
        case 'addColumnAfter':  ed.chain().focus().addColumnAfter().run(); break;
        case 'deleteRow':       ed.chain().focus().deleteRow().run(); break;
        case 'deleteColumn':    ed.chain().focus().deleteColumn().run(); break;
        case 'mergeCells':      ed.chain().focus().mergeCells().run(); break;
        case 'splitCell':       ed.chain().focus().splitCell().run(); break;
        case 'deleteTable':     ed.chain().focus().deleteTable().run(); break;
        case 'toggleHeaderRow':    ed.chain().focus().toggleHeaderRow().run(); break;
        case 'toggleHeaderColumn': ed.chain().focus().toggleHeaderColumn().run(); break;
        case 'setTextAlignLeft':
          if (!this._applyCellSelectionCommand('setTextAlignLeft')) ed.chain().focus().setTextAlign('left').run(); break;
        case 'setTextAlignCenter':
          if (!this._applyCellSelectionCommand('setTextAlignCenter')) ed.chain().focus().setTextAlign('center').run(); break;
        case 'setTextAlignRight':
          if (!this._applyCellSelectionCommand('setTextAlignRight')) ed.chain().focus().setTextAlign('right').run(); break;
        case 'setTextAlignJustify':
          if (!this._applyCellSelectionCommand('setTextAlignJustify')) ed.chain().focus().setTextAlign('justify').run(); break;
        case 'setCellAlignTop':
          ed.chain().focus().setCellAttribute('verticalAlign', 'top').run(); break;
        case 'setCellAlignMiddle':
          ed.chain().focus().setCellAttribute('verticalAlign', 'middle').run(); break;
        case 'setCellAlignBottom':
          ed.chain().focus().setCellAttribute('verticalAlign', 'bottom').run(); break;
        case 'setCellBgColor':
          _openCellColorPicker(btn); return;

        // ── Select row / column / entire table ──────────────────────────
        case 'selectRow': {
          try {
            const { state } = ed;
            const $cell = selectionCell(state);
            if (!$cell) break;
            const sel = CellSelection.rowSelection($cell);
            ed.view.dispatch(state.tr.setSelection(sel));
          } catch(e) { /* not in a table cell */ }
          break;
        }
        case 'selectColumn': {
          try {
            const { state } = ed;
            const $cell = selectionCell(state);
            if (!$cell) break;
            const sel = CellSelection.colSelection($cell);
            ed.view.dispatch(state.tr.setSelection(sel));
          } catch(e) { /* not in a table cell */ }
          break;
        }
        case 'selectTable': {
          try {
            const { state } = ed;
            const tableInfo = findTable(state.selection.$anchor);
            if (!tableInfo) break;
            const map = TableMap.get(tableInfo.node);
            const tableStart = tableInfo.start;
            // anchor = top-left cell, head = bottom-right cell
            const $anchor = state.doc.resolve(tableStart + map.map[0]);
            const $head   = state.doc.resolve(tableStart + map.map[map.map.length - 1]);
            const sel = new CellSelection($anchor, $head);
            ed.view.dispatch(state.tr.setSelection(sel));
          } catch(e) { /* not in a table */ }
          break;
        }

        case 'distributeColumnsEvenly': {
          this._distributeTableColumnsEvenly();
          break;
        }
      }
    });

    // Show/hide toolbar based on cursor position.
    // Guarded by requestAnimationFrame so the DOM update is batched once per
    // frame even when prosemirror-tables fires many mousemove transactions
    // during a cell drag-selection.  Without this guard, each transaction
    // triggers a layout recalculation which amplified the table-stretch bug.
    let _toolbarRafId = 0;
    const _updateTableToolbarVisibility = () => {
      if (_toolbarRafId) return; // already scheduled this frame
      _toolbarRafId = requestAnimationFrame(() => {
        _toolbarRafId = 0;
        if (!ed || ed.isDestroyed) { toolbar.style.display = 'none'; return; }
        _doUpdateTableToolbar();
      });
    };
    const _doUpdateTableToolbar = () => {
      if (!ed || ed.isDestroyed) { toolbar.style.display = 'none'; return; }
      const inTable = ed.isActive('table');
      toolbar.style.display = inTable ? 'flex' : 'none';
      if (!inTable) {
        if (cpPopup) cpPopup.style.display = 'none';
        return;
      }

      // Update quickbar state
      const cellAttrs = ed.getAttributes('tableCell') || ed.getAttributes('tableHeader') || {};

      // Update cell bg swatch
      const sw = toolbar.querySelector('#ttf-cell-bg-swatch');
      if (sw) sw.style.background = cellAttrs.backgroundColor || 'transparent';

      const _setButtonState = (command, isActive) => {
        const button = toolbar.querySelector(`[data-table-cmd="${command}"]`);
        if (button) button.classList.toggle('is-active', !!isActive);
      };

      const cellSelection = this._getActiveCellSelection();
      const textAlign = cellSelection
        ? this._getCellSelectionBlockAttrValue('textAlign', { defaultValue: 'left' }, cellSelection)
        : (['left', 'center', 'right', 'justify']
          .find(align => ed.isActive({ textAlign: align })) || 'left');
      const verticalAlign = cellAttrs.verticalAlign || 'top';

      _setButtonState('toggleHeaderRow', ed.isActive('tableHeader'));
      _setButtonState('setTextAlignLeft', textAlign === 'left');
      _setButtonState('setTextAlignCenter', textAlign === 'center');
      _setButtonState('setTextAlignRight', textAlign === 'right');
      _setButtonState('setTextAlignJustify', textAlign === 'justify');
      _setButtonState('setCellAlignTop', verticalAlign === 'top');
      _setButtonState('setCellAlignMiddle', verticalAlign === 'middle');
      _setButtonState('setCellAlignBottom', verticalAlign === 'bottom');
    };

    const _tableToolbarUpdateHandler = ({ transaction } = {}) => {
      if (transaction?.getMeta?.(DOCX_TABLE_RESIZE_TRANSACTION_META)) return;
      _updateTableToolbarVisibility();
    };
    ed.on('selectionUpdate', _tableToolbarUpdateHandler);
    ed.on('update', _tableToolbarUpdateHandler);
    this._tableToolbarUpdateFn = _tableToolbarUpdateHandler;

    // ── Table size picker (for insert table button) ──────────────────────
    this._wireTableSizePicker(wrap);
  }

  // ── _wireTableSizePicker ────────────────────────────────────────────────
  // Interactive NxM grid picker for the insertTable toolbar button.
  _wireTableSizePicker(wrap) {
    const pickerWrap = wrap.querySelector('#tt-table-picker');
    const grid = wrap.querySelector('#tt-table-grid');
    const label = wrap.querySelector('#tt-table-picker-label');
    const insertBtn = wrap.querySelector('[data-cmd="insertTable"]');
    if (!pickerWrap || !grid || !insertBtn || !this.editor) return;
    const ed = this.editor;

    const MAX_ROWS = 8, MAX_COLS = 8;
    let isOpen = false;

    // Build grid cells
    grid.innerHTML = '';
    for (let r = 0; r < MAX_ROWS; r++) {
      for (let c = 0; c < MAX_COLS; c++) {
        const cell = document.createElement('div');
        cell.className = 'tt-tpick-cell';
        cell.dataset.row = String(r + 1);
        cell.dataset.col = String(c + 1);
        grid.appendChild(cell);
      }
    }

    const _highlight = (rows, cols) => {
      grid.querySelectorAll('.tt-tpick-cell').forEach(c => {
        const cr = parseInt(c.dataset.row);
        const cc = parseInt(c.dataset.col);
        c.classList.toggle('active', cr <= rows && cc <= cols);
      });
      if (label) label.textContent = `${rows} × ${cols} 表格`;
    };

    grid.addEventListener('mouseover', (e) => {
      const cell = e.target.closest('.tt-tpick-cell');
      if (cell) _highlight(parseInt(cell.dataset.row), parseInt(cell.dataset.col));
    });

    grid.addEventListener('click', (e) => {
      const cell = e.target.closest('.tt-tpick-cell');
      if (!cell) return;
      const rows = parseInt(cell.dataset.row);
      const cols = parseInt(cell.dataset.col);
      ed.chain().focus().insertTable({ rows, cols, withHeaderRow: true }).run();
      pickerWrap.style.display = 'none';
      isOpen = false;
    });

    // Override the insertTable button to show picker instead
    insertBtn.addEventListener('mousedown', (e) => {
      e.preventDefault();
      e.stopPropagation();
      if (isOpen) { pickerWrap.style.display = 'none'; isOpen = false; return; }
      pickerWrap.style.display = 'block';
      isOpen = true;
      _highlight(0, 0);
      if (label) label.textContent = '选择表格大小';
    }, true);

    // Close on outside click
    document.addEventListener('mousedown', (evt) => {
      if (!isOpen) return;
      if (pickerWrap.contains(evt.target)) return;
      if (insertBtn.contains(evt.target)) return;
      pickerWrap.style.display = 'none';
      isOpen = false;
    }, true);
  }

  // ── _wireTableBorderSelect ──────────────────────────────────────────────
  // Word-like behavior: clicking on a table's outer border selects the entire
  // table. Detects clicks that land on the tableWrapper but NOT inside any
  // cell content, or on the very edge of the table element itself.
  _wireTableBorderSelect(container) {
    if (!this.editor) return;
    const EDGE_PX = 6; // border detection threshold in pixels

    const _clearTableSelection = () => {
      container.querySelectorAll('.tableWrapper.koto-table-selected')
        .forEach(tw => tw.classList.remove('koto-table-selected'));
    };

    this._tableBorderHandler = (e) => {
      if (!this.editor) return;

      // Only handle left-click
      if (e.button !== 0) return;

      // Find the closest table-related element
      const tableWrapper = e.target.closest('.tableWrapper');
      const cell = e.target.closest('td, th');

      // Case 1: Click is on the tableWrapper but NOT inside a cell
      // (e.g. the gap around the table in the wrapper)
      if (tableWrapper && !cell) {
        e.preventDefault();
        e.stopPropagation();
        this._selectTableNode(tableWrapper);
        _clearTableSelection();
        tableWrapper.classList.add('koto-table-selected');
        return;
      }

      // Case 2: Click is inside a cell — check if it's on the outer edge
      // of the TABLE (not an inner border between cells)
      if (cell) {
        const table = cell.closest('table');
        if (!table) { _clearTableSelection(); return; }
        const tableRect = table.getBoundingClientRect();
        const x = e.clientX;
        const y = e.clientY;
        const onLeftEdge   = x - tableRect.left  < EDGE_PX;
        const onRightEdge  = tableRect.right  - x < EDGE_PX;
        const onTopEdge    = y - tableRect.top    < EDGE_PX;
        const onBottomEdge = tableRect.bottom - y < EDGE_PX;

        if (onLeftEdge || onRightEdge || onTopEdge || onBottomEdge) {
          e.preventDefault();
          e.stopPropagation();
          const tw = table.closest('.tableWrapper');
          this._selectTableNode(tw || table);
          _clearTableSelection();
          if (tw) tw.classList.add('koto-table-selected');
          return;
        }
      }

      // Click elsewhere — clear table selection
      if (!tableWrapper) {
        _clearTableSelection();
      }
    };

    container.addEventListener('mousedown', this._tableBorderHandler, true);
  }

  // Find the ProseMirror table node and select all its cells via CellSelection
  _selectTableNode(wrapperOrTable) {
    if (!this.editor) return;
    const view = this.editor.view;
    const table = wrapperOrTable.tagName === 'TABLE'
      ? wrapperOrTable
      : wrapperOrTable.querySelector('table');
    if (!table) return;

    // Walk ProseMirror document to find the table node position
    const doc = view.state.doc;
    let tablePos = null;
    let tableNode = null;
    doc.descendants((node, pos) => {
      if (tablePos !== null) return false;
      if (node.type.name === 'table') {
        const domNode = view.nodeDOM(pos);
        if (domNode === table || (domNode && domNode.querySelector && domNode.querySelector('table') === table)) {
          tablePos = pos;
          tableNode = node;
          return false;
        }
      }
    });

    if (tablePos !== null && tableNode) {
      try {
        // Find first and last cell positions in the table
        const $firstCell = doc.resolve(tablePos + 2); // table > row > first cell
        // Find last cell: traverse to end of table
        let lastCellPos = tablePos + 1; // start of first row
        tableNode.descendants((node, offset) => {
          if (node.type.name === 'tableCell' || node.type.name === 'tableHeader') {
            lastCellPos = tablePos + 1 + offset;
          }
        });
        const $lastCell = doc.resolve(lastCellPos);

        const cellSel = CellSelection.create(doc, $firstCell.pos, $lastCell.pos);
        const tr = view.state.tr.setSelection(cellSel);
        view.dispatch(tr);
      } catch (_) {
        // CellSelection may fail on edge cases; silently ignore
      }
    }
  }

  // ── setZoom ────────────────────────────────────────────────────────────────
  setZoom(pct) {
    this._zoom = Math.max(50, Math.min(200, pct));

    // ── Throttle CSS zoom to one reflow per animation frame ─────────────
    if (!this._pendingZoomRaf) {
      this._pendingZoomRaf = requestAnimationFrame(() => {
        this._pendingZoomRaf = null;
        this._applyZoom();
      });
    }

    // Zoom no longer triggers pagination recalc.  Page breaks are measured
    // at zoom=1 (see AutoPageBreakPlugin._measure) so they stay stable
    // regardless of UI zoom level.  Only content edits trigger re-measurement.
  }

  _applyZoom() {
    if (!this.editor) return;
    const zoomEl = this._zoomWrapper || this.editor.view.dom.parentElement;
    if (zoomEl) {
      const scale = this._zoom / 100;
      zoomEl.style.transform = `scale(${scale})`;
      zoomEl.style.transformOrigin = 'top center';
      // Add margin-bottom so scrollable container accounts for scaled height
      // This prevents the bottom of the document from clipping when zoomed in
      const extraHeight = zoomEl.offsetHeight * (scale - 1);
      zoomEl.style.marginBottom = Math.max(0, extraHeight) + 'px';
    }
    requestAnimationFrame(() => {
      this._updatePageIndicator();
      this._renderReviewProposalAnchors();
      if (window.WA && typeof window.WA.relayoutDocxReviewRail === 'function') {
        window.WA.relayoutDocxReviewRail();
      }
    });
  }

  _ensureDocxSections() {
    if (!Array.isArray(this._sections)) this._sections = [];
    if (!this._sections.length) {
      this._sections = [{
        page_width_px: this._pageWidthPx || null,
        page_height_px: this._pageHeightPx || null,
        margin_top_px: this._marginTopPx || null,
        margin_bottom_px: this._marginBottomPx || null,
        margin_left_px: this._marginLeftPx || null,
        margin_right_px: this._marginRightPx || null,
        header_html: this._headerHtml || '',
        footer_html: this._footerHtml || '',
        first_header_html: '',
        first_footer_html: '',
        even_header_html: '',
        even_footer_html: '',
      }];
    }
    return this._sections;
  }

  _syncSectionsToStorage() {
    if (this.editor?.storage?.autoPageBreak) {
      this.editor.storage.autoPageBreak.sections = this._sections || [];
    }
  }

  _updateSectionField(fieldName, value, allSections = false) {
    const sections = this._ensureDocxSections();
    if (allSections) {
      sections.forEach((section) => {
        if (section && typeof section === 'object') section[fieldName] = value;
      });
    } else {
      const section = sections[0] || {};
      section[fieldName] = value;
      sections[0] = section;
    }
    this._syncSectionsToStorage();
  }

  _setHeaderFooterSlotState(slotEl, html, slotType) {
    if (!slotEl) return;
    const hasContent = _hasHdrFtrContent(html);
    const slotLabel = _hdrFtrSlotLabel(slotType);
    slotEl.dataset.slotType = slotType;
    slotEl.dataset.slotLabel = slotLabel;
    slotEl.title = `双击编辑${slotLabel}`;
    slotEl.classList.toggle('is-empty', !hasContent);
    slotEl.innerHTML = hasContent ? html : '';
  }

  _refreshHeaderFooterPageNumbers(totalPages) {
    const root = document.getElementById(this.containerId);
    if (!root) return;
    root.querySelectorAll('.koto-page-header-first .koto-hdr-page-num').forEach((el) => {
      el.textContent = '1';
      el.setAttribute('contenteditable', 'false');
    });
    root.querySelectorAll('.koto-page-footer-last .koto-hdr-page-num').forEach((el) => {
      el.textContent = String(Math.max(1, totalPages || 1));
      el.setAttribute('contenteditable', 'false');
    });
  }

  _getPaginationRuntimeSource() {
    return {
      pageWidthPx: this._pageWidthPx || null,
      pageHeightPx: this._pageHeightPx || null,
      marginTopPx: this._marginTopPx || null,
      marginBottomPx: this._marginBottomPx || null,
      marginLeftPx: this._marginLeftPx || null,
      marginRightPx: this._marginRightPx || null,
      headerHtml: this._headerHtml || '',
      footerHtml: this._footerHtml || '',
      sections: this._sections || [],
    };
  }

  _refreshRenderedBreakChrome() {
    const root = document.getElementById(this.containerId);
    if (!root) return;

    const source = this._getPaginationRuntimeSource();
    root.querySelectorAll('[data-soft-page-break], [data-page-break][data-page-num]').forEach((breakEl) => {
      const pageAttr = breakEl.getAttribute('data-soft-page-break') || breakEl.getAttribute('data-page-num') || '';
      const pageNum = Number.parseInt(pageAttr, 10);
      if (!Number.isFinite(pageNum) || pageNum < 1) return;

      const currentSectionIdx = Math.max(0, Number.parseInt(breakEl.getAttribute('data-current-section-idx') || breakEl.getAttribute('data-section-idx') || '0', 10) || 0);
      const nextSectionIdx = Math.max(0, Number.parseInt(breakEl.getAttribute('data-next-section-idx') || breakEl.getAttribute('data-section-idx') || '0', 10) || 0);
      const breakChrome = resolveDocxBreakChrome(source, pageNum, currentSectionIdx, nextSectionIdx);
      const footerEl = breakEl.querySelector('.koto-pb-footer');
      const headerEl = breakEl.querySelector('.koto-pb-header');

      if (footerEl && !footerEl.querySelector('.koto-hdrftr-overlay')) {
        footerEl.dataset.variant = breakChrome.currentPage.footerVariant || 'default';
        this._setHeaderFooterSlotState(footerEl, breakChrome.currentPage.footerHtml || '', 'footer');
        footerEl.querySelectorAll('.koto-hdr-page-num').forEach((el) => {
          el.textContent = String(pageNum);
          el.setAttribute('contenteditable', 'false');
        });
      }

      if (headerEl && !headerEl.querySelector('.koto-hdrftr-overlay')) {
        headerEl.dataset.variant = breakChrome.nextPage.headerVariant || 'default';
        this._setHeaderFooterSlotState(headerEl, breakChrome.nextPage.headerHtml || '', 'header');
        headerEl.querySelectorAll('.koto-hdr-page-num').forEach((el) => {
          el.textContent = String(pageNum + 1);
          el.setAttribute('contenteditable', 'false');
        });
      }
    });
  }

  _refreshPageChromeShells(totalPages) {
    const root = document.getElementById(this.containerId);
    if (!root) return;

    const source = this._getPaginationRuntimeSource();
    const firstShell = root.querySelector('.koto-page-header-first');
    const lastShell = root.querySelector('.koto-page-footer-last');

    if (firstShell && !firstShell.querySelector('.koto-hdrftr-overlay')) {
      const firstPageChrome = resolveDocxPageChrome(source, 1, 0);
      this._topHeaderVariant = firstPageChrome.headerVariant;
      firstShell.dataset.variant = firstPageChrome.headerVariant;
      this._setHeaderFooterSlotState(firstShell, firstPageChrome.headerHtml || '', 'header');
      firstShell.querySelectorAll('.koto-hdr-page-num').forEach((el) => {
        el.textContent = '1';
        el.setAttribute('contenteditable', 'false');
      });
    }

    if (lastShell && !lastShell.querySelector('.koto-hdrftr-overlay')) {
      const lastSectionIdx = Math.max(0, this._ensureDocxSections().length - 1);
      const lastPageChrome = resolveDocxPageChrome(source, Math.max(1, totalPages || 1), lastSectionIdx);
      this._bottomFooterVariant = lastPageChrome.footerVariant;
      lastShell.dataset.variant = lastPageChrome.footerVariant;
      this._setHeaderFooterSlotState(lastShell, lastPageChrome.footerHtml || '', 'footer');
      lastShell.querySelectorAll('.koto-hdr-page-num').forEach((el) => {
        el.textContent = String(Math.max(1, totalPages || 1));
        el.setAttribute('contenteditable', 'false');
      });
    }

    this._refreshRenderedBreakChrome();
  }

  _applyHeaderEdit(newHtml, variant, slotEl) {
    const html = _hasHdrFtrContent(newHtml) ? newHtml : '';
    if (variant === 'first') {
      this._updateSectionField('first_header_html', html);
      this._setHeaderFooterSlotState(slotEl, html, 'header');
      this._refreshPageChromeShells(this._totalPages || 1);
      this._refreshHeaderFooterPageNumbers(this._totalPages || 1);
      return;
    }

    this._headerHtml = html;
    if (this.editor?.storage?.autoPageBreak) this.editor.storage.autoPageBreak.headerHtml = html;
    if (this.editor?.storage?.docxPageBreak) this.editor.storage.docxPageBreak.headerHtml = html;
    this._updateSectionField('header_html', html, true);

    this._refreshPageChromeShells(this._totalPages || 1);
    this._refreshHeaderFooterPageNumbers(this._totalPages || 1);
  }

  _applyFooterEdit(newHtml, variant, slotEl) {
    const html = _hasHdrFtrContent(newHtml) ? newHtml : '';
    if (variant === 'first') {
      this._updateSectionField('first_footer_html', html);
      this._setHeaderFooterSlotState(slotEl, html, 'footer');
      this._refreshPageChromeShells(this._totalPages || 1);
      this._refreshHeaderFooterPageNumbers(this._totalPages || 1);
      return;
    }

    this._footerHtml = html;
    if (this.editor?.storage?.autoPageBreak) this.editor.storage.autoPageBreak.footerHtml = html;
    if (this.editor?.storage?.docxPageBreak) this.editor.storage.docxPageBreak.footerHtml = html;
    this._updateSectionField('footer_html', html, true);

    this._refreshPageChromeShells(this._totalPages || 1);
    this._refreshHeaderFooterPageNumbers(this._totalPages || 1);
  }

  // ── getContent ────────────────────────────────────────────────────────────
  getContent() {
    if (!this.editor) return '';
    const wholeTableInfo = this.getWholeTableSelectionInfo();
    if (wholeTableInfo && wholeTableInfo.text) {
      return `[当前选中表格]:\n${wholeTableInfo.text}\n`;
    }
    const cellSelectionInfo = this.getCellSelectionInfo();
    if (cellSelectionInfo && cellSelectionInfo.text) {
      return `[当前选中单元格]:\n${cellSelectionInfo.text}\n`;
    }
    const { doc } = this.editor.state;
    const selectedText = this.getSelectionTextForAI();
    if (selectedText) return `[当前选中文本]:\n${selectedText}\n`;
    return `[文档全文]:\n${doc.textContent}\n`;
  }

  // ── serialize ─────────────────────────────────────────────────────────────
  serialize() {
    if (!this.editor) return this._lastHtml || '';
    try {
      const h = this.editor.getHTML();
      const stripped = h.replace(/<p><\/p>/gi, '').trim();
      return stripped ? h : (this._lastHtml || h);
    } catch (_) { return this._lastHtml || ''; }
  }

  getDocxSavePayload() {
    const storage = this.editor?.storage?.autoPageBreak || {};
    return {
      html: this.serialize(),
      header_html: typeof storage.headerHtml === 'string' ? storage.headerHtml : (this._headerHtml || ''),
      footer_html: typeof storage.footerHtml === 'string' ? storage.footerHtml : (this._footerHtml || ''),
      sections: _cloneJson(Array.isArray(storage.sections) ? storage.sections : this._sections || [], []),
      page_width_px: this._pageWidthPx || null,
      page_height_px: this._pageHeightPx || null,
      margin_top_px: this._marginTopPx || null,
      margin_bottom_px: this._marginBottomPx || null,
      margin_left_px: this._marginLeftPx || null,
      margin_right_px: this._marginRightPx || null,
    };
  }

  // ── _saveSelection ────────────────────────────────────────────────────────
  // Called by the workspace selection toolbar before focus leaves.
  saveSelection() {
    if (!this.editor) return;
    const { selection } = this.editor.state;
    if (selection && (!selection.empty || selection instanceof CellSelection)) {
      this._savedSel = { from: selection.from, to: selection.to };
      this._captureToolbarSelection();
      return;
    }

    // Toolbar clicks can collapse the live DOM selection before the host asks
    // us to persist it. Reuse the last non-empty TipTap selection snapshot
    // instead of overwriting `_savedSel` with an empty range.
    if (!this._savedSel && this._restoreToolbarSelection({ focus: false })) {
      const restored = this.editor.state && this.editor.state.selection;
      if (restored && (!restored.empty || restored instanceof CellSelection)) {
        this._savedSel = { from: restored.from, to: restored.to };
      }
    }
  }

  _captureToolbarSelection() {
    if (!this.editor || this.editor.isDestroyed) return false;
    const selection = this.editor.state && this.editor.state.selection;
    if (!selection || typeof selection.toJSON !== 'function') return false;
    if (selection.empty && !(selection instanceof CellSelection)) return false;
    this._toolbarSelection = _cloneJson(selection.toJSON(), null);
    return !!this._toolbarSelection;
  }

  _restoreToolbarSelection({ focus = false } = {}) {
    if (!this.editor || this.editor.isDestroyed || !this._toolbarSelection) return false;
    try {
      const { state, view } = this.editor;
      const selection = Selection.fromJSON(state.doc, this._toolbarSelection);
      if (focus) view.focus();
      view.dispatch(state.tr.setSelection(selection));
      return true;
    } catch (_) {
      this._toolbarSelection = null;
      return false;
    }
  }

  _captureContextMenuSelection() {
    if (!this.editor || this.editor.isDestroyed) return false;
    const selection = this.editor.state && this.editor.state.selection;
    if (!selection || typeof selection.toJSON !== 'function') return false;
    this._ctxMenuSelection = _cloneJson(selection.toJSON(), null);
    return !!this._ctxMenuSelection;
  }

  _restoreContextMenuSelection({ focus = false } = {}) {
    if (!this.editor || this.editor.isDestroyed || !this._ctxMenuSelection) return false;
    try {
      const { state, view } = this.editor;
      const selection = Selection.fromJSON(state.doc, this._ctxMenuSelection);
      if (focus) view.focus();
      view.dispatch(state.tr.setSelection(selection));
      return true;
    } catch (_) {
      this._ctxMenuSelection = null;
      return false;
    }
  }

  // ── applyToolCall ─────────────────────────────────────────────────────────
  applyToolCall(cmd) {
    if (!this.editor) return;

    // ── insert_image ──────────────────────────────────────────────────────
    if (cmd.type === 'insert_image') {
      let src = cmd.src || cmd.value || '';
      if (!src) return;
      // Convert large base64 to blob URL
      if (src.startsWith('data:image/') && src.length > 50000) {
        try {
          const [head, b64] = src.split(',');
          const mime = head.split(':')[1].split(';')[0];
          const bin = atob(b64);
          const arr = new Uint8Array(bin.length);
          for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
          src = URL.createObjectURL(new Blob([arr], { type: mime }));
        } catch (_) {}
      }
      this.editor.chain().focus().setImage({ src, alt: cmd.alt || '' }).run();
      _scheduleAutoSave();
      return;
    }

    // ── replace_all ───────────────────────────────────────────────────────
    if (cmd.type === 'replace_all') {
      this.render(cmd.value || '');
      _showToast('AI 已替换文档内容', 'success');
      _scheduleAutoSave();
      return;
    }

    // ── replace_text ──────────────────────────────────────────────────────
    if (cmd.type === 'replace_text') {
      const original = cmd.original || '';
      const proposed = cmd.value   || '';
      if (!original) return;

      let replaced = false;

      // Strategy 1: Restore ProseMirror saved selection and replace
      if (this._savedSel && this._savedSel.from !== this._savedSel.to) {
        try {
          const { from, to } = this._savedSel;
          const selText = this.editor.state.doc.textBetween(from, to, '\n');
          const origNorm = original.replace(/\s+/g, ' ').trim();
          const selNorm  = (selText   || '').replace(/\s+/g, ' ').trim();
          const overlap = selNorm && (
            selNorm === origNorm ||
            origNorm.startsWith(selNorm.substring(0, Math.min(15, selNorm.length))) ||
            selNorm.startsWith(origNorm.substring(0, Math.min(15, origNorm.length)))
          );
          if (overlap) {
            this.editor.chain()
              .focus()
              .setTextSelection({ from, to })
              .insertContent(_toInsertContent(proposed))
              .run();
            this._savedSel = null;
            replaced = true;
          }
        } catch (e) {
          console.warn('[KotoTipTapEditor] replace_text saved-sel path failed:', e);
        }
      }

      // Strategy 2: Full-HTML string replacement
      if (!replaced) {
        try {
          const currentHtml = this.serialize();
          let newHtml = currentHtml;
          if (currentHtml.includes(original)) {
            newHtml = currentHtml.split(original).join(proposed);
          }
          if (newHtml !== currentHtml) {
            this.editor.commands.setContent(newHtml, false);
            this._lastHtml = newHtml;
            replaced = true;
          }
        } catch (e) {
          console.warn('[KotoTipTapEditor] replace_text html path failed:', e);
        }
      }

      if (!replaced) {
        _showToast('未在文档中找到原文', 'info');
        return;
      }
      _showToast('AI 已更新文档', 'success');
      _scheduleAutoSave();
      return;
    }

    // ── set_html / insert_text ────────────────────────────────────────────
    if (cmd.type === 'set_html' || cmd.type === 'insert_text') {
      this.editor.chain().focus().insertContent(_toInsertContent(cmd.value || '')).run();
      this._savedSel = null;
      _showToast('AI 已更新文档', 'success');
      _scheduleAutoSave();
    }
  }

  applyImportedReviewDecision(proposal, decision = 'accept') {
    if (!this.editor || !proposal) return false;
    const reviewId = String((proposal.review_id || proposal.id || '')).replace(/^proposal:/, '').trim();
    if (!reviewId) return false;

    const currentHtml = this.serialize();
    if (!currentHtml) return false;

    const parser = new DOMParser();
    const parsed = parser.parseFromString(`<div id="__koto_review_root">${currentHtml}</div>`, 'text/html');
    const root = parsed.getElementById('__koto_review_root');
    if (!root) return false;

    const markers = Array.from(root.querySelectorAll('[data-koto-review-id]')).filter((node) => {
      return String(node.getAttribute('data-koto-review-id') || '').trim() === reviewId;
    });
    if (!markers.length) return false;

    const marker = markers[0];

    const action = String(marker.getAttribute('data-koto-review-action') || proposal.action || proposal.action_type || '').trim() || 'replace';
    const deletedNode = markers
      .map((node) => node.querySelector('.koto-docx-track-change-delete'))
      .find((node) => !!node) || null;
    const insertedNode = markers
      .map((node) => node.querySelector('.koto-docx-track-change-insert'))
      .find((node) => !!node) || null;
    const domDeletedHtml = deletedNode ? deletedNode.innerHTML : '';
    const domInsertedHtml = insertedNode ? insertedNode.innerHTML : '';
    const fallbackDeletedHtml = _toReplacementHtml(proposal.original_text || '');
    const fallbackInsertedHtml = _toReplacementHtml(proposal.proposed_text || '');
    const groupedMarkers = markers.length > 1;
    const ambiguousDomParts = (
      groupedMarkers
      ||
      (action === 'replace' && (
        !deletedNode
        || !insertedNode
        || deletedNode === insertedNode
        || (domDeletedHtml && domDeletedHtml === domInsertedHtml)
      ))
      || (action === 'delete' && !deletedNode)
      || (action === 'insert' && !insertedNode)
    );
    const deletedHtml = ambiguousDomParts && fallbackDeletedHtml
      ? fallbackDeletedHtml
      : domDeletedHtml;
    const insertedHtml = ambiguousDomParts && fallbackInsertedHtml
      ? fallbackInsertedHtml
      : domInsertedHtml;

    let replacementHtml = '';
    if (decision === 'reject') {
      if (action === 'replace' || action === 'delete') {
        replacementHtml = deletedHtml;
      }
    } else if (action === 'replace' || action === 'insert') {
      replacementHtml = insertedHtml;
    }

    if (replacementHtml) {
      const temp = parsed.createElement('div');
      temp.innerHTML = replacementHtml;
      marker.replaceWith(...Array.from(temp.childNodes));
    } else {
      marker.remove();
    }

    markers.slice(1).forEach((node) => node.remove());

    const nextHtml = root.innerHTML;
    this.editor.commands.setContent(nextHtml, false);
    this._lastHtml = nextHtml;
    return true;
  }

  _writeToPreservedSelection(mode, clean) {
    if (!this.editor || this.editor.isDestroyed) return false;

    try {
      let selection = this.editor.state && this.editor.state.selection;
      const hasLiveSelection = !!(selection && (!selection.empty || selection instanceof CellSelection));

      if (!hasLiveSelection && this._restoreToolbarSelection({ focus: true })) {
        selection = this.editor.state && this.editor.state.selection;
      } else if (!hasLiveSelection && this._savedSel && this._savedSel.from !== this._savedSel.to) {
        this.editor.chain().focus().setTextSelection({ from: this._savedSel.from, to: this._savedSel.to }).run();
        selection = this.editor.state && this.editor.state.selection;
      }

      if (!selection || selection.empty) return false;

      if (mode === 'append') {
        if (!clean) return true;
        this.editor.chain()
          .focus()
          .setTextSelection(selection.to)
          .insertContent(_toInsertContent('\n' + clean))
          .run();
      } else if (!clean) {
        this.editor.chain().focus().deleteSelection().run();
      } else {
        this.editor.chain().focus().insertContent(_toInsertContent(clean)).run();
      }

      this._savedSel = null;
      this._toolbarSelection = null;
      _showToast('AI 已更新文档', 'success');
      _scheduleAutoSave();
      return true;
    } catch (e) {
      console.warn('[KotoTipTapEditor] preserved selection write failed:', e);
      return false;
    }
  }

  // ── replaceSelectionWith ──────────────────────────────────────────────────
  replaceSelectionWith(mode, pinnedText, newText) {
    const clean = typeof newText === 'string' ? newText : String(newText || '');

    if (this._writeToPreservedSelection(mode, clean)) return;

    if (mode === 'append') {
      if (!clean) return;
      this.applyToolCall({ type: 'insert_text', value: '\n' + clean });
    } else {
      if (pinnedText) {
        this.applyToolCall({ type: 'replace_text', original: pinnedText, value: clean });
      } else {
        this.applyToolCall({ type: 'set_html', value: clean });
      }
    }
  }

  // ── _showDocxContextMenu ──────────────────────────────────────────────────
  // Right-click handler for DOCX editor. Shows Word-like context menu.
  // Detects table context and adds table operations; always shows basic ops.
  _showDocxContextMenu(e) {
    e.preventDefault();
    e.stopPropagation();
    this._closeDocxCtxMenu({ preserveSelection: true });

    const menu = document.getElementById('wa-docx-ctx');
    if (!menu || !this.editor) return;

    if (!this._ctxMenuSelection) this._captureContextMenuSelection();
    this._restoreContextMenuSelection({ focus: true });

    const inTable = !!(e.target && e.target.closest && e.target.closest('table'));

    const items = [
      { label: '剪切',  action: () => document.execCommand('cut') },
      { label: '复制',  action: () => document.execCommand('copy') },
      { label: '粘贴',  action: () => document.execCommand('paste') },
      { sep: true },
      { label: '全选',  action: () => this.editor.chain().focus().selectAll().run() },
    ];

    if (inTable) {
      items.push({ sep: true });
      items.push({ heading: '插入' });
      items.push({ label: '在上方插入行', action: () => this.editor.chain().focus().addRowBefore().run() });
      items.push({ label: '在下方插入行', action: () => this.editor.chain().focus().addRowAfter().run() });
      items.push({ label: '在左侧插入列', action: () => this.editor.chain().focus().addColumnBefore().run() });
      items.push({ label: '在右侧插入列', action: () => this.editor.chain().focus().addColumnAfter().run() });
      items.push({ sep: true });
      items.push({ heading: '选择' });
      items.push({ label: '选择当前行', action: () => {
        try {
          const { state } = this.editor;
          const $cell = selectionCell(state);
          if (!$cell) return;
          this.editor.view.dispatch(state.tr.setSelection(CellSelection.rowSelection($cell)));
        } catch (_) {}
      } });
      items.push({ label: '选择当前列', action: () => {
        try {
          const { state } = this.editor;
          const $cell = selectionCell(state);
          if (!$cell) return;
          this.editor.view.dispatch(state.tr.setSelection(CellSelection.colSelection($cell)));
        } catch (_) {}
      } });
      items.push({ label: '选择整个表格', action: () => this._selectTableNode(e.target.closest('table')) });
      items.push({ sep: true });
      items.push({ heading: '单元格' });
      items.push({ label: '合并单元格', action: () => this.editor.chain().focus().mergeCells().run() });
      items.push({ label: '拆分单元格', action: () => this.editor.chain().focus().splitCell().run() });
      items.push({ label: '平均分布各列', action: () => this._distributeTableColumnsEvenly() });
      items.push({ sep: true });
      items.push({ heading: '样式' });
      items.push({ label: '切换表头行', action: () => this.editor.chain().focus().toggleHeaderRow().run() });
      items.push({ label: '切换首列表头', action: () => this.editor.chain().focus().toggleHeaderColumn().run() });
      items.push({ label: '顶端对齐', action: () => this.editor.chain().focus().setCellAttribute('verticalAlign', 'top').run() });
      items.push({ label: '居中对齐', action: () => this.editor.chain().focus().setCellAttribute('verticalAlign', 'middle').run() });
      items.push({ label: '底端对齐', action: () => this.editor.chain().focus().setCellAttribute('verticalAlign', 'bottom').run() });
      items.push({ sep: true });
      items.push({ heading: '文本对齐' });
      items.push({ label: '左对齐', action: () => this._applyCellSelectionCommand('setTextAlignLeft') || this.editor.chain().focus().setTextAlign('left').run() });
      items.push({ label: '水平居中', action: () => this._applyCellSelectionCommand('setTextAlignCenter') || this.editor.chain().focus().setTextAlign('center').run() });
      items.push({ label: '右对齐', action: () => this._applyCellSelectionCommand('setTextAlignRight') || this.editor.chain().focus().setTextAlign('right').run() });
      items.push({ label: '两端对齐', action: () => this._applyCellSelectionCommand('setTextAlignJustify') || this.editor.chain().focus().setTextAlign('justify').run() });
      items.push({ sep: true });
      items.push({ heading: '删除' });
      items.push({ label: '删除当前行', action: () => this.editor.chain().focus().deleteRow().run() });
      items.push({ label: '删除当前列', action: () => this.editor.chain().focus().deleteColumn().run() });
      items.push({ label: '删除表格', danger: true, action: () => this.editor.chain().focus().deleteTable().run() });
    }

    menu.innerHTML = '';
    items.forEach(item => {
      if (item.sep) {
        const d = document.createElement('div');
        d.className = 'wa-ctx-separator';
        menu.appendChild(d);
      } else if (item.heading) {
        const d = document.createElement('div');
        d.className = 'wa-ctx-heading';
        d.textContent = item.heading;
        menu.appendChild(d);
      } else {
        const div = document.createElement('div');
        div.className = 'wa-ctx-item' + (item.danger ? ' danger' : '');
        div.textContent = item.label;
        div.addEventListener('mousedown', ev => {
          ev.preventDefault();
          ev.stopPropagation();
          this._restoreContextMenuSelection({ focus: true });
          item.action();
          this._closeDocxCtxMenu();
        });
        menu.appendChild(div);
      }
    });

    menu.style.display = 'block';
    const vw = window.innerWidth, vh = window.innerHeight;
    const mw = menu.offsetWidth || 190;
    const mh = menu.offsetHeight || (items.length * 28 + 8);
    menu.style.left = Math.min(e.clientX, vw - mw - 8) + 'px';
    menu.style.top  = Math.min(e.clientY, vh - mh - 8) + 'px';

    // Close on outside click or Escape
    this._ctxCloseOnClick = (ev) => {
      if (!menu.contains(ev.target)) this._closeDocxCtxMenu();
    };
    this._ctxCloseOnKey = (ev) => {
      if (ev.key === 'Escape') this._closeDocxCtxMenu();
    };
    setTimeout(() => {
      document.addEventListener('mousedown', this._ctxCloseOnClick, { once: true });
      document.addEventListener('keydown',   this._ctxCloseOnKey,   { once: true });
    }, 0);
  }

  _closeDocxCtxMenu({ preserveSelection = false } = {}) {
    const menu = document.getElementById('wa-docx-ctx');
    if (menu) menu.style.display = 'none';
    if (this._ctxCloseOnClick) {
      document.removeEventListener('mousedown', this._ctxCloseOnClick);
      this._ctxCloseOnClick = null;
    }
    if (this._ctxCloseOnKey) {
      document.removeEventListener('keydown', this._ctxCloseOnKey);
      this._ctxCloseOnKey = null;
    }
    if (!preserveSelection) this._ctxMenuSelection = null;
  }

  // ── destroy ───────────────────────────────────────────────────────────────
  destroy() {
    this._cleanup();
    const wrap = document.getElementById(this.containerId);
    if (wrap) wrap.classList.remove('active');
  }

  _cleanup() {
    if (this._pendingZoomRaf) { cancelAnimationFrame(this._pendingZoomRaf); this._pendingZoomRaf = null; }

    // Remove scroll listener from the canvas div
    if (this._scrollHandler && this._scrollEl) {
      try { this._scrollEl.removeEventListener('scroll', this._scrollHandler); } catch (_) {}
    }
    this._scrollHandler = null;
    this._scrollEl      = null;
    if (this._ctxSelectionPreserveHandler && this._zoomWrapper) {
      try { this._zoomWrapper.removeEventListener('mousedown', this._ctxSelectionPreserveHandler, true); } catch (_) {}
    }
    this._ctxSelectionPreserveHandler = null;
    if (this._ctxMenuHandler && this._zoomWrapper) {
      try { this._zoomWrapper.removeEventListener('contextmenu', this._ctxMenuHandler); } catch (_) {}
    }
    this._ctxMenuHandler = null;
    if (this._tableBorderHandler && this._zoomWrapper) {
      try { this._zoomWrapper.removeEventListener('mousedown', this._tableBorderHandler, true); } catch (_) {}
    }
    this._tableBorderHandler = null;
    this._closeDocxCtxMenu();
    this._zoomWrapper   = null;

    // Remove floating table toolbar
    if (this._tableToolbarUpdateFn && this.editor) {
      try { this.editor.off('selectionUpdate', this._tableToolbarUpdateFn); } catch (_) {}
      try { this.editor.off('update', this._tableToolbarUpdateFn); } catch (_) {}
    }
    this._tableToolbarUpdateFn = null;
    if (this._hdrFtrSelectionHandler) {
      try { document.removeEventListener('selectionchange', this._hdrFtrSelectionHandler); } catch (_) {}
    }
    this._hdrFtrSelectionHandler = null;
    const ftb = document.getElementById('koto-table-float-toolbar');
    if (ftb) ftb.remove();

    // Remove TipTap update listener before destroying editor
    if (this._updateHandler && this.editor) {
      try { this.editor.off('update', this._updateHandler); } catch (_) {}
    }
    this._updateHandler = null;
    this._pageIndicator = null;
    this._totalPages    = 1;

    if (this.editor) {
      try {
        const wrap = document.getElementById(this.containerId);
        if (wrap && this._wheelHandler) {
          wrap.removeEventListener('wheel', this._wheelHandler);
        }
      } catch (_) {}
      try { this.editor.destroy(); } catch (_) {}
      this.editor = null;
    }
    this._wheelHandler = null;
    this._savedSel     = null;
    this._toolbarSelection = null;
    this._ctxMenuSelection = null;
    this.clearReviewProposals();
    this._reviewPreviewAnchorLayer = null;
  }
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

/** Convert plain text or HTML to TipTap insertContent() compatible value. */
function _toInsertContent(text) {
  if (!text) return '';
  // If it looks like HTML, pass through; otherwise escape as text
  if (text.trimStart().startsWith('<')) return text;
  return text;
}

function _escapeHtmlText(text) {
  return String(text || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function _toReplacementHtml(value) {
  const text = String(value || '');
  if (!text) return '';
  if (text.trimStart().startsWith('<')) return text;
  return _escapeHtmlText(text).replace(/\r\n?|\n/g, '<br>');
}

/**
 * Basic HTML sanitizer for DOCX content.
 * Strips event handlers and javascript: hrefs but preserves all structure.
 * Full sanitization of arbitrary HTML should use DOMPurify; this is a
 * lightweight version for trusted server-generated DOCX HTML only.
 */
function _sanitizeDocxHtml(html) {
  if (!html) return '';
  // Remove on* event handler attributes (e.g. onclick="...")
  html = html.replace(/\s+on\w+\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]*)/gi, '');
  // Remove javascript: hrefs
  html = html.replace(/href\s*=\s*["']?\s*javascript:[^"'\s>]*/gi, 'href="#"');
  // Remove <script> tags and content
  html = html.replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, '');
  // Imported DOCX tables already carry colwidth metadata for ProseMirror.
  // Strip forced 100% widths so the table view can honor the real grid width
  // instead of stretching/shrinking the last column against the page edge.
  if (typeof document !== 'undefined') {
    const root = document.createElement('div');
    root.innerHTML = html;
    root.querySelectorAll('table.koto-docx-table').forEach((tableEl) => {
      const style = tableEl.style;
      if (style && style.width && style.width.trim() === '100%') {
        style.removeProperty('width');
      }
      if (style && style.maxWidth && style.maxWidth.trim() === '100%') {
        style.removeProperty('max-width');
      }
      if (!tableEl.getAttribute('style')) {
        tableEl.removeAttribute('style');
      }
    });
    html = root.innerHTML;
  }
  return html;
}

/** Proxy helpers — forwards to global WA if available. */
function _scheduleAutoSave(options) {
  if (typeof window !== 'undefined' && window.WA && typeof window.WA.scheduleAutoSave === 'function') {
    window.WA.scheduleAutoSave(options);
  }
}

function _showToast(msg, type) {
  if (typeof window !== 'undefined' && window.showToast) {
    window.showToast(msg, type);
  }
}
