/**
 * DocxReadView - high-fidelity OOXML DOCX fallback renderer.
 */

import type { WorkspaceEditor } from './types';

declare global {
  interface Window {
    docx: any;
  }
}

function $(id: string): HTMLElement | null { return document.getElementById(id); }

export class DocxReadView implements WorkspaceEditor {
  containerId: string;
  _zoom: number;
  _styleSlot: HTMLStyleElement | null;
  _renderArea: HTMLElement | null;
  _scrollArea: HTMLElement | null;
  _topbar: HTMLElement | null;
  _pageInfo: HTMLElement | null;
  _imgToolbar: HTMLElement | null;
  _selectedImg: HTMLImageElement | null;
  _wheelHandler: ((e: WheelEvent) => void) | null;

  constructor() {
    this.containerId = 'wa-docx-read-view';
    this._zoom = 100;
    this._styleSlot = null;
    this._renderArea = null;
    this._scrollArea = null;
    this._topbar = null;
    this._pageInfo = null;
    this._imgToolbar = null;
    this._selectedImg = null;

    const host = $(this.containerId)!;
    host.innerHTML = '';
    host.classList.add('active');

    this._styleSlot = document.createElement('style');
    this._styleSlot.id = 'wa-drv-docx-styles';
    document.head.appendChild(this._styleSlot);

    this._topbar = document.createElement('div');
    this._topbar.className = 'wa-drv-topbar';
    this._topbar.innerHTML = `
      <button class="wa-drv-edit-btn" title="切换到编辑模式">
        <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor"><path d="M12.1 1.3a1 1 0 0 1 1.4 0l1.2 1.2a1 1 0 0 1 0 1.4l-8.5 8.5-3.1.8a.5.5 0 0 1-.6-.6l.8-3.1 8.8-8.2zm.7 1L4.5 10.6l-.5 1.9 1.9-.5L14.2 3.7l-1.4-1.4z"/></svg>
        编辑
      </button>
      <span class="wa-drv-page-info"></span>
    `;
    host.appendChild(this._topbar);
    this._pageInfo = this._topbar.querySelector('.wa-drv-page-info') as HTMLElement;

    this._topbar.querySelector('.wa-drv-edit-btn')!.addEventListener('click', () => {
      if (typeof (window as any).WA._switchDocxMode === 'function') (window as any).WA._switchDocxMode('edit');
    });

    this._scrollArea = document.createElement('div');
    this._scrollArea.className = 'wa-drv-scroll';
    host.appendChild(this._scrollArea);

    this._renderArea = document.createElement('div');
    this._renderArea.className = 'wa-drv-render';
    this._scrollArea.appendChild(this._renderArea);

    this._imgToolbar = document.createElement('div');
    this._imgToolbar.className = 'wa-drv-img-toolbar';
    this._imgToolbar.innerHTML = `
      <button data-action="describe">描述</button>
      <button data-action="replace">替换</button>
    `;
    host.appendChild(this._imgToolbar);
    this._imgToolbar.addEventListener('click', (e) => {
      const btn = (e.target as HTMLElement).closest('button[data-action]') as HTMLButtonElement | null;
      if (!btn || !this._selectedImg) return;
      const action = btn.dataset.action;
      const src = this._selectedImg.src;
      if (typeof (window as any).WA._sendImageToAI === 'function') {
        (window as any).WA._sendImageToAI(action, src);
      }
      this._hideImgToolbar();
    });

    this._wheelHandler = (e: WheelEvent) => {
      if (!e.ctrlKey && !e.metaKey) return;
      e.preventDefault();
      const delta = e.deltaY > 0 ? -10 : 10;
      this.setZoom(this._zoom + delta);
    };
    host.addEventListener('wheel', this._wheelHandler, { passive: false });

    this._renderArea.addEventListener('click', (e) => {
      const img = (e.target as HTMLElement).closest('img') as HTMLImageElement | null;
      if (img) {
        e.preventDefault();
        this._selectImage(img);
      } else if (!(e.target as HTMLElement).closest('.wa-drv-img-toolbar')) {
        this._hideImgToolbar();
      }
    });

    this._renderArea.addEventListener('click', (e) => {
      const a = (e.target as HTMLElement).closest('a[href]') as HTMLAnchorElement | null;
      if (!a) return;
      const href = a.getAttribute('href') || '';
      if (href.startsWith('#')) {
        e.preventDefault();
        e.stopPropagation();
        const targetId = href.slice(1);
        const target = this._renderArea!.querySelector(`[id="${CSS.escape(targetId)}"], [name="${CSS.escape(targetId)}"]`);
        if (target) {
          target.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
      } else if (href.startsWith('http')) {
        e.preventDefault();
        window.open(href, '_blank', 'noopener');
      } else {
        e.preventDefault();
      }
    }, true);
  }

  async render(rawUrl: string) {
    this._renderArea!.innerHTML = '<div class="wa-drv-loading">正在渲染文档…</div>';

    const lib = window.docx;
    if (!lib || typeof lib.renderAsync !== 'function') {
      this._renderArea!.innerHTML =
        '<div class="wa-drv-loading" style="color:#f87171">docx-preview 库未加载</div>';
      return;
    }

    try {
      const resp = await fetch(rawUrl);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const buf = await resp.arrayBuffer();

      this._renderArea!.innerHTML = '';

      await lib.renderAsync(buf, this._renderArea, this._styleSlot, {
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
      });

      const pages = this._renderArea!.querySelectorAll('section.docx');
      if (this._pageInfo) {
        this._pageInfo.textContent = `共 ${pages.length || 1} 页`;
      }

      requestAnimationFrame(() => this._fixWrapNoneImages());

      this._renderArea!.querySelectorAll('a').forEach(a => a.setAttribute('tabindex', '-1'));

    } catch (err: any) {
      console.error('[DocxReadView] render error:', err);
      this._renderArea!.innerHTML =
        `<div class="wa-drv-loading" style="color:#f87171">渲染失败：${(window as any)._escHtml(String(err.message || err))}</div>`;
    }

    if (this._scrollArea) this._scrollArea.scrollTop = 0;
  }

  setZoom(pct: number) {
    this._zoom = Math.max(50, Math.min(200, pct));
    if (this._renderArea) (this._renderArea.style as any).zoom = this._zoom / 100;
    if (typeof (window as any)._updateDocxZoomUI === 'function') {
      (window as any)._updateDocxZoomUI(this._zoom);
    }
  }

  getContent(): string {
    const sel = window.getSelection();
    if (sel && sel.toString().trim()) {
      return `[当前选中文本]:\n${sel.toString()}\n`;
    }
    return `[文档全文]:\n${this.getFullText()}\n`;
  }

  getFullText(): string {
    if (!this._renderArea) return '';
    return (this._renderArea as HTMLElement).innerText || '';
  }

  serialize(): null {
    return null;
  }

  applyToolCall(_cmd?: any) {}

  destroy() {
    const host = $(this.containerId);
    if (host) {
      if (this._wheelHandler) host.removeEventListener('wheel', this._wheelHandler);
      host.classList.remove('active');
      host.innerHTML = '';
    }
    if (this._styleSlot && this._styleSlot.parentNode) {
      this._styleSlot.parentNode.removeChild(this._styleSlot);
    }
    this._renderArea = null;
    this._scrollArea = null;
    this._topbar = null;
    this._imgToolbar = null;
    this._selectedImg = null;
  }

  _selectImage(img: HTMLImageElement) {
    if (this._selectedImg) this._selectedImg.classList.remove('wa-drv-img-selected');
    this._selectedImg = img;
    img.classList.add('wa-drv-img-selected');

    const imgRect = img.getBoundingClientRect();
    const hostRect = $(this.containerId)!.getBoundingClientRect();
    this._imgToolbar!.style.left = (imgRect.left - hostRect.left + imgRect.width / 2 - 60) + 'px';
    this._imgToolbar!.style.top = (imgRect.top - hostRect.top - 36) + 'px';
    this._imgToolbar!.classList.add('visible');
  }

  _hideImgToolbar() {
    if (this._selectedImg) this._selectedImg.classList.remove('wa-drv-img-selected');
    this._selectedImg = null;
    this._imgToolbar!.classList.remove('visible');
  }

  _fixWrapNoneImages() {
    if (!this._renderArea) return;
    const zoom = this._zoom / 100;

    this._renderArea.querySelectorAll('section.docx').forEach((section: Element) => {
      const secBox = section.getBoundingClientRect();

      const wrapDivs = Array.from(section.querySelectorAll('div[style]')).filter(div => {
        const s = (div as HTMLElement).style;
        return s.position === 'relative'
          && s.width === '0px'
          && s.height === '0px'
          && s.display === 'block'
          && div.querySelector('img');
      });

      wrapDivs.forEach((div: Element) => {
        const divEl = div as HTMLElement;
        const divBox = divEl.getBoundingClientRect();
        const cssLeft = (divBox.left - secBox.left) / zoom;
        const cssTop = (divBox.top - secBox.top) / zoom;

        const img = divEl.querySelector('img') as HTMLImageElement | null;
        const w = img ? (img.style.width || '') : '';
        const h = img ? (img.style.height || '') : '';

        section.appendChild(divEl);
        divEl.style.position = 'absolute';
        divEl.style.left = cssLeft + 'px';
        divEl.style.top = cssTop + 'px';
        divEl.style.width = w;
        divEl.style.height = h;
      });
    });
  }
}

(window as any).DocxReadView = DocxReadView;
