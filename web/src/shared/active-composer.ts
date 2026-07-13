/**
 * The only supported way for cross-feature UI to reach Koto's active composer.
 * The workspace composer is authoritative whenever it is visible; the legacy
 * chat composer remains a narrow fallback while its view is still retained.
 */

export type KotoComposerInput = HTMLInputElement | HTMLTextAreaElement;

function isVisible(element: HTMLElement | null): element is HTMLElement {
  if (!element) return false;
  const style = window.getComputedStyle(element);
  return style.display !== 'none' && style.visibility !== 'hidden' && element.getClientRects().length > 0;
}

export function getActiveKotoComposer(): KotoComposerInput | null {
  const workspaceInput = document.getElementById('wa-user-input') as HTMLTextAreaElement | null;
  if (isVisible(workspaceInput)) return workspaceInput;

  const legacyInput = document.getElementById('messageInput') as HTMLTextAreaElement | null;
  if (isVisible(legacyInput)) return legacyInput;

  return document.querySelector('.chat-input textarea, textarea[placeholder]') as KotoComposerInput | null;
}

export function getActiveKotoMessageContainer(): HTMLElement | null {
  const composer = getActiveKotoComposer();
  if (composer?.id === 'wa-user-input') {
    return document.getElementById('wa-ai-messages');
  }
  return document.getElementById('chatMessages')
    || document.querySelector<HTMLElement>('.messages-container, .chat-messages');
}

export function setActiveKotoComposerText(
  text: string,
  options: { focus?: boolean; flash?: boolean } = {},
): KotoComposerInput | null {
  const input = getActiveKotoComposer();
  if (!input) return null;

  const prototype = input instanceof HTMLTextAreaElement
    ? window.HTMLTextAreaElement.prototype
    : window.HTMLInputElement.prototype;
  const nativeSetter = Object.getOwnPropertyDescriptor(prototype, 'value');
  if (nativeSetter?.set) nativeSetter.set.call(input, text);
  else input.value = text;
  input.dispatchEvent(new Event('input', { bubbles: true }));

  if (options.focus !== false) {
    input.focus();
    try { input.setSelectionRange(text.length, text.length); } catch (_) { /* noop */ }
  }
  if (options.flash !== false) {
    input.classList.add('input-flash');
    window.setTimeout(() => input.classList.remove('input-flash'), 800);
  }
  return input;
}

export function submitActiveKotoComposerText(text: string): boolean {
  const input = setActiveKotoComposerText(text);
  if (!input) return false;

  if (input.id === 'wa-user-input') {
    const workspace = (window as any).WA || {};
    if (typeof workspace.submitUnifiedAiComposer === 'function') {
      workspace.submitUnifiedAiComposer();
      return true;
    }
    if (typeof workspace.sendMessage === 'function') {
      workspace.sendMessage();
      return true;
    }
  }

  const sendButton = document.querySelector('#sendBtn, [data-role="send-button"], button[type="submit"]') as HTMLElement | null;
  if (sendButton) {
    sendButton.click();
    return true;
  }
  input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
  return true;
}
