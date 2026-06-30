# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
Phase 5b: Alerting System

Local log notifications for monitoring events.
Supports customizable alert rules and severity thresholds.
"""

import logging
import threading
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class AlertChannel(Enum):
    """Alert delivery channels."""

    LOG = "log"


class AlertRule:
    """
    Rule for triggering alerts based on events.
    """

    def __init__(
        self,
        name: str,
        event_types: List[str],
        min_severity: str = "medium",
        channels: Optional[List[AlertChannel]] = None,
    ):
        """
        Initialize alert rule.

        Args:
            name: Rule name
            event_types: Event types to match (e.g., ['cpu_high', 'memory_high'])
            min_severity: Minimum severity to trigger alert (low, medium, high)
            channels: Alert delivery channels
        """
        self.name = name
        self.event_types = event_types
        self.min_severity = min_severity
        self.channels = channels or [AlertChannel.LOG]
        self.enabled = True

    def matches(self, event: Dict[str, Any]) -> bool:
        """Check if event matches this rule."""
        if not self.enabled:
            return False

        # Check event type
        if event.get("event_type") not in self.event_types:
            return False

        # Check severity
        severity_order = {"low": 0, "medium": 1, "high": 2}
        event_severity = severity_order.get(event.get("severity", "low"), 0)
        rule_severity = severity_order.get(self.min_severity, 1)

        return event_severity >= rule_severity

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict."""
        return {
            "name": self.name,
            "event_types": self.event_types,
            "min_severity": self.min_severity,
            "channels": [ch.value for ch in self.channels],
            "enabled": self.enabled,
        }


class AlertManager:
    """
    Manages alert rules and sends notifications.
    """

    _MAX_ALERT_HISTORY = 10000

    def __init__(self):
        """Initialize alert manager."""
        self.rules: Dict[str, AlertRule] = {}
        self.alert_history: List[Dict[str, Any]] = []
        self.handlers: Dict[AlertChannel, Callable] = {
            AlertChannel.LOG: self._send_log_alert,
        }

    def add_rule(self, rule: AlertRule) -> bool:
        """
        Add alert rule.

        Args:
            rule: AlertRule instance

        Returns:
            True if added
        """
        self.rules[rule.name] = rule
        logger.info(f"Alert rule '{rule.name}' added")
        return True

    def process_event(self, event: Dict[str, Any]) -> List[str]:
        """
        Check event against rules and send alerts.

        Args:
            event: Event dict from monitoring

        Returns:
            List of alert IDs sent
        """
        alert_ids = []

        for rule_name, rule in self.rules.items():
            if rule.matches(event):
                alert_id = self._send_alerts(rule, event)
                if alert_id:
                    alert_ids.append(alert_id)

        return alert_ids

    def _send_alerts(self, rule: AlertRule, event: Dict[str, Any]) -> Optional[str]:
        """Send alerts via configured channels for a rule."""
        alert_id = f"{event.get('event_type')}_{int(datetime.now().timestamp())}"

        try:
            for channel in rule.channels:
                if channel in self.handlers:
                    try:
                        self.handlers[channel](rule, event)
                    except Exception as e:
                        logger.error(f"Error sending {channel.value} alert: {e}")

            # Record in history
            self.alert_history.append(
                {
                    "id": alert_id,
                    "rule": rule.name,
                    "event_type": event.get("event_type"),
                    "severity": event.get("severity"),
                    "timestamp": datetime.now().isoformat(),
                    "channels": [ch.value for ch in rule.channels],
                }
            )

            if len(self.alert_history) > self._MAX_ALERT_HISTORY:
                self.alert_history = self.alert_history[-self._MAX_ALERT_HISTORY :]

            return alert_id
        except Exception as e:
            logger.error(f"Error processing alerts: {e}")
            return None

    def _send_log_alert(self, rule: AlertRule, event: Dict[str, Any]) -> None:
        """Log alert."""
        logger.warning(
            f"[ALERT: {rule.name}] {event.get('event_type')} - "
            f"{event.get('severity')}: {event.get('description')}"
        )

    def get_alert_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent alerts."""
        return self.alert_history[-limit:]

    def get_rules(self) -> Dict[str, Dict[str, Any]]:
        """Get all alert rules."""
        return {name: rule.to_dict() for name, rule in self.rules.items()}


# Global instance
_alert_manager: Optional[AlertManager] = None
_alert_lock = threading.Lock()


def get_alert_manager() -> AlertManager:
    """Get or create the singleton AlertManager instance."""
    global _alert_manager

    if _alert_manager is None:
        with _alert_lock:
            if _alert_manager is None:
                _alert_manager = AlertManager()

                # Add default rules
                _alert_manager.add_rule(
                    AlertRule(
                        "cpu_critical", ["cpu_spike", "cpu_high"], min_severity="high"
                    )
                )
                _alert_manager.add_rule(
                    AlertRule("memory_warning", ["memory_high"], min_severity="medium")
                )
                _alert_manager.add_rule(
                    AlertRule(
                        "disk_critical", ["disk_full", "disk_high"], min_severity="high"
                    )
                )

    return _alert_manager
