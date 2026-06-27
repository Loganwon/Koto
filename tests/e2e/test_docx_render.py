"""
tests/e2e/test_docx_render.py

Playwright E2E tests for DOCX rendering fidelity in the Koto file assistant.

These tests:
  1. Open the test document via the API
  2. Navigate to the unified Koto app entry /
  3. Inject the HTML into the TipTap editor via JS
  4. Take screenshots to compare with Word visually
  5. Assert DOM-measurable properties (page count, header visibility, etc.)

Run with:
    python -m pytest tests/e2e/test_docx_render.py -v -m e2e --headed

Screenshots are saved to:
    tests/e2e/screenshots/
    (compare these PNGs side-by-side with Word screenshots for visual QA)

Target document: workspace/雷鸟创新-邗投珒创-投资建议书.docx
Word page count: 72 pages
"""

from __future__ import annotations

import io
import os
import time

import pytest
import requests

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DOCX_PATH = os.path.join(_REPO_ROOT, "workspace", "雷鸟创新-邗投珒创-投资建议书.docx")
REAL_OPEN_DOCX_CANDIDATES = [
    os.path.join(_REPO_ROOT, "workspace", "雷鸟创新-投资建议书 (1).docx"),
    DOCX_PATH,
    os.path.join(_REPO_ROOT, "workspace", "2.1书稿翻译2.docx"),
]
SCREENSHOTS_DIR = os.path.join(os.path.dirname(__file__), "screenshots")

WORD_PAGE_COUNT = 72
PAGE_BOUNDARY_SELECTOR = "[data-page-break],[data-soft-page-break]"
# TipTap renders at different heights than Word (different font metrics, line
# heights, table sizing), so use ±30% when comparing to Word's page count.
# The primary assertions use internal consistency (boundary_count == totalPages - 1)
# which is independent of the Word reference.
PAGE_COUNT_LOWER = int(WORD_PAGE_COUNT * 0.70)
PAGE_COUNT_UPPER = int(WORD_PAGE_COUNT * 1.30)

EDITOR_LOAD_TIMEOUT = 30_000  # ms — TipTap needs time to render large documents
ANIMATION_SETTLE_MS = 1_000   # wait after page-boundary markers appear (extra settle)


def _preferred_page_count_docx_path() -> str | None:
    """Return the expected 72-page 雷鸟 document, allowing the local '(1)' copy."""
    preferred_candidates = [
        os.path.join(_REPO_ROOT, "workspace", "雷鸟创新-投资建议书 (1).docx"),
        DOCX_PATH,
    ]
    for path in preferred_candidates:
        if os.path.exists(path):
            return path
    return None


# ---------------------------------------------------------------------------
# Module-level fixture: parse the DOCX once via the API and reuse the HTML
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def docx_html_from_api(e2e_base_url: str) -> str:
    """
    POST the DOCX to /api/v1/workspace/open_file and return the rendered HTML.
    Runs once per test session — shared across all tests in this module.
    """
    source_docx_path = _preferred_page_count_docx_path()
    if not source_docx_path:
        pytest.skip(
            "No 72-page 雷鸟 DOCX found in candidates: "
            f"{[os.path.join(_REPO_ROOT, 'workspace', '雷鸟创新-投资建议书 (1).docx'), DOCX_PATH]!r}"
        )

    with open(source_docx_path, "rb") as fh:
        resp = requests.post(
            f"{e2e_base_url}/api/v1/workspace/open_file",
            files={"file": (os.path.basename(source_docx_path), fh, "application/octet-stream")},
            timeout=120,
        )

    assert resp.status_code == 200, (
        f"open_file API returned {resp.status_code}: {resp.text[:300]}"
    )
    body = resp.json()
    assert body.get("file_type") == "docx", f"Unexpected file_type: {body.get('file_type')}"

    html = body["data"]["html"]
    assert isinstance(html, str) and len(html) > 10_000, (
        f"HTML too short ({len(html)} chars) — parser may have failed"
    )
    return html


@pytest.fixture(scope="module")
def real_open_docx_path() -> str:
    """Return a real multi-page DOCX path for end-to-end file-open coverage."""
    for path in REAL_OPEN_DOCX_CANDIDATES:
        if os.path.exists(path):
            return path
    pytest.skip(f"No real multi-page DOCX found in candidates: {REAL_OPEN_DOCX_CANDIDATES!r}")


@pytest.fixture()
def blank_docx_upload(e2e_base_url: str):
    """
    Upload a minimal DOCX with no header/footer content and keep the HTTP
    session alive so the same tmp file_id can be saved and fetched later.
    """
    docx_module = pytest.importorskip("docx")
    session = requests.Session()

    source_doc = docx_module.Document()
    source_doc.add_paragraph("Body baseline")
    buf = io.BytesIO()
    source_doc.save(buf)
    buf.seek(0)

    try:
        resp = session.post(
            f"{e2e_base_url}/api/v1/workspace/open_file",
            files={"file": ("blank_header_footer.docx", buf, "application/octet-stream")},
            timeout=120,
        )
        assert resp.status_code == 200, (
            f"open_file API returned {resp.status_code}: {resp.text[:300]}"
        )
        body = resp.json()
        assert body.get("file_type") == "docx", f"Unexpected file_type: {body.get('file_type')}"
        yield {
            "session": session,
            "docx_module": docx_module,
            "file_id": body["file_id"],
            "data": body["data"],
        }
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Helper: mount the HTML in the TipTap editor via JavaScript
# ---------------------------------------------------------------------------

def _docx_render_opts(data: dict | None) -> dict:
    data = data if isinstance(data, dict) else {}
    return {
        "pageWidthPx": data.get("page_width_px") or None,
        "pageHeightPx": data.get("page_height_px") or None,
        "marginTopPx": data.get("margin_top_px") or None,
        "marginBottomPx": data.get("margin_bottom_px") or None,
        "marginLeftPx": data.get("margin_left_px") or None,
        "marginRightPx": data.get("margin_right_px") or None,
        "headerHtml": data.get("header_html") or "",
        "footerHtml": data.get("footer_html") or "",
        "sections": data.get("sections") or [],
    }


def _mount_docx(page, html: str, base_url: str, opts: dict | None = None) -> None:
    """
    Navigate to the unified Koto app entry (which loads workspace.css and the TipTap
    bundle), then inject the DOCX HTML into TipTap via JS.

    workspace.css scopes the TipTap styles to ``#wa-docx-editor .ProseMirror``
    (padding, width, line-height, etc.) so we MUST use a page that loads that
    stylesheet — ``about:blank`` cannot be used.

    Implementation notes
    --------------------
    * We create a FRESH ``#wa-docx-editor`` container at ``document.body`` level
      and give it inline ``display:flex`` so no CSS specificity rule can hide it.
    * We add ``class="active"`` as belt-and-suspenders (workspace.css rule).
    * The workspace runtime can call ``.classList.remove('active')`` via
      ``destroy()``, but inline-style ``display:flex`` always wins the cascade.
    * We wait explicitly for page-boundary markers to appear before returning.
    """
    page.goto(f"{base_url}/", timeout=15_000, wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle", timeout=15_000)

    # Ensure the TipTap bundle is available for the workspace DOCX runtime.
    page.wait_for_function(
        "() => typeof window.KotoDocxEditorLib !== 'undefined' || "
        "document.querySelector('#wa-docx-editor') !== null",
        timeout=10_000,
    )

    page.evaluate("""
        async ({ html, opts }) => {
            // ── 1. Load TipTap bundle if not yet present ──────────────────
            if (!window.KotoDocxEditorLib) {
                await new Promise((resolve, reject) => {
                    const s = document.createElement('script');
                    s.src = '/static/js/tiptap-docx-bundle.js';
                    s.onload = resolve;
                    s.onerror = reject;
                    document.head.appendChild(s);
                });
            }

            // ── 2. Create a fresh, always-visible container ────────────────
            // Remove any pre-existing #wa-docx-editor (original or from a
            // previous _mount_docx call in the same browser page).
            const old = document.getElementById('wa-docx-editor');
            if (old) old.parentNode.removeChild(old);

            const container = document.createElement('div');
            container.id = 'wa-docx-editor';
            container.classList.add('active');
            // Inline style trumps ALL CSS selector rules (highest cascade priority).
            // Even if the workspace runtime removes the .active class, display:flex
            // in the inline style keeps the element visible.
            container.style.cssText =
                'position:fixed;inset:0;z-index:9999;' +
                'display:flex;flex-direction:column;' +
                'background:#e5e5e5;overflow-y:auto;';
            document.body.appendChild(container);

            // ── 3. Render ──────────────────────────────────────────────────
            window._testEditor = new window.KotoDocxEditorLib.KotoTipTapEditor();
            window._testEditor.render(html, opts || undefined);
        }
    """, {"html": html, "opts": opts})

    # Wait for ProseMirror to be visible (TipTap creates it during render)
    page.wait_for_selector('#wa-docx-editor .ProseMirror', state='visible', timeout=EDITOR_LOAD_TIMEOUT)

    # Wait for page-boundary markers to populate (debounced after first DOM layout)
    try:
        page.wait_for_function(
            "() => document.querySelectorAll('[data-page-break],[data-soft-page-break]').length > 0",
            timeout=15_000,
        )
    except Exception:
        pass  # not all documents produce page breaks — tested in a dedicated test

    # Extra settle for ResizeObserver and scroll tracking to stabilise
    time.sleep(ANIMATION_SETTLE_MS / 1000)


def _open_docx_via_file_input(page, base_url: str, docx_path: str) -> None:
    """Open a DOCX through the real unified workspace file input flow."""
    page.goto(f"{base_url}/", timeout=15_000, wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle", timeout=15_000)
    page.locator("#wa-file-input").set_input_files(docx_path)
    page.wait_for_selector("#wa-docx-editor .ProseMirror", state="visible", timeout=60_000)
    page.wait_for_function(
        "() => document.querySelectorAll('.koto-page-break').length > 0",
        timeout=30_000,
    )
    time.sleep(ANIMATION_SETTLE_MS / 1000)


def _edit_header_footer_slot(page, selector: str, text: str) -> None:
    overlay = _open_header_footer_overlay(page, selector)
    page.keyboard.press("Control+A")
    page.keyboard.type(text)
    _commit_header_footer_overlay(page, selector, text)


def _open_header_footer_overlay(page, selector: str):
    slot = page.locator(selector)
    assert slot.count() > 0, f"Missing header/footer slot: {selector}"
    slot.scroll_into_view_if_needed(timeout=5_000)
    slot.dblclick()

    overlay = page.locator(f"{selector} .koto-hdrftr-overlay")
    overlay.wait_for(state="visible", timeout=5_000)
    overlay.click()
    return overlay


def _commit_header_footer_overlay(page, selector: str, text: str | None = None) -> None:
    page.locator("#wa-docx-page-indicator").click(force=True)
    page.wait_for_function(
        """(args) => {
            const slot = document.querySelector(args.selector);
            const overlay = slot ? slot.querySelector('.koto-hdrftr-overlay') : null;
            return !overlay && slot && (!args.text || slot.textContent.includes(args.text));
        }""",
        arg={"selector": selector, "text": text},
        timeout=5_000,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.e2e
class TestDocxEditorMount:
    """Verify the editor mounts and displays real content."""

    def test_prosemirror_is_visible(self, e2e_page, e2e_base_url, docx_html_from_api):
        """TipTap editor (.ProseMirror) must be visible after render()."""
        _mount_docx(e2e_page, docx_html_from_api, e2e_base_url)
        el = e2e_page.locator('#wa-docx-editor .ProseMirror')
        assert el.count() > 0, "No #wa-docx-editor .ProseMirror element found"

        # Use JS computed-style check instead of Playwright's to_be_visible().
        # Playwright's visibility model can have false-negatives when the element
        # is inside an overflow:visible chain that is also a flex container.
        is_visible = e2e_page.evaluate("""() => {
            const pm = document.querySelector('#wa-docx-editor .ProseMirror');
            if (!pm) return false;
            const rect = pm.getBoundingClientRect();
            if (rect.width <= 0 || rect.height <= 0) return false;
            const cs = window.getComputedStyle(pm);
            return cs.display !== 'none'
                && cs.visibility !== 'hidden'
                && parseFloat(cs.opacity) >= 0.1;
        }""")
        assert is_visible, (
            ".ProseMirror exists in DOM but its computed style marks it hidden "
            "(display:none / visibility:hidden / zero-sized bounding box)"
        )

    def test_editor_has_text_content(self, e2e_page, e2e_base_url, docx_html_from_api):
        """Editor must contain visible text (not just empty paragraphs)."""
        _mount_docx(e2e_page, docx_html_from_api, e2e_base_url)
        text = e2e_page.locator('.ProseMirror').inner_text()
        assert len(text.strip()) > 200, (
            f"Editor text content too short ({len(text.strip())} chars) — "
            "document may not have rendered"
        )


@pytest.mark.e2e
class TestHeaderFooter:
    """Header and footer CSS class visibility in the rendered DOM."""

    def test_header_element_in_dom(self, e2e_page, e2e_base_url, docx_html_from_api):
        """
        After the DocxParagraph className-attribute fix, <p class="koto-header">
        elements must survive TipTap's parse cycle and appear in the DOM.
        """
        _mount_docx(e2e_page, docx_html_from_api, e2e_base_url)
        count = e2e_page.locator('.koto-header').count()
        assert count > 0, (
            "No .koto-header elements found in editor DOM.  "
            "The TipTap className attribute fix may not have been built into the bundle, "
            "or the parser is not emitting koto-header classes."
        )

    def test_footer_element_in_dom(self, e2e_page, e2e_base_url, docx_html_from_api):
        """Footer paragraphs must have the koto-footer class in DOM.
        Skipped when the test doc has no footer section (same as backend test)."""
        _mount_docx(e2e_page, docx_html_from_api, e2e_base_url)
        count = e2e_page.locator('.koto-footer').count()
        if count == 0:
            pytest.skip("Document has no footer section — koto-footer class not present")
        assert count > 0

    def test_header_is_not_display_none(self, e2e_page, e2e_base_url, docx_html_from_api):
        """First koto-header element must not be hidden."""
        _mount_docx(e2e_page, docx_html_from_api, e2e_base_url)
        if e2e_page.locator('.koto-header').count() == 0:
            pytest.skip("No .koto-header — covered by test_header_element_in_dom")
        # Use computed style so the check is robust against Playwright's
        # is_visible() stricter bounding-box requirement.
        hidden = e2e_page.evaluate("""() => {
            const el = document.querySelector('.koto-header');
            if (!el) return null;
            const s = window.getComputedStyle(el);
            return s.display === 'none' || s.visibility === 'hidden' || s.opacity === '0';
        }""")
        assert hidden is False, (
            ".koto-header element has display:none / visibility:hidden / opacity:0"
        )


@pytest.mark.e2e
class TestHeaderFooterEditing:
    """Blank header/footer shells must be editable and survive a save round-trip."""

    def test_blank_header_footer_can_be_saved_and_reopened(
        self,
        e2e_page,
        e2e_base_url,
        blank_docx_upload,
        console_errors,
    ):
        upload = blank_docx_upload
        header_text = "Playwright Header"
        footer_text = "Playwright Footer"

        _mount_docx(
            e2e_page,
            upload["data"]["html"],
            e2e_base_url,
            _docx_render_opts(upload["data"]),
        )

        _edit_header_footer_slot(e2e_page, ".koto-page-header-first", header_text)
        _edit_header_footer_slot(e2e_page, ".koto-page-footer-last", footer_text)

        payload = e2e_page.evaluate("() => window._testEditor.getDocxSavePayload()")
        assert header_text in (payload.get("header_html") or "")
        assert footer_text in (payload.get("footer_html") or "")

        save_resp = upload["session"].post(
            f"{e2e_base_url}/api/v1/workspace/auto_save",
            json={
                "file_type": "docx",
                "file_id": upload["file_id"],
                "explicit": True,
                "data": payload,
            },
            timeout=120,
        )
        assert save_resp.status_code == 200, save_resp.text[:300]

        raw_resp = upload["session"].get(
            f"{e2e_base_url}/api/v1/workspace/raw/{upload['file_id']}",
            timeout=120,
        )
        assert raw_resp.status_code == 200, raw_resp.text[:300]

        saved_doc = upload["docx_module"].Document(io.BytesIO(raw_resp.content))
        saved_header = "\n".join(p.text for p in saved_doc.sections[0].header.paragraphs)
        saved_footer = "\n".join(p.text for p in saved_doc.sections[0].footer.paragraphs)
        assert header_text in saved_header
        assert footer_text in saved_footer

        reopen_resp = upload["session"].post(
            f"{e2e_base_url}/api/v1/workspace/open_file",
            files={"file": ("roundtrip_header_footer.docx", io.BytesIO(raw_resp.content), "application/octet-stream")},
            timeout=120,
        )
        assert reopen_resp.status_code == 200, reopen_resp.text[:300]
        reopened = reopen_resp.json()["data"]

        _mount_docx(
            e2e_page,
            reopened["html"],
            e2e_base_url,
            _docx_render_opts(reopened),
        )

        assert header_text in e2e_page.locator(".koto-page-header-first").inner_text()
        assert footer_text in e2e_page.locator(".koto-page-footer-last").inner_text()
        assert console_errors == [], f"JS errors: {console_errors}"

    def test_header_footer_toolbar_alignment_updates_overlay_content(
        self,
        e2e_page,
        e2e_base_url,
        blank_docx_upload,
        console_errors,
    ):
        upload = blank_docx_upload
        header_text = "Centered Header"
        footer_text = "Right Footer"

        _mount_docx(
            e2e_page,
            upload["data"]["html"],
            e2e_base_url,
            _docx_render_opts(upload["data"]),
        )

        _open_header_footer_overlay(e2e_page, ".koto-page-header-first")
        e2e_page.keyboard.press("Control+A")
        e2e_page.keyboard.type(header_text)
        e2e_page.keyboard.press("Control+A")
        e2e_page.locator('#koto-tt-toolbar [data-cmd="setTextAlignCenter"]').dispatch_event("click")
        _commit_header_footer_overlay(e2e_page, ".koto-page-header-first", header_text)

        _open_header_footer_overlay(e2e_page, ".koto-page-footer-last")
        e2e_page.keyboard.press("Control+A")
        e2e_page.keyboard.type(footer_text)
        e2e_page.keyboard.press("Control+A")
        e2e_page.locator('#koto-tt-toolbar [data-cmd="setTextAlignRight"]').dispatch_event("click")
        _commit_header_footer_overlay(e2e_page, ".koto-page-footer-last", footer_text)

        header_align = e2e_page.evaluate(
            """() => {
                const node = document.querySelector('.koto-page-header-first p');
                return node ? window.getComputedStyle(node).textAlign : null;
            }"""
        )
        footer_align = e2e_page.evaluate(
            """() => {
                const node = document.querySelector('.koto-page-footer-last p');
                return node ? window.getComputedStyle(node).textAlign : null;
            }"""
        )
        assert header_align == "center"
        assert footer_align == "right"

        payload = e2e_page.evaluate("() => window._testEditor.getDocxSavePayload()")
        assert "text-align: center" in (payload.get("header_html") or "")
        assert "text-align: right" in (payload.get("footer_html") or "")
        assert console_errors == [], f"JS errors: {console_errors}"

    def test_first_page_header_markers_show_and_overlay_has_no_separator_line(
        self,
        e2e_page,
        e2e_base_url,
        blank_docx_upload,
        console_errors,
    ):
        upload = blank_docx_upload
        opts = _docx_render_opts(upload["data"])
        opts["headerHtml"] = '<p class="koto-header">Header Probe</p>'

        _mount_docx(
            e2e_page,
            upload["data"]["html"],
            e2e_base_url,
            opts,
        )

        shell_metrics = e2e_page.evaluate(
            """() => {
                const header = document.querySelector('.koto-page-header-first');
                const legacyHeader = document.querySelector('.koto-page-header-first .koto-header');
                const leftStyle = header ? window.getComputedStyle(header, '::before') : null;
                const rightStyle = header ? window.getComputedStyle(header, '::after') : null;
                const legacyStyle = legacyHeader ? window.getComputedStyle(legacyHeader) : null;
                return {
                    leftDisplay: leftStyle ? leftStyle.display : null,
                    rightDisplay: rightStyle ? rightStyle.display : null,
                    leftBottom: leftStyle ? leftStyle.bottom : null,
                    rightBottom: rightStyle ? rightStyle.bottom : null,
                    leftBorderBottomStyle: leftStyle ? leftStyle.borderBottomStyle : null,
                    rightBorderBottomStyle: rightStyle ? rightStyle.borderBottomStyle : null,
                    headerBackground: header ? window.getComputedStyle(header).backgroundColor : null,
                    legacyExists: !!legacyHeader,
                    legacyBorderBottomStyle: legacyStyle ? legacyStyle.borderBottomStyle : null,
                    legacyBorderBottomWidth: legacyStyle ? legacyStyle.borderBottomWidth : null,
                };
            }"""
        )
        assert shell_metrics["leftDisplay"] == "block"
        assert shell_metrics["rightDisplay"] == "block"
        assert shell_metrics["leftBottom"] == "12px"
        assert shell_metrics["rightBottom"] == "12px"
        assert shell_metrics["leftBorderBottomStyle"] == "solid"
        assert shell_metrics["rightBorderBottomStyle"] == "solid"
        assert shell_metrics["headerBackground"] == "rgb(255, 255, 255)"
        assert shell_metrics["legacyExists"] is True
        assert shell_metrics["legacyBorderBottomStyle"] == "none"
        assert shell_metrics["legacyBorderBottomWidth"] == "0px"

        _open_header_footer_overlay(e2e_page, ".koto-page-header-first")
        overlay_metrics = e2e_page.evaluate(
            """() => {
                const overlay = document.querySelector('.koto-page-header-first .koto-hdrftr-overlay');
                const legacyHeader = document.querySelector('.koto-page-header-first .koto-hdrftr-overlay .koto-header');
                const style = overlay ? window.getComputedStyle(overlay) : null;
                const legacyStyle = legacyHeader ? window.getComputedStyle(legacyHeader) : null;
                return {
                    outlineStyle: style ? style.outlineStyle : null,
                    outlineWidth: style ? style.outlineWidth : null,
                    legacyExists: !!legacyHeader,
                    legacyBorderBottomStyle: legacyStyle ? legacyStyle.borderBottomStyle : null,
                    legacyBorderBottomWidth: legacyStyle ? legacyStyle.borderBottomWidth : null,
                };
            }"""
        )
        assert overlay_metrics["outlineStyle"] == "none"
        assert overlay_metrics["outlineWidth"] == "0px"
        assert overlay_metrics["legacyExists"] is True
        assert overlay_metrics["legacyBorderBottomStyle"] == "none"
        assert overlay_metrics["legacyBorderBottomWidth"] == "0px"

        _commit_header_footer_overlay(e2e_page, ".koto-page-header-first")
        assert console_errors == [], f"JS errors: {console_errors}"

    def test_page_break_footer_overlay_opens_bottom_aligned_and_markers_track_content_edge(
        self,
        e2e_page,
        e2e_base_url,
        real_open_docx_path,
        console_errors,
    ):
        _open_docx_via_file_input(e2e_page, e2e_base_url, real_open_docx_path)

        marker_metrics = e2e_page.evaluate(
            """() => {
                const endZone = document.querySelector('.koto-pb-end');
                const startZone = document.querySelector('.koto-pb-start');
                const endStyle = endZone ? window.getComputedStyle(endZone, '::before') : null;
                const startStyle = startZone ? window.getComputedStyle(startZone, '::before') : null;
                return {
                    endMarkerTop: endStyle ? endStyle.top : null,
                    endMarkerBottom: endStyle ? endStyle.bottom : null,
                    startMarkerTop: startStyle ? startStyle.top : null,
                    startMarkerBottom: startStyle ? startStyle.bottom : null,
                };
            }"""
        )
        assert marker_metrics["endMarkerTop"] == "12px"
        assert marker_metrics["endMarkerBottom"] != "12px"
        assert marker_metrics["startMarkerBottom"] == "12px"
        assert marker_metrics["startMarkerTop"] != "12px"

        footer = e2e_page.locator('.koto-pb-footer').first
        footer.scroll_into_view_if_needed(timeout=5_000)
        footer.dblclick()

        overlay = e2e_page.locator('.koto-pb-footer .koto-hdrftr-overlay').first
        overlay.wait_for(state="visible", timeout=5_000)
        overlay.click()

        footer_metrics = e2e_page.evaluate(
            """() => {
                const overlay = document.querySelector('.koto-pb-footer .koto-hdrftr-overlay');
                const firstBlock = overlay ? overlay.firstElementChild : null;
                const sel = window.getSelection ? window.getSelection() : null;
                const overlayRect = overlay ? overlay.getBoundingClientRect() : null;
                const blockRect = firstBlock ? firstBlock.getBoundingClientRect() : null;
                return {
                    overlayHtml: overlay ? overlay.innerHTML : null,
                    overlayJustify: overlay ? window.getComputedStyle(overlay).justifyContent : null,
                    selectionAnchorNode: sel && sel.anchorNode ? sel.anchorNode.nodeName : null,
                    firstBlockHeight: blockRect ? blockRect.height : null,
                    bottomGap: overlayRect && blockRect ? (overlayRect.bottom - blockRect.bottom) : null,
                };
            }"""
        )
        assert footer_metrics["overlayJustify"] == "flex-end"
        assert footer_metrics["selectionAnchorNode"] != "DIV"
        assert (footer_metrics["overlayHtml"] or "").startswith("<p")
        assert footer_metrics["firstBlockHeight"] is not None and footer_metrics["firstBlockHeight"] > 0
        assert footer_metrics["bottomGap"] is not None and footer_metrics["bottomGap"] <= 1
        assert console_errors == [], f"JS errors: {console_errors}"

    def test_toc_entries_render_with_dot_leader_width_and_right_aligned_page_number(
        self,
        e2e_page,
        e2e_base_url,
        real_open_docx_path,
        console_errors,
    ):
        _open_docx_via_file_input(e2e_page, e2e_base_url, real_open_docx_path)
        e2e_page.wait_for_function(
            "() => document.querySelectorAll('tr.koto-table-page-break-row .koto-page-break').length > 0",
            timeout=30_000,
        )
        e2e_page.wait_for_function(
            """() => {
                const pm = document.querySelector('#wa-docx-editor .ProseMirror');
                const rows = Array.from(document.querySelectorAll('tr.koto-table-page-break-row')).slice(0, 5);
                if (!pm || rows.length === 0) return false;
                const pmRect = pm.getBoundingClientRect();
                return rows.every((row) => {
                    const widget = row.querySelector('.koto-page-break');
                    if (!widget) return false;
                    const widgetRect = widget.getBoundingClientRect();
                    return Math.abs(widgetRect.left - pmRect.left) < 4
                        && Math.abs(widgetRect.right - pmRect.right) < 4;
                });
            }""",
            timeout=30_000,
        )

        metrics = e2e_page.evaluate(
            """() => {
                const para = document.querySelector('.koto-toc-1, .koto-toc-2');
                const link = para ? para.querySelector('a') : null;
                const tab = para ? para.querySelector('.koto-toc-tab') : null;
                const walker = link ? document.createTreeWalker(link, NodeFilter.SHOW_TEXT) : null;
                let pageNode = null;
                if (walker) {
                    while (walker.nextNode()) {
                        const value = walker.currentNode.nodeValue || '';
                        if (value.trim()) {
                            pageNode = walker.currentNode;
                        }
                    }
                }
                const pageRange = pageNode
                    ? (() => {
                        const range = document.createRange();
                        range.selectNodeContents(pageNode);
                        return range.getBoundingClientRect();
                    })()
                    : null;
                const paraRect = para ? para.getBoundingClientRect() : null;
                const linkRect = link ? link.getBoundingClientRect() : null;
                const tabRect = tab ? tab.getBoundingClientRect() : null;
                return {
                    paraExists: !!para,
                    linkExists: !!link,
                    pageText: pageNode ? pageNode.nodeValue : null,
                    paraRect: paraRect ? { left: paraRect.left, right: paraRect.right, width: paraRect.width } : null,
                    linkRect: linkRect ? { left: linkRect.left, right: linkRect.right, width: linkRect.width } : null,
                    tabRect: tabRect ? { left: tabRect.left, right: tabRect.right, width: tabRect.width } : null,
                    pageRect: pageRange ? { left: pageRange.left, right: pageRange.right, width: pageRange.width } : null,
                    fontSize: para ? window.getComputedStyle(para).fontSize : null,
                    fontWeight: para ? window.getComputedStyle(para).fontWeight : null,
                };
            }"""
        )
        assert metrics["paraExists"] is True
        assert metrics["linkExists"] is True
        assert (metrics["pageText"] or "").strip().isdigit()
        assert metrics["tabRect"] is not None and metrics["tabRect"]["width"] > 40
        assert metrics["pageRect"] is not None
        assert metrics["linkRect"]["right"] - metrics["pageRect"]["right"] < 24
        assert metrics["fontSize"] == "16px"
        assert metrics["fontWeight"] == "400"
        assert console_errors == [], f"JS errors: {console_errors}"

    def test_table_page_break_row_tracks_page_left_edge_for_split_tables(
        self,
        e2e_page,
        e2e_base_url,
        real_open_docx_path,
        console_errors,
    ):
        _open_docx_via_file_input(e2e_page, e2e_base_url, real_open_docx_path)

        metrics = e2e_page.evaluate(
            """() => {
                const pm = document.querySelector('#wa-docx-editor .ProseMirror');
                const pmRect = pm ? pm.getBoundingClientRect() : null;
                const rows = Array.from(document.querySelectorAll('tr.koto-table-page-break-row')).slice(0, 5);
                return {
                    pmRect: pmRect ? { left: pmRect.left, right: pmRect.right, width: pmRect.width } : null,
                    items: rows.map((row) => {
                        const widget = row.querySelector('.koto-page-break');
                        const table = row.closest('table');
                        const widgetRect = widget ? widget.getBoundingClientRect() : null;
                        const tableRect = table ? table.getBoundingClientRect() : null;
                        return {
                            widgetRect: widgetRect ? { left: widgetRect.left, right: widgetRect.right, width: widgetRect.width } : null,
                            tableRect: tableRect ? { left: tableRect.left, right: tableRect.right, width: tableRect.width } : null,
                        };
                    }),
                };
            }"""
        )
        assert metrics["pmRect"] is not None
        assert metrics["items"], "Expected at least one row-level table page break in the real DOCX"
        assert any(
            item["tableRect"] and item["tableRect"]["left"] > metrics["pmRect"]["left"] + 40
            for item in metrics["items"]
        )
        for item in metrics["items"]:
            assert item["widgetRect"] is not None
            assert item["tableRect"] is not None
            assert abs(item["widgetRect"]["left"] - metrics["pmRect"]["left"]) < 4
            assert abs(item["widgetRect"]["right"] - metrics["pmRect"]["right"]) < 4
        assert console_errors == [], f"JS errors: {console_errors}"

    def test_table_page_break_rows_only_insert_at_safe_rowspan_boundaries(
        self,
        e2e_page,
        e2e_base_url,
        real_open_docx_path,
        console_errors,
    ):
        _open_docx_via_file_input(e2e_page, e2e_base_url, real_open_docx_path)

        metrics = e2e_page.evaluate(
            """() => {
                const tables = Array.from(document.querySelectorAll('#wa-docx-editor .ProseMirror table'));
                const consumeRowspans = (activeRowspans, row, columnCount) => {
                    const width = Math.max(1, columnCount || 1);
                    const current = Array.from({ length: width }, (_, idx) => Math.max(0, Number(activeRowspans[idx] || 0)));
                    const next = current.map((span) => Math.max(0, span - 1));
                    let colIdx = 0;

                    Array.from(row.cells || []).forEach((cell) => {
                        while (colIdx < width && current[colIdx] > 0) colIdx += 1;
                        const colspan = Math.max(1, Number(cell.colSpan) || 1);
                        const rowspan = Math.max(1, Number(cell.rowSpan) || 1);
                        if (rowspan > 1) {
                            for (let offset = 0; offset < colspan && colIdx + offset < width; offset += 1) {
                                next[colIdx + offset] = Math.max(next[colIdx + offset], rowspan - 1);
                            }
                        }
                        colIdx += colspan;
                    });

                    return next;
                };

                const items = [];
                tables.forEach((table, tableIndex) => {
                    const rows = Array.from(table.rows || []);
                    const columnCount = Math.max(
                        1,
                        ...rows.map((row) => Array.from(row.cells || []).reduce(
                            (sum, cell) => sum + Math.max(1, Number(cell.colSpan) || 1),
                            0,
                        )),
                    );
                    let activeRowspans = Array(columnCount).fill(0);

                    rows.forEach((row, rowIndex) => {
                        if (row.classList.contains('koto-table-page-break-row')) {
                            items.push({
                                tableIndex,
                                rowIndex,
                                carriedCols: activeRowspans.filter((span) => span > 0).length,
                            });
                            return;
                        }
                        activeRowspans = consumeRowspans(activeRowspans, row, columnCount);
                    });
                });

                return { items };
            }"""
        )

        assert metrics["items"], "Expected at least one row-level table page break in the real DOCX"
        assert all(item["carriedCols"] == 0 for item in metrics["items"]), metrics["items"][:10]
        assert console_errors == [], f"JS errors: {console_errors}"

    def test_real_docx_outline_recovers_full_navigation_tree_for_chaptered_doc(
        self,
        e2e_page,
        e2e_base_url,
        real_open_docx_path,
        console_errors,
    ):
        _open_docx_via_file_input(e2e_page, e2e_base_url, real_open_docx_path)
        e2e_page.wait_for_function(
            "() => document.querySelectorAll('.wa-outline-item').length >= 20",
            timeout=30_000,
        )

        metrics = e2e_page.evaluate(
            """() => {
                const outlineItems = Array.from(document.querySelectorAll('.wa-outline-item'));
                const visibleItems = outlineItems.filter((el) => el.offsetParent !== null);
                return {
                    outlineCount: outlineItems.length,
                    visibleCount: visibleItems.length,
                    texts: outlineItems.map((el) => (el.querySelector('.wa-outline-text')?.textContent || '').trim()),
                };
            }"""
        )

        assert metrics["outlineCount"] >= 20, metrics
        assert metrics["visibleCount"] >= 10, metrics
        assert "第二章 行业分析" in metrics["texts"], metrics["texts"][:20]
        assert "四、公司历次融资情况" in metrics["texts"], metrics["texts"][:20]
        assert console_errors == [], f"JS errors: {console_errors}"


@pytest.mark.e2e
class TestPageCount:
    """Page count accuracy — must be close to Word's 72 pages."""

    def test_page_break_boundaries_exist(self, e2e_page, e2e_base_url, docx_html_from_api):
        """At least one real page-boundary marker must exist after editor setup."""
        _mount_docx(e2e_page, docx_html_from_api, e2e_base_url)
        count = e2e_page.locator(PAGE_BOUNDARY_SELECTOR).count()
        assert count > 0, "No page-boundary marker found — pagination markers may not have rendered"

    def test_page_break_boundary_count(self, e2e_page, e2e_base_url, docx_html_from_api):
        """
        Number of real page-boundary markers must equal (totalPages - 1) exactly,
        and totalPages must be within ±30% of Word's page count.

        Also validates internal consistency: boundary_count == totalPages − 1
        (the number of separators between pages equals pages minus one).
        """
        _mount_docx(e2e_page, docx_html_from_api, e2e_base_url)
        # Give the debounced AutoPageBreakPlugin measurement another chance to finish.
        try:
            e2e_page.wait_for_function(
                "() => document.querySelectorAll('[data-page-break],[data-soft-page-break]').length > 0",
                timeout=20_000,
            )
        except Exception:
            pass
        boundary_count = e2e_page.evaluate(
            "() => window._testEditor && typeof window._testEditor._getDocxPageBreakBoundaries === 'function'"
            " ? window._testEditor._getDocxPageBreakBoundaries().length"
            " : document.querySelectorAll('[data-page-break],[data-soft-page-break]').length"
        )
        # _totalPages is set by the pagination plugin on the editor instance.
        total_pages = e2e_page.evaluate(
            "() => window._testEditor ? window._testEditor._totalPages : 0"
        )
        # Internal consistency: unique page boundaries == pages - 1
        assert boundary_count == total_pages - 1, (
            f"Page-boundary count ({boundary_count}) != _totalPages ({total_pages}) - 1. "
            "Page break logic is inconsistent."
        )
        # Sanity range: TipTap does not always match Word exactly because line
        # heights / table rendering differ, so we use a generous ±30% band.
        expected_lower = int(WORD_PAGE_COUNT * 0.70)
        expected_upper = int(WORD_PAGE_COUNT * 1.30)
        assert expected_lower <= total_pages <= expected_upper, (
            f"TipTap renders {total_pages} pages; "
            f"expected {expected_lower}–{expected_upper} (Word: {WORD_PAGE_COUNT}, ±30%)."
        )

    def test_page_indicator_text(self, e2e_page, e2e_base_url, docx_html_from_api):
        """
        #wa-pi-text (page indicator) must show a total page count that matches
        ``_testEditor._totalPages`` (internal consistency).
        """
        _mount_docx(e2e_page, docx_html_from_api, e2e_base_url)
        indicator = e2e_page.locator('#wa-pi-text')
        if indicator.count() == 0:
            pytest.skip("#wa-pi-text not found — indicator may not be mounted in test context")
        # Wait for the indicator to reflect the real page count (past "共 1 页")
        try:
            e2e_page.wait_for_function(
                "() => { const el = document.getElementById('wa-pi-text'); "
                "return el && /共\\s*[2-9]\\d/.test(el.textContent); }",
                timeout=20_000,
            )
        except Exception:
            pass
        text = indicator.inner_text()
        import re
        m = re.search(r'共\s*(\d+)\s*页', text)
        assert m, f"Cannot parse page indicator text: {text!r}"
        shown_total = int(m.group(1))

        # Compare against the JS _totalPages property (internal consistency)
        total_pages = e2e_page.evaluate(
            "() => window._testEditor ? window._testEditor._totalPages : 0"
        )
        # The indicator must match the editor's own _totalPages
        assert shown_total == total_pages, (
            f"Page indicator shows {shown_total} but _totalPages={total_pages}. "
            f"Indicator text: {text!r}"
        )
        # Also check it's in a reasonable range
        expected_lower = int(WORD_PAGE_COUNT * 0.70)
        expected_upper = int(WORD_PAGE_COUNT * 1.30)
        assert expected_lower <= shown_total <= expected_upper, (
            f"Page indicator shows {shown_total} total pages; "
            f"expected {expected_lower}–{expected_upper} (Word: {WORD_PAGE_COUNT}, ±30%). "
            f"Indicator text: {text!r}"
        )


@pytest.mark.e2e
class TestImageSizing:
    """Images must display at their natural proportions."""

    def test_images_not_stretched(self, e2e_page, e2e_base_url, docx_html_from_api):
        """
        No image should be wider than 110% of its natural width.
        CSS 'height:auto' was removed; inline style dimensions should take effect.
        """
        _mount_docx(e2e_page, docx_html_from_api, e2e_base_url)
        stretched = e2e_page.evaluate("""
            () => {
                const imgs = [...document.querySelectorAll('.ProseMirror img')];
                return imgs.filter(img => {
                    if (!img.naturalWidth || img.naturalWidth === 0) return false;
                    return img.offsetWidth > img.naturalWidth * 1.1;
                }).length;
            }
        """)
        total_imgs = e2e_page.locator('.ProseMirror img').count()
        if total_imgs == 0:
            pytest.skip("No images found in editor")
        assert stretched == 0, (
            f"{stretched}/{total_imgs} images are stretched beyond their natural width.  "
            "CSS height:auto may still be overriding inline image dimensions."
        )


# ---------------------------------------------------------------------------
# Screenshot tests — for manual visual comparison with Word
# ---------------------------------------------------------------------------

@pytest.mark.e2e
class TestScreenshots:
    """
    These tests produce PNG screenshots for side-by-side comparison with Word.
    They do not assert pass/fail on visual content — the human reviewer checks them.

    Output directory: tests/e2e/screenshots/
    """

    def _ensure_dir(self):
        os.makedirs(SCREENSHOTS_DIR, exist_ok=True)

    def test_screenshot_page1_top(self, e2e_page, e2e_base_url, docx_html_from_api):
        """
        Screenshot of the top of page 1 (cover page / title table).
        Compare with Word's first page.
        """
        self._ensure_dir()
        _mount_docx(e2e_page, docx_html_from_api, e2e_base_url)
        # Scroll to the very top
        e2e_page.evaluate("() => { const el = document.getElementById('wa-editor-content'); if(el) el.scrollTop = 0; }")
        time.sleep(0.3)
        e2e_page.screenshot(path=os.path.join(SCREENSHOTS_DIR, "koto_page1_top.png"))
        assert os.path.exists(os.path.join(SCREENSHOTS_DIR, "koto_page1_top.png"))

    def test_screenshot_first_page_break(self, e2e_page, e2e_base_url, docx_html_from_api):
        """
        Screenshot around the first page break — should show the Word-style
        gray gap between two white page surfaces with drop shadows.
        Compare with Word's page boundary appearance.
        """
        self._ensure_dir()
        _mount_docx(e2e_page, docx_html_from_api, e2e_base_url)

        if e2e_page.locator(PAGE_BOUNDARY_SELECTOR).count() == 0:
            pytest.skip("No page-boundary markers rendered")

        # Page-boundary markers are in-flow blocks, so we can scroll the first one directly.
        e2e_page.evaluate("""() => {
            const boundary = document.querySelector('[data-page-break],[data-soft-page-break]');
            const container = document.getElementById('wa-editor-content') || document.getElementById('wa-docx-editor');
            if (!boundary || !container) return;
            const lineRect = boundary.getBoundingClientRect();
            const containerRect = container.getBoundingClientRect();
            // Center the first boundary in the viewport.
            const target = (lineRect.top - containerRect.top) + container.scrollTop
                           - (container.clientHeight / 2);
            container.scrollTo({ top: target, behavior: 'instant' });
        }""")
        time.sleep(0.3)
        e2e_page.screenshot(path=os.path.join(SCREENSHOTS_DIR, "koto_first_page_break.png"))
        assert os.path.exists(os.path.join(SCREENSHOTS_DIR, "koto_first_page_break.png"))

    def test_screenshot_header_area(self, e2e_page, e2e_base_url, docx_html_from_api):
        """
        Screenshot of the first .koto-header element.
        Should show the header text styled as it is in Word.
        """
        self._ensure_dir()
        _mount_docx(e2e_page, docx_html_from_api, e2e_base_url)
        if e2e_page.locator('.koto-header').count() == 0:
            pytest.skip("No .koto-header elements")
        # Scroll the header element into view via JS (may be outside initial viewport)
        e2e_page.evaluate("""() => {
            const el = document.querySelector('.koto-header');
            const container = document.getElementById('wa-docx-editor');
            if (!el || !container) return;
            const rect = el.getBoundingClientRect();
            const cRect = container.getBoundingClientRect();
            const target = (rect.top - cRect.top) + container.scrollTop
                           - (container.clientHeight / 2);
            container.scrollTo({ top: Math.max(0, target), behavior: 'instant' });
        }""")
        time.sleep(0.3)
        e2e_page.screenshot(path=os.path.join(SCREENSHOTS_DIR, "koto_header_area.png"))
        assert os.path.exists(os.path.join(SCREENSHOTS_DIR, "koto_header_area.png"))

    def test_screenshot_full_page2(self, e2e_page, e2e_base_url, docx_html_from_api):
        """
        Screenshot of page 2 content area (scroll past first page break).
        Compare with Word page 2 to check table formatting, fonts, spacing.
        """
        self._ensure_dir()
        _mount_docx(e2e_page, docx_html_from_api, e2e_base_url)
        # Scroll past the first page break — 1056px into the document
        e2e_page.evaluate("""
            () => {
                const el = document.getElementById('wa-editor-content');
                if (el) el.scrollTop = 1100;
            }
        """)
        time.sleep(0.3)
        e2e_page.screenshot(path=os.path.join(SCREENSHOTS_DIR, "koto_page2.png"))
        assert os.path.exists(os.path.join(SCREENSHOTS_DIR, "koto_page2.png"))
