"""Playwright E2E tests for DOCX review/comment interactions."""

from __future__ import annotations

import pytest

EDITOR_LOAD_TIMEOUT = 60_000
REVIEW_TIMEOUT = 20_000


def _wait_until_visible(page, selector: str, timeout: int = REVIEW_TIMEOUT) -> None:
    page.wait_for_function(
        """(selector) => {
            const el = document.querySelector(selector);
            if (!el) return false;
            const rect = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return rect.width > 0
                && rect.height > 0
                && style.display !== 'none'
                && style.visibility !== 'hidden'
                && parseFloat(style.opacity || '1') > 0.05;
        }""",
        arg=selector,
        timeout=timeout,
    )


def _wait_until_text_includes(
    page,
    selector: str,
    expected_text: str,
    timeout: int = REVIEW_TIMEOUT,
) -> None:
    page.wait_for_function(
        """({ selector, expectedText }) => {
            const el = document.querySelector(selector);
            return !!el && String(el.textContent || '').includes(expectedText);
        }""",
        arg={"selector": selector, "expectedText": expected_text},
        timeout=timeout,
    )


def _open_docx_for_review(page, base_url: str, docx_path: str) -> None:
    page.goto(f"{base_url}/", timeout=15_000, wait_until="domcontentloaded")
    page.locator("#wa-file-input").set_input_files(docx_path)
    _wait_until_visible(
        page, "#wa-docx-editor .ProseMirror", timeout=EDITOR_LOAD_TIMEOUT
    )
    page.wait_for_function(
        "() => !!window.WA && typeof window.WA.toggleReviewCommentMode === 'function'",
        timeout=REVIEW_TIMEOUT,
    )
    _wait_until_visible(page, ".wa-docx-review-mode")


def _ensure_review_mode_open(page) -> None:
    is_open = page.evaluate("""() => {
            const shell = document.getElementById('wa-review-shell');
            if (!shell) return false;
            const style = window.getComputedStyle(shell);
            return style.display !== 'none' && style.visibility !== 'hidden';
        }""")
    if is_open:
        return
    page.locator(".wa-docx-review-mode").click()
    _wait_until_visible(page, "#wa-review-shell")
    page.wait_for_function(
        """() => {
            const btn = document.querySelector('.wa-docx-review-mode');
            return !!btn && btn.getAttribute('aria-pressed') === 'true';
        }""",
        timeout=REVIEW_TIMEOUT,
    )


def _select_docx_text(page, target_text: str) -> None:
    selection = page.evaluate(
        """({ targetText }) => {
            const root = document.querySelector('#wa-docx-editor .ProseMirror');
            if (!root) return null;
            const walker = document.createTreeWalker(
                root,
                NodeFilter.SHOW_TEXT,
                {
                    acceptNode(node) {
                        return String(node.textContent || '').trim()
                            ? NodeFilter.FILTER_ACCEPT
                            : NodeFilter.FILTER_REJECT;
                    },
                },
            );
            let node = null;
            while ((node = walker.nextNode())) {
                const text = String(node.textContent || '');
                const index = text.indexOf(targetText);
                if (index < 0) continue;
                const parent = node.parentElement;
                if (parent && typeof parent.scrollIntoView === 'function') {
                    parent.scrollIntoView({ block: 'center', inline: 'nearest' });
                }
                const range = document.createRange();
                range.setStart(node, index);
                range.setEnd(node, index + targetText.length);
                const selection = window.getSelection();
                if (!selection) return null;
                selection.removeAllRanges();
                selection.addRange(range);
                document.dispatchEvent(new Event('selectionchange', { bubbles: true }));
                return {
                    selectedText: selection.toString(),
                    rectCount: range.getClientRects().length,
                };
            }
            return null;
        }""",
        {"targetText": target_text},
    )
    assert selection, f"Could not select DOCX text: {target_text!r}"
    assert target_text in selection["selectedText"]
    assert selection["rectCount"] > 0
    page.evaluate("() => window.WA.captureReviewSelection()")


def _review_card_ids(page) -> list[str]:
    return page.evaluate(
        """() => Array.from(
            document.querySelectorAll('#wa-review-shell .koto-docx-comment-card[data-review-id]')
        ).map((node) => String(node.getAttribute('data-review-id') || '').trim()).filter(Boolean)"""
    )


def _click_last_review_action(page, action: str) -> None:
    clicked = page.evaluate(
        """(actionName) => {
            const buttons = Array.from(
                document.querySelectorAll(`#wa-review-shell [data-review-action="${actionName}"]`)
            );
            const btn = buttons[buttons.length - 1];
            if (!btn) return false;
            btn.click();
            return true;
        }""",
        action,
    )
    assert clicked, f"Could not click review action: {action!r}"


def _review_geometry(page, card_selector: str, anchor_text: str) -> dict:
    geometry = page.evaluate(
        """({ cardSelector, anchorText }) => {
            const card = document.querySelector(cardSelector);
            const root = document.querySelector('#wa-docx-editor .ProseMirror');
            if (!card || !root) return null;
            const walker = document.createTreeWalker(
                root,
                NodeFilter.SHOW_TEXT,
                {
                    acceptNode(node) {
                        return String(node.textContent || '').trim()
                            ? NodeFilter.FILTER_ACCEPT
                            : NodeFilter.FILTER_REJECT;
                    },
                },
            );
            let node = null;
            let anchorRect = null;
            while ((node = walker.nextNode())) {
                const text = String(node.textContent || '');
                const index = text.indexOf(anchorText);
                if (index < 0) continue;
                const range = document.createRange();
                range.setStart(node, index);
                range.setEnd(node, index + anchorText.length);
                const rects = Array.from(range.getClientRects()).filter(
                    (rect) => rect.width > 0 || rect.height > 0
                );
                const rect = rects[rects.length - 1] || range.getBoundingClientRect();
                anchorRect = rect;
                break;
            }
            if (!anchorRect) return null;
            const cardRect = card.getBoundingClientRect();
            const saveButton = card.querySelector('[data-review-action="save"]');
            const saveRect = saveButton ? saveButton.getBoundingClientRect() : null;
            const pageEl = root;
            const pageRect = pageEl.getBoundingClientRect();
            const pageStyles = window.getComputedStyle(pageEl);
            const pagePaddingRight = Math.max(0, parseFloat(pageStyles.paddingRight || '0') || 0);
            const pageScaleX = pageEl.offsetWidth > 0 ? (pageRect.width / pageEl.offsetWidth) : 1;
            const textColRight = Math.round(pageRect.right - (pagePaddingRight * pageScaleX));
            const viewportWidth = window.innerWidth;
            const viewportHeight = window.innerHeight;
            const inViewport = (rect) => !!rect
                && rect.left >= 0
                && rect.top >= 0
                && rect.right <= viewportWidth
                && rect.bottom <= viewportHeight;
            return {
                cardWidth: Math.round(cardRect.width),
                cardHeight: Math.round(cardRect.height),
                cardLeftDelta: Math.round(cardRect.left - anchorRect.right),
                cardTopDelta: Math.round(cardRect.top - anchorRect.top),
                textColRight,
                cardOutsideText: Math.round(cardRect.left) >= textColRight + 4,
                cardInViewport: inViewport(cardRect),
                saveInViewport: inViewport(saveRect),
                hasInlineAnchorButton: !!card.querySelector('.wa-review-anchor-inline'),
                hasLegacyAnchorRow: !!card.querySelector('.wa-review-anchor-link'),
                anchorButtonLabel: (() => {
                    const button = card.querySelector('.wa-review-anchor-inline');
                    return button ? String(button.getAttribute('title') || button.textContent || '').trim() : '';
                })(),
                connectorExists: !!document.querySelector('#wa-review-shell .wa-review-connector-path'),
            };
        }""",
        {"cardSelector": card_selector, "anchorText": anchor_text},
    )
    assert geometry, f"Could not measure review geometry for {card_selector!r}"
    return geometry


def _wait_for_review_card_focus(
    page, review_id: str, timeout: int = REVIEW_TIMEOUT
) -> None:
    page.wait_for_function(
        """(reviewId) => {
            const card = document.querySelector(`#wa-review-shell [data-review-id="${reviewId}"]`);
            return !!card && card.classList.contains('is-focused');
        }""",
        arg=review_id,
        timeout=timeout,
    )


def _create_comment_via_launcher(
    page,
    anchor_text: str,
    comment_text: str,
    expected_summary: str,
) -> str:
    _ensure_review_mode_open(page)
    _select_docx_text(page, anchor_text)
    _wait_until_visible(page, "#wa-review-selection-launcher")
    _wait_until_text_includes(
        page,
        "#wa-review-selection-launcher .wa-review-selection-title",
        "添加批注或修订",
    )
    page.locator('#wa-review-selection-launcher [data-review-create="comment"]').click()
    _wait_until_visible(page, "#wa-review-shell .koto-docx-comment-edit")
    textarea = page.locator("#wa-review-shell .koto-docx-comment-edit").last
    textarea.fill(comment_text)
    draft_geometry = _review_geometry(
        page,
        "#wa-review-shell .koto-docx-comment-card:last-of-type",
        anchor_text,
    )
    assert 218 <= draft_geometry["cardWidth"] <= 302
    assert draft_geometry["cardLeftDelta"] >= 6
    card_count = page.locator("#wa-review-shell .koto-docx-comment-card").count()
    if card_count == 1:
        assert abs(draft_geometry["cardTopDelta"]) <= 24
    else:
        assert -24 <= draft_geometry["cardTopDelta"] <= 200
    assert draft_geometry["cardOutsideText"] is True, draft_geometry
    assert draft_geometry["cardInViewport"] is True
    assert draft_geometry["saveInViewport"] is True
    assert draft_geometry["hasInlineAnchorButton"] is True
    assert draft_geometry["hasLegacyAnchorRow"] is False
    assert draft_geometry["connectorExists"] is True
    _click_last_review_action(page, "save")
    page.wait_for_function(
        """(text) => Array.from(
            document.querySelectorAll('#wa-review-shell .koto-docx-comment-body')
        ).some((node) => String(node.textContent || '').includes(text))""",
        arg=comment_text,
        timeout=REVIEW_TIMEOUT,
    )
    _wait_until_text_includes(page, ".wa-docx-review-summary", expected_summary)
    ids = _review_card_ids(page)
    assert ids, "Expected at least one review comment card after saving"
    return ids[-1]


@pytest.fixture()
def docx_review_ui_docx_path(tmp_path):
    docx_module = pytest.importorskip("docx")

    path = tmp_path / "docx_review_ui.docx"
    doc = docx_module.Document()
    doc.add_paragraph("第一段用于批注测试，应该可以稳定选中并创建批注。")
    doc.add_paragraph("第二段用于导航定位测试，应该支持第二条批注。")
    doc.save(path)
    return str(path)


pytestmark = pytest.mark.e2e


def test_docx_review_selection_launcher_creates_comment(
    e2e_page,
    e2e_base_url,
    docx_review_ui_docx_path,
    console_errors,
):
    _open_docx_for_review(e2e_page, e2e_base_url, docx_review_ui_docx_path)

    review_id = _create_comment_via_launcher(
        e2e_page,
        anchor_text="批注测试",
        comment_text="这是第一条批注",
        expected_summary="1条批注",
    )

    _wait_for_review_card_focus(e2e_page, review_id)
    e2e_page.wait_for_function(
        """({ selector, text }) => {
            const button = document.querySelector(selector);
            return !!button && String(button.getAttribute('title') || '').includes(text);
        }""",
        arg={
            "selector": f'#wa-review-shell [data-review-id="{review_id}"] .wa-review-anchor-inline',
            "text": "批注测试",
        },
        timeout=REVIEW_TIMEOUT,
    )
    saved_geometry = _review_geometry(
        e2e_page,
        f'#wa-review-shell [data-review-id="{review_id}"]',
        "批注测试",
    )
    assert 218 <= saved_geometry["cardWidth"] <= 302
    assert saved_geometry["cardHeight"] <= 100
    assert saved_geometry["cardLeftDelta"] >= 6
    assert abs(saved_geometry["cardTopDelta"]) <= 24
    assert saved_geometry["cardOutsideText"] is True
    assert saved_geometry["cardInViewport"] is True
    assert saved_geometry["hasInlineAnchorButton"] is True
    assert saved_geometry["hasLegacyAnchorRow"] is False
    assert "批注测试" in saved_geometry["anchorButtonLabel"]
    assert saved_geometry["connectorExists"] is True
    assert len(_review_card_ids(e2e_page)) == 1
    assert console_errors == [], f"JS errors: {console_errors}"


def test_docx_review_nav_menu_edit_and_delete_flow(
    e2e_page,
    e2e_base_url,
    docx_review_ui_docx_path,
    console_errors,
):
    _open_docx_for_review(e2e_page, e2e_base_url, docx_review_ui_docx_path)

    first_id = _create_comment_via_launcher(
        e2e_page,
        anchor_text="批注测试",
        comment_text="第一条原始批注",
        expected_summary="1条批注",
    )
    second_id = _create_comment_via_launcher(
        e2e_page,
        anchor_text="导航定位测试",
        comment_text="第二条原始批注",
        expected_summary="2条批注",
    )
    e2e_page.locator(f'#wa-review-shell [data-review-id="{first_id}"]').click()
    _wait_for_review_card_focus(e2e_page, first_id)

    e2e_page.locator(".wa-docx-review-summary").click()
    _wait_until_visible(e2e_page, ".wa-docx-review-nav-menu")
    assert e2e_page.locator(".wa-docx-review-nav-item").count() == 2

    e2e_page.locator(
        f'.wa-docx-review-nav-item[data-review-nav-id="{second_id}"]'
    ).click()
    _wait_for_review_card_focus(e2e_page, second_id)
    e2e_page.wait_for_function(
        """() => {
            const btn = document.querySelector('.wa-docx-review-summary');
            return !!btn && btn.getAttribute('aria-expanded') === 'false';
        }""",
        timeout=REVIEW_TIMEOUT,
    )

    updated_text = "第二条批注已更新"
    e2e_page.locator(
        f'#wa-review-shell [data-review-id="{second_id}"] [data-review-action="edit"]'
    ).click()
    _wait_until_visible(
        e2e_page,
        f'#wa-review-shell [data-review-id="{second_id}"] .koto-docx-comment-edit',
    )
    e2e_page.locator(
        f'#wa-review-shell [data-review-id="{second_id}"] .koto-docx-comment-edit'
    ).fill(updated_text)
    e2e_page.locator(
        f'#wa-review-shell [data-review-id="{second_id}"] [data-review-action="save"]'
    ).click()
    _wait_until_text_includes(
        e2e_page,
        f'#wa-review-shell [data-review-id="{second_id}"] .koto-docx-comment-body',
        updated_text,
    )

    e2e_page.locator(
        f'#wa-review-shell [data-review-id="{second_id}"] [data-review-action="delete"]'
    ).click()
    e2e_page.wait_for_function(
        """(reviewId) => !document.querySelector(
            `#wa-review-shell [data-review-id="${reviewId}"]`
        )""",
        arg=second_id,
        timeout=REVIEW_TIMEOUT,
    )
    _wait_until_text_includes(e2e_page, ".wa-docx-review-summary", "1条批注")

    e2e_page.locator(f'#wa-review-shell [data-review-id="{first_id}"]').hover()
    e2e_page.locator(
        f'#wa-review-shell [data-review-id="{first_id}"] [data-review-action="delete"]'
    ).click()
    e2e_page.wait_for_function(
        """(reviewId) => !document.querySelector(
            `#wa-review-shell [data-review-id="${reviewId}"]`
        )""",
        arg=first_id,
        timeout=REVIEW_TIMEOUT,
    )
    _wait_until_text_includes(e2e_page, ".wa-docx-review-summary", "无批注或建议")
    e2e_page.wait_for_function(
        """() => {
            const btn = document.querySelector('.wa-docx-review-summary');
            return !!btn && btn.disabled === true;
        }""",
        timeout=REVIEW_TIMEOUT,
    )
    assert console_errors == [], f"JS errors: {console_errors}"
