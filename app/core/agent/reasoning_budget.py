# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
Reasoning Budget — 可见推理链与思考预算
=======================================
仿照 Anthropic Claude Extended Thinking / OpenAI o-series 的推理模式。
原创实现，无复制自任何闭源代码。

核心思路（来自公开论文：Chain-of-Thought Prompting, Self-Consistency,
Tree of Thoughts, ReWOO, etc.）：

  1. 在正式回答前，让 LLM 进行结构化"内部思考"
  2. 思考过程存储在 <thinking>...</thinking> 块中
  3. 支持"思考预算"（max_thinking_tokens）→ 避免无限循环
  4. 支持"反射"（reflection）→ 思考后让 LLM 自我质疑一次
  5. 最终答案从思考结果中提炼，而非直接输出

与 Koto 集成：
  - 作为 UnifiedAgent 的可选"推理增强模式"
  - 对复杂问题（代码调试、多步规划、逻辑推理）自动触发
  - 思考链可选择性地流式传给前端展示（类似 Claude 的"show thinking"）

用法
----
    from app.core.agent.reasoning_budget import ReasoningEngine, ComplexityTier

    engine = ReasoningEngine(llm_provider=llm, model_id="gemini-2.5-flash")

    # 简单问答（不触发深度思考）
    result = engine.think_and_answer("今天北京天气怎么样？")
    print(result.answer)

    # 强制深度思考
    result = engine.think_and_answer(
        "设计一个支持百万并发的消息队列架构",
        force_deep=True
    )
    print(result.thinking)  # 可见推理链
    print(result.answer)    # 最终答案

    # 流式输出（支持前端实时展示推理过程）
    for chunk in engine.stream_think("请证明 P≠NP 问题的研究现状"):
        if chunk["type"] == "thinking":
            print(f"[思考中] {chunk['text']}")
        elif chunk["type"] == "answer":
            print(f"[答案] {chunk['text']}")
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Generator, List, Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# 复杂度分级
# ─────────────────────────────────────────────────────────────────────────────


class ComplexityTier(str, Enum):
    TRIVIAL = "trivial"  # 直接回答，无需思考
    MODERATE = "moderate"  # 简短思考
    COMPLEX = "complex"  # 深度思考 + 反射
    EXPERT = "expert"  # 多步推理 + 反射 + 自我批评


# 复杂度判断关键词（原创规则，非机器学习）
_TRIVIAL_PATTERNS = [
    r"^(你好|hello|hi|嗨|再见|谢谢|thanks)",
    r"^(今天|现在|当前).{0,5}(几点|日期|时间)",
    r"^(是|否|对|不对|有|没有)\s*$",
]

_COMPLEX_KEYWORDS = [
    "设计",
    "架构",
    "实现",
    "优化",
    "分析",
    "比较",
    "证明",
    "为什么",
    "如何",
    "推导",
    "调试",
    "重构",
    "评估",
    "预测",
    "design",
    "implement",
    "architecture",
    "optimize",
    "analyze",
    "why",
    "how to",
    "debug",
    "refactor",
    "prove",
]

_EXPERT_KEYWORDS = [
    "百万并发",
    "分布式",
    "一致性",
    "CAP定理",
    "NP",
    "算法复杂度",
    "深度学习训练",
    "量化",
    "微调",
    "安全漏洞",
    "密码学",
    "million concurrent",
    "distributed consensus",
    "complexity proof",
]


# ─────────────────────────────────────────────────────────────────────────────
# 结果数据类
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class ThinkingResult:
    question: str
    thinking: str  # 完整推理链（可能为 "" 表示未触发）
    reflection: str = ""  # 自我反思内容
    answer: str = ""  # 最终答案
    tier: ComplexityTier = ComplexityTier.TRIVIAL
    thinking_tokens_used: int = 0  # 估算使用的思考 token 数
    total_time_ms: int = 0
    model_id: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# Prompt 模板
# ─────────────────────────────────────────────────────────────────────────────

_THINKING_PROMPT = """\
你是一个采用 "先思考、后回答" 模式的 AI 助手。

在回答用户问题之前，你需要进行结构化的内部思考。
请将你的思考过程放在 <thinking> 标签内，最终答案放在 <answer> 标签内。

思考要求：
- 分解问题的核心要素
- 考虑多种解决思路
- 分析各方案的优劣
- 识别潜在的陷阱或错误
- 得出最优方案

最终答案要求：
- 直接、清晰、专业
- 基于上面的思考，不重复思考过程
- 用中文回答（除非用户要求英文）

用户问题：
{question}

{context}

请开始思考和回答：
"""

_REFLECTION_PROMPT = """\
你刚才给出了以下思考和回答：

思考过程：
{thinking}

初步答案：
{initial_answer}

现在请进行**自我反思**：
1. 我的推理有没有逻辑漏洞？
2. 我是否遗漏了重要的边界情况？
3. 我的答案有没有不准确或者可以改进的地方？

如果发现问题，请在 <correction> 标签内给出修正，
如果答案已经正确，在 <correction> 标签内写 "答案正确，无需修正"。

同时给出最终优化后的答案（放在 <final_answer> 标签内）。
"""

_STEP_BACK_PROMPT = """\
在直接回答以下问题之前，先思考更高级别的原则和概念：

问题：{question}

1. 这个问题涉及哪个更广泛的领域或原则？
2. 相关的核心概念是什么？
3. 有哪些类似的问题或经典案例可以参考？

请先回答上述"退一步"的问题，然后再针对原始问题给出答案。
"""


# ─────────────────────────────────────────────────────────────────────────────
# ReasoningEngine
# ─────────────────────────────────────────────────────────────────────────────


class ReasoningEngine:
    """
    为 Koto 提供"扩展推理"能力的引擎。

    根据问题复杂度自动选择推理策略：
      TRIVIAL  → 直接调用 LLM，无思考开销
      MODERATE → 单轮 <thinking> + <answer>
      COMPLEX  → 单轮 <thinking> + <answer> + 反射修正
      EXPERT   → Step-back + 多轮 <thinking> + 反射
    """

    def __init__(
        self,
        llm_provider,
        model_id: str = "gemini-2.5-flash",
        max_thinking_tokens: int = 2000,  # 估算的最大思考 token 预算
        enable_reflection: bool = True,
        auto_tier: bool = True,  # 自动判断复杂度
    ):
        self.llm = llm_provider
        self.model_id = model_id
        self.max_thinking_tokens = max_thinking_tokens
        self.enable_reflection = enable_reflection
        self.auto_tier = auto_tier

    # ── 公开接口 ──────────────────────────────────────────────────────────────

    def think_and_answer(
        self,
        question: str,
        context: str = "",
        force_deep: bool = False,
        history: Optional[List[Dict]] = None,
    ) -> ThinkingResult:
        """同步执行推理，返回完整 ThinkingResult。"""
        start = time.time()
        tier = self._classify(question) if self.auto_tier else ComplexityTier.COMPLEX
        if force_deep and tier in (ComplexityTier.TRIVIAL, ComplexityTier.MODERATE):
            tier = ComplexityTier.COMPLEX

        result = ThinkingResult(
            question=question,
            thinking="",
            tier=tier,
            model_id=self.model_id,
        )

        if tier == ComplexityTier.TRIVIAL:
            result.answer = self._direct_answer(question, context)
        elif tier == ComplexityTier.MODERATE:
            result.thinking, result.answer = self._single_thinking(question, context)
        elif tier == ComplexityTier.COMPLEX:
            result.thinking, result.answer = self._single_thinking(question, context)
            if self.enable_reflection:
                result.reflection, result.answer = self._reflect(
                    result.thinking, result.answer
                )
        else:  # EXPERT
            step_back = self._step_back(question)
            enriched_context = f"背景知识：\n{step_back}\n\n{context}"
            result.thinking, result.answer = self._single_thinking(
                question, enriched_context
            )
            if self.enable_reflection:
                result.reflection, result.answer = self._reflect(
                    result.thinking, result.answer
                )

        result.thinking_tokens_used = len(result.thinking.split()) * 2  # 粗略估算
        result.total_time_ms = int((time.time() - start) * 1000)
        return result

    def stream_think(
        self,
        question: str,
        context: str = "",
    ) -> Generator[Dict[str, str], None, None]:
        """
        流式输出推理过程（供前端实时展示）。

        每个 yield 的格式：
          {"type": "thinking", "text": "..."}   # 推理过程块
          {"type": "reflection", "text": "..."}  # 反思块
          {"type": "answer", "text": "..."}      # 最终答案块
          {"type": "meta", "tier": "...", "ms": int}
        """
        start = time.time()
        tier = self._classify(question)

        yield {"type": "meta", "tier": tier.value, "ms": 0}

        if tier == ComplexityTier.TRIVIAL:
            answer = self._direct_answer(question, context)
            yield {"type": "answer", "text": answer}
        else:
            thinking, answer = self._single_thinking(question, context)

            # 流式输出思考过程（按句子切分）
            for sentence in re.split(r"(?<=[。！？\n])", thinking):
                if sentence.strip():
                    yield {"type": "thinking", "text": sentence}

            if self.enable_reflection and tier in (
                ComplexityTier.COMPLEX,
                ComplexityTier.EXPERT,
            ):
                reflection, answer = self._reflect(thinking, answer)
                if reflection and "无需修正" not in reflection:
                    for sentence in re.split(r"(?<=[。！？\n])", reflection):
                        if sentence.strip():
                            yield {"type": "reflection", "text": sentence}

            yield {"type": "answer", "text": answer}

        ms = int((time.time() - start) * 1000)
        yield {"type": "meta", "tier": tier.value, "ms": ms}

    # ── 复杂度分类 ────────────────────────────────────────────────────────────

    def _classify(self, question: str) -> ComplexityTier:
        q_lower = question.lower()

        # TRIVIAL 检查
        for pattern in _TRIVIAL_PATTERNS:
            if re.search(pattern, question):
                return ComplexityTier.TRIVIAL

        # EXPERT 检查
        if any(kw in q_lower for kw in _EXPERT_KEYWORDS):
            return ComplexityTier.EXPERT

        # COMPLEX 检查
        if any(kw in q_lower for kw in _COMPLEX_KEYWORDS):
            return ComplexityTier.COMPLEX

        # 长问题（>50字）默认 MODERATE
        if len(question) > 50:
            return ComplexityTier.MODERATE

        return ComplexityTier.TRIVIAL

    # ── LLM 调用 ──────────────────────────────────────────────────────────────

    def _llm(self, prompt: str, temperature: float = 0.3) -> str:
        try:
            result = self.llm.generate_text(
                prompt=prompt,
                model_id=self.model_id,
                temperature=temperature,
            )
            if isinstance(result, dict):
                return result.get("text", result.get("content", str(result)))
            return str(result)
        except Exception as e:
            logger.warning(f"[ReasoningEngine] LLM 调用失败: {e}")
            return ""

    def _direct_answer(self, question: str, context: str = "") -> str:
        """直接回答，无思考层。"""
        ctx = f"\n背景：{context}" if context else ""
        return self._llm(f"{question}{ctx}")

    def _single_thinking(self, question: str, context: str = "") -> tuple[str, str]:
        """
        单轮思考 + 回答。
        返回 (thinking_text, answer_text)。
        """
        ctx = f"\n{context}" if context else ""
        prompt = _THINKING_PROMPT.format(question=question, context=ctx)
        raw = self._llm(prompt, temperature=0.4)

        thinking = self._extract_tag(raw, "thinking")
        answer = self._extract_tag(raw, "answer")

        # 如果 LLM 未遵循格式，整体作为答案
        if not answer:
            answer = raw.strip()

        # 检查思考预算
        if len(thinking.split()) * 2 > self.max_thinking_tokens:
            thinking = (
                thinking[: self.max_thinking_tokens * 3]
                + "\n...[推理已截断，达到预算上限]"
            )

        return thinking, answer

    def _reflect(self, thinking: str, initial_answer: str) -> tuple[str, str]:
        """
        自我反思阶段。
        返回 (reflection_text, final_answer)。
        """
        prompt = _REFLECTION_PROMPT.format(
            thinking=thinking[:2000],
            initial_answer=initial_answer[:1000],
        )
        raw = self._llm(prompt, temperature=0.3)
        correction = self._extract_tag(raw, "correction")
        final_answer = self._extract_tag(raw, "final_answer") or initial_answer
        return correction, final_answer

    def _step_back(self, question: str) -> str:
        """退一步思考（Step-back prompting），获取背景知识。"""
        prompt = _STEP_BACK_PROMPT.format(question=question)
        return self._llm(prompt, temperature=0.3)

    @staticmethod
    def _extract_tag(text: str, tag: str) -> str:
        """从 LLM 输出中提取 <tag>...</tag> 内容。"""
        pattern = rf"<{tag}>(.*?)</{tag}>"
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        return match.group(1).strip() if match else ""


# ─────────────────────────────────────────────────────────────────────────────
# UnifiedAgent 集成协议 — 装饰器
# ─────────────────────────────────────────────────────────────────────────────


def with_reasoning(
    llm_provider,
    model_id: str = "gemini-2.5-flash",
    max_tokens: int = 2000,
):
    """
    装饰器：让任意函数在执行前先进入推理模式。

    用法：
        engine = ReasoningEngine(llm, model_id)

        @with_reasoning(llm, model_id)
        def handle_question(question: str) -> str:
            return question  # 这里的 question 会先经过推理引擎增强

    实际上这是一个工厂函数，返回的结果是增强后的最终答案。
    """
    engine = ReasoningEngine(llm_provider, model_id, max_thinking_tokens=max_tokens)

    def decorator(fn):
        def wrapper(question: str, *args, **kwargs):
            result = engine.think_and_answer(question)
            if result.thinking:
                logger.debug(
                    f"[ReasoningBudget] tier={result.tier.value} "
                    f"tokens≈{result.thinking_tokens_used} ms={result.total_time_ms}"
                )
            # 将增强后的答案传给原函数（或直接返回）
            return result.answer

        return wrapper

    return decorator
