#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Web search capabilities kept outside the Flask monolith."""

from __future__ import annotations

import logging
import os
import time
from typing import Any

from web.runtime_context import (
    get_app_module,
    get_client,
    get_create_client,
    get_model_map,
    get_types,
    get_workspace_dir,
)

logger = logging.getLogger(__name__)


def _app_attr(name: str, default: Any = None) -> Any:
    return getattr(get_app_module(), name, default)


def _app_call(name: str, *args: Any, **kwargs: Any) -> Any:
    func = _app_attr(name)
    if not callable(func):
        raise RuntimeError(f"web.app runtime callable is unavailable: {name}")
    return func(*args, **kwargs)


def _client() -> Any:
    return get_client()


def _create_client() -> Any:
    factory = get_create_client()
    if not callable(factory):
        raise RuntimeError("runtime client factory is unavailable")
    return factory()


def _types() -> Any:
    types_module = get_types()
    if types_module is not None:
        return types_module
    from google.genai import types as genai_types

    return genai_types


# ================= 联网搜索能力 =================
class WebSearcher:
    """
    使用 Gemini 的 Google Search Grounding 能力
    获取实时天气、新闻等信息
    """

    # 需要联网的关键词（严格收窄：仅包含几乎只在需要实时信息时才会出现的词）
    WEB_KEYWORDS = [
        # 天气（高置信）
        "天气",
        "气温",
        "下雨吗",
        "下雪吗",
        "温度多少",
        "天气怎么样",
        "天气预报",
        "weather",
        "temperature",
        "forecast",
        # 实时行情（高置信）
        "股价",
        "汇率",
        "比特币价格",
        "黄金价格",
        "金价",
        "实时金价",
        "今日金价",
        "当前金价",
        "现货黄金",
        "国际金价",
        "石油价格",
        "a股",
        "港股",
        "美股",
        "stock price",
        # 比赛/体育（高置信）
        "比分",
        "比赛结果",
        "谁赢了",
        # 新闻（只匹配明确的新闻请求）
        "今天新闻",
        "最新新闻",
        "latest news",
        # 交通出行票务（高置信 — 余票/时刻表实时变化）
        "火车票",
        "高铁票",
        "动车票",
        "机票",
        "余票",
        "班次查询",
        "车次查询",
        "时刻表",
        "列车时刻",
        "航班查询",
        "航班动态",
        "几点出发",
        "几点到",
        "几点到达",
        "多久到",
        "要多久",
    ]

    @classmethod
    def needs_web_search(cls, text):
        """检测是否需要联网搜索

        优化策略：
        1. 检查关键词列表
        2. 对于金融/预测类，更倾向于web-search
        3. 对于热点事件、新品发布，必须web-search
        """
        text_lower = text.lower()

        # 必须 web-search 的模式（绝不能用纯AI）
        must_search_patterns = [
            r"(能不能|应该不应该|值不值得|是否).*?买",  # 股票建议
            r"(最新|实时|今天|明天|下周).*?(股|行情|数据)",  # 实时行情
            r"(预测|预期|后市|趋势).*?(股|市场|行业)",  # 趋势预测
            r"(财报|业绩|营收).*?(公布|发布)",  # 财报动态
            r"(新品|发布|推出).*?(上市|发售)",  # 新品信息
            r"(突发|紧急|最新)\w*事件",  # 突发事件
            r"(当前|今日|实时|最新).*?(金价|黄金)",  # 黄金实时行情
            r"(金价|黄金).*?(多少|报价|走势|行情)",  # 金价查询
            # 交通出行——余票/时刻均实时变化
            r"(查|看|查询|查一下|有没有|有无|还有).{0,6}(火车票|高铁票|动车票|机票|余票)",
            r"(下周|明天|后天|今天|大后天|\d+[号日]).{0,12}(去|到|从).{0,12}(的|要).{0,5}(票|高铁|动车|火车|航班)",
            r"(去|从).{1,12}(去|到).{1,18}(火车|高铁|动车|机票|班次|航班)",
            r"(几点|什么时候).{0,6}(出发|到|到达|抵达).{0,12}(班|次|票|车|机)",
        ]

        import re

        for pattern in must_search_patterns:
            if re.search(pattern, text_lower, re.IGNORECASE):
                return True

        # 关键词匹配
        if any(kw in text_lower for kw in cls.WEB_KEYWORDS):
            return True

        return False

    @classmethod
    def _detect_query_type(cls, query: str) -> str:
        """检测搜索查询的意图类型，返回: travel / weather / finance / news / general"""
        q = query.lower()
        travel_kw = [
            "火车票",
            "高铁票",
            "动车票",
            "机票",
            "余票",
            "班次",
            "车次",
            "时刻表",
            "列车时刻",
            "列车",
            "高铁",
            "动车",
            "航班",
            "航班动态",
            "几点到",
            "几点出发",
            "几点抵达",
            "要多久",
            "多久到",
        ]
        if any(kw in q for kw in travel_kw):
            return "travel"
        weather_kw = [
            "天气",
            "气温",
            "下雨",
            "下雪",
            "温度",
            "weather",
            "forecast",
            "天气预报",
        ]
        if any(kw in q for kw in weather_kw):
            return "weather"
        finance_kw = [
            "股价",
            "股票",
            "汇率",
            "比特币",
            "黄金",
            "金价",
            "行情",
            "基金",
            "石油",
            "原油",
        ]
        if any(kw in q for kw in finance_kw):
            return "finance"
        return "general"

    @classmethod
    def _build_search_context(cls, query: str, query_type: str) -> tuple:
        """根据查询类型返回 (enriched_query, system_instruction)"""
        if query_type == "travel":
            instruction = (
                "你是 Koto，一个智能出行助手。用户在查询交通出行信息（高铁/火车/动车/机票等）。\n"
                "请基于搜索结果，按以下格式输出（用 Markdown）：\n\n"
                "1. 先用一句话说明查询的出发日期和路线（如有）。\n"
                "2. 用 **Markdown 表格** 列出主要班次，列标题为：\n"
                "   | 班次 | 出发站 | 到达站 | 出发时间 | 到达时间 | 历时 | 二等座 | 一等座 |\n"
                "   只列出搜索结果中明确出现的班次，不要自行补全或推测。\n"
                "3. 表格后，提醒用户前往 12306 或铁路官方渠道查看实时余票并购票。\n"
                "4. **严禁** 在搜索结果班次信息不足时自行编造、补全或推测班次数据。若搜索结果不足，明确告知用户『当前搜索结果班次信息有限』，并直接引导用户前往 12306 官网或 App 查询。\n"
                "用中文输出，格式整洁，突出关键数据。"
            )
            return query, instruction
        elif query_type == "weather":
            instruction = (
                "你是 Koto，一个智能助手。请根据搜索结果提供准确的天气信息。\n"
                "格式要求：\n"
                "1. 当前气温和天气状况\n"
                "2. 今日最高 / 最低气温\n"
                "3. 未来 3 天天气（如果有）\n"
                "4. 简短的出行或着装建议\n"
                "用中文输出，简洁清晰。"
            )
            return query, instruction
        elif query_type == "finance":
            instruction = (
                "你是 Koto，一个智能助手。请根据搜索结果提供准确的金融行情信息。\n"
                "格式要求：\n"
                "1. 当前价格 / 价值及所属市场\n"
                "2. 今日涨跌幅（如有）\n"
                "3. 近期走势简析（1-2 句）\n"
                "用中文输出，简洁专业。"
            )
            return query, instruction
        else:
            instruction = (
                "你是 Koto，一个智能助手。使用搜索结果提供准确、实时的信息。"
                "用中文回答，格式清晰，关键数据用 Markdown 列表或加粗呈现。"
            )
            return query, instruction

    @staticmethod
    def _extract_sources(response) -> list:
        """从 Gemini grounding 响应中提取去重后的来源列表。"""
        try:
            candidates = getattr(response, "candidates", None) or []
            if not candidates:
                return []

            first = candidates[0]
            grounding = getattr(first, "grounding_metadata", None)
            if grounding is None and isinstance(first, dict):
                grounding = first.get("grounding_metadata")
            if grounding is None:
                return []

            chunks = getattr(grounding, "grounding_chunks", None)
            if chunks is None and isinstance(grounding, dict):
                chunks = grounding.get("grounding_chunks")
            if not chunks:
                return []

            seen = set()
            sources = []
            for idx, chunk in enumerate(chunks, 1):
                web_obj = getattr(chunk, "web", None)
                if web_obj is None and isinstance(chunk, dict):
                    web_obj = chunk.get("web") or chunk

                url = getattr(web_obj, "uri", None)
                title = getattr(web_obj, "title", None)
                if isinstance(web_obj, dict):
                    url = url or web_obj.get("uri") or web_obj.get("url")
                    title = title or web_obj.get("title")

                if not url:
                    continue
                norm_url = str(url).strip()
                if not norm_url or norm_url in seen:
                    continue

                seen.add(norm_url)
                sources.append(
                    {
                        "id": len(sources) + 1,
                        "title": (str(title).strip() if title else "未命名来源"),
                        "url": norm_url,
                        "domain": (
                            norm_url.split("/")[2]
                            if "//" in norm_url and len(norm_url.split("/")) > 2
                            else ""
                        ),
                    }
                )

            return sources
        except Exception as exc:
            logger.debug(f"[WebSearcher] 来源提取失败: {exc}")
            return []

    @classmethod
    def search_with_grounding(cls, query, skill_prompt=None):
        """使用 Gemini Google Search Grounding 进行实时搜索（意图感知版本）

        skill_prompt: 来自本地/AI路由器生成的执行指令。
          - 若提供，直接用作 system_instruction（正确理解用户意图）
          - 若未提供，回退到关键词检测分支（保指安全下线）
        """
        # 1. 优先使用模型生成的 skill_prompt
        if skill_prompt and len(skill_prompt.strip()) > 5:
            system_instruction = (
                "你是 Koto，一个智能助手。请使用搜索结果提供准确、实时的信息。\n"
                f"{skill_prompt}\n"
                "用中文回答，格式整洁清晰。"
            )
            logger.debug(f"[WebSearcher] 使用 skill_prompt: {skill_prompt[:60]}")
        else:
            # 2. 回退：关键词检测 + 分类 system_instruction
            query_type = cls._detect_query_type(query)
            _, system_instruction = cls._build_search_context(query, query_type)
            logger.debug(f"[WebSearcher] 关键词检测备用: {query_type}")
        try:
            # 使用 Google Search 作为工具
            search_client = _client()
            try:
                if "ollama" in type(search_client).__name__.lower():
                    search_client = _create_client()
            except Exception:
                search_client = _client()
            search_config = _types().GenerateContentConfig(
                tools=[_types().Tool(google_search=_types().GoogleSearch())],
                system_instruction=system_instruction,
            )
            try:
                response = search_client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=query,
                    config=search_config,
                )
            except Exception as exc:
                exc_text = str(exc)
                if "model is required" not in exc_text and "Ollama" not in exc_text:
                    raise
                response = _create_client().models.generate_content(
                    model="gemini-2.5-flash",
                    contents=query,
                    config=search_config,
                )

            if response.text:
                return {"success": True, "response": response.text, "grounded": True}
            else:
                return {
                    "success": False,
                    "response": "搜索未返回结果",
                    "grounded": False,
                }
        except Exception as e:
            return {
                "success": False,
                "response": f"搜索失败: {str(e)}",
                "grounded": False,
            }

    @classmethod
    def generate_ppt_images(
        cls, slide_titles: list, topic: str, max_images: int = 3
    ) -> list:
        """为 PPT 幻灯片生成配图（使用 Imagen / Gemini 图像模型）

        从幻灯片标题中挑选最适合配图的 2-3 页，生成高质量配图。
        返回: [{"slide_index": int, "image_path": str}, ...]
        """
        import queue as _queue
        import threading

        if not slide_titles:
            return []

        # 用 AI 挑选最适合配图的幻灯片
        pick_prompt = (
            f"以下是一个关于「{topic}」的PPT的各页标题,请挑选最适合配图的 {min(max_images, len(slide_titles))} 页。\n"
            f"对每页生成一个简洁的英文图像描述（适合AI图像生成）。\n"
            f'只输出 JSON 数组，格式：[{{"index": 0, "prompt": "..."}}]\n\n'
        )
        for i, t in enumerate(slide_titles):
            pick_prompt += f"{i}. {t}\n"

        try:
            resp = _client().models.generate_content(
                model="gemini-2.5-flash",
                contents=pick_prompt,
                config=_types().GenerateContentConfig(
                    temperature=0.3, max_output_tokens=1024
                ),
            )
            import json as _json

            raw = resp.text or ""
            # 提取 JSON 数组
            import re as _re

            m = _re.search(r"\[.*\]", raw, _re.DOTALL)
            if m:
                picks = _json.loads(m.group())
            else:
                picks = []
        except Exception as e:
            logger.debug(f"[PPT-IMAGE] 选图AI失败: {e}")
            # 回退：选前 max_images 个非过渡页
            picks = [
                {"index": i, "prompt": f"professional illustration about {t}"}
                for i, t in enumerate(slide_titles[:max_images])
            ]

        results = []
        images_dir = os.path.join(get_workspace_dir(), "images")
        os.makedirs(images_dir, exist_ok=True)

        for pick in picks[:max_images]:
            idx = pick.get("index", 0)
            prompt = pick.get("prompt", f"professional illustration for presentation")
            # 增强 prompt 质量 — 确保简洁、无文字要求
            full_prompt = (
                f"Create a clean, modern, professional infographic-style illustration for a presentation slide. "
                f"Topic: {prompt}. "
                f"Style: flat design, clean layout, soft gradients, business-appropriate color palette. "
                f"Requirements: NO text, NO words, NO letters, NO numbers in the image. "
                f"Pure visual illustration only."
            )

            result_q = _queue.Queue()

            def _gen_image(p, q):
                # ① 首选: Gemini 3.1 Flash Image
                try:
                    res = _client().models.generate_content(
                        model="gemini-3.1-flash-image-preview",
                        contents=p,
                        config=_types().GenerateContentConfig(
                            response_modalities=["TEXT", "IMAGE"]
                        ),
                    )
                    if res.candidates and res.candidates[0].content.parts:
                        for part in res.candidates[0].content.parts:
                            if (
                                hasattr(part, "inline_data")
                                and part.inline_data
                                and part.inline_data.data
                            ):
                                q.put(("success", part.inline_data.data))
                                return
                except Exception as e0:
                    logger.debug(f"[PPT-IMAGE] Gemini 3.1 Flash Image 失败: {e0}")

                # ② 备选: Imagen 4.0
                try:
                    res = _client().models.generate_images(
                        model="imagen-4.0-generate-001",
                        prompt=p,
                        config=_types().GenerateImagesConfig(number_of_images=1),
                    )
                    if res.generated_images:
                        q.put(("success", res.generated_images[0].image.image_bytes))
                        return
                except Exception as e1:
                    logger.debug(f"[PPT-IMAGE] Imagen 4.0 失败: {e1}")

                # ③ 备选: Imagen 4.0 Fast
                try:
                    res2 = _client().models.generate_images(
                        model="imagen-4.0-fast-generate-001",
                        prompt=p,
                        config=_types().GenerateImagesConfig(number_of_images=1),
                    )
                    if res2.generated_images:
                        q.put(("success", res2.generated_images[0].image.image_bytes))
                        return
                except Exception as e2:
                    logger.debug(f"[PPT-IMAGE] Imagen 4.0 Fast 也失败: {e2}")

                # ④ 最终备选: Imagen 3.0（当前公开稳定版）
                try:
                    res3 = _client().models.generate_images(
                        model="imagen-3.0-generate-001",
                        prompt=p,
                        config=_types().GenerateImagesConfig(number_of_images=1),
                    )
                    if res3.generated_images:
                        q.put(("success", res3.generated_images[0].image.image_bytes))
                        return
                except Exception as e3:
                    logger.debug(f"[PPT-IMAGE] Imagen 3.0 也失败: {e3}")
                q.put(("fail", None))

            thread = threading.Thread(
                target=_gen_image, args=(full_prompt, result_q), daemon=True
            )
            thread.start()
            thread.join(timeout=120)  # Gemini 图像生成可能较慢，给足时间

            try:
                status, data = result_q.get_nowait()
                if status == "success" and data:
                    ts = int(time.time() * 1000) % 1000000
                    fname = f"ppt_slide_{idx}_{ts}.png"
                    fpath = os.path.join(images_dir, fname)
                    with open(fpath, "wb") as f:
                        f.write(data)
                    results.append({"slide_index": idx, "image_path": fpath})
                    logger.info(f"[PPT-IMAGE] ✅ 幻灯片 {idx} 配图生成: {fname}")
            except Exception:
                logger.warning(f"[PPT-IMAGE] ⚠️ 幻灯片 {idx} 配图超时或失败")

        return results

    @classmethod
    def deep_research_for_ppt(cls, user_input: str, search_context: str = "") -> str:
        """对复杂/学术主题进行深度研究，返回详细的研究报告文本

        用于在生成 PPT 大纲之前，先用 Pro 模型做深度分析，
        保证内容专业度和信息量。
        """
        research_prompt = (
            "你是一位顶级行业研究分析师。请对以下主题进行深入、全面的研究分析。\n\n"
            "## 严格要求\n"
            "1. **必须提供具体数据** — 市场规模（金额）、增长率（%）、市占率、出货量等定量信息\n"
            "2. **必须引用来源** — 如 IDC、Gartner、Statista、行业年报等（基于搜索资料中的数据）\n"
            "3. **必须包含真实案例** — 具体公司名称、产品型号、发布时间、销售数据等\n"
            "4. **必须有对比分析** — 不同产品/方案/技术路线之间的优劣对比\n"
            "5. **必须覆盖完整视角** — 历史演进 → 现状格局 → 技术路线 → 竞争分析 → 未来趋势\n"
            "6. **必须结构化** — 用清晰的标题层级和要点编排\n"
            "7. 中文回答，内容必须详实，**空洞的描述是不可接受的**\n\n"
            "## 输出格式\n"
            "为每个板块提供:\n"
            "- 2-3 个核心数据点（带数字和来源）\n"
            "- 2-3 个具体案例/产品\n"
            "- 1-2 个关键趋势判断\n\n"
            f"研究主题：{user_input}\n"
        )
        if search_context:
            research_prompt += f"\n已有的搜索参考资料：\n{search_context[:8000]}\n"

        def _extract_text_from_obj(obj) -> list[str]:
            walker = getattr(_app_attr("_extract_interaction_text_global"), "_walk", None)
            return walker(obj) if callable(walker) else []

        def _extract_interaction_text(interaction_obj) -> str:
            return _app_call("_extract_interaction_text_global", interaction_obj)

        # 深度研究专用：Interactions API（deep-research-pro-preview-*）
        preferred_model = get_model_map().get("RESEARCH", "deep-research-pro-preview-12-2025")
        if preferred_model.startswith("deep-research-pro-preview"):
            try:
                research_client = _app_call("create_research_client")
                _log_ppt = logging.getLogger(__name__)
                _log_ppt.info(
                    "[PPT-RESEARCH] 🚀 提交 deep-research job (model=%s)",
                    preferred_model,
                )
                _ppt_create_kwargs: dict = {
                    "input": research_prompt,
                    "background": True,
                    "stream": False,
                }
                if _app_call("_is_interactions_agent", preferred_model):
                    _ppt_create_kwargs["agent"] = preferred_model
                else:
                    _ppt_create_kwargs["model"] = preferred_model
                interaction = research_client.interactions.create(**_ppt_create_kwargs)
                interaction_id = getattr(interaction, "id", None)
                init_status = str(getattr(interaction, "status", "") or "").lower()
                if init_status in _app_attr("_INTERACTION_FAIL_STATES", frozenset()):
                    raise RuntimeError(f"deep-research job 立即失败: {init_status}")

                final_interaction = _app_call("_poll_interaction",
                    research_client,
                    interaction_id,
                    timeout=600.0,  # PPT 研究最多 10 分钟
                    initial_sleep=3.0,
                    backoff_multiplier=1.5,
                    max_sleep=30.0,
                    label="PPT-RESEARCH",
                )
                text = _extract_interaction_text(final_interaction)
                if text and len(text) > 200:
                    logger.info(
                        f"[PPT-RESEARCH] ✅ 深度研究完成 ({preferred_model}), {len(text)} 字符"
                    )
                    return text
                logger.warning(f"[PPT-RESEARCH] ⚠️ Interactions 返回空结果或过短")
            except Exception as inter_err:
                logger.debug(f"[PPT-RESEARCH] Interactions 失败: {inter_err}")

        logger.debug(f"[PPT-RESEARCH] 🔄 切换到备用模型进行研究...")
        research_models = [
            get_model_map().get("RESEARCH", "deep-research-pro-preview-12-2025"),
            "gemini-2.5-pro",
            "gemini-2.5-flash",
        ]
        # 去重并去空，保持顺序
        research_models = [
            m
            for i, m in enumerate(research_models)
            if m and m not in research_models[:i]
        ]
        for model in research_models:
            try:
                # Interactions-only 模型必须走 Interactions API，不走 generate_content
                if _app_call("_is_interactions_only", model):
                    continue
                # 备用路径必须启用 Google Search Grounding，避免模型在无实时数据的情况下
                # 捏造统计数据、引用来源或市场数字（幻觉风险）
                resp = _client().models.generate_content(
                    model=model,
                    contents=research_prompt,
                    config=_types().GenerateContentConfig(
                        tools=[_types().Tool(google_search=_types().GoogleSearch())],
                        temperature=0.5,
                        max_output_tokens=16384,
                    ),
                )
                if resp.text and len(resp.text) > 200:
                    logger.info(
                        f"[PPT-RESEARCH] ✅ 深度研究完成 ({model}), {len(resp.text)} 字符"
                    )
                    return resp.text
            except Exception as e:
                logger.debug(f"[PPT-RESEARCH] {model} 失败: {e}")
                continue
        return ""


def search_with_grounding(query: str, skill_prompt: str | None = None) -> dict:
    return WebSearcher.search_with_grounding(query, skill_prompt)
