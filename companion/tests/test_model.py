import json
import threading

import httpx
import pytest

from companion.contracts import CompanionError, OperationCancelled
from companion.desktop import CompanionAPI
from companion.model import ModelConfig, ToolCallingModel


def config():
    return ModelConfig("https://example.test/v1", "test-model", "private-api-key")


def response(
    text="Edited fragment",
    note="Clearer",
    name="replace_current_text",
    finish="tool_calls",
):
    return {
        "choices": [
            {
                "finish_reason": finish,
                "message": {
                    "tool_calls": [
                        {
                            "function": {
                                "name": name,
                                "arguments": json.dumps({"text": text, "note": note}),
                            }
                        }
                    ]
                },
            }
        ]
    }


def run_model(handler, cancelled=None):
    return ToolCallingModel(config(), httpx.MockTransport(handler)).propose(
        original="Original",
        current="Current",
        instruction="Polish",
        feedback=("Concise",),
        index=0,
        total=2,
        cancelled=cancelled or threading.Event(),
    )


def test_compatible_tool_request_only_sends_bound_fragment():
    def handler(request):
        assert str(request.url) == "https://example.test/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer private-api-key"
        payload = json.loads(request.content)
        context = json.loads(payload["messages"][1]["content"])
        assert context["current_text"] == "Current"
        assert context["feedback"] == ["Concise"]
        assert payload["tools"][0]["function"]["name"] == "replace_current_text"
        return httpx.Response(200, json=response())

    proposal = run_model(handler)
    assert proposal.text == "Edited fragment"


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"choices": []},
        response(name="write_any_file"),
        response(text="one\nnew paragraph"),
        response(text=""),
        response(note=42),
        response(finish="length"),
        {"choices": [{"message": {"content": "I edited the document"}}]},
    ],
)
def test_invalid_or_incomplete_tool_output_cannot_write(body):
    with pytest.raises(CompanionError):
        run_model(lambda request: httpx.Response(200, json=body))


def test_cancelled_request_cannot_deliver_a_late_proposal():
    cancelled = threading.Event()

    def handler(request):
        cancelled.set()
        return httpx.Response(200, json=response())

    with pytest.raises(OperationCancelled):
        run_model(handler, cancelled)


def test_provider_error_and_repr_do_not_expose_key():
    with pytest.raises(CompanionError) as error:
        run_model(
            lambda request: httpx.Response(401, json={"error": "private-api-key"})
        )
    assert "private-api-key" not in str(error.value)
    assert "private-api-key" not in repr(config())


@pytest.mark.parametrize(
    "url",
    [
        "file:///private",
        "https://user:pass@example.test",
        "https://example.test?key=secret",
        "https://example.test#secret",
    ],
)
def test_invalid_api_destination_is_rejected(url):
    with pytest.raises(CompanionError):
        ModelConfig(url, "model", "key").validated()


def test_ui_status_never_returns_key():
    api = CompanionAPI(config())
    state = api.status()
    assert state["settings"]["configured"]
    assert "private-api-key" not in json.dumps(state)
    assert api.configure("https://example.test/v1", "new-model", "")["ok"]
    assert api.status()["settings"]["model"] == "new-model"


def test_switching_endpoint_requires_a_new_explicit_key():
    api = CompanionAPI(config())
    result = api.configure("https://another.test/v1", "model", "")
    assert not result["ok"]
    assert api.status()["settings"]["base_url"] == config().base_url
