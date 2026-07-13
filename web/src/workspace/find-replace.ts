/**
 * Find/replace for DOCX and PPTX editors.
 */

import { getWorkspaceApi, publishWorkspaceApi } from '../shared/workspace-api';

interface DocxMatch {
  from: number;
  to: number;
}

interface PptxMatch {
  slideIdx: number;
  shapeId: string;
  paraIdx: number;
  runIdx: number;
  charIdx: number;
  len: number;
  displayText: string;
}

interface PptxSlideShape {
  id: string;
  has_text?: boolean;
  paragraphs?: PptxParagraph[];
}

interface PptxParagraph {
  runs?: PptxRun[];
}

interface PptxRun {
  text?: string;
}

interface PptxSlide {
  shapes?: PptxSlideShape[];
}

interface ActiveEditor {
  editor?: {
    state: {
      doc: {
        descendants: (fn: (node: any, pos: number) => void) => void;
      };
    };
    commands: {
      setTextSelection: (range: { from: number; to: number }) => any;
      scrollIntoView: () => any;
    };
    chain: () => {
      setTextSelection: (range: { from: number; to: number }) => any;
      insertContent: (content: string) => any;
      focus: () => any;
      run: () => void;
    };
  };
  data?: {
    slides: PptxSlide[];
  };
  _curIdx?: number;
  _renderSlide?: (idx: number) => void;
  _redrawThumb?: (idx: number) => void;
}

interface FindReplaceDeps {
  getActiveEditor: () => ActiveEditor | null | undefined;
  showToast?: (msg: string, type?: string) => void;
  pptxNav?: (delta: number) => void;
  scheduleAutoSave?: () => void;
}

interface DocxFindState {
  matches: DocxMatch[];
  idx: number;
  marks: any[];
  replaceOpen: boolean;
}

interface PptxFindState {
  matches: PptxMatch[];
  idx: number;
  replaceOpen: boolean;
}

function installDocxFindReplace(deps: FindReplaceDeps) {
  const { getActiveEditor, showToast } = deps;
  const docxFind: DocxFindState = {
    matches: [],
    idx: 0,
    marks: [],
    replaceOpen: false,
  };

  function docxFindAll(query: string, caseSensitive: boolean): DocxMatch[] {
    const activeEditor = getActiveEditor();
    const editor = activeEditor && activeEditor.editor;
    if (!editor || !query) return [];
    const escaped = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const regex = new RegExp(escaped, caseSensitive ? 'g' : 'gi');
    const results: DocxMatch[] = [];
    editor.state.doc.descendants((node: any, pos: number) => {
      if (!node.isText || !node.text) return;
      regex.lastIndex = 0;
      let match: RegExpExecArray | null;
      while ((match = regex.exec(node.text)) !== null) {
        results.push({ from: pos + match.index, to: pos + match.index + match[0].length });
      }
    });
    return results;
  }

  function docxFindGo(matches: DocxMatch[], idx: number): void {
    const activeEditor = getActiveEditor();
    const editor = activeEditor && activeEditor.editor;
    if (!editor || !matches.length) return;
    const { from, to } = matches[idx];
    editor.commands.setTextSelection({ from, to });
    editor.commands.scrollIntoView();
  }

  function docxFindUpdateCount(query: string): void {
    const caseSensitive = !!(document.getElementById('wa-docx-find-case') as HTMLInputElement | null)?.checked;
    docxFind.matches = docxFindAll(query, caseSensitive);
    docxFind.idx = docxFind.matches.length ? 0 : -1;
    const countEl = document.getElementById('wa-docx-find-count');
    const input = document.getElementById('wa-docx-find-input');
    if (countEl) countEl.textContent = docxFind.matches.length ? `1 / ${docxFind.matches.length}` : (query ? '无匹配' : '');
    if (input) input.classList.toggle('no-match', !!query && !docxFind.matches.length);
    if (docxFind.matches.length) docxFindGo(docxFind.matches, 0);
  }

  const docxFindInput = (value: unknown) => docxFindUpdateCount(String(value || '').trim());

  const docxFindNext = () => {
    if (!docxFind.matches.length) return;
    docxFind.idx = (docxFind.idx + 1) % docxFind.matches.length;
    docxFindGo(docxFind.matches, docxFind.idx);
    const countEl = document.getElementById('wa-docx-find-count');
    if (countEl) countEl.textContent = `${docxFind.idx + 1} / ${docxFind.matches.length}`;
  };

  const docxFindPrev = () => {
    if (!docxFind.matches.length) return;
    docxFind.idx = (docxFind.idx - 1 + docxFind.matches.length) % docxFind.matches.length;
    docxFindGo(docxFind.matches, docxFind.idx);
    const countEl = document.getElementById('wa-docx-find-count');
    if (countEl) countEl.textContent = `${docxFind.idx + 1} / ${docxFind.matches.length}`;
  };

  const docxFindKeydown = (event: KeyboardEvent) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      docxFindNext();
    }
    if (event.key === 'Enter' && event.shiftKey) {
      event.preventDefault();
      docxFindPrev();
    }
    if (event.key === 'Escape') docxFindClose();
  };

  const docxFindClose = () => {
    const bar = document.getElementById('wa-docx-find-bar');
    if (bar) bar.style.display = 'none';
    docxFind.matches = [];
    docxFind.idx = -1;
    const input = document.getElementById('wa-docx-find-input');
    if (input) {
      (input as HTMLInputElement).value = '';
      input.classList.remove('no-match');
    }
    const countEl = document.getElementById('wa-docx-find-count');
    if (countEl) countEl.textContent = '';
    const pm = document.querySelector('#wa-docx-editor .ProseMirror');
    if (pm) (pm as HTMLElement).focus();
  };

  const docxToggleReplace = (forceOpen: boolean) => {
    const row = document.getElementById('wa-docx-replace-row');
    const btn = document.getElementById('wa-docx-replace-toggle');
    if (!row) return;
    docxFind.replaceOpen = (forceOpen === true) ? true : !docxFind.replaceOpen;
    row.style.display = docxFind.replaceOpen ? '' : 'none';
    if (btn) btn.classList.toggle('active', docxFind.replaceOpen);
    if (docxFind.replaceOpen) {
      const input = document.getElementById('wa-docx-replace-input');
      if (input) input.focus();
    }
  };

  const docxReplaceNext = () => {
    const activeEditor = getActiveEditor();
    const editor = activeEditor && activeEditor.editor;
    if (!editor || !docxFind.matches.length || docxFind.idx < 0) return;
    const replaceVal = ((document.getElementById('wa-docx-replace-input') as HTMLInputElement) || { value: '' }).value || '';
    const { from, to } = docxFind.matches[docxFind.idx];
    editor.chain().setTextSelection({ from, to }).insertContent(replaceVal).run();
    const query = ((document.getElementById('wa-docx-find-input') as HTMLInputElement) || { value: '' }).value || '';
    docxFindUpdateCount(query.trim());
  };

  const docxReplaceAll = () => {
    const activeEditor = getActiveEditor();
    const editor = activeEditor && activeEditor.editor;
    if (!editor || !docxFind.matches.length) return;
    const replaceVal = ((document.getElementById('wa-docx-replace-input') as HTMLInputElement) || { value: '' }).value || '';
    const count = docxFind.matches.length;
    const sorted = [...docxFind.matches].sort((a, b) => b.from - a.from);
    editor.chain().focus().run();
    for (const { from, to } of sorted) {
      editor.chain().setTextSelection({ from, to }).insertContent(replaceVal).run();
    }
    if (showToast) showToast(`已替换 ${count} 处`, 'success');
    const query = ((document.getElementById('wa-docx-find-input') as HTMLInputElement) || { value: '' }).value || '';
    docxFindUpdateCount(query.trim());
  };

  return {
    docxFindInput,
    docxFindNext,
    docxFindPrev,
    docxFindKeydown,
    docxFindClose,
    docxToggleReplace,
    docxReplaceNext,
    docxReplaceAll,
  };
}

function installPptxFindReplace(deps: FindReplaceDeps) {
  const { getActiveEditor, showToast, pptxNav, scheduleAutoSave } = deps;
  const pptxFind: PptxFindState = {
    matches: [],
    idx: 0,
    replaceOpen: false,
  };

  function pptxFindAll(query: string, caseSensitive: boolean): PptxMatch[] {
    const editor = getActiveEditor();
    if (!editor || !editor.data || !query) return [];
    const q = caseSensitive ? query : query.toLowerCase();
    const results: PptxMatch[] = [];
    editor.data.slides.forEach((slide, slideIdx) => {
      (slide.shapes || []).forEach((shape) => {
        if (!shape.has_text) return;
        (shape.paragraphs || []).forEach((para, paraIdx) => {
          (para.runs || []).forEach((run, runIdx) => {
            const text = run.text || '';
            const target = caseSensitive ? text : text.toLowerCase();
            let charIdx = 0;
            while ((charIdx = target.indexOf(q, charIdx)) !== -1) {
              results.push({ slideIdx, shapeId: shape.id, paraIdx, runIdx, charIdx, len: q.length, displayText: text.substring(charIdx, charIdx + q.length) });
              charIdx++;
            }
          });
        });
      });
    });
    return results;
  }

  function pptxFindGo(matches: PptxMatch[], idx: number): void {
    const editor = getActiveEditor();
    if (!editor || !matches.length) return;
    const { slideIdx } = matches[idx];
    if (typeof editor._curIdx !== 'undefined' && editor._curIdx !== slideIdx && pptxNav) {
      pptxNav(slideIdx - editor._curIdx);
    }
  }

  function pptxFindUpdateCount(query: string): void {
    const caseSensitive = !!(document.getElementById('wa-pptx-find-case') as HTMLInputElement | null)?.checked;
    pptxFind.matches = pptxFindAll(query, caseSensitive);
    pptxFind.idx = pptxFind.matches.length ? 0 : -1;
    const countEl = document.getElementById('wa-pptx-find-count');
    const input = document.getElementById('wa-pptx-find-input');
    if (countEl) countEl.textContent = pptxFind.matches.length ? `1 / ${pptxFind.matches.length}` : (query ? '无匹配' : '');
    if (input) input.classList.toggle('no-match', !!query && !pptxFind.matches.length);
    if (pptxFind.matches.length) pptxFindGo(pptxFind.matches, 0);
  }

  const pptxFindInput = (value: unknown) => pptxFindUpdateCount(String(value || '').trim());

  const pptxFindNext = () => {
    if (!pptxFind.matches.length) return;
    pptxFind.idx = (pptxFind.idx + 1) % pptxFind.matches.length;
    pptxFindGo(pptxFind.matches, pptxFind.idx);
    const countEl = document.getElementById('wa-pptx-find-count');
    if (countEl) countEl.textContent = `${pptxFind.idx + 1} / ${pptxFind.matches.length}`;
  };

  const pptxFindPrev = () => {
    if (!pptxFind.matches.length) return;
    pptxFind.idx = (pptxFind.idx - 1 + pptxFind.matches.length) % pptxFind.matches.length;
    pptxFindGo(pptxFind.matches, pptxFind.idx);
    const countEl = document.getElementById('wa-pptx-find-count');
    if (countEl) countEl.textContent = `${pptxFind.idx + 1} / ${pptxFind.matches.length}`;
  };

  const pptxFindKeydown = (event: KeyboardEvent) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      pptxFindNext();
    }
    if (event.key === 'Enter' && event.shiftKey) {
      event.preventDefault();
      pptxFindPrev();
    }
    if (event.key === 'Escape') pptxFindClose();
  };

  const pptxFindClose = () => {
    const bar = document.getElementById('wa-pptx-find-bar');
    if (bar) bar.style.display = 'none';
    pptxFind.matches = [];
    pptxFind.idx = -1;
    const input = document.getElementById('wa-pptx-find-input');
    if (input) {
      (input as HTMLInputElement).value = '';
      input.classList.remove('no-match');
    }
    const countEl = document.getElementById('wa-pptx-find-count');
    if (countEl) countEl.textContent = '';
  };

  const pptxToggleReplace = (forceOpen: boolean) => {
    const row = document.getElementById('wa-pptx-replace-row');
    const btn = document.getElementById('wa-pptx-replace-toggle');
    if (!row) return;
    pptxFind.replaceOpen = (forceOpen === true) ? true : !pptxFind.replaceOpen;
    row.style.display = pptxFind.replaceOpen ? '' : 'none';
    if (btn) btn.classList.toggle('active', pptxFind.replaceOpen);
    if (pptxFind.replaceOpen) {
      const input = document.getElementById('wa-pptx-replace-input');
      if (input) input.focus();
    }
  };

  function pptxApplyReplace(match: PptxMatch, replaceVal: string): boolean {
    const editor = getActiveEditor();
    if (!editor || !editor.data) return false;
    const slide = editor.data.slides[match.slideIdx];
    if (!slide) return false;
    const shape = (slide.shapes || []).find((item) => item.id === match.shapeId);
    if (!shape) return false;
    const para = (shape.paragraphs || [])[match.paraIdx];
    if (!para) return false;
    const run = (para.runs || [])[match.runIdx];
    if (!run) return false;
    run.text = run.text!.substring(0, match.charIdx) + replaceVal + run.text!.substring(match.charIdx + match.len);
    if (editor._curIdx === match.slideIdx && typeof editor._renderSlide === 'function') editor._renderSlide(match.slideIdx);
    if (typeof editor._redrawThumb === 'function') editor._redrawThumb(match.slideIdx);
    if (scheduleAutoSave) scheduleAutoSave();
    return true;
  }

  const pptxReplaceNext = () => {
    if (!pptxFind.matches.length || pptxFind.idx < 0) return;
    const replaceVal = ((document.getElementById('wa-pptx-replace-input') as HTMLInputElement) || { value: '' }).value || '';
    pptxApplyReplace(pptxFind.matches[pptxFind.idx], replaceVal);
    const query = ((document.getElementById('wa-pptx-find-input') as HTMLInputElement) || { value: '' }).value || '';
    pptxFindUpdateCount(query.trim());
  };

  const pptxReplaceAll = () => {
    if (!pptxFind.matches.length) return;
    const replaceVal = ((document.getElementById('wa-pptx-replace-input') as HTMLInputElement) || { value: '' }).value || '';
    const count = pptxFind.matches.length;
    [...pptxFind.matches].reverse().forEach((match) => pptxApplyReplace(match, replaceVal));
    if (showToast) showToast(`已替换 ${count} 处`, 'success');
    const query = ((document.getElementById('wa-pptx-find-input') as HTMLInputElement) || { value: '' }).value || '';
    pptxFindUpdateCount(query.trim());
  };

  return {
    pptxFindInput,
    pptxFindNext,
    pptxFindPrev,
    pptxFindKeydown,
    pptxFindClose,
    pptxToggleReplace,
    pptxReplaceNext,
    pptxReplaceAll,
  };
}

let _findReplaceActionDelegationInstalled = false;

function _findReplaceApiMethod(scope: string, action: string): string {
  const prefix = scope === 'docx' ? 'docx' : scope === 'pptx' ? 'pptx' : '';
  if (!prefix) return '';
  const suffixes: Record<string, string> = {
    input: 'FindInput',
    keydown: 'FindKeydown',
    prev: 'FindPrev',
    next: 'FindNext',
    close: 'FindClose',
    'toggle-replace': 'ToggleReplace',
    'replace-next': 'ReplaceNext',
    'replace-all': 'ReplaceAll',
  };
  return suffixes[action] ? `${prefix}${suffixes[action]}` : '';
}

function _invokeFindReplaceAction(scope: string, action: string, ...args: any[]): void {
  const method = _findReplaceApiMethod(scope, action);
  const handler = method ? getWorkspaceApi()[method] : null;
  if (typeof handler === 'function') handler(...args);
}

function _installFindReplaceActionDelegation(): void {
  if (_findReplaceActionDelegationInstalled) return;
  _findReplaceActionDelegationInstalled = true;

  document.addEventListener('mousedown', (event) => {
    const target = event.target as HTMLElement | null;
    if (target?.closest?.('[data-wa-find-action]')) event.preventDefault();
  }, true);

  document.addEventListener('input', (event) => {
    const input = event.target as HTMLInputElement | null;
    const scope = String(input?.dataset.waFindInput || '');
    if (scope && input) _invokeFindReplaceAction(scope, 'input', input.value);
  });

  document.addEventListener('change', (event) => {
    const input = event.target as HTMLInputElement | null;
    const scope = String(input?.dataset.waFindCase || '');
    if (!scope) return;
    const query = document.getElementById(`wa-${scope}-find-input`) as HTMLInputElement | null;
    _invokeFindReplaceAction(scope, 'input', query?.value || '');
  });

  document.addEventListener('keydown', (event) => {
    const input = event.target as HTMLInputElement | null;
    const findScope = String(input?.dataset.waFindInput || '');
    if (findScope) {
      _invokeFindReplaceAction(findScope, 'keydown', event);
      return;
    }
    const replaceScope = String(input?.dataset.waFindReplaceInput || '');
    if (replaceScope && event.key === 'Enter') {
      event.preventDefault();
      _invokeFindReplaceAction(replaceScope, 'replace-next');
    }
  });

  document.addEventListener('click', (event) => {
    const target = event.target as HTMLElement | null;
    const control = target?.closest?.<HTMLElement>('[data-wa-find-action]');
    if (!control) return;
    const scope = String(control.dataset.waFindScope || '');
    const action = String(control.dataset.waFindAction || '');
    if (!scope || !action) return;
    event.preventDefault();
    event.stopPropagation();
    _invokeFindReplaceAction(scope, action);
  }, true);
}

export function installWorkspaceFindReplace(deps: FindReplaceDeps): void {
  const workspaceApi = getWorkspaceApi();
  if (workspaceApi.__workspaceFindReplaceInstalled) return;
  workspaceApi.__workspaceFindReplaceInstalled = true;

  publishWorkspaceApi({
    ...installDocxFindReplace(deps),
    ...installPptxFindReplace(deps),
  });
}

publishWorkspaceApi({ installWorkspaceFindReplace });
_installFindReplaceActionDelegation();
