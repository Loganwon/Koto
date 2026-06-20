from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read(rel_path: str) -> str:
    return (_repo_root() / rel_path).read_text(encoding="utf-8")


def test_main_chat_onboarding_uses_prompt_first_welcome():
    html = _read("web/templates/index.html")

    assert "直接开始" in html
    assert "先说目标，再补充文件或上下文" in html
    assert "直接告诉 Koto 你想完成什么" in html
    assert "不必先选固定任务" in html
    assert "welcome-capability-row" in html
    assert "先帮我判断怎么做" in html
    assert "先给我一个结果" in html
    assert "快速开始 — 点击任意卡片填入示例" not in html
    assert "写作与润色" not in html
    assert "insertSuggestionWithSkill(" not in html


def test_main_chat_onboarding_placeholder_and_greeting_logic_match_prompt_first_flow():
    html = _read("web/templates/index.html")
    app_js = _read("web/static/js/app.js")

    assert "直接告诉我你想完成什么，或拖入文件开始分析…" in html
    assert 'id="welcomeGreeting"' in html
    assert "选择或创建对话" not in html
    assert "选择或创建对话" not in app_js
    assert "夜深了，还在呢🌙" in app_js
    assert "早上好，有什么需要帮忙？☀️" in app_js


def test_setup_wizard_uses_deepseek_api_key_only():
    html = _read("web/templates/index.html")
    app_js = _read("web/static/js/build/app-bundle.js")

    assert "设置云端模型 API Key" in html
    assert 'id="setupProviderDeepSeek"' in html
    assert 'id="setupProviderGemini"' not in html
    assert "Gemini" not in html
    assert "Google AI Studio" not in html
    assert "platform.deepseek.com/api_keys" in app_js
    assert "function selectSetupProvider(provider)" in app_js
    assert "DeepSeek API Key" in app_js
    assert "Gemini" not in app_js
