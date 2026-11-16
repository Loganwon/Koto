import json
import threading

import httpx
import pytest

from companion.embedded import EmbeddedAPI, PaneServer


class API:
    host = "word"

    def __init__(self):
        self.stop_calls = 0

    def fork(self, host, documents):
        return API()

    def status(self):
        return {"settings": {"configured": True, "provider": "DeepSeek"}}

    def stop(self):
        self.stop_calls += 1
        return {"ok": True}


@pytest.fixture
def pane_server():
    server = PaneServer(API())
    server.sessions["test-channel"] = server.api
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


def test_embedded_page_uses_shared_ui_and_native_host_transport(pane_server):
    response = httpx.get(pane_server.origin + "/ui/")
    assert response.status_code == 200
    assert "bridge.js" in response.text and "KOTO_EMBEDDED=" in response.text
    assert "DS_KEY" not in response.text and "api_key" not in response.text
    assert response.headers["x-frame-options"] == "DENY"
    assert "window.pywebview" in httpx.get(pane_server.origin + "/ui/bridge.js").text
    assert "CreateTaskPane" in httpx.get(pane_server.origin + "/wps/main.js").text


def test_mutations_require_token_same_origin_and_allowlisted_methods(pane_server):
    url = pane_server.origin + "/api/stop"
    assert httpx.post(url, json=[]).status_code == 403
    headers = {"X-Koto-Token": pane_server.token, "X-Koto-Channel": "test-channel"}
    assert (
        httpx.post(
            url, json=[], headers={**headers, "Origin": "https://attacker.test"}
        ).status_code
        == 403
    )
    assert httpx.post(url, json=[], headers=headers).json() == {"ok": True}
    assert (
        httpx.post(
            pane_server.origin + "/api/_close", json=[], headers=headers
        ).status_code
        == 404
    )
    assert httpx.post(url, json={}, headers=headers).status_code == 400
    assert (
        httpx.get(pane_server.origin + "/../../config/deepseek_config.env").status_code
        == 404
    )


def test_embedded_file_drawer_never_resizes_an_external_window():
    api = EmbeddedAPI("word")
    assert api.set_files_open(True)["ok"]
    assert api.host == "word"


def test_rejected_post_has_readable_http_response_with_unread_body_on_windows(
    pane_server,
):
    with httpx.Client(trust_env=False) as client:
        for _ in range(5):
            response = client.post(
                pane_server.origin + "/api/stop", content=b"x" * 100000
            )
            assert response.status_code == 403
    assert pane_server.api.stop_calls == 0


def test_attach_and_actions_survive_lost_responses_without_duplicate_sessions(
    pane_server,
):
    headers = {"X-Koto-Token": pane_server.token}
    url = pane_server.origin
    first = httpx.post(
        url + "/host/attach", json=["word", "same-pane"], headers=headers
    ).json()
    second = httpx.post(
        url + "/host/attach", json=["word", "same-pane"], headers=headers
    ).json()
    assert first == second
    headers.update(
        {
            "X-Koto-Channel": first["channel"],
            "X-Koto-Request": "same-action",
            "X-Koto-Sequence": "3",
        }
    )
    for _ in range(2):
        assert httpx.post(url + "/api/stop", json=[], headers=headers).json() == {
            "ok": True
        }
    assert pane_server.sessions[first["channel"]].stop_calls == 1
    assert (
        httpx.post(url + "/api/stop", json=["changed"], headers=headers).status_code
        == 400
    )
    headers["X-Koto-Channel"] = "expired-channel"
    assert httpx.post(url + "/api/stop", json=[], headers=headers).status_code == 403
    assert pane_server.api.stop_calls == 0
