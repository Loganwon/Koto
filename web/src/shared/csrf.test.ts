import { describe, it, expect } from 'vitest';
import { getCsrfToken, refreshCsrfToken } from '../shared/csrf';

describe('csrf', () => {
  beforeEach(() => {
    const existing = document.querySelector('meta[name=csrf-token]');
    if (existing) existing.remove();
  });

  it('returns empty when no meta', () => {
    expect(getCsrfToken()).toBe('');
  });

  it('returns token from meta', () => {
    const meta = document.createElement('meta');
    meta.name = 'csrf-token';
    meta.setAttribute('content', 'test-token');
    document.head.appendChild(meta);
    expect(getCsrfToken()).toBe('test-token');
  });

  it('refreshCsrfToken survives fetch failure', async () => {
    const meta = document.createElement('meta');
    meta.name = 'csrf-token';
    meta.setAttribute('content', 'existing');
    document.head.appendChild(meta);
    const token = await refreshCsrfToken();
    expect(token).toBe('existing');
  });

  it('refreshCsrfToken deduplicates concurrent calls', async () => {
    const meta = document.createElement('meta');
    meta.name = 'csrf-token';
    meta.setAttribute('content', 'initial');
    document.head.appendChild(meta);
    const [a, b] = await Promise.all([refreshCsrfToken(), refreshCsrfToken()]);
    expect(a).toBe('initial');
    expect(b).toBe('initial');
  });
});
