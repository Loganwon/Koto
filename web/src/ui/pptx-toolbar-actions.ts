// @ts-nocheck
/**
 * DOCX/PPTX toolbar bridges - hoverbar formatting, slide operations, shape operations.
 */

import {
  _evtEl,
  _getDocxSelectionPayload,
  _showTableTooltipNear,
  _updateContextBar,
} from './selection-toolbar';
import { $, _csrfFetch, _escHtml, showToast } from '../workspace/infrastructure';
import { _updateDocxZoomUI } from '../editors/cdn-loaders';
import { placeFixedInViewport } from '../shared/ui-scale';
import { WA, _CP_COLORS, state, workspaceApi } from './docx-pptx-toolbar';

// ── PPTX shape/slide operations ───────────────────────────────────

export function pptxShapeFill(val: string): void {
  const ed = state.activeEditor;
  if (!ed || !ed._selShape) { showToast('\u8bf7\u5148\u9009\u4e2d\u4e00\u4e2a\u5f62\u72b6', 'info'); return; }
  const swatch = $('wa-pptx-shapefill-swatch');
  if (swatch) swatch.style.background = val;
  ed._pushUndo();
  const shapeId = parseInt(ed._selShape.dataset.shapeId);
  const slide = ed.data.slides[ed._curIdx];
  const shape = (slide.shapes || []).find((s: any) => s.id === shapeId);
  if (shape) {
    shape.fill = val;
    ed._selShape.style.backgroundColor = val;
    WA.scheduleAutoSave();
  }
}

export function pptxShapeBorder(val: string): void {
  const ed = state.activeEditor;
  if (!ed || !ed._selShape) { showToast('\u8bf7\u5148\u9009\u4e2d\u4e00\u4e2a\u5f62\u72b6', 'info'); return; }
  const swatch = $('wa-pptx-shapeborder-swatch');
  if (swatch) swatch.style.background = val;
  ed._pushUndo();
  const shapeId = parseInt(ed._selShape.dataset.shapeId);
  const slide = ed.data.slides[ed._curIdx];
  const shape = (slide.shapes || []).find((s: any) => s.id === shapeId);
  if (shape) {
    if (!shape.border) shape.border = {};
    shape.border.color = val;
    const w = shape.border.width || 1;
    ed._selShape.style.border = w + 'pt solid ' + val;
    WA.scheduleAutoSave();
  }
}

export function pptxBorderWidth(val: string): void {
  const ed = state.activeEditor;
  if (!ed || !ed._selShape) return;
  ed._pushUndo();
  const shapeId = parseInt(ed._selShape.dataset.shapeId);
  const slide = ed.data.slides[ed._curIdx];
  const shape = (slide.shapes || []).find((s: any) => s.id === shapeId);
  if (shape) {
    if (!shape.border) shape.border = {};
    shape.border.width = parseFloat(val);
    if (parseFloat(val) === 0) {
      ed._selShape.style.border = 'none';
    } else {
      const c = shape.border.color || '#000000';
      ed._selShape.style.border = val + 'pt solid ' + c;
    }
    WA.scheduleAutoSave();
  }
}

export function pptxDupSlide(): void {
  const ed = state.activeEditor;
  if (ed && ed._duplicateSlide) ed._duplicateSlide();
}

export function pptxStepFont(dir: number): void {
  const ed = state.activeEditor;
  if (ed && ed._stepFontSize) ed._stepFontSize(dir);
}

export function pptxClearFormat(): void {
  const ed = state.activeEditor;
  if (!ed) return;
  const slide = ed.data.slides[ed._curIdx];
  const getSpans = (): HTMLElement[] => {
    const sel = window.getSelection && window.getSelection();
    const actRange = (ed._savedRange && !ed._savedRange.collapsed)
      ? ed._savedRange
      : (sel && sel.rangeCount > 0 && !sel.isCollapsed ? sel.getRangeAt(0) : null);
    if (actRange) {
      const arr: HTMLElement[] = [];
      ed._selShape && ed._selShape.querySelectorAll('.wa-pptx-run').forEach((s: HTMLElement) => {
        if (sel ? sel.containsNode(s, true) : actRange.intersectsNode(s)) arr.push(s);
      });
      if (arr.length) return arr;
    }
    return ed._activeSpan ? [ed._activeSpan]
      : (ed._selShape ? Array.from(ed._selShape.querySelectorAll('.wa-pptx-run')) : []);
  };
  const spans = getSpans();
  if (!spans.length) return;
  ed._pushUndo();
  spans.forEach((sp: HTMLElement) => {
    const shape = (slide.shapes || []).find((s: any) => s.id === parseInt(sp.dataset.shapeId || '0'));
    const run = shape && shape.paragraphs[parseInt(sp.dataset.pi || '0')] && shape.paragraphs[parseInt(sp.dataset.pi || '0')].runs[parseInt(sp.dataset.ri || '0')];
    if (!run) return;
    ['bold','italic','underline','strikethrough','superscript','subscript','highlight','color'].forEach(p => { delete run[p]; });
    sp.style.fontWeight = '';
    sp.style.fontStyle = '';
    sp.style.textDecoration = '';
    sp.style.verticalAlign = '';
    sp.style.backgroundColor = '';
    sp.style.color = '';
    const canvasEl = $('wa-pptx-slide-canvas');
    if (canvasEl) {
      const scaleW = parseFloat(canvasEl.style.width) / ed.data.slideWidthEmu;
      sp.style.fontSize = Math.max(Math.round((run.size || 18) * scaleW * 12700), 6) + 'px';
    }
  });
  WA.scheduleAutoSave();
}

export function pptxAddSlide(): void {
  const ed = state.activeEditor;
  if (!ed || !ed.data) return;
  ed._pushUndo();
  const newIdx = ed.data.slides.length;
  const sW = ed.data.slideWidthEmu || 9144000;
  const sH = ed.data.slideHeightEmu || 6858000;
  ed.data.slides.push({
    index: newIdx, background: '#ffffff',
    shapes: [
      {
        id: -(Date.now() % 100000000),
        name: 'Title', type: 'TEXT_BOX',
        left: Math.round(sW * 0.05), top: Math.round(sH * 0.06),
        width: Math.round(sW * 0.9), height: Math.round(sH * 0.18),
        z_order: 1, has_text: true, fill: null,
        paragraphs: [{ align: 'CENTER', runs: [{ text: '\u70b9\u51fb\u8f93\u5165\u6807\u9898', size: 36, bold: true }] }],
      },
      {
        id: -(Date.now() % 100000000) - 1,
        name: 'Content', type: 'TEXT_BOX',
        left: Math.round(sW * 0.05), top: Math.round(sH * 0.30),
        width: Math.round(sW * 0.9), height: Math.round(sH * 0.60),
        z_order: 2, has_text: true, fill: null,
        paragraphs: [{ align: 'LEFT', runs: [{ text: '\u70b9\u51fb\u8f93\u5165\u5185\u5bb9', size: 24 }] }],
      },
    ],
  });
  ed._buildThumbs();
  ed._renderSlide(newIdx);
  WA.scheduleAutoSave();
}

export function pptxDelSlide(): void {
  const ed = state.activeEditor;
  if (!ed || !ed.data || ed.data.slides.length <= 1) { showToast('\u81f3\u5c11\u4fdd\u7559\u4e00\u5f20\u5e7b\u706f\u7247', 'error'); return; }
  ed._pushUndo();
  const deletedIdx = ed._curIdx;
  ed.data.slides.splice(deletedIdx, 1);
  ed.data.slides.forEach((s: any, i: number) => { s.index = i; });
  const newIdx = Math.min(deletedIdx, ed.data.slides.length - 1);
  ed._buildThumbs();
  ed._renderSlide(newIdx);
  WA.scheduleAutoSave();
  showToast(`\u5df2\u5220\u9664\u7b2c ${deletedIdx + 1} \u5f20\u5e7b\u706f\u7247`, 'info');
}

export function pptxInsertShape(type: string): void {
  const ed = state.activeEditor;
  if (!ed) return;
  const slide = ed.data.slides[ed._curIdx];
  if (!slide) return;
  ed._pushUndo();
  const newId = Math.max(0, ...(slide.shapes || []).map((s: any) => s.id || 0)) + 1;
  const W = ed.data.slideWidthEmu, H = ed.data.slideHeightEmu;
  const shape: any = {
    id: newId, type: 'shape', shapeType: type,
    left: W * 0.3, top: H * 0.3,
    width: W * 0.2, height: H * 0.15,
    fill: '#4472C4',
    border: { color: '#2F4E8A', width: 1 },
    paragraphs: [{ runs: [], align: 'CENTER' }]
  };
  if (type === 'line') {
    shape.height = 0;
    shape.top = H * 0.5;
    shape.fill = 'none';
    shape.border = { color: '#4472C4', width: 2 };
  }
  slide.shapes.push(shape);
  ed._renderSlide(ed._curIdx);
  WA.scheduleAutoSave();
}

export function pptxSetShapeSize(dim: string, val: string): void {
  const ed = state.activeEditor;
  if (!ed || !ed._selShape) return;
  const px = parseFloat(val);
  if (isNaN(px) || px <= 0) return;
  const shapeId = parseInt(ed._selShape.dataset.shapeId);
  const slide = ed.data.slides[ed._curIdx];
  const shape = (slide.shapes || []).find((s: any) => s.id === shapeId);
  if (!shape) return;
  ed._pushUndo();
  const canvasEl = $('wa-pptx-slide-canvas');
  const scaleW = parseFloat(canvasEl!.style.width) / ed.data.slideWidthEmu;
  const scaleH = parseFloat(canvasEl!.style.height) / ed.data.slideHeightEmu;
  if (dim === 'w') { shape.width = px / scaleW; ed._selShape.style.width = px + 'px'; }
  else             { shape.height = px / scaleH; ed._selShape.style.height = px + 'px'; }
  WA.scheduleAutoSave();
}

export function pptxSetShapePos(dim: string, val: string): void {
  const ed = state.activeEditor;
  if (!ed || !ed._selShape) return;
  const px = parseFloat(val);
  if (isNaN(px)) return;
  const shapeId = parseInt(ed._selShape.dataset.shapeId);
  const slide = ed.data.slides[ed._curIdx];
  const shape = (slide.shapes || []).find((s: any) => s.id === shapeId);
  if (!shape) return;
  ed._pushUndo();
  const canvasEl = $('wa-pptx-slide-canvas');
  const scaleW = parseFloat(canvasEl!.style.width) / ed.data.slideWidthEmu;
  const scaleH = parseFloat(canvasEl!.style.height) / ed.data.slideHeightEmu;
  if (dim === 'x') { shape.left = px / scaleW;  ed._selShape.style.left = px + 'px'; }
  else             { shape.top  = px / scaleH;  ed._selShape.style.top  = px + 'px'; }
  WA.scheduleAutoSave();
}

export function pptxSetShapeRot(deg: string): void {
  const ed = state.activeEditor;
  if (!ed || !ed._selShape) return;
  const d = parseFloat(deg);
  if (isNaN(d)) return;
  const shapeId = parseInt(ed._selShape.dataset.shapeId);
  const slide = ed.data.slides[ed._curIdx];
  const shape = (slide.shapes || []).find((s: any) => s.id === shapeId);
  if (!shape) return;
  ed._pushUndo();
  shape.rotation = d;
  ed._selShape.style.transform = 'rotate(' + d + 'deg)';
  WA.scheduleAutoSave();
}

export function pptxHighlightColor(val: string): void {
  const swatch = $('wa-pptx-highlight-swatch');
  if (swatch) swatch.style.background = val;
  const ed = state.activeEditor;
  if (ed && ed.applyFormat) ed.applyFormat('highlight', val);
}

// ── PPTX slide background operations ──────────────────────────────

export function pptxBgColor(color: string): void {
  const ed = state.activeEditor;
  if (!ed) return;
  ed._pushUndo();
  const slide = ed.data.slides[ed._curIdx];
  slide.background = color;
  slide.backgroundGradient = null;
  slide.backgroundImage = null;
  const canvas = $('wa-pptx-slide-canvas');
  if (canvas) canvas.style.background = color;
  const swatch = $('wa-pptx-bg-swatch');
  if (swatch) swatch.style.background = color;
  ed._redrawThumb(ed._curIdx);
  WA.scheduleAutoSave();
}

export function pptxSetBgImage(fileInput: HTMLInputElement): void {
  const ed = state.activeEditor;
  if (!ed || !fileInput.files || !fileInput.files[0]) return;
  const file = fileInput.files[0];
  fileInput.value = '';
  const reader = new FileReader();
  reader.onload = (ev) => {
    const raw = ev.target!.result as string;
    const img = new Image();
    img.onload = () => {
      const MAX = 1920;
      let w = img.naturalWidth, h = img.naturalHeight;
      if (w > MAX || h > MAX) {
        const ratio = Math.min(MAX / w, MAX / h);
        w = Math.round(w * ratio);
        h = Math.round(h * ratio);
      }
      const _cv = document.createElement('canvas');
      _cv.width = w; _cv.height = h;
      const _ctx = _cv.getContext('2d')!;
      _ctx.drawImage(img, 0, 0, w, h);
      const dataUri = _cv.toDataURL('image/jpeg', 0.82);
      ed._pushUndo();
      const slide = ed.data.slides[ed._curIdx];
      slide.backgroundImage = dataUri;
      slide.backgroundGradient = null;
      const canvas = $('wa-pptx-slide-canvas');
      if (canvas) canvas.style.background = `url('${dataUri}') center/cover no-repeat`;
      const swatch = $('wa-pptx-bg-swatch');
      if (swatch) { swatch.style.background = `url('${dataUri}') center/cover`; swatch.style.backgroundSize = 'cover'; }
      ed._redrawThumb(ed._curIdx);
      WA.scheduleAutoSave();
    };
    img.src = raw;
  };
  reader.readAsDataURL(file);
}

export function pptxRemoveBg(): void {
  const ed = state.activeEditor;
  if (!ed) return;
  ed._pushUndo();
  const slide = ed.data.slides[ed._curIdx];
  slide.background = '#ffffff';
  slide.backgroundGradient = null;
  slide.backgroundImage = null;
  const canvas = $('wa-pptx-slide-canvas');
  if (canvas) canvas.style.background = '#ffffff';
  const swatch = $('wa-pptx-bg-swatch');
  if (swatch) { swatch.style.background = '#ffffff'; swatch.style.backgroundImage = ''; }
  ed._redrawThumb(ed._curIdx);
  WA.scheduleAutoSave();
}

export function pptxApplyQuickLayout(layout: string): void {
  const ed = state.activeEditor;
  if (ed && ed._applyQuickLayout) ed._applyQuickLayout(layout);
}

export function pptxChangeBgImage(fileInput: HTMLInputElement): void {
  pptxSetBgImage(fileInput);
}

export function pptxFmt(cmd: string): void {
  const ed = state.activeEditor;
  if (ed && typeof ed.applyFormat === 'function') ed.applyFormat(cmd);
}

export function pptxAlign(align: string): void {
  const ed = state.activeEditor;
  if (ed && typeof ed.applyFormat === 'function') ed.applyFormat('align', align);
}

export function pptxFontSize(size: string): void {
  const ed = state.activeEditor;
  if (ed && typeof ed.applyFormat === 'function') ed.applyFormat('size', size);
}

export function pptxFontName(value: string): void {
  const ed = state.activeEditor;
  if (ed && typeof ed.applyFormat === 'function') ed.applyFormat('fontName', value);
}

export function pptxFontColor(value: string): void {
  const swatch = $('wa-pptx-fontcolor-swatch');
  if (swatch) swatch.style.background = value;
  const hoverSwatch = $('wa-hb-color-swatch');
  if (hoverSwatch) hoverSwatch.style.background = value;
  const ed = state.activeEditor;
  if (ed && typeof ed.applyFormat === 'function') ed.applyFormat('color', value);
}

export function pptxColorPicker(type: string, triggerEl?: HTMLElement): void {
  const palette = $('wa-pptx-cp');
  const grid = $('wa-pptx-cp-grid');
  if (!palette || !grid) return;
  if (palette.style.display !== 'none' && palette.dataset.cpType === type) {
    palette.style.display = 'none';
    return;
  }
  palette.dataset.cpType = type;
  grid.innerHTML = _CP_COLORS.map((c: string) =>
    `<div title="${c}" style="width:18px;height:18px;border-radius:3px;background:${c};cursor:pointer;border:1px solid rgba(255,255,255,.12);box-sizing:border-box"` +
    ` data-wa-toolbar-color="pptx" data-color="${c}"></div>`
  ).join('');
  if (triggerEl) {
    const r = triggerEl.getBoundingClientRect();
    palette.style.visibility = 'hidden';
    palette.style.display = 'block';
    placeFixedInViewport(palette, r.left, r.bottom + 4, 4);
    palette.style.visibility = '';
    return;
  }
  palette.style.display = 'block';
}

export function _pptxPickColor(color: string, keepOpen?: boolean): void {
  const palette = $('wa-pptx-cp');
  const type = palette ? palette.dataset.cpType : '';
  if (type === 'font') pptxFontColor(color);
  else if (type === 'fill') pptxShapeFill(color);
  else if (type === 'border') pptxShapeBorder(color);
  else if (type === 'highlight') pptxHighlightColor(color);
  else if (type === 'bg') pptxBgColor(color);
  const hexEl = $('wa-pptx-cp-hex');
  if (hexEl) hexEl.textContent = color;
  const customInput = $('wa-pptx-cp-custom') as HTMLInputElement;
  if (customInput && /^#[0-9a-f]{6}$/i.test(color)) customInput.value = color;
  if (!keepOpen && palette) palette.style.display = 'none';
}

export function pptxIndent(delta: number): void {
  const ed = state.activeEditor;
  if (ed && typeof ed.applyFormat === 'function') ed.applyFormat('indent', Number(delta) || 0);
}

export function pptxLineSpacing(value: string): void {
  const ed = state.activeEditor;
  if (ed && typeof ed.applyFormat === 'function') ed.applyFormat('lineSpacing', value);
}

export function pptxToggleBullet(): void {
  const ed = state.activeEditor;
  if (ed && typeof ed.applyFormat === 'function') ed.applyFormat('bullet', true);
}

export function pptxToggleNumbered(): void {
  const ed = state.activeEditor;
  if (ed && typeof ed.applyFormat === 'function') ed.applyFormat('numbered', true);
}

export function pptxVertAlign(value: string): void {
  const ed = state.activeEditor;
  if (ed && typeof ed.applyFormat === 'function') ed.applyFormat('verticalAlign', value);
}

export function pptxOpacity(value: string): void {
  const ed = state.activeEditor;
  if (!ed || !ed._selShape) return;
  const pct = Math.max(0, Math.min(100, parseFloat(value)));
  if (!Number.isFinite(pct)) return;
  const shapeId = parseInt(ed._selShape.dataset.shapeId || '0');
  const slide = ed.data && ed.data.slides && ed.data.slides[ed._curIdx];
  const shape = slide && (slide.shapes || []).find((s: any) => s.id === shapeId);
  if (!shape) return;
  if (typeof ed._pushUndo === 'function') ed._pushUndo();
  shape.opacity = pct / 100;
  ed._selShape.style.opacity = String(shape.opacity);
  WA.scheduleAutoSave();
}

export function pptxZOrder(action: string): void {
  const ed = state.activeEditor;
  if (!ed || !ed._selShape) return;
  const shapeId = parseInt(ed._selShape.dataset.shapeId || '0');
  if (action === 'front' && typeof ed._bringToFront === 'function') ed._bringToFront(shapeId);
  else if (action === 'back' && typeof ed._sendToBack === 'function') ed._sendToBack(shapeId);
  else if ((action === 'up' || action === 'forward') && typeof ed._reorder === 'function') ed._reorder(shapeId, 1);
  else if ((action === 'down' || action === 'backward') && typeof ed._reorder === 'function') ed._reorder(shapeId, -1);
}

export function pptxZoom(value: string | number): void {
  const pct = parseInt(String(value), 10);
  const label = $('wa-pptx-zoom-label');
  if (label && Number.isFinite(pct)) label.textContent = pct + '%';
  const ed = state.activeEditor;
  if (ed && typeof ed.setZoom === 'function' && Number.isFinite(pct)) ed.setZoom(pct);
}

export function pptxNav(delta: number): void {
  const ed = state.activeEditor;
  if (!ed || !ed.data || !Array.isArray(ed.data.slides) || typeof ed._renderSlide !== 'function') return;
  const next = (ed._curIdx || 0) + Number(delta || 0);
  if (next >= 0 && next < ed.data.slides.length) ed._renderSlide(next);
}

export function docxZoom(value: string | number): void {
  const pct = parseInt(String(value), 10);
  const ed = state.activeEditor;
  if (ed && typeof ed.setZoom === 'function' && Number.isFinite(pct)) ed.setZoom(pct);
  if (Number.isFinite(pct)) _updateDocxZoomUI(pct);
}

export function pptxInsertImageClick(): void {
  const input = document.getElementById('wa-pptx-img-input') as HTMLInputElement | null
    || document.getElementById('wa-pptx-insert-image-file') as HTMLInputElement | null
    || document.getElementById('wa-pptx-image-input') as HTMLInputElement | null;
  if (input) {
    input.click();
    return;
  }
  showToast('未找到 PPT 图片文件选择器，请刷新后重试', 'warning');
}

export function pptxInsertImageFile(input: HTMLInputElement): void {
  const ed = state.activeEditor;
  const file = input && input.files && input.files[0];
  if (!file) return;
  input.value = '';
  if (!ed) {
    showToast('请先打开一个 PPT 文件', 'warning');
    return;
  }
  if (typeof ed.insertImageFile === 'function') {
    ed.insertImageFile(file);
    return;
  }
  if (typeof ed._insertImageFile === 'function') {
    ed._insertImageFile(file);
    return;
  }
  showToast('当前 PPT 编辑器不支持插入图片，请刷新后重试', 'error');
}

// ── Image send-to-AI ───────────────────────────────────────────────
export function _sendImageToAI(action: string, imgSrc: string): void {
  const aiInput = document.getElementById('wa-user-input') as HTMLTextAreaElement;
  if (!aiInput) return;
  const label = action === 'describe' ? '\u8bf7\u63cf\u8ff0\u8fd9\u5f20\u56fe\u7247\u7684\u5185\u5bb9' : '\u8bf7\u4e3a\u8fd9\u5f20\u56fe\u7247\u751f\u6210\u66ff\u6362\u65b9\u6848';
  aiInput.value = label;
  aiInput.focus();
  workspaceApi._pendingImageSrc = imgSrc;
  WA.sendMessage();
}

export function pptxDelShape(): void {
  const ed = state.activeEditor;
  if (ed && ed.deleteSelected) ed.deleteSelected();
}

export function pptxSwitchTab(btn: HTMLElement, tabName: string): void {
  document.querySelectorAll('.wa-pptx-rtab').forEach(t => t.classList.remove('active'));
  btn.classList.add('active');
  const toolbar = document.getElementById('wa-pptx-toolbar');
  if (!toolbar) return;
  toolbar.querySelectorAll('[data-tab]').forEach(el => {
    (el as HTMLElement).style.display = ((el as HTMLElement).dataset.tab === tabName) ? '' : 'none';
  });
}

export function pptxInsertMode(): void {
  const ed = state.activeEditor;
  if (!ed || !ed.data) return;
  ed._insertMode = !ed._insertMode;
  const btn = $('wa-pptx-insert-tb');
  if (btn) btn.classList.toggle('active', ed._insertMode);
  const canvas = $('wa-pptx-slide-canvas');
  if (canvas) canvas.style.cursor = ed._insertMode ? 'crosshair' : '';
  const mainEl = $('wa-pptx-main');
  if (mainEl) { mainEl.scrollLeft = 0; mainEl.scrollTop = 0; }
  if (ed._insertMode) showToast('\u5728\u5e7b\u706f\u7247\u4e0a\u62d6\u62fd\u7ed8\u5236\u6587\u672c\u6846', 'info');
}

export function pptxSave(): void {
  if (state.activeEditor && state.activeEditor.serialize) {
    WA.saveFile();
  }
}

export function pptxUndo(): void {
  if (state.activeEditor && state.activeEditor._undo) state.activeEditor._undo();
}

export function pptxRedo(): void {
  if (state.activeEditor && state.activeEditor._redo) state.activeEditor._redo();
}

export function pptxDownload(): void {
  if (state.fileId) {
    WA.saveFile().then(() => {
      const a = document.createElement('a');
      a.href = `/api/v1/workspace/raw/${state.fileId}`;
      a.download = state.fileName || 'presentation.pptx';
      a.click();
    }).catch(() => {});
  }
}
