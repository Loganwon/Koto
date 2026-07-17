import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('./state', () => ({
  state: {},
  _renderMyWorkspace: vi.fn(),
}));

import { _setStreamBtn } from './ai-review';

describe('workspace stream button state', () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <div id="wa-ai-input-area">
        <textarea id="wa-user-input"></textarea>
        <button id="wa-send-btn"></button>
      </div>`;
  });

  it('keeps the stop action available while streaming and restores empty-input disabling', () => {
    const input = document.getElementById('wa-user-input') as HTMLTextAreaElement;
    const button = document.getElementById('wa-send-btn') as HTMLButtonElement;
    input.value = '';
    button.disabled = true;

    _setStreamBtn(true);
    expect(button.disabled).toBe(false);
    expect(button.classList.contains('is-streaming')).toBe(true);
    expect(button.title).toBe('停止当前任务');

    _setStreamBtn(false);
    expect(button.disabled).toBe(true);
    expect(button.classList.contains('is-streaming')).toBe(false);
    expect(button.title).toBe('发送');
  });

  it('restores an enabled send action when text remains after streaming', () => {
    const input = document.getElementById('wa-user-input') as HTMLTextAreaElement;
    const button = document.getElementById('wa-send-btn') as HTMLButtonElement;
    input.value = '继续处理';

    _setStreamBtn(false);
    expect(button.disabled).toBe(false);
  });
});
