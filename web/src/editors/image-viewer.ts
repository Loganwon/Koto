/**
 * KotoImageViewer - simple image viewer with zoom/pan
 */

import type { WorkspaceEditor } from './types';

function $(id: string): HTMLElement | null { return document.getElementById(id); }

export class KotoImageViewer implements WorkspaceEditor {
  containerId: string;
  _scale: number;
  _wheelHandler: ((e: WheelEvent) => void) | null;

  constructor() {
    this.containerId = 'wa-image-viewer';
    this._scale = 1.0;
    const container = $(this.containerId);
    if (container) container.classList.add('active');
    this._wheelHandler = (e: WheelEvent) => {
      if (!e.ctrlKey && !e.metaKey) return;
      e.preventDefault();
      const delta = e.deltaY > 0 ? -0.1 : 0.1;
      this._scale = Math.max(0.1, Math.min(5.0, this._scale + delta));
      const img = $(this.containerId)!.querySelector('img');
      if (img) (img as HTMLElement).style.transform = `scale(${this._scale})`;
    };
    if (container) container.addEventListener('wheel', this._wheelHandler, { passive: false });
  }

  render(rawUrl: string) {
    const c = $(this.containerId);
    if (!c) return;
    this._scale = 1.0;
    c.innerHTML = `<div class="wa-image-wrap"><img src="${rawUrl}" alt="image" draggable="false" /></div>`;
  }

  getContent(): string { return '[图片文件，无文本内容]'; }

  serialize(): null { return null; }

  applyToolCall(_cmd?: any) {}

  destroy() {
    const container = $(this.containerId);
    if (!container) return;
    container.classList.remove('active');
    container.innerHTML = '';
    if (this._wheelHandler) container.removeEventListener('wheel', this._wheelHandler);
  }
}

(window as any).KotoImageViewer = KotoImageViewer;
