from __future__ import annotations

from app.core.agent.file_task_review_intent import (
    should_route_docx_file_edit,
    should_use_docx_review_system,
)
from app.core.routing.rule_router import RuleRouter
from app.core.routing.routing_rule_chain import RuleChain, RuleContext


class _DummyDispatcher:
    @staticmethod
    def _build_routing_list(scores, boosts=None, reasons=None):
        return []


def _rule_chain() -> RuleChain:
    return RuleChain(_DummyDispatcher)


def test_rule_router_uses_shared_docx_review_intent_behavior():
    cases = [
        "帮我润色这篇文章",
        "校对一下文档内容",
        "这段翻译有翻译腔，帮我改",
        "修改这份文档",
    ]

    for text in cases:
        assert RuleRouter.should_use_annotation_system(
            text,
            has_file=True,
        ) == should_use_docx_review_system(text, has_file=True)
        assert RuleRouter.should_use_annotation_system(text, has_file=True) is True


def test_shared_docx_review_intent_requires_file_context():
    assert should_use_docx_review_system("帮我润色这篇文章", has_file=False) is False
    assert RuleRouter.should_use_annotation_system("帮我润色这篇文章", has_file=False) is False


def test_shared_docx_review_intent_ignores_unrelated_file_requests():
    assert should_use_docx_review_system("帮我写一首诗", has_file=True) is False
    assert RuleRouter.should_use_annotation_system("帮我写一首诗", has_file=True) is False


def test_rule_chain_docx_file_edit_uses_shared_broad_edit_intent():
    chain = _rule_chain()
    ctx = RuleContext(
        user_input="帮我把这份文档改得更通顺",
        user_lower="帮我把这份文档改得更通顺",
        file_context={"has_file": True, "file_type": ".docx"},
        similarity_scores={},
    )

    assert should_route_docx_file_edit(ctx.user_input, has_file=True) is True
    assert chain._check_file_edit(ctx) is True
    task, label, info = chain._build_file_edit(ctx)
    assert task == "DOC_ANNOTATE"
    assert "Doc-Annotate" in label


def test_rule_chain_keeps_workflow_text_file_edit_keywords_separate():
    chain = _rule_chain()
    ctx = RuleContext(
        user_input="修改这个文件",
        user_lower="修改这个文件",
        file_context={"has_file": True, "file_type": ".md"},
        similarity_scores={},
    )

    assert chain._check_file_edit(ctx) is True
    task, label, info = chain._build_file_edit(ctx)
    assert task == "FILE_GEN"
    assert "File-Edit" in label


def test_rule_chain_file_edit_requires_file_context():
    chain = _rule_chain()
    ctx = RuleContext(
        user_input="帮我把这份文档改得更通顺",
        user_lower="帮我把这份文档改得更通顺",
        file_context={"has_file": False, "file_type": ".docx"},
        similarity_scores={},
    )

    assert should_route_docx_file_edit(ctx.user_input, has_file=False) is False
    assert chain._check_file_edit(ctx) is False
