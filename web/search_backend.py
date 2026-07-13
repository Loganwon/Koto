# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Small provider-independent web result retriever.

This module deliberately returns search result metadata only.  Answer
synthesis belongs to the configured Koto LLM provider and is handled by
``web.web_searcher``.
"""

from __future__ import annotations

import html
import logging
from urllib.parse import parse_qs, unquote, urlparse
from xml.etree import ElementTree

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Koto/1.0"
    )
}


def _direct_url(value: str) -> str:
    url = html.unescape(str(value or "").strip())
    if url.startswith("//"):
        url = "https:" + url
    parsed = urlparse(url)
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg", [""])[0]
        if target:
            return unquote(target)
    return url


def _normalize(rows: list[dict], limit: int) -> list[dict]:
    output: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        url = _direct_url(row.get("url", ""))
        if not url.startswith(("http://", "https://")) or url in seen:
            continue
        seen.add(url)
        output.append(
            {
                "id": len(output) + 1,
                "title": str(row.get("title") or "未命名来源").strip(),
                "url": url,
                "domain": urlparse(url).netloc,
                "snippet": str(row.get("snippet") or "").strip(),
            }
        )
        if len(output) >= limit:
            break
    return output


def _duckduckgo(query: str, timeout: float) -> list[dict]:
    response = requests.get(
        "https://html.duckduckgo.com/html/",
        params={"q": query},
        headers=_HEADERS,
        timeout=timeout,
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    rows: list[dict] = []
    for result in soup.select(".result"):
        link = result.select_one(".result__a")
        if not link:
            continue
        snippet = result.select_one(".result__snippet")
        rows.append(
            {
                "title": link.get_text(" ", strip=True),
                "url": link.get("href", ""),
                "snippet": snippet.get_text(" ", strip=True) if snippet else "",
            }
        )
    return rows


def _bing_rss(query: str, timeout: float) -> list[dict]:
    response = requests.get(
        "https://www.bing.com/search",
        params={"q": query, "format": "rss"},
        headers=_HEADERS,
        timeout=timeout,
    )
    response.raise_for_status()
    root = ElementTree.fromstring(response.content)
    rows: list[dict] = []
    for item in root.findall(".//item"):
        rows.append(
            {
                "title": item.findtext("title", default=""),
                "url": item.findtext("link", default=""),
                "snippet": item.findtext("description", default=""),
            }
        )
    return rows


def search_web(query: str, *, limit: int = 8, timeout: float = 12.0) -> list[dict]:
    text = str(query or "").strip()
    if not text:
        return []
    errors: list[str] = []
    for name, searcher in (("duckduckgo", _duckduckgo), ("bing_rss", _bing_rss)):
        try:
            rows = _normalize(searcher(text, timeout), max(1, min(limit, 12)))
            if rows:
                return rows
        except Exception as exc:
            errors.append(f"{name}: {exc}")
    if errors:
        logger.warning("[WebSearch] all retrieval backends failed: %s", "; ".join(errors))
    return []
