from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read(rel_path: str) -> str:
    return (_repo_root() / rel_path).read_text(encoding="utf-8")


def test_workspace_templates_remove_top_settings_use_bottom_dropdown_and_keep_files_above_input():
    embedded_html = _read("web/templates/index.html")
    standalone_html = _read("web/templates/workspace_assistant.html")

    for html in (embedded_html, standalone_html):
        assert 'id="wa-subject-icon"' in html
        assert 'class="subject-editor-badge">当前编辑<' in html
        assert 'id="wa-ai-settings-panel"' not in html
        assert 'AI 输出模式' not in html
        assert 'id="wa-model-mode-menu"' in html
        assert 'id="wa-model-mode-trigger"' in html
        assert 'id="wa-model-mode-dropdown"' in html
        assert html.index('<div id="wa-ai-file-chips"') < html.index('<div id="wa-actions-bar">')
        assert html.index('<div id="wa-ai-file-chips"') < html.index('<div class="wa-input-box">')
        assert html.index('<div class="wa-input-box-footer">') < html.index('id="wa-model-mode-menu"')
        assert html.index('id="wa-model-mode-menu"') < html.index('id="wa-send-btn"')


def test_workspace_subject_bar_and_action_row_styles_support_restored_layout():
    js = _read("web/static/js/workspace-assistant.js")
    css = _read("web/static/css/workspace.css")

    assert "Keep the legacy subject-bar hidden" not in js
    assert "const hasAttachedFiles = Array.isArray(state._aiFileContext) && state._aiFileContext.length > 0;" in js
    assert "bar.style.display = 'flex';" in js
    assert "#wa-subject-bar { display: none !important;" not in css
    assert ".wa-actions-spacer" in css
    assert ".wa-model-mode-menu" in css
    assert ".wa-model-mode-dropdown" in css
    assert "localStorage.removeItem('wa_ai_output_mode');" in js
    assert "toggleModelModeMenu" in js
    assert "border-bottom: 1px solid var(--border);" in css