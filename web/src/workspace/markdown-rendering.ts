/** Shared, side-effect-free rendering boundary for workspace AI text. */

export function sanitizeRenderedHtml(html: string): string {
  const template = document.createElement('template');
  template.innerHTML = String(html || '');
  template.content
    .querySelectorAll('script, style, iframe, object, embed, link, meta, base')
    .forEach((node) => node.remove());
  template.content.querySelectorAll('*').forEach((node) => {
    Array.from((node as Element).attributes || []).forEach((attr) => {
      const name = String(attr.name || '').toLowerCase();
      const value = String(attr.value || '').trim().toLowerCase();
      if (name.startsWith('on')) {
        (node as Element).removeAttribute(attr.name);
        return;
      }
      if ((name === 'href' || name === 'src') && value && !/^(https?:|mailto:|\/|#|data:image\/)/i.test(value)) {
        (node as Element).removeAttribute(attr.name);
      }
    });
  });
  return template.innerHTML;
}

export function renderWorkspaceMarkdown(text: string): string {
  if ((window as any).marked) {
    try {
      return sanitizeRenderedHtml((window as any).marked.parse(text || ''));
    } catch (_) { /* fall through to the readable built-in renderer */ }
  }
  const source = String(text || '').trim().replace(/^(?:---|\*\*\*)\s*\n+(?=#{1,6}\s+)/, '').trim();
  return source
    .split(/\r?\n/)
    .map((line) => {
      const trimmed = line.trim();
      const heading = /^(#{1,4})\s+(.+)$/.exec(trimmed);
      const formatInline = (value: string): string => value
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/`([^`]+)`/g, '<code>$1</code>')
        .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
      if (heading) {
        const level = Math.min(4, heading[1].length + 1);
        return '<h' + level + '>' + formatInline(heading[2]) + '</h' + level + '>';
      }
      return formatInline(trimmed);
    })
    .filter(Boolean)
    .join('<br>');
}
