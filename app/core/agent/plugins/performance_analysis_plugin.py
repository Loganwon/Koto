"""
PerformanceAnalysisPlugin — Phase 4 性能优化建议

提供系统性能分析和优化建议工具。
"""

import json
from typing import Any, Dict, List

from app.core.agent.base import AgentPlugin
from web.system_info import get_system_info_collector


class PerformanceAnalysisPlugin(AgentPlugin):
    @property
    def name(self) -> str:
        return "PerformanceAnalysis"

    @property
    def description(self) -> str:
        return "Analyze system performance and suggest optimizations."

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "analyze_system_performance",
                "func": self.analyze_system_performance,
                "description": "Collect comprehensive system metrics and identify bottlenecks.",
                "parameters": {"type": "OBJECT", "properties": {}},
            },
            {
                "name": "suggest_optimizations",
                "func": self.suggest_optimizations,
                "description": "Generate performance optimization suggestions based on current metrics.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "focus_area": {
                            "type": "STRING",
                            "description": "Focus on specific area: cpu|memory|disk|general",
                        }
                    },
                },
            },
        ]

    @staticmethod
    def _to_json(data: Any) -> str:
        return json.dumps(data, ensure_ascii=False, indent=2)

    def analyze_system_performance(self) -> str:
        """Collect all system metrics and identify bottlenecks."""
        try:
            collector = get_system_info_collector()

            metrics = {
                "timestamp": int(__import__("time").time()),
                "cpu": collector.get_cpu_info(),
                "memory": collector.get_memory_info(),
                "disk": collector.get_disk_info(),
                "processes": collector.get_running_processes(top_n=5),
                "warnings": collector.get_system_warnings(),
            }

            bottlenecks = []
            if metrics["cpu"]["usage_percent"] > 80:
                bottlenecks.append("🔴 CPU very high")
            elif metrics["cpu"]["usage_percent"] > 60:
                bottlenecks.append("🟠 CPU elevated")

            if metrics["memory"]["percent"] > 90:
                bottlenecks.append("🔴 Memory critical")
            elif metrics["memory"]["percent"] > 75:
                bottlenecks.append("🟠 Memory high")

            if metrics["disk"]["percent_full"] > 90:
                bottlenecks.append("🔴 Disk almost full")
            elif metrics["disk"]["percent_full"] > 80:
                bottlenecks.append("🟠 Disk space limited")

            metrics["bottlenecks"] = bottlenecks

            return self._to_json(metrics)

        except Exception as exc:
            return f"Error analyzing performance: {exc}"

    def suggest_optimizations(self, focus_area: str = "general") -> str:
        """Generate optimization suggestions."""
        try:
            collector = get_system_info_collector()

            cpu = collector.get_cpu_info()
            memory = collector.get_memory_info()
            disk = collector.get_disk_info()
            processes = collector.get_running_processes(top_n=10)

            suggestions = {
                "timestamp": int(__import__("time").time()),
                "focus_area": focus_area,
                "recommendations": [],
            }

            # CPU suggestions
            if cpu["usage_percent"] > 80 or focus_area in ("cpu", "general"):
                suggestions["recommendations"].append(
                    {
                        "category": "CPU",
                        "severity": "high" if cpu["usage_percent"] > 80 else "medium",
                        "issue": f"CPU usage: {cpu['usage_percent']}%",
                        "actions": [
                            "Check top processes and close unnecessary ones",
                            "Consider upgrading CPU or enabling power saving mode",
                            "Use Task Scheduler to defer non-critical background tasks",
                        ],
                    }
                )

            # Memory suggestions
            if memory["percent"] > 80 or focus_area in ("memory", "general"):
                suggestions["recommendations"].append(
                    {
                        "category": "Memory",
                        "severity": "high" if memory["percent"] > 90 else "medium",
                        "issue": f"Memory usage: {memory['percent']}%",
                        "actions": [
                            "Close unused applications and browser tabs",
                            f"Available memory: {memory['available_gb']}GB",
                            "Consider adding more RAM or increasing virtual memory",
                            "Disable startup programs that consume memory",
                        ],
                    }
                )

            # Disk suggestions
            if disk["percent_full"] > 80 or focus_area in ("disk", "general"):
                suggestions["recommendations"].append(
                    {
                        "category": "Disk",
                        "severity": "high" if disk["percent_full"] > 90 else "medium",
                        "issue": f"Disk usage: {disk['percent_full']}% full ({disk['free_gb']}GB free)",
                        "actions": [
                            "Clean up temporary files (Temp, Downloads folders)",
                            "Run Disk Cleanup tool (Windows) or BleachBit (Linux)",
                            "Delete old logs and cached files",
                            "Consider external backup/archival for old data",
                            "Defragment disk if using HDD (not SSD)",
                        ],
                    }
                )

            # Process-level suggestions
            if processes.get("top_processes"):
                heavy_procs = processes["top_processes"][:3]
                if heavy_procs and heavy_procs[0].get("memory_percent", 0) > 10:
                    suggestions["recommendations"].append(
                        {
                            "category": "Processes",
                            "severity": "medium",
                            "issue": f"Top process uses {heavy_procs[0].get('memory_percent', '?')}% memory",
                            "actions": [
                                f"Monitor: {heavy_procs[0]['name']}",
                                "Consider closing or upgrading if problematic",
                                "Check for memory leaks with prolonged CPU/memory use",
                            ],
                        }
                    )

            if not suggestions["recommendations"]:
                suggestions["recommendations"].append(
                    {
                        "category": "General",
                        "severity": "info",
                        "issue": "System performance is normal",
                        "actions": ["Continue monitoring periodically"],
                    }
                )

            return self._to_json(suggestions)

        except Exception as exc:
            return f"Error generating suggestions: {exc}"
