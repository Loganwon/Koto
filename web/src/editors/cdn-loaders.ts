/**
 * Runtime loaders for editing libraries (TipTap, Univer Sheets, PDF.js).
 * Workspace editor dependency loaders.
 */

import { publishWorkspaceApi } from '../shared/workspace-api';

declare global {
  var KotoDocxEditorLib: any;
  var KotoSheetsAPI: any;
  var pdfjsLib: any;
}

const _libsLoaded: Record<string, boolean> = { tiptap: false, sheets: false, pdfjs: false };
const _libLoadPromises: Record<string, Promise<void> | null> = { tiptap: null, sheets: null, pdfjs: null };
const _scriptLoadPromises = new Map<string, Promise<void>>();
const _assetCacheBust = String(Date.now());

export function _ensureWorkbookDefaults(wb: any): any {
  if (!wb || typeof wb !== 'object') return wb;
  return Object.assign({ appVersion: '0.5.0', locale: 'zh-CN', styles: {}, resources: [] }, wb);
}

export function _injectCSS(href: string) {
  const hrefBase = href.split('?')[0];
  if (document.querySelector(`link[href^="${hrefBase}"]`)) return;
  const l = document.createElement('link');
  l.rel = 'stylesheet';
  l.href = href;
  document.head.appendChild(l);
}

export function _loadScript(src: string, timeout: number = 20000): Promise<void> {
  const srcBase = src.split('?')[0];
  const inFlight = _scriptLoadPromises.get(srcBase);
  if (inFlight) return inFlight;

  const existingScripts = Array.from(
    document.querySelectorAll<HTMLScriptElement>('script[data-koto-loader-src]')
  ).filter((script) => script.dataset.kotoLoaderSrc === srcBase);
  if (existingScripts.some((script) => script.dataset.kotoLoaderState === 'loaded')) {
    return Promise.resolve();
  }
  // A failed/timed-out script tag is not a loaded dependency. Leaving it in
  // the DOM previously made every future attempt resolve immediately, even
  // though the library global had never appeared.
  existingScripts.forEach((script) => script.remove());

  const pending = new Promise<void>((resolve, reject) => {
    const s = document.createElement('script');
    s.src = src;
    s.dataset.kotoLoaderSrc = srcBase;
    s.dataset.kotoLoaderState = 'loading';
    let settled = false;
    let timer: number | null = null;

    const clearPendingTimer = () => {
      if (timer !== null) window.clearTimeout(timer);
      timer = null;
    };
    const fail = (message: string) => {
      if (settled) return;
      settled = true;
      clearPendingTimer();
      s.onload = null;
      s.onerror = null;
      s.dataset.kotoLoaderState = 'failed';
      s.remove();
      reject(new Error(message));
    };

    timer = window.setTimeout(() => {
      fail(`CDN 加载超时(${src.split('/').pop()})`);
    }, timeout);
    s.onload = () => {
      if (settled) return;
      settled = true;
      clearPendingTimer();
      s.onload = null;
      s.onerror = null;
      s.dataset.kotoLoaderState = 'loaded';
      resolve();
    };
    s.onerror = () => fail(`CDN 加载失败(${src.split('/').pop()})`);
    document.head.appendChild(s);
  });

  const tracked = pending.finally(() => _scriptLoadPromises.delete(srcBase));
  _scriptLoadPromises.set(srcBase, tracked);
  return tracked;
}

export function _waitForRuntimeGlobal(check: () => boolean, label: string, timeout: number = 5000): Promise<void> {
  return new Promise((resolve, reject) => {
    const deadline = Date.now() + timeout;
    const tick = () => {
      try {
        if (check()) {
          resolve();
          return;
        }
      } catch (e) { console.warn("[Koto]", e) }
      if (Date.now() > deadline) {
        reject(new Error(`${label} 加载后未就绪`));
        return;
      }
      setTimeout(tick, 30);
    };
    tick();
  });
}

export async function _ensureTipTap(): Promise<void> {
  if (window.KotoDocxEditorLib && window.KotoDocxEditorLib.KotoTipTapEditor) return;
  if (_libLoadPromises.tiptap) return _libLoadPromises.tiptap;
  _libLoadPromises.tiptap = (async () => {
    await _loadScript('/static/js/tiptap-docx-bundle.js?v=' + _assetCacheBust);
    await _waitForRuntimeGlobal(
      () => window.KotoDocxEditorLib && window.KotoDocxEditorLib.KotoTipTapEditor,
      'DOCX 编辑器'
    );
    _libsLoaded.tiptap = true;
  })().finally(() => { _libLoadPromises.tiptap = null; });
  return _libLoadPromises.tiptap;
}

export async function _ensureUniverSheets(): Promise<void> {
  // Univer registers dependency identifiers globally while evaluating its
  // bundle. Re-evaluating the script produces duplicate-component warnings
  // even if the previous workbook instance was correctly disposed.
  if (window.KotoSheetsAPI) {
    _libsLoaded.sheets = true;
    return;
  }
  if (_libsLoaded.sheets) return;
  if (_libLoadPromises.sheets) return _libLoadPromises.sheets;
  _libLoadPromises.sheets = (async () => {
    _injectCSS('/static/univer-dist/assets/sheets-main.css?v=' + _assetCacheBust);
    await _loadScript('/static/univer-dist/assets/sheets-main.js?v=' + _assetCacheBust, 60000);
    if (!window.KotoSheetsAPI) {
      throw new Error('Univer Sheets 加载失败 — window.KotoSheetsAPI 未定义');
    }
    // '[WA] KotoSheetsAPI 已就绪');
    _libsLoaded.sheets = true;
  })().finally(() => { _libLoadPromises.sheets = null; });
  return _libLoadPromises.sheets;
}

export async function _ensurePdfJS(): Promise<void> {
  if (window.pdfjsLib || _libsLoaded.pdfjs) return;
  if (_libLoadPromises.pdfjs) return _libLoadPromises.pdfjs;
  _libLoadPromises.pdfjs = (async () => {
    // PDF rendering is a packaged capability.  Remote fallbacks make the
    // rendered result and failure mode depend on the user's network, and can
    // silently switch the runtime version after a local resource problem.
    const script = '/static/vendor/pdfjs-dist/3.11.174/build/pdf.min.js';
    const worker = '/static/vendor/pdfjs-dist/3.11.174/build/pdf.worker.min.js';
    await _loadScript(script);
    if (!window.pdfjsLib) {
      throw new Error(`PDF.js 本地运行时未注册：${script}`);
    }
    window.pdfjsLib.GlobalWorkerOptions.workerSrc = worker;
    _libsLoaded.pdfjs = true;
  })().finally(() => { _libLoadPromises.pdfjs = null; });
  return _libLoadPromises.pdfjs;
}

// ── Zoom UI helpers (module-level) ──
function $(id: string): HTMLElement | null { return document.getElementById(id); }

export function _updatePdfZoomUI(pct: number) {
  const label = $('wa-pdf-zoom-label');
  const slider = $('wa-pdf-zoom') as HTMLInputElement | null;
  if (label) label.textContent = pct + '%';
  if (slider) slider.value = String(pct);
}

export function _updateDocxZoomUI(pct: number) {
  const label = $('wa-docx-zoom-label');
  const slider = $('wa-docx-zoom') as HTMLInputElement | null;
  if (label) label.textContent = pct + '%';
  if (slider) slider.value = String(pct);
}

// Cross-bundle compatibility boundary; editor callers should import directly.
publishWorkspaceApi({
  _ensureTipTap,
  _ensureUniverSheets,
  _ensurePdfJS,
  _ensureWorkbookDefaults,
  _updatePdfZoomUI,
  _updateDocxZoomUI,
});

Object.assign(window as any, {
  _updatePdfZoomUI,
  _updateDocxZoomUI,
});
