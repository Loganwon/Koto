from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.diagnostics.failure_replay import (
    REPLAY_KEYS,
    build_failure_replay_case,
    validate_failure_replay_case,
)
from scripts.run_p6_failure_replay import REPLAY_TESTS, load_cases, selectors_for_cases


def test_failure_capture_redacts_identity_paths_and_secrets():
    case = build_failure_replay_case(
        {
            "type": "runtime_error",
            "level": "error",
            "message": (
                "user@example.com failed at C:\\Users\\Alice\\秘密\\report.docx "
                "with Bearer abc.def.ghi and sk-live-supersecret"
            ),
            "session_id": "private-session-123",
            "details": {
                "apiKey": "sk-private-value",
                "url": "https://service.invalid/run?token=private-token",
                "ip": "203.0.113.7",
            },
        },
        replay_key="docx.large_review",
        surface="docx",
        operation="load_comments_and_revisions",
    )
    serialized = json.dumps(case, ensure_ascii=False)

    for secret in (
        "user@example.com",
        "Alice",
        "private-session-123",
        "abc.def.ghi",
        "sk-live-supersecret",
        "sk-private-value",
        "private-token",
        "203.0.113.7",
    ):
        assert secret not in serialized
    assert "[path]" in serialized
    assert "[redacted]" in serialized
    validate_failure_replay_case(case)


def test_replay_rejects_unknown_commands_and_keys():
    with pytest.raises(ValueError, match="unsupported replay key"):
        build_failure_replay_case(
            {"type": "error"},
            replay_key="shell.run_arbitrary_command",
            surface="unknown",
            operation="unknown",
        )


def test_p6_replay_corpus_is_complete_and_allowlisted():
    path = Path("tests/replay/p6_anonymized_failures.json")
    cases = load_cases(path)

    assert len(cases) == 8
    assert {case["replay_key"] for case in cases} == REPLAY_KEYS
    assert set(REPLAY_TESTS) == REPLAY_KEYS
    selectors = selectors_for_cases(cases)
    assert len(selectors) == 8
    assert all(Path(selector.split("::", 1)[0]).is_file() for selector in selectors)
