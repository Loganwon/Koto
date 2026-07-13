/**
 * Notebook-side utilities for the unified workspace shell.
 */

import { _csrfFetch } from './infrastructure';

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
  getSessionId?: () => string | null;
  escHtml?: (value: any) => string;
  sanitizeRenderedHtml?: (html: string) => string;
  fileIcon?: (name: string) => string;
  showToast?: (message: string, kind?: 'success' | 'error' | 'info' | 'warning', duration?: number) => void;
};

const DEFAULT_OPTIONS: Required<Pick<NotebookToolsOptions, '$' | 'getFiles' | 'getSessionId' | 'escHtml' | 'sanitizeRenderedHtml' | 'fileIcon'>> = {
  $: (id: string) => document.getElementById(id),
  getFiles: () => [],
  getSessionId: () => null,
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

function _artifactFiles(files: NotebookFile[]): Array<{ name: string; content: string }> {
  return files.map((file) => ({
    name: _fileLabel(file),
    content: String(file.content || file.text || file.summary || file.snippet || '').trim(),
  })).filter((file) => file.content);
}

function _renderTextBlock(value: any): string {
  const html = _opt('escHtml')(String(value || '')).replace(/\n/g, '<br>');
  return _opt('sanitizeRenderedHtml')(html);
}

async function notebookPost(url: string, files: NotebookFile[] = _opt('getFiles')(), extra: Record<string, any> = {}): Promise<Response> {
  const payload = Object.assign({ files: _artifactFiles(files) }, extra || {});
  const response = await _csrfFetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    let message = `请求失败 (${response.status})`;
    try {
      const data = await response.json();
      message = String(data?.error || data?.message || message);
    } catch (_) {
      try { message = (await response.text()).trim() || message; } catch (e) { console.warn("[Koto]", e) }
    }
    throw new Error(message);
  }
  return response;
}

async function _readNotebookEvents(response: Response, onEvent: (event: any) => void): Promise<void> {
  const reader = response.body?.getReader();
  if (!reader) {
    const text = await response.text();
    text.split(/\n\n+/).forEach((block) => {
      const line = block.split(/\n/).find((item) => item.startsWith('data:'));
      if (!line) return;
      let event: any = null;
      try { event = JSON.parse(line.slice(5).trim()); } catch (_) { return; }
      onEvent(event);
    });
    return;
  }

  const decoder = new TextDecoder();
  let buffer = '';
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split(/\n\n/);
    buffer = parts.pop() || '';
    for (const part of parts) {
      const line = part.split(/\n/).find((item) => item.startsWith('data:'));
      if (!line) continue;
      let event: any = null;
      try { event = JSON.parse(line.slice(5).trim()); } catch (_) { continue; }
      onEvent(event);
    }
  }
}

function _requireArtifactFiles(): NotebookFile[] {
  const files = _opt('getFiles')() || [];
  if (_artifactFiles(files).length) return files;
  _options.showToast?.('请先附加包含文本内容的文件', 'info');
  throw new Error('缺少可生成内容的文件');
}

export async function openNotebookGuide(): Promise<void> {
  const panel = _el('wa-notebook-guide');
  const body = _el('wa-notebook-body');
  _setVisible(panel, true);
  if (body) body.innerHTML = '<div class="wa-audio-loading"><span class="wa-spinner"></span> 正在生成学习包…</div>';

  try {
    const response = await notebookPost('/api/v1/workspace/notebook_guide', _requireArtifactFiles());
    const sections: string[] = [];
    await _readNotebookEvents(response, (event) => {
      if (event?.section === 'done') return;
      if (event?.section === 'error') throw new Error(String(event.content || '学习包生成失败'));
      const title = _opt('escHtml')(event?.label || event?.section || '学习包');
      sections.push(`<section class="wa-notebook-section"><h4>${title}</h4><div>${_renderTextBlock(event?.content)}</div></section>`);
      if (body) body.innerHTML = _opt('sanitizeRenderedHtml')(sections.join(''));
    });
  } catch (error: any) {
    if (body) body.innerHTML = `<div class="wa-source-search-empty">${_opt('escHtml')(error?.message || '学习包生成失败')}</div>`;
    _options.showToast?.(error?.message || '学习包生成失败', 'error');
  }
}

export async function openAudioOverview(): Promise<void> {
  const modal = _el('wa-audio-modal');
  const body = _el('wa-audio-modal-body');
  _setVisible(modal, true);
  if (body) body.innerHTML = '<div class="wa-audio-loading"><span class="wa-spinner"></span> 正在生成脚本…</div>';

  try {
    const sessionId = _opt('getSessionId')() || undefined;
    const response = await notebookPost('/api/v1/workspace/audio_overview', _requireArtifactFiles(), { session_id: sessionId });
    let scriptHtml = '';
    let audioHtml = '';
    await _readNotebookEvents(response, (event) => {
      if (event?.event === 'error') throw new Error(String(event.data || '有声概览生成失败'));
      if (event?.event === 'script' && Array.isArray(event.data)) {
        scriptHtml = event.data.map((line: any) => {
          const speaker = _opt('escHtml')(line?.speaker || 'Host');
          return `<p><strong>${speaker}</strong>：${_renderTextBlock(line?.text)}</p>`;
        }).join('');
      }
      if (event?.event === 'audio_url' && event.data) {
        const url = _opt('escHtml')(event.data);
        audioHtml = `<audio controls src="${url}" style="width:100%"></audio>`;
      }
      if (body) body.innerHTML = _opt('sanitizeRenderedHtml')(`${audioHtml}<div class="wa-audio-script">${scriptHtml || '<div class="wa-audio-loading"><span class="wa-spinner"></span> 正在生成脚本…</div>'}</div>`);
    });
  } catch (error: any) {
    if (body) body.innerHTML = `<div class="wa-source-search-empty">${_opt('escHtml')(error?.message || '有声概览生成失败')}</div>`;
    _options.showToast?.(error?.message || '有声概览生成失败', 'error');
  }
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
  WA.openNotebookGuide = openNotebookGuide;
  WA.openAudioOverview = openAudioOverview;
  WA.doSourceSearch = doSourceSearch;
  WA.clearSourceSearch = clearSourceSearch;
}

const WA = (window as any).WA || ((window as any).WA = {});
WA.installWorkspaceNotebookTools = installWorkspaceNotebookTools;
installWorkspaceNotebookTools();
