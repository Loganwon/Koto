// ══════════════════════════════════════════════════════════════
// DocController.js — 模块 A：Canvas 渲染控制层
//
// 唯一有权操作 Univer 引擎的模块。向外暴露极简的 Facade 接口，
// 屏蔽 Univer 底层复杂度，禁止其他模块直接导入 @univerjs/*。
//
// 重要：Univer 0.5.x FDocument Facade 仅暴露 appendText / setSelection，
// 无 replaceText / getBody / getActiveRange。所有文本变更统一通过
// disposeUnit → createUnit 管线确保 paragraphs / sectionBreaks 合法。
// ══════════════════════════════════════════════════════════════

import { UniverInstanceType } from '@univerjs/core';

export class DocController {
  /** @param {import('@univerjs/core').FUniver} univerAPI */
  constructor(univerAPI) {
    this._api = univerAPI;
    /** Undo stack: stores previous full-text strings (max 30) */
    this._undoStack = [];
    /** Current open file extension (e.g. '.docx', '.pptx') — set by FileManager */
    this._fileType = '';
    /** Current open file display name — set by FileManager */
    this._fileName = '';
  }

  setFileType(ext)  { this._fileType = ext  || ''; }
  getFileType()     { return this._fileType; }
  setFileName(name) { this._fileName = name || ''; }
  getFileName()     { return this._fileName; }

  // ──────────────────────────────────────────
  // 1. 获取当前选区文本（优先使用浏览器原生选区）
  //    无选区时返回 null，由调用方自行决定是否回退到全文。
  // ──────────────────────────────────────────
  getSelection() {
    const fullText = this.getFullText();
    if (!fullText) return null;

    // 尝试从浏览器原生 Selection 获取（Univer 0.5.x Facade 不暴露选区）
    try {
      const sel = window.getSelection();
      if (sel && !sel.isCollapsed && sel.rangeCount > 0) {
        const selectedText = sel.toString().trim();
        if (selectedText && selectedText.length > 0) {
          // 精确定位：先用 DOM Range 走读字符数，回退 indexOf（首次匹配）
          let idx = this._getDomRangeStartOffset(sel);
          if (idx < 0 || fullText.substring(idx, idx + selectedText.length) !== selectedText) {
            idx = fullText.indexOf(selectedText);
          }
          if (idx >= 0) {
            return {
              text: selectedText,
              range: { startOffset: idx, endOffset: idx + selectedText.length },
              fullText,
            };
          }
        }
      }
    } catch (_) { /* 浏览器选区不可用，回退全文 */ }

    return null;
  }

  // ──────────────────────────────────────────
  // 2. 获取全文纯文本
  // ──────────────────────────────────────────
  getFullText() {
    const doc = this._getDoc();
    if (!doc) return '';
    try {
      const snapshot = typeof doc.getSnapshot === 'function' ? doc.getSnapshot() : null;
      return this._streamToText(snapshot?.body?.dataStream || '').trim();
    } catch (e) {
      console.error('[DocController] getFullText 失败:', e);
      return '';
    }
  }

  // ──────────────────────────────────────────
  // 3. 在文档末尾追加文本
  // ──────────────────────────────────────────
  insertTextAtCursor(text) {
    if (!text) return false;
    const current = this.getFullText();
    const hlStart = current.length;
    const hlEnd   = current.length + text.length;
    const ok = this._replaceEntireDoc(current + text);
    if (ok) this._flashChangedRegion(hlStart, hlEnd, text.replace(/^\n/, ''));
    return ok;
  }

  // ──────────────────────────────────────────
  // 3b. 在文档区底部追加图片（浮动 overlay）
  // ──────────────────────────────────────────
  insertImageAtEnd(dataUrl, altText) {
    // Univer 0.5.x Facade does not expose image insertion.
    // Append a positioned image block inside #center-doc as a best-effort overlay.
    const container = document.getElementById('center-doc');
    if (!container) return;

    // Remove any previous dropped-image placeholder from the same session
    // so multiple drops don't stack if user made a mistake.
    const wrapper = document.createElement('div');
    wrapper.className = 'koto-dropped-image';
    wrapper.title = '图表已插入（拖动可重新定位）';

    const img = document.createElement('img');
    img.src = dataUrl;
    img.alt = altText || '图表';
    img.draggable = false;

    const closeBtn = document.createElement('button');
    closeBtn.className = 'koto-dropped-image-close';
    closeBtn.textContent = '✕';
    closeBtn.title = '移除图片';
    closeBtn.addEventListener('click', () => wrapper.remove());

    wrapper.appendChild(img);
    wrapper.appendChild(closeBtn);
    container.appendChild(wrapper);

    // Simple drag-to-reposition within #center-doc
    let _ox = 0, _oy = 0, _sx = 0, _sy = 0;
    wrapper.addEventListener('mousedown', (e) => {
      if (e.target === closeBtn) return;
      e.preventDefault();
      _sx = e.clientX; _sy = e.clientY;
      _ox = wrapper.offsetLeft; _oy = wrapper.offsetTop;
      const onMove = (ev) => {
        wrapper.style.left = (_ox + ev.clientX - _sx) + 'px';
        wrapper.style.top  = (_oy + ev.clientY - _sy) + 'px';
      };
      const onUp = () => {
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
      };
      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
    });

    // Flash the container to confirm success
    this._flashChangedRegion(0, 0, altText || '图表');
  }

  // ──────────────────────────────────────────
  // 4. 替换指定范围内的文本（安全重建文档）
  // ──────────────────────────────────────────
  replaceRange(range, newText) {
    if (!newText) return false;
    const doc = this._getDoc();
    if (!doc) return false;

    try {
      const snapshot = typeof doc.getSnapshot === 'function' ? doc.getSnapshot() : null;
      const dataStream = snapshot?.body?.dataStream || '';
      const fullText = this._streamToText(dataStream);
      const start = range?.startOffset ?? 0;
      const end = range?.endOffset ?? fullText.length;

      // 拼接替换后的全文并重建文档
      if (start >= 0 && end > start && end <= fullText.length) {
        const before = fullText.substring(0, start);
        const after = fullText.substring(end);
        const ok = this._replaceEntireDoc(before + newText + after);
        if (ok) this._flashChangedRegion(start, start + newText.length, newText);
        return ok;
      }

      // 范围不合法时直接用新文本替换全文
      const ok = this._replaceEntireDoc(newText);
      if (ok) this._flashChangedRegion(0, newText.length, newText);
      return ok;
    } catch (e) {
      console.error('[DocController] replaceRange 失败:', e);
      return false;
    }
  }

  // ──────────────────────────────────────────
  // 5. 将文本内容加载到文档中（替换全部内容）
  // 加载文件时清空撤销栈，不作为可撤销操作记录
  // ──────────────────────────────────────────
  loadContent(text) {
    this._undoStack = [];
    return this._replaceEntireDocNoStack(text || '');
  }

  // ──────────────────────────────────────────
  // 6. 获取文档快照（JSON 格式）
  // ──────────────────────────────────────────
  getSnapshot() {
    const doc = this._getDoc();
    if (!doc) return null;
    try {
      return typeof doc.getSnapshot === 'function' ? doc.getSnapshot() : null;
    } catch (e) {
      console.error('[DocController] getSnapshot 失败:', e);
      return null;
    }
  }

  // ──────────────────────────────────────────
  // 7. 获取文档元信息
  // ──────────────────────────────────────────
  getDocInfo() {
    const doc = this._getDoc();
    if (!doc) return null;
    try {
      const snapshot = typeof doc.getSnapshot === 'function' ? doc.getSnapshot() : null;
      const stream = snapshot?.body?.dataStream || '';
      return {
        id: typeof doc.getId === 'function' ? doc.getId() : 'unknown',
        charCount: stream.replace(/[\r\n\0]/g, '').length,
        paragraphCount: (stream.match(/\r/g) || []).length,
      };
    } catch (e) {
      return null;
    }
  }

  // ──────────────────────────────────────────
  // 8. 撤销上一次 AI 注入（自定义撤销栈）
  // ──────────────────────────────────────────
  canUndo() { return this._undoStack.length > 0; }

  undo() {
    if (!this.canUndo()) return false;
    const prev = this._undoStack.pop();
    // Call _replaceEntireDoc directly to avoid pushing to stack again
    return this._replaceEntireDocNoStack(prev);
  }

  // ══════════════════════════════════════════
  // 私有方法
  // ══════════════════════════════════════════

  /**
   * 安全替换整篇文档内容。
   * 流程：disposeUnit(旧) → createUnit(新) — 保证 paragraphs/sectionBreaks 合法。
   */
  _replaceEntireDoc(text) {
    try {
      // Save current state to undo stack before overwriting
      const current = this.getFullText();
      if (current) {
        this._undoStack.push(current);
        if (this._undoStack.length > 30) this._undoStack.shift();
      }

      const univer = window.__univer;
      if (!univer) return false;

      // 销毁当前文档单元
      const currentDoc = this._getDoc();
      if (currentDoc) {
        const id = typeof currentDoc.getId === 'function' ? currentDoc.getId() : null;
        if (id) {
          try { this._api.disposeUnit(id); } catch (_) { /* ignore */ }
        }
      }

      // 创建结构合法的新文档
      univer.createUnit(UniverInstanceType.UNIVER_DOC, {
        id: 'koto-doc-' + Date.now(),
        body: this._buildDocBody(text),
        documentStyle: {
          pageSize: { width: 595.28, height: 841.89 },
          marginTop: 72, marginBottom: 72,
          marginLeft: 90, marginRight: 90,
        },
      });

      return true;
    } catch (e) {
      console.error('[DocController] _replaceEntireDoc 失败:', e);
      return false;
    }
  }

  /** Raw replace without touching undo stack — used by undo() itself */
  _replaceEntireDocNoStack(text) {
    try {
      const univer = window.__univer;
      if (!univer) return false;
      const currentDoc = this._getDoc();
      if (currentDoc) {
        const id = typeof currentDoc.getId === 'function' ? currentDoc.getId() : null;
        if (id) { try { this._api.disposeUnit(id); } catch (_) { /* ignore */ } }
      }
      univer.createUnit(UniverInstanceType.UNIVER_DOC, {
        id: 'koto-doc-' + Date.now(),
        body: this._buildDocBody(text),
        documentStyle: {
          pageSize: { width: 595.28, height: 841.89 },
          marginTop: 72, marginBottom: 72,
          marginLeft: 90, marginRight: 90,
        },
      });
      return true;
    } catch (e) {
      console.error('[DocController] _replaceEntireDocNoStack 失败:', e);
      return false;
    }
  }

  /**
   * 从纯文本构建合法的 Univer 文档 body（dataStream + paragraphs + sectionBreaks）。
   * 规则：每个 \n 翻译为 \r（段落），末尾固定追加 \r\n（最后段落 + 节分隔符）。
   */
  _buildDocBody(text) {
    const normalized = (text || '').replace(/\r\n/g, '\n').replace(/\r/g, '\n');

    if (!normalized) {
      return {
        dataStream: '\r\n',
        textRuns: [],
        paragraphs: [{ startIndex: 0 }],
        sectionBreaks: [{ startIndex: 1 }],
      };
    }

    const lines = normalized.split('\n');
    let dataStream = '';
    const paragraphs = [];

    for (let i = 0; i < lines.length; i++) {
      dataStream += lines[i];
      paragraphs.push({ startIndex: dataStream.length });
      dataStream += '\r';
    }

    const sectionBreaks = [{ startIndex: dataStream.length }];
    dataStream += '\n';

    return { dataStream, textRuns: [], paragraphs, sectionBreaks };
  }

  /** 将 Univer dataStream 还原为纯文本（\r→\n，去掉尾部 \n 节分隔符） */
  _streamToText(dataStream) {
    return (dataStream || '').replace(/\n$/, '').replace(/\r/g, '\n');
  }

  _getDoc() {
    if (!this._api) return null;
    return this._api.getActiveDocument();
  }

  // ──────────────────────────────────────────
  // 用 DOM Range 计算选区起始偏移量（精确定位，避免 indexOf 首次匹配问题）
  // ──────────────────────────────────────────
  _getDomRangeStartOffset(sel) {
    try {
      if (!sel || sel.isCollapsed || sel.rangeCount === 0) return -1;
      const range = sel.getRangeAt(0);
      // Univer 0.5.x 将文档渲染为 DOM 节点，可走读字符数
      const docRoot = document.querySelector(
        '.univer-doc-content, #center-doc > .univer-slide-host, #center-doc .univer-doc-scroll-content'
      );
      if (!docRoot || docRoot.tagName === 'CANVAS') return -1;
      const preRange = document.createRange();
      preRange.selectNodeContents(docRoot);
      preRange.setEnd(range.startContainer, range.startOffset);
      return preRange.toString().length;
    } catch (_) { return -1; }
  }

  // ──────────────────────────────────────────
  // 修改高亮闪烁：显示横幅 + 尝试设置 Univer 选区 + 文字高亮浮层
  // ──────────────────────────────────────────
  _flashChangedRegion(startOffset, endOffset, newText) {
    // ① 尝试通过 Univer Facade 设置选区（视觉蓝色选中高亮）
    setTimeout(() => {
      try {
        const doc = this._getDoc();
        if (doc && typeof doc.setSelection === 'function') {
          doc.setSelection(startOffset, endOffset);
        }
      } catch (_) { /* best-effort */ }
    }, 150);

    // ② 在文档 canvas 容器上叠加一个临时高亮 overlay（黄色脉冲渐淡）
    // Univer 0.5.x 没有原生 text-highlight API，我们在 canvas 上层叠一个
    // position:absolute 的半透明色块，带脉冲动画后淡出消失。
    const canvasEl = document.querySelector('#center-doc canvas');
    const centerDoc = document.getElementById('center-doc');
    if (canvasEl && centerDoc) {
      // Remove old overlay first
      const old = document.getElementById('koto-text-highlight-overlay');
      if (old) old.remove();

      const hlOverlay = document.createElement('div');
      hlOverlay.id = 'koto-text-highlight-overlay';
      centerDoc.appendChild(hlOverlay);

      // Estimate vertical position based on text offset ratio
      const rect = canvasEl.getBoundingClientRect();
      const cRect = centerDoc.getBoundingClientRect();
      const fullLen = this._getFullTextLength();
      const ratio = fullLen > 0 ? Math.min(startOffset / fullLen, 0.9) : 0;
      const estimatedTop = rect.top - cRect.top + ratio * rect.height;
      // Estimate height based on text length (rough: 20px per 80 chars)
      const textLen = Math.max(endOffset - startOffset, (newText || '').length);
      const estimatedH = Math.max(28, Math.min(Math.ceil(textLen / 80) * 22, rect.height * 0.3));

      hlOverlay.style.cssText =
        `position:absolute;pointer-events:none;z-index:500;border-radius:4px;`
        + `background:rgba(255,220,0,0.35);`
        + `top:${Math.max(estimatedTop, rect.top - cRect.top)}px;`
        + `left:${rect.left - cRect.left + 60}px;`
        + `width:${Math.max(rect.width - 120, 100)}px;`
        + `height:${estimatedH}px;`
        + `opacity:1;`
        + `animation: koto-hl-pulse 0.4s ease 2, koto-hl-fade 0.8s ease 2.2s forwards;`;

      clearTimeout(this._hlTimer);
      this._hlTimer = setTimeout(() => {
        if (hlOverlay.parentNode) hlOverlay.remove();
      }, 3500);
    }

    // ③ 在文档区顶部显示横幅提示（显示修改后的文字预览）
    const container = document.getElementById('center-doc');
    if (!container) return;

    let wrap = document.getElementById('koto-change-notice');
    if (!wrap) {
      wrap = document.createElement('div');
      wrap.id = 'koto-change-notice';
      container.appendChild(wrap);
    }
    // 保证绝对定位不被 #center-doc > * { height:100% } 影响
    wrap.style.cssText = 'position:absolute;top:0;left:0;right:0;height:auto;z-index:1000;'
                       + 'display:flex;align-items:center;justify-content:center;pointer-events:none;';

    const preview = (newText || '').replace(/\n/g, ' ').trim();
    const label   = preview.length > 40 ? preview.substring(0, 40) + '…' : preview;

    const banner = document.createElement('div');
    banner.className = 'koto-change-banner';
    banner.style.pointerEvents = 'auto';
    banner.innerHTML =
      `<span class="koto-banner-icon">✅</span>`
      + `<span>已替换选中文字</span>`
      + (label ? `<span class="koto-banner-hl">${this._esc(label)}</span>` : '')
      + `<button class="koto-banner-close" title="关闭">✕</button>`;

    banner.querySelector('.koto-banner-close').addEventListener('click', () => {
      wrap.innerHTML = '';
    });

    wrap.innerHTML = '';
    wrap.appendChild(banner);

    // 3 秒后自动淡出（缩短以配合高亮消失节奏）
    clearTimeout(this._bannerTimer);
    this._bannerTimer = setTimeout(() => {
      banner.classList.add('koto-change-banner-fade');
      setTimeout(() => { wrap.innerHTML = ''; }, 500);
    }, 3000);
  }

  /** Get full text length for offset ratio estimation */
  _getFullTextLength() {
    try {
      const doc = this._getDoc();
      if (!doc) return 0;
      const snapshot = typeof doc.getSnapshot === 'function' ? doc.getSnapshot() : null;
      const dataStream = snapshot?.body?.dataStream || '';
      return this._streamToText(dataStream).length;
    } catch { return 0; }
  }

  /** HTML 转义（用于横幅中显示用户文本） */
  _esc(str) {
    return (str || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }
}
