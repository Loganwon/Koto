from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read(rel_path: str) -> str:
    return (_repo_root() / rel_path).read_text(encoding="utf-8")


def test_workspace_templates_remove_top_settings_use_bottom_toggle_and_keep_files_above_input():
    embedded_html = _read("web/templates/index.html")
    standalone_html = _read("web/templates/workspace_assistant.html")

    for html in (embedded_html, standalone_html):
        assert 'id="wa-subject-icon"' in html
        assert 'class="subject-editor-badge">当前编辑<' in html
        assert 'id="wa-ai-settings-panel"' not in html
        assert 'AI 输出模式' not in html
        assert 'id="wa-footer-file-chip"' not in html
        assert 'id="wa-model-mode-toggle"' in html
        assert 'id="wa-model-mode-cloud-btn"' in html
        assert 'id="wa-model-mode-local-btn"' in html
        assert 'class="wa-model-mode-main">Gemini<' in html
        assert 'id="wa-model-mode-cloud-model"' in html
        assert 'id="wa-model-mode-local-model"' in html
        assert html.index('<div id="wa-ai-file-chips"') < html.index('<div id="wa-actions-bar">')
        assert html.index('<div id="wa-ai-file-chips"') < html.index('<div class="wa-input-box">')
        assert html.index('<div class="wa-input-box-footer">') < html.index('id="wa-model-mode-toggle"')
        assert html.index('id="wa-model-mode-toggle"') < html.index('<div class="wa-footer-actions">')
        assert html.index('<div class="wa-footer-actions">') < html.index('id="wa-send-btn"')


def test_workspace_subject_bar_and_action_row_styles_support_restored_layout():
    js = _read("web/static/js/workspace-assistant.js")
    css = _read("web/static/css/workspace.css")

    assert "Keep the legacy subject-bar hidden" not in js
    assert "const hasAttachedFiles = Array.isArray(state._aiFileContext) && state._aiFileContext.length > 0;" in js
    assert "bar.style.display = 'flex';" in js
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