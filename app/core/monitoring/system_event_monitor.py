"""
Phase 4b: System Event Monitoring

Background service that continuously monitors system metrics and detects anomalies.
Triggers proactive agent advisory when issues are detected.
"""

import json
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class SystemEvent:
    """Represents a detected system anomaly."""

    timestamp: str
    event_type: str  # 'cpu_spike', 'memory_high', 'disk_full', 'process_crash', etc.
    severity: str  # 'low', 'medium', 'high'
    metric_name: str
    metric_value: float
    threshold: float
    description: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "severity": self.severity,
            "metric_name": self.metric_name,
            "metric_value": self.metric_value,
            "threshold": self.threshold,
            "description": self.description,
        }


class SystemEventMonitor:
    """
    Background monitor for system anomalies.
    Runs in separate thread, collects metrics, detects issues.
    """

    # Anomaly thresholds
    THRESHOLDS = {
        "cpu_percent": 85,  # CPU usage > 85%
        "memory_percent": 90,  # Memory > 90%
        "disk_percent": 85,  # Disk > 85%
        "cpu_temperature": 80,  # CPU temp > 80°C (if available)
        "process_memory_mb": 1000,  # Single process > 1GB
    }

    def __init__(self, check_interval: int = 30):
        """
        Initialize monitor.

        Args:
            check_interval: Seconds between metric collections (default 30s)
        """
        self.check_interval = check_interval
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.events: List[SystemEvent] = []
        self.event_lock = threading.Lock()
        self.event_callbacks: List[callable] = []
        self._last_cpu = 0.0
        self._last_memory = 0.0
        self._last_disk = 0.0

    def start(self) -> None:
        """Start background monitoring thread."""
        if self.running:
            logger.warning("Monitor already running")
            return

        self.running = True
        self.thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.thread.start()
        logger.info(f"SystemEventMonitor started (interval={self.check_interval}s)")

    def stop(self) -> None:
        """Stop background monitoring thread."""
        if not self.running:
            logger.warning("Monitor not running")
            return

        self.running = False
        if self.thread and self.thread.is_alive():
            # Don't join daemon threads, just wait briefly
            self.thread.join(timeout=1)
        logger.info("SystemEventMonitor stopped")

    def _monitor_loop(self) -> None:
        """
        Main monitoring loop (runs in background thread).
        Collects metrics and detects anomalies.
        """
        while self.running:
            try:
                self._check_system_metrics()
                time.sleep(self.check_interval)
            except Exception as e:
                logger.error(f"Error in monitor loop: {e}", exc_info=True)
                time.sleep(self.check_interval)

    def _check_system_metrics(self) -> None:
        """Collect system metrics and detect anomalies."""
        try:
            import psutil
        except ImportError:
            logger.warning("psutil not available for monitoring")
            return

        try:
            # CPU check
            cpu_percent = psutil.cpu_percent(interval=1)
            if cpu_percent > self.THRESHOLDS["cpu_percent"]:
                # Detect spike (>20% jump from last reading)
                if cpu_percent - self._last_cpu > 20:
                    self._record_event(
                        event_type="cpu_spike",
                        severity="high",
                        metric_name="cpu_percent",
                        metric_value=cpu_percent,
                        threshold=self.THRESHOLDS["cpu_percent"],
                        description=f"CPU usage spiked to {cpu_percent:.1f}%",
                    )
                elif cpu_percent > self.THRESHOLDS["cpu_percent"]:
                    self._record_event(
                        event_type="cpu_high",
                        severity="medium",
                        metric_name="cpu_percent",
                        metric_value=cpu_percent,
                        threshold=self.THRESHOLDS["cpu_percent"],
                        description=f"CPU usage high: {cpu_percent:.1f}%",
                    )
            self._last_cpu = cpu_percent

            # Memory check
            memory = psutil.virtual_memory()
            mem_percent = memory.percent
            if mem_percent > self.THRESHOLDS["memory_percent"]:
                self._record_event(
                    event_type="memory_high",
                    severity="high",
                    metric_name="memory_percent",
                    metric_value=mem_percent,
                    threshold=self.THRESHOLDS["memory_percent"],
                    description=f"Memory usage high: {mem_percent:.1f}% ({memory.used // (1024**3)}GB/{memory.total // (1024**3)}GB)",
                )
            self._last_memory = mem_percent

            # Disk check
            disk = psutil.disk_usage("/")
            disk_percent = disk.percent
            if disk_percent > self.THRESHOLDS["disk_percent"]:
                self._record_event(
                    event_type="disk_high",
                    severity="high",
                    metric_name="disk_percent",
                    metric_value=disk_percent,
                    threshold=self.THRESHOLDS["disk_percent"],
                    description=f"Disk usage high: {disk_percent:.1f}% ({disk.used // (1024**3)}GB free)",
                )
            self._last_disk = disk_percent

            # Check for high-memory processes
            processes = psutil.process_iter(["pid", "name", "memory_info"])
            for proc in processes:
                try:
                    mem_mb = proc.memory_info().rss / (1024**2)
                    if mem_mb > self.THRESHOLDS["process_memory_mb"]:
                        self._record_event(
                            event_type="process_memory_high",
                            severity="medium",
                            metric_name="process_memory_mb",
                            metric_value=mem_mb,
                            threshold=self.THRESHOLDS["process_memory_mb"],
                            description=f"Process {proc.name()} using {mem_mb:.0f}MB",
                        )
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

        except Exception as e:
            logger.error(f"Error checking system metrics: {e}", exc_info=True)

    def _record_event(
        self,
        event_type: str,
        severity: str,
        metric_name: str,
        metric_value: float,
        threshold: float,
        description: str,
    ) -> None:
        """Record a detected anomaly event."""
        event = SystemEvent(
            timestamp=datetime.now().isoformat(),
            event_type=event_type,
            severity=severity,
            metric_name=metric_name,
            metric_value=metric_value,
            threshold=threshold,
            description=description,
        )

        with self.event_lock:
            self.events.append(event)
            # Keep only last 100 events
            if len(self.events) > 100:
                self.events = self.events[-100:]

        logger.info(f"[{severity.upper()}] {description}")

        # Trigger callbacks
        for callback in self.event_callbacks:
            try:
                callback(event)
            except Exception as e:
                logger.error(f"Error in event callback: {e}", exc_info=True)

    def register_callback(self, callback: callable) -> None:
        """
        Register callback function to be called on new events.
        Callback receives SystemEvent object.
        """
        self.event_callbacks.append(callback)

    def get_events(
        self, limit: int = 20, event_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get recent events.

        Args:
            limit: Max number of events to return
            event_type: Filter by event type (None = all)

        Returns:
            List of event dicts, most recent first
        """
        with self.event_lock:
            events = list(self.events)

        if event_type:
            events = [e for e in events if e.event_type == event_type]

        # Reverse to get most recent first
        events.reverse()

        return [e.to_dict() for e in events[:limit]]

    def get_summary(self) -> Dict[str, Any]:
        """Get summary of recent events."""
        with self.event_lock:
            events = list(self.events)

        if not events:
            return {
                "total_events": 0,
                "by_type": {},
                "by_severity": {},
                "status": "healthy",
            }

        by_type = {}
        by_severity = {}

        for event in events:
            by_type[event.event_type] = by_type.get(event.event_type, 0) + 1
            by_severity[event.severity] = by_severity.get(event.severity, 0) + 1

        # Determine overall status
        status = "healthy"
        if by_severity.get("high", 0) > 0:
            status = "critical"
        elif by_severity.get("medium", 0) > 2:
            status = "warning"

        return {
            "total_events": len(events),
            "by_type": by_type,
            "by_severity": by_severity,
            "status": status,
            "last_event": events[-1].to_dict() if events else None,
        }

    def clear_events(self) -> int:
        """Clear all recorded events. Returns count cleared."""
        with self.event_lock:
            count = len(self.events)
            self.events = []
        return count

    def is_running(self) -> bool:
        """Check if monitor is actively running."""
        return self.running and (self.thread is not None and self.thread.is_alive())


# Global singleton instance
_monitor_instance: Optional[SystemEventMonitor] = None
_monitor_lock = threading.Lock()


def get_system_event_monitor(check_interval: int = 30) -> SystemEventMonitor:
    """
    Get or create the singleton SystemEventMonitor.

    Args:
        check_interval: Seconds between checks (only used on first call)

    Returns:
        SystemEventMonitor singleton instance
    """
    global _monitor_instance

    if _monitor_instance is None:
        with _monitor_lock:
            if _monitor_instance is None:
                _monitor_instance = SystemEventMonitor(check_interval=check_interval)

    return _monitor_instance
