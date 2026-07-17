import { describe, expect, it, vi } from 'vitest';
import {
  createTaskRunEventHandlers,
  taskTerminalResult,
} from './task-run-event-handlers';

function createRuntime(card: HTMLElement) {
  const steps = new Map<string, HTMLElement>();
  const taskStageStep = vi.fn((_card: HTMLElement, stepId: string) => {
    let step = steps.get(stepId);
    if (!step) {
      step = document.createElement('section');
      step.className = 'wa-task-step';
      step.dataset.stepId = stepId;
      card.querySelector('[data-role="steps"]')?.appendChild(step);
      steps.set(stepId, step);
    }
    return step;
  });
  return {
    getState: vi.fn(() => ({ fileChanges: [] })),
    ensureReport: vi.fn(),
    setRunContext: vi.fn(),
    taskStageStep,
    markStepRunning: vi.fn((step: HTMLElement) => step.classList.add('running')),
    markStepDone: vi.fn((step: HTMLElement) => step.classList.add('done')),
    markStepFailed: vi.fn((step: HTMLElement) => step.classList.add('failed')),
    setCurrentStage: vi.fn(),
    setStatus: vi.fn(),
    updatePerformance: vi.fn(),
    startHeartbeat: vi.fn(),
    stopHeartbeat: vi.fn(),
    syncLiveProgress: vi.fn(),
    decodeArtifactResult: vi.fn(() => null),
    normalizeWorkspacePath: vi.fn((value: unknown) => String(value || '')),
    reloadFileByPath: vi.fn(),
    persistTerminalCard: vi.fn(),
    showToast: vi.fn(),
  };
}

describe('task run event handlers', () => {
  it('owns run start preparation and heartbeat activation', () => {
    const card = document.createElement('article');
    card.className = 'done';
    card.innerHTML = '<div data-role="steps"></div>';
    const runtime = createRuntime(card);
    const handlers = createTaskRunEventHandlers(runtime);

    handlers['run.started'](card, { run_id: 'run-1' }, { tool_use_id: 'tool-1' });

    expect(card.classList).toContain('streaming');
    expect(card.classList).not.toContain('done');
    expect(card.dataset.taskToolUseId).toBe('tool-1');
    expect(runtime.setRunContext).toHaveBeenCalledTimes(1);
    expect(runtime.markStepRunning).toHaveBeenCalledTimes(1);
    expect(runtime.startHeartbeat).toHaveBeenCalledWith(card);
  });

  it('projects a completed run into one final report and persistence path', () => {
    const card = document.createElement('article');
    card.className = 'wa-task-run streaming';
    card.dataset.taskCompleted = 'true';
    card.dataset.taskTerminalStatus = 'completed';
    card.innerHTML = `
      <h3 class="wa-task-title">处理中</h3>
      <details data-role="process"><span data-role="process-title"></span><span data-role="process-state"></span></details>
      <div data-role="steps"></div>
      <div data-role="summary"></div>
      <button data-role="cancel">取消</button>
    `;
    const runtime = createRuntime(card);
    const handlers = createTaskRunEventHandlers(runtime);

    handlers['run.finished'](card, {}, { summary: '报告已经生成。' });

    expect(card.classList).toContain('done');
    expect(card.classList).not.toContain('streaming');
    expect(card.dataset.taskSummary).toBe('报告已经生成。');
    expect(card.querySelector('[data-role="final-report"]')).not.toBeNull();
    expect(runtime.stopHeartbeat).toHaveBeenCalledWith(card);
    expect(runtime.persistTerminalCard).toHaveBeenCalledWith(card);
  });

  it('derives terminal results from the card dataset without another owner', () => {
    const card = document.createElement('article');
    card.dataset.taskId = 'task-1';
    card.dataset.taskRunId = 'run-1';
    card.dataset.taskTerminalStatus = 'write_not_performed';
    card.dataset.taskCompleted = 'false';
    card.dataset.taskFailureSummary = '目标文件没有变化';

    expect(taskTerminalResult(card, '备用摘要')).toMatchObject({
      task_id: 'task-1',
      run_id: 'run-1',
      terminal_status: 'write_not_performed',
      completed_task: false,
      status: 'error',
      summary: '目标文件没有变化',
    });
  });
});
