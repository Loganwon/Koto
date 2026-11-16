# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary

import json
import time

from web.sse.sanitizer import safe_sse as _safe_sse
from app.core.llm.provider_compat import types


def handle_web_search(yield_thinking, client, session_manager, user_input, session_name, start_time, _app_logger, MODEL_MAP):
    from web.runtime_context import service_registry

    Utils = service_registry.utils
    try:
        WebSearcher = service_registry.web_searcher
    except RuntimeError:
        from web.knowledge import web_searcher as _web_searcher

        class WebSearcher:
            search_with_grounding = staticmethod(_web_searcher.search_with_grounding)

    def generate_with_cloud_fallback(model, contents, config):
        from app.core.llm.provider_boundary import normalize_public_model

        model = normalize_public_model(model)
        try:
            return client.generate_content(
                model=model,
                contents=contents,
                config=config,
            )
        except Exception as exc:
            exc_text = str(exc)
            if "model is required" not in exc_text and "Ollama" not in exc_text:
                raise
            gateway = service_registry.llm_gateway
            if gateway is None:
                raise
            return gateway.generate_content(
                model=model,
                contents=contents,
                config=config,
            )

    used_model = "deepseek-chat (web search)"
    yield _safe_sse({"type": "progress", "message": "正在连接互联网搜索...", "detail": ""})
    yield _safe_sse({"type": "progress", "message": "正在搜索实时信息...", "detail": "Web Search"})
    yield _safe_sse({"type": "progress", "message": "正在整理搜索结果...", "detail": ""})

    search_result = WebSearcher.search_with_grounding(user_input)
    response_text = search_result["response"]
    response_sources = search_result.get("sources") or []

    if (
        Utils.is_failure_output(response_text)
        or "搜索失败" in response_text
    ):
        t = yield_thinking(
            "初次搜索结果不佳，正在改写查询词后重试",
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
            model="deepseek-chat",
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
            model=MODEL_MAP.get("WEB_SEARCH", "deepseek-chat"),
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
