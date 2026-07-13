# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
app/core/agent/plugins/ppt_plugin.py
=====================================
PPT 生成 Agent 插件 — 通过 app.core.services.ppt_generation_service 提供
Agent 可调用的规划与生成工具。

注册以下工具：

  generate_ppt_outline(topic, extra_context)
    → 纯 LLM 规划，返回结构化 JSON 大纲（不创建文件，速度快）

  generate_ppt(topic, outline, output_filename, theme)
    → 根据大纲生成 .pptx 文件，返回下载路径

使用方式（factory.py 中已自动注册）：
    registry = _build_registry(full=True)
    # PPTPlugin 已包含在 full 注册列表中
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List

from app.core.agent.base import AgentPlugin
from app.core.services.ppt_generation_service import (
    PPTGenerationService,
    fallback_outline,
    normalize_slide,
)

logger = logging.getLogger(__name__)

# 输出目录
_OUTPUT_DIR = Path(os.environ.get("KOTO_PPT_OUTPUT_DIR", "workspace/ppt_output"))
_DOWNLOAD_PREFIX = "/download/ppt"


def _ensure_output_dir() -> Path:
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return _OUTPUT_DIR


def _to_download_url(file_path: str) -> str:
    return f"{_DOWNLOAD_PREFIX}/{Path(file_path).name}"


class PPTPlugin(AgentPlugin):
    """
    Koto PPT 生成插件。

    提供两个工具：
    1. ``generate_ppt_outline`` — 快速规划，返回可编辑的 JSON 大纲
    2. ``generate_ppt``         — 根据大纲生成 .pptx 文件
    """

    @property
    def name(self) -> str:
        return "PPT"

    @property
    def description(self) -> str:
        return (
            "生成 PowerPoint 演示文稿：支持主题规划、内容大纲生成与完整 .pptx 文件输出"
        )

    def get_tools(self) -> List[Dict[str, Any]]:
        _OUTLINE_SCHEMA = {
            "type": "OBJECT",
            "description": (
                "PPT 大纲参数。\n"
                "示例：\n"
                '{"topic": "量子计算入门", "slide_count": 10, "audience": "工程师", '
                '"extra_context": "重点介绍原理和应用场景"}'
            ),
            "properties": {
                "topic": {
                    "type": "STRING",
                    "description": "PPT 主题（必填），如「2026年公司战略规划」",
                },
                "slide_count": {
                    "type": "INTEGER",
                    "description": "预期幻灯片数量，默认 10",
                },
                "audience": {
                    "type": "STRING",
                    "description": "目标受众描述，如「高管」「工程师」「客户」，默认通用",
                },
                "extra_context": {
                    "type": "STRING",
                    "description": "额外背景信息或要求（可选）",
                },
            },
            "required": ["topic"],
        }

        _GENERATE_SCHEMA = {
            "type": "OBJECT",
            "description": (
                "PPT 生成参数。\n"
                "outline 格式：\n"
                '  [{"title": "幻灯片标题", "type": "detail", "points": ["要点1","要点2"]}]\n'
                "type 取值：detail / overview / highlight / divider / comparison / image_full"
            ),
            "properties": {
                "topic": {
                    "type": "STRING",
                    "description": "PPT 主题标题（必填）",
                },
                "outline": {
                    "type": "ARRAY",
                    "description": (
                        "幻灯片大纲数组，每项含 title / type / points。"
                        "可以直接使用 generate_ppt_outline 的输出结果。"
                    ),
                },
                "output_filename": {
                    "type": "STRING",
                    "description": "输出文件名（不含扩展名），留空则自动生成",
                },
                "theme": {
                    "type": "STRING",
                    "description": "主题风格：business（默认）/ tech / minimal / colorful",
                },
                "author": {
                    "type": "STRING",
                    "description": "作者署名，默认 Koto AI",
                },
            },
            "required": ["topic", "outline"],
        }

        return [
            {
                "name": "generate_ppt_outline",
                "func": self.generate_ppt_outline,
                "description": (
                    "为给定主题快速规划 PPT 结构大纲，返回 JSON 格式的幻灯片列表。\n"
                    "每个幻灯片包含：标题、类型（detail/overview/highlight/divider）、要点列表。\n"
                    "使用场景：①先规划大纲确认结构 ②再调用 generate_ppt 生成文件。\n"
                    "速度快（纯规划，不生成文件），适合让用户审核后再生成。"
                ),
                "parameters": _OUTLINE_SCHEMA,
            },
            {
                "name": "generate_ppt",
                "func": self.generate_ppt,
                "description": (
                    "根据大纲生成完整的 PowerPoint (.pptx) 演示文稿文件。\n"
                    "若未提供 outline，内部会自动调用 generate_ppt_outline 规划大纲再生成。\n"
                    "生成完成后返回文件路径和下载链接。\n"
                    "适用场景：汇报 PPT、演讲稿、培训材料、产品介绍、项目进展。"
                ),
                "parameters": _GENERATE_SCHEMA,
            },
        ]

    # ─────────────────────────────────────────────────────────────────────────
    # 工具实现
    # ─────────────────────────────────────────────────────────────────────────

    def generate_ppt_outline(self, ppt_params: Any) -> str:
        """
        规划 PPT 大纲。

        Args:
            ppt_params: dict 或 JSON 字符串，含 topic / slide_count / audience / extra_context

        Returns:
            JSON 字符串，形如：
            {"outline": [...], "slide_count": 10, "topic": "..."}
        """
        params = self._parse_params(ppt_params)
        topic = params.get("topic", "")
        if not topic:
            return json.dumps({"error": "topic 不能为空"}, ensure_ascii=False)

        slide_count = int(params.get("slide_count", 10))
        audience = params.get("audience", "通用受众")
        extra = params.get("extra_context", "")

        try:
            outline = PPTGenerationService().plan_outline(
                topic=topic,
                slide_count=slide_count,
                audience=audience,
                extra_context=extra,
            )
            return json.dumps(
                {
                    "topic": topic,
                    "slide_count": len(outline),
                    "outline": outline,
                },
                ensure_ascii=False,
                indent=2,
            )
        except Exception as exc:
            logger.error(
                "[PPTPlugin] generate_ppt_outline 失败: %s", exc, exc_info=True
            )
            # 降级：返回固定结构大纲
            outline = fallback_outline(topic, slide_count)
            return json.dumps(
                {"topic": topic, "slide_count": len(outline), "outline": outline},
                ensure_ascii=False,
                indent=2,
            )

    def generate_ppt(self, ppt_params: Any) -> str:
        """
        根据大纲生成 .pptx 文件。

        Args:
            ppt_params: dict 或 JSON 字符串，含 topic / outline / output_filename / theme / author

        Returns:
            JSON 字符串，含 file_path / download_url / slide_count / status
        """
        params = self._parse_params(ppt_params)
        topic = params.get("topic", "")
        if not topic:
            return json.dumps({"error": "topic 不能为空"}, ensure_ascii=False)

        outline = params.get("outline")
        if not outline:
            # 自动规划大纲
            _raw = self.generate_ppt_outline({"topic": topic})
            _plan = json.loads(_raw)
            outline = _plan.get("outline", [])

        outline = [normalize_slide(s) for s in outline]
        theme = params.get("theme", "business")
        author = params.get("author", "Koto AI")
        fname = params.get("output_filename") or f"ppt_{uuid.uuid4().hex[:8]}"
        if not fname.endswith(".pptx"):
            fname += ".pptx"

        output_path = str(_ensure_output_dir() / fname)

        try:
            saved_path = PPTGenerationService().generate_from_outline(
                title=topic,
                outline=outline,
                output_path=output_path,
                theme=theme,
                author=author,
            )
            return json.dumps(
                {
                    "status": "success",
                    "file_path": saved_path,
                    "download_url": _to_download_url(saved_path),
                    "slide_count": len(outline),
                    "message": f"✅ PPT 已生成：{Path(saved_path).name}（共 {len(outline)} 页）",
                },
                ensure_ascii=False,
            )
        except ImportError as exc:
            logger.error("[PPTPlugin] ppt_generator 导入失败: %s", exc)
            return json.dumps(
                {"error": f"PPT 生成模块不可用，请确认 python-pptx 已安装: {exc}"},
                ensure_ascii=False,
            )
        except Exception as exc:
            logger.error("[PPTPlugin] generate_ppt 失败: %s", exc, exc_info=True)
            return json.dumps({"error": str(exc)}, ensure_ascii=False)

    # ─────────────────────────────────────────────────────────────────────────
    # 内部工具
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_params(raw: Any) -> Dict:
        """接受 dict 或 JSON 字符串，返回 dict。"""
        if isinstance(raw, str):
            try:
                return json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f"参数不是合法 JSON: {exc}") from exc
        if isinstance(raw, dict):
            return raw
        raise TypeError(f"参数类型不支持: {type(raw)}")

    @staticmethod
    def _fallback_outline(topic: str, slide_count: int) -> List[Dict]:
        """当规划器不可用时生成通用大纲结构。"""
        return fallback_outline(topic, slide_count)
