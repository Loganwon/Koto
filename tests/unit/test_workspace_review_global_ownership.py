"""Guard the single-owner contract for workspace review and selection globals."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def _wa_assignment_count(source: str, name: str) -> int:
    return source.count(f".WA.{name} =")


def test_review_and_selection_globals_have_one_source_owner() -> None:
    ai_review = _read("web/src/workspace/ai-review.ts")
    docx_review_api = _read("web/src/workspace/docx-review-api.ts")
    docx_review_runtime = _read("web/src/workspace/docx-review-runtime.ts")
    docx_pptx_toolbar = _read("web/src/ui/docx-pptx-toolbar.ts")
    selection_toolbar = _read("web/src/ui/selection-toolbar.ts")

    assert _wa_assignment_count(ai_review, "closeReviewCenter") == 0
    assert _wa_assignment_count(docx_review_runtime, "closeReviewCenter") == 0
    assert _wa_assignment_count(ai_review, "setReviewMode") == 0
    assert _wa_assignment_count(docx_review_runtime, "setReviewMode") == 0
    assert "export function closeReviewCenter" not in ai_review
    assert "export function setReviewMode" not in ai_review
    assert "export function closeReviewCenter" not in docx_review_runtime
    assert "export function setReviewMode" not in docx_review_runtime
    assert "(window as any)._syncReview" not in docx_review_runtime
    assert "(window as any)._renderReview" not in docx_review_runtime
    assert "closeReviewCenter" not in docx_review_api
    assert "setReviewMode" not in docx_review_api

    assert _wa_assignment_count(selection_toolbar, "closeSelectionToolbar") == 0
    assert _wa_assignment_count(docx_pptx_toolbar, "closeSelectionToolbar") == 0
    assert "publishWorkspaceApi({" in selection_toolbar
    assert "closeSelectionToolbar," in selection_toolbar


def test_docx_review_keeps_only_the_external_editor_workspace_api_contract() -> None:
    ai_review = _read("web/src/workspace/ai-review.ts")
    docx_review_api = _read("web/src/workspace/docx-review-api.ts")
    docx_review_runtime = _read("web/src/workspace/docx-review-runtime.ts")
    selection_toolbar = _read("web/src/ui/selection-toolbar.ts")

    assert "_installReviewActionDelegation" not in ai_review
    assert "export async function acceptProposal" not in ai_review
    assert "export function rejectProposal" not in ai_review
    assert "export function toggleReviewCommentMode" in docx_review_runtime
    assert "export async function focusReviewThread" in docx_review_runtime
    assert "export function relayoutDocxReviewRail" in docx_review_runtime
    assert "publishWorkspaceApi({" not in docx_review_runtime
    published = docx_review_api.split("publishWorkspaceApi({", 1)[1]
    assert "focusReviewThread," in published
    assert "relayoutDocxReviewRail," in published
    assert "toggleReviewCommentMode," not in published
    assert "applyStructuredDocToolCall," not in published

    assert "if (state.fileType === 'docx')" in selection_toolbar
    assert "setDocxHoverForceHiddenText" in selection_toolbar
    assert "_docxHoverForceHiddenText" not in selection_toolbar
    assert "_resetDocxSelection();" in selection_toolbar


def test_docx_review_lazy_bundle_is_the_only_engine_registration_bridge() -> None:
    engine_entry = _read("web/src/bundles/docx-review-engine.ts")
    engine_loader = _read("web/src/workspace/docx-review-loader.ts")
    review_runtime = _read("web/src/workspace/docx-review-runtime.ts")

    assert engine_entry.count("KotoDocxReviewEngineModule =") == 1
    assert "KotoDocxReviewEngineModule =" not in engine_loader
    assert "KotoDocxReviewEngineModule =" not in review_runtime
    assert "loadDocxReviewEngine" in engine_loader
    assert "installDocxReviewEngine(existing)" in engine_loader
