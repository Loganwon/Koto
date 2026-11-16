from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.core.llm.local_model_runtime import OllamaRuntime


@pytest.fixture(autouse=True)
def _reset_runtime():
    OllamaRuntime._available = None
    OllamaRuntime._check_time = 0
    OllamaRuntime.reset_response_model()
    yield
    OllamaRuntime._available = None
    OllamaRuntime._check_time = 0
    OllamaRuntime.reset_response_model()


def test_runtime_is_transport_only():
    assert not hasattr(OllamaRuntime, "classify")
    assert not hasattr(OllamaRuntime, "classify_v2")
    assert not hasattr(OllamaRuntime, "is_simple_query")
    assert not hasattr(OllamaRuntime, "generate_plan")


def test_availability_uses_cached_socket_result(mocker):
    sock = mocker.MagicMock()
    sock.connect_ex.return_value = 0
    socket_factory = mocker.patch("socket.socket", return_value=sock)

    assert OllamaRuntime.is_available() is True
    assert OllamaRuntime.is_available() is True
    assert socket_factory.call_count == 1


def test_cloud_deployment_disables_local_runtime(monkeypatch):
    monkeypatch.setenv("KOTO_DEPLOY_MODE", "cloud")
    assert OllamaRuntime.is_available() is False


def test_pick_best_chat_model_uses_explicit_installed_list():
    assert OllamaRuntime.pick_best_chat_model(["llama3.2:3b", "qwen3:8b"]) == "qwen3:8b"
    assert OllamaRuntime.pick_best_chat_model(["custom:latest"]) == "custom:latest"
    assert OllamaRuntime.pick_best_chat_model([]) == ""


def test_configured_response_model_is_respected(monkeypatch):
    monkeypatch.setattr(
        "app.core.llm.local_model_runtime.get_configured_local_model_tag",
        lambda: "chosen:latest",
    )
    monkeypatch.setattr(
        OllamaRuntime,
        "_installed_models",
        classmethod(lambda cls: ["chosen:latest", "qwen3:8b"]),
    )

    assert OllamaRuntime._init_response_model() is True
    assert OllamaRuntime._response_model == "chosen:latest"


def test_call_chat_strips_hidden_thinking(mocker):
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {
        "message": {"content": "<think>private reasoning</think>answer"}
    }
    mocker.patch(
        "app.core.llm.local_model_runtime.requests.post", return_value=response
    )

    content, error = OllamaRuntime.call_chat(
        [{"role": "user", "content": "hello"}], model_name="qwen3:8b"
    )

    assert error is None
    assert content == "answer"


def test_call_chat_reports_http_failure(mocker):
    response = MagicMock(status_code=500, text="failed")
    mocker.patch(
        "app.core.llm.local_model_runtime.requests.post", return_value=response
    )

    content, error = OllamaRuntime.call_chat(
        [{"role": "user", "content": "hello"}], model_name="qwen3:8b"
    )

    assert content == ""
    assert "HTTP 500" in str(error)
