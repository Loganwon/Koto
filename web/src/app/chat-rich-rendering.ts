// @ts-nocheck
/**
 * Koto Chat UI Module — chat interface, messages, input, streaming, markdown
 */

import { getFeatureRegistry } from '../shared/feature-registry';
// ── Source rendering ──
export function renderSourcesPanel(sources: any[]): string {
  if (!Array.isArray(sources) || sources.length === 0) return '';
  const items = sources.slice(0, 8).map((source, idx) => {
    const rawUrl = String(source.url || '').trim();
    const safeUrl = /^https?:\/\//i.test(rawUrl) ? rawUrl : '#';
    return `<a class="message-source-item" href="${safeUrl}" target="_blank"><span class="message-source-index">[${idx + 1}]</span><span class="message-source-title">${escapeHtml(String(source.title || `来源 ${idx + 1}`))}</span></a>`;
  }).join('');
  return `<div class="message-sources"><div class="message-sources-title">📚 参考来源</div><div class="message-sources-list">${items}</div></div>`;
}

export function appendSourcesToBody(bodyEl: HTMLElement, sources: any[]): void {
  if (!bodyEl) return;
  const oldPanel = bodyEl.querySelector('.message-sources');
  if (oldPanel) oldPanel.remove();
  if (!Array.isArray(sources) || sources.length === 0) return;
  bodyEl.insertAdjacentHTML('beforeend', renderSourcesPanel(sources));
}

// ── Escape HTML ──
export function escapeHtml(str: string): string {
  return String(str || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// ── Markdown ──
export function parseMarkdown(text: string): string {
  if (!text) return '';
  try {
    if (typeof getFeatureRegistry().marked === 'undefined') {
      return `<div class="markdown-fallback" style="white-space: pre-wrap;">${escapeHtml(text)}</div>`;
    }
    const marked = (window as any).marked;
    const renderer = new marked.Renderer();
    renderer.table = function(header: string, body: string): string {
      const tableId = 'table-' + Math.random().toString(36).slice(2, 10);
      return `<div class="table-wrapper" id="${tableId}"><div class="table-header"><span class="table-label">📊 表格</span><button class="copy-table-btn" data-koto-action="copy-table" data-table-id="${tableId}" title="复制表格"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg><span>复制</span></button></div><div class="table-scroll"><table><thead>${header}</thead><tbody>${body}</tbody></table></div></div>`;
    };
    renderer.code = function(code: string, language: string): string {
      try {
        if (language === 'mermaid') {
          const mermaidId = 'mermaid-' + Math.random().toString(36).slice(2, 10);
          return `<div class="mermaid-wrapper"><div class="mermaid" id="${mermaidId}">${escapeHtml(code)}</div></div>`;
        }
        if (typeof getFeatureRegistry().hljs === 'undefined') return `<pre><code>${escapeHtml(code)}</code></pre>`;
        const hljs = (window as any).hljs;
        const validLang = language && hljs.getLanguage(language) ? language : '';
        const highlighted = validLang ? hljs.highlight(code, { language: validLang }).value : hljs.highlightAuto(code).value;
        const encodedCode = btoa(unescape(encodeURIComponent(code)));
        const lineCount = (code.match(/\n/g) || []).length + 1;
        const artifactBtn = lineCount > 5 ? `<button class="open-artifact-btn" data-code="${encodedCode}" data-lang="${validLang || 'plaintext'}" data-koto-action="open-artifact" title="在侧面板中打开"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="9" y1="3" x2="9" y2="21"/></svg><span>Artifact</span></button>` : '';
        return `<div class="code-block-wrapper"><div class="code-header"><span class="code-lang">${validLang || 'code'}</span><div style="display:flex;align-items:center;gap:4px;">${artifactBtn}<button class="copy-btn" data-code="${encodedCode}" data-koto-action="copy-code" title="复制代码"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg><span>复制</span></button></div></div><pre data-lang="${validLang}"><code class="hljs language-${validLang || 'plaintext'}">${highlighted}</code></pre></div>`;
      } catch { return `<pre><code>${code}</code></pre>`; }
    };
    renderer.link = function(href: string, title: string | null, text: string): string {
      if (href && (href.startsWith('http://') || href.startsWith('https://'))) {
        return `<a href="${href}" data-ext="1"${title ? ` title="${title}"` : ''} class="ext-link">${text}</a>`;
      }
      return `<a href="${href || '#'}">${text}</a>`;
    };
    marked.setOptions({ renderer, breaks: true, gfm: true });
    let html = marked.parse(text);
    html = renderKaTeX(html);
    return html;
  } catch (e) { return String(text); }
}

function renderKaTeX(html: string): string {
  if (typeof getFeatureRegistry().katex === 'undefined') return html;
  const katex = (window as any).katex;
  try {
    html = html.replace(/\$\$([\s\S]+?)\$\$/g, (_match: string, tex: string) => {
      try { return katex.renderToString(tex.trim(), { displayMode: true, throwOnError: false }); } catch { return _match; }
    });
    html = html.replace(/(?<!\$)\$(?!\$)([^\n$]+?)\$(?!\$)/g, (_match: string, tex: string) => {
      try { return katex.renderToString(tex.trim(), { displayMode: false, throwOnError: false }); } catch { return _match; }
    });
  } catch (e) { /* ignore */ }
  return html;
}

let _mermaidLoaded = false;
let _mermaidLoading: Promise<void> | null = null;

function _ensureMermaid(): Promise<void> {
  if (typeof (window as any).mermaid !== 'undefined') return Promise.resolve();
  if (_mermaidLoading) return _mermaidLoading;
  _mermaidLoading = new Promise<void>((resolve) => {
    const script = document.createElement('script');
    script.src = '/static/vendor/mermaid/10.9.0/mermaid.min.js';
    script.onload = () => { _mermaidLoaded = true; resolve(); };
    script.onerror = () => resolve();
    document.head.appendChild(script);
  });
  return _mermaidLoading;
}

export async function renderMermaidBlocks(): Promise<void> {
  await _ensureMermaid();
  if (typeof getFeatureRegistry().mermaid === 'undefined') return;
  const mermaid = (window as any).mermaid;
  try {
    const blocks = document.querySelectorAll('.mermaid');
    for (const block of Array.from(blocks)) {
      if ((block as HTMLElement).dataset.rendered === 'true') continue;
      try {
        const id = block.id;
        const code = (block as HTMLElement).textContent || '';
        const { svg } = await mermaid.render('mermaid-svg-' + id, code);
        block.innerHTML = svg;
        (block as HTMLElement).dataset.rendered = 'true';
      } catch (e) { /* ignore individual failures */ }
    }
  } catch (e) { /* ignore */ }
}

export function highlightCode(): void {
  if (typeof getFeatureRegistry().hljs === 'undefined') return;
  document.querySelectorAll('pre code').forEach((block: Element) => {
    if (!block.classList.contains('hljs')) {
      try { (window as any).hljs.highlightElement(block as HTMLElement); } catch (e) { /* ignore */ }
    }
  });
}
