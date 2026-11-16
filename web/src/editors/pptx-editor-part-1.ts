// @ts-nocheck
import { getFeatureRegistry } from '../shared/feature-registry';
import { setLastSelectionText } from '../shared/selection-runtime';
import { placeFixedInViewport } from '../shared/ui-scale';
import {
  createRenderSurfaceController,
  getRenderScaleSnapshot,
} from '../shared/render-surface';

const WA = getFeatureRegistry();
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


export class KotoPptxEditorPart1 {

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
      this._installRenderSurface();
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
        }
      };
      _tryPptxRender();
    }

    _installRenderSurface() {
      this._renderSurface?.dispose();
      this._renderSurface = null;
      const area = $('wa-pptx-slide-area');
      if (!area) return;
      const snapshot = getRenderScaleSnapshot(area);
      this._surfaceLogicalWidth = Math.round(snapshot.logicalSize.width * 100) / 100;
      this._surfaceDensityKey = `${snapshot.backingScale.x.toFixed(3)}:${snapshot.backingScale.y.toFixed(3)}`;
      this._renderSurface = createRenderSurfaceController(area, (nextSnapshot) => {
        const logicalWidth = Math.round(nextSnapshot.logicalSize.width * 100) / 100;
        const densityKey = `${nextSnapshot.backingScale.x.toFixed(3)}:${nextSnapshot.backingScale.y.toFixed(3)}`;
        const widthChanged = logicalWidth !== this._surfaceLogicalWidth;
        const densityChanged = densityKey !== this._surfaceDensityKey;
        this._surfaceLogicalWidth = logicalWidth;
        this._surfaceDensityKey = densityKey;
        if (!this.data) return;
        if (densityChanged) this._redrawAllThumbs();
        if (widthChanged && logicalWidth > 48) this._renderSlide(this._curIdx);
      });
    }

    _redrawAllThumbs() {
      document.querySelectorAll('.wa-pptx-thumb canvas').forEach((canvas, idx) => {
        const slide = this.data?.slides?.[idx];
        if (slide && this._renderedThumbs.has(idx)) this._drawThumbCanvas(canvas, slide, idx);
      });
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
      this._renderSurface?.dispose();
      this._renderSurface = null;
      this._thumbObserver?.disconnect();
      this._thumbObserver = null;
      this._renderedThumbs.clear();
      this._thumbAccess.clear();
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
      placeFixedInViewport(menu, x, y, 8);
    }

    _closeCtxMenu() {
      const menu = $('wa-pptx-ctx');
      if (menu) menu.style.display = 'none';
    }

    _showThumbCtxMenu(x, y, _idx) {
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
      placeFixedInViewport(menu, x, y, 8);
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
}
