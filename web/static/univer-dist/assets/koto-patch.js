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
    console.log('[Koto Patch] ✅ 快捷键 & 浮动工具栏已增强');
  });

})();
