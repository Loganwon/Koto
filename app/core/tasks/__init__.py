# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
app.core.tasks
==============
统一任务管理子系统

模块:
  task_ledger   — 持久化任务台账（SQLite）
  progress_bus  — 全局进度事件总线（SSE + 内存订阅）
  task_planner  — 通用多步骤 DAG 规划器
"""

from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def _prefer_source_module(module_basename: str) -> None:
    module_name = f"{__name__}.{module_basename}"
    if module_name in sys.modules:
        return

    source_path = Path(__file__).with_name(f"{module_basename}.py")
    if not source_path.exists():
        return

    try:
        spec = importlib.util.spec_from_file_location(module_name, source_path)
        if spec is None or spec.loader is None:
            return
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    except Exception as exc:
        sys.modules.pop(module_name, None)
        logger.debug("[app.core.tasks] 源码 %s 预加载失败: %s", module_basename, exc)


_prefer_source_module("task_ledger")

from .progress_bus import (
    ProgressBus,
    ProgressEvent,
    get_progress_bus,
)
from .task_ledger import (
    TaskLedger,
    TaskRecord,
    TaskStatus,
    get_ledger,
)
from .task_planner import (
    Plan,
    PlanStep,
    StepResult,
    StepStatus,
    TaskPlanner,
)

__all__ = [
    # ledger
    "TaskLedger",
    "TaskRecord",
    "TaskStatus",
    "get_ledger",
    # bus
    "ProgressBus",
    "ProgressEvent",
    "get_progress_bus",
    # planner
    "TaskPlanner",
    "PlanStep",
    "StepStatus",
    "StepResult",
    "Plan",
]
