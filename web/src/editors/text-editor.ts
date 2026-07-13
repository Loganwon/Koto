/**
 * KotoTextEditor - plain text/code editor
 */

import type { WorkspaceEditor } from './types';
import type { TextEditorData } from './types';
import { getWorkspaceApi } from '../shared/workspace-api';

function $(id: string): HTMLElement | null { return document.getElementById(id); }

export class KotoTextEditor implements WorkspaceEditor {
  _fileType: string;
  _ta: HTMLTextAreaElement | null;
  _badge: HTMLElement | null;
  _selectionNotifyTimer: number | null;

  constructor(fileType: string) {
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

  _handleInput = () => {
    const scheduleAutoSave = getWorkspaceApi().scheduleAutoSave;
    if (typeof scheduleAutoSave === 'function') scheduleAutoSave();
    this._queueSelectionToolbarUpdate();
  };

  _handleSelectionChange = () => {
    this._queueSelectionToolbarUpdate();
  };

  _queueSelectionToolbarUpdate() {
    if (this._selectionNotifyTimer) window.clearTimeout(this._selectionNotifyTimer);
    this._selectionNotifyTimer = window.setTimeout(() => {
      this._selectionNotifyTimer = null;
      const showToolbar = getWorkspaceApi()._showSelectionToolbarForCurrentSelection;
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
      getWorkspaceApi().scheduleAutoSave?.();
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

(window as any).KotoTextEditor = KotoTextEditor;
