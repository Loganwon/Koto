from __future__ import annotations

import json

from app.core.agent.file_task_completion_gates import (
    apply_declared_incomplete_read_completion_gate,
    apply_readonly_source_coverage_completion_gate,
)
from app.core.agent.file_task_contract import FileTaskFile, FileTaskRequest
from app.core.agent.file_task_evidence_policy import requires_readonly_source_coverage
from app.core.agent.file_task_evidence_validation import (
    answer_declares_incomplete_read,
    missing_readonly_source_coverage,
)
from app.core.agent.file_task_runtime import FileTaskRuntime


def _complete_docx_read(path: str, text: str) -> dict:
    return {
        "tool_name": "read_docx_content",
        "args": {"path": path},
        "result": json.dumps(
            {
                "paragraphs": [{"text": text}],
                "tables": [],
                "total_paragraphs": 1,
                "total_tables": 0,
                "truncated": False,
            }
        ),
    }


def test_read_docx_content_reads_tables_past_previous_twenty_row_cap(tmp_path):
    from docx import Document

    from app.core.agent.task_tools import read_docx_content

    path = tmp_path / "report.docx"
    document = Document()
    table = document.add_table(rows=35, cols=2)
    for index, row in enumerate(table.rows):
        row.cells[0].text = str(index)
        row.cells[1].text = f"content {index}"
    document.save(path)

    payload = json.loads(read_docx_content(str(path), max_chars=120000))

    assert payload["tables"][0]["row_count"] == 35
    assert len(payload["tables"][0]["rows"]) == 35
    assert payload["truncated"] is False


def test_any_readonly_file_answer_declaring_unread_content_cannot_pass():
    payload = apply_declared_incomplete_read_completion_gate(
        check_payload={"passed": True, "status": "verified"},
        files=[FileTaskFile(path="notes.txt", type="txt")],
        final_summary="目前仅看到预览，尚未读取具体内容，建议继续读取。",
        write_intent=False,
    )

    assert payload["passed"] is False
    assert payload["status"] == "analysis_incomplete"
    assert payload["criteria_results"][0]["criterion"] == (
        "declared_file_read_completeness"
    )
    assert answer_declares_incomplete_read("尚未读取报告正文") is True


def test_generic_multi_file_comparison_requires_complete_read_for_every_source():
    files = [
        FileTaskFile(path="a.docx", name="a.docx", type="docx"),
        FileTaskFile(path="b.docx", name="b.docx", type="docx"),
    ]

    assert requires_readonly_source_coverage("比较两个文件的内容差异", files)
    assert missing_readonly_source_coverage(
        files, [_complete_docx_read("a.docx", "A")]
    ) == ["b.docx 的完整读取证据"]


def test_source_coverage_completion_gate_is_domain_neutral():
    files = [
        FileTaskFile(path="a.docx", name="a.docx", type="docx"),
        FileTaskFile(path="b.docx", name="b.docx", type="docx"),
    ]
    payload = apply_readonly_source_coverage_completion_gate(
        check_payload={"passed": True, "status": "verified"},
        task="比较两个文件的内容差异",
        files=files,
        final_summary="已完成比较。",
        readonly_tool_outputs=[_complete_docx_read("a.docx", "A")],
        write_intent=False,
    )

    assert payload["passed"] is False
    assert payload["criteria_results"][0]["criterion"] == "readonly_source_coverage"


def test_runtime_generic_compare_keeps_tools_and_reads_both_documents():
    calls = []
    responses = iter(
        [
            {"content": "只能看到预览，建议继续读取。", "tool_calls": []},
            {
                "content": "读取两个来源。",
                "tool_calls": [
                    {"name": "read_docx_content", "args": {"path": "a.docx"}},
                    {"name": "read_docx_content", "args": {"path": "b.docx"}},
                ],
            },
            {"content": "比较完成：A 强调收入，B 强调利润。", "tool_calls": []},
        ]
    )

    def fake_model(**kwargs):
        calls.append(kwargs)
        return next(responses)

    def fake_executor(tool_name, args):
        assert tool_name == "read_docx_content"
        label = args["path"].split(".", 1)[0].upper()
        return _complete_docx_read(args["path"], label)["result"]

    request = FileTaskRequest(
        task="比较这两个文件的内容差异",
        run_id="generic_compare_complete",
        files=[
            FileTaskFile(path="a.docx", name="a.docx", type="docx", content="A 预览"),
            FileTaskFile(path="b.docx", name="b.docx", type="docx", content="B 预览"),
        ],
    )
    events = list(
        FileTaskRuntime(
            model_client=fake_model,
            tool_executor=fake_executor,
            max_rounds=3,
        ).run(request)
    )

    check = next(event for event in events if event.type == "check.finished")
    run = next(event for event in events if event.type == "run.finished")
    assert all(len(call["tools"]) > 0 for call in calls)
    assert check.payload["passed"] is True
    assert run.payload["completed_task"] is True


def test_runtime_generic_compare_does_not_complete_from_previews_only():
    request = FileTaskRequest(
        task="比较这两个文件的内容差异",
        run_id="generic_compare_incomplete",
        files=[
            FileTaskFile(path="a.docx", name="a.docx", type="docx", content="A 预览"),
            FileTaskFile(path="b.docx", name="b.docx", type="docx", content="B 预览"),
        ],
    )
    events = list(
        FileTaskRuntime(
            model_client=lambda **_: {
                "content": "只能看到两个文件的预览，建议继续读取。",
                "tool_calls": [],
            },
            tool_executor=lambda *_: "",
            max_rounds=2,
        ).run(request)
    )

    check = next(event for event in events if event.type == "check.finished")
    run = next(event for event in events if event.type == "run.finished")
    assert check.payload["status"] == "analysis_incomplete"
    assert check.payload["passed"] is False
    assert run.payload["completed_task"] is False
    assert "只读分析未完成" in run.payload["summary"]
