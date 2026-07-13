from app.core.agent.file_task_evidence_guard import (
    requests_verbatim_quote,
    sanitize_unverified_readonly_quotes,
    source_grounding_policy,
)
from app.core.agent.file_task_contract import FileTaskFile, FileTaskRequest
from app.core.agent.file_task_runtime import FileTaskRuntime


def test_source_grounding_policy_requires_evidence_and_forbids_unrequested_quotes():
    policy = source_grounding_policy(task="总结这篇文章", has_source_context=True)

    assert policy["mode"] == "source_grounded"
    assert policy["verbatim_quotes_requested"] is False
    assert any("Do not fabricate" in rule for rule in policy["rules"])
    assert any("quotation marks" in rule for rule in policy["rules"])


def test_quote_guard_only_preserves_quotes_when_user_explicitly_requests_them():
    text = '作者结论：\n> “全球艺术并非普世价值的胜利，而是一场投机游戏。”'

    guarded = sanitize_unverified_readonly_quotes(task="总结文章", text=text)
    assert ">" not in guarded
    assert "“" not in guarded
    assert "概括：全球艺术并非普世价值的胜利" in guarded

    assert requests_verbatim_quote("请引用原文中的一句结论") is True
    assert (
        sanitize_unverified_readonly_quotes(
            task="请引用原文中的一句结论", text=text
        )
        == text
    )


def test_quote_guard_does_not_cross_short_inline_term_quotes():
    text = '“全球艺术”作为概念，与“二元文化世界经济”共同构成文章主线。'

    assert sanitize_unverified_readonly_quotes(task="总结文章", text=text) == text


def test_quote_guard_keeps_inline_prose_unchanged_to_avoid_cross_delimiter_damage():
    text = '作者把“全球艺术”概念与"二元文化世界经济"模型并列讨论。'

    assert sanitize_unverified_readonly_quotes(task="总结文章", text=text) == text


def test_readonly_runtime_downgrades_an_unrequested_block_quote_to_a_summary():
    model_answer = '作者结论：\n> “这一句并没有作为逐字证据提供。”'

    def fake_model(**_kwargs):
        return {"content": model_answer, "tool_calls": []}

    request = FileTaskRequest(
        task="总结这个文档",
        run_id="unverified_quote_guard",
        files=[
            FileTaskFile(
                path="article.docx",
                name="article.docx",
                type="docx",
                content="文档仅提供一段用于总结的正文。",
            )
        ],
    )
    events = list(FileTaskRuntime(tool_executor=lambda *_: "", model_client=fake_model).run(request))
    summary = events[-1].payload["summary"]

    assert ">" not in summary
    assert "“" not in summary
    assert "概括：这一句并没有作为逐字证据提供。" in summary
