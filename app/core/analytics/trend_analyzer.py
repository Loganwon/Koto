"""
Phase 5d: Trend Analysis System

Analyzes historical event data to identify patterns and predict issues.
"""

import logging
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class TrendAnalyzer:
    """
    Analyzes trends in system metrics and events.
    """

    def __init__(self):
        """Initialize trend analyzer."""
        self.lock = __import__("threading").Lock()

    def analyze_event_trends(
        self, events: List[Dict[str, Any]], hours_back: int = 24
    ) -> Dict[str, Any]:
        """
        Analyze trends in event data.

        Args:
            events: List of event records
            hours_back: Time window for analysis

        Returns:
            Trend analysis dictionary
        """
        if not events:
            return {"error": "No events to analyze"}

        # Count by event type
        type_counts = defaultdict(int)
        severity_counts = defaultdict(int)

        for event in events:
            type_counts[event.get("event_type", "unknown")] += 1
            severity_counts[event.get("severity", "unknown")] += 1

        # Calculate rate of change
        total_events = len(events)
        avg_events_per_hour = total_events / max(hours_back, 1)

        # Identify trends
        trends = []
        for event_type, count in type_counts.items():
            if count >= 3:  # Threshold for trend
                trends.append(
                    {
                        "event_type": event_type,
                        "count": count,
                        "percentage": round((count / total_events) * 100, 2),
                    }
                )

        # Sort by frequency
        trends = sorted(trends, key=lambda x: x["count"], reverse=True)

        return {
            "time_window_hours": hours_back,
            "total_events": total_events,
            "avg_events_per_hour": round(avg_events_per_hour, 2),
            "event_types": dict(type_counts),
            "severity_breakdown": dict(severity_counts),
            "top_trends": trends[:5],
            "analysis_timestamp": datetime.now().isoformat(),
        }

    def predict_issues(
        self, events: List[Dict[str, Any]], metrics: Optional[Dict[str, float]] = None
    ) -> Dict[str, Any]:
        """
        Predict potential issues based on historical trends.

        Args:
            events: Historical events
            metrics: Current system metrics

        Returns:
            Predictions dictionary
        """
        predictions = []

        if not events:
            return {"warnings": [], "timestamp": datetime.now().isoformat()}

        # Analyze frequency of each event type
        type_frequency = defaultdict(int)
        for event in events:
            type_frequency[event.get("event_type")] += 1

        # High frequency = elevated risk
        for event_type, count in type_frequency.items():
            if count >= 5:
                predictions.append(
                    {
                        "issue": event_type,
                        "risk_level": "high" if count >= 10 else "medium",
                        "frequency": count,
                        "recommendation": f"Consider preventive action for {event_type}",
                    }
                )

        # Add metric-based predictions
        if metrics:
            if metrics.get("cpu_usage", 0) > 70:
                predictions.append(
                    {
                        "issue": "High CPU Usage Trend",
                        "risk_level": (
                            "high" if metrics.get("cpu_usage", 0) > 85 else "medium"
                        ),
                        "current_value": metrics.get("cpu_usage"),
                        "recommendation": "Review running processes and optimize CPU-intensive tasks",
                    }
                )

            if metrics.get("memory_usage", 0) > 80:
                predictions.append(
                    {
                        "issue": "High Memory Usage Trend",
                        "risk_level": (
                            "high" if metrics.get("memory_usage", 0) > 90 else "medium"
                        ),
                        "current_value": metrics.get("memory_usage"),
                        "recommendation": "Check for memory leaks and restart services if needed",
                    }
                )

        return {
            "predictions": predictions,
            "total_risk_count": len(predictions),
            "timestamp": datetime.now().isoformat(),
        }

    def get_historical_comparison(
        self, current_metrics: Dict[str, float], historical_stats: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Compare current metrics with historical patterns.

        Args:
            current_metrics: Current system metrics
            historical_stats: Historical statistics from database

        Returns:
            Comparison analysis
        """
        comparison = {}

        if not historical_stats:
            return {"message": "No historical data available"}

        avg_cpu = historical_stats.get("avg_cpu", 0)
        avg_memory = historical_stats.get("avg_memory", 0)
        avg_disk = historical_stats.get("avg_disk", 0)

        # Compare current with historical average
        if avg_cpu > 0:
            cpu_diff = current_metrics.get("cpu_usage", 0) - avg_cpu
            comparison["cpu"] = {
                "current": current_metrics.get("cpu_usage", 0),
                "historical_avg": avg_cpu,
                "difference": round(cpu_diff, 2),
                "status": "above" if cpu_diff > 0 else "below",
            }

        if avg_memory > 0:
            mem_diff = current_metrics.get("memory_usage", 0) - avg_memory
            comparison["memory"] = {
                "current": current_metrics.get("memory_usage", 0),
                "historical_avg": avg_memory,
                "difference": round(mem_diff, 2),
                "status": "above" if mem_diff > 0 else "below",
            }

        if avg_disk > 0:
            disk_diff = current_metrics.get("disk_usage", 0) - avg_disk
            comparison["disk"] = {
                "current": current_metrics.get("disk_usage", 0),
                "historical_avg": avg_disk,
                "difference": round(disk_diff, 2),
                "status": "above" if disk_diff > 0 else "below",
            }

        return {"comparisons": comparison, "timestamp": datetime.now().isoformat()}

    def get_anomaly_score(
        self, events: List[Dict[str, Any]], hours_back: int = 24
    ) -> float:
        """
        Calculate anomaly score based on event frequency.
        0 = normal, 1 = highly anomalous

        Args:
            events: Event list
            hours_back: Time window

        Returns:
            Anomaly score (0-1)
        """
        if not events:
            return 0.0

        # Baseline: expect 1-5 events per hour
        event_rate = len(events) / max(hours_back, 1)

        if event_rate < 1:
            return 0.0
        elif event_rate < 2:
            return 0.1
        elif event_rate < 5:
            return 0.3
        elif event_rate < 10:
            return 0.6
        else:
            return 0.9


# Global instance
_trend_analyzer: Optional["TrendAnalyzer"] = None
_trend_lock = __import__("threading").Lock()


def get_trend_analyzer() -> TrendAnalyzer:
    """Get or create the singleton TrendAnalyzer instance."""
    global _trend_analyzer

    if _trend_analyzer is None:
        with _trend_lock:
            if _trend_analyzer is None:
                _trend_analyzer = TrendAnalyzer()

    return _trend_analyzer
