import { afterEach, describe, expect, it, vi } from 'vitest';
import { createWorkspaceChatStreamer } from './task-direct-chat';
import { createTaskScrollFollower } from './task-follow-scroll';
import { createTaskChatPresentation } from './task-chat-presentation';
import { applyTaskMessageStreamEvent, createStreamingTextRenderer, createTaskMessageStreamState } from './task-message-stream';

function response(events: any[]): Response {
  const chunks = events.map((event) => new TextEncoder().encode(`data: ${JSON.stringify(event)}\n\n`));
  return { ok: true, status: 200, body: { getReader: () => ({
    read: async () => chunks.length ? { done: false, value: chunks.shift() } : { done: true },
    cancel: vi.fn(async () => {}), releaseLock: vi.fn(),
  }) } } as unknown as Response;
}
function fixture(fetch: (url: string, options?: any) => Promise<Response>) {
  const state: Record<string, any> = {};
  const host = document.createElement('article');
  const append = vi.fn(); const sync = vi.fn();
  const stream = createWorkspaceChatStreamer({ state, csrfFetch: fetch, getSessionId: () => 'session',
    buildFileContext: () => null, appendAssistantTurn: append, syncAssistantTurn: sync });
  return { state, host, append, sync, stream };
}
afterEach(() => { document.body.replaceChildren(); vi.useRealTimers(); });

describe('safe continuation and reading', () => {
  it('reattaches across repeated disconnects by task/run/cursor without repeating POST', async () => {
    let request: any; let reads = 0;
    const event = (seq: number, type: string, payload: any = {}) => ({ seq, type, run_id: request.run_id, payload });
    const fetch = vi.fn(async (url: string, options?: any) => {
      if (url === '/api/chat/stream') {
        request = JSON.parse(options.body);
        return response([event(1, 'run.started'), event(2, 'message.started', { message_id: 'm' }), event(3, 'message.delta', { message_id: 'm', delta: '甲' })]);
      }
      reads += 1;
      return reads === 1 ? response([event(4, 'message.delta', { message_id: 'm', delta: '乙' })])
        : response([event(4, 'message.delta', { message_id: 'm', delta: '乙' }), event(5, 'model.metrics'),
          event(6, 'message.finished', { message_id: 'm', text: '甲乙', status: 'completed' }),
          event(7, 'run.finished', { status: 'success', result: '甲乙' })]);
    });
    const { stream, host, append } = fixture(fetch);
    expect((await stream({ text: 'test', loadingEl: host }, {})).assistantText).toBe('甲乙');
    expect(fetch.mock.calls.filter(([url]) => url === '/api/chat/stream')).toHaveLength(1);
    const resumed = fetch.mock.calls.filter(([url]) => url !== '/api/chat/stream');
    expect(resumed.map(([url]) => new URL(url, 'http://localhost').searchParams.get('after_seq'))).toEqual(['3', '4']);
    expect(resumed.every(([url, options]) => url.includes(`run_id=${request.run_id}`) && options.method === 'GET')).toBe(true);
    expect(append).toHaveBeenCalledOnce();
  });

  it('offers manual continuation and cancellation after retries without duplicating a conversation turn', async () => {
    let request: any; let online = false; let cancel = false;
    const event = (seq: number, type: string, payload: any = {}) => ({ seq, type, run_id: request.run_id, payload });
    const fetch = vi.fn(async (url: string, options?: any) => {
      if (url.endsWith('/cancel')) { cancel = true; return { ok: true, status: 202 } as Response; }
      if (url === '/api/chat/stream') {
        request = JSON.parse(options.body);
        return response([event(1, 'run.started'), event(2, 'message.started', { message_id: 'm' }),
          event(3, 'message.delta', { message_id: 'm', delta: '已有内容' }), event(4, 'file.changed', { path: 'report.docx' })]);
      }
      if (!online) throw new Error('offline');
      return response([event(5, 'run.finished', { status: 'cancelled', result: '已有内容' })]);
    });
    const { stream, host, append, sync } = fixture(fetch);
    await stream({ text: 'test', loadingEl: host }, {});
    const button = host.querySelector<HTMLButtonElement>('[data-role="reconnect-task"]')!;
    expect(button.textContent).toBe('继续查看原任务');
    button.click(); button.click();
    await vi.waitFor(() => expect(button.textContent).toBe('再次查看原任务'), { timeout: 2000 });
    host.querySelector<HTMLButtonElement>('[data-role="cancel-original-task"]')!.click();
    await vi.waitFor(() => expect(cancel).toBe(true));
    expect(host.textContent).not.toContain('已确认停止');
    online = true; button.click();
    await vi.waitFor(() => expect(sync).toHaveBeenCalledOnce());
    expect(sync.mock.calls[0]).toEqual([request.run_id, expect.objectContaining({ status: 'cancelled', task_id: request.task_id })]);
    expect(append).toHaveBeenCalledOnce();
    expect(fetch.mock.calls.filter(([url]) => url === '/api/chat/stream')).toHaveLength(1);
    expect(host.textContent).toContain('已确认停止');
    expect(host.textContent).toContain('成果仍保留');
  });

  it('repairs a sequence gap from its last applied cursor before displaying later text', async () => {
    let request: any;
    const event = (seq: number, type: string, payload = {}) => ({ seq, type, run_id: request.run_id, payload });
    const fetch = vi.fn(async (url: string, options?: any) => {
      if (url === '/api/chat/stream') {
        request = JSON.parse(options.body);
        return response([event(1, 'run.started'), event(2, 'message.started', { message_id: 'm' }),
          event(3, 'message.delta', { message_id: 'm', delta: '甲' }), event(5, 'message.delta', { message_id: 'm', delta: '丙' })]);
      }
      expect(url).toContain('after_seq=3');
      return response([event(4, 'message.delta', { message_id: 'm', delta: '乙' }), event(5, 'message.delta', { message_id: 'm', delta: '丙' }),
        event(6, 'run.finished', { status: 'success', result: '甲乙丙' })]);
    });
    const { stream, host } = fixture(fetch);
    expect((await stream({ text: 'test', loadingEl: host }, {})).assistantText).toBe('甲乙丙');
  });

  it('does not turn an empty failed terminal into completed or discard a validated refusal', async () => {
    const { stream, host, append } = fixture(async () => response([
      { type: 'run.started' }, { type: 'message.finished', payload: { message_id: 'm', text: '验收未通过', status: 'blocked' } },
      { type: 'error', payload: { message: 'validation failed' } }, { type: 'run.finished', payload: { status: 'failed', result: '' } },
    ]));
    await stream({ text: 'test', loadingEl: host }, {});
    expect(append).toHaveBeenCalledWith('验收未通过', expect.objectContaining({ status: 'failed', skip_model_context: true }));
    expect(host.textContent).toContain('任务未完成');
    expect(host.textContent).not.toContain('已完成。');
  });

  it('treats explicit submission rejection as failure rather than a disconnected background run', async () => {
    const fetch = vi.fn(async () => ({ ok: false, status: 400 } as Response));
    const { stream, host, append } = fixture(fetch);
    await stream({ text: 'test', loadingEl: host }, {});
    expect(fetch).toHaveBeenCalledOnce();
    expect(host.querySelector('[data-role="reconnect-task"]')).toBeNull();
    expect(append.mock.calls[0][1].status).toBe('failed');
  });

  it('preserves a reader position while showing an explicit new-content control', () => {
    const container = document.createElement('section'); const host = document.createElement('div');
    container.append(host); document.body.appendChild(container);
    Object.defineProperties(container, { scrollHeight: { value: 1000 }, clientHeight: { value: 200 } });
    container.scrollTop = 100;
    const follow = createTaskScrollFollower(container, host);
    follow.notify(); follow.preserve(() => { container.scrollTop = 900; });
    expect(container.scrollTop).toBe(100);
    expect(container.nextElementSibling?.className).toBe('wa-stream-follow-controls');
    expect(host.querySelector('button')).toBeNull();
    container.nextElementSibling!.querySelector<HTMLButtonElement>('button')!.click();
    expect(container.scrollTop).toBe(1000);
    follow.dispose();
  });

  it('keeps one pane-level hint and an older follower cannot remove a newer hint', () => {
    const container = document.createElement('section'); document.body.appendChild(container);
    Object.defineProperties(container, { scrollHeight: { value: 1000 }, clientHeight: { value: 200 } });
    const old = createTaskScrollFollower(container); old.notify();
    const next = createTaskScrollFollower(container); next.notify(); old.dispose();
    expect(document.querySelectorAll('.wa-stream-follow-controls')).toHaveLength(1);
    expect(document.querySelectorAll('.wa-stream-new-content')).toHaveLength(1);
    document.querySelector<HTMLButtonElement>('.wa-stream-new-content')!.click();
    expect(container.scrollTop).toBe(1000); expect(document.querySelector('.wa-stream-follow-controls')).toBeNull();
    next.dispose();
  });

  it('bounds old drafts and does not re-render after disposal or parse huge output as HTML', () => {
    const state = createTaskMessageStreamState();
    for (let i = 0; i < 60; i += 1) applyTaskMessageStreamEvent(state, { type: 'message.finished', message_id: String(i), text: 'draft' });
    expect(state.messages.size).toBeLessThanOrEqual(16);
    const node = document.createElement('div'); const format = vi.fn((text) => text);
    const renderer = createStreamingTextRenderer(node, format);
    const long = '<script>'.repeat(40_000);
    renderer.update(long, true);
    expect(format).not.toHaveBeenCalled(); expect(node.textContent).toBe(long);
    renderer.dispose(); renderer.update('late', true);
    expect(node.textContent).toBe(long);
  });

  it('shows concrete operations and real progress while retaining committed results after failure', () => {
    const host = document.createElement('div');
    const view = createTaskChatPresentation(host);
    view.event({ type: 'tool.started', payload: { tool_name: 'read_docx_content', tool_call_id: 'read-1' } });
    view.event({ type: 'tool.progress', payload: { tool_name: 'read_docx_content', tool_call_id: 'read-1', payload: { detail: '已读取 2/4 页' } } });
    expect(host.textContent).toContain('读取 Word 内容');
    expect(host.textContent).toContain('已读取 2/4 页');
    expect(host.textContent).not.toContain('正在思考');
    view.event({ type: 'file.changed', payload: { path: 'report.docx' } });
    view.settle('failed', '核验没有通过');
    expect(host.textContent).toContain('任务未完成');
    expect(host.textContent).toContain('成果仍保留');
    expect(host.textContent).toContain('核验没有通过');
  });
});
