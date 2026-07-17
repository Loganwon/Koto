import { describe, expect, it, vi } from 'vitest';
import { createTaskVerificationEventHandlers } from './task-verification-event-handlers';

function runtime() {
  const step = document.createElement('section');
  return {
    step,
    taskStageStep: vi.fn(() => step),
    markStepDone: vi.fn(),
    markStepRunning: vi.fn(),
    markStepFailed: vi.fn(),
    setRunContext: vi.fn(),
    upsertStepRow: vi.fn(() => document.createElement('div')),
  };
}

describe('task verification event handlers', () => {
  it('keeps successful step rollups compact', () => {
    const card = document.createElement('article');
    const host = runtime();
    const handlers = createTaskVerificationEventHandlers(host);
    handlers['step.result'](card, { step_id: 'execute' }, {
      status: 'completed', summary: '写入完成',
    });
    expect(host.markStepDone).toHaveBeenCalledWith(host.step);
    expect(host.upsertStepRow).not.toHaveBeenCalled();
  });

  it('surfaces failed step evidence once', () => {
    const card = document.createElement('article');
    const host = runtime();
    const handlers = createTaskVerificationEventHandlers(host);
    handlers['step.result'](card, { step_id: 'check' }, {
      status: 'verify_error', summary: '<b>核验失败</b>',
    });
    expect(host.markStepFailed).toHaveBeenCalledWith(host.step);
    expect(host.upsertStepRow).toHaveBeenCalledWith(
      host.step,
      expect.stringContaining('step.result:check'),
      'warn',
      expect.stringContaining('&lt;b&gt;核验失败&lt;/b&gt;'),
    );
  });

  it('keeps confirmation checks running and visible', () => {
    const card = document.createElement('article');
    const host = runtime();
    const handlers = createTaskVerificationEventHandlers(host);
    handlers['check.finished'](card, {}, {
      status: 'awaiting_confirmation', passed: false,
    });
    expect(host.setRunContext).toHaveBeenCalledWith(card, {}, expect.any(Object));
    expect(host.markStepRunning).toHaveBeenCalledWith(host.step);
    expect(host.upsertStepRow).toHaveBeenCalledWith(
      host.step,
      'check.finished',
      'progress',
      expect.stringContaining('待确认'),
    );
  });
});
