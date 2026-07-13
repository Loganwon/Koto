from web.document_feedback_ai_call import call_with_timeout


def test_call_with_timeout_returns_provider_response() -> None:
    response, error = call_with_timeout(
        lambda contents: {"echo": contents}, "review", 1
    )

    assert response == {"echo": "review"}
    assert error is None


def test_call_with_timeout_preserves_provider_error() -> None:
    def failing_call(_contents: str):
        raise RuntimeError("provider unavailable")

    response, error = call_with_timeout(failing_call, "review", 1)

    assert response is None
    assert isinstance(error, RuntimeError)
