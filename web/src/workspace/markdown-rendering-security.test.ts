import { afterEach, describe, expect, it } from 'vitest';
import { renderWorkspaceMarkdown, sanitizeRenderedHtml } from './markdown-rendering';

afterEach(() => { delete (window as any).marked; document.body.replaceChildren(); });

describe('untrusted model HTML stays passive', () => {
  it('preserves readable GFM structures and code languages', () => {
    const result = sanitizeRenderedHtml('<h2>标题</h2><table><tr><td colspan="2"><strong>42</strong></td></tr></table><pre><code class="language-python">print(1)</code></pre>');
    const host = document.createElement('div'); host.innerHTML = result;
    expect(host.querySelector('h2')?.textContent).toBe('标题');
    expect(host.querySelector('td')?.getAttribute('colspan')).toBe('2');
    expect(host.querySelector('code')?.className).toBe('language-python');
  });

  it('removes delegated application actions, named properties and styles', () => {
    const html = sanitizeRenderedHtml('<div id="wa-user-input" name="config" class="wa-save-button" style="position:fixed" data-koto-shell-action="new" data-koto-event-click="privileged"><span data-task-artifact-path="private">caption</span></div>');
    const host = document.createElement('div'); host.innerHTML = html;
    document.body.appendChild(host);
    expect(host.textContent).toBe('caption');
    expect(host.querySelector('[id],[name],[class],[style],[data-koto-shell-action],[data-koto-event-click],[data-task-artifact-path]')).toBeNull();
    expect(document.getElementById('wa-user-input')).toBeNull();
  });

  it.each([
    '<svg><a><animate attributeName="href" values="javascript:alert(1)"/></a></svg>',
    '<math><mtext><a href="javascript:alert(1)">bad</a></mtext></math>',
    '<iframe srcdoc="<script>alert(1)</script>"></iframe>',
    '<form action="/api/action"><input name="x"><button>submit</button></form>',
    '<script>alert(1)</script><style>body{display:none}</style>',
  ])('drops active or foreign namespaces: %s', (input) => {
    const html = sanitizeRenderedHtml(input);
    expect(html).not.toMatch(/<(svg|math|iframe|script|style|form|input|button)/i);
  });

  it.each(['javascript:alert(1)', 'java\nscript:alert(1)', 'data:text/html,<script>x</script>', 'vbscript:alert(1)', 'file:///private'])('rejects active links: %s', (href) => {
    const host = document.createElement('div'); host.innerHTML = sanitizeRenderedHtml(`<a href="${href}">link</a>`);
    expect(host.querySelector('a')?.hasAttribute('href')).toBe(false);
  });

  it('prevents automatic remote image requests while keeping an explicit safe link', () => {
    const host = document.createElement('div');
    host.innerHTML = sanitizeRenderedHtml('<img src="https://example.invalid/image.png" alt="远程图片" onerror="alert(1)">');
    expect(host.querySelector('img')).toBeNull();
    expect(host.querySelector('a')?.getAttribute('href')).toBe('https://example.invalid/image.png');
    expect(host.querySelector('a')?.textContent).toBe('远程图片');
    expect(host.querySelector('a')?.rel).toContain('noopener');
  });

  it('allows raster image data and drops SVG data', () => {
    const host = document.createElement('div');
    host.innerHTML = sanitizeRenderedHtml('<img src="data:image/png;base64,AAAA" alt="png"><img src="data:image/svg+xml;base64,AAAA" alt="svg">');
    expect(host.querySelectorAll('img')).toHaveLength(1);
    expect(host.querySelector('img')?.getAttribute('referrerpolicy')).toBe('no-referrer');
  });

  it('sanitizes actual marked output and re-sanitization is stable', () => {
    (window as any).marked = { parse: () => '<p>answer</p><a id="wa-user-input" href="https://example.invalid" target="_blank" onclick="bad()">source</a>' };
    const result = renderWorkspaceMarkdown('model reply');
    expect(result).toContain('answer'); expect(result).not.toContain('onclick'); expect(result).not.toContain('id=');
    expect(sanitizeRenderedHtml(result)).toBe(result);
  });
});
