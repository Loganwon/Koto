#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Conversation context analysis and history filtering."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


# ================= RAG 上下文分析器 =================
class ContextAnalyzer:
    """
    基于 RAG (检索增强生成) 的智能上下文分析器

    功能：
    1. 分析历史对话，提取关键信息
    2. 构建结构化的上下文提示词
    3. 智能判断任务关联性
    4. 生成增强后的输入
    """

    # 任务类型特征签名
    TASK_SIGNATURES = {
        "PAINTER": {
            "keywords": [
                "图",
                "画",
                "照片",
                "image",
                "photo",
                "picture",
                "图像已生成",
                "图片已生成",
                "猫",
                "狗",
                "人物",
                "风景",
                "头像",
            ],
            "outputs": ["图像已生成", "图片已生成", "已保存图片", "✨ 图片已生成"],
            "entities": [
                "颜色",
                "风格",
                "大小",
                "背景",
                "表情",
                "姿势",
                "眼睛",
                "毛发",
                "脸",
            ],
        },
        "FILE_GEN": {
            "keywords": [
                "pdf",
                "word",
                "excel",
                "docx",
                "文档",
                "报告",
                "文件",
                "简历",
                "合同",
                "标注",
                "批注",
                "润色",
                "改写",
                "校对",
                "审校",
                "修订",
                "优化",
                "纠错",
            ],
            "outputs": [
                "已生成文件",
                "文件已保存",
                ".pdf",
                ".docx",
                ".xlsx",
                "✅ **文件生成成功",
            ],
            "entities": [
                "标题",
                "章节",
                "内容",
                "格式",
                "模板",
                "标注",
                "批注",
                "修改建议",
            ],
        },
        "RESEARCH": {
            "keywords": ["研究", "分析", "介绍", "了解", "原理", "技术", "深入"],
            "outputs": ["##", "###", "1.", "2.", "总结", "结论"],
            "entities": ["定义", "特点", "优势", "劣势", "应用", "发展"],
        },
        "CODER": {
            "keywords": [
                "代码",
                "编程",
                "函数",
                "脚本",
                "code",
                "script",
                "python",
                "javascript",
            ],
            "outputs": ["```python", "```javascript", "```", "def ", "class "],
            "entities": ["函数", "变量", "类", "模块", "算法"],
        },
        "CHAT": {
            "keywords": ["你好", "谢谢", "帮我", "请问", "什么是"],
            "outputs": [],
            "entities": [],
        },
    }

    # 延续性指示词分类 - 需要更严格的匹配
    CONTINUATION_PATTERNS = {
        "modify": {
            # 修改类：必须是短句或明确的修改指令
            "indicators": [
                "再来一张",
                "再来一个",
                "更大一点",
                "更小一点",
                "大一点",
                "小一点",
                "深一些",
                "浅一些",
                "颜色换成",
                "背景换成",
            ],
            "weight": 0.9,
            "max_input_length": 30,  # 限制输入长度，长句子不太可能是简单修改
            "prompt_template": "用户要求修改之前的结果：{modification}",
        },
        "reference": {
            # 引用类：必须在句首或独立使用
            "indicators": [
                "这个怎么",
                "这张图",
                "那个文件",
                "上面的",
                "刚才的",
                "把它",
                "把这个",
                "基于这个",
            ],
            "weight": 0.85,
            "require_start": True,  # 需要在句首出现
            "prompt_template": "用户引用了之前的内容：{reference}",
        },
        "reference_loose": {
            # 引用类（宽松）：用于计划/大纲/方案等需要跟随之前内容的请求
            "indicators": [
                "这个计划",
                "该计划",
                "上述计划",
                "上面的计划",
                "这个方案",
                "该方案",
                "上述方案",
                "这个大纲",
                "该大纲",
                "这个ppt",
                "该ppt",
                "这个PPT",
                "该PPT",
                "按照这个",
                "根据这个",
            ],
            "weight": 0.78,
            "require_start": False,
            "prompt_template": "用户引用了之前的计划或大纲：{reference}",
        },
        "convert": {
            # 转换类：明确的格式转换请求
            "indicators": [
                "做成word",
                "做成pdf",
                "做成excel",
                "转成word",
                "转成pdf",
                "变成文档",
                "导出为",
                "保存为word",
                "保存为pdf",
            ],
            "weight": 0.95,
            "prompt_template": "用户要求将之前的内容转换为新格式：{conversion}",
        },
        "continue": {
            # 继续类：明确要求继续之前的内容
            "indicators": [
                "继续写",
                "接着说",
                "接着写",
                "然后呢",
                "下一步",
                "还有呢",
                "另外补充",
                "再找找",
                "再搜",
                "再查",
                "再看看",
                "继续查",
                "继续找",
                "再找",
                "再搜一下",
            ],
            "weight": 0.7,
            "max_input_length": 20,  # 短句才是继续指令
            "prompt_template": "用户要求继续之前的任务：{continuation}",
        },
        "detail": {
            # 详细类：只有非常明确的展开请求才算，且必须是短句
            "indicators": [
                "详细说说",
                "展开说说",
                "详细讲讲",
                "具体说一下",
                "解释一下刚才的",
            ],
            "weight": 0.75,
            "max_input_length": 25,  # 限制长度
            "prompt_template": "用户要求详细说明之前提到的内容：{detail}",
        },
    }

    @classmethod
    def extract_entities(cls, text: str, task_type: str = None) -> list:
        """从文本中提取关键实体"""
        entities = []
        text_lower = text.lower()

        # 通用实体提取
        # 颜色
        colors = [
            "红色",
            "蓝色",
            "绿色",
            "黄色",
            "白色",
            "黑色",
            "灰色",
            "粉色",
            "紫色",
            "橙色",
            "棕色",
        ]
        for color in colors:
            if color in text_lower:
                entities.append({"type": "color", "value": color})

        # 风格
        styles = [
            "可爱",
            "帅气",
            "写实",
            "卡通",
            "动漫",
            "赛博朋克",
            "水彩",
            "油画",
            "简约",
            "复古",
        ]
        for style in styles:
            if style in text_lower:
                entities.append({"type": "style", "value": style})

        # 主题/对象
        subjects = [
            "猫",
            "狗",
            "人",
            "风景",
            "建筑",
            "汽车",
            "花",
            "树",
            "山",
            "海",
            "城市",
        ]
        for subject in subjects:
            if subject in text_lower:
                entities.append({"type": "subject", "value": subject})

        # 特定任务的实体
        if task_type and task_type in cls.TASK_SIGNATURES:
            for entity_keyword in cls.TASK_SIGNATURES[task_type].get("entities", []):
                if entity_keyword in text_lower:
                    entities.append({"type": "task_specific", "value": entity_keyword})

        return entities

    @classmethod
    def build_context_summary(cls, history: list, max_turns: int = 3) -> dict:
        """
        构建历史上下文摘要

        返回:
        {
            "task_history": [],      # 任务历史
            "key_entities": [],      # 关键实体
            "last_user_intent": "",  # 最近的用户意图
            "last_model_output": "", # 最近的模型输出
            "conversation_topic": "" # 对话主题
        }
        """
        summary = {
            "task_history": [],
            "key_entities": [],
            "last_user_intent": "",
            "last_model_output": "",
            "conversation_topic": "",
        }

        if not history:
            return summary

        # 分析最近的对话
        recent_turns = (
            history[-max_turns * 2 :] if len(history) > max_turns * 2 else history
        )

        all_entities = []
        topics = []

        for turn in recent_turns:
            content = turn["parts"][0] if turn["parts"] else ""
            role = turn["role"]

            if role == "user":
                summary["last_user_intent"] = content
                # 识别任务类型
                for task_type, signatures in cls.TASK_SIGNATURES.items():
                    if any(kw in content.lower() for kw in signatures["keywords"]):
                        summary["task_history"].append(
                            {"type": task_type, "content": content[:100]}
                        )
                        topics.append(task_type)
                        break

                # 提取实体
                entities = cls.extract_entities(content)
                all_entities.extend(entities)

            elif role == "model":
                summary["last_model_output"] = content

        # 去重实体
        seen = set()
        unique_entities = []
        for e in all_entities:
            key = f"{e['type']}:{e['value']}"
            if key not in seen:
                seen.add(key)
                unique_entities.append(e)
        summary["key_entities"] = unique_entities

        # 确定对话主题
        if topics:
            summary["conversation_topic"] = topics[-1]  # 最近的任务类型

        return summary

    @classmethod
    def build_rag_prompt(
        cls, user_input: str, context_summary: dict, continuation_type: str = None
    ) -> str:
        """
        构建 RAG 风格的增强提示词

        将上下文信息结构化地注入到用户输入中
        """
        prompt_parts = []

        # 1. 添加上下文标记
        if context_summary.get("conversation_topic"):
            prompt_parts.append(
                f"[上下文类型: {context_summary['conversation_topic']}]"
            )

        # 2. 添加关键实体信息
        if context_summary.get("key_entities"):
            entities_str = ", ".join(
                [
                    f"{e['type']}={e['value']}"
                    for e in context_summary["key_entities"][:5]
                ]
            )
            prompt_parts.append(f"[关键信息: {entities_str}]")

        # 3. 添加历史意图
        if context_summary.get("last_user_intent"):
            # 截取核心描述
            last_intent = context_summary["last_user_intent"]
            if len(last_intent) > 200:
                last_intent = last_intent[:200] + "..."
            prompt_parts.append(f"[之前的请求: {last_intent}]")

        # 4. 根据延续类型添加特定指令
        if continuation_type and continuation_type in cls.CONTINUATION_PATTERNS:
            pattern = cls.CONTINUATION_PATTERNS[continuation_type]
            # 不添加模板，让实体和上下文自然融合

        # 5. 添加用户当前输入
        prompt_parts.append(f"[当前请求: {user_input}]")

        # 6. 如果是转换请求，添加源内容
        if continuation_type == "convert" and context_summary.get("last_model_output"):
            output = context_summary["last_model_output"]
            # 限制长度
            if len(output) > 4000:
                output = output[:4000] + "\n...(内容已截断)"
            prompt_parts.append(f"\n[需要转换的源内容:]\n{output}")

        # 7. 如果是引用类延续，附上最近输出摘要
        if continuation_type in (
            "reference",
            "reference_loose",
        ) and context_summary.get("last_model_output"):
            output = context_summary["last_model_output"]
            if len(output) > 2000:
                output = output[:2000] + "\n...(内容已截断)"
            prompt_parts.append(f"\n[最近输出摘要:]\n{output}")

        # 组合成最终的增强提示
        enhanced_prompt = "\n".join(prompt_parts)

        return enhanced_prompt

    @classmethod
    def analyze_context(cls, user_input: str, history: list) -> dict:
        """
        RAG 风格的上下文分析

        返回:
        {
            "is_continuation": bool,      # 是否是延续任务
            "related_task": str,          # 关联的任务类型
            "continuation_type": str,     # 延续类型 (modify/reference/convert/continue/detail)
            "context_summary": dict,      # 结构化上下文摘要
            "enhanced_input": str,        # RAG 增强后的输入
            "confidence": float,          # 置信度
        }
        """
        result = {
            "is_continuation": False,
            "related_task": None,
            "continuation_type": None,
            "context_summary": {},
            "enhanced_input": user_input,
            "confidence": 0.0,
        }

        if not history or len(history) < 2:
            return result

        user_lower = user_input.lower()
        input_length = len(user_input)

        # 1. 构建上下文摘要
        context_summary = cls.build_context_summary(history)
        result["context_summary"] = context_summary

        # 2. 检测延续类型和置信度（更严格的匹配）
        detected_type = None
        max_weight = 0.0

        for pattern_type, pattern_info in cls.CONTINUATION_PATTERNS.items():
            indicators = pattern_info["indicators"]
            weight = pattern_info["weight"]

            # 检查输入长度限制（如果有）
            max_len = pattern_info.get("max_input_length")
            if max_len and input_length > max_len:
                continue  # 输入太长，不太可能是简单的延续指令

            # 检查是否需要在句首出现
            require_start = pattern_info.get("require_start", False)

            # 计算匹配的指示词数量
            matches = 0
            for ind in indicators:
                if ind in user_lower:
                    if require_start:
                        # 需要在句首（前10个字符内）
                        if user_lower.find(ind) < 10:
                            matches += 1
                    else:
                        matches += 1

            if matches > 0:
                # 加权计算置信度
                adjusted_weight = weight * (
                    1 + 0.1 * (matches - 1)
                )  # 多个匹配增加置信度
                if adjusted_weight > max_weight:
                    max_weight = adjusted_weight
                    detected_type = pattern_type

        # 3. 额外检查：如果用户输入包含明确的新主题，降低延续判断
        # 新主题标志：包含"关于"、"一个"后接新实体
        new_topic_indicators = [
            "关于",
            "一篇",
            "一份",
            "一个新的",
            "帮我写",
            "帮我做",
            "帮我生成",
            "给我生成",
            "生成一",
        ]
        has_new_topic = any(ind in user_lower for ind in new_topic_indicators)

        # 检查是否是完全不同的任务类型（如：打开微信 -> 生成图片）
        task_mismatch = False
        if context_summary.get("conversation_topic"):
            prev_topic = context_summary["conversation_topic"]
            # 检测当前输入的任务类型
            curr_likely_task = None
            if any(
                kw in user_lower
                for kw in ["查", "搜", "搜索", "查询", "找", "再找", "再查", "再搜"]
            ):
                curr_likely_task = "WEB_SEARCH"
            elif any(kw in user_lower for kw in ["图", "画", "照片", "image"]):
                curr_likely_task = "PAINTER"
            elif any(kw in user_lower for kw in ["word", "pdf", "文档", "报告"]):
                curr_likely_task = "FILE_GEN"
            elif any(kw in user_lower for kw in ["打开", "运行", "关闭"]):
                curr_likely_task = "SYSTEM"

            # 如果任务类型完全不同，不应该是延续
            if curr_likely_task and prev_topic and curr_likely_task != prev_topic:
                task_mismatch = True
                logger.debug(
                    f"[ContextAnalyzer] 任务类型不匹配: {prev_topic} -> {curr_likely_task}"
                )

        if has_new_topic and input_length > 10:
            # 有新主题且输入较长，很可能是独立任务
            max_weight *= 0.2  # 大幅降低置信度
            logger.debug(f"[ContextAnalyzer] 检测到新主题标志，降低延续置信度")

        if task_mismatch:
            # 任务类型不匹配，强制清零
            max_weight = 0
            detected_type = None
            logger.debug(f"[ContextAnalyzer] 任务类型不匹配，清除延续判断")

        # 4. 如果检测到延续模式且置信度足够高
        if detected_type and max_weight > 0.5:
            result["is_continuation"] = True
            result["continuation_type"] = detected_type
            result["confidence"] = min(max_weight, 1.0)

            # 确定关联的任务类型
            if context_summary.get("conversation_topic"):
                result["related_task"] = context_summary["conversation_topic"]
            elif context_summary.get("task_history"):
                result["related_task"] = context_summary["task_history"][-1]["type"]

            # 4. 构建 RAG 增强提示
            result["enhanced_input"] = cls.build_rag_prompt(
                user_input, context_summary, detected_type
            )

            logger.debug(f"[ContextAnalyzer] RAG Analysis:")
            logger.info(f"  - Continuation Type: {detected_type}")
            logger.info(f"  - Related Task: {result['related_task']}")
            logger.info(f"  - Confidence: {result['confidence']:.2f}")
            logger.info(
                f"  - Entities: {[e['value'] for e in context_summary.get('key_entities', [])]}"
            )

        # 5. 特殊处理：转换请求（即使没有明确的延续指示词）
        convert_patterns = [
            "做成word",
            "做成pdf",
            "转成word",
            "转成pdf",
            "生成word",
            "生成pdf",
            "导出为",
        ]
        if any(p in user_lower for p in convert_patterns) and context_summary.get(
            "last_model_output"
        ):
            result["is_continuation"] = True
            result["continuation_type"] = "convert"
            result["related_task"] = "FILE_GEN"
            result["confidence"] = 0.95
            result["enhanced_input"] = cls.build_rag_prompt(
                user_input, context_summary, "convert"
            )

        return result

    @classmethod
    def filter_history(
        cls, user_input: str, history: list, keep_turns: int = 6
    ) -> list:
        """过滤历史记录，尽量避免无关上下文污染"""
        if not history:
            return []

        # 如果历史很短，直接返回
        if len(history) <= keep_turns * 2:
            return history

        user_lower = user_input.lower()

        # 抽取用户输入中的实体与关键词
        entities = cls.extract_entities(user_input)
        entity_values = {e["value"] for e in entities}

        # 额外提取中文关键词（长度>=2）与英文单词（长度>=3）
        import re

        cjk_words = re.findall(r"[\u4e00-\u9fff]{2,}", user_input)
        eng_words = re.findall(r"[a-zA-Z]{3,}", user_input)
        keyword_set = {k.lower() for k in (cjk_words + eng_words)}
        keyword_set.update({v.lower() for v in entity_values})

        # 构建相关历史：包含关键词的对话
        relevant = []
        for turn in history:
            content = (turn.get("parts") or [""])[0]
            content_lower = content.lower()
            if any(k in content_lower for k in keyword_set if k):
                relevant.append(turn)

        # 始终保留最近 3 轮对话（确保上下文连贯）
        tail_count = 6
        tail_start_index = max(0, len(history) - tail_count)

        # 收集需要保留的索引
        indices_to_keep = set()

        # 1. 关键词匹配的历史
        for i, turn in enumerate(history):
            content = (turn.get("parts") or [""])[0]
            content_lower = content.lower()
            if any(k in content_lower for k in keyword_set if k):
                indices_to_keep.add(i)
                # 同时保留该条的前一条（如果是User/Model配对）
                if i > 0:
                    indices_to_keep.add(i - 1)

        # 2. 也是最重要的：保留尾部上下文
        for i in range(tail_start_index, len(history)):
            indices_to_keep.add(i)

        # 按原始顺序重组
        filtered_history = [history[i] for i in sorted(indices_to_keep)]

        return filtered_history
