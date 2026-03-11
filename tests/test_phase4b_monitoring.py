"""
Phase 4b: System Event Monitoring Tests

Tests for background system monitoring, anomaly detection, and event tracking.
"""

import threading
import time
import unittest

from app.core.monitoring.system_event_monitor import (
    SystemEvent,
    SystemEventMonitor,
    get_system_event_monitor,
)


class TestSystemEventMonitor(unittest.TestCase):
    """Test SystemEventMonitor core functionality."""

    def setUp(self):
        """Create fresh monitor instance for each test."""
        self.monitor = SystemEventMonitor(check_interval=1)

    def tearDown(self):
        """Stop monitor after test."""
        if self.monitor.is_running():
            self.monitor.stop()

    def test_monitor_initialization(self):
        """Test monitor initializes with correct defaults."""
        self.assertFalse(self.monitor.is_running())
        self.assertEqual(self.monitor.check_interval, 1)
        self.assertEqual(len(self.monitor.events), 0)

    def test_monitor_start_stop(self):
        """Test starting and stopping monitor."""
        self.assertFalse(self.monitor.is_running())

        self.monitor.start()
        time.sleep(0.1)
        self.assertTrue(self.monitor.is_running())

        self.monitor.stop()
        time.sleep(0.1)
        self.assertFalse(self.monitor.is_running())

    def test_multiple_start_calls(self):
        """Test that multiple start calls don't create duplicate threads."""
        self.monitor.start()
        time.sleep(0.1)
        thread1 = self.monitor.thread

        self.monitor.start()  # Should not create new thread
        time.sleep(0.1)
        thread2 = self.monitor.thread

        self.assertIs(thread1, thread2)
        self.monitor.stop()

    def test_event_recording(self):
        """Test recording events."""
        self.monitor._record_event(
            event_type="cpu_high",
            severity="high",
            metric_name="cpu_percent",
            metric_value=85.5,
            threshold=85,
            description="CPU usage high",
        )

        self.assertEqual(len(self.monitor.events), 1)
        event = self.monitor.events[0]
        self.assertEqual(event.event_type, "cpu_high")
        self.assertEqual(event.severity, "high")
        self.assertEqual(event.metric_value, 85.5)

    def test_get_events(self):
        """Test retrieving events."""
        # Record multiple events
        for i in range(5):
            self.monitor._record_event(
                event_type=f"type_{i}",
                severity="medium",
                metric_name=f"metric_{i}",
                metric_value=50.0 + i,
                threshold=80,
                description=f"Event {i}",
            )

        # Get all events
        events = self.monitor.get_events(limit=10)
        self.assertEqual(len(events), 5)

        # Get limited events (most recent first)
        events = self.monitor.get_events(limit=2)
        self.assertEqual(len(events), 2)
        # Most recent should be last recorded
        self.assertEqual(events[0]["event_type"], "type_4")

    def test_filter_by_event_type(self):
        """Test filtering events by type."""
        self.monitor._record_event(
            event_type="cpu_high",
            severity="high",
            metric_name="cpu",
            metric_value=90,
            threshold=85,
            description="CPU high",
        )
        self.monitor._record_event(
            event_type="memory_high",
            severity="high",
            metric_name="memory",
            metric_value=95,
            threshold=90,
            description="Memory high",
        )

        cpu_events = self.monitor.get_events(event_type="cpu_high")
        self.assertEqual(len(cpu_events), 1)
        self.assertEqual(cpu_events[0]["event_type"], "cpu_high")

    def test_event_limit_100(self):
        """Test that monitor keeps only last 100 events."""
        for i in range(150):
            self.monitor._record_event(
                event_type="test",
                severity="low",
                metric_name="test",
                metric_value=10,
                threshold=50,
                description=f"Event {i}",
            )

        self.assertEqual(len(self.monitor.events), 100)

    def test_get_summary(self):
        """Test health summary generation."""
        summary = self.monitor.get_summary()
        self.assertEqual(summary["total_events"], 0)
        self.assertEqual(summary["status"], "healthy")

        # Add high severity event
        self.monitor._record_event(
            event_type="critical",
            severity="high",
            metric_name="test",
            metric_value=100,
            threshold=80,
            description="Critical issue",
        )

        summary = self.monitor.get_summary()
        self.assertEqual(summary["total_events"], 1)
        self.assertEqual(summary["status"], "critical")
        self.assertIn("high", summary["by_severity"])

    def test_clear_events(self):
        """Test clearing event log."""
        for i in range(10):
            self.monitor._record_event(
                event_type="test",
                severity="low",
                metric_name="test",
                metric_value=10,
                threshold=50,
                description=f"Event {i}",
            )

        self.assertEqual(len(self.monitor.events), 10)
        count = self.monitor.clear_events()
        self.assertEqual(count, 10)
        self.assertEqual(len(self.monitor.events), 0)

    def test_event_callbacks(self):
        """Test event callback mechanism."""
        received_events = []

        def on_event(event: SystemEvent):
            received_events.append(event)

        self.monitor.register_callback(on_event)

        self.monitor._record_event(
            event_type="test",
            severity="low",
            metric_name="test",
            metric_value=10,
            threshold=50,
            description="Test event",
        )

        self.assertEqual(len(received_events), 1)
        self.assertEqual(received_events[0].event_type, "test")

    def test_system_event_to_dict(self):
        """Test SystemEvent serialization."""
        event = SystemEvent(
            timestamp="2025-02-19T10:00:00",
            event_type="cpu_spike",
            severity="high",
            metric_name="cpu_percent",
            metric_value=95.5,
            threshold=85,
            description="CPU spiked to 95.5%",
        )

        event_dict = event.to_dict()
        self.assertEqual(event_dict["event_type"], "cpu_spike")
        self.assertEqual(event_dict["metric_value"], 95.5)
        self.assertEqual(event_dict["severity"], "high")


class TestMonitoringPlugin(unittest.TestCase):
    """Test SystemEventMonitoringPlugin integration."""

    def test_plugin_tools(self):
        """Test monitoring plugin exposes all tools."""
        from app.core.agent.plugins.system_event_monitoring_plugin import (
            SystemEventMonitoringPlugin,
        )

        plugin = SystemEventMonitoringPlugin()
        tools = plugin.get_tools()

        tool_names = [t["name"] for t in tools]
        expected = [
            "start_system_monitoring",
            "stop_system_monitoring",
            "get_system_anomalies",
            "get_system_health",
            "clear_monitoring_log",
            "get_monitoring_status",
        ]

        for tool_name in expected:
            self.assertIn(tool_name, tool_names)

    def test_plugin_start_monitoring(self):
        """Test start_monitoring tool."""
        from app.core.agent.plugins.system_event_monitoring_plugin import (
            SystemEventMonitoringPlugin,
        )

        plugin = SystemEventMonitoringPlugin()
        result = plugin.start_monitoring()

        self.assertEqual(result["status"], "success")
        self.assertIn("check_interval", result)

        # Clean up
        plugin.stop_monitoring()

    def test_plugin_get_status(self):
        """Test get_monitoring_status tool."""
        from app.core.agent.plugins.system_event_monitoring_plugin import (
            SystemEventMonitoringPlugin,
        )

        plugin = SystemEventMonitoringPlugin()

        status = plugin.get_status()
        self.assertEqual(status["status"], "success")
        self.assertFalse(status["monitoring_active"])

        plugin.start_monitoring()
        status = plugin.get_status()
        self.assertTrue(status["monitoring_active"])

        plugin.stop_monitoring()


class TestMonitoringSingleton(unittest.TestCase):
    """Test singleton behavior."""

    def test_singleton_instance(self):
        """Test that get_system_event_monitor returns same instance."""
        monitor1 = get_system_event_monitor()
        monitor2 = get_system_event_monitor()

        self.assertIs(monitor1, monitor2)


if __name__ == "__main__":
    unittest.main()
