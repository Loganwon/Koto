# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Core workflow execution preparation helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.workflows.catalog import get_workflow_definition, is_chat_workflow
from app.core.workflows.registry import get_workflow_executor


@dataclass(frozen=True)
class WorkflowExecutionPlan:
    workflow_id: str
    executor: Any


class WorkflowExecutionError(ValueError):
    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


def prepare_workflow_execution(workflow_id: str) -> WorkflowExecutionPlan:
    normalized_id = str(workflow_id or "").strip()
    if not normalized_id:
        raise WorkflowExecutionError("缺少 workflow_id 参数", 400)

    workflow_definition = get_workflow_definition(normalized_id)
    if workflow_definition is None:
        raise WorkflowExecutionError(f"未知的工作流: {normalized_id}", 404)

    if is_chat_workflow(normalized_id):
        raise WorkflowExecutionError(
            f"工作流 {normalized_id} 为对话模式，请通过聊天发送", 400
        )

    executor = get_workflow_executor(normalized_id)
    if executor is None:
        raise WorkflowExecutionError(f"工作流 {normalized_id} 加载失败", 500)

    return WorkflowExecutionPlan(workflow_id=normalized_id, executor=executor)


def iter_workflow_events(plan: WorkflowExecutionPlan, params: dict[str, Any]):
    yield from plan.executor.run(params or {})
