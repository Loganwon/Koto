/**
 * Lazy editor loader ? dynamically imports editor modules on demand.
 * Reduces initial bundle size by ~40% since editors are only loaded
 * when a file of the corresponding type is opened.
 */

import { KotoTextEditor } from '../editors/text-editor';
import { _setupDocOutline } from '../editors/docx-outline';
import { _loadScript } from './cdn-loaders';

// These are loaded eagerly since they're needed for most workflows
export { KotoTextEditor, _setupDocOutline };

type EditorModule = any;

const _lazyCache: Record<string, EditorModule> = {};
const _lazyLoadPromises: Record<string, Promise<EditorModule> | undefined> = {};

function _editorAssetUrl(bundleName: string): string {
  const configured = (window as any).__kotoWorkspaceEditorAssets;
  return String(configured && configured[bundleName] || `/static/js/build/${bundleName}.js`);
}

async function _lazyLoad(name: string, bundleName: string, globalName: string): Promise<EditorModule> {
  if (_lazyCache[name]) return _lazyCache[name];
  if (_lazyLoadPromises[name]) return _lazyLoadPromises[name]!;
  const loadPromise = _loadScript(_editorAssetUrl(bundleName), 60000).then(() => {
    const mod = (window as any)[globalName];
    if (!mod || typeof mod !== 'object') throw new Error(`${bundleName} 加载后未注册 ${globalName}`);
    _lazyCache[name] = mod;
    return mod;
  }).finally(() => {
    delete _lazyLoadPromises[name];
  });
  _lazyLoadPromises[name] = loadPromise;
  return loadPromise;
}

/** Load the PPTX editor (heavy: slide rendering engine). */
export async function loadPptxEditor(): Promise<EditorModule> {
  return _lazyLoad('pptx', 'pptx-editor-bundle', 'KotoPptxEditorModule');
}

/** Load the PDF viewer (medium: PDF.js wrapper). */
export async function loadPdfViewer(): Promise<EditorModule> {
  return _lazyLoad('pdf', 'pdf-viewer-bundle', 'KotoPdfViewerModule');
}

/** Load the XLSX editor (heavy: Univer Sheets engine). */
export async function loadXlsxEditor(): Promise<EditorModule> {
  return _lazyLoad('xlsx', 'xlsx-editor-bundle', 'KotoXlsxEditorModule');
}

/** Load the image viewer (medium: pan/zoom canvas). */
export async function loadImageViewer(): Promise<EditorModule> {
  return _lazyLoad('image', 'image-viewer-bundle', 'KotoImageViewerModule');
}
