from app.core.agent.file_task_readonly_loop_guard import (
    READONLY_ANSWER_GUARD_PENDING_SUMMARY,
    READONLY_DUPLICATE_FALLBACK_SUMMARY,
    WRITE_DUPLICATE_STOP_SUMMARY,
    WRITE_DUPLICATE_SUPERVISOR_SUMMARY,
    answer_only_round,
    discard_answer_only_tool_calls,
    duplicate_guard_tool_payload,
    readonly_duplicate_final_summary,
    readonly_duplicate_guard_reminder,
    should_retry_readonly_answer_guard,
    should_retry_readonly_duplicate_guard,
    should_retry_write_duplicate_guard,
    supervisor_guard_tool_payload,
)


def test_answer_only_round_disables_tools_as_soon_as_readonly_context_is_ready():
    tools = [{"name": "parse_file_to_text"}]

    plan = answer_only_round(
        write_intent=False,
        readonly_answer_guard_injected=False,
        readonly_duplicate_guard_injected=False,
        has_context=True,
        tool_defs=tools,
    )

    assert plan.enabled is True
    assert plan.tool_defs == []


def test_answer_only_round_keeps_tools_for_write_or_missing_context():
    tools = [{"name": "parse_file_to_text"}]

    assert (
        answer_only_round(
            write_intent=True,
            readonly_answer_guard_injected=True,
            readonly_duplicate_guard_injected=False,
            has_context=True,
            tool_defs=tools,
        ).tool_defs
        == tools
    )
    assert (
        answer_only_round(
            write_intent=False,
            readonly_answer_guard_injected=True,
            readonly_duplicate_guard_injected=False,
            has_context=False,
            tool_defs=tools,
        ).tool_defs
        == tools
    )


def test_discard_answer_only_tool_calls_only_in_answer_only_round():
    calls = [{"name": "parse_file_to_text"}]

    discarded = discard_answer_only_tool_calls(
        answer_only=True,
        tool_calls=calls,
    )
    preserved = discard_answer_only_tool_calls(
        answer_only=False,
        tool_calls=calls,
    )

    assert discarded.tool_calls == []
    assert discarded.discarded_count == 1
    assert preserved.tool_calls == calls
    assert preserved.discarded_count == 0


def test_readonly_duplicate_guard_retries_once_before_last_round():
    assert (
        should_retry_readonly_duplicate_guard(
            readonly_duplicate_guard_injected=False,
            round_index=2,
            max_rounds=3,
        )
        is True
    )
    assert (
        should_retry_readonly_duplicate_guard(
            readonly_duplicate_guard_injected=True,
            round_index=2,
            max_rounds=3,
        )
        is False
    )


def test_readonly_answer_guard_retries_only_for_blank_answer_with_context():
    assert (
        should_retry_readonly_answer_guard(
            content_text="",
            has_context=True,
            readonly_answer_guard_injected=False,
            round_index=2,
            max_rounds=3,
        )
        is True
    )
    assert (
        should_retry_readonly_answer_guard(
            content_text="已有答案",
            has_context=True,
            readonly_answer_guard_injected=False,
            round_index=2,
            max_rounds=3,
        )
        is False
    )
    assert (
        should_retry_readonly_answer_guard(
            content_text="",
            has_context=False,
            readonly_answer_guard_injected=False,
            round_index=2,
            max_rounds=3,
        )
        is False
    )
    assert (
        should_retry_readonly_answer_guard(
            content_text="",
            has_context=True,
            readonly_answer_guard_injected=True,
            round_index=2,
            max_rounds=3,
        )
        is False
    )
    assert (
        should_retry_readonly_answer_guard(
            content_text="",
            has_context=True,
            readonly_answer_guard_injected=False,
            round_index=3,
            max_rounds=3,
        )
        is False
    )
    assert "生成可见分析结果" in READONLY_ANSWER_GUARD_PENDING_SUMMARY
    assert (
        should_retry_readonly_duplicate_guard(
            readonly_duplicate_guard_injected=False,
            round_index=3,
            max_rounds=3,
        )
        is False
    )


def test_readonly_duplicate_guard_reminder_includes_task_and_source_lines():
    reminder = readonly_duplicate_guard_reminder(
        task="分析这个文章",
        source_lines=["- 文章主张：操作性身体。"],
    )

    assert "不要再次调用任何工具" in reminder
    assert "用户任务：分析这个文章" in reminder
    assert "已读取内容摘录" in reminder
    assert "操作性身体" in reminder


def test_readonly_duplicate_final_summary_prefers_context_then_content_then_fallback():
    assert (
        readonly_duplicate_final_summary(
            context_summary="上下文总结",
            content_text="模型文本",
        )
        == "上下文总结"
    )
    assert (
        readonly_duplicate_final_summary(
            context_summary="",
            content_text="模型文本",
        )
        == "模型文本"
    )
    assert (
        readonly_duplicate_final_summary(
            context_summary="",
            content_text="",
        )
        == READONLY_DUPLICATE_FALLBACK_SUMMARY
    )


def test_write_duplicate_guard_retries_only_when_write_is_unmodified_and_not_last_round():
    assert (
        should_retry_write_duplicate_guard(
            write_intent=True,
            has_file_changes=False,
            duplicate_supervisor_guard_injected=False,
            round_index=2,
            max_rounds=3,
        )
        is True
    )
    assert (
        should_retry_write_duplicate_guard(
            write_intent=False,
            has_file_changes=False,
            duplicate_supervisor_guard_injected=False,
            round_index=2,
            max_rounds=3,
        )
        is False
    )
    assert (
        should_retry_write_duplicate_guard(
            write_intent=True,
            has_file_changes=True,
            duplicate_supervisor_guard_injected=False,
            round_index=2,
            max_rounds=3,
        )
        is False
    )
    assert (
        should_retry_write_duplicate_guard(
            write_intent=True,
            has_file_changes=False,
            duplicate_supervisor_guard_injected=True,
            round_index=2,
            max_rounds=3,
        )
        is False
    )
    assert (
        should_retry_write_duplicate_guard(
            write_intent=True,
            has_file_changes=False,
            duplicate_supervisor_guard_injected=False,
            round_index=3,
            max_rounds=3,
        )
        is False
    )


def test_write_duplicate_guard_summaries_are_centralized():
    assert "监管层已要求模型回到计划主线" in WRITE_DUPLICATE_SUPERVISOR_SUMMARY
    assert "避免重复写入" in WRITE_DUPLICATE_STOP_SUMMARY


def test_duplicate_guard_tool_payloads_are_centralized():
    assert supervisor_guard_tool_payload("retry") == {
        "tool_name": "supervisor_guard",
        "success": False,
        "skipped": True,
        "result_preview": "retry",
    }
    assert duplicate_guard_tool_payload("stop") == {
        "tool_name": "duplicate_guard",
        "success": True,
        "skipped": True,
        "result_preview": "stop",
    }
