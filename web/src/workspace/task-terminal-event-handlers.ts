import { normalizeFileTaskTerminalStatus } from './file-task-status';
import { normalizedTaskLifecyclePayload } from './task-lifecycle-payload';

export interface TaskTerminalEventCard extends HTMLElement {
  _fatalErrorText?: string;
}

export type TaskTerminalEventHandler<TCard extends TaskTerminalEventCard> = (
  _card: TCard,
  _event: Record<string, any>,
  _payload: Record<string, any>,
) => void;

export interface TaskTerminalEventRuntime<TCard extends TaskTerminalEventCard> {
  finish: TaskTerminalEventHandler<TCard>;
}

export function createTaskTerminalEventHandlers<TCard extends TaskTerminalEventCard>(
  runtime: TaskTerminalEventRuntime<TCard>,
): Record<string, TaskTerminalEventHandler<TCard>> {
  const handleCancelled: TaskTerminalEventHandler<TCard> = (card, evt, payload) => {
    card.dataset.taskTerminalStatus = 'cancelled';
    card.dataset.taskCompleted = 'false';
    runtime.finish(card, evt, {
      ...(payload || {}),
      text: payload && payload.text ? payload.text : '任务已被取消。',
    });
  };

  const handleError: TaskTerminalEventHandler<TCard> = (card, evt, payload) => {
    const data = normalizedTaskLifecyclePayload(payload);
    const failure = data.failure && typeof data.failure === 'object' ? data.failure : {};
    const failureStatus = normalizeFileTaskTerminalStatus(
      failure.status || data.status || 'failed',
    ) || 'failed';
    const failureText = String(
      failure.summary || data.error || data.text || data.message || '任务执行出错。',
    ).trim();
    card.dataset.taskTerminalStatus = failureStatus;
    card.dataset.taskCompleted = 'false';
    card._fatalErrorText = failureText;
    runtime.finish(card, evt, {
      ...(payload || {}),
      summary: failureText,
      completed_task: false,
      runtime: { ...(data.runtime || {}), terminal_status: failureStatus },
      failure,
    });
  };

  return {
    'run.cancelled': handleCancelled,
    error: handleError,
  };
}
