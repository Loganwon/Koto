# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
from __future__ import annotations


def merge_task_results(subtasks: list, context: dict | None = None) -> dict:
    """Assemble the public compound-task result summary from executed subtasks."""
    merged = {"summary": "任务执行完成", "steps": [], "final_output": ""}

    for index, subtask in enumerate(subtasks):
        step_info = {
            "step": index + 1,
            "task": subtask["task_type"],
            "status": subtask["status"],
            "description": subtask["description"],
        }

        if subtask["result"]:
            step_info["output"] = subtask["result"].get("output", "")
        if subtask["error"]:
            step_info["error"] = subtask["error"]

        merged["steps"].append(step_info)

    for subtask in reversed(subtasks):
        if subtask["status"] == "completed" and subtask["result"]:
            merged["final_output"] = subtask["result"].get("output", "")
            break

    return merged
