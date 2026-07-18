from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_guided_tour_has_initialized_state_and_readable_copy() -> None:
    html = _read("web/templates/index.html")
    tour_start = html.index('var TOUR_KEY = "koto_tour_done_v3"')
    tour_end = html.index("</script>", tour_start)
    tour = html[tour_start:tour_end]

    assert "var currentStep = 0;" in tour
    assert "欢迎使用 Koto" in tour
    assert "开始对话" in tour
    assert "????????" not in tour


def test_welcome_onboarding_and_placeholders_have_readable_copy() -> None:
    html = _read("web/templates/index.html")

    assert "只需 3 步，开始使用 Koto" in html
    assert "写一份工作总结" in html
    assert "拖入 Excel/CSV → Koto 分析 → 输出结论与图表" in html
    assert "你的 AI 工作伙伴。直接告诉我你想做什么，我来帮你搞定。" in html


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
