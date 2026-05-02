from pathlib import Path
import re


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_docx_tooltip_buttons_keep_editor_focus():
    html = (_repo_root() / "web" / "templates" / "workspace_assistant.html").read_text(
        encoding="utf-8"
    )
    start_marker = '<div id="wa-pdf-tooltip" class="wa-selection-toolbar">'
    end_marker = "<!-- Chart Generation Dialog -->"
    start = html.find(start_marker)
    assert start != -1, "wa-pdf-tooltip block not found"
    end = html.find(end_marker, start)
    assert end != -1, "wa-pdf-tooltip block end marker not found"
    tooltip_block = html[start:end]
    assert tooltip_block.count('onmousedown="event.preventDefault()"') >= 6


def test_docx_hoverbar_has_font_controls():
    js = (_repo_root() / "web" / "static" / "js" / "workspace-assistant.js").read_text(
        encoding="utf-8"
    )
    assert "'fontFamily', 'fontSize'" in js


def test_canvas_body_does_not_clip_hoverbar():
    css = (_repo_root() / "web" / "static" / "css" / "workspace.css").read_text(
        encoding="utf-8"
    )
    block = re.search(r"#wa-canvas-body\s*\{(.*?)\}", css, flags=re.S)
    assert block, "#wa-canvas-body css block not found"
    body_css = block.group(1)
    assert "overflow: visible" in body_css
    assert "overflow: hidden" not in body_css
