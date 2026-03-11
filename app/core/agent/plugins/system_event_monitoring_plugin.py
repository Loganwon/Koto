"""
Phase 4b: System Event Monitoring Plugin

Integrates SystemEventMonitor with Agent tools.
Allows agent to control background monitoring and query anomalies.
"""

import logging
from typing import Any, Dict, List, Optional

from app.core.agent.base import AgentPlugin

logger = logging.getLogger(__name__)


class SystemEventMonitoringPlugin(AgentPlugin):
    """
    Plugin for system event monitoring.
    Provides tools for:
    - Starting/stopping background monitor
    - Querying detected anomalies
    - Getting system health summary
    - Managing monitoring thresholds
    """

    @property
    def name(self) -> str:
        """Plugin name"""
        return "SystemEventMonitoringPlugin"

    @property
    def description(self) -> str:
        """Plugin description"""
        return "Monitor system anomalies in background and trigger proactive advisory"

    def __init__(self):
        super().__init__()
        # Lazy import to avoid circular dependencies
        self.monitor = None

    def _get_monitor(self):
        """Lazy load monitor singleton."""
        if self.monitor is None:
            from app.core.monitoring.system_event_monitor import (
                get_system_event_monitor,
            )

            self.monitor = get_system_event_monitor()
        return self.monitor

    def get_tools(self) -> List[Dict[str, Any]]:
        """Return tools for monitoring control and queries."""
        return [
            {
                "name": "start_system_monitoring",
                "description": "Start background system monitoring. Detects CPU spikes, high memory, disk full, and other anomalies.",
                "func": self.start_monitoring,
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "check_interval": {
                            "type": "INTEGER",
                            "description": "Seconds between metric collections (default 30)",
                        }
                    },
                    "required": [],
                },
            },
            {
                "name": "stop_system_monitoring",
                "description": "Stop background system monitoring.",
                "func": self.stop_monitoring,
                "parameters": {"type": "OBJECT", "properties": {}, "required": []},
            },
            {
                "name": "get_system_anomalies",
                "description": "Get recent detected system anomalies (CPU spikes, high memory, disk full, etc.)",
                "func": self.get_anomalies,
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "limit": {
                            "type": "INTEGER",
                            "description": "Max anomalies to return (default 20)",
                        },
                        "event_type": {
                            "type": "STRING",
                            "description": "Filter by event type: 'cpu_spike', 'cpu_high', 'memory_high', 'disk_high', 'process_memory_high' (optional)",
                        },
                    },
                    "required": [],
                },
            },
            {
                "name": "get_system_health",
                "description": "Get system health summary from recent monitoring. Shows overall status (healthy/warning/critical) and event distribution.",
                "func": self.get_health_summary,
                "parameters": {"type": "OBJECT", "properties": {}, "required": []},
            },
            {
                "name": "clear_monitoring_log",
                "description": "Clear all recorded anomaly events from memory. Useful after taking corrective action.",
                "func": self.clear_log,
                "parameters": {"type": "OBJECT", "properties": {}, "required": []},
            },
            {
                "name": "get_monitoring_status",
                "description": "Check if system monitoring is currently active.",
                "func": self.get_status,
                "parameters": {"type": "OBJECT", "properties": {}, "required": []},
            },
        ]

    def start_monitoring(self, check_interval: int = 30) -> Dict[str, Any]:
        """Start background monitoring."""
        try:
            monitor = self._get_monitor()

            if monitor.is_running():
                return {
                    "status": "already_running",
                    "message": "System monitoring is already active",
                    "check_interval": monitor.check_interval,
                }

            monitor.start()
            return {
                "status": "success",
                "message": "System monitoring started",
                "check_interval": monitor.check_interval,
            }
        except Exception as e:
            logger.error(f"Error starting monitoring: {e}", exc_info=True)
            return {
                "status": "error",
                "message": f"Failed to start monitoring: {str(e)}",
            }

    def stop_monitoring(self) -> Dict[str, Any]:
        """Stop background monitoring."""
        try:
            monitor = self._get_monitor()

            if not monitor.is_running():
                return {
                    "status": "not_running",
                    "message": "System monitoring is not currently active",
                }

            monitor.stop()
            return {"status": "success", "message": "System monitoring stopped"}
        except Exception as e:
            logger.error(f"Error stopping monitoring: {e}", exc_info=True)
            return {
                "status": "error",
                "message": f"Failed to stop monitoring: {str(e)}",
            }

    def get_anomalies(
        self, limit: int = 20, event_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get recent detected anomalies."""
        try:
            monitor = self._get_monitor()
            events = monitor.get_events(limit=limit, event_type=event_type)

            return {
                "status": "success",
                "anomaly_count": len(events),
                "anomalies": events,
                "monitoring_active": monitor.is_running(),
            }
        except Exception as e:
            logger.error(f"Error getting anomalies: {e}", exc_info=True)
            return {"status": "error", "message": f"Failed to get anomalies: {str(e)}"}

    def get_health_summary(self) -> Dict[str, Any]:
        """Get system health summary."""
        try:
            monitor = self._get_monitor()
            summary = monitor.get_summary()

            return {
                "status": "success",
                "health": summary,
                "monitoring_active": monitor.is_running(),
            }
        except Exception as e:
            logger.error(f"Error getting health summary: {e}", exc_info=True)
            return {
                "status": "error",
                "message": f"Failed to get health summary: {str(e)}",
            }

    def clear_log(self) -> Dict[str, Any]:
        """Clear monitoring event log."""
        try:
            monitor = self._get_monitor()
            count = monitor.clear_events()

            return {
                "status": "success",
                "message": f"Cleared {count} events from monitoring log",
            }
        except Exception as e:
            logger.error(f"Error clearing log: {e}", exc_info=True)
            return {"status": "error", "message": f"Failed to clear log: {str(e)}"}

    def get_status(self) -> Dict[str, Any]:
        """Get current monitoring status."""
        try:
            monitor = self._get_monitor()

            return {
                "status": "success",
                "monitoring_active": monitor.is_running(),
                "check_interval": (
                    monitor.check_interval if monitor.is_running() else None
                ),
                "event_count": len(monitor.events),
            }
        except Exception as e:
            logger.error(f"Error getting status: {e}", exc_info=True)
            return {"status": "error", "message": f"Failed to get status: {str(e)}"}
