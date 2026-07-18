export interface FileTaskEventState {
  processedEventKeys: Set<string>;
  lastEventRunId: string;
  lastEventSeq: number;
}

export type FileTaskEventHandler<Card> = (
  _card: Card,
  _event: Record<string, any>,
  _payload: Record<string, any>,
) => void;

export interface FileTaskDispatchOptions<Card, State extends FileTaskEventState> {
  handlers: Record<string, FileTaskEventHandler<Card>>;
  getState: (_card: Card) => State;
  noteStreamIssue?: (_card: Card, _key: string, _text: string) => void;
  afterDispatch?: (_card: Card, _event: Record<string, any>) => void;
}

export interface FileTaskEventControllerOptions<
  Card,
  State extends FileTaskEventState,
> extends FileTaskDispatchOptions<Card, State> {
  isActive: (_card: Card) => boolean;
  prepareActive: (_card: Card) => void;
  startHeartbeat: (_card: Card) => void;
  markActivity: (_card: Card) => void;
}

export interface FileTaskEventController<Card> {
  dispatchEvent: (_card: Card, _event: Record<string, any>) => void;
  processEvent: (_card: Card, _event: Record<string, any>) => void;
}

export function fileTaskEventSequence(
  event: Record<string, any>,
  payload: Record<string, any>,
): number {
  const raw = event.seq || event.event_seq || payload.seq || payload.event_seq || 0;
  const sequence = Number(raw);
  return Number.isFinite(sequence) ? sequence : 0;
}

export function dispatchFileTaskEvent<Card, State extends FileTaskEventState>(
  card: Card,
  event: Record<string, any>,
  options: FileTaskDispatchOptions<Card, State>,
): boolean {
  if (!card || !event || typeof event !== 'object') return false;

  const eventType = String(event.type || '').trim().toLowerCase();
  const handler = eventType ? options.handlers[eventType] : undefined;
  if (!handler) return false;

  const payload = event.payload || event;
  const state = options.getState(card);
  const runId = String(event.run_id || payload.run_id || '').trim();
  const seq = fileTaskEventSequence(event, payload);
  const eventKey = `${runId}:${eventType}:${seq}`;

  if (runId && state.lastEventRunId && state.lastEventRunId !== runId) {
    state.processedEventKeys.clear();
    state.lastEventSeq = 0;
  }
  if (runId && seq > 0) {
    if (state.processedEventKeys.has(eventKey)) {
      options.noteStreamIssue?.(
        card,
        `duplicate-event-${eventKey}`,
        'Duplicate progress event merged.',
      );
      return false;
    }
    if (state.lastEventSeq > 0 && seq <= state.lastEventSeq) {
      options.noteStreamIssue?.(
        card,
        `out-of-order-event-${runId}-${seq}`,
        'Progress event arrived out of order.',
      );
    } else if (state.lastEventSeq > 0 && seq > state.lastEventSeq + 1) {
      options.noteStreamIssue?.(
        card,
        `missing-event-${runId}-${state.lastEventSeq}-${seq}`,
        'Progress event sequence has a gap.',
      );
    }
  }

  state.lastEventRunId = runId;
  state.lastEventSeq = Math.max(state.lastEventSeq, seq);
  state.processedEventKeys.add(eventKey);
  handler(card, event, payload);
  options.afterDispatch?.(card, event);
  return true;
}

export function createFileTaskEventController<
  Card,
  State extends FileTaskEventState,
>(
  options: FileTaskEventControllerOptions<Card, State>,
): FileTaskEventController<Card> {
  const dispatchEvent = (card: Card, event: Record<string, any>): void => {
    dispatchFileTaskEvent(card, event, options);
  };

  const processEvent = (card: Card, event: Record<string, any>): void => {
    if (!card || !event || typeof event !== 'object') return;
    if (!options.isActive(card)) {
      options.prepareActive(card);
      options.startHeartbeat(card);
    }
    options.markActivity(card);
    dispatchEvent(card, event);
  };

  return { dispatchEvent, processEvent };
}
