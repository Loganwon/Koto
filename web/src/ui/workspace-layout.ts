/** The document stays on screen while its AI assistant opens alongside it. */
import { getFeatureRegistry, registerFeatures } from '../shared/feature-registry';
import { state } from '../workspace/state';
import { showToast } from '../workspace/infrastructure';
import { initWorkspaceMaterials, showTaskMaterials, syncWorkspaceMaterials } from './workspace-materials';

let initialized = false;
let assistantOpen = false;
let filesTrigger: HTMLElement | null = null;

export function refreshWorkspaceLayout(): void {
  requestAnimationFrame(() => {
    if (assistantOpen && state.fileType === 'docx') {
      const editor = state.activeEditor;
      const viewport = document.getElementById('wa-editor-content');
      const page = document.querySelector<HTMLElement>('#wa-docx-editor .ProseMirror');
      const pageWidth = Number(editor?._pageWidthPx) || page?.offsetWidth || 0;
      const available = (viewport?.clientWidth || 0) - 32;
      if (pageWidth > 0 && available > 0 && typeof editor?.setZoom === 'function') {
        const fit = Math.max(50, Math.min(100, Math.floor(available / pageWidth * 100)));
        if (Number(editor._zoom || 100) > fit) {
          editor.setZoom(fit);
          getFeatureRegistry()._updateDocxZoomUI?.(fit);
        }
      }
    }
    const refresh = state.activeEditor?.refreshLayout;
    if (typeof refresh === 'function') refresh.call(state.activeEditor);
    else if (state.fileType === 'pptx' && document.getElementById('wa-canvas')?.offsetWidth) {
      const render = state.activeEditor?._renderSlide;
      if (typeof render === 'function') render.call(state.activeEditor, state.activeEditor?._curIdx || 0);
    }
    window.dispatchEvent(new CustomEvent('koto-workspace-layout-change'));
  });
}

function syncDocumentButton(): void {
  const button = document.getElementById('koto-document-toggle');
  if (!button) return;
  const workspace = document.getElementById('workspaceView');
  workspace?.toggleAttribute('data-has-document', !!state.fileId);
  button.hidden = !state.fileId || workspace?.dataset.layout === 'document';
  button.textContent = '文档工作区';
  button.title = '返回文档工作区';
  document.querySelectorAll('[data-koto-shell-action="assistant"]').forEach((entry) => {
    entry.setAttribute('aria-expanded', String(assistantOpen));
  });
  const scope = document.getElementById('koto-ai-document-name');
  if (scope) {
    scope.textContent = state.fileName || '打开文档后，可直接编辑当前内容';
    scope.title = state.fileName || '';
  }
  const input = document.getElementById('wa-user-input') as HTMLTextAreaElement | null;
  if (input) input.placeholder = state.fileId
    ? '描述要怎样修改，或选中文字后提问…' : '描述任务，或打开文档开始编辑…';
}

export function showConversationLayout(): void {
  const workspace = document.getElementById('workspaceView');
  if (!workspace) return;
  // Opening a task must never replace an open editor.
  workspace.dataset.layout = state.fileId ? 'document' : 'conversation';
  assistantOpen = true;
  workspace.setAttribute('data-ai-open', '');
  syncLayoutA11y();
  syncDocumentButton();
  refreshWorkspaceLayout();
}

export function showDocumentLayout(): void {
  const workspace = document.getElementById('workspaceView');
  if (!workspace) return;
  if (!state.fileId) { showConversationLayout(); return; }
  workspace.dataset.layout = 'document';
  workspace.toggleAttribute('data-ai-open', assistantOpen);
  if (assistantOpen && state.fileType === 'docx') getFeatureRegistry()._toggleDocOutline?.(false);
  getFeatureRegistry().closeMobileFiles?.();
  syncLayoutA11y();
  syncDocumentButton();
  refreshWorkspaceLayout();
}

function syncLayoutA11y(): void {
  const workspace = document.getElementById('workspaceView');
  const documentOpen = workspace?.dataset.layout === 'document';
  const ai = document.getElementById('wa-ai');
  const canvas = document.getElementById('wa-canvas');
  const aiHidden = !!documentOpen && !assistantOpen;
  if (ai) { ai.inert = aiHidden; ai.setAttribute('aria-hidden', String(aiHidden)); }
  if (canvas) { canvas.inert = !documentOpen; canvas.setAttribute('aria-hidden', String(!documentOpen)); }
  const sidebar = document.getElementById('sideNav');
  const sidebarHidden = document.body.classList.contains('koto-layout-phone')
    && !document.body.classList.contains('koto-nav-open');
  if (sidebar) sidebar.inert = sidebarHidden;
  document.querySelectorAll('[data-koto-shell-action="navigation"]').forEach((button) => {
    const expanded = document.body.classList.contains('koto-layout-phone')
      ? !sidebarHidden : !document.querySelector('.app-shell')?.classList.contains('koto-nav-collapsed');
    button.setAttribute('aria-expanded', String(expanded));
  });
}

export function toggleAiPanel(): void {
  const workspace = document.getElementById('workspaceView');
  if (!workspace) return;
  if (!state.fileId) { showConversationLayout(); return; }
  assistantOpen = workspace.dataset.layout === 'document' ? !assistantOpen : false;
  workspace.dataset.layout = 'document';
  workspace.toggleAttribute('data-ai-open', assistantOpen);
  if (assistantOpen && state.fileType === 'docx') getFeatureRegistry()._toggleDocOutline?.(false);
  syncLayoutA11y();
  syncDocumentButton();
  refreshWorkspaceLayout();
}

export function _expandWAPanel(): void {
  const workspace = document.getElementById('workspaceView');
  if (!workspace) return;
  if (!assistantOpen && state.fileType === 'docx') getFeatureRegistry()._toggleDocOutline?.(false);
  assistantOpen = true;
  workspace.setAttribute('data-ai-open', '');
  syncLayoutA11y();
  syncDocumentButton();
  refreshWorkspaceLayout();
}

function toggleNavigation(): void {
  const phone = document.body.classList.contains('koto-layout-phone');
  if (phone) document.body.classList.toggle('koto-nav-open');
  else document.querySelector('.app-shell')?.classList.toggle('koto-nav-collapsed');
  const expanded = phone ? document.body.classList.contains('koto-nav-open')
    : !document.querySelector('.app-shell')?.classList.contains('koto-nav-collapsed');
  document.querySelectorAll('[data-koto-shell-action="navigation"]').forEach((button) => {
    button.setAttribute('aria-expanded', String(expanded));
  });
  syncLayoutA11y();
  refreshWorkspaceLayout();
}

function syncWelcome(): void {
  const messages = document.getElementById('wa-ai-messages');
  const empty = !messages?.querySelector('.wa-msg, .wa-proposal-card, .wa-task-run');
  document.getElementById('wa-ai-chat-view')?.classList.toggle('koto-conversation-empty', empty);
  const welcome = document.getElementById('wa-ai-welcome');
  if (welcome) welcome.hidden = !empty;
}

export function closeWorkspaceNavigation(): void {
  document.body.classList.remove('koto-nav-open');
  syncLayoutA11y();
}

export function initWorkspaceLayout(): void {
  if (initialized || !document.getElementById('workspaceView')) return;
  initialized = true;
  showConversationLayout();
  initWorkspaceMaterials();
  void Promise.resolve(getFeatureRegistry().loadConversationList?.()).catch(() => {
    const placeholder = document.querySelector('.koto-history-placeholder');
    if (placeholder) placeholder.textContent = '任务暂时无法加载，请刷新重试';
  });
  const messages = document.getElementById('wa-ai-messages');
  if (messages) new MutationObserver(() => {
    syncWelcome();
    // A running task, including a selection action, is always visible beside the document.
    if (!assistantOpen && messages.querySelector('.wa-msg.streaming')) _expandWAPanel();
  }).observe(messages, { childList: true });
  syncWelcome();
  if (!state.fileId && document.activeElement === document.body) {
    document.getElementById('wa-user-input')?.focus();
  }
  document.addEventListener('koto:workspace-file-change', () => {
    showConversationLayout();
    syncWorkspaceMaterials();
  });
  document.addEventListener('click', (event) => {
    const element = event.target instanceof Element ? event.target : null;
    const action = element?.closest<HTMLElement>('[data-koto-shell-action]')?.dataset.kotoShellAction;
    if (action === 'navigation') toggleNavigation();
    if (action === 'close-navigation') {
      closeWorkspaceNavigation();
    }
    if (action === 'files' || action === 'materials') {
      filesTrigger = element?.closest<HTMLElement>('[data-koto-shell-action]') || null;
      if (action === 'materials') showTaskMaterials();
      getFeatureRegistry().toggleMobileFiles?.(action === 'materials' ? true : undefined);
      if (document.body.classList.contains('wa-mobile-files-open')) {
        syncWorkspaceMaterials();
        document.querySelector<HTMLElement>('#wa-left [role="tab"][aria-selected="true"]')?.focus();
      }
    }
    if (action === 'close-files') {
      getFeatureRegistry().closeMobileFiles?.();
      (filesTrigger || document.getElementById('koto-files-toggle'))?.focus();
    }
    if (action === 'document') {
      showDocumentLayout();
    }
    if (action === 'assistant') {
      toggleAiPanel();
      const selection = window.getSelection();
      const selectedDocumentText = selection?.toString().trim()
        && document.getElementById('wa-canvas')?.contains(selection.anchorNode);
      const textEditor = document.getElementById('wa-text-content') as HTMLTextAreaElement | null;
      const selectedTextRange = textEditor && document.activeElement === textEditor
        && textEditor.selectionEnd > textEditor.selectionStart;
      if (assistantOpen && (selectedDocumentText || selectedTextRange)) getFeatureRegistry().sendSelectionToAI?.();
      else if (assistantOpen) document.getElementById('wa-user-input')?.focus();
      else document.getElementById('koto-document-ai-launcher')?.focus();
    }
    if (action === 'close-assistant') {
      if (assistantOpen) toggleAiPanel();
      document.getElementById('koto-document-ai-launcher')?.focus();
    }
    if (action === 'new') {
      const button = element?.closest<HTMLButtonElement>('button');
      if (!button || button.disabled) return;
      button.disabled = true;
      Promise.resolve(getFeatureRegistry().newAiSession?.({ toast: false }))
        .then((session) => {
          if (!session) return;
          showConversationLayout();
          getFeatureRegistry().closeMobileFiles?.();
          document.body.classList.remove('koto-nav-open');
          syncLayoutA11y();
        }).catch(() => {
          showToast('新建任务暂时不可用，请稍后重试', 'error');
        }).finally(() => { button.disabled = false; });
    }
  });
  document.addEventListener('mousedown', (event) => {
    if (event.target instanceof Element && event.target.closest('#koto-document-ai-launcher')) {
      event.preventDefault(); // Keep the editor selection available to the existing selection bridge.
    }
  });
  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape' || event.defaultPrevented) return;
    const files = document.body.classList.contains('wa-mobile-files-open');
    const navigation = document.body.classList.contains('koto-nav-open');
    if (!files && !navigation) return;
    getFeatureRegistry().closeMobileFiles?.();
    document.body.classList.remove('koto-nav-open');
    syncLayoutA11y();
    (files ? filesTrigger || document.getElementById('koto-files-toggle')
      : document.getElementById('koto-nav-toggle'))?.focus();
  });
  window.addEventListener('resize', () => { syncLayoutA11y(); refreshWorkspaceLayout(); });
  window.addEventListener('koto-ui-zoom-change', syncLayoutA11y);
}

registerFeatures({ refreshWorkspaceLayout, toggleAiPanel, _expandWAPanel,
  showConversationLayout, showDocumentLayout, initWorkspaceLayout, closeWorkspaceNavigation });

// The workspace entry initializes this after installing the lazy feature bridges.
