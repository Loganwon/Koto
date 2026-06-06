"""
tool_executor.py — Tool registry construction and result formatting helpers
extracted from KotoAgentLoop.

Provides a stateless ToolExecutor class so that KotoAgentLoop._build_task_registry
becomes a thin delegator.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


class ToolExecutor:
    """
    Stateless helpers for building the task tool registry and formatting
    tool execution results.
    KotoAgentLoop methods delegate to these static methods.
    """

    @staticmethod
    def build_registry(
        task_files: Optional[List[Dict[str, Any]]] = None,
        socketio: Any = None,
    ):
        """Build a ToolRegistry backed by TaskToolsPlugin.

        Mirrors KotoAgentLoop._build_task_registry.

        Parameters
        ----------
        task_files:
            Optional list of task file metadata dicts forwarded to
            TaskToolsPlugin.
        socketio:
            Optional SocketIO instance forwarded to TaskToolsPlugin so that
            progress events can be emitted during tool execution.
        """
        from app.core.agent.task_tools import TaskToolsPlugin
        from app.core.agent.tool_registry import ToolRegistry

        registry = ToolRegistry()
        registry.register_plugin(
            TaskToolsPlugin(socketio=socketio, task_files=task_files)
        )
        return registry

    @staticmethod
    def format_result(result: Any) -> str:
        """Unified tool result → string.

        Delegates to the shared stringify_tool_result utility so that all
        tool result serialisation goes through one code path.
        """
        from app.core.shared.tool_parser import stringify_tool_result

        return stringify_tool_result(result)
