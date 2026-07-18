import { describe, expect, it, vi } from 'vitest';
import { createTaskTerminalEventHandlers } from './task-terminal-event-handlers';

describe('task terminal event handlers', () => {
  it('normalizes cancellation before the shared finish path', () => {
    const card = document.createElement('article');
    const finish = vi.fn();
    const handlers = createTaskTerminalEventHandlers({ finish });
    handlers['run.cancelled'](card, { run_id: 'run-1' }, {});
    expect(card.dataset.taskTerminalStatus).toBe('cancelled');
    expect(card.dataset.taskCompleted).toBe('false');
    expect(finish).toHaveBeenCalledWith(
      card,
      { run_id: 'run-1' },
      expect.objectContaining({ text: '任务已被取消。' }),
    );
  });

  it('preserves structured failures and finishes only once', () => {
    const card = document.createElement('article') as HTMLElement & {
      _fatalErrorText?: string;
    };
    const finish = vi.fn();
    const handlers = createTaskTerminalEventHandlers({ finish });
    handlers.error(card, {}, {
      failure: { status: 'write_not_performed', summary: '目标文件没有变化' },
      runtime: { execution_path: 'native' },
    });
    expect(card.dataset.taskTerminalStatus).toBe('write_not_performed');
    expect(card._fatalErrorText).toBe('目标文件没有变化');
    expect(finish).toHaveBeenCalledTimes(1);
    expect(finish).toHaveBeenCalledWith(
      card,
      {},
      expect.objectContaining({
        summary: '目标文件没有变化',
        completed_task: false,
        runtime: expect.objectContaining({
          terminal_status: 'write_not_performed',
        }),
      }),
    );
  });
});
