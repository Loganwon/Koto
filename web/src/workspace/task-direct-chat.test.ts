import { describe, expect, it, vi } from 'vitest';
import {
  appendWorkspaceChatEvents,
  chatStreamLockedModel,
  createWorkspaceChatStreamer,
  directChatRouteContract,
  parseWorkspaceSseEvents,
} from './task-direct-chat';

function streamResponse(frames: string[]): Response {
  const chunks = frames.map((frame) => ({
    done: false,
    value: new TextEncoder().encode(frame),
  }));
  return {
    ok: true,
    status: 200,
    body: {
      getReader: () => ({
        read: vi.fn(async () => chunks.shift() || { done: true, value: undefined }),
      }),
    },
  } as unknown as Response;
}

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
      lockedTask: '',
      taskKind: 'message',
    });
  });

  it('keeps local mode locked and falls back to the cloud alias', () => {
    expect(chatStreamLockedModel('local', 'deepseek-chat')).toBe('local');
    expect(chatStreamLockedModel('deepseek', 'deepseek-chat')).toBe('deepseek-chat');
    expect(chatStreamLockedModel('deepseek', '')).toBe('cloud');
  });

  it('streams every direct route through the canonical chat endpoint', async () => {
    const csrfFetch = vi.fn(async () => streamResponse([
      'data: {"type":"token","content":"执行"}\n\n',
      'data: {"type":"token","content":"完成"}\n\n'
        + 'data: {"type":"done"}\n\n',
    ]));
    const appendAssistantTurn = vi.fn();
    const setStreamButton = vi.fn();
    const state: Record<string, any> = {};
    const loadingEl = document.createElement('div');
    const streamer = createWorkspaceChatStreamer({
      state,
      csrfFetch,
      ensureSessionId: async () => 'workspace-session',
      getModelMode: () => 'deepseek',
      getSelectedCloudModelId: () => 'deepseek-chat',
      setStreamButton,
      buildFileContext: () => ({ file_path: 'report.xlsx', file_type: 'xlsx' }),
      appendAssistantTurn,
    });
    const routeDecision = {
      route_kind: 'direct_response',
      route: 'system_action',
      task_type: 'SYSTEM',
      route_source: 'frontend_deterministic_system',
    };

    const result = await streamer({ text: '打开微信', loadingEl }, routeDecision);

    expect(csrfFetch).toHaveBeenCalledOnce();
    const [url, init] = csrfFetch.mock.calls[0];
    expect(url).toBe('/api/chat/stream');
    const payload = JSON.parse(String(init?.body || '{}'));
    expect(payload).toMatchObject({
      session: 'workspace-session',
      message: '打开微信',
      locked_task: 'SYSTEM',
      locked_model: 'deepseek-chat',
      workspace_route_intent: routeDecision,
      file_context: { file_path: 'report.xlsx', file_type: 'xlsx' },
    });
    expect(payload).not.toHaveProperty('skills_enabled');
    expect(result).toMatchObject({ routeId: 'system_action', assistantText: '执行完成' });
    expect(appendAssistantTurn).toHaveBeenCalledWith('执行完成', expect.objectContaining({
      task_kind: 'system_action',
      status: 'done',
    }));
    expect(setStreamButton.mock.calls).toEqual([[true], [false]]);
    expect(state.isLoading).toBe(false);
    expect(state._streamAbortCtrl).toBeNull();
  });

  it('shows generated text before the model finishes and waits for a real cancel terminal', async () => {
    let controller: ReadableStreamDefaultController<Uint8Array>;
    const body = new ReadableStream<Uint8Array>({ start: (value) => { controller = value; } });
    const encode = (value: any) => new TextEncoder().encode(`data: ${JSON.stringify(value)}\n\n`);
    const fetch = vi.fn(async (url: string) => url.endsWith('/cancel')
      ? { ok: true, status: 202 } as Response
      : { ok: true, body } as Response);
    const state: Record<string, any> = {};
    const append = vi.fn();
    const element = document.createElement('div');
    const stream = createWorkspaceChatStreamer({ state, csrfFetch: fetch,
      getSessionId: () => 's', buildFileContext: () => null, appendAssistantTurn: append });
    let finished = false;
    const running = stream({ text: '解释原理', loadingEl: element }, { route: 'light_chat' }).then((result) => { finished = true; return result; });
    controller!.enqueue(encode({ type: 'message.started', message_id: 'm' }));
    controller!.enqueue(encode({ type: 'message.delta', message_id: 'm', delta: '先生成的内容' }));
    await vi.waitFor(() => expect(element.textContent).toContain('先生成的内容'));
    expect(finished).toBe(false);
    await state._cancelCurrentTask();
    expect(state._streamAbortCtrl.signal.aborted).toBe(false);
    expect(element.textContent).toContain('正在停止');
    expect(append).not.toHaveBeenCalled();
    controller!.enqueue(encode({ type: 'task_final', data: { status: 'cancelled', result: '保留的部分内容' } }));
    controller!.close();
    await running;
    expect(append).toHaveBeenCalledWith('保留的部分内容', expect.objectContaining({ status: 'cancelled' }));
    const request = JSON.parse(String(fetch.mock.calls[0][1]?.body || '{}'));
    expect(request).not.toHaveProperty('locked_task');
  });
});
