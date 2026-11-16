import { describe, expect, it, vi } from 'vitest';
import { KotoTipTapEditor } from '../../tiptap-editor/koto-docx-editor.js';
import { registerFeatures } from '../shared/feature-registry';

describe('native DOCX semantic edit persistence boundary', () => {
  it('marks semantic transactions dirty without scheduling disk persistence while ordinary edits still autosave', () => {
    document.body.innerHTML = '<div id="wa-docx-editor"></div>';
    const scheduleAutoSave = vi.fn();
    registerFeatures({ scheduleAutoSave });
    vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
    vi.stubGlobal('requestAnimationFrame', vi.fn(() => 0));
    const editor = new KotoTipTapEditor();
    try {
      editor.render('<p>Original document</p>');
      scheduleAutoSave.mockClear();
      const pm = editor.editor!;
      pm.view.dispatch(pm.state.tr.insertText('AI ', 1).setMeta('kotoSkipDiskWrite', true));
      expect(pm.state.doc.textContent).toBe('AI Original document');
      expect(scheduleAutoSave).toHaveBeenCalledWith({ skipDiskWrite: true });
      expect(scheduleAutoSave.mock.calls.every(([options]) => options?.skipDiskWrite === true)).toBe(true);
      scheduleAutoSave.mockClear();
      pm.view.dispatch(pm.state.tr.insertText('Author ', 1));
      expect(scheduleAutoSave).toHaveBeenCalledWith(undefined);
    } finally { editor.destroy(); vi.unstubAllGlobals(); }
  });
});
