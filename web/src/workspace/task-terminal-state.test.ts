import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  applyTaskTerminalCardPresentation,
  compactTerminalProcess,
  persistTerminalTaskCard,
  prepareTaskCardForActiveRun,
  taskTerminalProjection,
} from './task-terminal-state';

afterEach(() => {
  vi.useRealTimers();
  document.body.innerHTML = '';
});

describe('task terminal state', () => {
  it('projects completed and confirmation terminal states consistently', () => {
    expect(taskTerminalProjection({
      status: 'done', terminal_status: 'completed', completed_task: true,
    })).toMatchObject({
      terminalStatus: 'completed', statusText: '已完成', title: '任务完成',
      cardClass: 'done', executeStepState: 'done', checkStepState: 'done',
      collapseProcess: true,
    });
    expect(taskTerminalProjection({
      status: 'pending', terminal_status: 'awaiting_confirmation', completed_task: false,
    })).toMatchObject({
      statusText: '待确认', title: '等待确认', cardClass: 'done',
      executeStepState: 'running', checkStepState: 'running',
      collapseProcess: false,
    });
  });

  it('projects failures without losing a semantic task title', () => {
    expect(taskTerminalProjection({
      status: 'error', terminal_status: '', completed_task: false,
    }, '生成月报')).toMatchObject({
      terminalStatus: 'failed', statusText: '执行失败', title: '生成月报',
      cardClass: 'failed', executeStepState: 'failed', runStepState: 'failed',
      checkStepState: 'failed', processStateText: '未完成',
    });
  });

  it('clears stale terminal classes when a task resumes and completes again', () => {
    const card = document.createElement('article');
    card.className = 'wa-task-run done failed cancelled pending';
    card.innerHTML = `
      <h3 class="wa-task-title"></h3>
      <details data-role="process" open>
        <summary><span data-role="process-title"></span><span data-role="process-state"></span></summary>
        <div class="wa-task-artifact-row"></div>
      </details>
      <button data-role="cancel"></button>
    `;
    prepareTaskCardForActiveRun(card);
    expect(card.classList.contains('streaming')).toBe(true);
    expect(card.classList.contains('failed')).toBe(false);

    const projection = taskTerminalProjection({
      status: 'done', terminal_status: 'completed', completed_task: true,
    });
    applyTaskTerminalCardPresentation(card, projection);
    expect(card.classList.contains('streaming')).toBe(false);
    expect(card.classList.contains('done')).toBe(true);
    expect(card.querySelector('details')?.open).toBe(false);
    expect(card.querySelector('[data-role="process-title"]')?.textContent)
      .toBe('查看执行详情 · 1个产出');
    expect(card.querySelector('[data-role="cancel"]')?.textContent).toBe('关闭');
  });

  it('removes internal terminal rows while retaining user-visible evidence', () => {
    const card = document.createElement('article');
    card.innerHTML = `
      <div data-role="steps">
        <section class="wa-task-step" data-step-id="run"><div class="wa-task-step-body"></div></section>
        <section class="wa-task-step" data-step-id="check"><div class="wa-task-step-body">
          <div class="wa-task-row" data-task-detail-visibility="internal"></div>
          <div class="wa-task-row" data-task-detail-visibility="user">已核验</div>
        </div></section>
      </div>
    `;
    compactTerminalProcess(card, {
      status: 'done', terminal_status: 'completed', completed_task: true,
    });
    expect(card.querySelector('[data-step-id="run"]')).toBeNull();
    expect(card.querySelectorAll('.wa-task-row')).toHaveLength(1);
    expect(card.textContent).toContain('已核验');
  });

  it('persists once after the terminal snapshot callback has run', () => {
    vi.useFakeTimers();
    const card = document.createElement('article') as HTMLElement & {
      _terminalSnapshotHandler?: (_card: HTMLElement) => void;
    };
    const snapshot = vi.fn();
    const persist = vi.fn();
    card._terminalSnapshotHandler = snapshot;
    persistTerminalTaskCard(card, persist);
    expect(snapshot).toHaveBeenCalledWith(card);
    expect(persist).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1000);
    expect(persist).toHaveBeenCalledWith(card);
  });
});
