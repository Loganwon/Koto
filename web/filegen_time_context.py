# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
from __future__ import annotations

import re
from datetime import datetime


def parse_time_info_for_filegen(user_text: str) -> dict:
    """解析 FILE_GEN 输入中的时间信息，重点处理“仅月份未写年份”的场景。"""
    now = datetime.now()
    info = {
        "raw": user_text or "",
        "year": None,
        "month": None,
        "resolved_year": None,
        "resolved_month": None,
        "time_text": now.strftime("%Y年%m月%d日"),
        "rule_hit": False,
    }

    text = user_text or ""
    m = re.search(r"(?:(20\d{2})\s*年)?\s*([1-9]|1[0-2])\s*月", text)
    if not m:
        return info

    year_str = m.group(1)
    month_str = m.group(2)
    month = int(month_str)
    year = int(year_str) if year_str else None

    info["year"] = year
    info["month"] = month
    info["resolved_year"] = year if year is not None else now.year
    info["resolved_month"] = month
    info["rule_hit"] = year is None
    return info


def build_filegen_time_context(user_text: str) -> tuple[str, dict]:
    """构建注入给模型的时间上下文文本。"""
    parsed = parse_time_info_for_filegen(user_text)
    now = datetime.now()
    lines = [
        "[时间上下文]",
        f"- 当前系统时间: {now.strftime('%Y-%m-%d %H:%M:%S')}",
    ]

    if parsed.get("resolved_month"):
        lines.append(
            f"- 用户时间意图解析: {parsed['resolved_year']}年{parsed['resolved_month']}月"
        )
        if parsed.get("rule_hit"):
            lines.append("- 解析规则命中: 用户仅提供月份，已按当前年份解析")
    else:
        lines.append("- 用户时间意图解析: 未检测到明确月份，按当前语境理解")

    return "\n".join(lines), parsed
