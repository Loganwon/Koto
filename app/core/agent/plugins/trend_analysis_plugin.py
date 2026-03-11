"""
Phase 5d: Trend Analysis Plugin

Provides historical analysis and predictive insights.
"""

import logging
from typing import Any, Dict, List, Optional

from app.core.agent.base import AgentPlugin
from app.core.analytics.trend_analyzer import get_trend_analyzer

logger = logging.getLogger(__name__)


class TrendAnalysisPlugin(AgentPlugin):
    """
    Trend analysis plugin for historical data insights.

    Tools:
    - analyze_event_trends: Analyze historical event patterns
    - predict_potential_issues: Predict problems based on trends
    - compare_with_historical: Compare current metrics with historical data
    - get_anomaly_score: Calculate anomaly score
    """

    @property
    def name(self) -> str:
        """Plugin name."""
        return "TrendAnalysisPlugin"

    @property
    def description(self) -> str:
        """Plugin description."""
        return "Historical analysis and predictive insights for system monitoring"

    def __init__(self):
        """Initialize plugin."""
        self.analyzer = get_trend_analyzer()

    def get_tools(self) -> List[Dict[str, Any]]:
        """Return tool definitions."""
        return [
            {
                "name": "analyze_event_trends",
                "func": self.analyze_event_trends,
                "description": "Analyze trends in historical events",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "event_data": {
                            "type": "STRING",
                            "description": "JSON-encoded list of events",
                        },
                        "hours_back": {
                            "type": "INTEGER",
                            "description": "Time window in hours (default: 24)",
                        },
                    },
                    "required": ["event_data"],
                },
            },
            {
                "name": "predict_potential_issues",
                "func": self.predict_potential_issues,
                "description": "Predict potential issues based on trends",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "event_data": {
                            "type": "STRING",
                            "description": "JSON-encoded list of events",
                        },
                        "metrics": {
                            "type": "STRING",
                            "description": "JSON-encoded current metrics (optional)",
                        },
                    },
                    "required": ["event_data"],
                },
            },
            {
                "name": "compare_with_historical",
                "func": self.compare_with_historical,
                "description": "Compare current metrics with historical patterns",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "current_metrics": {
                            "type": "STRING",
                            "description": "JSON-encoded current metrics",
                        },
                        "historical_stats": {
                            "type": "STRING",
                            "description": "JSON-encoded historical statistics",
                        },
                    },
                    "required": ["current_metrics", "historical_stats"],
                },
            },
            {
                "name": "get_anomaly_score",
                "func": self.get_anomaly_score,
                "description": "Calculate anomaly score based on event frequency",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "event_data": {
                            "type": "STRING",
                            "description": "JSON-encoded list of events",
                        },
                        "hours_back": {
                            "type": "INTEGER",
                            "description": "Time window in hours (default: 24)",
                        },
                    },
                    "required": ["event_data"],
                },
            },
        ]

    def analyze_event_trends(self, event_data: str, hours_back: int = 24) -> str:
        """Analyze event trends."""
        try:
            import json

            events = json.loads(event_data)

            result = self.analyzer.analyze_event_trends(events, hours_back)

            output = f"Event Trend Analysis ({hours_back} hours):\n\n"
            output += f"Total Events: {result['total_events']}\n"
            output += f"Average per Hour: {result['avg_events_per_hour']}\n\n"

            output += "Event Types:\n"
            for etype, count in sorted(
                result["event_types"].items(), key=lambda x: x[1], reverse=True
            )[:5]:
                output += f"  {etype}: {count}\n"

            output += "\nTop Trends:\n"
            for trend in result["top_trends"]:
                output += f"  {trend['event_type']}: {trend['count']} ({trend['percentage']}%)\n"

            return output
        except Exception as e:
            return f"Error analyzing trends: {str(e)}"

    def predict_potential_issues(
        self, event_data: str, metrics: Optional[str] = None
    ) -> str:
        """Predict potential issues."""
        try:
            import json

            events = json.loads(event_data)

            metrics_dict = None
            if metrics:
                metrics_dict = json.loads(metrics)

            result = self.analyzer.predict_issues(events, metrics_dict)

            if not result["predictions"]:
                return "No significant risks identified based on current trends."

            output = f"Potential Issues ({result['total_risk_count']}):\n\n"
            for pred in result["predictions"]:
                output += f"Issue: {pred['issue']}\n"
                output += f"  Risk Level: {pred['risk_level'].upper()}\n"
                output += f"  Recommendation: {pred['recommendation']}\n\n"

            return output
        except Exception as e:
            return f"Error predicting issues: {str(e)}"

    def compare_with_historical(
        self, current_metrics: str, historical_stats: str
    ) -> str:
        """Compare with historical data."""
        try:
            import json

            current = json.loads(current_metrics)
            historical = json.loads(historical_stats)

            result = self.analyzer.get_historical_comparison(current, historical)

            output = "Historical Comparison:\n\n"

            if "comparisons" not in result:
                return result.get("message", "No comparison available")

            for metric, data in result["comparisons"].items():
                output += f"{metric.upper()}:\n"
                output += f"  Current: {data['current']}\n"
                output += f"  Historical Avg: {data['historical_avg']}\n"
                output += f"  Difference: {data['difference']} ({data['status']})\n\n"

            return output
        except Exception as e:
            return f"Error comparing with historical data: {str(e)}"

    def get_anomaly_score(self, event_data: str, hours_back: int = 24) -> str:
        """Get anomaly score."""
        try:
            import json

            events = json.loads(event_data)

            score = self.analyzer.get_anomaly_score(events, hours_back)

            if score < 0.2:
                status = "Normal"
            elif score < 0.5:
                status = "Elevated"
            elif score < 0.7:
                status = "High"
            else:
                status = "Critical"

            output = "Anomaly Score:\n\n"
            output += f"Score: {score:.2f} / 1.0\n"
            output += f"Status: {status}\n\n"
            output += "Interpretation:\n"
            output += f"  0.0 - 0.2: Normal behavior\n"
            output += f"  0.2 - 0.5: Elevated activity\n"
            output += f"  0.5 - 0.7: High activity level\n"
            output += f"  0.7 - 1.0: Anomalous behavior\n"

            return output
        except Exception as e:
            return f"Error calculating anomaly score: {str(e)}"
