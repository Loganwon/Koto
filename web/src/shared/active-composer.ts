/**
 * The only supported way for cross-feature UI to reach Koto's AI composer.
 * The unified workspace composer is the single desktop owner.
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
  return null;
}

export function getActiveKotoMessageContainer(): HTMLElement | null {
  return document.getElementById('wa-ai-messages');
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

  const workspace = (window as any).WA || {};
  if (typeof workspace.submitUnifiedAiComposer === 'function') {
    workspace.submitUnifiedAiComposer();
    return true;
  }
  if (typeof workspace.sendMessage === 'function') {
    workspace.sendMessage();
    return true;
  }
  return false;
}
