from __future__ import annotations

import asyncio

from app.core.services.ppt_generation_service import (
    PPTGenerationService,
    choose_ppt_theme,
    fallback_outline,
    normalize_generation_result,
    normalize_slide,
    parse_ppt_outline_markdown,
)


class FakePlanner:
    def __init__(self, ai_client=None, model_name=None):
        self.ai_client = ai_client
        self.model_name = model_name

    def _generate_default_plan(self, user_request: str):
        assert "主题：Roadmap" in user_request
        assert "目标受众：工程师" in user_request
        return {
            "slides": [
                {"heading": "Intro", "slide_type": "overview", "content": ["A"]},
                "Raw Slide",
            ]
        }

    async def plan_content_structure(self, user_input: str, *, search_results=None):
        assert user_input == "make deck"
        assert search_results is None
        return {"outline": [], "theme_recommendation": "tech"}

    async def expand_slide_content(self, title, points, *, context=""):
        assert title == "Intro"
        assert context == "Context"
        return [*points, "expanded"]


class FakeGenerator:
    def __init__(self, theme: str):
        self.theme = theme

    def generate_from_outline(self, **kwargs):
        assert self.theme == "tech"
        assert kwargs["title"] == "Roadmap"
        assert kwargs["subtitle"] == "Q3"
        assert kwargs["author"] == "Koto"
        assert kwargs["enable_ai_images"] is False
        return {"output_path": kwargs["output_path"] + ".saved", "slide_count": 2}


def test_ppt_generation_service_plans_outline_with_injected_planner():
    service = PPTGenerationService(planner_cls=FakePlanner)

    outline = service.plan_outline(
        topic="Roadmap",
        slide_count=3,
        audience="工程师",
        extra_context="focus",
    )

    assert outline == [
        {"title": "Intro", "type": "overview", "points": ["A"]},
        {"title": "Raw Slide", "type": "detail", "points": []},
    ]


def test_ppt_generation_service_delegates_async_planning_methods():
    service = PPTGenerationService(
        planner_cls=FakePlanner,
        ai_client=object(),
        model_name="model-x",
    )

    async def _run():
        plan = await service.plan_content_structure("make deck", search_results=None)
        expanded = await service.expand_slide_content("Intro", ["A"], context="Context")
        return plan, expanded

    plan, expanded = asyncio.run(_run())

    assert plan == {"outline": [], "theme_recommendation": "tech"}
    assert expanded == ["A", "expanded"]


def test_ppt_generation_service_generates_with_injected_generator():
    service = PPTGenerationService(generator_cls=FakeGenerator)

    saved = service.generate_from_outline(
        title="Roadmap",
        outline=[{"title": "Intro", "type": "detail", "points": []}],
        output_path="/tmp/deck.pptx",
        theme="tech",
        subtitle="Q3",
        author="Koto",
        enable_ai_images=False,
    )

    assert saved == "/tmp/deck.pptx.saved"


def test_ppt_generation_service_normalizes_generator_result():
    service = PPTGenerationService(generator_cls=FakeGenerator)

    result = service.generate_outline_result(
        title="Roadmap",
        outline=[{"title": "Intro", "type": "detail", "points": []}],
        output_path="/tmp/deck.pptx",
        theme="tech",
        subtitle="Q3",
        author="Koto",
    )

    assert result["success"] is True
    assert result["output_path"] == "/tmp/deck.pptx.saved"
    assert result["slide_count"] == 2


def test_normalize_generation_result_accepts_non_dict_renderer_return():
    assert normalize_generation_result(None, "/tmp/deck.pptx") == {
        "success": True,
        "output_path": "/tmp/deck.pptx",
    }
    assert normalize_generation_result("/tmp/other.pptx", "/tmp/deck.pptx") == {
        "success": True,
        "output_path": "/tmp/other.pptx",
    }


def test_ppt_generation_service_renders_editor_pptx_payload():
    service = PPTGenerationService(generator_cls=FakeGenerator)

    result = service.render_editor_pptx(
        ppt_data={
            "title": "Roadmap",
            "subtitle": "Q3",
            "slides": [{"title": "Intro", "type": "detail", "points": []}],
        },
        output_path="/tmp/deck.pptx",
        theme="tech",
        author="Koto",
    )

    assert result["success"] is True
    assert result["output_path"] == "/tmp/deck.pptx.saved"


def test_normalize_slide_accepts_legacy_shapes():
    assert normalize_slide({"heading": "H", "slide_type": "detail", "bullets": ["x"]}) == {
        "title": "H",
        "type": "detail",
        "points": ["x"],
    }


def test_fallback_outline_has_requested_shape():
    outline = fallback_outline("Topic", 5)

    assert outline[0]["title"] == "Topic"
    assert outline[-1]["title"] == "总结"
    assert len(outline) == 5


def test_parse_ppt_outline_markdown_preserves_legacy_labeled_shapes():
    outline = parse_ppt_outline_markdown(
        "# 产品路线图\n\n"
        "[对比]\n"
        "## 方案选择\n"
        "### 方案A\n"
        "- 快速上线\n"
        "### 方案B\n"
        "- 长期稳定\n\n"
        "[过渡页]\n"
        "## 下一阶段\n"
        "进入执行计划"
    )

    assert outline["title"] == "产品路线图"
    assert outline["slides"][0]["type"] == "comparison"
    assert outline["slides"][0]["left"]["points"] == ["快速上线"]
    assert outline["slides"][0]["right"]["points"] == ["长期稳定"]
    assert outline["slides"][1]["type"] == "divider"
    assert outline["slides"][1]["description"] == "进入执行计划"


def test_choose_ppt_theme_matches_legacy_keywords():
    assert choose_ppt_theme("技术路线汇报") == "tech"
    assert choose_ppt_theme("creative brand deck") == "creative"
    assert choose_ppt_theme("极简周报") == "minimal"
    assert choose_ppt_theme("季度经营汇报") == "business"
