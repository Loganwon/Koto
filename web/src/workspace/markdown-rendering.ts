/** Shared, side-effect-free rendering boundary for workspace AI text. */

const PASSIVE_HTML = new Set('p br hr h1 h2 h3 h4 h5 h6 strong b em i del s u blockquote pre code ul ol li table thead tbody tfoot tr th td caption div span a img details summary sub sup kbd samp'.split(' '));
const DROP_HTML = new Set('script style iframe object embed link meta base template noscript form input button textarea select option audio video source track canvas'.split(' '));

function safeUrl(raw: string, image = false): string | null {
  const value = String(raw || '').trim();
  if (!value || /[\u0000-\u001f\u007f]/.test(value)) return null;
  if (image && value.length < 6_000_000 && /^data:image\/(?:png|jpeg|gif|webp|avif);base64,[a-z0-9+/=]+$/i.test(value)) return value;
  try {
    const url = new URL(value, window.location.href);
    if (image) return ['http:', 'https:'].includes(url.protocol) && url.origin === window.location.origin ? value : null;
    return ['http:', 'https:', 'mailto:'].includes(url.protocol) ? value : null;
  } catch (_) { return null; }
}

export function sanitizeRenderedHtml(html: string): string {
  // Copy passive HTML into fresh HTML nodes rather than trusting a blacklist.
  // In particular, model output must never create application event attributes,
  // named DOM properties, SVG animation, forms or custom-element side effects.
  const input = document.createElement('template');
  input.innerHTML = String(html || '');
  const output = document.createElement('div');
  const copy = (source: Node, parent: Node): void => {
    if (source.nodeType === Node.TEXT_NODE) {
      parent.appendChild(document.createTextNode(source.nodeValue || ''));
      return;
    }
    if (source.nodeType !== Node.ELEMENT_NODE) return;
    const element = source as Element;
    const tag = element.localName.toLowerCase();
    if (element.namespaceURI !== 'http://www.w3.org/1999/xhtml' || DROP_HTML.has(tag)) return;
    if (!PASSIVE_HTML.has(tag)) {
      parent.appendChild(document.createTextNode(element.textContent || ''));
      return;
    }
    if (tag === 'img' && !safeUrl(element.getAttribute('src') || '', true)) {
      const alt = element.getAttribute('alt') || '图片';
      const href = safeUrl(element.getAttribute('src') || '');
      if (href) {
        const link = document.createElement('a');
        link.textContent = alt;
        link.setAttribute('href', href);
        link.setAttribute('target', '_blank');
        link.setAttribute('rel', 'noopener noreferrer');
        parent.appendChild(link);
      } else parent.appendChild(document.createTextNode(alt));
      return;
    }
    const target = document.createElement(tag);
    const title = element.getAttribute('title');
    if (title) target.setAttribute('title', title);
    if (tag === 'a') {
      const href = safeUrl(element.getAttribute('href') || '');
      if (href) target.setAttribute('href', href);
      if (element.getAttribute('target') === '_blank') target.setAttribute('target', '_blank');
      target.setAttribute('rel', 'noopener noreferrer');
    }
    if (tag === 'img') {
      target.setAttribute('src', safeUrl(element.getAttribute('src') || '', true)!);
      target.setAttribute('alt', element.getAttribute('alt') || '');
      target.setAttribute('loading', 'lazy');
      target.setAttribute('referrerpolicy', 'no-referrer');
    }
    if (tag === 'code') {
      const language = (element.getAttribute('class') || '').split(/\s+/).filter((name) => /^language-[a-z0-9_-]{1,40}$/i.test(name));
      if (language.length) target.className = language.join(' ');
    }
    if (tag === 'th' || tag === 'td') {
      for (const name of ['colspan', 'rowspan']) {
        const count = Number(element.getAttribute(name));
        if (Number.isInteger(count) && count > 0 && count <= 100) target.setAttribute(name, String(count));
      }
    }
    for (const child of Array.from(element.childNodes)) copy(child, target);
    parent.appendChild(target);
  };
  for (const child of Array.from(input.content.childNodes)) copy(child, output);
  return output.innerHTML;
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
