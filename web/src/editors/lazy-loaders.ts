/**
 * Lazy editor loader ? dynamically imports editor modules on demand.
 * Reduces initial bundle size by ~40% since editors are only loaded
 * when a file of the corresponding type is opened.
 */

import { KotoTextEditor } from '../editors/text-editor';
import { _setupDocOutline } from '../editors/docx-outline';
import { getWorkspaceAssetUrl } from '../shared/workspace-assets';
import type { KotoPptxEditor } from './pptx-editor';
import type { KotoPdfViewer } from './pdf-viewer';
import type { XlsxEditor } from './xlsx-editor';
import type { KotoImageViewer } from './image-viewer';

// These are loaded eagerly since they're needed for most workflows
export { KotoTextEditor, _setupDocOutline };

type PptxEditorModule = { KotoPptxEditor: typeof KotoPptxEditor };
type PdfViewerModule = { KotoPdfViewer: typeof KotoPdfViewer };
type XlsxEditorModule = { XlsxEditor: typeof XlsxEditor };
type ImageViewerModule = { KotoImageViewer: typeof KotoImageViewer };
type EditorModule = PptxEditorModule | PdfViewerModule | XlsxEditorModule | ImageViewerModule;

const _lazyCache: Record<string, EditorModule> = {};
const _lazyLoadPromises: Record<string, Promise<EditorModule> | undefined> = {};

async function _lazyLoad(name: string, bundleName: string): Promise<EditorModule> {
  if (_lazyCache[name]) return _lazyCache[name];
  if (_lazyLoadPromises[name]) return _lazyLoadPromises[name]!;
  const loadPromise = import(/* @vite-ignore */ getWorkspaceAssetUrl(bundleName)).then((mod) => {
    if (!mod || typeof mod !== 'object') throw new Error(`${bundleName} 未返回编辑器模块`);
    _lazyCache[name] = mod;
    return mod;
  }).finally(() => {
    delete _lazyLoadPromises[name];
  });
  _lazyLoadPromises[name] = loadPromise;
  return loadPromise;
}

/** Load the PPTX editor (heavy: slide rendering engine). */
export async function loadPptxEditor(): Promise<PptxEditorModule> {
  return _lazyLoad('pptx', 'pptx-editor-bundle') as Promise<PptxEditorModule>;
}

/** Load the PDF viewer (medium: PDF.js wrapper). */
export async function loadPdfViewer(): Promise<PdfViewerModule> {
  return _lazyLoad('pdf', 'pdf-viewer-bundle') as Promise<PdfViewerModule>;
}

/** Load the XLSX editor (heavy: Univer Sheets engine). */
export async function loadXlsxEditor(): Promise<XlsxEditorModule> {
  return _lazyLoad('xlsx', 'xlsx-editor-bundle') as Promise<XlsxEditorModule>;
}

/** Load the image viewer (medium: pan/zoom canvas). */
export async function loadImageViewer(): Promise<ImageViewerModule> {
  return _lazyLoad('image', 'image-viewer-bundle') as Promise<ImageViewerModule>;
}
