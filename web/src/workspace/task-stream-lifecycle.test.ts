import { describe, expect, it, vi } from 'vitest';
import {
  consumeTaskEventStream,
  createTaskStreamLifecycle,
  installTaskCancelHandler,
  TaskStreamLifecycleState,
} from './task-stream-lifecycle';

function encodedChunk(text: string): Uint8Array {
  return new TextEncoder().encode(text);
}

describe('task stream lifecycle', () => {
  it('consumes split SSE frames and stops on the first terminal event', async () => {
    const read = vi.fn()
      .mockResolvedValueOnce({
        done: false,
        value: encodedChunk('data: {"type":"run.started"}\n\ndata: {"type":"run.'),
      })
      .mockResolvedValueOnce({
        done: false,
        value: encodedChunk('finished","payload":{"summary":"完成"}}\n\n'),
      })
      .mockResolvedValueOnce({ done: true, value: undefined });
    const cancel = vi.fn().mockResolvedValue(undefined);
    const reader = { read, cancel } as unknown as ReadableStreamDefaultReader<Uint8Array>;
    const events: Record<string, any>[] = [];

    const result = await consumeTaskEventStream(reader, {
      onEvent: (event) => events.push(event),
      stopOnTerminal: true,
    });

    expect(events.map((event) => event.type)).toEqual([
      'run.started',
      'run.finished',
    ]);
    expect(result.terminalSeen).toBe(true);
    expect(read).toHaveBeenCalledTimes(2);
    expect(cancel).toHaveBeenCalledTimes(1);
  });

  it('installs an idempotent cancel handler and removes only its own handler', () => {
    const card = document.createElement('article');
    const abort = vi.fn();
    const finalize = vi.fn();
    const cleanup = installTaskCancelHandler(card, abort, finalize);

    card._cancelHandler?.();
    card._cancelHandler?.();

    expect(abort).toHaveBeenCalledTimes(1);
    expect(finalize).toHaveBeenCalledTimes(1);
    cleanup();
    expect(card._cancelHandler).toBeUndefined();
  });

  it('owns reconnect state and cancellation finalization', () => {
    const card = document.createElement('article');
    card.className = 'streaming';
    card.dataset.taskId = 'task-1';
    card.innerHTML = '<span data-role="status"></span>';
    const step = document.createElement('section');
    const state: TaskStreamLifecycleState = {
      lastActivityAt: Date.now(),
      heartbeatTimer: null,
      waitNoticeLevel: 'none',
      streamConnectionState: 'connected',
    };
    const dispatchEvent = vi.fn((_card, event) => {
      if (event.type === 'run.cancelled') card.dataset.taskTerminalStatus = 'cancelled';
    });
    const syncLiveProgress = vi.fn();
    const upsertStatusRow = vi.fn(() => document.createElement('div'));
    const controller = createTaskStreamLifecycle({
      getState: () => state,
      isCard: (value): value is HTMLElement => value === card,
      removeStatusRow: vi.fn(),
      restoreStageStatus: vi.fn(),
      ensureRunStep: () => step,
      currentRunStep: () => step,
      markStepRunning: vi.fn(),
      upsertStatusRow,
      setStatus: vi.fn(),
      syncLiveProgress,
      dispatchEvent,
    });

    controller.showReconnectNotice(card, 'failed');
    expect(state.streamConnectionState).toBe('failed');
    expect(upsertStatusRow).toHaveBeenCalledWith(
      step,
      'stream-reconnect',
      'warn',
      expect.stringContaining('同步中断'),
    );

    expect(controller.cancelRun(card)).toBe(true);
    expect(dispatchEvent).toHaveBeenCalledWith(card, expect.objectContaining({
      type: 'run.cancelled',
    }));
    expect(card.classList).toContain('cancelled');
    expect(card.classList).not.toContain('streaming');
    expect(syncLiveProgress).toHaveBeenCalled();
  });
});
