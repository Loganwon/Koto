from pathlib import Path


def test_system_handler_respects_non_retryable_local_executor_failures():
    source = Path("web/services/chat_stream/generate/system_handler.py").read_text(
        encoding="utf-8"
    )

    assert "Utils.is_failure_output(response_text)" in source
    assert 'exec_result.get("retryable") is not False' in source
