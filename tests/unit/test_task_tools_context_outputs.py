# -*- coding: utf-8 -*-
import json


def test_extract_file_changes_reads_run_python_spreadsheet_metrics():
    from app.core.agent.file_task_result_markers import (
        KOTO_CREATED_RESULT_MARKER,
        KOTO_MODIFIED_RESULT_MARKER,
    )
    from app.core.agent.file_task_tool_feedback import extract_file_changes

    result = {
        "stdout": (
            "Data rows written: 4 rows\n"
            "Total cells written: 20\n"
            "KOTO_CREATED:C:\\workspace\\sales_profit_report.xlsx"
        ),
        "__koto_created__": ["C:\\workspace\\sales_profit_report.xlsx"],
    }

    changes = extract_file_changes(
        "run_python_code",
        {"code": "write report"},
        result,
        created_marker=KOTO_CREATED_RESULT_MARKER,
        modified_marker=KOTO_MODIFIED_RESULT_MARKER,
    )

    assert changes[0]["operation"] == "run_python_code"
    assert changes[0]["rows_written"] == 4
    assert changes[0]["cells_written"] == 20


def test_create_file_uses_context_directory_for_bare_output(tmp_path, monkeypatch):
    import app.core.agent.task_tools as task_tools

    monkeypatch.setattr(task_tools, "_WORKSPACE_ROOT", str(tmp_path))
    source_dir = tmp_path / "codex_context_dir"
    source_dir.mkdir()
    (source_dir / "orders.csv").write_text("sku,units\nA100,1\n", encoding="utf-8")

    provider = task_tools.TaskToolsPlugin(
        workspace_root=str(tmp_path),
        request_context={
            "task": "请从 codex_context_dir 读取 orders.csv 并创建 restock_plan.csv",
        },
    )
    create_tool = next(
        tool for tool in provider.get_tools() if tool["name"] == "create_file"
    )

    payload = json.loads(
        create_tool["func"](
            "restock_plan.csv",
            "sku,restock_quantity\nA100,30\n",
        )
    )

    assert payload["success"] is True
    assert payload["path"] == "codex_context_dir/restock_plan.csv"
    assert (source_dir / "restock_plan.csv").exists()
    assert not (tmp_path / "restock_plan.csv").exists()


def test_run_python_relocates_root_created_files_to_context_directory(
    tmp_path, monkeypatch
):
    import app.core.agent.task_tools as task_tools

    monkeypatch.setattr(task_tools, "_WORKSPACE_ROOT", str(tmp_path))
    source_dir = tmp_path / "codex_context_dir"
    source_dir.mkdir()
    root_output = tmp_path / "restock_plan.csv"
    root_output.write_text("sku,restock_quantity\nA100,30\n", encoding="utf-8")

    result = task_tools._relocate_root_created_files_to_output_dir(
        {"stdout": f"KOTO_CREATED:{root_output}"},
        output_dir="codex_context_dir",
    )

    relocated = source_dir / "restock_plan.csv"
    assert relocated.exists()
    assert not root_output.exists()
    assert str(relocated) in result["stdout"]
    assert str(root_output) not in result["stdout"]


def test_context_directory_uses_resolved_workspace_root(tmp_path, monkeypatch):
    import app.core.agent.task_tools as task_tools

    monkeypatch.setattr(task_tools, "_WORKSPACE_ROOT", str(tmp_path))
    source_dir = tmp_path / "codex_context_dir"
    source_dir.mkdir()
    plugin = task_tools.TaskToolsPlugin(
        workspace_root=str(tmp_path),
        request_context={
            "task": (
                "读取 codex_context_dir/orders.csv 和 codex_context_dir/rules.md，"
                "生成 restock_plan.csv"
            ),
        },
    )

    assert plugin._contextual_output_directory() == "codex_context_dir"


def test_copy_file_delegates_to_canonical_file_service(tmp_path, monkeypatch):
    import app.core.agent.task_tools as task_tools

    monkeypatch.setattr(task_tools, "_WORKSPACE_ROOT", str(tmp_path))
    source = tmp_path / "source.txt"
    source.write_text("hello", encoding="utf-8")
    calls = []

    class FakeFileService:
        def __init__(self, *, workspace_dir, backup_enabled):
            calls.append(
                {
                    "workspace_dir": workspace_dir,
                    "backup_enabled": backup_enabled,
                }
            )

        def copy_file(self, source_path, destination_path, overwrite=False):
            calls.append(
                {
                    "source": source_path,
                    "destination": destination_path,
                    "overwrite": overwrite,
                }
            )
            return {
                "success": True,
                "destination": destination_path,
            }

    monkeypatch.setattr(task_tools, "FileService", FakeFileService)

    payload = json.loads(task_tools.copy_file("source.txt", "copied.txt"))

    assert calls == [
        {
            "workspace_dir": str(tmp_path),
            "backup_enabled": False,
        },
        {
            "source": str(source),
            "destination": str(tmp_path / "copied.txt"),
            "overwrite": True,
        },
    ]
    assert payload["success"] is True
    assert payload["path"] == "copied.txt"
    assert payload["operation"] == "copy_file"
    assert payload["change_type"] == "create"
