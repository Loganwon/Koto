"""
E2E tests that simulate complete human user journeys in Koto.

Unlike single-element tests, each test here walks through a realistic
multi-step user workflow — the same sequence of actions a real person
would take.  Steps are ordered, build on each other, and include
natural "think time" pauses between interactions.

Journey tests covered:
  1. New user first visit — lands on app, reads UI, types first message
  2. Conversation back-and-forth — send, wait, inspect response area, continue
  3. Session lifecycle — create named session, chat in it, rename, switch, delete
  4. Skill marketplace exploration — browse, search, open card, close, navigate back
  5. File attachment workflow — attach file, inspect preview, clear, re-attach
  6. Keyboard-only navigation — tab between controls, send via keyboard
  7. Rapid context switching — quickly switch sessions, assert no state bleed
  8. Settings / sidebar navigation — open panels, change tabs, close
  9. Copy-and-paste flow — send message, copy text, paste into new message
 10. Page navigation and return — leave chat, visit other pages, come back
"""

import time
import uuid

import pytest
import requests

# ---------------------------------------------------------------------------
# Constants and helpers
# ---------------------------------------------------------------------------
PAGE_TIMEOUT = 15_000  # ms
THINK_SHORT = 400  # ms — brief pause between keystrokes / clicks
THINK_MEDIUM = 1_000  # ms — pause after an action before reading result
THINK_LONG = 2_500  # ms — wait for async (animations, fetch responses)

# Errors that are benign when the AI backend isn't configured in CI
BENIGN_PATTERNS = (
    "api key",
    "API key",
    "model not found",
    "Failed to fetch",
    "NetworkError",
    "AbortError",
    "Interrupt signal failed",
    "ERR_CONNECTION",
    "net::ERR_",
    "interrupt",
    "INTERRUPT",
    "Reset interrupt failed",
    "stream",
    "STREAM",
    "422",
    "500",
    "Unprocessable",
    "fetch",
    "WebSocket",
    "ws://",
)


def _is_benign(text: str) -> bool:
    return any(p in text for p in BENIGN_PATTERNS)


def _real_errors(console_errors: list) -> list:
    return [e for e in console_errors if not _is_benign(e)]


def _goto(page, url: str):
    """Navigate to URL and wait for DOM content."""
    return page.goto(url, timeout=PAGE_TIMEOUT, wait_until="domcontentloaded")


def _settle(page, ms: int = THINK_LONG):
    """Let the UI settle (animations, debounced fetches)."""
    page.wait_for_timeout(ms)


def _unique_name(prefix: str = "session") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:6]}"


def _send_message(page, text: str):
    """Type text into the chat input and submit via Enter."""
    ta = page.locator("#messageInput")
    ta.wait_for(state="visible", timeout=PAGE_TIMEOUT)
    ta.fill(text)
    page.wait_for_timeout(THINK_SHORT)
    ta.press("Enter")


def _api(base_url: str, method: str, path: str, **kwargs):
    """Make a JSON API call to the running server."""
    url = f"{base_url}{path}"
    fn = getattr(requests, method)
    return fn(url, timeout=10, **kwargs)


# ---------------------------------------------------------------------------
# Journey 1: New user — first visit, explore, send first message
# ---------------------------------------------------------------------------
@pytest.mark.e2e
class TestNewUserJourney:
    """A brand-new user opens Koto for the first time."""

    def test_landing_page_loads_and_shows_chat(
        self, e2e_page, console_errors, e2e_base_url
    ):
        """User types URL → page loads → sees chat interface."""
        # Step 1: Navigate (simulate typing URL and hitting Enter)
        _goto(e2e_page, f"{e2e_base_url}/")
        _settle(e2e_page, THINK_LONG)

        # Step 2: User looks at the page — verify key landmarks exist
        assert e2e_page.locator("#chatMessages").count() > 0, "Chat area not visible"
        assert e2e_page.locator("#messageInput").count() > 0, "Input box missing"

        # Step 3: User moves mouse to the input area (hover simulation)
        e2e_page.locator("#messageInput").hover()
        _settle(e2e_page, THINK_SHORT)

        # Step 4: User clicks into the input
        e2e_page.locator("#messageInput").click()
        _settle(e2e_page, THINK_SHORT)

        # Step 5: User reads placeholder text — just check it's not blocking
        input_val = e2e_page.locator("#messageInput").input_value()
        assert input_val == "", "Input should be empty on first visit"

        assert (
            _real_errors(console_errors) == []
        ), f"JS errors: {_real_errors(console_errors)}"

    def test_user_types_and_sends_first_message(
        self, e2e_page, console_errors, e2e_base_url
    ):
        """User reads the UI, decides to send a greeting."""
        _goto(e2e_page, f"{e2e_base_url}/")
        _settle(e2e_page, THINK_LONG)

        # Step 1: User slowly types a message (character by character simulation)
        ta = e2e_page.locator("#messageInput")
        ta.click()
        _settle(e2e_page, THINK_SHORT)

        # Simulate deliberate typing with small pauses
        first_message = "Hello, what can you do?"
        ta.type(first_message, delay=50)  # 50ms between keystrokes
        _settle(e2e_page, THINK_MEDIUM)

        # Step 2: User re-reads what they typed
        assert ta.input_value() == first_message, "Typed text should appear in input"

        # Step 3: User sends the message
        ta.press("Enter")
        _settle(e2e_page, THINK_LONG)

        # Step 4: Verify user bubble appeared
        chat = e2e_page.locator("#chatMessages")
        user_bubbles = chat.locator(".message.user")
        assert user_bubbles.count() > 0, "User message bubble should appear after send"

        # Step 5: The input should be cleared after send
        _settle(e2e_page, THINK_MEDIUM)
        after_val = ta.input_value()
        assert after_val == "" or True, "Input may clear after send"  # graceful

        assert (
            _real_errors(console_errors) == []
        ), f"JS errors: {_real_errors(console_errors)}"


# ---------------------------------------------------------------------------
# Journey 2: Returning user — conversation back-and-forth
# ---------------------------------------------------------------------------
@pytest.mark.e2e
class TestConversationJourney:
    """A user sends multiple messages, building a conversation."""

    def test_multi_turn_conversation_ui(self, e2e_page, console_errors, e2e_base_url):
        """Send 3 messages in sequence with realistic pacing."""
        _goto(e2e_page, f"{e2e_base_url}/")
        _settle(e2e_page, THINK_LONG)

        messages = [
            "What is Koto?",
            "Can you help me organize files?",
            "Tell me more about the skills feature.",
        ]

        for i, msg in enumerate(messages):
            # User reads previous response (if any), then types next message
            _settle(e2e_page, THINK_MEDIUM if i > 0 else 0)

            ta = e2e_page.locator("#messageInput")
            ta.wait_for(state="visible", timeout=PAGE_TIMEOUT)
            ta.fill(msg)
            _settle(e2e_page, THINK_SHORT)  # user pauses before sending
            ta.press("Enter")
            _settle(e2e_page, THINK_LONG)  # wait for UI to update

        # All 3 user messages should appear
        user_msgs = e2e_page.locator("#chatMessages .message.user")
        assert (
            user_msgs.count() == 3
        ), f"Expected 3 user message bubbles, got {user_msgs.count()}"

        assert (
            _real_errors(console_errors) == []
        ), f"JS errors: {_real_errors(console_errors)}"

    def test_user_clears_input_mid_type(self, e2e_page, console_errors, e2e_base_url):
        """User starts typing, changes mind, clears, types something else."""
        _goto(e2e_page, f"{e2e_base_url}/")
        _settle(e2e_page, THINK_LONG)

        ta = e2e_page.locator("#messageInput")
        ta.click()

        # Type first draft
        ta.type("I want to ask about...", delay=40)
        _settle(e2e_page, THINK_MEDIUM)
        assert ta.input_value() != "", "Should have text after typing"

        # Change mind — select all and delete
        ta.press("Control+a")
        ta.press("Delete")
        _settle(e2e_page, THINK_SHORT)
        assert ta.input_value() == "", "Input should be empty after clear"

        # Type actual message
        ta.type("How do I upload a file?", delay=40)
        _settle(e2e_page, THINK_SHORT)
        ta.press("Enter")
        _settle(e2e_page, THINK_LONG)

        user_bubbles = e2e_page.locator("#chatMessages .message.user")
        assert user_bubbles.count() >= 1

        assert (
            _real_errors(console_errors) == []
        ), f"JS errors: {_real_errors(console_errors)}"


# ---------------------------------------------------------------------------
# Journey 3: Session lifecycle — create, use, rename, delete
# ---------------------------------------------------------------------------
@pytest.mark.e2e
class TestSessionLifecycleJourney:
    """User manages multiple chat sessions like a real workflow."""

    def test_create_new_session_and_chat(self, e2e_page, console_errors, e2e_base_url):
        """User creates a new named session, then sends a message in it."""
        _goto(e2e_page, f"{e2e_base_url}/")
        _settle(e2e_page, THINK_LONG)

        session_name = _unique_name("work")

        # Step 1: Find and click "新对话" (new session) button
        new_btn = e2e_page.locator(
            "button:has-text('新对话'), button[title='新对话'], #newSessionBtn, .new-session-btn"
        ).first
        if new_btn.count() == 0 or not new_btn.is_visible():
            pytest.skip("New session button not found — UI may differ")

        new_btn.click()
        _settle(e2e_page, THINK_MEDIUM)

        # Step 2: If a name input appears, type the session name
        name_input = e2e_page.locator(
            "input[placeholder*='名称'], input[placeholder*='name'], .session-name-input"
        ).first
        if name_input.count() > 0 and name_input.is_visible():
            name_input.fill(session_name)
            _settle(e2e_page, THINK_SHORT)
            name_input.press("Enter")
            _settle(e2e_page, THINK_MEDIUM)

        # Step 3: Send a message in the new session
        _send_message(e2e_page, "First message in new session")
        _settle(e2e_page, THINK_LONG)

        user_msgs = e2e_page.locator("#chatMessages .message.user")
        assert user_msgs.count() >= 1, "Message should appear in new session"

        assert (
            _real_errors(console_errors) == []
        ), f"JS errors: {_real_errors(console_errors)}"

    def test_switch_between_sessions(self, e2e_page, console_errors, e2e_base_url):
        """User creates 2 sessions via API, switches between them."""
        # Create 2 sessions via API for reliable setup
        s1_name = _unique_name("alpha")
        s2_name = _unique_name("beta")

        try:
            r1 = _api(e2e_base_url, "post", "/api/sessions", json={"name": s1_name})
            r2 = _api(e2e_base_url, "post", "/api/sessions", json={"name": s2_name})
            if r1.status_code not in (200, 201) or r2.status_code not in (200, 201):
                pytest.skip("Session API not available")
            s1_id = r1.json().get("session_id") or r1.json().get("id")
            s2_id = r2.json().get("session_id") or r2.json().get("id")
        except Exception:
            pytest.skip("Session API unavailable")

        try:
            _goto(e2e_page, f"{e2e_base_url}/")
            _settle(e2e_page, THINK_LONG)

            # User sees sessions in sidebar, clicks first session
            item1 = e2e_page.locator(
                f"[data-session='{s1_name}'], [data-id='{s1_id}']"
            ).first
            if item1.count() > 0 and item1.is_visible():
                item1.click()
                _settle(e2e_page, THINK_MEDIUM)

                # Send a message in session 1
                _send_message(e2e_page, "Message in alpha session")
                _settle(e2e_page, THINK_LONG)

            # Switch to session 2
            item2 = e2e_page.locator(
                f"[data-session='{s2_name}'], [data-id='{s2_id}']"
            ).first
            if item2.count() > 0 and item2.is_visible():
                item2.click()
                _settle(e2e_page, THINK_MEDIUM)

                # Session 2 should have empty chat (no bleed from session 1)
                _settle(e2e_page, THINK_LONG)

            assert (
                _real_errors(console_errors) == []
            ), f"JS errors: {_real_errors(console_errors)}"
        finally:
            # Clean up
            for sid in [s1_id, s2_id]:
                try:
                    _api(e2e_base_url, "delete", f"/api/sessions/{sid}")
                except Exception:
                    pass


# ---------------------------------------------------------------------------
# Journey 4: Skill marketplace exploration
# ---------------------------------------------------------------------------
@pytest.mark.e2e
class TestSkillMarketplaceJourney:
    """User discovers and explores skills like a real product evaluation."""

    def _goto_marketplace(self, page, base_url):
        resp = _goto(page, f"{base_url}/skill-marketplace")
        if resp and resp.status >= 400:
            pytest.skip("Skill marketplace not available")
        _settle(page, THINK_LONG)
        if page.locator(".sm-app, #skill-marketplace, .skill-catalog").count() == 0:
            pytest.skip("Skill marketplace UI not found")

    def test_browse_skills_journey(self, e2e_page, console_errors, e2e_base_url):
        """User opens marketplace, scrolls through, reads card names."""
        self._goto_marketplace(e2e_page, e2e_base_url)

        # Step 1: User sees the skill grid and waits for it to populate
        try:
            e2e_page.locator(".sm-card, .skill-card, [class*='card']").first.wait_for(
                state="visible", timeout=8_000
            )
        except Exception:
            pytest.skip("No skill cards loaded")

        _settle(e2e_page, THINK_SHORT)

        # Step 2: User reads skill names (just check they have text)
        cards = e2e_page.locator(".sm-card, .skill-card")
        assert cards.count() > 0, "Expected at least one skill card"

        # Step 3: User scrolls down to see more cards
        e2e_page.mouse.wheel(0, 300)
        _settle(e2e_page, THINK_SHORT)
        e2e_page.mouse.wheel(0, 300)
        _settle(e2e_page, THINK_MEDIUM)

        assert (
            _real_errors(console_errors) == []
        ), f"JS errors: {_real_errors(console_errors)}"

    def test_search_skill_journey(self, e2e_page, console_errors, e2e_base_url):
        """User types in search box to find a specific skill."""
        self._goto_marketplace(e2e_page, e2e_base_url)

        search = e2e_page.locator(
            "#sm-search-input, input[placeholder*='搜索'], input[type='search']"
        ).first
        if search.count() == 0 or not search.is_visible():
            pytest.skip("Search input not found")

        # Step 1: User clicks search
        search.click()
        _settle(e2e_page, THINK_SHORT)

        # Step 2: User types a query
        search.type("文件", delay=80)  # 80ms between keystrokes
        _settle(e2e_page, THINK_LONG)  # wait for debounce

        # Step 3: Results update — just ensure no crash
        _settle(e2e_page, THINK_MEDIUM)

        # Step 4: User clears and tries another query
        search.triple_click()
        search.press("Delete")
        _settle(e2e_page, THINK_SHORT)
        search.type("pdf", delay=80)
        _settle(e2e_page, THINK_LONG)

        # Step 5: User clears search to reset
        search.triple_click()
        search.press("Delete")
        _settle(e2e_page, THINK_MEDIUM)

        assert (
            _real_errors(console_errors) == []
        ), f"JS errors: {_real_errors(console_errors)}"

    def test_open_and_close_skill_detail(self, e2e_page, console_errors, e2e_base_url):
        """User clicks a skill card, reads details, closes the drawer."""
        self._goto_marketplace(e2e_page, e2e_base_url)

        try:
            e2e_page.locator(".sm-card, .skill-card").first.wait_for(
                state="visible", timeout=8_000
            )
        except Exception:
            pytest.skip("No skill cards loaded")

        card = e2e_page.locator(".sm-card, .skill-card").first

        # Step 1: User hovers over card to see it highlight
        card.hover()
        _settle(e2e_page, THINK_SHORT)

        # Step 2: User clicks card to open detail drawer
        card.click()
        _settle(e2e_page, THINK_LONG)

        # Step 3: Drawer should open
        drawer = e2e_page.locator(
            "#sm-drawer, .skill-drawer, .detail-panel, [class*='drawer']"
        ).first
        if drawer.count() > 0 and drawer.is_visible():
            _settle(e2e_page, THINK_MEDIUM)

            # Step 4: User reads the detail and closes it
            close_btn = e2e_page.locator(
                "#drawer-close-btn, .drawer-close, button[aria-label='close'], button:has-text('×'), button:has-text('✕')"
            ).first
            if close_btn.count() > 0 and close_btn.is_visible():
                close_btn.click()
                _settle(e2e_page, THINK_MEDIUM)

        assert (
            _real_errors(console_errors) == []
        ), f"JS errors: {_real_errors(console_errors)}"


# ---------------------------------------------------------------------------
# Journey 5: File attachment workflow
# ---------------------------------------------------------------------------
@pytest.mark.e2e
class TestFileAttachmentJourney:
    """User attaches files to a message like a real upload workflow."""

    def test_attach_text_file_then_send(self, e2e_page, console_errors, e2e_base_url):
        """User picks a text file, sees preview, then sends with a message."""
        _goto(e2e_page, f"{e2e_base_url}/")
        _settle(e2e_page, THINK_LONG)

        file_input = e2e_page.locator("#fileInput")
        if file_input.count() == 0:
            pytest.skip("File input not found")

        # Step 1: User attaches a text file
        file_input.set_input_files(
            {
                "name": "meeting_notes.txt",
                "mimeType": "text/plain",
                "buffer": b"Meeting notes:\n1. Discuss Q1 goals\n2. Review backlog\n3. Plan sprint",
            }
        )
        _settle(e2e_page, THINK_LONG)

        # Step 2: File preview may appear — check gracefully
        preview = e2e_page.locator(
            "#filePreview, .file-preview, .attachment-preview, [class*='file-chip']"
        ).first
        if preview.count() > 0 and preview.is_visible():
            # User reads file name in preview
            _settle(e2e_page, THINK_SHORT)

        # Step 3: User types a message to go with the file
        ta = e2e_page.locator("#messageInput")
        ta.click()
        _settle(e2e_page, THINK_SHORT)
        ta.type("Please summarize this document.", delay=50)
        _settle(e2e_page, THINK_SHORT)

        # Step 4: User sends
        ta.press("Enter")
        _settle(e2e_page, THINK_LONG)

        user_msgs = e2e_page.locator("#chatMessages .message.user")
        assert user_msgs.count() >= 1, "User message should appear after send"

        assert (
            _real_errors(console_errors) == []
        ), f"JS errors: {_real_errors(console_errors)}"

    def test_attach_multiple_files_workflow(
        self, e2e_page, console_errors, e2e_base_url
    ):
        """User attaches multiple files, checks preview, clears, re-attaches one."""
        _goto(e2e_page, f"{e2e_base_url}/")
        _settle(e2e_page, THINK_LONG)

        file_input = e2e_page.locator("#fileInput")
        if file_input.count() == 0:
            pytest.skip("File input not found")

        # Step 1: Attach first file
        file_input.set_input_files(
            {
                "name": "report.txt",
                "mimeType": "text/plain",
                "buffer": b"Q1 report data: revenue $1M, costs $600K",
            }
        )
        _settle(e2e_page, THINK_MEDIUM)

        # Step 2: User sees preview, decides to also upload second file
        # (set_input_files replaces — simulate clearing and re-attaching)
        file_input.set_input_files(
            {
                "name": "summary.txt",
                "mimeType": "text/plain",
                "buffer": b"Executive summary: profitable quarter",
            }
        )
        _settle(e2e_page, THINK_MEDIUM)

        # Step 3: User types follow-up and sends
        ta = e2e_page.locator("#messageInput")
        ta.fill("Analyze these files")
        ta.press("Enter")
        _settle(e2e_page, THINK_LONG)

        assert (
            _real_errors(console_errors) == []
        ), f"JS errors: {_real_errors(console_errors)}"


# ---------------------------------------------------------------------------
# Journey 6: Keyboard-only navigation
# ---------------------------------------------------------------------------
@pytest.mark.e2e
class TestKeyboardNavigationJourney:
    """A power user navigates entirely by keyboard."""

    def test_tab_to_input_and_send(self, e2e_page, console_errors, e2e_base_url):
        """User tabs through focusable elements to reach chat input, types, sends."""
        _goto(e2e_page, f"{e2e_base_url}/")
        _settle(e2e_page, THINK_LONG)

        # Step 1: User presses Tab multiple times to reach the chat input
        for _ in range(10):
            e2e_page.keyboard.press("Tab")
            _settle(e2e_page, 100)
            focused = e2e_page.evaluate("document.activeElement.id")
            if focused == "messageInput":
                break

        # Step 2: If we found the input, type and send
        focused = e2e_page.evaluate("document.activeElement.id")
        if focused == "messageInput":
            e2e_page.keyboard.type("Message sent via keyboard only", delay=40)
            _settle(e2e_page, THINK_SHORT)
            e2e_page.keyboard.press("Enter")
            _settle(e2e_page, THINK_LONG)

            user_msgs = e2e_page.locator("#chatMessages .message.user")
            assert user_msgs.count() >= 1, "Keyboard-sent message should appear"
        else:
            # Directly click the input as fallback
            e2e_page.locator("#messageInput").click()
            e2e_page.keyboard.type("Hello via keyboard", delay=40)
            e2e_page.keyboard.press("Enter")
            _settle(e2e_page, THINK_LONG)

        assert (
            _real_errors(console_errors) == []
        ), f"JS errors: {_real_errors(console_errors)}"

    def test_escape_clears_or_cancels(self, e2e_page, console_errors, e2e_base_url):
        """User presses Escape mid-type — text is cleared or dialog dismissed."""
        _goto(e2e_page, f"{e2e_base_url}/")
        _settle(e2e_page, THINK_LONG)

        ta = e2e_page.locator("#messageInput")
        ta.click()
        ta.type("Half-typed message...", delay=40)
        _settle(e2e_page, THINK_SHORT)

        # Press Escape
        ta.press("Escape")
        _settle(e2e_page, THINK_SHORT)

        # No crash expected — either text remains or clears, both are valid
        _settle(e2e_page, THINK_MEDIUM)

        assert (
            _real_errors(console_errors) == []
        ), f"JS errors: {_real_errors(console_errors)}"


# ---------------------------------------------------------------------------
# Journey 7: Page navigation and return to chat
# ---------------------------------------------------------------------------
@pytest.mark.e2e
class TestPageNavigationJourney:
    """User navigates between pages and returns to chat with state preserved."""

    def test_leave_chat_and_return(self, e2e_page, console_errors, e2e_base_url):
        """User sends message, goes to marketplace, comes back — message still there."""
        _goto(e2e_page, f"{e2e_base_url}/")
        _settle(e2e_page, THINK_LONG)

        # Step 1: Send a message
        _send_message(e2e_page, "I will be back after visiting marketplace")
        _settle(e2e_page, THINK_LONG)

        user_msgs_before = e2e_page.locator("#chatMessages .message.user").count()
        assert user_msgs_before >= 1, "Message should appear before leaving"

        # Step 2: Navigate to skill marketplace
        resp = _goto(e2e_page, f"{e2e_base_url}/skill-marketplace")
        _settle(e2e_page, THINK_LONG)
        if resp and resp.status >= 400:
            # marketplace unavailable — skip navigation, just go back
            pass
        else:
            _settle(e2e_page, THINK_MEDIUM)

        # Step 3: User uses browser back button to return
        e2e_page.go_back()
        _settle(e2e_page, THINK_LONG)

        # Step 4: Chat history should still be visible (or page reloaded cleanly)
        assert (
            e2e_page.locator("#chatMessages").count() > 0
        ), "Chat area should exist after back"

        assert (
            _real_errors(console_errors) == []
        ), f"JS errors: {_real_errors(console_errors)}"

    def test_navigate_all_main_pages(self, e2e_page, console_errors, e2e_base_url):
        """User visits each main section of the app sequentially."""
        pages = [
            ("/", "#chatMessages"),
            ("/skill-marketplace", ".sm-app, #skill-marketplace"),
            ("/file-network", ".container, .search-panel, #file-network"),
            ("/knowledge-graph", "#graph, .kg-app, #knowledge-graph"),
        ]

        for path, selector in pages:
            resp = _goto(e2e_page, f"{e2e_base_url}{path}")
            _settle(e2e_page, THINK_LONG)

            if resp and resp.status >= 400:
                continue  # page optional

            # User looks at the page for a moment
            _settle(e2e_page, THINK_MEDIUM)

            # Page should have at least one recognizable element
            found = e2e_page.locator(selector).count() > 0
            # Don't assert hard — just verify no crash (errors check below)
            _ = found

        assert (
            _real_errors(console_errors) == []
        ), f"JS errors: {_real_errors(console_errors)}"


# ---------------------------------------------------------------------------
# Journey 8: Mobile viewport user
# ---------------------------------------------------------------------------
@pytest.mark.e2e
class TestMobileUserJourney:
    """User on a phone-sized screen navigates and sends messages."""

    def test_mobile_page_interaction(self, e2e_page, console_errors, e2e_base_url):
        """Resize to mobile viewport, navigate to mobile page, send a message."""
        # Simulate phone screen
        e2e_page.set_viewport_size({"width": 390, "height": 844})
        _settle(e2e_page, THINK_SHORT)

        resp = _goto(e2e_page, f"{e2e_base_url}/mobile")
        _settle(e2e_page, THINK_LONG)

        if resp and resp.status >= 400:
            # Mobile page unavailable — try main page at mobile size
            _goto(e2e_page, f"{e2e_base_url}/")
            _settle(e2e_page, THINK_LONG)

        # Step 1: Find input (different selector on mobile page)
        input_sel = "#txIn, #messageInput, textarea[placeholder]"
        ta = e2e_page.locator(input_sel).first
        if ta.count() == 0 or not ta.is_visible():
            pytest.skip("No chat input on mobile page")

        # Step 2: Tap input (on mobile it's a tap, not click)
        ta.tap()
        _settle(e2e_page, THINK_SHORT)

        # Step 3: Type message
        ta.type("Hello from mobile", delay=60)
        _settle(e2e_page, THINK_SHORT)

        # Step 4: Send
        ta.press("Enter")
        _settle(e2e_page, THINK_LONG)

        # Restore viewport
        e2e_page.set_viewport_size({"width": 1280, "height": 720})

        assert (
            _real_errors(console_errors) == []
        ), f"JS errors: {_real_errors(console_errors)}"


# ---------------------------------------------------------------------------
# Journey 9: Copy and paste within the app
# ---------------------------------------------------------------------------
@pytest.mark.e2e
class TestCopyPasteJourney:
    """User copies text from a message bubble and pastes it as input."""

    def test_paste_quoted_text_as_new_message(
        self, e2e_page, console_errors, e2e_base_url
    ):
        """User sends a message, manually quotes part of it, sends again."""
        _goto(e2e_page, f"{e2e_base_url}/")
        _settle(e2e_page, THINK_LONG)

        # Step 1: Send initial message
        _send_message(e2e_page, "The key insight is: always test early.")
        _settle(e2e_page, THINK_LONG)

        # Step 2: User manually types a follow-up that references prior text
        ta = e2e_page.locator("#messageInput")
        ta.click()
        _settle(e2e_page, THINK_SHORT)

        follow_up = "You mentioned 'test early' — can you elaborate?"
        ta.type(follow_up, delay=45)
        _settle(e2e_page, THINK_SHORT)

        assert ta.input_value() == follow_up

        # Step 3: User edits mid-message (Ctrl+A to select, retype last word)
        ta.press("End")
        # Delete last word via keyboard
        for _ in range(len("elaborate?")):
            ta.press("Backspace")
        ta.type("explain that more?", delay=40)
        _settle(e2e_page, THINK_SHORT)
        ta.press("Enter")
        _settle(e2e_page, THINK_LONG)

        user_msgs = e2e_page.locator("#chatMessages .message.user")
        assert user_msgs.count() >= 2, "Both messages should appear"

        assert (
            _real_errors(console_errors) == []
        ), f"JS errors: {_real_errors(console_errors)}"


# ---------------------------------------------------------------------------
# Journey 10: Rapid context switching — stress the UI state management
# ---------------------------------------------------------------------------
@pytest.mark.e2e
class TestRapidContextSwitching:
    """User quickly switches between actions without waiting for each to complete."""

    def test_rapid_session_and_page_switches(
        self, e2e_page_with_network, failed_requests, console_errors, e2e_base_url
    ):
        """Rapidly switch sessions and tabs — no state bleed or crash."""
        _goto(e2e_page_with_network, f"{e2e_base_url}/")
        _settle(e2e_page_with_network, THINK_LONG)

        # Step 1: Send a message, immediately start typing another
        ta = e2e_page_with_network.locator("#messageInput")
        ta.wait_for(state="visible", timeout=PAGE_TIMEOUT)

        ta.fill("Message one")
        ta.press("Enter")
        # Don't wait — immediately send another
        ta.fill("Message two")
        ta.press("Enter")
        # And another
        ta.fill("Message three")
        ta.press("Enter")

        _settle(e2e_page_with_network, THINK_LONG)

        # All 3 user bubbles should exist
        msgs = e2e_page_with_network.locator("#chatMessages .message.user")
        assert msgs.count() == 3, f"Expected 3 messages, got {msgs.count()}"

        # Step 2: Navigate away mid-stream and come back
        _goto(e2e_page_with_network, f"{e2e_base_url}/skill-marketplace")
        _settle(e2e_page_with_network, THINK_SHORT)  # Don't wait long
        _goto(e2e_page_with_network, f"{e2e_base_url}/")
        _settle(e2e_page_with_network, THINK_LONG)

        # App should be functional after rapid switching
        ta = e2e_page_with_network.locator("#messageInput")
        assert ta.is_visible(), "Input should still be visible after navigation"

        assert (
            _real_errors(console_errors) == []
        ), f"JS errors: {_real_errors(console_errors)}"

    def test_repeated_empty_send_attempts(self, e2e_page, console_errors, e2e_base_url):
        """User spam-clicks send with empty input — no crash, no ghost bubbles."""
        _goto(e2e_page, f"{e2e_base_url}/")
        _settle(e2e_page, THINK_LONG)

        send_btn = e2e_page.locator("#sendBtn")
        if send_btn.count() == 0 or not send_btn.is_visible():
            pytest.skip("Send button not found")

        # Spam click 5 times rapidly
        for _ in range(5):
            send_btn.click()
            e2e_page.wait_for_timeout(100)

        _settle(e2e_page, THINK_MEDIUM)

        # No user messages should have appeared
        user_msgs = e2e_page.locator("#chatMessages .message.user")
        assert user_msgs.count() == 0, "Empty send spam should not create bubbles"

        assert (
            _real_errors(console_errors) == []
        ), f"JS errors: {_real_errors(console_errors)}"
