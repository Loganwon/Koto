/**
 * CDN loaders for editing libraries (TipTap, Univer Sheets, PDF.js)
 * Workspace editor dependency loaders.
 */

declare global {
  var KotoDocxEditorLib: any;
  var KotoSheetsAPI: any;
  var pdfjsLib: any;
}

const _libsLoaded: Record<string, boolean> = { tiptap: false, sheets: false, pdfjs: false };
const _libLoadPromises: Record<string, Promise<void> | null> = { tiptap: null, sheets: null, pdfjs: null };
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
  return new Promise((resolve, reject) => {
    if (document.querySelector(`script[src="${src}"]`)) { resolve(); return; }
    const s = document.createElement('script');
    s.src = src;
    const timer = setTimeout(() => {
      (s as any).onload = (s as any).onerror = null;
      reject(new Error(`CDN 加载超时(${src.split('/').pop()})`));
    }, timeout);
    s.onload = () => { clearTimeout(timer); resolve(); };
    s.onerror = () => { clearTimeout(timer); reject(new Error(`CDN 加载失败(${src.split('/').pop()})`)); };
    document.head.appendChild(s);
  });
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
      } catch (_) {}
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
  if (_libsLoaded.sheets) return;
  if (_libLoadPromises.sheets) return _libLoadPromises.sheets;
  _libLoadPromises.sheets = (async () => {
    _injectCSS('/static/univer-dist/assets/sheets-main.css?v=' + _assetCacheBust);
    await _loadScript('/static/univer-dist/assets/sheets-main.js?v=' + _assetCacheBust, 60000);
    if (!window.KotoSheetsAPI) {
      throw new Error('Univer Sheets 加载失败 — window.KotoSheetsAPI 未定义');
    }
    console.log('[WA] KotoSheetsAPI 已就绪');
    _libsLoaded.sheets = true;
  })().finally(() => { _libLoadPromises.sheets = null; });
  return _libLoadPromises.sheets;
}

export async function _ensurePdfJS(): Promise<void> {
  if (window.pdfjsLib || _libsLoaded.pdfjs) return;
  if (_libLoadPromises.pdfjs) return _libLoadPromises.pdfjs;
  _libLoadPromises.pdfjs = (async () => {
    const candidates = [
      {
        script: '/static/vendor/pdfjs-dist/3.11.174/build/pdf.min.js',
        worker: '/static/vendor/pdfjs-dist/3.11.174/build/pdf.worker.min.js',
      },
      {
        script: 'https://cdn.jsdelivr.net/npm/pdfjs-dist@3.11.174/build/pdf.min.js',
        worker: 'https://cdn.jsdelivr.net/npm/pdfjs-dist@3.11.174/build/pdf.worker.min.js',
      },
      {
        script: 'https://unpkg.com/pdfjs-dist@3.11.174/build/pdf.min.js',
        worker: 'https://unpkg.com/pdfjs-dist@3.11.174/build/pdf.worker.min.js',
      },
    ];
    const errors: string[] = [];

    for (const candidate of candidates) {
      try {
        await _loadScript(candidate.script);
        if (window.pdfjsLib) {
          window.pdfjsLib.GlobalWorkerOptions.workerSrc = candidate.worker;
          _libsLoaded.pdfjs = true;
          return;
        }
        errors.push(`${candidate.script}: pdfjsLib 未注册`);
      } catch (error: any) {
        errors.push(`${candidate.script}: ${error?.message || error}`);
      }
    }
    throw new Error(`PDF.js 加载失败：${errors.join('；')}`);
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

// Backward compat
Object.assign((window as any).WA || ((window as any).WA = {}), {
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
