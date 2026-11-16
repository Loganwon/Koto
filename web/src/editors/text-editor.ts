/**
 * KotoTextEditor - plain text/code editor
 */

import type { TextEditorData, WorkspaceEditor } from './types';
import type { EditorSession } from './editor-session';
import { getFeatureRegistry } from '../shared/feature-registry';

function $(id: string): HTMLElement | null { return document.getElementById(id); }

export class KotoTextEditor implements WorkspaceEditor {
  _fileType: string;
  _ta: HTMLTextAreaElement | null;
  _badge: HTMLElement | null;
  _selectionNotifyTimer: number | null;
  _session: EditorSession;

  constructor(session: EditorSession, fileType: string) {
    this._session = session;
    this._fileType = fileType;
    this._ta = $('wa-text-content') as HTMLTextAreaElement | null;
    this._badge = $('wa-text-lang-badge');
    this._selectionNotifyTimer = null;
    const editor = $('wa-text-editor');
    if (editor) editor.classList.add('active');
    if (this._ta) {
      this._ta.addEventListener('input', this._handleInput);
      this._ta.addEventListener('select', this._handleSelectionChange);
      this._ta.addEventListener('mouseup', this._handleSelectionChange);
      this._ta.addEventListener('keyup', this._handleSelectionChange);
    }
  }

  _handleInput = (event: Event) => {
    const scheduleAutoSave = getFeatureRegistry().scheduleAutoSave;
    if (typeof scheduleAutoSave === 'function') {
      if ((event as Event & { kotoSkipDiskWrite?: boolean }).kotoSkipDiskWrite === true) scheduleAutoSave({ skipDiskWrite: true });
      else scheduleAutoSave();
    }
    this._queueSelectionToolbarUpdate();
  };

  _handleSelectionChange = () => {
    this._queueSelectionToolbarUpdate();
  };

  _queueSelectionToolbarUpdate() {
    if (this._selectionNotifyTimer) window.clearTimeout(this._selectionNotifyTimer);
    this._selectionNotifyTimer = window.setTimeout(() => {
      this._selectionNotifyTimer = null;
      const showToolbar = getFeatureRegistry()._showSelectionToolbarForCurrentSelection;
      if (typeof showToolbar === 'function') showToolbar();
    }, 0);
  }

  render(data: string | TextEditorData) {
    const content = (data && typeof data === 'object') ? ((data as TextEditorData).content || '') : (data as string || '');
    const lang = (data && typeof data === 'object') ? ((data as TextEditorData).language || '') : '';
    if (!this._ta) return;
    this._ta.value = content;
    if (this._badge) {
      this._badge.textContent = lang ? lang.toUpperCase() : 'TXT';
      this._badge.style.display = lang ? 'block' : 'none';
    }
    this._ta.focus();
  }

  getContent(): string { return this._ta ? this._ta.value : ''; }

  serialize(): string { return this._ta ? this._ta.value : ''; }

  applyToolCall(cmd: any) {
    if (cmd.type === 'set_html' || cmd.type === 'set_text') {
      if (this._ta) this._ta.value = cmd.value || '';
      getFeatureRegistry().scheduleAutoSave?.();
    }
  }

  destroy() {
    if (this._selectionNotifyTimer) {
      window.clearTimeout(this._selectionNotifyTimer);
      this._selectionNotifyTimer = null;
    }
    if (this._ta) {
      this._ta.removeEventListener('input', this._handleInput);
      this._ta.removeEventListener('select', this._handleSelectionChange);
      this._ta.removeEventListener('mouseup', this._handleSelectionChange);
      this._ta.removeEventListener('keyup', this._handleSelectionChange);
    }
    const editor = $('wa-text-editor');
    if (editor) editor.classList.remove('active');
    if (this._badge) { this._badge.textContent = ''; this._badge.style.display = 'none'; }
  }
}

getFeatureRegistry().KotoTextEditor = KotoTextEditor;
