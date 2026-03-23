/**
 * skill-ui.js  —  Koto Skill UI 定制引擎
 * ==========================================
 * 让激活的 Skill 能够改变聊天界面的视觉和交互方式：
 *   - CSS 变量覆盖（主题色、背景色等）
 *   - 背景叠加特效（星空、烟雾、水晶等）
 *   - 输入框占位符文字
 *   - 侧边栏标题文字
 *   - AI 回复前缀装饰
 *
 * 工作原理：
 *   1. 每次 refreshActiveSkills() 调用后，拉取 /api/skills/active-ui-config
 *   2. 将 CSS 变量注入 :root style 标签
 *   3. 根据 overlay_effect 添加/移除背景特效 DOM 节点
 *   4. 修改输入框 placeholder 和标题文字
 *   5. 当所有有 UI 配置的 Skill 都被禁用时，恢复原始状态
 *
 * @version 2026-03-19
 */
(function (global) {
    'use strict';

    // ─── 内部状态 ─────────────────────────────────────────────────────────────
    const OVERLAY_ID       = 'skill-ui-overlay';
    const CSS_STYLE_ID     = 'skill-ui-css-vars';
    const FONT_STYLE_ID    = 'skill-ui-font';

    let _isApplied         = false;
    let _originalTitle     = '';
    let _originalSubtitle  = '';
    let _originalTheme     = '';
    let _originalPlaceholder = '';
    let _assistantPrefix   = '';
    let _lastDivinationConfig = null;

    // ─── CSS 变量注入 ─────────────────────────────────────────────────────────

    function applyCSS(cssVars, theme) {
        let styleEl = document.getElementById(CSS_STYLE_ID);
        if (!styleEl) {
            styleEl = document.createElement('style');
            styleEl.id = CSS_STYLE_ID;
            document.head.appendChild(styleEl);
        }

        const rules = [];

        // 切换内置主题 — 仅在首次应用（_isApplied=false）时记录原始主题，
        // 避免后续重复调用覆盖已保存的原始值
        if (theme) {
            const htmlEl = document.documentElement;
            if (!_isApplied) {
                _originalTheme = htmlEl.getAttribute('data-theme') || '';
            }
            htmlEl.setAttribute('data-theme', theme);
        }

        // 追加 CSS 变量覆盖
        if (cssVars && Object.keys(cssVars).length > 0) {
            const varLines = Object.entries(cssVars).map(([k, v]) => `    ${k}: ${v} !important;`).join('\n');
            rules.push(`:root, [data-theme], body, html, #chatMessages {\n${varLines}\n}`);
        }

        // 强制文本输入框使用主题字色（防止浏览器默认样式覆盖）
        if (cssVars && cssVars['--text-primary']) {
            const c = cssVars['--text-primary'];
            rules.push(`#messageInput { color: ${c} !important; caret-color: ${c}; }`);
        }

        styleEl.textContent = rules.join('\n');
    }

    function removeCSS() {
        const styleEl = document.getElementById(CSS_STYLE_ID);
        if (styleEl) styleEl.textContent = '';

        // 恢复主题
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

    // ─── 字体风格 ──────────────────────────────────────────────────────────────

    function applyFont(fontStyle) {
        let styleEl = document.getElementById(FONT_STYLE_ID);
        if (!styleEl) {
            styleEl = document.createElement('style');
            styleEl.id = FONT_STYLE_ID;
            document.head.appendChild(styleEl);
        }
        const fontMap = {
            'serif':       "'Georgia', 'Times New Roman', serif",
            'mono':        "'JetBrains Mono', 'Consolas', monospace",
            'handwriting': "'Segoe Script', 'cursive'",
        };
        const family = fontMap[fontStyle] || fontStyle;
        if (family) {
            styleEl.textContent = `body { font-family: ${family} !important; }`;
            styleEl.textContent += `\n#messageInput, .message-content, .tp-heading, .tp-subheading, .tp-face-name-zh { font-family: ${family} !important; }`;
        }
    }

    function removeFont() {
        const styleEl = document.getElementById(FONT_STYLE_ID);
        if (styleEl) styleEl.textContent = '';
    }

    // ─── 背景叠加特效 ──────────────────────────────────────────────────────────

    function applyOverlay(effect) {
        removeOverlay();
        if (!effect) return;

        const el = document.createElement('div');
        el.id = OVERLAY_ID;
        el.className = `skill-ui-overlay skill-ui-overlay-${effect}`;
        el.setAttribute('aria-hidden', 'true');

        // 星空特效：动态生成星点
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

        // 水晶特效：浮动几何图形
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

        // 蜡烛特效：底部火焰涌动
        if (effect === 'candles') {
            for (let i = 0; i < 5; i++) {
                const candle = document.createElement('div');
                candle.className = 'skill-ui-candle';
                candle.style.cssText = `
                    left: ${8 + i * 21}%;
                    animation-delay: ${Math.random() * 1.5}s;
                `;
                el.appendChild(candle);
            }
        }

        document.body.appendChild(el);
    }

    function removeOverlay() {
        const el = document.getElementById(OVERLAY_ID);
        if (el) el.remove();
    }

    // ─── 输入框占位符 ───────────────────────────────────────────────────────────

    function applyPlaceholder(text) {
        const input = document.getElementById('messageInput') || document.querySelector('.chat-input textarea, textarea[placeholder]');
        if (!input) return;
        if (!_originalPlaceholder) _originalPlaceholder = input.placeholder;
        if (text) input.placeholder = text;
    }

    function restorePlaceholder() {
        const input = document.getElementById('messageInput') || document.querySelector('.chat-input textarea, textarea[placeholder]');
        if (!input) return;
        if (_originalPlaceholder) input.placeholder = _originalPlaceholder;
        _originalPlaceholder = '';
    }

    // ─── 标题文字 ───────────────────────────────────────────────────────────────

    function applyTitle(titleText, subtitleText) {
        const titleEl = document.querySelector('.logo-text');
        const subEl   = document.querySelector('.logo-sub');
        if (titleEl) {
            if (!_originalTitle) _originalTitle = titleEl.textContent;
            if (titleText) titleEl.textContent = titleText;
        }
        if (subEl) {
            if (!_originalSubtitle) _originalSubtitle = subEl.textContent;
            if (subtitleText) subEl.textContent = subtitleText;
        }
    }

    function restoreTitle() {
        const titleEl = document.querySelector('.logo-text');
        const subEl   = document.querySelector('.logo-sub');
        if (titleEl && _originalTitle) { titleEl.textContent = _originalTitle; _originalTitle = ''; }
        if (subEl && _originalSubtitle) { subEl.textContent = _originalSubtitle; _originalSubtitle = ''; }
    }

    // ─── 技能栏显示/隐藏 ──────────────────────────────────────────────────────

    function applySkillBarVisibility(hide) {
        const bar = document.getElementById('chat-skill-bar');
        if (bar) bar.style.setProperty('--skill-bar-display', hide ? 'none' : '');
    }

    // ─── AI 回复前缀 ──────────────────────────────────────────────────────────
    // 将当前前缀暴露到全局，让消息渲染函数使用

    function applyAssistantPrefix(prefix) {
        _assistantPrefix = prefix || '';
        global.skillUiAssistantPrefix = _assistantPrefix;
    }

    // ─── 欢迎语 ────────────────────────────────────────────────────────────────

    function showWelcomeText(text) {
        if (!text) return;
        const chatMessages = document.getElementById('chatMessages') || document.querySelector('.messages-container, .chat-messages');
        if (!chatMessages) return;

        const existing = document.getElementById('skill-ui-welcome');
        if (existing) existing.remove();

        const el = document.createElement('div');
        el.id = 'skill-ui-welcome';
        el.className = 'skill-ui-welcome';
        el.innerHTML = `<div class="skill-ui-welcome-inner">${escapeHtml(text)}</div>`;
        chatMessages.insertBefore(el, chatMessages.firstChild);
    }

    function removeWelcomeText() {
        const el = document.getElementById('skill-ui-welcome');
        if (el) el.remove();
    }

    function escapeHtml(s) {
        return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }

    // ─── 主 apply / remove ───────────────────────────────────────────────────

    function applySkillUI(config, isNew) {
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

    function removeSkillUI() {
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

    // ─── 拉取并应用 ──────────────────────────────────────────────────────────

    let _lastSources = JSON.stringify([]);

    async function fetchAndApply() {
        try {
            const res = await fetch('/api/skills/active-ui-config');
            if (!res.ok) return;
            const data = await res.json();

            if (!data.success) return;

            const sourcesStr = JSON.stringify(data.sources || []);
            const isNew = sourcesStr !== _lastSources;
            _lastSources = sourcesStr;

            const sourceList = Array.isArray(data.sources) ? data.sources : [];
            const hasDivinationSource = sourceList.includes('divination');
            const tarotPersistent = Boolean(
                (global.TarotPicker && typeof global.TarotPicker.isPersistentActive === 'function' && global.TarotPicker.isPersistentActive()) ||
                document.getElementById('tarot-picker-widget') ||
                global._kotoTarotPending
            );

            if (data.has_ui && hasDivinationSource && data.config) {
                _lastDivinationConfig = data.config;
            }

            if (data.has_ui) {
                const configToApply = (tarotPersistent && _lastDivinationConfig) ? _lastDivinationConfig : data.config;
                applySkillUI(configToApply, isNew);
            } else if (tarotPersistent && _lastDivinationConfig) {
                applySkillUI(_lastDivinationConfig, false);
            } else {
                removeSkillUI();
            }

            // Activate tarot picker when divination skill is in the active source list
            const divinationActive = (data.has_ui && hasDivinationSource) || tarotPersistent;
            global._kotoDivinationActive = divinationActive;
            if (global.TarotPicker) {
                global.TarotPicker.setActive(divinationActive);
            }
        } catch (e) {
            // 静默失败 — UI 定制是增强功能，不阻断核心流程
        }
    }

    // ─── 钩入 refreshActiveSkills ────────────────────────────────────────────

    function hookRefreshActiveSkills() {
        const origFn = global.refreshActiveSkills;
        global.refreshActiveSkills = async function () {
            const result = origFn ? await origFn.apply(this, arguments) : undefined;
            await fetchAndApply();
            return result;
        };
    }

    // ─── 初始化 ──────────────────────────────────────────────────────────────

    function init() {
        document.addEventListener('DOMContentLoaded', () => {
            fetchAndApply();
            hookRefreshActiveSkills();
        });

        // 如果 DOMContentLoaded 已经触发，立即执行
        if (document.readyState !== 'loading') {
            fetchAndApply();
            hookRefreshActiveSkills();
        }
    }

    // ─── 公开 API ─────────────────────────────────────────────────────────────
    global.SkillUI = {
        refresh: fetchAndApply,
        remove:  removeSkillUI,
    };

    init();

})(window);
