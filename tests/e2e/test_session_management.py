"""Browser E2E coverage for the unified workspace conversation history."""

from __future__ import annotations

import pytest


def _csrf_headers(page, base_url: str) -> dict[str, str]:
    response = page.request.get(f"{base_url}/api/csrf-token")
    assert response.ok, f"Failed to obtain CSRF token: {response.status}"
    payload = response.json()
    token = payload.get("csrf_token") or payload.get("token")
    assert token
    return {"X-CSRFToken": token}


def _api_delete_session(page, base_url: str, session_id: str) -> None:
    if not session_id:
        return
    try:
        page.request.delete(
            f"{base_url}/api/sessions/{session_id}",
            headers=_csrf_headers(page, base_url),
        )
    except Exception:
        pass


def _show_session_list(page) -> None:
    back = page.locator("#wa-ai-session-back")
    if back.is_visible():
        back.click()
    page.locator("#wa-ai-session-list-view").wait_for(state="visible", timeout=5000)


def _active_session(page):
    active = page.locator(".wa-ai-session-item.is-active")
    active.wait_for(state="visible", timeout=5000)
    assert active.count() == 1
    session_id = active.get_attribute("data-ai-session-id") or ""
    assert session_id
    return active, session_id


def _create_session(page, base_url: str) -> tuple[object, str]:
    page.goto(f"{base_url}/", wait_until="domcontentloaded")
    _show_session_list(page)
    new_button = page.locator("#wa-ai-session-new")
    assert new_button.count() == 1
    new_button.click()
    page.locator("#wa-ai-chat-view").wait_for(state="visible", timeout=5000)
    _show_session_list(page)
    return _active_session(page)


@pytest.mark.e2e
def test_create_session_in_unified_history(e2e_page, e2e_base_url, console_errors):
    page = e2e_page
    session_id = ""
    try:
        _item, session_id = _create_session(page, e2e_base_url)
        assert console_errors == []
    finally:
        _api_delete_session(page, e2e_base_url, session_id)


@pytest.mark.e2e
def test_click_session_opens_unified_chat(e2e_page, e2e_base_url, console_errors):
    page = e2e_page
    session_id = ""
    try:
        item, session_id = _create_session(page, e2e_base_url)
        item.click()
        page.locator("#wa-ai-chat-view").wait_for(state="visible", timeout=5000)
        assert console_errors == []
    finally:
        _api_delete_session(page, e2e_base_url, session_id)


@pytest.mark.e2e
def test_refresh_preserves_current_session(e2e_page, e2e_base_url, console_errors):
    page = e2e_page
    session_id = ""
    try:
        _item, session_id = _create_session(page, e2e_base_url)
        refresh = page.locator("#wa-ai-session-refresh")
        assert refresh.count() == 1
        refresh.click()
        current = page.locator(
            f'.wa-ai-session-item[data-ai-session-id="{session_id}"]'
        )
        current.wait_for(state="visible", timeout=5000)
        assert console_errors == []
    finally:
        _api_delete_session(page, e2e_base_url, session_id)


@pytest.mark.e2e
def test_delete_session_from_unified_history(e2e_page, e2e_base_url, console_errors):
    page = e2e_page
    session_id = ""
    try:
        _item, session_id = _create_session(page, e2e_base_url)
        delete_button = page.locator(f'[data-ai-session-delete="{session_id}"]')
        assert delete_button.count() == 1
        page.on("dialog", lambda dialog: dialog.accept())
        delete_button.click()
        page.locator(
            f'.wa-ai-session-item[data-ai-session-id="{session_id}"]'
        ).wait_for(state="detached", timeout=5000)
        session_id = ""
        assert console_errors == []
    finally:
        _api_delete_session(page, e2e_base_url, session_id)


@pytest.mark.e2e
def test_session_lifecycle_has_no_client_or_server_errors(
    e2e_page_with_network, e2e_base_url, console_errors, failed_requests
):
    page = e2e_page_with_network
    session_id = ""
    try:
        item, session_id = _create_session(page, e2e_base_url)
        item.click()
        page.locator("#wa-ai-chat-view").wait_for(state="visible", timeout=5000)
        _show_session_list(page)

        delete_button = page.locator(f'[data-ai-session-delete="{session_id}"]')
        assert delete_button.count() == 1
        page.on("dialog", lambda dialog: dialog.accept())
        delete_button.click()
        page.locator(
            f'.wa-ai-session-item[data-ai-session-id="{session_id}"]'
        ).wait_for(state="detached", timeout=5000)
        session_id = ""

        assert console_errors == []
        assert failed_requests == []
    finally:
        _api_delete_session(page, e2e_base_url, session_id)
