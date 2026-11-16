import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getFeatureRegistry, registerFeatures } from '../shared/feature-registry';

const mocks = vi.hoisted(() => ({
  loadScript: vi.fn(),
}));

vi.mock('../editors/cdn-loaders', () => ({
  _loadScript: mocks.loadScript,
}));

describe('conversation list loader', () => {
  beforeEach(() => {
    vi.resetModules();
    mocks.loadScript.mockReset();
    Object.keys(getFeatureRegistry()).forEach((key) => delete getFeatureRegistry()[key]);
    document.body.innerHTML = `
      <script id="koto-workspace-bundle"></script>
      <div id="wa-ai-session-list-view" hidden></div>
      <div id="wa-ai-chat-view"></div>
      <div id="wa-chat-composer-host"><div id="wa-ai-input-area"></div></div>
      <textarea id="wa-user-input"></textarea>
      <button id="wa-send-btn"></button>
    `;
    document.documentElement.removeAttribute('data-koto-conversation-list');
  });

  it('keeps normal chat and silent refresh on the lightweight bridge', async () => {
    const sendMessage = vi.fn(() => 'sent');
    registerFeatures({ sendMessage });
    const { installConversationListLoader } = await import('./conversation-list-loader');
    installConversationListLoader();

    await expect(getFeatureRegistry().refreshAiSessions({ silent: true })).resolves.toEqual([]);
    expect(getFeatureRegistry().submitUnifiedAiComposer()).toBe('sent');
    expect(sendMessage).toHaveBeenCalledTimes(1);
    expect(mocks.loadScript).not.toHaveBeenCalled();
  });

  it('keeps the send button in sync before the history runtime is loaded', async () => {
    const { installConversationListLoader } = await import('./conversation-list-loader');
    installConversationListLoader();

    const input = document.getElementById('wa-user-input') as HTMLTextAreaElement;
    const sendButton = document.getElementById('wa-send-btn') as HTMLButtonElement;
    expect(sendButton.disabled).toBe(true);

    input.value = '123';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    expect(sendButton.disabled).toBe(false);

    input.value = '   ';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    expect(sendButton.disabled).toBe(true);
    expect(mocks.loadScript).not.toHaveBeenCalled();
  });

  it('loads once and replays the first history request', async () => {
    const show = vi.fn();
    const open = vi.fn(async () => ({ id: 'session-42' }));
    const submit = vi.fn(async () => 'submitted');
    (document.getElementById('koto-workspace-bundle') as HTMLScriptElement).dataset.conversationListBundleUrl = '/assets/conversation-list.v1.js';
    mocks.loadScript.mockImplementation(async () => {
      registerFeatures({
        showAiSessionList: show,
        openAiSession: open,
        submitUnifiedAiComposer: submit,
      });
    });

    const {
      installConversationListLoader,
      loadConversationList,
    } = await import('./conversation-list-loader');
    installConversationListLoader();
    expect(getFeatureRegistry().showAiSessionList()).toBeNull();
    await loadConversationList();
    await Promise.resolve();

    expect(mocks.loadScript).toHaveBeenCalledTimes(1);
    expect(mocks.loadScript).toHaveBeenCalledWith('/assets/conversation-list.v1.js', 60000);
    expect(show).toHaveBeenCalledTimes(1);
    expect(document.documentElement.dataset.kotoConversationList).toBe('ready');
    await expect(getFeatureRegistry().openAiSession('session-42', { force: true }))
      .resolves.toEqual({ id: 'session-42' });
  });
});
