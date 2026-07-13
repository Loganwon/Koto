import { describe, it, expect } from 'vitest';
import { escHtml, escapeHtml } from './sanitize';

describe('escHtml', () => {
  it('escapes < and >', () => {
    expect(escHtml('<script>')).toBe('&lt;script&gt;');
  });

  it('escapes &', () => {
    expect(escHtml('a & b')).toBe('a &amp; b');
  });

  it('escapes double quotes', () => {
    expect(escHtml('"hello"')).toBe('&quot;hello&quot;');
  });

  it('escapes single quotes', () => {
    expect(escHtml("it's")).toBe('it&#39;s');
  });

  it('handles null/undefined', () => {
    expect(escHtml(null)).toBe('');
    expect(escHtml(undefined)).toBe('');
  });

  it('handles numbers', () => {
    expect(escHtml(42)).toBe('42');
  });

  it('leaves safe text unchanged', () => {
    expect(escHtml('hello world')).toBe('hello world');
  });

  it('escapeHtml is an alias', () => {
    expect(escapeHtml).toBe(escHtml);
  });
});
