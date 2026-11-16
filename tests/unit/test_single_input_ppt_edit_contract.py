"""The ordinary dispatcher payload must remain usable without hidden edit modes."""

from __future__ import annotations

import pytest
from pptx import Presentation

from app.core.agent.file_task_artifact_transaction import resolved_write_path
from app.core.agent.file_task_contract import FileTaskRequest
from app.core.agent.file_task_runtime import FileTaskRuntime


def _initial_payload(task):
    # Paired with task-document-routing.test.ts's real dispatcher capture.
    return {
        "task": task,
        "session_id": "single-input",
        "target_path": "",
        "files": [],
        "current_file": {
            "path": "deck.pptx",
            "name": "deck.pptx",
            "type": "pptx",
            "target": False,
        },
        "options": {
            "router_policy": "model_primary_intent",
            "workspace_route_intent": {
                "route": "file_task",
                "route_kind": "workflow",
                "task_type": "FILE_TASK",
                "route_source": "active_file_format",
            },
        },
    }


def test_single_input_current_ppt_executes_the_real_design_tool_without_output_mode(
    tmp_path, monkeypatch
):
    from app.core.agent import task_tools_common

    path = tmp_path / "deck.pptx"
    source = tmp_path / "source.txt"
    source.write_bytes(b"protected unrelated source")
    deck = Presentation()
    for title, body in (
        ("Original title", "Original evidence"),
        ("Original plan", "Keep this wording"),
    ):
        slide = deck.slides.add_slide(deck.slide_layouts[1])
        slide.shapes.title.text = title
        slide.placeholders[1].text = body
    deck.save(path)
    before = path.read_bytes()
    monkeypatch.setattr(task_tools_common, "_WORKSPACE_ROOT", str(tmp_path))
    calls = []

    def model(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            assert "design_pptx_theme_layout" in {
                tool["name"] for tool in kwargs["tools"]
            }
            return {
                "tool_calls": [
                    {
                        "id": "design",
                        "name": "design_pptx_theme_layout",
                        "args": {
                            "path": "deck.pptx",
                            "style_brief": "科技感商业 BP",
                            "density": "balanced",
                        },
                    }
                ]
            }
        return {"content": "已完成统一主题与版式设计。"}

    payload = _initial_payload("把这个 PPT 编辑得好看一点，做成专业高级的汇报风格")
    assert "output_mode" not in payload["options"]
    request = FileTaskRequest.from_mapping(payload)
    runtime = FileTaskRuntime(workspace_root=str(tmp_path), model_client=model)
    classification = runtime._classify_request(request, runtime._context_files(request))
    assert classification.output_mode == "hybrid" and classification.write_authorized
    assert not classification.write_required
    events = list(runtime.run(request))
    changed = [event.payload for event in events if event.type == "file.changed"]
    assert any(
        change.get("operation") == "design_pptx_theme_layout" for change in changed
    )
    assert all(
        resolved_write_path(str(change.get("path") or "")) == path.resolve()
        for change in changed
    )
    assert path.read_bytes() != before
    assert source.read_bytes() == b"protected unrelated source"
    rendered = Presentation(path)
    text = "\n".join(
        shape.text
        for slide in rendered.slides
        for shape in slide.shapes
        if hasattr(shape, "text")
    )
    assert all(
        value in text
        for value in (
            "Original title",
            "Original evidence",
            "Original plan",
            "Keep this wording",
        )
    )
    final = events[-1]
    assert final.type == "run.finished"
    assert final.payload["completed_task"] is True


@pytest.mark.parametrize(
    "task",
    [
        "请说明如何修改这个 PPT，不要实际执行",
        "请说明如何保存这个 PPT",
        "看看这个 PPT 的设计有没有问题，先不要改",
        "处理当前内容",
    ],
)
def test_same_initial_context_does_not_authorize_questions_or_target_alone(
    tmp_path, task
):
    request = FileTaskRequest.from_mapping(_initial_payload(task))
    classification = FileTaskRuntime(workspace_root=str(tmp_path))._classify_request(
        request, []
    )
    assert classification.output_mode == "answer"
    assert not classification.write_authorized
