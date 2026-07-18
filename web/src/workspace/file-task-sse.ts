export interface SseParseResult {
  events: Record<string, any>[];
  remainder: string;
}

export function persistedTaskStreamEvent(event: Record<string, any>): Record<string, any> {
  const nested = event && event.detail && typeof event.detail === 'object'
    ? (event.detail as Record<string, any>).event
    : null;
  return nested && typeof nested === 'object' && String((nested as Record<string, any>).type || '').trim()
    ? nested as Record<string, any>
    : event;
}

export function isTaskStreamTerminalEvent(event: Record<string, any>): boolean {
  const type = String(event && event.type || '').trim();
  return type === 'run.finished' || type === 'run.cancelled' || type === 'error';
}

export function parseSseEvents(buffer: string, flush: boolean): SseParseResult {
  const source = String(buffer || '').replace(/\r\n/g, '\n');
  const frames = source.split('\n\n');
  const remainder = flush ? '' : (frames.pop() || '');
  const completeFrames = flush ? frames.filter((frame) => frame.trim()) : frames;
  const events: Record<string, any>[] = [];
  completeFrames.forEach((frame) => {
    const dataLines = String(frame || '')
      .split('\n')
      .filter((line) => line.startsWith('data:'))
      .map((line) => line.replace(/^data:\s?/, ''));
    if (!dataLines.length) return;
    try {
      events.push(JSON.parse(dataLines.join('\n')));
    } catch {
      // Ignore malformed frames; the stream may continue with later valid data.
    }
  });
  return { events, remainder };
}
