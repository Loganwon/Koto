import { describe, expect, it, vi } from 'vitest';
import {
  createFileTaskEventController,
  dispatchFileTaskEvent,
  fileTaskEventSequence,
} from './file-task-dispatch';

function createState() {
  return {
    processedEventKeys: new Set<string>(),
    lastEventRunId: '',
    lastEventSeq: 0,
  };
}

describe('file task event dispatch', () => {
  it('normalizes seq and event_seq through one sequence contract', () => {
    expect(fileTaskEventSequence({ event_seq: '7' }, {})).toBe(7);
    expect(fileTaskEventSequence({}, { seq: 8 })).toBe(8);
    expect(fileTaskEventSequence({ seq: 'invalid' }, {})).toBe(0);
  });

  it('merges duplicates and reports gaps and out-of-order events once', () => {
    const card = document.createElement('article');
    const state = createState();
    const handler = vi.fn();
    const noteStreamIssue = vi.fn();
    const options = {
      handlers: {
        'step.started': handler,
        'step.finished': handler,
      },
      getState: () => state,
      noteStreamIssue,
    };

    expect(dispatchFileTaskEvent(card, {
      type: 'step.started',
      run_id: 'run-1',
      event_seq: 1,
    }, options)).toBe(true);
    expect(dispatchFileTaskEvent(card, {
      type: 'step.started',
      run_id: 'run-1',
      event_seq: 1,
    }, options)).toBe(false);
    expect(dispatchFileTaskEvent(card, {
      type: 'step.finished',
      run_id: 'run-1',
      event_seq: 3,
    }, options)).toBe(true);
    expect(dispatchFileTaskEvent(card, {
      type: 'step.finished',
      run_id: 'run-1',
      event_seq: 2,
    }, options)).toBe(true);

    expect(handler).toHaveBeenCalledTimes(3);
    expect(noteStreamIssue).toHaveBeenCalledWith(
      card,
      'duplicate-event-run-1:step.started:1',
      'Duplicate progress event merged.',
    );
    expect(noteStreamIssue).toHaveBeenCalledWith(
      card,
      'missing-event-run-1-1-3',
      'Progress event sequence has a gap.',
    );
    expect(noteStreamIssue).toHaveBeenCalledWith(
      card,
      'out-of-order-event-run-1-2',
      'Progress event arrived out of order.',
    );
  });

  it('resets dedupe state when a new run starts', () => {
    const card = document.createElement('article');
    const state = createState();
    const handler = vi.fn();
    const options = {
      handlers: { 'run.started': handler },
      getState: () => state,
    };

    dispatchFileTaskEvent(card, {
      type: 'run.started', run_id: 'run-1', seq: 1,
    }, options);
    dispatchFileTaskEvent(card, {
      type: 'run.started', run_id: 'run-2', seq: 1,
    }, options);

    expect(handler).toHaveBeenCalledTimes(2);
    expect(state.lastEventRunId).toBe('run-2');
    expect(state.lastEventSeq).toBe(1);
    expect(state.processedEventKeys).toEqual(
      new Set(['run-2:run.started:1']),
    );
  });

  it('owns activation, activity tracking and post-dispatch projection', () => {
    const card = document.createElement('article');
    const state = createState();
    let active = false;
    const handler = vi.fn();
    const prepareActive = vi.fn(() => { active = true; });
    const startHeartbeat = vi.fn();
    const markActivity = vi.fn();
    const afterDispatch = vi.fn();
    const controller = createFileTaskEventController({
      handlers: { 'run.started': handler },
      getState: () => state,
      isActive: () => active,
      prepareActive,
      startHeartbeat,
      markActivity,
      afterDispatch,
    });
    const event = { type: 'run.started', run_id: 'run-1', seq: 1 };

    controller.processEvent(card, event);
    controller.processEvent(card, { ...event, seq: 2 });

    expect(prepareActive).toHaveBeenCalledTimes(1);
    expect(startHeartbeat).toHaveBeenCalledTimes(1);
    expect(markActivity).toHaveBeenCalledTimes(2);
    expect(handler).toHaveBeenCalledTimes(2);
    expect(afterDispatch).toHaveBeenLastCalledWith(card, { ...event, seq: 2 });
  });
});
