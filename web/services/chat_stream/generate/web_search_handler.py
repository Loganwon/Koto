# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary

import json
import time

from web.sse.sanitizer import safe_sse as _safe_sse
from google.genai import types


def handle_web_search(yield_thinking, context_info, client, session_manager, user_input, session_name, start_time, _app_logger, MODEL_MAP):
    from web.runtime_context import get_create_client, get_utils, get_web_searcher

    Utils = get_utils()
    try:
        WebSearcher = get_web_searcher()
    except RuntimeError:
        from web import web_searcher as _web_searcher

        class WebSearcher:
            search_with_grounding = staticmethod(_web_searcher.search_with_grounding)

    def generate_with_cloud_fallback(model, contents, config):
        model = str(model or "").strip() or "gemini-2.5-flash"
        if not model.startswith("gemini-"):
            model = "gemini-2.5-flash"
        try:
            return client.models.generate_content(
                model=model,
                contents=contents,
                config=config,
            )
        except Exception as exc:
            exc_text = str(exc)
            if "model is required" not in exc_text and "Ollama" not in exc_text:
                raise
            create_client = get_create_client()
            if not callable(create_client):
                raise
            return create_client().models.generate_content(
                model=model,
                contents=contents,
                config=config,
            )

    used_model = "gemini-2.5-flash (Google Search)"
    yield _safe_sse({"type": "progress", "message": "正在连接互联网搜索...", "detail": ""})
    yield _safe_sse({"type": "progress", "message": "正在搜索实时信息...", "detail": "Google Search"})
    yield _safe_sse({"type": "progress", "message": "正在整理搜索结果...", "detail": ""})

    _skill_prompt = (context_info or {}).get("skill_prompt")
    search_result = WebSearcher.search_with_grounding(
        user_input, skill_prompt=_skill_prompt
    )
    response_text = search_result["response"]
    response_sources = search_result.get("sources") or []

    if (
        Utils.is_failure_output(response_text)
        or "搜索失败" in response_text
    ):
        t = yield_thinking(
            "初次搜索结果不佳，使用 gemini-2.5-flash-lite 改写查询词后重试",
            "searching",
        )
        if t:
            yield t
        yield _safe_sse({"type": "progress", "message": "⚠️ 初次搜索失败，正在修正查询...", "detail": ""})
        fix_query_prompt = (
            "请把用户需求改写成更适合搜索的简短关键词或查询语句，只输出查询语句。\n"
            f"用户需求: {user_input}"
        )
        fix_query_resp = generate_with_cloud_fallback(
            model="gemini-2.5-flash-lite",
            contents=fix_query_prompt,
            config=types.GenerateContentConfig(
                temperature=0.2,
                max_output_tokens=64,
            ),
        )
        fixed_query = (fix_query_resp.text or user_input).strip()
        search_result = WebSearcher.search_with_grounding(fixed_query)
        response_text = search_result["response"]
        response_sources = search_result.get("sources") or []

    if Utils.is_failure_output(response_text):
        fix_prompt = Utils.build_fix_prompt(
            "WEB_SEARCH", user_input, response_text
        )
        fix_resp = generate_with_cloud_fallback(
            model=MODEL_MAP.get("WEB_SEARCH", "gemini-3-flash-preview"),
            contents=fix_prompt,
            config=types.GenerateContentConfig(
                temperature=0.4,
                max_output_tokens=1200,
            ),
        )
        response_text = fix_resp.text or response_text

    yield _safe_sse({"type": "token", "content": response_text})
    if response_sources:
        yield _safe_sse({"type": "sources", "sources": response_sources})

    session_manager.append_and_save(
        f"{session_name}.json", user_input, response_text
    )

    total_time = time.time() - start_time
    yield _safe_sse({"type": "done", "images": [], "saved_files": [], "total_time": total_time})
