"""
E2E test fixtures for Koto UI testing with Playwright.

Starts the Flask app on a dedicated test port and provides
browser fixtures with automatic JS console error collection.
"""

import importlib.util
import json
import os
import signal
import socket
import subprocess
import sys
import time

import pytest
import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
def _select_e2e_port() -> int:
    """Use the requested port, otherwise reserve an unused local test port."""
    configured_port = os.environ.get("KOTO_E2E_PORT")
    if configured_port:
        return int(configured_port)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


E2E_PORT = _select_e2e_port()
E2E_BASE_URL = f"http://127.0.0.1:{E2E_PORT}"
APP_STARTUP_TIMEOUT = 60  # seconds
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PLAYWRIGHT_PREREQ_MESSAGE = (
    "pytest-playwright is not installed. Install `pytest-playwright` and `playwright`, "
    "then run `python -m playwright install chromium` to enable browser E2E tests."
)


def _has_playwright_pytest_plugin() -> bool:
    return importlib.util.find_spec("pytest_playwright") is not None


def _wait_for_server(base_url: str, timeout: int, proc: subprocess.Popen) -> bool:
    """Poll the health endpoint until the server is ready."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            return False
        try:
            r = requests.get(f"{base_url}/api/ping", timeout=5)
            if r.status_code == 200:
                return True
        except (requests.ConnectionError, requests.ReadTimeout, requests.Timeout):
            pass
        time.sleep(1)
    return False


# ---------------------------------------------------------------------------
# Session-scoped fixtures (one server per test session)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def e2e_base_url():
    """Return the base URL for the E2E test server."""
    return E2E_BASE_URL


@pytest.fixture(scope="session")
def _flask_server(e2e_base_url, _protect_user_settings, tmp_path_factory):
    """Start Flask in a child process, wait for readiness, then tear down."""
    source_settings_path = os.path.join(REPO_ROOT, "config", "user_settings.json")
    try:
        with open(source_settings_path, encoding="utf-8-sig") as handle:
            settings_before_start = json.load(handle)
    except Exception:
        settings_before_start = {}
    settings_path = tmp_path_factory.mktemp("koto-e2e-settings") / "user_settings.json"
    if settings_before_start:
        settings_path.write_text(
            json.dumps(settings_before_start, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    env = os.environ.copy()
    env.update(
        {
            "KOTO_PORT": str(E2E_PORT),
            "KOTO_DEPLOY_MODE": "local",
            "KOTO_AUTH_ENABLED": "false",
            "FLASK_DEBUG": "false",
            "GEMINI_API_KEY": env.get("GEMINI_API_KEY", ""),
            "PYTHONIOENCODING": "utf-8",
            "PYTHONPATH": os.pathsep.join([REPO_ROOT, os.path.join(REPO_ROOT, "src")]),
            "KOTO_USER_SETTINGS_PATH": str(settings_path),
        }
    )
    stderr_path = os.path.join(REPO_ROOT, "logs", "e2e_server.log")
    os.makedirs(os.path.dirname(stderr_path), exist_ok=True)
    stderr_file = open(stderr_path, "w", encoding="utf-8")

    proc = subprocess.Popen(
        [sys.executable, os.path.join(REPO_ROOT, "src", "server.py")],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=stderr_file,
    )

    if not _wait_for_server(e2e_base_url, APP_STARTUP_TIMEOUT, proc):
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        try:
            stderr_file.close()
            err_text = open(stderr_path, encoding="utf-8", errors="replace").read()[
                -2000:
            ]
        except Exception:
            err_text = "(could not read stderr)"
        pytest.fail(
            f"Flask server did not become ready within {APP_STARTUP_TIMEOUT}s "
            f"on {e2e_base_url}\n\nServer stderr:\n{err_text}"
        )

    try:
        settings_after_start = requests.get(
            f"{e2e_base_url}/api/settings", timeout=10
        ).json()
        stable_paths = (
            ("appearance", "theme"),
            ("appearance", "ui_zoom"),
            ("ai", "show_thinking"),
            ("ai", "show_task_type"),
            ("ai", "auto_save_files"),
            ("proxy", "enabled"),
        )
        for section, key in stable_paths:
            before_section = settings_before_start.get(section)
            if isinstance(before_section, dict) and key in before_section:
                assert settings_after_start.get(section, {}).get(key) == before_section[key], (
                    f"Server startup rewrote {section}.{key}: "
                    f"{before_section[key]!r} -> "
                    f"{settings_after_start.get(section, {}).get(key)!r}"
                )
    except AssertionError:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        stderr_file.close()
        raise

    yield proc

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    finally:
        stderr_file.close()


@pytest.fixture(scope="session")
def browser_context_args():
    """Playwright browser context defaults."""
    return {
        "viewport": {"width": 1280, "height": 720},
        "ignore_https_errors": True,
    }


if not _has_playwright_pytest_plugin():

    @pytest.fixture()
    def page():
        pytest.skip(PLAYWRIGHT_PREREQ_MESSAGE)


# ---------------------------------------------------------------------------
# Known benign console errors to ignore
# ---------------------------------------------------------------------------
BENIGN_ERROR_PATTERNS = [
    "WebSocket",
    "ws://",
    "wss://",
    "net::ERR_",
    "favicon.ico",
    "API key",
    "api key",
    "Failed to load resource",
    "ERR_CONNECTION_REFUSED",
]


def _is_benign(msg: str) -> bool:
    """Return True if the console error is a known benign message."""
    return any(pat in msg for pat in BENIGN_ERROR_PATTERNS)


# ---------------------------------------------------------------------------
# Per-test fixtures
# ---------------------------------------------------------------------------
@pytest.fixture()
def console_errors():
    """Collector for JS console errors. Tests should assert this list is empty."""
    return []


@pytest.fixture()
def e2e_page(page, _flask_server, e2e_base_url, console_errors):
    """
    A Playwright page wired to the running Flask server with
    automatic console-error capture (filters benign errors).

    Also auto-dismisses the setup wizard by mocking /api/setup/status
    to return initialized=true, so the modal never blocks clicks.

    Usage in tests:
        def test_something(e2e_page, console_errors, e2e_base_url):
            e2e_page.goto(f"{e2e_base_url}/")
            ...
            assert console_errors == [], f"JS errors: {console_errors}"
    """
    # Mock the setup status API so the setup wizard never appears
    page.route(
        "**/api/setup/status",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"initialized": true, "has_api_key": true}',
        ),
    )

    page.on(
        "console",
        lambda msg: (
            console_errors.append(msg.text)
            if msg.type == "error" and not _is_benign(msg.text)
            else None
        ),
    )
    page.on(
        "pageerror",
        lambda exc: (
            console_errors.append(str(exc)) if not _is_benign(str(exc)) else None
        ),
    )
    yield page


@pytest.fixture()
def failed_requests():
    """Collector for failed network requests (HTTP 500+)."""
    return []


@pytest.fixture()
def e2e_page_with_network(e2e_page, failed_requests):
    """
    Like e2e_page but also captures failed network requests (5xx).
    """
    e2e_page.on(
        "response",
        lambda resp: (
            failed_requests.append(f"{resp.status} {resp.url}")
            if resp.status >= 500
            else None
        ),
    )
    yield e2e_page
