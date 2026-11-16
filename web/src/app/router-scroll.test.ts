import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getFeatureRegistry } from '../shared/feature-registry';
vi.mock('./session-bridge', () => ({
  getCurrentProject: vi.fn(), getProjectOptions: vi.fn(), initProjectSelector: vi.fn(),
  saveProjectOptions: vi.fn(), setCurrentProject: vi.fn(),
}));
import { initScrollBehavior, scrollToBottom, scrollToBottomForce } from './router';

beforeEach(() => {
  document.body.innerHTML = '<div id="wa-ai-messages"></div><div id="chatMessages"></div>';
  getFeatureRegistry().isScrollLocked = false;
  Object.defineProperties(document.getElementById('wa-ai-messages')!, {
    scrollHeight: { configurable: true, value: 1000 },
    clientHeight: { configurable: true, value: 200 },
  });
});

describe('unified conversation scroll bridge', () => {
  it('scrolls the workspace while preserving an explicit reader lock', () => {
    const messages = document.getElementById('wa-ai-messages')!;
    messages.scrollTop = 100;
    getFeatureRegistry().isScrollLocked = true;
    scrollToBottom();
    expect(messages.scrollTop).toBe(100);
    scrollToBottomForce();
    expect(messages.scrollTop).toBe(1000);
    expect(getFeatureRegistry().isScrollLocked).toBe(false);
    expect(document.getElementById('chatMessages')!.scrollTop).toBe(0);
  });

  it('binds one scroll observer per message container and tracks reader position', () => {
    const messages = document.getElementById('wa-ai-messages')!;
    const add = vi.spyOn(messages, 'addEventListener');
    initScrollBehavior();
    initScrollBehavior();
    expect(add).toHaveBeenCalledTimes(1);
    messages.scrollTop = 100;
    messages.dispatchEvent(new Event('scroll'));
    expect(getFeatureRegistry().isScrollLocked).toBe(true);
    messages.scrollTop = 790;
    messages.dispatchEvent(new Event('scroll'));
    expect(getFeatureRegistry().isScrollLocked).toBe(false);
  });
});
