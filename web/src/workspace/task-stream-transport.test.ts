import { describe, expect, it, vi } from 'vitest';
import {
  createFileTaskId,
  createFileTaskRunId,
  createTaskStreamTransport,
  type TaskStreamTransportCard,
  type TaskStreamTransportRuntime,
} from './task-stream-transport';

interface TestCard extends TaskStreamTransportCard {}

interface TestTerminalResult {
  summary?: string;
  card: TestCard;
}

function encodedChunk(text: string): Uint8Array {
  return new TextEncoder().encode(text);
}

function streamResponse(frames: string[]): Response {
  const reads = frames.map((frame) => ({
    done: false,
    value: encodedChunk(frame),
  }));
  const reader = {
    read: vi.fn()
      .mockImplementation(() => Promise.resolve(
        reads.shift() || { done: true, value: undefined },
      )),
    cancel: vi.fn().mockResolvedValue(undefined),
  };
  return {
    ok: true,
    status: 200,
    statusText: 'OK',
    body: { getReader: () => reader },
  } as unknown as Response;
}

function createFixture(
  csrfFetch = vi.fn(async () => streamResponse([
    'data: {"type":"run.started"}\n\n'
      + 'data: {"type":"run.finished","payload":{"summary":"完成"}}\n\n',
  ])),
  fetchImpl = vi.fn(async () => streamResponse([
    'data: {"type":"run.finished","payload":{"summary":"完成"}}\n\n',
  ])),
) {
  const events: Record<string, any>[] = [];
  const runtime: TaskStreamTransportRuntime<TestCard, TestTerminalResult> = {
    makeRunCard: vi.fn((loadingEl) => (
      loadingEl || document.createElement('article') as TestCard
    )),
    claimLivePresentation: vi.fn(),
    finalizeCancellation: vi.fn(),
    processEvent: vi.fn((_card, event) => events.push(event)),
    stopHeartbeat: vi.fn(),
    startHeartbeat: vi.fn(),
    seedRouteModelContext: vi.fn(),
    prepareActive: vi.fn((card) => card.classList.add('streaming')),
    showReconnectNotice: vi.fn(),
    terminalResult: vi.fn((card) => ({
      summary: card.dataset.taskId || 'done',
      card,
    })),
    csrfFetch,
    fetchImpl,
  };
  const transport = createTaskStreamTransport(runtime);
  return { events, runtime, transport, csrfFetch, fetchImpl };
}

describe('task stream transport', () => {
  it('creates stable client identifiers with the expected shape', () => {
    expect(createFileTaskId()).toMatch(/^task_[a-z0-9]{12,32}$/i);
    expect(createFileTaskRunId()).toMatch(/^[a-z0-9]{12}$/i);
    expect(createFileTaskId()).not.toBe(createFileTaskId());
  });

  it('owns initial request setup, SSE consumption, and terminal cleanup', async () => {
    const { events, runtime, transport, csrfFetch } = createFixture();
    const messages = document.createElement('section');
    messages.id = 'wa-ai-messages';
    document.body.appendChild(messages);
    const payload = {
      task: '生成报告',
      options: { quick_action_mode: 'simple' },
    };
    const snapshots = vi.fn();

    const result = await transport.streamTaskFlow({
      payload,
      msgs: messages,
      onTaskCardSnapshot: snapshots,
    });

    const card = (result as TestTerminalResult).card;
    expect(payload).toEqual(expect.objectContaining({
      task_id: expect.stringMatching(/^task_/),
      run_id: expect.stringMatching(/^[a-z0-9]{12}$/i),
    }));
    expect(card.dataset.taskId).toBe(payload.task_id);
    expect(card.dataset.taskRunId).toBe(payload.run_id);
    expect(card.dataset.taskQuickActionMode).toBe('answer');
    expect(messages.contains(card)).toBe(true);
    expect(events.map((event) => event.type)).toEqual([
      'run.started',
      'run.finished',
    ]);
    expect(runtime.prepareActive).toHaveBeenCalledWith(card);
    expect(runtime.startHeartbeat).toHaveBeenCalledWith(card);
    expect(runtime.stopHeartbeat).toHaveBeenCalledWith(card);
    expect(runtime.seedRouteModelContext).toHaveBeenCalledWith(card, payload);
    expect(snapshots).toHaveBeenCalled();
    expect(card.classList.contains('streaming')).toBe(false);
    expect(card._abortFileTaskStream).toBeUndefined();
    expect(csrfFetch).toHaveBeenCalledWith(
      '/api/editor/ai/task-stream',
      expect.objectContaining({ method: 'POST' }),
    );
  });

  it('recovers the persisted task once after an initial transport failure', async () => {
    const csrfFetch = vi.fn(async () => {
      throw new Error('offline');
    });
    const { runtime, transport } = createFixture(csrfFetch);
    const recoveredCard = document.createElement('article') as TestCard;
    recoveredCard.dataset.taskId = 'task-recovered';
    const resume = vi.fn(async () => recoveredCard);
    transport.setResumePersistedTask(resume);

    const result = await transport.streamTaskFlow({
      payload: { task_id: 'task-4', run_id: 'run-4' },
    });

    expect(runtime.showReconnectNotice).toHaveBeenCalledWith(
      expect.any(HTMLElement),
      'recovering',
    );
    expect(resume).toHaveBeenCalledWith({
      taskId: 'task-4',
      runId: 'run-4',
      loadingEl: expect.any(HTMLElement),
      initialStatus: 'running',
      replay: true,
    });
    expect((result as TestTerminalResult).card).toBe(recoveredCard);
  });

  it('rejects a recovery SSE stream without a terminal event and cleans cancellation', async () => {
    const fetchImpl = vi.fn(async () => streamResponse([]));
    const { runtime, transport } = createFixture(undefined, fetchImpl);
    const card = document.createElement('article') as TestCard;

    await expect(transport.streamTaskSse(
      card,
      '/api/tasks/task-5/stream',
      {},
      'GET',
    )).rejects.toThrow('任务状态流已断开，正在保留后台任务状态。');

    expect(runtime.showReconnectNotice).toHaveBeenCalledWith(card, 'failed');
    expect(runtime.stopHeartbeat).toHaveBeenCalledWith(card);
    expect(card._cancelHandler).toBeUndefined();
  });
});
