# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
RuleRouter — deterministic keyword/pattern based routing rules.

All pure-logic helpers that do NOT depend on ML models, external I/O, or
mutable class state live here.  SmartDispatcher delegates to these methods.
"""
from __future__ import annotations

import re

from app.core.routing.routing_config import (
    TRIVIAL_EXCLUDE,
    TRIVIAL_GREETINGS,
    TRIVIAL_IDENTITY,
)


class RuleRouter:
    """Stateless rule-based routing helpers."""

    # ── trivial-input constants ───────────────────────────────────────────────
    _TRIVIAL_GREETINGS = TRIVIAL_GREETINGS
    _TRIVIAL_IDENTITY = TRIVIAL_IDENTITY
    _TRIVIAL_EXCLUDE = TRIVIAL_EXCLUDE

    _CAPABILITY_PREFIXES = (
        "你会",
        "你能",
        "能不能",
        "你可以",
        "能否",
        "可以吗",
        "你支持",
        "支持吗",
    )
    _HOWTO_PREFIXES = ("怎么", "如何", "怎样", "怎么样", "什么是", "怎么用")
    _QUESTION_ENDINGS = ("吗", "么", "?", "？", "嘛", "不")
    _ACTION_TOOL_KWS = (
        "ppt",
        "幻灯片",
        "演示文稿",
        "word",
        "docx",
        "pdf",
        "excel",
        "文档",
        "文件",
        "图片",
        "图表",
        "折线图",
        "柱状图",
        "画图",
        "绘图",
        "代码",
        "程序",
        "音频",
        "润色",
        "改写",
        "批注",
        "标注",
    )

    # ─────────────────────────────────────────────────────────────────────────
    # Trivial-input detection
    # ─────────────────────────────────────────────────────────────────────────
    @classmethod
    def is_trivial(cls, user_input: str) -> bool:
        """
        Return True if the input is trivially simple and can be routed to
        CHAT without any AI classifier.

        Conditions:
          1. Known greeting / acknowledgement word, OR
          2. Short identity question (≤20 chars), OR
          3. Length ≤15 chars and no complex-task keyword.
        """
        text = user_input.strip()
        tl = text.lower()

        if tl in cls._TRIVIAL_GREETINGS:
            return True

        if len(text) <= 20 and any(kw in tl for kw in cls._TRIVIAL_IDENTITY):
            return True

        if len(text) <= 15 and not any(k in tl for k in cls._TRIVIAL_EXCLUDE):
            return True

        return False

    # ─────────────────────────────────────────────────────────────────────────
    # Built-in quick replies for trivial inputs
    # ─────────────────────────────────────────────────────────────────────────
    @classmethod
    def get_trivial_reply(cls, user_input: str) -> str:
        """
        Return a built-in quick response for a trivial input.

        Match order: exact greeting > thanks > farewell > acknowledgement >
        generic fallback.
        """
        tl = user_input.strip().lower()
        if tl in {"你好", "你好呀", "你好啊", "hi", "hello", "哈喽", "嗨", "hey"}:
            return "你好！😊 有什么我可以帮您？"
        if tl in {"早上好", "早安"}:
            return "早上好！☀️ 今天有什么需要帮忙？"
        if tl in {"中午好"}:
            return "中午好！🌤️ 需要帮忙吗？"
        if tl in {"下午好"}:
            return "下午好！有什么我可以帮您的？"
        if tl in {"晚上好"}:
            return "晚上好！🌙 今晚有什么需要帮忙？"
        if tl in {"晚安"}:
            return "晚安！🌙"
        if tl in {"谢谢", "谢谢你", "谢了", "感谢", "多谢", "thanks", "thank you"}:
            return "不客气！😊 有需要随时叫我。"
        if tl in {"再见", "拜拜", "bye", "goodbye", "下次见"}:
            return "再见！👋 有需要随时回来找我。"
        if tl in {"好的", "好", "明白了", "知道了", "收到", "ok", "okay"}:
            return "好的，有需要随时说。"
        if tl in {"嗯", "嗯嗯"}:
            return "嗯，有什么我可以帮到您？"
        return "有什么需要帮忙的？😊"

    @classmethod
    def is_capability_or_howto_query(cls, user_input: str) -> bool:
        """Return True when the user asks about capability/how-to, not execution."""
        text_lower = str(user_input or "").strip().lower()
        if not text_lower:
            return False
        if any(text_lower.startswith(prefix) for prefix in cls._CAPABILITY_PREFIXES) and any(
            text_lower.endswith(suffix) for suffix in cls._QUESTION_ENDINGS
        ):
            return True
        return any(text_lower.startswith(prefix) for prefix in cls._HOWTO_PREFIXES) and any(
            keyword in text_lower for keyword in cls._ACTION_TOOL_KWS
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Quick-task hint (keyword heuristic, no ML)
    # ─────────────────────────────────────────────────────────────────────────
    @classmethod
    def quick_task_hint(cls, user_input: str) -> str:
        """Return a fast keyword-based task-type hint (no ML involved)."""
        text_lower = user_input.lower()
        if cls.is_capability_or_howto_query(user_input):
            return "CHAT"
        # Data charts / visualisation — must be checked before the generic "图" check
        # to avoid routing bar/line charts to PAINTER.
        if any(
            k in text_lower
            for k in [
                "图表",
                "折线图",
                "柱状图",
                "饼图",
                "散点图",
                "直方图",
                "作图",
                "可视化",
                "统计图",
                "数据图",
                "chart",
                "plot",
                "matplotlib",
                "seaborn",
                "plotly",
                "echarts",
            ]
        ):
            return "CODER"
        # AI image generation (generic "图" placed after chart check)
        if any(
            k in text_lower
            for k in ["画", "图片", "照片", "生成图", "绘制", "绘图", "ai画", "图"]
        ):
            return "PAINTER"
        if any(
            k in text_lower for k in ["代码", "编程", "python", "javascript", "函数"]
        ):
            return "CODER"
        if any(k in text_lower for k in ["查", "搜索", "价格", "天气", "新闻"]):
            return "WEB_SEARCH"
        # Reminder / message → AGENT
        if any(
            k in text_lower
            for k in ["提醒我", "提醒一下", "设闹钟", "设提醒", "发微信"]
        ):
            return "AGENT"
        # When input contains [FILE_ATTACHED:ext] prefix, prefer annotation over
        # new-file generation to avoid mis-routing "docx" → FILE_GEN.
        if "[file_attached:" in text_lower:
            _file_edit_hints = [
                "修改",
                "更改",
                "标注",
                "批注",
                "润色",
                "改写",
                "校对",
                "审校",
                "修订",
                "纠错",
                "改善",
                "优化",
                "调整",
                "精炼",
                "通畅",
                "整体修改",
                "通顺",
                "流畅",
                "精简",
                "凝练",
                "简洁",
                "整理",
                "梳理",
                "提炼",
                "修一下",
                "帮我改",
                "改一改",
                "改得",
                "写得",
                "改写",
                "polish",
                "refine",
                "revise",
            ]
            if any(k in text_lower for k in _file_edit_hints):
                return "DOC_ANNOTATE"
        if any(
            k in text_lower
            for k in [
                "word",
                "pdf",
                "docx",
                "表格",
                "文档",
                "报告",
                "生成",
                "做成",
                "标注",
                "批注",
                "润色",
                "改写",
                "校对",
                "审校",
                "修订",
                "纠错",
            ]
        ):
            return "FILE_GEN"
        if any(k in text_lower for k in ["研究", "分析", "深入", "介绍"]):
            return "RESEARCH"
        # MEETING_EXTRACT check
        meeting_verbs = {"提炼", "提取", "整理", "总结", "记录", "归纳", "纪要"}
        meeting_nouns = {"会议", "纪要", "转录", "会议记录"}
        meeting_q_guard = {"什么是", "是什么", "怎么写", "如何做"}
        _has_mv = any(v in text_lower for v in meeting_verbs)
        _has_mn = any(v in text_lower for v in meeting_nouns)
        _has_qg = any(v in text_lower for v in meeting_q_guard)
        if _has_mv and _has_mn and not _has_qg:
            return "MEETING_EXTRACT"
        return "CHAT"

    # ─────────────────────────────────────────────────────────────────────────
    # Safety overwrite — correct obvious misclassifications from ML models
    # ─────────────────────────────────────────────────────────────────────────
    @classmethod
    def apply_safety(
        cls,
        task_type: str,
        user_input: str,
        user_lower: str,
        file_context,
        LocalExecutor,
        WebSearcher,
    ) -> str:
        """
        Apply strong rule-based safety overrides on top of model output to
        prevent misclassification at edge cases.
        """
        if (
            task_type == "CHAT"
            and WebSearcher
            and WebSearcher.needs_web_search(user_input)
        ):
            return "WEB_SEARCH"
        if (
            task_type not in ("SYSTEM", "AGENT")
            and LocalExecutor
            and LocalExecutor.is_system_command(user_input)
        ):
            return "SYSTEM"
        _agent_pat = [
            r"发微信",
            r"回微信",
            r"微信发",
            r"微信回",
            r"给.{1,6}发消息",
            r"给.{1,6}发微信",
            r"浏览器打开",
            r"点击.{1,6}按键",
        ]
        if any(re.search(p, user_input) for p in _agent_pat):
            return "AGENT"
        if task_type == "DOC_ANNOTATE" and not (
            file_context and file_context.get("has_file")
        ):
            return "CHAT"
        return task_type

    # ─────────────────────────────────────────────────────────────────────────
    # Annotation-system check
    # ─────────────────────────────────────────────────────────────────────────
    @staticmethod
    def should_use_annotation_system(user_input: str, has_file: bool = False) -> bool:
        """Return True if the annotation workflow should be engaged."""
        keywords = [
            "标注",
            "批注",
            "润色",
            "改写",
            "校对",
            "审校",
            "修订",
            "纠错",
            "改善",
            "优化",
            "修改",
        ]
        quality_words = ["不合适", "生硬", "翻译腔", "语序", "用词", "逻辑", "问题"]
        target_words = ["翻译", "文章", "文档", "内容", "文本", "段落", "句子", "字词"]

        if not has_file:
            return False

        has_kw = any(k in user_input for k in keywords)
        has_qw = any(q in user_input for q in quality_words)
        has_target = any(t in user_input for t in target_words)

        return has_kw or (has_qw and has_target)
