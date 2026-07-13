# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Pure PPT generation contract helpers.

These helpers define the stable shapes used by PPT generation callers while the
concrete renderer still lives behind PPTGenerationService.
"""

from __future__ import annotations

import re
from typing import Any


def normalize_slide(slide: Any) -> dict[str, Any]:
    """Normalize arbitrary slide records to the PPT renderer outline shape."""
    if not isinstance(slide, dict):
        return {"title": str(slide), "type": "detail", "points": []}
    return {
        "title": slide.get("title", slide.get("heading", "幻灯片")),
        "type": slide.get("type", slide.get("slide_type", "detail")),
        "points": slide.get("points", slide.get("content", slide.get("bullets", []))),
    }


def normalize_generation_result(result: Any, output_path: str) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {"success": True, "output_path": str(result or output_path)}
    normalized = dict(result)
    normalized.setdefault("success", True)
    normalized.setdefault("output_path", output_path)
    return normalized


def fallback_outline(topic: str, slide_count: int) -> list[dict[str, Any]]:
    slides: list[dict[str, Any]] = [
        {"title": topic, "type": "highlight", "points": ["副标题", "Koto AI 生成"]},
        {
            "title": "议程",
            "type": "overview",
            "points": ["背景介绍", "核心内容", "总结展望"],
        },
    ]
    section_count = max(1, slide_count - 3)
    for i in range(1, section_count + 1):
        slides.append(
            {
                "title": f"第 {i} 部分",
                "type": "detail",
                "points": [f"要点 {i}.1", f"要点 {i}.2", f"要点 {i}.3"],
            }
        )
    slides.append(
        {"title": "总结", "type": "highlight", "points": ["感谢观看", "欢迎提问"]}
    )
    return slides


def choose_ppt_theme(user_input: str) -> str:
    user_input_lower = user_input.lower()
    if (
        "tech" in user_input_lower
        or "技术" in user_input_lower
        or "科技" in user_input_lower
    ):
        return "tech"
    if (
        "creative" in user_input_lower
        or "创意" in user_input_lower
        or "艺术" in user_input_lower
    ):
        return "creative"
    if (
        "simple" in user_input_lower
        or "minimal" in user_input_lower
        or "极简" in user_input_lower
    ):
        return "minimal"
    return "business"


def parse_ppt_outline_markdown(md_text: str) -> dict[str, Any]:
    lines = md_text.split("\n")
    outline: dict[str, Any] = {"title": "", "slides": []}
    type_map = {
        "过渡页": "divider",
        "过渡": "divider",
        "详细": "detail",
        "重点": "detail",
        "亮点": "highlight",
        "数据": "highlight",
        "概览": "overview",
        "速览": "overview",
        "简要": "overview",
        "对比": "comparison",
        "比较": "comparison",
    }
    current_type = "detail"
    current_slide: dict[str, Any] | None = None
    current_subsection: dict[str, Any] | None = None

    for line in lines:
        line = line.rstrip()
        if line.strip() in ("```", "```markdown"):
            continue
        type_match = re.match(r"^\s*\[(.+?)\]\s*$", line)
        if type_match:
            current_type = type_map.get(type_match.group(1).strip(), "detail")
            continue
        if line.startswith("# ") and not line.startswith("## "):
            outline["title"] = line[2:].strip()
        elif line.startswith("## "):
            if (
                current_subsection
                and current_slide
                and current_slide.get("type") in ("overview", "comparison")
            ):
                current_slide.setdefault("subsections", []).append(current_subsection)
                current_subsection = None
            if current_slide:
                outline["slides"].append(current_slide)
            current_slide = {
                "type": current_type,
                "title": line[3:].strip(),
                "points": [],
                "content": [],
            }
            if current_type == "divider":
                current_slide["description"] = ""
            current_type = "detail"
            current_subsection = None
        elif line.startswith("### ") and current_slide:
            if current_subsection:
                current_slide.setdefault("subsections", []).append(current_subsection)
            current_subsection = {
                "subtitle": line[4:].strip(),
                "label": line[4:].strip(),
                "points": [],
            }
        elif re.match(r"^[\s]*[-•*]\s", line) and current_slide is not None:
            point = re.sub(r"^[\s]*[-•*]\s+", "", line).strip()
            if current_subsection is not None:
                current_subsection["points"].append(point)
            else:
                current_slide["points"].append(point)
                current_slide["content"].append(point)
        elif current_slide and current_slide.get("type") == "divider" and line.strip():
            current_slide["description"] = line.strip()

    if (
        current_subsection
        and current_slide
        and current_slide.get("type") in ("overview", "comparison")
    ):
        current_slide.setdefault("subsections", []).append(current_subsection)
    if current_slide:
        outline["slides"].append(current_slide)
    for slide in outline["slides"]:
        if slide.get("type") == "comparison" and "subsections" in slide:
            subsections = slide["subsections"]
            if len(subsections) >= 2:
                slide["left"] = subsections[0]
                slide["right"] = subsections[1]
    return outline


__all__ = [
    "choose_ppt_theme",
    "fallback_outline",
    "normalize_generation_result",
    "normalize_slide",
    "parse_ppt_outline_markdown",
]
