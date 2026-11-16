import { afterEach, describe, expect, it, vi } from 'vitest';
import { parseSseEvents, isTaskStreamTerminalEvent } from './file-task-sse';
import { applyTaskMessageStreamEvent, createStreamingTextRenderer, createTaskMessageStreamState } from './task-message-stream';

afterEach(() => vi.useRealTimers());

describe('canonical workbench message stream', () => {
  it('keeps deltas, validated replacement and final answer distinct', () => {
    const state = createTaskMessageStreamState();
    [
      { type: 'message.started', message_id: 'm1' },
      { type: 'message.delta', message_id: 'm1', delta: '你' },
      { type: 'message.delta', message_id: 'm1', delta: '好' },
      { type: 'message.finished', message_id: 'm1', text: '你好。', status: 'completed' },
      { type: 'agent_step', data: { step_type: 'answer', content: '你好。' } },
      { type: 'task_final', data: { status: 'success', result: '你好。' } },
    ].forEach((event) => applyTaskMessageStreamEvent(state, event));
    expect(state.text).toBe('你好。');
    expect(state.terminal).toBe(true);
    applyTaskMessageStreamEvent(state, { type: 'message.delta', message_id: 'm1', delta: '迟到片段' });
    expect(state.text).toBe('你好。');
  });

  it('starts a separate message for validation retry and drops replayed deltas', () => {
    const state = createTaskMessageStreamState();
    const emit = (seq: number, type: string, message_id: string, data = {}) =>
      applyTaskMessageStreamEvent(state, { run_id: 'r', seq, type, payload: { message_id, ...data } });
    emit(1, 'message.started', 'old');
    emit(2, 'message.delta', 'old', { delta: '旧草稿' });
    emit(3, 'message.finished', 'old', { text: '旧草稿', status: 'retrying' });
    emit(4, 'message.started', 'new');
    emit(5, 'message.delta', 'new', { delta: '修订稿' });
    emit(5, 'message.delta', 'new', { delta: '修订稿' });
    expect(state.text).toBe('修订稿');
    expect(state.messages.get('old')?.status).toBe('retrying');
  });

  it('uses SSE ids for resume and preserves multibyte text across byte chunks', () => {
    const bytes = new TextEncoder().encode('id: run-1:9\r\ndata: {"type":"message.delta","delta":"你好🙂"}\r\n\r\n');
    const decoder = new TextDecoder();
    let buffer = '';
    const events: Record<string, any>[] = [];
    for (let i = 0; i < bytes.length; i += 1) {
      buffer += decoder.decode(bytes.slice(i, i + 1), { stream: true });
      const parsed = parseSseEvents(buffer, false);
      buffer = parsed.remainder;
      events.push(...parsed.events);
    }
    expect(events).toEqual([{ type: 'message.delta', delta: '你好🙂', event_id: 'run-1:9', run_id: 'run-1', seq: 9 }]);
  });

  it('does not treat a recoverable tool error as run completion', () => {
    expect(isTaskStreamTerminalEvent({ type: 'error', payload: { recoverable: true } })).toBe(false);
    expect(isTaskStreamTerminalEvent({ type: 'run.finished' })).toBe(true);
  });

  it('shows partial text before completion and only formats Markdown at the end', () => {
    vi.useFakeTimers();
    const node = document.createElement('div');
    const format = vi.fn((value) => `<strong>${value}</strong>`);
    const renderer = createStreamingTextRenderer(node, format);
    renderer.update('第一段');
    renderer.update('第一段，第二段');
    expect(format).not.toHaveBeenCalled();
    vi.advanceTimersByTime(32);
    expect(node.textContent).toBe('第一段，第二段');
    expect(format).not.toHaveBeenCalled();
    renderer.update('完整回答', true);
    expect(node.innerHTML).toBe('<strong>完整回答</strong>');
    renderer.dispose();
  });
});
