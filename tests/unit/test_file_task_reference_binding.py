from __future__ import annotations

import json

import pytest

from app.core.agent.file_task_completion_verifier import verify_task_completion
from app.core.agent.file_task_contract import FileTaskFile, FileTaskRequest
from app.core.agent.file_task_read_evidence import (
    explicit_file_reference_was_read,
    file_references_in_task_text,
    unsatisfied_explicit_read_file_references,
)
from app.core.agent.file_task_targeting import (
    explicit_output_paths_from_task,
    files_explicitly_mentioned_in_task,
    task_file_reference_spans,
    task_text_mentions_path,
)


def test_source_and_generated_output_are_distinct_references(tmp_path):
    source = tmp_path / "source.txt"
    source.write_text("Revenue 240", encoding="utf-8")
    task = "读取source.txt，生成summary.xlsx"
    assert file_references_in_task_text(task) == ["source.txt", "summary.xlsx"]
    assert explicit_output_paths_from_task(
        task,
        has_artifact_creation_intent=lambda _: True,
    ) == ["summary.xlsx"]
    request = FileTaskRequest(
        task=task,
        files=[FileTaskFile(path=str(source), name=source.name)],
        target_path=str(tmp_path / "summary.xlsx"),
    )
    assert (
        unsatisfied_explicit_read_file_references(
            request,
            [{"path": str(source), "preview": "Revenue 240"}],
            [],
        )
        == []
    )
    assert [
        item.path
        for item in files_explicitly_mentioned_in_task(
            workspace_root=tmp_path,
            task=task,
        )
    ] == [str(source.resolve())]


@pytest.mark.parametrize(
    "filename", ["财务report.docx", "other_report.docx", "年度 summary.docx"]
)
def test_output_names_keep_literal_prefix_and_spaces(filename, tmp_path):
    target = tmp_path / "report.docx"
    task = f"创建“{filename}”"
    assert explicit_output_paths_from_task(
        task,
        has_artifact_creation_intent=lambda _: True,
        known_target_path=str(target),
    ) == [filename]
    result = json.loads(
        verify_task_completion(
            task,
            target_path=str(target),
            file_states=[{"path": str(target), "exists": True, "modified": True}],
            file_changes=[{"path": str(target), "operation": "write_docx"}],
        )
    )
    assert not result["completed"]


def test_unquoted_chinese_filename_is_not_replaced_by_known_suffix():
    assert explicit_output_paths_from_task(
        "创建 财务report.docx",
        has_artifact_creation_intent=lambda _: True,
        known_target_path="report.docx",
    ) == ["财务report.docx"]


@pytest.mark.parametrize(
    "filename", ["source.txt", "output.xlsx", "input.docx", "读取报告.docx"]
)
def test_trusted_filename_is_a_literal_not_an_instruction(filename):
    assert [
        value
        for value, _, _ in task_file_reference_spans(
            filename,
            known_paths=[filename],
        )
    ] == [filename]


def test_binding_does_not_strip_a_verb_inside_the_known_filename():
    assert [
        value
        for value, _, _ in task_file_reference_spans(
            "读取生成报告.docx",
            known_paths=["生成报告.docx"],
        )
    ] == ["生成报告.docx"]


def test_matching_a_filename_never_accepts_a_substring(tmp_path):
    source = tmp_path / "source.txt"
    source.write_text("source", encoding="utf-8")
    assert not explicit_file_reference_was_read(
        "source.txt",
        [{"path": str(tmp_path / "not_source.txt"), "name": "source.txt"}],
        [],
    )
    assert not task_text_mentions_path("读取not_source.txt", "source.txt")
    assert not task_text_mentions_path("读取source.txt.bak", "source.txt")
    files = files_explicitly_mentioned_in_task(
        workspace_root=tmp_path, task="读取not_source.txt"
    )
    assert [item.path for item in files] == ["not_source.txt"]


def test_bound_source_requires_the_selected_path_not_another_directory(tmp_path):
    source = tmp_path / "selected" / "source.txt"
    request = FileTaskRequest(
        task="读取source.txt", files=[FileTaskFile(path=str(source))]
    )
    snippets = [{"path": str(tmp_path / "other" / "source.txt")}]
    assert unsatisfied_explicit_read_file_references(request, snippets, []) == [
        "source.txt"
    ]
    assert (
        unsatisfied_explicit_read_file_references(request, [{"path": str(source)}], [])
        == []
    )
    assert not explicit_file_reference_was_read(
        "selected/source.txt", [{"path": "other/source.txt", "name": "source.txt"}], []
    )
    assert explicit_file_reference_was_read(
        "selected/source.txt",
        [{"path": str(source)}],
        [],
        known_paths=[str(source)],
    )


def test_ambiguous_basename_does_not_select_one_inventory_source(tmp_path):
    paths = [str(tmp_path / folder / "source.txt") for folder in ("a", "b")]
    assert not explicit_file_reference_was_read(
        "source.txt",
        [{"path": paths[0]}],
        [],
        known_paths=paths,
    )


@pytest.mark.parametrize(
    "result", [{"error": "missing"}, {"ok": False}, '{"success":false}', None]
)
def test_failed_tool_results_are_not_read_evidence(result):
    assert not explicit_file_reference_was_read(
        "source.txt",
        [],
        [
            {
                "tool_name": "parse_file_to_text",
                "args": {"path": "source.txt"},
                "result": result,
            }
        ],
    )


def test_output_read_again_in_same_task_still_requires_read_evidence():
    request = FileTaskRequest(task="生成summary.txt，再读取 summary.txt 并回答")
    assert unsatisfied_explicit_read_file_references(request, [], []) == ["summary.txt"]


def test_read_receipt_cannot_reinterpret_instruction_as_a_literal_filename():
    request = FileTaskRequest(task="读取source.txt")
    assert unsatisfied_explicit_read_file_references(
        request,
        [{"path": "读取source.txt"}],
        [],
    ) == ["source.txt"]


def test_split_output_directory_does_not_require_reading_the_new_file():
    request = FileTaskRequest(task="生成文件名为 summary.xlsx 保存到 reports 目录下")
    assert unsatisfied_explicit_read_file_references(request, [], []) == []


def test_bound_multi_source_list_never_creates_prose_files(tmp_path):
    from app.core.agent.file_task_runtime import FileTaskRuntime

    paths = [tmp_path / "source.txt", tmp_path / "milestones.pptx"]
    for path in paths:
        path.write_bytes(b"fixture")
    request = FileTaskRequest(
        task="同时读取source.txt和milestones.pptx，核对两个来源。",
        files=[FileTaskFile(path=str(path), name=path.name) for path in paths],
    )
    files = FileTaskRuntime(workspace_root=str(tmp_path))._context_files(request)
    assert {item.path for item in files} == {str(path) for path in paths}
    assert (
        unsatisfied_explicit_read_file_references(
            request,
            [{"path": str(path)} for path in paths],
            [],
        )
        == []
    )


@pytest.mark.parametrize(
    "task,filename",
    [
        ("只把edit.txt中的文字改短", "edit.txt"),
        ("在brief.docx末尾追加一段", "brief.docx"),
    ],
)
def test_mutation_prose_adds_no_unbound_context_file(task, filename, tmp_path):
    from app.core.agent.file_task_runtime import FileTaskRuntime

    path = tmp_path / filename
    path.write_bytes(b"fixture")
    request = FileTaskRequest(
        task=task, target_path=str(path), files=[FileTaskFile(path=str(path))]
    )
    files = FileTaskRuntime(workspace_root=str(tmp_path))._context_files(request)
    assert [item.path for item in files] == [str(path)]


def test_unbound_natural_language_is_resolved_by_kernel_tools(tmp_path):
    from openpyxl import Workbook

    from app.core.agent.file_task_runtime import FileTaskRuntime

    path = tmp_path / "销售台账.xlsx"
    workbook = Workbook()
    workbook.active.append(["客户", "营收"])
    workbook.active.append(["甲", 240])
    workbook.save(path)
    calls = []

    def model(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return {
                "tool_calls": [
                    {
                        "id": "locate",
                        "name": "list_workspace_files",
                        "args": {"path": "", "recursive": True},
                    }
                ]
            }
        if len(calls) == 2:
            assert "销售台账.xlsx" in json.dumps(kwargs["messages"], ensure_ascii=False)
            return {
                "tool_calls": [
                    {
                        "id": "read",
                        "name": "read_sheet_data",
                        "args": {"path": str(path)},
                    }
                ]
            }
        assert "240" in json.dumps(kwargs["messages"], ensure_ascii=False)
        return {"content": "销售台账.xlsx 中甲客户营收240。"}

    request = FileTaskRequest(
        task="请读取我的工作区里的销售台账.xlsx，告诉我哪个客户贡献最高。",
        options={"output_mode": "answer"},
    )
    runtime = FileTaskRuntime(
        model_client=model, workspace_root=str(tmp_path), max_rounds=3
    )
    assert runtime._context_files(request) == []
    events = list(runtime.run(request))
    terminal = next(event for event in reversed(events) if event.type == "run.finished")
    assert terminal.payload["completed_task"] is True
    assert any(
        event.type == "tool.finished"
        and event.payload.get("tool_name") == "read_sheet_data"
        and event.payload.get("success")
        for event in events
    )


def test_unrelated_structured_target_is_not_overwritten_by_another_output_name(
    tmp_path,
):
    from app.core.agent.file_task_runtime import FileTaskRuntime

    target = str(tmp_path / "report.docx")
    request = FileTaskRequest(task="生成other_report.docx", target_path=target)
    runtime = FileTaskRuntime(workspace_root=str(tmp_path))
    assert runtime._request_with_inferred_target_path(request).target_path == target
    assert (
        runtime._verification_target_path(request, [{"path": "other_report.docx"}])
        == target
    )


def test_verification_does_not_infer_a_second_target_from_prose(tmp_path):
    from app.core.agent.file_task_runtime import FileTaskRuntime

    runtime = FileTaskRuntime(workspace_root=str(tmp_path))
    assert (
        runtime._verification_target_path(FileTaskRequest(task="生成report.docx"), [])
        == ""
    )


@pytest.mark.parametrize(
    "task,filename",
    [
        (
            "继续在刚生成的report.docx末尾追加‘后续行动：复核收入结构。’一次，不另建文档。",
            "report.docx",
        ),
        ("继续仅把刚生成summary.xlsx的B2改为125，其他数字保留。", "summary.xlsx"),
        (
            "在刚生成summary.pptx追加后续行动页，原页数字不动，不另存副本。",
            "summary.pptx",
        ),
        ("继续在刚生成的report.docx中写入一段结论。", "report.docx"),
    ],
)
def test_edit_followup_keeps_the_bound_existing_target(task, filename, tmp_path):
    from app.core.agent.file_task_runtime import FileTaskRuntime

    target = tmp_path / filename
    target.write_bytes(b"fixture")
    request = FileTaskRequest(
        task=task,
        target_path=str(target),
        files=[FileTaskFile(path=str(target), target=True)],
        options={"output_mode": "edit"},
    )
    runtime = FileTaskRuntime(workspace_root=str(tmp_path))
    normalized = runtime._request_with_inferred_target_path(request)
    assert normalized.target_path == str(target)
    assert [item.path for item in runtime._context_files(normalized)] == [str(target)]
    result = json.loads(
        verify_task_completion(
            task,
            target_path=normalized.target_path,
            file_states=[{"path": str(target), "exists": True, "modified": True}],
            file_changes=[
                {"path": str(target), "operation": "write", "summary": "updated"}
            ],
        )
    )
    assert result["completed"] is True


@pytest.mark.parametrize(
    "task,output",
    [
        ("另存为other_report.docx", "other_report.docx"),
        ("创建 财务report.docx", "财务report.docx"),
        ("另存为“财务 report.docx”", "财务 report.docx"),
    ],
)
def test_edit_contract_can_still_name_an_explicit_new_output(task, output, tmp_path):
    from app.core.agent.file_task_runtime import FileTaskRuntime

    source = tmp_path / "report.docx"
    source.write_bytes(b"fixture")
    request = FileTaskRequest(
        task=task,
        target_path=str(source),
        files=[FileTaskFile(path=str(source), target=True)],
        options={"output_mode": "edit"},
    )
    normalized = FileTaskRuntime(
        workspace_root=str(tmp_path)
    )._request_with_inferred_target_path(request)
    assert normalized.target_path == output
    assert not normalized.files[0].target


def test_corrupt_docx_production_parse_is_not_a_successful_read(tmp_path):
    from app.core.agent.file_task_runtime import FileTaskRuntime
    from app.core.agent.task_tools import parse_file_to_text

    path = tmp_path / "broken.docx"
    path.write_bytes(b"not a DOCX ZIP archive")
    result = parse_file_to_text(str(path))
    assert result.startswith("Error parsing file:")
    from app.core.file.text_extraction import parse_source_file

    assert parse_source_file(str(path)) == ""  # Legacy callers keep their fallback.
    assert not explicit_file_reference_was_read(
        "broken.docx",
        [],
        [
            {
                "tool_name": "parse_file_to_text",
                "args": {"path": str(path)},
                "result": result,
            }
        ],
    )
    assert not explicit_file_reference_was_read(
        "broken.docx",
        [{"path": str(path), "preview": result}],
        [],
    )
    request = FileTaskRequest(
        task="读取broken.docx并总结",
        files=[FileTaskFile(path=str(path), type="docx")],
        options={"output_mode": "answer"},
    )
    events = list(
        FileTaskRuntime(
            model_client=lambda **_: {"content": "已经全部读取完成。"},
            workspace_root=str(tmp_path),
            max_rounds=1,
        ).run(request)
    )
    reads = [
        event.payload
        for event in events
        if event.type == "tool.finished"
        and event.payload.get("tool_name") == "parse_file_to_text"
    ]
    assert reads and all(read.get("success") is False for read in reads)
    context = next(
        event
        for event in events
        if event.type == "step.result"
        and event.payload.get("title") == "读取显式上下文"
    )
    assert context.payload.get("snippet_count", 0) == 0
    assert not context.payload.get("snippets")
    assert context.payload["status"] == "skipped"
    terminal = next(event for event in reversed(events) if event.type == "run.finished")
    assert terminal.payload["completed_task"] is False


def test_typed_success_receipt_preserves_real_error_prefix_text():
    text = "Error parsing file: is the literal first line of this document"
    assert explicit_file_reference_was_read(
        "source.txt",
        [],
        [
            {
                "tool_name": "parse_file_to_text",
                "args": {"path": "source.txt"},
                "result": {"ok": True, "value": text},
            }
        ],
    )
    assert explicit_file_reference_was_read(
        "source.txt",
        [{"path": "source.txt", "success": True, "preview": text}],
        [],
    )


@pytest.mark.parametrize("suffix", ["txt", "docx"])
def test_empty_file_is_a_successful_production_read(tmp_path, suffix):
    from app.core.agent.file_task_runtime_utils import _is_error_result
    from app.core.agent.task_tools import parse_file_to_text

    path = tmp_path / f"empty.{suffix}"
    if suffix == "docx":
        from docx import Document

        Document().save(path)
    else:
        path.write_text("", encoding="utf-8")
    result = parse_file_to_text(str(path))
    assert result.startswith("(File parsed but no text content:")
    assert not _is_error_result(result)
