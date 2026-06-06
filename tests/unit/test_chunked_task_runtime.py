from __future__ import annotations

import json


def _parse_sse(events):
    parsed = []
    for event in events:
        if isinstance(event, str) and event.startswith("data: "):
            parsed.append(json.loads(event[6:]))
    return parsed


def test_chunked_runtime_emits_phase_plan_progress_and_result(monkeypatch):
    from app.core.agent.chunked_task_runtime import ChunkedTaskRuntime, ChunkUnit

    runtime = ChunkedTaskRuntime(model_id="gemini-2.5-pro")

    monkeypatch.setattr(
        runtime,
        "_build_chunks",
        lambda source_text, options: [
            ChunkUnit("chunk_1", 1, "第 1/2 块", "第一块正文"),
            ChunkUnit("chunk_2", 2, "第 2/2 块", "第二块正文"),
        ],
    )
    monkeypatch.setattr(
        runtime._task_agent, "_get_provider", lambda options=None: object()
    )
    monkeypatch.setattr(
        runtime,
        "_process_chunk",
        lambda provider, task, chunk, previous_summary, file_type, options: {
            "chunk_output": f"{chunk.label}:{chunk.text}",
            "chunk_summary": f"{chunk.label} 摘要",
        },
    )

    events = _parse_sse(
        runtime.execute(
            task="润色当前文件",
            files=[{"path": "demo.docx", "name": "demo.docx", "type": "docx"}],
            options={
                "model_mode": "auto",
                "current_file": "demo.docx",
                "current_file_name": "demo.docx",
                "current_file_text": ("原文段落。\n\n" * 800).strip(),
            },
        )
    )

    event_types = [event.get("type") for event in events]
    assert event_types.count("phase") >= 5
    assert "plan" in event_types
    assert "progress" in event_types
    assert "file_change" in event_types
    assert "result" in event_types
    assert event_types[-1] == "done"


def test_chunked_runtime_should_handle_only_long_transform_docx_tasks():
    from app.core.agent.chunked_task_runtime import ChunkedTaskRuntime

    runtime = ChunkedTaskRuntime(model_id="gemini-2.5-pro")

    assert runtime.should_handle(
        task="润色当前文件",
        files=[{"path": "demo.docx", "name": "demo.docx", "type": "docx"}],
        options={"current_file_text": ("原文。\n\n" * 2000).strip()},
    )
    assert not runtime.should_handle(
        task="总结当前文件",
        files=[{"path": "demo.docx", "name": "demo.docx", "type": "docx"}],
        options={"current_file_text": ("原文。\n\n" * 2000).strip()},
    )
    assert not runtime.should_handle(
        task="润色当前文件",
        files=[{"path": "demo.xlsx", "name": "demo.xlsx", "type": "xlsx"}],
        options={"current_file_text": ("原文。\n\n" * 2000).strip()},
    )
