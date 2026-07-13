"""Guard the single-owner contract for workspace review and selection globals."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def _wa_assignment_count(source: str, name: str) -> int:
    return source.count(f".WA.{name} =")


def test_review_and_selection_wa_globals_have_one_source_owner() -> None:
    ai_review = _read("web/src/workspace/ai-review.ts")
    docx_review_runtime = _read("web/src/workspace/docx-review-runtime.ts")
    docx_pptx_toolbar = _read("web/src/ui/docx-pptx-toolbar.ts")
    selection_toolbar = _read("web/src/ui/selection-toolbar.ts")

    assert _wa_assignment_count(ai_review, "closeReviewCenter") == 0
    assert _wa_assignment_count(docx_review_runtime, "closeReviewCenter") == 0
    assert _wa_assignment_count(ai_review, "setReviewMode") == 0
    assert _wa_assignment_count(docx_review_runtime, "setReviewMode") == 0
    assert "publishWorkspaceApi({" in ai_review
    assert "closeReviewCenter," in ai_review
    assert "setReviewMode," in ai_review

    assert _wa_assignment_count(selection_toolbar, "closeSelectionToolbar") == 0
    assert _wa_assignment_count(docx_pptx_toolbar, "closeSelectionToolbar") == 0
    assert "publishWorkspaceApi({" in selection_toolbar
    assert "closeSelectionToolbar," in selection_toolbar


def test_global_owners_keep_docx_review_and_toolbar_close_contracts() -> None:
    ai_review = _read("web/src/workspace/ai-review.ts")
    docx_review_runtime = _read("web/src/workspace/docx-review-runtime.ts")
    selection_toolbar = _read("web/src/ui/selection-toolbar.ts")

    assert "export function closeReviewCenter(): void" in ai_review
    assert "export function setReviewMode(mode: string): void" in ai_review
    assert "_syncReviewStateForActiveFile().catch(() => {});" in ai_review
    assert "_refreshReviewShell();" in ai_review

    assert (
        "WA.openReviewCenter = () => { _setReviewCenterOpen(true); _renderReviewShell(); };"
        in docx_review_runtime
    )
    assert "WA.toggleReviewCommentMode" in docx_review_runtime

    assert "if (state.fileType === 'docx')" in selection_toolbar
    assert "_docxHoverForceHiddenText" in selection_toolbar
    assert "_resetDocxSelection();" in selection_toolbar
