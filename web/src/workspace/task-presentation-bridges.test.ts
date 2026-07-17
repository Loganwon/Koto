import { describe, expect, it, vi } from 'vitest';
import {
  taskPerformanceFromDataset,
  updateTaskPerformanceRow,
} from './task-performance';
import { syncTaskInteractionSummary } from './task-interaction-summary';
import { syncTaskPrimaryAction } from './task-result-presentation';
import {
  ensureTaskReportAfterProcess,
  restoreTaskStageStatus,
} from './task-stage-presentation';

describe('task presentation bridges', () => {
  it('owns performance dataset merging on the task card', () => {
    const card = document.createElement('article');

    updateTaskPerformanceRow(card, {
      performance: { route_decision_ms: 12 },
    });
    updateTaskPerformanceRow(card, {
      runtime: { performance: { total_ms: 48 } },
    });

    expect(taskPerformanceFromDataset(card.dataset.taskPerformance || ''))
      .toEqual({ route_decision_ms: 12, total_ms: 48 });
  });

  it('keeps the report after process details and restores visible stage status', () => {
    const card = document.createElement('article');
    card.innerHTML = `
      <div data-role="summary"></div>
      <details data-role="process"></details>
      <span data-role="status"></span>
    `;
    card.dataset.taskStageStatus = 'waiting';
    const setStatus = vi.fn();

    ensureTaskReportAfterProcess(card);
    restoreTaskStageStatus(card, setStatus);

    const process = card.querySelector('[data-role="process"]');
    expect(process?.nextElementSibling?.getAttribute('data-role')).toBe('summary');
    expect(card.querySelector<HTMLElement>('[data-role="status"]')?.dataset.status)
      .toBe('waiting');
    expect(setStatus).toHaveBeenCalledWith(card, '待确认');
  });

  it('projects stream state into the single primary action host', () => {
    const card = document.createElement('article');
    card.innerHTML = '<div data-role="task-primary-action"></div>';
    card.classList.add('streaming');

    syncTaskPrimaryAction(card, { streamConnectionState: 'connected' });
    expect(card.querySelector('[data-role="cancel"]')).not.toBeNull();

    card.classList.remove('streaming');
    card.dataset.taskId = 'task-1';
    syncTaskPrimaryAction(card, { streamConnectionState: 'failed' });
    expect(card.querySelector('[data-task-stream-retry]')).not.toBeNull();
  });

  it('upserts one interaction summary before result actions', () => {
    const card = document.createElement('article');
    card.dataset.taskRequest = '分析当前文档';
    card.dataset.taskContextSummary = '文件: report.docx';
    card.innerHTML = `
      <details data-role="process"></details>
      <div data-role="summary" hidden>
        <div class="wa-task-actions"></div>
      </div>
    `;

    syncTaskInteractionSummary(card);
    syncTaskInteractionSummary(card);

    const summary = card.querySelector<HTMLElement>('[data-role="summary"]');
    expect(summary?.querySelectorAll(':scope > [data-role="task-context"]'))
      .toHaveLength(1);
    expect(summary?.firstElementChild?.getAttribute('data-role'))
      .toBe('task-context');
    expect(summary?.hidden).toBe(false);
  });
});
