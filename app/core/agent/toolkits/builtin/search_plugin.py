"""SearchPlugin ? web search tool for KernelAgent.

Migrated from the retired app/core/agent/plugins namespace.  The old
implementation depended on the grounded-search compatibility service.
This version delegates through a Core gateway whose concrete search
implementation is supplied by the application composition root.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from app.core.agent.base import AgentPlugin
from app.core.services.web_search_gateway import search_with_grounding

logger = logging.getLogger(__name__)


class SearchPlugin(AgentPlugin):
    """Web search tool backed by Koto's production search workflow."""

    def __init__(self, api_key: str | None = None):
        # Kept for tool_profile compatibility; the production search
        # backend does not require a dedicated search API key.
        self.api_key = api_key

    @property
    def name(self) -> str:
        return "WebSearch"

    @property
    def description(self) -> str:
        return "Search the web for real-time information."

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "web_search",
                "func": self.web_search,
                "description": (
                    "Perform a web search to find up-to-date information about a topic. "
                    "Use this for live facts, news, weather, prices, or anything that "
                    "changes over time."
                ),
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "query": {
                            "type": "STRING",
                            "description": "The search query, e.g. 'today's weather in Shanghai'.",
                        }
                    },
                    "required": ["query"],
                },
            }
        ]

    def web_search(self, query: str) -> str:
        """Search the web and return a synthesized answer with sources."""
        try:
            result = search_with_grounding(query)
        except Exception as exc:
            logger.warning("[SearchPlugin] search backend failed: %s", exc)
            return "Web search is currently unavailable; please try again later."
        if not isinstance(result, dict):
            return "Web search returned an unexpected result."
        if not result.get("success"):
            return str(result.get("response") or "Web search failed.")
        answer = str(result.get("response") or "").strip()
        sources = result.get("sources") or []
        if sources:
            lines = [answer, "", "来源："]
            lines.extend(
                f"{item.get('id', i + 1)}. {item.get('title', '')} {item.get('url', '')}"
                for i, item in enumerate(sources)
            )
            return "\n".join(lines)
        return answer
