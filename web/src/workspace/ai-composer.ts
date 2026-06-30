/**
 * Shared workspace AI composer helpers.
 * The workspace owns one real composer DOM node and mounts it between views.
 */

export type WorkspaceAiComposerKind = 'chat' | 'sessionList';

interface ComposerConfig {
  inputId: string;
  sendButtonId: string;
  hostId: string;
  placeholder: string;
  sendTitle: string;
  fallbackMaxHeight: number;
}

const COMPOSERS: Record<WorkspaceAiComposerKind, ComposerConfig> = {
  chat: {
    inputId: 'wa-user-input',
    sendButtonId: 'wa-send-btn',
    hostId: 'wa-chat-composer-host',
    placeholder: '输入问题，或让 Koto 处理当前文件',
    sendTitle: '发送',
    fallbackMaxHeight: 180,
  },
  sessionList: {
    inputId: 'wa-user-input',
    sendButtonId: 'wa-send-btn',
    hostId: 'wa-session-list-composer-host',
    placeholder: '输入问题，新建对话',
    sendTitle: '发送并新建对话',
    fallbackMaxHeight: 180,
  },
};

function configFor(kind: WorkspaceAiComposerKind): ComposerConfig {
  return COMPOSERS[kind] || COMPOSERS.chat;
}

export function getWorkspaceAiComposerInput(kind: WorkspaceAiComposerKind = 'chat'): HTMLTextAreaElement | null {
  return document.getElementById(configFor(kind).inputId) as HTMLTextAreaElement | null;
}

export function getWorkspaceAiComposerSendButton(kind: WorkspaceAiComposerKind = 'chat'): HTMLButtonElement | null {
  return document.getElementById(configFor(kind).sendButtonId) as HTMLButtonElement | null;
}

export function workspaceAiComposerMode(): WorkspaceAiComposerKind {
  const area = document.getElementById('wa-ai-input-area');
  if (area && area.parentElement && area.parentElement.id === COMPOSERS.sessionList.hostId) {
    return 'sessionList';
  }
  const listView = document.getElementById('wa-ai-session-list-view');
  return listView && !listView.hidden ? 'sessionList' : 'chat';
}

export function visibleWorkspaceAiComposerKind(): WorkspaceAiComposerKind {
  return workspaceAiComposerMode();
}

export function getVisibleWorkspaceAiComposerInput(): HTMLTextAreaElement | null {
  return getWorkspaceAiComposerInput();
}

export function mountWorkspaceAiComposer(kind: WorkspaceAiComposerKind): void {
  const config = configFor(kind);
  const host = document.getElementById(config.hostId);
  const area = document.getElementById('wa-ai-input-area');
  if (host && area && area.parentElement !== host) {
    host.appendChild(area);
  }
  const input = getWorkspaceAiComposerInput();
  if (input) {
    input.placeholder = config.placeholder;
    input.dataset.composerMode = kind;
    resizeWorkspaceAiComposer(input);
  }
  const button = getWorkspaceAiComposerSendButton();
  if (button) {
    button.title = config.sendTitle;
    button.setAttribute('aria-label', config.sendTitle);
  }
  syncWorkspaceAiComposerSendState(kind);
}

export function resizeWorkspaceAiComposer(
  inputOrKind: HTMLTextAreaElement | WorkspaceAiComposerKind | null,
): void {
  const input = typeof inputOrKind === 'string'
    ? getWorkspaceAiComposerInput(inputOrKind)
    : inputOrKind;
  if (!input) return;
  const cssMaxHeight = parseFloat(window.getComputedStyle(input).maxHeight || '');
  const maxHeight = Number.isFinite(cssMaxHeight) && cssMaxHeight > 0
    ? cssMaxHeight
    : configFor(workspaceAiComposerMode()).fallbackMaxHeight;
  input.style.height = 'auto';
  input.style.height = Math.min(input.scrollHeight, maxHeight) + 'px';
  input.style.overflowY = input.scrollHeight > maxHeight ? 'auto' : 'hidden';
}

export function setWorkspaceAiComposerValue(
  kind: WorkspaceAiComposerKind,
  text: string,
  options: { focus?: boolean; dispatchInput?: boolean } = {},
): HTMLTextAreaElement | null {
  const input = getWorkspaceAiComposerInput(kind);
  if (!input) return null;
  input.value = text;
  resizeWorkspaceAiComposer(input);
  if (options.dispatchInput !== false) {
    input.dispatchEvent(new Event('input', { bubbles: true }));
  }
  if (options.focus !== false) {
    try {
      input.focus();
      const len = input.value.length;
      input.setSelectionRange(len, len);
    } catch (_) { /* noop */ }
  }
  return input;
}

export function focusWorkspaceAiComposer(kind: WorkspaceAiComposerKind = 'chat'): void {
  const input = getWorkspaceAiComposerInput(kind);
  if (!input) return;
  try {
    input.focus();
    const len = input.value.length;
    input.setSelectionRange(len, len);
  } catch (_) { /* noop */ }
}

export function syncWorkspaceAiComposerSendState(kind: WorkspaceAiComposerKind): void {
  const input = getWorkspaceAiComposerInput();
  const button = getWorkspaceAiComposerSendButton();
  if (!button) return;
  button.disabled = !input || input.disabled || (kind === 'sessionList' && !input.value.trim());
}
