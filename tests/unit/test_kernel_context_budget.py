"""Model budget regressions: preserve actual intent, calls, and write facts."""

import copy
import json

import pytest

from app.core.agent.kernel.context_budget import (
    ContextBudgetExceeded,
    estimate_tokens,
    input_token_budget,
    prepare_model_messages,
)


def project(messages, capacity=2200, prompt="只修改第二段"):
    return prepare_model_messages(
        messages,
        system="Use tools and actual receipts.",
        tools=[],
        prompt=prompt,
        options={"context_window_tokens": capacity, "reserved_output_tokens": 256},
    )


def test_small_request_is_unchanged_and_source_is_not_mutated():
    messages = [{"role": "user", "content": "只修改第二段"}]
    result = project(messages)
    assert result.messages == messages
    assert result.messages is not messages
    assert result.compacted is False


def test_explicit_model_capacity_and_output_reservation_are_used(monkeypatch):
    monkeypatch.setenv("KOTO_CONTEXT_WINDOW_TOKENS", "32000")
    assert input_token_budget({"num_ctx": 2048, "max_tokens": 512}) == 1434
    assert (
        input_token_budget({"options": {"num_ctx": 4096, "num_predict": 1024}}) == 2868
    )
    assert estimate_tokens("中" * 10) > estimate_tokens("a" * 10)


def test_history_is_removed_as_whole_turns_without_orphaning_tool_results():
    messages = [
        {"role": "user", "content": "older " * 900},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "old-call", "name": "read_file", "args": {"path": "old.txt"}}
            ],
        },
        {"role": "tool", "tool_call_id": "old-call", "content": "old result"},
        {"role": "assistant", "content": "done"},
        {"role": "user", "content": "只修改第二段"},
    ]
    result = project(messages, 1200)
    assert result.messages == messages[-1:]
    assert result.removed_history_messages == 4
    assert result.estimated_tokens <= result.input_budget


def test_large_result_preserves_call_pair_and_persisted_write_facts():
    receipt = {
        "call_id": "save-1",
        "tool_name": "ui_save",
        "ok": True,
        "value": {
            "saved": True,
            "verified": True,
            "path": "report.docx",
            "new_revision": "v2",
            "content": "材料正文" * 8000,
        },
    }
    messages = [
        {"role": "user", "content": "只修改第二段"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "save-1", "name": "ui_save", "args": {"document_id": "doc-1"}}
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "save-1",
            "name": "ui_save",
            "content": json.dumps(receipt, ensure_ascii=False),
        },
    ]
    original = copy.deepcopy(messages)
    result = project(messages)
    assert messages == original
    assert result.messages[:2] == original[:2]
    shortened = json.loads(result.messages[2]["content"])
    assert shortened["ok"] is True
    assert shortened["value"]["saved"] is True
    assert shortened["value"]["verified"] is True
    assert shortened["value"]["new_revision"] == "v2"
    assert shortened["value"]["context_truncated"] is True
    assert result.reduced_tool_results == 1
    assert result.estimated_tokens <= result.input_budget


def test_failure_receipt_never_becomes_success_when_reduced():
    error = json.dumps(
        {
            "ok": False,
            "call_id": "a",
            "error": {"code": "write_failed", "message": "details " * 9000},
        }
    )
    result = project(
        [
            {"role": "user", "content": "只修改第二段"},
            {"role": "tool", "tool_call_id": "a", "content": error},
        ]
    )
    shortened = json.loads(result.messages[-1]["content"])
    assert shortened["ok"] is False
    assert shortened["error"]["code"] == "write_failed"


def test_protected_user_goal_is_not_truncated_to_make_an_oversized_request_fit():
    prompt = "很长且不可省略的用户要求" * 1000
    with pytest.raises(ContextBudgetExceeded, match="输入预算"):
        project([{"role": "user", "content": prompt}], 1200, prompt)


def test_current_explicit_document_context_is_not_discarded_as_old_history():
    messages = [
        {"role": "user", "content": "Context:\n" + "正文" * 3000},
        {"role": "user", "content": "只修改第二段"},
    ]
    with pytest.raises(ContextBudgetExceeded):
        project(messages, 1200)


def test_tool_arguments_and_validation_retry_keep_original_instruction():
    messages = [
        {"role": "user", "content": "只修改第二段"},
        {"role": "assistant", "content": "draft"},
        {"role": "user", "content": "请依据实际工具回执修正回答"},
    ]
    result = project(messages)
    assert result.messages == messages
    with pytest.raises(ContextBudgetExceeded):
        project(
            [
                messages[0],
                {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": "a",
                            "name": "write_file",
                            "args": {"text": "新正文" * 3000},
                        }
                    ],
                },
            ],
            1200,
        )


def test_impossible_output_reservation_fails_before_model_call():
    with pytest.raises(ContextBudgetExceeded, match="上下文容量不足"):
        input_token_budget({"context_window_tokens": 1024, "max_tokens": 1024})


def test_long_history_is_counted_once_while_preserving_the_exact_budget(monkeypatch):
    from app.core.agent.kernel import context_budget

    messages = []
    for index in range(120):
        messages.extend(
            [
                {"role": "user", "content": f"old task {index}"},
                {"role": "assistant", "content": "archived " + "a" * 900},
            ]
        )
    messages.append({"role": "user", "content": "current task"})
    count = 0

    def measured(value):
        nonlocal count
        count += 1
        return estimate_tokens(value)

    monkeypatch.setattr(context_budget, "estimate_tokens", measured)
    result = prepare_model_messages(
        messages,
        system="system",
        tools=[],
        prompt="current task",
        options={"context_window_tokens": 8192, "reserved_output_tokens": 1024},
    )
    assert count <= len(messages) + 4
    assert result.removed_history_messages > 100
    assert result.messages[-1] == messages[-1]
    expected = (
        estimate_tokens("system")
        + estimate_tokens([])
        + sum(estimate_tokens(message) + 12 for message in result.messages)
    )
    assert result.estimated_tokens == expected <= result.input_budget
