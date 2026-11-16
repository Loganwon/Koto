from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_review_card_render_does_not_ensure_whole_state_per_card() -> None:
    source = _read("web/src/workspace/docx-review-runtime.ts")
    card_fn = source.split("function _cardHtml(", 1)[1].split(
        "function _renderReviewNavMenu", 1
    )[0]

    assert "_ensureTabReviewState" not in card_fn
    assert "focusedId: string" in card_fn


def test_review_entry_lookup_uses_a_per_tab_index() -> None:
    source = _read("web/src/workspace/docx-review-runtime.ts")
    lookup_fn = source.split("function _findReviewEntry", 1)[1].split(
        "function _previewReviewText", 1
    )[0]

    assert "WeakMap" in source
    assert ".index.get(raw)" in lookup_fn
    assert "_allReviewEntries(tab).find" not in lookup_fn


def test_review_dom_is_windowed_for_large_comment_sets() -> None:
    source = _read("web/src/workspace/docx-review-runtime.ts")
    windowing = _read("web/src/workspace/docx-review-window.ts")
    navigation = _read("web/src/workspace/docx-review-nav.ts")

    assert "DOCX_REVIEW_CARD_RENDER_BUDGET = 120" in windowing
    assert "DOCX_REVIEW_NAV_RENDER_BUDGET = 80" in windowing
    assert "function reviewNavWindow" in windowing
    assert "function reviewRenderWindow" in windowing
    assert ".slice(start, start + DOCX_REVIEW_CARD_RENDER_BUDGET)" in windowing
    assert "reviewRenderWindow(entries, focusedId)" in source
    assert "list.dataset.reviewTotal" in source
    assert 'aria-setsize="${Math.max(1, total)}"' in source
    assert "renderReviewNavMenu(_allReviewEntries()" in source
    assert "reviewNavWindow(" in navigation
    assert "menu.dataset.reviewNavRendered" in navigation


def test_review_geometry_excludes_the_compact_ai_overlay() -> None:
    geometry = _read("web/src/review/geometry.ts")
    layout = _read("web/src/review/layout-position.ts")

    assert "function visibleViewportRight" in geometry
    assert "aiRect.left < viewportRect.right" in geometry
    assert "usableViewportRight - viewportRect.left" in geometry
    assert "requiredScrollLeft" in layout
    assert "viewport.clientWidth" in layout


def test_review_layout_collision_resolution_only_checks_previous_peer() -> None:
    source = _read("web/src/review/layout-position.ts")
    placement = source.split("const lastLayoutEntryByPage", 1)[1].split(
        "const contentHeight", 1
    )[0]

    assert "lastLayoutEntryByPage.get(pageKey)" in placement
    assert "layoutEntries.filter" not in placement


def test_review_layout_second_pass_is_conditional() -> None:
    source = _read("web/src/review/layout-position.ts")
    scheduler = source.split("function scheduleReviewShellLayout", 1)[1].split(
        "function ensureReviewShellViewportSync", 1
    )[0]

    assert "scrollLeftAfterLayout !== scrollLeftBeforeLayout" in scheduler
    assert "else {\n        reviewShellLayoutFrame = 0;" in scheduler


def test_native_comment_layout_uses_exact_rendered_markers() -> None:
    renderer = _read("app/core/file/parsers/docx_rich_renderer.py")
    inline_renderer = _read("app/core/file/parsers/docx_rich_inline_renderer.py")
    layout = _read("web/src/review/layout-svg.ts")

    assert 'data-koto-review-source="docx_comment"' in inline_renderer
    assert "active_comment_ids=active_body_comment_ids" in renderer
    assert "const firstMarker = exactMarkers[0]" in layout
    assert "range.setEndAfter(lastMarker)" in layout
