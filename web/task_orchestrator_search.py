# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
from __future__ import annotations

import asyncio
import logging

from web.web_searcher import WebSearcher

_app_logger = logging.getLogger("koto.app")


async def execute_web_search(
    user_input: str, context: dict, progress_callback=None
) -> dict:
    """执行 Web 搜索子任务 (带可视进度)"""

    def _report(msg: str, detail: str = ""):
        _app_logger.debug(f"[WEB_SEARCH] {msg} | {detail}")
        if progress_callback:
            progress_callback(msg, detail)

    try:
        _report("启动网络搜索...", "正在规划搜索关键词")
        await asyncio.sleep(0.3)
        _report("执行 Google Search...", f"关键词: {user_input[:20]}...")

        result = await asyncio.to_thread(WebSearcher.search_with_grounding, user_input)

        if result.get("grounded"):
            _report("✅ 搜索并引用完成", "已结合最新信息")
        else:
            _report("✅ 搜索完成", "已获取相关网页摘要")

        return {
            "success": result.get("success", False),
            "output": result.get("response", ""),
            "content": result.get("response", ""),
            "grounded": result.get("grounded", False),
            "raw_result": result,
            "model_id": "gemini-2.5-flash",
        }
    except Exception as e:
        _report("❌ 搜索遇到问题", str(e))
        return {
            "success": False,
            "output": "",
            "error": str(e),
            "raw_result": None,
            "model_id": "gemini-2.5-flash",
        }
