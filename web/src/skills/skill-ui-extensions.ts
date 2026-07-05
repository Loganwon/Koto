/** skill-ui-extensions.ts — Koto Skill UI 交互扩展引擎 */

export interface ActionButton {
  id?: string;
  label?: string;
  tooltip?: string;
  variant?: string;
  message?: string;
  action?: string;
}

export interface FloatingWidgetDef {
  type?: string;
  title?: string;
  position?: string;
}

export interface UiExtensions {
  action_buttons?: ActionButton[];
  quick_replies?: string[];
  floating_widget?: FloatingWidgetDef;
}

export interface PermItem {
  id: string;
  label?: string;
  description?: string;
  risk?: string;
}

// ─── 常量 ─────────────────────────────────────────────────
const ACTION_BAR_ID = 'skill-ext-action-bar';
const FLOAT_WIDGET_ID = 'skill-ext-floating-widget';
const QUICK_REPLY_CLS = 'skill-ext-quick-reply-row';
const PERM_DIALOG_ID = 'skill-ext-perm-dialog';

// ─── 状态 ─────────────────────────────────────────────────
let _currentExtensions: UiExtensions | null = null;
let _qrObserver: MutationObserver | null = null;

// ─── 工具函数 ──────────────────────────────────────────────
function esc(str: string): string {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function sendMessage(text: string): void {
  const input = document.querySelector('#messageInput, #userInput, [data-role="chat-input"]') as HTMLInputElement | HTMLTextAreaElement | null;
  if (!input) return;
  const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value') ||
    Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value');
  if (nativeSetter && nativeSetter.set) {
    nativeSetter.set.call(input, text);
  } else {
    input.value = text;
  }
  input.dispatchEvent(new Event('input', { bubbles: true }));
  const sendBtn = document.querySelector('#sendBtn, [data-role="send-button"], button[type="submit"]') as HTMLElement | null;
  if (sendBtn) {
    sendBtn.click();
  } else {
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
  }
}

// ─── 1. Action Buttons ───────────────────────────────────
function renderActionButtons(buttons: ActionButton[]): void {
  removeActionBar();
  if (!buttons || buttons.length === 0) return;

  const bar = document.createElement('div');
  bar.id = ACTION_BAR_ID;
  bar.className = 'skill-ext-action-bar';
  bar.setAttribute('role', 'toolbar');
  bar.setAttribute('aria-label', '技能快捷操作');

  buttons.forEach((btn) => {
    const el = document.createElement('button');
    el.type = 'button';
    el.className = 'skill-ext-action-btn skill-ext-action-btn--' + esc(btn.variant || 'default');
    el.textContent = btn.label || '';
    if (btn.tooltip) el.setAttribute('title', esc(btn.tooltip));
    el.setAttribute('data-action-id', esc(btn.id || ''));

    el.addEventListener('click', () => {
      if (btn.message) {
        sendMessage(btn.message);
      } else if (btn.action) {
        handleBuiltinAction(btn.action, btn);
      }
    });
    bar.appendChild(el);
  });

  const inputArea = document.querySelector(
    '#inputArea, #input-area, .input-area, .chat-input-area, #chatForm'
  );
  if (inputArea) {
    inputArea.parentNode!.insertBefore(bar, inputArea);
  } else {
    document.body.appendChild(bar);
  }
}

function removeActionBar(): void {
  const el = document.getElementById(ACTION_BAR_ID);
  if (el) el.remove();
}

function handleBuiltinAction(action: string, _btn: ActionButton): void {
  if (action === 'open_floating_widget' && _currentExtensions) {
    renderFloatingWidget(_currentExtensions.floating_widget!);
  }
}

// ─── 2. Quick Replies ────────────────────────────────────
function attachQuickRepliesToMessage(msgEl: Element, replies: string[]): void {
  if (msgEl.querySelector('.' + QUICK_REPLY_CLS)) return;

  const row = document.createElement('div');
  row.className = QUICK_REPLY_CLS;
  row.setAttribute('role', 'group');
  row.setAttribute('aria-label', '快速回复');

  replies.forEach((text) => {
    const chip = document.createElement('button');
    chip.type = 'button';
    chip.className = 'skill-ext-qr-chip';
    chip.textContent = text;
    chip.addEventListener('click', () => {
      sendMessage(text);
      row.remove();
    });
    row.appendChild(chip);
  });

  msgEl.appendChild(row);
}

function getAIMessageElements(): Element[] {
  return Array.from(document.querySelectorAll(
    '.message.assistant, .message--assistant, [data-role="assistant-message"], .ai-message'
  ));
}

function applyQuickRepliesToLatestMessage(replies: string[]): void {
  if (!replies || replies.length === 0) return;
  const msgs = getAIMessageElements();
  if (msgs.length > 0) {
    attachQuickRepliesToMessage(msgs[msgs.length - 1], replies);
  }
}

function startQuickReplyObserver(replies: string[]): void {
  stopQuickReplyObserver();
  if (!replies || replies.length === 0) return;

  const container = document.querySelector(
    '#messages, #messageList, .messages, .chat-messages, [data-role="messages"]'
  );
  if (!container) return;

  _qrObserver = new MutationObserver((mutations) => {
    mutations.forEach((m) => {
      m.addedNodes.forEach((node) => {
        if (node.nodeType !== 1) return;
        const el = node as Element;
        const isAI = el.classList.contains('assistant') ||
          el.classList.contains('message--assistant') ||
          el.getAttribute('data-role') === 'assistant-message' ||
          el.classList.contains('ai-message');
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

function stopQuickReplyObserver(): void {
  if (_qrObserver) {
    _qrObserver.disconnect();
    _qrObserver = null;
  }
  document.querySelectorAll('.' + QUICK_REPLY_CLS).forEach((el) => { el.remove(); });
}

// ─── 3. Floating Widget ───────────────────────────────────
const WIDGET_RENDERERS: Record<string, (container: HTMLElement) => void> = {
  dice_roller: renderDiceRoller,
  timer: renderTimer,
  notes: renderNotes,
  calculator: renderCalculator,
  word_counter: renderWordCounter,
  color_picker: renderColorPicker,
};

function renderFloatingWidget(widgetDef: FloatingWidgetDef): void {
  removeFloatingWidget();
  if (!widgetDef || !widgetDef.type) return;

  const renderer = WIDGET_RENDERERS[widgetDef.type];
  if (!renderer) return;

  const panel = document.createElement('div');
  panel.id = FLOAT_WIDGET_ID;
  panel.className = 'skill-ext-float-panel skill-ext-float-panel--' + esc(widgetDef.type);
  panel.setAttribute('role', 'dialog');
  panel.setAttribute('aria-label', widgetDef.title || widgetDef.type);

  const titleBar = document.createElement('div');
  titleBar.className = 'skill-ext-float-title-bar';
  titleBar.innerHTML =
    '<span class="skill-ext-float-title">' + esc(widgetDef.title || widgetDef.type) + '</span>' +
    '<button type="button" class="skill-ext-float-close" aria-label="关闭">✕</button>';
  panel.appendChild(titleBar);
  titleBar.querySelector('.skill-ext-float-close')!.addEventListener('click', removeFloatingWidget);

  const content = document.createElement('div');
  content.className = 'skill-ext-float-content';
  renderer(content);
  panel.appendChild(content);

  const pos = widgetDef.position || 'bottom-right';
  applyWidgetPosition(panel, pos);

  document.body.appendChild(panel);
  makeDraggable(panel, titleBar);
}

function applyWidgetPosition(el: HTMLElement, pos: string): void {
  const margin = '16px';
  el.style.position = 'fixed';
  el.style.zIndex = '9000';
  if (pos === 'bottom-right' || pos === 'bottom_right') {
    el.style.bottom = margin; el.style.right = margin;
  } else if (pos === 'bottom-left' || pos === 'bottom_left') {
    el.style.bottom = margin; el.style.left = margin;
  } else if (pos === 'top-right' || pos === 'top_right') {
    el.style.top = margin; el.style.right = margin;
  } else if (pos === 'top-left' || pos === 'top_left') {
    el.style.top = margin; el.style.left = margin;
  }
}

function makeDraggable(panel: HTMLElement, handle: HTMLElement): void {
  let startX: number, startY: number, startLeft: number, startTop: number;
  handle.style.cursor = 'move';
  handle.addEventListener('mousedown', (e) => {
    if ((e.target as HTMLElement).classList.contains('skill-ext-float-close')) return;
    e.preventDefault();
    const rect = panel.getBoundingClientRect();
    startX = e.clientX;
    startY = e.clientY;
    startLeft = rect.left;
    startTop = rect.top;
    panel.style.right = 'auto';
    panel.style.bottom = 'auto';
    panel.style.left = startLeft + 'px';
    panel.style.top = startTop + 'px';

    function onMove(e2: MouseEvent) {
      panel.style.left = (startLeft + e2.clientX - startX) + 'px';
      panel.style.top = (startTop + e2.clientY - startY) + 'px';
    }
    function onUp() {
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
    }
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
  });
}

function removeFloatingWidget(): void {
  const el = document.getElementById(FLOAT_WIDGET_ID);
  if (el) el.remove();
}

// ─── 内置 Widget 渲染器 ───────────────────────────────────
function renderDiceRoller(container: HTMLElement): void {
  container.innerHTML =
    '<div class="skill-ext-dice">' +
    '  <div class="skill-ext-dice-result" id="skill-ext-dice-result">🎲</div>' +
    '  <div class="skill-ext-dice-btns">' +
    '    <button type="button" data-sides="4">D4</button>' +
    '    <button type="button" data-sides="6">D6</button>' +
    '    <button type="button" data-sides="8">D8</button>' +
    '    <button type="button" data-sides="10">D10</button>' +
    '    <button type="button" data-sides="12">D12</button>' +
    '    <button type="button" data-sides="20">D20</button>' +
    '    <button type="button" data-sides="100">D100</button>' +
    '  </div>' +
    '</div>';
  container.querySelectorAll('button[data-sides]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const sides = parseInt(btn.getAttribute('data-sides')!, 10);
      const result = Math.floor(Math.random() * sides) + 1;
      container.querySelector('#skill-ext-dice-result')!.textContent = result + ' / D' + sides;
    });
  });
}

function renderTimer(container: HTMLElement): void {
  let seconds = 0, interval: ReturnType<typeof setInterval> | null = null;
  container.innerHTML =
    '<div class="skill-ext-timer">' +
    '  <div class="skill-ext-timer-display" id="skill-ext-timer-display">00:00</div>' +
    '  <div class="skill-ext-timer-btns">' +
    '    <button type="button" id="skill-ext-timer-start">开始</button>' +
    '    <button type="button" id="skill-ext-timer-reset">重置</button>' +
    '  </div>' +
    '</div>';

  function pad(n: number): string { return n < 10 ? '0' + n : '' + n; }
        function updateDisplay() {
            const m = Math.floor(seconds / 60), s = seconds % 60;
            (container.querySelector('#skill-ext-timer-display') as HTMLElement).textContent = pad(m) + ':' + pad(s);
        }

  const startBtn = container.querySelector('#skill-ext-timer-start')!;
  const resetBtn = container.querySelector('#skill-ext-timer-reset')!;

  startBtn.addEventListener('click', () => {
    if (interval) {
      clearInterval(interval); interval = null;
      startBtn.textContent = '继续';
    } else {
      interval = setInterval(() => { seconds++; updateDisplay(); }, 1000);
      startBtn.textContent = '暂停';
    }
  });
  resetBtn.addEventListener('click', () => {
    clearInterval(interval!); interval = null;
    seconds = 0; updateDisplay();
    startBtn.textContent = '开始';
  });
}

function renderNotes(container: HTMLElement): void {
  const storageKey = 'skill_ext_notes';
  container.innerHTML =
    '<textarea class="skill-ext-notes-area" placeholder="在此记笔记…" rows="6" ' +
    'style="width:100%;resize:vertical;box-sizing:border-box;font-size:0.9em;" ' +
    'maxlength="4096"></textarea>';
  const ta = container.querySelector('textarea')!;
  ta.value = sessionStorage.getItem(storageKey) || '';
  ta.addEventListener('input', () => {
    sessionStorage.setItem(storageKey, ta.value);
  });
}

function renderCalculator(container: HTMLElement): void {
  let expr = '';
  const btnLayout = [
    ['C', '±', '%', '÷'],
    ['7', '8', '9', '×'],
    ['4', '5', '6', '−'],
    ['1', '2', '3', '+'],
    ['0', '.', '='],
  ];
  const displayId = 'skill-ext-calc-display';
  let html = '<div class="skill-ext-calc"><div class="skill-ext-calc-display" id="' + displayId + '">0</div><div class="skill-ext-calc-btns">';
  btnLayout.forEach((row) => {
    row.forEach((lbl) => {
      const wide = lbl === '0' ? ' skill-ext-calc-btn--wide' : '';
      html += '<button type="button" class="skill-ext-calc-btn' + wide + '" data-lbl="' + esc(lbl) + '">' + esc(lbl) + '</button>';
    });
  });
  html += '</div></div>';
  container.innerHTML = html;

  const display = container.querySelector('#' + displayId)!;

  function setDisplay(val: string) { display.textContent = val || '0'; }

  container.querySelectorAll('.skill-ext-calc-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      const lbl = btn.getAttribute('data-lbl');
      if (lbl === 'C') { expr = ''; setDisplay('0'); return; }
      if (lbl === '±') {
        if (expr && !isNaN(parseFloat(expr))) {
          expr = String(-parseFloat(expr));
          setDisplay(expr);
        }
        return;
      }
      if (lbl === '=') {
        try {
          const safeExpr = expr
            .replace(/×/g, '*')
            .replace(/÷/g, '/')
            .replace(/−/g, '-');
          if (!/^[0-9+\-*/.() %]+$/.test(safeExpr)) {
            setDisplay('错误'); expr = ''; return;
          }
          const result = Function('"use strict"; return (' + safeExpr + ')')();
          expr = String(result);
          setDisplay(expr);
        } catch (e) {
          setDisplay('错误'); expr = '';
        }
        return;
      }
      if (lbl === '%') {
        try {
          const v = Function('"use strict"; return (' + expr + ')')();
          expr = String(v / 100);
          setDisplay(expr);
        } catch (e) {
          setDisplay('错误'); expr = '';
        }
        return;
      }
      expr += lbl;
      setDisplay(expr);
    });
  });
}

function renderWordCounter(container: HTMLElement): void {
  container.innerHTML =
    '<div class="skill-ext-wordcount">' +
    '  <textarea class="skill-ext-wordcount-input" placeholder="粘贴文字以计算字数…" rows="5" ' +
    '  style="width:100%;resize:vertical;box-sizing:border-box;" maxlength="50000"></textarea>' +
    '  <div class="skill-ext-wordcount-stats">' +
    '    字符：<span id="skill-ext-wc-chars">0</span>　' +
    '    词数：<span id="skill-ext-wc-words">0</span>' +
    '  </div>' +
    '</div>';
  const ta = container.querySelector('textarea')!;
  const charsEl = container.querySelector('#skill-ext-wc-chars')!;
  const wordsEl = container.querySelector('#skill-ext-wc-words')!;
  ta.addEventListener('input', () => {
    const text = ta.value;
    charsEl.textContent = String(text.length);
    const cjkMatches = (text.match(/[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]/g) || []).length;
    const latinMatches = (text.match(/\b[a-zA-Z'-]+\b/g) || []).length;
    wordsEl.textContent = String(cjkMatches + latinMatches);
  });
}

function renderColorPicker(container: HTMLElement): void {
  container.innerHTML =
    '<div class="skill-ext-colorpicker">' +
    '  <input type="color" id="skill-ext-color-input" value="#6366f1" ' +
    '         style="width:100%;height:80px;border:none;cursor:pointer;">' +
    '  <div class="skill-ext-color-info">' +
    '    <code id="skill-ext-color-hex">#6366f1</code>' +
    '    <button type="button" id="skill-ext-color-copy">复制</button>' +
    '  </div>' +
    '</div>';
  const input = container.querySelector('#skill-ext-color-input') as HTMLInputElement;
  const hexEl = container.querySelector('#skill-ext-color-hex')!;
  const copyBtn = container.querySelector('#skill-ext-color-copy')!;

  input.addEventListener('input', () => {
    hexEl.textContent = input.value;
  });
  copyBtn.addEventListener('click', () => {
    if (navigator.clipboard) {
      navigator.clipboard.writeText(input.value).catch(() => { });
    }
    copyBtn.textContent = '已复制!';
    setTimeout(() => { copyBtn.textContent = '复制'; }, 1500);
  });
}

// ─── 4. 权限申请对话框 ────────────────────────────────────
function showPermissionDialog(skillId: string, skillName: string, missingPerms: PermItem[], onGranted?: () => void): void {
  removePermissionDialog();

  const overlay = document.createElement('div');
  overlay.id = PERM_DIALOG_ID;
  overlay.className = 'skill-ext-perm-overlay';
  overlay.setAttribute('role', 'dialog');
  overlay.setAttribute('aria-modal', 'true');
  overlay.setAttribute('aria-label', '权限申请');

  const permListHtml = missingPerms.map((p) => {
    return '<li><strong>' + esc(p.label || p.id) + '</strong>: ' + esc(p.description || '') +
      ' <span class="skill-ext-risk skill-ext-risk--' + esc(p.risk || 'unknown') + '">' +
      esc(p.risk || '') + '</span></li>';
  }).join('');

  overlay.innerHTML =
    '<div class="skill-ext-perm-dialog">' +
    '  <h3>「' + esc(skillName) + '」申请权限</h3>' +
    '  <p>该技能需要以下额外权限才能激活完整功能：</p>' +
    '  <ul>' + permListHtml + '</ul>' +
    '  <div class="skill-ext-perm-actions">' +
    '    <button type="button" id="skill-ext-perm-grant">授予权限</button>' +
    '    <button type="button" id="skill-ext-perm-deny">暂不授予</button>' +
    '  </div>' +
    '</div>';

  overlay.querySelector('#skill-ext-perm-grant')!.addEventListener('click', () => {
    const perms = missingPerms.map((p) => { return p.id; });
    fetch('/api/skills/' + encodeURIComponent(skillId) + '/permissions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ permissions: perms }),
    })
      .then((r) => { return r.json(); })
      .then((data: any) => {
        removePermissionDialog();
        if (data.success && onGranted) onGranted();
      })
      .catch(() => { removePermissionDialog(); });
  });

  overlay.querySelector('#skill-ext-perm-deny')!.addEventListener('click', removePermissionDialog);

  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) removePermissionDialog();
  });

  document.body.appendChild(overlay);
}

function removePermissionDialog(): void {
  const el = document.getElementById(PERM_DIALOG_ID);
  if (el) el.remove();
}

// ─── 主流程 ───────────────────────────────────────────────
async function fetchAndApplyExtensions(): Promise<void> {
  try {
    const resp = await fetch('/api/skills/active-ui-config');
    if (!resp.ok) return;
    const data = await resp.json();
    const ext = (data && data.extensions) ? data.extensions as UiExtensions : {};
    applyExtensions(ext);
  } catch (e) {
    // 网络错误时静默失败
  }
}

function applyExtensions(ext: UiExtensions): void {
  _currentExtensions = ext;
  const isEmpty = !ext || (
    (!ext.action_buttons || ext.action_buttons.length === 0) &&
    (!ext.quick_replies || ext.quick_replies.length === 0) &&
    (!ext.floating_widget)
  );

  if (isEmpty) {
    clearAllExtensions();
    return;
  }

  renderActionButtons(ext.action_buttons || []);
  startQuickReplyObserver(ext.quick_replies || []);
  applyQuickRepliesToLatestMessage(ext.quick_replies || []);

  if (ext.floating_widget) {
    const existing = document.getElementById(FLOAT_WIDGET_ID);
    if (!existing ||
      existing.getAttribute('data-widget-type') !== ext.floating_widget.type) {
      renderFloatingWidget(ext.floating_widget);
      if (document.getElementById(FLOAT_WIDGET_ID)) {
        document.getElementById(FLOAT_WIDGET_ID)!
          .setAttribute('data-widget-type', ext.floating_widget.type || '');
      }
    }
  } else {
    removeFloatingWidget();
  }
}

function clearAllExtensions(): void {
  removeActionBar();
  stopQuickReplyObserver();
  removeFloatingWidget();
  _currentExtensions = null;
}

function hookRefreshActiveSkills(): void {
  const origFn = (window as any).refreshActiveSkills as (() => Promise<any>) | undefined;
  (window as any).refreshActiveSkills = async function (this: any) {
    const result = origFn ? await origFn.apply(this, arguments as any) : undefined;
    await fetchAndApplyExtensions();
    return result;
  };
}

function init(): void {
  function setup() {
    fetchAndApplyExtensions();
    hookRefreshActiveSkills();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', setup);
  } else {
    setup();
  }
}

export {
  fetchAndApplyExtensions as refreshSkillExtensions,
  clearAllExtensions,
  renderFloatingWidget,
  removeFloatingWidget,
  showPermissionDialog,
};

// ─── 公开 API ─────────────────────────────────────────────
const W = (window as any);
W.SkillUIExt = Object.assign(W.SkillUIExt || {}, {
  refresh: fetchAndApplyExtensions,
  clear: clearAllExtensions,
  renderFloatingWidget: renderFloatingWidget,
  removeFloatingWidget: removeFloatingWidget,
  showPermissionDialog: showPermissionDialog,
});

init();
