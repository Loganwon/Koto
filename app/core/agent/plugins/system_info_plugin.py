"""
SystemInfoPlugin — 按需查询本机系统状态

对应 Phase 3 工具集成目标：让 Agent 在需要时主动查询系统信息，
避免预注入大量上下文。
"""

import json
from typing import Any, Dict, List

from app.core.agent.base import AgentPlugin
from web.system_info import get_system_info_collector


class SystemInfoPlugin(AgentPlugin):
    @property
    def name(self) -> str:
        return "SystemInfo"

    @property
    def description(self) -> str:
        return "On-demand system status tools (CPU, memory, disk, processes, warnings)."

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "query_cpu_status",
                "func": self.query_cpu_status,
                "description": "Query current CPU usage, core count, and frequency.",
                "parameters": {"type": "OBJECT", "properties": {}},
            },
            {
                "name": "query_memory_status",
                "func": self.query_memory_status,
                "description": "Query current memory and swap usage.",
                "parameters": {"type": "OBJECT", "properties": {}},
            },
            {
                "name": "query_disk_usage",
                "func": self.query_disk_usage,
                "description": "Query disk usage across mounted drives.",
                "parameters": {"type": "OBJECT", "properties": {}},
            },
            {
                "name": "query_network_status",
                "func": self.query_network_status,
                "description": "Query current network interfaces and connection status.",
                "parameters": {"type": "OBJECT", "properties": {}},
            },
            {
                "name": "query_python_env",
                "func": self.query_python_env,
                "description": "Query current Python runtime/environment details.",
                "parameters": {"type": "OBJECT", "properties": {}},
            },
            {
                "name": "list_running_apps",
                "func": self.list_running_apps,
                "description": "List top running processes sorted by memory usage.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "top_n": {
                            "type": "INTEGER",
                            "description": "How many processes to return.",
                        }
                    },
                },
            },
            {
                "name": "get_system_warnings",
                "func": self.get_system_warnings,
                "description": "Return system health warnings if resource usage is high.",
                "parameters": {"type": "OBJECT", "properties": {}},
            },
        ]

    @staticmethod
    def _to_json(data: Any) -> str:
        return json.dumps(data, ensure_ascii=False, indent=2)

    def query_cpu_status(self) -> str:
        try:
            info = get_system_info_collector().get_cpu_info()
            return self._to_json(info)
        except Exception as exc:
            return f"Error querying CPU status: {exc}"

    def query_memory_status(self) -> str:
        try:
            info = get_system_info_collector().get_memory_info()
            return self._to_json(info)
        except Exception as exc:
            return f"Error querying memory status: {exc}"

    def query_disk_usage(self) -> str:
        try:
            info = get_system_info_collector().get_disk_info()
            return self._to_json(info)
        except Exception as exc:
            return f"Error querying disk usage: {exc}"

    def query_network_status(self) -> str:
        try:
            info = get_system_info_collector().get_network_info()
            return self._to_json(info)
        except Exception as exc:
            return f"Error querying network status: {exc}"

    def query_python_env(self) -> str:
        try:
            info = get_system_info_collector().get_python_environment()
            return self._to_json(info)
        except Exception as exc:
            return f"Error querying python environment: {exc}"

    def list_running_apps(self, top_n: int = 10) -> str:
        try:
            top_n = max(1, min(int(top_n), 30))
            info = get_system_info_collector().get_running_processes(top_n=top_n)
            return self._to_json(info)
        except Exception as exc:
            return f"Error listing running apps: {exc}"

    def get_system_warnings(self) -> str:
        try:
            warnings = get_system_info_collector().get_system_warnings()
            return self._to_json({"warnings": warnings})
        except Exception as exc:
            return f"Error getting system warnings: {exc}"
