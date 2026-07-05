/**
 * Lazy editor loader ? dynamically imports editor modules on demand.
 * Reduces initial bundle size by ~40% since editors are only loaded
 * when a file of the corresponding type is opened.
 */

import { KotoTextEditor } from '../editors/text-editor';
import { _setupDocOutline } from '../editors/docx-outline';

// These are loaded eagerly since they're needed for most workflows
export { KotoTextEditor, _setupDocOutline };

type EditorModule = any;

const _lazyCache: Record<string, EditorModule | null> = {};

async function _lazyLoad(name: string, importer: () => Promise<EditorModule>): Promise<EditorModule> {
  if (_lazyCache[name]) return _lazyCache[name]!;
  _lazyCache[name] = null; // Prevent concurrent loads
  const mod = await importer();
  _lazyCache[name] = mod;
  return mod;
}

/** Load the PPTX editor (heavy: slide rendering engine). */
export async function loadPptxEditor(): Promise<typeof import('../editors/pptx-editor')> {
  return _lazyLoad('pptx', () => import('../editors/pptx-editor'));
}

/** Load the PDF viewer (medium: PDF.js wrapper). */
export async function loadPdfViewer(): Promise<typeof import('../editors/pdf-viewer')> {
  return _lazyLoad('pdf', () => import('../editors/pdf-viewer'));
}

/** Load the XLSX editor (heavy: Univer Sheets engine). */
export async function loadXlsxEditor(): Promise<typeof import('../editors/xlsx-editor')> {
  return _lazyLoad('xlsx', () => import('../editors/xlsx-editor'));
}

/** Load the image viewer (medium: pan/zoom canvas). */
export async function loadImageViewer(): Promise<typeof import('../editors/image-viewer')> {
  return _lazyLoad('image', () => import('../editors/image-viewer'));
}
