from __future__ import annotations

from web.task_orchestrator_results import merge_task_results


def test_merge_task_results_uses_last_completed_output():
    subtasks = [
        {
            "task_type": "WEB_SEARCH",
            "status": "completed",
            "description": "search",
            "result": {"output": "found"},
            "error": None,
        },
        {
            "task_type": "FILE_GEN",
            "status": "completed",
            "description": "generate",
            "result": {"output": "generated"},
            "error": None,
        },
    ]

    merged = merge_task_results(subtasks)

    assert merged["summary"] == "任务执行完成"
    assert merged["final_output"] == "generated"
    assert [step["task"] for step in merged["steps"]] == ["WEB_SEARCH", "FILE_GEN"]


def test_merge_task_results_preserves_failed_step_error():
    merged = merge_task_results(
        [
            {
                "task_type": "WEB_SEARCH",
                "status": "failed",
                "description": "search",
                "result": None,
                "error": "timeout",
            }
        ]
    )

    assert merged["final_output"] == ""
    assert merged["steps"][0]["error"] == "timeout"
