"""
Phase 5e: Configuration Plugin

Provides tools for managing system thresholds and settings.
"""

import logging
from typing import Any, Dict, List, Optional

from app.core.agent.base import AgentPlugin
from app.core.config.configuration_manager import get_config_manager

logger = logging.getLogger(__name__)


class ConfigurationPlugin(AgentPlugin):
    """
    Configuration plugin for system settings and thresholds.

    Tools:
    - set_threshold: Configure alert thresholds
    - get_thresholds: View current thresholds
    - reset_thresholds: Reset to defaults
    - get_settings: View configuration settings
    - validate_metric: Check metric against thresholds
    """

    @property
    def name(self) -> str:
        """Plugin name."""
        return "ConfigurationPlugin"

    @property
    def description(self) -> str:
        """Plugin description."""
        return "System configuration and threshold management"

    def __init__(self):
        """Initialize plugin."""
        self.config_manager = get_config_manager()

    def get_tools(self) -> List[Dict[str, Any]]:
        """Return tool definitions."""
        return [
            {
                "name": "set_threshold",
                "func": self.set_threshold,
                "description": "Set alert threshold for a metric",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "metric": {
                            "type": "STRING",
                            "description": "Metric name (cpu, memory, disk, process_cpu, process_memory, network_latency, event_rate)",
                        },
                        "level": {
                            "type": "STRING",
                            "description": "Severity level: warning or critical",
                        },
                        "value": {"type": "NUMBER", "description": "Threshold value"},
                    },
                    "required": ["metric", "level", "value"],
                },
            },
            {
                "name": "get_thresholds",
                "func": self.get_thresholds,
                "description": "Get current threshold configuration",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "metric": {
                            "type": "STRING",
                            "description": "Specific metric (optional, shows all if not specified)",
                        }
                    },
                },
            },
            {
                "name": "reset_threshold",
                "func": self.reset_threshold,
                "description": "Reset metric threshold to default",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "metric": {
                            "type": "STRING",
                            "description": "Metric to reset (or 'all' for all metrics)",
                        }
                    },
                    "required": ["metric"],
                },
            },
            {
                "name": "get_configuration",
                "func": self.get_configuration,
                "description": "Get current system configuration",
                "parameters": {"type": "OBJECT", "properties": {}},
            },
            {
                "name": "validate_metric",
                "func": self.validate_metric,
                "description": "Validate a metric value against configured thresholds",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "metric": {"type": "STRING", "description": "Metric name"},
                        "value": {
                            "type": "NUMBER",
                            "description": "Metric value to validate",
                        },
                    },
                    "required": ["metric", "value"],
                },
            },
        ]

    def set_threshold(self, metric: str, level: str, value: float) -> str:
        """Set threshold."""
        try:
            result = self.config_manager.set_threshold(metric, level, value)

            if result:
                return (
                    f"Threshold set successfully:\n"
                    f"  Metric: {metric}\n"
                    f"  Level: {level}\n"
                    f"  Value: {value}"
                )
            else:
                return f"Failed to set threshold - check metric and level names"
        except Exception as e:
            return f"Error setting threshold: {str(e)}"

    def get_thresholds(self, metric: Optional[str] = None) -> str:
        """Get thresholds."""
        try:
            if metric:
                threshold = self.config_manager.get_threshold(metric)

                if threshold is None:
                    return f"Metric '{metric}' not found"

                result = f"Threshold for {metric}:\n"
                for level, value in threshold.items():
                    result += f"  {level}: {value}\n"
                return result
            else:
                all_thresholds = self.config_manager.get_all_thresholds()

                result = "All Thresholds:\n\n"
                for metric_name, levels in sorted(all_thresholds.items()):
                    result += f"{metric_name}:\n"
                    for level, value in levels.items():
                        result += f"  {level}: {value}\n"
                    result += "\n"
                return result
        except Exception as e:
            return f"Error getting thresholds: {str(e)}"

    def reset_threshold(self, metric: str) -> str:
        """Reset threshold."""
        try:
            if metric.lower() == "all":
                result = self.config_manager.reset_all_thresholds()
                if result:
                    return "All thresholds reset to defaults"
                else:
                    return "Failed to reset thresholds"
            else:
                result = self.config_manager.reset_threshold(metric)

                if result:
                    return (
                        f"Threshold for '{metric}' reset to default:\n"
                        f"{self.get_thresholds(metric)}"
                    )
                else:
                    return f"Failed to reset threshold for '{metric}'"
        except Exception as e:
            return f"Error resetting threshold: {str(e)}"

    def get_configuration(self) -> str:
        """Get configuration."""
        try:
            config_json = self.config_manager.export_config()

            result = "Current Configuration:\n\n"
            result += config_json

            return result
        except Exception as e:
            return f"Error getting configuration: {str(e)}"

    def validate_metric(self, metric: str, value: float) -> str:
        """Validate metric."""
        try:
            validation = self.config_manager.validate_metric_value(metric, value)

            result = f"Metric Validation:\n\n"
            result += f"Metric: {metric}\n"
            result += f"Value: {value}\n"
            result += f"Status: {validation['status'].upper()}\n"
            result += f"Message: {validation['message']}\n"

            return result
        except Exception as e:
            return f"Error validating metric: {str(e)}"
