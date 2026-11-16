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
import { KotoTipTapEditorPart4 } from './koto-docx-editor-part-4.js';

export class KotoTipTapEditorPart5 extends KotoTipTapEditorPart4 {

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

  _buildLinearTextMap() {
    const doc = this.editor && this.editor.state && this.editor.state.doc;
    const chars = [];
    let sawTextBlock = false;
    if (!doc || typeof doc.descendants !== 'function') return { text: '', chars };
    doc.descendants((node, pos) => {
      if (node && node.isTextblock) {
        if (sawTextBlock) chars.push({ ch: '\n', pos: null });
        sawTextBlock = true;
        return true;
      }
      if (!node || !node.isText || typeof node.text !== 'string') return true;
      for (let index = 0; index < node.text.length; index += 1) {
        chars.push({ ch: node.text[index], pos: pos + index });
      }
      return true;
    });
    return { text: chars.map((item) => item.ch).join(''), chars };
  }

  _resolveAnchoredTextRange(cmd) {
    const anchorText = String(cmd.anchor_text || cmd.original || '');
    if (!anchorText) return null;
    const linear = this._buildLinearTextMap();
    if (!linear.text) return null;
    const wantedOccurrence = Number.isFinite(Number(cmd.anchor_occurrence)) ? Number(cmd.anchor_occurrence) : null;
    const wantedStart = Number.isFinite(Number(cmd.anchor_start_offset)) ? Number(cmd.anchor_start_offset) : null;
    const normalize = (value) => String(value || '').replace(/\s+/g, ' ').trim();
    const beforeNeedle = normalize(cmd.anchor_context_before).slice(-80);
    const afterNeedle = normalize(cmd.anchor_context_after).slice(0, 80);
    const contextMatches = (actual, expected, side) => {
      if (!expected) return true;
      const normalized = normalize(actual);
      return side === 'before'
        ? normalized.endsWith(expected) || normalized.includes(expected)
        : normalized.startsWith(expected) || normalized.includes(expected);
    };
    const candidates = [];
    let cursor = 0;
    let occurrence = 0;
    while (cursor <= linear.text.length) {
      const start = linear.text.indexOf(anchorText, cursor);
      if (start < 0) break;
      const slice = linear.chars.slice(start, start + anchorText.length);
      const first = slice.find((item) => Number.isFinite(item.pos));
      const last = [...slice].reverse().find((item) => Number.isFinite(item.pos));
      if (first && last && !slice.some((item) => item.pos === null)) {
        const contextBefore = linear.text.slice(Math.max(0, start - 160), start);
        const contextAfter = linear.text.slice(start + anchorText.length, start + anchorText.length + 160);
        if ((wantedOccurrence === null || occurrence === wantedOccurrence)
            && contextMatches(contextBefore, beforeNeedle, 'before')
            && contextMatches(contextAfter, afterNeedle, 'after')) {
          let score = 10;
          if (wantedOccurrence !== null && occurrence === wantedOccurrence) score += 100;
          if (wantedStart !== null) score += Math.max(0, 30 - Math.abs(start - wantedStart));
          if (beforeNeedle) score += 20;
          if (afterNeedle) score += 20;
          candidates.push({ from: Number(first.pos), to: Number(last.pos) + 1, score });
        }
      }
      occurrence += 1;
      cursor = start + Math.max(anchorText.length, 1);
    }
    candidates.sort((a, b) => b.score - a.score);
    if (!candidates.length) return null;
    if (candidates.length > 1 && candidates[0].score === candidates[1].score && wantedOccurrence === null && wantedStart === null) {
      return null;
    }
    return candidates[0];
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

      // Strategy 2: Resolve the pinned selection against current document positions.
      if (!replaced) {
        try {
          const anchoredRange = this._resolveAnchoredTextRange(cmd);
          if (anchoredRange) {
            this.editor.chain()
              .focus()
              .setTextSelection({ from: anchoredRange.from, to: anchoredRange.to })
              .insertContent(_toInsertContent(proposed))
              .run();
            this._savedSel = null;
            replaced = true;
          }
        } catch (e) {
          console.warn('[KotoTipTapEditor] replace_text anchor path failed:', e);
        }
      }

      // Strategy 3: Full-HTML string replacement
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
    window.KotoUiScale.placeFixedInViewport(menu, e.clientX, e.clientY, 8);

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
    try { this._renderSurfaceController?.dispose(); } catch (_) {}
    this._renderSurfaceController = null;

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
