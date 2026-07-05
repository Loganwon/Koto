import { _escHtml } from './infrastructure';

import { previewText } from './task-final-report';


function basename(path: string): string {
  const text = String(path || '').trim();
  if (!text) return '';
  const parts = text.split(/[\\/]+/).filter(Boolean);
  return parts.length ? parts[parts.length - 1] : text;
}

function firstContextText(source: Record<string, any>, keys: string[]): string {
  if (!source || typeof source !== 'object') return '';
  for (const key of keys) {
    if (!Object.prototype.hasOwnProperty.call(source, key)) continue;
    const value = source[key];
    if (typeof value === 'string') {
      const text = value.trim();
      if (text) return text;
    }
  }
  return '';
}

function readableResultItem(value: any): string {
  if (value == null) return '';
  if (typeof value === 'string') return basename(value) || value;
  if (typeof value !== 'object') return String(value);
  const raw = value.name || value.title || value.path || value.file || value.file_path || value.target_path || value.id || '';
  return basename(String(raw || '').trim()) || String(raw || '').trim();
}

export function taskContextSummaryText(context: any): string {
  const data = context && typeof context === 'object' ? context : {};
  const lines: string[] = [];
  const file = firstContextText(data, ['active_file', 'activeFile', 'file_name', 'fileName', 'file', 'path']);
  const range = firstContextText(data, ['rangeA1', 'range', 'selection_range', 'selectedRange']);
  const selection = firstContextText(data, ['selection', 'selected_text', 'selectedText', 'text']);
  if (file) lines.push('文件: ' + previewText(basename(file) || file, 80));
  if (range) lines.push('范围: ' + previewText(range, 80));
  if (selection) lines.push('选中内容: ' + previewText(selection.replace(/\s+/g, ' '), 140));
  const files = Array.isArray(data.files) ? data.files : (Array.isArray(data.attachments) ? data.attachments : []);
  const names = files.map((item: any) => readableResultItem(item)).filter(Boolean).slice(0, 3);
  if (names.length) lines.push('附件: ' + names.join('、') + (files.length > names.length ? ' 等' : ''));
  if (!lines.length) {
    const keys = Object.keys(data).filter((key) => data[key] != null && data[key] !== '').slice(0, 4);
    if (keys.length) lines.push('上下文字段: ' + keys.join('、'));
  }
  return lines.join('\n');
}

export function renderTaskInteractionLine(label: string, text: string): string {
  const value = String(text || '').trim();
  if (!value) return '';
  return '<div class="wa-task-interaction-line"><span>' + _escHtml(label) + '</span><p>' + _escHtml(value).replace(/\n/g, '<br>') + '</p></div>';
}

export function renderTaskUnderstandingCard(card: { dataset?: Record<string, any> } | null): string {
  const request = String(card && card.dataset && card.dataset.taskRequest || '').trim();
  const context = String(card && card.dataset && card.dataset.taskContextSummary || '').trim();
  if (!request && !context) return '';
  const rows = [
    renderTaskInteractionLine('我理解的任务', request ? previewText(request.replace(/\s+/g, ' '), 180) : '按当前上下文继续处理文件任务。'),
    renderTaskInteractionLine('使用的上下文', context),
  ].filter(Boolean).join('');
  if (!rows) return '';
  return '<div class="wa-task-interaction-card" data-role="task-understanding"><div class="wa-task-interaction-title">任务理解</div>' + rows + '</div>';
}

export function renderTaskMemoryCard(card: { dataset?: Record<string, any> } | null): string {
  const memory = String(card && card.dataset && card.dataset.taskMemorySummary || '').trim();
  if (!memory) return '';
  return '<div class="wa-task-interaction-card wa-task-memory-card" data-role="task-memory-summary"><div class="wa-task-interaction-title">已写入任务记忆</div>'
    + renderTaskInteractionLine('记忆摘要', previewText(memory.replace(/\s+/g, ' '), 260))
    + '</div>';
}
