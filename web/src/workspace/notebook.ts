/**
 * Notebook-side utilities for the unified workspace shell.
 */

type NotebookFile = {
  name?: string;
  path?: string;
  file?: string;
  title?: string;
  type?: string;
  ext?: string;
  content?: string;
  text?: string;
  summary?: string;
  snippet?: string;
};

type NotebookToolsOptions = {
  $?: (id: string) => HTMLElement | null;
  getFiles?: () => NotebookFile[];
  escHtml?: (value: any) => string;
  sanitizeRenderedHtml?: (html: string) => string;
  fileIcon?: (name: string) => string;
  showToast?: (message: string, kind?: 'success' | 'error' | 'info' | 'warning', duration?: number) => void;
};

const DEFAULT_OPTIONS: Required<Pick<NotebookToolsOptions, '$' | 'getFiles' | 'escHtml' | 'sanitizeRenderedHtml' | 'fileIcon'>> = {
  $: (id: string) => document.getElementById(id),
  getFiles: () => [],
  escHtml: (value: any) => String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;'),
  sanitizeRenderedHtml: (html: string) => html,
  fileIcon: () => '',
};

let _options: NotebookToolsOptions = {};

function _opt<K extends keyof NotebookToolsOptions>(key: K): NonNullable<NotebookToolsOptions[K]> {
  return (_options[key] || (DEFAULT_OPTIONS as any)[key]) as NonNullable<NotebookToolsOptions[K]>;
}

function _el<T extends HTMLElement = HTMLElement>(id: string): T | null {
  return _opt('$')(id) as T | null;
}

function _setVisible(el: HTMLElement | null, visible: boolean): void {
  if (!el) return;
  el.style.display = visible ? '' : 'none';
  el.toggleAttribute('hidden', !visible);
}

function _fileLabel(file: NotebookFile): string {
  return String(file.name || file.title || file.file || file.path || '未命名文档').trim();
}

function _fileText(file: NotebookFile): string {
  return [
    file.name,
    file.title,
    file.path,
    file.file,
    file.type,
    file.ext,
    file.summary,
    file.snippet,
    file.text,
    file.content,
  ].filter(Boolean).join('\n');
}

function _renderSearchRows(files: NotebookFile[], query: string): string {
  const escHtml = _opt('escHtml');
  const fileIcon = _opt('fileIcon');
  const normalized = query.trim().toLowerCase();
  const matches = files
    .filter((file) => _fileText(file).toLowerCase().includes(normalized))
    .slice(0, 20);

  if (!matches.length) {
    return `<div class="wa-source-search-empty">未找到匹配的已附加文档</div>`;
  }

  return matches.map((file, idx) => {
    const label = _fileLabel(file);
    const meta = String(file.path || file.file || file.type || file.ext || '').trim();
    const preview = String(file.summary || file.snippet || file.text || file.content || '').replace(/\s+/g, ' ').trim().slice(0, 160);
    return `
      <button type="button" class="wa-source-search-item" data-source-idx="${idx}">
        <span class="wa-source-search-icon">${fileIcon(label)}</span>
        <span class="wa-source-search-main">
          <span class="wa-source-search-title">${escHtml(label)}</span>
          ${meta ? `<span class="wa-source-search-meta">${escHtml(meta)}</span>` : ''}
          ${preview ? `<span class="wa-source-search-preview">${escHtml(preview)}</span>` : ''}
        </span>
      </button>`;
  }).join('');
}

export function closeSourcePreview(): void {
  _setVisible(_el('wa-source-preview'), false);
  const body = _el('wa-source-preview-body');
  if (body) body.innerHTML = '';
}

export function closeAudioModal(): void {
  _setVisible(_el('wa-audio-modal'), false);
}

export function closeNotebookGuide(): void {
  _setVisible(_el('wa-notebook-guide'), false);
  closeSourcePreview();
}

export function doSourceSearch(value: string = ''): void {
  const query = String(value || '');
  const clearBtn = _el('wa-source-clear-btn');
  const results = _el('wa-source-search-results');
  if (clearBtn) clearBtn.style.display = query.trim() ? '' : 'none';
  if (!results) return;

  if (!query.trim()) {
    results.innerHTML = '';
    _setVisible(results, false);
    return;
  }

  const html = _renderSearchRows(_opt('getFiles')() || [], query);
  results.innerHTML = _opt('sanitizeRenderedHtml')(html);
  _setVisible(results, true);
}

export function clearSourceSearch(): void {
  const input = _el<HTMLInputElement>('wa-source-search-input');
  if (input) input.value = '';
  doSourceSearch('');
  if (input && typeof input.focus === 'function') input.focus();
}

export function installWorkspaceNotebookTools(options: NotebookToolsOptions = {}): void {
  _options = Object.assign({}, _options, options || {});
  const WA = (window as any).WA || ((window as any).WA = {});
  WA.closeSourcePreview = closeSourcePreview;
  WA.closeAudioModal = closeAudioModal;
  WA.closeNotebookGuide = closeNotebookGuide;
  WA.doSourceSearch = doSourceSearch;
  WA.clearSourceSearch = clearSourceSearch;
}

const WA = (window as any).WA || ((window as any).WA = {});
WA.installWorkspaceNotebookTools = installWorkspaceNotebookTools;
installWorkspaceNotebookTools();
