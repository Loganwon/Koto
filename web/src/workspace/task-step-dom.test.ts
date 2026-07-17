import { describe, expect, it } from 'vitest';
import {
  appendTaskStepRow,
  ensureTaskStep,
  markTaskStepDone,
  markTaskStepFailed,
  markTaskStepRunning,
  removeTaskStepRow,
  setTaskStatus,
  taskStageStep,
  upsertTaskStepSingletonRow,
} from './task-step-dom';

function createCard(): HTMLElement {
  const card = document.createElement('article');
  card.innerHTML = '<span data-role="status"></span><div data-role="steps"></div>';
  return card;
}

describe('task step DOM', () => {
  it('creates one escaped step and updates its title in place', () => {
    const card = createCard();
    const first = ensureTaskStep(card, 'execute', '<script>执行</script>');
    const second = ensureTaskStep(card, 'execute', '执行文件操作');

    expect(second).toBe(first);
    expect(card.querySelectorAll('.wa-task-step')).toHaveLength(1);
    expect(first.querySelector('script')).toBeNull();
    expect(first.querySelector('.wa-task-step-title')?.textContent)
      .toBe('执行文件操作');
    expect(taskStageStep(card, 'check').dataset.stepId).toBe('check');
  });

  it('keeps step state classes mutually exclusive', () => {
    const step = document.createElement('section');
    step.className = 'pending failed';

    markTaskStepRunning(step);
    expect(step.className).toBe('running');
    markTaskStepDone(step);
    expect(step.className).toBe('done');
    markTaskStepFailed(step);
    expect(step.className).toBe('failed');
  });

  it('reuses singleton rows and keeps unlabelled rows internal', () => {
    const card = createCard();
    const step = ensureTaskStep(card, 'run', '任务状态');
    const internal = appendTaskStepRow(step, 'debug', '内部信息');
    const first = upsertTaskStepSingletonRow(
      step,
      'stream-issue',
      'warn',
      '首次同步提示',
    );
    const second = upsertTaskStepSingletonRow(
      step,
      'stream-issue',
      'info',
      '同步已恢复',
    );

    expect(internal.dataset.taskDetailVisibility).toBe('internal');
    expect(second).toBe(first);
    expect(step.querySelectorAll('[data-role="stream-issue"]')).toHaveLength(1);
    expect(second?.className).toBe('wa-task-row info');
    expect(second?.textContent).toBe('同步已恢复');
  });

  it('updates card status and removes empty step containers', () => {
    const card = createCard();
    const step = ensureTaskStep(card, 'run', '任务状态');
    upsertTaskStepSingletonRow(step, 'wait', 'info', '仍在处理');

    setTaskStatus(card, '处理中');
    removeTaskStepRow(card, 'run', 'wait');

    expect(card.querySelector('[data-role="status"]')?.textContent).toBe('处理中');
    expect(card.querySelector('[data-step-id="run"]')).toBeNull();
  });
});
