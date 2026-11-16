from __future__ import annotations

import pytest
from docx import Document

from app.core.agent.file_task_contract import FileTaskFile, FileTaskRequest
from app.core.agent.file_task_quality_gate import evaluate_task_quality_gate
from app.core.agent.file_task_runtime import FileTaskRuntime


def _classify(tmp_path, task, mode=""):
    path = tmp_path / "report.docx"
    request = FileTaskRequest(
        task=task,
        target_path=str(path),
        files=[FileTaskFile(path=str(path), type="docx", target=True)],
        options={"output_mode": mode} if mode else {},
    )
    return FileTaskRuntime(workspace_root=str(tmp_path))._classify_request(request, [])


@pytest.mark.parametrize(
    "task",
    [
        "请说明如何修改 report.docx，不要实际执行",
        "请说明如何写回 report.docx，不要实际执行",
        "Explain how to save report.docx; do not actually execute.",
        "请说明如何修改当前文件",
        "请说明如何保存 report.docx",
        "How do I save report.docx?",
        "Explain how to save report.docx, then explain how to export another file.",
    ],
)
def test_a_target_and_quoted_write_verb_do_not_authorize_description_requests(
    tmp_path, task
):
    result = _classify(tmp_path, task)
    assert result.output_mode == "answer"
    assert not result.write_authorized
    assert not result.write_required


@pytest.mark.parametrize(
    "task",
    [
        "请说明如何修改 A.docx，再把结论写入 B.docx",
        "Explain how to edit A.docx, then save the changes to B.docx.",
        "Explain how to edit A.docx, then apply the changes to B.docx.",
        "把结论写入 B.docx，然后说明如何修改 A.docx",
    ],
)
def test_independent_explicit_write_clause_is_not_swallowed_by_explanation_guard(
    tmp_path, task
):
    result = _classify(tmp_path, task)
    assert result.output_mode == "write"
    assert result.write_authorized and result.write_required


@pytest.mark.parametrize("mode", ["edit", "write", "hybrid"])
def test_explicit_transport_keeps_soft_editing_authorized(tmp_path, mode):
    result = _classify(tmp_path, "把这个 PPT 编辑得好看一点，做成专业汇报风格", mode)
    assert result.write_authorized
    assert result.write_required is (mode != "hybrid")


@pytest.mark.parametrize("mode", ["edit", "write", "hybrid"])
def test_explicit_do_not_execute_remains_authoritative_over_transport(tmp_path, mode):
    result = _classify(tmp_path, "请说明如何修改 report.docx，不要实际执行", mode)
    assert result.output_mode == "answer" and not result.write_authorized


def _existing_table(tmp_path):
    path = tmp_path / "report.docx"
    doc = Document()
    doc.add_paragraph("Original paragraph")
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Existing table"
    doc.save(path)
    request = FileTaskRequest(task="在末尾插入一个新表格", target_path=str(path))
    return path, request


def test_existing_two_by_two_table_cannot_satisfy_a_new_table_request(tmp_path):
    path, request = _existing_table(tmp_path)
    doc = Document(path)
    doc.add_paragraph("Only a new paragraph")
    doc.save(path)
    changes = [
        {
            "path": str(path),
            "operation": "write_docx_content",
            "paragraphs_written": 1,
            "structure_verified": True,
            "docx_tables_before": 1,
            "docx_tables_after": 1,
        }
    ]
    gate = evaluate_task_quality_gate(
        request, changes, write_intent=True, output_mode="write"
    )
    assert not gate["passed"]
    assert any(
        item["criterion"] == "docx_table_request_has_table" and not item["passed"]
        for item in gate["criteria_results"]
    )


def test_actual_new_table_with_verified_same_target_growth_passes(tmp_path):
    path, request = _existing_table(tmp_path)
    doc = Document(path)
    doc.add_table(rows=2, cols=2)
    doc.save(path)
    changes = [
        {
            "path": str(path),
            "operation": "run_python_code",
            "structure_verified": True,
            "docx_tables_before": 1,
            "docx_tables_after": 2,
        }
    ]
    gate = evaluate_task_quality_gate(
        request, changes, write_intent=True, output_mode="write"
    )
    assert gate["passed"]


def test_nested_word_tables_use_the_same_xml_counts_as_transaction_evidence(tmp_path):
    path, request = _existing_table(tmp_path)
    doc = Document(path)
    doc.tables[0].cell(0, 0).add_table(rows=2, cols=2)
    doc.add_table(rows=2, cols=2)
    doc.save(path)
    changes = [
        {
            "path": str(path),
            "operation": "run_python_code",
            "structure_verified": True,
            "docx_tables_before": 2,
            "docx_tables_after": 3,
        }
    ]
    assert evaluate_task_quality_gate(
        request, changes, write_intent=True, output_mode="write"
    )["passed"]


@pytest.mark.parametrize(
    "evidence",
    [
        {"docx_tables_before": 0, "docx_tables_after": 2},
        {"structure_verified": True},
        {"structure_verified": True, "docx_tables_before": 1, "docx_tables_after": 1},
        {"structure_verified": True, "docx_tables_before": 1, "docx_tables_after": 2},
    ],
)
def test_unverified_or_unchanged_table_metrics_are_not_new_table_evidence(
    tmp_path, evidence
):
    path, request = _existing_table(tmp_path)
    changes = [{"path": str(path), "operation": "run_python_code", **evidence}]
    assert not evaluate_task_quality_gate(
        request, changes, write_intent=True, output_mode="write"
    )["passed"]


def test_table_in_an_unrelated_changed_document_cannot_satisfy_target_growth(tmp_path):
    path, request = _existing_table(tmp_path)
    changes = [
        {
            "path": str(tmp_path / "other.docx"),
            "operation": "insert_excel_as_docx_table",
            "rows_written": 8,
            "structure_verified": True,
            "docx_tables_before": 0,
            "docx_tables_after": 1,
        }
    ]
    assert not evaluate_task_quality_gate(
        request, changes, write_intent=True, output_mode="write"
    )["passed"]


def test_append_conclusion_and_preserve_table_does_not_require_new_table(tmp_path):
    path, request = _existing_table(tmp_path)
    request.task = "追加一段结论，保留原表格不变。"
    doc = Document(path)
    doc.add_paragraph("Conclusion")
    doc.save(path)
    gate = evaluate_task_quality_gate(
        request,
        [
            {
                "path": str(path),
                "operation": "insert_docx_paragraph",
                "paragraphs_written": 1,
                "inserted_text": "Conclusion",
            }
        ],
        write_intent=True,
        output_mode="write",
    )
    assert gate["passed"]
    assert not any(
        item["criterion"] == "docx_table_request_has_table"
        for item in gate["criteria_results"]
    )


def test_csv_native_selection_change_uses_its_actual_replacement_receipt(tmp_path):
    path = tmp_path / "sales.csv"
    path.write_text("department,amount\nmarket,45\nengineering,80\n", encoding="utf-8")
    request = FileTaskRequest(
        task="只将市场部门金额由40改为45，保留其它部门", target_path=str(path)
    )
    changed = {
        "path": str(path),
        "operation": "replace_file_selection",
        "replacements_made": 1,
    }
    result = evaluate_task_quality_gate(
        request, [changed], write_intent=True, output_mode="write"
    )
    assert result["passed"]
    assert not evaluate_task_quality_gate(
        request,
        [{**changed, "replacements_made": 0}],
        write_intent=True,
        output_mode="write",
    )["passed"]


def test_csv_relative_receipt_matches_absolute_target_through_workspace_owner(
    tmp_path, monkeypatch
):
    from app.core.agent import task_tools_common

    workspace = tmp_path / "workspace"
    target = workspace / "sales" / "edit.csv"
    other = workspace / "unrelated" / "edit.csv"
    for path in (target, other):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("department,amount\nmarket,45\n", encoding="utf-8")
    monkeypatch.setattr(task_tools_common, "_WORKSPACE_ROOT", str(workspace))
    request = FileTaskRequest(task="只修改市场部门金额", target_path=str(target))
    change = {
        "path": "sales/edit.csv",
        "operation": "replace_file_selection",
        "replacements_made": 1,
    }
    assert evaluate_task_quality_gate(
        request, [change], write_intent=True, output_mode="write"
    )["passed"]
    # Equal basenames and a real changed file in another directory are not the target.
    for wrong_path in ("unrelated/edit.csv", "", None):
        wrong = {**change, "path": wrong_path}
        assert not evaluate_task_quality_gate(
            request, [wrong], write_intent=True, output_mode="write"
        )["passed"]
