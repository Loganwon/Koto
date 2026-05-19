from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

from app.core.workflows.doc_ai_review import DocAIReview


pytestmark = [pytest.mark.unit]


def _decode_sse_payload(chunk: str) -> dict:
    assert chunk.startswith("data: ")
    return json.loads(chunk[len("data: ") :])


def test_doc_ai_review_writes_tracked_changes(monkeypatch, tmp_path: Path):
    output_path = tmp_path / "reviewed.docx"
    copy_calls: list[tuple[str, str]] = []
    tracked_calls: list[tuple[str, list[dict[str, str]]]] = []
    annotations = [
        {
            "原文片段": "需要修改的句子",
            "修改建议": "已经修改后的句子",
            "修改原因": "表达更准确",
        }
    ]

    class FakeTrackChangesEditor:
        def __init__(self, author: str):
            assert author == "Koto AI"

        def apply_tracked_changes(self, file_path: str, items: list[dict[str, str]]):
            tracked_calls.append((file_path, items))
            return {"applied": len(items)}

        def apply_comment_changes(self, file_path: str, items: list[dict[str, str]]):
            raise AssertionError("comment mode should not be used")

    fake_track_changes_module = types.ModuleType("web.track_changes_editor")
    fake_track_changes_module.TrackChangesEditor = FakeTrackChangesEditor
    monkeypatch.setitem(sys.modules, "web.track_changes_editor", fake_track_changes_module)

    monkeypatch.setattr(DocAIReview, "parse_file", staticmethod(lambda _path: "需要修改的句子"))
    monkeypatch.setattr(DocAIReview, "save_output_file", staticmethod(lambda suffix=".docx": output_path))
    monkeypatch.setattr(DocAIReview, "_review_chunk", lambda self, chunk, system, model_mode: annotations)

    import app.core.workflows.doc_ai_review as workflow_module

    monkeypatch.setattr(
        workflow_module.shutil,
        "copy2",
        lambda src, dst: copy_calls.append((src, dst)),
    )

    events = list(
        DocAIReview().run(
            {
                "doc_file": str(tmp_path / "source.docx"),
                "review_focus": "all",
                "model_mode": "local",
            }
        )
    )
    payloads = [_decode_sse_payload(chunk) for chunk in events]

    assert copy_calls == [(str(tmp_path / "source.docx"), str(output_path))]
    assert tracked_calls == [(str(output_path), annotations)]
    assert any(
        payload.get("type") == "step_start" and payload.get("label") == "📝 写入修订…"
        for payload in payloads
    )
    assert any(
        payload.get("type") == "step_done" and payload.get("label") == "📝 已写入 1 条修订"
        for payload in payloads
    )
    assert any(
        payload.get("type") == "output"
        and payload.get("output_type") == "docx_file"
        and payload.get("label") == "审阅结果（1 条修订）"
        for payload in payloads
    )