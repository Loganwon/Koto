import { describe, expect, it, vi } from 'vitest';
import {
  createTaskExecutionEventHandlers,
  TaskExecutionEvidenceCard,
  TaskExecutionEvidenceState,
} from './task-execution-event-handlers';

function setup() {
  const card = document.createElement('article') as TaskExecutionEvidenceCard;
  const executeStep = document.createElement('section');
  const contextStep = document.createElement('section');
  card.append(executeStep, contextStep);
  const state: TaskExecutionEvidenceState = {
    fileChangeKeys: new Set(),
    fileChanges: [],
    readKeys: new Set(),
    codeSummaryRows: new Map(),
  };
  const upsertStepRow = vi.fn((step, role, kind, html) => {
    let row = step.querySelector(`[data-role="${role}"]`) as HTMLElement | null;
    if (!row) {
      row = document.createElement('div');
      row.dataset.role = role;
      step.appendChild(row);
    }
    row.dataset.kind = kind;
    row.innerHTML = html;
    return row;
  });
  const appendRow = vi.fn((step, kind, html, role = '') => {
    const row = document.createElement('div');
    row.dataset.kind = kind;
    if (role) row.dataset.role = role;
    row.innerHTML = html;
    step.appendChild(row);
    return row;
  });
  const markExternalFileChange = vi.fn();
  const requestFileBrowserRefresh = vi.fn();
  const handlers = createTaskExecutionEventHandlers({
    getState: () => state,
    taskStageStep: (_card, stepId) => (
      stepId === 'context' ? contextStep : executeStep
    ),
    markStepRunning: (step) => step.classList.add('running'),
    upsertStepRow,
    appendRow,
    setRunContext: vi.fn(),
    normalizeWorkspacePath: (path) => path.replace(/^workspace\//, ''),
    markExternalFileChange,
    requestFileBrowserRefresh,
  });
  return {
    card,
    state,
    executeStep,
    contextStep,
    handlers,
    upsertStepRow,
    appendRow,
    markExternalFileChange,
    requestFileBrowserRefresh,
  };
}

describe('task execution event handlers', () => {
  it('renders one readable tool lifecycle row', () => {
    const { card, executeStep, handlers } = setup();

    handlers['tool.started'](card, {}, {
      tool_name: 'run_python_code',
      tool_use_id: 'tool-1',
    });
    handlers['tool.finished'](card, {}, {
      tool_name: 'run_python_code',
      tool_use_id: 'tool-1',
      success: true,
    });

    const rows = executeStep.querySelectorAll('[data-role="tool:run_python_code:tool-1"]');
    expect(rows).toHaveLength(1);
    expect(rows[0].textContent).toContain('完成');
    expect(rows[0].textContent).toContain('运行 Python');
  });

  it('deduplicates file changes while preserving refresh notification', () => {
    const {
      card,
      state,
      handlers,
      appendRow,
      markExternalFileChange,
      requestFileBrowserRefresh,
    } = setup();
    const payload = {
      path: 'workspace/reports/final.docx',
      change_type: 'created',
    };

    handlers['file.changed'](card, {}, payload);
    handlers['file.changed'](card, {}, payload);

    expect(state.fileChanges).toEqual([{
      path: 'workspace/reports/final.docx',
      changeType: 'created',
    }]);
    expect(appendRow).toHaveBeenCalledTimes(1);
    expect(markExternalFileChange).toHaveBeenCalledWith('reports/final.docx');
    expect(requestFileBrowserRefresh).toHaveBeenCalled();
  });

  it('aggregates read evidence into one bounded row', () => {
    const { card, contextStep, handlers } = setup();
    ['a.docx', 'b.xlsx', 'c.pdf', 'd.txt'].forEach((path) => {
      handlers['read.changed'](card, {}, { path: `workspace/${path}` });
    });

    const row = contextStep.querySelector('[data-role="read-files"]');
    expect(row).not.toBeNull();
    expect(row?.querySelectorAll('a')).toHaveLength(3);
    expect(row?.textContent).toContain('等 4 个文件');
  });

  it('deduplicates code summaries and marks produced output', () => {
    const { card, state, handlers, appendRow } = setup();
    const payload = { file: 'workspace/result.py', action: 'write' };

    handlers.code_summary(card, {}, payload);
    handlers.code_summary(card, {}, payload);

    expect(appendRow).toHaveBeenCalledTimes(1);
    expect(state.codeSummaryRows.size).toBe(1);
    expect(card.dataset.taskCompleted).toBe('true');
  });
});
