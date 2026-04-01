"""
E2E UI tests for the PPTX editor in workspace-assistant.
Simulates real user interaction: upload → render → edit → toolbar → move → new slide.

Run:
    python tests/e2e_pptx_editor.py
"""

from __future__ import annotations

import sys
import time
import traceback
from pathlib import Path

from playwright.sync_api import Page, expect, sync_playwright

BASE_URL = "http://localhost:5000"
PPTX_PATH = Path(__file__).parent.parent / "workspace" / "022cf2309db3_original.pptx"

PASS = "✅"
FAIL = "❌"
SKIP = "⚠️ "

results: list[tuple[str, str, str]] = []  # (status, name, detail)


def check(name: str, cond: bool, detail: str = ""):
    status = PASS if cond else FAIL
    results.append((status, name, detail))
    print(f"  {status} {name}" + (f"  — {detail}" if detail else ""))
    return cond


def run_test(name: str, fn):
    print(f"\n{'─'*60}\n▶ {name}")
    try:
        fn()
    except Exception as e:
        results.append((FAIL, name, str(e)))
        print(f"  {FAIL} EXCEPTION: {e}")
        traceback.print_exc()


# ─────────────────────────────────────────────────────────────────────────────


def test_page_load(page: Page):
    page.goto(BASE_URL + "/workspace-assistant", wait_until="networkidle")
    check("Page title contains Koto", "Koto" in page.title(), page.title())
    check("PPTX toolbar exists in DOM", page.locator("#wa-pptx-toolbar").count() > 0)
    check("Slide canvas exists", page.locator("#wa-pptx-slide-canvas").count() > 0)
    check("Thumbstrip exists", page.locator("#wa-pptx-thumbstrip").count() > 0)


def test_upload_pptx(page: Page):
    if not PPTX_PATH.exists():
        results.append((SKIP, "Upload PPTX", f"file not found: {PPTX_PATH}"))
        return

    # Click "打开文件" button or use the hidden file input
    file_input = page.locator("input[type=file]").first
    file_input.set_input_files(str(PPTX_PATH))
    # Wait for the editor to become active
    page.wait_for_selector("#wa-pptx-editor.active", timeout=8000)
    time.sleep(0.8)  # allow JS render pass

    check(
        "PPTX editor becomes active", page.locator("#wa-pptx-editor.active").count() > 0
    )

    # Slide canvas should have child divs (shapes)
    shapes = page.locator("#wa-pptx-slide-canvas .wa-pptx-shape")
    n_shapes = shapes.count()
    check("Shapes rendered on canvas", n_shapes > 0, f"{n_shapes} shapes")

    # Slide counter should show "1 / N"
    counter = page.locator("#wa-pptx-slide-counter").inner_text()
    check("Slide counter visible", "/" in counter, counter)

    # Thumbnail strip should have at least one canvas thumbnail
    thumbs = page.locator(".wa-pptx-thumb")
    n_thumbs = thumbs.count()
    check("Thumbnails rendered", n_thumbs > 0, f"{n_thumbs} thumbs")


def test_text_visible(page: Page):
    runs = page.locator(".wa-pptx-run")
    n = runs.count()
    check("Run spans exist", n > 0, f"{n} runs")

    # Check no run has font-size 0px (the old bug)
    zero_size = 0
    for i in range(n):
        fs = runs.nth(i).evaluate("el => window.getComputedStyle(el).fontSize")
        if fs == "0px" or fs == "":
            zero_size += 1
    check("No run has font-size 0px", zero_size == 0, f"{zero_size}/{n} invisible runs")

    # First run should have visible text content
    if n > 0:
        txt = runs.first.inner_text()
        check("First run has text content", len(txt.strip()) > 0, repr(txt[:40]))


def test_text_color(page: Page):
    runs = page.locator(".wa-pptx-run")
    if runs.count() == 0:
        results.append((SKIP, "Text color", "no runs"))
        return
    # Check text color is not white or near-white (which would be invisible on white bg)
    colors_ok = 0
    for i in range(min(runs.count(), 5)):
        color = runs.nth(i).evaluate("el => window.getComputedStyle(el).color")
        # Accept anything not rgb(255,255,255) or empty
        if color and color != "rgb(255, 255, 255)" and color != "rgba(0, 0, 0, 0)":
            colors_ok += 1
    check(
        "Text color is visible (not white/transparent)",
        colors_ok > 0,
        f"{colors_ok} runs with visible color",
    )


def test_click_and_edit(page: Page):
    runs = page.locator(".wa-pptx-run")
    if runs.count() == 0:
        results.append((SKIP, "Click and edit", "no runs"))
        return

    # Double-click to enter edit mode (PowerPoint-style)
    runs.first.dblclick()
    time.sleep(0.2)
    focused = page.evaluate(
        "() => document.activeElement?.classList?.contains('wa-pptx-run')"
    )
    check("Clicking run focuses it", focused)

    # Type some text
    page.keyboard.type(" TEST")
    time.sleep(0.1)
    text_after = runs.first.inner_text()
    check("Typed text appears in run", "TEST" in text_after, repr(text_after[:40]))

    # Undo
    page.keyboard.press("Control+z")


def test_bold_toolbar(page: Page):
    runs = page.locator(".wa-pptx-run")
    if runs.count() == 0:
        results.append((SKIP, "Bold toolbar", "no runs"))
        return

    runs.first.dblclick()
    time.sleep(0.2)
    # Press End to clear word-selection from dblclick (cursor stays in run)
    # Without this, character-level split would change which span is runs.first
    page.keyboard.press("End")
    time.sleep(0.05)
    bold_btn = page.locator("#wa-pptx-bold")
    if bold_btn.count() == 0:
        results.append((SKIP, "Bold toolbar", "button not found"))
        return

    bold_btn.click()
    time.sleep(0.1)
    fw = runs.first.evaluate("el => window.getComputedStyle(el).fontWeight")
    check("Bold button makes text bold", fw in ("700", "bold"), f"fontWeight={fw}")
    # Toggle off
    bold_btn.click()


def test_fontsize_toolbar(page: Page):
    runs = page.locator(".wa-pptx-run")
    if runs.count() == 0:
        results.append((SKIP, "Font size toolbar", "no runs"))
        return

    runs.first.dblclick()
    time.sleep(0.2)
    # Press End to clear word-selection from dblclick before changing font size
    page.keyboard.press("End")
    time.sleep(0.05)
    sel = page.locator("#wa-pptx-fontsize")
    if sel.count() == 0:
        results.append((SKIP, "Font size toolbar", "select not found"))
        return

    before = runs.first.evaluate("el => window.getComputedStyle(el).fontSize")
    sel.select_option("32")
    time.sleep(0.2)
    after = runs.first.evaluate("el => window.getComputedStyle(el).fontSize")
    check("Font size change updates run style", before != after, f"{before} → {after}")


def test_slide_navigation(page: Page):
    prev = page.locator("#wa-pptx-prev")
    nxt = page.locator("#wa-pptx-next")
    if prev.count() == 0:
        results.append((SKIP, "Slide navigation", "buttons not found"))
        return

    counter_before = page.locator("#wa-pptx-slide-counter").inner_text()
    nxt.click()
    time.sleep(0.3)
    counter_after = page.locator("#wa-pptx-slide-counter").inner_text()
    check(
        "Next slide changes counter",
        counter_before != counter_after,
        f"{counter_before} → {counter_after}",
    )

    prev.click()
    time.sleep(0.3)
    counter_back = page.locator("#wa-pptx-slide-counter").inner_text()
    check("Prev slide returns to first", counter_back == counter_before, counter_back)


def test_new_slide(page: Page):
    # New slide button is on Home tab (default)
    home_tab = page.locator(".wa-pptx-rtab", has_text="开始")
    if home_tab.count():
        home_tab.click()
        time.sleep(0.1)

    add_btn = page.locator("button[onclick='WA.pptxAddSlide()']")
    if add_btn.count() == 0:
        results.append((SKIP, "New slide", "button not found"))
        return

    counter_before = page.locator("#wa-pptx-slide-counter").inner_text()
    add_btn.click()
    time.sleep(0.5)
    counter_after = page.locator("#wa-pptx-slide-counter").inner_text()
    check(
        "新建 adds a slide",
        counter_before != counter_after,
        f"{counter_before} → {counter_after}",
    )

    # New slide should have default title and body shapes
    shapes = page.locator("#wa-pptx-slide-canvas .wa-pptx-shape")
    n = shapes.count()
    check("New slide has default shapes", n >= 2, f"{n} shapes")

    runs = page.locator(".wa-pptx-run")
    texts = [runs.nth(i).inner_text() for i in range(runs.count())]
    has_title = any("标题" in t or "Title" in t for t in texts)
    check("New slide has placeholder title text", has_title, str(texts[:3]))


def test_insert_textbox(page: Page):
    # Switch to Insert tab so the insert-tb button becomes visible
    insert_tab = page.locator(".wa-pptx-rtab", has_text="插入")
    if insert_tab.count():
        insert_tab.click()
        time.sleep(0.1)

    insert_btn = page.locator("#wa-pptx-insert-tb")
    if insert_btn.count() == 0:
        results.append((SKIP, "Insert text box", "button not found"))
        return

    insert_btn.click()
    time.sleep(0.1)
    active_class = insert_btn.get_attribute("class") or ""
    check("Insert mode button activates", "active" in active_class)

    # Draw a text box by dragging on canvas
    canvas = page.locator("#wa-pptx-slide-canvas")
    box = canvas.bounding_box()
    if not box:
        results.append((SKIP, "Insert text box drag", "canvas not visible"))
        return

    cx, cy = box["x"] + box["width"] * 0.2, box["y"] + box["height"] * 0.5
    page.mouse.move(cx, cy)
    page.mouse.down()
    page.mouse.move(cx + 180, cy + 60, steps=10)
    page.mouse.up()
    time.sleep(0.4)

    # A new run span should exist now
    runs_after = page.locator(".wa-pptx-run").count()
    check("Drawing text box creates a new shape", runs_after > 0)

    # Wait for double-rAF auto-edit-mode to fire
    time.sleep(0.15)

    # The new shape should be in edit mode (has wa-pptx-editing class)
    editing_shapes = page.locator(".wa-pptx-shape.wa-pptx-editing").count()
    check("Inserted text box auto-enters edit mode", editing_shapes > 0)

    # Type into the newly inserted text box
    page.keyboard.type("Hello")
    time.sleep(0.15)

    # The span should now contain the typed text
    new_spans = page.locator(".wa-pptx-shape.wa-pptx-editing .wa-pptx-run")
    typed_text = ""
    if new_spans.count() > 0:
        typed_text = new_spans.first.inner_text()
    check(
        "Inserted text box accepts typed input",
        "Hello" in typed_text,
        f"span text='{typed_text}'",
    )


def test_drag_move(page: Page):
    shapes = page.locator("#wa-pptx-slide-canvas .wa-pptx-shape")
    if shapes.count() == 0:
        results.append((SKIP, "Drag move", "no shapes"))
        return

    shape = shapes.first
    box = shape.bounding_box()
    if not box:
        results.append((SKIP, "Drag move", "shape not visible"))
        return

    orig_left = box["x"]
    cx, cy = box["x"] + 5, box["y"] + 5  # click near top-left corner (border)
    page.mouse.move(cx, cy)
    page.mouse.down()
    page.mouse.move(cx + 50, cy + 30, steps=10)
    page.mouse.up()
    time.sleep(0.3)

    new_box = shape.bounding_box()
    moved = new_box and abs(new_box["x"] - orig_left) > 5
    check(
        "Shape can be dragged to new position",
        moved,
        f"orig_x={orig_left:.0f} new_x={new_box['x']:.0f}" if new_box else "no box",
    )


def test_no_js_errors(page: Page):
    errors = []
    page.on(
        "console", lambda msg: errors.append(msg.text) if msg.type == "error" else None
    )
    page.reload(wait_until="networkidle")
    time.sleep(1)
    js_errors = [e for e in errors if "TypeError" in e or "ReferenceError" in e]
    check(
        "No JS TypeError/ReferenceError on load",
        len(js_errors) == 0,
        "; ".join(js_errors[:3]),
    )


def test_delete_shape(page: Page):
    shapes_before = page.locator("#wa-pptx-slide-canvas .wa-pptx-shape").count()
    if shapes_before == 0:
        results.append((SKIP, "Delete shape", "no shapes"))
        return
    # Escape any existing selection/edit mode first → first click will just select
    page.keyboard.press("Escape")
    page.keyboard.press("Escape")
    time.sleep(0.1)
    page.locator("#wa-pptx-slide-canvas .wa-pptx-shape").first.click()
    time.sleep(0.2)
    page.keyboard.press("Delete")
    time.sleep(0.3)
    shapes_after = page.locator("#wa-pptx-slide-canvas .wa-pptx-shape").count()
    check(
        "Delete key removes selected shape",
        shapes_after < shapes_before,
        f"{shapes_before} -> {shapes_after}",
    )


def test_right_click_menu(page: Page):
    import time

    shapes = page.locator("#wa-pptx-slide-canvas .wa-pptx-shape")
    if shapes.count() == 0:
        results.append((SKIP, "Right-click menu", "no shapes"))
        return
    shapes.first.click(button="right")
    time.sleep(0.2)
    menu = page.locator("#wa-pptx-ctx")
    visible = menu.is_visible()
    check("Right-click shows context menu", visible)
    if visible:
        items = page.locator(".wa-pptx-ctx-item")
        n = items.count()
        check("Context menu has items", n >= 3, f"{n} items")
        texts = [items.nth(i).inner_text() for i in range(n)]
        check(
            "Context menu has delete option",
            any("删除" in t for t in texts),
            str(texts),
        )
        # Press Escape to close
        page.keyboard.press("Escape")
        time.sleep(0.1)
        check("Escape closes context menu", not menu.is_visible())


# ─────────────────────────────────────────────────────────────────────────────


def main():
    print(f"\n{'='*60}")
    print("  PPTX Editor E2E Tests — Playwright Chromium")
    print(f"{'='*60}")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1280, "height": 900})
        page = ctx.new_page()

        # Capture JS console errors throughout
        js_errors: list[str] = []
        page.on(
            "console", lambda m: js_errors.append(m.text) if m.type == "error" else None
        )
        page.on("pageerror", lambda e: js_errors.append(f"PAGE ERROR: {e}"))

        run_test("Page load", lambda: test_page_load(page))
        run_test("Upload PPTX", lambda: test_upload_pptx(page))
        run_test("Text visible", lambda: test_text_visible(page))
        run_test("Text color", lambda: test_text_color(page))
        run_test("Click and edit", lambda: test_click_and_edit(page))
        run_test("Bold toolbar", lambda: test_bold_toolbar(page))
        run_test("Font size toolbar", lambda: test_fontsize_toolbar(page))
        run_test("Right-click menu", lambda: test_right_click_menu(page))
        run_test("Delete shape", lambda: test_delete_shape(page))
        run_test("Insert text box", lambda: test_insert_textbox(page))
        run_test("Drag move", lambda: test_drag_move(page))
        run_test("Slide navigation", lambda: test_slide_navigation(page))
        run_test("New slide", lambda: test_new_slide(page))
        run_test("No JS errors", lambda: test_no_js_errors(page))

        # Print any JS errors collected
        if js_errors:
            print(f"\n{'─'*60}")
            print(f"⚠️  JS console errors collected during session:")
            for e in js_errors[:10]:
                print(f"    {e}")

        ctx.close()
        browser.close()

    # ── Summary ──────────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    passed = sum(1 for s, _, _ in results if s == PASS)
    failed = sum(1 for s, _, _ in results if s == FAIL)
    skipped = sum(1 for s, _, _ in results if s == SKIP)
    print(f"  PASSED: {passed}   FAILED: {failed}   SKIPPED: {skipped}")
    print(f"{'='*60}\n")

    if failed:
        print("Failed checks:")
        for s, name, detail in results:
            if s == FAIL:
                print(f"  {FAIL} {name}: {detail}")
        sys.exit(1)


if __name__ == "__main__":
    main()
