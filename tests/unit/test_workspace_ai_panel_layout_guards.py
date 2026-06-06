from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read(rel_path: str) -> str:
    return (_repo_root() / rel_path).read_text(encoding="utf-8")


def test_workspace_templates_remove_top_settings_use_bottom_toggle_and_keep_files_above_input():
    embedded_html = _read("web/templates/index.html")
    standalone_html = _read("web/templates/workspace_assistant.html")
    model_controls = _read("web/templates/_workspace_model_controls.html")

    for html in (embedded_html, standalone_html):
        assert 'id="wa-subject-bar"' not in html
        assert '当前编辑' not in html
        assert 'id="wa-ai-settings-panel"' not in html
        assert 'AI 输出模式' not in html
        assert 'id="wa-footer-file-chip"' not in html
        assert 'id="wa-footer-attach-current-btn"' not in html
        assert "{% include '_workspace_model_controls.html' %}" in html
        assert '只有明确选中的文本和分析文档会进入当前任务上下文。' in html
        assert '快速读懂当前文件' not in html
        assert '当前文件、选区和附件会自动并入上下文。' not in html
        assert html.index('<div id="wa-ai-file-chips"') < html.index('<div id="wa-actions-bar">')
        assert html.index('<div id="wa-ai-file-chips"') < html.index('<div class="wa-input-box">')
        assert html.index('<div class="wa-input-box-footer">') < html.index("{% include '_workspace_model_controls.html' %}")
        assert html.index("{% include '_workspace_model_controls.html' %}") < html.index('<div class="wa-footer-actions">')
        assert html.index('<div class="wa-footer-actions">') < html.index('id="wa-send-btn"')

    assert 'id="wa-model-mode-toggle"' in model_controls
    assert 'id="wa-model-mode-gemini-btn"' in model_controls
    assert 'id="wa-model-mode-deepseek-btn"' in model_controls
    assert 'id="wa-model-mode-local-btn"' in model_controls
    assert 'class="wa-model-mode-main">Gemini<' in model_controls
    assert 'class="wa-model-mode-main">DeepSeek<' in model_controls
    assert 'id="wa-model-mode-gemini-model"' in model_controls
    assert 'id="wa-model-mode-deepseek-model"' in model_controls
    assert 'id="wa-model-mode-local-model"' in model_controls


def test_workspace_subject_bar_and_action_row_styles_support_restored_layout():
    js = _read("web/static/js/workspace-assistant.js")
    css = _read("web/static/css/workspace.css")

    assert "toggleCurrentFileAIContext" not in js
    assert "addCurrentFileToAIContext" not in js
    assert "只处理用户明确提供的选中文本和分析文档" in js
    assert "按提取文本估算" not in js
    assert "open_tabs: []," in js
    assert "当前文件: ${state.fileName}" not in js
    assert "#wa-subject-bar { display: none !important;" not in css
    assert ".wa-actions-spacer" in css
    assert ".wa-model-mode-toggle" in css
    assert ".wa-model-mode-toggle-btn" in css
    assert ".wa-model-mode-sub[hidden]" in css
    assert ".wa-model-mode-sub::before" in css
    assert "_coerceModelLabel" in js
    assert "wa_model_choice_explicit" in js
    assert "_currentCloudModelHint" in js
    assert "_localRuntimeModel" in js
    assert "localStorage.removeItem('wa_ai_output_mode');" in js
    assert "border-bottom: 1px solid var(--border);" in css
    assert "--ai-bg: #FFFFFF;" in css
    assert "--ai-surface: #FBFCFE;" in css
    assert "--ai-border: rgba(15, 23, 42, 0.10);" in css
    assert "#wa-ai {" in css
    assert "background: var(--ai-bg);" in css
    assert "border: 1px solid color-mix(in srgb, var(--ai-border) 70%, transparent);" in css