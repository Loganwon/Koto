export interface SseParseResult {
  events: Record<string, any>[];
  remainder: string;
}

export function persistedTaskStreamEvent(event: Record<string, any>): Record<string, any> {
  const nested = event && event.detail && typeof event.detail === 'object'
    ? (event.detail as Record<string, any>).event
    : null;
  if (nested && typeof nested === 'object' && String((nested as Record<string, any>).type || '').trim()) {
    return {
      ...(event.event_id ? { event_id: event.event_id } : {}),
      ...(event.run_id ? { run_id: event.run_id } : {}),
      ...(event.seq ? { seq: event.seq } : {}),
      ...nested as Record<string, any>,
    };
  }
  return event;
}

export function isTaskStreamTerminalEvent(event: Record<string, any>): boolean {
  const type = String(event && event.type || '').trim();
  const payload = event.payload || event;
  return type === 'run.finished' || type === 'run.cancelled' || type === 'task_final'
    || type === 'done' || (type === 'error' && payload.recoverable !== true);
}

export function parseSseEvents(buffer: string, flush: boolean): SseParseResult {
  const source = String(buffer || '').replace(/\r\n/g, '\n');
  const frames = source.split('\n\n');
  const remainder = flush ? '' : (frames.pop() || '');
  const completeFrames = flush ? frames.filter((frame) => frame.trim()) : frames;
  const events: Record<string, any>[] = [];
  completeFrames.forEach((frame) => {
    const lines = String(frame || '').split('\n');
    const dataLines = lines
      .filter((line) => line.startsWith('data:'))
      .map((line) => line.replace(/^data:\s?/, ''));
    if (!dataLines.length) return;
    try {
      const parsed = JSON.parse(dataLines.join('\n'));
      const id = lines.find((line) => line.startsWith('id:'))?.replace(/^id:\s?/, '');
      if (id && parsed && typeof parsed === 'object') {
        parsed.event_id ??= id;
        const split = id.lastIndexOf(':');
        if (split > 0 && /^\d+$/.test(id.slice(split + 1))) {
          parsed.run_id ??= id.slice(0, split);
          parsed.seq ??= Number(id.slice(split + 1));
        }
      }
      events.push(parsed);
    } catch {
      // Ignore malformed frames; the stream may continue with later valid data.
    }
  });
  return { events, remainder };
}
