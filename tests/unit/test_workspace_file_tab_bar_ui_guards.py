from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read(rel_path: str) -> str:
    return (_repo_root() / rel_path).read_text(encoding="utf-8")


def test_workspace_templates_keep_file_tab_bar_before_canvas_body():
    embedded_html = _read("web/templates/index.html")
    standalone_html = _read("web/templates/workspace_assistant.html")

    for html in (embedded_html, standalone_html):
      assert '<div id="wa-tab-bar"></div>' in html
      assert html.index('<div id="wa-tab-bar"></div>') < html.index('<div id="wa-canvas-body">')


def test_workspace_tab_bar_js_renders_document_badges_and_single_tab_mode():
    js = _read("web/static/js/workspace-assistant.js")

    assert "function _tabDisplayInfo(tab)" in js
    assert "bar.classList.toggle('single-tab', state.openTabs.length <= 1);" in js
    assert 'data-ext="${extAttr}"' in js
    assert '<span class="tab-main">' in js
    assert '<span class="tab-badge">${badgeEsc}</span>' in js


def test_workspace_tab_bar_css_has_document_chrome_and_file_type_accents():
    css = _read("web/static/css/workspace.css")

    assert "#wa-tab-bar.single-tab .wa-tab" in css
    assert '.wa-tab[data-ext="docx"]' in css
    assert ".wa-tab::before" in css
    assert ".wa-tab .tab-badge" in css