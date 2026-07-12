from __future__ import annotations

from app.core.agent.file_task_runtime import FileTaskRuntime
from app.core.agent.file_task_step_payload import execute_step_summary


def test_compiled_step_payload_safely_formats_windows_file_name() -> None:
    summary = execute_step_summary(
        round_index=1,
        final_summary="",
        model_failed=False,
        tool_gap=None,
        file_changes=[
            {"path": r"reports\budget.xlsx", "summary": "已更新预算"},
        ],
        tool_runtime_outcome=None,
        runtime_status="",
    )

    assert "budget.xlsx" in summary


def test_compiled_runtime_safely_selects_last_generated_image(tmp_path) -> None:
    runtime = FileTaskRuntime()
    first = tmp_path / "first.png"
    latest = tmp_path / "latest.png"
    first.write_bytes(b"image")
    latest.write_bytes(b"image")

    assert runtime._display_path(r"reports\budget.xlsx") == "budget.xlsx"
    assert runtime._latest_generated_image_artifact_path(
        [
            {"kind": "image", "path": str(first)},
            {"kind": "image", "path": str(latest)},
        ]
    ) == str(latest)
