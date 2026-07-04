export interface SseParseResult {
  events: Record<string, any>[];
  remainder: string;
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
