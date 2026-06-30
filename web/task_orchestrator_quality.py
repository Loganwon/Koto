# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
from __future__ import annotations

import asyncio
import logging
import re

try:
    from google.genai import types
except Exception:  # pragma: no cover - optional SDK in some test envs
    types = None

from web.task_orchestrator_runtime import client

_app_logger = logging.getLogger("koto.app")


async def validate_quality(
    user_input: str, combined_output: dict, context: dict
) -> int:
    """
    验证输出质量（语义评分版本）。
    先用快速规则给基准分，再用 gemini-2.5-flash-lite 做语义评估。
    返回: 质量评分 (0-100)
    """
    score = 40
    total_steps = len(combined_output.get("steps", []))
    completed_steps = len(
        [
            s
            for s in combined_output.get("steps", [])
            if s.get("status") == "completed"
        ]
    )
    if total_steps > 0:
        score += int((completed_steps / total_steps) * 30)

    final_output = combined_output.get("final_output", "")
    if not final_output:
        return max(0, min(100, score))

    has_files = any(
        r.get("result", {}).get("saved_files")
        for r in combined_output.get("steps", [])
        if isinstance(r.get("result"), dict)
    )
    if has_files:
        score += 10

    try:
        check_prompt = (
            f"用户需求：{user_input[:300]}\n\n"
            f"最终输出（前1500字）：{final_output[:1500]}\n\n"
            "请评估输出是否满足了用户需求。只输出一个 0~30 的整数（30为完全满足）。"
        )
        resp = await asyncio.to_thread(
            lambda: client.models.generate_content(
                model="gemini-2.5-flash-lite",
                contents=check_prompt,
                config=types.GenerateContentConfig(
                    max_output_tokens=8,
                    temperature=0.0,
                ),
            )
        )
        text = (resp.text or "").strip()
        m = re.search(r"\d+", text)
        if m:
            semantic_score = min(30, max(0, int(m.group())))
            score += semantic_score
    except Exception as e:
        _app_logger.debug(f"[VALIDATE_QUALITY] 语义评分失败，使用规则分: {e}")

    return max(0, min(100, score))
