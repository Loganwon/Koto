from typing import Any, Dict, List

from app.core.agent.base import AgentPlugin
from app.core.services.search_service import SearchService


class SearchPlugin(AgentPlugin):
    def __init__(self, api_key: str = None):
        try:
            from app.core.services.search_service import SearchService

            self.service = SearchService(api_key=api_key)
            self.enabled = True
        except ImportError:
            self.enabled = False

    @property
    def name(self) -> str:
        return "WebSearch"

    @property
    def description(self) -> str:
        return "Tools for searching the web to find real-time information."

    def get_tools(self) -> List[Dict[str, Any]]:
        if not self.enabled:
            return []

        return [
            {
                "name": "web_search",
                "func": self.web_search,
                "description": "Perform a Google search to find information about a topic.",
            }
        ]

    def web_search(self, query: str) -> str:
        """
        Searches the web for the given query.
        Returns a summary of search results.
        """
        if not self.enabled:
            return "Search service is disabled or not configured."

        result = self.service.search(query)
        if result.get("success"):
            return f"Search Result for '{query}':\n{result.get('data')}"
        else:
            return f"Search failed: {result.get('error')}"
