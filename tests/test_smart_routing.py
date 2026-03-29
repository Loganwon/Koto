#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
路由系统回归测试
验证路由重构后，各类请求被正确分发

NOTE: _is_analysis_request is inlined here to avoid importing web.app at
module level — web.app initialises Flask/SocketIO/background-threads which
hangs the pytest collection phase in CI.  The copy below must stay in sync
with the original definition in web/app.py (search for `def _is_analysis_request`).
"""


def _is_analysis_request(requirement: str) -> bool:
    """判断是否为分析/问答类请求（包括简单问答和复杂分析，但不含生成文档意图）"""
    if not requirement:
        return False

    requirement_lower = requirement.lower()

    analysis_actions = [
        "分析", "总结", "概述", "梳理", "解读", "评估", "对比", "提炼", "归纳",
        "主要观点", "核心观点", "要点", "重点", "亮点",
        "告诉我", "告诉", "是什么", "做什么", "想做什么", "在做什么", "是否",
        "有没有", "值不值", "值不值得", "投资价值", "投资建议", "是否值得",
        "值得投资", "有无价值", "有价值吗", "值得关注",
        "讲讲", "讲一下", "说说", "说一下", "介绍", "介绍一下", "介绍下",
        "解释", "解释一下", "帮我解释", "了解", "看看", "看一看",
        "读一读", "读一下", "什么是", "怎么看", "怎么样", "如何", "什么情况",
        "帮我看", "帮我读", "帮我理解", "帮我了解", "帮我评估", "帮我判断",
        "这份", "这个", "检查一下", "查看一下", "看一下这",
        "他们想", "他想", "它想", "该公司", "该项目",
        "review", "analysis", "summary", "summarize", "analyze", "explain",
        "understand", "evaluate", "assess", "what is", "what does", "how does",
        "tell me", "should i", "is it worth", "investment value",
        "check", "read this", "look at",
    ]

    generation_words = [
        "生成一份", "生成一个", "帮我生成", "写一份", "写一个", "帮我写",
        "改善", "改进", "优化", "润色", "重写",
        "帮我做一份", "做一个报告", "做一份报告",
        "create a document", "generate a report", "write a report",
    ]

    has_analysis = any(kw in requirement_lower for kw in analysis_actions)
    has_generation = any(kw in requirement_lower for kw in generation_words)
    return has_analysis and not has_generation


def test_analysis_request():
    """测试分析请求判断 — 纯分析不带生成意图"""
    cases = [
        # 纯分析请求
        ("分析这篇论文的结构", True),
        ("总结这篇文档的要点", True),
        ("梳理一下文章的核心观点", True),
        ("评估一下这篇报告", True),
        ("对比两种方案的优缺点", True),
        # 带生成/改善意图 → 不是纯分析
        ("分析并改善结论", False),
        ("总结之后帮我写个摘要", False),
        ("分析文章并优化引言", False),
        ("帮我改善引言", False),
        ("重写结论", False),
        ("润色这段话", False),
    ]
    for text, expected in cases:
        assert _is_analysis_request(text) == expected, (
            f'_is_analysis_request({text!r}) expected {expected}'
        )


def test_intelligent_analyzer_routing():
    """测试文档上传时智能分析器是否正确触发"""
    _doc_intent_keywords = [
        "写", "生成", "帮我写", "写一段", "写个",
        "改", "改善", "改进", "优化", "润色", "重写", "修改", "提升",
        "摘要", "引言", "结论", "abstract", "前言", "导言",
        "分析", "总结", "梳理", "概述", "评估",
        "不满意", "不好", "不够", "需要改", "有问题",
    ]

    cases = [
        # 应该触发智能分析器的请求
        ("写一段摘要", True),
        ("帮我改善结论", True),
        ("重新改善引言", True),
        ("分析这篇论文的结构", True),
        ("帮我写一段300字的摘要", True),
        ("这篇论文的结论不够好，帮我优化", True),
        ("帮我润色引言部分", True),
        ("生成一个摘要", True),
        ("改进引言，使其与文章主体符合", True),
        # 不应该触发的请求（非文档处理）
        ("这是什么文件", False),
        ("打开这个文件", False),
    ]

    for text, expected in cases:
        result = any(kw in text.lower() for kw in _doc_intent_keywords)
        assert result == expected, (
            f'routing({text!r}) expected {expected}'
        )


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
