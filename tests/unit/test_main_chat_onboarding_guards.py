import re
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read(rel_path: str) -> str:
    return (_repo_root() / rel_path).read_text(encoding="utf-8")


def test_main_chat_onboarding_uses_actionable_examples():
    html = _read("web/templates/index.html")

    assert "今天要完成什么？" in html
    assert "提出问题、添加材料，或打开文档直接修改。" in html
    assert "执行过程与成果会保留在同一会话。" in html
    assert 'class="koto-task-suggestions"' in html
    assert "比较材料" in html
    assert "生成报告" in html
    assert "快速开始 — 点击任意卡片填入示例" not in html
    assert "insertSuggestionWithSkill(" not in html
    assert "window.insertSuggestion" not in html
    assert 'onclick="insertSuggestion' not in html
    suggestions = re.findall(r'data-koto-suggestion="([^"]+)"', html)
    assert len(suggestions) >= 2
    assert "比较我附加的材料，列出主要差异与来源" in suggestions
    assert "根据材料生成一份有清晰结论的报告" in suggestions
    assert all(item.strip() for item in suggestions)
    primary_composer = _read("web/src/workspace/primary-composer.ts")
    assert "setActiveKotoComposerText(text)" in primary_composer
    assert "[data-koto-suggestion]" in primary_composer


def test_main_chat_onboarding_placeholder_and_greeting_logic_match_prompt_first_flow():
    html = _read("web/templates/index.html")
    router_ts = _read("web/src/app/router.ts")

    assert "描述任务，或添加文件一起处理…" in html
    assert 'id="messageInput"' not in html
    assert html.count('id="wa-user-input"') == 1
    assert "选择或创建对话" not in html
    assert "选择或创建对话" not in router_ts
    assert "今天要完成什么？" in router_ts
    assert "在文档旁，把修改做好" not in router_ts


def test_desktop_ai_composer_has_one_send_owner():
    main_ts = _read("web/src/app/main.ts")
    html = _read("web/templates/index.html")

    assert 'id="wa-user-input"' in html
    assert 'id="wa-send-btn"' in html
    assert 'id="messageInput"' not in html
    assert 'id="sendBtn"' not in html
    assert "delegateHiddenLegacySendToWorkspace" not in main_ts
    assert "window as any).sendMessage" not in main_ts
    assert "export async function sendMessage" not in main_ts
    assert 'id="kotoTourOverlay"' not in html


def test_cross_feature_composer_access_has_one_workspace_first_boundary():
    boundary = _read("web/src/shared/active-composer.ts")

    assert "export function getActiveKotoComposer" in boundary
    assert "export function setActiveKotoComposerText" in boundary
    assert "export function submitActiveKotoComposerText" in boundary
    assert "export function getActiveKotoMessageContainer" in boundary
    assert "wa-user-input" in boundary
    assert "messageInput" not in boundary
    assert "#sendBtn" not in boundary
    for retired in (
        "web/src/skills/skill-ui.ts",
        "web/src/skills/skill-ui-extensions.ts",
        "web/src/extras/tarot-picker.ts",
    ):
        assert not (_repo_root() / retired).exists()


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
    assert (
        "getFeatureRegistry().selectSetupProvider = selectSetupProvider" in settings_ts
    )
    assert "DeepSeek API Key" in app_js
    assert "Gemini" not in app_js
