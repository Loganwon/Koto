"""
E2E smoke tests — verify every major Koto page loads without errors.

Each test navigates to a page, checks for a 2xx/3xx response,
waits for the DOM to settle, asserts zero JS console errors,
and confirms at least one key element is visible.
"""

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
PAGE_TIMEOUT = 15_000  # ms – generous enough for cold-start Flask


def _goto(page, url):
    """Navigate and return the Playwright Response so callers can check status."""
    resp = page.goto(url, timeout=PAGE_TIMEOUT, wait_until="domcontentloaded")
    return resp


# ---------------------------------------------------------------------------
# Individual page tests
# ---------------------------------------------------------------------------


@pytest.mark.e2e
def test_index_page(e2e_page, console_errors, e2e_base_url):
    """/ — main chat UI with session sidebar and chat input."""
    resp = _goto(e2e_page, f"{e2e_base_url}/")
    assert resp is not None and resp.status < 500, f"Status {resp.status}"

    # The unified workspace keeps long-lived connections open, so networkidle
    # is not a valid readiness signal. Wait for its actual shell contract.
    e2e_page.locator("#wa-workspace").wait_for(state="attached", timeout=PAGE_TIMEOUT)
    assert (
        e2e_page.locator("#wa-ai-messages").count() == 1
    ), "Missing AI message surface"
    assert (
        e2e_page.locator("#wa-ai-session-list").count() == 1
    ), "Missing AI session list"

    assert console_errors == [], f"JS errors: {console_errors}"


@pytest.mark.e2e
def test_addon_center_page(e2e_page, console_errors, e2e_base_url):
    """/addons — current Addon protocol and admission surface."""
    resp = _goto(e2e_page, f"{e2e_base_url}/addons")
    assert resp is not None and resp.status < 500, f"Status {resp.status}"

    e2e_page.wait_for_load_state("networkidle", timeout=PAGE_TIMEOUT)

    assert e2e_page.locator("#manifest-input").count() == 1, "Missing manifest input"
    assert e2e_page.locator("#addon-catalog").count() == 1, "Missing Addon catalog"

    assert console_errors == [], f"JS errors: {console_errors}"


@pytest.mark.e2e
def test_mini_page(e2e_page, console_errors, e2e_base_url):
    """/mini — the supported compact chat surface."""
    resp = _goto(e2e_page, f"{e2e_base_url}/mini")
    assert resp is not None and resp.status < 400, f"Status {resp.status}"
    assert e2e_page.locator(".app").count() == 1
    assert e2e_page.locator("#q").count() == 1
    assert console_errors == [], f"JS errors: {console_errors}"


# ---------------------------------------------------------------------------
# Parametrised test — all pages in one sweep
# ---------------------------------------------------------------------------
ALL_PAGES = [
    ("/", "body"),
    ("/addons", "#addon-catalog"),
    ("/mini", ".app"),
]


@pytest.mark.e2e
@pytest.mark.parametrize("path, selector", ALL_PAGES, ids=[p for p, _ in ALL_PAGES])
def test_page_loads_without_errors(
    e2e_page, console_errors, e2e_base_url, path, selector
):
    """Every major page should return < 500, render its key element, and emit no JS errors."""
    resp = _goto(e2e_page, f"{e2e_base_url}{path}")
    assert resp is not None and resp.status < 400, f"{path} returned {resp.status}"

    e2e_page.wait_for_load_state("domcontentloaded", timeout=PAGE_TIMEOUT)

    assert (
        e2e_page.locator(selector).count() > 0
    ), f"{path}: expected element '{selector}' not found"

    assert console_errors == [], f"{path} JS errors: {console_errors}"
