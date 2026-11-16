// @ts-nocheck
import { getWorkspaceRuntime as _workspaceRuntime } from './workspace-runtime-inspector';
import { getFeatureRegistry } from '../shared/feature-registry';
import { FrontendAction, _argToText, _isVisible, _targetSummary, _visibleText } from './frontend-observer';

export function _bestSelector(el: Element): string {
  if (el.id) return `#${CSS.escape(el.id)}`;
  const testId = el.getAttribute('data-testid');
  if (testId) return `[data-testid="${CSS.escape(testId)}"]`;
  const action = el.getAttribute('data-action');
  if (action) return `[data-action="${CSS.escape(action)}"]`;
  const aria = el.getAttribute('aria-label');
  if (aria) return `${el.tagName.toLowerCase()}[aria-label="${CSS.escape(aria)}"]`;
  return el.tagName.toLowerCase();
}

function _textMatch(el: Element, text: string): boolean {
  const wanted = text.replace(/\s+/g, ' ').trim().toLowerCase();
  if (!wanted) return false;
  const candidates = [
    el.getAttribute('aria-label') || '',
    el.getAttribute('title') || '',
    el.getAttribute('placeholder') || '',
    _visibleText(el, 500),
  ].map((item) => item.toLowerCase());
  return candidates.some((item) => item === wanted || item.includes(wanted));
}

export function _findTarget(action: FrontendAction): Element | null {
  const selector = (action.selector || '').trim();
  if (selector) {
    const selected = document.querySelector(selector);
    if (selected) return selected;
  }
  const text = (action.text || '').trim();
  if (!text) return null;
  return Array.from(document.querySelectorAll('button,a,input,select,textarea,[role="button"],[data-action],[contenteditable="true"]'))
    .find((item) => _isVisible(item) && _textMatch(item, text)) || null;
}

export function _panelSelector(panel: string): string {
  const normalized = panel.trim().toLowerCase();
  if (normalized === 'settings') return '#navSettingsBtn';
  if (normalized === 'addons' || normalized === 'capabilities') return '#navCapabilityBtn';
  if (normalized === 'artifact') return '#artifactsPanel, [data-action="open-artifact"], #navArtifactsBtn';
  if (normalized === 'workspace') return '[data-action="show-file-workspace"], #navWorkspaceBtn, #sidebarToggle';
  if (normalized === 'ai') return '[data-action="show-ai-workspace"], #wa-user-input';
  return '';
}

export function _findFirstVisible(selectors: string[]): Element | null {
  for (const selector of selectors) {
    if (!selector) continue;
    const elements = Array.from(document.querySelectorAll(selector));
    const match = elements.find(_isVisible);
    if (match) return match;
  }
  return null;
}

function _ensureUnifiedAiComposerVisible(): Element | null {
  const existing = _findFirstVisible(['#wa-user-input']);
  if (existing) return existing;
  const wa = getFeatureRegistry();
  if (wa && typeof wa.showAiWorkspace === 'function') {
    try { wa.showAiWorkspace(); } catch (_) { /* keep fallback below */ }
  } else {
    const panelTarget = _findFirstVisible(['#navAiSessionsBtn', '[data-action="show-ai-workspace"]']);
    if (panelTarget) (panelTarget as HTMLElement).click();
  }
  return _findFirstVisible(['#wa-user-input']);
}

export function _assistantComposerTargets(): { input: Element | null; send: Element | null } {
  const input = _ensureUnifiedAiComposerVisible();
  return { input, send: input ? _findFirstVisible(['#wa-send-btn']) : null };
}

export function _selectedTexts(selector: string, limit = 10): string[] {
  return Array.from(document.querySelectorAll(selector))
    .slice(0, limit)
    .map((item) => _visibleText(item, 200))
    .filter(Boolean);
}

export function _safeJsonClone(value: unknown, fallback: unknown = null): unknown {
  try {
    return JSON.parse(JSON.stringify(value));
  } catch (_) {
    return fallback;
  }
}

export function _limitString(value: unknown, limit: number): { text: string; length: number; truncated: boolean } {
  const text = typeof value === 'string' ? value : value == null ? '' : String(value);
  const safeLimit = Math.max(100, Math.min(Number(limit || 8000), 50000));
  return {
    text: text.slice(0, safeLimit),
    length: text.length,
    truncated: text.length > safeLimit,
  };
}

function _jsonPreview(value: unknown, limit: number): { text: string; length: number; truncated: boolean } {
  let text = '';
  try {
    text = JSON.stringify(value, null, 2);
  } catch (_) {
    text = String(value);
  }
  return _limitString(text, limit);
}

export function _workspaceStateDetails(): Record<string, unknown> {
  const runtime = _workspaceRuntime();
  const state = runtime.state;
  const openTabs = Array.isArray(state.openTabs) ? state.openTabs : [];
  const activePath = String(state.activeTabPath || state.wsSourcePath || '');
  const activeTab = openTabs.find((tab: any) => String(tab?.path || '') === activePath) || null;
  const activeEditorRuntime = runtime.activeEditor;
  const editorIds = [
    'wa-docx-editor',
    'wa-xlsx-editor',
    'wa-pptx-editor',
    'wa-pdf-viewer',
    'wa-image-viewer',
    'wa-text-editor',
  ];
  const editors = editorIds.map((id) => {
    const el = document.getElementById(id);
    const active = Boolean(el?.classList.contains('active'));
    let textPreview = '';
    if (active && activeEditorRuntime && typeof activeEditorRuntime.getContent === 'function') {
      textPreview = String(activeEditorRuntime.getContent() || '');
    } else if (active && activeEditorRuntime?.editor && typeof activeEditorRuntime.editor.getText === 'function') {
      textPreview = String(activeEditorRuntime.editor.getText() || '');
    } else if (id === 'wa-docx-editor') {
      textPreview = _visibleText(el?.querySelector('.ProseMirror, [contenteditable="true"]'), 300);
    } else {
      textPreview = _visibleText(el, 300);
    }
    return {
      id,
      active,
      visible: el ? _isVisible(el) : false,
      textPreview: textPreview.replace(/\s+/g, ' ').trim().slice(0, 300),
    };
  });
  const wa = getFeatureRegistry() || {};
  return {
    fileId: state.fileId || '',
    fileType: state.fileType || '',
    fileName: state.fileName || document.getElementById('wa-file-name')?.textContent?.trim() || '',
    filePath: state.filePath || '',
    wsSourcePath: state.wsSourcePath || '',
    activeTabPath: state.activeTabPath || '',
    activeTab: activeTab
      ? {
          path: activeTab.path || '',
          name: activeTab.name || '',
          ext: activeTab.ext || '',
          fileType: activeTab.fileType || '',
          fileId: activeTab.fileId || '',
          filePath: activeTab.filePath || '',
          modified: Boolean(activeTab.modified),
          capabilityProfile: _safeJsonClone(activeTab.capabilityProfile || null),
        }
      : null,
    openTabs: openTabs.slice(0, 20).map((tab: any) => ({
      path: tab?.path || '',
      name: tab?.name || '',
      ext: tab?.ext || '',
      fileType: tab?.fileType || '',
      modified: Boolean(tab?.modified),
    })),
    activeEditors: editors.filter((item) => item.active || item.visible),
    tabLabels: _selectedTexts('#wa-tab-bar .wa-tab', 20),
    headerFileName: document.getElementById('wa-file-name')?.textContent?.trim() || '',
    waMethods: {
      openWorkspaceFile: typeof wa.openWorkspaceFile === 'function',
      openBrowserFile: typeof wa.openBrowserFile === 'function',
      applyFileJson: typeof wa._applyFileJson === 'function',
      refreshFiles: typeof wa.refreshFiles === 'function',
    },
  };
}

export function _readEditorContent(action: FrontendAction): Record<string, unknown> {
  const limit = Number(action.options?.maxChars || action.options?.max_chars || action.options?.limit || 12000);
  const editor = _workspaceRuntime().activeEditor;
  const result: Record<string, unknown> = {
    state: _workspaceStateDetails(),
    content: _limitString('', limit),
    html: null,
    serialized: null,
    source: '',
  };
  try {
    if (editor && typeof editor.getContent === 'function') {
      result.content = _limitString(editor.getContent(), limit);
      result.source = 'activeEditor.getContent';
    } else if (editor?.editor && typeof editor.editor.getText === 'function') {
      result.content = _limitString(editor.editor.getText(), limit);
      result.source = 'activeEditor.editor.getText';
    } else {
      const textArea = document.getElementById('wa-text-content') as HTMLTextAreaElement | null;
      if (textArea && _isVisible(textArea)) {
        result.content = _limitString(textArea.value, limit);
        result.source = '#wa-text-content';
      } else {
        const activeEditor = document.querySelector(
          '#wa-docx-editor.active, #wa-xlsx-editor.active, #wa-pptx-editor.active, #wa-pdf-viewer.active, #wa-image-viewer.active, #wa-text-editor.active'
        );
        result.content = _limitString(_visibleText(activeEditor, limit), limit);
        result.source = 'active editor visible text';
      }
    }
    if (editor?.editor && typeof editor.editor.getHTML === 'function') {
      result.html = _limitString(editor.editor.getHTML(), Math.min(limit, 20000));
    }
    if (editor && typeof editor.serialize === 'function') {
      const serialized = editor.serialize();
      result.serialized = typeof serialized === 'string'
        ? _limitString(serialized, limit)
        : _jsonPreview(serialized, Math.min(limit, 20000));
    }
  } catch (error) {
    result.error = _argToText(error);
  }
  return result;
}

function _selectionRectSummary(selection: Selection | null): Record<string, unknown> | null {
  if (!selection || selection.rangeCount <= 0) return null;
  try {
    const rect = selection.getRangeAt(0).getBoundingClientRect();
    return {
      x: Math.round(rect.x),
      y: Math.round(rect.y),
      width: Math.round(rect.width),
      height: Math.round(rect.height),
    };
  } catch (_) {
    return null;
  }
}

export function _currentSelectionDetails(action: FrontendAction): Record<string, unknown> {
  const limit = Number(action.options?.maxChars || action.options?.max_chars || action.options?.limit || 4000);
  const active = document.activeElement;
  const selection = window.getSelection ? window.getSelection() : null;
  const wa = getFeatureRegistry() || {};
  let inputSelection: Record<string, unknown> | null = null;
  if (active instanceof HTMLInputElement || active instanceof HTMLTextAreaElement) {
    const start = Number(active.selectionStart || 0);
    const end = Number(active.selectionEnd || 0);
    inputSelection = {
      target: _targetSummary(active),
      selectionStart: start,
      selectionEnd: end,
      selectedText: _limitString(active.value.slice(start, end), limit),
    };
  }
  let docxSelection = '';
  try {
    if (typeof wa._getDocxSelectionTextForAI === 'function') {
      docxSelection = String(wa._getDocxSelectionTextForAI() || '');
    }
  } catch (_) {
    docxSelection = '';
  }
  const windowText = selection ? selection.toString() : '';
  const inputText = inputSelection && inputSelection.selectedText
    ? String((inputSelection.selectedText as Record<string, unknown>).text || '')
    : '';
  const text = docxSelection || inputText || windowText || '';
  return {
    state: _workspaceStateDetails(),
    activeElement: active instanceof Element ? _targetSummary(active) : {},
    hasSelection: Boolean(String(text || '').trim()),
    selectedText: _limitString(text, limit),
    inputSelection,
    windowSelection: {
      text: _limitString(windowText, limit),
      rangeCount: selection?.rangeCount || 0,
      isCollapsed: selection ? selection.isCollapsed : true,
      rect: _selectionRectSummary(selection),
    },
    docxSelection: _limitString(docxSelection, limit),
  };
}
