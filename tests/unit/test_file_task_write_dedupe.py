from __future__ import annotations

from pathlib import Path


def test_write_tool_key_is_scoped_below_its_target_key(tmp_path: Path) -> None:
    from app.core.agent.file_task_runtime import FileTaskRuntime

    runtime = FileTaskRuntime(workspace_root=str(tmp_path))
    target = tmp_path / "current.docx"

    docx_key = runtime._write_dedupe_key_for_tool(
        "write_docx_content", {"path": str(target)}
    )
    python_change_key = runtime._write_dedupe_key_for_target(str(target))

    assert docx_key.startswith(python_change_key + "::tool::")
    assert docx_key.endswith("write_docx_content")


def test_relative_and_absolute_write_targets_share_one_key(tmp_path: Path) -> None:
    from app.core.agent.file_task_runtime import FileTaskRuntime

    runtime = FileTaskRuntime(workspace_root=str(tmp_path))

    relative_key = runtime._write_dedupe_key_for_target("current.docx")
    absolute_key = runtime._write_dedupe_key_for_target(str(tmp_path / "current.docx"))

    assert relative_key == absolute_key


def test_python_file_changes_are_counted_before_a_second_writer() -> None:
    source = Path("app/core/agent/file_task_execution_loop.py").read_text(
        encoding="utf-8"
    )

    assert 'if success and tool_name == "run_python_code":' in source
    assert "runtime._write_dedupe_key_for_target(changed_path)" in source
    assert "target_was_locked_by_code" in source
