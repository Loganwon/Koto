// @vitest-environment jsdom

import { describe, expect, it, vi } from 'vitest';
import { createTaskStagePresentation } from './task-stage-presentation';
import { createFileTaskUiState, type FileTaskUiState } from './task-ui-state';

describe('task stage presentation', () => {
  it('returns from verification to execution when repair begins', () => {
    const states = new WeakMap<HTMLElement, FileTaskUiState>();
    const presentation = createTaskStagePresentation<HTMLElement, FileTaskUiState>({
      isTaskCardElement: (value) => value instanceof HTMLElement,
      ensureTaskUiState: (card) => {
        let state = states.get(card);
        if (!state) {
          state = createFileTaskUiState();
          states.set(card, state);
        }
        return state;
      },
      attachRunCardBehavior: (card) => card,
      taskStageStep: (card, stageId) => {
        const host = card.querySelector('[data-role="steps"]') as HTMLElement;
        let step = host.querySelector(`[data-step-id="${stageId}"]`) as HTMLElement | null;
        if (!step) {
          step = document.createElement('div');
          step.dataset.stepId = stageId;
          step.className = 'wa-task-step';
          step.innerHTML = `<span class="wa-task-step-title">${stageId}</span>`;
          host.appendChild(step);
        }
        return step;
      },
      markStepDone: (step) => { step.className = 'wa-task-step done'; },
      markStepRunning: (step) => { step.className = 'wa-task-step running'; },
      markStepFailed: (step) => { step.className = 'wa-task-step failed'; },
      setStatus: (card, text) => {
        const status = card.querySelector('[data-role="status"]');
        if (status) status.textContent = text;
      },
    });
    const card = presentation.makeRunCard();

    presentation.applyCanonicalTaskStageState(card, {
      type: 'check.started',
      ui_state: {
        phase: 'check', status: 'running', progress: 86, title: '正在核验结果',
      },
    });
    expect(card.dataset.taskCurrentStage).toBe('check');

    presentation.applyCanonicalTaskStageState(card, {
      type: 'supervisor.status',
      payload: { stage: 'repairing' },
      ui_state: {
        phase: 'execute', status: 'warning', progress: 90, title: '正在修复结果',
      },
    });

    expect(card.dataset.taskCurrentStage).toBe('execute');
    expect(card.querySelector('[data-role="stage-current-label"]')?.textContent)
      .toBe('正在处理');
    expect(card.querySelector('[data-role="stage-journal-count"]')?.textContent)
      .toBe('1 条');
  });

  it('batches high-frequency stage rendering into one animation frame', () => {
    const callbacks: FrameRequestCallback[] = [];
    const originalRequestAnimationFrame = window.requestAnimationFrame;
    Object.defineProperty(window, 'requestAnimationFrame', {
      configurable: true,
      value: vi.fn((callback: FrameRequestCallback) => {
        callbacks.push(callback);
        return callbacks.length;
      }),
    });
    document.body.innerHTML = '<div><div id="wa-ai-messages"></div></div>';

    try {
      const states = new WeakMap<HTMLElement, FileTaskUiState>();
      const syncPrimaryAction = vi.fn();
      const presentation = createTaskStagePresentation<HTMLElement, FileTaskUiState>({
        isTaskCardElement: (value) => value instanceof HTMLElement,
        ensureTaskUiState: (card) => {
          let state = states.get(card);
          if (!state) {
            state = createFileTaskUiState();
            states.set(card, state);
          }
          return state;
        },
        attachRunCardBehavior: (card) => card,
        taskStageStep: (card, stageId) => {
          const host = card.querySelector('[data-role="steps"]') as HTMLElement;
          let step = host.querySelector(`[data-step-id="${stageId}"]`) as HTMLElement | null;
          if (!step) {
            step = document.createElement('div');
            step.dataset.stepId = stageId;
            step.className = 'wa-task-step';
            step.innerHTML = `<span class="wa-task-step-title">${stageId}</span>`;
            host.appendChild(step);
          }
          return step;
        },
        markStepDone: (step) => { step.className = 'wa-task-step done'; },
        markStepRunning: (step) => { step.className = 'wa-task-step running'; },
        markStepFailed: (step) => { step.className = 'wa-task-step failed'; },
        setStatus: (card, text) => {
          const status = card.querySelector('[data-role="status"]');
          if (status) status.textContent = text;
        },
        syncTaskPrimaryAction: syncPrimaryAction,
      });
      const card = presentation.makeRunCard();
      document.body.appendChild(card);
      const rect = vi.spyOn(card, 'getBoundingClientRect').mockReturnValue({
        x: 0,
        y: 0,
        width: 600,
        height: 400,
        top: 0,
        right: 600,
        bottom: 400,
        left: 0,
        toJSON: () => ({}),
      } as DOMRect);
      syncPrimaryAction.mockClear();

      for (let index = 0; index < 25; index += 1) {
        presentation.scheduleCanonicalTaskStageState(card, {
          type: 'tool.started',
          payload: { tool_use_id: 'write-output', tool_name: 'write_docx' },
          ui_state: {
            schema: 'koto.file_task_ui_state.v1',
            phase: 'execute',
            status: 'running',
            progress: 30 + index,
            title: `写入文档 ${index + 1}`,
          },
        });
      }

      expect(callbacks).toHaveLength(1);
      expect(rect).not.toHaveBeenCalled();
      expect(card.dataset.taskCurrentStage).toBeUndefined();

      callbacks.shift()?.(0);

      expect(rect).toHaveBeenCalledTimes(1);
      expect(syncPrimaryAction).toHaveBeenCalledTimes(1);
      expect(card.dataset.taskCurrentStage).toBe('execute');
      expect(card.querySelector('[data-role="stage-journal-count"]')?.textContent)
        .toBe('1 条');
      expect(card.querySelector('.wa-task-progress-entry strong')?.textContent)
        .toBe('写入文档 25');

      presentation.scheduleCanonicalTaskStageState(card, {
        type: 'plan.proposed',
        ui_state: {
          schema: 'koto.file_task_ui_state.v1',
          phase: 'plan',
          status: 'waiting',
          progress: 55,
          title: '等待确认执行方案',
        },
      });

      expect(callbacks).toHaveLength(0);
      expect(rect).toHaveBeenCalledTimes(2);
      expect(card.dataset.taskStageStatus).toBe('waiting');
    } finally {
      if (originalRequestAnimationFrame) {
        Object.defineProperty(window, 'requestAnimationFrame', {
          configurable: true,
          value: originalRequestAnimationFrame,
        });
      } else {
        delete (window as any).requestAnimationFrame;
      }
      document.body.innerHTML = '';
    }
  });
});
