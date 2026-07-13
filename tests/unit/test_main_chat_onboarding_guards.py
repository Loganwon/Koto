from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read(rel_path: str) -> str:
    return (_repo_root() / rel_path).read_text(encoding="utf-8")


def test_main_chat_onboarding_uses_actionable_examples():
    html = _read("web/templates/index.html")

    assert "你好，我是 Koto" in html
    assert "直接告诉我你想做什么，我来帮你搞定" in html
    assert "welcome-quick-cards" in html
    assert "写文档" in html
    assert "分析数据" in html
    assert "做PPT" in html
    assert "只需 3 步，开始使用 Koto" in html
    assert "快速开始 — 点击任意卡片填入示例" not in html
    assert "insertSuggestionWithSkill(" not in html
    assert "window.insertSuggestion" not in html
    assert "onclick=\"insertSuggestion" not in html
    assert html.count("data-koto-suggestion=") == 9
    primary_composer = _read("web/src/workspace/primary-composer.ts")
    assert "setActiveKotoComposerText(text)" in primary_composer
    assert "[data-koto-suggestion]" in primary_composer


def test_main_chat_onboarding_placeholder_and_greeting_logic_match_prompt_first_flow():
    html = _read("web/templates/index.html")
    router_ts = _read("web/src/app/router.ts")

    assert "直接告诉我你想完成什么，或拖入文件开始分析…" in html
    assert 'id="welcomeGreeting"' in html
    assert "选择或创建对话" not in html
    assert "选择或创建对话" not in router_ts
    assert "夜深了，还在呢🌙" in router_ts
    assert "早上好，有什么需要帮忙？☀️" in router_ts


def test_hidden_legacy_composer_delegates_to_workspace_sender():
    main_ts = _read("web/src/app/main.ts")
    html = _read("web/templates/index.html")

    assert "function delegateHiddenLegacySendToWorkspace(event?: Event)" in main_ts
    assert "const workspaceSender = (window as any).WA?.sendMessage" in main_ts
    assert "if (legacyMessage || workspaceInput.value.trim()) workspaceSender();" in main_ts
    assert "Double-click / rapid-submit prevention" not in html
    assert "_kotoResetSending" not in html
    assert 'target: "#wa-chat-panel, #wa-user-input"' in html


def test_cross_feature_composer_access_has_one_workspace_first_boundary():
    boundary = _read("web/src/shared/active-composer.ts")
    skill_ui = _read("web/src/skills/skill-ui.ts")
    skill_extensions = _read("web/src/skills/skill-ui-extensions.ts")
    tarot = _read("web/src/extras/tarot-picker.ts")

    assert "export function getActiveKotoComposer" in boundary
    assert "export function setActiveKotoComposerText" in boundary
    assert "export function submitActiveKotoComposerText" in boundary
    assert "export function getActiveKotoMessageContainer" in boundary
    assert boundary.index("wa-user-input") < boundary.index("messageInput")
    assert "from '../shared/active-composer';" in skill_ui
    assert "getActiveKotoComposer" in skill_ui
    assert "import { submitActiveKotoComposerText } from '../shared/active-composer';" in skill_extensions
    assert "function _setChatInputValue" not in skill_extensions
    assert "getActiveKotoMessageContainer" in skill_ui
    assert "submitActiveKotoComposerText(final);" in tarot
    assert "getActiveKotoMessageContainer" in tarot
    on_confirm = tarot[tarot.index("function onConfirm(): void {"):tarot.index("function renderPostReadingScreen", tarot.index("function onConfirm(): void {"))]
    assert "messageInput" not in on_confirm
    assert "sendBtn" not in on_confirm


def test_setup_wizard_uses_deepseek_api_key_only():
    html = _read("web/templates/index.html")
    app_js = _read("web/static/js/build/app-bundle.js")
    settings_ts = _read("web/src/app/settings.ts")

    assert "设置云端模型 API Key" in html
    assert 'id="setupProviderDeepSeek"' in html
    assert 'id="setupProviderGemini"' not in html
    assert "Gemini" not in html
    assert "Google AI Studio" not in html
    assert "platform.deepseek.com/api_keys" in app_js
    assert "export function selectSetupProvider(provider: string)" in settings_ts
    assert "window as any).selectSetupProvider = selectSetupProvider" in settings_ts
    assert "DeepSeek API Key" in app_js
    assert "Gemini" not in app_js
