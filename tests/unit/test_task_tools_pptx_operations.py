from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_pptx_operations_do_not_import_legacy_task_tools_facade() -> None:
    source = (ROOT / "app/core/agent/toolkits/foundation/pptx.py").read_text(
        encoding="utf-8"
    )

    assert "app.core.agent.task_tools import" not in source
    tree = ast.parse(source)
    functions = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert functions == {
        "write_pptx_slides",
        "design_pptx_theme_layout",
        "add_pptx_slides",
    }


def test_legacy_pptx_facade_contains_only_operation_delegation() -> None:
    source = (ROOT / "app/core/agent/task_tools.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    expected_calls = {
        "write_pptx_slides": "_pptx_write_slides",
        "design_pptx_theme_layout": "_pptx_design_theme_layout",
        "add_pptx_slides": "_pptx_add_slides",
    }

    for node in tree.body:
        if not isinstance(node, ast.FunctionDef) or node.name not in expected_calls:
            continue
        returns = [item for item in ast.walk(node) if isinstance(item, ast.Return)]
        assert len(returns) == 1
        assert isinstance(returns[0].value, ast.Call)
        assert isinstance(returns[0].value.func, ast.Name)
        assert returns[0].value.func.id == expected_calls[node.name]


def test_write_pptx_slides_facade_updates_existing_shape(tmp_path) -> None:
    from pptx import Presentation

    from app.core.agent.task_tools import write_pptx_slides

    pptx_path = tmp_path / "deck.pptx"
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[1])
    slide.shapes.title.text = "旧标题"
    title_name = slide.shapes.title.name
    presentation.save(pptx_path)

    payload = json.loads(
        write_pptx_slides(
            str(pptx_path),
            updates=[
                {
                    "slide_index": 0,
                    "shape_name": title_name,
                    "text": "新标题",
                }
            ],
        )
    )

    assert payload["success"] is True
    assert payload["slides_updated"] == 1
    assert Presentation(str(pptx_path)).slides[0].shapes.title.text == "新标题"
