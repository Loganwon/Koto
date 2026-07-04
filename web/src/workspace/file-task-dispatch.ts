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
  afterDispatch?: (_card: Card) => void;
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
  const seq = Number(event.seq || payload.seq || 0);
  const eventKey = `${runId}:${eventType}:${seq}`;

  if (runId && state.lastEventRunId && state.lastEventRunId !== runId) {
    state.processedEventKeys.clear();
    state.lastEventSeq = 0;
  }
  state.lastEventRunId = runId;

  if (runId && seq > 0 && state.lastEventSeq >= seq && state.processedEventKeys.has(eventKey)) {
    return false;
  }

  state.lastEventSeq = Math.max(state.lastEventSeq, seq);
  state.processedEventKeys.add(eventKey);
  handler(card, event, payload);
  options.afterDispatch?.(card);
  return true;
}
