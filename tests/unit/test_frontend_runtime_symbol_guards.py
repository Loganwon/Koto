from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_welcome_onboarding_and_placeholders_have_readable_copy() -> None:
    html = _read("web/templates/index.html")

    assert "今天要完成什么？" in html
    assert "提出问题、添加材料，或打开文档直接修改。" in html
    assert "执行过程与成果会保留在同一会话。" in html
    assert 'data-koto-suggestion="比较我附加的材料，列出主要差异与来源"' in html
    assert "描述任务，或添加文件一起处理…" in html


def test_docx_toolbar_imports_selection_payload_instead_of_declaring_global() -> None:
    toolbar = _read("web/src/ui/docx-pptx-toolbar.ts")

    assert re.search(
        r"import\s*\{[^}]*\b_getDocxSelectionPayload\b[^}]*\}\s*"
        r"from\s*['\"]\./selection-toolbar['\"]",
        toolbar,
    )
    assert "declare function _getDocxSelectionPayload" not in toolbar


def test_file_utils_imports_tab_renderer_instead_of_declaring_global() -> None:
    file_utils = _read("web/src/workspace/file-utils.ts")

    assert re.search(
        r"import\s*\{[^}]*\b_renderTabs\b[^}]*\}\s*from\s*['\"]\./state['\"]",
        file_utils,
        flags=re.S,
    )
    assert "declare function _renderTabs" not in file_utils
