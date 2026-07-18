import { describe, expect, it } from 'vitest';
import {
  appendWorkspaceChatEvents,
  chatStreamLockedModel,
  directChatRouteContract,
  parseWorkspaceSseEvents,
} from './task-direct-chat';

describe('workspace direct chat stream', () => {
  it('keeps an incomplete SSE frame for the next chunk', () => {
    const parsed = parseWorkspaceSseEvents(
      'data: {"type":"token","content":"你"}\n\ndata: {"type":"token"',
      false,
    );

    expect(parsed.events).toEqual([{ type: 'token', content: '你' }]);
    expect(parsed.remainder).toBe('data: {"type":"token"');
  });

  it('flushes a final frame without a trailing separator', () => {
    expect(parseWorkspaceSseEvents(
      'data: {"type":"token","content":"好"}',
      true,
    ).events).toEqual([{ type: 'token', content: '好' }]);
  });

  it('propagates an error from the terminal SSE frame', () => {
    expect(() => appendWorkspaceChatEvents('已有内容', [
      { type: 'error', message: '模型连接失败' },
    ])).toThrow('模型连接失败');
  });

  it('maps each direct route to the correct backend lock', () => {
    expect(directChatRouteContract({ route: 'system_action' })).toMatchObject({
      lockedTask: 'SYSTEM',
      taskKind: 'system_action',
    });
    expect(directChatRouteContract({ route: 'web_search' })).toMatchObject({
      lockedTask: 'WEB_SEARCH',
      taskKind: 'web_search',
    });
    expect(directChatRouteContract({ route: 'light_chat' })).toMatchObject({
      lockedTask: 'CHAT',
      taskKind: 'message',
    });
  });

  it('keeps local mode locked and falls back to the cloud alias', () => {
    expect(chatStreamLockedModel('local', 'deepseek-chat')).toBe('local');
    expect(chatStreamLockedModel('deepseek', 'deepseek-chat')).toBe('deepseek-chat');
    expect(chatStreamLockedModel('deepseek', '')).toBe('cloud');
  });
});
