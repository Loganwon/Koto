"""Explicit client contracts and actual effects outrank incidental prose."""

import json

from app.core.agent.file_task_completion_verifier import verify_task_completion
from app.core.agent.file_task_contract import FileTaskFile, FileTaskRequest
from app.core.agent.file_task_kernel_validation import FileTaskKernelValidator
from app.core.agent.file_task_mutation_evidence import update_mutation_failures
from app.core.agent.file_task_quality_gate import _looks_like_docx_table_output_request
from app.core.agent.file_task_runtime import FileTaskRuntime
from app.core.agent.kernel import AgentRequest


def runtime(tmp_path):
    return FileTaskRuntime(
        workspace_root=str(tmp_path), model_client=lambda **_: {"content": "fixture"}
    )


def test_explicit_edit_transport_requires_real_write_even_for_soft_wording(tmp_path):
    request = FileTaskRequest(
        task="润色这一段",
        target_path=str(tmp_path / "edit.txt"),
        options={"output_mode": "edit"},
    )
    r = runtime(tmp_path)
    classification = r._classify_request(request, [])
    assert classification.write_authorized and classification.write_required
    assert classification.output_mode == "write"


def test_readonly_request_never_invents_prose_prefixed_write_target(tmp_path):
    source = tmp_path / "source.txt"
    source.write_text("quarterly revenue 240", encoding="utf-8")
    request = FileTaskRequest(
        task="读取source.txt，回答营收并写明来源，不要修改文件。",
        files=[FileTaskFile(path=str(source), name=source.name)],
        options={"output_mode": "answer"},
    )
    assert (
        runtime(tmp_path)._request_with_inferred_target_path(request).target_path == ""
    )


def test_structured_target_survives_generation_and_followup_wording(tmp_path):
    target = str(tmp_path / "report.docx")
    r = runtime(tmp_path)
    for task in (
        "生成report.docx",
        "继续在刚生成的report.docx补充结论",
        "修改report.docx且保持其它内容",
    ):
        request = FileTaskRequest(task=task, target_path=target)
        assert r._request_with_inferred_target_path(request).target_path == target
        assert r._verification_target_path(request, [{"path": target}]) == target


def test_completion_lexes_known_filename_without_swallowing_chinese_prose(tmp_path):
    target = tmp_path / "summary.xlsx"
    payload = json.loads(
        verify_task_completion(
            "读取材料，生成summary.xlsx",
            target_path=str(target),
            file_states=json.dumps(
                [{"path": str(target), "exists": True, "modified": True}]
            ),
            file_changes=json.dumps(
                [{"path": str(target), "operation": "write_cell", "summary": "written"}]
            ),
        )
    )
    assert payload["completed"] is True
    missing = json.loads(
        verify_task_completion(
            "生成other_summary.xlsx",
            target_path=str(target),
            file_states=json.dumps(
                [{"path": str(target), "exists": True, "modified": True}]
            ),
            file_changes=json.dumps([{"path": str(target), "operation": "write_cell"}]),
        )
    )
    assert missing["completed"] is False


def test_table_preservation_clause_does_not_turn_paragraph_append_into_table_creation():
    assert not _looks_like_docx_table_output_request("追加一段结论，保留原表格不变。")
    assert not _looks_like_docx_table_output_request(
        "Append a conclusion; keep the original table unchanged."
    )
    assert _looks_like_docx_table_output_request("保留原表格不变，新增一个表格。")


def test_failed_write_cannot_be_accepted_as_readonly_success():
    failures = []
    update_mutation_failures(
        failures,
        tool_name="create_file",
        tool_args={"path": "blocked.txt"},
        result={"ok": False, "error": {"code": "policy_denied"}},
        changes=[],
        call_id="denied",
    )
    validator = FileTaskKernelValidator(
        task="read",
        files=[],
        readonly_tool_outputs=[],
        write_required=False,
        mutation_failures=failures,
    )
    result = validator.validate("已经全部完成", AgentRequest(prompt="read"))
    assert result.blocked and not result.accepted
    assert "mutation_policy_denied" in result.reasons


def test_only_matching_successful_commit_resolves_failed_write():
    failures = []
    update_mutation_failures(
        failures,
        tool_name="replace_file_selection",
        tool_args={"path": "first.txt"},
        result={"ok": False, "error": {"code": "execution_error"}},
        changes=[],
        call_id="bad",
    )
    update_mutation_failures(
        failures,
        tool_name="replace_file_selection",
        tool_args={"path": "second.txt"},
        result={"ok": True},
        changes=[{"path": "second.txt"}],
        call_id="unrelated",
    )
    assert failures
    update_mutation_failures(
        failures,
        tool_name="replace_file_selection",
        tool_args={"path": "first.txt"},
        result={"ok": True},
        changes=[{"path": "first.txt"}],
        call_id="repaired",
    )
    assert failures == []


def test_real_runtime_denied_mutation_keeps_source_and_failed_terminal(tmp_path):
    source = tmp_path / "source.txt"
    source.write_text("original", encoding="utf-8")
    calls = []
    turn = 0

    def model(**_):
        nonlocal turn
        turn += 1
        if turn == 1:
            return {
                "tool_calls": [
                    {
                        "id": "forbidden",
                        "name": "create_file",
                        "args": {"path": str(source), "content": "bad"},
                    }
                ]
            }
        return {"content": "已经全部完成"}

    def execute(name, args):
        calls.append(name)
        assert name != "create_file", "unauthorized mutation reached executor"
        return {"path": str(source), "text": "original"}

    events = list(
        FileTaskRuntime(
            tool_executor=execute,
            model_client=model,
            workspace_root=str(tmp_path),
            max_rounds=2,
        ).run(
            FileTaskRequest(
                task="根据材料解释原文含义",
                options={"output_mode": "answer"},
                files=[FileTaskFile(path=str(source), name=source.name, type="txt")],
            )
        )
    )
    final = next(event for event in reversed(events) if event.type == "run.finished")
    assert final.payload.get("completed_task") is False
    assert source.read_text(encoding="utf-8") == "original"


def test_other_sheet_write_never_clears_an_unfinished_cell_operation():
    failures = []
    update_mutation_failures(
        failures,
        tool_name="write_sheet_data",
        tool_args={
            "path": "book.xlsx",
            "sheet_name": "Sheet1",
            "start_cell": "A1",
            "data": [[42]],
        },
        result={"ok": False, "error": {"code": "execution_error"}},
        changes=[],
        call_id="a1",
    )
    update_mutation_failures(
        failures,
        tool_name="write_sheet_data",
        tool_args={
            "path": "book.xlsx",
            "sheet_name": "Sheet2",
            "start_cell": "B1",
            "data": [[9]],
        },
        result={"ok": True},
        changes=[{"path": "book.xlsx"}],
        call_id="b1",
    )
    assert len(failures) == 1
    outcome = FileTaskKernelValidator(
        task="write",
        files=[],
        readonly_tool_outputs=[],
        write_required=True,
        file_changes=[{"path": "book.xlsx"}],
        mutation_failures=failures,
    ).validate("done", AgentRequest(prompt="write"))
    assert not outcome.accepted


def test_protected_source_attempt_can_recover_only_by_committing_bound_output():
    failures = []
    update_mutation_failures(
        failures,
        tool_name="create_file",
        tool_args={"path": "source.txt"},
        result={"ok": False, "error": {"code": "policy_denied"}},
        changes=[],
        call_id="denied",
    )
    update_mutation_failures(
        failures,
        tool_name="create_file",
        tool_args={"path": "other.txt"},
        result={"ok": True},
        changes=[{"path": "other.txt"}],
        call_id="other",
        authorized_target="report.txt",
    )
    assert failures
    update_mutation_failures(
        failures,
        tool_name="create_file",
        tool_args={"path": "report.txt"},
        result={"ok": True},
        changes=[{"path": "report.txt"}],
        call_id="correct",
        authorized_target="report.txt",
    )
    assert failures == []
