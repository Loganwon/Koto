"""
Phase 5e: Configuration System

Manages system thresholds and alert configuration.
"""

import json
import logging
import threading
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class ConfigurationManager:
    """
    Manages system monitoring thresholds and settings.
    """

    # Default thresholds
    DEFAULT_THRESHOLDS = {
        "cpu": {"warning": 70, "critical": 85},
        "memory": {"warning": 75, "critical": 90},
        "disk": {"warning": 80, "critical": 95},
        "process_cpu": {"warning": 30, "critical": 50},
        "process_memory": {"warning": 200, "critical": 500},
        "network_latency": {"warning": 100, "critical": 200},
        "event_rate": {"warning": 5, "critical": 20},
    }

    def __init__(self):
        """Initialize configuration manager."""
        # Deep copy defaults for each instance
        self.thresholds = {k: dict(v) for k, v in self.DEFAULT_THRESHOLDS.items()}
        self.settings = {}
        self.lock = threading.Lock()

    def set_threshold(self, metric: str, level: str, value: float) -> bool:
        """
        Set a threshold value.

        Args:
            metric: Metric name (cpu, memory, disk, etc.)
            level: Severity level (warning, critical)
            value: Threshold value

        Returns:
            True if successful
        """
        with self.lock:
            if metric not in self.thresholds:
                logger.warning(f"Unknown metric: {metric}")
                return False

            if level not in ["warning", "critical"]:
                logger.warning(f"Invalid level: {level}")
                return False

            self.thresholds[metric][level] = value
            logger.info(f"Set {metric} {level} threshold to {value}")
            return True

    def get_threshold(self, metric: str, level: Optional[str] = None) -> Any:
        """Get threshold value."""
        with self.lock:
            if metric not in self.thresholds:
                return None

            if level:
                return self.thresholds[metric].get(level)
            else:
                return self.thresholds[metric]

    def get_all_thresholds(self) -> Dict[str, Any]:
        """Get all configured thresholds."""
        with self.lock:
            return dict(self.thresholds)

    def reset_threshold(self, metric: str) -> bool:
        """Reset metric to default threshold."""
        with self.lock:
            if metric not in self.DEFAULT_THRESHOLDS:
                logger.warning(f"Unknown metric: {metric}")
                return False

            # Deep copy of defaults to avoid cross-contamination
            self.thresholds[metric] = dict(self.DEFAULT_THRESHOLDS[metric])
            logger.info(f"Reset {metric} to defaults")
            return True

    def reset_all_thresholds(self) -> bool:
        """Reset all thresholds to defaults."""
        with self.lock:
            # Deep copy all defaults
            self.thresholds = {k: dict(v) for k, v in self.DEFAULT_THRESHOLDS.items()}
            logger.info("Reset all thresholds to defaults")
            return True

    def set_setting(self, key: str, value: Any) -> bool:
        """Set a configuration setting."""
        with self.lock:
            self.settings[key] = value
            logger.info(f"Set configuration: {key} = {value}")
            return True

    def get_setting(self, key: str, default: Any = None) -> Any:
        """Get a configuration setting."""
        with self.lock:
            return self.settings.get(key, default)

    def get_all_settings(self) -> Dict[str, Any]:
        """Get all settings."""
        with self.lock:
            return dict(self.settings)

    def export_config(self) -> str:
        """Export configuration as JSON."""
        with self.lock:
            config = {
                "thresholds": self.thresholds,
                "settings": self.settings,
                "exported_at": __import__("datetime").datetime.now().isoformat(),
            }
            return json.dumps(config, indent=2)

    def import_config(self, config_json: str) -> bool:
        """Import configuration from JSON."""
        try:
            config = json.loads(config_json)

            with self.lock:
                if "thresholds" in config:
                    self.thresholds = config["thresholds"]
                if "settings" in config:
                    self.settings = config["settings"]

            logger.info("Configuration imported successfully")
            return True
        except Exception as e:
            logger.error(f"Error importing configuration: {e}")
            return False

    def validate_metric_value(self, metric: str, value: float) -> Dict[str, Any]:
        """
        Validate a metric value against thresholds.

        Args:
            metric: Metric name
            value: Current value

        Returns:
            Validation result dict
        """
        thresholds = self.get_threshold(metric)

        if not thresholds:
            return {
                "valid": True,
                "status": "unknown",
                "message": "No thresholds for metric",
            }

        critical = thresholds.get("critical", float("inf"))
        warning = thresholds.get("warning", float("inf"))

        if value >= critical:
            return {
                "valid": False,
                "status": "critical",
                "message": f"{metric} exceeded critical threshold ({value} >= {critical})",
            }
        elif value >= warning:
            return {
                "valid": False,
                "status": "warning",
                "message": f"{metric} exceeded warning threshold ({value} >= {warning})",
            }
        else:
            return {
                "valid": True,
                "status": "normal",
                "message": f"{metric} is within normal range ({value} < {warning})",
            }


# Global instance
_config_manager: Optional[ConfigurationManager] = None
_config_lock = threading.Lock()


def get_config_manager() -> ConfigurationManager:
    """Get or create the singleton ConfigurationManager instance."""
    global _config_manager

    if _config_manager is None:
        with _config_lock:
            if _config_manager is None:
                _config_manager = ConfigurationManager()

    return _config_manager
