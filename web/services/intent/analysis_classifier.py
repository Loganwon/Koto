# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary


def is_analysis_request(requirement: str) -> bool:
    if not requirement:
        return False

    requirement_lower = requirement.lower()

    analysis_actions = [
        "分析", "总结", "概述", "梳理", "解读", "评估", "对比", "提炼", "归纳",
        "主要观点", "核心观点", "要点", "重点", "亮点",
        "告诉我", "告诉", "是什么", "做什么", "想做什么", "在做什么",
        "是否", "有没有", "值不值", "值不值得", "投资价值", "投资建议",
        "帮我分析", "帮我总结", "帮我整理", "帮我解读", "帮我看看",
        "怎么看", "如何评价", "怎么评价", "评价一下", "介绍", "描述",
        "包括", "包含", "有哪些", "有什么", "是谁", "谁",
        "什么时候", "哪里", "什么是", "什么意思", "是什么意思",
        "怎么", "为什么", "为何", "原因", "区别", "区别是什么",
        "不同", "差异", "比较", "相比", "相对于",
        "建议", "推荐", "方案", "解决方案",
        "好不好", "行不行", "可不可以", "能不用", "能不能",
        "好处", "优点", "缺点", "劣势", "优势", "风险", "挑战",
        "机会", "威胁", "前景", "趋势", "发展", "方向", "规划",
        "note", "notes", "笔记", "记录",
        "summary", "summarize", "brief", "overview", "review",
    ]

    gen_keywords = [
        "生成", "创建", "制作", "编写", "写一个", "写一份", "新建",
        "帮我做", "帮我生成", "帮我写", "帮我创建", "帮我制作",
        "做一个", "做一份", "弄一个", "搞一个", "来一个", "来一份",
        "设计一个", "设计一份",
    ]

    for kw in gen_keywords:
        if kw in requirement_lower:
            return False

    for action in analysis_actions:
        if action in requirement_lower:
            return True

    return False
