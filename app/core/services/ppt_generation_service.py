# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Facade for PPT planning and rendering.

The concrete PPT planner/generator still lives in web modules during the
migration. This service gives app/core callers one boundary to depend on while
the rendering implementation is moved in later batches.
"""

from __future__ import annotations

from typing import Any

from app.core.services.ppt_generation_contract import (
    choose_ppt_theme,
    fallback_outline,
    normalize_generation_result,
    normalize_slide,
    parse_ppt_outline_markdown,
)
from app.core.services.ppt_generator import PPTGenerator as _PPTGenerator
from app.core.services.ppt_master import PPTContentPlanner as _PPTContentPlanner


class PPTGenerationService:
    def __init__(
        self,
        planner_cls=None,
        generator_cls=None,
        *,
        ai_client=None,
        model_name: str | None = None,
    ) -> None:
        self._planner_cls = planner_cls
        self._generator_cls = generator_cls
        self._ai_client = ai_client
        self._model_name = model_name
        self._planner = None

    def plan_outline(
        self,
        *,
        topic: str,
        slide_count: int,
        audience: str = "通用受众",
        extra_context: str = "",
    ) -> list[dict[str, Any]]:
        planner_cls = self._planner_cls or _PPTContentPlanner
        planner = planner_cls()
        outline_dict = planner._generate_default_plan(
            user_request=(
                f"主题：{topic}\n"
                f"目标受众：{audience}\n"
                f"幻灯片数量：约 {slide_count} 页\n"
                + (f"背景信息：{extra_context}" if extra_context else "")
            )
        )
        slides_raw = outline_dict.get("slides", outline_dict.get("outline", []))
        return [normalize_slide(slide) for slide in slides_raw]

    async def plan_content_structure(
        self, user_input: str, *, search_results=None
    ) -> dict[str, Any]:
        planner = self._get_planner()
        return await planner.plan_content_structure(
            user_input, search_results=search_results
        )

    async def expand_slide_content(
        self,
        title: str,
        points: list[Any],
        *,
        context: str = "",
    ) -> list[Any]:
        planner = self._get_planner()
        if not hasattr(planner, "expand_slide_content"):
            return points
        return await planner.expand_slide_content(title, points, context=context)

    def generate_from_outline(
        self,
        *,
        title: str,
        outline: list[dict[str, Any]],
        output_path: str,
        theme: str = "business",
        subtitle: str = "",
        author: str = "Koto AI",
        enable_ai_images: bool = False,
        progress_callback=None,
    ) -> str:
        result = self.generate_outline_result(
            title=title,
            outline=outline,
            output_path=output_path,
            theme=theme,
            subtitle=subtitle,
            author=author,
            enable_ai_images=enable_ai_images,
            progress_callback=progress_callback,
        )
        return str(result.get("output_path") or output_path)

    def generate_outline_result(
        self,
        *,
        title: str,
        outline: list[dict[str, Any]],
        output_path: str,
        theme: str = "business",
        subtitle: str = "",
        author: str = "Koto AI",
        enable_ai_images: bool = False,
        progress_callback=None,
    ) -> dict[str, Any]:
        generator_cls = self._generator_cls or _PPTGenerator
        generator = generator_cls(theme=theme)
        result = generator.generate_from_outline(
            title=title,
            outline=outline,
            output_path=output_path,
            subtitle=subtitle,
            author=author,
            enable_ai_images=enable_ai_images,
            progress_callback=progress_callback,
        )
        return normalize_generation_result(result, output_path)

    def render_editor_pptx(
        self,
        *,
        ppt_data: dict[str, Any],
        output_path: str,
        theme: str = "business",
        author: str = "Koto AI",
    ) -> dict[str, Any]:
        return self.generate_outline_result(
            title=ppt_data.get("title", "演示文稿"),
            outline=ppt_data.get("slides", []),
            output_path=output_path,
            theme=theme,
            subtitle=ppt_data.get("subtitle", ""),
            author=author,
        )

    def _get_planner(self):
        if self._planner is None:
            planner_cls = self._planner_cls or _PPTContentPlanner
            kwargs = {}
            if self._ai_client is not None:
                kwargs["ai_client"] = self._ai_client
            if self._model_name:
                kwargs["model_name"] = self._model_name
            self._planner = planner_cls(**kwargs)
        return self._planner
