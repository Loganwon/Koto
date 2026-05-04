from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read(rel_path: str) -> str:
    return (_repo_root() / rel_path).read_text(encoding="utf-8")


def test_review_shell_entry_is_present_without_ai_comment_entrypoints():
    embedded_html = _read("web/templates/index.html")
    standalone_html = _read("web/templates/workspace_assistant.html")

    for html in (embedded_html, standalone_html):
        assert 'id="wa-review-shell"' in html
        assert 'onclick="WA.openReviewCenter()"' in html
        assert 'id="wa-review-mode-group"' in html
        assert "onclick=\"WA.sendQuickAction('批注')\"" not in html
        assert "onclick=\"WA.addSelectionComment()\"" not in html
        assert '>AI 批注<' not in html


def test_workspace_hydrates_native_docx_review_state_and_exposes_visible_review_entry():
    js = _read("web/static/js/workspace-assistant.js")

    assert "function _syncReviewStateForActiveFile" in js
    assert "function _syncDocCommentStateForActiveFile" in js
    assert "function _ensureReviewToggleBtn" in js
    assert "window.WA.openReviewCenter" in js
    assert "window.WA.editReviewComment" in js
    assert "window.WA.focusReviewThread" in js
    assert "_syncReviewStateForActiveFile().catch" in js
    assert "window.WA.onDocxCommentsChanged" in js
    assert "window.WA.addSelectionComment" not in js
    assert "'批注': 'comment'" not in js
    assert "AI 批注当前仅支持 DOCX 文档视图" not in js


def test_workspace_review_css_keeps_native_comment_surfaces():
    css = _read("web/static/css/workspace.css")

    assert ".koto-comment-anchor" in css
    assert ".koto-docx-comment-layer" in css
    assert ".koto-docx-comment-card" in css
    assert ".koto-docx-comment-edit" in css