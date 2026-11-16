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

function _kotoFeatures() {
  return (typeof document !== 'undefined' && document.__kotoFeatureRegistry__) || {};
}

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
import { KotoTipTapEditorPart1 } from './koto-docx-editor-part-1.js';

export class KotoTipTapEditorPart2 extends KotoTipTapEditorPart1 {

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
        cpPopup.style.visibility = 'hidden';
        cpPopup.style.display = 'block';
        window.KotoUiScale.placeFixedInViewport(cpPopup, r.left, r.bottom + 4, 4);
        cpPopup.style.visibility = '';
        return;
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

/** Proxy helpers — resolve workspace features through the typed registry. */
function _scheduleAutoSave(options) {
  const features = _kotoFeatures();
  if (typeof features.scheduleAutoSave === 'function') {
    features.scheduleAutoSave(options);
  }
}

function _showToast(msg, type) {
  if (typeof window !== 'undefined' && window.showToast) {
    window.showToast(msg, type);
  }
}
