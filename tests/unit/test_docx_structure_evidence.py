"""A pre-existing table must not be evidence that a new table was created."""

import json

import pytest
from docx import Document

from app.core.agent.file_task_contract import (
    FileTaskRequest,
    FileTaskToolStreamChunk,
    FileTaskToolStreamResult,
)
from app.core.agent.file_task_document_metrics import attach_structure_to_changes
from app.core.agent.file_task_quality_gate import _docx_table_requirement_gate
from app.core.agent.file_task_tool_feedback import extract_file_changes
from app.core.agent.file_task_tool_gateway import (
    FileTaskToolContext,
    FileTaskToolGateway,
)


def changes(value, path):
    return extract_file_changes(
        "write_docx_content",
        {"path": str(path)},
        value,
        created_marker="KOTO_CREATED:",
        modified_marker="KOTO_MODIFIED:",
    )


def test_actual_added_table_has_host_observed_before_and_after(tmp_path):
    target = tmp_path / "report.docx"
    document = Document()
    document.add_paragraph("Original")
    document.save(target)

    def execute(name, args):
        document = Document(target)
        document.add_table(rows=2, cols=2)
        document.save(target)
        return json.dumps(
            {"success": True, "path": str(target), "operation": "write_docx_content"}
        )

    gateway = FileTaskToolGateway(tool_executor=execute)
    value = gateway.execute(
        "write_docx_content", {"path": str(target), "paragraphs": "[]"}
    )
    assert isinstance(value, str)  # Existing provider return type stays compatible.
    observed = changes(value, target)
    assert observed and observed[0]["structure_verified"] is True
    assert (
        observed[0]["docx_tables_before"] == 0 and observed[0]["docx_tables_after"] == 1
    )
    gate = _docx_table_requirement_gate(
        FileTaskRequest(task="在文档末尾插入一个新表格", target_path=str(target)),
        observed,
        "docx",
        {"write_docx_content"},
        0,
    )
    assert gate["passed"] is True


def test_old_table_and_new_paragraph_never_prove_new_table(tmp_path):
    target = tmp_path / "report.docx"
    document = Document()
    document.add_table(rows=2, cols=2)
    document.save(target)

    def execute(name, args):
        document = Document(target)
        document.add_paragraph("A conclusion")
        document.save(target)
        return {"success": True, "path": str(target), "operation": "write_docx_content"}

    value = FileTaskToolGateway(tool_executor=execute).execute(
        "write_docx_content", {"path": str(target), "paragraphs": "[]"}
    )
    observed = changes(value, target)
    assert observed[0]["docx_tables_before"] == observed[0]["docx_tables_after"] == 1
    gate = _docx_table_requirement_gate(
        FileTaskRequest(task="新增一个表格", target_path=str(target)),
        observed,
        "docx",
        {"write_docx_content"},
        0,
    )
    assert gate["passed"] is False


def test_new_document_records_zero_tables_before_the_write(tmp_path):
    target = tmp_path / "new.docx"

    def execute(name, args):
        document = Document()
        document.add_table(rows=2, cols=2)
        document.save(target)
        return {"success": True, "path": str(target), "operation": "write_docx_content"}

    value = FileTaskToolGateway(tool_executor=execute).execute(
        "write_docx_content", {"path": str(target), "paragraphs": "[]"}
    )
    observed = changes(value, target)
    assert (
        observed[0]["docx_tables_before"] == 0 and observed[0]["docx_tables_after"] == 1
    )


def test_interrupted_stream_rolls_back_even_after_provisional_result(tmp_path):
    target = tmp_path / "report.docx"
    document = Document()
    document.add_table(rows=2, cols=2)
    document.save(target)
    before = target.read_bytes()

    def execute(name, args):
        def stream():
            document = Document(target)
            document.add_table(rows=3, cols=2)
            document.save(target)
            yield FileTaskToolStreamChunk(
                kind="result", payload={"success": True, "path": str(target)}
            )
            raise RuntimeError("interrupted before transaction completion")

        return FileTaskToolStreamResult(chunks=stream())

    value = FileTaskToolGateway(tool_executor=execute).execute(
        "write_docx_content", {"path": str(target), "paragraphs": "[]"}
    )
    with pytest.raises(RuntimeError, match="interrupted"):
        list(value.chunks)
    assert target.read_bytes() == before


def test_forged_plain_structure_fields_are_not_host_receipts():
    fake = {"structure_verified": True, "docx_tables_before": 0, "docx_tables_after": 9}
    observed = [{"path": "report.docx", **fake}]
    attach_structure_to_changes(observed, fake)
    assert "structure_verified" not in observed[0]


def test_claimed_write_without_a_real_document_has_no_verified_structure(tmp_path):
    target = tmp_path / "missing.docx"
    value = FileTaskToolGateway(
        tool_executor=lambda *_: {
            "success": True,
            "path": str(target),
            "operation": "write_docx_content",
        }
    ).execute(
        "write_docx_content",
        {"path": str(target), "paragraphs": "[]"},
    )
    assert not any(
        change.get("structure_verified") for change in changes(value, target)
    )


def test_trusted_python_target_gets_the_same_actual_structure_boundary(tmp_path):
    target = tmp_path / "report.docx"

    def execute(name, args):
        document = Document()
        document.add_table(rows=2, cols=2)
        document.save(target)
        return json.dumps({"stdout": "created"})

    gateway = FileTaskToolGateway(
        tool_executor=execute,
        context=FileTaskToolContext(request_context={"target_path": str(target)}),
    )
    value = gateway.execute(
        "run_python_code", {"code": "# fixture executor performs actual file write"}
    )
    observed = [{"path": str(target), "operation": "run_python_code"}]
    attach_structure_to_changes(observed, value)
    assert (
        observed[0]["docx_tables_before"] == 0 and observed[0]["docx_tables_after"] == 1
    )


@pytest.mark.parametrize("streaming", [False, True])
def test_direct_file_tools_cannot_bypass_complex_source_loss_guard(tmp_path, streaming):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    target = tmp_path / "bookmarked.docx"
    document = Document()
    paragraph = document.add_paragraph("Protected original")
    start = OxmlElement("w:bookmarkStart")
    start.set(qn("w:id"), "7")
    start.set(qn("w:name"), "UserBookmark")
    end = OxmlElement("w:bookmarkEnd")
    end.set(qn("w:id"), "7")
    paragraph._p.insert(0, start)
    paragraph._p.append(end)
    document.save(target)
    before = target.read_bytes()

    def execute(name, args):
        replacement = Document()
        replacement.add_paragraph("Changed text")
        replacement.save(target)
        result = {
            "success": True,
            "path": str(target),
            "operation": "write_docx_content",
        }
        return (
            FileTaskToolStreamResult(
                chunks=[FileTaskToolStreamChunk(kind="result", payload=result)]
            )
            if streaming
            else result
        )

    gateway = FileTaskToolGateway(tool_executor=execute)
    with pytest.raises(RuntimeError, match="原文件已回滚"):
        value = gateway.execute(
            "write_docx_content", {"path": str(target), "paragraphs": "[]"}
        )
        if streaming:
            list(value.chunks)
    assert target.read_bytes() == before
