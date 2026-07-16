# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Single-pass conversation extraction for profile, memory, and Graph RAG."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

_PROFILE_FIELDS = (
    "programming_languages",
    "tools",
    "domains",
    "likes",
    "dislikes",
    "communication_style",
)
_REFLECT_TASK_TYPES = {"CHAT", "RESEARCH", "CODER", "FILE_GEN", "AGENT"}
_MIN_MEMORY_CONFIDENCE = 0.45
_MIN_TRIPLE_CONFIDENCE = 0.50

_EXTRACTION_PROMPT = """\
分析以下对话，用一次结构化提取完成用户画像、长期记忆和知识三元组更新。

用户：{user_msg}
Koto：{ai_msg}

只返回 JSON 对象，格式如下：
{{
  "profile_updates": {{
    "programming_languages": [],
    "tools": [],
    "domains": [],
    "likes": [],
    "dislikes": [],
    "communication_style": {{}}
  }},
  "personality_updates": {{
    "cognitive": {{
      "exploratory": 0.0,
      "executor": 0.0,
      "analytical": 0.0,
      "creative": 0.0
    }},
    "expertise": {{"领域": 0.0}},
    "goals": ["用户近期目标"],
    "recent_themes": ["近期关注主题"]
  }},
  "memories": [
    {{
      "content": "可独立理解的1-2句话",
      "category": "user_fact|preference|topic_summary|decision|reminder",
      "confidence": 0.0
    }}
  ],
  "triples": [
    {{
      "subject": "主语",
      "relation": "关系",
      "object": "宾语",
      "confidence": 0.0
    }}
  ]
}}

规则：
1. 只保留能跨会话复用的用户事实、偏好、项目、决策和明确提醒。
2. 画像更新必须是明确信息；不确定的字段留空。
3. personality_updates 只记录可从对话判断的认知倾向、专长、目标和主题。
4. 记忆 confidence 使用 0.0-1.0；无价值内容时返回空列表。
5. 三元组只提取用户、技术工具、系统或具体事件的明确事实。
6. 不要返回 Markdown 或解释文字。
"""


class ConversationMemoryExtractor:
    """Own the complete one-call conversation-memory extraction pipeline."""

    @staticmethod
    def should_extract(
        user_msg: str,
        ai_msg: str = "",
        task_type: str = "CHAT",
    ) -> bool:
        normalized = (user_msg or "").strip().lower()
        if not normalized:
            return False

        if normalized in {
            "你好",
            "hi",
            "hello",
            "嗨",
            "在吗",
            "hey",
            "ok",
            "okay",
            "好的",
            "好",
        }:
            return False

        combined = f"{user_msg or ''}{ai_msg or ''}".strip()
        reflection_candidate = (
            (task_type or "CHAT").upper() in _REFLECT_TASK_TYPES
            and len(combined) >= 30
            and len((ai_msg or "").strip()) >= 20
        )
        durable_signals = (
            "我叫",
            "我的名字",
            "我是",
            "喜欢",
            "不喜欢",
            "prefer",
            "倾向",
            "避免",
            "不要",
            "更好",
            "优先",
            "希望",
            "想要",
            "编程风格",
            "记得",
            "记住",
            "下次",
            "以后",
            "不要再",
        )
        if any(signal in normalized for signal in durable_signals):
            return True
        if len(normalized) < 8:
            return reflection_candidate

        technical_signals = (
            "python",
            "javascript",
            "java",
            "代码",
            "项目",
            "开发",
            "编程",
            "算法",
            "数据",
            "ai",
            "react",
            "vue",
            "flask",
            "django",
            "fastapi",
            "docker",
            "框架",
            "库",
            "工具",
            "数据库",
        )
        if any(signal in normalized for signal in technical_signals):
            return True
        if len(normalized) > 40:
            return True

        return reflection_candidate

    @classmethod
    def extract_and_apply(
        cls,
        memory_manager: Any,
        user_msg: str,
        ai_msg: str,
        history: Optional[list] = None,
        *,
        task_type: str = "CHAT",
        session_name: str = "default",
        llm_fn: Optional[Callable[[str], str]] = None,
    ) -> Dict[str, Any]:
        """Run one LLM extraction and apply every validated output."""
        del history  # Reserved for future multi-turn extraction without changing callers.
        result = {
            "memories": [],
            "profile_updates": {},
            "personality_updates": {},
            "triples": [],
            "saved_count": 0,
            "triple_count": 0,
            "used_fallback": False,
        }

        try:
            raw = cls._call_llm(memory_manager, user_msg, ai_msg, llm_fn)
            payload = cls._parse_payload(raw)
        except Exception as exc:
            logger.warning(
                "[ConversationMemoryExtractor] structured extraction failed: %s",
                exc,
            )
            return cls._apply_keyword_fallback(memory_manager, user_msg, result)

        profile_updates = cls._normalize_profile_updates(payload)
        if profile_updates:
            memory_manager.user_profile.update_from_extraction(profile_updates)
            result["profile_updates"] = profile_updates

        personality_updates = cls._normalize_personality_updates(payload)
        personality_matrix = getattr(memory_manager, "personality_matrix", None)
        if personality_updates and personality_matrix is not None:
            personality_matrix.apply_extraction(personality_updates)
            result["personality_updates"] = personality_updates

        memories = cls._normalize_memories(payload)
        for memory in memories:
            item = memory_manager.add_memory(
                content=memory["content"],
                category=memory["category"],
                source="conversation_extractor",
                metadata={
                    "tags": [
                        f"session:{session_name}",
                        f"task:{task_type}",
                        "single_pass_extraction",
                    ],
                    "confidence": memory["confidence"],
                },
            )
            if item is not None:
                result["memories"].append(memory["content"])
                result["saved_count"] += 1

        triples = cls._normalize_triples(payload)
        result["triples"] = triples
        if triples:
            try:
                from app.core.services.graph_rag_service import GraphRAGService

                result["triple_count"] = GraphRAGService.add_triples_from_llm(
                    triples,
                    source_text=f"{user_msg[:200]} | {ai_msg[:200]}",
                    origin="conversation_extractor",
                )
            except Exception as exc:
                logger.debug(
                    "[ConversationMemoryExtractor] Graph RAG update failed: %s",
                    exc,
                )

        if memories or profile_updates or personality_updates or triples:
            cls._observe_contacts(user_msg, ai_msg)

        return result

    @staticmethod
    def _call_llm(
        memory_manager: Any,
        user_msg: str,
        ai_msg: str,
        llm_fn: Optional[Callable[[str], str]],
    ) -> str:
        prompt = _EXTRACTION_PROMPT.format(
            user_msg=(user_msg or "")[:800],
            ai_msg=(ai_msg or "")[:1200],
        )
        if llm_fn is not None:
            return str(llm_fn(prompt) or "")

        generate_fn = getattr(memory_manager, "_generate_fn", None)
        if generate_fn is None:
            raise RuntimeError("no memory extraction LLM is configured")
        return str(generate_fn(prompt, temperature=0.1, max_tokens=1100) or "")

    @staticmethod
    def _parse_payload(raw: str) -> Dict[str, Any]:
        cleaned = (raw or "").strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", cleaned, re.DOTALL)
            if match is None:
                raise
            payload = json.loads(match.group())
        if not isinstance(payload, dict):
            raise ValueError("memory extraction response must be a JSON object")
        return payload

    @staticmethod
    def _normalize_profile_updates(payload: Dict[str, Any]) -> Dict[str, Any]:
        raw_updates = payload.get("profile_updates")
        if not isinstance(raw_updates, dict):
            raw_updates = payload
        normalized = {}
        for key in _PROFILE_FIELDS:
            value = raw_updates.get(key)
            if key == "communication_style":
                if isinstance(value, dict) and value:
                    normalized[key] = value
                continue
            if isinstance(value, list):
                cleaned = [str(item).strip() for item in value if str(item).strip()]
                if cleaned:
                    normalized[key] = cleaned
        return normalized

    @staticmethod
    def _normalize_memories(payload: Dict[str, Any]) -> list[Dict[str, Any]]:
        raw_memories = payload.get("memories", payload.get("memories_to_save", []))
        if not isinstance(raw_memories, list):
            return []
        normalized = []
        for memory in raw_memories:
            if not isinstance(memory, dict):
                continue
            content = str(memory.get("content", "")).strip()
            try:
                confidence = float(memory.get("confidence", 0.8))
            except (TypeError, ValueError):
                continue
            if len(content) < 6 or confidence < _MIN_MEMORY_CONFIDENCE:
                continue
            category = str(memory.get("category", "user_fact")).strip()
            category = {
                "preference": "user_preference",
                "user_fact": "fact",
            }.get(category, category)
            normalized.append(
                {
                    "content": content,
                    "category": category,
                    "confidence": confidence,
                }
            )
        return normalized

    @staticmethod
    def _normalize_personality_updates(payload: Dict[str, Any]) -> Dict[str, Any]:
        raw = payload.get("personality_updates", {})
        if not isinstance(raw, dict):
            return {}

        normalized: Dict[str, Any] = {}
        cognitive = raw.get("cognitive", {})
        if isinstance(cognitive, dict):
            valid_cognitive = {}
            for key in ("exploratory", "executor", "analytical", "creative"):
                value = cognitive.get(key)
                if isinstance(value, (int, float)):
                    valid_cognitive[key] = max(0.0, min(1.0, float(value)))
            if valid_cognitive:
                normalized["cognitive"] = valid_cognitive

        expertise = raw.get("expertise", {})
        if isinstance(expertise, dict):
            valid_expertise = {}
            for topic, value in expertise.items():
                topic_name = str(topic).strip()
                if topic_name and isinstance(value, (int, float)):
                    valid_expertise[topic_name] = max(
                        0.0, min(1.0, float(value))
                    )
            if valid_expertise:
                normalized["expertise"] = valid_expertise

        for key in ("goals", "recent_themes"):
            values = raw.get(key, [])
            if isinstance(values, list):
                cleaned = [str(value).strip() for value in values if str(value).strip()]
                if cleaned:
                    normalized[key] = cleaned
        return normalized

    @staticmethod
    def _normalize_triples(payload: Dict[str, Any]) -> list[Dict[str, Any]]:
        raw_triples = payload.get("triples", [])
        if not isinstance(raw_triples, list):
            return []
        normalized = []
        for triple in raw_triples:
            if not isinstance(triple, dict):
                continue
            subject = str(triple.get("subject", "")).strip()
            relation = str(triple.get("relation", "")).strip()
            obj = str(triple.get("object", "")).strip()
            try:
                confidence = float(triple.get("confidence", 0.8))
            except (TypeError, ValueError):
                continue
            if not subject or not relation or not obj:
                continue
            if confidence < _MIN_TRIPLE_CONFIDENCE:
                continue
            normalized.append(
                {
                    "subject": subject,
                    "relation": relation,
                    "object": obj,
                    "confidence": confidence,
                }
            )
        return normalized

    @staticmethod
    def _apply_keyword_fallback(
        memory_manager: Any,
        user_msg: str,
        result: Dict[str, Any],
    ) -> Dict[str, Any]:
        normalized = (user_msg or "").lower()
        updates: Dict[str, Any] = {}
        languages = []
        language_keywords = {
            "python": ("python", "py"),
            "javascript": ("javascript", "node"),
            "java": ("java",),
            "c++": ("c++", "cpp"),
            "go": ("golang", "go语言"),
            "rust": ("rust",),
            "typescript": ("typescript",),
        }
        for language, keywords in language_keywords.items():
            if any(keyword in normalized for keyword in keywords):
                languages.append(language)
        if languages:
            updates["programming_languages"] = languages
        if any(signal in normalized for signal in ("喜欢", "prefer", "倾向", "更喜欢")):
            if "简洁" in normalized or "简单" in normalized:
                updates["communication_style"] = {"preferred_detail_level": "brief"}
        if updates:
            memory_manager.user_profile.update_from_extraction(updates)
        result["profile_updates"] = updates
        result["used_fallback"] = True
        return result

    @staticmethod
    def _observe_contacts(user_msg: str, ai_msg: str) -> None:
        try:
            from app.core.memory.contact_manager import get_contact_manager

            get_contact_manager().observe_turn(
                user_msg,
                ai_msg,
                topic=(user_msg or "")[:30].strip(),
            )
        except Exception as exc:
            logger.debug(
                "[ConversationMemoryExtractor] contact observation failed: %s",
                exc,
            )
