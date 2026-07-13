"""Tool registry construction and result-formatting helpers."""

from __future__ import annotations

from typing import Any, Dict, List, Optional


class ToolExecutor:
    """
    Stateless helpers for building the task tool registry and formatting
    tool execution results.
    """

    @staticmethod
    def build_registry(
        task_files: Optional[List[Dict[str, Any]]] = None,
        socketio: Any = None,
    ):
        """Build a ToolRegistry backed by TaskToolsPlugin.

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
