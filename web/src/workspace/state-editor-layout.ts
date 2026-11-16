// @ts-nocheck
/**
 * Global State + Tab Management + Workspace Tree + Recent Files + My/Temp Workspace.
 * Workspace state.
 */

import { _csrfFetch, _fileIcon, _escHtml, _FOLDER_SVG, _FOLDER_OPEN_SVG } from './infrastructure';
import { _clearActiveFileState, _destroyActiveEditorForClosedFile, _removeOpenTabAfterFileDeleted, _renderTabs, _switchToTabImpl } from './state-tab-lifecycle';
// ── Editor Layout Helpers ──

function _editorLayoutContainerId(fileType: string): string | null {
  return fileType === 'xlsx'
    ? 'wa-xlsx-editor'
    : fileType === 'pptx'
      ? 'wa-pptx-editor'
      : fileType === 'pdf'
        ? 'wa-pdf-editor'
        : null;
}

const _WORKSPACE_SURFACE_IDS = [
  'wa-drop-zone',
  'wa-docx-editor',
  'wa-xlsx-editor',
  'wa-pptx-editor',
  'wa-pdf-editor',
  'wa-pdf-viewer',
  'wa-image-viewer',
  'wa-text-editor',
];

function _setSurfaceA11y(el: HTMLElement, isActive: boolean): void {
  el.setAttribute('aria-hidden', isActive ? 'false' : 'true');
  (el as any).inert = !isActive;
  el.toggleAttribute('inert', !isActive);
}

export function _syncWorkspaceSurfaces(): void {
  _WORKSPACE_SURFACE_IDS.forEach((id) => {
    const el = document.getElementById(id) as HTMLElement | null;
    if (!el) return;
    const isDropZone = id === 'wa-drop-zone';
    const isActive = isDropZone ? !el.classList.contains('hidden') : el.classList.contains('active');
    _setSurfaceA11y(el, isActive);
  });
}

export function _primeEditorLayout(fileType: string): void {
  const containerId = _editorLayoutContainerId(fileType);
  if (!containerId) return;
  const el = document.getElementById(containerId);
  if (el) el.classList.add('active');
  if (fileType === 'pdf') {
    document.getElementById('wa-pdf-viewer')?.classList.add('active');
  }
  _syncWorkspaceSurfaces();
}

export function _waitForEditorLayout(fileType: string, timeoutMs: number = 800): Promise<void> {
  const containerId = _editorLayoutContainerId(fileType);
  if (!containerId) return Promise.resolve();
  const isReady = () => {
    const el = document.getElementById(containerId);
    return !!(el && el.offsetWidth > 0 && el.offsetHeight > 0);
  };
  if (isReady()) return Promise.resolve();
  return new Promise((resolve) => {
    const deadline = Date.now() + timeoutMs;
    function check() {
      const el = document.getElementById(containerId!);
      if (el && el.offsetWidth > 0 && el.offsetHeight > 0) {
        resolve();
        return;
      }
      if (Date.now() >= deadline) {
        console.warn(
          '[WA] _waitForEditorLayout timeout for',
          containerId,
          'offsetW:',
          el ? el.offsetWidth : 'null',
          'offsetH:',
          el ? el.offsetHeight : 'null'
        );
        resolve();
        return;
      }
      requestAnimationFrame(check);
    }
    requestAnimationFrame(check);
  });
}
