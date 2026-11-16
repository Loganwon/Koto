// @ts-nocheck
import { getFeatureRegistry } from '../shared/feature-registry';
import {
  getElementPaintScale,
  viewportPointToElement,
} from '../shared/ui-scale';
import { prepareCanvas2d } from '../shared/render-surface';

const WA = getFeatureRegistry();
const $ = (id: string): HTMLElement | null => document.getElementById(id);
const _hexLuma = (...args: any[]): any => WA._hexLuma?.(...args);
const _runTextDecoration = (...args: any[]): any => WA._runTextDecoration?.(...args);
const _safeTextColor = (...args: any[]): any => WA._safeTextColor?.(...args);
const _shouldIgnorePptxGlobalKeydown = (...args: any[]): boolean => Boolean(WA._shouldIgnorePptxGlobalKeydown?.(...args));
const _extractPptxTableText = (...args: any[]): string => String(WA._extractPptxTableText?.(...args) || '');
const _normalizePptxTableSelection = (...args: any[]): any => WA._normalizePptxTableSelection?.(...args) || null;
const _pinSelectionChip = (...args: any[]): void => WA._pinSelectionChip?.(...args);
const _positionSelectionToolbar = (...args: any[]): void => WA._positionSelectionToolbar?.(...args);
const _updateContextBar = (...args: any[]): void => WA._updateContextBar?.(...args);
const _PENCIL_SVG = String(WA._PENCIL_SVG || '');
const _TRASH_SVG = String(WA._TRASH_SVG || '');
const _CLIPBOARD_SVG = String(WA._CLIPBOARD_SVG || '');
const PPTX_THUMB_CACHE_BUDGET = 48;

import { KotoPptxEditorPart1 } from './pptx-editor-part-1';

export class KotoPptxEditorPart2 extends KotoPptxEditorPart1 {

    _buildThumbs() {
      const strip = $('wa-pptx-thumbstrip');
      this._thumbObserver?.disconnect();
      this._thumbObserver = null;
      this._renderedThumbs.clear();
      this._thumbAccess.clear();
      strip.innerHTML = '';
      this.data.slides.forEach((slide, idx) => {
        const wrap = document.createElement('div');
        wrap.className = 'wa-pptx-thumb-wrap';
        wrap.dataset.idx = idx;
        const numSpan = document.createElement('span');
        numSpan.className = 'wa-pptx-thumb-idx';
        numSpan.textContent = idx + 1;
        const thumb = document.createElement('div');
        thumb.className = 'wa-pptx-thumb' + (idx === 0 ? ' active' : '');
        const cv = document.createElement('canvas');
        const logicalHeight = Math.round(148 * this.data.slideHeightEmu / this.data.slideWidthEmu);
        cv.style.width = '148px';
        cv.style.height = `${logicalHeight}px`;
        cv.width = 1;
        cv.height = 1;
        thumb.appendChild(cv);
        wrap.appendChild(numSpan);
        wrap.appendChild(thumb);
        wrap.onclick = () => this._renderSlide(idx);
        wrap.oncontextmenu = (e) => {
          e.preventDefault();
          this._renderSlide(idx);
          this._showThumbCtxMenu(e.clientX, e.clientY, idx);
        };
        strip.appendChild(wrap);
      });

      if (typeof IntersectionObserver !== 'undefined') {
        this._thumbObserver = new IntersectionObserver((entries) => {
          entries.forEach((entry) => {
            if (!entry.isIntersecting) return;
            const idx = Number(entry.target.dataset.idx);
            this._renderThumbIfNeeded(idx);
          });
        }, { root: strip, rootMargin: '260px 0px', threshold: 0 });
        strip.querySelectorAll('.wa-pptx-thumb-wrap').forEach(el => this._thumbObserver.observe(el));
      } else {
        for (let idx = 0; idx < Math.min(this.data.slides.length, 12); idx += 1) {
          this._renderThumbIfNeeded(idx);
        }
      }
    }

    _renderThumbIfNeeded(idx) {
      if (!Number.isInteger(idx) || idx < 0 || this._renderedThumbs.has(idx)) return;
      const canvas = document.querySelectorAll('.wa-pptx-thumb canvas')[idx];
      const slide = this.data?.slides?.[idx];
      if (canvas && slide) this._drawThumbCanvas(canvas, slide, idx);
    }

    _drawThumbCanvas(cv, slide, slideIndex = -1) {
      const sw = 148;
      const sh = Math.round(sw * this.data.slideHeightEmu / this.data.slideWidthEmu);
      const prepared = prepareCanvas2d(cv, sw, sh, cv.parentElement || cv);
      if (!prepared) return;
      const ctx = prepared.context;
      const renderToken = String(++this._thumbRenderToken);
      cv.dataset.renderToken = renderToken;
      if (slideIndex >= 0) {
        this._renderedThumbs.add(slideIndex);
        this._thumbAccess.set(slideIndex, performance.now());
      }
      const sW = this.data.slideWidthEmu, sH = this.data.slideHeightEmu;
      const scX = sw / sW, scY = sh / sH;
      // Background: try image first, then solid fill
      if (slide.backgroundImage) {
        const bgImg = new Image();
        bgImg.onload = () => {
          if (cv.dataset.renderToken !== renderToken) return;
          ctx.drawImage(bgImg, 0, 0, sw, sh);
          // Re-draw shapes on top after image loads
          this._drawThumbShapes(ctx, sw, sh, scX, scY, slide, renderToken);
        };
        bgImg.src = slide.backgroundImage;
        // Draw solid fallback immediately while image loads
        ctx.fillStyle = slide.background || '#ffffff';
        ctx.fillRect(0, 0, sw, sh);
      } else {
        ctx.fillStyle = slide.background || '#ffffff';
        ctx.fillRect(0, 0, sw, sh);
      }
      this._drawThumbShapes(ctx, sw, sh, scX, scY, slide, renderToken);
      if (slideIndex >= 0) this._enforceThumbBudget(slideIndex);
    }

    _enforceThumbBudget(protectedIndex = -1) {
      const strip = $('wa-pptx-thumbstrip');
      const visible = new Set([protectedIndex]);
      const stripRect = strip?.getBoundingClientRect();
      strip?.querySelectorAll('.wa-pptx-thumb-wrap').forEach((wrap) => {
        const rect = wrap.getBoundingClientRect();
        if (stripRect && rect.bottom >= stripRect.top - 260 && rect.top <= stripRect.bottom + 260) {
          visible.add(Number(wrap.dataset.idx));
        }
      });
      const candidates = [...this._renderedThumbs]
        .filter(idx => !visible.has(idx))
        .sort((a, b) => (this._thumbAccess.get(a) || 0) - (this._thumbAccess.get(b) || 0));
      const canvases = document.querySelectorAll('.wa-pptx-thumb canvas');
      while (this._renderedThumbs.size > PPTX_THUMB_CACHE_BUDGET && candidates.length) {
        const idx = candidates.shift();
        const canvas = canvases[idx];
        if (canvas) {
          canvas.dataset.renderToken = String(++this._thumbRenderToken);
          canvas.width = 1;
          canvas.height = 1;
        }
        this._renderedThumbs.delete(idx);
        this._thumbAccess.delete(idx);
      }
    }

    _drawThumbShapes(ctx, sw, sh, scX, scY, slide, renderToken) {
      (slide.shapes || []).forEach(shape => {
        const x = shape.left * scX, y = shape.top * scY;
        const w = shape.width * scX, h = shape.height * scY;
        if (shape.fill) { ctx.fillStyle = shape.fill; ctx.fillRect(x, y, w, h); }
        // ── Picture: draw image asynchronously onto this canvas ──
        if (shape._type === 'PICTURE' && shape.image_b64) {
          const img = new Image();
          img.onload = () => {
            if (ctx.canvas.dataset.renderToken === renderToken) ctx.drawImage(img, x, y, w, h);
          };
          img.src = shape.image_b64;
          // Draw a light grey placeholder immediately (visible before image loads)
          ctx.fillStyle = '#e8e8e8';
          ctx.fillRect(x, y, w, h);
          return;
        }
        // ── Table: draw a simple grid placeholder ──
        if (shape._type === 'TABLE' && shape.cells) {
          ctx.strokeStyle = '#bbb';
          ctx.lineWidth = 0.5;
          ctx.strokeRect(x, y, w, h);
          ctx.fillStyle = '#f5f5f5';
          ctx.fillRect(x, y, w, h);
          return;
        }
        if (shape.has_text && shape.paragraphs) {
          ctx.save(); ctx.beginPath(); ctx.rect(x, y, w, h); ctx.clip();
          let ty = y + 2;
          const thumbBg = shape.fill || slide.background || '#ffffff';
          shape.paragraphs.forEach(para => {
            const lineText = (para.runs || []).map(r => r.text).join('');
            if (!lineText.trim()) { ty += 4; return; }
            const fr = para.runs[0] || {};
            // Fixed scale: pt size relative to standard 540pt slide height
            const defaultThumbPt = shape.is_title ? 28 : 14;
            const px = Math.max(Math.round((fr.size || defaultThumbPt) * sh / 540), 5);
            ctx.font = (fr.bold ? 'bold ' : '') + px + 'px ' + (fr.fontName || 'sans-serif');
            ctx.fillStyle = _safeTextColor(fr.color, thumbBg) || (_hexLuma(thumbBg) < 0.4 ? '#f0f0f0' : '#222');
            ctx.fillText(lineText, x + 2, ty + px);
            ty += px * 1.35;
          });
          ctx.restore();
        }
      });
    }

    _redrawThumb(idx) {
      const thumbs = document.querySelectorAll('.wa-pptx-thumb canvas');
      if (thumbs[idx]) this._drawThumbCanvas(thumbs[idx], this.data.slides[idx], idx);
    }

    _renderSlide(idx) {
      this._curIdx = idx;
      this._clearTableSelection({ restoreWholeTableSummary: false });
      this._selShape = null;
      this._activeSpan = null;
      this._savedRange = null;   // clear stale selection when slide is re-rendered
      document.querySelectorAll('.wa-pptx-thumb').forEach((el, i) =>
        el.classList.toggle('active', i === idx));
      $('wa-pptx-prev').disabled = (idx === 0);
      $('wa-pptx-next').disabled = (idx === this.data.slides.length - 1);
      const counter = (idx + 1) + ' / ' + this.data.slides.length;
      if ($('wa-pptx-slide-counter')) $('wa-pptx-slide-counter').textContent = counter;

      const slide = this.data.slides[idx];
      const sW = this.data.slideWidthEmu, sH = this.data.slideHeightEmu;
      const area = $('wa-pptx-slide-area');
      // Guard against zero clientWidth (may happen before layout completes).
      // Fall back to 700px which gives a 16:9 canvas at 75% zoom.
      const rawW = area ? area.clientWidth : 0;
      const availW = (rawW > 48 ? rawW : 700) - 48;
      const baseWidth = Math.min(availW, 960);
      const displayWidth = Math.round(baseWidth * (this._zoom || 1));
      const scale = displayWidth / sW;
      const pxW = displayWidth;
      const pxH = Math.round(sH * scale);

      const canvas = $('wa-pptx-slide-canvas');
      canvas.style.width  = pxW + 'px';
      canvas.style.height = pxH + 'px';
      // Background: prefer image > gradient > solid color
      if (slide.backgroundImage) {
        canvas.style.background = `url('${slide.backgroundImage}') center/cover no-repeat`;
      } else if (slide.backgroundGradient) {
        canvas.style.background = slide.backgroundGradient;
      } else {
        canvas.style.background = slide.background || '#ffffff';
      }
      // Sync background swatch in toolbar
      const bgSwatch = $('wa-pptx-bg-swatch');
      if (bgSwatch) {
        if (slide.backgroundImage) {
          bgSwatch.style.backgroundImage = `url('${slide.backgroundImage}')`;
          bgSwatch.style.backgroundSize  = 'cover';
          bgSwatch.style.backgroundColor = '';
        } else {
          bgSwatch.style.backgroundImage = '';
          bgSwatch.style.backgroundColor = slide.background || '#ffffff';
        }
      }
      canvas.innerHTML = '';
      this._scale = scale;  // store for use by _selectShape/_startResize

      // Ascending z_order: low z = back (appended first), high z = front (appended last, on top in DOM)
      (slide.shapes || []).sort((a, b) => a.z_order - b.z_order).forEach(shape => {
        const el = document.createElement('div');
        el.className = 'wa-pptx-shape';
        el.dataset.shapeId = shape.id;
        el.style.position = 'absolute';
        el.style.left   = Math.round(shape.left   * scale) + 'px';
        el.style.top    = Math.round(shape.top    * scale) + 'px';
        el.style.width  = Math.round(shape.width  * scale) + 'px';
        el.style.height = Math.round(shape.height * scale) + 'px';
        el.style.overflow = 'hidden';
        el.style.boxSizing = 'border-box';
        el.style.zIndex = shape.z_order;   // explicit stacking in case of overlaps
        if (shape.rotation) el.style.transform = 'rotate(' + shape.rotation + 'deg)';
        // Fill: gradient > fillImage > solid color
        if (shape.fillGradient)  el.style.background = shape.fillGradient;
        else if (shape.fillImage) el.style.backgroundImage = `url('${shape.fillImage}')`;
        else if (shape.fill)      el.style.background = shape.fill;
        // Border (widthEmu stored in EMU; convert to px using scale)
        if (shape.border && shape.border.widthEmu) {
          const bwPx = Math.max(1, Math.round(shape.border.widthEmu * scale));
          el.style.border = `${bwPx}px solid ${shape.border.color || '#000'}`;
        }
        // Rounded corners for roundRect, snip, etc.
        if (shape.autoShapeType === 'roundRect' && shape.cornerRadiusEmu != null) {
          el.style.borderRadius = Math.round(shape.cornerRadiusEmu * scale) + 'px';
        }

        if (shape.has_text && shape.paragraphs) {
          el.style.cursor = 'text';
          // fontScale from PPTX normAutofit (e.g. 75 = text renders at 75% of declared pt size)
          const fontScaleMult = (shape.fontScale != null) ? shape.fontScale / 100 : 1.0;
          // spAutoFit: text was already fit at save-time — keep fixed dimensions (overflow:hidden)
          // Pick a default text color that contrasts with the EFFECTIVE background:
          // shape fill (if present) takes priority over the slide background.
          // This handles the common case of colored header bars / dark-filled shapes
          // where the theme text is white but shape.fill is dark.
          const effectiveBg = shape.fill || slide.background || '#ffffff';
          const bgLuma = _hexLuma(effectiveBg);
          const defaultTextColor = bgLuma < 0.4 ? '#f0f0f0' : '#1a1a1a';
          const inner = document.createElement('div');
          inner.className = 'wa-pptx-inner';
          // ── Dynamic text insets from PPTX bodyPr (lIns/tIns/rIns/bIns) ──
          const ins = shape.textInsets;
          let padCSS = '4px 6px';
          if (ins) {
            const pT = Math.round(ins.t * scale) + 'px';
            const pR = Math.round(ins.r * scale) + 'px';
            const pB = Math.round(ins.b * scale) + 'px';
            const pL = Math.round(ins.l * scale) + 'px';
            padCSS = `${pT} ${pR} ${pB} ${pL}`;
          }
          // ── Vertical alignment from textAnchor ──
          let justifyContent = 'flex-start';
          if (shape.textAnchor === 'ctr')  justifyContent = 'center';
          else if (shape.textAnchor === 'b') justifyContent = 'flex-end';
          inner.style.cssText = `width:100%;height:100%;padding:${padCSS};box-sizing:border-box;overflow:hidden;display:flex;flex-direction:column;justify-content:${justifyContent};color:${defaultTextColor};`;
          shape.paragraphs.forEach((para, pi) => {
            const pEl = document.createElement('div');
            pEl.className = 'wa-pptx-para';
            // ── Line spacing ──
            if (para.lineSpacing) {
              pEl.style.lineHeight = String(para.lineSpacing);
            } else if (para.lineSpacingPt) {
              pEl.style.lineHeight = Math.round(para.lineSpacingPt * scale * 12700) + 'px';
            } else {
              pEl.style.lineHeight = '1.3';
            }
            pEl.style.textAlign = (para.align || 'LEFT').toLowerCase();
            if (shape.wordWrap === 'none') {
              pEl.style.whiteSpace = 'nowrap';
              pEl.style.wordBreak  = 'normal';
            } else {
              pEl.style.wordBreak = 'break-word';
            }
            pEl.style.minHeight = '1.2em';   // ensures empty paragraphs have clickable height
            // ── Bullet / numbered list ──
            if (para.bullet) {
              pEl.style.paddingLeft = '1.8em';
              pEl.dataset.bullet = typeof para.bullet === 'string' ? para.bullet : '\u2022';
            } else if (para.numbered) {
              pEl.style.paddingLeft = '1.8em';
              pEl.dataset.numbered = '1';
            } else if (para.indent) {
              pEl.style.paddingLeft = (para.indent * 20) + 'px';
            }
            // ── Paragraph spacing (space before / after) ──
            if (para.spaceBefore) {
              pEl.style.marginTop = Math.round(para.spaceBefore * scale * 12700) + 'px';
            } else if (para.spaceBeforePct) {
              pEl.style.marginTop = (para.spaceBeforePct * 100) + '%';
            }
            if (para.spaceAfter) {
              pEl.style.marginBottom = Math.round(para.spaceAfter * scale * 12700) + 'px';
            } else if (para.spaceAfterPct) {
              pEl.style.marginBottom = (para.spaceAfterPct * 100) + '%';
            }
            (para.runs || []).forEach((run, ri) => {
              const span = document.createElement('span');
              span.className = 'wa-pptx-run';
              span.tabIndex = -1;               // ensures programmatic focus() always works
              span.contentEditable = 'false';   // read-only until double-click enters edit mode
              span.dataset.shapeId = shape.id;
              span.dataset.pi = pi;
              span.dataset.ri = ri;
              span.textContent = run.text;
              span.style.outline = 'none';
              span.style.display = 'inline';
              span.style.whiteSpace = 'pre-wrap';
              const defaultPt = shape.is_title ? (this.data.defaultTitleFontSizePt || 36) : (this.data.defaultFontSizePt || 18);
              span.style.fontSize = Math.max(Math.round((run.size || defaultPt) * fontScaleMult * scale * 12700), 6) + 'px';
              if (run.bold)      span.style.fontWeight = 'bold';
              if (run.italic)    span.style.fontStyle = 'italic';
              const td = _runTextDecoration(run);
              if (td) span.style.textDecoration = td;
              // Build font-family with CJK fallback chain.
              // eaFontName is the East Asian font (Chinese/Japanese text in PPT often specifies
              // this exclusively). Without it, browsers fall back to a Latin font with completely
              // different glyph widths, causing text wrapping/alignment mismatches.
              if (run.eaFontName || run.fontName) {
                const parts = [];
                if (run.eaFontName) parts.push(`'${run.eaFontName}'`);
                if (run.fontName && run.fontName !== run.eaFontName) parts.push(`'${run.fontName}'`);
                // CJK system font fallbacks: covers most Windows/Mac/Linux setups
                parts.push("'Microsoft YaHei'", "'PingFang SC'", "'Noto Sans CJK SC'", "'SimSun'", 'sans-serif');
                span.style.fontFamily = parts.join(', ');
              }
              if (run.color) {
                const safe = _safeTextColor(run.color, effectiveBg);
                if (safe) span.style.color = safe;
              }
              if (run.superscript) { span.style.verticalAlign = 'super'; span.style.fontSize = Math.max(Math.round((run.size || defaultPt) * fontScaleMult * scale * 12700 * 0.75), 5) + 'px'; }
              if (run.subscript)   { span.style.verticalAlign = 'sub';   span.style.fontSize = Math.max(Math.round((run.size || defaultPt) * fontScaleMult * scale * 12700 * 0.75), 5) + 'px'; }
              if (run.highlight)   span.style.backgroundColor = run.highlight;
              if (run.charSpacing) span.style.letterSpacing = Math.round(run.charSpacing * 127 * scale) + 'px';
              span.addEventListener('input', () => {
                run.text = span.textContent;
                this._redrawThumb(idx);
                WA.scheduleAutoSave();
              });
              span.addEventListener('focus', () => this._onRunFocus(el, shape, pi, ri, run));
              span.addEventListener('keydown', e => { if (e.key === 'Escape') { this._exitEditMode(); } });
              pEl.appendChild(span);
            });
            if (!(para.runs || []).length) pEl.appendChild(document.createElement('br'));
            inner.appendChild(pEl);
          });
          // Sync all run text to data model when inner (the contentEditable container) fires input.
          inner.addEventListener('input', () => {
            // Browser deletion may remove or merge complete run spans.  Rebuild
            // the paragraph/run model from the surviving DOM so deleted text
            // cannot reappear after save, rerender, or reopen.
            this._syncShapeTextFromDom(shape, inner);
            this._redrawThumb(idx);
            WA.scheduleAutoSave();
          });
          // Prevent Enter from inserting raw DOM nodes; Escape exits edit mode.
          inner.addEventListener('keydown', ev => {
            if (ev.key === 'Enter') ev.preventDefault();
            if (ev.key === 'Escape') { ev.stopPropagation(); this._exitEditMode(); }
          });
          el.appendChild(inner);
          // Belt-and-suspenders: stop mousedown from reaching shape's move handler
          // when already in edit mode for this shape (prevents move during text drag).
          inner.addEventListener('mousedown', ev => {
            if (this._editMode && this._selShape === el) ev.stopPropagation();
          });
          // Cursor: border zone → 'move', interior → 'text' (matches PPT: border=move, interior=text)
          el.addEventListener('mousemove', ev => {
            if (ev.target.classList && ev.target.classList.contains('wa-pptx-handle')) return;
            if (this._editMode && this._selShape === el) { el.style.cursor = 'text'; return; }
            const _r = el.getBoundingClientRect(), _B = 8 * getElementPaintScale(el).x;
            const _onBord = ev.clientX < _r.left + _B || ev.clientX > _r.right - _B ||
                            ev.clientY < _r.top  + _B || ev.clientY > _r.bottom - _B;
            el.style.cursor = _onBord ? 'move' : 'text';
          });
          el.addEventListener('mousedown', e => {
            if (this._insertMode) return;
            // In edit mode on this shape: let browser (and inner) handle cursor/text-selection
            if (this._editMode && this._selShape === el) return;
            e.stopPropagation();
            // PPT model: ONLY the border zone can drag/move the shape.
            // Interior: first click=select, second click=enter text edit. Never drags.
            const rect = el.getBoundingClientRect();
            const BORDER_T = 8 * getElementPaintScale(el).x;
            const onBorder = e.clientX < rect.left + BORDER_T || e.clientX > rect.right - BORDER_T ||
                             e.clientY < rect.top + BORDER_T  || e.clientY > rect.bottom - BORDER_T;
            const wasSelected = (this._selShape === el);
            this._selectShape(el, shape);
            if (onBorder) {
              // Border zone → drag to move the shape
              this._startMove(e, el, shape, canvas, scale, false, true);
            } else {
              // Interior → NEVER drag; enter text edit on mouseup only if already selected
              this._startMove(e, el, shape, canvas, scale, wasSelected, false);
            }
          });
          el.addEventListener('dblclick', e => {
            if (this._insertMode) return;
            e.stopPropagation();
            this._enterEditMode(el);
          });
        } else if (shape._type === 'PICTURE' && shape.image_b64) {
          // ── Image shape ─────────────────────────────────────────────────
          const img = document.createElement('img');
          img.src = shape.image_b64;
          img.style.width = '100%';
          img.style.height = '100%';
          img.style.objectFit = 'contain';
          img.style.display = 'block';
          img.style.pointerEvents = 'none'; // let mousedown fall through to el
          img.draggable = false;
          el.appendChild(img);
          el.style.cursor = 'default';
          // Cursor: border zone → 'move', interior → 'default' (only when selected)
          el.addEventListener('mousemove', ev => {
            if (ev.target.classList && ev.target.classList.contains('wa-pptx-handle')) return;
            if (this._selShape !== el) { el.style.cursor = 'default'; return; }
            const _r = el.getBoundingClientRect(), _B = 8;
            const _onBord = ev.clientX < _r.left + _B || ev.clientX > _r.right - _B ||
                            ev.clientY < _r.top  + _B || ev.clientY > _r.bottom - _B;
            el.style.cursor = _onBord ? 'move' : 'default';
          });
          el.addEventListener('mousedown', e => {
            if (this._insertMode) return;
            this._selectShape(el, shape);
            this._startMove(e, el, shape, canvas, scale);
          });
        } else if (shape._type === 'TABLE' && shape.cells) {
          // ── Table shape ──────────────────────────────────────────────────
          el.classList.add('wa-shape-table');
          const rows = shape.table_rows || 0;
          const cols = shape.table_cols || 0;
          // Keep a mutable map to cell data objects so input handlers update shape.cells in place
          const cellDataMap = {};
          (shape.cells || []).forEach(c => { cellDataMap[c.row + '_' + c.col] = c; });
          const tbl = document.createElement('table');
          tbl.dataset.tableRows = String(rows);
          tbl.dataset.tableCols = String(cols);
          tbl.style.cssText = 'width:100%;height:100%;border-collapse:collapse;table-layout:fixed;';
          // Build <colgroup> with per-column proportional widths from parsed col_widths
          const colWidths = shape.col_widths && shape.col_widths.length === cols ? shape.col_widths : null;
          if (colWidths) {
            const totalW = colWidths.reduce((s, w) => s + w, 0) || 1;
            const cg = document.createElement('colgroup');
            colWidths.forEach(w => {
              const col = document.createElement('col');
              col.style.width = (w / totalW * 100).toFixed(2) + '%';
              cg.appendChild(col);
            });
            tbl.appendChild(cg);
          }
          const rowHeights = shape.row_heights && shape.row_heights.length === rows ? shape.row_heights : null;
          const baseFontPx = Math.max(Math.round(10 * 12700 * scale), 6);
          for (let r = 0; r < rows; r++) {
            const tr = document.createElement('tr');
            if (rowHeights) tr.style.height = Math.round(rowHeights[r] * scale) + 'px';
            for (let c = 0; c < cols; c++) {
              const td = document.createElement('td');
              td.className = 'wa-pptx-cell';
              td.dataset.row = r;
              td.dataset.col = c;
              td.contentEditable = 'false';
              const cellData = cellDataMap[r + '_' + c];
              // Per-cell font size overrides the table base if present
              const cellFontPx = cellData && cellData.fontSize
                ? Math.max(Math.round(cellData.fontSize * 12700 * scale), 6)
                : baseFontPx;
              td.style.cssText = `border:1px solid #d0d0d0;padding:2px 4px;overflow:hidden;font-size:${cellFontPx}px;vertical-align:top;word-break:break-word;outline:none;text-align:${(cellData && cellData.align || 'LEFT').toLowerCase()};`;
              if (cellData && cellData.fill)  td.style.backgroundColor = cellData.fill;
              if (cellData && cellData.color) td.style.color = cellData.color;
              if (cellData && cellData.bold)  td.style.fontWeight = 'bold';
              td.textContent = (cellData && cellData.text) || '';
              td.addEventListener('input', () => {
                if (cellData) {
                  cellData.text = td.textContent;
                } else {
                  // Defensive: cell not in original data — create entry
                  const newCell = { row: r, col: c, text: td.textContent };
                  shape.cells.push(newCell);
                  cellDataMap[r + '_' + c] = newCell;
                }
                WA.scheduleAutoSave();
              });
              td.addEventListener('keydown', e => {
                if (e.key === 'Escape') {
                  this._exitEditMode();
                  e.preventDefault();
                } else if (e.key === 'Tab') {
                  e.preventDefault();
                  const allCells = Array.from(tbl.querySelectorAll('.wa-pptx-cell'));
                  const tdIdx = allCells.indexOf(td);
                  const next = allCells[e.shiftKey ? tdIdx - 1 : tdIdx + 1];
                  if (next) { next.focus(); this._activeSpan = next; }
                }
              });
              td.addEventListener('focus', () => {
                this._selectShape(el, shape);
                this._activeSpan = td;
              });
              tr.appendChild(td);
            }
            tbl.appendChild(tr);
          }
          el.appendChild(tbl);
          el.style.overflow = 'hidden';
          el.style.cursor = 'default';
          // Cursor: border zone → 'move' (only when selected)
          el.addEventListener('mousemove', ev => {
            if (ev.target.classList && ev.target.classList.contains('wa-pptx-handle')) return;
            if (this._editMode && this._selShape === el) return;  // let browser handle inside table
            if (this._selShape !== el) { el.style.cursor = 'default'; return; }
            const _r = el.getBoundingClientRect(), _B = 8;
            const _onBord = ev.clientX < _r.left + _B || ev.clientX > _r.right - _B ||
                            ev.clientY < _r.top  + _B || ev.clientY > _r.bottom - _B;
            el.style.cursor = _onBord ? 'move' : 'default';
          });
          // Stop mousedown from propagating to the move handler when already editing this table
          tbl.addEventListener('mousedown', ev => {
            if (this._editMode && this._selShape === el) ev.stopPropagation();
          });
          el.addEventListener('mousedown', e => {
            if (this._insertMode) return;
            if (e.button !== 0) return;
            if (this._editMode && this._selShape === el) return;

            const rect = el.getBoundingClientRect();
            const BORDER_T = 8 * getElementPaintScale(el).x;
            const onBorder = e.clientX < rect.left + BORDER_T || e.clientX > rect.right - BORDER_T ||
              e.clientY < rect.top + BORDER_T || e.clientY > rect.bottom - BORDER_T;
            const targetCell = e.target && e.target.closest ? e.target.closest('.wa-pptx-cell') : null;

            this._selectShape(el, shape);
            if (onBorder || !targetCell) {
              this._clearTableSelection();
              this._startMove(e, el, shape, canvas, scale);
              return;
            }

            e.preventDefault();
            e.stopPropagation();
            this._beginTableSelection(e, el, shape, tbl, targetCell);
          });
          el.addEventListener('dblclick', e => {
            if (this._insertMode) return;
            e.stopPropagation();
            // Enter table edit mode: make all cells editable
            if (this._editMode && this._selShape === el) return;
            this._clearTableSelection();
            this._editMode = true;
            el.classList.add('wa-pptx-editing');
            el.querySelectorAll('.wa-pptx-cell').forEach(td => { td.contentEditable = 'true'; });
            // Try to focus the cell that was double-clicked
            const target = e.target.closest('.wa-pptx-cell');
            const focusCell = target || el.querySelector('.wa-pptx-cell');
            if (focusCell) { focusCell.focus(); this._activeSpan = focusCell; }
          });
        } else if (shape._type === 'CHART') {
          // ── Chart shape — show a visible placeholder (no chart lib available)
          el.style.background = '#f0f4f8';
          el.style.border = '1px dashed #a0aec0';
          el.style.display = 'flex';
          el.style.alignItems = 'center';
          el.style.justifyContent = 'center';
          el.style.color = '#718096';
          el.style.fontSize = Math.max(Math.round(11 * scale * 12700), 8) + 'px';
          el.style.userSelect = 'none';
          el.textContent = `[图表]`;
          el.style.pointerEvents = 'none';
        } else {
          // ── Unknown / connector / group — render as thin line (LINE type) or invisible
          if (shape._type === 'LINE') {
            const svgNS = 'http://www.w3.org/2000/svg';
            const svg = document.createElementNS(svgNS, 'svg');
            svg.setAttribute('width',  el.style.width);
            svg.setAttribute('height', el.style.height);
            svg.style.cssText = 'position:absolute;top:0;left:0;overflow:visible;';
            const line = document.createElementNS(svgNS, 'line');
            const _w = Math.round(shape.width  * scale);
            const _h = Math.round(shape.height * scale);
            // Draw diagonal from (0,0) to (w,h); correct for vertical/horizontal lines too
            line.setAttribute('x1', '0'); line.setAttribute('y1', '0');
            line.setAttribute('x2', String(_w || 1)); line.setAttribute('y2', String(_h || 1));
            const lc = (shape.border && shape.border.color) || '#666';
            const lw = shape.border && shape.border.widthEmu
              ? Math.max(1, Math.round(shape.border.widthEmu * scale)) : 1;
            line.setAttribute('stroke', lc);
            line.setAttribute('stroke-width', String(lw));
            svg.appendChild(line);
            el.appendChild(svg);
            el.style.overflow = 'visible';
          } else {
            el.style.opacity = '0';
            el.style.pointerEvents = 'none';
          }
        }
        canvas.appendChild(el);

        // Non-editable background shapes (from slide layout/master): skip all interaction
        if (shape.editable === false) {
          el.style.pointerEvents = 'none';
          el.style.userSelect    = 'none';
          return;
        }

        // Right-click context menu on every shape
        el.addEventListener('contextmenu', e => {
          e.preventDefault();
          e.stopPropagation();
          this._selectShape(el, shape);
          this._showCtxMenu(e.clientX, e.clientY, shape);
        });
      });

      // Remove stale listeners from previous renders before adding new ones
      if (this._canvasMousedownFn) canvas.removeEventListener('mousedown', this._canvasMousedownFn);
      if (this._canvasCtxMenuFn)   canvas.removeEventListener('contextmenu', this._canvasCtxMenuFn);
      this._canvasMousedownFn = e => {
        this._closeCtxMenu();
        if (this._insertMode) {
          this._startInsert(e, canvas, scale);
        } else if (e.target === canvas) {
          this._clearSelection();
        }
      };
      this._canvasCtxMenuFn = e => {
        if (e.target === canvas) { e.preventDefault(); this._closeCtxMenu(); }
      };
      canvas.addEventListener('mousedown', this._canvasMousedownFn);
      canvas.addEventListener('contextmenu', this._canvasCtxMenuFn);

      if (this._insertMode) canvas.style.cursor = 'crosshair';
    }

    // ── Insert text box ──────────────────────────────────────────────────────

    insertTextBox(leftEmu, topEmu, wEmu, hEmu) {
      const newId = -(Date.now() % 100000000);  // negative = new (backend creates it)
      this.data.slides[this._curIdx].shapes.push({
        id: newId, name: 'Text Box', type: 'TEXT_BOX',
        left: leftEmu, top: topEmu,
        width: Math.max(wEmu, 914400),    // min 1 inch wide
        height: Math.max(hEmu, 457200),   // min 0.5 inch tall
        z_order: 999, has_text: true, fill: null,
        paragraphs: [{ align: 'LEFT', runs: [{ text: '' }] }],
      });
      this._renderSlide(this._curIdx);
      this._redrawThumb(this._curIdx);
      // Auto-enter edit mode for newly created text box (double-rAF ensures DOM is fully laid out)
      requestAnimationFrame(() => requestAnimationFrame(() => {
        const span = document.querySelector(`.wa-pptx-run[data-shape-id="${newId}"]`);
        if (span) {
          const shapeEl = span.closest('.wa-pptx-shape');
          if (shapeEl) { this._selectShape(shapeEl, null); this._enterEditMode(shapeEl); }
          this._activeSpan = span;
        }
      }));
      WA.scheduleAutoSave();
    }

    _startInsert(e, canvas, scale) {
      e.preventDefault();
      const start = viewportPointToElement(canvas, e.clientX, e.clientY);
      const startX = start.x;
      const startY = start.y;

      const overlay = document.createElement('div');
      overlay.style.cssText = 'position:absolute;border:2px dashed #0078d4;background:rgba(0,120,212,.06);pointer-events:none;box-sizing:border-box;z-index:999;';
      overlay.style.left = startX + 'px'; overlay.style.top = startY + 'px';
      overlay.style.width = '0px'; overlay.style.height = '0px';
      canvas.appendChild(overlay);

      const onMove = (ev) => {
        const { x, y } = viewportPointToElement(canvas, ev.clientX, ev.clientY);
        overlay.style.left   = Math.min(x, startX) + 'px';
        overlay.style.top    = Math.min(y, startY) + 'px';
        overlay.style.width  = Math.abs(x - startX) + 'px';
        overlay.style.height = Math.abs(y - startY) + 'px';
      };

      const onUp = (ev) => {
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
        overlay.remove();

        const { x, y } = viewportPointToElement(canvas, ev.clientX, ev.clientY);
        const lPx = Math.min(x, startX), tPx = Math.min(y, startY);
        const wPx = Math.abs(x - startX), hPx = Math.abs(y - startY);

        // px → EMU  (scale = baseW / slideWidthEmu, so emu = px / scale)
        const leftEmu = Math.round(lPx / scale);
        const topEmu  = Math.round(tPx / scale);
        // If drag was tiny (just a click), use a default 3" × 1" box
        const wEmu = wPx > 20 ? Math.round(wPx / scale) : 2743200;
        const hEmu = hPx > 10 ? Math.round(hPx / scale) : 914400;

        this._insertMode = false;
        canvas.style.cursor = '';
        const btn = $('wa-pptx-insert-tb');
        if (btn) btn.classList.remove('active');

        this.insertTextBox(leftEmu, topEmu, wEmu, hEmu);
      };

      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
    }
}
