/** skill-ui.ts — Koto Skill UI 定制引擎 */

import { getActiveKotoComposer, getActiveKotoMessageContainer } from '../shared/active-composer';

export interface SkillUiConfig {
  css_vars?: Record<string, string>;
  theme?: string;
  overlay_effect?: string;
  input_placeholder?: string;
  title_text?: string;
  subtitle_text?: string;
  font_style?: string;
  assistant_prefix?: string;
  hide_skill_bar?: boolean;
  welcome_text?: string;
}

export interface ActiveUiResponse {
  success: boolean;
  has_ui?: boolean;
  sources?: string[];
  config?: SkillUiConfig;
}

// ─── 内部状态 ────────────────────────────────────────────
const OVERLAY_ID = 'skill-ui-overlay';
const CSS_STYLE_ID = 'skill-ui-css-vars';
const FONT_STYLE_ID = 'skill-ui-font';

let _isApplied = false;
let _originalTitle = '';
let _originalSubtitle = '';
let _originalTheme = '';
let _originalPlaceholder = '';
let _placeholderTarget: HTMLInputElement | HTMLTextAreaElement | null = null;
let _assistantPrefix = '';
let _lastDivinationConfig: SkillUiConfig | null = null;

function applyCSS(cssVars: Record<string, string> | undefined, theme: string): void {
  let styleEl = document.getElementById(CSS_STYLE_ID);
  if (!styleEl) {
    styleEl = document.createElement('style');
    styleEl.id = CSS_STYLE_ID;
    document.head.appendChild(styleEl);
  }

  const rules: string[] = [];

  if (theme) {
    const htmlEl = document.documentElement;
    if (!_isApplied) {
      _originalTheme = htmlEl.getAttribute('data-theme') || '';
    }
    htmlEl.setAttribute('data-theme', theme);
  }

  if (cssVars && Object.keys(cssVars).length > 0) {
    const varLines = Object.entries(cssVars).map(([k, v]) => `    ${k}: ${v} !important;`).join('\n');
    rules.push(`:root, [data-theme], body, html, #chatMessages {\n${varLines}\n}`);
  }

  if (cssVars && cssVars['--text-primary']) {
    const c = cssVars['--text-primary'];
    rules.push(`#wa-user-input { color: ${c} !important; caret-color: ${c}; }`);
  }

  styleEl.textContent = rules.join('\n');
}

function removeCSS(): void {
  const styleEl = document.getElementById(CSS_STYLE_ID);
  if (styleEl) styleEl.textContent = '';

  if (_originalTheme !== null && _originalTheme !== undefined) {
    const htmlEl = document.documentElement;
    if (_originalTheme) {
      htmlEl.setAttribute('data-theme', _originalTheme);
    } else {
      htmlEl.removeAttribute('data-theme');
    }
    _originalTheme = '';
  }
}

function applyFont(fontStyle: string): void {
  let styleEl = document.getElementById(FONT_STYLE_ID);
  if (!styleEl) {
    styleEl = document.createElement('style');
    styleEl.id = FONT_STYLE_ID;
    document.head.appendChild(styleEl);
  }
  const fontMap: Record<string, string> = {
    'serif': "'Georgia', 'Times New Roman', serif",
    'mono': "'JetBrains Mono', 'Consolas', monospace",
    'handwriting': "'Segoe Script', 'cursive'",
  };
  const family = fontMap[fontStyle] || fontStyle;
  if (family) {
    styleEl.textContent = `body { font-family: ${family} !important; }`;
    styleEl.textContent += `\n#wa-user-input, .message-content, .tp-heading, .tp-subheading, .tp-face-name-zh { font-family: ${family} !important; }`;
  }
}

function removeFont(): void {
  const styleEl = document.getElementById(FONT_STYLE_ID);
  if (styleEl) styleEl.textContent = '';
}

function applyOverlay(effect: string): void {
  removeOverlay();
  if (!effect) return;

  const el = document.createElement('div');
  el.id = OVERLAY_ID;
  el.className = `skill-ui-overlay skill-ui-overlay-${effect}`;
  el.setAttribute('aria-hidden', 'true');

  if (effect === 'stars') {
    for (let i = 0; i < 120; i++) {
      const star = document.createElement('div');
      star.className = 'skill-ui-star';
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

  if (effect === 'crystals') {
    for (let i = 0; i < 8; i++) {
      const gem = document.createElement('div');
      gem.className = 'skill-ui-crystal';
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

  if (effect === 'candles') {
    for (let i = 0; i < 5; i++) {
      const candle = document.createElement('div');
      candle.className = 'skill-ui-candle';
      candle.style.cssText = `left: ${8 + i * 21}%; animation-delay: ${Math.random() * 1.5}s;`;
      el.appendChild(candle);
    }
  }

  document.body.appendChild(el);
}

function removeOverlay(): void {
  const el = document.getElementById(OVERLAY_ID);
  if (el) el.remove();
}

function applyPlaceholder(text: string): void {
  const input = getActiveKotoComposer();
  if (!input) return;
  if (_placeholderTarget !== input) {
    restorePlaceholder();
    _placeholderTarget = input;
    _originalPlaceholder = input.placeholder;
  }
  if (text) input.placeholder = text;
}

function restorePlaceholder(): void {
  if (_placeholderTarget && _originalPlaceholder) _placeholderTarget.placeholder = _originalPlaceholder;
  _placeholderTarget = null;
  _originalPlaceholder = '';
}

function applyTitle(titleText: string, subtitleText: string): void {
  const titleEl = document.querySelector('.logo-text');
  const subEl = document.querySelector('.logo-sub');
  if (titleEl) {
    if (!_originalTitle) _originalTitle = titleEl.textContent || '';
    if (titleText) titleEl.textContent = titleText;
  }
  if (subEl) {
    if (!_originalSubtitle) _originalSubtitle = subEl.textContent || '';
    if (subtitleText) subEl.textContent = subtitleText;
  }
}

function restoreTitle(): void {
  const titleEl = document.querySelector('.logo-text');
  const subEl = document.querySelector('.logo-sub');
  if (titleEl && _originalTitle) { titleEl.textContent = _originalTitle; _originalTitle = ''; }
  if (subEl && _originalSubtitle) { subEl.textContent = _originalSubtitle; _originalSubtitle = ''; }
}

function applySkillBarVisibility(hide: boolean): void {
  const bar = document.getElementById('chat-skill-bar');
  if (bar) bar.style.setProperty('--skill-bar-display', hide ? 'none' : '');
}

function applyAssistantPrefix(prefix: string): void {
  _assistantPrefix = prefix || '';
  (window as any).skillUiAssistantPrefix = _assistantPrefix;
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function showWelcomeText(text: string): void {
  if (!text) return;
  const chatMessages = getActiveKotoMessageContainer();
  if (!chatMessages) return;

  const existing = document.getElementById('skill-ui-welcome');
  if (existing) existing.remove();

  const el = document.createElement('div');
  el.id = 'skill-ui-welcome';
  el.className = 'skill-ui-welcome';
  el.innerHTML = `<div class="skill-ui-welcome-inner">${escapeHtml(text)}</div>`;
  chatMessages.insertBefore(el, chatMessages.firstChild);
}

function removeWelcomeText(): void {
  const el = document.getElementById('skill-ui-welcome');
  if (el) el.remove();
}

function applySkillUI(config: SkillUiConfig, isNew?: boolean): void {
  applyCSS(config.css_vars || {}, config.theme || '');
  applyOverlay(config.overlay_effect || '');
  applyPlaceholder(config.input_placeholder || '');
  applyTitle(config.title_text || '', config.subtitle_text || '');
  applyFont(config.font_style || '');
  applyAssistantPrefix(config.assistant_prefix || '');
  applySkillBarVisibility(config.hide_skill_bar || false);
  if (isNew && config.welcome_text) {
    showWelcomeText(config.welcome_text);
  }
  _isApplied = true;
}

function removeSkillUI(): void {
  if (!_isApplied) return;
  removeCSS();
  removeOverlay();
  restorePlaceholder();
  restoreTitle();
  removeFont();
  removeWelcomeText();
  applyAssistantPrefix('');
  applySkillBarVisibility(false);
  _isApplied = false;
}

let _lastSources = JSON.stringify([]);

async function fetchAndApply(): Promise<void> {
  try {
    const res = await fetch('/api/skills/active-ui-config');
    if (!res.ok) return;
    const data: ActiveUiResponse = await res.json();

    if (!data.success) return;

    const sourcesStr = JSON.stringify(data.sources || []);
    const isNew = sourcesStr !== _lastSources;
    _lastSources = sourcesStr;

    const sourceList = Array.isArray(data.sources) ? data.sources : [];
    const hasDivinationSource = sourceList.includes('divination');
    const tarotPersistent = Boolean(
      ((window as any).TarotPicker && typeof (window as any).TarotPicker.isPersistentActive === 'function' && (window as any).TarotPicker.isPersistentActive()) ||
      document.getElementById('tarot-picker-widget') ||
      (window as any)._kotoTarotPending
    );

    if (data.has_ui && hasDivinationSource && data.config) {
      _lastDivinationConfig = data.config;
    }

    if (data.has_ui) {
      const configToApply = (tarotPersistent && _lastDivinationConfig) ? _lastDivinationConfig : data.config;
      applySkillUI(configToApply!, isNew);
    } else if (tarotPersistent && _lastDivinationConfig) {
      applySkillUI(_lastDivinationConfig, false);
    } else {
      removeSkillUI();
    }

    const divinationActive = (data.has_ui && hasDivinationSource) || tarotPersistent;
    (window as any)._kotoDivinationActive = divinationActive;
    if ((window as any).TarotPicker) {
      (window as any).TarotPicker.setActive(divinationActive);
    }
  } catch (e) {
    // 静默失败
  }
}

function hookRefreshActiveSkills(): void {
  const origFn = (window as any).refreshActiveSkills as (() => Promise<any>) | undefined;
  (window as any).refreshActiveSkills = async function (this: any) {
    const result = origFn ? await origFn.apply(this, arguments as any) : undefined;
    await fetchAndApply();
    return result;
  };
}

function init(): void {
  document.addEventListener('DOMContentLoaded', () => {
    fetchAndApply();
    hookRefreshActiveSkills();
  });

  if (document.readyState !== 'loading') {
    fetchAndApply();
    hookRefreshActiveSkills();
  }
}

export { fetchAndApply as refreshSkillUI, removeSkillUI };

// ─── 公开 API ─────────────────────────────────────────────
const SkillUI = {
  refresh: fetchAndApply,
  remove: removeSkillUI,
};

const W = (window as any);
W.SkillUI = SkillUI;

init();
