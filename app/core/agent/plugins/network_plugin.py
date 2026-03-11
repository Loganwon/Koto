"""
NetworkPlugin — 网络请求、网页内容抓取

从 web/adaptive_agent.py 的 network_ops 工具迁移而来,
适配 UnifiedAgent 插件体系。
"""

from typing import Any, Dict, List

from app.core.agent.base import AgentPlugin


class NetworkPlugin(AgentPlugin):
    """Provides HTTP fetching and basic HTML parsing capabilities."""

    @property
    def name(self) -> str:
        return "Network"

    @property
    def description(self) -> str:
        return "Fetch web pages, download content, and parse HTML."

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "http_get",
                "func": self.http_get,
                "description": "Perform an HTTP GET request and return status code plus "
                "the first 2000 characters of the response body.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "url": {"type": "STRING", "description": "The URL to fetch."}
                    },
                    "required": ["url"],
                },
            },
            {
                "name": "http_post",
                "func": self.http_post,
                "description": "Perform an HTTP POST request with a JSON body.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "url": {"type": "STRING", "description": "The URL to post to."},
                        "body": {
                            "type": "STRING",
                            "description": "JSON string to send as the request body.",
                        },
                    },
                    "required": ["url", "body"],
                },
            },
            {
                "name": "parse_html",
                "func": self.parse_html,
                "description": "Fetch a web page and extract elements matching a CSS selector. "
                "Returns up to 10 matched elements.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "url": {
                            "type": "STRING",
                            "description": "The URL of the web page.",
                        },
                        "selector": {
                            "type": "STRING",
                            "description": "CSS selector, e.g. 'h2', 'a.link', '#main p'.",
                        },
                    },
                    "required": ["url", "selector"],
                },
            },
        ]

    # ------------------------------------------------------------------

    @staticmethod
    def http_get(url: str) -> str:
        """Fetch a URL and return the response."""
        try:
            import requests

            resp = requests.get(url, timeout=15, headers={"User-Agent": "Koto/1.0"})
            return (
                f"Status: {resp.status_code}\n"
                f"Content-Type: {resp.headers.get('content-type', 'unknown')}\n\n"
                f"{resp.text[:2000]}"
            )
        except Exception as exc:
            return f"HTTP GET error: {exc}"

    @staticmethod
    def http_post(url: str, body: str) -> str:
        """POST JSON to a URL."""
        try:
            import json as _json

            import requests

            data = _json.loads(body)
            resp = requests.post(
                url, json=data, timeout=15, headers={"User-Agent": "Koto/1.0"}
            )
            return f"Status: {resp.status_code}\n" f"{resp.text[:2000]}"
        except Exception as exc:
            return f"HTTP POST error: {exc}"

    @staticmethod
    def parse_html(url: str, selector: str) -> str:
        """Fetch a page and extract elements via CSS selector."""
        try:
            import requests
            from bs4 import BeautifulSoup

            resp = requests.get(url, timeout=15, headers={"User-Agent": "Koto/1.0"})
            soup = BeautifulSoup(resp.text, "html.parser")
            elements = soup.select(selector)

            if not elements:
                return f"No elements matched selector '{selector}'."

            lines = [f"Found {len(elements)} element(s). Showing up to 10:\n"]
            for i, el in enumerate(elements[:10], 1):
                text = el.get_text(strip=True)[:200]
                lines.append(f"  [{i}] {text}")
            return "\n".join(lines)
        except Exception as exc:
            return f"HTML parse error: {exc}"
