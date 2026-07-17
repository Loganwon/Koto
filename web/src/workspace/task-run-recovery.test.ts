import { describe, expect, it, vi } from 'vitest';
import {
  createTaskRunRecovery,
  installTerminalSnapshotHandler,
  notifyTaskCardSnapshot,
  TaskRunRecoveryCard,
} from './task-run-recovery';

function makeCard(): TaskRunRecoveryCard {
  const card = document.createElement('article') as TaskRunRecoveryCard;
  card.className = 'wa-task-run';
  card.innerHTML = `
    <div class="wa-task-title-wrap"><span class="wa-task-title">任务</span></div>
    <span data-role="status"></span>
    <div data-role="steps"></div>
    <details data-role="process" open><span data-role="process-state"></span></details>
    <div data-role="summary" hidden></div>
    <button data-role="cancel">取消</button>
    <div class="wa-task-actions">操作</div>
  `;
  return card;
}

function makeRuntime(card: TaskRunRecoveryCard) {
  return {
    isCard: (value: unknown): value is TaskRunRecoveryCard => (
      value instanceof HTMLElement && value.classList.contains('wa-task-run')
    ),
    makeRunCard: vi.fn(() => card),
    ensureReport: vi.fn(),
    attachBehavior: vi.fn((value: TaskRunRecoveryCard) => value),
    startHeartbeat: vi.fn(),
    syncLiveProgress: vi.fn(),
    appendIfDetached: vi.fn(),
    claimLivePresentation: vi.fn(),
    dispatchEvent: vi.fn(),
    streamTaskSse: vi.fn(async (value: TaskRunRecoveryCard) => value),
  };
}

describe('task run recovery', () => {
  it('notifies snapshot handlers without letting persistence errors break the run', () => {
    const card = makeCard();
    const handler = vi.fn(() => { throw new Error('storage unavailable'); });

    expect(notifyTaskCardSnapshot(card, handler)).toBe(true);
    expect(handler).toHaveBeenCalledWith(card);
    expect(notifyTaskCardSnapshot(card)).toBe(false);
  });

  it('installs and safely clears the terminal persistence bridge', () => {
    const card = makeCard();
    const handler = vi.fn();
    const cleanup = installTerminalSnapshotHandler(card, handler);

    card._terminalSnapshotHandler?.(card);
    expect(handler).toHaveBeenCalledWith(card);
    cleanup();
    expect(card._terminalSnapshotHandler).toBeUndefined();
  });

  it('restores serialized history cards without live controls', () => {
    const card = makeCard();
    const runtime = makeRuntime(card);
    const recovery = createTaskRunRecovery(runtime);
    const restored = recovery.restoreTaskRunCard({
      html: card.outerHTML,
      fatal_error_text: '',
    }, {
      history: true,
      initialStatus: 'completed',
      history_label: '历史任务记录',
      history_note: '来自上一轮会话',
    });

    expect(restored).not.toBeNull();
    expect(restored?.dataset.historySnapshot).toBe('true');
    expect(restored?.classList).toContain('is-history-snapshot');
    expect(restored?.querySelector('[data-role="cancel"]')).toBeNull();
    expect(restored?.querySelector('.wa-task-actions')).toBeNull();
    expect(restored?.querySelector('[data-role="history-badge"]')?.textContent)
      .toBe('历史任务记录');
    expect(restored?.querySelector('[data-role="history-note"]')?.textContent)
      .toBe('来自上一轮会话');
  });

  it('projects terminal persisted tasks without opening another stream', async () => {
    const card = makeCard();
    const runtime = makeRuntime(card);
    const recovery = createTaskRunRecovery(runtime);
    const onSnapshot = vi.fn();

    const restored = await recovery.resumePersistedFileTask({
      taskId: 'task-completed',
      runId: 'run-1',
      initialStatus: 'completed',
      loadingEl: card,
      taskPayload: { summary: '已经完成' },
      onTaskCardSnapshot: onSnapshot,
    });

    expect(restored).toBe(card);
    expect(runtime.streamTaskSse).not.toHaveBeenCalled();
    expect(runtime.dispatchEvent).toHaveBeenCalledWith(card, {
      type: 'run.finished',
      payload: {
        summary: '已经完成',
        terminal_status: 'completed',
        completed_task: true,
      },
    });
    expect(onSnapshot).toHaveBeenCalledWith(card);
  });

  it('replays active tasks through the persisted stream endpoint', async () => {
    const card = makeCard();
    const runtime = makeRuntime(card);
    const recovery = createTaskRunRecovery(runtime);

    await recovery.resumePersistedFileTask({
      taskId: 'task-running',
      initialStatus: 'running',
      loadingEl: card,
      replay: false,
    });

    expect(runtime.streamTaskSse).toHaveBeenCalledWith(
      card,
      '/api/tasks/task-running/stream?replay=false',
      {},
      'GET',
    );
  });
});
