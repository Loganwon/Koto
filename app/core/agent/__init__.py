# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
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
        logger.debug("[app.core.agent] 源码 %s 预加载失败: %s", module_basename, exc)


_prefer_source_module("langgraph_agent")
_prefer_source_module("tool_registry")
_prefer_source_module("unified_agent")

from .base import Agent, AgentPlugin
from .tool_registry import ToolRegistry
from .types import AgentAction, AgentResponse, AgentStep, AgentStepType
from .unified_agent import UnifiedAgent
