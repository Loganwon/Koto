/**
 * koto-patch.js — 运行时扩展补丁（无需重新构建）
 *
 * 提供:
 *   1. 扩展浮动快速助手：8 项 AI 操作（翻译/改写/续写/摘要/润色/标注/引用/AI指令）
 *   2. Word 风格 + AI 专属键盘快捷键
 *   3. 初次进入自动激活文档
 */
(function () {
  'use strict';

  // ── 操作定义 ──────────────────────────────────────────────
  var ACTIONS = [
    { action: 'translate',        icon: '🌐', label: '翻译' },
    { action: 'rewrite',          icon: '✏️', label: '改写' },
    { action: 'continue_writing', icon: '📝', label: '续写' },
    { action: 'polish',           icon: '✨', label: '润色' },
    { action: 'summarize',        icon: '📋', label: '摘要' },
    { action: 'annotate',         icon: '🔖', label: '标注' },
    { action: 'quote',            icon: '❝',  label: '引用' },
    { action: 'custom',           icon: '💬', label: 'AI' },
  ];

  var LABEL_MAP = {};
  ACTIONS.forEach(function (a) { LABEL_MAP[a.action] = a.label; });

  // ── 等待 __koto 就绪 ──────────────────────────────────────
  function onReady(cb) {
    var n = 0;
    var t = setInterval(function () {
      n++;
      if (window.__koto && window.__koto.floatingToolbar && window.__koto.socketBridge) {
        clearInterval(t);
        cb();
      }
      if (n > 150) clearInterval(t); // 15 秒超时
    }, 100);
  }

  // ═════════════════════════════════════════════════════════
  // 1. 扩展浮动工具栏
  // ═════════════════════════════════════════════════════════
  function patchFloatingToolbar(ft) {
    var toolbar = ft._toolbar;
    if (!toolbar) return;

    // 重建 HTML（两行布局）
    toolbar.innerHTML = ACTIONS.map(function (a) {
      return '<button class="ft-btn" data-action="' + a.action + '" title="' + a.label + '">'
        + a.icon + ' ' + a.label + '</button>';
    }).join('');
    toolbar.style.flexWrap = 'wrap';
    toolbar.style.maxWidth = '270px';
    toolbar.style.gap = '4px';

    toolbar.addEventListener('mousedown', function (e) {
      e.preventDefault();
      e.stopPropagation();
    });

    toolbar.querySelectorAll('.ft-btn').forEach(function (btn) {
      btn.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        _runAction(ft, btn.dataset.action);
      });
    });
  }

  function _runAction(ft, action) {
    var koto = window.__koto;
    if (!koto) return;
    var bridge = koto.socketBridge;
    var panel  = koto.aiPanel;
    var doc    = koto.docController;

    if (!ft._selectedText) return;

    var selData = {
      text:      ft._selectedText,
      range:     ft._selectionRange,
      fullText:  doc.getFullText(),
    };

    var label = LABEL_MAP[action] || action;
    var preview = ft._selectedText.substring(0, 40) + (ft._selectedText.length > 40 ? '…' : '');

    if (action === 'quote') {
      // 引用：纯客户端格式化，不需要 AI
      var quoted = '\n「' + ft._selectedText + '」\n';
      panel.addMessage('引用格式化', 'user');
      panel.startStreamMessage();
      panel.appendStreamChunk(quoted);
      panel.finalizeStreamMessage(quoted, 'quote', selData);
      panel.expand();
    } else if (action === 'custom') {
      var instruction = prompt('输入 AI 指令（将应用于选中文本）：');
      if (!instruction) return;
      panel.addMessage(instruction, 'user');
      bridge.sendAction('custom_instruction', { instruction: instruction, context: selData });
      panel.expand();
    } else {
      panel.addMessage(label + '：「' + preview + '」', 'user');
      bridge.sendAction(action, selData);
      panel.expand();
    }

    ft.hide();
  }

  // ═════════════════════════════════════════════════════════
  // 2. 键盘快捷键
  // ═════════════════════════════════════════════════════════
  //
  // Word 原生快捷键（Univer 已处理）：
  //   Ctrl+Z/Y  Undo/Redo        Ctrl+B/I/U  Bold/Italic/Underline
  //   Ctrl+A    Select All       Ctrl+F      Find
  //   Ctrl+C/X/V  Copy/Cut/Paste
  //
  // Koto 新增快捷键：
  //   Ctrl+S          → 保存（FileManager 已绑定，此处作备份）
  //   Ctrl+N          → 新建文档（阻止浏览器新窗口）
  //   Ctrl+Shift+E    → 导出为 .txt
  //   Ctrl+Shift+T    → AI 翻译（选中文本或全文）
  //   Ctrl+Shift+R    → AI 改写
  //   Ctrl+Shift+P    → AI 润色
  //   Ctrl+Shift+U    → AI 续写（U for continUe）
  //   Ctrl+Shift+M    → AI 摘要（M for suMmarize）
  //   Ctrl+Shift+A    → AI 标注

  var AI_SHORTCUT_MAP = {
    'T': 'translate',
    'R': 'rewrite',
    'P': 'polish',
    'U': 'continue_writing',
    'M': 'summarize',
    'A': 'annotate',
  };

  function addKeyboardShortcuts() {
    var koto = window.__koto;

    document.addEventListener('keydown', function (e) {
      var ctrl  = e.ctrlKey || e.metaKey;
      var shift = e.shiftKey;
      var key   = e.key; // e.g. 'n', 'N', 's', 'T' …

      // Ctrl+N → 新建文档（阻止浏览器打开新窗口）
      if (ctrl && !shift && (key === 'n' || key === 'N')) {
        e.preventDefault();
        var fm = koto.fileManager;
        if (fm && fm._createDoc) fm._createDoc();
        return;
      }

      // Ctrl+S → 保存（备份；FileManager 的 Ctrl+S 监听优先）
      if (ctrl && !shift && (key === 's' || key === 'S')) {
        e.preventDefault();
        var fm = koto.fileManager;
        if (fm && fm.saveWithFeedback) fm.saveWithFeedback();
        return;
      }

      // Ctrl+Shift+E → 导出为 .txt
      if (ctrl && shift && (key === 'e' || key === 'E')) {
        e.preventDefault();
        _exportTxt();
        return;
      }

      // Ctrl+Shift+<letter> → AI 操作
      if (ctrl && shift) {
        var upper = key.toUpperCase();
        var action = AI_SHORTCUT_MAP[upper];
        if (action) {
          e.preventDefault();
          _triggerAIShortcut(action);
        }
      }
    }, true); // capture phase — fires before Univer swallows events
  }

  function _triggerAIShortcut(action) {
    var koto = window.__koto;
    if (!koto) return;
    var bridge = koto.socketBridge;
    var panel  = koto.aiPanel;
    var doc    = koto.docController;

    var sel      = window.getSelection();
    var selText  = sel && !sel.isCollapsed ? sel.toString().trim() : '';
    var fullText = doc.getFullText();

    var payload;
    if (selText) {
      var idx = fullText.indexOf(selText);
      payload = {
        text:     selText,
        range:    idx >= 0
          ? { startOffset: idx, endOffset: idx + selText.length }
          : { startOffset: 0, endOffset: fullText.length },
        fullText: fullText,
      };
    } else {
      // 无选中 → 操作全文
      payload = { text: fullText, fullText: fullText };
    }

    var label   = LABEL_MAP[action] || action;
    var preview = (payload.text || '').substring(0, 30);
    panel.addMessage(label + '（快捷键）：「' + preview + (payload.text.length > 30 ? '…' : '') + '」', 'user');
    bridge.sendAction(action, payload);
    panel.expand();
  }

  function _exportTxt() {
    var koto = window.__koto;
    if (!koto) return;
    var doc  = koto.docController;
    var fm   = koto.fileManager;
    var text = doc.getFullText();
    var activeFile = fm._files && fm._activeId
      ? fm._files.find(function (f) { return f.id === fm._activeId; })
      : null;
    var name = (activeFile && activeFile.name) ? activeFile.name : '文档';
    var blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
    var a    = document.createElement('a');
    a.href     = URL.createObjectURL(blob);
    a.download = name.replace(/\.[^.]+$/, '') + '.txt';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(a.href);
  }

  // ═════════════════════════════════════════════════════════
  // 3. 显示快捷键提示（右面板底部挂件）
  // ═════════════════════════════════════════════════════════
  function injectShortcutHint() {
    // 挂在 AI 面板的输入栏上方
    var inputBar = document.querySelector('.ai-input-bar');
    if (!inputBar) return;
    var hint = document.createElement('div');
    hint.className = 'koto-shortcut-hint';
    hint.innerHTML = [
      '<span title="翻译">Ctrl+Shift+T 翻译</span>',
      '<span title="改写">Ctrl+Shift+R 改写</span>',
      '<span title="润色">Ctrl+Shift+P 润色</span>',
      '<span title="续写">Ctrl+Shift+U 续写</span>',
      '<span title="摘要">Ctrl+Shift+M 摘要</span>',
      '<span title="新建">Ctrl+N 新建</span>',
      '<span title="导出">Ctrl+Shift+E 导出</span>',
    ].join('');
    inputBar.parentNode.insertBefore(hint, inputBar);
  }

  // ═════════════════════════════════════════════════════════
  // Boot
  // ═════════════════════════════════════════════════════════
  onReady(function () {
    patchFloatingToolbar(window.__koto.floatingToolbar);
    addKeyboardShortcuts();
    injectShortcutHint();
    // fetch interceptor is installed immediately by the AltViewer IIFE below
    console.log('[Koto Patch] ✅ 快捷键 & 浮动工具栏 & 多格式查看器 已增强');
  });

})();

// ═════════════════════════════════════════════════════════════════
// AltViewer — 多格式文件查看器（独立 IIFE，不依赖 __koto 就绪）
// ═════════════════════════════════════════════════════════════════
(function () {
  'use strict';

  // ── AltViewer controller ──────────────────────────────────────
  var AltViewer = {
    _currentDocContent: '',
    _currentDocId: '',

    show: function (data) {
      var el = document.getElementById('koto-alt-viewer');
      var uc = document.getElementById('univer-container');
      if (!el) return;

      this._currentDocContent = data.content || '';
      this._currentDocId = data.id || '';

      // Show viewer, hide (but keep) Univer canvas
      el.style.display = 'flex';
      if (uc) uc.style.visibility = 'hidden';

      // Update filename bar
      var fnEl = document.getElementById('koto-viewer-filename');
      var iconEl = document.getElementById('koto-viewer-icon');
      if (fnEl) fnEl.textContent = data.name || data.importedFrom || '文件';

      var vd = data.viewerData || {};
      var iconMap = { pdf: '📕', excel: '📊', csv: '📋', ppt: '📑', code: '💻', markdown: '📝', docx: '📘' };
      if (iconEl) iconEl.textContent = iconMap[vd.type] || '📄';

      // Render body
      var body = document.getElementById('koto-viewer-body');
      if (body) body.innerHTML = '';

      switch (vd.type) {
        case 'pdf':     this._renderPDF(data.id, body); break;
        case 'excel':   this._renderExcel(vd, body); break;
        case 'csv':     this._renderCSV(vd, body); break;
        case 'ppt':     this._renderPPT(vd, body); break;
        case 'code':    this._renderCode(data.content || '', vd.lang || 'text', body); break;
        case 'markdown':this._renderCode(data.content || '', 'markdown', body); break;
        case 'docx':    this._renderDocxImages(vd, body); break;
        default:        el.style.display = 'none'; if (uc) uc.style.visibility = 'visible'; return;
      }

      // Bind toolbar buttons
      var toTextBtn = document.getElementById('koto-viewer-to-text');
      var aiBtn = document.getElementById('koto-viewer-ai');
      if (toTextBtn) {
        toTextBtn.onclick = function () { AltViewer.convertToText(); };
      }
      if (aiBtn) {
        aiBtn.onclick = function () { AltViewer.aiAnalyze(); };
      }

      // DOCX: also show Univer editor alongside image badge
      if (vd.type === 'docx') {
        el.style.display = 'none';  // Don't show full overlay
        if (uc) uc.style.visibility = 'visible';
        this._injectDocxBadge(vd);
      }
    },

    hide: function () {
      var el = document.getElementById('koto-alt-viewer');
      var uc = document.getElementById('univer-container');
      if (el) el.style.display = 'none';
      if (uc) uc.style.visibility = 'visible';
      // Remove docx badge if any
      var badge = document.getElementById('koto-docx-img-badge');
      if (badge) badge.remove();
      var gallery = document.getElementById('koto-docx-img-gallery');
      if (gallery) gallery.remove();
    },

    convertToText: function () {
      var koto = window.__koto;
      if (!koto) return;
      // Load text content into Univer doc editor
      if (koto.docController && this._currentDocContent) {
        koto.docController.loadContent(this._currentDocContent);
      }
      this.hide();
    },

    aiAnalyze: function () {
      var koto = window.__koto;
      if (!koto) return;
      var panel = koto.aiPanel;
      var bridge = koto.socketBridge;
      if (!this._currentDocContent) {
        if (panel) panel.addMessage('文件内容为空。', 'error');
        return;
      }
      if (panel) panel.addMessage('🤖 AI 分析文件内容…', 'user');
      if (bridge) bridge.sendAction('summarize', { text: this._currentDocContent, fullText: this._currentDocContent });
      if (panel) panel.expand();
    },

    // ── Renderers ──

    _renderPDF: function (docId, body) {
      var iframe = document.createElement('iframe');
      iframe.className = 'koto-pdf-frame';
      iframe.title = 'PDF 预览';
      iframe.src = '/api/editor/docs/' + encodeURIComponent(docId) + '/raw';
      body.appendChild(iframe);
    },

    _renderExcel: function (vd, body) {
      var sheets = vd.sheets || [];
      if (!sheets.length) { body.textContent = '（空表格）'; return; }

      // Tab bar
      var tabBar = document.createElement('div');
      tabBar.className = 'koto-sheet-tabs';
      var currentSheet = 0;

      var tableWrapper = document.createElement('div');
      tableWrapper.className = 'koto-table-wrapper';
      tableWrapper.style.height = 'calc(100% - 36px)';
      tableWrapper.style.overflow = 'auto';

      function renderSheet(idx) {
        currentSheet = idx;
        tabBar.querySelectorAll('.koto-sheet-tab').forEach(function (t, i) {
          t.classList.toggle('active', i === idx);
        });
        tableWrapper.innerHTML = '';
        var sheet = sheets[idx];
        var rows = sheet.rows || [];
        if (!rows.length) { tableWrapper.textContent = '（空）'; return; }

        var table = document.createElement('table');
        table.className = 'koto-sheet-table';

        // Row number + data headers (A B C…)
        var maxCols = rows.reduce(function (m, r) { return Math.max(m, r.length); }, 0);
        var thead = document.createElement('thead');
        var hrow = document.createElement('tr');
        var thNum = document.createElement('th');
        thNum.textContent = '#';
        hrow.appendChild(thNum);
        for (var ci = 0; ci < maxCols; ci++) {
          var th = document.createElement('th');
          // Convert col index to letter(s): A, B, ... Z, AA, AB...
          var colLabel = '';
          var n = ci;
          do {
            colLabel = String.fromCharCode(65 + (n % 26)) + colLabel;
            n = Math.floor(n / 26) - 1;
          } while (n >= 0);
          th.textContent = colLabel;
          hrow.appendChild(th);
        }
        thead.appendChild(hrow);
        table.appendChild(thead);

        var tbody = document.createElement('tbody');
        rows.forEach(function (row, ri) {
          var tr = document.createElement('tr');
          var tdNum = document.createElement('td');
          tdNum.textContent = ri + 1;
          tdNum.style.color = '#999';
          tdNum.style.background = '#f0f0f0';
          tdNum.style.fontWeight = '500';
          tr.appendChild(tdNum);
          for (var ci2 = 0; ci2 < maxCols; ci2++) {
            var td = document.createElement('td');
            var cell = row[ci2];
            td.textContent = cell ? String(cell.v !== undefined ? cell.v : '') : '';
            if (cell && cell.t === 'n') td.style.textAlign = 'right';
            tr.appendChild(td);
          }
          tbody.appendChild(tr);
        });
        table.appendChild(tbody);
        tableWrapper.appendChild(table);
      }

      sheets.forEach(function (sheet, idx) {
        var tab = document.createElement('div');
        tab.className = 'koto-sheet-tab' + (idx === 0 ? ' active' : '');
        tab.textContent = sheet.name || ('Sheet' + (idx + 1));
        tab.addEventListener('click', function () { renderSheet(idx); });
        tabBar.appendChild(tab);
      });

      body.style.display = 'flex';
      body.style.flexDirection = 'column';
      body.style.height = '100%';
      body.appendChild(tabBar);
      body.appendChild(tableWrapper);
      renderSheet(0);
    },

    _renderCSV: function (vd, body) {
      var headers = vd.headers || [];
      var rows = vd.rows || [];

      var wrapper = document.createElement('div');
      wrapper.className = 'koto-table-wrapper';
      wrapper.style.padding = '8px';

      var table = document.createElement('table');
      table.className = 'koto-sheet-table';

      if (headers.length) {
        var thead = document.createElement('thead');
        var hrow = document.createElement('tr');
        headers.forEach(function (h) {
          var th = document.createElement('th');
          th.textContent = h;
          hrow.appendChild(th);
        });
        thead.appendChild(hrow);
        table.appendChild(thead);
      }

      var tbody = document.createElement('tbody');
      rows.forEach(function (row, ri) {
        var tr = document.createElement('tr');
        row.forEach(function (cell) {
          var td = document.createElement('td');
          td.textContent = cell;
          tr.appendChild(td);
        });
        tbody.appendChild(tr);
      });
      table.appendChild(tbody);
      wrapper.appendChild(table);
      body.appendChild(wrapper);
    },

    _renderPPT: function (vd, body) {
      var slides = vd.slides || [];
      if (!slides.length) { body.textContent = '（空演示文稿）'; return; }

      var currentIdx = 0;

      // Nav bar
      var nav = document.createElement('div');
      nav.className = 'koto-slide-nav';
      var prevBtn = document.createElement('button');
      prevBtn.textContent = '◀ 上一页';
      var counter = document.createElement('span');
      var nextBtn = document.createElement('button');
      nextBtn.textContent = '下一页 ▶';

      nav.appendChild(prevBtn);
      nav.appendChild(counter);
      nav.appendChild(nextBtn);

      // Slide display area
      var slideArea = document.createElement('div');
      slideArea.style.overflowY = 'auto';
      slideArea.style.flex = '1';
      slideArea.style.padding = '12px';

      function showSlide(idx) {
        currentIdx = idx;
        prevBtn.disabled = idx === 0;
        nextBtn.disabled = idx === slides.length - 1;
        counter.textContent = (idx + 1) + ' / ' + slides.length;

        slideArea.innerHTML = '';
        var s = slides[idx];
        var card = document.createElement('div');
        card.className = 'koto-slide-card';

        if (s.title) {
          var header = document.createElement('div');
          header.className = 'koto-slide-header';
          header.textContent = s.title;
          card.appendChild(header);
        }

        if (s.body) {
          var sbody = document.createElement('div');
          sbody.className = 'koto-slide-body';
          sbody.textContent = s.body;
          card.appendChild(sbody);
        }

        if (s.images && s.images.length) {
          var imgRow = document.createElement('div');
          imgRow.className = 'koto-slide-images';
          s.images.forEach(function (img) {
            var im = document.createElement('img');
            im.src = img.url;
            im.alt = img.filename || '图片';
            im.title = img.filename || '图片';
            im.onerror = function () { this.style.display = 'none'; };
            imgRow.appendChild(im);
          });
          card.appendChild(imgRow);
        }

        if (s.notes) {
          var notes = document.createElement('div');
          notes.className = 'koto-slide-notes';
          notes.textContent = '备注：' + s.notes;
          card.appendChild(notes);
        }

        slideArea.appendChild(card);
      }

      prevBtn.onclick = function () { if (currentIdx > 0) showSlide(currentIdx - 1); };
      nextBtn.onclick = function () { if (currentIdx < slides.length - 1) showSlide(currentIdx + 1); };

      body.style.display = 'flex';
      body.style.flexDirection = 'column';
      body.style.height = '100%';
      body.appendChild(nav);
      body.appendChild(slideArea);
      showSlide(0);
    },

    _renderCode: function (content, lang, body) {
      var header = document.createElement('div');
      header.className = 'koto-code-header';

      var badge = document.createElement('span');
      badge.className = 'koto-lang-badge';
      badge.textContent = lang;
      header.appendChild(badge);

      var copyBtn = document.createElement('button');
      copyBtn.className = 'koto-copy-btn';
      copyBtn.textContent = '📋 复制';
      copyBtn.onclick = function () {
        navigator.clipboard.writeText(content).then(function () {
          copyBtn.textContent = '✅ 已复制';
          setTimeout(function () { copyBtn.textContent = '📋 复制'; }, 2000);
        }).catch(function () {
          copyBtn.textContent = '❌ 失败';
        });
      };
      header.appendChild(copyBtn);

      var pre = document.createElement('pre');
      pre.className = 'koto-code-block';
      // Safely escape HTML
      pre.textContent = content;

      body.appendChild(header);
      body.appendChild(pre);
    },

    // DOCX: show images as a badge above the Univer editor (editor stays usable)
    _injectDocxBadge: function (vd) {
      var images = vd.images || [];
      if (!images.length) return;

      var container = document.getElementById('univer-container');
      if (!container) return;

      // Remove existing badge/gallery
      var old = document.getElementById('koto-docx-img-badge');
      if (old) old.remove();
      var oldG = document.getElementById('koto-docx-img-gallery');
      if (oldG) oldG.remove();

      var badge = document.createElement('div');
      badge.id = 'koto-docx-img-badge';
      badge.className = 'koto-img-badge';
      badge.style.cssText = 'position:absolute;top:8px;right:12px;z-index:30;';
      badge.innerHTML = '📷 ' + images.length + ' 张图片';

      var gallery = document.createElement('div');
      gallery.id = 'koto-docx-img-gallery';
      gallery.className = 'koto-img-gallery';
      gallery.style.cssText = 'position:absolute;top:40px;right:0;left:0;z-index:29;display:none;max-height:200px;overflow-y:auto;';
      images.forEach(function (img) {
        var im = document.createElement('img');
        im.src = img.url;
        im.alt = img.filename || '图片';
        im.title = img.filename;
        im.onerror = function () { this.style.display = 'none'; };
        gallery.appendChild(im);
      });

      badge.onclick = function () {
        gallery.style.display = gallery.style.display === 'none' ? 'flex' : 'none';
      };

      var parent = container.parentElement;
      if (parent) {
        parent.style.position = 'relative';
        parent.appendChild(badge);
        parent.appendChild(gallery);
      }
    },
  };

  // Expose AltViewer globally so the fetch interceptor (inside main IIFE) can call it
  window.__kotoAltViewer = AltViewer;

  // Script has `defer` so DOM is interactive when we run — install directly.
  installFetchInterceptor();

  function installFetchInterceptor() {
    if (window.__kotoFetchPatched) return;
    window.__kotoFetchPatched = true;

    var origFetch = window.fetch;
    window.fetch = function (input, init) {
      var url = typeof input === 'string' ? input : (input && input.url) || String(input);
      var p = origFetch.apply(this, arguments);

      if (/\/api\/editor\/docs\/[a-zA-Z0-9_-]+$/.test(url)) {
        var method = (init && init.method ? init.method : 'GET').toUpperCase();
        if (method === 'GET') {
          p.then(function (res) {
            var clone = res.clone();
            clone.json().then(function (data) {
              if (data && data.viewerData && data.viewerData.type) {
                setTimeout(function () { AltViewer.show(data); }, 80);
              } else {
                AltViewer.hide();
              }
            }).catch(function () {});
          }).catch(function () {});
        }
      }

      return p;
    };
  }

})();
