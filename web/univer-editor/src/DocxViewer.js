// ══════════════════════════════════════════════════════════════
// DocxViewer.js — Word 高保真 DOCX 只读渲染器 v2
//
// 使用 docx-preview (window.docx) 直接解析 OOXML，完整保留：
//   字体大小/颜色/高亮、段落间距、行间距、表格列宽、
//   有序列表多级样式、页眉/页脚、分页符、文本框。
//
// 依赖：window.docx（由 index.html CDN 脚本提供）
// ══════════════════════════════════════════════════════════════

export class DocxViewer {
  /**
   * @param {string} centerId   中央编辑区容器的 DOM id（如 'center-doc'）
   */
  constructor(centerId) {
    this._center = document.getElementById(centerId);
    this._host = null;        // #docx-view-host
    this._renderArea = null;  // .docx-render-area  (docx-preview renders here)
    this._styleSlot = null;   // <style> element docx-preview writes into
    this._titleEl = null;     // .docx-topbar-name
    this._active = false;
    this._docMeta = null;

    this._buildDOM();
  }

  // ─────────────────────────────────────────────────────────
  // 公共 API
  // ─────────────────────────────────────────────────────────

  /**
   * 设置文档元信息（页面尺寸/页边距/默认字体）。
   */
  setMeta(meta) {
    this._docMeta = meta || null;
    this._applyMeta();
  }

  /**
   * 从 ArrayBuffer 渲染 .docx 文档（通过 docx-preview）。
   * @param {ArrayBuffer} arrayBuffer  原始 DOCX 二进制
   * @param {string}      filename     文档名称（显示在标题栏）
   */
  async render(arrayBuffer, filename) {
    this._setTitle(filename || '文档');
    this._renderArea.innerHTML = '<div class="docx-loading">正在渲染文档…</div>';
    this.show();

    const lib = window.docx;
    if (!lib || typeof lib.renderAsync !== 'function') {
      this._renderArea.innerHTML =
        '<div class="docx-error">⚠ 无法加载 docx-preview 库（需要网络连接或将其部署到本地）</div>';
      return;
    }

    try {
      this._renderArea.innerHTML = '';

      await lib.renderAsync(
        arrayBuffer,
        this._renderArea,
        this._styleSlot,
        {
          className: 'docx',
          inWrapper: false,
          ignoreWidth: false,
          ignoreHeight: false,
          ignoreFonts: false,
          breakPages: true,
          useBase64URL: true,
          renderHeaders: true,
          renderFooters: true,
          renderFootnotes: true,
          renderEndnotes: true,
          experimental: false,
        }
      );

      const pages = this._renderArea.querySelectorAll('section.docx');
      const pageEl = this._host.querySelector('#docx-status-page');
      if (pageEl) pageEl.textContent = `共 ${pages.length || 1} 页`;

      this._updateStats();

    } catch (err) {
      console.error('[DocxViewer] render error:', err);
      this._renderArea.innerHTML =
        `<div class="docx-error">⚠ 渲染失败：${this._esc(err.message)}</div>`;
    }

    const scrollArea = this._host.querySelector('.docx-scroll-area');
    if (scrollArea) scrollArea.scrollTop = 0;
  }

  /** 显示查看器，隐藏 Univer 全部 UI */
  show() {
    if (this._active) return;
    this._active = true;
    this._host.style.display = 'flex';
    const univerContainer = document.getElementById('univer-container');
    if (univerContainer) univerContainer.style.display = 'none';
    const ft = window.__koto && window.__koto.floatingToolbar;
    if (ft && ft._toolbar) ft._toolbar.classList.add('hidden');
  }

  /** 隐藏查看器，恢复 Univer Canvas */
  hide() {
    if (!this._active) return;
    this._active = false;
    this._host.style.display = 'none';
    const univerContainer = document.getElementById('univer-container');
    if (univerContainer) univerContainer.style.display = '';
  }

  /** 是否当前处于 DOCX 查看模式 */
  isActive() {
    return this._active;
  }

  /**
   * 将图片追加到文档末尾（供拖戏功能使用）。
   * 在渲染区域尾部插入一个居中显示的图片块。
   * @param {string} dataUrl  图片 data URL 或 HTTP URL
   * @param {string} altText  alt 文本
   */
  appendImage(dataUrl, altText) {
    if (!this._renderArea) return;
    const wrapper = document.createElement('p');
    wrapper.style.cssText = 'text-align:center;margin:16px 0;';
    const img = document.createElement('img');
    img.src = dataUrl;
    img.alt = altText || '图表';
    img.style.cssText = 'max-width:90%;border-radius:4px;box-shadow:0 2px 8px rgba(0,0,0,0.15);';
    wrapper.appendChild(img);
    this._renderArea.appendChild(wrapper);
    // Scroll to new image
    const scrollArea = this._host && this._host.querySelector('.docx-scroll-area');
    if (scrollArea) scrollArea.scrollTop = scrollArea.scrollHeight;
  }

  /** 提取渲染区域的纯文本（供 FloatingToolbar 计算选区偏移量） */
  getFullText() {
    if (!this._renderArea) return '';
    return this._renderArea.textContent || '';
  }

  /**
   * 在渲染后的 DOCX DOM 中查找并替换第一处匹配文本。
   * 通过 TreeWalker 遍历文本节点，保留原有样式（加粗/斜体等）。
   * @param {string} original  要替换的原文
   * @param {string} newText   替换后的新文本
   * @returns {boolean} 成功替换返回 true，未找到原文返回 false
   */
  replaceText(original, newText) {
    if (!original || !this._renderArea) return false;

    const walker = document.createTreeWalker(this._renderArea, NodeFilter.SHOW_TEXT);
    const nodes = [];
    let fullText = '';
    let n;
    while ((n = walker.nextNode())) {
      nodes.push({ node: n, start: fullText.length });
      fullText += n.nodeValue;
    }

    const idx = fullText.indexOf(original);
    if (idx < 0) return false;

    const end = idx + original.length;
    let replaced = false;

    for (const { node, start } of nodes) {
      const len = node.nodeValue.length;
      const nodeEnd = start + len;
      if (nodeEnd <= idx || start >= end) continue;

      const localStart = Math.max(0, idx - start);
      const localEnd   = Math.min(len, end - start);
      const text = node.nodeValue;

      if (!replaced) {
        // First overlapping node: inject replacement here
        node.nodeValue = text.slice(0, localStart) + newText + text.slice(localEnd);
        replaced = true;
      } else {
        // Subsequent nodes: erase the overlapping portion
        node.nodeValue = text.slice(localEnd);
      }
    }

    return replaced;
  }

  // ─────────────────────────────────────────────────────────
  // 私有方法
  // ─────────────────────────────────────────────────────────

  _buildDOM() {
    this._styleSlot = document.createElement('style');
    this._styleSlot.id = 'docx-preview-styles';
    document.head.appendChild(this._styleSlot);

    this._host = document.createElement('div');
    this._host.id = 'docx-view-host';
    this._host.style.display = 'none';
    this._host.innerHTML = `
      <div class="docx-topbar">
        <div class="docx-topbar-icon">W</div>
        <div class="docx-topbar-name">文档</div>
        <div class="docx-topbar-badge">只读预览</div>
      </div>
      <div class="docx-ribbon">
        <span class="docx-ribbon-tab active">开始</span>
        <span class="docx-ribbon-tab">插入</span>
        <span class="docx-ribbon-tab">设计</span>
        <span class="docx-ribbon-tab">布局</span>
        <span class="docx-ribbon-tab">引用</span>
        <span class="docx-ribbon-tab">视图</span>
        <div class="docx-ribbon-spacer"></div>
      </div>
      <div class="docx-scroll-area">
        <div class="docx-render-area" id="docx-render-area"></div>
      </div>
      <div class="docx-statusbar">
        <span id="docx-status-page">第 1 页</span>
        <span class="docx-status-sep">|</span>
        <span id="docx-status-words">0 个字</span>
        <div style="flex:1"></div>
        <span class="docx-zoom-label">100%</span>
        <input type="range" class="docx-zoom-slider" min="50" max="200" value="100" />
      </div>
    `;

    this._center.appendChild(this._host);
    this._renderArea = this._host.querySelector('#docx-render-area');
    this._titleEl = this._host.querySelector('.docx-topbar-name');

    const slider = this._host.querySelector('.docx-zoom-slider');
    const zoomLabel = this._host.querySelector('.docx-zoom-label');
    slider.addEventListener('input', () => {
      const pct = parseInt(slider.value, 10);
      zoomLabel.textContent = pct + '%';
      this._renderArea.style.transform = `scale(${pct / 100})`;
      this._renderArea.style.transformOrigin = 'top center';
    });

    // ── Fix A: 拦截锚点导航（只读模式，docx-preview 渲染的 <a href="#"> / <a href="#bookmark"> 不应触发页面跳转）──
    // 使用 capture 阶段确保在原生导航前处理，同时阻止 focus-triggered scrollIntoView
    const _blockAnchor = (e) => {
      const link = e.target.closest('a[href]');
      if (link) { e.preventDefault(); e.stopPropagation(); }
    };
    this._renderArea.addEventListener('click',     _blockAnchor, true);
    this._renderArea.addEventListener('mousedown', _blockAnchor, true);

    // ── Fix B: 防止跨表格单元格向上拖选时 scrollTop 瞬间归零 ──
    // 浏览器对跨 <td> 向上拖选会调用 scrollIntoView(anchor cell) 导致跳顶；
    // 用 isDragging 标记 + lastScrollTop 快照，发现非预期归零时立即恢复。
    const scrollArea = this._host.querySelector('.docx-scroll-area');
    this._isDragging = false;
    this._lastScrollTop = 0;

    this._renderArea.addEventListener('mousedown', () => {
      this._isDragging = true;
      this._lastScrollTop = scrollArea.scrollTop;
    });
    document.addEventListener('mouseup', () => { this._isDragging = false; }, true);

    scrollArea.addEventListener('scroll', () => {
      const cur = scrollArea.scrollTop;
      if (this._isDragging && cur === 0 && this._lastScrollTop > 150) {
        // 瞬间归零且之前已滚动超过 150px → 异常跳顶，立即恢复
        scrollArea.scrollTop = this._lastScrollTop;
        return;
      }
      this._lastScrollTop = cur;
    });
  }

  _applyMeta() {
    if (!this._docMeta) return;
    const m = this._docMeta;
    if (m.pageWidth) {
      const px = Math.round(m.pageWidth * (96 / 72));
      this._renderArea.style.minWidth = px + 'px';
    }
    if (m.defaultFont) {
      this._renderArea.style.fontFamily =
        `"${m.defaultFont}", "等线", "Microsoft YaHei", "PingFang SC", sans-serif`;
    }
  }

  _setTitle(name) {
    if (this._titleEl) this._titleEl.textContent = name;
  }

  _updateStats() {
    const text = this._renderArea.textContent || '';
    const wEl = this._host.querySelector('#docx-status-words');
    if (wEl) wEl.textContent = `${text.replace(/\s/g, '').length} 个字`;
  }

  _esc(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }
}
