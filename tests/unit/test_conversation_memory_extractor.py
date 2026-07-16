from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from app.core.memory.conversation_memory_extractor import (
    ConversationMemoryExtractor,
)


@pytest.mark.unit
def test_single_pass_applies_profile_memory_triples_and_contacts(monkeypatch):
    from app.core.memory import contact_manager
    from app.core.services.graph_rag_service import GraphRAGService

    calls = []

    def generate(prompt, temperature, max_tokens):
        calls.append((prompt, temperature, max_tokens))
        return json.dumps(
            {
                "profile_updates": {
                    "programming_languages": ["Python"],
                    "communication_style": {"preferred_detail_level": "brief"},
                },
                "personality_updates": {
                    "cognitive": {"analytical": 0.9},
                    "expertise": {"Python": 0.85},
                    "goals": ["优化 Koto 架构"],
                    "recent_themes": ["记忆系统"],
                },
                "memories": [
                    {
                        "content": "用户偏好简洁的 Python 技术回答",
                        "category": "preference",
                        "confidence": 0.92,
                    }
                ],
                "triples": [
                    {
                        "subject": "用户",
                        "relation": "偏好",
                        "object": "简洁的 Python 回答",
                        "confidence": 0.9,
                    }
                ],
            },
            ensure_ascii=False,
        )

    manager = MagicMock()
    manager._generate_fn = generate
    manager.add_memory.return_value = {"id": 1}
    contact = MagicMock()
    monkeypatch.setattr(contact_manager, "get_contact_manager", lambda: contact)
    graph_add = MagicMock(return_value=1)
    monkeypatch.setattr(GraphRAGService, "add_triples_from_llm", graph_add)

    result = ConversationMemoryExtractor.extract_and_apply(
        manager,
        "我喜欢简洁的 Python 回答",
        "好的，以后我会简洁回答。",
        task_type="CHAT",
        session_name="single-pass",
    )

    assert len(calls) == 1
    manager.user_profile.update_from_extraction.assert_called_once_with(
        {
            "programming_languages": ["Python"],
            "communication_style": {"preferred_detail_level": "brief"},
        }
    )
    manager.personality_matrix.apply_extraction.assert_called_once_with(
        {
            "cognitive": {"analytical": 0.9},
            "expertise": {"Python": 0.85},
            "goals": ["优化 Koto 架构"],
            "recent_themes": ["记忆系统"],
        }
    )
    manager.add_memory.assert_called_once()
    memory_call = manager.add_memory.call_args.kwargs
    assert memory_call["source"] == "conversation_extractor"
    assert memory_call["category"] == "user_preference"
    assert memory_call["metadata"]["confidence"] == 0.92
    assert "session:single-pass" in memory_call["metadata"]["tags"]
    graph_add.assert_called_once()
    contact.observe_turn.assert_called_once()
    assert result["saved_count"] == 1
    assert result["triple_count"] == 1
    assert result["personality_updates"]["goals"] == ["优化 Koto 架构"]


@pytest.mark.unit
def test_invalid_llm_response_uses_keyword_profile_fallback():
    manager = MagicMock()
    manager._generate_fn = lambda *args, **kwargs: "not-json"

    result = ConversationMemoryExtractor.extract_and_apply(
        manager,
        "我喜欢简洁的 Python 回答",
        "好的",
    )

    assert result["used_fallback"] is True
    assert result["profile_updates"]["programming_languages"] == ["python"]
    assert result["profile_updates"]["communication_style"] == {
        "preferred_detail_level": "brief"
    }
    manager.user_profile.update_from_extraction.assert_called_once()
    manager.add_memory.assert_not_called()


@pytest.mark.unit
def test_should_extract_preserves_substantive_reflection_coverage():
    assert (
        ConversationMemoryExtractor.should_extract(
            "请帮我分析这个方案的风险",
            "这个方案的主要风险是依赖集中，建议分阶段进行验证。",
            "CHAT",
        )
        is True
    )
    assert ConversationMemoryExtractor.should_extract("你好", "你好", "CHAT") is False
    assert (
        ConversationMemoryExtractor.should_extract(
            "我叫张三",
            "你好张三，我已经记住你的名字，以后会这样称呼你。",
            "CHAT",
        )
        is True
    )
    assert (
        ConversationMemoryExtractor.should_extract(
            "这是一条普通较短的消息",
            "这是一条普通较短的回复",
            "SYSTEM",
        )
        is False
    )


@pytest.mark.unit
def test_personality_matrix_applies_smoothed_single_pass_update(tmp_path):
    from app.core.services.memory_manager import PersonalityMatrix

    matrix_path = tmp_path / "personality.json"
    matrix = PersonalityMatrix(str(matrix_path))

    changed = matrix.apply_extraction(
        {
            "cognitive": {"analytical": 1.0},
            "expertise": {"Python": 0.8},
            "goals": ["完成 Koto 内存架构清理"],
            "recent_themes": ["单一记忆入口"],
        }
    )

    assert changed is True
    assert matrix.data["cognitive"]["analytical"] == 0.575
    assert matrix.data["expertise"]["Python"] == 0.16
    assert matrix.data["goals"] == ["完成 Koto 内存架构清理"]
    assert matrix.data["recent_themes"] == ["单一记忆入口"]
    assert matrix_path.exists()
