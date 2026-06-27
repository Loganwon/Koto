(function() {
  "use strict";
  const OVERLAY_ID = "skill-ui-overlay";
  const CSS_STYLE_ID = "skill-ui-css-vars";
  const FONT_STYLE_ID = "skill-ui-font";
  let _isApplied = false;
  let _originalTitle = "";
  let _originalSubtitle = "";
  let _originalTheme = "";
  let _originalPlaceholder = "";
  let _assistantPrefix = "";
  let _lastDivinationConfig = null;
  function applyCSS(cssVars, theme) {
    let styleEl = document.getElementById(CSS_STYLE_ID);
    if (!styleEl) {
      styleEl = document.createElement("style");
      styleEl.id = CSS_STYLE_ID;
      document.head.appendChild(styleEl);
    }
    const rules = [];
    if (theme) {
      const htmlEl = document.documentElement;
      if (!_isApplied) {
        _originalTheme = htmlEl.getAttribute("data-theme") || "";
      }
      htmlEl.setAttribute("data-theme", theme);
    }
    if (cssVars && Object.keys(cssVars).length > 0) {
      const varLines = Object.entries(cssVars).map(([k, v]) => `    ${k}: ${v} !important;`).join("\n");
      rules.push(`:root, [data-theme], body, html, #chatMessages {
${varLines}
}`);
    }
    if (cssVars && cssVars["--text-primary"]) {
      const c = cssVars["--text-primary"];
      rules.push(`#messageInput { color: ${c} !important; caret-color: ${c}; }`);
    }
    styleEl.textContent = rules.join("\n");
  }
  function removeCSS() {
    const styleEl = document.getElementById(CSS_STYLE_ID);
    if (styleEl) styleEl.textContent = "";
    if (_originalTheme !== null && _originalTheme !== void 0) {
      const htmlEl = document.documentElement;
      if (_originalTheme) {
        htmlEl.setAttribute("data-theme", _originalTheme);
      } else {
        htmlEl.removeAttribute("data-theme");
      }
      _originalTheme = "";
    }
  }
  function applyFont(fontStyle) {
    let styleEl = document.getElementById(FONT_STYLE_ID);
    if (!styleEl) {
      styleEl = document.createElement("style");
      styleEl.id = FONT_STYLE_ID;
      document.head.appendChild(styleEl);
    }
    const fontMap = {
      "serif": "'Georgia', 'Times New Roman', serif",
      "mono": "'JetBrains Mono', 'Consolas', monospace",
      "handwriting": "'Segoe Script', 'cursive'"
    };
    const family = fontMap[fontStyle] || fontStyle;
    if (family) {
      styleEl.textContent = `body { font-family: ${family} !important; }`;
      styleEl.textContent += `
#messageInput, .message-content, .tp-heading, .tp-subheading, .tp-face-name-zh { font-family: ${family} !important; }`;
    }
  }
  function removeFont() {
    const styleEl = document.getElementById(FONT_STYLE_ID);
    if (styleEl) styleEl.textContent = "";
  }
  function applyOverlay(effect) {
    removeOverlay();
    if (!effect) return;
    const el = document.createElement("div");
    el.id = OVERLAY_ID;
    el.className = `skill-ui-overlay skill-ui-overlay-${effect}`;
    el.setAttribute("aria-hidden", "true");
    if (effect === "stars") {
      for (let i = 0; i < 120; i++) {
        const star = document.createElement("div");
        star.className = "skill-ui-star";
        star.style.cssText = `
        left: ${Math.random() * 100}%;
        top: ${Math.random() * 100}%;
        width: ${Math.random() * 2.5 + 0.5}px;
        height: ${Math.random() * 2.5 + 0.5}px;
        animation-delay: ${Math.random() * 4}s;
        animation-duration: ${2 + Math.random() * 3}s;
      `;
        el.appendChild(star);
      }
    }
    if (effect === "crystals") {
      for (let i = 0; i < 8; i++) {
        const gem = document.createElement("div");
        gem.className = "skill-ui-crystal";
        gem.style.cssText = `
        left: ${10 + Math.random() * 80}%;
        top: ${10 + Math.random() * 80}%;
        animation-delay: ${Math.random() * 5}s;
        animation-duration: ${6 + Math.random() * 6}s;
        transform: rotate(${Math.random() * 360}deg);
      `;
        el.appendChild(gem);
      }
    }
    if (effect === "candles") {
      for (let i = 0; i < 5; i++) {
        const candle = document.createElement("div");
        candle.className = "skill-ui-candle";
        candle.style.cssText = `left: ${8 + i * 21}%; animation-delay: ${Math.random() * 1.5}s;`;
        el.appendChild(candle);
      }
    }
    document.body.appendChild(el);
  }
  function removeOverlay() {
    const el = document.getElementById(OVERLAY_ID);
    if (el) el.remove();
  }
  function applyPlaceholder(text) {
    const input = document.getElementById("messageInput") || document.querySelector(".chat-input textarea, textarea[placeholder]");
    if (!input) return;
    if (!_originalPlaceholder) _originalPlaceholder = input.placeholder;
    if (text) input.placeholder = text;
  }
  function restorePlaceholder() {
    const input = document.getElementById("messageInput") || document.querySelector(".chat-input textarea, textarea[placeholder]");
    if (!input) return;
    if (_originalPlaceholder) input.placeholder = _originalPlaceholder;
    _originalPlaceholder = "";
  }
  function applyTitle(titleText, subtitleText) {
    const titleEl = document.querySelector(".logo-text");
    const subEl = document.querySelector(".logo-sub");
    if (titleEl) {
      if (!_originalTitle) _originalTitle = titleEl.textContent || "";
      if (titleText) titleEl.textContent = titleText;
    }
    if (subEl) {
      if (!_originalSubtitle) _originalSubtitle = subEl.textContent || "";
      if (subtitleText) subEl.textContent = subtitleText;
    }
  }
  function restoreTitle() {
    const titleEl = document.querySelector(".logo-text");
    const subEl = document.querySelector(".logo-sub");
    if (titleEl && _originalTitle) {
      titleEl.textContent = _originalTitle;
      _originalTitle = "";
    }
    if (subEl && _originalSubtitle) {
      subEl.textContent = _originalSubtitle;
      _originalSubtitle = "";
    }
  }
  function applySkillBarVisibility(hide) {
    const bar = document.getElementById("chat-skill-bar");
    if (bar) bar.style.setProperty("--skill-bar-display", hide ? "none" : "");
  }
  function applyAssistantPrefix(prefix) {
    _assistantPrefix = prefix || "";
    window.skillUiAssistantPrefix = _assistantPrefix;
  }
  function escapeHtml(s) {
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }
  function showWelcomeText(text) {
    if (!text) return;
    const chatMessages = document.getElementById("chatMessages") || document.querySelector(".messages-container, .chat-messages");
    if (!chatMessages) return;
    const existing = document.getElementById("skill-ui-welcome");
    if (existing) existing.remove();
    const el = document.createElement("div");
    el.id = "skill-ui-welcome";
    el.className = "skill-ui-welcome";
    el.innerHTML = `<div class="skill-ui-welcome-inner">${escapeHtml(text)}</div>`;
    chatMessages.insertBefore(el, chatMessages.firstChild);
  }
  function removeWelcomeText() {
    const el = document.getElementById("skill-ui-welcome");
    if (el) el.remove();
  }
  function applySkillUI(config, isNew) {
    applyCSS(config.css_vars || {}, config.theme || "");
    applyOverlay(config.overlay_effect || "");
    applyPlaceholder(config.input_placeholder || "");
    applyTitle(config.title_text || "", config.subtitle_text || "");
    applyFont(config.font_style || "");
    applyAssistantPrefix(config.assistant_prefix || "");
    applySkillBarVisibility(config.hide_skill_bar || false);
    if (isNew && config.welcome_text) {
      showWelcomeText(config.welcome_text);
    }
    _isApplied = true;
  }
  function removeSkillUI() {
    if (!_isApplied) return;
    removeCSS();
    removeOverlay();
    restorePlaceholder();
    restoreTitle();
    removeFont();
    removeWelcomeText();
    applyAssistantPrefix("");
    applySkillBarVisibility(false);
    _isApplied = false;
  }
  let _lastSources = JSON.stringify([]);
  async function fetchAndApply() {
    try {
      const res = await fetch("/api/skills/active-ui-config");
      if (!res.ok) return;
      const data = await res.json();
      if (!data.success) return;
      const sourcesStr = JSON.stringify(data.sources || []);
      const isNew = sourcesStr !== _lastSources;
      _lastSources = sourcesStr;
      const sourceList = Array.isArray(data.sources) ? data.sources : [];
      const hasDivinationSource = sourceList.includes("divination");
      const tarotPersistent = Boolean(
        window.TarotPicker && typeof window.TarotPicker.isPersistentActive === "function" && window.TarotPicker.isPersistentActive() || document.getElementById("tarot-picker-widget") || window._kotoTarotPending
      );
      if (data.has_ui && hasDivinationSource && data.config) {
        _lastDivinationConfig = data.config;
      }
      if (data.has_ui) {
        const configToApply = tarotPersistent && _lastDivinationConfig ? _lastDivinationConfig : data.config;
        applySkillUI(configToApply, isNew);
      } else if (tarotPersistent && _lastDivinationConfig) {
        applySkillUI(_lastDivinationConfig, false);
      } else {
        removeSkillUI();
      }
      const divinationActive = data.has_ui && hasDivinationSource || tarotPersistent;
      window._kotoDivinationActive = divinationActive;
      if (window.TarotPicker) {
        window.TarotPicker.setActive(divinationActive);
      }
    } catch (e) {
    }
  }
  function hookRefreshActiveSkills$1() {
    const origFn = window.refreshActiveSkills;
    window.refreshActiveSkills = async function() {
      const result = origFn ? await origFn.apply(this, arguments) : void 0;
      await fetchAndApply();
      return result;
    };
  }
  function init$1() {
    document.addEventListener("DOMContentLoaded", () => {
      fetchAndApply();
      hookRefreshActiveSkills$1();
    });
    if (document.readyState !== "loading") {
      fetchAndApply();
      hookRefreshActiveSkills$1();
    }
  }
  const SkillUI = {
    refresh: fetchAndApply,
    remove: removeSkillUI
  };
  const W$1 = window;
  W$1.SkillUI = SkillUI;
  init$1();
  const ACTION_BAR_ID = "skill-ext-action-bar";
  const FLOAT_WIDGET_ID = "skill-ext-floating-widget";
  const QUICK_REPLY_CLS = "skill-ext-quick-reply-row";
  const PERM_DIALOG_ID = "skill-ext-perm-dialog";
  let _currentExtensions = null;
  let _qrObserver = null;
  function esc(str) {
    return String(str).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
  function sendMessage(text) {
    const input = document.querySelector('#messageInput, #userInput, [data-role="chat-input"]');
    if (!input) return;
    const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value") || Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value");
    if (nativeSetter && nativeSetter.set) {
      nativeSetter.set.call(input, text);
    } else {
      input.value = text;
    }
    input.dispatchEvent(new Event("input", { bubbles: true }));
    const sendBtn = document.querySelector('#sendBtn, [data-role="send-button"], button[type="submit"]');
    if (sendBtn) {
      sendBtn.click();
    } else {
      input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    }
  }
  function renderActionButtons(buttons) {
    removeActionBar();
    if (!buttons || buttons.length === 0) return;
    const bar = document.createElement("div");
    bar.id = ACTION_BAR_ID;
    bar.className = "skill-ext-action-bar";
    bar.setAttribute("role", "toolbar");
    bar.setAttribute("aria-label", "技能快捷操作");
    buttons.forEach(function(btn) {
      const el = document.createElement("button");
      el.type = "button";
      el.className = "skill-ext-action-btn skill-ext-action-btn--" + esc(btn.variant || "default");
      el.textContent = btn.label || "";
      if (btn.tooltip) el.setAttribute("title", esc(btn.tooltip));
      el.setAttribute("data-action-id", esc(btn.id || ""));
      el.addEventListener("click", function() {
        if (btn.message) {
          sendMessage(btn.message);
        } else if (btn.action) {
          handleBuiltinAction(btn.action);
        }
      });
      bar.appendChild(el);
    });
    const inputArea = document.querySelector(
      "#inputArea, #input-area, .input-area, .chat-input-area, #chatForm"
    );
    if (inputArea) {
      inputArea.parentNode.insertBefore(bar, inputArea);
    } else {
      document.body.appendChild(bar);
    }
  }
  function removeActionBar() {
    const el = document.getElementById(ACTION_BAR_ID);
    if (el) el.remove();
  }
  function handleBuiltinAction(action, _btn) {
    if (action === "open_floating_widget" && _currentExtensions) {
      renderFloatingWidget(_currentExtensions.floating_widget);
    }
  }
  function attachQuickRepliesToMessage(msgEl, replies) {
    if (msgEl.querySelector("." + QUICK_REPLY_CLS)) return;
    const row = document.createElement("div");
    row.className = QUICK_REPLY_CLS;
    row.setAttribute("role", "group");
    row.setAttribute("aria-label", "快速回复");
    replies.forEach(function(text) {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "skill-ext-qr-chip";
      chip.textContent = text;
      chip.addEventListener("click", function() {
        sendMessage(text);
        row.remove();
      });
      row.appendChild(chip);
    });
    msgEl.appendChild(row);
  }
  function getAIMessageElements() {
    return Array.from(document.querySelectorAll(
      '.message.assistant, .message--assistant, [data-role="assistant-message"], .ai-message'
    ));
  }
  function applyQuickRepliesToLatestMessage(replies) {
    if (!replies || replies.length === 0) return;
    const msgs = getAIMessageElements();
    if (msgs.length > 0) {
      attachQuickRepliesToMessage(msgs[msgs.length - 1], replies);
    }
  }
  function startQuickReplyObserver(replies) {
    stopQuickReplyObserver();
    if (!replies || replies.length === 0) return;
    const container = document.querySelector(
      '#messages, #messageList, .messages, .chat-messages, [data-role="messages"]'
    );
    if (!container) return;
    _qrObserver = new MutationObserver(function(mutations) {
      mutations.forEach(function(m) {
        m.addedNodes.forEach(function(node) {
          if (node.nodeType !== 1) return;
          const el = node;
          const isAI = el.classList.contains("assistant") || el.classList.contains("message--assistant") || el.getAttribute("data-role") === "assistant-message" || el.classList.contains("ai-message");
          if (isAI) {
            attachQuickRepliesToMessage(el, replies);
          }
          const inner = el.querySelector(
            '.message.assistant, .message--assistant, [data-role="assistant-message"], .ai-message'
          );
          if (inner) attachQuickRepliesToMessage(inner, replies);
        });
      });
    });
    _qrObserver.observe(container, { childList: true, subtree: true });
  }
  function stopQuickReplyObserver() {
    if (_qrObserver) {
      _qrObserver.disconnect();
      _qrObserver = null;
    }
    document.querySelectorAll("." + QUICK_REPLY_CLS).forEach(function(el) {
      el.remove();
    });
  }
  const WIDGET_RENDERERS = {
    dice_roller: renderDiceRoller,
    timer: renderTimer,
    notes: renderNotes,
    calculator: renderCalculator,
    word_counter: renderWordCounter,
    color_picker: renderColorPicker
  };
  function renderFloatingWidget(widgetDef) {
    removeFloatingWidget();
    if (!widgetDef || !widgetDef.type) return;
    const renderer = WIDGET_RENDERERS[widgetDef.type];
    if (!renderer) return;
    const panel = document.createElement("div");
    panel.id = FLOAT_WIDGET_ID;
    panel.className = "skill-ext-float-panel skill-ext-float-panel--" + esc(widgetDef.type);
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-label", widgetDef.title || widgetDef.type);
    const titleBar = document.createElement("div");
    titleBar.className = "skill-ext-float-title-bar";
    titleBar.innerHTML = '<span class="skill-ext-float-title">' + esc(widgetDef.title || widgetDef.type) + '</span><button type="button" class="skill-ext-float-close" aria-label="关闭">✕</button>';
    panel.appendChild(titleBar);
    titleBar.querySelector(".skill-ext-float-close").addEventListener("click", removeFloatingWidget);
    const content = document.createElement("div");
    content.className = "skill-ext-float-content";
    renderer(content);
    panel.appendChild(content);
    const pos = widgetDef.position || "bottom-right";
    applyWidgetPosition(panel, pos);
    document.body.appendChild(panel);
    makeDraggable(panel, titleBar);
  }
  function applyWidgetPosition(el, pos) {
    const margin = "16px";
    el.style.position = "fixed";
    el.style.zIndex = "9000";
    if (pos === "bottom-right" || pos === "bottom_right") {
      el.style.bottom = margin;
      el.style.right = margin;
    } else if (pos === "bottom-left" || pos === "bottom_left") {
      el.style.bottom = margin;
      el.style.left = margin;
    } else if (pos === "top-right" || pos === "top_right") {
      el.style.top = margin;
      el.style.right = margin;
    } else if (pos === "top-left" || pos === "top_left") {
      el.style.top = margin;
      el.style.left = margin;
    }
  }
  function makeDraggable(panel, handle) {
    let startX, startY, startLeft, startTop;
    handle.style.cursor = "move";
    handle.addEventListener("mousedown", function(e) {
      if (e.target.classList.contains("skill-ext-float-close")) return;
      e.preventDefault();
      const rect = panel.getBoundingClientRect();
      startX = e.clientX;
      startY = e.clientY;
      startLeft = rect.left;
      startTop = rect.top;
      panel.style.right = "auto";
      panel.style.bottom = "auto";
      panel.style.left = startLeft + "px";
      panel.style.top = startTop + "px";
      function onMove(e2) {
        panel.style.left = startLeft + e2.clientX - startX + "px";
        panel.style.top = startTop + e2.clientY - startY + "px";
      }
      function onUp() {
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
      }
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    });
  }
  function removeFloatingWidget() {
    const el = document.getElementById(FLOAT_WIDGET_ID);
    if (el) el.remove();
  }
  function renderDiceRoller(container) {
    container.innerHTML = '<div class="skill-ext-dice">  <div class="skill-ext-dice-result" id="skill-ext-dice-result">🎲</div>  <div class="skill-ext-dice-btns">    <button type="button" data-sides="4">D4</button>    <button type="button" data-sides="6">D6</button>    <button type="button" data-sides="8">D8</button>    <button type="button" data-sides="10">D10</button>    <button type="button" data-sides="12">D12</button>    <button type="button" data-sides="20">D20</button>    <button type="button" data-sides="100">D100</button>  </div></div>';
    container.querySelectorAll("button[data-sides]").forEach(function(btn) {
      btn.addEventListener("click", function() {
        const sides = parseInt(btn.getAttribute("data-sides"), 10);
        const result = Math.floor(Math.random() * sides) + 1;
        container.querySelector("#skill-ext-dice-result").textContent = result + " / D" + sides;
      });
    });
  }
  function renderTimer(container) {
    let seconds = 0, interval = null;
    container.innerHTML = '<div class="skill-ext-timer">  <div class="skill-ext-timer-display" id="skill-ext-timer-display">00:00</div>  <div class="skill-ext-timer-btns">    <button type="button" id="skill-ext-timer-start">开始</button>    <button type="button" id="skill-ext-timer-reset">重置</button>  </div></div>';
    function pad(n) {
      return n < 10 ? "0" + n : "" + n;
    }
    function updateDisplay() {
      const m = Math.floor(seconds / 60), s = seconds % 60;
      container.querySelector("#skill-ext-timer-display").textContent = pad(m) + ":" + pad(s);
    }
    const startBtn = container.querySelector("#skill-ext-timer-start");
    const resetBtn = container.querySelector("#skill-ext-timer-reset");
    startBtn.addEventListener("click", function() {
      if (interval) {
        clearInterval(interval);
        interval = null;
        startBtn.textContent = "继续";
      } else {
        interval = setInterval(function() {
          seconds++;
          updateDisplay();
        }, 1e3);
        startBtn.textContent = "暂停";
      }
    });
    resetBtn.addEventListener("click", function() {
      clearInterval(interval);
      interval = null;
      seconds = 0;
      updateDisplay();
      startBtn.textContent = "开始";
    });
  }
  function renderNotes(container) {
    const storageKey = "skill_ext_notes";
    container.innerHTML = '<textarea class="skill-ext-notes-area" placeholder="在此记笔记…" rows="6" style="width:100%;resize:vertical;box-sizing:border-box;font-size:0.9em;" maxlength="4096"></textarea>';
    const ta = container.querySelector("textarea");
    ta.value = sessionStorage.getItem(storageKey) || "";
    ta.addEventListener("input", function() {
      sessionStorage.setItem(storageKey, ta.value);
    });
  }
  function renderCalculator(container) {
    let expr = "";
    const btnLayout = [
      ["C", "±", "%", "÷"],
      ["7", "8", "9", "×"],
      ["4", "5", "6", "−"],
      ["1", "2", "3", "+"],
      ["0", ".", "="]
    ];
    const displayId = "skill-ext-calc-display";
    let html = '<div class="skill-ext-calc"><div class="skill-ext-calc-display" id="' + displayId + '">0</div><div class="skill-ext-calc-btns">';
    btnLayout.forEach(function(row) {
      row.forEach(function(lbl) {
        const wide = lbl === "0" ? " skill-ext-calc-btn--wide" : "";
        html += '<button type="button" class="skill-ext-calc-btn' + wide + '" data-lbl="' + esc(lbl) + '">' + esc(lbl) + "</button>";
      });
    });
    html += "</div></div>";
    container.innerHTML = html;
    const display = container.querySelector("#" + displayId);
    function setDisplay(val) {
      display.textContent = val || "0";
    }
    container.querySelectorAll(".skill-ext-calc-btn").forEach(function(btn) {
      btn.addEventListener("click", function() {
        const lbl = btn.getAttribute("data-lbl");
        if (lbl === "C") {
          expr = "";
          setDisplay("0");
          return;
        }
        if (lbl === "±") {
          if (expr && !isNaN(parseFloat(expr))) {
            expr = String(-parseFloat(expr));
            setDisplay(expr);
          }
          return;
        }
        if (lbl === "=") {
          try {
            const safeExpr = expr.replace(/×/g, "*").replace(/÷/g, "/").replace(/−/g, "-");
            if (!/^[0-9+\-*/.() %]+$/.test(safeExpr)) {
              setDisplay("错误");
              expr = "";
              return;
            }
            const result = Function('"use strict"; return (' + safeExpr + ")")();
            expr = String(result);
            setDisplay(expr);
          } catch (e) {
            setDisplay("错误");
            expr = "";
          }
          return;
        }
        if (lbl === "%") {
          try {
            const v = Function('"use strict"; return (' + expr + ")")();
            expr = String(v / 100);
            setDisplay(expr);
          } catch (e) {
            setDisplay("错误");
            expr = "";
          }
          return;
        }
        expr += lbl;
        setDisplay(expr);
      });
    });
  }
  function renderWordCounter(container) {
    container.innerHTML = '<div class="skill-ext-wordcount">  <textarea class="skill-ext-wordcount-input" placeholder="粘贴文字以计算字数…" rows="5"   style="width:100%;resize:vertical;box-sizing:border-box;" maxlength="50000"></textarea>  <div class="skill-ext-wordcount-stats">    字符：<span id="skill-ext-wc-chars">0</span>　    词数：<span id="skill-ext-wc-words">0</span>  </div></div>';
    const ta = container.querySelector("textarea");
    const charsEl = container.querySelector("#skill-ext-wc-chars");
    const wordsEl = container.querySelector("#skill-ext-wc-words");
    ta.addEventListener("input", function() {
      const text = ta.value;
      charsEl.textContent = String(text.length);
      const cjkMatches = (text.match(/[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]/g) || []).length;
      const latinMatches = (text.match(/\b[a-zA-Z'-]+\b/g) || []).length;
      wordsEl.textContent = String(cjkMatches + latinMatches);
    });
  }
  function renderColorPicker(container) {
    container.innerHTML = '<div class="skill-ext-colorpicker">  <input type="color" id="skill-ext-color-input" value="#6366f1"          style="width:100%;height:80px;border:none;cursor:pointer;">  <div class="skill-ext-color-info">    <code id="skill-ext-color-hex">#6366f1</code>    <button type="button" id="skill-ext-color-copy">复制</button>  </div></div>';
    const input = container.querySelector("#skill-ext-color-input");
    const hexEl = container.querySelector("#skill-ext-color-hex");
    const copyBtn = container.querySelector("#skill-ext-color-copy");
    input.addEventListener("input", function() {
      hexEl.textContent = input.value;
    });
    copyBtn.addEventListener("click", function() {
      if (navigator.clipboard) {
        navigator.clipboard.writeText(input.value).catch(function() {
        });
      }
      copyBtn.textContent = "已复制!";
      setTimeout(function() {
        copyBtn.textContent = "复制";
      }, 1500);
    });
  }
  function showPermissionDialog(skillId, skillName, missingPerms, onGranted) {
    removePermissionDialog();
    const overlay = document.createElement("div");
    overlay.id = PERM_DIALOG_ID;
    overlay.className = "skill-ext-perm-overlay";
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");
    overlay.setAttribute("aria-label", "权限申请");
    const permListHtml = missingPerms.map(function(p) {
      return "<li><strong>" + esc(p.label || p.id) + "</strong>: " + esc(p.description || "") + ' <span class="skill-ext-risk skill-ext-risk--' + esc(p.risk || "unknown") + '">' + esc(p.risk || "") + "</span></li>";
    }).join("");
    overlay.innerHTML = '<div class="skill-ext-perm-dialog">  <h3>「' + esc(skillName) + "」申请权限</h3>  <p>该技能需要以下额外权限才能激活完整功能：</p>  <ul>" + permListHtml + '</ul>  <div class="skill-ext-perm-actions">    <button type="button" id="skill-ext-perm-grant">授予权限</button>    <button type="button" id="skill-ext-perm-deny">暂不授予</button>  </div></div>';
    overlay.querySelector("#skill-ext-perm-grant").addEventListener("click", function() {
      const perms = missingPerms.map(function(p) {
        return p.id;
      });
      fetch("/api/skills/" + encodeURIComponent(skillId) + "/permissions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ permissions: perms })
      }).then(function(r) {
        return r.json();
      }).then(function(data) {
        removePermissionDialog();
        if (data.success && onGranted) onGranted();
      }).catch(function() {
        removePermissionDialog();
      });
    });
    overlay.querySelector("#skill-ext-perm-deny").addEventListener("click", removePermissionDialog);
    overlay.addEventListener("click", function(e) {
      if (e.target === overlay) removePermissionDialog();
    });
    document.body.appendChild(overlay);
  }
  function removePermissionDialog() {
    const el = document.getElementById(PERM_DIALOG_ID);
    if (el) el.remove();
  }
  async function fetchAndApplyExtensions() {
    try {
      const resp = await fetch("/api/skills/active-ui-config");
      if (!resp.ok) return;
      const data = await resp.json();
      const ext = data && data.extensions ? data.extensions : {};
      applyExtensions(ext);
    } catch (e) {
    }
  }
  function applyExtensions(ext) {
    _currentExtensions = ext;
    const isEmpty = !ext || (!ext.action_buttons || ext.action_buttons.length === 0) && (!ext.quick_replies || ext.quick_replies.length === 0) && !ext.floating_widget;
    if (isEmpty) {
      clearAllExtensions();
      return;
    }
    renderActionButtons(ext.action_buttons || []);
    startQuickReplyObserver(ext.quick_replies || []);
    applyQuickRepliesToLatestMessage(ext.quick_replies || []);
    if (ext.floating_widget) {
      const existing = document.getElementById(FLOAT_WIDGET_ID);
      if (!existing || existing.getAttribute("data-widget-type") !== ext.floating_widget.type) {
        renderFloatingWidget(ext.floating_widget);
        if (document.getElementById(FLOAT_WIDGET_ID)) {
          document.getElementById(FLOAT_WIDGET_ID).setAttribute("data-widget-type", ext.floating_widget.type || "");
        }
      }
    } else {
      removeFloatingWidget();
    }
  }
  function clearAllExtensions() {
    removeActionBar();
    stopQuickReplyObserver();
    removeFloatingWidget();
    _currentExtensions = null;
  }
  function hookRefreshActiveSkills() {
    const origFn = window.refreshActiveSkills;
    window.refreshActiveSkills = async function() {
      const result = origFn ? await origFn.apply(this, arguments) : void 0;
      await fetchAndApplyExtensions();
      return result;
    };
  }
  function init() {
    function setup() {
      fetchAndApplyExtensions();
      hookRefreshActiveSkills();
    }
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", setup);
    } else {
      setup();
    }
  }
  const W = window;
  W.SkillUIExt = Object.assign(W.SkillUIExt || {}, {
    refresh: fetchAndApplyExtensions,
    clear: clearAllExtensions,
    renderFloatingWidget,
    removeFloatingWidget,
    showPermissionDialog
  });
  init();
})();
//# sourceMappingURL=skills-ui-bundle.js.map
