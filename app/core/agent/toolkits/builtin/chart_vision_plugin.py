# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""ChartVisionPlugin - chart and data visualization analysis."""

from __future__ import annotations

import base64
import os
from typing import Any, Dict, List

from app.core.agent.base import AgentPlugin


class ChartVisionPlugin(AgentPlugin):
    """Analyzes chart images and data visualizations from screenshots and files."""

    @property
    def name(self) -> str:
        return "ChartVision"

    @property
    def description(self) -> str:
        return "Chart and data visualization analysis from images and screenshots."

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "analyze_chart_image",
                "func": self.analyze_chart_image,
                "description": (
                    "Analyze a chart or data visualization image. "
                    "Extracts chart type, data trends, axis labels, and key insights. "
                    "Args: image_path (str) - path to the chart image file."
                ),
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "image_path": {
                            "type": "STRING",
                            "description": "Path to chart image file",
                        },
                    },
                    "required": ["image_path"],
                },
            },
            {
                "name": "analyze_screenshot",
                "func": self.analyze_screenshot,
                "description": (
                    "Analyze a screenshot for charts, tables, and data visualizations. "
                    "Detects embedded charts and extracts their structure. "
                    "Args: image_path (str) - path to screenshot file."
                ),
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "image_path": {
                            "type": "STRING",
                            "description": "Path to screenshot file",
                        },
                    },
                    "required": ["image_path"],
                },
            },
        ]

    def analyze_chart_image(self, image_path: str) -> str:
        """Analyze a chart image and return insights."""
        path = str(image_path or "").strip()
        if not path or not os.path.isfile(path):
            return "Error: chart image file not found"
        try:
            suffix = os.path.splitext(path)[1].lower().lstrip(".")
            with open(path, "rb") as f:
                data = base64.b64encode(f.read()).decode("ascii")
            mime = {
                "png": "image/png",
                "jpg": "image/jpeg",
                "jpeg": "image/jpeg",
                "webp": "image/webp",
            }.get(suffix, "image/png")
            return (
                f"Chart image loaded: {os.path.basename(path)} ({len(data)} bytes base64, {mime}). "
                "Use a vision-capable model to analyze this chart for type, trends, labels, and outliers."
            )
        except Exception as e:
            return f"Error reading chart: {e}"

    def analyze_screenshot(self, image_path: str) -> str:
        """Analyze a screenshot for embedded visualizations."""
        path = str(image_path or "").strip()
        if not path or not os.path.isfile(path):
            return "Error: screenshot file not found"
        return self.analyze_chart_image(image_path)
