"""
Test Phase 5c, 5d, 5e: Full system testing

Tests for Auto-Remediation, Trend Analysis, and Configuration.
"""

import json
import unittest

from app.core.agent.plugins.auto_remediation_plugin import AutoRemediationPlugin
from app.core.agent.plugins.configuration_plugin import ConfigurationPlugin
from app.core.agent.plugins.trend_analysis_plugin import TrendAnalysisPlugin
from app.core.analytics.trend_analyzer import TrendAnalyzer
from app.core.config.configuration_manager import ConfigurationManager
from app.core.remediation.remediation_manager import (
    RemediationAction,
    RemediationManager,
    RemediationStatus,
)


class TestAutoRemediation(unittest.TestCase):
    """Test auto-remediation system."""

    def setUp(self):
        self.manager = RemediationManager()

    def test_create_action(self):
        """Test creating remediation action."""
        action_id = self.manager.create_action(
            event_id=1,
            action_type="restart_service",
            description="Restart failing service",
        )

        self.assertIsNotNone(action_id)
        self.assertEqual(len(action_id) > 0, True)

    def test_approve_action(self):
        """Test approving action."""
        action_id = self.manager.create_action(
            event_id=1, action_type="clear_cache", description="Clear application cache"
        )

        result = self.manager.approve_action(action_id)
        self.assertTrue(result)

        action = self.manager.get_action(action_id)
        self.assertEqual(action["status"], RemediationStatus.APPROVED.value)

    def test_reject_action(self):
        """Test rejecting action."""
        action_id = self.manager.create_action(
            event_id=2,
            action_type="reboot",
            description="System reboot",
            risk_level="high",
        )

        result = self.manager.reject_action(action_id, "Too risky")
        self.assertTrue(result)

        action = self.manager.get_action(action_id)
        self.assertEqual(action["status"], RemediationStatus.REJECTED.value)

    def test_get_pending_actions(self):
        """Test getting pending actions."""
        for i in range(3):
            self.manager.create_action(
                event_id=i, action_type=f"action_{i}", description=f"Description {i}"
            )

        pending = self.manager.get_pending_actions()
        self.assertEqual(len(pending), 3)

    def test_remediation_stats(self):
        """Test remediation statistics."""
        # Create multiple actions with different statuses
        id1 = self.manager.create_action(1, "action1", "desc1")
        id2 = self.manager.create_action(2, "action2", "desc2")

        self.manager.approve_action(id1)
        self.manager.reject_action(id2)

        stats = self.manager.get_stats()

        self.assertEqual(stats["total_actions"], 2)
        self.assertEqual(stats["by_status"]["pending"], 0)
        self.assertEqual(stats["by_status"]["approved"], 1)
        self.assertEqual(stats["by_status"]["rejected"], 1)


class TestTrendAnalysis(unittest.TestCase):
    """Test trend analysis system."""

    def setUp(self):
        self.analyzer = TrendAnalyzer()

    def test_analyze_trends(self):
        """Test trend analysis."""
        events = [
            {"event_type": "cpu_high", "severity": "high"},
            {"event_type": "cpu_high", "severity": "high"},
            {"event_type": "memory_high", "severity": "medium"},
            {"event_type": "cpu_high", "severity": "high"},
            {"event_type": "disk_full", "severity": "high"},
        ]

        result = self.analyzer.analyze_event_trends(events, hours_back=24)

        self.assertEqual(result["total_events"], 5)
        self.assertIn("cpu_high", result["event_types"])
        self.assertEqual(result["event_types"]["cpu_high"], 3)

    def test_predict_issues(self):
        """Test issue prediction."""
        events = [{"event_type": "cpu_high", "severity": "high"} for _ in range(10)]
        metrics = {"cpu_usage": 95, "memory_usage": 50}

        result = self.analyzer.predict_issues(events, metrics)

        self.assertGreater(len(result["predictions"]), 0)

    def test_anomaly_score(self):
        """Test anomaly scoring."""
        # Few events = normal (< 1 per hour = 0.0)
        normal_events = [{"event_type": "test", "severity": "low"} for _ in range(1)]
        normal_score = self.analyzer.get_anomaly_score(normal_events)
        self.assertLess(normal_score, 0.2)

        # Many events = anomalous (30 events / 24 hours = 1.25 per hour = 0.1, but in 1 hour = 30, so > 0.8)
        anomaly_events = [{"event_type": "test", "severity": "high"} for _ in range(30)]
        # Anomaly score with 1 hour window and 30 events
        anomaly_score = self.analyzer.get_anomaly_score(anomaly_events, hours_back=1)
        self.assertGreater(anomaly_score, 0.8)


class TestConfiguration(unittest.TestCase):
    """Test configuration system."""

    def setUp(self):
        self.manager = ConfigurationManager()

    def test_set_threshold(self):
        """Test setting thresholds."""
        result = self.manager.set_threshold("cpu", "warning", 75)
        self.assertTrue(result)

        value = self.manager.get_threshold("cpu", "warning")
        self.assertEqual(value, 75)

    def test_get_all_thresholds(self):
        """Test getting all thresholds."""
        thresholds = self.manager.get_all_thresholds()

        self.assertIn("cpu", thresholds)
        self.assertIn("memory", thresholds)
        self.assertIn("disk", thresholds)

    def test_reset_threshold(self):
        """Test resetting thresholds."""
        manager = ConfigurationManager()  # Fresh instance

        # Modify
        manager.set_threshold("cpu", "critical", 100)

        # Reset
        manager.reset_threshold("cpu")

        # Verify reset to default (85)
        value = manager.get_threshold("cpu", "critical")
        self.assertEqual(value, 85)

    def test_validate_metric(self):
        """Test metric validation."""
        manager = ConfigurationManager()  # Fresh instance

        # Normal value
        result = manager.validate_metric_value("cpu", 50)
        self.assertTrue(result["valid"])
        self.assertEqual(result["status"], "normal")

        # Warning level
        result = manager.validate_metric_value("cpu", 72)
        self.assertFalse(result["valid"])
        self.assertEqual(result["status"], "warning")

        # Critical level
        result = manager.validate_metric_value("cpu", 88)
        self.assertFalse(result["valid"])
        self.assertEqual(result["status"], "critical")

    def test_export_import_config(self):
        """Test config export/import."""
        # Modify config
        self.manager.set_threshold("memory", "warning", 85)

        # Export
        config_json = self.manager.export_config()

        # Create new manager and import
        new_manager = ConfigurationManager()
        new_manager.import_config(config_json)

        # Verify
        value = new_manager.get_threshold("memory", "warning")
        self.assertEqual(value, 85)


class TestPlugins(unittest.TestCase):
    """Test Phase 5 plugins."""

    def test_auto_remediation_plugin(self):
        """Test auto-remediation plugin."""
        plugin = AutoRemediationPlugin()

        self.assertEqual(plugin.name, "AutoRemediationPlugin")

        tools = plugin.get_tools()
        self.assertEqual(len(tools), 7)

        tool_names = {t["name"] for t in tools}
        self.assertIn("create_remediation_action", tool_names)
        self.assertIn("approve_remediation_action", tool_names)

    def test_trend_analysis_plugin(self):
        """Test trend analysis plugin."""
        plugin = TrendAnalysisPlugin()

        self.assertEqual(plugin.name, "TrendAnalysisPlugin")

        tools = plugin.get_tools()
        self.assertEqual(len(tools), 4)

        tool_names = {t["name"] for t in tools}
        self.assertIn("analyze_event_trends", tool_names)
        self.assertIn("predict_potential_issues", tool_names)

    def test_configuration_plugin(self):
        """Test configuration plugin."""
        plugin = ConfigurationPlugin()

        self.assertEqual(plugin.name, "ConfigurationPlugin")

        tools = plugin.get_tools()
        self.assertEqual(len(tools), 5)

        tool_names = {t["name"] for t in tools}
        self.assertIn("set_threshold", tool_names)
        self.assertIn("get_thresholds", tool_names)


class TestPhase5Integration(unittest.TestCase):
    """Integration tests for Phase 5."""

    def test_remediation_workflow(self):
        """Test complete remediation workflow."""
        plugin = AutoRemediationPlugin()

        # Create action
        result = plugin.create_remediation_action(
            event_id=1, action_type="restart", description="Restart service"
        )

        self.assertIn("ID", result)

        # Approve action
        action_id = result.split("ID: ")[1].split(")")[0]
        approve_result = plugin.approve_remediation_action(action_id)

        self.assertIn("approved", approve_result.lower())

    def test_trend_analysis_workflow(self):
        """Test trend analysis workflow."""
        plugin = TrendAnalysisPlugin()

        events = json.dumps(
            [
                {"event_type": "cpu_high", "severity": "high"},
                {"event_type": "cpu_high", "severity": "high"},
                {"event_type": "memory_high", "severity": "medium"},
            ]
        )

        result = plugin.analyze_event_trends(events)

        self.assertIn("cpu_high", result)
        self.assertIn("Total Events", result)

    def test_configuration_workflow(self):
        """Test configuration workflow."""
        plugin = ConfigurationPlugin()

        # Get current thresholds
        result = plugin.get_thresholds()
        self.assertIn("cpu", result)

        # Set threshold
        set_result = plugin.set_threshold("cpu", "warning", 65)
        self.assertIn("success", set_result.lower())

        # Validate metric
        validate_result = plugin.validate_metric("cpu", 70)
        self.assertIn("warning", validate_result.lower())


if __name__ == "__main__":
    unittest.main()
