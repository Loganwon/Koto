// @ts-nocheck
import type { WorkspaceEditor, PptxSlide, SlideShape, ParaRun, TextRun, TableCell } from './types';
import { getWorkspaceApi } from '../shared/workspace-api';
import { setLastSelectionText } from '../shared/selection-runtime';

const WA = getWorkspaceApi();
const state: any = (window as any).state || {};
const $ = (id: string): HTMLElement | null => document.getElementById(id);
const showToast = (...args: any[]): void => WA.showToast?.(...args);
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

export class KotoPptxEditor implements WorkspaceEditor {
    constructor() {
      this.data = null;
      this._curIdx = 0;
      this._selShape = null;
      this._activeSpan = null;   // last focused run span — persists when toolbar takes focus
      this._insertMode = false;  // true while user is drawing a new text box
      this._editMode = false;    // true when double-clicked into text editing (like PowerPoint)
      this._savedRange = null;   // saved selection range — survives toolbar interactions
      this._canvasMousedownFn = null;  // stored so we can remove stale listeners on re-render
      this._canvasCtxMenuFn = null;
      this._undoStack = [];         // history for Ctrl+Z (shape-level ops)
      this._redoStack = [];         // history for Ctrl+Y / Ctrl+Shift+Z
      this._shapeClipboard = null;  // shape copy buffer for Ctrl+C/V
      this._nudgeTimer = null;      // debounce timer for arrow-key nudge
      this._tableSelection = null;
      this._tableSelectionCleanup = null;
      const editor = $('wa-pptx-editor');
      if (editor) editor.classList.add('active');
    }

    render(richData) {
      if (!richData || typeof richData !== 'object' || Array.isArray(richData)) {
        throw new TypeError('PPTX 编辑器需要结构化幻灯片数据');
      }
      // Normalize snake_case keys returned by Python backend to camelCase used internally.
      this.data = {
        slideWidthEmu:  richData.slideWidthEmu  || richData.slide_width_emu  || 9144000,
        slideHeightEmu: richData.slideHeightEmu || richData.slide_height_emu || 6858000,
        defaultFontSizePt: richData.defaultFontSizePt || richData.default_font_size_pt || 18,
        defaultTitleFontSizePt: richData.defaultTitleFontSizePt || richData.default_title_font_size_pt || 36,
        slides: richData.slides || [],
      };
      // Ensure every slide has .index (backend uses slide_index; AI tool calls match on .index)
      this.data.slides.forEach((s, i) => { if (s.index === undefined) s.index = s.slide_index ?? i; });
      this._curIdx = 0;
      this._buildThumbs();
      this._initKeyHandler();
      const zoomSlider = $('wa-pptx-zoom');
      if (zoomSlider) { zoomSlider.value = 75; this._zoom = 0.75; }
      // The outer file-open path already waited for layout once, so keep the
      // in-editor retry short and only for the residual zero-width race.
      const _pptxMountDeadline = Date.now() + 250;
      const _tryPptxRender = () => {
        const area = $('wa-pptx-slide-area');
        const rawW = area ? area.clientWidth : 0;
        if (rawW > 48) {
          this._renderSlide(0);
          WA.pptxZoom && WA.pptxZoom(75);
        } else if (Date.now() < _pptxMountDeadline) {
          requestAnimationFrame(_tryPptxRender);
        } else {
          // Deadline reached — render anyway (will use fallback width logic inside _renderSlide)
          console.warn('[KotoPptxEditor] slide-area 宽度仍为零，使用回退宽度渲染');
          this._renderSlide(0);
          WA.pptxZoom && WA.pptxZoom(75);
          // Secondary recovery: re-render once layout is available in next frame
          setTimeout(() => { this._renderSlide(this._curIdx); }, 200);
        }
      };
      _tryPptxRender();
    }

    serialize() { return this.data; }

    getContent() {
      // Serialize full current slide with shape IDs so AI can target the right shape
      const slide = this.data && this.data.slides[this._curIdx];
      if (!slide) return '[PPT 大纲未加载]';
      const lines = [];
      (slide.shapes || []).forEach(s => {
        if (s.has_text && s.paragraphs) {
          const text = s.paragraphs.map(p => (p.runs || []).map(r => r.text).join('')).join('\n');
          if (text.trim()) lines.push(`[shape_id=${s.id} name="${s.name}"]: ${text}`);
        }
      });
      return lines.length
        ? `[PPT幻灯片${this._curIdx + 1}内容, slide_index=${this._curIdx}]\n${lines.join('\n')}`
        : `[幻灯片${this._curIdx + 1}无文字内容, slide_index=${this._curIdx}]`;
    }

    getSelectionPayload() {
      const sel = window.getSelection();
      let range = sel && !sel.isCollapsed && sel.rangeCount ? sel.getRangeAt(0) : null;
      if ((!range || !range.toString().trim()) && this._savedRange) range = this._savedRange;
      if (!range) return null;
      const text = range.toString().trim();
      if (!text) return null;
      const ancestor = range.commonAncestorContainer.nodeType === Node.TEXT_NODE
        ? range.commonAncestorContainer.parentElement
        : range.commonAncestorContainer;
      const shapeEl = ancestor && ancestor.closest ? ancestor.closest('.wa-pptx-shape') : this._selShape;
      if (!shapeEl || !shapeEl.closest('#wa-pptx-editor')) return null;
      const slide = this.data && this.data.slides[this._curIdx];
      const shapeId = Number(shapeEl.dataset.shapeId || 0);
      const shape = slide && (slide.shapes || []).find((item) => Number(item.id) === shapeId);
      return {
        kind: 'pptx-text',
        text,
        aiText: `[PPT 第 ${this._curIdx + 1} 页选中文字，shape_id=${shapeId}]:\n${text}\n`,
        previewText: `第 ${this._curIdx + 1} 页 · ${text.length} 字`,
        countLabel: `${text.replace(/\s/g, '').length}字`,
        slideIndex: this._curIdx,
        shapeId,
        shapeName: shape && shape.name ? String(shape.name) : '',
      };
    }

    _syncShapeTextFromDom(shape, inner) {
      const previousParagraphs = Array.isArray(shape.paragraphs) ? shape.paragraphs : [];
      const paragraphEls = Array.from(inner.querySelectorAll(':scope > .wa-pptx-para'));
      if (!paragraphEls.length) {
        const previousParagraph = previousParagraphs[0] || { align: 'LEFT', runs: [] };
        const previousRun = Array.isArray(previousParagraph.runs) && previousParagraph.runs[0]
          ? previousParagraph.runs[0]
          : {};
        shape.paragraphs = [{
          ...previousParagraph,
          runs: [{ ...previousRun, text: String(inner.textContent || '') }],
        }];
        return;
      }
      const nextParagraphs = paragraphEls.map((paragraphEl, paragraphIndex) => {
        const previousParagraph = previousParagraphs[paragraphIndex] || previousParagraphs[0] || { align: 'LEFT', runs: [] };
        const previousRuns = Array.isArray(previousParagraph.runs) ? previousParagraph.runs : [];
        const nextRuns = [];
        const pushText = (text, template) => {
          const value = String(text == null ? '' : text);
          if (!value && nextRuns.length) return;
          nextRuns.push({ ...(template || previousRuns[0] || {}), text: value });
        };
        Array.from(paragraphEl.childNodes).forEach((node) => {
          if (node.nodeType === Node.TEXT_NODE) {
            if (String(node.nodeValue || '')) pushText(node.nodeValue, previousRuns[nextRuns.length]);
            return;
          }
          if (!(node instanceof HTMLElement)) return;
          if (node.tagName === 'BR') return;
          const oldIndex = Number(node.dataset && node.dataset.ri);
          const template = Number.isFinite(oldIndex) ? previousRuns[oldIndex] : previousRuns[nextRuns.length];
          pushText(node.textContent || '', template);
        });
        if (!nextRuns.length) pushText(paragraphEl.textContent || '', previousRuns[0]);
        return { ...previousParagraph, runs: nextRuns };
      });
      shape.paragraphs = nextParagraphs;
      paragraphEls.forEach((paragraphEl, paragraphIndex) => {
        paragraphEl.querySelectorAll('.wa-pptx-run').forEach((span, runIndex) => {
          span.dataset.pi = String(paragraphIndex);
          span.dataset.ri = String(runIndex);
        });
      });
    }

    applyToolCall(cmd) {
      if (cmd.type === 'insert_image') {
        this._insertImageFromSource(cmd.src || cmd.value || '', cmd.alt || cmd.name || 'image');
        return;
      }
      if (cmd.type !== 'set_pptx_text') return;
      const slide = this.data.slides.find(s => s.index === cmd.slide_index);
      if (!slide) return;
      const shape = slide.shapes.find(s => s.id === cmd.shape_id);
      if (!shape || !shape.paragraphs) return;
      // Preserve formatting from the first run, then replace ALL content
      const refPara = shape.paragraphs[0] || { align: 'LEFT', runs: [] };
      const refRun = (refPara.runs && refPara.runs[0]) || {};
      const newLines = cmd.value.split('\n');
      shape.paragraphs = newLines.map((line, i) => ({
        align: (shape.paragraphs[i] && shape.paragraphs[i].align) || refPara.align || 'LEFT',
        runs: [{ text: line, bold: refRun.bold, italic: refRun.italic,
                 underline: refRun.underline, size: refRun.size,
                 color: refRun.color, fontName: refRun.fontName }],
      }));
      if (this._curIdx === cmd.slide_index) this._renderSlide(cmd.slide_index);
      this._redrawThumb(cmd.slide_index);
      showToast('AI 已更新 PPT 文本', 'success');
      WA.scheduleAutoSave();
    }

    insertImageFile(file) {
      if (!file || (file.type && !file.type.startsWith('image/'))) {
        showToast('请选择图片文件', 'warning');
        return;
      }
      const reader = new FileReader();
      reader.onload = (ev) => {
        this._insertImageDataUri(String(ev.target && ev.target.result || ''), file.name || 'image');
      };
      reader.onerror = () => showToast('读取图片失败', 'error');
      reader.readAsDataURL(file);
    }

    async _insertImageFromSource(src, alt = 'image') {
      if (!src) {
        showToast('缺少图片来源', 'warning');
        return;
      }
      if (String(src).startsWith('data:image/')) {
        this._insertImageDataUri(String(src), alt);
        return;
      }
      try {
        const resp = await fetch(src);
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        const blob = await resp.blob();
        if (!blob.type.startsWith('image/')) throw new Error('不是图片文件');
        const reader = new FileReader();
        reader.onload = (ev) => {
          this._insertImageDataUri(String(ev.target && ev.target.result || ''), alt);
        };
        reader.onerror = () => showToast('读取图片失败', 'error');
        reader.readAsDataURL(blob);
      } catch (err) {
        showToast('插入图片失败: ' + (err && err.message ? err.message : err), 'error');
      }
    }

    _insertImageDataUri(dataUri, alt = 'image') {
      if (!dataUri || !String(dataUri).startsWith('data:image/')) {
        showToast('图片数据无效', 'warning');
        return;
      }
      const slide = this.data && this.data.slides && this.data.slides[this._curIdx];
      if (!slide) return;
      const img = new Image();
      img.onload = () => {
        this._pushUndo();
        const shapes = slide.shapes || (slide.shapes = []);
        const newId = Math.max(0, ...shapes.map(s => Number(s.id) || 0)) + 1;
        const maxW = this.data.slideWidthEmu * 0.5;
        const maxH = this.data.slideHeightEmu * 0.5;
        const ratio = img.naturalWidth / (img.naturalHeight || 1);
        let width = maxW;
        let height = maxW / ratio;
        if (height > maxH) {
          height = maxH;
          width = maxH * ratio;
        }
        const shape = {
          id: newId,
          name: alt || 'image',
          type: 'picture',
          _type: 'PICTURE',
          left: Math.round((this.data.slideWidthEmu - width) / 2),
          top: Math.round((this.data.slideHeightEmu - height) / 2),
          width: Math.round(width),
          height: Math.round(height),
          z_order: Math.max(0, ...shapes.map(s => Number(s.z_order) || 0)) + 1,
          has_text: false,
          image_b64: dataUri,
        };
        shapes.push(shape);
        this._renderSlide(this._curIdx);
        this._redrawThumb(this._curIdx);
        showToast('已插入图片', 'success');
        WA.scheduleAutoSave();
      };
      img.onerror = () => showToast('图片加载失败', 'error');
      img.src = dataUri;
    }

    appendToolCall(cmd) {
      if (cmd.type !== 'set_pptx_text') return;
      const slide = this.data.slides.find(s => s.index === cmd.slide_index);
      if (!slide) return;
      const shape = slide.shapes.find(s => s.id === cmd.shape_id);
      if (!shape || !shape.paragraphs) return;
      const lastPara = shape.paragraphs[shape.paragraphs.length - 1];
      const refRun = (lastPara && lastPara.runs && lastPara.runs[0]) || {};
      shape.paragraphs.push({
        runs: [{ text: cmd.value, bold: refRun.bold || false, italic: refRun.italic || false,
                 underline: refRun.underline || false, size: refRun.size || 14,
                 color: refRun.color, fontName: refRun.fontName }],
        align: (lastPara && lastPara.align) || 'LEFT',
      });
      if (this._curIdx === cmd.slide_index) this._renderSlide(cmd.slide_index);
      this._redrawThumb(cmd.slide_index);
      showToast('AI 已追加文本', 'success');
      WA.scheduleAutoSave();
    }

    // Fallback when AI replies plain text (no tool call): use pinned shape context
    replaceSelectionWith(mode, _pinnedText, newText) {
      const shapeId = this._pinnedShapeId;
      const slideIdx = (this._pinnedSlideIdx !== undefined) ? this._pinnedSlideIdx : this._curIdx;
      if (!shapeId) { showToast('请先在幻灯片中选中文字', 'info'); return; }
      const cmd = { type: 'set_pptx_text', slide_index: slideIdx, shape_id: shapeId, value: newText };
      if (mode === 'append') {
        this.appendToolCall(cmd);
      } else {
        this.applyToolCall(cmd);
      }
    }

    destroy() {
      const editor = $('wa-pptx-editor');
      if (editor) editor.classList.remove('active');
      const thumbstrip = $('wa-pptx-thumbstrip');
      if (thumbstrip) thumbstrip.innerHTML = '';
      const canvas = $('wa-pptx-slide-canvas');
      if (canvas) canvas.innerHTML = '';
      this._clearTableSelection({ restoreWholeTableSummary: false });
      this._closeCtxMenu();
      document.removeEventListener('keydown', this._keyHandler);
      if (this._selChangeHandler) document.removeEventListener('selectionchange', this._selChangeHandler);
      const slideArea = $('wa-pptx-slide-area');
      if (slideArea && this._pptxWheelHandler) slideArea.removeEventListener('wheel', this._pptxWheelHandler);
      this.data = null;
    }

    // ── Delete / Duplicate shape ──────────────────────────────────────────────

    deleteShape(shapeId) {
      this._pushUndo();
      const slide = this.data.slides[this._curIdx];
      const idx = (slide.shapes || []).findIndex(s => s.id === shapeId);
      if (idx < 0) return;
      slide.shapes.splice(idx, 1);
      this._selShape = null;
      this._activeSpan = null;
      this._renderSlide(this._curIdx);
      this._redrawThumb(this._curIdx);
      WA.scheduleAutoSave();
    }

    deleteSelected() {
      if (!this._selShape) { showToast('请先单击选中一个形状', 'info'); return; }
      const id = parseInt(this._selShape.dataset.shapeId);
      this.deleteShape(id);
    }

    duplicateShape(shapeId) {
      this._pushUndo();
      const slide = this.data.slides[this._curIdx];
      const orig = (slide.shapes || []).find(s => s.id === shapeId);
      if (!orig) return;
      const copy = JSON.parse(JSON.stringify(orig));
      copy.id = -(Date.now() % 100000000);
      copy.left += 457200;   // offset 0.5 inch right
      copy.top  += 457200;
      copy.z_order = (slide.shapes.reduce((m, s) => Math.max(m, s.z_order), 0)) + 1;
      slide.shapes.push(copy);
      this._renderSlide(this._curIdx);
      this._redrawThumb(this._curIdx);
      WA.scheduleAutoSave();
    }

    // ── Right-click context menu ──────────────────────────────────────────────

    _showCtxMenu(x, y, shape) {
      this._closeCtxMenu();
      const menu = $('wa-pptx-ctx');
      if (!menu) return;
      const items = [
        { label: `${_PENCIL_SVG}  编辑文字`,  action: () => {
            const shapeEl = document.querySelector(`.wa-pptx-shape[data-shape-id="${shape.id}"]`);
            if (shapeEl) this._enterEditMode(shapeEl);
        }},
        { sep: true },
        { label: `${_CLIPBOARD_SVG}  复制形状 (Ctrl+C)`,  action: () => {
            this._shapeClipboard = JSON.parse(JSON.stringify(shape));
            showToast('已复制形状', 'info');
        }},
        { label: '⧉  粘贴并偏移 (Ctrl+V)', action: () => {
            if (!this._shapeClipboard) { showToast('剪贴板为空', 'info'); return; }
            this._pushUndo();
            const slide = this.data.slides[this._curIdx];
            const copy = JSON.parse(JSON.stringify(this._shapeClipboard));
            copy.id = -(Date.now() % 100000000);
            copy.left += 457200; copy.top += 457200;
            copy.z_order = (slide.shapes.reduce((m, s) => Math.max(m, s.z_order), 0)) + 1;
            slide.shapes.push(copy);
            this._renderSlide(this._curIdx);
            this._redrawThumb(this._curIdx);
            WA.scheduleAutoSave();
        }},
        { label: '⧉  就地复制',  action: () => this.duplicateShape(shape.id) },
        { sep: true },
        { label: '↑  上移一层',  action: () => this._reorder(shape.id, +1) },
        { label: '↓  下移一层',  action: () => this._reorder(shape.id, -1) },
        { label: '↑↑ 置于顶层',  action: () => this._bringToFront(shape.id) },
        { label: '↓↓ 置于底层',  action: () => this._sendToBack(shape.id) },
        { sep: true },
        { label: `${_TRASH_SVG}  删除形状`,  danger: true, action: () => this.deleteShape(shape.id) },
      ];

      menu.innerHTML = '';
      items.forEach(item => {
        if (item.sep) {
          const d = document.createElement('div'); d.className = 'wa-pptx-ctx-sep'; menu.appendChild(d);
        } else {
          const div = document.createElement('div');
          div.className = 'wa-pptx-ctx-item' + (item.danger ? ' danger' : '');
          div.innerHTML = item.label;
          div.addEventListener('mousedown', e => { e.stopPropagation(); item.action(); this._closeCtxMenu(); });
          menu.appendChild(div);
        }
      });

      // Clamp to viewport
      menu.style.display = 'block';
      const vw = window.innerWidth, vh = window.innerHeight;
      const mw = menu.offsetWidth, mh = menu.offsetHeight;
      menu.style.left = Math.min(x, vw - mw - 8) + 'px';
      menu.style.top  = Math.min(y, vh - mh - 8) + 'px';
    }

    _closeCtxMenu() {
      const menu = $('wa-pptx-ctx');
      if (menu) menu.style.display = 'none';
    }

    _showThumbCtxMenu(x, y, idx) {
      this._closeCtxMenu();
      const menu = $('wa-pptx-ctx');
      if (!menu) return;
      const total = this.data.slides.length;
      const items = [
        { label: '+  新建幻灯片', action: () => WA.pptxAddSlide() },
        { label: '⧉  复制幻灯片 (Ctrl+Shift+D)', action: () => this._duplicateSlide() },
        { sep: true },
        { label: `${_TRASH_SVG}  删除此幻灯片`, danger: true,
          action: () => { if (total > 1) WA.pptxDelSlide(); else showToast('至少保留一张幻灯片', 'error'); }
        },
      ];
      menu.innerHTML = '';
      items.forEach(item => {
        if (item.sep) {
          const d = document.createElement('div'); d.className = 'wa-pptx-ctx-sep'; menu.appendChild(d);
        } else {
          const div = document.createElement('div');
          div.className = 'wa-pptx-ctx-item' + (item.danger ? ' danger' : '');
          div.innerHTML = item.label;
          div.addEventListener('mousedown', e => { e.stopPropagation(); item.action(); this._closeCtxMenu(); });
          menu.appendChild(div);
        }
      });
      menu.style.display = 'block';
      const vw = window.innerWidth, vh = window.innerHeight;
      const mw = menu.offsetWidth, mh = menu.offsetHeight;
      menu.style.left = Math.min(x, vw - mw - 8) + 'px';
      menu.style.top  = Math.min(y, vh - mh - 8) + 'px';
    }

    _reorder(shapeId, delta) {
      this._pushUndo();
      const slide = this.data.slides[this._curIdx];
      const shape = (slide.shapes || []).find(s => s.id === shapeId);
      if (!shape) return;
      shape.z_order = Math.max(0, shape.z_order + delta);
      this._renderSlide(this._curIdx);
      WA.scheduleAutoSave();
    }

    // ── Keyboard handler ─────────────────────────────────────────────────────

    _initKeyHandler() {
      this._keyHandler = (e) => {
        // Only act when PPTX editor is active
        const editor = $('wa-pptx-editor');
        if (!editor || !editor.classList.contains('active')) return;
        const active = document.activeElement;
        if (_shouldIgnorePptxGlobalKeydown(e.target) || _shouldIgnorePptxGlobalKeydown(active)) return;

        // ── Escape ──────────────────────────────────────────────────────────
        if (e.key === 'Escape') {
          this._closeCtxMenu();
          if (this._editMode) {
            this._exitEditMode();  // exit text editing, stay selected
          } else {
            this._clearSelection();
          }
          return;
        }

        // ── Ctrl/Cmd shortcuts (global — work in or out of edit mode) ───────
        const ctrl = e.ctrlKey || e.metaKey;
        if (ctrl) {
          // Ctrl+Z — undo (shape ops; text editing native undo handled by browser)
          if (e.key === 'z' && !e.shiftKey && !this._editMode) {
            e.preventDefault(); this._undo(); return;
          }
          // Ctrl+Y / Ctrl+Shift+Z — redo
          if ((e.key === 'y' || (e.key === 'z' && e.shiftKey)) && !this._editMode) {
            e.preventDefault(); this._redo(); return;
          }
          // Ctrl+B/I/U/S — text formatting (in text edit mode)
          if (this._editMode) {
            if (e.key === 'b') { e.preventDefault(); this.applyFormat('bold');          return; }
            if (e.key === 'i') { e.preventDefault(); this.applyFormat('italic');        return; }
            if (e.key === 'u') { e.preventDefault(); this.applyFormat('underline');     return; }
            if (e.key === '.') { e.preventDefault(); this.applyFormat('strikethrough'); return; }
            // Ctrl+E/L/R/J — alignment shortcuts (in text edit mode)
            if (e.key === 'e') { e.preventDefault(); this.applyFormat('align', 'center');  return; }
            if (e.key === 'l') { e.preventDefault(); this.applyFormat('align', 'left');    return; }
            if (e.key === 'r') { e.preventDefault(); this.applyFormat('align', 'right');   return; }
            if (e.key === 'j') { e.preventDefault(); this.applyFormat('align', 'justify'); return; }
            // Ctrl+Shift+> / Ctrl+Shift+< — increase/decrease font size
            if (e.shiftKey && (e.key === '>' || e.key === '.' || e.code === 'Period')) {
              e.preventDefault(); this._stepFontSize(+1); return;
            }
            if (e.shiftKey && (e.key === '<' || e.key === ',' || e.code === 'Comma')) {
              e.preventDefault(); this._stepFontSize(-1); return;
            }
          }
          // Ctrl+M — new slide
          if (e.key === 'm') { e.preventDefault(); WA.pptxAddSlide(); return; }
          // Ctrl+Shift+D — duplicate slide
          if (e.key === 'd' && e.shiftKey && !this._editMode) {
            e.preventDefault(); this._duplicateSlide(); return;
          }
          // Ctrl+D — duplicate selected shape
          if (e.key === 'd' && !this._editMode && this._selShape) {
            e.preventDefault();
            this.duplicateShape(parseInt(this._selShape.dataset.shapeId));
            return;
          }
          // Ctrl+C — copy selected shape to clipboard buffer
          if (e.key === 'c' && !this._editMode && this._selShape) {
            const slide = this.data.slides[this._curIdx];
            const shape = (slide.shapes || []).find(s => s.id === parseInt(this._selShape.dataset.shapeId));
            if (shape) { this._shapeClipboard = JSON.parse(JSON.stringify(shape)); showToast('已复制形状', 'info'); }
            return;
          }
          // Ctrl+V — paste shape from clipboard buffer
          if (e.key === 'v' && !this._editMode && this._shapeClipboard) {
            e.preventDefault();
            this._pushUndo();
            const slide = this.data.slides[this._curIdx];
            const copy = JSON.parse(JSON.stringify(this._shapeClipboard));
            copy.id = -(Date.now() % 100000000);
            copy.left += 457200; copy.top += 457200;
            copy.z_order = (slide.shapes.reduce((m, s) => Math.max(m, s.z_order), 0)) + 1;
            slide.shapes.push(copy);
            this._renderSlide(this._curIdx);
            this._redrawThumb(this._curIdx);
            WA.scheduleAutoSave();
            return;
          }
          // Ctrl+A — select all shapes (first shape, then cycle)
          if (e.key === 'a' && !this._editMode) {
            e.preventDefault();
            const slide = this.data.slides[this._curIdx];
            if (slide && slide.shapes && slide.shapes.length) {
              const next = this._selShape
                ? ((slide.shapes.findIndex(s => s.id === parseInt(this._selShape.dataset.shapeId)) + 1) % slide.shapes.length)
                : 0;
              const shapeEl = document.querySelector(`.wa-pptx-shape[data-shape-id="${slide.shapes[next].id}"]`);
              if (shapeEl) this._selectShape(shapeEl, slide.shapes[next]);
            }
            return;
          }
          // Ctrl+Shift+] — bring shape forward / Ctrl+Shift+[ — send shape backward
          if (e.shiftKey && (e.key === ']' || e.key === '[') && !this._editMode && this._selShape) {
            e.preventDefault();
            const shapeId = parseInt(this._selShape.dataset.shapeId);
            if (e.key === ']') this._reorder(shapeId, +1);
            else this._reorder(shapeId, -1);
            return;
          }
        }

        // ── Tab / Shift+Tab — cycle through shapes ──────────────────────────
        if (e.key === 'Tab' && !this._editMode) {
          e.preventDefault();
          const slide = this.data.slides[this._curIdx];
          if (!slide || !slide.shapes || !slide.shapes.length) return;
          const curIdx = this._selShape
            ? slide.shapes.findIndex(s => s.id === parseInt(this._selShape.dataset.shapeId))
            : -1;
          const next = e.shiftKey
            ? (curIdx <= 0 ? slide.shapes.length - 1 : curIdx - 1)
            : ((curIdx + 1) % slide.shapes.length);
          const shapeEl = document.querySelector(`.wa-pptx-shape[data-shape-id="${slide.shapes[next].id}"]`);
          if (shapeEl) this._selectShape(shapeEl, slide.shapes[next]);
          return;
        }

        // ── PageUp / PageDown — navigate slides ─────────────────────────────
        if (e.key === 'PageUp') {
          e.preventDefault(); WA.pptxNav(-1); return;
        }
        if (e.key === 'PageDown') {
          e.preventDefault(); WA.pptxNav(1); return;
        }
        if (!this._editMode && this._selShape && ['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.key)) {
          e.preventDefault();
          const step = e.shiftKey ? 9144 : 914;  // 0.1 inch or ~0.01 inch in EMU
          const slide = this.data.slides[this._curIdx];
          const shape = (slide.shapes || []).find(s => s.id === parseInt(this._selShape.dataset.shapeId));
          if (!shape) return;
          // Snapshot BEFORE first nudge in a sequence (debounce: only push once per burst)
          if (!this._nudgeTimer) this._pushUndo();
          if (e.key === 'ArrowLeft')  shape.left -= step;
          if (e.key === 'ArrowRight') shape.left += step;
          if (e.key === 'ArrowUp')    shape.top  -= step;
          if (e.key === 'ArrowDown')  shape.top  += step;
          shape.left = Math.max(0, shape.left);
          shape.top  = Math.max(0, shape.top);
          this._renderSlide(this._curIdx);
          this._redrawThumb(this._curIdx);
          // Debounce auto-save for nudge to avoid hammering on key repeat
          clearTimeout(this._nudgeTimer);
          this._nudgeTimer = setTimeout(() => { this._nudgeTimer = null; WA.scheduleAutoSave(); }, 400);
          return;
        }

        // ── Delete / Backspace — remove shape or slide ───────────────────────
        if ((e.key === 'Delete' || e.key === 'Backspace') && !this._editMode) {
          e.preventDefault();
          if (this._selShape) {
            this.deleteSelected();
          } else {
            WA.pptxDelSlide();  // no shape selected → delete slide
          }
        }
      };
      document.addEventListener('keydown', this._keyHandler);

      // Ctrl+Wheel zoom on the slide area
      const slideArea = $('wa-pptx-slide-area');
      if (slideArea) {
        this._pptxWheelHandler = (e) => {
          if (!e.ctrlKey && !e.metaKey) return;
          e.preventDefault();
          const curPct = Math.round((this._zoom || 0.75) * 100);
          const delta = e.deltaY > 0 ? -5 : 5;
          const newPct = Math.max(40, Math.min(150, curPct + delta));
          const slider = $('wa-pptx-zoom');
          if (slider) slider.value = newPct;
          WA.pptxZoom(newPct);
        };
        slideArea.addEventListener('wheel', this._pptxWheelHandler, { passive: false });
      }

      // Save selection range so toolbar interactions (font-size select, etc.) don't lose it.
      // Also update the format toolbar to reflect the run at the current cursor/selection start.
      this._selChangeHandler = () => {
        if (!this._editMode) return;
        const sel = window.getSelection();
        if (sel && sel.rangeCount > 0) {
          const r = sel.getRangeAt(0);
          const anchorEl = r.startContainer.nodeType === 3 ? r.startContainer.parentElement : r.startContainer;
          if (anchorEl && anchorEl.classList && anchorEl.classList.contains('wa-pptx-run')) {
            if (!r.isCollapsed) this._savedRange = r.cloneRange();
            // Update toolbar to reflect run at cursor/selection start
            this._activeSpan = anchorEl;
            const _pi = parseInt(anchorEl.dataset.pi), _ri = parseInt(anchorEl.dataset.ri);
            const _slide = this.data && this.data.slides[this._curIdx];
            const _shp = _slide && (_slide.shapes || []).find(s => s.id === parseInt(anchorEl.dataset.shapeId));
            if (_shp && _shp.paragraphs[_pi]) {
              const _run = (_shp.paragraphs[_pi].runs || [])[_ri];
              if (_run) {
                if ($('wa-pptx-bold'))      $('wa-pptx-bold').classList.toggle('active', !!_run.bold);
                if ($('wa-pptx-italic'))    $('wa-pptx-italic').classList.toggle('active', !!_run.italic);
                if ($('wa-pptx-underline')) $('wa-pptx-underline').classList.toggle('active', !!_run.underline);
                if ($('wa-pptx-fontsize') && _run.size) $('wa-pptx-fontsize').value = Math.round(_run.size);
                if ($('wa-pptx-fontname') && _run.fontName) $('wa-pptx-fontname').value = _run.fontName;
                if ($('wa-pptx-fontcolor') && _run.color) {
                  $('wa-pptx-fontcolor').value = _run.color.startsWith('#') ? _run.color : '#000000';
                  const _sw = $('wa-pptx-fontcolor-swatch');
                  if (_sw) _sw.style.background = _run.color;
                }
                // Sync hover bar format state whenever selection changes inside a run
                if (!r.isCollapsed) this._syncHoverBar(_run);
              }
            }
          }
          // Hide hover bar when selection collapses (no text selected)
          if (r.isCollapsed) this._hideHoverBar();
        } else {
          // Collapsed or no selection — only clear saved range when still in edit mode focus
          const active = document.activeElement;
          if (!active || !active.classList.contains('wa-pptx-run')) {
            // Focus left the canvas — keep saved range so toolbar can use it
          } else {
            this._savedRange = null;
          }
          this._hideHoverBar();
        }
      };
      // Show hover bar when the user finishes text selection (mouseup inside canvas)
      const _hbSlideArea = $('wa-pptx-slide-area');
      if (_hbSlideArea && !this._hbMouseupBound) {
        this._hbMouseupBound = true;
        _hbSlideArea.addEventListener('mouseup', () => {
          setTimeout(() => {
            const sel = window.getSelection();
            if (!sel || sel.isCollapsed || !sel.rangeCount) { this._hideHoverBar(); return; }
            const text = sel.toString().trim();
            if (!text) { this._hideHoverBar(); return; }
            const range = sel.getRangeAt(0);
            if (!_hbSlideArea.contains(range.commonAncestorContainer)) { this._hideHoverBar(); return; }
            this._showHoverBar(range);
            // Sync format state (bold/italic/fontName/size/color) from the active run
            if (typeof this._syncHoverBar === 'function') {
              const activeEl = document.activeElement;
              if (activeEl && activeEl.dataset && activeEl.dataset.ri !== undefined) {
                const pi  = parseInt(activeEl.dataset.pi  ?? 0);
                const ri  = parseInt(activeEl.dataset.ri  ?? 0);
                const slides = this.data && this.data.slides;
                const run = slides && slides[this._curIdx] &&
                            slides[this._curIdx].paragraphs &&
                            slides[this._curIdx].paragraphs[pi] &&
                            slides[this._curIdx].paragraphs[pi].runs &&
                            slides[this._curIdx].paragraphs[pi].runs[ri];
                if (run) this._syncHoverBar(run);
              }
            }
            // ── Also ensure the floating AI quick-action toolbar appears BELOW ──
            // (format bar = above selection, AI bar = below — both coexist without overlap)
            setLastSelectionText(text);
            _positionSelectionToolbar();
            const countEl = $('wa-tooltip-count');
            if (countEl) countEl.textContent = `${text.replace(/\s/g, '').length}字`;
            _updateContextBar({ selection: text });
          }, 30);
        });
      }
      document.addEventListener('selectionchange', this._selChangeHandler);
    }

    _buildThumbs() {
      const strip = $('wa-pptx-thumbstrip');
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
        cv.width = 148;
        cv.height = Math.round(148 * this.data.slideHeightEmu / this.data.slideWidthEmu);
        this._drawThumbCanvas(cv, slide);
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
    }

    _drawThumbCanvas(cv, slide) {
      const ctx = cv.getContext('2d');
      const sw = cv.width, sh = cv.height;
      const sW = this.data.slideWidthEmu, sH = this.data.slideHeightEmu;
      const scX = sw / sW, scY = sh / sH;
      // Background: try image first, then solid fill
      if (slide.backgroundImage) {
        const bgImg = new Image();
        bgImg.onload = () => {
          ctx.drawImage(bgImg, 0, 0, sw, sh);
          // Re-draw shapes on top after image loads
          this._drawThumbShapes(ctx, sw, sh, scX, scY, slide);
        };
        bgImg.src = slide.backgroundImage;
        // Draw solid fallback immediately while image loads
        ctx.fillStyle = slide.background || '#ffffff';
        ctx.fillRect(0, 0, sw, sh);
      } else {
        ctx.fillStyle = slide.background || '#ffffff';
        ctx.fillRect(0, 0, sw, sh);
      }
      this._drawThumbShapes(ctx, sw, sh, scX, scY, slide);
    }

    _drawThumbShapes(ctx, sw, sh, scX, scY, slide) {
      (slide.shapes || []).forEach(shape => {
        const x = shape.left * scX, y = shape.top * scY;
        const w = shape.width * scX, h = shape.height * scY;
        if (shape.fill) { ctx.fillStyle = shape.fill; ctx.fillRect(x, y, w, h); }
        // ── Picture: draw image asynchronously onto this canvas ──
        if (shape._type === 'PICTURE' && shape.image_b64) {
          const img = new Image();
          img.onload = () => { ctx.drawImage(img, x, y, w, h); };
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
      if (thumbs[idx]) this._drawThumbCanvas(thumbs[idx], this.data.slides[idx]);
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
            const _r = el.getBoundingClientRect(), _B = 8;
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
            const BORDER_T = 8;
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
            const BORDER_T = 8;
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
      const rect = canvas.getBoundingClientRect();
      const startX = e.clientX - rect.left;
      const startY = e.clientY - rect.top;

      const overlay = document.createElement('div');
      overlay.style.cssText = 'position:absolute;border:2px dashed #0078d4;background:rgba(0,120,212,.06);pointer-events:none;box-sizing:border-box;z-index:999;';
      overlay.style.left = startX + 'px'; overlay.style.top = startY + 'px';
      overlay.style.width = '0px'; overlay.style.height = '0px';
      canvas.appendChild(overlay);

      const onMove = (ev) => {
        const x = ev.clientX - rect.left, y = ev.clientY - rect.top;
        overlay.style.left   = Math.min(x, startX) + 'px';
        overlay.style.top    = Math.min(y, startY) + 'px';
        overlay.style.width  = Math.abs(x - startX) + 'px';
        overlay.style.height = Math.abs(y - startY) + 'px';
      };

      const onUp = (ev) => {
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
        overlay.remove();

        const x = ev.clientX - rect.left, y = ev.clientY - rect.top;
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

    // ── Resize shape ─────────────────────────────────────────────────────────

    _startResize(e, el, shape, canvas, scale, handleType) {
      const startX = e.clientX, startY = e.clientY;
      const startLeft = el.offsetLeft, startTop = el.offsetTop;
      const startW = el.offsetWidth, startH = el.offsetHeight;
      const pxW = canvas.offsetWidth, pxH = canvas.offsetHeight;
      const MIN_W = 30, MIN_H = 20;

      const onMove = (ev) => {
        const dx = ev.clientX - startX, dy = ev.clientY - startY;
        let newLeft = startLeft, newTop = startTop;
        let newW = startW, newH = startH;

        if (handleType.includes('e')) newW = Math.max(MIN_W, startW + dx);
        if (handleType.includes('s')) newH = Math.max(MIN_H, startH + dy);
        if (handleType.includes('w')) {
          newW = Math.max(MIN_W, startW - dx);
          newLeft = startLeft + startW - newW;
        }
        if (handleType.includes('n')) {
          newH = Math.max(MIN_H, startH - dy);
          newTop = startTop + startH - newH;
        }
        // Clamp to canvas bounds
        newLeft = Math.max(0, Math.min(pxW - MIN_W, newLeft));
        newTop  = Math.max(0, Math.min(pxH - MIN_H, newTop));

        el.style.left   = newLeft + 'px';
        el.style.top    = newTop  + 'px';
        el.style.width  = newW    + 'px';
        el.style.height = newH    + 'px';
      };

      const onUp = () => {
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
        // Snapshot BEFORE writing back (data model still has pre-drag values)
        this._pushUndo();
        // Write back to data model in EMU
        shape.left   = Math.round(parseInt(el.style.left)   / scale);
        shape.top    = Math.round(parseInt(el.style.top)    / scale);
        shape.width  = Math.round(parseInt(el.style.width)  / scale);
        shape.height = Math.round(parseInt(el.style.height) / scale);
        this._redrawThumb(this._curIdx);
        WA.scheduleAutoSave();
      };

      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
    }

    // ── Drag to move ─────────────────────────────────────────────────────────

    _startMove(e, el, shape, canvas, scale, enterEditOnClick = false, allowDrag = true) {
      // preventDefault/stopPropagation only happen once movement exceeds threshold.
      e.stopPropagation();

      const startX = e.clientX, startY = e.clientY;
      const origLeft = el.offsetLeft, origTop = el.offsetTop;
      const pxW = canvas.offsetWidth, pxH = canvas.offsetHeight;
      let moved = false;

      const onMove = (ev) => {
        const dx = ev.clientX - startX, dy = ev.clientY - startY;
        if (Math.abs(dx) < 4 && Math.abs(dy) < 4) return;
        if (!allowDrag) return;  // interior text click — don't drag shape
        ev.preventDefault();
        if (!moved) { window.getSelection && window.getSelection().removeAllRanges(); }
        moved = true;
        el.style.cursor = 'grabbing';
        const newL = Math.max(0, Math.min(pxW - el.offsetWidth,  origLeft + dx));
        const newT = Math.max(0, Math.min(pxH - el.offsetHeight, origTop  + dy));
        el.style.left = newL + 'px';
        el.style.top  = newT + 'px';
      };

      const onUp = (ev) => {
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
        el.style.cursor = shape.has_text ? 'text' : '';
        if (moved) {
          // Snapshot BEFORE writing back (el.style already updated, data model still old)
          this._pushUndo();
          // Write back to data model in EMU
          shape.left = Math.round(parseInt(el.style.left)  / scale);
          shape.top  = Math.round(parseInt(el.style.top)   / scale);
          this._redrawThumb(this._curIdx);
          WA.scheduleAutoSave();
        } else if (enterEditOnClick && shape.has_text && !this._editMode) {
          // Click (no drag) on an already-selected text shape → enter edit mode.
          // Place cursor at click position using caretRangeFromPoint for precision.
          this._enterEditModeAtPoint(el, ev.clientX, ev.clientY);
        }
      };

      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
    }

    // Enter edit mode and try to place the cursor at (x, y) screen coordinates.
    _enterEditModeAtPoint(el, x, y) {
      if (this._editMode && this._selShape === el) return;
      this._editMode = true;
      el.classList.add('wa-pptx-editing');
      const _inner = el.querySelector('.wa-pptx-inner');
      if (_inner) {
        _inner.contentEditable = 'true';
        _inner.querySelectorAll('.wa-pptx-run').forEach(s => s.removeAttribute('contenteditable'));
      } else {
        el.querySelectorAll('.wa-pptx-run').forEach(s => { s.contentEditable = 'true'; });
      }

      // Attempt precise caret placement at click point
      let placed = false;
      try {
        let range = null;
        if (document.caretRangeFromPoint) {
          range = document.caretRangeFromPoint(x, y);
        } else if (document.caretPositionFromPoint) {
          const pos = document.caretPositionFromPoint(x, y);
          if (pos) { range = document.createRange(); range.setStart(pos.offsetNode, pos.offset); range.collapse(true); }
        }
        if (range) {
          const node = range.startContainer;
          const span = node.nodeType === 3 ? node.parentElement : node;
          if (span && span.classList && span.classList.contains('wa-pptx-run')) {
            const sel = window.getSelection();
            sel.removeAllRanges();
            sel.addRange(range);
            span.focus();
            this._activeSpan = span;
            placed = true;
          }
        }
      } catch (_) { /* ignore */ }

      if (!placed) {
        const first = el.querySelector('.wa-pptx-run');
        if (first) { first.focus(); this._activeSpan = first; }
      }
    }

    _setActiveTableSummary(shape, selection = null) {
      if (shape && shape._type === 'TABLE' && Array.isArray(shape.cells)) {
        const normalized = _normalizePptxTableSelection(selection, shape.table_rows || 0, shape.table_cols || 0);
        this._lastTableText = _extractPptxTableText(shape, normalized);
        this._lastTableRows = normalized ? normalized.rows : (shape.table_rows || 0);
        this._lastTableCols = normalized ? normalized.cols : (shape.table_cols || 0);
        return;
      }
      this._lastTableText = null;
      this._lastTableRows = 0;
      this._lastTableCols = 0;
    }

    _clearTableSelection({ restoreWholeTableSummary = true } = {}) {
      if (this._tableSelectionCleanup) {
        try { this._tableSelectionCleanup(); } catch (_) { /* allowed to fail */ }
        this._tableSelectionCleanup = null;
      }

      const previousSelection = this._tableSelection;
      if (previousSelection && previousSelection.tableEl) {
        previousSelection.tableEl.querySelectorAll('.wa-pptx-cell-selected').forEach((cell) => {
          cell.classList.remove('wa-pptx-cell-selected');
        });
      }
      this._tableSelection = null;

      if (restoreWholeTableSummary && previousSelection && this._selShape) {
        const activeShapeId = Number(this._selShape.dataset.shapeId);
        if (activeShapeId === previousSelection.shapeId) {
          this._setActiveTableSummary(previousSelection.shape);
        }
      }
    }

    _setTableSelection(shapeEl, shape, tableEl, anchorCell, headCell = anchorCell) {
      const normalized = _normalizePptxTableSelection({
        anchorRow: anchorCell && anchorCell.row,
        anchorCol: anchorCell && anchorCell.col,
        headRow: headCell && headCell.row,
        headCol: headCell && headCell.col,
      }, shape.table_rows || 0, shape.table_cols || 0);
      if (!normalized || !tableEl) return null;

      this._tableSelection = Object.assign({
        shapeId: shape.id,
        shape,
        shapeEl,
        tableEl,
      }, normalized);

      tableEl.querySelectorAll('.wa-pptx-cell').forEach((cell) => {
        const row = Number(cell.dataset.row);
        const col = Number(cell.dataset.col);
        const isSelected = Number.isFinite(row) && Number.isFinite(col)
          && row >= normalized.startRow && row <= normalized.endRow
          && col >= normalized.startCol && col <= normalized.endCol;
        cell.classList.toggle('wa-pptx-cell-selected', isSelected);
      });

      this._setActiveTableSummary(shape, this._tableSelection);
      return this._tableSelection;
    }

    _beginTableSelection(event, shapeEl, shape, tableEl, startCellEl) {
      if (!event || event.button !== 0 || !startCellEl) return;

      const startCell = {
        row: Number(startCellEl.dataset.row),
        col: Number(startCellEl.dataset.col),
      };
      if (!Number.isFinite(startCell.row) || !Number.isFinite(startCell.col)) return;

      const previousSelection = this._tableSelection;
      const anchorCell = event.shiftKey && previousSelection && previousSelection.shapeId === shape.id
        ? { row: previousSelection.anchorRow, col: previousSelection.anchorCol }
        : startCell;

      this._clearTableSelection({ restoreWholeTableSummary: false });
      this._setTableSelection(shapeEl, shape, tableEl, anchorCell, startCell);

      const resolveCellFromPoint = (clientX, clientY) => {
        const target = document.elementFromPoint(clientX, clientY);
        const cell = target && target.closest ? target.closest('.wa-pptx-cell') : null;
        if (!cell || !tableEl.contains(cell)) return null;

        const row = Number(cell.dataset.row);
        const col = Number(cell.dataset.col);
        return Number.isFinite(row) && Number.isFinite(col) ? { row, col } : null;
      };

      const cleanup = () => {
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
        if (this._tableSelectionCleanup === cleanup) this._tableSelectionCleanup = null;
      };

      const onMove = (moveEvent) => {
        if ((moveEvent.buttons & 1) === 0) {
          cleanup();
          return;
        }

        const headCell = resolveCellFromPoint(moveEvent.clientX, moveEvent.clientY);
        if (!headCell) return;

        moveEvent.preventDefault();
        this._setTableSelection(shapeEl, shape, tableEl, anchorCell, headCell);
      };

      const onUp = (upEvent) => {
        const headCell = resolveCellFromPoint(upEvent.clientX, upEvent.clientY);
        if (headCell) this._setTableSelection(shapeEl, shape, tableEl, anchorCell, headCell);
        cleanup();
      };

      this._tableSelectionCleanup = cleanup;
      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
    }

    getCellSelectionInfo() {
      const selection = this._tableSelection;
      if (!selection || !selection.shape || !selection.tableEl) return null;

      const totalRows = selection.shape.table_rows || 0;
      const totalCols = selection.shape.table_cols || 0;
      if (selection.rows === totalRows && selection.cols === totalCols) return null;

      const text = _extractPptxTableText(selection.shape, selection).trim();
      if (!text) return null;

      return {
        text,
        rows: selection.rows,
        cols: selection.cols,
        selectedCells: selection.rows * selection.cols,
        tableElement: selection.tableEl,
      };
    }

    getWholeTableSelectionInfo() {
      const selection = this._tableSelection;
      if (selection && selection.shape && selection.tableEl) {
        const totalRows = selection.shape.table_rows || 0;
        const totalCols = selection.shape.table_cols || 0;
        if (selection.rows !== totalRows || selection.cols !== totalCols) return null;

        const text = _extractPptxTableText(selection.shape, selection).trim();
        if (!text) return null;
        return {
          text,
          rows: totalRows,
          cols: totalCols,
          tableElement: selection.tableEl,
        };
      }

      if (!this._selShape) return null;
      const slide = this.data && this.data.slides && this.data.slides[this._curIdx];
      const shapeId = Number(this._selShape.dataset.shapeId);
      const shape = slide && (slide.shapes || []).find((item) => item.id === shapeId);
      if (!shape || shape._type !== 'TABLE' || !shape.cells) return null;

      const text = _extractPptxTableText(shape).trim();
      if (!text) return null;

      return {
        text,
        rows: shape.table_rows || 0,
        cols: shape.table_cols || 0,
        tableElement: this._selShape.querySelector('table'),
      };
    }

    _selectShape(el, shape) {
      if (el === this._selShape) return;  // already selected — don't wipe edit mode
      this._clearSelection();
      this._selShape = el;
      el.classList.add('wa-pptx-selected');
      // Add 8 resize handles (CSS positions them at corners + edge midpoints)
      const _canvas = $('wa-pptx-slide-canvas');
      ['nw','n','ne','e','se','s','sw','w'].forEach(hType => {
        const hEl = document.createElement('div');
        hEl.className = 'wa-pptx-handle';
        hEl.dataset.h = hType;
        hEl.addEventListener('mousedown', e => {
          e.stopPropagation();
          e.preventDefault();
          this._startResize(e, el, shape, _canvas, this._scale || 1, hType);
        });
        el.appendChild(hEl);
      });
      // Store table data so the mouseup handler can expose it to AI quick-actions
      this._setActiveTableSummary(shape);
      // Show PPTX format hoverbar when a text shape is selected (even without entering edit mode)
      if (shape && shape.has_text) {
        setTimeout(() => {
          const hb = document.getElementById('wa-pptx-hoverbar');
          if (!hb) return;
          const shapeEl = el;
          const rect = shapeEl.getBoundingClientRect();
          const hbW = hb.offsetWidth || 360;
          const hbH = hb.offsetHeight || 30;
          let top = rect.top - hbH - 6;
          if (top < 60) top = rect.bottom + 6;
          let left = rect.left + rect.width / 2 - hbW / 2;
          left = Math.max(8, Math.min(left, window.innerWidth - hbW - 8));
          top = Math.min(top, window.innerHeight - hbH - 8);
          hb.style.left = left + 'px';
          hb.style.top  = top  + 'px';
          hb.style.display = 'flex';
        }, 20);
      } else {
        // Non-text shape selected — hide the format hoverbar if it was open
        this._hideHoverBar();
      }
      // Sync shape format toolbar
      if (shape) {
        const fillSw = $('wa-pptx-shapefill-swatch');
        if (fillSw) fillSw.style.background = shape.fill || '#fff';
        if ($('wa-pptx-shapefill')) $('wa-pptx-shapefill').value = shape.fill || '#ffffff';
        const borderSw = $('wa-pptx-shapeborder-swatch');
        if (borderSw) borderSw.style.background = (shape.border && shape.border.color) || '#000';
        if ($('wa-pptx-shapeborder')) $('wa-pptx-shapeborder').value = (shape.border && shape.border.color) || '#000000';
        if ($('wa-pptx-borderwidth')) $('wa-pptx-borderwidth').value = (shape.border && shape.border.width) || 0;
        // Populate Format tab (size / pos / rotation) from DOM geometry
        const canvasEl = $('wa-pptx-slide-canvas');
        if (canvasEl && el) {
          const scaleW = parseFloat(canvasEl.style.width)  / (this.data.slideWidthEmu  || 1);
          const scaleH = parseFloat(canvasEl.style.height) / (this.data.slideHeightEmu || 1);
          const pxW = Math.round((shape.width  || 0) * scaleW);
          const pxH = Math.round((shape.height || 0) * scaleH);
          const pxX = Math.round((shape.left   || 0) * scaleW);
          const pxY = Math.round((shape.top    || 0) * scaleH);
          if ($('wa-pptx-shapeW'))   $('wa-pptx-shapeW').value   = pxW;
          if ($('wa-pptx-shapeH'))   $('wa-pptx-shapeH').value   = pxH;
          if ($('wa-pptx-shapeX'))   $('wa-pptx-shapeX').value   = pxX;
          if ($('wa-pptx-shapeY'))   $('wa-pptx-shapeY').value   = pxY;
          if ($('wa-pptx-shapeRot')) $('wa-pptx-shapeRot').value = Math.round(shape.rotation || 0);
        }
        if ($('wa-pptx-opacity')) $('wa-pptx-opacity').value = Math.round((shape.opacity !== undefined ? shape.opacity : 1) * 100);
      }
    }

    _clearSelection() {
      this._clearTableSelection({ restoreWholeTableSummary: false });
      if (this._selShape) {
        this._selShape.classList.remove('wa-pptx-selected');
        // Remove resize handles
        this._selShape.querySelectorAll('.wa-pptx-handle').forEach(h => h.remove());
        this._selShape.style.overflow = 'hidden';
        const _inner = this._selShape.querySelector('.wa-pptx-inner');
        if (_inner) {
          _inner.contentEditable = 'false';
          _inner.querySelectorAll('.wa-pptx-run').forEach(s => { s.contentEditable = 'false'; });
        } else {
          this._selShape.querySelectorAll('.wa-pptx-run').forEach(s => { s.contentEditable = 'false'; });
        }
        this._selShape.querySelectorAll('.wa-pptx-cell').forEach(td => { td.contentEditable = 'false'; td.blur(); });
        this._selShape = null;
      }
      this._editMode = false;
      this._lastTableText = null;
      this._lastTableRows = 0;
      this._lastTableCols = 0;
      this._hideHoverBar();
    }

    _enterEditMode(el) {
      if (this._editMode && this._selShape === el) return;  // already editing this shape
      this._editMode = true;
      el.classList.add('wa-pptx-editing');
      // Make inner container the single contentEditable region so cross-run/line selection works
      const _inner = el.querySelector('.wa-pptx-inner');
      if (_inner) {
        _inner.contentEditable = 'true';
        _inner.querySelectorAll('.wa-pptx-run').forEach(s => s.removeAttribute('contenteditable'));
      } else {
        el.querySelectorAll('.wa-pptx-run').forEach(s => { s.contentEditable = 'true'; });
      }
      const first = el.querySelector('.wa-pptx-run');
      if (first) {
        first.focus();
        this._activeSpan = first;
        // Explicitly place cursor at end of span so empty spans are reliably typeable
        try {
          const r = document.createRange();
          r.selectNodeContents(first);
          r.collapse(false);   // collapse to end
          const sel = window.getSelection();
          if (sel) { sel.removeAllRanges(); sel.addRange(r); }
        } catch (e) { console.warn("[Koto]", e) }
      }
    }

    _exitEditMode() {
      if (this._selShape) {
        this._selShape.classList.remove('wa-pptx-editing');
        const _inner = this._selShape.querySelector('.wa-pptx-inner');
        if (_inner) {
          _inner.contentEditable = 'false';
          _inner.querySelectorAll('.wa-pptx-run').forEach(s => { s.contentEditable = 'false'; s.blur(); });
        } else {
          this._selShape.querySelectorAll('.wa-pptx-run').forEach(s => { s.contentEditable = 'false'; s.blur(); });
        }
        this._selShape.querySelectorAll('.wa-pptx-cell').forEach(td => {
          td.contentEditable = 'false';
          td.blur();
        });
      }
      this._editMode = false;
      this._hideHoverBar();
    }

    // ── Floating format hover bar (文字格式助手) ───────────────────────────────

    _showHoverBar(range) {
      const hb = document.getElementById('wa-pptx-hoverbar');
      if (!hb) return;
      hb.style.display = 'flex';
      let rect = range.getBoundingClientRect();
      // Fallback: getClientRects()[0] for cross-block or single-caret selections
      if (!rect || rect.height === 0) {
        const rects = range.getClientRects();
        for (let i = 0; i < rects.length; i++) {
          if (rects[i].height > 0) { rect = rects[i]; break; }
        }
      }
      // Last resort: anchor to the selected shape element
      if (!rect || rect.height === 0) {
        const shapeEl = this._selShape && document.querySelector(`.wa-pptx-shape[data-si="${this._selShape.shapeIdx ?? ''}"]`);
        if (shapeEl) rect = shapeEl.getBoundingClientRect();
      }
      if (!rect || rect.height === 0) { hb.style.display = 'none'; return; }
      const hbW = hb.offsetWidth || 360;
      const hbH = hb.offsetHeight || 30;
      let top = rect.top - hbH - 6;
      if (top < 60) top = rect.bottom + 6;
      let left = rect.left + rect.width / 2 - hbW / 2;
      left = Math.max(8, Math.min(left, window.innerWidth - hbW - 8));
      top = Math.min(top, window.innerHeight - hbH - 8);
      hb.style.left = left + 'px';
      hb.style.top  = top  + 'px';
    }

    _hideHoverBar() {
      const hb = document.getElementById('wa-pptx-hoverbar');
      if (hb) hb.style.display = 'none';
    }

    _syncHoverBar(run) {
      if (!run) return;
      const hbName = document.getElementById('wa-hb-fontname');
      const hbSize = document.getElementById('wa-hb-fontsize');
      const hbBold = document.getElementById('wa-hb-bold');
      const hbItal = document.getElementById('wa-hb-italic');
      const hbUnd  = document.getElementById('wa-hb-underline');
      const hbSw   = document.getElementById('wa-hb-color-swatch');
      if (hbName && run.fontName) hbName.value = run.fontName;
      if (hbSize && run.size)     hbSize.value  = Math.round(run.size);
      if (hbBold)  hbBold.classList.toggle('active',  !!run.bold);
      if (hbItal)  hbItal.classList.toggle('active',  !!run.italic);
      if (hbUnd)   hbUnd.classList.toggle('active',   !!run.underline);
      if (hbSw && run.color) hbSw.style.background = run.color;
    }

    _onRunFocus(shapeEl, shape, pi, ri, run) {
      this._activeSpan = document.activeElement;  // save before focus can move to toolbar
      this._selectShape(shapeEl, shape);
      if ($('wa-pptx-bold'))        $('wa-pptx-bold').classList.toggle('active',        !!run.bold);
      if ($('wa-pptx-italic'))      $('wa-pptx-italic').classList.toggle('active',      !!run.italic);
      if ($('wa-pptx-underline'))   $('wa-pptx-underline').classList.toggle('active',   !!run.underline);
      if ($('wa-pptx-strike'))      $('wa-pptx-strike').classList.toggle('active',      !!run.strikethrough);
      if ($('wa-pptx-super'))       $('wa-pptx-super').classList.toggle('active',       !!run.superscript);
      if ($('wa-pptx-sub'))         $('wa-pptx-sub').classList.toggle('active',         !!run.subscript);
      const _hsFocus = $('wa-pptx-highlight-swatch');
      if (_hsFocus) _hsFocus.style.background = run.highlight || 'transparent';
      if ($('wa-pptx-fontsize') && run.size) $('wa-pptx-fontsize').value = Math.round(run.size);
      if ($('wa-pptx-fontname') && run.fontName) $('wa-pptx-fontname').value = run.fontName;
      if ($('wa-pptx-fontcolor') && run.color) {
        $('wa-pptx-fontcolor').value = run.color.startsWith('#') ? run.color : '#000000';
        const sw = $('wa-pptx-fontcolor-swatch');
        if (sw) sw.style.background = run.color;
      }
    }

    // Apply a single property to a run data object (no DOM update)
    _applyRunProp(run, prop, value) {
      if (prop === 'bold')          run.bold          = value;
      else if (prop === 'italic')        run.italic        = value;
      else if (prop === 'underline')     run.underline     = value;
      else if (prop === 'strikethrough') run.strikethrough = value;
      else if (prop === 'superscript')   { run.superscript = value; if (value) run.subscript = false; }
      else if (prop === 'subscript')     { run.subscript   = value; if (value) run.superscript = false; }
      else if (prop === 'highlight')     run.highlight     = value;
      else if (prop === 'size')          run.size          = parseFloat(value);
      else if (prop === 'fontName')      run.fontName      = value;
      else if (prop === 'color')         run.color         = value;
    }

    applyFormat(prop, value) {
      this._pushUndo();
      const slide = this.data.slides[this._curIdx];
      // Prefer _savedRange (set by selectionchange handler) so toolbar clicks don't lose selection
      const browserSel = window.getSelection && window.getSelection();
      const activeRange = (this._savedRange && !this._savedRange.collapsed)
        ? this._savedRange
        : (browserSel && browserSel.rangeCount > 0 && !browserSel.isCollapsed ? browserSel.getRangeAt(0) : null);
      const sel = activeRange ? { isCollapsed: false, rangeCount: 1, getRangeAt: () => activeRange,
        containsNode: (n, p) => browserSel ? browserSel.containsNode(n, p) : activeRange.intersectsNode(n) } : null;

      // ── Case 1: partial selection within ONE span → split run ──────────────
      if (sel && !sel.isCollapsed && sel.rangeCount > 0) {
        const range = sel.getRangeAt(0);
        const startSpan = range.startContainer.nodeType === Node.TEXT_NODE
          ? range.startContainer.parentElement : range.startContainer;
        const endSpan   = range.endContainer.nodeType === Node.TEXT_NODE
          ? range.endContainer.parentElement   : range.endContainer;

        if (startSpan === endSpan && startSpan.classList.contains('wa-pptx-run')) {
          const shapeId = parseInt(startSpan.dataset.shapeId);
          const pi      = parseInt(startSpan.dataset.pi);
          const ri      = parseInt(startSpan.dataset.ri);
          const shape   = (slide.shapes || []).find(s => s.id === shapeId);
          const para    = shape && shape.paragraphs[pi];
          const run     = para && para.runs[ri];
          if (run) {
            const s = range.startOffset, e = range.endOffset;
            const text = run.text;
            // Determine toggle value from current run state
            if (prop === 'bold')            value = !run.bold;
            else if (prop === 'italic')         value = !run.italic;
            else if (prop === 'underline')      value = !run.underline;
            else if (prop === 'strikethrough')  value = !run.strikethrough;
            else if (prop === 'superscript')    value = !run.superscript;
            else if (prop === 'subscript')      value = !run.subscript;

            if (s === 0 && e === text.length) {
              // Whole span selected — just apply to the run in-place, no split needed
              this._applyRunProp(run, prop, value);
              startSpan.style.fontWeight      = run.bold      ? 'bold'      : '';
              startSpan.style.fontStyle       = run.italic    ? 'italic'    : '';
              startSpan.style.textDecoration  = _runTextDecoration(run);
              if (prop === 'size') {
                const scaleW = parseFloat($('wa-pptx-slide-canvas').style.width) / this.data.slideWidthEmu;
                startSpan.style.fontSize = Math.max(Math.round(run.size * scaleW * 12700), 6) + 'px';
              }
              if (prop === 'fontName') startSpan.style.fontFamily = value;
              if (prop === 'color')    startSpan.style.color = value;
              if (prop === 'superscript' || prop === 'subscript') {
                startSpan.style.verticalAlign = run.superscript ? 'super' : (run.subscript ? 'sub' : '');
                startSpan.style.fontSize = (run.superscript || run.subscript)
                  ? Math.max(Math.round((run.size || 18) * (parseFloat($('wa-pptx-slide-canvas').style.width) / this.data.slideWidthEmu) * 12700 * 0.75), 5) + 'px'
                  : Math.max(Math.round((run.size || 18) * (parseFloat($('wa-pptx-slide-canvas').style.width) / this.data.slideWidthEmu) * 12700), 6) + 'px';
              }
              if (prop === 'highlight') startSpan.style.backgroundColor = value || '';
              if (prop === 'align') {
                para.align = value.toUpperCase();
                if (startSpan.parentElement) startSpan.parentElement.style.textAlign = value;
              }
              if (prop === 'lineSpacing') {
                para.lineSpacing = value;
                if (startSpan.parentElement) startSpan.parentElement.style.lineHeight = value;
              }
            } else {
              // Partial selection — split into up to 3 sub-runs
              const newRuns = [];
              if (s > 0) newRuns.push({ ...run, text: text.slice(0, s) });
              const mid = { ...run, text: text.slice(s, e) };
              this._applyRunProp(mid, prop, value);
              newRuns.push(mid);
              if (e < text.length) newRuns.push({ ...run, text: text.slice(e) });
              para.runs.splice(ri, 1, ...newRuns);
              this._renderSlide(this._curIdx);
            }
            WA.scheduleAutoSave();
            return;
          }
        }
      }

      // ── Case 2: multi-span selection, focused span, or whole shape ──────────
      const selSpans = [];
      if (sel && !sel.isCollapsed && this._selShape) {
        this._selShape.querySelectorAll('.wa-pptx-run').forEach(s => {
          if (sel.containsNode(s, true)) selSpans.push(s);
        });
      }
      const spansToFormat = selSpans.length > 0
        ? selSpans
        : (this._activeSpan && this._activeSpan.classList.contains('wa-pptx-run'))
            ? [this._activeSpan]
            : (this._selShape ? Array.from(this._selShape.querySelectorAll('.wa-pptx-run')) : []);

      if (!spansToFormat.length) return;

      // For toggle props on multiple spans, determine direction from the first run
      let toggleVal = value;
      spansToFormat.forEach((active, idx) => {
        const shapeId = parseInt(active.dataset.shapeId);
        const pi      = parseInt(active.dataset.pi);
        const ri      = parseInt(active.dataset.ri);
        const shape   = (slide.shapes || []).find(s => s.id === shapeId);
        if (!shape) return;
        const run = shape.paragraphs[pi] && shape.paragraphs[pi].runs[ri];
        if (!run) return;

        // On the first run, fix the toggle direction and reuse for others
        if (idx === 0 && (prop === 'bold' || prop === 'italic' || prop === 'underline' || prop === 'strikethrough' || prop === 'superscript' || prop === 'subscript')) {
          toggleVal = !run[prop];
        }
        const fVal = (prop === 'bold' || prop === 'italic' || prop === 'underline' || prop === 'strikethrough' || prop === 'superscript' || prop === 'subscript') ? toggleVal : value;
        this._applyRunProp(run, prop, fVal);

        // Live DOM update (no full re-render needed)
        active.style.fontWeight     = run.bold      ? 'bold'      : '';
        active.style.fontStyle      = run.italic    ? 'italic'    : '';
        active.style.textDecoration = _runTextDecoration(run);
        if (prop === 'size') {
          const scaleW = parseFloat($('wa-pptx-slide-canvas').style.width) / this.data.slideWidthEmu;
          active.style.fontSize = Math.max(Math.round(run.size * scaleW * 12700), 6) + 'px';
        }
        if (prop === 'fontName') active.style.fontFamily = value;
        if (prop === 'color')    active.style.color = value;
        if (prop === 'superscript' || prop === 'subscript') {
          active.style.verticalAlign = run.superscript ? 'super' : (run.subscript ? 'sub' : '');
          const scaleW = parseFloat($('wa-pptx-slide-canvas').style.width) / this.data.slideWidthEmu;
          active.style.fontSize = (run.superscript || run.subscript)
            ? Math.max(Math.round((run.size || 18) * scaleW * 12700 * 0.75), 5) + 'px'
            : Math.max(Math.round((run.size || 18) * scaleW * 12700), 6) + 'px';
        }
        if (prop === 'highlight') active.style.backgroundColor = fVal || '';
        // Paragraph-level props
        if (prop === 'align') {
          shape.paragraphs[pi].align = fVal.toUpperCase();
          if (active.parentElement) active.parentElement.style.textAlign = fVal;
        }
        if (prop === 'lineSpacing') {
          shape.paragraphs[pi].lineSpacing = fVal;
          if (active.parentElement) active.parentElement.style.lineHeight = fVal;
        }
        if (prop === 'bullet') {
          const para = shape.paragraphs[pi];
          para.bullet = fVal;
          if (fVal) para.numbered = false;
          const pEl = active.parentElement;
          if (pEl) { pEl.style.paddingLeft = fVal ? '1.5em' : ''; pEl.dataset.bullet = fVal ? (typeof fVal === 'string' ? fVal : '•') : ''; }
        }
        if (prop === 'numbered') {
          const para = shape.paragraphs[pi];
          para.numbered = fVal;
          if (fVal) para.bullet = false;
          const pEl = active.parentElement;
          if (pEl) pEl.dataset.numbered = fVal ? '1' : '';
        }
        if (prop === 'indent') {
          const para = shape.paragraphs[pi];
          para.indent = Math.max(0, (para.indent || 0) + (fVal || 0));
          const pEl = active.parentElement;
          if (pEl) pEl.style.paddingLeft = (para.indent * 20) + 'px';
        }
        // Shape-level vertical-align (textAnchor)
        if (prop === 'verticalAlign') {
          const shapeEl = this._selShape;
          if (shapeEl) {
            shape.textAnchor = fVal;
            const inner = shapeEl.querySelector('.wa-pptx-inner');
            if (inner) {
              const jcMap = { t: 'flex-start', ctr: 'center', b: 'flex-end' };
              inner.style.justifyContent = jcMap[fVal] || 'flex-start';
            }
          }
        }
      });
      // Sync toolbar state for the first formatted span
      const firstRun = (() => {
        if (!spansToFormat[0]) return null;
        const sp = spansToFormat[0];
        const shape = (slide.shapes || []).find(s => s.id === parseInt(sp.dataset.shapeId));
        const pi = parseInt(sp.dataset.pi), ri = parseInt(sp.dataset.ri);
        return shape && shape.paragraphs[pi] && shape.paragraphs[pi].runs[ri];
      })();
      if (firstRun) {
        if ($('wa-pptx-bold'))      $('wa-pptx-bold').classList.toggle('active',      !!firstRun.bold);
        if ($('wa-pptx-italic'))    $('wa-pptx-italic').classList.toggle('active',    !!firstRun.italic);
        if ($('wa-pptx-underline')) $('wa-pptx-underline').classList.toggle('active', !!firstRun.underline);
        if ($('wa-pptx-strike'))    $('wa-pptx-strike').classList.toggle('active',    !!firstRun.strikethrough);
        if ($('wa-pptx-super'))     $('wa-pptx-super').classList.toggle('active',     !!firstRun.superscript);
        if ($('wa-pptx-sub'))       $('wa-pptx-sub').classList.toggle('active',       !!firstRun.subscript);
        const _hs = $('wa-pptx-highlight-swatch');
        if (_hs) _hs.style.background = firstRun.highlight || 'transparent';
      }
      WA.scheduleAutoSave();
    }

    setZoom(pct) {
      this._zoom = pct / 100;
      this._renderSlide(this._curIdx);
    }

    // ── Font size stepping (Ctrl+Shift+> / <) ────────────────────────────────

    _stepFontSize(dir) {
      const SIZES = [8,9,10,11,12,14,16,18,20,22,24,28,32,36,40,44,48,54,60,66,72,80,88,96];
      // Get current size from active span / savedRange
      const span = this._activeSpan;
      if (!span) return;
      const shapeId = parseInt(span.dataset.shapeId);
      const pi = parseInt(span.dataset.pi), ri = parseInt(span.dataset.ri);
      const slide = this.data.slides[this._curIdx];
      const shape = slide && (slide.shapes || []).find(s => s.id === shapeId);
      const run = shape && shape.paragraphs[pi] && shape.paragraphs[pi].runs[ri];
      if (!run) return;
      const curSize = Math.round(run.size || 18);
      let idx = SIZES.findIndex(s => s >= curSize);
      if (idx === -1) idx = SIZES.length - 1;
      const newIdx = Math.max(0, Math.min(SIZES.length - 1, idx + dir));
      this.applyFormat('size', SIZES[newIdx]);
      // Update toolbar font size display
      if ($('wa-pptx-fontsize')) $('wa-pptx-fontsize').value = SIZES[newIdx];
    }

    // ── Duplicate current slide ──────────────────────────────────────────────

    _duplicateSlide() {
      if (!this.data || !this.data.slides.length) return;
      this._pushUndo();
      const src = this.data.slides[this._curIdx];
      const copy = JSON.parse(JSON.stringify(src));
      // Assign new unique IDs to all shapes
      copy.shapes.forEach(s => { s.id = -(Date.now() % 100000000) - Math.floor(Math.random() * 10000); });
      const insertIdx = this._curIdx + 1;
      this.data.slides.splice(insertIdx, 0, copy);
      this.data.slides.forEach((s, i) => { s.index = i; });
      this._buildThumbs();
      this._renderSlide(insertIdx);
      WA.scheduleAutoSave();
      showToast('已复制幻灯片', 'info');
    }

    // ── Z-order: bring to front / send to back ──────────────────────────────

    _bringToFront(shapeId) {
      this._pushUndo();
      const slide = this.data.slides[this._curIdx];
      const shape = (slide.shapes || []).find(s => s.id === shapeId);
      if (!shape) return;
      shape.z_order = (slide.shapes.reduce((m, s) => Math.max(m, s.z_order), 0)) + 1;
      this._renderSlide(this._curIdx);
      WA.scheduleAutoSave();
    }

    _sendToBack(shapeId) {
      this._pushUndo();
      const slide = this.data.slides[this._curIdx];
      const shape = (slide.shapes || []).find(s => s.id === shapeId);
      if (!shape) return;
      const minZ = slide.shapes.reduce((m, s) => Math.min(m, s.z_order), Infinity);
      shape.z_order = Math.max(0, minZ - 1);
      this._renderSlide(this._curIdx);
      WA.scheduleAutoSave();
    }

    // ── Undo / Redo ──────────────────────────────────────────────────────────

    /** Snapshot current data + slideIdx onto the undo stack before any mutations. */
    _pushUndo() {
      this._undoStack.push({ slideIdx: this._curIdx, data: JSON.parse(JSON.stringify(this.data)) });
      if (this._undoStack.length > 50) this._undoStack.shift();
      this._redoStack = [];
      this._updateUndoRedoUI();
    }

    _undo() {
      if (!this._undoStack.length) return;
      this._redoStack.push({ slideIdx: this._curIdx, data: JSON.parse(JSON.stringify(this.data)) });
      const snap = this._undoStack.pop();
      this.data = snap.data;
      this._selShape = null;
      this._activeSpan = null;
      this._editMode = false;
      this._buildThumbs();
      this._renderSlide(Math.min(snap.slideIdx, this.data.slides.length - 1));
      this._updateUndoRedoUI();
      WA.scheduleAutoSave();
    }

    _redo() {
      if (!this._redoStack.length) return;
      this._undoStack.push({ slideIdx: this._curIdx, data: JSON.parse(JSON.stringify(this.data)) });
      const snap = this._redoStack.pop();
      this.data = snap.data;
      this._selShape = null;
      this._activeSpan = null;
      this._editMode = false;
      this._buildThumbs();
      this._renderSlide(Math.min(snap.slideIdx, this.data.slides.length - 1));
      this._updateUndoRedoUI();
      WA.scheduleAutoSave();
    }

    _updateUndoRedoUI() {
      const u = $('wa-pptx-undo');
      const r = $('wa-pptx-redo');
      if (u) u.disabled = !this._undoStack.length;
      if (r) r.disabled = !this._redoStack.length;
    }

  }
(window as any).KotoPptxEditor = KotoPptxEditor;
