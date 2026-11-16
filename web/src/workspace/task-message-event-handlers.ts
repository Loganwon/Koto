import { applyTaskMessageStreamEvent, createTaskMessageStreamState, createStreamingTextRenderer } from './task-message-stream';
import { renderWorkspaceMarkdown } from './markdown-rendering';

export function createTaskMessageEventHandlers<TCard extends HTMLElement>(): Record<
  string, (_card: TCard, _event: Record<string, any>, _payload: Record<string, any>) => void
> {
  const states = new WeakMap<TCard, ReturnType<typeof createTaskMessageStreamState>>();
  const renderers = new WeakMap<TCard, ReturnType<typeof createStreamingTextRenderer>>();
  const handle = (card: TCard, event: Record<string, any>, payload: Record<string, any>): void => {
    let text = card.querySelector<HTMLElement>('[data-role="live-answer"]');
    if (!text) {
      text = document.createElement('div');
      text.dataset.role = 'live-answer';
      text.className = 'wa-task-live-answer';
      text.setAttribute('aria-label', '正在生成的回答');
      const process = card.querySelector('[data-role="process"]');
      card.insertBefore(text, process);
    }
    let state = states.get(card);
    if (!state) {
      state = createTaskMessageStreamState(text.dataset.rawText || '');
      if (text.dataset.messageId) {
        state.activeMessageId = text.dataset.messageId;
        state.messages.set(state.activeMessageId, { text: state.text, status: 'generating' });
      }
      states.set(card, state);
    }
    let renderer = renderers.get(card);
    if (!renderer) {
      renderer = createStreamingTextRenderer(text, renderWorkspaceMarkdown);
      renderers.set(card, renderer);
    }
    applyTaskMessageStreamEvent(state, { ...event, payload });
    text.dataset.messageId = state.activeMessageId;
    text.dataset.rawText = state.text;
    text.dataset.status = String(payload.status || 'generating');
    text.hidden = !state.text;
    renderer.update(state.text, event.type === 'message.finished');
  };
  return {
    'message.started': handle,
    'message.delta': handle,
    'message.finished': handle,
  };
}
