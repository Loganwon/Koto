/** One text reducer shared by chat and the task workbench. */
export interface TaskMessageStreamState {
  messages: Map<string, { text: string; status: string }>;
  activeMessageId: string;
  text: string;
  canonical: boolean;
  terminal: boolean;
  terminalStatus: string;
  lastSeqByRun: Map<string, number>;
  runStarted: boolean;
  errorMessage: string;
}

export function createTaskMessageStreamState(text = ''): TaskMessageStreamState {
  return {
    messages: new Map(), activeMessageId: '', text, canonical: false,
    terminal: false, terminalStatus: '', lastSeqByRun: new Map(), runStarted: false, errorMessage: '',
  };
}

export function applyTaskMessageStreamEvent(
  state: TaskMessageStreamState,
  event: Record<string, any>,
  onAccepted?: () => void,
): boolean {
  const type = String(event.type || '');
  if (state.terminal) return false;
  const data = event.payload && typeof event.payload === 'object' ? event.payload : event;
  const runId = String(event.run_id || data.run_id || '');
  const seq = Number(event.seq || data.seq || 0);
  if (runId && seq > 0) {
    const previous = state.lastSeqByRun.get(runId) || 0;
    if (seq <= previous) return false;
    if (previous && seq > previous + 1) throw new Error('任务进度存在缺口，需要重新同步');
    state.lastSeqByRun.set(runId, seq);
    if (state.lastSeqByRun.size > 8) state.lastSeqByRun.delete(state.lastSeqByRun.keys().next().value!);
  }
  onAccepted?.();
  const before = state.text;
  if (type === 'run.started') state.runStarted = true;
  else if (['message.started', 'message.delta', 'message.finished'].includes(type)) {
    state.canonical = true;
    const id = String(data.message_id || event.message_id || data.attempt_id || 'answer');
    const message = state.messages.get(id) || { text: '', status: 'generating' };
    if (type === 'message.started') {
      if (!state.messages.has(id)) message.text = '';
      state.activeMessageId = id;
    } else if (type === 'message.delta') {
      message.text += String(data.delta ?? data.content ?? data.text ?? '');
      state.activeMessageId = id;
    } else if (type === 'message.finished') {
      const finalText = data.text ?? data.content;
      if (finalText !== undefined) message.text = String(finalText);
      message.status = String(data.status || 'completed');
      state.activeMessageId = id;
    }
    state.messages.set(id, message);
    while (state.messages.size > 16) state.messages.delete(state.messages.keys().next().value!);
    state.text = message.text;
  } else if (type === 'token' && !state.canonical) {
    state.text += String(data.content ?? data.text ?? '');
  } else if (type === 'agent_step' && !state.canonical) {
    const step = event.data || data.data || data;
    if (String(step.step_type || '').toLowerCase() === 'answer') {
      state.text = String(step.content || '');
    }
  } else if (type === 'task_final') {
    const result = event.data || data.data || data;
    if (typeof result.result === 'string' && (result.result || !state.text)) state.text = result.result;
    state.terminal = true;
    state.terminalStatus = String(result.status || 'success');
  } else if (type === 'run.finished' || type === 'run.cancelled') {
    if (typeof data.result === 'string' && (data.result || !state.text)) state.text = data.result;
    state.terminal = true;
    state.terminalStatus = String(data.terminal_status || data.status || data.state
      || (type === 'run.cancelled' ? 'cancelled' : 'completed'));
  } else if (type === 'done') {
    state.terminal = true;
    state.terminalStatus ||= String(data.status || 'completed');
  } else if (type === 'error' && data.recoverable !== true) {
    state.errorMessage = String(data.message || data.text || '任务失败');
    if (state.runStarted) return before !== state.text;
    state.terminal = true;
    state.terminalStatus = 'failed';
    throw new Error(state.errorMessage);
  }
  return before !== state.text;
}

/** Keep live text cheap and stable; render full Markdown once the segment ends. */
export function createStreamingTextRenderer(
  element: HTMLElement,
  renderFinal: (text: string) => string,
  onRendered?: () => void,
): { update: (text: string, final?: boolean) => void; dispose: () => void } {
  let timer: ReturnType<typeof setTimeout> | undefined;
  let pending = '';
  let disposed = false;
  const flush = (final = false): void => {
    if (timer !== undefined) clearTimeout(timer);
    timer = undefined;
    element.dataset.rawText = pending;
    if (final && pending.length <= 250_000) element.innerHTML = renderFinal(pending);
    else element.textContent = pending;
    element.classList.toggle('wa-stream-text', !final);
    onRendered?.();
  };
  return {
    update: (text, final = false) => {
      pending = text;
      if (disposed) return;
      if (final) flush(true);
      else if (timer === undefined) timer = setTimeout(() => flush(), pending.length > 100_000 ? 96 : 32);
    },
    dispose: () => { disposed = true; pending = ''; if (timer !== undefined) clearTimeout(timer); },
  };
}
