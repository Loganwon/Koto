from __future__ import annotations

import json

from app.core.agent.file_task_contract import FileTaskFile
from app.core.agent.file_task_kernel_validation import FileTaskKernelValidator
from app.core.agent.kernel import AgentRequest


def test_kernel_validator_retries_premature_multi_file_answer() -> None:
    outputs = []
    validator = FileTaskKernelValidator(
        task="比较两个文件的内容差异",
        files=[
            FileTaskFile(path="a.docx", type="docx"),
            FileTaskFile(path="b.docx", type="docx"),
        ],
        readonly_tool_outputs=outputs,
        write_required=False,
    )

    outcome = validator.validate("只能看到预览。", AgentRequest(prompt="compare"))

    assert outcome.accepted is False
    assert "readonly_source_coverage_missing" in outcome.reasons
    assert "read_docx_content" in outcome.retry_instruction


def test_kernel_validator_accepts_answer_after_source_coverage() -> None:
    outputs = [
        {
            "tool_name": "read_docx_content",
            "args": {"path": path},
            "result": json.dumps(
                {
                    "paragraphs": [{"text": path}],
                    "tables": [],
                    "total_paragraphs": 1,
                    "total_tables": 0,
                    "truncated": False,
                }
            ),
        }
        for path in ("a.docx", "b.docx")
    ]
    validator = FileTaskKernelValidator(
        task="比较两个文件的内容差异",
        files=[
            FileTaskFile(path="a.docx", type="docx"),
            FileTaskFile(path="b.docx", type="docx"),
        ],
        readonly_tool_outputs=outputs,
        write_required=False,
    )

    outcome = validator.validate("比较完成。", AgentRequest(prompt="compare"))

    assert outcome.accepted is True
    assert outcome.content == "比较完成。"


def test_kernel_validator_requires_observable_write_before_final_text() -> None:
    changes = []
    validator = FileTaskKernelValidator(
        task="写入报告",
        files=[],
        readonly_tool_outputs=[],
        write_required=True,
        file_changes=changes,
        write_tool_names=("write_docx_content",),
    )

    premature = validator.validate("已完成。", AgentRequest(prompt="write"))
    assert premature.accepted is False
    assert "write_docx_content" in premature.retry_instruction

    changes.append({"path": "report.docx", "operation": "write_docx_content"})
    assert validator.validate("已完成。", AgentRequest(prompt="write")).accepted
