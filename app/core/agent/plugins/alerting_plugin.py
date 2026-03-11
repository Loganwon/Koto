"""
Phase 5b: AlertingPlugin

Provides alert management tools for the unified agent.
Integrates with AlertManager for email and webhook notifications.
"""

import logging
from typing import Any, Dict, List, Optional

from app.core.agent.base import AgentPlugin
from app.core.monitoring.alert_manager import AlertChannel, AlertRule, get_alert_manager

logger = logging.getLogger(__name__)


class AlertingPlugin(AgentPlugin):
    """
    Alerting plugin for system monitoring.

    Tools:
    - configure_email_alerts: Setup email alerting
    - add_webhook_alert: Register webhook endpoint
    - create_alert_rule: Add alert rule
    - disable_alert_rule: Disable rule
    - enable_alert_rule: Enable rule
    - get_alert_rules: List all rules
    - get_alert_history: View recent alerts
    - test_alert_rule: Test a rule
    """

    @property
    def name(self) -> str:
        """Plugin name."""
        return "AlertingPlugin"

    @property
    def description(self) -> str:
        """Plugin description."""
        return "Email and webhook alerting for system events"

    def __init__(self):
        """Initialize alerting plugin."""
        self.alert_manager = get_alert_manager()

    def get_tools(self) -> List[Dict[str, Any]]:
        """Return tool definitions."""
        return [
            {
                "name": "configure_email_alerts",
                "func": self.configure_email_alerts,
                "description": "Configure email alerting with SMTP settings",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "smtp_server": {
                            "type": "STRING",
                            "description": "SMTP server address (e.g., smtp.gmail.com)",
                        },
                        "smtp_port": {
                            "type": "INTEGER",
                            "description": "SMTP port (typically 587 for TLS)",
                        },
                        "sender_email": {
                            "type": "STRING",
                            "description": "Email address to send from",
                        },
                        "sender_password": {
                            "type": "STRING",
                            "description": "Email password or app-specific token",
                        },
                        "recipients": {
                            "type": "ARRAY",
                            "description": "List of recipient email addresses",
                        },
                    },
                    "required": [
                        "smtp_server",
                        "smtp_port",
                        "sender_email",
                        "sender_password",
                        "recipients",
                    ],
                },
            },
            {
                "name": "add_webhook_alert",
                "func": self.add_webhook_alert,
                "description": "Register webhook endpoint for alerts (Slack, Teams, Discord, etc.)",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "webhook_name": {
                            "type": "STRING",
                            "description": "Name for this webhook (e.g., 'slack', 'teams')",
                        },
                        "webhook_url": {
                            "type": "STRING",
                            "description": "Full webhook URL to receive alerts",
                        },
                    },
                    "required": ["webhook_name", "webhook_url"],
                },
            },
            {
                "name": "create_alert_rule",
                "func": self.create_alert_rule,
                "description": "Create and enable a new alert rule",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "rule_name": {
                            "type": "STRING",
                            "description": "Unique name for this rule",
                        },
                        "event_types": {
                            "type": "ARRAY",
                            "description": "Event types to match (e.g., ['cpu_high', 'memory_high'])",
                        },
                        "min_severity": {
                            "type": "STRING",
                            "description": "Minimum severity: low, medium, high",
                        },
                        "alert_channels": {
                            "type": "ARRAY",
                            "description": "Delivery channels: email, webhook, log",
                        },
                    },
                    "required": [
                        "rule_name",
                        "event_types",
                        "min_severity",
                        "alert_channels",
                    ],
                },
            },
            {
                "name": "disable_alert_rule",
                "func": self.disable_alert_rule,
                "description": "Disable an alert rule temporarily",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "rule_name": {
                            "type": "STRING",
                            "description": "Name of rule to disable",
                        }
                    },
                    "required": ["rule_name"],
                },
            },
            {
                "name": "enable_alert_rule",
                "func": self.enable_alert_rule,
                "description": "Re-enable a disabled alert rule",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "rule_name": {
                            "type": "STRING",
                            "description": "Name of rule to enable",
                        }
                    },
                    "required": ["rule_name"],
                },
            },
            {
                "name": "get_alert_rules",
                "func": self.get_alert_rules,
                "description": "List all alert rules and their configurations",
                "parameters": {"type": "OBJECT", "properties": {}},
            },
            {
                "name": "get_alert_history",
                "func": self.get_alert_history,
                "description": "Get recent alerts that have been triggered",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "limit": {
                            "type": "INTEGER",
                            "description": "Number of recent alerts to return (default: 50)",
                        }
                    },
                },
            },
            {
                "name": "test_alert_rule",
                "func": self.test_alert_rule,
                "description": "Test an alert rule by sending a test alert",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "rule_name": {
                            "type": "STRING",
                            "description": "Name of rule to test",
                        }
                    },
                    "required": ["rule_name"],
                },
            },
        ]

    def configure_email_alerts(
        self,
        smtp_server: str,
        smtp_port: int,
        sender_email: str,
        sender_password: str,
        recipients: List[str],
    ) -> str:
        """Configure email alerting."""
        try:
            result = self.alert_manager.configure_email(
                smtp_server=smtp_server,
                smtp_port=smtp_port,
                sender_email=sender_email,
                sender_password=sender_password,
                recipients=recipients,
            )

            if result:
                return f"Email alerting configured successfully. Recipients: {', '.join(recipients)}"
            else:
                return "Failed to configure email alerting"
        except Exception as e:
            return f"Error configuring email alerts: {str(e)}"

    def add_webhook_alert(self, webhook_name: str, webhook_url: str) -> str:
        """Add webhook alert."""
        try:
            result = self.alert_manager.add_webhook(name=webhook_name, url=webhook_url)

            if result:
                return f"Webhook '{webhook_name}' registered successfully"
            else:
                return f"Failed to register webhook '{webhook_name}'"
        except Exception as e:
            return f"Error adding webhook: {str(e)}"

    def create_alert_rule(
        self,
        rule_name: str,
        event_types: List[str],
        min_severity: str,
        alert_channels: List[str],
    ) -> str:
        """Create alert rule."""
        try:
            # Convert channel strings to AlertChannel enums
            channels = []
            for ch in alert_channels:
                if ch.lower() == "email":
                    channels.append(AlertChannel.EMAIL)
                elif ch.lower() == "webhook":
                    channels.append(AlertChannel.WEBHOOK)
                elif ch.lower() == "log":
                    channels.append(AlertChannel.LOG)

            rule = AlertRule(
                name=rule_name,
                event_types=event_types,
                min_severity=min_severity,
                channels=channels,
            )

            result = self.alert_manager.add_rule(rule)

            if result:
                return (
                    f"Alert rule '{rule_name}' created successfully.\n"
                    f"Events: {', '.join(event_types)}\n"
                    f"Min Severity: {min_severity}\n"
                    f"Channels: {', '.join(alert_channels)}"
                )
            else:
                return f"Failed to create rule '{rule_name}'"
        except Exception as e:
            return f"Error creating alert rule: {str(e)}"

    def disable_alert_rule(self, rule_name: str) -> str:
        """Disable alert rule."""
        if rule_name not in self.alert_manager.rules:
            return f"Rule '{rule_name}' not found"

        self.alert_manager.rules[rule_name].enabled = False
        return f"Alert rule '{rule_name}' disabled"

    def enable_alert_rule(self, rule_name: str) -> str:
        """Enable alert rule."""
        if rule_name not in self.alert_manager.rules:
            return f"Rule '{rule_name}' not found"

        self.alert_manager.rules[rule_name].enabled = True
        return f"Alert rule '{rule_name}' enabled"

    def get_alert_rules(self) -> str:
        """Get all alert rules."""
        rules = self.alert_manager.get_rules()

        if not rules:
            return "No alert rules configured"

        result = "Alert Rules:\n\n"
        for rule_name, config in rules.items():
            result += f"Rule: {rule_name}\n"
            result += f"  Events: {', '.join(config['event_types'])}\n"
            result += f"  Min Severity: {config['min_severity']}\n"
            result += f"  Channels: {', '.join(config['channels'])}\n"
            result += f"  Enabled: {config['enabled']}\n\n"

        return result

    def get_alert_history(self, limit: int = 50) -> str:
        """Get alert history."""
        history = self.alert_manager.get_alert_history(limit)

        if not history:
            return "No alerts in history"

        result = f"Recent Alerts (last {len(history)}):\n\n"
        for alert in reversed(history):
            result += f"ID: {alert['id']}\n"
            result += f"  Rule: {alert['rule']}\n"
            result += f"  Event: {alert['event_type']}\n"
            result += f"  Severity: {alert['severity']}\n"
            result += f"  Channels: {', '.join(alert['channels'])}\n"
            result += f"  Time: {alert['timestamp']}\n\n"

        return result

    def test_alert_rule(self, rule_name: str) -> str:
        """Test alert rule."""
        if rule_name not in self.alert_manager.rules:
            return f"Rule '{rule_name}' not found"

        # Create a test event
        test_event = {
            "event_type": self.alert_manager.rules[rule_name].event_types[0],
            "severity": self.alert_manager.rules[rule_name].min_severity,
            "metric_name": "test_metric",
            "metric_value": 95,
            "threshold": 80,
            "description": f"Test alert for rule '{rule_name}'",
            "timestamp": None,
        }

        rule = self.alert_manager.rules[rule_name]
        alert_id = self.alert_manager._send_alerts(rule, test_event)

        if alert_id:
            return (
                f"Test alert sent successfully for rule '{rule_name}' (ID: {alert_id})"
            )
        else:
            return f"Failed to send test alert for rule '{rule_name}'"

    def _configure_email_alerts(self, params: Dict[str, Any]) -> str:
        """Configure email alerting."""
        try:
            result = self.alert_manager.configure_email(
                smtp_server=params["smtp_server"],
                smtp_port=params["smtp_port"],
                sender_email=params["sender_email"],
                sender_password=params["sender_password"],
                recipients=params["recipients"],
            )

            if result:
                return f"Email alerting configured successfully. Recipients: {', '.join(params['recipients'])}"
            else:
                return "Failed to configure email alerting"
        except Exception as e:
            return f"Error configuring email alerts: {str(e)}"

    def _add_webhook_alert(self, params: Dict[str, Any]) -> str:
        """Add webhook alert."""
        try:
            result = self.alert_manager.add_webhook(
                name=params["webhook_name"], url=params["webhook_url"]
            )

            if result:
                return f"Webhook '{params['webhook_name']}' registered successfully"
            else:
                return f"Failed to register webhook '{params['webhook_name']}'"
        except Exception as e:
            return f"Error adding webhook: {str(e)}"

    def _create_alert_rule(self, params: Dict[str, Any]) -> str:
        """Create alert rule."""
        try:
            # Convert channel strings to AlertChannel enums
            channels = []
            for ch in params["alert_channels"]:
                if ch.lower() == "email":
                    channels.append(AlertChannel.EMAIL)
                elif ch.lower() == "webhook":
                    channels.append(AlertChannel.WEBHOOK)
                elif ch.lower() == "log":
                    channels.append(AlertChannel.LOG)

            rule = AlertRule(
                name=params["rule_name"],
                event_types=params["event_types"],
                min_severity=params["min_severity"],
                channels=channels,
            )

            result = self.alert_manager.add_rule(rule)

            if result:
                return (
                    f"Alert rule '{params['rule_name']}' created successfully.\n"
                    f"Events: {', '.join(params['event_types'])}\n"
                    f"Min Severity: {params['min_severity']}\n"
                    f"Channels: {', '.join(params['alert_channels'])}"
                )
            else:
                return f"Failed to create rule '{params['rule_name']}'"
        except Exception as e:
            return f"Error creating alert rule: {str(e)}"

    def _disable_alert_rule(self, params: Dict[str, Any]) -> str:
        """Disable alert rule."""
        rule_name = params["rule_name"]

        if rule_name not in self.alert_manager.rules:
            return f"Rule '{rule_name}' not found"

        self.alert_manager.rules[rule_name].enabled = False
        return f"Alert rule '{rule_name}' disabled"

    def _enable_alert_rule(self, params: Dict[str, Any]) -> str:
        """Enable alert rule."""
        rule_name = params["rule_name"]

        if rule_name not in self.alert_manager.rules:
            return f"Rule '{rule_name}' not found"

        self.alert_manager.rules[rule_name].enabled = True
        return f"Alert rule '{rule_name}' enabled"

    def _get_alert_rules(self) -> str:
        """Get all alert rules."""
        rules = self.alert_manager.get_rules()

        if not rules:
            return "No alert rules configured"

        result = "Alert Rules:\n\n"
        for rule_name, config in rules.items():
            result += f"Rule: {rule_name}\n"
            result += f"  Events: {', '.join(config['event_types'])}\n"
            result += f"  Min Severity: {config['min_severity']}\n"
            result += f"  Channels: {', '.join(config['channels'])}\n"
            result += f"  Enabled: {config['enabled']}\n\n"

        return result

    def _get_alert_history(self, params: Dict[str, Any]) -> str:
        """Get alert history."""
        limit = params.get("limit", 50)
        history = self.alert_manager.get_alert_history(limit)

        if not history:
            return "No alerts in history"

        result = f"Recent Alerts (last {len(history)}):\n\n"
        for alert in reversed(history):
            result += f"ID: {alert['id']}\n"
            result += f"  Rule: {alert['rule']}\n"
            result += f"  Event: {alert['event_type']}\n"
            result += f"  Severity: {alert['severity']}\n"
            result += f"  Channels: {', '.join(alert['channels'])}\n"
            result += f"  Time: {alert['timestamp']}\n\n"

        return result

    def _test_alert_rule(self, params: Dict[str, Any]) -> str:
        """Test alert rule."""
        rule_name = params["rule_name"]

        if rule_name not in self.alert_manager.rules:
            return f"Rule '{rule_name}' not found"

        # Create a test event
        test_event = {
            "event_type": self.alert_manager.rules[rule_name].event_types[0],
            "severity": self.alert_manager.rules[rule_name].min_severity,
            "metric_name": "test_metric",
            "metric_value": 95,
            "threshold": 80,
            "description": f"Test alert for rule '{rule_name}'",
            "timestamp": None,
        }

        rule = self.alert_manager.rules[rule_name]
        alert_id = self.alert_manager._send_alerts(rule, test_event)

        if alert_id:
            return (
                f"Test alert sent successfully for rule '{rule_name}' (ID: {alert_id})"
            )
        else:
            return f"Failed to send test alert for rule '{rule_name}'"
