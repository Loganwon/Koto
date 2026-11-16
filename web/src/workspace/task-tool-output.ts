import { looksLikeFullAnswerText, previewText } from './task-final-report';
import {
  isInternalTaskTool,
  isReadTaskTool,
  shouldAlwaysSuppressTaskToolFinished,
} from './task-step-labels';
import { escHtml as esc } from '../shared/sanitize';

const escAttr = esc;

function basename(path: string): string {
  const text = String(path || '').trim();
  if (!text) return '';
  const parts = text.split(/[\\/]+/).filter(Boolean);
  return parts.length ? parts[parts.length - 1] : text;
}

function tryParseJson(value: string): any {
  const text = String(value || '').trim();
  if (!text || !'[{'.includes(text[0])) return null;
  try { return JSON.parse(text); } catch { return null; }
}

function readableResultItem(value: any): string {
  if (value == null) return '';
  if (typeof value === 'string') return basename(value) || value;
  if (typeof value !== 'object') return String(value);
  const raw = value.name || value.title || value.path || value.file
    || value.file_path || value.target_path || value.id || '';
  return basename(String(raw || '').trim()) || String(raw || '').trim();
}

export function summarizeParsedResult(toolName: string, parsed: any): string {
  if (Array.isArray(parsed)) {
    const names = parsed.map(readableResultItem).filter(Boolean).slice(0, 3);
    const countText = toolName === 'list_workspace_files'
      ? '读取到 ' + parsed.length + ' 个工作区条目'
      : '返回 ' + parsed.length + ' 项结果';
    return names.length ? countText + '：' + names.join('、') : countText;
  }
  if (parsed && typeof parsed === 'object') {
    const summary = parsed.summary || parsed.message || parsed.result_summary
      || parsed.preview || parsed.text || '';
    if (summary) return previewText(String(summary), 160);
    const keys = Object.keys(parsed).slice(0, 4);
    if (keys.length) return '返回结果字段：' + keys.join('、');
  }
  return '';
}

export function toolPreviewSummary(toolName: string, text: string): string {
  const source = String(text || '').trim();
  if (!source) return '';
  const parsed = tryParseJson(source);
  const parsedSummary = summarizeParsedResult(toolName, parsed);
  if (parsedSummary) return parsedSummary;
  const compact = source.replace(/\s+/g, ' ').trim();
  return compact ? previewText(compact, 180) : '';
}

function collapsibleBlock(label: string, content: string): string {
  const text = String(content || '').trim();
  if (!text) return '';
  return '<details class="wa-task-collapse" data-full-content="' + escAttr(text)
    + '"><summary>' + esc(label) + '</summary></details>';
}

function artifactSrc(artifact: Record<string, any>): string {
  if (!artifact || typeof artifact !== 'object') return '';
  const raw = String(artifact.data || artifact.src || artifact.url || '').trim();
  if (!raw) return '';
  if (raw.startsWith('data:') || raw.startsWith('http://')
    || raw.startsWith('https://') || raw.startsWith('/')) return raw;
  const mime = String(artifact.mime_type || 'image/png').trim() || 'image/png';
  return 'data:' + mime + ';base64,' + raw;
}

function artifactHostForRow(row: HTMLElement): HTMLElement {
  const existing = Array.from(row.children).find((child) =>
    child.classList.contains('wa-task-artifacts')
  );
  if (existing instanceof HTMLElement) return existing;
  const host = document.createElement('div');
  host.className = 'wa-task-artifacts';
  return host;
}

export function appendToolArtifacts(row: HTMLElement, payload: Record<string, any>): void {
  const artifacts = Array.isArray(payload.artifacts) ? payload.artifacts : [];
  if (!row || !artifacts.length) return;
  const host = artifactHostForRow(row);
  artifacts.forEach((artifact: Record<string, any>) => {
    if (artifact?.kind && artifact.kind !== 'image') return;
    const src = artifactSrc(artifact);
    if (!src) return;
    const key = String(artifact.path || artifact.name || src.slice(0, 96)).trim();
    let figure = Array.from(host.querySelectorAll<HTMLElement>('.wa-task-artifact'))
      .find((item) => item.dataset.artifactKey === key) || null;
    const label = String(artifact.name || '查看图像');
    if (figure) {
      const img = figure.querySelector<HTMLImageElement>('img');
      const link = figure.querySelector<HTMLAnchorElement>('a');
      if (img) { img.src = src; img.alt = label; }
      if (link) { link.href = src; link.textContent = label; }
      return;
    }
    figure = document.createElement('figure');
    figure.className = 'wa-task-artifact';
    figure.dataset.artifactKey = key;
    const img = document.createElement('img');
    img.className = 'wa-task-artifact-image';
    img.src = src;
    img.alt = label;
    img.loading = 'lazy';
    figure.appendChild(img);
    const caption = document.createElement('figcaption');
    caption.className = 'wa-task-artifact-caption';
    const link = document.createElement('a');
    link.className = 'wa-task-artifact-open';
    link.href = src;
    link.target = '_blank';
    link.rel = 'noopener';
    link.textContent = label;
    caption.appendChild(link);
    figure.appendChild(caption);
    host.appendChild(figure);
  });
  if (host.childNodes.length && !host.isConnected) row.appendChild(host);
}

export function resultPreviewHtml(payload: Record<string, any>): string {
  const preview = String(payload.result_preview || payload.result_text || payload.result || '').trim();
  if (!preview) return '';
  const toolName = payload.tool_name || '';
  if (toolName === 'run_python_code') {
    return collapsibleBlock(payload.blocked ? '查看拦截原因' : '查看执行输出', preview);
  }
  if (toolName === 'provided_file_context' || toolName === 'selection_context') return '';
  if (toolName === 'parse_file_to_text' && payload.success !== false) return '';
  if (looksLikeFullAnswerText(preview)) {
    return '<div class="wa-task-result-text">' + esc('已收到较长内容，详细内容见任务结果。') + '</div>';
  }
  const summary = toolPreviewSummary(toolName, preview);
  if (!summary) return '';
  const full = preview.length > summary.length || tryParseJson(preview);
  return '<div class="wa-task-result-text">' + esc(summary) + '</div>'
    + (full ? collapsibleBlock('查看完整结果', preview) : '');
}

export function shouldSuppressToolStart(payload: Record<string, any>): boolean {
  const name = payload.tool_name || '';
  return isInternalTaskTool(name) || isReadTaskTool(name);
}

export function shouldSuppressToolFinished(payload: Record<string, any>): boolean {
  const name = payload.tool_name || '';
  if (shouldAlwaysSuppressTaskToolFinished(name)) return true;
  if (isInternalTaskTool(name) && payload.success !== false && !payload.blocked) return true;
  return !!payload.skipped;
}
