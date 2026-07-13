import { afterEach, describe, expect, it } from 'vitest';
import { getWorkspaceApi, getWorkspaceApiMethod, publishWorkspaceApi } from './workspace-api';

afterEach(() => {
  delete (window as any).WA;
});

describe('workspace API compatibility boundary', () => {
  it('preserves an early compatibility queue while publishing bundle methods', () => {
    (window as any).WA = { _pendingSendBrowserFilesToAI: ['draft.docx'] };
    const send = () => 'sent';

    const api = publishWorkspaceApi({ send });

    expect(api._pendingSendBrowserFilesToAI).toEqual(['draft.docx']);
    expect(getWorkspaceApiMethod<() => string>('send')).toBe(send);
  });

  it('repairs an invalid global without exposing a second API object', () => {
    (window as any).WA = 'stale bridge';

    const api = getWorkspaceApi();

    expect(api).toEqual({});
    expect((window as any).WA).toBe(api);
  });
});
