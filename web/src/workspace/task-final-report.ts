function escapeHtml(value: unknown): string {
  return String(value == null ? '' : value)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

export function previewText(value: string, limit: number): string {
  const text = String(value || '').trim();
  const max = Number(limit) > 0 ? Number(limit) : 0;
  if (!max || text.length <= max) return text;
  return text.slice(0, max) + '...';
}

export function looksLikeFullAnswerText(value: string): boolean {
  const text = String(value || '').trim();
  if (!text) return false;
  if (text.length > 260) return true;
  return /(^|\n)\s*#{1,6}\s|\*\*|```|(^|\n)\s*[-*]\s+\S/u.test(text);
}

export function compactFlowSummary(value: string, fallback = '详细内容见总结与回答。'): string {
  const text = String(value || '').trim();
  if (!text) return fallback;
  if (looksLikeFullAnswerText(text)) return fallback;
  return previewText(text.replace(/\s+/g, ' '), 160);
}

export function terminalTextValue(value: any, depth = 0): string {
  if (typeof value === 'string') return value.trim();
  if (!value || depth > 3) return '';
  if (Array.isArray(value)) {
    return value.map((item) => terminalTextValue(item, depth + 1)).filter(Boolean).join('\n').trim();
  }
  if (typeof value !== 'object') return '';
  const keys = [
    'final_answer', 'finalAnswer', 'answer', 'summary', 'text',
    'content', 'output_text', 'output', 'result', 'message', 'error',
  ];
  for (const key of keys) {
    if (!Object.prototype.hasOwnProperty.call(value, key)) continue;
    const text = terminalTextValue(value[key], depth + 1);
    if (text) return text;
  }
  return '';
}

export function terminalAnswerText(payload: any, fallback = ''): string {
  const data = payload && typeof payload === 'object' ? payload : {};
  const candidates = [
    data.final_answer,
    data.finalAnswer,
    data.answer,
    data.output_text,
    data.output,
    data.result,
    data.summary,
    data.text,
    data.content,
    data.message,
    data.error,
    data.data,
    data.payload,
    fallback,
  ];
  for (const candidate of candidates) {
    const text = terminalTextValue(candidate);
    if (text) return text;
  }
  return '';
}

export function renderTaskFinalReport(value: string): string {
  const text = normalizeTaskFinalReportMarkdown(value);
  if (!text) return '';
  const renderer = (window as any)._waRenderMarkdown;
  if (typeof renderer === 'function' && (window as any).marked) {
    try { return renderer(text); } catch { /* noop */ }
  }
  if ((window as any).marked) {
    try {
      const sanitizer = (window as any)._sanitizeRenderedHtml;
      const html = (window as any).marked.parse(text);
      return typeof sanitizer === 'function' ? sanitizer(html) : html;
    } catch { /* noop */ }
  }
  return renderReadableMarkdownFallback(text);
}

export function normalizeTaskFinalReportMarkdown(value: string): string {
  return String(value || '')
    .trim()
    .replace(/^(?:---|\*\*\*)\s*\n+(?=#{1,6}\s+)/, '')
    .trim();
}

export function renderReadableMarkdownFallback(value: string): string {
  const text = normalizeTaskFinalReportMarkdown(value);
  if (!text) return '';
  const lines = text.split(/\r?\n/);
  const blocks: string[] = [];
  let paragraph: string[] = [];
  let listItems: string[] = [];

  const inline = (source: string): string => escapeHtml(source)
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  const flushParagraph = () => {
    if (!paragraph.length) return;
    blocks.push('<p>' + inline(paragraph.join(' ')) + '</p>');
    paragraph = [];
  };
  const flushList = () => {
    if (!listItems.length) return;
    blocks.push('<ul>' + listItems.map((item) => '<li>' + inline(item) + '</li>').join('') + '</ul>');
    listItems = [];
  };

  lines.forEach((rawLine, index) => {
    const line = rawLine.trim();
    if (!line || (/^(?:---|\*\*\*)$/.test(line) && index === 0)) {
      flushParagraph();
      flushList();
      return;
    }
    const heading = /^(#{1,4})\s+(.+)$/.exec(line);
    if (heading) {
      flushParagraph();
      flushList();
      const level = Math.min(4, heading[1].length + 1);
      blocks.push('<h' + level + '>' + inline(heading[2]) + '</h' + level + '>');
      return;
    }
    const bullet = /^(?:[-*]|\d+\.)\s+(.+)$/.exec(line);
    if (bullet) {
      flushParagraph();
      listItems.push(bullet[1]);
      return;
    }
    flushList();
    paragraph.push(line);
  });
  flushParagraph();
  flushList();
  return blocks.join('');
}
