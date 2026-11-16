import { describe, expect, it, vi } from 'vitest';
import {
  persistedTaskRunId,
  createTaskRunRecovery,
  createSessionTaskRecovery,
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
  it('rebinds a serialized manual continuation to the original task and cursor', async () => {
    const card = makeCard(); card.dataset.taskId = 'original'; card.dataset.taskRunId = 'run-1';
    card.dataset.taskLastSeq = '14'; card.dataset.taskTerminalStatus = 'interrupted';
    card.innerHTML += '<div data-role="reconnect-actions"><button data-role="reconnect-task">继续查看原任务</button></div>';
    const runtime = makeRuntime(card); const recovery = createTaskRunRecovery(runtime);
    const restored = recovery.restoreTaskRunCard({ html: card.outerHTML }, { history: true, initialStatus: 'interrupted' })!;
    restored.querySelector<HTMLButtonElement>('[data-role="reconnect-task"]')!.click();
    await vi.waitFor(() => expect(runtime.streamTaskSse).toHaveBeenCalledOnce());
    expect(runtime.streamTaskSse.mock.calls[0][1]).toContain('/api/tasks/original/stream?replay=true&after_seq=14&run_id=run-1');
  });

  it('reattaches an inactive history card in place rather than duplicating or skipping it', async () => {
    const card = makeCard(); card.dataset.taskId = 'old'; card.dataset.historySnapshot = 'true';
    document.body.appendChild(card);
    const fetch = vi.fn(async () => ({ ok: true, json: async () => ({ data: [{ task_id: 'old', run_id: 'r', status: 'running' }] }) }) as Response);
    const resume = vi.fn(async () => card);
    const recover = createSessionTaskRecovery(fetch, resume);
    expect(await recover('session')).toBe(1);
    expect(resume).toHaveBeenCalledWith(expect.objectContaining({ taskId: 'old', runId: 'r', loadingEl: card }));
    expect(await recover('session')).toBe(0);
    document.body.replaceChildren();
  });
  it('reattaches only active unmounted runs and resolves missing ledger run identities', async () => {
    document.body.innerHTML = '<article data-task-id="already-visible"></article>';
    const fetchRequest = vi.fn(async (url: string) => ({ ok: true, json: async () => ({
      data: url.includes('?') ? [
        { task_id: 'already-visible', status: 'running', run_id: 'run-visible' },
        { task_id: 'finished', status: 'completed', run_id: 'run-finished' },
        { task_id: 'active', status: 'running', user_input: '继续当前工作' },
      ] : { metadata: JSON.stringify({ run_id: 'run-active' }) },
    }) }) as Response);
    const resume = vi.fn(async () => makeCard());
    const recover = createSessionTaskRecovery(fetchRequest, resume);

    expect(await recover('session/one')).toBe(1);
    expect(fetchRequest.mock.calls.map(([url]) => url)).toEqual([
      '/api/tasks?session_id=session%2Fone&limit=30', '/api/tasks/active',
    ]);
    expect(resume).toHaveBeenCalledExactlyOnceWith({
      taskId: 'active', runId: 'run-active', initialStatus: 'running',
      taskPayload: { summary: '继续当前工作' },
    });
    document.body.replaceChildren();
  });

  it('resolves serialized ledger metadata and active checkpoint run identities', () => {
    expect(persistedTaskRunId({ metadata: '{"run_id":"r1"}' })).toBe('r1');
    expect(persistedTaskRunId({ recovery: { run_id: 'r2' }, metadata: '{}' })).toBe('r2');
    expect(persistedTaskRunId({ last_event: { run_id: 'r3' } })).toBe('r3');
    expect(persistedTaskRunId({ metadata: 'broken' })).toBe('');
  });
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
      '/api/tasks/task-running/stream?replay=false&after_seq=0',
      {},
      'GET',
    );
  });
});
