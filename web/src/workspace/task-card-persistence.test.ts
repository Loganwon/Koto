// @vitest-environment jsdom

import { describe, expect, it } from 'vitest';
import { taskCardPersistenceStructure } from './task-card-persistence';

describe('task card persistence', () => {
  it('persists a bounded semantic progress journal', () => {
    const card = document.createElement('article');
    card.className = 'wa-task-run';
    card.dataset.taskProgressJournalCount = '7';
    card.dataset.taskTerminalStatus = 'completed';
    card.innerHTML = `
      <ol data-role="stage-journal-list">
        <li class="wa-task-progress-entry done" data-status="done">
          <span class="wa-task-progress-stage">制定计划</span><strong>已生成执行方案</strong>
        </li>
        <li class="wa-task-progress-entry done" data-status="done">
          <span class="wa-task-progress-stage">正在处理</span><strong>已创建 output.txt</strong>
        </li>
      </ol>
      <div data-role="summary">任务完成。</div>
    `;

    const structure = taskCardPersistenceStructure(card);

    expect(structure?.progress_count).toBe(7);
    expect(structure?.progress_journal).toEqual([
      { stage: '制定计划', title: '已生成执行方案', status: 'done' },
      { stage: '正在处理', title: '已创建 output.txt', status: 'done' },
    ]);
  });
});
