// ══════════════════════════════════════════════════════════════
// DocxViewer.js — Word 高保真 DOCX 只读渲染器 v2
//
// 使用 docx-preview (window.docx) 直接解析 OOXML，完整保留：
//   字体大小/颜色/高亮、段落间距、行间距、表格列宽、
//   有序列表多级样式、页眉/页脚、分页符、文本框。
//
// 依赖：window.docx / window.JSZip（首次打开 DOCX 时按本地静态资源优先加载）
// ══════════════════════════════════════════════════════════════

let _docxRuntimePromise = null;


function _injectScript(src, label, isReady) {
  return new Promise((resolve, reject) => {
    if (isReady()) {
      resolve();
      return;
    }

    const script = document.createElement('script');
    script.src = src;
    script.crossOrigin = 'anonymous';
    script.dataset.kotoRuntimeLib = label;
    script.onload = () => {
      if (isReady()) {
        resolve();
      } else {
        reject(new Error(`${label} 已加载，但运行时对象不可用`));
      }
    };
    script.onerror = () => reject(new Error(`${label} 加载失败: ${src}`));
    document.head.appendChild(script);
  });
}


async function _loadWithFallback(primarySrc, fallbackSrc, label, isReady) {
  if (isReady()) return;
  try {
    await _injectScript(primarySrc, label, isReady);
  } catch (primaryError) {
    console.warn(`[${label}] 本地加载失败，切换至 CDN`, primaryError);
    await _injectScript(fallbackSrc, label, isReady);
  }
}


async function ensureDocxRuntimeLoaded() {
  if (window.JSZip && window.docx && typeof window.docx.renderAsync === 'function') {
    return;
  }

  if (!_docxRuntimePromise) {
    _docxRuntimePromise = (async () => {
      await _loadWithFallback(
        '/static/jszip.min.js',
        'https://cdn.jsdelivr.net/npm/jszip@3/dist/jszip.min.js',
        'jszip',
        () => !!window.JSZip
      );

      await _loadWithFallback(
        '/static/docx-preview.min.js',
        'https://cdn.jsdelivr.net/npm/docx-preview@latest/dist/docx-preview.min.js',
        'docx-preview',
        () => !!(window.docx && typeof window.docx.renderAsync === 'function')
      );
    })().catch((error) => {
      _docxRuntimePromise = null;
      throw error;
    });
  }

  await _docxRuntimePromise;
}

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

    try {
      await ensureDocxRuntimeLoaded();
    } catch (err) {
      console.error('[DocxViewer] runtime load error:', err);
      this._renderArea.innerHTML =
        `<div class="docx-error">⚠ 无法加载 docx-preview 运行库：${this._esc(err.message)}</div>`;
      return;
    }

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
          experimental: true,
        }
      );

      const pages = this._renderArea.querySelectorAll('section.docx');
      const pageEl = this._host.querySelector('#docx-status-page');
      if (pageEl) pageEl.textContent = `共 ${pages.length || 1} 页`;

      this._updateStats();
      // Auto-fit width on first render, then fix wrapNone anchored images
      requestAnimationFrame(() => {
        this.fitWidth();
        this._fixWrapNoneImages();
      });

      // 只读视图中，所有超链接/书签锚点不应接收焦点（click-to-focus 会触发 scrollIntoView
      // 干扰拖选定位，英文文档尤其明显，因为英文超链接密度更高）。
      // tabindex="-1" 保留元素可响应 mousedown 和拖选，但不再因 click 聚焦。
      this._renderArea.querySelectorAll('a').forEach(a => a.setAttribute('tabindex', '-1'));

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

  /** 设置缩放级别（50-200）*/
  setZoom(pct) {
    const slider = this._host && this._host.querySelector('.docx-zoom-slider');
    if (slider) slider.dispatchEvent(Object.assign(new Event('input'), { _pct: pct }));
    // Direct path: call _applyZoom if already built
    if (this._applyZoom) this._applyZoom(pct);
  }

  /** 自动缩放：按滚动区域宽度适配页面宽度 */
  fitWidth() {
    if (!this._renderArea || !this._host) return;
    const scrollArea = this._host.querySelector('.docx-scroll-area');
    if (!scrollArea) return;
    const availW = scrollArea.clientWidth - 48;
    // Measure the first page's natural width via getBoundingClientRect (accounts for current zoom)
    const firstPage = this._renderArea.querySelector('section.docx');
    if (!firstPage) return;
    const naturalW = firstPage.getBoundingClientRect().width / (this._zoom / 100);
    if (naturalW <= 0 || naturalW > 5000) return;
    const pct = Math.round(Math.min(150, Math.max(50, (availW / naturalW) * 100)));
    if (this._applyZoom) this._applyZoom(pct);
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
   * Show a lightweight live text preview while the agent is still processing.
   * This favors immediacy over full DOCX fidelity.
   */
  setLiveText(text, options = {}) {
    if (!this._renderArea) return false;

    const append = !!options.append;
    const label = options.label || 'AI 实时预览';
    const normalized = String(text || '').replace(/\r\n/g, '\n').trim();

    this.show();

    if (!append) {
      this._renderArea.innerHTML = '';

      const banner = document.createElement('div');
      banner.textContent = label;
      banner.style.cssText = [
        'margin:0 0 12px 0',
        'padding:8px 12px',
        'border-radius:10px',
        'background:#eef4ff',
        'color:#24458a',
        'font-size:12px',
        'font-weight:600',
      ].join(';');
      this._renderArea.appendChild(banner);
    }

    if (!normalized) {
      this._updateStats();
      return true;
    }

    const block = document.createElement('div');
    block.className = 'docx-live-preview';

    normalized.split(/\n{2,}/).forEach((paragraph) => {
      const p = document.createElement('p');
      p.textContent = paragraph;
      p.style.whiteSpace = 'pre-wrap';
      block.appendChild(p);
    });

    this._renderArea.appendChild(block);

    const pageEl = this._host.querySelector('#docx-status-page');
    if (pageEl) pageEl.textContent = label;

    this._updateStats();

    const scrollArea = this._host.querySelector('.docx-scroll-area');
    if (scrollArea) scrollArea.scrollTop = append ? scrollArea.scrollHeight : 0;

    return true;
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

  /**
   * 修复 docx-preview 对 wrapNone（锚定图片）的错误定位。
   *
   * 问题：docx-preview 忽略 relativeFrom 属性，直接把 EMU→pt 偏移量作为
   * CSS `left` 施加在 position:relative、width:0、height:0 的包装 div 上。
   * 当锚定段落在表格单元格内时，relative 相对的是单元格流排版位置，
   * 与页面绝对坐标不一致，图片被裁剪或渲染在错误位置。
   *
   * 修复：通过 getBoundingClientRect 获取包装 div 的视口真实位置，
   * 将元素重挂载到 section（页面容器），改为 position:absolute，
   * 使用 section-relative 坐标精确定位。此操作不影响 docx-preview
   * 内部异步 Promise 给 img.src 赋值的过程。
   */
  _fixWrapNoneImages() {
    if (!this._renderArea) return;

    // Current zoom factor from CSS zoom on _renderArea
    const zoom = (this._zoom || 100) / 100;

    this._renderArea.querySelectorAll('section.docx').forEach(section => {
      const secBox = section.getBoundingClientRect();

      // docx-preview wrapNone drawing wrapper:
      //   display:block; position:relative; width:0px; height:0px; left:Xpt; top:Ypt
      // Collect before mutating the DOM
      const wrapDivs = Array.from(section.querySelectorAll('div[style]')).filter(div => {
        const s = div.style;
        return s.position === 'relative'
            && s.width    === '0px'
            && s.height   === '0px'
            && s.display  === 'block'

            && div.querySelector('img');
      });

      wrapDivs.forEach(div => {
        // getBoundingClientRect is in viewport px (includes CSS transform scaling)
        // Divide by zoom to recover unscaled CSS-space position relative to section
        const divBox = div.getBoundingClientRect();
        const cssLeft = (divBox.left - secBox.left) / zoom;
        const cssTop  = (divBox.top  - secBox.top)  / zoom;

        const img = div.querySelector('img');
        const w = img ? (img.style.width  || '') : '';
        const h = img ? (img.style.height || '') : '';

        // Reparent into section so position:absolute resolves against the page box
        section.appendChild(div);

        div.style.position = 'absolute';
        div.style.left     = cssLeft + 'px';
        div.style.top      = cssTop  + 'px';
        div.style.width    = w;
        div.style.height   = h;
      });
    });
  }

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
    this._zoom = 100;

    // ── Fix B: 防止跨表格单元格向上拖选时 scrollTop 瞬间归零 ──
    // 浏览器对跨 <td> 向上拖选会调用 scrollIntoView(anchor cell) 导致跳顶；
    // 用 isDragging 标记 + lastScrollTop 快照，发现非预期归零时立即恢复。
    const scrollArea = this._host.querySelector('.docx-scroll-area');
    this._isDragging = false;
    this._lastScrollTop = 0;

    const applyZoom = (pct) => {
      this._zoom = Math.max(50, Math.min(200, pct));
      slider.value = this._zoom;
      zoomLabel.textContent = this._zoom + '%';
      // CSS zoom causes proper layout reflow (text rewraps, scroll adjusts)
      this._renderArea.style.zoom = this._zoom / 100;
    };
    this._applyZoom = applyZoom;

    slider.addEventListener('input', () => applyZoom(parseInt(slider.value, 10)));

    // Ctrl+Wheel zoom
    scrollArea.addEventListener('wheel', (e) => {
      if (!e.ctrlKey && !e.metaKey) return;
      e.preventDefault();
      const delta = e.deltaY > 0 ? -10 : 10;
      applyZoom(this._zoom + delta);
    }, { passive: false });

    // ── Fix A: 拦截锚点导航（只读模式，docx-preview 渲染的 <a href="#"> / <a href="#bookmark"> 不应触发页面跳转）──
    // 只拦截 click（导航发生在 click），不拦截 mousedown —— mousedown 上 preventDefault 会
    // 阻止从锚点元素发起的拖选，导致选区无法建立。
    this._renderArea.addEventListener('click', (e) => {
      if (e.target.closest('a[href]')) { e.preventDefault(); e.stopPropagation(); }
    }, true);

    this._renderArea.addEventListener('mousedown', () => {
      this._isDragging = true;
      this._lastScrollTop = scrollArea.scrollTop;
    });
    document.addEventListener('mouseup', () => { this._isDragging = false; }, true);

    // 拖选期间若有元素获得焦点（focusin），浏览器会立即调用 scrollIntoView 把该元素
    // 滚入视口，造成选区「跳位」。在 focusin 捕获阶段保存当前 scrollTop，
    // 下一帧（scrollIntoView 已执行完毕）立即恢复。
    this._renderArea.addEventListener('focusin', () => {
      if (!this._isDragging) return;
      const saved = scrollArea.scrollTop;
      requestAnimationFrame(() => {
        if (this._isDragging) scrollArea.scrollTop = saved;
      });
    }, true);

    scrollArea.addEventListener('scroll', () => {
      const cur = scrollArea.scrollTop;
      if (this._isDragging) {
        const jump = Math.abs(cur - this._lastScrollTop);
        // 拖选过程中发生 >200px 的瞬间跳转 → 极可能是 scrollIntoView（锚点/表格单元格）
        // 触发的异常跳转，立即恢复。正常的拖选自动滚动是渐进式的（< 60px/event）。
        if (jump > 200) {
          scrollArea.scrollTop = this._lastScrollTop;
          return; // 不更新 _lastScrollTop，保持参考位置不变
        }
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
