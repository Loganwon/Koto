"""Realistic browser journeys for Koto's current unified product surfaces.

These tests deliberately use the same entry points a user sees today.  They
must not retain selectors or routes from retired parallel frontends.
"""

from __future__ import annotations

import uuid

import pytest
import requests

PAGE_TIMEOUT = 15_000
THINK_SHORT = 300
THINK_MEDIUM = 800

BENIGN_PATTERNS = (
    "api key",
    "API key",
    "model not found",
    "Failed to fetch",
    "NetworkError",
    "AbortError",
    "ERR_CONNECTION",
    "net::ERR_",
    "interrupt",
    "stream",
    "WebSocket",
    "ws://",
    "422",
    "500",
)


def _real_errors(console_errors: list[str]) -> list[str]:
    return [
        error
        for error in console_errors
        if not any(pattern.lower() in error.lower() for pattern in BENIGN_PATTERNS)
    ]


def _goto(page, url: str):
    response = page.goto(url, timeout=PAGE_TIMEOUT, wait_until="domcontentloaded")
    assert (
        response is not None and response.status < 400
    ), f"{url} returned {response.status}"
    return response


def _open_workspace_ai(page, base_url: str):
    """Open the unified workspace through its public feature boundary."""
    page.add_init_script("window.__KOTO_E2E__ = true")
    _goto(page, f"{base_url}/")
    page.wait_for_function(
        """() => document.__kotoFeatureRegistry__
            && typeof document.__kotoFeatureRegistry__.openInMainView === 'function'
            && typeof document.__kotoFeatureRegistry__.newAiSession === 'function'""",
        timeout=PAGE_TIMEOUT,
    )
    page.evaluate("() => document.__kotoFeatureRegistry__.openInMainView()")
    page.evaluate(
        "() => document.__kotoFeatureRegistry__.newAiSession({toast: false, focus: false})"
    )
    page.locator("#wa-user-input").wait_for(state="visible", timeout=PAGE_TIMEOUT)


def _send_one_message(page, text: str):
    composer = page.locator("#wa-user-input")
    composer.fill(text)
    composer.press("Enter")
    bubble = page.locator("#wa-ai-messages .wa-msg.user").last
    bubble.wait_for(state="visible", timeout=PAGE_TIMEOUT)
    assert text in bubble.inner_text()
    return bubble


def _csrf_api_client(base_url: str) -> tuple[requests.Session, dict[str, str]]:
    """Create the same cookie + CSRF context used by browser mutations."""
    client = requests.Session()
    response = client.get(f"{base_url}/api/csrf-token", timeout=10)
    assert response.status_code == 200, response.text
    body = response.json()
    token = body.get("csrf_token") or body.get("token")
    assert token, body
    return client, {"X-CSRFToken": token}


@pytest.mark.e2e
class TestUnifiedWorkspaceJourney:
    def test_first_visit_opens_current_ai_workspace(
        self, e2e_page, console_errors, e2e_base_url
    ):
        _open_workspace_ai(e2e_page, e2e_base_url)

        assert e2e_page.locator("#wa-ai-messages").is_visible()
        assert e2e_page.locator("#wa-user-input").is_visible()
        assert e2e_page.locator("#wa-send-btn").is_visible()
        assert e2e_page.locator("#wa-user-input").input_value() == ""
        assert _real_errors(console_errors) == []

    def test_user_edits_a_draft_before_sending(
        self, e2e_page, console_errors, e2e_base_url
    ):
        _open_workspace_ai(e2e_page, e2e_base_url)
        composer = e2e_page.locator("#wa-user-input")
        composer.fill("请分析旧版本")
        composer.press("Control+a")
        composer.fill("请分析当前文档")
        assert composer.input_value() == "请分析当前文档"
        assert not e2e_page.locator("#wa-send-btn").is_disabled()
        assert _real_errors(console_errors) == []

    def test_user_message_enters_current_conversation(
        self, e2e_page, console_errors, e2e_base_url
    ):
        _open_workspace_ai(e2e_page, e2e_base_url)
        _send_one_message(e2e_page, "请总结今天的待办事项")
        assert e2e_page.locator("#wa-user-input").input_value() == ""
        assert _real_errors(console_errors) == []

    def test_empty_send_does_not_create_ghost_message(
        self, e2e_page, console_errors, e2e_base_url
    ):
        _open_workspace_ai(e2e_page, e2e_base_url)
        before = e2e_page.locator("#wa-ai-messages .wa-msg.user").count()
        send_button = e2e_page.locator("#wa-send-btn")
        assert send_button.is_disabled(), "Empty composer must disable send"
        for _ in range(5):
            send_button.dispatch_event("click")
        assert e2e_page.locator("#wa-ai-messages .wa-msg.user").count() == before
        assert _real_errors(console_errors) == []


@pytest.mark.e2e
class TestConversationLifecycleJourney:
    def test_back_to_history_and_new_conversation(
        self, e2e_page, console_errors, e2e_base_url
    ):
        _open_workspace_ai(e2e_page, e2e_base_url)
        e2e_page.locator("#wa-ai-session-back").click()
        e2e_page.locator("#wa-ai-session-list-view").wait_for(
            state="visible", timeout=PAGE_TIMEOUT
        )
        e2e_page.locator("#wa-ai-session-new").click()
        e2e_page.locator("#wa-ai-chat-view").wait_for(
            state="visible", timeout=PAGE_TIMEOUT
        )
        e2e_page.locator("#wa-user-input").wait_for(
            state="visible", timeout=PAGE_TIMEOUT
        )
        assert _real_errors(console_errors) == []

    def test_server_session_appears_and_opens_from_history(
        self, e2e_page, console_errors, e2e_base_url
    ):
        session_name = f"journey_{uuid.uuid4().hex[:8]}"
        client, headers = _csrf_api_client(e2e_base_url)
        created = client.post(
            f"{e2e_base_url}/api/sessions",
            json={"name": session_name},
            headers=headers,
            timeout=10,
        )
        assert created.status_code in (200, 201), created.text
        session_id = created.json().get("session")
        assert session_id
        try:
            seeded = client.post(
                f"{e2e_base_url}/api/sessions/{session_id}/workspace-turn",
                json={
                    "user": "检查会话历史",
                    "assistant": "会话历史可用",
                    "turn_id": f"turn_{uuid.uuid4().hex[:8]}",
                },
                headers=headers,
                timeout=10,
            )
            assert seeded.status_code == 200, seeded.text
            _open_workspace_ai(e2e_page, e2e_base_url)
            e2e_page.locator("#wa-ai-session-back").click()
            e2e_page.locator("#wa-ai-session-refresh").click()
            item = e2e_page.locator(f'[data-ai-session-id="{session_id}"]')
            item.wait_for(state="visible", timeout=PAGE_TIMEOUT)
            item.click()
            e2e_page.locator("#wa-ai-chat-view").wait_for(
                state="visible", timeout=PAGE_TIMEOUT
            )
            user_turn = e2e_page.locator("#wa-ai-messages .wa-msg.user").last
            assistant_turn = e2e_page.locator("#wa-ai-messages .wa-msg.ai").last
            user_turn.wait_for(state="visible", timeout=PAGE_TIMEOUT)
            assert "检查会话历史" in user_turn.inner_text()
            assert "会话历史可用" in assistant_turn.inner_text()
            assert _real_errors(console_errors) == []
        finally:
            client.delete(
                f"{e2e_base_url}/api/sessions/{session_id}",
                headers=headers,
                timeout=10,
            )


@pytest.mark.e2e
class TestAddonCapabilityJourney:
    def test_capability_panel_and_addon_admission(
        self, e2e_page, console_errors, e2e_base_url
    ):
        _goto(e2e_page, f"{e2e_base_url}/")
        e2e_page.wait_for_function(
            """() => typeof document.__kotoFeatureRegistry__
                ?.loadCapabilityPanelBundle === 'function'""",
            timeout=PAGE_TIMEOUT,
        )
        e2e_page.evaluate(
            "() => document.__kotoFeatureRegistry__.loadCapabilityPanelBundle()"
        )
        e2e_page.wait_for_function(
            """() => typeof document.__kotoFeatureRegistry__
                ?.openCapabilityPanel === 'function'""",
            timeout=PAGE_TIMEOUT,
        )
        e2e_page.locator("#navCapabilityBtn").click()
        panel = e2e_page.locator("#capabilityPanel")
        panel.wait_for(state="visible", timeout=PAGE_TIMEOUT)
        assert panel.get_attribute("aria-hidden") == "false"

        _goto(e2e_page, f"{e2e_base_url}/addons")
        e2e_page.locator("#example-button").click()
        e2e_page.locator("#validate-button").click()
        e2e_page.locator(".validation--ok").wait_for(
            state="visible", timeout=PAGE_TIMEOUT
        )
        assert not e2e_page.locator("#register-button").is_disabled()
        assert _real_errors(console_errors) == []


@pytest.mark.e2e
class TestFileAndNavigationJourney:
    def test_attach_file_as_workspace_context(
        self, e2e_page, console_errors, e2e_base_url
    ):
        _open_workspace_ai(e2e_page, e2e_base_url)
        e2e_page.wait_for_function(
            """() => typeof document.__kotoFeatureRegistry__
                ?.addLocalFilesToAIContext === 'function'""",
            timeout=PAGE_TIMEOUT,
        )
        file_name = f"journey_notes_{uuid.uuid4().hex[:8]}.txt"
        try:
            e2e_page.locator("#wa-ai-context-file-input").set_input_files(
                {
                    "name": file_name,
                    "mimeType": "text/plain",
                    "buffer": b"Q1 goals\nReview backlog\nPlan sprint",
                }
            )
            e2e_page.wait_for_function(
                """expected => document.getElementById('wa-ai-file-chip-list')
                    ?.innerText.includes(expected)""",
                arg=file_name,
                timeout=PAGE_TIMEOUT,
            )
            assert file_name in e2e_page.locator("#wa-ai-file-chip-list").inner_text()
            assert _real_errors(console_errors) == []
        finally:
            client, headers = _csrf_api_client(e2e_base_url)
            deleted = client.delete(
                f"{e2e_base_url}/api/v1/workspace/file",
                params={"path": file_name},
                headers=headers,
                timeout=10,
            )
            assert deleted.status_code in (200, 404), deleted.text

    def test_leave_for_addons_and_return_to_workspace(
        self, e2e_page, console_errors, e2e_base_url
    ):
        _open_workspace_ai(e2e_page, e2e_base_url)
        _goto(e2e_page, f"{e2e_base_url}/addons")
        assert e2e_page.locator("#addon-catalog").count() == 1
        e2e_page.go_back(wait_until="domcontentloaded")
        e2e_page.locator("#wa-workspace").wait_for(
            state="attached", timeout=PAGE_TIMEOUT
        )
        assert _real_errors(console_errors) == []

    @pytest.mark.parametrize(
        "path, selector",
        [
            ("/", "#wa-workspace"),
            ("/addons", "#addon-catalog"),
            ("/mini", ".app"),
        ],
    )
    def test_current_main_surface_is_reachable(
        self, e2e_page, console_errors, e2e_base_url, path, selector
    ):
        _goto(e2e_page, f"{e2e_base_url}{path}")
        assert e2e_page.locator(selector).count() > 0
        assert _real_errors(console_errors) == []


@pytest.mark.e2e
class TestKeyboardAndMobileJourney:
    def test_keyboard_composer_contract(self, e2e_page, console_errors, e2e_base_url):
        _open_workspace_ai(e2e_page, e2e_base_url)
        composer = e2e_page.locator("#wa-user-input")
        composer.focus()
        e2e_page.keyboard.type("键盘输入草稿")
        e2e_page.keyboard.press("Shift+Enter")
        e2e_page.keyboard.type("第二行")
        assert "\n第二行" in composer.input_value()
        assert _real_errors(console_errors) == []

    def test_mobile_viewport_uses_the_unified_composer(
        self, e2e_page, console_errors, e2e_base_url
    ):
        e2e_page.set_viewport_size({"width": 390, "height": 844})
        _open_workspace_ai(e2e_page, e2e_base_url)
        composer = e2e_page.locator("#wa-user-input")
        composer.click()
        composer.fill("来自移动端的消息")
        assert e2e_page.locator("#wa-send-btn").count() == 1
        assert composer.input_value() == "来自移动端的消息"
        assert _real_errors(console_errors) == []
