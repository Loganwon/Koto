(function () {
  window.WA = window.WA || {};

  window.WA.installWorkspaceFindReplace = function installWorkspaceFindReplace(deps) {
    if (window.WA.__workspaceFindReplaceInstalled) return;
    window.WA.__workspaceFindReplaceInstalled = true;

    const getActiveEditor = deps.getActiveEditor || (() => null);
    const showToast = deps.showToast || (() => {});
    const pptxNav = deps.pptxNav || (() => {});
    const scheduleAutoSave = deps.scheduleAutoSave || (() => {});

    const docxFind = {
      matches: [],
      idx: 0,
      marks: [],
      replaceOpen: false,
    };

    function docxFindAll(query, caseSensitive) {
      const activeEditor = getActiveEditor();
      const editor = activeEditor && activeEditor.editor;
      if (!editor || !query) return [];
      const escaped = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      const regex = new RegExp(escaped, caseSensitive ? 'g' : 'gi');
      const results = [];
      editor.state.doc.descendants((node, pos) => {
        if (!node.isText || !node.text) return;
        regex.lastIndex = 0;
        let match;
        while ((match = regex.exec(node.text)) !== null) {
          results.push({ from: pos + match.index, to: pos + match.index + match[0].length });
        }
      });
      return results;
    }

    function docxFindGo(matches, idx) {
      const activeEditor = getActiveEditor();
      const editor = activeEditor && activeEditor.editor;
      if (!editor || !matches.length) return;
      const { from, to } = matches[idx];
      editor.commands.setTextSelection({ from, to });
      editor.commands.scrollIntoView();
    }

    function docxFindUpdateCount(query) {
      const caseSensitive = (document.getElementById('wa-docx-find-case') || {}).checked;
      docxFind.matches = docxFindAll(query, caseSensitive);
      docxFind.idx = docxFind.matches.length ? 0 : -1;
      const countEl = document.getElementById('wa-docx-find-count');
      const input = document.getElementById('wa-docx-find-input');
      if (countEl) countEl.textContent = docxFind.matches.length ? `1 / ${docxFind.matches.length}` : (query ? '无匹配' : '');
      if (input) input.classList.toggle('no-match', !!query && !docxFind.matches.length);
      if (docxFind.matches.length) docxFindGo(docxFind.matches, 0);
    }

    window.WA.docxFindInput = (value) => docxFindUpdateCount(String(value || '').trim());

    window.WA.docxFindNext = () => {
      if (!docxFind.matches.length) return;
      docxFind.idx = (docxFind.idx + 1) % docxFind.matches.length;
      docxFindGo(docxFind.matches, docxFind.idx);
      const countEl = document.getElementById('wa-docx-find-count');
      if (countEl) countEl.textContent = `${docxFind.idx + 1} / ${docxFind.matches.length}`;
    };

    window.WA.docxFindPrev = () => {
      if (!docxFind.matches.length) return;
      docxFind.idx = (docxFind.idx - 1 + docxFind.matches.length) % docxFind.matches.length;
      docxFindGo(docxFind.matches, docxFind.idx);
      const countEl = document.getElementById('wa-docx-find-count');
      if (countEl) countEl.textContent = `${docxFind.idx + 1} / ${docxFind.matches.length}`;
    };

    window.WA.docxFindKeydown = (event) => {
      if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        window.WA.docxFindNext();
      }
      if (event.key === 'Enter' && event.shiftKey) {
        event.preventDefault();
        window.WA.docxFindPrev();
      }
      if (event.key === 'Escape') window.WA.docxFindClose();
    };

    window.WA.docxFindClose = () => {
      const bar = document.getElementById('wa-docx-find-bar');
      if (bar) bar.style.display = 'none';
      docxFind.matches = [];
      docxFind.idx = -1;
      const input = document.getElementById('wa-docx-find-input');
      if (input) {
        input.value = '';
        input.classList.remove('no-match');
      }
      const countEl = document.getElementById('wa-docx-find-count');
      if (countEl) countEl.textContent = '';
      const pm = document.querySelector('#wa-docx-editor .ProseMirror');
      if (pm) pm.focus();
    };

    window.WA.docxToggleReplace = (forceOpen) => {
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

    window.WA.docxReplaceNext = () => {
      const activeEditor = getActiveEditor();
      const editor = activeEditor && activeEditor.editor;
      if (!editor || !docxFind.matches.length || docxFind.idx < 0) return;
      const replaceVal = (document.getElementById('wa-docx-replace-input') || {}).value || '';
      const { from, to } = docxFind.matches[docxFind.idx];
      editor.chain().setTextSelection({ from, to }).insertContent(replaceVal).run();
      const query = (document.getElementById('wa-docx-find-input') || {}).value || '';
      docxFindUpdateCount(query.trim());
    };

    window.WA.docxReplaceAll = () => {
      const activeEditor = getActiveEditor();
      const editor = activeEditor && activeEditor.editor;
      if (!editor || !docxFind.matches.length) return;
      const replaceVal = (document.getElementById('wa-docx-replace-input') || {}).value || '';
      const count = docxFind.matches.length;
      const sorted = [...docxFind.matches].sort((a, b) => b.from - a.from);
      editor.chain().focus().run();
      for (const { from, to } of sorted) {
        editor.chain().setTextSelection({ from, to }).insertContent(replaceVal).run();
      }
      showToast(`已替换 ${count} 处`, 'success');
      const query = (document.getElementById('wa-docx-find-input') || {}).value || '';
      docxFindUpdateCount(query.trim());
    };

    const pptxFind = {
      matches: [],
      idx: 0,
      replaceOpen: false,
    };

    function pptxFindAll(query, caseSensitive) {
      const editor = getActiveEditor();
      if (!editor || !editor.data || !query) return [];
      const q = caseSensitive ? query : query.toLowerCase();
      const results = [];
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

    function pptxFindGo(matches, idx) {
      const editor = getActiveEditor();
      if (!editor || !matches.length) return;
      const { slideIdx } = matches[idx];
      if (typeof editor._curIdx !== 'undefined' && editor._curIdx !== slideIdx) {
        pptxNav(slideIdx - editor._curIdx);
      }
    }

    function pptxFindUpdateCount(query) {
      const caseSensitive = (document.getElementById('wa-pptx-find-case') || {}).checked;
      pptxFind.matches = pptxFindAll(query, caseSensitive);
      pptxFind.idx = pptxFind.matches.length ? 0 : -1;
      const countEl = document.getElementById('wa-pptx-find-count');
      const input = document.getElementById('wa-pptx-find-input');
      if (countEl) countEl.textContent = pptxFind.matches.length ? `1 / ${pptxFind.matches.length}` : (query ? '无匹配' : '');
      if (input) input.classList.toggle('no-match', !!query && !pptxFind.matches.length);
      if (pptxFind.matches.length) pptxFindGo(pptxFind.matches, 0);
    }

    window.WA.pptxFindInput = (value) => pptxFindUpdateCount(String(value || '').trim());

    window.WA.pptxFindNext = () => {
      if (!pptxFind.matches.length) return;
      pptxFind.idx = (pptxFind.idx + 1) % pptxFind.matches.length;
      pptxFindGo(pptxFind.matches, pptxFind.idx);
      const countEl = document.getElementById('wa-pptx-find-count');
      if (countEl) countEl.textContent = `${pptxFind.idx + 1} / ${pptxFind.matches.length}`;
    };

    window.WA.pptxFindPrev = () => {
      if (!pptxFind.matches.length) return;
      pptxFind.idx = (pptxFind.idx - 1 + pptxFind.matches.length) % pptxFind.matches.length;
      pptxFindGo(pptxFind.matches, pptxFind.idx);
      const countEl = document.getElementById('wa-pptx-find-count');
      if (countEl) countEl.textContent = `${pptxFind.idx + 1} / ${pptxFind.matches.length}`;
    };

    window.WA.pptxFindKeydown = (event) => {
      if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        window.WA.pptxFindNext();
      }
      if (event.key === 'Enter' && event.shiftKey) {
        event.preventDefault();
        window.WA.pptxFindPrev();
      }
      if (event.key === 'Escape') window.WA.pptxFindClose();
    };

    window.WA.pptxFindClose = () => {
      const bar = document.getElementById('wa-pptx-find-bar');
      if (bar) bar.style.display = 'none';
      pptxFind.matches = [];
      pptxFind.idx = -1;
      const input = document.getElementById('wa-pptx-find-input');
      if (input) {
        input.value = '';
        input.classList.remove('no-match');
      }
      const countEl = document.getElementById('wa-pptx-find-count');
      if (countEl) countEl.textContent = '';
    };

    window.WA.pptxToggleReplace = (forceOpen) => {
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

    function pptxApplyReplace(match, replaceVal) {
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
      run.text = run.text.substring(0, match.charIdx) + replaceVal + run.text.substring(match.charIdx + match.len);
      if (editor._curIdx === match.slideIdx && typeof editor._renderSlide === 'function') editor._renderSlide(match.slideIdx);
      if (typeof editor._redrawThumb === 'function') editor._redrawThumb(match.slideIdx);
      scheduleAutoSave();
      return true;
    }

    window.WA.pptxReplaceNext = () => {
      if (!pptxFind.matches.length || pptxFind.idx < 0) return;
      const replaceVal = (document.getElementById('wa-pptx-replace-input') || {}).value || '';
      pptxApplyReplace(pptxFind.matches[pptxFind.idx], replaceVal);
      const query = (document.getElementById('wa-pptx-find-input') || {}).value || '';
      pptxFindUpdateCount(query.trim());
    };

    window.WA.pptxReplaceAll = () => {
      if (!pptxFind.matches.length) return;
      const replaceVal = (document.getElementById('wa-pptx-replace-input') || {}).value || '';
      const count = pptxFind.matches.length;
      [...pptxFind.matches].reverse().forEach((match) => pptxApplyReplace(match, replaceVal));
      showToast(`已替换 ${count} 处`, 'success');
      const query = (document.getElementById('wa-pptx-find-input') || {}).value || '';
      pptxFindUpdateCount(query.trim());
    };
  };
})();
