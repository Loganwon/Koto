// ══════════════════════════════════════════════════════════════
// PptxViewer.js — 可编辑 PowerPoint 查看器 (文件助手集成版)
//
// 从 pptxData (slideWidthEmu / slideHeightEmu / slides) 渲染幻灯片。
// 文字 contentEditable 可直接编辑，编辑结果写回内存 pptxData，
// 通过 FileManager._saveCurrentDoc() 持久化。
// ══════════════════════════════════════════════════════════════

export class PptxViewer {
  /**
   * @param {string} centerId  中央区容器 DOM id (如 'center-doc')
   */
  constructor(centerId) {
    this._center = document.getElementById(centerId);
    this._host = null;

    this._pptxData = null;   // { slideWidthEmu, slideHeightEmu, slides[] }
    this._docId = null;
    this._name = '';
    this._curIdx = 0;
    this._zoom = 1.0;
    this._selShape = null;
    this._active = false;
    this._thumbTimer = null;

    this._buildDOM();
  }

  // ─── DOM 构建 ──────────────────────────────────────────────

  _buildDOM() {
    this._host = document.createElement('div');
    this._host.id = 'pptx-view-host';
    this._host.innerHTML = `
      <div class="pptx-topbar">
        <span class="pptx-topbar-name" id="pptx-topbar-name">演示文稿</span>
        <div class="pptx-topbar-controls">
          <button class="pptx-nav-btn" id="pptx-prev" title="上一张">◀</button>
          <span id="pptx-slide-indicator" style="min-width:44px;text-align:center">1/1</span>
          <button class="pptx-nav-btn" id="pptx-next" title="下一张">▶</button>
          <input type="range" id="pptx-zoom" min="40" max="200" value="100"
                 style="width:80px;accent-color:#4f7eff;cursor:pointer" title="缩放"/>
          <span id="pptx-zoom-label" style="min-width:38px;font-size:11px">100%</span>
          <button class="pptx-dl-btn" id="pptx-dl-btn">⬇ 下载</button>
        </div>
      </div>
      <div class="pptx-workspace">
        <div class="pptx-thumb-panel" id="pptx-thumb-panel"></div>
        <div class="pptx-canvas-area" id="pptx-canvas-area">
          <div class="pptx-slide-wrapper" id="pptx-slide-wrapper"></div>
        </div>
      </div>
    `;
    this._center.appendChild(this._host);

    // 绑定控件事件
    this._host.querySelector('#pptx-prev').addEventListener('click', () => this._prevSlide());
    this._host.querySelector('#pptx-next').addEventListener('click', () => this._nextSlide());
    this._host.querySelector('#pptx-zoom').addEventListener('input', (e) => {
      this._zoom = e.target.value / 100;
      this._host.querySelector('#pptx-zoom-label').textContent = e.target.value + '%';
      if (this._pptxData) this._renderSlide(this._curIdx);
    });
    this._host.querySelector('#pptx-dl-btn').addEventListener('click', () => this._download());
    this._host.querySelector('#pptx-canvas-area').addEventListener('click', (e) => {
      if (e.target === this._host.querySelector('#pptx-canvas-area')) {
        if (this._selShape) { this._selShape.classList.remove('pptx-shape-selected'); this._selShape = null; }
      }
    });
  }

  // ─── 公共 API ──────────────────────────────────────────────

  /**
   * 渲染幻灯片数据。
   * @param {object} pptxData  { slideWidthEmu, slideHeightEmu, slides[] }
   * @param {string} docId     文档 ID（用于下载端点）
   * @param {string} name      文档名称
   */
  async render(pptxData, docId, name) {
    this._pptxData = pptxData;
    this._docId = docId;
    this._name = name || '演示文稿';
    this._curIdx = 0;
    this._zoom = 1.0;
    this._host.querySelector('#pptx-topbar-name').textContent = this._name;
    this._host.querySelector('#pptx-zoom').value = '100';
    this._host.querySelector('#pptx-zoom-label').textContent = '100%';
    this.show();
    this._buildThumbs();
    this._renderSlide(0);
  }

  /** 返回当前（可能已编辑的）幻灯片数据，供 FileManager 保存 */
  getPptxData() {
    return this._pptxData;
  }

  show() {
    if (this._active) return;
    this._active = true;
    this._host.style.display = 'flex';
    // 隐藏 Univer Docs 画布
    const univerContainer = document.getElementById('univer-container');
    if (univerContainer) univerContainer.style.display = 'none';
    // 隐藏 DocxViewer
    const docxHost = document.getElementById('docx-view-host');
    if (docxHost) docxHost.style.display = 'none';
    // 隐藏 ExcelViewer
    const excelHost = document.getElementById('excel-view-host');
    if (excelHost) excelHost.style.display = 'none';
    // 隐藏浮动工具栏（选区 AI）
    const ft = window.__koto && window.__koto.floatingToolbar;
    if (ft && ft._toolbar) ft._toolbar.classList.add('hidden');
  }

  hide() {
    if (!this._active) return;
    this._active = false;
    this._host.style.display = 'none';
  }

  isActive() { return this._active; }

  /** Extract plain text from all slides (used by AIPanel / FloatingToolbar for context injection). */
  getFullText() {
    if (!this._pptxData || !this._pptxData.slides) return '';
    return this._pptxData.slides.map((slide, idx) =>
      `[幻灯片 ${idx + 1}]\n` +
      slide.shapes
        .filter(s => s.has_text && s.paragraphs)
        .map(s => s.paragraphs
          .map(p => (p.runs || []).map(r => r.text).join(''))
          .filter(t => t.trim()).join('\n'))
        .filter(t => t.trim()).join('\n')
    ).filter(t => t.trim()).join('\n\n');
  }

  // ─── 缩略图 ────────────────────────────────────────────────

  _buildThumbs() {
    const panel = this._host.querySelector('#pptx-thumb-panel');
    panel.innerHTML = '';
    const W = this._pptxData.slideWidthEmu;
    const H = this._pptxData.slideHeightEmu;
    const THUMB_W = 130;
    const THUMB_H = Math.round(THUMB_W * H / W);

    this._pptxData.slides.forEach((slide, idx) => {
      const wrap = document.createElement('div');
      wrap.className = 'pptx-thumb' + (idx === this._curIdx ? ' pptx-thumb-active' : '');
      wrap.title = `幻灯片 ${idx + 1}`;
      wrap.addEventListener('click', () => this._renderSlide(idx));

      const cv = document.createElement('canvas');
      cv.width = THUMB_W;
      cv.height = THUMB_H;
      this._drawThumb(cv, slide, W, H);

      const num = document.createElement('div');
      num.className = 'pptx-thumb-num';
      num.textContent = idx + 1;

      wrap.appendChild(cv);
      wrap.appendChild(num);
      panel.appendChild(wrap);
    });
  }

  _drawThumb(canvas, slide, slideW, slideH) {
    const ctx = canvas.getContext('2d');
    const sw = canvas.width, sh = canvas.height;
    const scX = sw / slideW, scY = sh / slideH;

    ctx.fillStyle = slide.background || '#ffffff';
    ctx.fillRect(0, 0, sw, sh);

    slide.shapes.forEach(shape => {
      const x = shape.left * scX, y = shape.top * scY;
      const w = shape.width * scX, h = shape.height * scY;
      if (shape.fill) {
        ctx.fillStyle = shape.fill;
        ctx.fillRect(x, y, w, h);
      }
      if (shape.has_text && shape.paragraphs) {
        ctx.save();
        ctx.beginPath(); ctx.rect(x, y, w, h); ctx.clip();
        let ty = y + 3;
        shape.paragraphs.forEach(para => {
          const lineText = (para.runs || []).map(r => r.text).join('');
          if (!lineText.trim()) { ty += 6; return; }
          const firstRun = (para.runs && para.runs[0]) || {};
          const ptSize = firstRun.size || 14;
          const px = Math.max(ptSize * scY * 0.85, 5);
          ctx.font = `${firstRun.bold ? 'bold ' : ''}${px}px "Microsoft YaHei",Segoe UI,sans-serif`;
          ctx.fillStyle = firstRun.color || '#222';
          ctx.fillText(lineText, x + 3, ty + px);
          ty += px * 1.4;
        });
        ctx.restore();
      }
    });
  }

  _scheduleThumbUpdate(idx) {
    clearTimeout(this._thumbTimer);
    this._thumbTimer = setTimeout(() => {
      const thumbs = this._host.querySelectorAll('.pptx-thumb canvas');
      if (thumbs[idx] && this._pptxData) {
        this._drawThumb(thumbs[idx], this._pptxData.slides[idx],
          this._pptxData.slideWidthEmu, this._pptxData.slideHeightEmu);
      }
    }, 350);
  }

  // ─── 幻灯片渲染 ────────────────────────────────────────────

  _renderSlide(idx) {
    this._curIdx = idx;
    this._selShape = null;

    // 高亮缩略图
    this._host.querySelectorAll('.pptx-thumb').forEach((el, i) => {
      el.classList.toggle('pptx-thumb-active', i === idx);
    });

    const slide = this._pptxData.slides[idx];
    const W = this._pptxData.slideWidthEmu;
    const H = this._pptxData.slideHeightEmu;

    const area = this._host.querySelector('#pptx-canvas-area');
    const maxW = (area.clientWidth || 900) - 48;
    const baseW = Math.min(maxW, 900);
    const scale = (this._zoom * baseW) / W;
    const pxW = Math.round(W * scale);
    const pxH = Math.round(H * scale);

    const wrapper = this._host.querySelector('#pptx-slide-wrapper');
    wrapper.style.width = pxW + 'px';
    wrapper.style.height = pxH + 'px';
    wrapper.style.background = slide.background || '#ffffff';
    wrapper.innerHTML = '';

    slide.shapes.forEach(shape => {
      const el = document.createElement('div');
      el.className = 'pptx-shape' + (shape.has_text ? ' pptx-shape-text' : '');
      el.dataset.shapeId = shape.id;
      el.style.left   = Math.round(shape.left   * scale) + 'px';
      el.style.top    = Math.round(shape.top    * scale) + 'px';
      el.style.width  = Math.round(shape.width  * scale) + 'px';
      el.style.height = Math.round(shape.height * scale) + 'px';

      if (shape.fill) el.style.background = shape.fill;

      if (shape.has_text && shape.paragraphs) {
        const inner = document.createElement('div');
        inner.className = 'pptx-shape-inner';

        shape.paragraphs.forEach((para, pi) => {
          const pEl = document.createElement('div');
          pEl.className = 'pptx-shape-para';
          pEl.style.textAlign = (para.align || 'LEFT').toLowerCase();

          (para.runs || []).forEach((run, ri) => {
            const span = document.createElement('span');
            span.contentEditable = 'true';
            span.spellcheck = false;
            span.dataset.pi = pi;
            span.dataset.ri = ri;
            span.textContent = run.text;

            const ptSize = run.size || 14;
            span.style.fontSize = Math.round(ptSize * scale * 1.33) + 'px';
            if (run.bold)      span.style.fontWeight = 'bold';
            if (run.italic)    span.style.fontStyle = 'italic';
            if (run.underline) span.style.textDecoration = 'underline';
            if (run.color)     span.style.color = run.color;
            span.style.whiteSpace = 'pre-wrap';
            span.style.display = 'inline';
            span.style.outline = 'none';
            span.style.fontFamily = '"Microsoft YaHei", "微软雅黑", Segoe UI, sans-serif';

            span.addEventListener('input', () => {
              // 写回内存
              if (shape.paragraphs[pi] && shape.paragraphs[pi].runs[ri] !== undefined) {
                shape.paragraphs[pi].runs[ri].text = span.textContent;
              }
              this._scheduleThumbUpdate(idx);
            });
            span.addEventListener('keydown', e => {
              if (e.key === 'Escape') span.blur();
            });
            pEl.appendChild(span);
          });

          if ((para.runs || []).length === 0) {
            pEl.appendChild(document.createElement('br'));
          }
          inner.appendChild(pEl);
        });

        el.appendChild(inner);
        el.addEventListener('mousedown', e => {
          if (!e.target.isContentEditable) this._selectShape(el);
        });
      }

      wrapper.appendChild(el);
    });

    this._host.querySelector('#pptx-slide-indicator').textContent =
      `${idx + 1} / ${this._pptxData.slides.length}`;
  }

  _selectShape(el) {
    if (this._selShape) this._selShape.classList.remove('pptx-shape-selected');
    this._selShape = el;
    el.classList.add('pptx-shape-selected');
  }

  // ─── 导航 & 下载 ────────────────────────────────────────────

  _prevSlide() {
    if (this._curIdx > 0) this._renderSlide(this._curIdx - 1);
  }

  _nextSlide() {
    if (this._pptxData && this._curIdx < this._pptxData.slides.length - 1) {
      this._renderSlide(this._curIdx + 1);
    }
  }

  async _download() {
    if (!this._docId) return;
    try {
      const r = await fetch(`/api/editor/docs/${encodeURIComponent(this._docId)}/pptx_download`);
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        alert(d.error || '下载失败');
        return;
      }
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = (this._name || 'presentation') + '.pptx';
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      alert('下载出错: ' + e.message);
    }
  }
}
