// @vitest-environment jsdom

import { beforeEach, describe, expect, it } from 'vitest';
import {
  recordTaskProgress,
  resetTaskProgressJournal,
  setTaskProgressJournalTerminal,
  taskProgressJournalEntries,
  taskProgressJournalMarkup,
  toggleTaskProgressJournal,
} from './task-progress-journal';
import type { TaskStageProjection } from './task-stage-state';

function projection(overrides: Partial<TaskStageProjection> = {}): TaskStageProjection {
  return {
    stageId: 'execute',
    title: '正在读取并分析文件',
    status: 'running',
    progress: 58,
    terminal: false,
    ...overrides,
  };
}

describe('task progress journal', () => {
  let card: HTMLElement;

  beforeEach(() => {
    document.body.innerHTML = `<article id="card">${taskProgressJournalMarkup()}</article>`;
    card = document.getElementById('card') as HTMLElement;
  });

  it('keeps distinct user-readable progress entries in event order', () => {
    recordTaskProgress(card, { type: 'run.started', payload: {} }, projection({
      stageId: 'route',
      title: '正在建立任务上下文',
      progress: 5,
    }));
    recordTaskProgress(card, { type: 'plan.created', payload: {} }, projection({
      stageId: 'plan',
      title: '已生成三步执行方案',
      progress: 32,
    }));
    recordTaskProgress(card, {
      type: 'tool.started',
      payload: { tool_name: 'parse_file_to_text', tool_use_id: 'tool-1' },
    }, projection());

    const entries = Array.from(card.querySelectorAll('.wa-task-progress-entry'));
    expect(entries).toHaveLength(3);
    expect(entries.map((entry) => entry.textContent)).toEqual([
      expect.stringContaining('正在建立任务上下文'),
      expect.stringContaining('已生成三步执行方案'),
      expect.stringContaining('正在读取并分析文件'),
    ]);
    expect(card.querySelector('[data-role="stage-journal-count"]')?.textContent).toBe('3 条');
  });

  it('updates a started action in place when the matching completion arrives', () => {
    const started = {
      type: 'tool.started',
      payload: { tool_name: 'write_docx', tool_use_id: 'tool-7' },
    };
    const finished = {
      type: 'tool.finished',
      payload: { tool_name: 'write_docx', tool_use_id: 'tool-7', success: true },
    };
    recordTaskProgress(card, started, projection({ title: '正在写入 Word' }));
    recordTaskProgress(card, finished, projection({ title: '已完成 Word 写入' }));

    const entries = card.querySelectorAll('.wa-task-progress-entry');
    expect(entries).toHaveLength(1);
    expect(entries[0].classList.contains('done')).toBe(true);
    expect(entries[0].textContent).toContain('已完成 Word 写入');
    expect(card.querySelector('[data-role="stage-journal-count"]')?.textContent).toBe('1 条');
  });

  it('coalesces duplicate passive status copy from different runtime events', () => {
    const statusProjection = projection({
      stageId: 'plan',
      title: '正在检查执行方案',
      progress: 24,
    });
    recordTaskProgress(card, { type: 'workflow.state', payload: {} }, statusProjection);
    recordTaskProgress(card, {
      type: 'supervisor.status', payload: { stage: 'planned' },
    }, statusProjection);

    expect(card.querySelectorAll('.wa-task-progress-entry')).toHaveLength(0);
    expect(card.querySelector('[data-role="stage-journal-count"]')?.textContent).toBe('0 条');
  });

  it('filters successful internal runtime chatter but keeps failures', () => {
    recordTaskProgress(card, { type: 'model.call.started', payload: {} }, projection({
      title: 'AI 正在分析内容',
    }));
    recordTaskProgress(card, {
      type: 'tool.finished', payload: { tool_name: 'model_message', success: true },
    }, projection({ title: '已完成模型说明，继续处理' }));
    recordTaskProgress(card, {
      type: 'model.call.finished', payload: { success: false },
    }, projection({
      title: 'AI 分析暂时失败，正在调整处理方式',
      status: 'warning',
    }));

    const entries = card.querySelectorAll('.wa-task-progress-entry');
    expect(entries).toHaveLength(1);
    expect(entries[0].textContent).toContain('AI 分析暂时失败');
    expect(entries[0].classList.contains('warning')).toBe(true);
  });

  it('keeps real file changes instead of successful internal tool summaries', () => {
    recordTaskProgress(card, {
      type: 'tool.finished', payload: { tool_name: 'list_workspace_files', success: true },
    }, projection({ title: '已完成当前处理步骤' }));
    recordTaskProgress(card, {
      type: 'tool.finished', payload: { tool_name: 'create_file', success: true },
    }, projection({ title: '已完成结果写入' }));
    recordTaskProgress(card, {
      type: 'file.changed', payload: { path: 'tmp/report.txt', change_type: 'create' },
    }, projection({ title: '已创建 report.txt' }));
    recordTaskProgress(card, {
      type: 'step.result', step_id: 'execute', payload: { status: 'completed' },
    }, projection({ title: '模型工具执行完成' }));

    const entries = card.querySelectorAll('.wa-task-progress-entry');
    expect(entries).toHaveLength(1);
    expect(entries[0].textContent).toContain('已创建 report.txt');
    expect(card.querySelector('[data-role="stage-journal-count"]')?.textContent).toBe('1 条');
  });

  it('removes the optional context step when there was nothing to read', () => {
    recordTaskProgress(card, {
      type: 'step.started', step_id: 'context', payload: { title: '读取显式上下文' },
    }, projection({ title: '读取显式上下文' }));
    recordTaskProgress(card, {
      type: 'step.result',
      step_id: 'context',
      payload: { title: '读取显式上下文', summary: '没有显式文件或选区可读取。', status: 'skipped' },
    }, projection({ title: '读取显式上下文' }));

    expect(card.querySelectorAll('.wa-task-progress-entry')).toHaveLength(0);
    expect(card.querySelector('[data-role="stage-journal-count"]')?.textContent).toBe('0 条');
  });

  it('resets journal state when a card is reused for another run', () => {
    recordTaskProgress(card, { type: 'check.started', payload: {} }, projection({
      stageId: 'check',
      title: '正在核验结果',
      progress: 86,
    }));

    resetTaskProgressJournal(card);

    expect(card.querySelectorAll('.wa-task-progress-entry')).toHaveLength(0);
    expect(card.querySelector('[data-role="stage-journal-count"]')?.textContent).toBe('0 条');
    expect(card.dataset.taskProgressJournalCount).toBeUndefined();
  });

  it('collapses terminal journals and exposes an explicit expand control', () => {
    const events = [
      ['run.started', 'route', '正在建立任务上下文'],
      ['task.classified', 'route', '已识别任务目标'],
      ['plan.created', 'plan', '已生成执行方案'],
      ['tool.started', 'execute', '正在读取文件'],
      ['file.changed', 'execute', '已创建 output.txt'],
    ] as const;
    events.forEach(([type, stageId, title], index) => {
      recordTaskProgress(card, {
        type,
        step_id: `step-${index}`,
        payload: type === 'tool.started'
          ? { tool_name: 'parse_file_to_text', tool_use_id: `tool-${index}` }
          : (type === 'file.changed' ? { path: 'output.txt' } : {}),
      }, projection({ stageId, title }));
    });

    setTaskProgressJournalTerminal(card);
    const journal = card.querySelector('[data-role="stage-journal"]') as HTMLElement;
    const toggle = card.querySelector('[data-task-progress-toggle]') as HTMLButtonElement;
    expect(journal.dataset.terminal).toBe('true');
    expect(journal.dataset.expanded).toBe('false');
    expect(toggle.hidden).toBe(false);
    expect(toggle.textContent).toBe('查看全部 5 条');
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    const list = card.querySelector('[data-role="stage-journal-list"]') as HTMLOListElement;
    expect(list.id).toMatch(/^wa-task-progress-list-/);
    expect(toggle.getAttribute('aria-controls')).toBe(list.id);

    toggleTaskProgressJournal(card);
    expect(journal.dataset.expanded).toBe('true');
    expect(toggle.textContent).toBe('收起进展');
    expect(toggle.getAttribute('aria-expanded')).toBe('true');
  });

  it('returns a bounded semantic snapshot for task history', () => {
    recordTaskProgress(card, { type: 'run.started', payload: {} }, projection({
      stageId: 'route', title: '正在建立任务上下文',
    }));
    recordTaskProgress(card, { type: 'plan.created', payload: {} }, projection({
      stageId: 'plan', title: '已生成执行方案', status: 'succeeded',
    }));
    recordTaskProgress(card, {
      type: 'file.changed', payload: { path: 'output.txt', change_type: 'created' },
    }, projection({ title: '已创建 output.txt', status: 'succeeded' }));

    expect(taskProgressJournalEntries(card, 2)).toEqual([
      { stage: '制定计划', title: '已生成执行方案', status: 'done' },
      { stage: '正在处理', title: '已创建 output.txt', status: 'done' },
    ]);
  });
});
