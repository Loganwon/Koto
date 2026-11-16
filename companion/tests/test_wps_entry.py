"""Launcher regressions; native WPS acceptance is recorded separately."""

import base64
import json

import httpx
import pytest

from companion.addins import open_wps


def client_with(monkeypatch, handler):
    real_client = httpx.Client
    monkeypatch.setattr(
        open_wps.httpx,
        "Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )


def test_entry_reuses_healthy_service_without_reading_api_key(tmp_path, monkeypatch):
    settings = tmp_path / "host.json"
    settings.write_text(json.dumps({"port": 19742, "api_key_file": "missing-key.txt"}))
    calls = []

    def request(req):
        calls.append((req.method, str(req.url)))
        return httpx.Response(200, json={"service": "koto-embedded", "protocol": 1})

    client_with(monkeypatch, request)
    monkeypatch.setattr(
        open_wps.subprocess, "Popen", lambda *a, **k: pytest.fail("duplicate service")
    )
    assert open_wps.ensure_service(settings) == "http://127.0.0.1:19742"
    assert calls == [("GET", "http://127.0.0.1:19742/health")]


@pytest.mark.parametrize("lost_reply", [False, True])
def test_entry_only_opens_existing_pane_and_never_retries_dispatch(
    monkeypatch, lost_reply
):
    requests = []

    def request(req):
        requests.append(req)
        assert req.headers["Origin"] == "https://127.0.0.1:19742"
        if req.url.path == "/version":
            return httpx.Response(200, text="1.0.3")
        assert req.url.path == "/transfer/runParams"
        body = json.loads(req.content)
        data = json.loads(
            base64.b64decode(body["data"].removeprefix("ksowebstartupwps://"))
        )
        assert body["app"] == "wps" and body["mode"] is False
        assert data["name"] == "Koto" and data["function"] == "var res = OpenKoto"
        assert data["jsPluginsXml"] == ""  # Do not replace other add-in configuration.
        assert "response: res" in data["info"] and "Documents.Open" not in data["info"]
        if lost_reply:
            raise httpx.ReadTimeout("lost reply", request=req)
        return httpx.Response(200, text="true")

    client_with(monkeypatch, request)
    if lost_reply:
        with pytest.raises(httpx.ReadTimeout):
            open_wps.open_pane("https://127.0.0.1:19742")
    else:
        open_wps.open_pane("https://127.0.0.1:19742")
    assert len(requests) == 2


@pytest.mark.skipif(__import__("os").name != "nt", reason="Windows entry lock")
def test_repeated_shortcut_does_not_queue_a_second_native_open(tmp_path):
    with open_wps.entry_lock(tmp_path) as first:
        assert first
        with open_wps.entry_lock(tmp_path) as second:
            assert not second
    with open_wps.entry_lock(tmp_path) as after_completion:
        assert after_completion


def test_explicit_refresh_reuses_the_pane_without_opening_a_document():
    request = open_wps.open_request("synthetic-refresh", refresh=True)
    start = json.loads(
        base64.b64decode(request["data"].removeprefix("ksowebstartupwps://"))
    )
    assert "kotoPane.Navigate(" in start["function"]
    from companion.embedded import UI_VERSION

    assert UI_VERSION in start["function"]
    assert "CreateTaskPane" not in start["function"]
    assert "Documents.Open" not in start["function"]
    assert start["jsPluginsXml"] == ""
