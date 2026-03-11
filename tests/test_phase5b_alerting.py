"""
Test Phase 5b: Alerting System

Tests for email/webhook alerting, alert rules, and alert history.
"""

import json
import unittest
from unittest.mock import MagicMock, Mock, patch

from app.core.agent.plugins.alerting_plugin import AlertingPlugin
from app.core.monitoring.alert_manager import (
    AlertChannel,
    AlertManager,
    AlertRule,
    get_alert_manager,
)


class TestAlertRule(unittest.TestCase):
    """Test AlertRule class."""

    def test_rule_creation(self):
        """Test alert rule creation."""
        rule = AlertRule("test_rule", ["cpu_high", "memory_high"], min_severity="high")

        self.assertEqual(rule.name, "test_rule")
        self.assertEqual(rule.event_types, ["cpu_high", "memory_high"])
        self.assertEqual(rule.min_severity, "high")
        self.assertTrue(rule.enabled)

    def test_rule_matches_event(self):
        """Test rule event matching."""
        rule = AlertRule("cpu_rule", ["cpu_high"], min_severity="high")

        # Matching event
        matching_event = {
            "event_type": "cpu_high",
            "severity": "high",
            "description": "CPU usage high",
        }
        self.assertTrue(rule.matches(matching_event))

        # Non-matching event (wrong type)
        non_matching = {
            "event_type": "memory_high",
            "severity": "high",
            "description": "Memory high",
        }
        self.assertFalse(rule.matches(non_matching))

        # Non-matching event (too low severity)
        low_severity = {
            "event_type": "cpu_high",
            "severity": "medium",
            "description": "CPU usage",
        }
        self.assertFalse(rule.matches(low_severity))

    def test_rule_disabled(self):
        """Test disabled rule doesn't match."""
        rule = AlertRule("disabled_rule", ["cpu_high"], min_severity="high")
        rule.enabled = False

        event = {"event_type": "cpu_high", "severity": "high"}

        self.assertFalse(rule.matches(event))

    def test_rule_to_dict(self):
        """Test rule serialization."""
        rule = AlertRule(
            "test_rule",
            ["cpu_high"],
            min_severity="medium",
            channels=[AlertChannel.EMAIL, AlertChannel.LOG],
        )

        rule_dict = rule.to_dict()

        self.assertEqual(rule_dict["name"], "test_rule")
        self.assertEqual(rule_dict["event_types"], ["cpu_high"])
        self.assertEqual(rule_dict["min_severity"], "medium")
        self.assertIn("email", rule_dict["channels"])
        self.assertIn("log", rule_dict["channels"])


class TestAlertManager(unittest.TestCase):
    """Test AlertManager class."""

    def setUp(self):
        """Set up test fixtures."""
        self.manager = AlertManager()

    def test_manager_initialization(self):
        """Test manager initialization."""
        self.assertIsNotNone(self.manager)
        self.assertEqual(len(self.manager.rules), 0)
        self.assertEqual(len(self.manager.alert_history), 0)

    def test_configure_email(self):
        """Test email configuration."""
        result = self.manager.configure_email(
            smtp_server="smtp.gmail.com",
            smtp_port=587,
            sender_email="test@example.com",
            sender_password="password",
            recipients=["admin@example.com"],
        )

        self.assertTrue(result)
        self.assertIsNotNone(self.manager.email_config)
        self.assertEqual(self.manager.email_config["smtp_server"], "smtp.gmail.com")
        self.assertEqual(self.manager.email_config["smtp_port"], 587)

    def test_add_webhook(self):
        """Test webhook configuration."""
        result = self.manager.add_webhook("slack", "https://hooks.slack.com/webhook")

        self.assertTrue(result)
        self.assertIn("slack", self.manager.webhook_urls)
        self.assertEqual(
            self.manager.webhook_urls["slack"], "https://hooks.slack.com/webhook"
        )

    def test_add_rule(self):
        """Test adding alert rule."""
        rule = AlertRule("test_rule", ["cpu_high"])
        result = self.manager.add_rule(rule)

        self.assertTrue(result)
        self.assertIn("test_rule", self.manager.rules)

    def test_process_event_matching_rule(self):
        """Test event processing with matching rule."""
        rule = AlertRule("cpu_rule", ["cpu_high"])
        self.manager.add_rule(rule)

        event = {
            "event_type": "cpu_high",
            "severity": "high",
            "metric_name": "cpu_usage",
            "metric_value": 95,
            "threshold": 80,
            "description": "CPU high",
        }

        alert_ids = self.manager.process_event(event)

        self.assertTrue(len(alert_ids) > 0)
        self.assertEqual(len(self.manager.alert_history), 1)

    def test_process_event_no_matching_rule(self):
        """Test event processing with no matching rules."""
        rule = AlertRule("cpu_rule", ["cpu_high"])
        self.manager.add_rule(rule)

        event = {
            "event_type": "memory_high",
            "severity": "high",
            "description": "Memory high",
        }

        alert_ids = self.manager.process_event(event)

        self.assertEqual(len(alert_ids), 0)
        self.assertEqual(len(self.manager.alert_history), 0)

    def test_get_alert_history(self):
        """Test alert history retrieval."""
        rule = AlertRule("test_rule", ["cpu_high"])
        self.manager.add_rule(rule)

        # Generate multiple alerts
        for i in range(5):
            event = {
                "event_type": "cpu_high",
                "severity": "high",
                "description": f"CPU alert {i}",
            }
            self.manager.process_event(event)

        history = self.manager.get_alert_history(limit=10)
        self.assertEqual(len(history), 5)

    def test_get_rules(self):
        """Test rules retrieval."""
        rule1 = AlertRule("rule1", ["cpu_high"])
        rule2 = AlertRule("rule2", ["memory_high"])

        self.manager.add_rule(rule1)
        self.manager.add_rule(rule2)

        rules = self.manager.get_rules()

        self.assertEqual(len(rules), 2)
        self.assertIn("rule1", rules)
        self.assertIn("rule2", rules)

    @patch("smtplib.SMTP")
    def test_send_email_alert(self, mock_smtp):
        """Test email alert sending."""
        # Configure email
        self.manager.configure_email(
            smtp_server="smtp.gmail.com",
            smtp_port=587,
            sender_email="test@example.com",
            sender_password="password",
            recipients=["admin@example.com"],
        )

        rule = AlertRule("test_rule", ["cpu_high"], channels=[AlertChannel.EMAIL])
        event = {
            "event_type": "cpu_high",
            "severity": "high",
            "metric_name": "cpu",
            "metric_value": 95,
            "threshold": 80,
            "description": "CPU high",
            "timestamp": "2024-01-01T00:00:00",
        }

        # Mock SMTP
        mock_smtp_instance = MagicMock()
        mock_smtp.return_value = mock_smtp_instance

        # Send alert
        self.manager._send_alerts(rule, event)

        # Verify alert added to history
        self.assertEqual(len(self.manager.alert_history), 1)


class TestAlertingPlugin(unittest.TestCase):
    """Test AlertingPlugin."""

    def setUp(self):
        """Set up test fixtures."""
        self.plugin = AlertingPlugin()

    def test_plugin_initialization(self):
        """Test plugin initialization."""
        self.assertEqual(self.plugin.name, "AlertingPlugin")
        self.assertIsNotNone(self.plugin.alert_manager)

    def test_get_tools(self):
        """Test tool definitions."""
        tools = self.plugin.get_tools()

        self.assertEqual(len(tools), 8)
        tool_names = [t["name"] for t in tools]

        self.assertIn("configure_email_alerts", tool_names)
        self.assertIn("add_webhook_alert", tool_names)
        self.assertIn("create_alert_rule", tool_names)
        self.assertIn("disable_alert_rule", tool_names)
        self.assertIn("enable_alert_rule", tool_names)
        self.assertIn("get_alert_rules", tool_names)
        self.assertIn("get_alert_history", tool_names)
        self.assertIn("test_alert_rule", tool_names)

    def test_configure_email_alerts_tool(self):
        """Test configure email alerts tool."""
        result = self.plugin.configure_email_alerts(
            smtp_server="smtp.gmail.com",
            smtp_port=587,
            sender_email="test@example.com",
            sender_password="password",
            recipients=["admin@example.com", "ops@example.com"],
        )

        self.assertIn("success", result.lower())
        self.assertIn("admin@example.com", result)
        self.assertIn("ops@example.com", result)

    def test_add_webhook_alert_tool(self):
        """Test add webhook alert tool."""
        result = self.plugin.add_webhook_alert(
            webhook_name="slack", webhook_url="https://hooks.slack.com/webhook"
        )

        self.assertIn("slack", result)
        self.assertIn("success", result.lower())

    def test_create_alert_rule_tool(self):
        """Test create alert rule tool."""
        result = self.plugin.create_alert_rule(
            rule_name="cpu_alert",
            event_types=["cpu_high", "cpu_spike"],
            min_severity="high",
            alert_channels=["email", "webhook", "log"],
        )

        self.assertIn("cpu_alert", result)
        self.assertIn("success", result.lower())

    def test_disable_alert_rule_tool(self):
        """Test disable alert rule tool."""
        # First create a rule
        self.plugin.create_alert_rule(
            rule_name="test_rule",
            event_types=["cpu_high"],
            min_severity="high",
            alert_channels=["log"],
        )

        # Then disable it
        result = self.plugin.disable_alert_rule(rule_name="test_rule")

        self.assertIn("disabled", result.lower())
        self.assertFalse(self.plugin.alert_manager.rules["test_rule"].enabled)

    def test_enable_alert_rule_tool(self):
        """Test enable alert rule tool."""
        # First create and disable a rule
        self.plugin.create_alert_rule(
            rule_name="test_rule",
            event_types=["cpu_high"],
            min_severity="high",
            alert_channels=["log"],
        )
        self.plugin.disable_alert_rule(rule_name="test_rule")

        # Then enable it
        result = self.plugin.enable_alert_rule(rule_name="test_rule")

        self.assertIn("enabled", result.lower())
        self.assertTrue(self.plugin.alert_manager.rules["test_rule"].enabled)

    def test_get_alert_rules_tool(self):
        """Test get alert rules tool."""
        # Create some rules
        self.plugin.create_alert_rule(
            rule_name="rule1",
            event_types=["cpu_high"],
            min_severity="high",
            alert_channels=["log"],
        )
        self.plugin.create_alert_rule(
            rule_name="rule2",
            event_types=["memory_high"],
            min_severity="medium",
            alert_channels=["email"],
        )

        result = self.plugin.get_alert_rules()

        self.assertIn("rule1", result)
        self.assertIn("rule2", result)
        self.assertIn("cpu_high", result)
        self.assertIn("memory_high", result)

    def test_get_alert_history_tool(self):
        """Test get alert history tool."""
        # Create a rule and process an event
        self.plugin.create_alert_rule(
            rule_name="cpu_rule",
            event_types=["cpu_high"],
            min_severity="high",
            alert_channels=["log"],
        )

        event = {
            "event_type": "cpu_high",
            "severity": "high",
            "metric_name": "cpu",
            "metric_value": 95,
            "threshold": 80,
            "description": "CPU high",
            "timestamp": "2024-01-01T00:00:00",
        }
        self.plugin.alert_manager.process_event(event)

        result = self.plugin.get_alert_history(limit=10)

        self.assertIn("cpu", result)
        self.assertIn("alert", result.lower())

    def test_tool_error_handling(self):
        """Test tool error handling."""
        result = self.plugin.disable_alert_rule(rule_name="nonexistent")

        self.assertIn("not found", result.lower())


class TestAlertIntegration(unittest.TestCase):
    """Integration tests for alerting system."""

    def test_end_to_end_alert_workflow(self):
        """Test complete alert workflow."""
        plugin = AlertingPlugin()

        # Step 1: Configure email
        plugin.configure_email_alerts(
            smtp_server="smtp.gmail.com",
            smtp_port=587,
            sender_email="test@example.com",
            sender_password="password",
            recipients=["admin@example.com"],
        )

        # Step 2: Add webhook
        plugin.add_webhook_alert(
            webhook_name="slack", webhook_url="https://hooks.slack.com/webhook"
        )

        # Step 3: Create alert rules
        for rule_name, events in [
            ("cpu_alerts", ["cpu_high", "cpu_spike"]),
            ("memory_alerts", ["memory_high"]),
            ("disk_alerts", ["disk_full"]),
        ]:
            plugin.create_alert_rule(
                rule_name=rule_name,
                event_types=events,
                min_severity="high",
                alert_channels=["email", "webhook"],
            )

        # Step 4: Get rules
        rules_result = plugin.get_alert_rules()
        self.assertIn("cpu_alerts", rules_result)
        self.assertIn("memory_alerts", rules_result)
        self.assertIn("disk_alerts", rules_result)

        # Step 5: Process events and verify alerts
        plugin.alert_manager.process_event(
            {
                "event_type": "cpu_high",
                "severity": "high",
                "metric_name": "cpu",
                "metric_value": 95,
                "threshold": 80,
                "description": "CPU high",
                "timestamp": "2024-01-01T00:00:00",
            }
        )

        # Step 6: Check alert history
        history = plugin.get_alert_history(limit=10)
        self.assertIn("cpu", history)


if __name__ == "__main__":
    unittest.main()
